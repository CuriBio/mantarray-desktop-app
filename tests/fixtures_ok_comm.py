# -*- coding: utf-8 -*-


from multiprocessing import Queue
from typing import Any
from typing import Dict
from typing import Tuple

from mantarray_desktop_app import ok_comm
from mantarray_desktop_app import OkCommunicationProcess
from mantarray_desktop_app import RunningFIFOSimulator
import pytest
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import okCFrontPanel


def generate_board_and_error_queues(num_boards: int = 4):
    error_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Tuple[Exception, str]
    ] = Queue()

    board_queues: Tuple[  # pylint-disable: duplicate-code
        Tuple[
            Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
            Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
            Queue[Any],  # pylint: disable=unsubscriptable-object
        ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
    ] = tuple(
        (
            (
                Queue(),
                Queue(),
                Queue(),
            )
            for _ in range(num_boards)
        )
    )
    return board_queues, error_queue


@pytest.fixture(scope="function", name="patch_connection_to_board")
def fixture_patch_connection_to_board(mocker):
    def set_info(info):
        info.serialNumber = RunningFIFOSimulator.default_xem_serial_number
        info.deviceID = RunningFIFOSimulator.default_device_id
        return 0

    dummy_xem = okCFrontPanel()
    mocker.patch.object(dummy_xem, "GetDeviceInfo", autospec=True, side_effect=set_info)
    mocked_open_board = mocker.patch.object(
        ok_comm, "open_board", autospec=True, return_value=dummy_xem
    )
    yield dummy_xem, mocked_open_board


@pytest.fixture(scope="function", name="four_board_comm_process")
def fixture_four_board_comm_process():
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    p = OkCommunicationProcess(board_queues, error_queue)
    yield p, board_queues, error_queue
    # clean up queues to avoid broken pipe errors
    p.hard_stop()


@pytest.fixture(scope="function", name="running_process_with_simulated_board")
def fixture_running_process_with_simulated_board():
    board_queues, error_queue = generate_board_and_error_queues()

    p = OkCommunicationProcess(
        board_queues, error_queue, suppress_setup_communication_to_main=True
    )

    def _foo(simulator: FrontPanelSimulator):
        p.set_board_connection(0, simulator)
        p.start()

        return p, board_queues, error_queue

    yield _foo

    p.stop()
    p.join()
