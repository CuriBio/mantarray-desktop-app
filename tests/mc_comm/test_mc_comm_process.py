# -*- coding: utf-8 -*-
import copy
import logging
from multiprocessing import Queue
from random import randint

from freezegun import freeze_time
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import McCommunicationProcess
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_REBOOT_PACKET_TYPE
from mantarray_desktop_app import SerialCommIncorrectMagicWordFromMantarrayError
from mantarray_desktop_app.constants import SERIAL_COMM_ERROR_ACK_PACKET_TYPE
from mantarray_desktop_app.constants import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app.constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app.exceptions import InstrumentFirmwareError
from mantarray_desktop_app.serial_comm_utils import convert_status_code_bytes_to_dict
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import generate_board_and_error_queues
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import DEFAULT_SIMULATOR_STATUS_CODES
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import random_timestamp
from ..helpers import assert_queue_is_eventually_not_empty
from ..helpers import assert_serial_packet_is_expected
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_four_board_mc_comm_process,
    fixture_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_four_board_mc_comm_process_no_handshake,
]


def test_McCommunicationProcess_super_is_called_during_init(mocker):
    error_queue = Queue()
    spied_init = mocker.spy(InfiniteProcess, "__init__")
    mc_process = McCommunicationProcess((), error_queue)
    spied_init.assert_called_once_with(mc_process, error_queue, logging_level=logging.INFO)


def test_McCommunicationProcess_setup_before_loop__calls_super(four_board_mc_comm_process, mocker):
    spied_setup = mocker.spy(InfiniteProcess, "_setup_before_loop")

    mc_process = four_board_mc_comm_process["mc_process"]
    # mock to speed up test
    mocker.patch.object(mc_process, "create_connections_to_all_available_boards", autospec=True)

    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    spied_setup.assert_called_once()


@freeze_time("2021-03-16 13:05:55.654321")
def test_McCommunicationProcess_setup_before_loop__connects_to_boards__and_sends_message_to_main(
    four_board_mc_comm_process, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    mocked_create_connections = mocker.patch.object(
        mc_process, "create_connections_to_all_available_boards", autospec=True
    )

    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    mocked_create_connections.assert_called_once()

    assert_queue_is_eventually_not_empty(board_queues[0][1])
    process_initiated_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert process_initiated_msg["communication_type"] == "log"
    assert (
        process_initiated_msg["message"]
        == "Microcontroller Communication Process initiated at 2021-03-16 13:05:55.654321"
    )


def test_McCommunicationProcess_setup_before_loop__does_not_send_message_to_main_when_setup_comm_is_suppressed(
    mocker,
):
    # mock this so the process priority isn't changed during unit tests
    mocker.patch.object(mc_comm, "set_this_process_high_priority", autospec=True)

    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    mc_process = McCommunicationProcess(board_queues, error_queue, suppress_setup_communication_to_main=True)
    mocked_create_connections = mocker.patch.object(
        mc_process, "create_connections_to_all_available_boards", autospec=True
    )

    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    mocked_create_connections.assert_called_once()

    # Other parts of the process after setup may or may not send messages to main, so drain queue and make sure none of the items (if present) have a setup message
    to_main_queue_items = drain_queue(board_queues[0][1])
    for item in to_main_queue_items:
        if "message" in item:
            assert "Microcontroller Communication Process initiated" not in item["message"]


def test_McCommunicationProcess_setup_before_loop__does_not_set_process_priority_when_connected_to_a_simulator(
    mocker, mantarray_mc_simulator
):
    simulator = mantarray_mc_simulator["simulator"]
    mocker.patch.object(simulator, "start", autospec=True)
    mocker.patch.object(simulator, "is_start_up_complete", autospec=True, return_value=True)

    # mock this so the process priority isn't changed during unit tests
    mocked_set_priority = mocker.patch.object(mc_comm, "set_this_process_high_priority", autospec=True)

    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    mc_process = McCommunicationProcess(board_queues, error_queue, suppress_setup_communication_to_main=True)
    mc_process.set_board_connection(0, simulator)

    mc_process._setup_before_loop()
    mocked_set_priority.assert_not_called()


def test_McCommunicationProcess_setup_before_loop__sets_process_priority_when_not_connected_to_a_simulator(
    mocker,
):
    # mock this so the process priority isn't changed during unit tests
    mocked_set_priority = mocker.patch.object(mc_comm, "set_this_process_high_priority", autospec=True)

    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    mc_process = McCommunicationProcess(board_queues, error_queue, suppress_setup_communication_to_main=True)
    mocker.patch.object(mc_process, "create_connections_to_all_available_boards", autospec=True)

    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    mocked_set_priority.assert_called_once()


def test_McCommunicationProcess_hard_stop__clears_all_queues_and_returns_lists_of_values(
    four_board_mc_comm_process,
):
    mc_process, board_queues, error_queue = four_board_mc_comm_process.values()

    expected = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]]
    expected_error = "error"

    for i, board in enumerate(board_queues):
        for j, queue in enumerate(board):
            item = expected[i][j]
            queue.put_nowait(item)
    confirm_queue_is_eventually_of_size(board_queues[3][2], 1)
    error_queue.put_nowait(expected_error)
    confirm_queue_is_eventually_of_size(error_queue, 1)

    actual = mc_process.hard_stop()
    assert actual["fatal_error_reporter"] == [expected_error]

    # Assert arbitrarily that most queues are empty
    confirm_queue_is_eventually_empty(board_queues[1][0])
    confirm_queue_is_eventually_empty(board_queues[2][0])
    confirm_queue_is_eventually_empty(board_queues[3][0])
    confirm_queue_is_eventually_empty(board_queues[0][0])
    confirm_queue_is_eventually_empty(board_queues[0][2])

    # Assert arbitrarily that most queue items are correct
    assert actual["board_1"]["main_to_instrument_comm"] == [expected[1][0]]
    assert actual["board_2"]["main_to_instrument_comm"] == [expected[2][0]]
    assert actual["board_3"]["main_to_instrument_comm"] == [expected[3][0]]
    assert actual["board_0"]["main_to_instrument_comm"] == [expected[0][0]]
    assert expected[0][1] in actual["board_0"]["instrument_comm_to_main"]
    assert actual["board_0"]["instrument_comm_to_file_writer"] == [expected[0][2]]


def test_McCommunicationProcess_soft_stop_not_allowed_if_communication_from_main_still_in_queue(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    dummy_communication = {"communication_type": "metadata_comm", "command": "get_metadata"}
    items_to_put_in_queue = [copy.deepcopy(dummy_communication)] * 3
    # The first two commands will be processed, but if there is a third one in the queue then the soft stop should be disabled
    handle_putting_multiple_objects_into_empty_queue(items_to_put_in_queue, board_queues[0][0])
    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)
    # attempt to soft stop and confirm process does not stop
    mc_process.soft_stop()
    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_stopped() is False


def test_McCommunicationProcess_soft_stop_not_allowed_if_waiting_for_command_response_from_instrument(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    test_communication = {"communication_type": "metadata_comm", "command": "get_metadata"}
    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)
    # send command but do not process it in simulator
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_communication, board_queues[0][0])
    invoke_process_run_and_check_errors(mc_process)
    # attempt to soft stop and confirm process does not stop
    mc_process.soft_stop()
    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_stopped() is False


def test_McCommunicationProcess_teardown_after_loop__sets_teardown_complete_event(
    four_board_mc_comm_process,
):
    mc_process = four_board_mc_comm_process["mc_process"]

    mc_process.soft_stop()
    invoke_process_run_and_check_errors(mc_process, num_iterations=1, perform_teardown_after_loop=True)

    assert mc_process.is_teardown_complete() is True


@freeze_time("2021-03-19 12:53:30.654321")
def test_McCommunicationProcess_teardown_after_loop__puts_teardown_log_message_into_queue(
    four_board_mc_comm_process,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    comm_to_main_queue = board_queues[0][1]

    mc_process.soft_stop()
    invoke_process_run_and_check_errors(mc_process, num_iterations=1, perform_teardown_after_loop=True)
    confirm_queue_is_eventually_of_size(comm_to_main_queue, 1)

    actual = comm_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert (
        actual["message"]
        == "Microcontroller Communication Process beginning teardown at 2021-03-19 12:53:30.654321"
    )


def test_McCommunicationProcess_teardown_after_loop__flushes_and_logs_remaining_serial_data__and_unread_data_in_cache__if_error_occurred_in_mc_comm(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # add one data packet with bad magic word to raise error and additional bytes to flush from simulator
    data_packet = create_data_packet(random_timestamp(), SERIAL_COMM_STATUS_BEACON_PACKET_TYPE)
    test_cache_bytes = (
        bytes(len(SERIAL_COMM_MAGIC_WORD_BYTES)) + data_packet[len(SERIAL_COMM_MAGIC_WORD_BYTES) :]
    )
    test_buffer_bytes = bytes([randint(0, 10) for _ in range(SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES)])
    mocker.patch.object(
        simulator, "read_all", autospec=True, side_effect=[test_cache_bytes, test_buffer_bytes]
    )

    # read beacon then flush remaining serial data
    with pytest.raises(SerialCommIncorrectMagicWordFromMantarrayError):
        invoke_process_run_and_check_errors(mc_process, perform_teardown_after_loop=True)
    assert simulator.in_waiting == 0
    # check that log message contains remaining data
    teardown_messages = drain_queue(output_queue)
    actual = teardown_messages[-1]
    assert "message" in actual, f"Correct message not found. Full message dict: {actual}"
    assert str(test_cache_bytes) in actual["message"]
    assert str(test_buffer_bytes) in actual["message"]


@pytest.mark.parametrize("error", [True, False])
@pytest.mark.parametrize("in_simulation_mode", [True, False])
def test_McCommunicationProcess_teardown_after_loop__sends_reboot_command_if_error_occurred_and_not_in_simulation_mode(
    in_simulation_mode,
    error,
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
    patch_print,
):
    board_connection = (
        mantarray_mc_simulator_no_beacon["simulator"] if in_simulation_mode else mocker.MagicMock()
    )
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    mc_process.set_board_connection(0, board_connection)

    spied_write = mocker.spy(board_connection, "write")
    spied_timestamp = mocker.spy(mc_comm, "get_serial_comm_timestamp")
    # mock so error is raised
    mocked_cferi = mocker.patch.object(mc_process, "_commands_for_each_run_iteration", autospec=True)
    if error:
        mocked_cferi.side_effect = Exception()

    # run one iteration and make sure reboot command is sent only if not connected to a simulator
    mc_process.run(num_iterations=1, perform_setup_before_loop=False, perform_teardown_after_loop=True)
    if in_simulation_mode or not error:
        spied_write.assert_not_called()
    else:
        reboot_command_bytes = create_data_packet(spied_timestamp.spy_return, SERIAL_COMM_REBOOT_PACKET_TYPE)
        spied_write.assert_called_once_with(reboot_command_bytes)


@pytest.mark.slow
@pytest.mark.timeout(15)
def test_McCommunicationProcess_teardown_after_loop__stops_running_simulator():
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    mc_process = McCommunicationProcess(board_queues, error_queue, suppress_setup_communication_to_main=True)
    invoke_process_run_and_check_errors(
        mc_process,
        num_iterations=1,
        perform_teardown_after_loop=True,
        perform_setup_before_loop=True,
    )
    mc_process.soft_stop()
    simulator = mc_process.get_board_connections_list()[0]
    assert simulator.is_stopped() is True
    assert simulator.is_alive() is False


@pytest.mark.parametrize("log_level", [logging.DEBUG, logging.INFO])
def test_McCommunicationProcess__logs_status_codes_from_status_beacons_correctly(
    log_level, four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    expected_status_code_dict = convert_status_code_bytes_to_dict(DEFAULT_SIMULATOR_STATUS_CODES)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    mc_process._logging_level = log_level
    invoke_process_run_and_check_errors(mc_process)

    if log_level == logging.INFO:
        confirm_queue_is_eventually_empty(output_queue)
    else:
        confirm_queue_is_eventually_of_size(output_queue, 1)
        actual = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert "status beacon" in actual["message"].lower()
        assert str(expected_status_code_dict) in actual["message"]


@pytest.mark.parametrize("log_level", [logging.DEBUG, logging.INFO])
def test_McCommunicationProcess__logs_status_codes_from_handshake_responses_correctly(
    log_level, four_board_mc_comm_process, mantarray_mc_simulator_no_beacon
):
    mc_process = four_board_mc_comm_process["mc_process"]
    output_queue = four_board_mc_comm_process["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    # handshake sent in this function
    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)

    expected_status_code_dict = convert_status_code_bytes_to_dict(DEFAULT_SIMULATOR_STATUS_CODES)

    # process handshake
    invoke_process_run_and_check_errors(simulator)
    # process handshake response
    mc_process._logging_level = log_level
    invoke_process_run_and_check_errors(mc_process)

    if log_level == logging.INFO:
        confirm_queue_is_eventually_empty(output_queue)
    else:
        confirm_queue_is_eventually_of_size(output_queue, 1)
        actual = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert "handshake" in actual["message"].lower()
        assert str(expected_status_code_dict) in actual["message"]


def test_McCommunicationProcess__handles_error_status_code_found_in_status_beacon(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    spied_write = mocker.spy(simulator, "write")
    # mock so that mc_comm will use teardown procedure for a real instrument
    mocker.patch.object(mc_comm, "_is_simulator", autospec=True, return_value=False)

    expected_status_codes = list(range(simulator._num_wells + 2))
    expected_status_code_dict = convert_status_code_bytes_to_dict(expected_status_codes)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_codes": expected_status_codes}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # read beacon with error code and then teardown
    with pytest.raises(InstrumentFirmwareError) as exc_info:
        invoke_process_run_and_check_errors(mc_process, perform_teardown_after_loop=True)
    # make sure only error ack packet was sent to simulator
    spied_write.assert_called_once()
    assert_serial_packet_is_expected(spied_write.call_args[0][0], SERIAL_COMM_ERROR_ACK_PACKET_TYPE)
    # make sure relevant info is in error message
    assert "status beacon" in str(exc_info.value).lower()
    assert str(expected_status_code_dict) in str(exc_info.value)


def test_McCommunicationProcess__handles_error_status_code_found_in_handshake_response(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    # mock to control when handshakes are sent
    mocked_secs_since_handshake = mocker.patch.object(
        mc_comm, "_get_secs_since_last_handshake", autospec=True, return_value=0
    )
    # mock this so function mocked above controls when next handshake will be sent
    mocker.patch.object(mc_process, "_has_initial_handshake_been_sent", autospec=True, return_value=True)

    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)

    # mock so that mc_comm will use teardown procedure for a real instrument
    mocker.patch.object(mc_comm, "_is_simulator", autospec=True, return_value=False)

    expected_status_codes = list(range(simulator._num_wells + 2))
    expected_status_code_dict = convert_status_code_bytes_to_dict(expected_status_codes)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_codes": expected_status_codes}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # send handshake and response
    mocked_secs_since_handshake.return_value = SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # read handshake response with error code and then teardown
    mocked_secs_since_handshake.return_value = 0
    spied_write = mocker.spy(simulator, "write")
    with pytest.raises(InstrumentFirmwareError) as exc_info:
        invoke_process_run_and_check_errors(mc_process, perform_teardown_after_loop=True)
    # make sure only error ack packet was sent to simulator
    spied_write.assert_called_once()
    assert_serial_packet_is_expected(spied_write.call_args[0][0], SERIAL_COMM_ERROR_ACK_PACKET_TYPE)
    # make sure relevant info is in error message
    assert "handshake" in str(exc_info.value).lower()
    assert str(expected_status_code_dict) in str(exc_info.value)


def test_McCommunicationProcess__checks_for_simulator_errors_in_simulator_error_queue__and_if_error_is_present_sends_to_main_process_and_stops_itself(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    simulator_eq = mantarray_mc_simulator_no_beacon["error_queue"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    error_msg = "something went wrong in the simulator"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "raise_error", "error": ValueError(error_msg)}, testing_queue
    )
    # run simulator to raise error
    simulator.run(num_iterations=1)
    confirm_queue_is_eventually_of_size(simulator_eq, 1)
    # run mc_process to pull out error and populate its own error queue
    assert mc_process.is_stopped() is False
    with pytest.raises(ValueError, match=error_msg):
        invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_stopped() is True
