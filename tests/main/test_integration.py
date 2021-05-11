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
from mantarray_desktop_app import CURRENT_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import main
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MILLIVOLTS_PER_VOLT
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
from mantarray_file_manager import ADC_GAIN_SETTING_UUID
from mantarray_file_manager import ADC_REF_OFFSET_UUID
from mantarray_file_manager import ADC_TISSUE_OFFSET_UUID
from mantarray_file_manager import BACKEND_LOG_UUID
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import COMPUTER_NAME_HASH_UUID
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import FILE_FORMAT_VERSION_METADATA_KEY
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import IS_FILE_ORIGINAL_UNTRIMMED_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import METADATA_UUID_DESCRIPTIONS
from mantarray_file_manager import ORIGINAL_FILE_VERSION_UUID
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import REF_SAMPLING_PERIOD_UUID
from mantarray_file_manager import REFERENCE_VOLTAGE_UUID
from mantarray_file_manager import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_file_manager import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
from mantarray_file_manager import TISSUE_SAMPLING_PERIOD_UUID
from mantarray_file_manager import TOTAL_WELL_COUNT_UUID
from mantarray_file_manager import TRIMMED_TIME_FROM_ORIGINAL_END_UUID
from mantarray_file_manager import TRIMMED_TIME_FROM_ORIGINAL_START_UUID
from mantarray_file_manager import USER_ACCOUNT_ID_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_BEGINNING_RECORDING_UUID
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
from ..fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from ..fixtures_file_writer import WELL_DEF_24
from ..helpers import confirm_queue_is_eventually_empty

__fixtures__ = [
    fixture_fully_running_app_from_main_entrypoint,
    fixture_patched_xem_scripts_folder,
    fixture_patched_firmware_folder,
]
LIVE_VIEW_ACTIVE_WAIT_TIME = 150
CALIBRATED_WAIT_TIME = 10
STOP_MANAGED_ACQUISITION_WAIT_TIME = 40
INTEGRATION_TEST_TIMEOUT = 720


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
        expected_barcode = GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            PLATE_BARCODE_UUID
        ]
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

        test_process_manager.soft_stop_processes()

        fw_process = test_process_manager.get_file_writer_process()
        # Tanner (12/29/20): Closing all files to avoid issues when reading them
        fw_process.close_all_files()
        actual_set_of_files = set(
            os.listdir(os.path.join(expected_recordings_dir, f"{expected_barcode}__{expected_timestamp}"))
        )
        # Tanner (12/29/20): Only assert that files for all 24 wells are present
        assert len(actual_set_of_files) == 24

        # Tanner (12/29/20): Good to do this at the end of tests to make sure they don't cause problems with other integration tests
        test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
def test_managed_acquisition_can_be_stopped_and_restarted_with_simulator(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
):
    app_info = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()
    test_process_manager = app_info["object_access_inside_main"]["process_manager"]

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

    # Tanner (12/30/20): Clear available data and double check that the expected amount of data passed through the system
    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 200
    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 200

    time.sleep(3)  # allow remaining data to pass through subprocesses

    # Second run
    # Tanner (12/30/20): Run managed_acquisition until in live_view state. This will confirm that data passed through the system completely
    response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
    assert response.status_code == 200
    assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True
    response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True

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
    # Tanner (12/29/20): Freeze time in order to make assertions on timestamps in the metadata
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
        return_value=GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            BACKEND_LOG_UUID
        ],
    )

    # Tanner (12/30/20): Skip auto boot-up so we can set the recording directory before boot-up
    app_info = fully_running_app_from_main_entrypoint(["--skip-mantarray-boot-up"])
    wait_for_subprocesses_to_start()

    test_process_manager = app_info["object_access_inside_main"]["process_manager"]

    assert system_state_eventually_equals(SERVER_READY_STATE, 5) is True

    # Tanner (12/29/20): Use TemporaryDirectory so we can access the files without worrying about clean up
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        # Tanner (12/29/20): Manually set recording directory through update_settings route
        response = requests.get(
            f"{get_api_endpoint()}update_settings?customer_account_uuid=curi&recording_directory={expected_recordings_dir}"
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
        expected_barcode1 = GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            PLATE_BARCODE_UUID
        ]
        start_recording_time_index = 960
        # Tanner (12/30/20): Start recording with barcode1 to create first set of files. Don't start recording at time index 0 since that data frame is discarded due to bit file issues
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode1}&time_index={start_recording_time_index}&is_hardware_test_recording=False"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 3) is True
        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files
        # Tanner (12/30/20): End recording at a known timepoint so next recording can start at a known timepoint
        expected_stop_index_1 = 190000
        response = requests.get(f"{get_api_endpoint()}stop_recording?time_index={expected_stop_index_1}")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True

        # Tanner (12/29/20): Use new barcode for second set of recordings
        expected_barcode2 = (
            expected_barcode1[:-1] + "2"
        )  # change last char of default barcode from '1' to '2'
        # Tanner (12/30/20): Start recording with barcode2 to create second set of files. Use known timepoint a just after end of first set of data
        expected_start_index_2 = expected_stop_index_1 + 1
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode2}&time_index={expected_start_index_2}&is_hardware_test_recording=False"
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

        # Tanner (12/30/20): stop processes in order to make assertions on recorded data
        test_process_manager.soft_stop_processes()

        fw_process = test_process_manager.get_file_writer_process()
        fw_process.close_all_files()

        actual_set_of_files = set(
            os.listdir(
                os.path.join(
                    expected_recordings_dir,
                    f"{expected_barcode1}__{expected_timestamp}",
                )
            )
        )
        assert len(actual_set_of_files) == 24

        # Tanner (6/15/20): Processes must be joined to avoid h5 errors with reading files, so hard-stopping before joining
        test_process_manager.hard_stop_and_join_processes()

        # test first recording for all data and metadata
        for row_idx in range(4):
            for col_idx in range(6):
                well_idx = col_idx * 4 + row_idx
                with h5py.File(
                    os.path.join(
                        expected_recordings_dir,
                        f"{expected_barcode1}__{expected_timestamp}",
                        f"{expected_barcode1}__{expected_timestamp}__{WELL_DEF_24.get_well_name_from_row_and_column(row_idx, col_idx)}.h5",
                    ),
                    "r",
                ) as this_file:
                    this_file_attrs = this_file.attrs
                    assert bool(this_file_attrs[str(HARDWARE_TEST_RECORDING_UUID)]) is False
                    assert this_file_attrs[str(SOFTWARE_BUILD_NUMBER_UUID)] == COMPILED_EXE_BUILD_TIMESTAMP
                    assert (
                        this_file_attrs[str(ORIGINAL_FILE_VERSION_UUID)] == CURRENT_HDF5_FILE_FORMAT_VERSION
                    )
                    assert (
                        this_file_attrs[FILE_FORMAT_VERSION_METADATA_KEY] == CURRENT_HDF5_FILE_FORMAT_VERSION
                    )
                    assert this_file_attrs[str(UTC_BEGINNING_DATA_ACQUISTION_UUID)] == expected_time.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )
                    assert this_file_attrs[str(START_RECORDING_TIME_INDEX_UUID)] == start_recording_time_index
                    assert this_file.attrs[str(UTC_BEGINNING_RECORDING_UUID)] == expected_time.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )
                    assert this_file_attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == (
                        expected_time
                        + datetime.timedelta(
                            seconds=(
                                start_recording_time_index
                                + WELL_24_INDEX_TO_ADC_AND_CH_INDEX[well_idx][1] * DATA_FRAME_PERIOD
                            )
                            / CENTIMILLISECONDS_PER_SECOND
                        )
                    ).strftime("%Y-%m-%d %H:%M:%S.%f")
                    assert this_file_attrs[str(UTC_FIRST_REF_DATA_POINT_UUID)] == (
                        expected_time
                        + datetime.timedelta(
                            seconds=(start_recording_time_index + DATA_FRAME_PERIOD)
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
                        GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                            BACKEND_LOG_UUID
                        ]
                    )
                    assert (
                        this_file_attrs[str(COMPUTER_NAME_HASH_UUID)]
                        == GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                            COMPUTER_NAME_HASH_UUID
                        ]
                    )
                    # Tanner (1/12/21): The barcode used for testing (which is passed to start_recoring route) is different than the simulator's barcode (the one that is 'scanned' in this test), so this should result to False
                    assert bool(this_file_attrs[str(BARCODE_IS_FROM_SCANNER_UUID)]) is False

        # Tanner (12/30/20): test second recording (only make sure it contains waveform data)
        for row_idx in range(4):
            for col_idx in range(6):
                with h5py.File(
                    os.path.join(
                        expected_recordings_dir,
                        f"{expected_barcode2}__2020_06_15_141957",
                        f"{expected_barcode2}__2020_06_15_141957__{WELL_DEF_24.get_well_name_from_row_and_column(row_idx, col_idx)}.h5",
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
def test_full_datapath(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
):
    app_info = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()
    test_process_manager = app_info["object_access_inside_main"]["process_manager"]

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
    # Tanner (12/29/20): When system status equals LIVE_VIEW_ACTIVE_STATE then enough data has passed through the data path to make assertions
    assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

    # Tanner (12/30/20): stop managed_acquisition now that we have a known amount of data available
    response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True
    # Tanner (12/30/20): Make sure first set of data is available
    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 200
    actual = json.loads(response.text)
    waveform_data_points = actual["waveform_data"]["basic_data"]["waveform_data_points"]
    # Tanner (12/29/20): Make sure second set of data is available and clear the remaining data
    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 200
    # Tanner (12/29/20): One more call to get_available_data to assert that no more data is available
    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 204
    confirm_queue_is_eventually_empty(da_out)

    # Tanner (12/29/20): create expected data
    test_well_index = 0
    x_values = np.array(
        [
            (ROUND_ROBIN_PERIOD * (i + 1) // TIMESTEP_CONVERSION_FACTOR)
            for i in range(math.ceil(DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS / ROUND_ROBIN_PERIOD))
        ]
    )
    sawtooth_points = signal.sawtooth(x_values / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5)
    scaling_factor = (test_well_index + 1) / 24 * 6
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
    pl_template = PipelineTemplate(
        noise_filter_uuid=BUTTERWORTH_LOWPASS_30_UUID,
        tissue_sampling_period=ROUND_ROBIN_PERIOD,
    )
    pipeline = pl_template.create_pipeline()
    pipeline.load_raw_gmr_data(test_data, np.zeros(test_data.shape))
    expected_well_data = pipeline.get_compressed_displacement()

    # Tanner (12/29/20): Assert data is as expected for two wells
    actual_well_0_y_data = waveform_data_points["0"]["y_data_points"]
    np.testing.assert_almost_equal(
        actual_well_0_y_data[0],
        expected_well_data[1][0] * MILLIVOLTS_PER_VOLT,
        decimal=4,
    )
    np.testing.assert_almost_equal(
        actual_well_0_y_data[9],
        expected_well_data[1][9] * MILLIVOLTS_PER_VOLT,
        decimal=4,
    )

    # Tanner (12/29/20): Good to do this at the end of tests to make sure they don't cause problems with other integration tests
    remaining_queue_items = test_process_manager.hard_stop_and_join_processes()
    # Tanner (12/31/20): Make sure that there were no errors in Data Analyzer
    da_error_list = remaining_queue_items["data_analyzer_items"]["fatal_error_reporter"]
    assert len(da_error_list) == 0


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
def test_app_shutdown__in_worst_case_while_recording_is_running(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
    mocker,
):
    spied_logger = mocker.spy(main.logger, "info")
    spied_server_logger = mocker.spy(server.logger, "info")
    app_info = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()
    test_process_manager = app_info["object_access_inside_main"]["process_manager"]

    # Tanner (12/30/20): Auto boot-up is completed when system reaches calibration_needed state
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    okc_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    # Tanner (12/29/20): Not making assertions on files, but still need a TemporaryDirectory to hold them
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        # Tanner (12/29/20): use updated settings to set the recording directory to the TemporaryDirectory
        response = requests.get(
            f"{get_api_endpoint()}update_settings?customer_account_uuid=curi&recording_directory={expected_recordings_dir}"
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

        expected_barcode = GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            PLATE_BARCODE_UUID
        ]
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode}&is_hardware_test_recording=False"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 5) is True

        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files

        # Tanner (12/29/20): Shutdown now that data is being acquired and actively written to files, which means each subprocess is doing something
        response = requests.get(f"{get_api_endpoint()}shutdown")
        assert response.status_code == 200
        # TODO (Eli 12/9/20): have /shutdown wait to return until the other processes have been stopped, or have a separate route to shut down other processes (that also waits)

        # Tanner (12/30/20): Confirming the port is available to make sure that the Flask server has shutdown
        confirm_port_available(get_server_port_number(), timeout=10)
        # Tanner (12/30/20): Double check that the system acknowledges that Flask sever has shutdown
        spied_server_logger.assert_any_call("Flask server successfully shut down.")

        # Eli (12/4/20): currently, Flask immediately shuts down and communicates up to ProcessMonitor to start shutting everything else down. So for now need to sleep a bit before attempting to confirm everything else is shut down
        time.sleep(10)

        # Tanner (12/30/20): This is the very last log message before the app is completely shutdown
        spied_logger.assert_any_call("Program exiting")

        # Tanner (12/29/20): If these are alive, this means that zombie processes will be created when the compiled desktop app EXE is running, so this assertion helps make sure that that won't happen
        assert okc_process.is_alive() is False
        assert fw_process.is_alive() is False
        assert da_process.is_alive() is False


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
def test_full_datapath_and_recorded_files_in_beta_2_mode(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
):
    # TODO Tanner (4/23/21): This integration test does not actually test the full data path or recorded files yet. When that functionality is added for beta 2 mode, this test needs to be updated
    app_info = fully_running_app_from_main_entrypoint(["--beta-2-mode"])
    wait_for_subprocesses_to_start()
    test_process_manager = app_info["object_access_inside_main"]["process_manager"]

    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    # Tanner (12/30/20): Calibrate instrument in order to start managed_acquisition
    response = requests.get(f"{get_api_endpoint()}start_calibration")
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

    # Tanner (4/5/21): Once magnetometer configuration route is added, test can go to buffering state. Once data path is updated to handle beta 2 data, test can go to recording state

    # Tanner (12/29/20): Good to do this at the end of tests to make sure they don't cause problems with other integration tests
    test_process_manager.hard_stop_and_join_processes()
