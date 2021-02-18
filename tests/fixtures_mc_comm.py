# -*- coding: utf-8 -*-


from mantarray_desktop_app import McCommunicationProcess
import pytest

from .fixtures import generate_board_and_error_queues


@pytest.fixture(scope="function", name="four_board_mc_comm_process")
def fixture_four_board_mc_comm_process():
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    p = McCommunicationProcess(board_queues, error_queue)
    yield p, board_queues, error_queue
    # clean up queues to avoid broken pipe errors
    p.hard_stop()
