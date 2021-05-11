# -*- coding: utf-8 -*-


from mantarray_desktop_app import ok_comm
from mantarray_desktop_app import OkCommunicationProcess
from mantarray_desktop_app import RunningFIFOSimulator
import pytest
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import okCFrontPanel

from .fixtures import generate_board_and_error_queues


@pytest.fixture(scope="function", name="patch_connection_to_board")
def fixture_patch_connection_to_board(mocker):
    def set_info(info):
        info.serialNumber = RunningFIFOSimulator.default_xem_serial_number
        info.deviceID = RunningFIFOSimulator.default_device_id
        return 0

    dummy_xem = okCFrontPanel()
    mocker.patch.object(dummy_xem, "GetDeviceInfo", autospec=True, side_effect=set_info)
    mocked_open_board = mocker.patch.object(ok_comm, "open_board", autospec=True, return_value=dummy_xem)
    yield dummy_xem, mocked_open_board


@pytest.fixture(scope="function", name="four_board_comm_process")
def fixture_four_board_comm_process():
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    ok_process = OkCommunicationProcess(board_queues, error_queue)
    ok_items_dict = {
        "ok_process": ok_process,
        "board_queues": board_queues,
        "error_queue": error_queue,
    }
    yield ok_items_dict


@pytest.fixture(scope="function", name="running_process_with_simulated_board")
def fixture_running_process_with_simulated_board():
    board_queues, error_queue = generate_board_and_error_queues()

    ok_process = OkCommunicationProcess(board_queues, error_queue, suppress_setup_communication_to_main=True)

    def _foo(simulator: FrontPanelSimulator):
        ok_process.set_board_connection(0, simulator)
        ok_process.start()

        ok_items_dict = {
            "ok_process": ok_process,
            "board_queues": board_queues,
            "error_queue": error_queue,
        }
        return ok_items_dict

    yield _foo

    ok_process.stop()
    ok_process.join()
