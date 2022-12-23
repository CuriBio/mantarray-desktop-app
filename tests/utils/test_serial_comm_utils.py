# -*- coding: utf-8 -*-
import copy
import datetime
import itertools
from random import choice
from random import randint
from zlib import crc32

from freezegun import freeze_time
from mantarray_desktop_app import convert_status_code_bytes_to_dict
from mantarray_desktop_app import convert_stim_dict_to_bytes
from mantarray_desktop_app import convert_subprotocol_pulse_bytes_to_dict
from mantarray_desktop_app import convert_subprotocol_pulse_dict_to_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import get_serial_comm_timestamp
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import parse_metadata_bytes
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_METADATA_BYTES_LENGTH
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_EPOCH
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import STIM_NO_PROTOCOL_ASSIGNED
from mantarray_desktop_app import validate_checksum
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import SERIAL_COMM_PACKET_BASE_LENGTH_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app.constants import STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS
from mantarray_desktop_app.constants import STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import STIM_OPEN_CIRCUIT_THRESHOLD_OHMS
from mantarray_desktop_app.constants import STIM_SHORT_CIRCUIT_THRESHOLD_OHMS
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
from mantarray_desktop_app.utils import serial_comm
from mantarray_desktop_app.utils.serial_comm import chunk_protocols_in_stim_info
from mantarray_desktop_app.utils.serial_comm import convert_adc_readings_to_circuit_status
from mantarray_desktop_app.utils.serial_comm import convert_adc_readings_to_impedance
from mantarray_desktop_app.utils.serial_comm import convert_subprotocol_node_bytes_to_dict
from mantarray_desktop_app.utils.serial_comm import convert_subprotocol_node_dict_to_bytes
import numpy as np
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import INITIAL_MAGNET_FINDING_PARAMS_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
import pytest

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_random_biphasic_pulse
from ..fixtures_mc_simulator import get_random_monophasic_pulse
from ..fixtures_mc_simulator import get_random_stim_delay
from ..fixtures_mc_simulator import get_random_stim_pulse
from ..fixtures_mc_simulator import random_stim_type
from ..helpers import assert_subprotocol_bytes_are_expected
from ..helpers import assert_subprotocol_node_bytes_are_expected
from ..helpers import random_bool


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
    test_packet_type = 1
    test_data = bytes([1, 5, 3])
    test_packet_remainder_size = (
        SERIAL_COMM_PACKET_BASE_LENGTH_BYTES + len(test_data) + SERIAL_COMM_CHECKSUM_LENGTH_BYTES
    )

    expected_data_packet_bytes = SERIAL_COMM_MAGIC_WORD_BYTES
    expected_data_packet_bytes += test_packet_remainder_size.to_bytes(2, byteorder="little")
    expected_data_packet_bytes += test_timestamp.to_bytes(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
    )
    expected_data_packet_bytes += bytes([test_packet_type])
    expected_data_packet_bytes += test_data
    expected_data_packet_bytes += crc32(expected_data_packet_bytes).to_bytes(
        SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little"
    )

    actual = create_data_packet(test_timestamp, test_packet_type, test_data)
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
    test_status_codes = list(range(SERIAL_COMM_STATUS_CODE_LENGTH_BYTES))

    metadata_bytes = (
        bytes([0b10101010])  # boot flags
        + bytes("マンタレ1", encoding="utf-8")  # nickname
        + bytes(MantarrayMcSimulator.default_mantarray_serial_number, encoding="ascii")
        + bytes([0, 1, 2])  # main FW version
        + bytes([255, 255, 255])  # channel FW version
        + bytes(test_status_codes)
        + MantarrayMcSimulator.initial_magnet_finding_params["X"].to_bytes(1, byteorder="little", signed=True)
        + MantarrayMcSimulator.initial_magnet_finding_params["Y"].to_bytes(1, byteorder="little", signed=True)
        + MantarrayMcSimulator.initial_magnet_finding_params["Z"].to_bytes(1, byteorder="little", signed=True)
        + MantarrayMcSimulator.initial_magnet_finding_params["REMN"].to_bytes(
            2, byteorder="little", signed=True
        )
    )

    metadata_bytes += bytes(SERIAL_COMM_METADATA_BYTES_LENGTH - len(metadata_bytes))

    # confirm precondition
    assert len(metadata_bytes) == SERIAL_COMM_METADATA_BYTES_LENGTH

    assert parse_metadata_bytes(metadata_bytes) == {
        BOOT_FLAGS_UUID: 0b10101010,
        MANTARRAY_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_mantarray_serial_number,
        MANTARRAY_NICKNAME_UUID: "マンタレ1",
        MAIN_FIRMWARE_VERSION_UUID: "0.1.2",
        CHANNEL_FIRMWARE_VERSION_UUID: "255.255.255",
        "status_codes_prior_to_reboot": convert_status_code_bytes_to_dict(bytes(test_status_codes)),
        INITIAL_MAGNET_FINDING_PARAMS_UUID: MantarrayMcSimulator.initial_magnet_finding_params,
    }


@freeze_time("2021-04-07 13:14:07.234987")
def test_get_serial_comm_timestamp__returns_microseconds_since_2021_01_01():
    expected_usecs = (
        datetime.datetime.now(tz=datetime.timezone.utc) - SERIAL_COMM_TIMESTAMP_EPOCH
    ) // datetime.timedelta(microseconds=1)
    actual = get_serial_comm_timestamp()
    assert actual == expected_usecs


@pytest.mark.parametrize(
    "test_adc8,test_adc9,expected_impedance",
    [(0, 0, 61.08021), (0, 2039, 21375.4744533), (0, 2049, -192709.2700799), (1113, 0, 9.9680762)],
)
def test_convert_adc_readings_to_impedance__returns_expected_values(test_adc8, test_adc9, expected_impedance):
    actual_impedance = convert_adc_readings_to_impedance(test_adc8, test_adc9)
    np.testing.assert_almost_equal(actual_impedance, expected_impedance)


@pytest.mark.parametrize(
    "test_impedance,expected_status",
    [
        (STIM_OPEN_CIRCUIT_THRESHOLD_OHMS + 1, StimulatorCircuitStatuses.OPEN),
        (STIM_OPEN_CIRCUIT_THRESHOLD_OHMS, StimulatorCircuitStatuses.OPEN),
        (STIM_OPEN_CIRCUIT_THRESHOLD_OHMS - 1, StimulatorCircuitStatuses.MEDIA),
        (STIM_SHORT_CIRCUIT_THRESHOLD_OHMS + 1, StimulatorCircuitStatuses.MEDIA),
        (STIM_SHORT_CIRCUIT_THRESHOLD_OHMS, StimulatorCircuitStatuses.SHORT),
        (STIM_SHORT_CIRCUIT_THRESHOLD_OHMS - 1, StimulatorCircuitStatuses.SHORT),
        (0, StimulatorCircuitStatuses.SHORT),
        (-1, StimulatorCircuitStatuses.ERROR),
    ],
)
def test_convert_adc_readings_to_circuit_status__returns_correct_values(
    test_impedance, expected_status, mocker
):
    mocked_to_impedance = mocker.patch.object(
        serial_comm, "convert_adc_readings_to_impedance", autospec=True, return_value=test_impedance
    )
    # mocking convert_adc_readings_to_impedance so these values don't actually matter
    test_adc8 = randint(0, 0xFFFF)
    test_adc9 = randint(0, 0xFFFF)

    assert convert_adc_readings_to_circuit_status(test_adc8, test_adc9) == expected_status

    mocked_to_impedance.assert_called_once_with(test_adc8, test_adc9)


@pytest.mark.parametrize(
    "test_len", [SERIAL_COMM_STATUS_CODE_LENGTH_BYTES - 1, SERIAL_COMM_STATUS_CODE_LENGTH_BYTES + 1]
)
def test_convert_status_code_bytes_to_dict__raises_error_if_given_value_does_not_expected_length_exactly(
    test_len,
):
    test_bytes = bytes([randint(0, 255) for _ in range(test_len)])
    with pytest.raises(ValueError) as exc_info:
        convert_status_code_bytes_to_dict(test_bytes)
    assert (
        str(exc_info.value)
        == f"Status code bytes must have len of {SERIAL_COMM_STATUS_CODE_LENGTH_BYTES}, {test_len} bytes given: {test_bytes}"
    )


def test_convert_subprotocol_pulse_dict_to_bytes__returns_expected_bytes__for_voltage_controlled_monophasic_pulse():
    test_subprotocol_dict = {
        "type": "monophasic",
        "phase_one_duration": 0x654321,
        "phase_one_charge": 0x333,
        "postphase_interval": 0x3BA,
        "num_cycles": 0xFF,
    }
    # fmt: off
    expected_bytes = bytes(
        [
            0x21, 0x43, 0x65, 0,  # phase_one_duration
            0x33, 3,  # phase_one_charge
            0, 0, 0, 0,  # interphase_interval (always 0 for monophasic)
            0, 0,  # interphase_interval amplitude (always 0)
            0, 0, 0, 0,  # phase_two_duration (always 0 for monophasic)
            0, 0,  # phase_two_charge (always 0 for monophasic)
            0xBA, 3, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0xFF, 0, 0, 0,  # num_cycles
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_pulse_dict_to_bytes(test_subprotocol_dict, is_voltage=True)
    assert_subprotocol_bytes_are_expected(actual, expected_bytes)


def test_convert_subprotocol_pulse_dict_to_bytes__returns_expected_bytes__for_current_controlled_monophasic_pulse():
    test_subprotocol_dict = {
        "type": "monophasic",
        "phase_one_duration": 0x111,
        "phase_one_charge": 50,
        "postphase_interval": 0x6BF,
        "num_cycles": 0x12000034,
    }
    # fmt: off
    expected_bytes = bytes(
        [
            0x11, 1, 0, 0,  # phase_one_duration
            0x05, 0,  # phase_one_charge  # Tanner (11/15/22): this currently gets divided by 10
            0, 0, 0, 0,  # interphase_interval (always 0 for monophasic)
            0, 0,  # interphase_interval amplitude (always 0)
            0, 0, 0, 0,  # phase_two_duration (always 0 for monophasic)
            0, 0,  # phase_two_charge (always 0 for monophasic)
            0xBF, 6, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x34, 0, 0, 0x12,  # num_cycles
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_pulse_dict_to_bytes(test_subprotocol_dict)
    assert_subprotocol_bytes_are_expected(actual, expected_bytes)


def test_convert_subprotocol_pulse_dict_to_bytes__returns_expected_bytes__for_voltage_controlled_biphasic_pulse():
    test_subprotocol_dict = {
        "type": "biphasic",
        "phase_one_duration": 0x111,
        "phase_one_charge": 0x333,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x777,
        "phase_two_charge": -1,
        "postphase_interval": 0x993,
        "num_cycles": 0x432100,
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
            0x93, 9, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0, 0x21, 0x43, 0,  # num_cycles
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_pulse_dict_to_bytes(test_subprotocol_dict, is_voltage=True)
    assert_subprotocol_bytes_are_expected(actual, expected_bytes)


def test_convert_subprotocol_pulse_dict_to_bytes__returns_expected_bytes__for_current_controlled_biphasic_pulse():
    test_subprotocol_dict = {
        "type": "biphasic",
        "phase_one_duration": 0x111,
        "phase_one_charge": 50,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x777,
        "phase_two_charge": -50,
        "postphase_interval": 0x993,
        "num_cycles": 0xFFFFFFFF,
    }
    # fmt: off
    expected_bytes = bytes(
        [
            0x11, 1, 0, 0,  # phase_one_duration
            0x05, 0,  # phase_one_charge  # Tanner (11/15/22): this currently gets divided by 10
            0x55, 5, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0x77, 7, 0, 0,  # phase_two_duration
            0xFB, 0xFF,  # phase_two_charge  # Tanner (11/15/22): this currently gets divided by 10
            0x93, 9, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0xFF, 0xFF, 0xFF, 0xFF,  # num_cycles
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_pulse_dict_to_bytes(test_subprotocol_dict)
    assert_subprotocol_bytes_are_expected(actual, expected_bytes)


def test_convert_subprotocol_pulse_dict_to_bytes__returns_expected_bytes__when_subprotocol_is_a_delay():
    test_subprotocol_dict = {"type": "delay", "duration": 123000}
    # fmt: off
    expected_bytes = bytes(
        [
            0, 0, 0, 0,  # phase_one_duration (value is ignored when converting delay)
            0, 0,  # phase_one_charge
            0, 0, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0, 0, 0, 0,  # phase_two_duration
            0, 0,  # phase_two_charge
            0, 0, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x7B, 0, 0, 0,  # duration_ms
            1,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_pulse_dict_to_bytes(test_subprotocol_dict)
    assert_subprotocol_bytes_are_expected(actual, expected_bytes)


def test_convert_subprotocol_pulse_bytes_to_dict__returns_expected_dict__for_voltage_controlled_monophasic_pulse():
    # fmt: off
    test_bytes = bytes(
        [
            0x99, 9, 0, 0,  # phase_one_duration
            0x77, 7,  # phase_one_charge
            0, 0, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0, 0, 0, 0,  # phase_two_duration
            0, 0,  # phase_two_charge
            0x11, 1, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x7, 0, 0, 0,  # num_cycles
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    expected_subprotocol_dict = {
        "type": "monophasic",
        "phase_one_duration": 0x999,
        "phase_one_charge": 0x777,
        "postphase_interval": 0x111,
        "num_cycles": 0x7,
    }

    actual = convert_subprotocol_pulse_bytes_to_dict(test_bytes, is_voltage=True)
    assert actual == expected_subprotocol_dict


def test_convert_subprotocol_pulse_bytes_to_dict__returns_expected_dict__for_current_controlled_monophasic_pulse():
    # fmt: off
    test_bytes = bytes(
        [
            0xBF, 6, 0, 0,  # phase_one_duration
            0x77, 7,  # phase_one_charge
            0, 0, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0, 0, 0, 0,  # phase_two_duration
            0, 0,  # phase_two_charge
            0x11, 1, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x12, 0, 0, 0x34,  # num_cycles
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    expected_subprotocol_dict = {
        "type": "monophasic",
        "phase_one_duration": 0x6BF,
        "phase_one_charge": 0x777 * 10,
        "postphase_interval": 0x111,
        "num_cycles": 0x34000012,
    }

    actual = convert_subprotocol_pulse_bytes_to_dict(test_bytes)
    assert actual == expected_subprotocol_dict


def test_convert_subprotocol_pulse_bytes_to_dict__returns_expected_dict__for_voltage_controlled_biphasic_pulse():
    # fmt: off
    test_bytes = bytes(
        [
            0x93, 9, 0, 0,  # phase_one_duration
            0x77, 7,  # phase_one_charge
            0x55, 5, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0x33, 3, 0, 0,  # phase_two_duration
            0xFF, 0xFF,  # phase_two_charge
            0x11, 1, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0, 0x80, 0, 0x80,  # num_cycles
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    expected_subprotocol_dict = {
        "type": "biphasic",
        "phase_one_duration": 0x993,
        "phase_one_charge": 0x777,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x333,
        "phase_two_charge": -1,
        "postphase_interval": 0x111,
        "num_cycles": 0x80008000,
    }

    actual = convert_subprotocol_pulse_bytes_to_dict(test_bytes, is_voltage=True)
    assert actual == expected_subprotocol_dict


def test_convert_subprotocol_pulse_bytes_to_dict__returns_expected_dict__for_current_controlled_biphasic_pulse():
    # fmt: off
    test_bytes = bytes(
        [
            0x93, 9, 0, 0,  # phase_one_duration
            0x77, 7,  # phase_one_charge
            0x55, 5, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0x33, 3, 0, 0,  # phase_two_duration
            0xFF, 0xFF,  # phase_two_charge
            0x11, 1, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x21, 3, 0, 0,  # num_cycles
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    expected_subprotocol_dict = {
        "type": "biphasic",
        "phase_one_duration": 0x993,
        "phase_one_charge": 0x777 * 10,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x333,
        "phase_two_charge": -1 * 10,
        "postphase_interval": 0x111,
        "num_cycles": 0x321,
    }

    actual = convert_subprotocol_pulse_bytes_to_dict(test_bytes)
    assert actual == expected_subprotocol_dict


def test_convert_subprotocol_pulse_bytes_to_dict__returns_expected_dict__when_subprotocol_is_a_delay():
    # fmt: off
    test_bytes = bytes(
        [
            0, 0, 0, 0,  # phase_one_duration
            0, 0,  # phase_one_charge
            0, 0, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0, 0, 0, 0,  # phase_two_duration
            0, 0,  # phase_two_charge
            0, 0, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x41, 1, 0, 0,  # duration_ms
            1,  # is_null_subprotocol
        ]
    )
    # fmt: on
    expected_subprotocol_dict = {"type": "delay", "duration": 321000}

    actual = convert_subprotocol_pulse_bytes_to_dict(test_bytes)
    assert actual == expected_subprotocol_dict


@pytest.mark.parametrize(
    "test_pulse_fn", [get_random_biphasic_pulse, get_random_monophasic_pulse, get_random_stim_delay]
)
def test_convert_subprotocol_node_dict_to_bytes__returns_expected_bytes__when_node_is_a_pulse(test_pulse_fn):
    test_pulse_dict = test_pulse_fn()

    is_voltage = random_bool()

    expected_bytes = bytes([0])  # node_type
    expected_bytes += convert_subprotocol_pulse_dict_to_bytes(test_pulse_dict, is_voltage)

    actual = convert_subprotocol_node_dict_to_bytes(test_pulse_dict, is_voltage)
    assert_subprotocol_node_bytes_are_expected(actual, expected_bytes)


def test_convert_subprotocol_node_dict_to_bytes__returns_expected_bytes__when_node_is_a_single_level_loop():
    is_voltage = random_bool()

    test_num_repeats = randint(1, 0xFFFFFFFF)

    test_num_subprotocol_pulses = randint(1, 3)
    test_subprotocol_pulses = [get_random_stim_pulse() for _ in range(test_num_subprotocol_pulses)]

    test_loop_dict = {
        "type": "loop",
        "num_repeats": test_num_repeats,
        "subprotocols": test_subprotocol_pulses,
    }
    actual = convert_subprotocol_node_dict_to_bytes(test_loop_dict, is_voltage)

    expected_bytes = bytes([1])  # node_type
    expected_bytes += bytes([test_num_subprotocol_pulses])
    expected_bytes += test_num_repeats.to_bytes(4, byteorder="little")
    for test_pulse_dict in test_subprotocol_pulses:
        expected_bytes += bytes([0])  # node_type
        expected_bytes += convert_subprotocol_pulse_dict_to_bytes(test_pulse_dict, is_voltage)

    assert_subprotocol_node_bytes_are_expected(actual, expected_bytes)


def test_convert_subprotocol_node_dict_to_bytes__returns_expected_bytes__when_node_is_a_multi_level_loop():
    is_voltage = random_bool()

    test_num_repeats = [randint(1, 0xFFFFFFFF) for _ in range(4)]
    test_subprotocol_pulses = [get_random_stim_pulse() for _ in range(7)]
    test_num_subprotocol_nodes = [3, 2, 2, 3]

    test_num_repeats_iter = iter(test_num_repeats)
    test_subprotocol_pulses_iter = iter(test_subprotocol_pulses)

    test_loop_dict = {
        "type": "loop",
        "num_repeats": next(test_num_repeats_iter),
        "subprotocols": [
            next(test_subprotocol_pulses_iter),
            {
                "type": "loop",
                "num_repeats": next(test_num_repeats_iter),
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_repeats": next(test_num_repeats_iter),
                        "subprotocols": [next(test_subprotocol_pulses_iter) for _ in range(2)],
                    },
                    {
                        "type": "loop",
                        "num_repeats": next(test_num_repeats_iter),
                        "subprotocols": [next(test_subprotocol_pulses_iter) for _ in range(3)],
                    },
                ],
            },
            next(test_subprotocol_pulses_iter),
        ],
    }
    actual = convert_subprotocol_node_dict_to_bytes(test_loop_dict, is_voltage)

    test_num_repeats_iter = iter(test_num_repeats)
    test_subprotocol_pulses_iter = iter(test_subprotocol_pulses)
    test_num_subprotocol_nodes_iter = iter(test_num_subprotocol_nodes)

    # top level loop
    expected_bytes = (
        bytes([1])
        + bytes([next(test_num_subprotocol_nodes_iter)])
        + next(test_num_repeats_iter).to_bytes(4, byteorder="little")
    )
    expected_bytes += bytes([0]) + convert_subprotocol_pulse_dict_to_bytes(
        next(test_subprotocol_pulses_iter), is_voltage
    )
    # - level 1 loop
    expected_bytes += (
        bytes([1])
        + bytes([next(test_num_subprotocol_nodes_iter)])
        + next(test_num_repeats_iter).to_bytes(4, byteorder="little")
    )
    # - - first level 2 loop
    expected_bytes += (
        bytes([1])
        + bytes([next(test_num_subprotocol_nodes_iter)])
        + next(test_num_repeats_iter).to_bytes(4, byteorder="little")
    )
    for _ in range(2):
        expected_bytes += bytes([0]) + convert_subprotocol_pulse_dict_to_bytes(
            next(test_subprotocol_pulses_iter), is_voltage
        )
    # - - second level 2 loop
    expected_bytes += (
        bytes([1])
        + bytes([next(test_num_subprotocol_nodes_iter)])
        + next(test_num_repeats_iter).to_bytes(4, byteorder="little")
    )
    for _ in range(3):
        expected_bytes += bytes([0]) + convert_subprotocol_pulse_dict_to_bytes(
            next(test_subprotocol_pulses_iter), is_voltage
        )
    # back to top level
    expected_bytes += bytes([0]) + convert_subprotocol_pulse_dict_to_bytes(
        next(test_subprotocol_pulses_iter), is_voltage
    )

    assert actual == expected_bytes

    # TODO
    # assert_subprotocol_node_bytes_are_expected(actual, expected_bytes)


@pytest.mark.parametrize(
    "test_pulse_fn", [get_random_biphasic_pulse, get_random_monophasic_pulse, get_random_stim_delay]
)
def test_convert_subprotocol_node_bytes_to_dict__returns_expected_dict__when_node_is_a_pulse(test_pulse_fn):
    expected_pulse_dict = test_pulse_fn()

    is_voltage = random_bool()

    # Tanner (12/23/22): this test is also dependent on convert_subprotocol_node_dict_to_bytes working properly. If this test fails, make sure the tests for this func are passing first
    test_pulse_node_bytes = convert_subprotocol_node_dict_to_bytes(expected_pulse_dict, is_voltage)

    actual = convert_subprotocol_node_bytes_to_dict(test_pulse_node_bytes, is_voltage)
    assert actual == expected_pulse_dict


def test_convert_subprotocol_node_bytes_to_dict__returns_expected_dict__when_node_is_a_single_level_loop():
    is_voltage = random_bool()

    expected_loop_dict = {
        "type": "loop",
        "num_repeats": randint(1, 0xFFFFFFFF),
        "subprotocols": [get_random_stim_pulse() for _ in range(randint(1, 3))],
    }
    # Tanner (12/23/22): this test is also dependent on convert_subprotocol_node_dict_to_bytes working properly. If this test fails, make sure the tests for this func are passing first
    test_loop_node_bytes = convert_subprotocol_node_dict_to_bytes(expected_loop_dict, is_voltage)

    actual = convert_subprotocol_node_bytes_to_dict(test_loop_node_bytes, is_voltage)

    # pop these to make an assertion on the rest of the dict keys
    actual_subprotocol_node_dicts = actual.pop("subprotocols")
    expected_subprotocol_pulses = expected_loop_dict.pop("subprotocols")

    assert actual == expected_loop_dict

    assert len(actual_subprotocol_node_dicts) == len(expected_subprotocol_pulses)
    # make assertions on these individually
    for i, (actual_dict, expected_dict) in enumerate(
        zip(actual_subprotocol_node_dicts, expected_subprotocol_pulses)
    ):
        assert actual_dict == expected_dict, f"Subprotocol {i} incorrect"


def test_convert_subprotocol_node_bytes_to_dict__returns_expected_dict__when_node_is_a_multi_level_loop():
    is_voltage = random_bool()

    expected_top_level_loop = {
        "type": "loop",
        "num_repeats": randint(1, 0xFFFFFFFF),
        "subprotocols": [
            get_random_stim_pulse(),
            {
                "type": "loop",
                "num_repeats": randint(1, 0xFFFFFFFF),
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_repeats": randint(1, 0xFFFFFFFF),
                        "subprotocols": [get_random_stim_pulse() for _ in range(randint(1, 3))],
                    },
                    {
                        "type": "loop",
                        "num_repeats": randint(1, 0xFFFFFFFF),
                        "subprotocols": [get_random_stim_pulse() for _ in range(randint(1, 3))],
                    },
                ],
            },
            get_random_stim_pulse(),
        ],
    }
    # Tanner (12/23/22): this test is also dependent on convert_subprotocol_node_dict_to_bytes working properly. If this test fails, make sure the tests for this func are passing first
    test_loop_node_bytes = convert_subprotocol_node_dict_to_bytes(expected_top_level_loop, is_voltage)

    actual_top_level_loop = convert_subprotocol_node_bytes_to_dict(test_loop_node_bytes, is_voltage)

    # pop these to make an assertion on the rest of the dict keys
    actual_top_level_nodes = actual_top_level_loop.pop("subprotocols")
    expected_top_level_nodes = expected_top_level_loop.pop("subprotocols")

    assert actual_top_level_loop == expected_top_level_loop
    assert len(actual_top_level_nodes) == len(expected_top_level_nodes)
    # check pulses
    assert actual_top_level_nodes[0] == expected_top_level_nodes[0]
    assert actual_top_level_nodes[2] == expected_top_level_nodes[2]

    # level 1
    actual_level_1_loop = actual_top_level_nodes[1]
    expected_level_1_loop = expected_top_level_nodes[1]
    # pop these to make an assertion on the rest of the dict keys
    actual_level_1_nodes = actual_level_1_loop.pop("subprotocols")
    expected_level_1_nodes = expected_level_1_loop.pop("subprotocols")

    assert actual_level_1_loop == expected_level_1_loop
    assert len(actual_level_1_nodes) == len(expected_level_1_nodes)

    # level 2
    for loop_idx, (actual_loop, expected_loop) in enumerate(
        zip(actual_level_1_nodes, expected_level_1_nodes)
    ):
        # pop these to make an assertion on the rest of the dict keys
        actual_nodes = actual_loop.pop("subprotocols")
        expected_nodes = expected_loop.pop("subprotocols")

        assert actual_loop == expected_loop, f"loop dict {loop_idx} in level 2 incorrect"
        assert len(actual_nodes) == len(
            expected_nodes
        ), f"Incorrect num subprotocols in loop {loop_idx} of level 2"
        # check pulses
        for pulse_idx, (actual_pulse, expected_pulse) in enumerate(zip(actual_nodes, expected_nodes)):
            assert (
                actual_pulse == expected_pulse
            ), f"pulse {pulse_idx} of loop dict {loop_idx} in level 2 incorrect"


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
                        "type": "monophasic",
                        "phase_one_duration": randint(1, 50),
                        "phase_one_charge": randint(1, 100),
                        "postphase_interval": randint(0, 50),
                        "num_cycles": randint(1, 100),
                    },
                    {"type": "delay", "duration": 250},
                ],
            },
            {
                "protocol_id": "D",
                "stimulation_type": "V",
                "run_until_stopped": False,
                "subprotocols": [
                    {
                        "type": "biphasic",
                        "phase_one_duration": randint(1, 50),
                        "phase_one_charge": randint(1, 100),
                        "interphase_interval": randint(1, 50),
                        "phase_two_duration": randint(1, 100),
                        "phase_two_charge": randint(1, 50),
                        "postphase_interval": randint(0, 50),
                        "num_cycles": randint(1, 100),
                    },
                ],
            },
        ],
        "protocol_assignments": protocol_assignments_dict,
    }

    expected_bytes = (
        bytes([2])  # num unique protocols
        # bytes for protocol A
        + bytes([2])  # num subprotocols in protocol A
        + convert_subprotocol_pulse_dict_to_bytes(
            stim_info_dict["protocols"][0]["subprotocols"][0], is_voltage=False
        )
        + convert_subprotocol_pulse_dict_to_bytes(
            stim_info_dict["protocols"][0]["subprotocols"][1], is_voltage=False
        )
        + bytes([0])  # control method
        + bytes([1])  # schedule mode
        + bytes(1)  # data type
        # bytes for protocol D
        + bytes([1])  # num subprotocols in protocol B
        + convert_subprotocol_pulse_dict_to_bytes(
            stim_info_dict["protocols"][1]["subprotocols"][0], is_voltage=True
        )
        + bytes([1])  # control method
        + bytes([0])  # schedule mode
        + bytes(1)  # data type
        # module/protocol pairs
        + bytes(expected_module_protocol_pairs)
    )

    actual = convert_stim_dict_to_bytes(stim_info_dict)
    assert actual == expected_bytes


def test_chunk_protocols_in_stim_info__returns_correct_values():
    test_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": random_stim_type(),
                "run_until_stopped": random_bool(),
                "subprotocols": [
                    # this will run for one cycle longer a full chunk, so will be split into two chunks
                    {
                        "type": "monophasic",
                        "phase_one_duration": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 6,
                        "phase_one_charge": randint(1, 10),
                        "postphase_interval": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 6,
                        "num_cycles": 4,
                    },
                    # this will run for exactly the max length of a chunk, so shouldn't be modified at all
                    {
                        "type": "biphasic",
                        "phase_one_duration": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 8,
                        "phase_one_charge": randint(1, 10),
                        "interphase_interval": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 8,
                        "phase_two_duration": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 8,
                        "phase_two_charge": randint(1, 10),
                        "postphase_interval": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 8,
                        "num_cycles": 2,
                    },
                ],
            },
            {
                "protocol_id": "B",
                "stimulation_type": random_stim_type(),
                "run_until_stopped": random_bool(),
                "subprotocols": [
                    # this will run for exactly the max length of a chunk, so shouldn't be modified at all
                    {
                        "type": "monophasic",
                        "phase_one_duration": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 2,
                        "phase_one_charge": randint(1, 10),
                        "postphase_interval": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 2,
                        "num_cycles": 1,
                    },
                    # delays don't need to be chunked, so this shouldn't be modified at all
                    {"type": "delay", "duration": STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS},
                    # this will run for two cycles longer than two full chunks, so will be split into three chunks
                    {
                        "type": "biphasic",
                        "phase_one_duration": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 10,
                        "phase_one_charge": randint(1, 10),
                        "interphase_interval": 0,
                        "phase_two_duration": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 10,
                        "phase_two_charge": randint(1, 10),
                        "postphase_interval": STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // 10,
                        "num_cycles": 8,
                    },
                ],
            },
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", "B"])
            for well_idx in range(24)
        },
    }

    expected_chunked_stim_info = copy.deepcopy(test_stim_info)
    expected_chunked_stim_info["protocols"][0]["subprotocols"] = [
        {**test_stim_info["protocols"][0]["subprotocols"][0], "num_cycles": 3},
        {**test_stim_info["protocols"][0]["subprotocols"][0], "num_cycles": 1},
        test_stim_info["protocols"][0]["subprotocols"][1],
    ]
    expected_chunked_stim_info["protocols"][1]["subprotocols"] = [
        test_stim_info["protocols"][1]["subprotocols"][0],
        test_stim_info["protocols"][1]["subprotocols"][1],
        {**test_stim_info["protocols"][1]["subprotocols"][2], "num_cycles": 3},
        {**test_stim_info["protocols"][1]["subprotocols"][2], "num_cycles": 3},
        {**test_stim_info["protocols"][1]["subprotocols"][2], "num_cycles": 2},
    ]

    actual_stim_info, subprotocol_idx_mappings = chunk_protocols_in_stim_info(test_stim_info)

    # test chunked protocol
    for protocol_idx, (actual_protocol, expected_protocol) in enumerate(
        itertools.zip_longest(actual_stim_info.pop("protocols"), expected_chunked_stim_info.pop("protocols"))
    ):
        for subprotocol_idx, (actual_subprotocol, expected_subprotocol) in enumerate(
            itertools.zip_longest(actual_protocol.pop("subprotocols"), expected_protocol.pop("subprotocols"))
        ):
            assert (
                actual_subprotocol == expected_subprotocol
            ), f"Protocol {protocol_idx}, Subprotocol {subprotocol_idx}"

        # make sure the rest of the protocol wasn't changed
        assert actual_protocol == expected_protocol, f"Protocol {protocol_idx}"

    # make sure other stim info wasn't changed
    assert actual_stim_info == expected_chunked_stim_info

    # test mapping
    assert subprotocol_idx_mappings == {"A": {0: 0, 1: 0, 2: 1}, "B": {0: 0, 1: 1, 2: 2, 3: 2, 4: 2}}
