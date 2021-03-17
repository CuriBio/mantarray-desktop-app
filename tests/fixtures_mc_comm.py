# -*- coding: utf-8 -*-


from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import McCommunicationProcess
import pytest
import serial

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


@pytest.fixture(scope="function", name="patch_comports")
def fixture_patch_comports(mocker):
    comport = "COM1"
    comport_name = f"STM ({comport})"
    mocked_comports = mocker.patch.object(
        mc_comm.list_ports,
        "comports",
        autospec=True,
        return_value=["bad COM port", comport_name, "other COM port"],
    )
    yield comport, comport_name, mocked_comports


@pytest.fixture(scope="function", name="patch_serial_connection")
def fixture_patch_serial_connection(mocker):
    dummy_serial_obj = serial.Serial()

    mocked_serial = mocker.patch.object(
        mc_comm.serial, "Serial", autospec=True, return_value=dummy_serial_obj
    )
    yield dummy_serial_obj, mocked_serial
