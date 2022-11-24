# -*- coding: utf-8 -*-
"""Utility functions for Serial Communication."""
from __future__ import annotations

import copy
import datetime
import math
import struct
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from typing import Union
from uuid import UUID
from zlib import crc32

from immutabledict import immutabledict
import numpy as np
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import BOOTUP_COUNTER_UUID
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import INITIAL_MAGNET_FINDING_PARAMS_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
from pulse3D.constants import PCB_SERIAL_NUMBER_UUID
from pulse3D.constants import TAMPER_FLAG_UUID
from pulse3D.constants import TOTAL_WORKING_HOURS_UUID

from ..constants import GENERIC_24_WELL_DEFINITION
from ..constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from ..constants import SERIAL_COMM_MAGIC_WORD_BYTES
from ..constants import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from ..constants import SERIAL_COMM_OKAY_CODE
from ..constants import SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
from ..constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from ..constants import SERIAL_COMM_TIMESTAMP_EPOCH
from ..constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from ..constants import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from ..constants import STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS
from ..constants import STIM_MODULE_ID_TO_WELL_IDX
from ..constants import STIM_NO_PROTOCOL_ASSIGNED
from ..constants import STIM_OPEN_CIRCUIT_THRESHOLD_OHMS
from ..constants import STIM_SHORT_CIRCUIT_THRESHOLD_OHMS
from ..constants import STIM_WELL_IDX_TO_MODULE_ID
from ..constants import StimulatorCircuitStatuses


# Tanner (3/18/21): If/When additional cython is needed to improve serial communication, this file may be worth investigating


METADATA_TYPES: immutabledict[UUID, str] = immutabledict(
    {
        MAIN_FIRMWARE_VERSION_UUID: str,
        CHANNEL_FIRMWARE_VERSION_UUID: str,
        MANTARRAY_NICKNAME_UUID: str,
        MANTARRAY_SERIAL_NUMBER_UUID: str,
        TOTAL_WORKING_HOURS_UUID: int,
        TAMPER_FLAG_UUID: int,
        BOOTUP_COUNTER_UUID: int,
        PCB_SERIAL_NUMBER_UUID: str,
        BOOT_FLAGS_UUID: int,
    }
)

SUBPROTOCOL_BIPHASIC_ONLY_COMPONENTS = frozenset(
    ["interphase_interval", "phase_two_duration", "phase_two_charge"]
)
SUBPROTOCOL_DUR_COMPONENTS = frozenset(
    ["phase_one_duration", "interphase_interval", "phase_two_duration", "postphase_interval"]
)


def _get_checksum_bytes(packet: bytes) -> bytes:
    return crc32(packet).to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")


def create_data_packet(
    timestamp: int,
    packet_type: int,
    packet_payload: bytes = bytes(0),
) -> bytes:
    """Create a data packet to send to the PC."""
    packet_base = convert_to_timestamp_bytes(timestamp) + bytes([packet_type])
    packet_remainder_size = len(packet_base) + len(packet_payload) + SERIAL_COMM_CHECKSUM_LENGTH_BYTES

    data_packet = SERIAL_COMM_MAGIC_WORD_BYTES
    data_packet += packet_remainder_size.to_bytes(
        SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES, byteorder="little"
    )
    data_packet += packet_base
    data_packet += packet_payload
    data_packet += _get_checksum_bytes(data_packet)
    return data_packet


def validate_checksum(comm_from_pc: bytes) -> bool:
    expected_checksum = crc32(comm_from_pc[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES])
    actual_checksum = int.from_bytes(
        comm_from_pc[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:],
        byteorder="little",
    )
    return actual_checksum == expected_checksum


def parse_metadata_bytes(metadata_bytes: bytes) -> Dict[Any, Any]:
    """Parse bytes containing metadata and return as Dict."""
    return {
        BOOT_FLAGS_UUID: metadata_bytes[0],
        MANTARRAY_NICKNAME_UUID: metadata_bytes[1:14].decode("utf-8"),
        MANTARRAY_SERIAL_NUMBER_UUID: metadata_bytes[14:26].decode("ascii"),
        MAIN_FIRMWARE_VERSION_UUID: convert_semver_bytes_to_str(metadata_bytes[26:29]),
        CHANNEL_FIRMWARE_VERSION_UUID: convert_semver_bytes_to_str(metadata_bytes[29:32]),
        "status_codes_prior_to_reboot": convert_status_code_bytes_to_dict(metadata_bytes[32:58]),
        INITIAL_MAGNET_FINDING_PARAMS_UUID: {
            "X": int.from_bytes(metadata_bytes[58:59], byteorder="little", signed=True),
            "Y": int.from_bytes(metadata_bytes[59:60], byteorder="little", signed=True),
            "Z": int.from_bytes(metadata_bytes[60:61], byteorder="little", signed=True),
            "REMN": int.from_bytes(metadata_bytes[61:63], byteorder="little", signed=True),
        },
    }


def convert_metadata_to_bytes(metadata_dict: Dict[UUID, Any]) -> bytes:
    num_wells = 24
    metadata_bytes = (
        bytes([metadata_dict[BOOT_FLAGS_UUID]])
        + bytes(metadata_dict[MANTARRAY_NICKNAME_UUID], encoding="utf-8")
        + bytes(metadata_dict[MANTARRAY_SERIAL_NUMBER_UUID], encoding="ascii")
        + convert_semver_str_to_bytes(metadata_dict[MAIN_FIRMWARE_VERSION_UUID])
        + convert_semver_str_to_bytes(metadata_dict[CHANNEL_FIRMWARE_VERSION_UUID])
        # this function is only used in the simulator, so always send default status code
        + bytes([SERIAL_COMM_OKAY_CODE] * (num_wells + 2))
        + metadata_dict[INITIAL_MAGNET_FINDING_PARAMS_UUID]["X"].to_bytes(1, byteorder="little", signed=True)
        + metadata_dict[INITIAL_MAGNET_FINDING_PARAMS_UUID]["Y"].to_bytes(1, byteorder="little", signed=True)
        + metadata_dict[INITIAL_MAGNET_FINDING_PARAMS_UUID]["Z"].to_bytes(1, byteorder="little", signed=True)
        + metadata_dict[INITIAL_MAGNET_FINDING_PARAMS_UUID]["REMN"].to_bytes(
            2, byteorder="little", signed=True
        )
    )
    # append empty bytes so the result length is always a multiple of 32
    metadata_bytes += bytes(math.ceil(len(metadata_bytes) / 32) * 32 - len(metadata_bytes))
    return metadata_bytes  # type: ignore


def convert_semver_bytes_to_str(semver_bytes: bytes) -> str:
    return f"{semver_bytes[0]}.{semver_bytes[1]}.{semver_bytes[2]}"


def convert_semver_str_to_bytes(semver_str: str) -> bytes:
    return bytes([int(num) for num in semver_str.split(".")])


def convert_status_code_bytes_to_dict(status_code_bytes: bytes) -> Dict[str, int]:
    if len(status_code_bytes) != SERIAL_COMM_STATUS_CODE_LENGTH_BYTES:
        raise ValueError(
            f"Status code bytes must have len of {SERIAL_COMM_STATUS_CODE_LENGTH_BYTES}, {len(status_code_bytes)} bytes given: {str(status_code_bytes)}"
        )
    status_code_labels = (
        "main_status",
        "index_of_thread_with_error",
        *[f"module_{i}_status" for i in range(1, 25)],
    )
    return {label: status_code_bytes[i] for i, label in enumerate(status_code_labels)}


def convert_to_timestamp_bytes(timestamp: int) -> bytes:
    return timestamp.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little")


def get_serial_comm_timestamp() -> int:
    # Tanner (4/7/21): This method should not be used in the simulator. It has its own way of determining the timestamp to send in order to behave more accurately like the real Mantarray instrument
    return (
        datetime.datetime.now(tz=datetime.timezone.utc) - SERIAL_COMM_TIMESTAMP_EPOCH
    ) // datetime.timedelta(microseconds=1)


def convert_stimulator_check_bytes_to_dict(stimulator_check_bytes: bytes) -> Dict[str, List[int]]:
    stimulator_checks_as_ints = struct.unpack("<" + "HHB" * 24, stimulator_check_bytes)
    # convert to lists of adc8, adc9, and status where the index of each list is the module id. Only creating an array here to reshape easily
    stimulator_checks_list = (
        np.array(stimulator_checks_as_ints, copy=False)
        .reshape((3, len(stimulator_checks_as_ints) // 3), order="F")
        .tolist()
    )
    stimulator_checks_dict = {
        key: stimulator_checks_list[i] for i, key in enumerate(["adc8", "adc9", "status"])
    }
    return stimulator_checks_dict


def convert_adc_readings_to_circuit_status(adc8: int, adc9: int) -> int:
    impedance = convert_adc_readings_to_impedance(adc8, adc9)
    # Tanner (5/12/22): this section NOT based on the FW's actual calculation
    if impedance < 0:
        return StimulatorCircuitStatuses.ERROR
    if impedance <= STIM_SHORT_CIRCUIT_THRESHOLD_OHMS:
        return StimulatorCircuitStatuses.SHORT
    if impedance >= STIM_OPEN_CIRCUIT_THRESHOLD_OHMS:
        return StimulatorCircuitStatuses.OPEN
    return StimulatorCircuitStatuses.MEDIA


def convert_adc_readings_to_impedance(adc8: int, adc9: int) -> float:
    # Tanner (5/12/22): this calculation is the FW's actual calculation  # TODO consider making all these numbers constants
    adc8_volts = (adc8 / 4096.0) * 3.3
    adc9_volts = (adc9 / 4096.0) * 3.3
    well_plus = 5.7 * (adc8_volts - 1.65053)
    well_minus = 2 * adc9_volts - 3.3
    current = well_minus / 33
    voltage = well_plus - well_minus
    impedance = voltage / current
    return impedance


def is_null_subprotocol(subprotocol_dict: Dict[str, Union[int, str]]) -> bool:
    return subprotocol_dict["type"] == "delay"


def convert_subprotocol_dict_to_bytes(
    subprotocol_dict: Dict[str, Union[int, str]], is_voltage: bool = False
) -> bytes:
    conversion_factor = 1 if is_voltage else 10
    is_null = is_null_subprotocol(subprotocol_dict)

    # for mypy
    subprotocol_components: Dict[str, int] = {k: v for k, v in subprotocol_dict.items() if isinstance(v, int)}

    if is_null:
        subprotocol_bytes = bytes(24) + subprotocol_components["duration"].to_bytes(4, byteorder="little")
    else:
        subprotocol_bytes = subprotocol_components["phase_one_duration"].to_bytes(4, byteorder="little") + (
            subprotocol_components["phase_one_charge"] // conversion_factor
        ).to_bytes(2, byteorder="little", signed=True)
        duration = subprotocol_components["phase_one_duration"]

        if subprotocol_dict["type"] == "monophasic":
            subprotocol_bytes += bytes(12)
        else:
            subprotocol_bytes += (
                subprotocol_components["interphase_interval"].to_bytes(4, byteorder="little")
                + bytes(2)  # interphase_interval amplitude (always 0)
                + subprotocol_components["phase_two_duration"].to_bytes(4, byteorder="little")
                + (subprotocol_components["phase_two_charge"] // conversion_factor).to_bytes(
                    2, byteorder="little", signed=True
                )
            )
            duration += (
                subprotocol_components["interphase_interval"] + subprotocol_components["phase_two_duration"]
            )

        subprotocol_bytes += subprotocol_components["postphase_interval"].to_bytes(
            4, byteorder="little"
        ) + bytes(
            2  # postphase_interval amplitude (always 0)
        )
        duration += subprotocol_components["postphase_interval"]
        duration *= subprotocol_components["num_cycles"]
        duration //= int(1e3)  # convert from µs from ms
        subprotocol_bytes += duration.to_bytes(4, byteorder="little")

    subprotocol_bytes += bytes([is_null])
    return subprotocol_bytes


def convert_bytes_to_subprotocol_dict(
    subprotocol_bytes: bytes, is_voltage: bool = False
) -> Dict[str, Union[int, str]]:
    duration_ms = int.from_bytes(subprotocol_bytes[24:28], byteorder="little")

    if subprotocol_bytes[-1]:
        # the final byte is a flag indicating whether or not this subprotocol is a delay
        return {"type": "delay", "duration": duration_ms}

    conversion_factor = 1 if is_voltage else 10
    subprotocol_dict: Dict[str, Union[int, str]] = {
        "type": "biphasic",  # assume biphasic to start
        "phase_one_duration": int.from_bytes(subprotocol_bytes[:4], byteorder="little"),
        "phase_one_charge": int.from_bytes(subprotocol_bytes[4:6], byteorder="little", signed=True)
        * conversion_factor,
        "interphase_interval": int.from_bytes(subprotocol_bytes[6:10], byteorder="little"),
        "phase_two_duration": int.from_bytes(subprotocol_bytes[12:16], byteorder="little"),
        "phase_two_charge": int.from_bytes(subprotocol_bytes[16:18], byteorder="little", signed=True)
        * conversion_factor,
        "postphase_interval": int.from_bytes(subprotocol_bytes[18:22], byteorder="little"),
    }

    if not any(subprotocol_dict[k] for k in SUBPROTOCOL_BIPHASIC_ONLY_COMPONENTS):
        subprotocol_dict["type"] = "monophasic"
        for k in SUBPROTOCOL_BIPHASIC_ONLY_COMPONENTS:
            subprotocol_dict.pop(k)

    subprotocol_dict["num_cycles"] = math.ceil(
        duration_ms * 1e3 / get_subprotocol_cycle_duration(subprotocol_dict)
    )

    return subprotocol_dict


def get_subprotocol_cycle_duration(subprotocol: Dict[str, Union[str, int]]) -> int:
    dur_components = set(SUBPROTOCOL_DUR_COMPONENTS)
    if subprotocol["type"] == "monophasic":
        dur_components -= SUBPROTOCOL_BIPHASIC_ONLY_COMPONENTS
    return sum(subprotocol[comp] for comp in dur_components)  # type: ignore


def get_subprotocol_duration(subprotocol: Dict[str, Union[str, int]]) -> int:
    duration = (
        subprotocol["duration"]
        if subprotocol["type"] == "delay"
        else get_subprotocol_cycle_duration(subprotocol) * subprotocol["num_cycles"]
    )
    return duration  # type: ignore


def convert_well_name_to_module_id(well_name: str, use_stim_mapping: bool = False) -> int:
    mapping = STIM_WELL_IDX_TO_MODULE_ID if use_stim_mapping else SERIAL_COMM_WELL_IDX_TO_MODULE_ID
    module_id: int = mapping[GENERIC_24_WELL_DEFINITION.get_well_index_from_well_name(well_name)]
    return module_id


def convert_stim_dict_to_bytes(stim_dict: Dict[str, Any]) -> bytes:
    """Convert a stimulation info dictionary to bytes.

    Assumes the stimulation dictionary given does not have any issues.
    """
    # add bytes for protocol definitions
    stim_bytes = bytes([len(stim_dict["protocols"])])  # number of unique protocols
    protocol_ids = list()
    for protocol_dict in stim_dict["protocols"]:
        is_voltage_controlled = protocol_dict["stimulation_type"] == "V"
        protocol_ids.append(protocol_dict["protocol_id"])
        stim_bytes += bytes([len(protocol_dict["subprotocols"])])  # num subprotocols
        for subprotocol_dict in protocol_dict["subprotocols"]:
            stim_bytes += convert_subprotocol_dict_to_bytes(
                subprotocol_dict, is_voltage=is_voltage_controlled
            )
        stim_bytes += bytes(
            # control method, schedule mode, data type (always 0 as of 9/29/21)
            [is_voltage_controlled, protocol_dict["run_until_stopped"], 0]
        )
    # add bytes for module ID / protocol ID pairs
    protocol_assignment_list = [-1] * 24
    for well_name, protocol_id in stim_dict["protocol_assignments"].items():
        module_id = convert_well_name_to_module_id(well_name, use_stim_mapping=True)
        protocol_assignment_list[module_id - 1] = (
            STIM_NO_PROTOCOL_ASSIGNED if protocol_id is None else protocol_ids.index(protocol_id)
        )
    stim_bytes += bytes(protocol_assignment_list)
    return stim_bytes


def convert_module_id_to_well_name(module_id: int, use_stim_mapping: bool = False) -> str:
    mapping = STIM_MODULE_ID_TO_WELL_IDX if use_stim_mapping else SERIAL_COMM_MODULE_ID_TO_WELL_IDX
    well_name: str = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(mapping[module_id])
    return well_name


def convert_stim_bytes_to_dict(stim_bytes: bytes) -> Dict[str, Any]:
    """Convert a stimulation info bytes to dictionary."""
    stim_info_dict: Dict[str, Any] = {"protocols": [], "protocol_assignments": {}}

    # convert protocol definition bytes
    num_protocols = stim_bytes[0]
    curr_byte_idx = 1
    for _ in range(num_protocols):
        num_subprotocols = stim_bytes[curr_byte_idx]
        curr_byte_idx += 1

        subprotocol_bytes_list = []
        for _ in range(num_subprotocols):
            subprotocol_bytes_list.append(stim_bytes[curr_byte_idx : curr_byte_idx + 29])
            curr_byte_idx += 29  # is_null_subprotocol byte is unused here

        stimulation_type = "V" if stim_bytes[curr_byte_idx] else "C"
        run_until_stopped = bool(stim_bytes[curr_byte_idx + 1])

        subprotocol_list = [
            convert_bytes_to_subprotocol_dict(subprotocol_bytes, is_voltage=stimulation_type == "V")
            for subprotocol_bytes in subprotocol_bytes_list
        ]
        stim_info_dict["protocols"].append(
            {
                "stimulation_type": stimulation_type,
                "run_until_stopped": run_until_stopped,
                "subprotocols": subprotocol_list,
            }
        )
        curr_byte_idx += 3

    # convert module ID / protocol idx pair bytes
    num_assignments = len(stim_bytes[curr_byte_idx:])
    for module_id in range(1, num_assignments + 1):
        well_name = (
            convert_module_id_to_well_name(module_id, use_stim_mapping=True) if module_id <= 24 else ""
        )
        protocol_id_idx = (
            None if stim_bytes[curr_byte_idx] == STIM_NO_PROTOCOL_ASSIGNED else stim_bytes[curr_byte_idx]
        )
        stim_info_dict["protocol_assignments"][well_name] = protocol_id_idx
        curr_byte_idx += 1
    return stim_info_dict


def chunk_protocols_in_stim_info(
    stim_info: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Dict[int, int]]]:
    # copying so the original dict passed in does not get modified
    stim_info_copy = copy.deepcopy(stim_info)

    subprotocol_idx_mappings = {}

    for protocol in stim_info_copy["protocols"]:
        chunked_idx_to_original_idx = {}
        curr_idx = 0

        subprotocol_chunks = []
        for original_idx, subprotocol in enumerate(protocol["subprotocols"]):
            if subprotocol["type"] == "delay":
                subprotocol_chunks.append(subprotocol)

                chunked_idx_to_original_idx[curr_idx] = original_idx
                curr_idx += 1
            else:
                subprotocol_cycle_dur = get_subprotocol_cycle_duration(subprotocol)
                total_num_cycles = subprotocol["num_cycles"]

                num_cycles_per_full_chunk = (
                    STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // subprotocol_cycle_dur
                )
                num_full_chunks = total_num_cycles // num_cycles_per_full_chunk

                # add full chunks
                subprotocol_chunks.extend(
                    [{**subprotocol, "num_cycles": num_cycles_per_full_chunk}] * num_full_chunks
                )

                # update mapping
                chunked_idx_to_original_idx.update(
                    {chunked_idx: original_idx for chunked_idx in range(curr_idx, curr_idx + num_full_chunks)}
                )
                curr_idx += num_full_chunks

                # if necessary, add one more incomplete chunk to reach the total number of cycles
                if num_remaining_cycles := total_num_cycles - (num_cycles_per_full_chunk * num_full_chunks):
                    subprotocol_chunks.append({**subprotocol, "num_cycles": num_remaining_cycles})
                    chunked_idx_to_original_idx[curr_idx] = original_idx
                    curr_idx += 1

        protocol["subprotocols"] = subprotocol_chunks
        subprotocol_idx_mappings[protocol["protocol_id"]] = chunked_idx_to_original_idx

    return stim_info_copy, subprotocol_idx_mappings
