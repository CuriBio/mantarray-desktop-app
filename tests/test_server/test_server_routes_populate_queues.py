# -*- coding: utf-8 -*-
from ..fixtures import fixture_generic_queue_container
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_server import fixture_client_and_server_thread_and_shared_values
from ..fixtures_server import fixture_server_thread
from ..fixtures_server import fixture_test_client
from ..helpers import is_queue_eventually_not_empty

__fixtures__ = [
    fixture_client_and_server_thread_and_shared_values,
    fixture_server_thread,
    fixture_generic_queue_container,
    fixture_test_client,
]


def test_send_single_set_mantarray_nickname_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    (
        test_client,
        test_server_info,
        shared_values_dict,
    ) = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info
    shared_values_dict["mantarray_nickname"] = dict()
    expected_nickname = "Surnom Français"

    response = test_client.get(f"/set_mantarray_nickname?nickname={expected_nickname}")
    assert response.status_code == 200

    to_main_queue = test_server.get_queue_to_main()
    assert is_queue_eventually_not_empty(to_main_queue) is True
    communication = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_nickname"
    assert communication["mantarray_nickname"] == expected_nickname
    response_json = response.get_json()
    assert response_json["command"] == "set_mantarray_nickname"
    assert response_json["mantarray_nickname"] == expected_nickname


def test_send_single_initialize_board_command_with_bit_file__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info
    board_idx = 0
    expected_bit_file_name = "main.bit"
    response = test_client.get(
        f"/insert_xem_command_into_queue/initialize_board?bit_file_name={expected_bit_file_name}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(
        board_idx
    )

    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "initialize_board"
    assert communication["bit_file_name"] == expected_bit_file_name
    assert communication["allow_board_reinitialization"] is False
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "initialize_board"
    assert response_json["bit_file_name"] == expected_bit_file_name
    assert response_json["allow_board_reinitialization"] is False
    assert response_json["suppress_error"] is True


def test_send_single_initialize_board_command_without_bit_file__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info
    board_idx = 0
    response = test_client.get("/insert_xem_command_into_queue/initialize_board")
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(
        board_idx
    )

    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "initialize_board"
    assert communication["bit_file_name"] is None
    assert communication["allow_board_reinitialization"] is False
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "initialize_board"
    assert response_json["bit_file_name"] is None
    assert response_json["allow_board_reinitialization"] is False
    assert response_json["suppress_error"] is True


def test_send_single_get_status_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_status"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_status"
    assert response_json["suppress_error"] is True


def test_send_single_activate_trigger_in_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info
    expected_ep_addr = 10
    expected_bit = 0x00000001
    response = test_client.get(
        f"/insert_xem_command_into_queue/activate_trigger_in?ep_addr={expected_ep_addr}&bit={expected_bit}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "activate_trigger_in"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["bit"] == expected_bit
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "activate_trigger_in"
    assert response_json["ep_addr"] == expected_ep_addr
    assert response_json["bit"] == expected_bit
    assert response_json["suppress_error"] is True


def test_send_single_activate_trigger_in_command__using_hex_notation__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info
    expected_ep_addr = "0x02"
    expected_bit = "0x00000001"
    response = test_client.get(
        f"/insert_xem_command_into_queue/activate_trigger_in?ep_addr={expected_ep_addr}&bit={expected_bit}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "activate_trigger_in"
    assert communication["ep_addr"] == 2
    assert communication["bit"] == 1
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "activate_trigger_in"
    assert response_json["ep_addr"] == 2
    assert response_json["bit"] == 1
    assert response_json["suppress_error"] is True


def test_send_single_comm_delay_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    expected_num_millis = 35
    response = test_client.get(
        f"/insert_xem_command_into_queue/comm_delay?num_milliseconds={expected_num_millis}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "comm_delay"
    assert communication["num_milliseconds"] == expected_num_millis
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "comm_delay"
    assert response_json["num_milliseconds"] == expected_num_millis
    assert response_json["suppress_error"] is True


def test_send_single_get_num_words_fifo_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info
    response = test_client.get("/insert_xem_command_into_queue/get_num_words_fifo")
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_num_words_fifo"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_num_words_fifo"
    assert response_json["suppress_error"] is True


def test_send_single_set_device_id_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    test_id = "Mantarray XEM"
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_device_id?new_id={test_id}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "set_device_id"
    assert communication["new_id"] == test_id
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "set_device_id"
    assert response_json["new_id"] == test_id
    assert response_json["suppress_error"] is True


def test_send_single_stop_acquisition_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    response = test_client.get("/insert_xem_command_into_queue/stop_acquisition")
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "stop_acquisition"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "stop_acquisition"
    assert response_json["suppress_error"] is True


def test_send_single_start_acquisition_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    response = test_client.get("/insert_xem_command_into_queue/start_acquisition")
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "start_acquisition"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "start_acquisition"
    assert response_json["suppress_error"] is True


def test_send_single_get_serial_number_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    response = test_client.get("/insert_xem_command_into_queue/get_serial_number")
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_serial_number"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_serial_number"
    assert response_json["suppress_error"] is True


def test_send_single_get_device_id_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    response = test_client.get("/insert_xem_command_into_queue/get_device_id")
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_device_id"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_device_id"
    assert response_json["suppress_error"] is True


def test_send_single_is_spi_running_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    response = test_client.get("/insert_xem_command_into_queue/is_spi_running")
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "is_spi_running"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "is_spi_running"
    assert response_json["suppress_error"] is True


def test_send_single_read_from_fifo_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    # test_bytearray = produce_data(1, 0)
    # fifo = Queue()
    # fifo.put(test_bytearray)
    # queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    # simulator = FrontPanelSimulator(queues)
    # simulator.initialize_board()
    # simulator.start_acquisition()
    # ok_process = test_process_manager.get_ok_comm_process()
    # ok_process.set_board_connection(0, simulator)

    response = test_client.get(
        "/insert_xem_command_into_queue/read_from_fifo?num_words_to_log=72"
    )
    assert response.status_code == 200
    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_from_fifo"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    assert response_json["suppress_error"] is True


def test_send_single_read_from_fifo_command_with_hex_notation__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    # test_bytearray = produce_data(1, 0)
    # fifo = Queue()
    # fifo.put(test_bytearray)
    # queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    # simulator = FrontPanelSimulator(queues)
    # simulator.initialize_board()
    # simulator.start_acquisition()
    # ok_process = test_process_manager.get_ok_comm_process()
    # ok_process.set_board_connection(0, simulator)

    response = test_client.get(
        "/insert_xem_command_into_queue/read_from_fifo?num_words_to_log=0x48"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container().get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_from_fifo"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    assert response_json["suppress_error"] is True
