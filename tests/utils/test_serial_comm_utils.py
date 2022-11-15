# -*- coding: utf-8 -*-
import datetime
from random import randint
from zlib import crc32

from freezegun import freeze_time
from mantarray_desktop_app import convert_bytes_to_subprotocol_dict
from mantarray_desktop_app import convert_status_code_bytes_to_dict
from mantarray_desktop_app import convert_stim_dict_to_bytes
from mantarray_desktop_app import convert_subprotocol_dict_to_bytes
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
from mantarray_desktop_app.constants import STIM_OPEN_CIRCUIT_THRESHOLD_OHMS
from mantarray_desktop_app.constants import STIM_SHORT_CIRCUIT_THRESHOLD_OHMS
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
from mantarray_desktop_app.utils import serial_comm
from mantarray_desktop_app.utils.serial_comm import convert_adc_readings_to_circuit_status
from mantarray_desktop_app.utils.serial_comm import convert_adc_readings_to_impedance
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


def test_convert_subprotocol_dict_to_bytes__returns_expected_bytes__for_voltage_controlled_monophasic_pulse():
    test_subprotocol_dict = {
        "type": "monophasic",
        "phase_one_duration": 0x321,
        "phase_one_charge": 0x333,
        "postphase_interval": 0x123,
    }
    # fmt: off
    expected_bytes = bytes(
        [
            0x21, 3, 0, 0,  # phase_one_duration
            0x33, 3,  # phase_one_charge
            0, 0, 0, 0,  # interphase_interval (always 0 for monophasic)
            0, 0,  # interphase_interval amplitude (always 0)
            0, 0, 0, 0,  # phase_two_duration (always 0 for monophasic)
            0, 0,  # phase_two_charge (always 0 for monophasic)
            0x12, 3, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x34, 0x12, 0, 0,  # total_active_duration
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_dict_to_bytes(test_subprotocol_dict, is_voltage=True)
    assert actual == expected_bytes


def test_convert_subprotocol_dict_to_bytes__returns_expected_bytes__for_current_controlled_monophasic_pulse():
    test_subprotocol_dict = {
        "type": "monophasic",
        "phase_one_duration": 0x111,
        "phase_one_charge": 50,
        "postphase_interval": 0x999,
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
            0x99, 9, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x34, 0x12, 0, 0,  # total_active_duration
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_dict_to_bytes(test_subprotocol_dict)
    assert actual == expected_bytes


def test_convert_subprotocol_dict_to_bytes__returns_expected_bytes__for_voltage_controlled_biphasic_pulse():
    test_subprotocol_dict = {
        "type": "biphasic",
        "phase_one_duration": 0x111,
        "phase_one_charge": 0x333,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x777,
        "phase_two_charge": -1,
        "postphase_interval": 0x999,
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
            0x99, 9, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x34, 0x12, 0, 0,  # total_active_duration
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_dict_to_bytes(test_subprotocol_dict, is_voltage=True)
    assert actual == expected_bytes


def test_convert_subprotocol_dict_to_bytes__returns_expected_bytes__for_current_controlled_biphasic_pulse():
    test_subprotocol_dict = {
        "type": "biphasic",
        "phase_one_duration": 0x111,
        "phase_one_charge": 50,
        "interphase_interval": 0x555,
        "phase_two_duration": 0x777,
        "phase_two_charge": -50,
        "postphase_interval": 0x999,
        "total_active_duration": 0x1234,
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
            0x99, 9, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
            0x34, 0x12, 0, 0,  # total_active_duration
            0,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_dict_to_bytes(test_subprotocol_dict)
    assert actual == expected_bytes


def test_convert_subprotocol_dict_to_bytes__returns_expected_bytes__when_subprotocol_is_a_delay():
    test_subprotocol_dict = {"type": "delay", "duration": 0x111}
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
            0x11, 1, 0, 0,  # total_active_duration
            1,  # is_null_subprotocol
        ]
    )
    # fmt: on
    actual = convert_subprotocol_dict_to_bytes(test_subprotocol_dict)
    assert actual == expected_bytes


def test_convert_bytes_to_subprotocol_dict__returns_expected_dict__for_voltage_controlled_biphasic_pulse():
    # fmt: off
    test_bytes = bytes(
        [
            0x99, 9, 0, 0,  # phase_one_duration
            0x77, 7,  # phase_one_charge
            0x55, 5, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0x33, 3, 0, 0,  # phase_two_duration
            0xFF, 0xFF,  # phase_two_charge
            0x11, 1, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
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
        "postphase_interval": 0x111,
        "total_active_duration": 0x4321,
    }

    actual = convert_bytes_to_subprotocol_dict(test_bytes, is_voltage=True)
    assert actual == expected_subprotocol_dict


def test_convert_bytes_to_subprotocol_dict__returns_expected_dict__for_current_controlled_biphasic_pulse():
    # fmt: off
    test_bytes = bytes(
        [
            0x99, 9, 0, 0,  # phase_one_duration
            0x77, 7,  # phase_one_charge
            0x55, 5, 0, 0,  # interphase_interval
            0, 0,  # interphase_interval amplitude (always 0)
            0x33, 3, 0, 0,  # phase_two_duration
            0xFF, 0xFF,  # phase_two_charge
            0x11, 1, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
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
        "postphase_interval": 0x111,
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
            0, 0, 0, 0,  # postphase_interval
            0, 0,  # postphase_interval amplitude (always 0)
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
        "postphase_interval": 0,
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
                        "postphase_interval": randint(0, 50),
                        "total_active_duration": randint(150, 300),
                    },
                    {
                        "phase_one_duration": 250,
                        "phase_one_charge": 0,
                        "interphase_interval": 0,
                        "phase_two_duration": 0,
                        "phase_two_charge": 0,
                        "postphase_interval": 0,
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
                        "postphase_interval": randint(0, 50),
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
