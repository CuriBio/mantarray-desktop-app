# -*- coding: utf-8 -*-
import datetime
from zlib import crc32

from freezegun import freeze_time
from mantarray_desktop_app import convert_metadata_bytes_to_str
from mantarray_desktop_app import convert_to_metadata_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import get_serial_comm_timestamp
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import parse_metadata_bytes
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_METADATA_BYTES_LENGTH
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_EPOCH
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SerialCommMetadataValueTooLargeError
from mantarray_desktop_app import validate_checksum
import pytest

from .fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon


__fixtures__ = [fixture_mantarray_mc_simulator_no_beacon]


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


def test_convert_to_metadata_bytes__raises_error_with_integer_that_value_cannot_fit_in_max_number_of_bytes():
    test_value = 1 << SERIAL_COMM_METADATA_BYTES_LENGTH
    with pytest.raises(SerialCommMetadataValueTooLargeError, match=str(test_value)):
        convert_to_metadata_bytes(test_value)


def test_convert_to_metadata_bytes__raises_error_string_longer_than_max_number_of_bytes():
    test_value = "T" * (SERIAL_COMM_METADATA_BYTES_LENGTH + 1)
    with pytest.raises(SerialCommMetadataValueTooLargeError, match=str(test_value)):
        convert_to_metadata_bytes(test_value)


@pytest.mark.parametrize(
    "test_bytes,expected_str,test_description",
    [
        (b"", "", "converts empty str correctly"),
        (b"A", "A", "converts single utf-8 character correctly"),
        (
            bytes("水", encoding="utf-8"),
            "水",
            "converts single unicode character correctly",
        ),
        (
            b"1" * SERIAL_COMM_METADATA_BYTES_LENGTH,
            "1" * SERIAL_COMM_METADATA_BYTES_LENGTH,
            "converts 32 bytes of utf-8 correctly",
        ),
        (
            bytes("AAø" * (SERIAL_COMM_METADATA_BYTES_LENGTH // 4), encoding="utf-8"),
            "AAø" * (SERIAL_COMM_METADATA_BYTES_LENGTH // 4),
            "converts 32 bytes with unicode chars correctly",
        ),
    ],
)
def test_convert_metadata_bytes_to_str__returns_correct_string(
    test_bytes, expected_str, test_description
):
    # make sure test_bytes are correct length before sending them through function
    test_bytes += b"\x00" * (SERIAL_COMM_METADATA_BYTES_LENGTH - len(test_bytes))
    actual_str = convert_metadata_bytes_to_str(test_bytes)
    assert actual_str == expected_str


def test_parse_metadata_bytes__returns_metadata_as_dictionary(
    mantarray_mc_simulator_no_beacon,
):
    # Tanner (3/18/21): Need to make sure to test this on all default metadata values, so get them from simulator
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    test_metadata_bytes = bytes(0)
    for key, value in simulator.get_metadata_dict().items():
        test_metadata_bytes += key + value

    actual = parse_metadata_bytes(test_metadata_bytes)
    assert actual == MantarrayMcSimulator.default_metadata_values


@freeze_time("2021-04-07 13:14:07.234987")
def test_get_serial_comm_timestamp__returns_microseconds_since_2021_01_01():
    expected_usecs = (
        datetime.datetime.now(tz=datetime.timezone.utc) - SERIAL_COMM_TIMESTAMP_EPOCH
    ) // datetime.timedelta(microseconds=1)
    actual = get_serial_comm_timestamp()
    assert actual == expected_usecs
