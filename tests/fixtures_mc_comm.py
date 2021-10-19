# -*- coding: utf-8 -*-


import time

from mantarray_desktop_app import DEFAULT_MAGNETOMETER_CONFIG
from mantarray_desktop_app import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import McCommunicationProcess
from mantarray_desktop_app import STM_VID
import pytest
import serial
from serial.tools.list_ports_common import ListPortInfo
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import TestingQueue

from .fixtures import generate_board_and_error_queues
from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .fixtures_mc_simulator import MantarrayMcSimulatorNoBeacons
from .helpers import confirm_queue_is_eventually_of_size
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


def set_connection_and_register_simulator(
    mc_process_fixture,
    simulator_fixture,
):
    """Send a single status beacon in order to register magic word.

    Sets connection on board index 0.
    """
    mc_process = mc_process_fixture["mc_process"]
    output_queue = mc_process_fixture["board_queues"][0][1]
    simulator = simulator_fixture["simulator"]
    testing_queue = simulator_fixture["testing_queue"]

    num_iterations = 1
    if not isinstance(simulator, MantarrayMcSimulatorNoBeacons):
        # first iteration to send possibly truncated beacon
        invoke_process_run_and_check_errors(simulator)
        num_iterations += 1  # Tanner (4/6/21): May need to run two iterations in case the first beacon is not truncated. Not doing this will cause issues with output_queue later on
    # send single non-truncated beacon and then register with mc_process
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    mc_process.set_board_connection(0, simulator)
    invoke_process_run_and_check_errors(mc_process, num_iterations=num_iterations)
    # remove status code log message(s)
    drain_queue(output_queue)


def set_magnetometer_config_and_start_streaming(
    mc_fixture,
    simulator,
    magnetometer_config=DEFAULT_MAGNETOMETER_CONFIG,
    sampling_period=DEFAULT_SAMPLING_PERIOD,
):
    mc_process = mc_fixture["mc_process"]
    from_main_queue = mc_fixture["board_queues"][0][0]
    to_main_queue = mc_fixture["board_queues"][0][1]
    config_command = {
        "communication_type": "acquisition_manager",
        "command": "change_magnetometer_config",
        "magnetometer_config": magnetometer_config,
        "sampling_period": sampling_period,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(config_command, from_main_queue)
    # send command, process command, process command response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    start_command = {
        "communication_type": "acquisition_manager",
        "command": "start_managed_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)
    # send command, process command, process command response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)


@pytest.fixture(scope="function", name="four_board_mc_comm_process")
def fixture_four_board_mc_comm_process():
    # Tests using this fixture should be responsible for cleaning up the queues
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4, queue_type=TestingQueue)
    mc_process = McCommunicationProcess(board_queues, error_queue)

    items_dict = {
        "mc_process": mc_process,
        "board_queues": board_queues,
        "error_queue": error_queue,
    }
    yield items_dict


@pytest.fixture(scope="function", name="runnable_four_board_mc_comm_process")
def fixture_runnable_four_board_mc_comm_process():
    # Tests using this fixture should be responsible for cleaning up the queues
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    mc_process = McCommunicationProcess(board_queues, error_queue)

    items_dict = {
        "mc_process": mc_process,
        "board_queues": board_queues,
        "error_queue": error_queue,
    }
    yield items_dict


class McCommunicationProcessNoHandshakes(McCommunicationProcess):
    def _send_handshake(self, board_idx: int) -> None:
        self._time_of_last_handshake_secs = time.perf_counter()

    def start(self) -> None:
        raise NotImplementedError("This class is only for unit tests not requiring a running process")


@pytest.fixture(scope="function", name="four_board_mc_comm_process_no_handshake")
def fixture_four_board_mc_comm_process_no_handshake():
    # Tests using this fixture should be responsible for cleaning up the queues
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4, queue_type=TestingQueue)
    mc_process = McCommunicationProcessNoHandshakes(board_queues, error_queue)

    items_dict = {
        "mc_process": mc_process,
        "board_queues": board_queues,
        "error_queue": error_queue,
    }
    yield items_dict


@pytest.fixture(scope="function", name="patch_comports")
def fixture_patch_comports(mocker):
    comport = "COM1"

    dummy_port_info = ListPortInfo("")
    dummy_port_info.vid = STM_VID
    dummy_port_info.name = comport
    dummy_port_info.description = f"Device ({comport})"

    mocked_comports = mocker.patch.object(
        mc_comm.list_ports,
        "comports",
        autospec=True,
        return_value=[dummy_port_info],
    )
    yield comport, dummy_port_info.description, mocked_comports


@pytest.fixture(scope="function", name="patch_serial_connection")
def fixture_patch_serial_connection(mocker):
    dummy_serial_obj = serial.Serial()

    mocked_serial = mocker.patch.object(
        mc_comm.serial, "Serial", autospec=True, return_value=dummy_serial_obj
    )
    yield dummy_serial_obj, mocked_serial
