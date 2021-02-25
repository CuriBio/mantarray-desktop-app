# -*- coding: utf-8 -*-


from mantarray_desktop_app import McCommunicationProcess
import pytest

from .fixtures import generate_board_and_error_queues


@pytest.fixture(scope="function", name="four_board_mc_comm_process")
def fixture_four_board_mc_comm_process():
    # Tests using this fixture should be responsible for cleaning up the queues
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    mc_process = McCommunicationProcess(board_queues, error_queue)

    items_dict = {
        "mc_process": mc_process,
        "board_queues": board_queues,
        "error_queue": error_queue,
    }
    yield items_dict
