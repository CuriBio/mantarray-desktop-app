# -*- coding: utf-8 -*-
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import wait_for_subprocesses_to_start
import pytest
import requests
from stdlib_utils import confirm_port_in_use
import base64
import datetime
import json
import math
import os
import tempfile
import time

from freezegun import freeze_time
import h5py
from mantarray_desktop_app import ADC_GAIN_SETTING_UUID
from mantarray_desktop_app import ADC_REF_OFFSET_UUID
from mantarray_desktop_app import ADC_TISSUE_OFFSET_UUID
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_desktop_app import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import main
from mantarray_desktop_app import MAIN_FIRMWARE_VERSION_UUID
from mantarray_desktop_app import MANTARRAY_NICKNAME_UUID
from mantarray_desktop_app import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MILLIVOLTS_PER_VOLT
from mantarray_desktop_app import PLATE_BARCODE_UUID
from mantarray_desktop_app import RAW_TO_SIGNED_CONVERSION_VALUE
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import REF_SAMPLING_PERIOD_UUID
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import REFERENCE_VOLTAGE_UUID
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_desktop_app import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_desktop_app import START_RECORDING_TIME_INDEX_UUID,server
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app import TISSUE_SAMPLING_PERIOD_UUID
from mantarray_desktop_app import TOTAL_WELL_COUNT_UUID
from mantarray_desktop_app import USER_ACCOUNT_ID_UUID
from mantarray_desktop_app import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_desktop_app import UTC_BEGINNING_RECORDING_UUID
from mantarray_desktop_app import UTC_FIRST_REF_DATA_POINT_UUID
from mantarray_desktop_app import UTC_FIRST_TISSUE_DATA_POINT_UUID
from mantarray_desktop_app import wait_for_subprocesses_to_start
from mantarray_desktop_app import WELL_24_INDEX_TO_ADC_AND_CH_INDEX
from mantarray_desktop_app import WELL_COLUMN_UUID
from mantarray_desktop_app import WELL_INDEX_UUID
from mantarray_desktop_app import WELL_NAME_UUID
from mantarray_desktop_app import WELL_ROW_UUID
from mantarray_desktop_app import XEM_SERIAL_NUMBER_UUID
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import METADATA_UUID_DESCRIPTIONS
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_waveform_analysis import BUTTERWORTH_LOWPASS_30_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
from mantarray_waveform_analysis import PipelineTemplate
import numpy as np
import pytest
import requests
from scipy import signal
from stdlib_utils import confirm_port_available

from ..fixtures import fixture_fully_running_app_from_main_entrypoint
from ..fixtures import fixture_patched_firmware_folder
from ..fixtures import fixture_patched_shared_values_dict
from ..fixtures import fixture_patched_short_calibration_script
from ..fixtures import fixture_patched_start_recording_shared_dict
from ..fixtures import fixture_patched_test_xem_scripts_folder,GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS 
from ..fixtures import fixture_patched_xem_scripts_folder

from ..fixtures import fixture_test_process_manager
from ..fixtures import fixture_fully_running_app_from_main_entrypoint
from ..fixtures import fixture_patched_firmware_folder
from ..fixtures import fixture_patched_shared_values_dict
from ..fixtures import fixture_patched_xem_scripts_folder

from ..fixtures import fixture_test_process_manager
from ..fixtures import fixture_test_process_manager_without_created_processes
from ..fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from ..helpers import is_queue_eventually_empty

__fixtures__ = [
    fixture_fully_running_app_from_main_entrypoint,
    
    fixture_test_process_manager,
    fixture_patched_shared_values_dict,
    fixture_patched_xem_scripts_folder,
    fixture_patched_firmware_folder,
    fixture_test_process_manager_without_created_processes,
]
LIVE_VIEW_ACTIVE_WAIT_TIME = 120
CALIBRATED_WAIT_TIME = 10
STOP_MANAGED_ACQUISITION_WAIT_TIME = 40
INTEGRATION_TEST_TIMEOUT = 720

@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_send_xem_scripts_command__gets_processed_in_fully_running_app(
    fully_running_app_from_main_entrypoint,
    patched_xem_scripts_folder,
    
):
    app_info = fully_running_app_from_main_entrypoint(["--skip-mantarray-boot-up"])
    wait_for_subprocesses_to_start()
    
    

    test_process_manager = app_info['object_access_inside_main']['process_manager']
    test_process_monitor = app_info['object_access_inside_main']['process_monitor']
    shared_values_dict=app_info['object_access_inside_main']['values_to_share_to_server']
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
    assert shared_values_dict["adc_gain"] == expected_gain_value
    assert is_queue_eventually_empty(monitor_error_queue) is True


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
@freeze_time(
    datetime.datetime(
        year=2020, month=7, day=16, hour=14, minute=19, second=55, microsecond=313309
    )
)
def test_system_states_and_recording_files_with_file_directory_passed_in_cmd_line_args(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    
    
    fully_running_app_from_main_entrypoint,
    mocker,
):
    expected_time = datetime.datetime(
        year=2020, month=7, day=16, hour=14, minute=19, second=55, microsecond=313309
    )
    mocker.patch.object(
        server,
        "_get_timestamp_of_acquisition_sample_index_zero",
        return_value=expected_time,
    )
    expected_timestamp = "2020_07_16_141955"

    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        test_dict = {
            "user_account_uuid": "0288efbc-7705-4946-8815-02701193f766",
            "customer_account_uuid": "14b9294a-9efb-47dd-a06e-8247e982e196",
            "recording_directory": expected_recordings_dir,
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")

        command_line_args = [
            "--skip-mantarray-boot-up",
            f"--initial-base64-settings={b64_encoded}",
        ]
        app_info = fully_running_app_from_main_entrypoint(command_line_args)
        wait_for_subprocesses_to_start()
        test_process_manager=app_info['object_access_inside_main']['process_manager']
        test_process_monitor=app_info['object_access_inside_main']['process_monitor']
        response = requests.get(f"{get_api_endpoint()}system_status")
        assert response.status_code == 200
        assert response.json()["ui_status_code"] == str(
            SYSTEM_STATUS_UUIDS[SERVER_READY_STATE]
        )

        response = requests.get(f"{get_api_endpoint()}boot_up")
        assert response.status_code == 200
        print ('in the test after calling boot-up')
        assert system_state_eventually_equals(INSTRUMENT_INITIALIZING_STATE, 3) is True
        # time.sleep(0.1) # wait for the status to change
        # response = requests.get(f"{get_api_endpoint()}system_status")
        # assert response.status_code == 200
        # assert response.json()["ui_status_code"] == str(
        #     SYSTEM_STATUS_UUIDS[INSTRUMENT_INITIALIZING_STATE]
        # )
        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 3) is True

        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        # response = requests.get(f"{get_api_endpoint()}system_status")
        # assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATING_STATE, 3) is True
        # assert response.json()["ui_status_code"] == str(
        #     SYSTEM_STATUS_UUIDS[CALIBRATING_STATE]
        # )
        assert (
            system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME)
            is True
        )

        response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(BUFFERING_STATE, 3) is True
        # response = requests.get(f"{get_api_endpoint()}system_status")
        # assert response.status_code == 200
        # assert response.json()["ui_status_code"] == str(
        #     SYSTEM_STATUS_UUIDS[BUFFERING_STATE]
        # )
        assert (
            system_state_eventually_equals(
                LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME
            )
            is True
        )

        expected_barcode = GENERIC_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][PLATE_BARCODE_UUID]
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode}&is_hardware_test_recording=False"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 3) is True
        # response = requests.get(f"{get_api_endpoint()}system_status")
        # assert response.status_code == 200
        # assert response.json()["ui_status_code"] == str(
        #     SYSTEM_STATUS_UUIDS[RECORDING_STATE]
        # )

        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files

        response = requests.get(f"{get_api_endpoint()}stop_recording")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True
        # response = requests.get(f"{get_api_endpoint()}system_status")
        # assert response.status_code == 200
        # assert response.json()["ui_status_code"] == str(
        #     SYSTEM_STATUS_UUIDS[LIVE_VIEW_ACTIVE_STATE]
        # )

        response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
        assert response.status_code == 200
        # response = requests.get(f"{get_api_endpoint()}system_status")
        # assert response.status_code == 200
        assert (
            system_state_eventually_equals(
                CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME
            )
            is True
        )

        test_process_manager.soft_stop_processes()

        fw_process = (
            test_process_manager.get_file_writer_process()
        )
        fw_process.close_all_files()
        actual_set_of_files = set(
            os.listdir(
                os.path.join(
                    expected_recordings_dir, f"{expected_barcode}__{expected_timestamp}"
                )
            )
        )
        assert len(actual_set_of_files) == 24

        test_process_manager.hard_stop_and_join_processes()
