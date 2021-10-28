# -*- coding: utf-8 -*-
import base64
import datetime
import json
import math
import os
import tempfile
import time
import uuid

from freezegun import freeze_time
import h5py
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import get_stimulation_dataset_from_file
from mantarray_desktop_app import get_time_index_dataset_from_file
from mantarray_desktop_app import get_time_offset_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import RAW_TO_SIGNED_CONVERSION_VALUE
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import server
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app import wait_for_subprocesses_to_start
from mantarray_desktop_app import WELL_24_INDEX_TO_ADC_AND_CH_INDEX
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_file_manager import ADC_GAIN_SETTING_UUID
from mantarray_file_manager import ADC_REF_OFFSET_UUID
from mantarray_file_manager import ADC_TISSUE_OFFSET_UUID
from mantarray_file_manager import BACKEND_LOG_UUID
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import BOOTUP_COUNTER_UUID
from mantarray_file_manager import COMPUTER_NAME_HASH_UUID
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import FILE_FORMAT_VERSION_METADATA_KEY
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import IS_FILE_ORIGINAL_UNTRIMMED_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import METADATA_UUID_DESCRIPTIONS
from mantarray_file_manager import NOT_APPLICABLE_H5_METADATA
from mantarray_file_manager import ORIGINAL_FILE_VERSION_UUID
from mantarray_file_manager import PCB_SERIAL_NUMBER_UUID
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import REF_SAMPLING_PERIOD_UUID
from mantarray_file_manager import REFERENCE_VOLTAGE_UUID
from mantarray_file_manager import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_file_manager import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
from mantarray_file_manager import STIMULATION_PROTOCOL_UUID
from mantarray_file_manager import TAMPER_FLAG_UUID
from mantarray_file_manager import TISSUE_SAMPLING_PERIOD_UUID
from mantarray_file_manager import TOTAL_WELL_COUNT_UUID
from mantarray_file_manager import TOTAL_WORKING_HOURS_UUID
from mantarray_file_manager import TRIMMED_TIME_FROM_ORIGINAL_END_UUID
from mantarray_file_manager import TRIMMED_TIME_FROM_ORIGINAL_START_UUID
from mantarray_file_manager import USER_ACCOUNT_ID_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_BEGINNING_RECORDING_UUID
from mantarray_file_manager import UTC_BEGINNING_STIMULATION_UUID
from mantarray_file_manager import UTC_FIRST_REF_DATA_POINT_UUID
from mantarray_file_manager import UTC_FIRST_TISSUE_DATA_POINT_UUID
from mantarray_file_manager import WELL_COLUMN_UUID
from mantarray_file_manager import WELL_INDEX_UUID
from mantarray_file_manager import WELL_NAME_UUID
from mantarray_file_manager import WELL_ROW_UUID
from mantarray_file_manager import XEM_SERIAL_NUMBER_UUID
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
from ..fixtures import fixture_patched_xem_scripts_folder
from ..fixtures_file_writer import GENERIC_BETA_1_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_BOARD_MAGNETOMETER_CONFIGURATION
from ..fixtures_file_writer import GENERIC_NUM_CHANNELS_ENABLED
from ..fixtures_file_writer import GENERIC_NUM_SENSORS_ENABLED
from ..fixtures_file_writer import WELL_DEF_24
from ..fixtures_mc_simulator import get_null_subprotocol
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_server import fixture_test_socketio_client
from ..helpers import confirm_queue_is_eventually_empty

__fixtures__ = [
    fixture_fully_running_app_from_main_entrypoint,
    fixture_patched_xem_scripts_folder,
    fixture_patched_firmware_folder,
    fixture_test_socketio_client,
]
LIVE_VIEW_ACTIVE_WAIT_TIME = 150
CALIBRATED_WAIT_TIME = 10
STOP_MANAGED_ACQUISITION_WAIT_TIME = 40
INTEGRATION_TEST_TIMEOUT = 720
FIRST_METRIC_WAIT_TIME = 20


def stimulation_running_status_eventually_equals(expected_status: bool, timeout: int) -> bool:
    """Check if stimulation status reaches the expected status before the timeout."""
    is_expected_status = False
    start = time.perf_counter()
    elapsed_time = 0.0
    while not is_expected_status and elapsed_time < timeout:
        response = requests.get(f"{get_api_endpoint()}system_status")
        is_expected_status = response.json()["is_stimulating"] is expected_status
        if is_expected_status and response.status_code == 200:
            break
        time.sleep(0.5)  # Don't just relentlessly ping the Flask server
        elapsed_time = time.perf_counter() - start
    return is_expected_status


@pytest.mark.timeout(60)
@pytest.mark.slow
def test_send_xem_scripts_command__gets_processed_in_fully_running_app(
    fully_running_app_from_main_entrypoint,
    patched_xem_scripts_folder,
):

    # Tanner (12/29/20): start up the app but skip automatic instrument boot-up process so we can manually test that xem_scripts are run
    app_info = fully_running_app_from_main_entrypoint(["--skip-mantarray-boot-up"])
    wait_for_subprocesses_to_start()

    test_process_manager = app_info["object_access_inside_main"]["process_manager"]
    test_process_monitor = app_info["object_access_inside_main"]["process_monitor"]
    shared_values_dict = app_info["object_access_inside_main"]["values_to_share_to_server"]
    monitor_error_queue = test_process_monitor.get_fatal_error_reporter()

    # Tanner (12/29/20): init with no bit file since local development environment does not have any real bit files and we are using a simulator
    response = requests.get(f"{get_api_endpoint()}insert_xem_command_into_queue/initialize_board")
    assert response.status_code == 200

    # Tanner (12/29/20): Test xem_scripts will run using start up script. When this script completes the system will be in calibration_needed state
    expected_script_type = "start_up"
    response = requests.get(f"{get_api_endpoint()}xem_scripts?script_type={expected_script_type}")
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5)

    # Tanner (12/30/20): Soft stopping and joining this process in order to make assertions
    instrument_process = test_process_manager.get_instrument_process()
    instrument_process.soft_stop()
    instrument_process.join()

    # Tanner (12/29/20): Easiest way to assert the start up script successfully ran is to assert that shared_values_dict contains the correct value for "adc_gain" and make sure the error queue is empty
    expected_gain_value = 16
    assert shared_values_dict["adc_gain"] == expected_gain_value
    confirm_queue_is_eventually_empty(monitor_error_queue)


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
@freeze_time(datetime.datetime(year=2020, month=7, day=16, hour=14, minute=19, second=55, microsecond=313309))
def test_system_states_and_recording_files__with_file_directory_passed_in_cmd_line_args__and_skip_mantarray_boot_up_flag(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
    mocker,
):
    # Tanner (12/29/20): Freeze time in order to make assertions on timestamps in the metadata
    expected_time = datetime.datetime(
        year=2020, month=7, day=16, hour=14, minute=19, second=55, microsecond=313309
    )
    mocker.patch.object(
        server,
        "_get_timestamp_of_acquisition_sample_index_zero",
        return_value=expected_time,
    )
    expected_timestamp = "2020_07_16_141955"
    # Tanner (12/29/20): Use TemporaryDirectory so we can access the files without worrying about clean up
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        # Tanner (12/29/20): Sending in alternate recording directory through command line args
        test_dict = {
            "stored_customer_ids": {
                "73f52be0-368c-42d8-a1fd-660d49ba5604": "filler_password",
            },
            "zipped_recordings_dir": f"{expected_recordings_dir}/zipped_recordings",
            "failed_uploads_dir": f"{expected_recordings_dir}/failed_uploads",
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
        test_process_manager = app_info["object_access_inside_main"]["process_manager"]

        # Tanner (12/30/20): Make sure we are in server_ready state before sending commands
        response = requests.get(f"{get_api_endpoint()}system_status")
        assert response.status_code == 200
        assert response.json()["ui_status_code"] == str(SYSTEM_STATUS_UUIDS[SERVER_READY_STATE])

        # Tanner (12/29/20): Manually boot up in order to start managed_acquisition and recording later
        response = requests.get(f"{get_api_endpoint()}boot_up")
        assert response.status_code == 200

        # Tanner (12/30/20): Boot up will go through these two states before completing
        assert system_state_eventually_equals(INSTRUMENT_INITIALIZING_STATE, 3) is True
        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 3) is True

        response = requests.get(
            f"{get_api_endpoint()}update_settings?customer_account_uuid=73f52be0-368c-42d8-a1fd-660d49ba5604&customer_pass_key=filler_password&user_account_uuid=73f52be0-368c-42d8-a1fd-660d49ba5604&recording_directory={expected_recordings_dir}&auto_upload=true&auto_delete=false"
        )
        assert response.status_code == 200

        # Tanner (12/30/20): Calibrate instrument in order to start managed_acquisition
        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATING_STATE, 3) is True
        assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

        # Tanner (12/29/20): Start acquiring and recording data for recording files
        response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(BUFFERING_STATE, 3) is True
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

        # Tanner (12/30/20): Need to start recording in order to test that recorded files are in the correct directory
        expected_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][PLATE_BARCODE_UUID]
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode}&is_hardware_test_recording=False"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 3) is True

        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files

        # Tanner (12/30/20): Stop recording to finalize files
        response = requests.get(f"{get_api_endpoint()}stop_recording")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True

        # Tanner (12/29/20): stop managed acquisition in order to successfully soft-stop all processes
        response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True

        # Tanner (8/18/21): Processes must be joined to avoid h5 errors with reading files, so hard-stopping before joining
        test_process_manager.hard_stop_and_join_processes()

        actual_set_of_files = set(
            os.listdir(os.path.join(expected_recordings_dir, f"{expected_barcode}__{expected_timestamp}"))
        )
        # Tanner (12/29/20): Only assert that files for all 24 wells are present
        assert len(actual_set_of_files) == 24


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
def test_managed_acquisition_can_be_stopped_and_restarted_with_simulator(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
    test_socketio_client,
):
    app_info = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()
    test_process_manager = app_info["object_access_inside_main"]["process_manager"]

    sio, msg_list_container = test_socketio_client()

    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    # Tanner (12/30/20): Calibrate instrument in order to start managed_acquisition
    response = requests.get(f"{get_api_endpoint()}start_calibration")
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

    # First run
    # Tanner (12/30/20): Run managed_acquisition until in live_view state. This will confirm that data passed through the system completely
    response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
    assert response.status_code == 200
    assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True
    response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True

    # Tanner (6/21/21): Double check that the expected amount of data passed through the system
    assert len(msg_list_container["waveform_data"]) >= 2

    time.sleep(3)  # allow remaining data to pass through subprocesses

    # Second run
    # Tanner (12/30/20): Run managed_acquisition until in live_view state. This will confirm that data passed through the system completely
    response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
    assert response.status_code == 200
    assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True
    response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True

    # Tanner (6/21/21): disconnect here to avoid problems with attempting to disconnect after the server stops
    sio.disconnect()

    # Tanner (12/29/20): Good to do this at the end of tests to make sure they don't cause problems with other integration tests. This will also clear available data in Data Analyzer
    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
@freeze_time(datetime.datetime(year=2020, month=6, day=15, hour=14, minute=19, second=55, microsecond=313309))
def test_system_states_and_recorded_metadata_with_update_to_file_writer_directory__and_files_after_stop_then_restart_recording_contain_waveform_data(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
    mocker,
):
    # pylint: disable=too-many-locals,too-many-statements # Tanner (12/29/20): Freeze time in order to make assertions on timestamps in the metadata
    expected_time = datetime.datetime(
        year=2020, month=6, day=15, hour=14, minute=19, second=55, microsecond=313309
    )
    mocker.patch.object(
        server,
        "_get_timestamp_of_acquisition_sample_index_zero",
        return_value=expected_time,
    )
    expected_timestamp = "2020_06_15_141955"
    # Tanner (12/29/20): Patching uuid4 so we get an expected UUID for the Log Files
    mocker.patch.object(
        uuid,
        "uuid4",
        autospec=True,
        return_value=GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            BACKEND_LOG_UUID
        ],
    )
    with tempfile.TemporaryDirectory() as expected_recordings_dir:

        test_dict = {
            "stored_customer_ids": {
                "73f52be0-368c-42d8-a1fd-660d49ba5604": "filler_password",
            },
            "user_account_id": "455b93eb-c78f-4494-9f73-d3291130f126",
            "zipped_recordings_dir": f"/{expected_recordings_dir}/zipped_recordings",
            "failed_uploads_dir": f"{expected_recordings_dir}/failed_uploads",
            "recording_directory": f"/{expected_recordings_dir}",
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
        command_line_args = [f"--initial-base64-settings={b64_encoded}", "--skip-mantarray-boot-up"]

        # Tanner (12/30/20): Skip auto boot-up so we can set the recording directory before boot-up
        app_info = fully_running_app_from_main_entrypoint(command_line_args)
        wait_for_subprocesses_to_start()

        test_process_manager = app_info["object_access_inside_main"]["process_manager"]

        assert system_state_eventually_equals(SERVER_READY_STATE, 5) is True

        # Tanner (12/29/20): Use TemporaryDirectory so we can access the files without worrying about clean up
        # Tanner (12/29/20): Manually set recording directory through update_settings route
        response = requests.get(
            f"{get_api_endpoint()}update_settings?customer_account_uuid=73f52be0-368c-42d8-a1fd-660d49ba5604&customer_pass_key=filler_password&user_account_uuid=455b93eb-c78f-4494-9f73-d3291130f126&recording_directory={expected_recordings_dir}&auto_upload=true&auto_delete=false"
        )
        assert response.status_code == 200

        # Tanner (12/29/20): Manually boot up in order to start managed_acquisition later
        response = requests.get(f"{get_api_endpoint()}boot_up")
        assert response.status_code == 200
        assert system_state_eventually_equals(INSTRUMENT_INITIALIZING_STATE, 5) is True

        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 3) is True
        # Tanner (12/30/20): Calibrate instrument in order to start managed_acquisition
        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATING_STATE, 3) is True

        assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

        # Tanner (12/29/20): Start acquiring and recording data for recording files
        response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(BUFFERING_STATE, 3) is True

        # Tanner (12/30/20): Run managed_acquisition until in live_view state. This will confirm that data passed through the system completely
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True
        expected_barcode_1 = GENERIC_BETA_1_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][PLATE_BARCODE_UUID]
        start_recording_time_index_1 = 960
        # Tanner (12/30/20): Start recording with barcode1 to create first set of files. Don't start recording at time index 0 since that data frame is discarded due to bit file issues
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode_1}&time_index={start_recording_time_index_1}&is_hardware_test_recording=False"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 3) is True
        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files
        # Tanner (12/30/20): End recording at a known timepoint so next recording can start at a known timepoint
        expected_stop_index_1 = int(1.9 * CENTIMILLISECONDS_PER_SECOND)
        response = requests.get(f"{get_api_endpoint()}stop_recording?time_index={expected_stop_index_1}")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True

        # Tanner (12/29/20): Use new barcode for second set of recordings
        expected_barcode_2 = (
            expected_barcode_1[:-1] + "2"
        )  # change last char of default barcode from '1' to '2'
        # Tanner (12/30/20): Start recording with barcode2 to create second set of files. Use known timepoint a just after end of first set of data
        expected_start_index_2 = expected_stop_index_1 + 1
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode_2}&time_index={expected_start_index_2}&is_hardware_test_recording=False"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 3) is True
        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files
        response = requests.get(f"{get_api_endpoint()}stop_recording")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True

        # Tanner (12/30/20): Stop managed_acquisition so processes can be stopped
        response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True

        # Tanner (6/15/20): Processes must be joined to avoid h5 errors with reading files, so hard-stopping before joining
        test_process_manager.hard_stop_and_join_processes()

        actual_set_of_files = set(
            os.listdir(
                os.path.join(
                    expected_recordings_dir,
                    f"{expected_barcode_1}__{expected_timestamp}",
                )
            )
        )
        assert len(actual_set_of_files) == 24

        # test first recording for all data and metadata
        for row_idx in range(4):
            for col_idx in range(6):
                well_idx = col_idx * 4 + row_idx
                with h5py.File(
                    os.path.join(
                        expected_recordings_dir,
                        f"{expected_barcode_1}__{expected_timestamp}",
                        f"{expected_barcode_1}__{expected_timestamp}__{WELL_DEF_24.get_well_name_from_row_and_column(row_idx, col_idx)}.h5",
                    ),
                    "r",
                ) as this_file:
                    this_file_attrs = this_file.attrs
                    assert bool(this_file_attrs[str(HARDWARE_TEST_RECORDING_UUID)]) is False
                    assert this_file_attrs[str(SOFTWARE_BUILD_NUMBER_UUID)] == COMPILED_EXE_BUILD_TIMESTAMP
                    assert (
                        this_file_attrs[str(ORIGINAL_FILE_VERSION_UUID)]
                        == CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
                    )
                    assert (
                        this_file_attrs[FILE_FORMAT_VERSION_METADATA_KEY]
                        == CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
                    )
                    assert this_file_attrs[str(UTC_BEGINNING_DATA_ACQUISTION_UUID)] == expected_time.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )
                    assert (
                        this_file_attrs[str(START_RECORDING_TIME_INDEX_UUID)] == start_recording_time_index_1
                    )
                    assert this_file.attrs[str(UTC_BEGINNING_RECORDING_UUID)] == expected_time.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )
                    assert this_file_attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == (
                        expected_time
                        + datetime.timedelta(
                            seconds=(
                                start_recording_time_index_1
                                + WELL_24_INDEX_TO_ADC_AND_CH_INDEX[well_idx][1] * DATA_FRAME_PERIOD
                            )
                            / CENTIMILLISECONDS_PER_SECOND
                        )
                    ).strftime("%Y-%m-%d %H:%M:%S.%f")
                    assert this_file_attrs[str(UTC_FIRST_REF_DATA_POINT_UUID)] == (
                        expected_time
                        + datetime.timedelta(
                            seconds=(start_recording_time_index_1 + DATA_FRAME_PERIOD)
                            / CENTIMILLISECONDS_PER_SECOND
                        )
                    ).strftime("%Y-%m-%d %H:%M:%S.%f")
                    assert this_file_attrs[str(USER_ACCOUNT_ID_UUID)] == str(CURI_BIO_USER_ACCOUNT_ID)
                    assert this_file_attrs[str(CUSTOMER_ACCOUNT_ID_UUID)] == str(CURI_BIO_ACCOUNT_UUID)
                    assert this_file_attrs[str(ADC_GAIN_SETTING_UUID)] == 16
                    assert (
                        this_file_attrs[str(ADC_TISSUE_OFFSET_UUID)] == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
                    )
                    assert this_file_attrs[str(ADC_REF_OFFSET_UUID)] == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
                    assert this_file_attrs[str(REFERENCE_VOLTAGE_UUID)] == REFERENCE_VOLTAGE
                    assert this_file_attrs[str(SLEEP_FIRMWARE_VERSION_UUID)] == "0.0.0"
                    assert (
                        this_file_attrs[str(MAIN_FIRMWARE_VERSION_UUID)]
                        == RunningFIFOSimulator.default_firmware_version
                    )
                    assert (
                        this_file_attrs[str(MANTARRAY_SERIAL_NUMBER_UUID)]
                        == RunningFIFOSimulator.default_mantarray_serial_number
                    )
                    assert (
                        this_file_attrs[str(MANTARRAY_NICKNAME_UUID)]
                        == RunningFIFOSimulator.default_mantarray_nickname
                    )
                    assert (
                        this_file_attrs[str(XEM_SERIAL_NUMBER_UUID)]
                        == RunningFIFOSimulator.default_xem_serial_number
                    )
                    assert this_file_attrs[str(SOFTWARE_RELEASE_VERSION_UUID)] == CURRENT_SOFTWARE_VERSION

                    assert (
                        this_file_attrs[str(WELL_NAME_UUID)]
                        == f"{WELL_DEF_24.get_well_name_from_row_and_column(row_idx, col_idx)}"
                    )
                    assert this_file_attrs["Metadata UUID Descriptions"] == json.dumps(
                        str(METADATA_UUID_DESCRIPTIONS)
                    )
                    assert bool(this_file_attrs[str(IS_FILE_ORIGINAL_UNTRIMMED_UUID)]) is True
                    assert this_file_attrs[str(TRIMMED_TIME_FROM_ORIGINAL_START_UUID)] == 0
                    assert this_file_attrs[str(TRIMMED_TIME_FROM_ORIGINAL_END_UUID)] == 0
                    assert this_file_attrs[str(TOTAL_WELL_COUNT_UUID)] == 24
                    assert this_file_attrs[str(WELL_ROW_UUID)] == row_idx
                    assert this_file_attrs[str(WELL_COLUMN_UUID)] == col_idx
                    assert this_file_attrs[
                        str(WELL_INDEX_UUID)
                    ] == WELL_DEF_24.get_well_index_from_row_and_column(row_idx, col_idx)
                    assert (
                        this_file_attrs[str(TISSUE_SAMPLING_PERIOD_UUID)]
                        == CONSTRUCT_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
                    )
                    assert (
                        this_file_attrs[str(REF_SAMPLING_PERIOD_UUID)]
                        == REFERENCE_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
                    )
                    assert this_file_attrs[str(BACKEND_LOG_UUID)] == str(
                        GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                            BACKEND_LOG_UUID
                        ]
                    )
                    assert (
                        this_file_attrs[str(COMPUTER_NAME_HASH_UUID)]
                        == GENERIC_BETA_1_START_RECORDING_COMMAND[
                            "metadata_to_copy_onto_main_file_attributes"
                        ][COMPUTER_NAME_HASH_UUID]
                    )
                    # Tanner (1/12/21): The barcode used for testing (which is passed to start_recording route) is different than the simulator's barcode (the one that is 'scanned' in this test), so this should result to False
                    assert bool(this_file_attrs[str(BARCODE_IS_FROM_SCANNER_UUID)]) is False

        expected_timestamp = expected_timestamp[:-1] + "7"
        # Tanner (12/30/20): test second recording (only make sure it contains waveform data)
        for row_idx in range(4):
            for col_idx in range(6):
                with h5py.File(
                    os.path.join(
                        expected_recordings_dir,
                        f"{expected_barcode_2}__2020_06_15_141957",
                        f"{expected_barcode_2}__2020_06_15_141957__{WELL_DEF_24.get_well_name_from_row_and_column(row_idx, col_idx)}.h5",
                    ),
                    "r",
                ) as this_file:
                    assert str(START_RECORDING_TIME_INDEX_UUID) in this_file.attrs
                    start_index_2 = this_file.attrs[str(START_RECORDING_TIME_INDEX_UUID)]
                    assert (  # Tanner (1/13/21): Here we are testing that the 'finalizing' state of File Writer is working correctly by asserting that the second set of recorded files start at the right time index
                        start_index_2 == expected_start_index_2
                    )
                    assert str(UTC_FIRST_TISSUE_DATA_POINT_UUID) in this_file.attrs
                    assert str(UTC_FIRST_REF_DATA_POINT_UUID) in this_file.attrs
                    actual_tissue_data = get_tissue_dataset_from_file(this_file)
                    assert actual_tissue_data.shape[0] > 0


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
def test_full_datapath_in_beta_1_mode(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
    test_socketio_client,
):
    app_info = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()
    test_process_manager = app_info["object_access_inside_main"]["process_manager"]

    sio, msg_list_container = test_socketio_client()

    # Tanner (12/30/20): Auto boot-up is completed when system reaches calibration_needed state
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    da_out = test_process_manager.queue_container().get_data_analyzer_data_out_queue()

    # Tanner (12/30/20): Start calibration in order to run managed_acquisition
    response = requests.get(f"{get_api_endpoint()}start_calibration")
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

    # Tanner (12/30/20): start managed_acquisition in order to get data moving through data path
    acquisition_request = f"{get_api_endpoint()}start_managed_acquisition"
    response = requests.get(acquisition_request)
    assert response.status_code == 200
    assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

    # Tanner (7/14/21): Wait for data metric message to be produced
    start = time.perf_counter()
    while time.perf_counter() - start < FIRST_METRIC_WAIT_TIME:
        if msg_list_container["twitch_metrics"]:
            break
        time.sleep(0.5)
    # Tanner (7/14/21): Check that list was populated after loop
    assert len(msg_list_container["twitch_metrics"]) > 0

    # Tanner (12/30/20): stop managed_acquisition now that we have a known min amount of data available
    response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True
    # Tanner (7/14/21): Beta 1 data packets are sent once per second, so there should be at least one data packet for every second needed to run analysis, but sometimes the final data packet doesn't get sent in time
    assert len(msg_list_container["waveform_data"]) >= MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 1
    confirm_queue_is_eventually_empty(da_out)

    # Tanner (12/29/20): create expected data
    test_well_index = 0
    x_values = np.array(
        [
            ROUND_ROBIN_PERIOD * (i + 1) // TIMESTEP_CONVERSION_FACTOR
            for i in range(math.ceil(CENTIMILLISECONDS_PER_SECOND / ROUND_ROBIN_PERIOD))
        ]
    )
    sawtooth_points = signal.sawtooth(x_values / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5)
    scaling_factor = test_well_index + 1
    data_amplitude = int(FIFO_READ_PRODUCER_WELL_AMPLITUDE * scaling_factor)
    test_data = np.array(
        (
            x_values,
            (
                (FIFO_READ_PRODUCER_DATA_OFFSET + data_amplitude * sawtooth_points)
                - RAW_TO_SIGNED_CONVERSION_VALUE
            ),
        ),
        dtype=np.int32,
    )
    test_data[1] -= min(test_data[1])
    pl_template = PipelineTemplate(
        noise_filter_uuid=BUTTERWORTH_LOWPASS_30_UUID,
        tissue_sampling_period=ROUND_ROBIN_PERIOD,
    )
    pipeline = pl_template.create_pipeline()
    pipeline.load_raw_gmr_data(test_data, np.zeros(test_data.shape))
    expected_well_data = pipeline.get_compressed_force()

    # Tanner (12/29/20): Assert data is as expected for two wells
    waveform_data_points = json.loads(msg_list_container["waveform_data"][0])["waveform_data"]["basic_data"][
        "waveform_data_points"
    ]
    actual_well_0_y_data = waveform_data_points["0"]["y_data_points"]
    np.testing.assert_almost_equal(
        actual_well_0_y_data[0],
        expected_well_data[1][0] * MICRO_TO_BASE_CONVERSION,
        decimal=2,
    )
    np.testing.assert_almost_equal(
        actual_well_0_y_data[2],
        expected_well_data[1][2] * MICRO_TO_BASE_CONVERSION,
        decimal=2,
    )

    # Tanner (6/21/21): disconnect here to avoid problems with attempting to disconnect after the server stops
    sio.disconnect()

    # Tanner (12/29/20): Good to do this at the end of tests to make sure they don't cause problems with other integration tests
    remaining_queue_items = test_process_manager.hard_stop_and_join_processes()
    # Tanner (12/31/20): Make sure that there were no errors in Data Analyzer
    da_error_list = remaining_queue_items["data_analyzer_items"]["fatal_error_reporter"]
    assert len(da_error_list) == 0


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
def test_app_shutdown__in_worst_case_while_recording_is_running(
    patched_xem_scripts_folder, patched_firmware_folder, fully_running_app_from_main_entrypoint, mocker
):
    spied_logger = mocker.spy(main.logger, "info")
    # Tanner (12/29/20): Not making assertions on files, but still need a TemporaryDirectory to hold them
    with tempfile.TemporaryDirectory() as tmp_dir:

        test_dict = {
            "stored_customer_ids": {
                "73f52be0-368c-42d8-a1fd-660d49ba5604": "filler_password",
            },
            "user_account_id": "455b93eb-c78f-4494-9f73-d3291130f126",
            "zipped_recordings_dir": f"{tmp_dir}/zipped_recordings",
            "failed_uploads_dir": f"{tmp_dir}/failed_uploads",
            "recording_directory": tmp_dir,
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
        command_line_args = [
            f"--initial-base64-settings={b64_encoded}",
        ]

        app_info = fully_running_app_from_main_entrypoint(command_line_args)
        wait_for_subprocesses_to_start()
        test_process_manager = app_info["object_access_inside_main"]["process_manager"]

        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

        okc_process = test_process_manager.get_instrument_process()
        fw_process = test_process_manager.get_file_writer_process()
        da_process = test_process_manager.get_data_analyzer_process()

        # Tanner (12/29/20): Not making assertions on files, but still need a TemporaryDirectory to hold them
        # Tanner (12/29/20): use updated settings to set the recording directory to the TemporaryDirectory

        response = requests.get(
            f"{get_api_endpoint()}update_settings?customer_account_uuid=73f52be0-368c-42d8-a1fd-660d49ba5604&customer_pass_key=filler_password&auto_upload=true&auto_delete=false"
        )
        assert response.status_code == 200

        # Tanner (12/30/20): Start calibration in order to run managed_acquisition
        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATING_STATE, 5) is True

        assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

        # Tanner (12/30/20): start managed_acquisition in order to start recording
        response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
        assert response.status_code == 200

        # Tanner (12/30/20): managed_acquisition will take system through buffering state and then to live_view active state before recording can start
        assert system_state_eventually_equals(BUFFERING_STATE, 5) is True
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

        expected_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][PLATE_BARCODE_UUID]
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode}&is_hardware_test_recording=False"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 5) is True

        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files

        # Tanner (12/29/20): Shutdown now that data is being acquired and actively written to files, which means each subprocess is doing something
        response = requests.get(f"{get_api_endpoint()}shutdown")
        assert response.status_code == 200

        # Tanner (12/30/20): Confirming the port is available to make sure that the Flask server has shutdown
        confirm_port_available(get_server_port_number(), timeout=10)
        # Tanner (6/21/21): sleep to ensure program exit log message is produced
        time.sleep(5)

        # Tanner (12/30/20): This is the very last log message before the app is completely shutdown
        spied_logger.assert_any_call("Program exiting")

        # Tanner (12/29/20): If these are alive, this means that zombie processes will be created when the compiled desktop app EXE is running, so this assertion helps make sure that that won't happen
        assert okc_process.is_alive() is False
        assert fw_process.is_alive() is False
        assert da_process.is_alive() is False


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
@freeze_time(datetime.datetime(year=2021, month=5, day=24, hour=21, minute=23, second=4, microsecond=141738))
def test_full_datapath_and_recorded_files_in_beta_2_mode(
    fully_running_app_from_main_entrypoint,
    test_socketio_client,
    mocker,
):
    # pylint: disable=too-many-statements,too-many-locals  # Tanner (6/1/21): This is a long integration test, it needs extra statements and local variables

    # Tanner (12/29/20): Freeze time in order to make assertions on timestamps in the metadata
    expected_time = datetime.datetime(
        year=2021, month=5, day=24, hour=21, minute=23, second=4, microsecond=141738
    )
    mocker.patch.object(
        server,
        "_get_timestamp_of_acquisition_sample_index_zero",
        return_value=expected_time,
    )
    # Tanner (12/29/20): Patching uuid4 so we get an expected UUID for the Log Files
    mocker.patch.object(
        uuid,
        "uuid4",
        autospec=True,
        return_value=GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            BACKEND_LOG_UUID
        ],
    )

    test_protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
            "A" if well_idx % 2 == 0 else "B"
        )
        for well_idx in range(24)
    }
    test_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "V",
                "run_until_stopped": True,
                "subprotocols": [
                    get_random_subprotocol(total_active_duration=1000),
                    get_null_subprotocol(500),
                    get_random_subprotocol(total_active_duration=1000),
                    get_null_subprotocol(500),
                ],
            },
            {
                "protocol_id": "B",
                "stimulation_type": "C",
                "run_until_stopped": False,
                "subprotocols": [
                    get_random_subprotocol(total_active_duration=1000),
                    get_random_subprotocol(total_active_duration=1000),
                    get_random_subprotocol(total_active_duration=1000),
                ],
            },
        ],
        "protocol_assignments": test_protocol_assignments,
    }

    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        test_dict = {
            "stored_customer_ids": {
                "73f52be0-368c-42d8-a1fd-660d49ba5604": "filler_password",
            },
            "user_account_id": "455b93eb-c78f-4494-9f73-d3291130f126",
            "zipped_recordings_dir": f"{expected_recordings_dir}/zipped_recordings",
            "failed_uploads_dir": f"{expected_recordings_dir}/failed_uploads",
            "recording_directory": expected_recordings_dir,
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
        command_line_args = [
            "--beta-2-mode",
            f"--initial-base64-settings={b64_encoded}",
        ]

        app_info = fully_running_app_from_main_entrypoint(command_line_args)
        wait_for_subprocesses_to_start()
        test_process_manager = app_info["object_access_inside_main"]["process_manager"]

        sio, msg_list_container = test_socketio_client()

        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 10) is True

        da_out = test_process_manager.queue_container().get_data_analyzer_data_out_queue()

        response = requests.get(
            f"{get_api_endpoint()}update_settings?customer_account_uuid=73f52be0-368c-42d8-a1fd-660d49ba5604&customer_pass_key=filler_password&auto_upload=true&auto_delete=false"
        )
        assert response.status_code == 200

        # Tanner (5/22/21): Set magnetometer configuration so data streaming can be initiated
        expected_sampling_period = 10000
        magnetometer_config_dict = {
            "magnetometer_config": GENERIC_BOARD_MAGNETOMETER_CONFIGURATION,
            "sampling_period": expected_sampling_period,
        }
        response = requests.post(
            f"{get_api_endpoint()}set_magnetometer_config", json=json.dumps(magnetometer_config_dict)
        )
        assert response.status_code == 200

        # Tanner (10/22/21): Set stimulation protocols and start stimulation
        response = requests.post(
            f"{get_api_endpoint()}set_protocols", json={"data": json.dumps(test_stim_info)}
        )
        assert response.status_code == 200
        response = requests.post(f"{get_api_endpoint()}set_stim_status?running=true")
        assert response.status_code == 200
        assert stimulation_running_status_eventually_equals(True, 4) is True
        # sleep to let protocol B complete before starting live view
        time.sleep(5)

        # TODO Tanner (5/22/21): Should eventually remove this route call from this test as it is not needed for Beta 2 and is only used right now to put the system in the calibrated state
        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

        # Tanner (6/1/21): Start managed_acquisition in order to start recording
        response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(BUFFERING_STATE, 5) is True
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

        expected_barcode_1 = GENERIC_BETA_2_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][PLATE_BARCODE_UUID]
        expected_start_index_1 = 0
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode_1}&time_index={expected_start_index_1}&is_hardware_test_recording=False"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 3) is True

        # Tanner (7/14/21): Wait for data metric message to be produced
        start = time.perf_counter()
        while time.perf_counter() - start < FIRST_METRIC_WAIT_TIME:
            if msg_list_container["twitch_metrics"]:
                break
            time.sleep(0.5)
        # Tanner (7/14/21): Check that list was populated after loop
        assert len(msg_list_container["twitch_metrics"]) > 0

        # Tanner (6/1/21): End recording at a known timepoint
        expected_stop_index_1 = expected_start_index_1 + int(2e6)
        response = requests.get(f"{get_api_endpoint()}stop_recording?time_index={expected_stop_index_1}")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True

        # Tanner (7/14/21): Stop managed_acquisition now that we have a known min amount of data available
        response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True
        # Tanner (7/14/21): Beta 2 data packets are currently sent once per second, so there should be at least one data packet for every second needed to run analysis, but sometimes the final data packet doesn't get sent in time
        assert len(msg_list_container["waveform_data"]) >= MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 1
        confirm_queue_is_eventually_empty(da_out)

        # Tanner (10/22/21): Stop stimulation
        response = requests.post(f"{get_api_endpoint()}set_stim_status?running=false")
        assert response.status_code == 200
        assert stimulation_running_status_eventually_equals(False, 4) is True

        # Tanner (6/1/21): Make sure managed_acquisition can be restarted
        response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
        assert response.status_code == 200
        # Tanner (6/1/21): managed_acquisition in beta 2 mode will currently only cause the system to enter buffering state. This is because no beta 2 data will come out of Data Analyzer yet
        assert system_state_eventually_equals(BUFFERING_STATE, 5) is True
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

        # Tanner (10/22/21): Restart stimulation
        response = requests.post(f"{get_api_endpoint()}set_stim_status?running=true")
        assert response.status_code == 200
        assert stimulation_running_status_eventually_equals(True, 4) is True

        # Tanner (6/1/21): Use new barcode for second set of recordings, change last char of default barcode from '1' to '2'
        expected_barcode_2 = expected_barcode_1[:-1] + "2"
        # Tanner (5/25/21): Start at a different timepoint to create a different timestamp in the names of the second set of files
        expected_start_index_2 = MICRO_TO_BASE_CONVERSION

        # Tanner (6/1/21): Start recording with second barcode to create second set of files
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode_2}&time_index={expected_start_index_2}&is_hardware_test_recording=False"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 3) is True

        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files

        expected_stop_index_2 = expected_start_index_2 + int(1.5e6)
        response = requests.get(f"{get_api_endpoint()}stop_recording?time_index={expected_stop_index_2}")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True

        # Tanner (10/22/21): Stop stimulation
        response = requests.post(f"{get_api_endpoint()}set_stim_status?running=false")
        assert response.status_code == 200
        assert stimulation_running_status_eventually_equals(False, 4) is True

        # Tanner (6/1/21): Stop managed_acquisition
        response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True
        confirm_queue_is_eventually_empty(da_out)

        # Tanner (6/19/21): disconnect here to avoid problems with attempting to disconnect after the server stops
        sio.disconnect()

        # Tanner (6/15/20): Processes must be joined to avoid h5 errors with reading files, so hard-stopping before joining
        test_process_manager.hard_stop_and_join_processes()

        expected_timestamp_1 = "2021_05_24_212304"
        actual_set_of_files = set(
            os.listdir(
                os.path.join(
                    expected_recordings_dir,
                    f"{expected_barcode_1}__{expected_timestamp_1}",
                )
            )
        )
        assert len(actual_set_of_files) == 24

        # test first recording for all data and metadata
        num_recorded_data_points_1 = (
            expected_stop_index_1 - expected_start_index_1
        ) // expected_sampling_period + 1
        for well_idx in range(24):
            well_name = WELL_DEF_24.get_well_name_from_well_index(well_idx)
            with h5py.File(
                os.path.join(
                    expected_recordings_dir,
                    f"{expected_barcode_1}__{expected_timestamp_1}",
                    f"{expected_barcode_1}__{expected_timestamp_1}__{well_name}.h5",
                ),
                "r",
            ) as this_file:
                # test metadata values
                this_file_attrs = this_file.attrs
                assert bool(this_file_attrs[str(HARDWARE_TEST_RECORDING_UUID)]) is False
                assert this_file_attrs[str(SOFTWARE_BUILD_NUMBER_UUID)] == COMPILED_EXE_BUILD_TIMESTAMP
                assert (
                    this_file_attrs[str(ORIGINAL_FILE_VERSION_UUID)] == CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
                )
                assert (
                    this_file_attrs[FILE_FORMAT_VERSION_METADATA_KEY]
                    == CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
                )
                assert this_file_attrs[str(UTC_BEGINNING_DATA_ACQUISTION_UUID)] == expected_time.strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )
                assert this_file_attrs[str(START_RECORDING_TIME_INDEX_UUID)] == expected_start_index_1
                assert this_file.attrs[str(UTC_BEGINNING_RECORDING_UUID)] == expected_time.strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )
                assert this_file_attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == (
                    expected_time + datetime.timedelta(seconds=expected_start_index_1)
                ).strftime("%Y-%m-%d %H:%M:%S.%f")
                assert this_file_attrs[str(USER_ACCOUNT_ID_UUID)] == str(CURI_BIO_USER_ACCOUNT_ID)
                assert this_file_attrs[str(CUSTOMER_ACCOUNT_ID_UUID)] == str(CURI_BIO_ACCOUNT_UUID)
                assert (
                    this_file_attrs[str(MAIN_FIRMWARE_VERSION_UUID)]
                    == MantarrayMcSimulator.default_firmware_version
                )
                assert (
                    this_file_attrs[str(MANTARRAY_SERIAL_NUMBER_UUID)]
                    == MantarrayMcSimulator.default_mantarray_serial_number
                )
                assert (
                    this_file_attrs[str(MANTARRAY_NICKNAME_UUID)]
                    == MantarrayMcSimulator.default_mantarray_nickname
                )
                assert this_file_attrs[str(SOFTWARE_RELEASE_VERSION_UUID)] == CURRENT_SOFTWARE_VERSION
                assert (
                    this_file_attrs[str(BOOTUP_COUNTER_UUID)]
                    == MantarrayMcSimulator.default_metadata_values[BOOTUP_COUNTER_UUID]
                )
                assert (
                    this_file_attrs[str(TOTAL_WORKING_HOURS_UUID)]
                    == MantarrayMcSimulator.default_metadata_values[TOTAL_WORKING_HOURS_UUID]
                )
                assert (
                    this_file_attrs[str(TAMPER_FLAG_UUID)]
                    == MantarrayMcSimulator.default_metadata_values[TAMPER_FLAG_UUID]
                )
                assert (
                    this_file_attrs[str(PCB_SERIAL_NUMBER_UUID)]
                    == MantarrayMcSimulator.default_pcb_serial_number
                )

                assert this_file_attrs[str(WELL_NAME_UUID)] == well_name
                assert this_file_attrs["Metadata UUID Descriptions"] == json.dumps(
                    str(METADATA_UUID_DESCRIPTIONS)
                )
                assert bool(this_file_attrs[str(IS_FILE_ORIGINAL_UNTRIMMED_UUID)]) is True
                assert this_file_attrs[str(TRIMMED_TIME_FROM_ORIGINAL_START_UUID)] == 0
                assert this_file_attrs[str(TRIMMED_TIME_FROM_ORIGINAL_END_UUID)] == 0
                assert this_file_attrs[str(TOTAL_WELL_COUNT_UUID)] == 24
                row_idx, col_idx = WELL_DEF_24.get_row_and_column_from_well_index(well_idx)
                assert this_file_attrs[str(WELL_ROW_UUID)] == row_idx
                assert this_file_attrs[str(WELL_COLUMN_UUID)] == col_idx
                assert this_file_attrs[str(WELL_INDEX_UUID)] == well_idx
                assert this_file_attrs[str(TISSUE_SAMPLING_PERIOD_UUID)] == expected_sampling_period
                assert this_file_attrs[str(BACKEND_LOG_UUID)] == str(
                    GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        BACKEND_LOG_UUID
                    ]
                )
                assert (
                    this_file_attrs[str(COMPUTER_NAME_HASH_UUID)]
                    == GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        COMPUTER_NAME_HASH_UUID
                    ]
                )
                if well_idx % 2 == 0:
                    assert this_file_attrs[str(STIMULATION_PROTOCOL_UUID)] == json.dumps(
                        test_stim_info["protocols"][0]
                    ), well_idx
                    assert this_file_attrs[str(UTC_BEGINNING_STIMULATION_UUID)] != str(
                        NOT_APPLICABLE_H5_METADATA
                    ), well_idx
                else:
                    assert this_file_attrs[str(STIMULATION_PROTOCOL_UUID)] == json.dumps(None), well_idx
                    assert this_file_attrs[str(UTC_BEGINNING_STIMULATION_UUID)] == str(
                        NOT_APPLICABLE_H5_METADATA
                    ), well_idx
                # Tanner (1/12/21): The barcode used for testing (which is passed to start_recording route) is different than the simulator's barcode (the one that is 'scanned' in this test), so this should result to False
                assert bool(this_file_attrs[str(BARCODE_IS_FROM_SCANNER_UUID)]) is False
                # test recorded magnetometer data
                actual_time_index_data = get_time_index_dataset_from_file(this_file)
                assert actual_time_index_data.shape == (num_recorded_data_points_1,)
                assert actual_time_index_data[0] == expected_start_index_1
                assert actual_time_index_data[-1] == expected_stop_index_1
                actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
                assert actual_time_offset_data.shape == (
                    GENERIC_NUM_SENSORS_ENABLED,
                    num_recorded_data_points_1,
                )
                actual_tissue_data = get_tissue_dataset_from_file(this_file)
                assert actual_tissue_data.shape == (
                    GENERIC_NUM_CHANNELS_ENABLED,
                    num_recorded_data_points_1,
                )
                # test recorded stim data
                actual_stim_data = get_stimulation_dataset_from_file(this_file)
                assert actual_stim_data.shape[0] == 2
                if well_idx % 2 == 0:
                    assert actual_stim_data.shape[1] > 0, well_idx
                else:
                    assert actual_stim_data.shape[1] == 0, well_idx

        expected_timestamp_2 = "2021_05_24_212305"
        # Tanner (12/30/20): test second recording (only make sure it contains waveform data)
        num_recorded_data_points_2 = (
            expected_stop_index_2 - expected_start_index_2
        ) // expected_sampling_period + 1
        for well_idx in range(24):
            well_name = WELL_DEF_24.get_well_name_from_well_index(well_idx)
            with h5py.File(
                os.path.join(
                    expected_recordings_dir,
                    f"{expected_barcode_2}__{expected_timestamp_2}",
                    f"{expected_barcode_2}__{expected_timestamp_2}__{well_name}.h5",
                ),
                "r",
            ) as this_file:
                # test metadata
                assert str(START_RECORDING_TIME_INDEX_UUID) in this_file.attrs
                start_index_2 = this_file.attrs[str(START_RECORDING_TIME_INDEX_UUID)]
                assert (  # Tanner (1/13/21): Here we are testing that the 'finalizing' state of File Writer is working correctly by asserting that the second set of recorded files start at the right time index
                    start_index_2 == expected_start_index_2
                )
                assert str(UTC_FIRST_TISSUE_DATA_POINT_UUID) in this_file.attrs
                assert this_file.attrs[str(STIMULATION_PROTOCOL_UUID)] == json.dumps(
                    test_stim_info["protocols"][well_idx % 2]
                ), well_idx
                assert this_file.attrs[str(UTC_BEGINNING_STIMULATION_UUID)] != str(
                    NOT_APPLICABLE_H5_METADATA
                ), well_idx
                # test recorded magnetometer data
                actual_time_index_data = get_time_index_dataset_from_file(this_file)
                assert actual_time_index_data.shape == (num_recorded_data_points_2,), f"Well {well_idx}"
                assert actual_time_index_data[0] == expected_start_index_2
                assert actual_time_index_data[-1] == expected_stop_index_2
                actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
                assert actual_time_offset_data.shape == (
                    GENERIC_NUM_SENSORS_ENABLED,
                    num_recorded_data_points_2,
                )
                actual_tissue_data = get_tissue_dataset_from_file(this_file)
                assert actual_tissue_data.shape == (
                    GENERIC_NUM_CHANNELS_ENABLED,
                    num_recorded_data_points_2,
                )
                # test recorded stim data
                actual_stim_data = get_stimulation_dataset_from_file(this_file)
                assert actual_stim_data.shape[0] == 2
                if well_idx % 2 == 0:
                    # since this protocol is not set to stop running after a certain amount of time, assert that a min value was reached rather than an exact number
                    assert actual_stim_data.shape[1] >= 5, well_idx
                else:
                    assert actual_stim_data.shape[1] == 4, well_idx
