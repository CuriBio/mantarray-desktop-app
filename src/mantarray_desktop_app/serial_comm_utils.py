# -*- coding: utf-8 -*-
"""Utility functions for Serial Communication."""
from __future__ import annotations

import datetime
from typing import Any
from typing import Dict
from typing import Optional
from typing import Union
from uuid import UUID
from zlib import crc32

from immutabledict import immutabledict
from mantarray_file_manager import BOOTUP_COUNTER_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import PCB_SERIAL_NUMBER_UUID
from mantarray_file_manager import TAMPER_FLAG_UUID
from mantarray_file_manager import TOTAL_WORKING_HOURS_UUID

from .constants import GENERIC_24_WELL_DEFINITION
from .constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_METADATA_BYTES_LENGTH
from .constants import SERIAL_COMM_NUM_DATA_CHANNELS
from .constants import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from .constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from .constants import SERIAL_COMM_TIMESTAMP_EPOCH
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .constants import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from .exceptions import SerialCommMetadataValueTooLargeError


# Tanner (3/18/21): If/When additional cython is needed to improve serial communication, this file may be worth investigating


METADATA_TYPES = immutabledict(
    {
        MAIN_FIRMWARE_VERSION_UUID: str,
        MANTARRAY_NICKNAME_UUID: str,
        MANTARRAY_SERIAL_NUMBER_UUID: str,
        TOTAL_WORKING_HOURS_UUID: int,
        TAMPER_FLAG_UUID: int,
        BOOTUP_COUNTER_UUID: int,
        PCB_SERIAL_NUMBER_UUID: str,
    }
)
BITMASK_SHIFT_VALUE = 16 - SERIAL_COMM_NUM_DATA_CHANNELS  # 16 for number of bits in int16


def _get_checksum_bytes(packet: bytes) -> bytes:
    return crc32(packet).to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")


def create_data_packet(
    timestamp: int,
    module_id: int,
    packet_type: int,
    packet_data: bytes,
) -> bytes:
    """Create a data packet to send to the PC."""
    packet_body = convert_to_timestamp_bytes(timestamp)
    packet_body += bytes([module_id, packet_type])
    packet_body += packet_data
    packet_length = len(packet_body) + SERIAL_COMM_CHECKSUM_LENGTH_BYTES

    data_packet = SERIAL_COMM_MAGIC_WORD_BYTES
    data_packet += packet_length.to_bytes(SERIAL_COMM_PACKET_INFO_LENGTH_BYTES, byteorder="little")
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


def convert_to_metadata_bytes(value: Union[str, int], signed: bool = False) -> bytes:
    """Convert a value to the correct number of bytes for MCU metadata.

    kwarg `signed` is ignored if the value is not an int.
    """
    if isinstance(value, int):
        value_bytes: bytes
        try:
            value_bytes = value.to_bytes(
                SERIAL_COMM_METADATA_BYTES_LENGTH,
                byteorder="little",
                signed=signed,
            )
        except OverflowError as e:
            signed_str = "Signed" if signed else "Unsigned"
            raise SerialCommMetadataValueTooLargeError(
                f"{signed_str} value: {value} cannot fit into {SERIAL_COMM_METADATA_BYTES_LENGTH} bytes"
            ) from e
        return value_bytes
    if isinstance(value, str):
        value_bytes = bytes(value, encoding="utf-8")
        if len(value_bytes) > SERIAL_COMM_METADATA_BYTES_LENGTH:
            raise SerialCommMetadataValueTooLargeError(
                f"String: {value} exceeds {SERIAL_COMM_METADATA_BYTES_LENGTH} bytes"
            )
        num_bytes_to_append = SERIAL_COMM_METADATA_BYTES_LENGTH - len(value_bytes)
        value_bytes += bytes(num_bytes_to_append)
        return value_bytes
    raise NotImplementedError(f"No MCU metadata values are of type: {type(value)}")


def convert_metadata_bytes_to_str(metadata_bytes: bytes) -> str:
    """Convert bytes to a string.

    Assumes that exactly 32 bytes are given.
    """
    metadata_str = metadata_bytes.decode("utf-8")
    stop_idx = len(metadata_str)
    for char in reversed(metadata_str):
        if char != "\x00":
            break
        stop_idx -= 1
    return metadata_str[:stop_idx]


def parse_metadata_bytes(metadata_bytes: bytes) -> Dict[UUID, Any]:
    """Parse bytes containing metadata and return as Dict."""
    uuid_bytes_length = 16
    single_metadata_length = uuid_bytes_length + SERIAL_COMM_METADATA_BYTES_LENGTH

    metadata_dict: Dict[UUID, Any] = dict()
    for this_metadata_idx in range(0, len(metadata_bytes), single_metadata_length):
        this_metadata_bytes = metadata_bytes[this_metadata_idx : this_metadata_idx + single_metadata_length]
        this_value_bytes = this_metadata_bytes[uuid_bytes_length:]
        this_uuid = UUID(bytes=this_metadata_bytes[:uuid_bytes_length])
        metadata_type = METADATA_TYPES[this_uuid]
        this_value = (
            convert_metadata_bytes_to_str(this_value_bytes)
            if metadata_type == str
            else int.from_bytes(this_value_bytes, byteorder="little")
        )
        metadata_dict[this_uuid] = this_value
    return metadata_dict


def convert_to_status_code_bytes(status_code: int) -> bytes:
    return status_code.to_bytes(SERIAL_COMM_STATUS_CODE_LENGTH_BYTES, byteorder="little")


def convert_to_timestamp_bytes(timestamp: int) -> bytes:
    return timestamp.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little")


def get_serial_comm_timestamp() -> int:
    # Tanner (4/7/21): This method should not be used in the simulator. It has its own way of determining the timestamp to send in order to behave more accurately like the real Mantarray instrument
    return (
        datetime.datetime.now(tz=datetime.timezone.utc) - SERIAL_COMM_TIMESTAMP_EPOCH
    ) // datetime.timedelta(microseconds=1)


def create_sensor_axis_bitmask(config_dict: Dict[int, bool]) -> int:
    bitmask = 0
    for sensor_axis_id, config_value in config_dict.items():
        bitmask += int(config_value) << sensor_axis_id
    return bitmask


def create_magnetometer_config_bytes(config_dict: Dict[int, Dict[int, bool]]) -> bytes:
    config_bytes = bytes(0)
    for module_id, well_config in config_dict.items():
        config_bytes += bytes([module_id])
        config_bytes += create_sensor_axis_bitmask(well_config).to_bytes(2, byteorder="little")
    return config_bytes


def convert_bitmask_to_config_dict(bitmask: int) -> Dict[int, bool]:
    config_dict: Dict[int, bool] = dict()
    bit = 1
    for sensor_axis_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
        config_dict[sensor_axis_id] = bool(bitmask & bit)
        bit <<= 1
    return config_dict


def convert_bytes_to_config_dict(
    magnetometer_config_bytes: bytes,
) -> Dict[int, Dict[int, bool]]:
    """Covert bytes from the instrument to a configuration dictionary."""
    config_dict: Dict[int, Dict[int, bool]] = dict()
    for config_block_idx in range(0, len(magnetometer_config_bytes), 3):
        module_id = magnetometer_config_bytes[config_block_idx]
        bitmask_bytes = magnetometer_config_bytes[config_block_idx + 1 : config_block_idx + 3]
        bitmask = int.from_bytes(bitmask_bytes, byteorder="little")
        config_dict[module_id] = convert_bitmask_to_config_dict(bitmask)
    return config_dict


def convert_subprotocol_dict_to_bytes(subprotocol_dict: Dict[str, int]) -> bytes:
    is_null_subprotocol = not any(
        val
        for key, val in subprotocol_dict.items()
        if key not in ("phase_one_duration", "total_active_duration")
    )
    return (
        subprotocol_dict["phase_one_duration"].to_bytes(4, byteorder="little")
        + subprotocol_dict["phase_one_charge"].to_bytes(2, byteorder="little", signed=True)
        + subprotocol_dict["interpulse_interval"].to_bytes(4, byteorder="little")
        + bytes(2)  # interpulse_interval amplitude (always 0)
        + subprotocol_dict["phase_two_duration"].to_bytes(4, byteorder="little")
        + subprotocol_dict["phase_two_charge"].to_bytes(2, byteorder="little", signed=True)
        + subprotocol_dict["repeat_delay_interval"].to_bytes(4, byteorder="little")
        + bytes(2)  # repeat_delay_interval amplitude (always 0)
        + subprotocol_dict["total_active_duration"].to_bytes(4, byteorder="little")
        + bytes([is_null_subprotocol])
    )


def convert_bytes_to_subprotocol_dict(subprotocol_bytes: bytes) -> Dict[str, int]:
    return {
        "phase_one_duration": int.from_bytes(subprotocol_bytes[:4], byteorder="little"),
        "phase_one_charge": int.from_bytes(subprotocol_bytes[4:6], byteorder="little", signed=True),
        "interpulse_interval": int.from_bytes(subprotocol_bytes[6:10], byteorder="little"),
        "phase_two_duration": int.from_bytes(subprotocol_bytes[12:16], byteorder="little"),
        "phase_two_charge": int.from_bytes(subprotocol_bytes[16:18], byteorder="little", signed=True),
        "repeat_delay_interval": int.from_bytes(subprotocol_bytes[18:22], byteorder="little"),
        "total_active_duration": int.from_bytes(subprotocol_bytes[24:28], byteorder="little"),
    }


def _convert_protocol_id_str_to_int(protocol_id: Optional[str]) -> int:
    return 0 if protocol_id is None else ord(protocol_id) - ord("A") + 1


def convert_stim_dict_to_bytes(stim_dict: Dict[Any, Any]) -> bytes:
    """Convert a stimulation info dictionary to bytes."""
    # add bytes for protocol definitions
    stim_bytes = bytes([len(stim_dict["protocols"])])  # number of unique protocols
    for protocol_dict in stim_dict["protocols"]:
        stim_bytes += bytes([_convert_protocol_id_str_to_int(protocol_dict["protocol_id"])])  # protocol ID
        stim_bytes += bytes([len(protocol_dict["subprotocols"])])  # num subprotocols
        for subprotocol_dict in protocol_dict["subprotocols"]:
            stim_bytes += convert_subprotocol_dict_to_bytes(subprotocol_dict)
        stim_bytes += bytes([protocol_dict["stimulation_type"] == "V"])  # control_method
        stim_bytes += bytes([protocol_dict["run_until_stopped"]])  # schedule_mode
        stim_bytes += bytes([0])  # data_type, always 0 as of 9/29/21
    # add bytes for module ID / protocol ID pairs
    protocol_ids = [-1] * 24
    for well_name, protocol_id in stim_dict["well_name_to_protocol_id"].items():
        module_id = SERIAL_COMM_WELL_IDX_TO_MODULE_ID[
            GENERIC_24_WELL_DEFINITION.get_well_index_from_well_name(well_name)
        ]
        protocol_ids[module_id - 1] = _convert_protocol_id_str_to_int(protocol_id)
    stim_bytes += bytes(protocol_ids)
    return stim_bytes
