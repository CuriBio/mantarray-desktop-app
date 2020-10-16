# -*- coding: utf-8 -*-
from multiprocessing import Queue

from mantarray_desktop_app import DataAnalyzerProcess
import pytest


@pytest.fixture(scope="function", name="four_board_analyzer_process")
def fixture_four_board_analyzer_process():
    comm_from_main_queue = Queue()
    comm_to_main_queue = Queue()
    error_queue = Queue()

    board_queues = tuple([(Queue(), Queue(),) for _ in range(4)])
    p = DataAnalyzerProcess(
        board_queues, comm_from_main_queue, comm_to_main_queue, error_queue,
    )
    yield p, board_queues, comm_from_main_queue, comm_to_main_queue, error_queue
