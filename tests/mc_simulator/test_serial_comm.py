# -*- coding: utf-8 -*-
import random
from random import randint
from zlib import crc32

from mantarray_desktop_app import convert_to_status_code_bytes
from mantarray_desktop_app import convert_to_timestamp_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import create_magnetometer_config_bytes
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_BOOT_UP_CODE
from mantarray_desktop_app import SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_COMMAND_FAILURE_BYTE
from mantarray_desktop_app import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_COMMAND_SUCCESS_BYTE
from mantarray_desktop_app import SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_FATAL_ERROR_CODE
from mantarray_desktop_app import SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_GET_METADATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_IDLE_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from mantarray_desktop_app import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_REBOOT_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import SERIAL_COMM_SET_NICKNAME_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_SET_TIME_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_TIME_SYNC_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SerialCommTooManyMissedHandshakesError
from mantarray_desktop_app import UnrecognizedSerialCommPacketTypeError
from mantarray_desktop_app.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app.mc_simulator import MC_SIMULATOR_BOOT_UP_DURATION_SECONDS
from mantarray_desktop_app.serial_comm_utils import convert_metadata_to_bytes
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import DEFAULT_SIMULATOR_STATUS_CODE
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import HANDSHAKE_RESPONSE_SIZE_BYTES
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..fixtures_mc_simulator import STATUS_BEACON_SIZE_BYTES
from ..fixtures_mc_simulator import TEST_HANDSHAKE
from ..fixtures_mc_simulator import TEST_HANDSHAKE_TIMESTAMP
from ..helpers import assert_serial_packet_is_expected
from ..helpers import get_full_packet_size_from_packet_body_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_patch_print,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_MantarrayMcSimulator__makes_status_beacon_available_to_read_on_first_iteration__with_random_truncation(
    mantarray_mc_simulator, mocker
):
    spied_randint = mocker.spy(random, "randint")

    simulator = mantarray_mc_simulator["simulator"]

    expected_cms_since_init = 0
    mocker.patch.object(
        simulator,
        "get_cms_since_init",
        autospec=True,
        return_value=expected_cms_since_init,
    )

    expected_initial_beacon = create_data_packet(
        expected_cms_since_init, SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, DEFAULT_SIMULATOR_STATUS_CODE
    )
    expected_randint_upper_bound = len(expected_initial_beacon) - 1

    invoke_process_run_and_check_errors(simulator)
    spied_randint.assert_called_once_with(0, expected_randint_upper_bound)

    actual = simulator.read(size=len(expected_initial_beacon[spied_randint.spy_return :]))
    assert actual == expected_initial_beacon[spied_randint.spy_return :]


def test_MantarrayMcSimulator__makes_status_beacon_available_to_read_every_5_seconds__and_includes_correct_timestamp_before_time_is_synced(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]

    expected_durs = [
        0,
        MICRO_TO_BASE_CONVERSION * SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS,
        MICRO_TO_BASE_CONVERSION * SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS * 2 + 1,
    ]
    mocker.patch.object(simulator, "get_cms_since_init", autospec=True, side_effect=expected_durs)
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_status_beacon",
        autospec=True,
        side_effect=[
            1,
            SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS,
            SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS - 1,
            SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS + 1,
        ],
    )

    # remove boot up beacon
    invoke_process_run_and_check_errors(simulator)
    simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    # 1 second since previous beacon
    invoke_process_run_and_check_errors(simulator)
    # 5 seconds since previous beacon
    invoke_process_run_and_check_errors(simulator)
    expected_beacon_1 = create_data_packet(
        expected_durs[1] * MICROSECONDS_PER_CENTIMILLISECOND,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    assert simulator.read(size=len(expected_beacon_1)) == expected_beacon_1
    # 4 seconds since previous beacon
    invoke_process_run_and_check_errors(simulator)
    # 6 seconds since previous beacon
    invoke_process_run_and_check_errors(simulator)
    expected_beacon_2 = create_data_packet(
        expected_durs[2] * MICROSECONDS_PER_CENTIMILLISECOND,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    assert simulator.read(size=len(expected_beacon_2)) == expected_beacon_2


def test_MantarrayMcSimulator__raises_error_if_unrecognized_packet_type_sent_from_pc(
    mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    dummy_timestamp = 0
    test_packet_type = 254
    test_handshake = create_data_packet(dummy_timestamp, test_packet_type, DEFAULT_SIMULATOR_STATUS_CODE)

    simulator.write(test_handshake)
    with pytest.raises(UnrecognizedSerialCommPacketTypeError) as exc_info:
        invoke_process_run_and_check_errors(simulator)
    assert str(test_packet_type) in str(exc_info.value)


def test_MantarrayMcSimulator__responds_to_handshake__when_checksum_is_correct(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    actual = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)

    assert_serial_packet_is_expected(
        actual,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        TEST_HANDSHAKE_TIMESTAMP.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little")
        + DEFAULT_SIMULATOR_STATUS_CODE,
    )


def test_MantarrayMcSimulator__responds_to_comm_from_pc__when_checksum_is_incorrect(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    dummy_timestamp_bytes = bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    dummy_checksum_bytes = bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES)
    handshake_packet_length = 14
    test_handshake = (
        SERIAL_COMM_MAGIC_WORD_BYTES
        + handshake_packet_length.to_bytes(SERIAL_COMM_PACKET_INFO_LENGTH_BYTES, byteorder="little")
        + dummy_timestamp_bytes
        + bytes([SERIAL_COMM_HANDSHAKE_PACKET_TYPE])
        + dummy_checksum_bytes
    )
    simulator.write(test_handshake)
    invoke_process_run_and_check_errors(simulator)

    expected_packet_body = test_handshake[len(SERIAL_COMM_MAGIC_WORD_BYTES) :]
    expected_size = get_full_packet_size_from_packet_body_size(len(expected_packet_body))
    actual = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(actual, SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE, expected_packet_body)


def test_MantarrayMcSimulator__discards_commands_from_pc_during_reboot_period__and_sends_reboot_response_packet_before_reboot__and_sends_status_beacon_after_reboot(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]

    spied_randint = mocker.spy(random, "randint")

    reboot_times = [
        AVERAGE_MC_REBOOT_DURATION_SECONDS - 1,
        AVERAGE_MC_REBOOT_DURATION_SECONDS,
    ]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        side_effect=reboot_times,
    )

    spied_reset = mocker.spy(simulator, "_reset_start_time")

    # remove initial status beacon
    invoke_process_run_and_check_errors(simulator)
    initial_status_beacon_length = STATUS_BEACON_SIZE_BYTES - spied_randint.spy_return
    initial_status_beacon = simulator.read(size=initial_status_beacon_length)
    assert len(initial_status_beacon) == initial_status_beacon_length

    # send reboot command
    expected_timestamp = 0
    test_reboot_command = create_data_packet(
        expected_timestamp, SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE, bytes([SERIAL_COMM_REBOOT_COMMAND_BYTE])
    )
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)

    # test that reboot response packet is sent
    reboot_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    )
    assert_serial_packet_is_expected(
        reboot_response,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        expected_timestamp.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"),
    )

    # test that handshake is ignored
    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    response_during_reboot = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)
    assert len(response_during_reboot) == 0

    # test that status beacon is sent after reboot
    invoke_process_run_and_check_errors(simulator)
    status_beacon = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert_serial_packet_is_expected(
        status_beacon,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        SERIAL_COMM_IDLE_READY_CODE.to_bytes(SERIAL_COMM_STATUS_CODE_LENGTH_BYTES, byteorder="little"),
    )

    # test that start time was reset
    spied_reset.assert_called_once()


def test_MantarrayMcSimulator__does_not_send_status_beacon_while_rebooting(mantarray_mc_simulator, mocker):
    simulator = mantarray_mc_simulator["simulator"]

    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_status_beacon",
        autospec=True,
        side_effect=[0, SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS],
    )

    # remove boot up beacon
    invoke_process_run_and_check_errors(simulator)
    simulator.read(size=STATUS_BEACON_SIZE_BYTES)

    # send reboot command
    expected_timestamp = 1
    test_reboot_command = create_data_packet(
        expected_timestamp, SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE, bytes([SERIAL_COMM_REBOOT_COMMAND_BYTE])
    )
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)
    # remove reboot response packet
    invoke_process_run_and_check_errors(simulator)
    reboot_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    )
    assert_serial_packet_is_expected(
        reboot_response,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        expected_timestamp.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"),
    )

    # check status beacon was not sent
    invoke_process_run_and_check_errors(simulator)
    actual_beacon_packet = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert actual_beacon_packet == bytes(0)


def test_MantarrayMcSimulator__allows_mantarray_nickname_to_be_set_by_command_received_from_pc__and_sends_correct_response(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # mock so that simulator will complete reboot on the next iteration
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        return_value=AVERAGE_MC_REBOOT_DURATION_SECONDS,
    )

    expected_nickname = "NewerNickname"
    expected_timestamp = SERIAL_COMM_MAX_TIMESTAMP_VALUE
    set_nickname_command = create_data_packet(
        expected_timestamp, SERIAL_COMM_SET_NICKNAME_PACKET_TYPE, bytes(expected_nickname, "utf-8")
    )
    simulator.write(set_nickname_command)
    invoke_process_run_and_check_errors(simulator)

    # check that simulator is rebooting
    assert simulator.is_rebooting() is True
    # run one iteration to complete reboot, send packet, then start next reboot
    invoke_process_run_and_check_errors(simulator)
    # check that nickname is updated
    assert simulator.get_metadata_dict()[MANTARRAY_NICKNAME_UUID] == expected_nickname
    # check that correct response is sent
    expected_response_size = get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    actual = simulator.read(size=expected_response_size)
    assert_serial_packet_is_expected(actual, SERIAL_COMM_SET_NICKNAME_PACKET_TYPE)
    # make sure simulator is rebooting again again
    assert simulator.is_rebooting() is True
    # run one more iteration to complete reboot
    invoke_process_run_and_check_errors(simulator)
    assert simulator.is_rebooting() is False


def test_MantarrayMcSimulator__processes_get_metadata_command(mantarray_mc_simulator_no_beacon, mocker):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    get_metadata_command = create_data_packet(expected_timestamp, SERIAL_COMM_GET_METADATA_PACKET_TYPE)
    simulator.write(get_metadata_command)
    invoke_process_run_and_check_errors(simulator)

    expected_metadata_bytes = convert_metadata_to_bytes(MantarrayMcSimulator.default_metadata_values)
    expected_size = get_full_packet_size_from_packet_body_size(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + len(expected_metadata_bytes)
    )
    actual = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        actual,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        expected_timestamp.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little")
        + expected_metadata_bytes,
    )


def test_MantarrayMcSimulator__raises_error_if_too_many_consecutive_handshake_periods_missed_from_pc__after_first_handshake_received(
    mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_handshake",
        autospec=True,
        side_effect=[
            0,
            SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS * SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES - 1,
            SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS * SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES,
        ],
    )

    # make sure error isn't raised before initial handshake received
    invoke_process_run_and_check_errors(simulator)
    # send and process first handshake
    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    # make sure error isn't raised 1 second before final handshake missed
    invoke_process_run_and_check_errors(simulator)
    # make sure error is raised when final handshake missed
    with pytest.raises(SerialCommTooManyMissedHandshakesError):
        invoke_process_run_and_check_errors(simulator)


def test_MantarrayMcSimulator__switches_to_time_sync_status_code_after_boot_up_period__and_automatically_sends_beacon_after_status_code_update(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_boot_up",
        autospec=True,
        side_effect=[0, MC_SIMULATOR_BOOT_UP_DURATION_SECONDS],
    )

    # remove initial beacon
    invoke_process_run_and_check_errors(simulator)
    simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    # run simulator to complete boot up
    invoke_process_run_and_check_errors(simulator)
    # check that status beacon is automatically sent with updated status code
    actual = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert_serial_packet_is_expected(
        actual,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        convert_to_status_code_bytes(SERIAL_COMM_TIME_SYNC_READY_CODE),
    )


def test_MantarrayMcSimulator__switches_from_idle_ready_status_to_magic_word_timeout_status_if_magic_word_not_detected_within_timeout_period(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_comm_from_pc",
        autospec=True,
        side_effect=[
            SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS - 1,
            SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS,
        ],
    )

    test_command = {
        "command": "set_status_code",
        "status_code": SERIAL_COMM_IDLE_READY_CODE,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    simulator.write(TEST_HANDSHAKE)
    # confirm idle ready and process handshake
    invoke_process_run_and_check_errors(simulator, num_iterations=2)
    assert simulator.get_status_code() == SERIAL_COMM_IDLE_READY_CODE
    # confirm magic word timeout
    invoke_process_run_and_check_errors(simulator)
    assert simulator.get_status_code() == SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE


@pytest.mark.parametrize(
    "test_code,test_description",
    [
        (SERIAL_COMM_BOOT_UP_CODE, "does not switch status code when booting up"),
        (
            SERIAL_COMM_TIME_SYNC_READY_CODE,
            "does not switch status code when waiting for time sync",
        ),
    ],
)
def test_MantarrayMcSimulator__does_not_switch_to_magic_word_timeout_status_before_time_is_synced(
    test_code, test_description, mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_comm_from_pc",
        autospec=True,
        side_effect=[SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS],
    )

    test_command = {
        "command": "set_status_code",
        "status_code": test_code,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    simulator.write(TEST_HANDSHAKE)
    # confirm test status code
    invoke_process_run_and_check_errors(simulator)
    assert simulator.get_status_code() == test_code
    # confirm status code did not change
    invoke_process_run_and_check_errors(simulator)
    assert simulator.get_status_code() == test_code


def test_MantarrayMcSimulator__processes_set_time_command(mantarray_mc_simulator, mocker):
    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]

    # put simulator in time sync ready state before syncing time
    test_command = {
        "command": "set_status_code",
        "status_code": SERIAL_COMM_TIME_SYNC_READY_CODE,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    invoke_process_run_and_check_errors(simulator)
    # remove initial beacon
    simulator.read(size=STATUS_BEACON_SIZE_BYTES)

    # mock here to avoid interference from previous iteration calling method
    expected_command_response_time_us = 111111
    expected_status_beacon_time_us = 222222
    mocker.patch.object(
        simulator,
        "_get_us_since_time_sync",
        autospec=True,
        side_effect=[
            expected_command_response_time_us,
            expected_status_beacon_time_us,
            0,  # dummy val
        ],
    )

    # send set time command
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_set_time_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_SET_TIME_COMMAND_BYTE]) + convert_to_timestamp_bytes(expected_pc_timestamp),
    )
    simulator.write(test_set_time_command)
    invoke_process_run_and_check_errors(simulator)

    # test that command response uses updated timestamp
    command_response_size = get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    command_response = simulator.read(size=command_response_size)
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp),
        timestamp=(expected_pc_timestamp + expected_command_response_time_us),
    )
    # test that status beacon is automatically sent after command response with status code updated to idle ready and correct timestamp
    status_beacon = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert_serial_packet_is_expected(
        status_beacon,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        additional_bytes=convert_to_status_code_bytes(SERIAL_COMM_IDLE_READY_CODE),
        timestamp=(expected_pc_timestamp + expected_status_beacon_time_us),
    )


def test_MantarrayMcSimulator__when_in_fatal_error_state__does_not_respond_to_commands_or_send_any_packets(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    mocker.patch.object(  # patch so simulator will always think it is ready to send status beacon
        mc_simulator,
        "_get_secs_since_last_status_beacon",
        autospec=True,
        return_value=SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS,
    )

    # put simulator in fatal error state
    test_command = {
        "command": "set_status_code",
        "status_code": SERIAL_COMM_FATAL_ERROR_CODE,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    # send a handshake
    simulator.write(TEST_HANDSHAKE)
    # run simulator to make sure the only data packet sent back to PC is a status beacon
    invoke_process_run_and_check_errors(simulator)
    status_beacon_size = get_full_packet_size_from_packet_body_size(SERIAL_COMM_STATUS_CODE_LENGTH_BYTES)
    status_beacon = simulator.read(size=status_beacon_size)
    assert_serial_packet_is_expected(
        status_beacon,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        additional_bytes=convert_to_status_code_bytes(SERIAL_COMM_FATAL_ERROR_CODE),
    )
    assert simulator.in_waiting == 0


def test_MantarrayMcSimulator__processes_start_data_streaming_command(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    mocker.patch.object(  # patch so no data packets will be sent
        mc_simulator, "_get_us_since_last_data_packet", autospec=True, return_value=0
    )
    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    # set arbitrary sampling period
    expected_sampling_period = 11000
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_sampling_period", "sampling_period": expected_sampling_period}, testing_queue
    )

    # need to send command once before data is being streamed and once after to test the response in both cases
    for response_byte_value in (
        SERIAL_COMM_COMMAND_SUCCESS_BYTE,
        SERIAL_COMM_COMMAND_FAILURE_BYTE,
    ):
        # send start streaming command
        expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
        test_start_data_streaming_command = create_data_packet(
            expected_pc_timestamp,
            SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
            bytes([SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE]),
        )
        simulator.write(test_start_data_streaming_command)
        invoke_process_run_and_check_errors(simulator)
        # assert response is correct
        additional_bytes = convert_to_timestamp_bytes(expected_pc_timestamp) + bytes([response_byte_value])
        if response_byte_value == SERIAL_COMM_COMMAND_SUCCESS_BYTE:
            additional_bytes += spied_global_timer.spy_return.to_bytes(8, byteorder="little")
            additional_bytes += expected_sampling_period.to_bytes(2, byteorder="little")
            additional_bytes += create_magnetometer_config_bytes(simulator.get_magnetometer_config())
        command_response_size = get_full_packet_size_from_packet_body_size(len(additional_bytes))
        command_response = simulator.read(size=command_response_size)
        assert_serial_packet_is_expected(
            command_response, SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE, additional_bytes=additional_bytes
        )


def test_MantarrayMcSimulator__processes_stop_data_streaming_command(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    mocker.patch.object(  # patch so no data packets will be sent
        mc_simulator, "_get_us_since_last_data_packet", autospec=True, return_value=0
    )

    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    # set arbitrary sampling period
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_sampling_period", "sampling_period": 2000}, testing_queue
    )

    dummy_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_start_data_streaming_command = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE]),
    )
    simulator.write(test_start_data_streaming_command)
    invoke_process_run_and_check_errors(simulator)
    # remove start data streaming response
    command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(
            SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
            + 11  # 1 for response byte, 2 for sampling period bytes, 8 for global timer bytes
            + len(create_magnetometer_config_bytes(simulator.get_magnetometer_config()))
        )
    )

    # need to send command once while data is being streamed and once after it stops to test the response in both cases
    for response_byte_value in (
        SERIAL_COMM_COMMAND_SUCCESS_BYTE,
        SERIAL_COMM_COMMAND_FAILURE_BYTE,
    ):
        # send stop streaming command
        expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
        test_stop_data_streaming_command = create_data_packet(
            expected_pc_timestamp,
            SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
            bytes([SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE]),
        )
        simulator.write(test_stop_data_streaming_command)
        invoke_process_run_and_check_errors(simulator)
        # assert response is correct
        command_response_size = get_full_packet_size_from_packet_body_size(
            SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1
        )
        command_response = simulator.read(size=command_response_size)
        assert_serial_packet_is_expected(
            command_response,
            SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
            additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp) + bytes([response_byte_value]),
        )


def test_MantarrayMcSimulator__processes_change_magnetometer_config_command__when_data_is_not_streaming(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # assert that sampling period has not been set
    assert simulator.get_sampling_period_us() == 0
    assert simulator.get_magnetometer_config() == MantarrayMcSimulator.default_24_well_magnetometer_config
    # set arbitrary configuration values
    expected_config_dict = dict(MantarrayMcSimulator.default_24_well_magnetometer_config)
    expected_config_dict[1] = {
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Y"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Z"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["X"]: False,
        # pylint: disable=duplicate-code
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Y"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Z"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["X"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Y"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: False,
    }
    magnetometer_config_bytes = create_magnetometer_config_bytes(expected_config_dict)
    # send command to set magnetometer configuration
    expected_sampling_period = 1000
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    change_config_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE])
        + expected_sampling_period.to_bytes(2, byteorder="little")
        + magnetometer_config_bytes,
    )
    simulator.write(change_config_command)
    # process command to update configuration and send response
    invoke_process_run_and_check_errors(simulator)
    # assert command response is correct
    command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
        + bytes([SERIAL_COMM_COMMAND_SUCCESS_BYTE]),
    )
    # assert that sampling period and configuration are updated
    assert simulator.get_sampling_period_us() == expected_sampling_period
    assert simulator.get_magnetometer_config() == expected_config_dict


def test_MantarrayMcSimulator__processes_change_magnetometer_config_command__when_data_is_streaming(
    mantarray_mc_simulator_no_beacon, mocker
):
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    mocker.patch.object(  # patch so no data packets will be sent
        mc_simulator, "_get_us_since_last_data_packet", autospec=True, return_value=0
    )

    # enable data streaming
    test_sampling_period = 3000
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "set_data_streaming_status",
            "data_streaming_status": True,
            "sampling_period": test_sampling_period,
        },
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    # set arbitrary configuration values
    expected_config_dict = dict(MantarrayMcSimulator.default_24_well_magnetometer_config)
    expected_config_dict[4] = {
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Y"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Z"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["X"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Y"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Z"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["X"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Y"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: False,
    }
    magnetometer_config_bytes = create_magnetometer_config_bytes(expected_config_dict)
    # send command to set magnetometer configuration
    ignored_sampling_period = 1000
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    change_config_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE])
        + ignored_sampling_period.to_bytes(2, byteorder="little")
        + magnetometer_config_bytes,
    )
    simulator.write(change_config_command)
    # process command and return response
    invoke_process_run_and_check_errors(simulator)
    # assert command response is correct
    command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
        + bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )
    # assert that sampling period and configuration are unchanged
    assert simulator.get_sampling_period_us() == test_sampling_period
    updated_magnetometer_config = simulator.get_magnetometer_config()
    assert updated_magnetometer_config == MantarrayMcSimulator.default_24_well_magnetometer_config

    simulator.hard_stop()  # prevent BrokenPipeErrors


@pytest.mark.parametrize("firmware_type", [0, 1, 2])
def test_MantarrayMcSimulator__processes_begin_firmware_update_command__when_not_already_updating_firmware(
    mantarray_mc_simulator_no_beacon, firmware_type
):
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    begin_firmware_update_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
        bytes([firmware_type])
        + randint(1, 0xFFFFFFFF).to_bytes(4, byteorder="little"),  # arbitrary non-zero value
    )
    simulator.write(begin_firmware_update_command)
    # process command and return response
    invoke_process_run_and_check_errors(simulator)
    # assert command response is correct
    command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    expected_success_value = int(firmware_type not in (0, 1))
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp) + bytes([expected_success_value]),
    )


def test_MantarrayMcSimulator__processes_begin_firmware_update_command__when_already_updating_firmware(
    mantarray_mc_simulator_no_beacon,
):
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    for success_failure_byte_value in range(2):
        expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
        firmware_type = randint(0, 1)
        begin_firmware_update_command = create_data_packet(
            expected_pc_timestamp,
            SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
            bytes([firmware_type])
            + randint(1, 0xFFFFFFFF).to_bytes(4, byteorder="little"),  # arbitrary non-zero value
        )
        simulator.write(begin_firmware_update_command)
        # process command and return response
        invoke_process_run_and_check_errors(simulator)
        # assert command response is correct
        command_response = simulator.read(
            size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
        )
        assert_serial_packet_is_expected(
            command_response,
            SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
            additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
            + bytes([success_failure_byte_value]),
        )


def test_MantarrayMcSimulator__processes_successful_firmware_update_packet(
    mantarray_mc_simulator_no_beacon,
):
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_firmware_len = randint(
        SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES,
        int(SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES * 1.5),
    )
    begin_firmware_update_command = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
        bytes([randint(0, 1)]) + expected_firmware_len.to_bytes(4, byteorder="little"),
    )
    simulator.write(begin_firmware_update_command)
    # process command and return response
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()

    # send two firmware update packets
    packet_body_sizes = (
        SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES - 1,
        expected_firmware_len - (SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES - 1),
    )
    for packet_idx, packet_body_size in enumerate(packet_body_sizes):
        expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
        firmware_update_packet = create_data_packet(
            expected_pc_timestamp,
            SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
            bytes([packet_idx])
            + bytes([randint(0, 255) for _ in range(packet_body_size)]),  # arbitrary bytes
        )
        simulator.write(firmware_update_packet)
        invoke_process_run_and_check_errors(simulator)
        # assert command response is correct
        command_response = simulator.read(
            size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
        )
        assert_serial_packet_is_expected(
            command_response,
            SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
            additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
            + bytes([SERIAL_COMM_COMMAND_SUCCESS_BYTE]),
            error_msg=f"packet {packet_idx}",
        )


def test_MantarrayMcSimulator__processes_firmware_update_packet_with_too_many_firmware_bytes(
    mantarray_mc_simulator_no_beacon,
):
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_firmware_len = SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES
    begin_firmware_update_command = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
        bytes([randint(0, 1)]) + expected_firmware_len.to_bytes(4, byteorder="little"),
    )
    simulator.write(begin_firmware_update_command)
    # process command and return response
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()

    # send firmware update packets
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    firmware_update_packet = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
        bytes([0])
        + bytes(
            [randint(0, 255) for _ in range(SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES)]
        ),  # arbitrary bytes
    )
    simulator.write(firmware_update_packet)
    invoke_process_run_and_check_errors(simulator)
    # assert command response is correct
    command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
        + bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


def test_MantarrayMcSimulator__processes_firmware_update_packet_when_packet_idx_is_incorrect(
    mantarray_mc_simulator_no_beacon,
):
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_firmware_len = 1000
    begin_firmware_update_command = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
        bytes([randint(0, 1)]) + expected_firmware_len.to_bytes(4, byteorder="little"),
    )
    simulator.write(begin_firmware_update_command)
    # process command and return response
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()

    # send firmware update packets
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    firmware_update_packet = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
        bytes([1])  # incorrect packet index
        + bytes([randint(0, 255) for _ in range(expected_firmware_len)]),  # arbitrary bytes
    )
    simulator.write(firmware_update_packet)
    invoke_process_run_and_check_errors(simulator)
    # assert command response is correct
    command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
        + bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


@pytest.mark.parametrize("firmware_type", [0, 1])
@pytest.mark.parametrize("is_checksum_correct", [True, False])
def test_MantarrayMcSimulator__processes_end_firmware_update_command(
    mantarray_mc_simulator_no_beacon, firmware_type, is_checksum_correct
):
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_firmware_len = SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES - 1
    expected_firmware_bytes = bytes([randint(0, 255) for _ in range(expected_firmware_len)])

    # first need to start firmware update
    begin_firmware_update_command = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
        bytes([firmware_type]) + expected_firmware_len.to_bytes(4, byteorder="little"),
    )
    simulator.write(begin_firmware_update_command)
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()
    # send firmware bytes
    simulator.write(
        create_data_packet(
            randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
            SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
            bytes([0]) + expected_firmware_bytes,
        )
    )
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()

    firmware_crc32_checksum = crc32(expected_firmware_bytes)
    if not is_checksum_correct:
        firmware_crc32_checksum -= 1

    # end firmware update
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    end_firmware_update_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE,
        firmware_crc32_checksum.to_bytes(4, byteorder="little"),
    )
    simulator.write(end_firmware_update_command)
    # process command and return response
    assert simulator.is_rebooting() is False
    invoke_process_run_and_check_errors(simulator)
    # make sure simulator is rebooting if checksum is correct
    assert simulator.is_rebooting() is is_checksum_correct
    # assert command response is correct
    command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp) + bytes([not is_checksum_correct]),
    )


@pytest.mark.parametrize(
    "firmware_type,packet_type",
    [
        (0, SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE),
        (1, SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE),
    ],
)
def test_MantarrayMcSimulator__sends_firmware_update_complete_message_after_reboot_then_reboots_again(
    mantarray_mc_simulator_no_beacon, firmware_type, packet_type, mocker
):
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_firmware_len = SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES - 1
    expected_firmware_bytes = bytes([randint(0, 255) for _ in range(expected_firmware_len)])

    # first need to start firmware update
    begin_firmware_update_command = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
        bytes([firmware_type]) + expected_firmware_len.to_bytes(4, byteorder="little"),
    )
    simulator.write(begin_firmware_update_command)
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()
    # send firmware bytes
    simulator.write(
        create_data_packet(
            randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
            SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
            bytes([0]) + expected_firmware_bytes,
        )
    )
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()
    # end of firmware update
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    end_firmware_update_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE,
        crc32(expected_firmware_bytes).to_bytes(4, byteorder="little"),
    )
    simulator.write(end_firmware_update_command)
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()

    assert simulator.is_rebooting() is True
    assert simulator.in_waiting == 0

    # mock so reboot completes on next iteration
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        return_value=AVERAGE_MC_REBOOT_DURATION_SECONDS,
    )
    # complete first reboot and send firmware update complete packet
    invoke_process_run_and_check_errors(simulator)
    command_response = simulator.read(size=get_full_packet_size_from_packet_body_size(3))
    assert_serial_packet_is_expected(
        command_response, packet_type, additional_bytes=bytes([0, 0, 0])
    )  # simulator currently always returns firmware version 0.0.0
    # make sure second reboot started immediately
    assert simulator.is_rebooting() is True
    # complete second reboot
    invoke_process_run_and_check_errors(simulator)
    assert simulator.is_rebooting() is False
    # make sure status code is idle ready
    assert simulator.get_status_code() == SERIAL_COMM_IDLE_READY_CODE
