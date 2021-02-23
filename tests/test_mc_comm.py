# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue

from mantarray_desktop_app import McCommunicationProcess
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from .fixtures_mc_comm import fixture_four_board_mc_comm_process
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from .helpers import confirm_queue_is_eventually_empty
from .helpers import confirm_queue_is_eventually_of_size
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_four_board_mc_comm_process,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_McCommunicationProcess_super_is_called_during_init(mocker):
    error_queue = Queue()
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")
    McCommunicationProcess((), error_queue)
    mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


def test_McCommunicationProcess_hard_stop__clears_all_queues_and_returns_lists_of_values(
    four_board_mc_comm_process,
):
    mc_process, board_queues, error_queue = four_board_mc_comm_process

    expected = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]]
    expected_error = "error"

    for i, board in enumerate(board_queues):
        for j, queue in enumerate(board):
            item = expected[i][j]
            queue.put(item)
    confirm_queue_is_eventually_of_size(board_queues[3][2], 1)
    error_queue.put(expected_error)
    confirm_queue_is_eventually_of_size(error_queue, 1)

    actual = mc_process.hard_stop()
    assert actual["fatal_error_reporter"] == [expected_error]

    confirm_queue_is_eventually_empty(board_queues[1][0])
    confirm_queue_is_eventually_empty(board_queues[2][0])
    confirm_queue_is_eventually_empty(board_queues[3][0])
    confirm_queue_is_eventually_empty(board_queues[0][0])
    confirm_queue_is_eventually_empty(board_queues[0][2])

    assert actual["board_1"]["main_to_instrument_comm"] == [expected[1][0]]
    assert actual["board_2"]["main_to_instrument_comm"] == [expected[2][0]]
    assert actual["board_3"]["main_to_instrument_comm"] == [expected[3][0]]
    assert actual["board_0"]["main_to_instrument_comm"] == [expected[0][0]]
    assert expected[0][1] in actual["board_0"]["instrument_comm_to_main"]
    assert actual["board_0"]["instrument_comm_to_file_writer"] == [expected[0][2]]


def test_McCommunicationProcess_set_board_connection__sets_connect_to_mc_simulator_correctly(
    four_board_mc_comm_process, mantarray_mc_simulator
):
    mc_process = four_board_mc_comm_process[0]
    simulator = mantarray_mc_simulator[4]

    mc_process.set_board_connection(1, simulator)
    actual = mc_process.get_board_connections_list()

    assert actual[0] is None
    assert actual[1] is simulator
    assert actual[2] is None
    assert actual[3] is None


def test_McCommunicationProcess_read_from_board__synces_with_magic_word_in_serial_comm_from_board__when_first_packet_is_truncated(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process[0]
    testing_queue = mantarray_mc_simulator_no_beacon[3]
    simulator = mantarray_mc_simulator_no_beacon[4]

    board_idx = 0
    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_synced_with_serial_comm(board_idx) is False

    mc_process.set_board_connection(board_idx, simulator)
    test_bytes = (
        SERIAL_COMM_MAGIC_WORD_BYTES[3:]
        + bytes(8)
        + SERIAL_COMM_MAGIC_WORD_BYTES
        + bytes(8)
    )
    test_item = {"command": "add_read_bytes", "read_bytes": test_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_synced_with_serial_comm(board_idx) is True
    # Make sure next iteration doesn't raise errors
    invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess_read_from_board__synces_with_magic_word_in_serial_comm_from_board__when_first_packet_is_not_truncated(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process[0]
    testing_queue = mantarray_mc_simulator_no_beacon[3]
    simulator = mantarray_mc_simulator_no_beacon[4]

    board_idx = 0
    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_synced_with_serial_comm(board_idx) is False

    mc_process.set_board_connection(board_idx, simulator)
    test_bytes = SERIAL_COMM_MAGIC_WORD_BYTES + bytes(8)
    test_item = {"command": "add_read_bytes", "read_bytes": test_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_synced_with_serial_comm(board_idx) is True
    # Make sure next iteration doesn't raise errors
    invoke_process_run_and_check_errors(mc_process)
