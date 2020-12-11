# -*- coding: utf-8 -*-
import datetime
from multiprocessing import Queue
import os
import struct
import tempfile

from freezegun import freeze_time
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import PLATE_BARCODE_UUID
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import queue_utils
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_desktop_app import utils
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import pytest
from stdlib_utils import confirm_parallelism_is_stopped
from stdlib_utils import confirm_port_in_use
from stdlib_utils import invoke_process_run_and_check_errors
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
from ..fixtures import fixture_test_process_manager
from ..fixtures import GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from ..fixtures_process_monitor import fixture_test_monitor
from ..fixtures_server import fixture_client_and_server_thread_and_shared_values
from ..fixtures_server import fixture_generic_start_recording_info_in_shared_dict
from ..fixtures_server import fixture_server_thread
from ..fixtures_server import fixture_test_client
from ..helpers import assert_queue_is_eventually_not_empty
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_not_empty
from ..helpers import is_queue_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_client_and_server_thread_and_shared_values,
    fixture_server_thread,
    fixture_generic_queue_container,
    fixture_test_process_manager,
    fixture_test_client,
    fixture_test_monitor,
    fixture_patched_firmware_folder,
    fixture_patched_short_calibration_script,
    fixture_patched_test_xem_scripts_folder,
    fixture_patched_xem_scripts_folder,
    fixture_patch_print,
    fixture_generic_start_recording_info_in_shared_dict,
]


@pytest.mark.slow
def test_send_single_set_mantarray_nickname_command__gets_processed_and_stores_nickname_in_shared_values_dict(
    test_monitor, test_client, test_process_manager
):
    monitor_thread, _, _, _ = test_monitor
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    expected_nickname = "Surnom Français"
    ok_process = test_process_manager.get_instrument_process()
    test_process_manager.start_processes()
    response = test_client.get(f"/set_mantarray_nickname?nickname={expected_nickname}")
    assert response.status_code == 200

    invoke_process_run_and_check_errors(monitor_thread)

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )

    assert shared_values_dict["mantarray_nickname"][0] == expected_nickname
    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull ok_comm connect to board message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_nickname"
    assert communication["mantarray_nickname"] == expected_nickname

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_start_calibration_command__gets_processed_and_sets_system_status_to_calibrating(
    patched_short_calibration_script,
    test_monitor,
    test_client,
    test_process_manager,
):
    monitor_thread, _, _, _ = test_monitor
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    expected_script_type = "start_calibration"

    test_process_manager.start_processes()
    response = test_client.get("/insert_xem_command_into_queue/initialize_board")
    assert response.status_code == 200
    response = test_client.get("/start_calibration")
    assert response.status_code == 200

    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == CALIBRATING_STATE

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)
    # assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull ok_comm connect to board message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull initialize board response message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    script_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert script_communication["communication_type"] == "xem_scripts"
    assert script_communication["script_type"] == expected_script_type
    assert f"Running {expected_script_type} script" in script_communication["response"]

    done_message = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    teardown_message = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    while is_queue_eventually_not_empty(comm_from_ok_queue):
        done_message = teardown_message
        teardown_message = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert done_message["communication_type"] == "xem_scripts"
    assert done_message["response"] == f"'{expected_script_type}' script complete."

    # clean up
    test_process_manager.hard_stop_and_join_processes()


# Keep this "gets_processed" test in main test suite
def test_send_single_initialize_board_command_with_bit_file__gets_processed(
    test_process_manager, test_client, patched_firmware_folder
):
    board_idx = 0
    expected_bit_file_name = patched_firmware_folder

    simulator = FrontPanelSimulator({})

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(board_idx, simulator)

    test_process_manager.start_processes()

    response = test_client.get(
        f"/insert_xem_command_into_queue/initialize_board?bit_file_name={expected_bit_file_name}"
    )
    assert response.status_code == 200
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )
    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(
            board_idx
        )
    )
    confirm_queue_is_eventually_empty(comm_queue)
    # assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        board_idx
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    initialize_board_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert initialize_board_communication["command"] == "initialize_board"
    assert initialize_board_communication["bit_file_name"] == expected_bit_file_name
    assert initialize_board_communication["allow_board_reinitialization"] is False
    get_status_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert (
        get_status_communication["response"]["bit_file_name"] == expected_bit_file_name
    )

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_initialize_board_command_without_bit_file__gets_processed(
    test_process_manager, test_client
):
    board_idx = 0

    simulator = FrontPanelSimulator({})

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(board_idx, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/initialize_board")
    assert response.status_code == 200

    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(
            board_idx
        )
    )
    confirm_queue_is_eventually_empty(comm_queue)
    # assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        board_idx
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    initialize_board_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert initialize_board_communication["command"] == "initialize_board"
    assert initialize_board_communication["bit_file_name"] is None
    assert initialize_board_communication["allow_board_reinitialization"] is False
    get_status_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert get_status_communication["response"]["bit_file_name"] is None

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_initialize_board_command_with_reinitialization__gets_processed(
    test_process_manager, test_client, patched_firmware_folder
):
    board_idx = 0

    expected_bit_file_name = patched_firmware_folder
    expected_reinitialization = True

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(board_idx, simulator)

    test_process_manager.start_processes()

    response = test_client.get(
        f"/insert_xem_command_into_queue/initialize_board?bit_file_name={expected_bit_file_name}&allow_board_reinitialization={expected_reinitialization}"
    )
    assert response.status_code == 200

    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(
            board_idx
        )
    )
    confirm_queue_is_eventually_empty(comm_queue)
    # assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        board_idx
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    initialize_board_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert initialize_board_communication["command"] == "initialize_board"
    assert initialize_board_communication["bit_file_name"] == expected_bit_file_name
    assert initialize_board_communication["allow_board_reinitialization"] is True
    get_status_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert (
        get_status_communication["response"]["bit_file_name"] == expected_bit_file_name
    )

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_activate_trigger_in_command__gets_processed(
    test_process_manager, test_client
):
    expected_ep_addr = 10
    expected_bit = 0x00000001

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get(
        f"/insert_xem_command_into_queue/activate_trigger_in?ep_addr={expected_ep_addr}&bit={expected_bit}"
    )
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)
    # assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "activate_trigger_in"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["bit"] == expected_bit

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_comm_delay_command__gets_processed(
    test_process_manager, test_client
):
    expected_num_millis = 100

    test_process_manager.start_processes()

    response = test_client.get(
        f"/insert_xem_command_into_queue/comm_delay?num_milliseconds={expected_num_millis}"
    )
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the board connection message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "comm_delay"
    assert communication["num_milliseconds"] == expected_num_millis
    assert (
        communication["response"] == f"Delayed for {expected_num_millis} milliseconds"
    )

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_get_num_words_fifo_command__gets_processed(
    test_process_manager, test_client
):
    expected_num_words = DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN
    test_bytearray = bytearray(expected_num_words * 4)
    fifo = Queue()
    fifo.put(test_bytearray)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/get_num_words_fifo")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )
    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "get_num_words_fifo"
    assert communication["response"] == expected_num_words
    assert communication["hex_converted_response"] == hex(expected_num_words)

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_set_device_id_command__gets_processed(
    test_process_manager, test_client
):
    test_id = "Mantarray XEM"
    simulator = FrontPanelSimulator({})

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_device_id?new_id={test_id}"
    )
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "set_device_id"
    assert communication["new_id"] == test_id

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_stop_acquisition_command__gets_processed(
    test_process_manager, test_client
):
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/stop_acquisition")
    assert response.status_code == 200
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    stop_acquisition_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert stop_acquisition_communication["command"] == "stop_acquisition"
    get_status_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert get_status_communication["response"]["is_spi_running"] is False

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_start_acquisition_command__gets_processed(
    test_process_manager, test_client
):
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/start_acquisition")
    assert response.status_code == 200
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    start_acquisition_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )

    assert start_acquisition_communication["command"] == "start_acquisition"
    get_status_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert get_status_communication["response"]["is_spi_running"] is True

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_get_serial_number_command__gets_processed(
    test_process_manager, test_client
):
    simulator = FrontPanelSimulator({})

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/get_serial_number")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )
    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)
    # assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "get_serial_number"
    assert communication["response"] == "1917000Q70"

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_get_device_id_command__gets_processed(
    test_process_manager, test_client
):
    simulator = FrontPanelSimulator({})
    expected_id = "Mantarray XEM"
    simulator.set_device_id(expected_id)

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/get_device_id")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "get_device_id"
    assert communication["response"] == expected_id

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_send_single_is_spi_running_command__gets_processed(
    test_process_manager, test_client
):
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/is_spi_running")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )

    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "is_spi_running"
    assert communication["response"] is False

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.parametrize(
    ",".join(("test_num_words_to_log", "test_description")),
    [
        (1, "logs 1 word"),
        (72, "logs 72 words"),
        (73, "logs 72 words given 73 num words to log"),
    ],
)
def test_read_from_fifo_command__is_received_by_ok_comm__with_correct_num_words_to_log(
    test_num_words_to_log, test_description, test_process_manager, test_client
):
    test_bytearray = produce_data(1, 0)
    fifo = Queue()
    fifo.put(test_bytearray)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)
    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )

    response = test_client.get(
        f"/insert_xem_command_into_queue/read_from_fifo?num_words_to_log={test_num_words_to_log}"
    )
    assert response.status_code == 200
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    assert is_queue_eventually_not_empty(comm_queue) is True

    invoke_process_run_and_check_errors(ok_process)

    confirm_queue_is_eventually_empty(comm_queue)

    ok_comm_to_main = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    assert is_queue_eventually_not_empty(ok_comm_to_main) is True

    communication = ok_comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "read_from_fifo"
    assert communication["num_words_to_log"] == test_num_words_to_log


# TODO (Eli 12/10/20): It's highly unlikely that slow tests should need to be parametrized--this should probably be set up as unit tests and one single slow integration test
@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
@pytest.mark.parametrize(
    ",".join(("test_num_words_to_log", "test_num_cycles_to_read", "test_description")),
    [
        (1, 1, "logs 1 word with one cycle read"),
        (72, 1, "logs 72 words with one cycle read"),
        (73, 1, "logs 72 words given 73 num words to log and one cycle read"),
        (144, 2, "logs 144 words given 144 num words to log and two cycles read"),
    ],
)
def test_send_single_read_from_fifo_command__gets_processed_with_correct_num_words(
    test_num_words_to_log,
    test_num_cycles_to_read,
    test_description,
    test_process_manager,
    test_client,
):
    test_bytearray = produce_data(1, 0)
    fifo = Queue()
    fifo.put(test_bytearray)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get(
        f"/insert_xem_command_into_queue/read_from_fifo?num_words_to_log={test_num_words_to_log}"
    )
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

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

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
def test_send_single_set_wire_in_command__gets_processed(
    test_process_manager, test_client
):
    expected_ep_addr = 6
    expected_value = 0x00000011
    expected_mask = 0x00000011

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_wire_in?ep_addr={expected_ep_addr}&value={expected_value}&mask={expected_mask}"
    )
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )
    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "set_wire_in"
    assert communication["ep_addr"] == expected_ep_addr

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_send_xem_scripts_command__gets_processed(
    test_process_manager, test_client, patched_test_xem_scripts_folder, mocker
):
    expected_script_type = "test_script"
    ok_process = test_process_manager.get_instrument_process()

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/initialize_board")
    assert response.status_code == 200
    response = test_client.get(f"/xem_scripts?script_type={expected_script_type}")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull ok_comm connect to board message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull initialize board response message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    script_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert script_communication["script_type"] == expected_script_type
    assert f"Running {expected_script_type} script" in script_communication["response"]

    done_message = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    teardown_message = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    while is_queue_eventually_not_empty(comm_from_ok_queue):
        done_message = teardown_message
        teardown_message = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert done_message["communication_type"] == "xem_scripts"
    assert done_message["response"] == f"'{expected_script_type}' script complete."

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_read_wire_out_command__gets_processed(
    test_process_manager, test_client
):
    board_idx = 0
    expected_ep_addr = 7
    wire_queue = Queue()
    expected_wire_out_response = 33
    wire_queue.put(expected_wire_out_response)

    simulator = FrontPanelSimulator({"wire_outs": {expected_ep_addr: wire_queue}})
    simulator.initialize_board()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    test_route = (
        f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}"
    )
    response = test_client.get(test_route)
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(
            board_idx
        )
    )
    confirm_queue_is_eventually_empty(comm_queue)
    # assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        board_idx
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "read_wire_out"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["response"] == expected_wire_out_response
    assert communication["hex_converted_response"] == hex(expected_wire_out_response)

    # clean-up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_stop_managed_acquisition_command__gets_processed(
    test_process_manager, test_client
):
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    simulator.start_acquisition()

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/stop_managed_acquisition")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )
    confirm_parallelism_is_stopped(
        test_process_manager.get_file_writer_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )
    confirm_parallelism_is_stopped(
        test_process_manager.get_data_analyzer_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    to_ok_comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(to_ok_comm_queue)

    to_file_writer_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    confirm_queue_is_eventually_empty(to_file_writer_queue)

    to_da_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    )
    confirm_queue_is_eventually_empty(to_da_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "stop_managed_acquisition"

    comm_from_file_writer_queue = (
        test_process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
    )
    assert is_queue_eventually_not_empty(comm_from_file_writer_queue) is True
    communication = comm_from_file_writer_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "command_receipt"
    assert communication["command"] == "stop_managed_acquisition"

    comm_from_da_queue = (
        test_process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
    )
    assert is_queue_eventually_not_empty(comm_from_da_queue) is True
    communication = comm_from_da_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "stop_managed_acquisition"

    # clean-up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_set_mantarray_serial_number_command__gets_processed_and_stores_serial_number_in_shared_values_dict(
    test_monitor, test_process_manager, test_client
):
    monitor_thread, _, _, _ = test_monitor
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    expected_serial_number = "M02001901"

    test_process_manager.start_processes()
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={expected_serial_number}"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    assert shared_values_dict["mantarray_serial_number"][0] == expected_serial_number

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)
    # assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull ok_comm connect to board message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_serial_number"
    assert communication["mantarray_serial_number"] == expected_serial_number

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_send_single_boot_up_command__gets_processed_and_sets_system_status_to_instrument_initializing(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    test_monitor,
    test_process_manager,
    test_client,
):
    monitor_thread, _, _, _ = test_monitor
    expected_script_type = "start_up"
    expected_bit_file_name = patched_firmware_folder

    test_process_manager.start_processes()
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)

    response = test_client.get("/boot_up")
    assert response.status_code == 200
    instrument_process = test_process_manager.get_instrument_process()
    invoke_process_run_and_check_errors(monitor_thread)

    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    assert shared_values_dict["system_status"] == INSTRUMENT_INITIALIZING_STATE
    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    assert is_queue_eventually_not_empty(comm_queue) is True

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        instrument_process,
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull ok_comm connect to board message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    initialize_board_communication = comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert initialize_board_communication["command"] == "initialize_board"
    assert expected_bit_file_name in initialize_board_communication["bit_file_name"]
    assert initialize_board_communication["allow_board_reinitialization"] is False

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    script_communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert script_communication["communication_type"] == "xem_scripts"
    assert script_communication["script_type"] == expected_script_type
    assert f"Running {expected_script_type} script" in script_communication["response"]

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_boot_up_command__populates_ok_comm_error_queue_if_bit_file_cannot_be_found(
    patch_print, test_monitor, test_process_manager, test_client, mocker
):
    monitor_thread, _, _, _ = test_monitor

    mocker.patch.object(
        process_manager, "get_latest_firmware", autospec=True, return_value="fake.bit"
    )

    test_process_manager.start_processes()
    response = test_client.get("/boot_up")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    assert shared_values_dict["system_status"] == INSTRUMENT_INITIALIZING_STATE
    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    assert is_queue_eventually_not_empty(comm_queue) is True

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )
    assert is_queue_eventually_not_empty(comm_queue) is True

    ok_comm_error_queue = (
        test_process_manager.queue_container().get_ok_communication_error_queue()
    )
    assert is_queue_eventually_not_empty(ok_comm_error_queue) is True

    error_info = ok_comm_error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual_exception, _ = error_info
    assert isinstance(actual_exception, OpalKellyFileNotFoundError) is True
    assert "fake.bit" in str(actual_exception)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull ok_comm connect to board message
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull ok_comm teardown message
    confirm_queue_is_eventually_empty(comm_from_ok_queue)

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_start_managed_acquisition_command__sets_system_status_to_buffering__and_clears_data_analyzer_outgoing_queue(
    test_process_manager, test_client, test_monitor
):
    monitor_thread, _, _, _ = test_monitor
    board_idx = 0
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    shared_values_dict["mantarray_serial_number"] = {
        board_idx: RunningFIFOSimulator.default_mantarray_serial_number
    }

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()

    ok_process = test_process_manager.get_instrument_process()
    ok_process.set_board_connection(0, simulator)

    dummy_data = {"well_index": 0, "data": [[0, 1], [100, 200]]}
    outgoing_data_queue = (
        test_process_manager.queue_container().get_data_analyzer_data_out_queue()
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dummy_data, outgoing_data_queue
    )

    test_process_manager.start_processes()

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 200

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["system_status"] == BUFFERING_STATE

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_instrument_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )
    confirm_parallelism_is_stopped(
        test_process_manager.get_data_analyzer_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    instrument_error_queue = (
        test_process_manager.queue_container().get_ok_communication_error_queue()
    )
    confirm_queue_is_eventually_empty(instrument_error_queue)

    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    to_da_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    )
    confirm_queue_is_eventually_empty(to_da_queue)

    confirm_queue_is_eventually_empty(outgoing_data_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message
    assert_queue_is_eventually_not_empty(
        comm_from_ok_queue
    )  # Eli (11/12/20): specifically using "not empty" instead of checking an exact size, because after calling soft_stop a variety of teardown messages get put into the queue

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    assert communication["command"] == "start_managed_acquisition"
    assert communication["timestamp"] - datetime.datetime.utcnow() < datetime.timedelta(
        0, 5
    )  # TODO (Eli 11/10/20): consider if this should be replaced with using freezegun

    comm_from_da_queue = (
        test_process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
    )
    assert is_queue_eventually_of_size(comm_from_da_queue, 1) is True
    communication = comm_from_da_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_managed_acquisition"

    # clean up teardown messages in Instrument queue
    queue_utils._drain_queue(  # pylint:disable=protected-access # Eli (12/8/20) - drain_queue should be moved into stdlib_utils
        comm_from_ok_queue
    )

    # clean up
    test_process_manager.hard_stop_and_join_processes()


def test_update_settings__stores_values_in_shared_values_dict__and_recordings_folder_in_file_writer_and_process_manager__and_logs_recording_folder(
    test_process_manager, test_client, test_monitor, mocker
):
    monitor_thread, _, _, _ = test_monitor

    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    spied_utils_logger = mocker.spy(utils.logger, "info")

    expected_customer_uuid = "2dc06596-9cea-46a2-9ddd-a0d8a0f13584"
    expected_user_uuid = "21875600-ca08-44c4-b1ea-0877b3c63ca7"

    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = test_client.get(
            f"/update_settings?customer_account_uuid={expected_customer_uuid}&user_account_uuid={expected_user_uuid}&recording_directory={expected_recordings_dir}"
        )
        assert response.status_code == 200
        invoke_process_run_and_check_errors(monitor_thread)

        assert (
            shared_values_dict["config_settings"]["Customer Account ID"]
            == expected_customer_uuid
        )
        assert (
            shared_values_dict["config_settings"]["Recording Directory"]
            == expected_recordings_dir
        )
        assert (
            shared_values_dict["config_settings"]["User Account ID"]
            == expected_user_uuid
        )
        assert test_process_manager.get_file_directory() == expected_recordings_dir

        spied_utils_logger.assert_any_call(
            f"Using directory for recording files: {expected_recordings_dir}"
        )

    queue_from_main_to_file_writer = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    confirm_queue_is_eventually_of_size(queue_from_main_to_file_writer, 1)

    # clean up the message that goes to file writer to update the recording directory
    queue_utils._drain_queue(  # pylint:disable=protected-access # Eli (12/8/20) - drain_queue should be moved into stdlib_utils
        queue_from_main_to_file_writer
    )


def test_update_settings__replaces_curi_with_default_account_uuids(
    test_process_manager, test_client, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    shared_values_dict = test_process_manager.get_values_to_share_to_server()

    response = test_client.get("/update_settings?customer_account_uuid=curi")
    assert response.status_code == 200

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["config_settings"]["Customer Account ID"] == str(
        CURI_BIO_ACCOUNT_UUID
    )
    assert shared_values_dict["config_settings"]["User Account ID"] == str(
        CURI_BIO_USER_ACCOUNT_ID
    )


def test_update_settings__replaces_only_new_values_in_shared_values_dict(
    test_process_manager, test_client, test_monitor
):
    monitor_thread, _, _, _ = test_monitor
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    expected_customer_uuid = "b357cab5-adba-4cc3-a805-93b0b57a6d72"
    expected_user_uuid = "05dab94c-88dc-4505-ae4f-be6fa4a6f5f0"

    shared_values_dict["config_settings"] = {
        "Customer Account ID": "2dc06596-9cea-46a2-9ddd-a0d8a0f13584",
        "User Account ID": expected_user_uuid,
    }
    response = test_client.get(
        f"/update_settings?customer_account_uuid={expected_customer_uuid}"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert (
        shared_values_dict["config_settings"]["Customer Account ID"]
        == expected_customer_uuid
    )
    assert (
        shared_values_dict["config_settings"]["User Account ID"] == expected_user_uuid
    )


@pytest.mark.slow
def test_single_update_settings_command_with_recording_dir__gets_processed_by_FileWriter(
    test_process_manager, test_client, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.start_processes()
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = test_client.get(
            f"/update_settings?recording_directory={expected_recordings_dir}"
        )
        assert response.status_code == 200
        invoke_process_run_and_check_errors(monitor_thread)
        test_process_manager.soft_stop_processes()
        confirm_parallelism_is_stopped(
            test_process_manager.get_file_writer_process(),
            timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
        )
        to_fw_queue = (
            test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
        )
        confirm_queue_is_eventually_empty(to_fw_queue)

        from_fw_queue = (
            test_process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
        )
        assert is_queue_eventually_not_empty(from_fw_queue) is True
        communication = from_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

        assert communication["command"] == "update_directory"
        assert communication["new_directory"] == expected_recordings_dir

        # clean up
        test_process_manager.hard_stop_and_join_processes()


def test_stop_recording_command__sets_system_status_to_live_view_active(
    test_process_manager, test_client, test_monitor
):
    monitor_thread, _, _, _ = test_monitor
    shared_values_dict = test_process_manager.get_values_to_share_to_server()

    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=6, day=2, hour=17, minute=9, second=22, microsecond=362490
    )
    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [
        expected_acquisition_timestamp
    ]

    response = test_client.get("/stop_recording")
    assert response.status_code == 200

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["system_status"] == LIVE_VIEW_ACTIVE_STATE

    queue_from_main_to_file_writer = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )

    # clean up the message that goes to file writer to stop the recording
    queue_utils._drain_queue(  # pylint:disable=protected-access # Eli (12/8/20) - drain_queue should be moved into stdlib_utils
        queue_from_main_to_file_writer
    )


def test_stop_recording_command__is_received_by_file_writer__with_given_time_index_parameter(
    test_process_manager, test_client, test_monitor
):
    monitor_thread, _, _, _ = test_monitor
    shared_values_dict = test_process_manager.get_values_to_share_to_server()

    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332597
    )
    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [
        expected_acquisition_timestamp
    ]

    expected_time_index = 1000
    comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    response = test_client.get(f"/stop_recording?time_index={expected_time_index}")
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_not_empty(comm_queue) is True

    response_json = response.get_json()
    assert response_json["command"] == "stop_recording"

    file_writer_process = test_process_manager.get_file_writer_process()
    invoke_process_run_and_check_errors(file_writer_process)

    confirm_queue_is_eventually_empty(comm_queue)
    # assert is_queue_eventually_empty(comm_queue) is True

    file_writer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
    )
    confirm_queue_is_eventually_of_size(file_writer_to_main, 1)

    communication = file_writer_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "stop_recording"

    assert communication["timepoint_to_stop_recording_at"] == expected_time_index


def test_start_recording__returns_error_code_and_message_if_called_with_is_hardware_test_mode_false_when_previously_true(
    test_process_manager,
    test_client,
    test_monitor,
    generic_start_recording_info_in_shared_dict,
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()

    response = test_client.get(
        "/start_recording?barcode=MA200440001&is_hardware_test_recording=True"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    response = test_client.get(
        "/start_recording?barcode=MA200440001&is_hardware_test_recording=False"
    )
    assert response.status_code == 403
    assert (
        response.status.endswith(
            "Cannot make standard recordings after previously making hardware test recordings. Server and board must both be restarted before making any more standard recordings"
        )
        is True
    )


@pytest.mark.slow
@freeze_time(
    GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ]
)
def test_start_recording_command__gets_processed_with_given_time_index_parameter(
    test_process_manager,
    test_client,
    mocker,
    test_monitor,
    generic_start_recording_info_in_shared_dict,
):
    monitor_thread, _, _, _ = test_monitor
    expected_time_index = 10000000
    timestamp_str = (
        GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        + datetime.timedelta(
            seconds=(expected_time_index / CENTIMILLISECONDS_PER_SECOND)
        )
    ).strftime("%Y_%m_%d_%H%M%S")
    generic_start_recording_info_in_shared_dict[  # pylint: disable=duplicate-code
        "utc_timestamps_of_beginning_of_data_acquisition"
    ] = [
        GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
    ]

    test_process_manager.start_processes()

    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&active_well_indices=3&time_index={expected_time_index}"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert (
        generic_start_recording_info_in_shared_dict["system_status"] == RECORDING_STATE
    )
    assert (
        generic_start_recording_info_in_shared_dict["is_hardware_test_recording"]
        is True
    )

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_file_writer_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    error_queue = test_process_manager.queue_container().get_file_writer_error_queue()

    confirm_queue_is_eventually_empty(error_queue)

    file_dir = test_process_manager.get_file_writer_process().get_file_directory()
    actual_files = os.listdir(
        os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}")
    )
    assert actual_files == [f"{expected_barcode}__{timestamp_str}__D1.h5"]

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
@freeze_time(
    GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ]
    + datetime.timedelta(
        seconds=GENERIC_START_RECORDING_COMMAND[  # pylint: disable=duplicate-code
            "timepoint_to_begin_recording_at"
        ]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_start_recording_command__gets_processed__and_creates_a_file__and_updates_shared_values_dict(
    test_process_manager,
    test_client,
    mocker,
    test_monitor,
    generic_start_recording_info_in_shared_dict,
):
    monitor_thread, _, _, _ = test_monitor

    timestamp_str = (
        GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        + datetime.timedelta(
            seconds=GENERIC_START_RECORDING_COMMAND[  # pylint: disable=duplicate-code
                "timepoint_to_begin_recording_at"
            ]
            / CENTIMILLISECONDS_PER_SECOND
        )
    ).strftime("%Y_%m_%d_%H%M%S")

    test_process_manager.start_processes()

    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&active_well_indices=3&is_hardware_test_recording=False"
    )
    assert response.status_code == 200
    invoke_process_run_and_check_errors(monitor_thread)
    assert (
        generic_start_recording_info_in_shared_dict["system_status"] == RECORDING_STATE
    )
    assert (
        generic_start_recording_info_in_shared_dict["is_hardware_test_recording"]
        is False
    )

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        test_process_manager.get_file_writer_process(),
        timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS,
    )

    error_queue = test_process_manager.queue_container().get_file_writer_error_queue()

    confirm_queue_is_eventually_empty(error_queue)

    file_dir = test_process_manager.get_file_writer_process().get_file_directory()
    actual_files = os.listdir(
        os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}")
    )
    assert actual_files == [f"{expected_barcode}__2020_02_09_190935__D1.h5"]

    # clean up
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
def test_send_single_get_status_command__gets_processed(
    test_process_manager, test_client
):
    expected_response = {
        "is_spi_running": False,
        "is_board_initialized": False,
        "bit_file_name": None,
    }
    simulator = FrontPanelSimulator({})

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    test_process_manager.soft_stop_processes()
    confirm_parallelism_is_stopped(
        ok_process, timeout_seconds=GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
    )
    comm_queue = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_empty(comm_queue)

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "get_status"
    assert communication["response"] == expected_response

    # clean up
    test_process_manager.hard_stop_and_join_processes()
