# -*- coding: utf-8 -*-
"""Utility functions for Serial Communication."""
from __future__ import annotations

from typing import Union
from zlib import crc32

from .constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_METADATA_BYTES_LENGTH
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .exceptions import SerialCommMetadataValueTooLargeError


def _get_checksum_bytes(packet: bytes) -> bytes:
    return crc32(packet).to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")


def create_data_packet(
    timestamp: int,
    module_id: int,
    packet_type: int,
    packet_data: bytes,
) -> bytes:
    """Create a data packet to send to the PC."""
    packet_body = timestamp.to_bytes(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
    )
    packet_body += bytes([module_id, packet_type])
    packet_body += packet_data
    packet_length = len(packet_body) + SERIAL_COMM_CHECKSUM_LENGTH_BYTES

    data_packet = SERIAL_COMM_MAGIC_WORD_BYTES
    data_packet += packet_length.to_bytes(2, byteorder="little")
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
