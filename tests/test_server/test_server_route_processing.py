# -*- coding: utf-8 -*-
from multiprocessing import Queue

from mantarray_desktop_app import CALIBRATING_STATE
import pytest
from stdlib_utils import invoke_process_run_and_check_errors
from xem_wrapper import DATA_FRAME_SIZE_WORDS
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import PIPE_OUT_FIFO

from ..fixtures import fixture_generic_queue_container
from ..fixtures import fixture_patched_firmware_folder
from ..fixtures import fixture_patched_short_calibration_script
from ..fixtures import fixture_test_process_manager
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_process_monitor import fixture_test_monitor
from ..fixtures_server import fixture_client_and_server_thread_and_shared_values
from ..fixtures_server import fixture_server_thread
from ..fixtures_server import fixture_test_client
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_not_empty

__fixtures__ = [
    fixture_client_and_server_thread_and_shared_values,
    fixture_server_thread,
    fixture_generic_queue_container,
    fixture_test_process_manager,
    fixture_test_client,
    fixture_test_monitor,
    fixture_patched_firmware_folder,
    fixture_patched_short_calibration_script,
]


@pytest.mark.slow
def test_send_single_set_mantarray_nickname_command__gets_processed_and_stores_nickname_in_shared_values_dict(
    test_monitor, test_client, test_process_manager
):
    monitor_thread, _, _, _ = test_monitor
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    expected_nickname = "Surnom Français"

    test_process_manager.start_processes()
    response = test_client.get(f"/set_mantarray_nickname?nickname={expected_nickname}")
    assert response.status_code == 200

    invoke_process_run_and_check_errors(monitor_thread)

    test_process_manager.soft_stop_and_join_processes()

    assert shared_values_dict["mantarray_nickname"][0] == expected_nickname
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    assert is_queue_eventually_empty(comm_queue) is True

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


@pytest.mark.slow
def test_send_single_start_calibration_command__gets_processed_and_sets_system_status_to_calibrating(
    patched_short_calibration_script, test_monitor, test_client, test_process_manager,
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

    test_process_manager.soft_stop_and_join_processes()

    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    assert is_queue_eventually_empty(comm_queue) is True

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

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        board_idx
    )
    assert is_queue_eventually_empty(comm_queue) is True

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

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        board_idx
    )
    assert is_queue_eventually_empty(comm_queue) is True

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

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        board_idx
    )
    assert is_queue_eventually_empty(comm_queue) is True

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

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    communication = comm_from_ok_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "activate_trigger_in"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["bit"] == expected_bit


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
    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    assert is_queue_eventually_empty(comm_queue) is True

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

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    assert is_queue_eventually_empty(comm_queue) is True

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

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    assert is_queue_eventually_empty(comm_queue) is True

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

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    assert is_queue_eventually_empty(comm_queue) is True

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

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )

    assert is_queue_eventually_empty(comm_queue) is True

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
