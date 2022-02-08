# -*- coding: utf-8 -*-
import copy
import datetime
import json
import os
import struct
import tempfile

from freezegun import freeze_time
from mantarray_desktop_app import BARCODE_VALID_UUID
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import get_redacted_string
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import ok_comm
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import redact_sensitive_info_from_path
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERIAL_COMM_DEFAULT_DATA_CHANNEL
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app import server
from mantarray_desktop_app import utils
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import PLATE_BARCODE_UUID
from pulse3D.constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from pulse3D.constants import UTC_BEGINNING_RECORDING_UUID
import pytest
import requests
from stdlib_utils import confirm_parallelism_is_stopped
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import TestingQueue
from xem_wrapper import DATA_FRAME_SIZE_WORDS
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import OpalKellyFileNotFoundError
from xem_wrapper import PIPE_OUT_FIFO

from ..fixtures import fixture_generic_queue_container
from ..fixtures import fixture_patch_print
from ..fixtures import fixture_patched_firmware_folder
from ..fixtures import fixture_patched_short_calibration_script
from ..fixtures import fixture_patched_test_xem_scripts_folder
from ..fixtures import fixture_patched_xem_scripts_folder
from ..fixtures import fixture_test_process_manager_creator
from ..fixtures import GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
from ..fixtures import GENERIC_STORED_CUSTOMER_ID
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import GENERIC_BETA_1_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import populate_calibration_folder
from ..fixtures_mc_simulator import create_random_stim_info
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_process_monitor import fixture_test_monitor
from ..fixtures_server import fixture_client_and_server_manager_and_shared_values
from ..fixtures_server import fixture_server_manager
from ..fixtures_server import fixture_test_client
from ..fixtures_server import put_generic_beta_1_start_recording_info_in_dict
from ..fixtures_server import put_generic_beta_2_start_recording_info_in_dict
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import convert_after_request_log_msg_to_json
from ..helpers import is_queue_eventually_not_empty
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_client_and_server_manager_and_shared_values,
    fixture_server_manager,
    fixture_generic_queue_container,
    fixture_test_process_manager_creator,
    fixture_test_client,
    fixture_test_monitor,
    fixture_patched_firmware_folder,
    fixture_patched_short_calibration_script,
    fixture_patched_test_xem_scripts_folder,
    fixture_patched_xem_scripts_folder,
    fixture_patch_print,
]


def set_connection_to_beta_1_board(ok_process, initialize_board=True):
    simulator = FrontPanelSimulator({})
    if initialize_board:
        simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)


def test_send_single_set_mantarray_nickname_command__gets_processed_and_stores_nickname_in_shared_values_dict(
    test_monitor, test_client, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    expected_nickname = "Surnom Français"

    ok_process = test_process_manager.get_instrument_process()
    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    comm_from_server_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    response = test_client.get(f"/set_mantarray_nickname?nickname={expected_nickname}")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_from_server_queue, 1)

    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["mantarray_nickname"][0] == expected_nickname
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    set_connection_to_beta_1_board(ok_process)
    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_empty(comm_to_ok_queue)

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_nickname"
    assert communication["mantarray_nickname"] == expected_nickname


def test_send_single_start_calibration_command__gets_processed_and_sets_system_status_to_calibrating(
    patched_short_calibration_script,
    test_monitor,
    test_client,
    test_process_manager_creator,
    mocker,
):
    # patch to speed up test
    mocker.patch.object(ok_comm, "sleep", autospec=True)

    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    shared_values_dict["system_status"] = CALIBRATED_STATE

    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process, initialize_board=False)
    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_server_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    response = test_client.get("/insert_xem_command_into_queue/initialize_board")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)
    response = test_client.get("/start_calibration")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_from_server_queue, 1)

    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == CALIBRATING_STATE
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 2)

    invoke_process_run_and_check_errors(ok_process, num_iterations=2)
    comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # pull initialize board response message
    # explicitly checking that queue is not empty here
    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    expected_script_type = "start_calibration"
    script_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert script_communication["communication_type"] == "xem_scripts"
    assert script_communication["script_type"] == expected_script_type
    assert f"Running {expected_script_type} script" in script_communication["response"]
    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    queue_items = drain_queue(comm_from_ok_queue)
    done_message = queue_items[-1]
    assert done_message["communication_type"] == "xem_scripts"
    assert done_message["response"] == f"'{expected_script_type}' script complete."


# Keep this "gets_processed" test with fully running processes
@pytest.mark.slow
def test_send_single_initialize_board_command_with_bit_file__gets_processed(
    test_process_manager_creator, test_client, patched_firmware_folder
):
    board_idx = 0
    expected_bit_file_name = patched_firmware_folder

    simulator = FrontPanelSimulator({})

    test_process_manager = test_process_manager_creator()
    ok_process = test_process_manager.get_instrument_process()
    ok_process.set_board_connection(board_idx, simulator)

    test_process_manager.start_processes()

    response = test_client.get(
        f"/insert_xem_command_into_queue/initialize_board?bit_file_name={expected_bit_file_name}"
    )
    assert response.status_code == 200
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(
        board_idx
    )
    confirm_queue_is_eventually_empty(comm_to_ok_queue)

    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(board_idx)
    )
    comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    initialize_board_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert initialize_board_communication["command"] == "initialize_board"
    assert initialize_board_communication["bit_file_name"] == expected_bit_file_name
    assert initialize_board_communication["allow_board_reinitialization"] is False
    get_status_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert get_status_communication["response"]["bit_file_name"] == expected_bit_file_name

    # clean up
    test_process_manager.hard_stop_and_join_processes()


def test_send_single_initialize_board_command_without_bit_file__gets_processed(
    test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)

    board_idx = 0
    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process, initialize_board=False)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(
        board_idx
    )
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(board_idx)
    )

    response = test_client.get("/insert_xem_command_into_queue/initialize_board")
    assert response.status_code == 200
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 2)

    invoke_process_run_and_check_errors(ok_process, num_iterations=2)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 2)

    initialize_board_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert initialize_board_communication["command"] == "initialize_board"
    assert initialize_board_communication["bit_file_name"] is None
    assert initialize_board_communication["allow_board_reinitialization"] is False
    get_status_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert get_status_communication["response"]["bit_file_name"] is None


def test_send_single_initialize_board_command_with_reinitialization__gets_processed(
    test_process_manager_creator, test_client, patched_firmware_folder
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)

    board_idx = 0
    expected_bit_file_name = patched_firmware_folder
    expected_reinitialization = True

    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process, initialize_board=False)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(
        board_idx
    )
    confirm_queue_is_eventually_empty(comm_to_ok_queue)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(board_idx)
    )

    response = test_client.get(
        f"/insert_xem_command_into_queue/initialize_board?bit_file_name={expected_bit_file_name}&allow_board_reinitialization={expected_reinitialization}"
    )
    assert response.status_code == 200
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 2)

    invoke_process_run_and_check_errors(ok_process, num_iterations=2)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 2)

    initialize_board_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert initialize_board_communication["command"] == "initialize_board"
    assert initialize_board_communication["bit_file_name"] == expected_bit_file_name
    assert initialize_board_communication["allow_board_reinitialization"] is True
    get_status_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert get_status_communication["response"]["bit_file_name"] == expected_bit_file_name


def test_send_single_activate_trigger_in_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    expected_ep_addr = 10
    expected_bit = 0x00000002
    response = test_client.get(
        f"/insert_xem_command_into_queue/activate_trigger_in?ep_addr={expected_ep_addr}&bit={expected_bit}"
    )
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "activate_trigger_in"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["bit"] == expected_bit


def test_send_single_comm_delay_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    expected_num_millis = 100
    response = test_client.get(
        f"/insert_xem_command_into_queue/comm_delay?num_milliseconds={expected_num_millis}"
    )
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "comm_delay"
    assert communication["num_milliseconds"] == expected_num_millis
    assert communication["response"] == f"Delayed for {expected_num_millis} milliseconds"


def test_send_single_get_num_words_fifo_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    expected_num_words = DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN
    test_bytearray = bytearray(expected_num_words * 4)
    fifo = TestingQueue()
    fifo.put_nowait(test_bytearray)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    response = test_client.get("/insert_xem_command_into_queue/get_num_words_fifo")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "get_num_words_fifo"
    assert communication["response"] == expected_num_words
    assert communication["hex_converted_response"] == hex(expected_num_words)


def test_send_single_set_device_id_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    test_id = "Mantarray XEM"
    response = test_client.get(f"/insert_xem_command_into_queue/set_device_id?new_id={test_id}")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "set_device_id"
    assert communication["new_id"] == test_id


def test_send_single_stop_acquisition_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process.set_board_connection(0, simulator)

    response = test_client.get("/insert_xem_command_into_queue/stop_acquisition")
    assert response.status_code == 200
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 2)

    invoke_process_run_and_check_errors(ok_process, num_iterations=2)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 2)

    stop_acquisition_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert stop_acquisition_communication["command"] == "stop_acquisition"
    get_status_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert get_status_communication["response"]["is_spi_running"] is False


def test_send_single_start_acquisition_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    response = test_client.get("/insert_xem_command_into_queue/start_acquisition")
    assert response.status_code == 200
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 2)

    invoke_process_run_and_check_errors(ok_process, num_iterations=2)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 2)

    start_acquisition_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert start_acquisition_communication["command"] == "start_acquisition"
    get_status_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert get_status_communication["response"]["is_spi_running"] is True


def test_send_single_get_serial_number_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    response = test_client.get("/insert_xem_command_into_queue/get_serial_number")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "get_serial_number"
    assert communication["response"] == "1917000Q70"


def test_send_single_get_device_id_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    simulator = FrontPanelSimulator({})
    expected_id = "Mantarray XEM"
    simulator.set_device_id(expected_id)
    ok_process.set_board_connection(0, simulator)

    response = test_client.get("/insert_xem_command_into_queue/get_device_id")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "get_device_id"
    assert communication["response"] == expected_id


def test_send_single_is_spi_running_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    response = test_client.get("/insert_xem_command_into_queue/is_spi_running")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "is_spi_running"
    assert communication["response"] is False


@pytest.mark.parametrize(
    ",".join(("test_num_words_to_log", "test_description")),
    [
        (1, "logs 1 word"),
        (72, "logs 72 words"),
        (73, "logs 72 words given 73 num words to log"),
    ],
)
def test_read_from_fifo_command__is_received_by_ok_comm__with_correct_num_words_to_log(
    test_num_words_to_log, test_description, test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    test_bytearray = produce_data(1, 0)
    fifo = TestingQueue()
    fifo.put_nowait(test_bytearray)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process.set_board_connection(0, simulator)

    response = test_client.get(
        f"/insert_xem_command_into_queue/read_from_fifo?num_words_to_log={test_num_words_to_log}"
    )
    assert response.status_code == 200
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "read_from_fifo"
    assert communication["num_words_to_log"] == test_num_words_to_log


# Tanner (12/30/20): This test was previously parametrized which is unnecessary since the same parametrization is done in test_OkCommunicationProcess_run__processes_read_from_fifo_debug_console_command in test_ok_comm_debug_console.py
def test_send_single_read_from_fifo_command__gets_processed_with_correct_num_words(
    test_process_manager_creator,
    test_client,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    test_bytearray = produce_data(1, 0)
    fifo = TestingQueue()
    fifo.put_nowait(test_bytearray)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process.set_board_connection(0, simulator)

    test_num_words_to_log = 72
    response = test_client.get(
        f"/insert_xem_command_into_queue/read_from_fifo?num_words_to_log={test_num_words_to_log}"
    )
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    total_num_words = len(test_bytearray) // 4
    test_words = struct.unpack(f"<{total_num_words}L", test_bytearray)
    expected_formatted_response = list()
    num_words_to_log = min(total_num_words, test_num_words_to_log)
    for i in range(num_words_to_log):
        expected_formatted_response.append(hex(test_words[i]))
    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "read_from_fifo"
    assert communication["response"] == expected_formatted_response


def test_send_single_set_wire_in_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    expected_ep_addr = 6
    expected_value = 0x00000011
    expected_mask = 0x00000011
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_wire_in?ep_addr={expected_ep_addr}&value={expected_value}&mask={expected_mask}"
    )
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "set_wire_in"
    assert communication["ep_addr"] == expected_ep_addr


def test_send_xem_scripts_command__gets_processed(
    test_process_manager_creator, test_client, patched_test_xem_scripts_folder, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    simulator = RunningFIFOSimulator()
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    expected_script_type = "test_script"
    response = test_client.get(f"/xem_scripts?script_type={expected_script_type}")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)

    script_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert script_communication["script_type"] == expected_script_type
    assert f"Running {expected_script_type} script" in script_communication["response"]

    done_message = drain_queue(comm_from_ok_queue)[-1]
    assert done_message["communication_type"] == "xem_scripts"
    assert done_message["response"] == f"'{expected_script_type}' script complete."


def test_send_single_read_wire_out_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    wire_queue = TestingQueue()
    expected_wire_out_response = 33
    wire_queue.put_nowait(expected_wire_out_response)

    expected_ep_addr = 7
    simulator = FrontPanelSimulator({"wire_outs": {expected_ep_addr: wire_queue}})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    test_route = f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}"
    response = test_client.get(test_route)
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "read_wire_out"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["response"] == expected_wire_out_response
    assert communication["hex_converted_response"] == hex(expected_wire_out_response)


def test_send_single_stop_managed_acquisition_command__gets_processed(
    test_monitor, test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE

    ok_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    to_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    to_file_writer_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    to_da_queue = test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    comm_from_fw_queue = (
        test_process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
    )
    comm_from_da_queue = (
        test_process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
    )

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process.set_board_connection(0, simulator)

    response = test_client.get("/stop_managed_acquisition")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_of_size(to_instrument_comm_queue, 1)
    confirm_queue_is_eventually_of_size(to_file_writer_queue, 1)
    confirm_queue_is_eventually_of_size(to_da_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "stop_managed_acquisition"

    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_of_size(comm_from_fw_queue, 1)
    communication = comm_from_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "command_receipt"
    assert communication["command"] == "stop_managed_acquisition"

    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(comm_from_da_queue, 1)
    communication = comm_from_da_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "stop_managed_acquisition"


def test_send_single_set_mantarray_serial_number_command__gets_processed_and_stores_serial_number_in_shared_values_dict(
    test_monitor, test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process)

    expected_serial_number = "M02001901"
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={expected_serial_number}"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["mantarray_serial_number"][0] == expected_serial_number
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_serial_number"
    assert communication["mantarray_serial_number"] == expected_serial_number


def test_send_single_boot_up_command__gets_processed_and_sets_system_status_to_instrument_initializing(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    test_monitor,
    test_process_manager_creator,
    test_client,
    mocker,
):
    # patch to speed up test
    mocker.patch.object(ok_comm, "sleep", autospec=True)

    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    server_to_main = test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    ok_process = test_process_manager.get_instrument_process()
    simulator = RunningFIFOSimulator()
    ok_process.set_board_connection(0, simulator)

    response = test_client.get("/boot_up")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(server_to_main, 1)

    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == INSTRUMENT_INITIALIZING_STATE
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 2)

    invoke_process_run_and_check_errors(ok_process, num_iterations=2)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 4)

    expected_bit_file_name = patched_firmware_folder
    initialize_board_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert initialize_board_communication["command"] == "initialize_board"
    assert expected_bit_file_name in initialize_board_communication["bit_file_name"]
    assert initialize_board_communication["allow_board_reinitialization"] is False

    expected_script_type = "start_up"
    script_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert script_communication["communication_type"] == "xem_scripts"
    assert script_communication["script_type"] == expected_script_type
    assert f"Running {expected_script_type} script" in script_communication["response"]

    # remove remaining items
    drain_queue(comm_from_ok_queue)


def test_send_single_boot_up_command__populates_ok_comm_error_queue_if_bit_file_cannot_be_found(
    patch_print, test_monitor, test_process_manager_creator, test_client, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    ok_process = test_process_manager.get_instrument_process()
    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    ok_comm_error_queue = test_process_manager.queue_container().get_instrument_communication_error_queue()

    mocker.patch.object(process_manager, "get_latest_firmware", autospec=True, return_value="fake.bit")

    response = test_client.get("/boot_up")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == INSTRUMENT_INITIALIZING_STATE
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 2)

    ok_process.run(num_iterations=2)
    confirm_queue_is_eventually_of_size(ok_comm_error_queue, 1)

    error_info = ok_comm_error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual_exception, _ = error_info
    assert isinstance(actual_exception, OpalKellyFileNotFoundError) is True
    assert "fake.bit" in str(actual_exception)

    # prevent BrokenPipeErrors
    drain_queue(comm_from_ok_queue)


def test_send_single_start_managed_acquisition_command__sets_system_status_to_buffering__and_clears_data_analyzer_outgoing_queue(
    test_process_manager_creator, test_client, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    board_idx = 0
    shared_values_dict["mantarray_serial_number"] = {
        board_idx: RunningFIFOSimulator.default_mantarray_serial_number
    }

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    comm_from_da_queue = (
        test_process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
    )
    to_da_queue = test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    outgoing_data_queue = test_process_manager.queue_container().get_data_analyzer_data_out_queue()

    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process)
    da_process = test_process_manager.get_data_analyzer_process()

    dummy_data = {"well_index": 0, "data": [[0, 1], [100, 200]]}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(dummy_data, outgoing_data_queue)

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == BUFFERING_STATE
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)
    confirm_queue_is_eventually_of_size(to_da_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    invoke_process_run_and_check_errors(da_process)

    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_managed_acquisition"
    assert "timestamp" in communication

    confirm_queue_is_eventually_of_size(comm_from_da_queue, 1)
    communication = comm_from_da_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_managed_acquisition"

    # clean up teardown messages in Instrument Comm queue
    drain_queue(comm_from_ok_queue)


def test_update_settings__stores_values_in_shared_values_dict__and_recordings_folder_in_file_writer_and_process_manager__and_logs_recording_folder_with_sensitive_info_redacted(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    spied_utils_logger = mocker.spy(utils.logger, "info")

    expected_customer_uuid = "test_id"
    expected_customer_pass_key = "test_password"

    shared_values_dict["stored_customer_settings"] = {"stored_customer_id": GENERIC_STORED_CUSTOMER_ID}
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = test_client.get(
            f"/update_settings?customer_account_uuid={expected_customer_uuid}&customer_pass_key={expected_customer_pass_key}&user_account_id=test_user&recording_directory={expected_recordings_dir}"
        )
        assert response.status_code == 200
        invoke_process_run_and_check_errors(monitor_thread)

        assert shared_values_dict["config_settings"]["customer_account_id"] == expected_customer_uuid
        assert shared_values_dict["config_settings"]["recording_directory"] == expected_recordings_dir
        assert test_process_manager.get_file_directory() == expected_recordings_dir

        scrubbed_recordings_dir = redact_sensitive_info_from_path(expected_recordings_dir)
        spied_utils_logger.assert_any_call(f"Using directory for recording files: {scrubbed_recordings_dir}")

    queue_from_main_to_file_writer = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    confirm_queue_is_eventually_of_size(queue_from_main_to_file_writer, 2)

    # clean up the message that goes to file writer to update the recording directory
    drain_queue(queue_from_main_to_file_writer)


def test_update_settings__replaces_only_new_values_in_shared_values_dict(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    mocker.patch.object(utils, "validate_customer_credentials", autospec=True)

    expected_customer_uuid = "test_id"
    expected_customer_pass_key = "test_password"

    shared_values_dict["stored_customer_settings"] = {"stored_customer_id": GENERIC_STORED_CUSTOMER_ID}
    shared_values_dict["config_settings"] = {
        "customer_account_id": "2dc06596-9cea-46a2-9ddd-a0d8a0f13584",
        "customer_pass_key": "other_password",
        "user_account_id": "other_user",
    }

    response = test_client.get(
        f"/update_settings?customer_account_uuid={expected_customer_uuid}&customer_pass_key={expected_customer_pass_key}&user_account_id=test_user"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["config_settings"]["customer_account_id"] == expected_customer_uuid
    assert shared_values_dict["config_settings"]["customer_pass_key"] == expected_customer_pass_key


def test_update_settings__errors_when_any_combo_of_invalid_customer_credits_gets_checked_against_stored_pairs(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    expected_customer_uuid = "test_id"
    expected_customer_pass_key = "test_password"

    shared_values_dict["stored_customer_settings"] = {"stored_customer_id": GENERIC_STORED_CUSTOMER_ID}

    response = test_client.get(
        f"/update_settings?customer_account_uuid={expected_customer_uuid}&customer_pass_key=wrong_password&user_account_id=test_user"
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert response.status_code == 401

    response = test_client.get(
        f"/update_settings?customer_account_uuid=wrong_customer_id&customer_pass_key={expected_customer_pass_key}&user_account_id=test_user"
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert response.status_code == 401

    response = test_client.get(
        f"/update_settings?customer_account_uuid={expected_customer_uuid}&customer_pass_key={expected_customer_pass_key}&user_account_id=wrong_user"
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert response.status_code == 200


def test_update_settings__errors_when_any_combo_of_invalid_customer_credits_gets_checked_against_aws_get_auth(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    expected_customer_uuid = "new_id"
    expected_customer_pass_key = "test_password"
    shared_values_dict["stored_customer_settings"] = {"stored_customer_id": GENERIC_STORED_CUSTOMER_ID}
    response = test_client.get(
        f"/update_settings?customer_account_uuid={expected_customer_uuid}&customer_pass_key={expected_customer_pass_key}"
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert response.status_code == 401

    mocked_post = mocker.patch.object(requests, "post", autospec=True)
    mocked_post.return_value.status_code = 200
    response = test_client.get(
        f"/update_settings?customer_account_uuid={expected_customer_uuid}&customer_pass_key={expected_customer_pass_key}"
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert response.status_code == 200


def test_update_settings__returns_boolean_values_for_auto_upload_delete_values(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    shared_values_dict["stored_customer_settings"] = {"stored_customer_id": GENERIC_STORED_CUSTOMER_ID}
    shared_values_dict["config_settings"] = {
        "auto_upload_on_completion": True,
        "auto_delete_local_files": False,
    }

    response = test_client.get("/update_settings?auto_upload=false&auto_delete=true")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["config_settings"]["auto_upload_on_completion"] is False
    assert shared_values_dict["config_settings"]["auto_delete_local_files"] is True


def test_shutdown__logs_will_only_be_uploaded_when_called_from_electron(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, _, *_ = test_monitor(test_process_manager)

    mocked_upload_util = mocker.patch.object(server, "upload_log_files_to_s3", autospec=True)

    mocker.patch.object(server, "wait_for_subprocesses_to_stop", autospec=True)
    mocker.patch.object(monitor_thread, "_hard_stop_and_join_processes_and_log_leftovers", autospec=True)

    response = test_client.get("/shutdown?called_through_app_will_quit=true")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert len(mocked_upload_util.call_args_list) == 1


def test_shutdown__log_files_will_not_be_uploaded_unless_customer_creds_have_been_entered(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, _, *_ = test_monitor(test_process_manager)
    spied_utils_logger = mocker.spy(utils.logger, "info")

    mocker.patch.object(server, "wait_for_subprocesses_to_stop", autospec=True)
    mocker.patch.object(monitor_thread, "_hard_stop_and_join_processes_and_log_leftovers", autospec=True)

    response = test_client.get("/shutdown?called_through_app_will_quit=true")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    spied_utils_logger.assert_any_call(
        "Log upload to s3 has been prevented because no customer account was found"
    )


def test_shutdown__upload_of_log_files_will_log_if_error_in_upload_thread(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["config_settings"] = {
        "customer_account_id": "test_id",
        "customer_pass_key": "test_pass",
        "log_directory": "/Users/fake/directory",
    }
    spied_utils_logger = mocker.spy(utils.logger, "error")
    mocker.patch.object(utils, "uploader", autospec=True, side_effect=Exception("mocked_error"))

    mocker.patch.object(server, "wait_for_subprocesses_to_stop", autospec=True)
    mocker.patch.object(monitor_thread, "_hard_stop_and_join_processes_and_log_leftovers", autospec=True)

    response = test_client.get("/shutdown?called_through_app_will_quit=true")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    spied_utils_logger.assert_any_call("Failed to upload log files to s3: mocked_error")


def test_shutdown__upload_of_log_files_will_log_success(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["config_settings"] = {
        "customer_account_id": "test_id",
        "customer_pass_key": "test_pass",
        "log_directory": "/Users/fake/directory",
    }
    spied_utils_logger = mocker.spy(utils.logger, "info")
    mocker.patch.object(utils, "uploader", autospec=True, return_value=None)

    mocker.patch.object(server, "wait_for_subprocesses_to_stop", autospec=True)
    mocker.patch.object(monitor_thread, "_hard_stop_and_join_processes_and_log_leftovers", autospec=True)

    response = test_client.get("/shutdown?called_through_app_will_quit=true")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    spied_utils_logger.assert_any_call("Successfully uploaded session logs to s3 at shutdown")


def test_single_update_settings_command_with_recording_dir__gets_processed_by_FileWriter(
    test_process_manager_creator, test_client, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    fw_process = test_process_manager.get_file_writer_process()
    to_fw_queue = test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    from_fw_queue = test_process_manager.queue_container().get_communication_queue_from_file_writer_to_main()

    shared_values_dict["stored_customer_settings"] = {"stored_customer_id": GENERIC_STORED_CUSTOMER_ID}
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = test_client.get(f"/update_settings?recording_directory={expected_recordings_dir}")
        assert response.status_code == 200
        invoke_process_run_and_check_errors(monitor_thread)
        confirm_queue_is_eventually_of_size(to_fw_queue, 1)

        invoke_process_run_and_check_errors(fw_process)
        confirm_queue_is_eventually_of_size(from_fw_queue, 1)

        communication = from_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert communication["command"] == "update_directory"
        assert communication["new_directory"] == expected_recordings_dir


def test_stop_recording_command__sets_system_status_to_live_view_active(
    test_process_manager_creator, test_client, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=6, day=2, hour=17, minute=9, second=22, microsecond=362490
    )
    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [expected_acquisition_timestamp]

    response = test_client.get("/stop_recording")
    assert response.status_code == 200

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["system_status"] == LIVE_VIEW_ACTIVE_STATE

    queue_from_main_to_file_writer = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )

    # clean up the message that goes to file writer to stop the recording
    drain_queue(queue_from_main_to_file_writer)


def test_stop_recording_command__is_received_by_file_writer__with_given_time_index_parameter(
    test_process_manager_creator, test_client, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332597
    )
    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [expected_acquisition_timestamp]

    expected_time_index = 9600
    comm_to_fw_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    response = test_client.get(f"/stop_recording?time_index={expected_time_index}")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_not_empty(comm_to_fw_queue) is True

    response_json = response.get_json()
    assert response_json["command"] == "stop_recording"

    file_writer_process = test_process_manager.get_file_writer_process()
    invoke_process_run_and_check_errors(file_writer_process)
    confirm_queue_is_eventually_empty(comm_to_fw_queue)

    file_writer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
    )
    confirm_queue_is_eventually_of_size(file_writer_to_main, 1)

    communication = file_writer_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "stop_recording"

    assert communication["timepoint_to_stop_recording_at"] == (
        expected_time_index / MICROSECONDS_PER_CENTIMILLISECOND
    )


def test_start_recording__returns_error_code_and_message_if_called_with_is_hardware_test_mode_false_when_previously_true(
    test_process_manager_creator,
    test_client,
    test_monitor,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)

    shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE
    response = test_client.get("/start_recording?barcode=MA200440001&is_hardware_test_recording=True")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE
    response = test_client.get("/start_recording?barcode=MA200440001&is_hardware_test_recording=False")
    assert response.status_code == 403
    assert (
        response.status.endswith(
            "Cannot make standard recordings after previously making hardware test recordings. Server and board must both be restarted before making any more standard recordings"
        )
        is True
    )


@freeze_time(
    GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ]
)
def test_start_recording_command__gets_processed_with_given_time_index_parameter(
    test_process_manager_creator,
    test_client,
    mocker,
    test_monitor,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)

    fw_process = test_process_manager.get_file_writer_process()
    to_fw_queue = test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    fw_error_queue = test_process_manager.queue_container().get_file_writer_error_queue()

    expected_time_index = 9600
    timestamp_str = (
        GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        + datetime.timedelta(seconds=(expected_time_index / CENTIMILLISECONDS_PER_SECOND))
    ).strftime("%Y_%m_%d_%H%M%S")
    shared_values_dict[  # pylint: disable=duplicate-code
        "utc_timestamps_of_beginning_of_data_acquisition"
    ] = [
        GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
    ]

    expected_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&active_well_indices=3&time_index={expected_time_index}"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == RECORDING_STATE
    assert shared_values_dict["is_hardware_test_recording"] is True
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)

    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(fw_error_queue)

    file_dir = fw_process.get_file_directory()
    actual_files = os.listdir(os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}"))
    assert actual_files == [f"{expected_barcode}__{timestamp_str}__D1.h5"]


@freeze_time(
    GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ]
    + datetime.timedelta(
        seconds=GENERIC_BETA_1_START_RECORDING_COMMAND[  # pylint: disable=duplicate-code
            "timepoint_to_begin_recording_at"
        ]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_start_recording_command__gets_processed_in_beta_1_mode__and_creates_a_file__and_updates_shared_values_dict(
    test_process_manager_creator,
    test_client,
    mocker,
    test_monitor,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)

    fw_process = test_process_manager.get_file_writer_process()
    to_fw_queue = test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    fw_error_queue = test_process_manager.queue_container().get_file_writer_error_queue()

    timestamp_str = (
        GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        + datetime.timedelta(
            seconds=GENERIC_BETA_1_START_RECORDING_COMMAND[  # pylint: disable=duplicate-code
                "timepoint_to_begin_recording_at"
            ]
            / CENTIMILLISECONDS_PER_SECOND
        )
    ).strftime("%Y_%m_%d_%H%M%S")

    expected_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&active_well_indices=3&is_hardware_test_recording=False"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == RECORDING_STATE
    assert shared_values_dict["is_hardware_test_recording"] is False
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)

    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(fw_error_queue)

    file_dir = fw_process.get_file_directory()
    actual_files = os.listdir(os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}"))
    assert actual_files == [f"{expected_barcode}__2020_02_09_190935__D1.h5"]


@freeze_time(
    GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_RECORDING_UUID
    ]
)
def test_start_recording_command__gets_processed_in_beta_2_mode__and_creates_a_file__and_updates_shared_values_dict(
    test_process_manager_creator,
    test_client,
    mocker,
    test_monitor,
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)

    shared_values_dict["stimulation_info"] = create_random_stim_info()

    fw_process = test_process_manager.get_file_writer_process()
    populate_calibration_folder(fw_process)
    to_fw_queue = test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    fw_error_queue = test_process_manager.queue_container().get_file_writer_error_queue()

    # set up config so only one well has a channel enabled
    test_magnetometer_config = create_magnetometer_config_dict(24)
    test_magnetometer_config[SERIAL_COMM_WELL_IDX_TO_MODULE_ID[3]][0] = True
    shared_values_dict["magnetometer_config_dict"]["magnetometer_config"] = test_magnetometer_config

    timestamp_str = GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_RECORDING_UUID
    ].strftime("%Y_%m_%d_%H%M%S")
    expected_barcode = GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]

    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&is_hardware_test_recording=False"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == RECORDING_STATE
    assert shared_values_dict["is_hardware_test_recording"] is False
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)

    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(fw_error_queue)

    file_dir = fw_process.get_file_directory()
    actual_files = os.listdir(os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}"))
    actual_files = [file_path for file_path in actual_files if "Calibration" not in file_path]
    assert actual_files == [f"{expected_barcode}__{timestamp_str}__D1.h5"]


def test_send_single_get_status_command__gets_processed(test_process_manager_creator, test_client):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    ok_process = test_process_manager.get_instrument_process()
    set_connection_to_beta_1_board(ok_process, initialize_board=False)

    comm_to_ok_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    comm_from_ok_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(comm_to_ok_queue, 1)

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(comm_from_ok_queue, 1)

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "get_status"
    assert communication["response"] == {
        "is_spi_running": False,
        "is_board_initialized": False,
        "bit_file_name": None,
    }


def test_system_status__returns_correct_plate_barcode_and_status__only_when_barcode_changes(
    test_process_manager_creator,
    test_monitor,
    test_client,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    expected_status = BARCODE_VALID_UUID
    expected_barcode = "MA200190000"
    expected_board_idx = 0
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["barcodes"] = {
        expected_board_idx: {
            "plate_barcode": expected_barcode,
            "barcode_status": expected_status,
            "frontend_needs_barcode_update": True,
        }
    }

    response = test_client.get("/system_status")
    assert response.status_code == 200
    response_json = response.get_json()
    assert response_json["barcode_status"] == str(expected_status)
    assert response_json["plate_barcode"] == expected_barcode

    invoke_process_run_and_check_errors(monitor_thread)
    response = test_client.get("/system_status")
    assert response.status_code == 200
    response_json = response.get_json()
    assert "barcode_status" not in response_json
    assert "plate_barcode" not in response_json


def test_set_magnetometer_config__gets_processed__and_default_channel_is_enabled(
    test_process_manager_creator, test_monitor, test_client
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = CALIBRATED_STATE
    assert "magnetometer_config_dict" not in shared_values_dict

    test_num_wells = 24
    expected_config_dict = {
        "magnetometer_config": create_magnetometer_config_dict(test_num_wells),
        "sampling_period": 10000,
    }

    # reverse order of magnetometer config keys here to test that they get sorted
    reversed_config_dict = copy.deepcopy(expected_config_dict)
    reversed_config_dict["magnetometer_config"] = dict(
        reversed(reversed_config_dict["magnetometer_config"].items())
    )
    # also reverse inner dicts
    for key, inner_dict in reversed_config_dict["magnetometer_config"].items():
        reversed_config_dict["magnetometer_config"][key] = dict(reversed(inner_dict.items()))

    response = test_client.post("/set_magnetometer_config", json=json.dumps(reversed_config_dict))
    assert response.status_code == 200
    response_json = response.get_json()
    assert "magnetometer_config" in response_json
    assert "sampling_period" in response_json

    invoke_process_run_and_check_errors(monitor_thread)

    # enable default channel in expected config
    for module_dict in expected_config_dict["magnetometer_config"].values():
        module_dict[SERIAL_COMM_DEFAULT_DATA_CHANNEL] = True

    assert shared_values_dict["magnetometer_config_dict"] == expected_config_dict
    # make sure module ID keys and inner channel keys are fully sorted
    module_configs = shared_values_dict["magnetometer_config_dict"]["magnetometer_config"]
    key_list = list(module_configs.keys())
    assert all(key_list[i] == key_list[i + 1] - 1 for i in range(len(key_list) - 1)) is True
    for key, inner_dict in module_configs.items():
        key_list = list(inner_dict.keys())
        assert all(key_list[i] == key_list[i + 1] - 1 for i in range(len(key_list) - 1)) is True


def test_set_protocols__waits_for_stim_info_in_shared_values_dict_to_be_updated_before_returning(
    client_and_server_manager_and_shared_values, test_client, mocker
):
    _, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_protocol_dict = {
        "protocols": [
            {
                "protocol_id": "S",
                "stimulation_type": "C",
                "run_until_stopped": True,
                "subprotocols": [get_random_subprotocol(), get_random_subprotocol()],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "S" for well_idx in range(24)
        },
    }

    mocker.patch.object(
        server,
        "_get_stim_info_from_process_monitor",
        autospec=True,
        side_effect=[None, None, test_protocol_dict],
    )
    mocked_sleep = mocker.patch.object(server, "sleep", autospec=True)

    response = test_client.post("/set_protocols", json={"data": json.dumps(test_protocol_dict)})
    assert response.status_code == 200
    assert mocked_sleep.call_args_list == [mocker.call(0.1), mocker.call(0.1)]


def test_system_status__returns_no_plate_barcode_and_status_when_none_present(
    client_and_server_manager_and_shared_values, test_client
):
    _, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE

    response = test_client.get("/system_status")
    assert response.status_code == 200
    response_json = response.get_json()
    assert "barcode_status" not in response_json
    assert "plate_barcode" not in response_json


def test_after_request__redacts_mantarray_nicknames_from_system_status_log_message(
    client_and_server_manager_and_shared_values,
    test_client,
    mocker,
):
    _, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE

    expected_nickname_1 = "Test Nickname 1"
    expected_nickname_2 = "Other Nickname"
    expected_nickname_dict = {"0": expected_nickname_1, "1": expected_nickname_2}
    shared_values_dict["mantarray_nickname"] = expected_nickname_dict

    spied_server_logger = mocker.spy(server.logger, "info")

    response = test_client.get("/system_status")
    assert response.status_code == 200
    response_json = response.get_json()
    assert response_json["mantarray_nickname"] == expected_nickname_dict

    expected_redaction_1 = get_redacted_string(len(expected_nickname_1))
    expected_redaction_2 = get_redacted_string(len(expected_nickname_2))
    expected_logged_dict = {"0": expected_redaction_1, "1": expected_redaction_2}
    logged_json = convert_after_request_log_msg_to_json(spied_server_logger.call_args_list[0][0][0])
    assert logged_json["mantarray_nickname"] == expected_logged_dict


def test_after_request__redacts_mantarray_nickname_from_set_mantarray_nickname_log_message(
    client_and_server_manager_and_shared_values,
    mocker,
):
    test_client, _, _ = client_and_server_manager_and_shared_values
    spied_server_logger = mocker.spy(server.logger, "info")

    expected_nickname = "A New Nickname"
    response = test_client.get(f"/set_mantarray_nickname?nickname={expected_nickname}")
    assert response.status_code == 200
    response_json = response.get_json()
    assert response_json["mantarray_nickname"] == expected_nickname

    expected_redaction = get_redacted_string(len(expected_nickname))
    logged_json = convert_after_request_log_msg_to_json(spied_server_logger.call_args_list[0][0][0])
    assert logged_json["mantarray_nickname"] == expected_redaction


def test_after_request__redacts_mantarray_nicknames_from_start_recording_log_message(
    client_and_server_manager_and_shared_values, mocker
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)

    board_idx = 0
    spied_server_logger = mocker.spy(server.logger, "info")

    expected_nickname = shared_values_dict["mantarray_nickname"][board_idx]
    response = test_client.get("/start_recording?barcode=MA200440001")
    assert response.status_code == 200
    response_json = response.get_json()
    assert (
        response_json["metadata_to_copy_onto_main_file_attributes"][str(MANTARRAY_NICKNAME_UUID)]
        == expected_nickname
    )

    expected_redaction = get_redacted_string(len(expected_nickname))
    logged_json = convert_after_request_log_msg_to_json(spied_server_logger.call_args_list[0][0][0])
    assert (
        logged_json["metadata_to_copy_onto_main_file_attributes"][str(MANTARRAY_NICKNAME_UUID)]
        == expected_redaction
    )
