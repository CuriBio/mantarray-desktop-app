# -*- coding: utf-8 -*-
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_mantarray_process_manager
from mantarray_desktop_app import get_mantarray_processes_monitor
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import wait_for_subprocesses_to_start
import pytest
import requests
from stdlib_utils import confirm_port_in_use
from xem_wrapper import FrontPanelSimulator

from .fixtures import fixture_fully_running_app_from_main_entrypoint
from .fixtures import fixture_patched_firmware_folder
from .fixtures import fixture_patched_shared_values_dict
from .fixtures import fixture_patched_short_calibration_script
from .fixtures import fixture_patched_start_recording_shared_dict
from .fixtures import fixture_patched_test_xem_scripts_folder
from .fixtures import fixture_patched_xem_scripts_folder
from .fixtures import fixture_test_client
from .fixtures import fixture_test_process_manager
from .helpers import is_queue_eventually_empty
from .helpers import is_queue_eventually_not_empty

__fixtures__ = [
    fixture_fully_running_app_from_main_entrypoint,
    fixture_patched_shared_values_dict,
    fixture_test_client,
    fixture_test_process_manager,
    fixture_patched_start_recording_shared_dict,
    fixture_patched_xem_scripts_folder,
    fixture_patched_firmware_folder,
    fixture_patched_xem_scripts_folder,
    fixture_patched_short_calibration_script,
    fixture_patched_test_xem_scripts_folder,
]


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

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get_nowait()
    assert communication["command"] == "get_status"
    assert communication["response"] == expected_response


@pytest.mark.timeout(20)
@pytest.mark.slow
def test_send_xem_scripts_command__gets_processed_in_fully_running_app(
    fully_running_app_from_main_entrypoint,
    patched_xem_scripts_folder,
    patched_shared_values_dict,
):
    _ = fully_running_app_from_main_entrypoint(["--skip-mantarray-boot-up"])
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=5)
    wait_for_subprocesses_to_start()

    test_process_manager = get_mantarray_process_manager()
    test_process_monitor = get_mantarray_processes_monitor()
    monitor_error_queue = test_process_monitor.get_fatal_error_reporter()

    response = requests.get(
        f"{get_api_endpoint()}insert_xem_command_into_queue/initialize_board"
    )
    assert response.status_code == 200

    expected_script_type = "start_up"
    response = requests.get(
        f"{get_api_endpoint()}xem_scripts?script_type={expected_script_type}"
    )
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5)

    ok_comm_process = test_process_manager.get_ok_comm_process()
    ok_comm_process.soft_stop()
    ok_comm_process.join()

    expected_gain_value = 16
    assert patched_shared_values_dict["adc_gain"] == expected_gain_value
    assert is_queue_eventually_empty(monitor_error_queue) is True
