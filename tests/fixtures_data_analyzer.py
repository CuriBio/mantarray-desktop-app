# -*- coding: utf-8 -*-
from multiprocessing import Queue

from mantarray_desktop_app import DataAnalyzerProcess
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


def set_sampling_period(da_fixture, sampling_period):
    da_process = da_fixture["da_process"]
    from_main_queue = da_fixture["from_main_queue"]

    set_sampling_period_command = {
        "communication_type": "sampling_period_update",
        "sampling_period": sampling_period,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        set_sampling_period_command, from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)


@pytest.fixture(scope="function", name="four_board_analyzer_process")
def fixture_four_board_analyzer_process():
    num_boards = 4
    comm_from_main_queue = Queue()
    comm_to_main_queue = Queue()
    error_queue = Queue()

    board_queues = tuple(
        (
            (
                Queue(),
                Queue(),
            )
            # pylint: disable=duplicate-code
            for _ in range(num_boards)
        )
    )
    p = DataAnalyzerProcess(
        board_queues,
        comm_from_main_queue,
        comm_to_main_queue,
        error_queue,
    )
    yield p, board_queues, comm_from_main_queue, comm_to_main_queue, error_queue


@pytest.fixture(scope="function", name="four_board_analyzer_process_beta_2_mode")
def fixture_four_board_analyzer_process_beta_2_mode():
    num_boards = 4
    comm_from_main_queue = Queue()
    comm_to_main_queue = Queue()
    error_queue = Queue()

    board_queues = tuple((Queue(), Queue()) for _ in range(num_boards))
    da_process = DataAnalyzerProcess(
        board_queues, comm_from_main_queue, comm_to_main_queue, error_queue, beta_2_mode=True
    )
    da_items_dict = {
        "da_process": da_process,
        "board_queues": board_queues,
        "from_main_queue": comm_from_main_queue,
        "to_main_queue": comm_to_main_queue,
        "error_queue": error_queue,
    }
    yield da_items_dict
