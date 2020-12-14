# -*- coding: utf-8 -*-
from multiprocessing import Queue

from mantarray_desktop_app import DataAnalyzerProcess
import pytest


@pytest.fixture(scope="function", name="four_board_analyzer_process")
def fixture_four_board_analyzer_process():
    num_boards = 4
    comm_from_main_queue = Queue()
    comm_to_main_queue = Queue()
    error_queue = Queue()

    board_queues = tuple(
        [
            (
                Queue(),
                Queue(),
            )
            for _ in range(num_boards)
        ]
    )
    p = DataAnalyzerProcess(
        board_queues,
        comm_from_main_queue,
        comm_to_main_queue,
        error_queue,
    )
    yield p, board_queues, comm_from_main_queue, comm_to_main_queue, error_queue
    # clean up by draining all the queues to avoid BrokenPipe errors
    p.hard_stop()
