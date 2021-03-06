# -*- coding: utf-8 -*-
import datetime
import json

from freezegun import freeze_time
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import server
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_file_manager import ADC_GAIN_SETTING_UUID
from mantarray_file_manager import BACKEND_LOG_UUID
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import COMPUTER_NAME_HASH_UUID
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import REFERENCE_VOLTAGE_UUID
from mantarray_file_manager import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_file_manager import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
from mantarray_file_manager import USER_ACCOUNT_ID_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_BEGINNING_RECORDING_UUID
from mantarray_file_manager import XEM_SERIAL_NUMBER_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import pytest

from ..fixtures import fixture_generic_queue_container
from ..fixtures import fixture_test_process_manager
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND
from ..fixtures_process_monitor import fixture_test_monitor
from ..fixtures_server import fixture_client_and_server_thread_and_shared_values
from ..fixtures_server import fixture_generic_start_recording_info_in_shared_dict
from ..fixtures_server import fixture_server_thread
from ..fixtures_server import fixture_test_client
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_not_empty
from ..helpers import is_queue_eventually_of_size

__fixtures__ = [
    fixture_client_and_server_thread_and_shared_values,
    fixture_server_thread,
    fixture_generic_queue_container,
    fixture_test_client,
    fixture_generic_start_recording_info_in_shared_dict,
    fixture_test_process_manager,
    fixture_test_monitor,
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(
            board_idx
        )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(
            board_idx
        )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    response = test_client.get(
        "/insert_xem_command_into_queue/read_from_fifo?num_words_to_log=72"
    )
    assert response.status_code == 200
    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
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

    response = test_client.get(
        "/insert_xem_command_into_queue/read_from_fifo?num_words_to_log=0x48"
    )
    assert response.status_code == 200

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_from_fifo"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    assert response_json["suppress_error"] is True


def test_send_single_set_wire_in_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    expected_ep_addr = 8
    expected_value = 0x00000010
    expected_mask = 0x00000010
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_wire_in?ep_addr={expected_ep_addr}&value={expected_value}&mask={expected_mask}"
    )
    assert response.status_code == 200
    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "set_wire_in"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["value"] == expected_value
    assert communication["mask"] == expected_mask
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "set_wire_in"
    assert response_json["ep_addr"] == expected_ep_addr
    assert response_json["value"] == expected_value
    assert response_json["mask"] == expected_mask
    assert response_json["suppress_error"] is True


def test_send_single_set_wire_in_command__using_hex_notation__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    expected_ep_addr = "0x05"
    value = "0x000000a0"
    mask = "0x00000011"
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_wire_in?ep_addr={expected_ep_addr}&value={value}&mask={mask}"
    )
    assert response.status_code == 200

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "set_wire_in"
    assert communication["ep_addr"] == 5
    assert communication["value"] == 160
    assert communication["mask"] == 17
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "set_wire_in"
    assert response_json["ep_addr"] == 5
    assert response_json["value"] == 160
    assert response_json["mask"] == 17
    assert response_json["suppress_error"] is True


def test_send_single_xem_scripts_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    expected_script_type = "start_up"
    response = test_client.get(f"/xem_scripts?script_type={expected_script_type}")
    assert response.status_code == 200

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "xem_scripts"
    assert communication["script_type"] == expected_script_type
    response_json = response.get_json()
    assert response_json["script_type"] == expected_script_type


def test_send_single_read_wire_out_command__populates_queue__and_logs_response(
    client_and_server_thread_and_shared_values, mocker
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    board_idx = 0
    expected_ep_addr = 6
    mocked_logger = mocker.patch.object(server.logger, "info", autospec=True)
    response = test_client.get(
        f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}"
    )
    assert response.status_code == 200

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(
            board_idx
        )
    )
    assert is_queue_eventually_of_size(comm_queue, 1) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_wire_out"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_wire_out"
    assert response_json["ep_addr"] == expected_ep_addr
    assert response_json["suppress_error"] is True
    mocked_logger.assert_called_once_with(
        f"Response to HTTP Request in next log entry: {json.dumps(response_json)}"
    )


def test_send_single_read_wire_out_command_with_hex_notation__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    board_idx = 0
    expected_ep_addr = "0x6"
    response = test_client.get(
        f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}"
    )
    assert response.status_code == 200

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(
            board_idx
        )
    )
    assert is_queue_eventually_of_size(comm_queue, 1) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_wire_out"
    assert communication["ep_addr"] == 6
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_wire_out"
    assert response_json["ep_addr"] == 6
    assert response_json["suppress_error"] is True


def test_send_single_read_wire_out_command_with_description__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    board_idx = 0
    expected_ep_addr = 6
    expected_description = "test"
    response = test_client.get(
        f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}&description={expected_description}"
    )
    assert response.status_code == 200

    comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(
            board_idx
        )
    )
    assert is_queue_eventually_of_size(comm_queue, 1) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_wire_out"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["description"] == expected_description
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_wire_out"
    assert response_json["ep_addr"] == expected_ep_addr
    assert response_json["description"] == expected_description
    assert response_json["suppress_error"] is True


def test_send_single_stop_managed_acquisition_command__populates_queues(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    response = test_client.get("/stop_managed_acquisition")
    assert response.status_code == 200

    to_instrument_comm_queue = (
        test_server.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    assert is_queue_eventually_of_size(to_instrument_comm_queue, 1) is True
    comm_to_instrument_comm = to_instrument_comm_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    assert comm_to_instrument_comm["communication_type"] == "to_instrument"
    assert comm_to_instrument_comm["command"] == "stop_managed_acquisition"
    response_json = response.get_json()
    assert response_json["command"] == "stop_managed_acquisition"

    to_file_writer_queue = (
        test_server.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    assert is_queue_eventually_not_empty(to_file_writer_queue) is True
    comm_to_da = to_file_writer_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert comm_to_da["communication_type"] == "to_instrument"
    assert comm_to_da["command"] == "stop_managed_acquisition"
    response_json = response.get_json()
    assert response_json["command"] == "stop_managed_acquisition"

    to_da_queue = (
        test_server.queue_container().get_communication_queue_from_main_to_data_analyzer()
    )
    assert is_queue_eventually_of_size(to_da_queue, 1) is True
    comm_to_da = to_da_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert comm_to_da["communication_type"] == "to_instrument"
    assert comm_to_da["command"] == "stop_managed_acquisition"
    response_json = response.get_json()
    assert response_json["command"] == "stop_managed_acquisition"


def test_send_single_set_mantarray_serial_number_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    expected_serial_number = "M02001901"

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={expected_serial_number}"
    )
    assert response.status_code == 200

    server_to_main_queue = test_server.get_queue_to_main()
    assert is_queue_eventually_of_size(server_to_main_queue, 1) is True
    communication = server_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_serial_number"
    assert communication["mantarray_serial_number"] == expected_serial_number
    response_json = response.get_json()
    assert response_json["command"] == "set_mantarray_serial_number"
    assert response_json["mantarray_serial_number"] == expected_serial_number


def test_send_single_boot_up_command__populates_queue(
    client_and_server_thread_and_shared_values,
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    response = test_client.get("/boot_up")
    assert response.status_code == 200

    to_main_queue = test_server.get_queue_to_main()

    assert is_queue_eventually_of_size(to_main_queue, 1) is True
    communication = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "to_instrument"
    assert communication["command"] == "boot_up"

    response_json = response.get_json()
    assert response_json == communication


def test_send_single_start_managed_acquisition_command__populates_queues(
    client_and_server_thread_and_shared_values,
):
    (
        test_client,
        test_server_info,
        shared_values_dict,
    ) = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    board_idx = 0
    shared_values_dict["mantarray_serial_number"] = {board_idx: "M02001801"}

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 200

    to_main_queue = test_server.get_queue_to_main()

    assert is_queue_eventually_of_size(to_main_queue, 1) is True
    communication = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication == START_MANAGED_ACQUISITION_COMMUNICATION
    response_json = response.get_json()
    assert response_json == START_MANAGED_ACQUISITION_COMMUNICATION


@freeze_time(
    datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332597
    )
    + datetime.timedelta(
        seconds=GENERIC_STOP_RECORDING_COMMAND["timepoint_to_stop_recording_at"]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_stop_recording_command__is_received_by_main__with_default__utcnow_recording_stop_time(
    client_and_server_thread_and_shared_values,
):
    (
        test_client,
        test_server_info,
        shared_values_dict,
    ) = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332597
    )

    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [
        expected_acquisition_timestamp
    ]

    server_to_main_queue = test_server.get_queue_to_main()
    response = test_client.get("/stop_recording")
    assert response.status_code == 200
    confirm_queue_is_eventually_of_size(server_to_main_queue, 1)

    response_json = response.get_json()
    assert response_json["command"] == "stop_recording"

    communication = server_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "stop_recording"

    assert (
        communication["timepoint_to_stop_recording_at"]
        == GENERIC_STOP_RECORDING_COMMAND["timepoint_to_stop_recording_at"]
    )


def test_start_recording_command__populates_queue__with_correct_adc_offset_values_if_is_hardware_test_recording_is_true(
    test_process_manager, test_client, generic_start_recording_info_in_shared_dict
):
    expected_adc_offsets = dict()
    for well_idx in range(24):
        expected_adc_offsets[well_idx] = {"construct": 0, "ref": 0}

    barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(f"/start_recording?barcode={barcode}")
    assert response.status_code == 200

    comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    confirm_queue_is_eventually_of_size(comm_queue, 1)

    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"]
        == expected_adc_offsets
    )


def test_start_recording_command__populates_queue__with_given_time_index_parameter(
    test_process_manager, test_client, generic_start_recording_info_in_shared_dict
):
    expected_time_index = 1000
    barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={barcode}&time_index={expected_time_index}&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            START_RECORDING_TIME_INDEX_UUID
        ]
        == expected_time_index
    )
    assert communication["timepoint_to_begin_recording_at"] == expected_time_index


def test_start_recording_command__populates_queue__with_correctly_parsed_set_of_well_indices(
    test_process_manager, test_client, generic_start_recording_info_in_shared_dict
):
    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&active_well_indices=0,5,8&is_hardware_test_recording=False"
    )
    assert response.status_code == 200

    comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    assert set(communication["active_well_indices"]) == set([0, 8, 5])


@pytest.mark.parametrize(
    "scanned_barcode,user_entered_barcode,expected_result,test_description",
    [
        (
            "MA200440001",
            "MA200440002",
            False,
            "correctly sets value to False with scanned barcode present",
        ),
        (
            "",
            "MA200440002",
            False,
            "correctly sets value to False after barcode scan fails",
        ),
        (
            None,
            "MA200440002",
            False,
            "correctly sets value to False without scanned barcode present",
        ),
        ("MA200440001", "MA200440001", True, "correctly sets value to True"),
    ],
)
def test_start_recording_command__correctly_sets_barcode_from_scanner_value(
    scanned_barcode,
    user_entered_barcode,
    expected_result,
    test_description,
    generic_start_recording_info_in_shared_dict,
    test_process_manager,
    test_client,
):
    board_idx = 0
    if scanned_barcode is None:
        del generic_start_recording_info_in_shared_dict["barcodes"]
    else:
        generic_start_recording_info_in_shared_dict["barcodes"][board_idx][
            "plate_barcode"
        ] = scanned_barcode

    response = test_client.get(
        f"/start_recording?barcode={user_entered_barcode}&is_hardware_test_recording=False"
    )
    assert response.status_code == 200

    comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"


@freeze_time(
    datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598
    )
    + datetime.timedelta(
        seconds=GENERIC_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_start_recording_command__populates_queue__with_defaults__24_wells__utcnow_recording_start_time__and_metadata(
    test_process_manager, test_client, generic_start_recording_info_in_shared_dict
):
    expected_acquisition_timestamp = (
        datetime.datetime(  # pylint: disable=duplicate-code
            year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598
        )
    )
    expected_recording_timepoint = GENERIC_START_RECORDING_COMMAND[
        "timepoint_to_begin_recording_at"
    ]
    expected_recording_timestamp = expected_acquisition_timestamp + datetime.timedelta(
        seconds=(expected_recording_timepoint / CENTIMILLISECONDS_PER_SECOND)
    )

    generic_start_recording_info_in_shared_dict[
        "utc_timestamps_of_beginning_of_data_acquisition"
    ] = [expected_acquisition_timestamp]

    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"

    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        == expected_acquisition_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_RECORDING_UUID
        ]
        == expected_recording_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            CUSTOMER_ACCOUNT_ID_UUID
        ]
        == generic_start_recording_info_in_shared_dict["config_settings"][
            "Customer Account ID"
        ]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            USER_ACCOUNT_ID_UUID
        ]
        == generic_start_recording_info_in_shared_dict["config_settings"][
            "User Account ID"
        ]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            START_RECORDING_TIME_INDEX_UUID
        ]
        == expected_recording_timepoint
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            SOFTWARE_BUILD_NUMBER_UUID
        ]
        == COMPILED_EXE_BUILD_TIMESTAMP
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            SOFTWARE_RELEASE_VERSION_UUID
        ]
        == CURRENT_SOFTWARE_VERSION
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            MAIN_FIRMWARE_VERSION_UUID
        ]
        == generic_start_recording_info_in_shared_dict["main_firmware_version"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            SLEEP_FIRMWARE_VERSION_UUID
        ]
        == generic_start_recording_info_in_shared_dict["sleep_firmware_version"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            XEM_SERIAL_NUMBER_UUID
        ]
        == generic_start_recording_info_in_shared_dict["xem_serial_number"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            MANTARRAY_SERIAL_NUMBER_UUID
        ]
        == generic_start_recording_info_in_shared_dict["mantarray_serial_number"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            MANTARRAY_NICKNAME_UUID
        ]
        == generic_start_recording_info_in_shared_dict["mantarray_nickname"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            REFERENCE_VOLTAGE_UUID
        ]
        == REFERENCE_VOLTAGE
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            ADC_GAIN_SETTING_UUID
        ]
        == generic_start_recording_info_in_shared_dict["adc_gain"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"]
        == generic_start_recording_info_in_shared_dict["adc_offsets"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][PLATE_BARCODE_UUID]
        == expected_barcode
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            HARDWARE_TEST_RECORDING_UUID
        ]
        is False
    )

    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][BACKEND_LOG_UUID]
        == GENERIC_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][BACKEND_LOG_UUID]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            BARCODE_IS_FROM_SCANNER_UUID
        ]
        is True
    )
    assert (  # pylint: disable=duplicate-code
        communication["metadata_to_copy_onto_main_file_attributes"][
            COMPUTER_NAME_HASH_UUID
        ]
        == GENERIC_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][COMPUTER_NAME_HASH_UUID]
    )
    assert set(communication["active_well_indices"]) == set(range(24))
    assert (
        communication["timepoint_to_begin_recording_at"]
        == GENERIC_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    )
    response_json = response.get_json()
    assert response_json["command"] == "start_recording"


def test_shutdown__populates_queue_with_request_to_soft_stop_then_request_to_hard_stop__and_calls_function_to_shut_down_server(
    client_and_server_thread_and_shared_values, mocker
):
    test_client, test_server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = test_server_info

    mocked_stop_server = mocker.patch.object(
        server, "shutdown_server", autospec=True
    )  # in the testing context, the Flask server cannot actually be shut down, so mocking instead of spying here

    response = test_client.get("/shutdown")
    assert response.status_code == 200

    server_to_main_queue = test_server.get_queue_to_main()
    assert is_queue_eventually_of_size(server_to_main_queue, 2) is True
    communication = server_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "shutdown"
    assert communication["command"] == "soft_stop"
    communication = server_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "shutdown"
    assert communication["command"] == "hard_stop"
    response_json = response.get_json()
    assert response_json == communication

    mocked_stop_server.assert_called_once()
