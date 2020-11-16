# -*- coding: utf-8 -*-
import datetime
import os

from freezegun import freeze_time
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_mantarray_process_manager
from mantarray_desktop_app import get_mantarray_processes_monitor
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import PLATE_BARCODE_UUID
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_desktop_app import wait_for_subprocesses_to_start
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
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
from .fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
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
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
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

    assert patched_start_recording_shared_dict["system_status"] == RECORDING_STATE
    assert patched_start_recording_shared_dict["is_hardware_test_recording"] is False

    test_process_manager.soft_stop_and_join_processes()
    error_queue = test_process_manager.get_file_writer_error_queue()

    assert is_queue_eventually_empty(error_queue) is True
    file_dir = test_process_manager.get_file_writer_process().get_file_directory()
    actual_files = os.listdir(
        os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}")
    )
    assert actual_files == [f"{expected_barcode}__2020_02_09_190935__D1.h5"]


@pytest.mark.slow
@freeze_time(
    GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ]
)
def test_start_recording_command__gets_processed_with_given_time_index_parameter(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_time_index = 10000000
    timestamp_str = (
        GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        + datetime.timedelta(
            seconds=(expected_time_index / CENTIMILLISECONDS_PER_SECOND)
        )
    ).strftime("%Y_%m_%d_%H%M%S")
    patched_start_recording_shared_dict[  # pylint: disable=duplicate-code
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

    assert patched_start_recording_shared_dict["system_status"] == RECORDING_STATE
    assert patched_start_recording_shared_dict["is_hardware_test_recording"] is True

    test_process_manager.soft_stop_and_join_processes()
    error_queue = test_process_manager.get_file_writer_error_queue()

    assert is_queue_eventually_empty(error_queue) is True
    file_dir = test_process_manager.get_file_writer_process().get_file_directory()
    actual_files = os.listdir(
        os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}")
    )
    assert actual_files == [f"{expected_barcode}__{timestamp_str}__D1.h5"]


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
