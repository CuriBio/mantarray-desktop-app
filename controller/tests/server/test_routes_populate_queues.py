# -*- coding: utf-8 -*-
import copy
import datetime
import json
from random import randint
import urllib

from freezegun import freeze_time
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app.constants import NUM_INITIAL_MICROSECONDS_TO_PAD
from mantarray_desktop_app.constants import RECORDING_STATE
from mantarray_desktop_app.constants import STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
from mantarray_desktop_app.main_process import server
from mantarray_desktop_app.simulators.mc_simulator import MantarrayMcSimulator
from pulse3D.constants import ADC_GAIN_SETTING_UUID
from pulse3D.constants import BACKEND_LOG_UUID
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import COMPUTER_NAME_HASH_UUID
from pulse3D.constants import CUSTOMER_ACCOUNT_ID_UUID
from pulse3D.constants import HARDWARE_TEST_RECORDING_UUID
from pulse3D.constants import INITIAL_MAGNET_FINDING_PARAMS_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
from pulse3D.constants import NOT_APPLICABLE_H5_METADATA
from pulse3D.constants import NUM_INITIAL_MICROSECONDS_TO_REMOVE_UUID
from pulse3D.constants import PLATE_BARCODE_IS_FROM_SCANNER_UUID
from pulse3D.constants import PLATE_BARCODE_UUID
from pulse3D.constants import REFERENCE_VOLTAGE_UUID
from pulse3D.constants import SLEEP_FIRMWARE_VERSION_UUID
from pulse3D.constants import SOFTWARE_BUILD_NUMBER_UUID
from pulse3D.constants import SOFTWARE_RELEASE_VERSION_UUID
from pulse3D.constants import START_RECORDING_TIME_INDEX_UUID
from pulse3D.constants import STIM_BARCODE_IS_FROM_SCANNER_UUID
from pulse3D.constants import STIM_BARCODE_UUID
from pulse3D.constants import USER_ACCOUNT_ID_UUID
from pulse3D.constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from pulse3D.constants import UTC_BEGINNING_RECORDING_UUID
from pulse3D.constants import XEM_SERIAL_NUMBER_UUID
import pytest

from ..fixtures import fixture_generic_queue_container
from ..fixtures import fixture_test_process_manager_creator
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import GENERIC_BETA_1_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND
from ..fixtures_mc_simulator import get_random_stim_delay
from ..fixtures_mc_simulator import get_random_stim_pulse
from ..fixtures_process_monitor import fixture_test_monitor
from ..fixtures_server import fixture_client_and_server_manager_and_shared_values
from ..fixtures_server import fixture_server_manager
from ..fixtures_server import fixture_test_client
from ..fixtures_server import put_generic_beta_1_start_recording_info_in_dict
from ..fixtures_server import put_generic_beta_2_start_recording_info_in_dict
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_not_empty
from ..helpers import random_bool

__fixtures__ = [
    fixture_client_and_server_manager_and_shared_values,
    fixture_server_manager,
    fixture_generic_queue_container,
    fixture_test_client,
    fixture_test_process_manager_creator,
    fixture_test_monitor,
]


def test_send_single_set_mantarray_nickname_command__populates_queue(
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), shared_values_dict = client_and_server_manager_and_shared_values
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


@pytest.mark.parametrize(
    "test_new_name,expected_new_name",
    [
        ("NormalName", "NormalName"),
        ("  TestName", "TestName"),
        ("TestName  ", "TestName"),
        ("  TestName  ", "TestName"),
    ],
)
def test_send_single_update_recording_name_command__populates_queue(
    test_new_name, expected_new_name, client_and_server_manager_and_shared_values
):
    test_client, (test_server, _), shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["new_name"] = test_new_name
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["config_settings"]["recording_directory"] = "/test/recording/directory"

    test_user_defined_metadata = "test_user_defined_metadata"

    response = test_client.post(
        f"/update_recording_name?new_name={test_new_name}&default_name=old_name&snapshot_enabled=false",
        json={"user_defined_metadata": test_user_defined_metadata},
    )
    assert response.status_code == 200

    to_main_queue = test_server.get_queue_to_main()
    assert is_queue_eventually_not_empty(to_main_queue) is True
    communication = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["new_name"] == expected_new_name
    assert communication["user_defined_metadata"] == test_user_defined_metadata


def test_send_single_initialize_board_command_with_bit_file__populates_queue(
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values
    board_idx = 0
    expected_bit_file_name = "main.bit"
    response = test_client.get(
        f"/insert_xem_command_into_queue/initialize_board?bit_file_name={expected_bit_file_name}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(board_idx)

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
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values
    board_idx = 0
    response = test_client.get("/insert_xem_command_into_queue/initialize_board")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(board_idx)

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


def test_send_single_get_status_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values
    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_status"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_status"
    assert response_json["suppress_error"] is True


def test_send_single_activate_trigger_in_command__populates_queue(
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values
    expected_ep_addr = 10
    expected_bit = 0x00000001
    response = test_client.get(
        f"/insert_xem_command_into_queue/activate_trigger_in?ep_addr={expected_ep_addr}&bit={expected_bit}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
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
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values
    expected_ep_addr = "0x02"
    expected_bit = "0x00000001"
    response = test_client.get(
        f"/insert_xem_command_into_queue/activate_trigger_in?ep_addr={expected_ep_addr}&bit={expected_bit}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
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


def test_send_single_comm_delay_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    expected_num_millis = 35
    response = test_client.get(
        f"/insert_xem_command_into_queue/comm_delay?num_milliseconds={expected_num_millis}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
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


def test_send_single_get_num_words_fifo_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values
    response = test_client.get("/insert_xem_command_into_queue/get_num_words_fifo")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_num_words_fifo"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_num_words_fifo"
    assert response_json["suppress_error"] is True


def test_send_single_set_device_id_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    test_id = "Mantarray XEM"
    response = test_client.get(f"/insert_xem_command_into_queue/set_device_id?new_id={test_id}")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
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


def test_send_single_stop_acquisition_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    response = test_client.get("/insert_xem_command_into_queue/stop_acquisition")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "stop_acquisition"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "stop_acquisition"
    assert response_json["suppress_error"] is True


def test_send_single_start_acquisition_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    response = test_client.get("/insert_xem_command_into_queue/start_acquisition")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "start_acquisition"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "start_acquisition"
    assert response_json["suppress_error"] is True


def test_send_single_get_serial_number_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    response = test_client.get("/insert_xem_command_into_queue/get_serial_number")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_serial_number"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_serial_number"
    assert response_json["suppress_error"] is True


def test_send_single_get_device_id_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    response = test_client.get("/insert_xem_command_into_queue/get_device_id")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_device_id"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_device_id"
    assert response_json["suppress_error"] is True


def test_send_single_is_spi_running_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    response = test_client.get("/insert_xem_command_into_queue/is_spi_running")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "is_spi_running"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "is_spi_running"
    assert response_json["suppress_error"] is True


def test_send_single_read_from_fifo_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    response = test_client.get("/insert_xem_command_into_queue/read_from_fifo?num_words_to_log=72")
    assert response.status_code == 200
    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_from_fifo"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    assert response_json["suppress_error"] is True


def test_send_single_read_from_fifo_command_with_hex_notation__populates_queue(
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    response = test_client.get("/insert_xem_command_into_queue/read_from_fifo?num_words_to_log=0x48")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_from_fifo"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    assert response_json["suppress_error"] is True


def test_send_single_set_wire_in_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    expected_ep_addr = 8
    expected_value = 0x00000010
    expected_mask = 0x00000010
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_wire_in?ep_addr={expected_ep_addr}&value={expected_value}&mask={expected_mask}"
    )
    assert response.status_code == 200
    comm_queue = test_server.queue_container.to_instrument_comm(0)
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
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    expected_ep_addr = "0x05"
    value = "0x000000a0"
    mask = "0x00000011"
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_wire_in?ep_addr={expected_ep_addr}&value={value}&mask={mask}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
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


def test_send_single_xem_scripts_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    expected_script_type = "start_up"
    response = test_client.get(f"/xem_scripts?script_type={expected_script_type}")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "xem_scripts"
    assert communication["script_type"] == expected_script_type
    response_json = response.get_json()
    assert response_json["script_type"] == expected_script_type


def test_send_single_read_wire_out_command__populates_queue__and_logs_response(
    client_and_server_manager_and_shared_values, mocker
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    board_idx = 0
    expected_ep_addr = 6
    mocked_logger = mocker.patch.object(server.logger, "info", autospec=True)
    response = test_client.get(f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(board_idx)
    confirm_queue_is_eventually_of_size(comm_queue, 1)
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
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    board_idx = 0
    expected_ep_addr = "0x6"
    response = test_client.get(f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}")
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(board_idx)
    confirm_queue_is_eventually_of_size(comm_queue, 1)
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
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    board_idx = 0
    expected_ep_addr = 6
    expected_description = "test"
    response = test_client.get(
        f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}&description={expected_description}"
    )
    assert response.status_code == 200

    comm_queue = test_server.queue_container.to_instrument_comm(board_idx)
    confirm_queue_is_eventually_of_size(comm_queue, 1)
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
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE
    shared_values_dict["system_action_transitions"] = {"live_view": None}

    response = test_client.get("/stop_managed_acquisition")
    assert response.status_code == 200

    server_to_main_queue = test_server.get_queue_to_main()
    confirm_queue_is_eventually_of_size(server_to_main_queue, 1)
    comm_to_main = server_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert comm_to_main == STOP_MANAGED_ACQUISITION_COMMUNICATION
    response_json = response.get_json()
    assert response_json == STOP_MANAGED_ACQUISITION_COMMUNICATION


def test_send_single_set_mantarray_serial_number_command__populates_queue(
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    expected_serial_number = "M02001901"

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={expected_serial_number}"
    )
    assert response.status_code == 200

    server_to_main_queue = test_server.get_queue_to_main()
    confirm_queue_is_eventually_of_size(server_to_main_queue, 1)
    communication = server_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_serial_number"
    assert communication["mantarray_serial_number"] == expected_serial_number
    response_json = response.get_json()
    assert response_json["command"] == "set_mantarray_serial_number"
    assert response_json["mantarray_serial_number"] == expected_serial_number


def test_send_single_boot_up_command__populates_queue(client_and_server_manager_and_shared_values):
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values

    response = test_client.get("/boot_up")
    assert response.status_code == 200

    to_main_queue = test_server.get_queue_to_main()

    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    communication = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "to_instrument"
    assert communication["command"] == "boot_up"

    response_json = response.get_json()
    assert response_json == communication


def test_send_single_start_managed_acquisition_command__populates_queues(
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    board_idx = 0
    shared_values_dict["mantarray_serial_number"] = {
        board_idx: MantarrayMcSimulator.default_mantarray_serial_number
    }
    shared_values_dict["stimulator_circuit_statuses"] = {}

    test_barcode = MantarrayMcSimulator.default_plate_barcode
    expected_command = {**START_MANAGED_ACQUISITION_COMMUNICATION, "barcode": test_barcode}

    response = test_client.get(f"/start_managed_acquisition?plate_barcode={test_barcode}")
    assert response.status_code == 200
    response_json = response.get_json()
    assert response_json == expected_command

    to_main_queue = test_server.get_queue_to_main()
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    communication = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication == expected_command


@freeze_time(
    datetime.datetime(year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332597)
    + datetime.timedelta(
        seconds=GENERIC_STOP_RECORDING_COMMAND["timepoint_to_stop_recording_at"]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_stop_recording_command__is_received_by_main__with_default__utcnow_recording_stop_time(
    client_and_server_manager_and_shared_values,
):
    test_client, (test_server, _), shared_values_dict = client_and_server_manager_and_shared_values

    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332597
    )

    shared_values_dict["system_status"] = RECORDING_STATE
    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [expected_acquisition_timestamp]

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


def test_start_recording_command__populates_queue_with_correct_adc_offset_values_if_is_hardware_test_recording_is_true(
    test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    put_generic_beta_1_start_recording_info_in_dict(test_process_manager.values_to_share_to_server)

    expected_adc_offsets = dict()
    for well_idx in range(24):
        expected_adc_offsets[well_idx] = {"construct": 0, "ref": 0}

    barcode = GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    response = test_client.get(f"/start_recording?plate_barcode={barcode}")
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)

    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    assert communication["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"] == expected_adc_offsets


def test_start_recording_command__populates_queue_with_given_time_index_parameter(
    test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    put_generic_beta_1_start_recording_info_in_dict(test_process_manager.values_to_share_to_server)

    expected_time_index = 9600
    barcode = GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    response = test_client.get(
        f"/start_recording?plate_barcode={barcode}&time_index={expected_time_index}&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    assert communication["metadata_to_copy_onto_main_file_attributes"][START_RECORDING_TIME_INDEX_UUID] == (
        expected_time_index / MICROSECONDS_PER_CENTIMILLISECOND
    )
    assert (
        communication["timepoint_to_begin_recording_at"]
        == expected_time_index / MICROSECONDS_PER_CENTIMILLISECOND
    )


def test_start_recording_command__populates_queue_with_correctly_parsed_set_of_well_indices(
    test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    put_generic_beta_1_start_recording_info_in_dict(test_process_manager.values_to_share_to_server)

    expected_plate_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?plate_barcode={expected_plate_barcode}&active_well_indices=0,5,8&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    assert set(communication["active_well_indices"]) == set([0, 8, 5])


def test_start_recording_command__beta_2_mode__populates_queue_with_correct_well_indices(
    test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    shared_values_dict = test_process_manager.values_to_share_to_server
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)

    total_num_wells = 24
    expected_plate_barcode = GENERIC_BETA_2_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?plate_barcode={expected_plate_barcode}&is_hardware_test_recording=False"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    assert set(communication["active_well_indices"]) == set(range(total_num_wells))


@pytest.mark.parametrize(
    "scanned_barcode,user_entered_barcode,expected_result,test_description",
    [
        (
            MantarrayMcSimulator.default_plate_barcode,
            MantarrayMcSimulator.default_plate_barcode.replace("000", "001"),
            False,
            "correctly sets value to False with scanned barcode present",
        ),
        (
            "",
            MantarrayMcSimulator.default_plate_barcode,
            False,
            "correctly sets value to False after barcode scan fails",
        ),
        (
            None,
            MantarrayMcSimulator.default_plate_barcode,
            False,
            "correctly sets value to False without scanned barcode present",
        ),
        (
            MantarrayMcSimulator.default_plate_barcode,
            MantarrayMcSimulator.default_plate_barcode,
            True,
            "correctly sets value to True",
        ),
    ],
)
def test_start_recording_command__correctly_sets_plate_barcode_from_scanner_value(
    scanned_barcode,
    user_entered_barcode,
    expected_result,
    test_description,
    test_process_manager_creator,
    test_client,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    shared_values_dict = test_process_manager.values_to_share_to_server
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)
    shared_values_dict["stimulation_running"] = [False] * 24

    board_idx = 0
    if scanned_barcode is None:
        del shared_values_dict["barcodes"]
    else:
        shared_values_dict["barcodes"][board_idx]["plate_barcode"] = scanned_barcode

    response = test_client.get(
        f"/start_recording?plate_barcode={user_entered_barcode}&is_hardware_test_recording=False"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][PLATE_BARCODE_IS_FROM_SCANNER_UUID]
        is expected_result
    )


@pytest.mark.parametrize(
    "scanned_barcode,user_entered_barcode,expected_result,test_description",
    [
        (
            MantarrayMcSimulator.default_stim_barcode,
            MantarrayMcSimulator.default_stim_barcode.replace("000", "001"),
            False,
            "correctly sets value to False with scanned barcode present",
        ),
        (
            "",
            MantarrayMcSimulator.default_stim_barcode,
            False,
            "correctly sets value to False after barcode scan fails",
        ),
        (
            None,
            MantarrayMcSimulator.default_stim_barcode,
            False,
            "correctly sets value to False without scanned barcode present",
        ),
        (
            MantarrayMcSimulator.default_stim_barcode,
            MantarrayMcSimulator.default_stim_barcode,
            True,
            "correctly sets value to True",
        ),
    ],
)
def test_start_recording_command__correctly_sets_stim_barcode_from_scanner_value(
    scanned_barcode,
    user_entered_barcode,
    expected_result,
    test_description,
    test_process_manager_creator,
    test_client,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    shared_values_dict = test_process_manager.values_to_share_to_server
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)
    shared_values_dict["stimulation_running"] = [True] * 24

    board_idx = 0
    if scanned_barcode is None:
        del shared_values_dict["barcodes"]
    else:
        shared_values_dict["barcodes"][board_idx]["stim_barcode"] = scanned_barcode

    params = {
        "plate_barcode": MantarrayMcSimulator.default_plate_barcode,
        "stim_barcode": user_entered_barcode,
    }
    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(params)}")
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][STIM_BARCODE_IS_FROM_SCANNER_UUID]
        is expected_result
    )


@freeze_time(
    datetime.datetime(year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598)
    + datetime.timedelta(
        seconds=GENERIC_BETA_1_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_start_recording_command__beta_1_mode__populates_queue__with_defaults__24_wells__utcnow_recording_start_time__and_metadata(
    test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    shared_values_dict = test_process_manager.values_to_share_to_server
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)

    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598
    )
    expected_recording_timepoint = GENERIC_BETA_1_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    expected_recording_timestamp = expected_acquisition_timestamp + datetime.timedelta(
        seconds=(expected_recording_timepoint / CENTIMILLISECONDS_PER_SECOND)
    )

    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [expected_acquisition_timestamp]

    expected_plate_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?plate_barcode={expected_plate_barcode}&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"

    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][UTC_BEGINNING_DATA_ACQUISTION_UUID]
        == expected_acquisition_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][UTC_BEGINNING_RECORDING_UUID]
        == expected_recording_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][CUSTOMER_ACCOUNT_ID_UUID]
        == shared_values_dict["config_settings"]["customer_id"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][USER_ACCOUNT_ID_UUID]
        == shared_values_dict["config_settings"]["user_name"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][START_RECORDING_TIME_INDEX_UUID]
        == expected_recording_timepoint
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][SOFTWARE_BUILD_NUMBER_UUID]
        == COMPILED_EXE_BUILD_TIMESTAMP
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][SOFTWARE_RELEASE_VERSION_UUID]
        == CURRENT_SOFTWARE_VERSION
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][MAIN_FIRMWARE_VERSION_UUID]
        == shared_values_dict["main_firmware_version"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][SLEEP_FIRMWARE_VERSION_UUID]
        == shared_values_dict["sleep_firmware_version"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][XEM_SERIAL_NUMBER_UUID]
        == shared_values_dict["xem_serial_number"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][MANTARRAY_SERIAL_NUMBER_UUID]
        == shared_values_dict["mantarray_serial_number"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][MANTARRAY_NICKNAME_UUID]
        == shared_values_dict["mantarray_nickname"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][REFERENCE_VOLTAGE_UUID]
        == REFERENCE_VOLTAGE
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][ADC_GAIN_SETTING_UUID]
        == shared_values_dict["adc_gain"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"]
        == shared_values_dict["adc_offsets"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][PLATE_BARCODE_UUID]
        == expected_plate_barcode
    )
    assert communication["metadata_to_copy_onto_main_file_attributes"][HARDWARE_TEST_RECORDING_UUID] is False

    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][BACKEND_LOG_UUID]
        == GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            BACKEND_LOG_UUID
        ]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][PLATE_BARCODE_IS_FROM_SCANNER_UUID]
        is True
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][COMPUTER_NAME_HASH_UUID]
        == GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            COMPUTER_NAME_HASH_UUID
        ]
    )
    assert set(communication["active_well_indices"]) == set(range(24))
    assert (
        communication["timepoint_to_begin_recording_at"]
        == GENERIC_BETA_1_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    )
    response_json = response.get_json()
    assert response_json["command"] == "start_recording"


@freeze_time(
    datetime.datetime(year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598)
    + datetime.timedelta(
        seconds=GENERIC_BETA_2_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
        / MICRO_TO_BASE_CONVERSION
    )
)
def test_start_recording_command__beta_2_mode__populates_queue__with_defaults__24_wells__utcnow_recording_start_time__and_metadata(
    test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    shared_values_dict = test_process_manager.values_to_share_to_server
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)

    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598
    )
    expected_recording_timepoint = (
        GENERIC_BETA_2_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
        - NUM_INITIAL_MICROSECONDS_TO_PAD
    )
    expected_recording_timestamp = expected_acquisition_timestamp + datetime.timedelta(
        seconds=(
            GENERIC_BETA_2_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
            / MICRO_TO_BASE_CONVERSION
        )
    )

    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [expected_acquisition_timestamp]

    expected_plate_barcode = GENERIC_BETA_2_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?plate_barcode={expected_plate_barcode}&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"

    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][UTC_BEGINNING_DATA_ACQUISTION_UUID]
        == expected_acquisition_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][UTC_BEGINNING_RECORDING_UUID]
        == expected_recording_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][CUSTOMER_ACCOUNT_ID_UUID]
        == shared_values_dict["config_settings"]["customer_id"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][USER_ACCOUNT_ID_UUID]
        == shared_values_dict["config_settings"]["user_name"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][START_RECORDING_TIME_INDEX_UUID]
        == expected_recording_timepoint
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][SOFTWARE_BUILD_NUMBER_UUID]
        == COMPILED_EXE_BUILD_TIMESTAMP
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][SOFTWARE_RELEASE_VERSION_UUID]
        == CURRENT_SOFTWARE_VERSION
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][MAIN_FIRMWARE_VERSION_UUID]
        == shared_values_dict["main_firmware_version"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][MANTARRAY_SERIAL_NUMBER_UUID]
        == shared_values_dict["mantarray_serial_number"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][MANTARRAY_NICKNAME_UUID]
        == shared_values_dict["mantarray_nickname"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][PLATE_BARCODE_UUID]
        == expected_plate_barcode
    )
    assert communication["metadata_to_copy_onto_main_file_attributes"][HARDWARE_TEST_RECORDING_UUID] is False
    assert communication["metadata_to_copy_onto_main_file_attributes"][
        INITIAL_MAGNET_FINDING_PARAMS_UUID
    ] == json.dumps(dict(MantarrayMcSimulator.initial_magnet_finding_params))
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][NUM_INITIAL_MICROSECONDS_TO_REMOVE_UUID]
        == NUM_INITIAL_MICROSECONDS_TO_PAD
    )
    # metadata values from instrument
    instrument_metadata = shared_values_dict["instrument_metadata"][0]
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][BOOT_FLAGS_UUID]
        == instrument_metadata[BOOT_FLAGS_UUID]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][CHANNEL_FIRMWARE_VERSION_UUID]
        == instrument_metadata[CHANNEL_FIRMWARE_VERSION_UUID]
    )
    # make sure current beta 1 only values are not present
    assert SLEEP_FIRMWARE_VERSION_UUID not in communication["metadata_to_copy_onto_main_file_attributes"]
    assert XEM_SERIAL_NUMBER_UUID not in communication["metadata_to_copy_onto_main_file_attributes"]
    assert REFERENCE_VOLTAGE not in communication["metadata_to_copy_onto_main_file_attributes"]
    assert ADC_GAIN_SETTING_UUID not in communication["metadata_to_copy_onto_main_file_attributes"]
    assert "adc_offsets" not in communication["metadata_to_copy_onto_main_file_attributes"]

    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][BACKEND_LOG_UUID]
        == GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            BACKEND_LOG_UUID
        ]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][PLATE_BARCODE_IS_FROM_SCANNER_UUID]
        is True
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][COMPUTER_NAME_HASH_UUID]
        == GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            COMPUTER_NAME_HASH_UUID
        ]
    )
    assert set(communication["active_well_indices"]) == set(range(24))
    assert communication["timepoint_to_begin_recording_at"] == expected_recording_timepoint
    response_json = response.get_json()
    assert response_json["command"] == "start_recording"


@pytest.mark.parametrize(
    "test_stim_info,test_stim_barcode,is_stim_running",
    [
        (None, None, False),
        ({"test": "info"}, None, False),
        ({"test": "info"}, MantarrayMcSimulator.default_stim_barcode, False),
        ({"test": "info"}, MantarrayMcSimulator.default_stim_barcode, True),
    ],
)
def test_start_recording_command__beta_2_mode__populates_queue_with_stim_barcode_correctly(
    test_stim_info, test_stim_barcode, is_stim_running, test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    shared_values_dict = test_process_manager.values_to_share_to_server
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)

    shared_values_dict["stimulation_info"] = test_stim_info
    expected_stim_running_list = [False] * 24
    if is_stim_running:
        expected_stim_running_list[randint(0, 23)] = True
    shared_values_dict["stimulation_running"] = expected_stim_running_list

    test_plate_barcode = GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    params = {"plate_barcode": test_plate_barcode}
    if test_stim_barcode:
        params["stim_barcode"] = test_stim_barcode
    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(params)}")
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    assert communication["command"] == "start_recording"
    expected_stim_barcode = test_stim_barcode if test_stim_barcode else NOT_APPLICABLE_H5_METADATA
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][STIM_BARCODE_UUID]
        == expected_stim_barcode
    )


@pytest.mark.parametrize("recording_name", ["Test Name", None])
def test_start_recording_command__populates_queue_with_recording_file_name_correctly(
    recording_name, test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    shared_values_dict = test_process_manager.values_to_share_to_server
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)

    params = {"plate_barcode": MantarrayMcSimulator.default_plate_barcode}
    if recording_name:
        params["recording_name"] = recording_name

    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(params)}")
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["command"] == "start_recording"
    if recording_name:
        assert communication["recording_name"] == recording_name
    else:
        assert "recording_name" not in communication


@pytest.mark.parametrize(
    "test_platemap",
    [
        None,
        {},
        {
            "map_name": "test platemap name",
            "labels": [{"name": "test-label-1", "wells": [0]}, {"name": "test_label_2", "wells": [1]}],
        },
    ],
)
def test_start_recording_command__populates_queue_with_platemap_info_correctly(
    test_platemap, test_process_manager_creator, test_client
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    put_generic_beta_2_start_recording_info_in_dict(test_process_manager.values_to_share_to_server)

    params = {"plate_barcode": MantarrayMcSimulator.default_plate_barcode}
    if test_platemap is not None:
        params["platemap"] = urllib.parse.quote_plus(json.dumps(test_platemap))
    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(params)}")
    assert response.status_code == 200

    comm_queue = test_process_manager.queue_container.from_flask
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    assert communication["command"] == "start_recording"
    if test_platemap:
        expected_platemap = {
            "name": test_platemap["map_name"],
            "labels": [label_info["name"] for label_info in test_platemap["labels"]]
            + [str(NOT_APPLICABLE_H5_METADATA)] * 22,
        }
    else:
        expected_platemap = {
            "name": str(NOT_APPLICABLE_H5_METADATA),
            "labels": [str(NOT_APPLICABLE_H5_METADATA)] * 24,
        }
    assert communication["platemap"] == expected_platemap


def test_shutdown__sends_hard_stop_command__waits_for_subprocesses_to_stop__then_shutdown_server_command_to_process_monitor(
    client_and_server_manager_and_shared_values, mocker
):
    mocked_queue_command = mocker.spy(server, "queue_command_to_main")

    def se():
        mocked_queue_command.assert_called_once()

    mocked_wait = mocker.patch.object(server, "wait_for_subprocesses_to_stop", autospec=True, side_effect=se)
    mocker.patch.object(server, "_get_values_from_process_monitor", autospec=True)
    test_client, (test_server, _), _ = client_and_server_manager_and_shared_values
    server_to_main_queue = test_server.get_queue_to_main()

    response = test_client.get("/shutdown")
    assert response.status_code == 200
    response_json = response.get_json()

    mocked_wait.assert_called_once()

    confirm_queue_is_eventually_of_size(server_to_main_queue, 2)
    hard_stop_command = server_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert hard_stop_command["communication_type"] == "shutdown"
    assert hard_stop_command["command"] == "hard_stop"
    shutdown_server_command = server_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert shutdown_server_command["communication_type"] == "shutdown"
    assert shutdown_server_command["command"] == "shutdown_server"
    assert response_json == shutdown_server_command


@pytest.mark.parametrize(
    "test_status,test_description",
    [
        ("true", "populates correctly with true"),
        ("True", "populates correctly with True"),
        ("false", "populates correctly with false"),
        ("False", "populates correctly with False"),
    ],
)
def test_set_stim_status__populates_queue_to_process_monitor_with_new_stim_status(
    test_status, test_description, client_and_server_manager_and_shared_values
):
    test_client, (server_manager, _), shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["system_action_transitions"] = {"stimulation": None}
    shared_values_dict["stimulation_info"] = {"protocols": [None] * 4, "protocol_assignments": {}}

    expected_status_bool = test_status in ("true", "True")
    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [not expected_status_bool] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }

    response = test_client.post(f"/set_stim_status?running={test_status}")
    assert response.status_code == 200

    comm_queue = server_manager.get_queue_to_main()
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "stimulation"
    assert communication["command"] == "set_stim_status"
    assert communication["status"] is expected_status_bool


def test_set_protocols__populates_queue_to_process_monitor_with_new_protocol(
    client_and_server_manager_and_shared_values, mocker
):
    test_client, (server_manager, _), shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_delay_dur = STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS + 0.4321

    test_protocol_dict = {
        "protocols": [
            {
                "stimulation_type": "C",
                "protocol_id": "X",
                "run_until_stopped": True,
                "subprotocols": [
                    get_random_stim_delay(test_delay_dur),
                    get_random_stim_pulse(),
                    {
                        "type": "loop",
                        "num_iterations": 10,
                        "subprotocols": [get_random_stim_pulse(), get_random_stim_delay()],
                    },
                ],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "X" for well_idx in range(24)
        },
    }

    expected_protocol_dict = copy.deepcopy(test_protocol_dict)
    expected_delay_subprotocol = expected_protocol_dict["protocols"][0]["subprotocols"][0]
    expected_delay_subprotocol["duration"] = int(expected_delay_subprotocol["duration"])

    # Tanner (11/21/22): using side_effect here so that if this function gets called more than once and error will be raised and prevent the test from hanging
    mocker.patch.object(
        server, "_get_stim_info_from_process_monitor", autospec=True, side_effect=[expected_protocol_dict]
    )
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_protocol_dict)})
    assert response.status_code == 200

    comm_queue = server_manager.get_queue_to_main()
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication["communication_type"] == "stimulation"
    assert communication["command"] == "set_protocols"
    assert communication["stim_info"] == expected_protocol_dict


@pytest.mark.parametrize(
    "test_beta_2_mode,test_comm_dict",
    [
        (True, {"communication_type": "calibration", "command": "run_calibration"}),
        (False, {"communication_type": "xem_scripts", "script_type": "start_calibration"}),
    ],
)
def test_start_calibration__populates_queue_to_process_monitor_with_correct_comm(
    client_and_server_manager_and_shared_values, test_beta_2_mode, test_comm_dict
):
    test_client, (server_manager, _), shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATION_NEEDED_STATE
    shared_values_dict["beta_2_mode"] = test_beta_2_mode
    if test_beta_2_mode:
        test_num_wells = 24
        shared_values_dict["stimulation_running"] = [False] * test_num_wells
        shared_values_dict["stimulator_circuit_statuses"] = {}

    response = test_client.get("/start_calibration")
    assert response.status_code == 200

    comm_queue = server_manager.get_queue_to_main()
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication == test_comm_dict


def test_start_stim_checks__populates_queue_to_process_monitor_with_correct_comm(
    client_and_server_manager_and_shared_values,
):
    test_client, (server_manager, _), shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["beta_2_mode"] = True

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = {}

    test_well_indices = [i for i in range(test_num_wells) if random_bool()]
    if not test_well_indices:
        # guard against unlikely case where no wells were selected
        test_well_indices = [0]

    test_stim_barcode = MantarrayMcSimulator.default_stim_barcode
    test_plate_barcode = MantarrayMcSimulator.default_plate_barcode

    expected_comm_dict = {
        "communication_type": "stimulation",
        "command": "start_stim_checks",
        "well_indices": test_well_indices,
        "plate_barcode": test_plate_barcode,
        "stim_barcode": test_stim_barcode,
        "plate_barcode_is_from_scanner": False,
        "stim_barcode_is_from_scanner": False,
    }

    response = test_client.post(
        "/start_stim_checks",
        json={
            "well_indices": [str(well_idx) for well_idx in test_well_indices],
            "plate_barcode": test_plate_barcode,
            "stim_barcode": test_stim_barcode,
        },
    )
    assert response.status_code == 200

    comm_queue = server_manager.get_queue_to_main()
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication == expected_comm_dict


def test_latest_software_version__returns_ok_when_version_string_is_a_valid_semantic_version(
    client_and_server_manager_and_shared_values,
):
    test_client, (server_manager, _), shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    test_version = "10.10.10"
    response = test_client.post(f"/latest_software_version?version={test_version}")
    assert response.status_code == 200

    comm_queue = server_manager.get_queue_to_main()
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication == {"communication_type": "set_latest_software_version", "version": test_version}


@pytest.mark.parametrize("user_response", ["true", "True", "false", "False"])
def test_firmware_update_confirmation__sends_correct_command_to_main(
    user_response, client_and_server_manager_and_shared_values
):
    test_client, (server_manager, _), shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    update_accepted = user_response in ("true", "True")

    response = test_client.post(f"/firmware_update_confirmation?update_accepted={update_accepted}")
    assert response.status_code == 200

    comm_queue = server_manager.get_queue_to_main()
    confirm_queue_is_eventually_of_size(comm_queue, 1)
    communication = comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert communication == {
        "communication_type": "firmware_update_confirmation",
        "update_accepted": update_accepted,
    }
