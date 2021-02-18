# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue

from mantarray_desktop_app import McCommunicationProcess
from stdlib_utils import InfiniteProcess

from .fixtures_mc_comm import fixture_four_board_mc_comm_process
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator
from .helpers import confirm_queue_is_eventually_empty
from .helpers import confirm_queue_is_eventually_of_size

__fixtures__ = [fixture_four_board_mc_comm_process, fixture_mantarray_mc_simulator]


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
