# -*- coding: utf-8 -*-
"""Utility functions for Serial Communication."""
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import Union
from uuid import UUID
from zlib import crc32

from immutabledict import immutabledict
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID

from .constants import BOOTUP_COUNTER_UUID
from .constants import PCB_SERIAL_NUMBER_UUID
from .constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_METADATA_BYTES_LENGTH
from .constants import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from .constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .constants import TAMPER_FLAG_UUID
from .constants import TOTAL_WORKING_HOURS_UUID
from .exceptions import SerialCommMetadataValueTooLargeError


# Tanner (3/18/21): If/When cython is needed to improve serial communication, this file will likely be a good place to start


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
    data_packet += packet_length.to_bytes(
        SERIAL_COMM_PACKET_INFO_LENGTH_BYTES, byteorder="little"
    )
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


def convert_to_metadata_bytes(value: Union[str, int]) -> bytes:
    """Convert a value to the correct number of bytes for MCU metadata."""
    # TODO Tanner (3/17/21): Need to be able to handle signed int values. This also includes determining if the int value should be signed, maybe a kwarg
    if isinstance(value, int):
        if value < 0:
            raise NotImplementedError(
                "Signed integer values are currrently unsupported"
            )
        if value > (1 << SERIAL_COMM_METADATA_BYTES_LENGTH) - 1:
            raise SerialCommMetadataValueTooLargeError(
                f"Value: {value} cannot fit into {SERIAL_COMM_METADATA_BYTES_LENGTH} bytes"
            )
        return value.to_bytes(SERIAL_COMM_METADATA_BYTES_LENGTH, byteorder="little")
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
        this_metadata_bytes = metadata_bytes[
            this_metadata_idx : this_metadata_idx + single_metadata_length
        ]
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
    return status_code.to_bytes(
        SERIAL_COMM_STATUS_CODE_LENGTH_BYTES, byteorder="little"
    )


def convert_to_timestamp_bytes(timestamp: int) -> bytes:
    return timestamp.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little")
