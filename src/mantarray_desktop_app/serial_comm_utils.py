# -*- coding: utf-8 -*-
"""Utility functions for Serial Communication."""
from __future__ import annotations

import datetime
from typing import Any
from typing import Dict
from uuid import UUID
from zlib import crc32

from immutabledict import immutabledict
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import BOOTUP_COUNTER_UUID
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
from pulse3D.constants import PCB_SERIAL_NUMBER_UUID
from pulse3D.constants import TAMPER_FLAG_UUID
from pulse3D.constants import TOTAL_WORKING_HOURS_UUID

from .constants import GENERIC_24_WELL_DEFINITION
from .constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from .constants import SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
from .constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from .constants import SERIAL_COMM_TIMESTAMP_EPOCH
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .constants import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from .constants import STIM_MODULE_ID_TO_WELL_IDX
from .constants import STIM_NO_PROTOCOL_ASSIGNED
from .constants import STIM_WELL_IDX_TO_MODULE_ID


# Tanner (3/18/21): If/When additional cython is needed to improve serial communication, this file may be worth investigating


METADATA_TYPES = immutabledict(
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


def _get_checksum_bytes(packet: bytes) -> bytes:
    return crc32(packet).to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")


def create_data_packet(
    timestamp: int,
    packet_type: int,
    packet_data: bytes = bytes(0),
) -> bytes:
    """Create a data packet to send to the PC."""
    packet_body = convert_to_timestamp_bytes(timestamp)
    packet_body += bytes([packet_type])
    packet_body += packet_data
    packet_length = len(packet_body) + SERIAL_COMM_CHECKSUM_LENGTH_BYTES

    data_packet = SERIAL_COMM_MAGIC_WORD_BYTES
    data_packet += packet_length.to_bytes(SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES, byteorder="little")
    data_packet += packet_body
    data_packet += _get_checksum_bytes(data_packet)
    return data_packet


def validate_checksum(comm_from_pc: bytes) -> bool:
    expected_checksum = crc32(comm_from_pc[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES])
    actual_checksum = int.from_bytes(
        comm_from_pc[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:],
        byteorder="little",
    )
    return actual_checksum == expected_checksum


def parse_metadata_bytes(metadata_bytes: bytes) -> Dict[UUID, Any]:
    """Parse bytes containing metadata and return as Dict."""
    return {
        BOOT_FLAGS_UUID: metadata_bytes[0],
        MANTARRAY_NICKNAME_UUID: metadata_bytes[1:14].decode("utf-8"),
        MANTARRAY_SERIAL_NUMBER_UUID: metadata_bytes[14:26].decode("ascii"),
        MAIN_FIRMWARE_VERSION_UUID: convert_semver_bytes_to_str(metadata_bytes[26:29]),
        CHANNEL_FIRMWARE_VERSION_UUID: convert_semver_bytes_to_str(metadata_bytes[29:32]),
    }


def convert_metadata_to_bytes(metadata_dict: Dict[UUID, Any]) -> bytes:
    return (
        bytes([metadata_dict[BOOT_FLAGS_UUID]])
        + bytes(metadata_dict[MANTARRAY_NICKNAME_UUID], encoding="utf-8")
        + bytes(metadata_dict[MANTARRAY_SERIAL_NUMBER_UUID], encoding="ascii")
        + convert_semver_str_to_bytes(metadata_dict[MAIN_FIRMWARE_VERSION_UUID])
        + convert_semver_str_to_bytes(metadata_dict[CHANNEL_FIRMWARE_VERSION_UUID])
    )


def convert_semver_bytes_to_str(semver_bytes: bytes) -> str:
    return f"{semver_bytes[0]}.{semver_bytes[1]}.{semver_bytes[2]}"


def convert_semver_str_to_bytes(semver_str: str) -> bytes:
    return bytes([int(num) for num in semver_str.split(".")])


def convert_to_status_code_bytes(status_code: int) -> bytes:
    # simulator will only ever change byte 0 of status code
    return bytes([status_code, 0, 0, 0])


def convert_status_code_bytes_to_dict(status_code_bytes: bytes) -> Dict[str, int]:
    if len(status_code_bytes) != SERIAL_COMM_STATUS_CODE_LENGTH_BYTES:
        raise ValueError(
            f"Status code bytes must have len of {SERIAL_COMM_STATUS_CODE_LENGTH_BYTES}, {len(status_code_bytes)} bytes given: {str(status_code_bytes)}"
        )
    status_code_labels = ("main", "channel", "index_of_thread_with_error", "TBD")
    return {label: status_code_bytes[i] for i, label in enumerate(status_code_labels)}


def convert_to_timestamp_bytes(timestamp: int) -> bytes:
    return timestamp.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little")


def get_serial_comm_timestamp() -> int:
    # Tanner (4/7/21): This method should not be used in the simulator. It has its own way of determining the timestamp to send in order to behave more accurately like the real Mantarray instrument
    return (
        datetime.datetime.now(tz=datetime.timezone.utc) - SERIAL_COMM_TIMESTAMP_EPOCH
    ) // datetime.timedelta(microseconds=1)


def is_null_subprotocol(subprotocol_dict: Dict[str, int]) -> bool:
    return not any(
        val
        for key, val in subprotocol_dict.items()
        if key not in ("phase_one_duration", "total_active_duration")
    )


def convert_subprotocol_dict_to_bytes(subprotocol_dict: Dict[str, int], is_voltage: bool = False) -> bytes:
    conversion_factor = 1 if is_voltage else 10
    return (
        subprotocol_dict["phase_one_duration"].to_bytes(4, byteorder="little")
        + (subprotocol_dict["phase_one_charge"] // conversion_factor).to_bytes(
            2, byteorder="little", signed=True
        )
        + subprotocol_dict["interphase_interval"].to_bytes(4, byteorder="little")
        + bytes(2)  # interphase_interval amplitude (always 0)
        + subprotocol_dict["phase_two_duration"].to_bytes(4, byteorder="little")
        + (subprotocol_dict["phase_two_charge"] // conversion_factor).to_bytes(
            2, byteorder="little", signed=True
        )
        + subprotocol_dict["repeat_delay_interval"].to_bytes(4, byteorder="little")
        + bytes(2)  # repeat_delay_interval amplitude (always 0)
        + subprotocol_dict["total_active_duration"].to_bytes(4, byteorder="little")
        + bytes([is_null_subprotocol(subprotocol_dict)])
    )


def convert_bytes_to_subprotocol_dict(subprotocol_bytes: bytes, is_voltage: bool = False) -> Dict[str, int]:
    conversion_factor = 1 if is_voltage else 10
    return {
        "phase_one_duration": int.from_bytes(subprotocol_bytes[:4], byteorder="little"),
        "phase_one_charge": int.from_bytes(subprotocol_bytes[4:6], byteorder="little", signed=True)
        * conversion_factor,
        "interphase_interval": int.from_bytes(subprotocol_bytes[6:10], byteorder="little"),
        "phase_two_duration": int.from_bytes(subprotocol_bytes[12:16], byteorder="little"),
        "phase_two_charge": int.from_bytes(subprotocol_bytes[16:18], byteorder="little", signed=True)
        * conversion_factor,
        "repeat_delay_interval": int.from_bytes(subprotocol_bytes[18:22], byteorder="little"),
        "total_active_duration": int.from_bytes(subprotocol_bytes[24:28], byteorder="little"),
    }


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
        stim_bytes += bytes([is_voltage_controlled])  # control method
        stim_bytes += bytes([protocol_dict["run_until_stopped"]])  # schedule mode
        stim_bytes += bytes([0])  # data type, always 0 as of 9/29/21
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
    stim_info_dict: Dict[str, Any] = {
        "protocols": [],
        "protocol_assignments": {},
    }

    # convert protocol definition bytes
    num_protocols = stim_bytes[0]
    curr_byte_idx = 1
    for _ in range(num_protocols):
        num_subprotocols = stim_bytes[curr_byte_idx]
        curr_byte_idx += 1

        subprotocol_bytes_list = []
        for _ in range(num_subprotocols):
            subprotocol_bytes_list.append(stim_bytes[curr_byte_idx : curr_byte_idx + 28])
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
