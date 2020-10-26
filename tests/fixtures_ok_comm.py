# -*- coding: utf-8 -*-


from multiprocessing import Queue

from mantarray_desktop_app import ok_comm
from mantarray_desktop_app import OkCommunicationProcess
from mantarray_desktop_app import RunningFIFOSimulator
import pytest
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import okCFrontPanel


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
    error_queue = Queue()

    board_queues = tuple([(Queue(), Queue(), Queue(),) for _ in range(4)])
    p = OkCommunicationProcess(board_queues, error_queue)
    yield p, board_queues, error_queue
    # clean up queues to avoid broken pipe errors
    p.hard_stop()


@pytest.fixture(scope="function", name="running_process_with_simulated_board")
def fixture_running_process_with_simulated_board():
    error_queue = Queue()

    board_queues = tuple([(Queue(), Queue(), Queue(),)] * 1)
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
