# -*- coding: utf-8 -*-
import random
from random import randint
from zlib import crc32

from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import GOING_DORMANT_HANDSHAKE_TIMEOUT_CODE
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_COMMAND_FAILURE_BYTE
from mantarray_desktop_app import SERIAL_COMM_COMMAND_SUCCESS_BYTE
from mantarray_desktop_app import SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_GET_METADATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_GOING_DORMANT_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from mantarray_desktop_app import SERIAL_COMM_OKAY_CODE
from mantarray_desktop_app import SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_REBOOT_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_SET_NICKNAME_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SerialCommTooManyMissedHandshakesError
from mantarray_desktop_app import UnrecognizedSerialCommPacketTypeError
from mantarray_desktop_app.constants import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app.serial_comm_utils import convert_metadata_to_bytes
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import DEFAULT_SIMULATOR_STATUS_CODE
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import HANDSHAKE_RESPONSE_SIZE_BYTES
from ..fixtures_mc_simulator import STATUS_BEACON_SIZE_BYTES
from ..fixtures_mc_simulator import TEST_HANDSHAKE
from ..helpers import assert_serial_packet_is_expected
from ..helpers import get_full_packet_size_from_payload_len
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
        actual, SERIAL_COMM_HANDSHAKE_PACKET_TYPE, additional_bytes=DEFAULT_SIMULATOR_STATUS_CODE
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
        + handshake_packet_length.to_bytes(SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES, byteorder="little")
        + dummy_timestamp_bytes
        + bytes([SERIAL_COMM_HANDSHAKE_PACKET_TYPE])
        + dummy_checksum_bytes
    )
    simulator.write(test_handshake)
    invoke_process_run_and_check_errors(simulator)

    expected_packet_body = test_handshake[len(SERIAL_COMM_MAGIC_WORD_BYTES) :]
    expected_size = get_full_packet_size_from_payload_len(len(expected_packet_body))
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
    test_reboot_command = create_data_packet(expected_timestamp, SERIAL_COMM_REBOOT_PACKET_TYPE)
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)

    # test that reboot response packet is sent
    reboot_response = simulator.read(size=get_full_packet_size_from_payload_len(0))
    assert_serial_packet_is_expected(reboot_response, SERIAL_COMM_REBOOT_PACKET_TYPE)

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
        SERIAL_COMM_OKAY_CODE.to_bytes(SERIAL_COMM_STATUS_CODE_LENGTH_BYTES, byteorder="little"),
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
    test_reboot_command = create_data_packet(expected_timestamp, SERIAL_COMM_REBOOT_PACKET_TYPE)
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)
    # remove reboot response packet
    invoke_process_run_and_check_errors(simulator)
    reboot_response = simulator.read(size=get_full_packet_size_from_payload_len(0))
    assert_serial_packet_is_expected(reboot_response, SERIAL_COMM_REBOOT_PACKET_TYPE)

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
    expected_response_size = get_full_packet_size_from_payload_len(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
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
    expected_size = get_full_packet_size_from_payload_len(len(expected_metadata_bytes))
    actual = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        actual, SERIAL_COMM_GET_METADATA_PACKET_TYPE, additional_bytes=expected_metadata_bytes
    )


def test_MantarrayMcSimulator__raises_error_if_too_many_consecutive_handshake_periods_missed_from_pc__after_first_handshake_received(
    mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

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


def test_MantarrayMcSimulator__sends_going_dormant_packet_if_initial_handshake_received_but_another_not_received_before_timeout(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_comm_from_pc",
        autospec=True,
        return_value=SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS,
    )

    # make sure timeout not sent before any comm received before PC
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0
    # process initial handshake, remove response
    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()
    # trigger timeout
    invoke_process_run_and_check_errors(simulator)
    additional_bytes = bytes([GOING_DORMANT_HANDSHAKE_TIMEOUT_CODE])
    going_dormant_packet_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    going_dormant_packet = simulator.read(size=going_dormant_packet_size)
    assert_serial_packet_is_expected(
        going_dormant_packet, SERIAL_COMM_GOING_DORMANT_PACKET_TYPE, additional_bytes=additional_bytes
    )
    # run one more interation to make sure packet is not sent again
    invoke_process_run_and_check_errors(simulator)
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
            expected_pc_timestamp, SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE
        )
        simulator.write(test_start_data_streaming_command)
        invoke_process_run_and_check_errors(simulator)
        # assert response is correct
        additional_bytes = bytes([response_byte_value])
        if response_byte_value == SERIAL_COMM_COMMAND_SUCCESS_BYTE:
            additional_bytes += spied_global_timer.spy_return.to_bytes(8, byteorder="little")
        command_response_size = get_full_packet_size_from_payload_len(len(additional_bytes))
        command_response = simulator.read(size=command_response_size)
        assert_serial_packet_is_expected(
            command_response, SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE, additional_bytes=additional_bytes
        )


def test_MantarrayMcSimulator__processes_stop_data_streaming_command(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    # mock so no data packets or barcodes will be sent
    mocker.patch.object(mc_simulator, "_get_us_since_last_data_packet", autospec=True, return_value=0)
    mocker.patch.object(simulator, "_handle_barcode", autospec=True)

    # set arbitrary sampling period
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_sampling_period", "sampling_period": 2000}, testing_queue
    )

    dummy_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_start_data_streaming_command = create_data_packet(
        dummy_timestamp, SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE
    )
    simulator.write(test_start_data_streaming_command)
    invoke_process_run_and_check_errors(simulator)
    # remove start data streaming response
    command_response = simulator.read(
        size=get_full_packet_size_from_payload_len(9)  # 1 for response byte, 8 for global timer bytes
    )

    # need to send command once while data is being streamed and once after it stops to test the response in both cases
    for response_byte_value in (
        SERIAL_COMM_COMMAND_SUCCESS_BYTE,
        SERIAL_COMM_COMMAND_FAILURE_BYTE,
    ):
        # send stop streaming command
        expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
        test_stop_data_streaming_command = create_data_packet(
            expected_pc_timestamp, SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE
        )
        simulator.write(test_stop_data_streaming_command)
        invoke_process_run_and_check_errors(simulator)
        # assert response is correct
        command_response_size = get_full_packet_size_from_payload_len(1)
        command_response = simulator.read(size=command_response_size)
        assert_serial_packet_is_expected(
            command_response,
            SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE,
            additional_bytes=bytes([response_byte_value]),
        )


def test_MantarrayMcSimulator__processes_set_sampling_period_command__when_data_is_not_streaming(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # assert that sampling period has not been set
    assert simulator.get_sampling_period_us() == DEFAULT_SAMPLING_PERIOD
    # send command to set magnetometer configuration
    expected_sampling_period = DEFAULT_SAMPLING_PERIOD + 1000
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    change_config_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE,
        expected_sampling_period.to_bytes(2, byteorder="little"),
    )
    simulator.write(change_config_command)
    # process command to update configuration and send response
    invoke_process_run_and_check_errors(simulator)
    # assert command response is correct
    command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE,
        additional_bytes=bytes([SERIAL_COMM_COMMAND_SUCCESS_BYTE]),
    )
    # assert that sampling period is updated
    assert simulator.get_sampling_period_us() == expected_sampling_period


def test_MantarrayMcSimulator__processes_set_sampling_period_command__when_data_is_streaming(
    mantarray_mc_simulator_no_beacon, mocker
):
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
    # send command to set magnetometer configuration
    ignored_sampling_period = 1000
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    change_config_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE,
        ignored_sampling_period.to_bytes(2, byteorder="little"),
    )
    simulator.write(change_config_command)
    # process command and return response
    invoke_process_run_and_check_errors(simulator)
    # assert command response is correct
    command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE,
        additional_bytes=bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )
    # assert that sampling period is unchanged
    assert simulator.get_sampling_period_us() == test_sampling_period

    simulator.hard_stop()  # prevent BrokenPipeErrors


@pytest.mark.parametrize("firmware_type", [0, 1, 2])
def test_MantarrayMcSimulator__processes_begin_firmware_update_command__when_not_already_updating_firmware(
    mantarray_mc_simulator_no_beacon, firmware_type
):
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
    command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
    expected_success_value = int(firmware_type not in (0, 1))
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
        additional_bytes=bytes([expected_success_value]),
    )


def test_MantarrayMcSimulator__processes_begin_firmware_update_command__when_already_updating_firmware(
    mantarray_mc_simulator_no_beacon,
):
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
        command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
        assert_serial_packet_is_expected(
            command_response,
            SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
            additional_bytes=bytes([success_failure_byte_value]),
        )


def test_MantarrayMcSimulator__processes_successful_firmware_update_packet(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_firmware_len = randint(
        SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES,
        int(SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES * 1.5),
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
        SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES - 1,
        expected_firmware_len - (SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES - 1),
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
        command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
        assert_serial_packet_is_expected(
            command_response,
            SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
            additional_bytes=bytes([SERIAL_COMM_COMMAND_SUCCESS_BYTE]),
            error_msg=f"packet {packet_idx}",
        )


def test_MantarrayMcSimulator__processes_firmware_update_packet_with_too_many_firmware_bytes(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_firmware_len = SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES
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
        + bytes([randint(0, 255) for _ in range(SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES)]),  # arbitrary bytes
    )
    simulator.write(firmware_update_packet)
    invoke_process_run_and_check_errors(simulator)
    # assert command response is correct
    command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
        additional_bytes=bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


def test_MantarrayMcSimulator__processes_firmware_update_packet_when_packet_idx_is_incorrect(
    mantarray_mc_simulator_no_beacon,
):
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
    command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
        additional_bytes=bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


@pytest.mark.parametrize("firmware_type", [0, 1])
@pytest.mark.parametrize("is_checksum_correct", [True, False])
def test_MantarrayMcSimulator__processes_end_firmware_update_command(
    mantarray_mc_simulator_no_beacon, firmware_type, is_checksum_correct
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_firmware_len = SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES - 1
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
    command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE,
        additional_bytes=bytes([not is_checksum_correct]),
    )


@pytest.mark.parametrize(
    "firmware_type,packet_type",
    [(0, SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE), (1, SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE)],
)
def test_MantarrayMcSimulator__sends_firmware_update_complete_message_after_reboot_then_reboots_again(
    mantarray_mc_simulator_no_beacon, firmware_type, packet_type, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_firmware_len = SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES - 1
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
    command_response = simulator.read(size=get_full_packet_size_from_payload_len(3))
    assert_serial_packet_is_expected(
        command_response, packet_type, additional_bytes=bytes([0, 0, 0])
    )  # simulator currently always returns firmware version 0.0.0
    # make sure second reboot started immediately
    assert simulator.is_rebooting() is True
    # complete second reboot
    invoke_process_run_and_check_errors(simulator)
    assert simulator.is_rebooting() is False
    # make sure status code is idle ready
    assert simulator.get_status_code() == SERIAL_COMM_OKAY_CODE
