# -*- coding: utf-8 -*-
from zlib import crc32

from mantarray_desktop_app import convert_to_metadata_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_METADATA_BYTES_LENGTH
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SerialCommMetadataValueTooLargeError
from mantarray_desktop_app import validate_checksum
import pytest


def test_create_data_packet__creates_data_packet_bytes_correctly():
    test_timestamp = 100
    test_module_id = 0
    test_packet_type = 1
    test_data = bytes([1, 5, 3])

    expected_data_packet_bytes = SERIAL_COMM_MAGIC_WORD_BYTES
    expected_data_packet_bytes += (17).to_bytes(2, byteorder="little")
    expected_data_packet_bytes += test_timestamp.to_bytes(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
    )
    expected_data_packet_bytes += bytes([test_module_id, test_packet_type])
    expected_data_packet_bytes += test_data
    expected_data_packet_bytes += crc32(expected_data_packet_bytes).to_bytes(
        SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little"
    )

    actual = create_data_packet(
        test_timestamp,
        test_module_id,
        test_packet_type,
        test_data,
    )
    assert actual == expected_data_packet_bytes


def test_validate_checksum__returns_true_when_checksum_is_correct():
    test_bytes = bytes([1, 2, 3, 4, 5])
    test_bytes += crc32(test_bytes).to_bytes(
        SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little"
    )
    assert validate_checksum(test_bytes) is True


def test_validate_checksum__returns_false_when_checksum_is_incorrect():
    test_bytes = bytes([1, 2, 3, 4, 5])
    test_bytes += (crc32(test_bytes) - 1).to_bytes(
        SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little"
    )
    assert validate_checksum(test_bytes) is False


@pytest.mark.parametrize(
    "test_value,expected_bytes,test_description",
    [
        (
            "My Mantarray Nickname",
            b"My Mantarray Nickname" + bytes(11),
            "converts string to 32 bytes",
        ),
        (
            "Unicøde Nickname",
            bytes("Unicøde Nickname", "utf-8") + bytes(15),
            "converts string with unicode characters to 32 bytes",
        ),
        (
            "A" * SERIAL_COMM_METADATA_BYTES_LENGTH,
            bytes("A" * SERIAL_COMM_METADATA_BYTES_LENGTH, "utf-8"),
            "converts string with max length 32 bytes",
        ),
        (
            (1 << SERIAL_COMM_METADATA_BYTES_LENGTH) - 1,
            ((1 << SERIAL_COMM_METADATA_BYTES_LENGTH) - 1).to_bytes(
                SERIAL_COMM_METADATA_BYTES_LENGTH, byteorder="little"
            ),
            "converts max uint value to 32-byte long little-endian value",
        ),
    ],
)
def test_convert_to_metadata_bytes__returns_correct_values(
    test_value, expected_bytes, test_description
):
    assert convert_to_metadata_bytes(test_value) == expected_bytes


def test_convert_to_metadata_bytes__raises_error_with_integer_value_cannot_fit_in_max_number_of_bytes():
    test_value = 1 << SERIAL_COMM_METADATA_BYTES_LENGTH
    with pytest.raises(SerialCommMetadataValueTooLargeError, match=str(test_value)):
        convert_to_metadata_bytes(test_value)


def test_convert_to_metadata_bytes__raises_error_string_longer_than_max_number_of_bytes():
    test_value = "T" * (SERIAL_COMM_METADATA_BYTES_LENGTH + 1)
    with pytest.raises(SerialCommMetadataValueTooLargeError, match=str(test_value)):
        convert_to_metadata_bytes(test_value)
