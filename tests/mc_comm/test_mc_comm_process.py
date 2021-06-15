# -*- coding: utf-8 -*-
import copy
import logging
from multiprocessing import Queue

from freezegun import freeze_time
from mantarray_desktop_app import MantarrayInstrumentError
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import McCommunicationProcess
from mantarray_desktop_app import SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_FATAL_ERROR_CODE
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from mantarray_desktop_app import SerialCommIncorrectMagicWordFromMantarrayError
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
from ..fixtures_mc_comm import sleep_side_effect
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
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
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")
    McCommunicationProcess((), error_queue)
    mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


def test_McCommunicationProcess_setup_before_loop__calls_super(
    four_board_mc_comm_process,
    mocker,
):
    spied_setup = mocker.spy(InfiniteProcess, "_setup_before_loop")

    mc_process = four_board_mc_comm_process["mc_process"]
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    spied_setup.assert_called_once()

    # simulator is automatically started by mc_comm during setup_before_loop. Need to hard stop here since there is no access to the simulator's queues which must be drained before joining
    populated_connections_list = mc_process.get_board_connections_list()
    populated_connections_list[0].hard_stop()
    populated_connections_list[0].join()


@pytest.mark.slow
@freeze_time("2021-03-16 13:05:55.654321")
@pytest.mark.timeout(15)
def test_McCommunicationProcess_setup_before_loop__connects_to_boards__and_sends_message_to_main(
    four_board_mc_comm_process,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    assert mc_process.get_board_connections_list() == [None] * 4
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    populated_connections_list = mc_process.get_board_connections_list()
    assert isinstance(populated_connections_list[0], MantarrayMcSimulator)
    assert populated_connections_list[1:] == [None] * 3

    assert_queue_is_eventually_not_empty(board_queues[0][1])
    process_initiated_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert process_initiated_msg["communication_type"] == "log"
    assert (
        process_initiated_msg["message"]
        == "Microcontroller Communication Process initiated at 2021-03-16 13:05:55.654321"
    )
    # simulator is automatically started by mc_comm during setup_before_loop. Need to hard stop here since there is no access to the simulator's queues which must be drained before joining
    populated_connections_list[0].hard_stop()
    populated_connections_list[0].join()


@pytest.mark.slow
@pytest.mark.timeout(15)
def test_McCommunicationProcess_setup_before_loop__does_not_send_message_to_main_when_setup_comm_is_suppressed():
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    mc_process = McCommunicationProcess(board_queues, error_queue, suppress_setup_communication_to_main=True)
    assert mc_process.get_board_connections_list() == [None] * 4
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    populated_connections_list = mc_process.get_board_connections_list()
    assert isinstance(populated_connections_list[0], MantarrayMcSimulator)
    assert populated_connections_list[1:] == [None] * 3

    # Other parts of the process after setup may or may not send messages to main, so drain queue and make sure none of the items (if present) have a setup message
    to_main_queue_items = drain_queue(board_queues[0][1])
    for item in to_main_queue_items:
        if "message" in item:
            assert "Microcontroller Communication Process initiated" not in item["message"]

    # simulator is automatically started by mc_comm during setup_before_loop. Need to hard stop here since there is no access to the simulator's queues which must be drained before joining
    populated_connections_list[0].hard_stop()
    populated_connections_list[0].join()


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
    dummy_communication = {
        "communication_type": "metadata_comm",
        "command": "get_metadata",
    }
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
    test_communication = {
        "communication_type": "metadata_comm",
        "command": "get_metadata",
    }
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


def test_McCommunicationProcess_teardown_after_loop__flushes_and_logs_remaining_serial_data__and_requests_eeprom_dump_if_error_occurred_in_mc_comm(
    patch_print,
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    mocked_write = mocker.patch.object(simulator, "write", autospec=True)
    mocked_sleep = mocker.patch.object(mc_comm, "sleep", autospec=True, side_effect=sleep_side_effect)

    # add one data packet with bad magic word to raise error and additional bytes to flush from simulator
    test_read_bytes = [
        bytes(SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES),  # bad packet
        bytes(SERIAL_COMM_MAX_PACKET_LENGTH_BYTES),  # start of additional bytes
        bytes(SERIAL_COMM_MAX_PACKET_LENGTH_BYTES),
        bytes(SERIAL_COMM_MAX_PACKET_LENGTH_BYTES // 2),  # arbitrary final length
    ]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "add_read_bytes",
            "read_bytes": test_read_bytes,
        },
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    # read beacon then flush remaining serial data
    with pytest.raises(SerialCommIncorrectMagicWordFromMantarrayError):
        invoke_process_run_and_check_errors(
            mc_process,
            perform_teardown_after_loop=True,
        )
    assert simulator.in_waiting == 0
    # check that log message contains remaining data
    teardown_messages = drain_queue(output_queue)
    actual = teardown_messages[-1]
    assert "message" in actual, f"Correct message not found. Full message dict: {actual}"
    expected_bytes = bytes(
        sum([len(packet) for packet in test_read_bytes]) - len(SERIAL_COMM_MAGIC_WORD_BYTES)
    )  # EEPROM bytes will not show up since simulator is not running while mc_process is in _teardown_after_loop. Assert that dump EEPROM command was sent instead
    assert str(expected_bytes) in actual["message"]
    # check that dump EEPROM command was sent
    assert_serial_packet_is_expected(
        mocked_write.call_args[0][0],
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE]),
    )
    # check that mc_process slept for 1 second prior to reading from simulator
    mocked_sleep.assert_called_once_with(1)


def test_McCommunicationProcess_teardown_after_loop__does_not_request_eeprom_dump_if_an_instrument_error_occurred(
    patch_print,
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    mocked_write = mocker.patch.object(simulator, "write", autospec=True)
    mocked_sleep = mocker.patch.object(mc_comm, "sleep", autospec=True, side_effect=sleep_side_effect)

    # put simulator in error state before sending beacon
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "set_status_code",
            "status_code": SERIAL_COMM_FATAL_ERROR_CODE,
        },
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    # add one beacon for mc_process to read normally
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    # add read bytes to flush from simulator
    test_read_bytes = [
        bytes(SERIAL_COMM_MAX_PACKET_LENGTH_BYTES),
        bytes(SERIAL_COMM_MAX_PACKET_LENGTH_BYTES),
        bytes(SERIAL_COMM_MAX_PACKET_LENGTH_BYTES // 2),  # arbitrary final length
    ]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "add_read_bytes",
            "read_bytes": test_read_bytes,
        },
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    # read beacon, raise, error, then flush remaining serial data
    with pytest.raises(MantarrayInstrumentError):
        invoke_process_run_and_check_errors(
            mc_process,
            perform_teardown_after_loop=True,
        )
    # check that all data was flushed here
    assert simulator.in_waiting == 0
    # check that dump EEPROM command was not sent and no sleep was performed
    mocked_write.assert_not_called()
    mocked_sleep.assert_not_called()
    # drain queue to prevent BrokenPipeErrors
    drain_queue(output_queue)


def test_McCommunicationProcess_teardown_after_loop__does_not_request_eeprom_dump_if_no_errors_occured(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    mocked_write = mocker.patch.object(simulator, "write", autospec=True)
    mocked_sleep = mocker.patch.object(mc_comm, "sleep", autospec=True, side_effect=sleep_side_effect)

    # run one iteration then teardown
    invoke_process_run_and_check_errors(
        mc_process,
        perform_teardown_after_loop=True,
    )
    # check that dump EEPROM command was not sent and no sleep was performed
    mocked_write.assert_not_called()
    mocked_sleep.assert_not_called()
    # drain queue to prevent BrokenPipeErrors
    drain_queue(output_queue)


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


def test_McCommunicationProcess__logs_status_codes_from_status_beacons(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    expected_status_code = 1234
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": expected_status_code},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    actual = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert str(expected_status_code) in actual["message"]


def test_McCommunicationProcess__logs_status_codes_from_handshake_responses(
    four_board_mc_comm_process,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    output_queue = four_board_mc_comm_process["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)

    expected_status_code = 1234
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": expected_status_code},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    actual = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert str(expected_status_code) in actual["message"]


def test_McCommunicationProcess__checks_for_simulator_errors_in_simulator_error_queue__and_if_error_is_present_sends_to_main_process_and_stops_itself(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    patch_print,
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
    confirm_queue_is_eventually_of_size(
        simulator_eq, 1, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    # run mc_process to pull out error and populate its own error queue
    assert mc_process.is_stopped() is False
    with pytest.raises(ValueError, match=error_msg):
        invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_stopped() is True
