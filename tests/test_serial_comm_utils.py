# -*- coding: utf-8 -*-
import datetime
from random import randint
from zlib import crc32

from freezegun import freeze_time
from mantarray_desktop_app import convert_bitmask_to_config_dict
from mantarray_desktop_app import convert_bytes_to_config_dict
from mantarray_desktop_app import convert_bytes_to_subprotocol_dict
from mantarray_desktop_app import convert_stim_dict_to_bytes
from mantarray_desktop_app import convert_subprotocol_dict_to_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import create_magnetometer_config_bytes
from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import create_sensor_axis_bitmask
from mantarray_desktop_app import get_serial_comm_timestamp
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import parse_metadata_bytes
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_METADATA_BYTES_LENGTH
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_EPOCH
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import STIM_NO_PROTOCOL_ASSIGNED
from mantarray_desktop_app import validate_checksum
from mantarray_desktop_app.constants import BOOT_FLAGS_UUID
from mantarray_desktop_app.constants import CHANNEL_FIRMWARE_VERSION_UUID
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID

from .fixtures import fixture_patch_print
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from .helpers import random_bool


__fixtures__ = [fixture_patch_print, fixture_mantarray_mc_simulator_no_beacon]


API_EXAMPLE_MODULE_DICT = {
    SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: True,
    SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Y"]: False,
    SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Z"]: True,
    SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["X"]: False,
    SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Y"]: True,
    SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Z"]: True,
    SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["X"]: False,
    SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Y"]: True,
    SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: True,
}
API_EXAMPLE_BITMASK = 0b110110101
API_EXAMPLE_BYTES = bytes([0b00001110, 0b10110101, 0b00000001])


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
    test_bytes += crc32(test_bytes).to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")
    assert validate_checksum(test_bytes) is True


def test_validate_checksum__returns_false_when_checksum_is_incorrect():
    test_bytes = bytes([1, 2, 3, 4, 5])
    test_bytes += (crc32(test_bytes) - 1).to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")
    assert validate_checksum(test_bytes) is False


def test_parse_metadata_bytes__returns_expected_value():
    metadata_bytes = (
        bytes([0b10101010])  # boot flags
        + bytes("マンタレ1", encoding="utf-8")  # nickname
        + bytes(MantarrayMcSimulator.default_mantarray_serial_number, encoding="ascii")
        + bytes([0, 1, 2])  # main FW version
        + bytes([255, 255, 255])  # channel FW version
    )
    assert len(metadata_bytes) == SERIAL_COMM_METADATA_BYTES_LENGTH

    assert parse_metadata_bytes(metadata_bytes) == {
        BOOT_FLAGS_UUID: 0b10101010,
        MANTARRAY_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_mantarray_serial_number,
        MANTARRAY_NICKNAME_UUID: "マンタレ1",
        MAIN_FIRMWARE_VERSION_UUID: "0.1.2",
        CHANNEL_FIRMWARE_VERSION_UUID: "255.255.255",
    }


@freeze_time("2021-04-07 13:14:07.234987")
def test_get_serial_comm_timestamp__returns_microseconds_since_2021_01_01():
    expected_usecs = (
        datetime.datetime.now(tz=datetime.timezone.utc) - SERIAL_COMM_TIMESTAMP_EPOCH
    ) // datetime.timedelta(microseconds=1)
    actual = get_serial_comm_timestamp()
    assert actual == expected_usecs


def test_create_sensor_axis_bitmask__returns_correct_value_for_api_definition():
    actual = create_sensor_axis_bitmask(API_EXAMPLE_MODULE_DICT)
    assert bin(actual) == bin(API_EXAMPLE_BITMASK)


def test_create_magnetometer_config_bytes__matches_api_definition_for_single_well():
    expected_module_id = API_EXAMPLE_BYTES[0]
    test_dict = {expected_module_id: API_EXAMPLE_MODULE_DICT}
    actual = create_magnetometer_config_bytes(test_dict)
    for byte_idx, byte_value in enumerate(API_EXAMPLE_BYTES):
        actual_byte = actual[byte_idx : byte_idx + 1]
        actual_value = int.from_bytes(actual_byte, byteorder="little")
        assert bin(actual_value) == bin(byte_value), f"Incorrect value at byte {byte_idx}"


def test_create_magnetometer_config_bytes__returns_correct_values_for_every_module_id():
    test_num_wells = 24
    test_dict = create_magnetometer_config_dict(test_num_wells)
    # arbitrarily change values
    for key in test_dict[1].keys():
        test_dict[1][key] = True
    test_dict[2] = convert_bitmask_to_config_dict(0b111000100)
    # create expected bit-masks
    expected_uint16_bitmasks = [0b111111111, 0b111000100]
    expected_uint16_bitmasks.extend([0 for _ in range(test_num_wells - 2)])
    # test actual bytes
    actual = create_magnetometer_config_bytes(test_dict)
    for module_id in range(1, test_num_wells + 1):
        start_idx = (module_id - 1) * 3
        assert actual[start_idx] == module_id, f"Incorrect module_id at idx: {module_id}"
        bitmask_bytes = expected_uint16_bitmasks[module_id - 1].to_bytes(2, byteorder="little")
        assert (
            actual[start_idx + 1 : start_idx + 3] == bitmask_bytes
        ), f"Incorrect bitmask bytes for module_id: {module_id}"


def test_convert_bitmask_to_config_dict__returns_correct_values_for_api_definition():
    actual = convert_bitmask_to_config_dict(API_EXAMPLE_BITMASK)
    assert actual == API_EXAMPLE_MODULE_DICT


def test_convert_bytes_to_config_dict__returns_correct_value_for_api_definition():
    expected_dict = {API_EXAMPLE_BYTES[0]: API_EXAMPLE_MODULE_DICT}
    actual = convert_bytes_to_config_dict(API_EXAMPLE_BYTES)
    assert actual == expected_dict


def test_convert_bytes_to_config_dict__returns_correct_values_for_every_module_id():
    test_num_wells = 24
    expected_config_dict = {
        module_id: {channel_id: random_bool() for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS)}
        for module_id in range(1, test_num_wells + 1)
    }
    test_bytes = create_magnetometer_config_bytes(expected_config_dict)
    actual = convert_bytes_to_config_dict(test_bytes)
    assert actual == expected_config_dict


def test_convert_subprotocol_dict_to_bytes__returns_expected_bytes__when_voltage_controlled_subprotocol_is_not_a_delay():
    test_subprotocol_dict = {
        "phase_one_duration": 0x111,
        "phase_one_charge": 0x333,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x777,
        "phase_two_charge": -1,
        "repeat_delay_interval": 0x999,
        "total_active_duration": 0x1234,
    }
    # fmt: off
    expected_bytes = bytes(
        [
            0x11, 1, 0, 0,  # phase_one_duration
            0x33, 3,  # phase_one_charge
            0x55, 5, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0x77, 7, 0, 0,  # phase_two_duration
            0xFF, 0xFF,  # phase_two_charge
            0x99, 9, 0, 0,  # repeat_delay_interval
            0, 0,  # repeat_delay_interval amplitude (always 0)
            0x34, 0x12, 0, 0,  # total_active_duration
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_dict_to_bytes(test_subprotocol_dict, is_voltage=True)
    assert actual == expected_bytes


def test_convert_subprotocol_dict_to_bytes__returns_expected_bytes__when_current_controlled_subprotocol_is_not_a_delay():
    test_subprotocol_dict = {
        "phase_one_duration": 0x111,
        "phase_one_charge": 50,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x777,
        "phase_two_charge": -50,
        "repeat_delay_interval": 0x999,
        "total_active_duration": 0x1234,
    }
    # fmt: off
    expected_bytes = bytes(
        [
            0x11, 1, 0, 0,  # phase_one_duration
            0x05, 0,  # phase_one_charge
            0x55, 5, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0x77, 7, 0, 0,  # phase_two_duration
            0xFB, 0xFF,  # phase_two_charge
            0x99, 9, 0, 0,  # repeat_delay_interval
            0, 0,  # repeat_delay_interval amplitude (always 0)
            0x34, 0x12, 0, 0,  # total_active_duration
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_dict_to_bytes(test_subprotocol_dict)
    assert actual == expected_bytes


def test_convert_subprotocol_dict_to_bytes__returns_expected_bytes__when_subprotocol_is_a_delay():
    test_subprotocol_dict = {
        "phase_one_duration": 0x111,
        "phase_one_charge": 0,
        "interphase_interval": 0,
        "phase_two_duration": 0,
        "phase_two_charge": 0,
        "repeat_delay_interval": 0,
        "total_active_duration": 0x111,
    }
    # fmt: off
    expected_bytes = bytes(
        [
            0x11, 1, 0, 0,  # phase_one_duration
            0, 0,  # phase_one_charge
            0, 0, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0, 0, 0, 0,  # phase_two_duration
            0, 0,  # phase_two_charge
            0, 0, 0, 0,  # repeat_delay_interval
            0, 0,  # repeat_delay_interval amplitude (always 0)
            0x11, 1, 0, 0,  # total_active_duration
            1,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_dict_to_bytes(test_subprotocol_dict)
    assert actual == expected_bytes


def test_convert_bytes_to_subprotocol_dict__returns_expected_dict__when_voltage_controlled_subprotocol_is_not_a_delay():
    # fmt: off
    test_bytes = bytes(
        [
            0x99, 9, 0, 0,  # phase_one_duration
            0x77, 7,  # phase_one_charge
            0x55, 5, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0x33, 3, 0, 0,  # phase_two_duration
            0xFF, 0xFF,  # phase_two_charge
            0x11, 1, 0, 0,  # repeat_delay_interval
            0, 0,  # repeat_delay_interval amplitude (always 0)
            0x21, 0x43, 0, 0,  # total_active_duration
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    expected_subprotocol_dict = {
        "phase_one_duration": 0x999,
        "phase_one_charge": 0x777,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x333,
        "phase_two_charge": -1,
        "repeat_delay_interval": 0x111,
        "total_active_duration": 0x4321,
    }

    actual = convert_bytes_to_subprotocol_dict(test_bytes, is_voltage=True)
    assert actual == expected_subprotocol_dict


def test_convert_bytes_to_subprotocol_dict__returns_expected_dict__when_current_controlled_subprotocol_is_not_a_delay():
    # fmt: off
    test_bytes = bytes(
        [
            0x99, 9, 0, 0,  # phase_one_duration
            0x77, 7,  # phase_one_charge
            0x55, 5, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0x33, 3, 0, 0,  # phase_two_duration
            0xFF, 0xFF,  # phase_two_charge
            0x11, 1, 0, 0,  # repeat_delay_interval
            0, 0,  # repeat_delay_interval amplitude (always 0)
            0x21, 0x43, 0, 0,  # total_active_duration
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    expected_subprotocol_dict = {
        "phase_one_duration": 0x999,
        "phase_one_charge": 0x777 * 10,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x333,
        "phase_two_charge": -1 * 10,
        "repeat_delay_interval": 0x111,
        "total_active_duration": 0x4321,
    }

    actual = convert_bytes_to_subprotocol_dict(test_bytes)
    assert actual == expected_subprotocol_dict


def test_convert_bytes_to_subprotocol_dict__returns_expected_dict__when_subprotocol_is_a_delay():
    # fmt: off
    test_bytes = bytes(
        [
            0x88, 8, 0, 0,  # phase_one_duration
            0, 0,  # phase_one_charge
            0, 0, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0, 0, 0, 0,  # phase_two_duration
            0, 0,  # phase_two_charge
            0, 0, 0, 0,  # repeat_delay_interval
            0, 0,  # repeat_delay_interval amplitude (always 0)
            0x88, 8, 0, 0,  # total_active_duration
            1,  # is_null_subprotocol
        ]
    )
    # fmt: on
    expected_subprotocol_dict = {
        "phase_one_duration": 0x888,
        "phase_one_charge": 0,
        "interphase_interval": 0,
        "phase_two_duration": 0,
        "phase_two_charge": 0,
        "repeat_delay_interval": 0,
        "total_active_duration": 0x888,
    }

    actual = convert_bytes_to_subprotocol_dict(test_bytes)
    assert actual == expected_subprotocol_dict


def test_convert_stim_dict_to_bytes__return_expected_bytes():
    protocol_assignments_dict = {"D1": "A", "D2": "D"}
    protocol_assignments_dict.update(
        {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): None
            for well_idx in range(24)
            if GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
            not in protocol_assignments_dict
        }
    )
    expected_module_protocol_pairs = [0, 1]
    expected_module_protocol_pairs.extend([STIM_NO_PROTOCOL_ASSIGNED] * 22)

    stim_info_dict = {
        "protocols": [
            {
                "run_until_stopped": True,
                "protocol_id": "A",
                "stimulation_type": "C",
                "subprotocols": [
                    {
                        "phase_one_duration": randint(1, 50),
                        "phase_one_charge": randint(1, 100),
                        "interphase_interval": randint(1, 50),
                        "phase_two_duration": randint(1, 100),
                        "phase_two_charge": randint(1, 50),
                        "repeat_delay_interval": randint(0, 50),
                        "total_active_duration": randint(150, 300),
                    },
                    {
                        "phase_one_duration": 250,
                        "phase_one_charge": 0,
                        "interphase_interval": 0,
                        "phase_two_duration": 0,
                        "phase_two_charge": 0,
                        "repeat_delay_interval": 0,
                        "total_active_duration": 250,
                    },
                ],
            },
            {
                "protocol_id": "D",
                "stimulation_type": "V",
                "run_until_stopped": False,
                "subprotocols": [
                    {
                        "phase_one_duration": randint(1, 50),
                        "phase_one_charge": randint(1, 100),
                        "interphase_interval": randint(1, 50),
                        "phase_two_duration": randint(1, 100),
                        "phase_two_charge": randint(1, 50),
                        "repeat_delay_interval": randint(0, 50),
                        "total_active_duration": randint(150, 300),
                    },
                ],
            },
        ],
        "protocol_assignments": protocol_assignments_dict,
    }

    expected_bytes = bytes([2])  # num unique protocols
    # bytes for protocol A
    expected_bytes += bytes([2])  # num subprotocols in protocol A
    expected_bytes += convert_subprotocol_dict_to_bytes(
        stim_info_dict["protocols"][0]["subprotocols"][0], is_voltage=False
    )
    expected_bytes += convert_subprotocol_dict_to_bytes(
        stim_info_dict["protocols"][0]["subprotocols"][1], is_voltage=False
    )
    expected_bytes += bytes([0])  # control method
    expected_bytes += bytes([1])  # schedule mode
    expected_bytes += bytes(1)  # data type
    # bytes for protocol D
    expected_bytes += bytes([1])  # num subprotocols in protocol B
    expected_bytes += convert_subprotocol_dict_to_bytes(
        stim_info_dict["protocols"][1]["subprotocols"][0], is_voltage=True
    )
    expected_bytes += bytes([1])  # control method
    expected_bytes += bytes([0])  # schedule mode
    expected_bytes += bytes(1)  # data type
    # module/protocol pairs
    expected_bytes += bytes(expected_module_protocol_pairs)

    actual = convert_stim_dict_to_bytes(stim_info_dict)
    assert actual == expected_bytes
