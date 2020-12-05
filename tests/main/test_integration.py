# -*- coding: utf-8 -*-
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
from mantarray_desktop_app import server
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_desktop_app import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_desktop_app import START_RECORDING_TIME_INDEX_UUID
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
from ..fixtures import fixture_patched_xem_scripts_folder
from ..fixtures import fixture_test_process_manager
from ..fixtures import GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
from ..fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from ..helpers import is_queue_eventually_empty

__fixtures__ = [
    fixture_fully_running_app_from_main_entrypoint,
    fixture_test_process_manager,
    fixture_patched_shared_values_dict,
    fixture_patched_xem_scripts_folder,
    fixture_patched_firmware_folder,
]
LIVE_VIEW_ACTIVE_WAIT_TIME = 120
CALIBRATED_WAIT_TIME = 10
STOP_MANAGED_ACQUISITION_WAIT_TIME = 40
INTEGRATION_TEST_TIMEOUT = 720


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_send_xem_scripts_command__gets_processed_in_fully_running_app(
    fully_running_app_from_main_entrypoint, patched_xem_scripts_folder,
):
    app_info = fully_running_app_from_main_entrypoint(["--skip-mantarray-boot-up"])
    wait_for_subprocesses_to_start()

    test_process_manager = app_info["object_access_inside_main"]["process_manager"]
    test_process_monitor = app_info["object_access_inside_main"]["process_monitor"]
    shared_values_dict = app_info["object_access_inside_main"][
        "values_to_share_to_server"
    ]
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
        test_process_manager = app_info["object_access_inside_main"]["process_manager"]
        test_process_monitor = app_info["object_access_inside_main"]["process_monitor"]
        response = requests.get(f"{get_api_endpoint()}system_status")
        assert response.status_code == 200
        assert response.json()["ui_status_code"] == str(
            SYSTEM_STATUS_UUIDS[SERVER_READY_STATE]
        )

        response = requests.get(f"{get_api_endpoint()}boot_up")
        assert response.status_code == 200

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

        fw_process = test_process_manager.get_file_writer_process()
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

    response = requests.get(f"{get_api_endpoint()}start_calibration")
    assert response.status_code == 200
    assert (
        system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True
    )

    # First run
    response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
    assert response.status_code == 200
    assert (
        system_state_eventually_equals(
            LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME
        )
        is True
    )
    response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
    assert response.status_code == 200
    assert (
        system_state_eventually_equals(
            CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME
        )
        is True
    )

    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 200
    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 200

    time.sleep(3)  # allow remaining data to pass through subprocesses

    # Second run
    response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
    assert response.status_code == 200
    assert (
        system_state_eventually_equals(
            LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME
        )
        is True
    )
    response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
    assert response.status_code == 200
    assert (
        system_state_eventually_equals(
            CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME
        )
        is True
    )

    test_process_manager.hard_stop_and_join_processes()


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
@freeze_time(
    datetime.datetime(
        year=2020, month=6, day=15, hour=14, minute=19, second=55, microsecond=313309
    )
)
def test_system_states_and_recorded_metadata_with_update_to_file_writer_directory(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
    mocker,
):
    expected_time = datetime.datetime(
        year=2020, month=6, day=15, hour=14, minute=19, second=55, microsecond=313309
    )
    mocker.patch.object(
        server,
        "_get_timestamp_of_acquisition_sample_index_zero",
        return_value=expected_time,
    )
    expected_timestamp = "2020_06_15_141955"

    app_info = fully_running_app_from_main_entrypoint(["--skip-mantarray-boot-up"])
    wait_for_subprocesses_to_start()

    test_process_manager = app_info["object_access_inside_main"]["process_manager"]

    assert system_state_eventually_equals(SERVER_READY_STATE, 5) is True
    # response = requests.get(f"{get_api_endpoint()}system_status")
    # assert response.status_code == 200
    # assert response.json()["ui_status_code"] == str(
    #     SYSTEM_STATUS_UUIDS[SERVER_READY_STATE]
    # )

    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = requests.get(
            f"{get_api_endpoint()}update_settings?customer_account_uuid=curi&recording_directory={expected_recordings_dir}"
        )
        assert response.status_code == 200
        response = requests.get(f"{get_api_endpoint()}boot_up")
        assert response.status_code == 200
        assert system_state_eventually_equals(INSTRUMENT_INITIALIZING_STATE, 5) is True
        # response = requests.get(f"{get_api_endpoint()}system_status")
        # assert response.status_code == 200
        # assert response.json()["ui_status_code"] == str(
        #     SYSTEM_STATUS_UUIDS[INSTRUMENT_INITIALIZING_STATE]
        # )
        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 3) is True
        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATING_STATE, 3) is True
        # response = requests.get(f"{get_api_endpoint()}system_status")
        # assert response.status_code == 200
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
        start_recording_time_index = 960
        response = requests.get(
            f"{get_api_endpoint()}start_recording?barcode={expected_barcode}&time_index={start_recording_time_index}&is_hardware_test_recording=False"
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

        fw_process = test_process_manager.get_file_writer_process()
        fw_process.close_all_files()

        actual_set_of_files = set(
            os.listdir(
                os.path.join(
                    expected_recordings_dir, f"{expected_barcode}__{expected_timestamp}"
                )
            )
        )
        assert len(actual_set_of_files) == 24

        # Tanner (6/15/20): Processes must be joined to avoid h5 errors with reading files, so clearing queues manually here in order to join
        test_process_manager.hard_stop_and_join_processes()

        for row_idx in range(4):
            for col_idx in range(6):
                well_idx = col_idx * 4 + row_idx
                with h5py.File(
                    os.path.join(
                        expected_recordings_dir,
                        f"{expected_barcode}__{expected_timestamp}",
                        f"{expected_barcode}__{expected_timestamp}__{chr(row_idx+65)}{col_idx+1}.h5",
                    ),
                    "r",
                ) as this_file:
                    this_file_attrs = this_file.attrs
                    assert (
                        bool(this_file_attrs[str(HARDWARE_TEST_RECORDING_UUID)])
                        is False
                    )
                    assert (
                        this_file_attrs[str(SOFTWARE_BUILD_NUMBER_UUID)]
                        == COMPILED_EXE_BUILD_TIMESTAMP
                    )
                    assert (
                        this_file_attrs["File Format Version"]
                        == CURRENT_HDF5_FILE_FORMAT_VERSION
                    )
                    assert this_file_attrs[
                        str(UTC_BEGINNING_DATA_ACQUISTION_UUID)
                    ] == expected_time.strftime("%Y-%m-%d %H:%M:%S.%f")
                    assert (
                        this_file_attrs[str(START_RECORDING_TIME_INDEX_UUID)]
                        == start_recording_time_index
                    )
                    assert this_file.attrs[
                        str(UTC_BEGINNING_RECORDING_UUID)
                    ] == expected_time.strftime("%Y-%m-%d %H:%M:%S.%f")
                    assert this_file_attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == (
                        expected_time
                        + datetime.timedelta(
                            seconds=(
                                start_recording_time_index
                                + WELL_24_INDEX_TO_ADC_AND_CH_INDEX[well_idx][1]
                                * DATA_FRAME_PERIOD
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
                    assert this_file_attrs[str(USER_ACCOUNT_ID_UUID)] == str(
                        CURI_BIO_USER_ACCOUNT_ID
                    )
                    assert this_file_attrs[str(CUSTOMER_ACCOUNT_ID_UUID)] == str(
                        CURI_BIO_ACCOUNT_UUID
                    )
                    assert this_file_attrs[str(ADC_GAIN_SETTING_UUID)] == 16
                    assert (
                        this_file_attrs[str(ADC_TISSUE_OFFSET_UUID)]
                        == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
                    )
                    assert (
                        this_file_attrs[str(ADC_REF_OFFSET_UUID)]
                        == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
                    )
                    assert (
                        this_file_attrs[str(REFERENCE_VOLTAGE_UUID)]
                        == REFERENCE_VOLTAGE
                    )
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
                    assert (
                        this_file_attrs[str(SOFTWARE_RELEASE_VERSION_UUID)]
                        == CURRENT_SOFTWARE_VERSION
                    )

                    assert (
                        this_file_attrs[str(WELL_NAME_UUID)]
                        == f"{chr(row_idx+65)}{col_idx+1}"
                    )
                    assert this_file_attrs["Metadata UUID Descriptions"] == json.dumps(
                        str(METADATA_UUID_DESCRIPTIONS)
                    )
                    assert this_file_attrs[str(TOTAL_WELL_COUNT_UUID)] == 24
                    assert this_file_attrs[str(WELL_ROW_UUID)] == row_idx
                    assert this_file_attrs[str(WELL_COLUMN_UUID)] == col_idx
                    assert (
                        this_file_attrs[str(WELL_INDEX_UUID)] == row_idx + col_idx * 4
                    )
                    assert (
                        this_file_attrs[str(TISSUE_SAMPLING_PERIOD_UUID)]
                        == CONSTRUCT_SENSOR_SAMPLING_PERIOD
                        * MICROSECONDS_PER_CENTIMILLISECOND
                    )
                    assert (
                        this_file_attrs[str(REF_SAMPLING_PERIOD_UUID)]
                        == REFERENCE_SENSOR_SAMPLING_PERIOD
                        * MICROSECONDS_PER_CENTIMILLISECOND
                    )


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

    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    da_error_queue = (
        test_process_manager.queue_container().get_data_analyzer_error_queue()
    )
    da_out = test_process_manager.queue_container().get_data_analyzer_data_out_queue()

    response = requests.get(f"{get_api_endpoint()}start_calibration")
    assert response.status_code == 200
    assert (
        system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True
    )

    acquisition_request = f"{get_api_endpoint()}start_managed_acquisition"
    response = requests.get(acquisition_request)
    assert response.status_code == 200
    assert (
        system_state_eventually_equals(
            LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME
        )
        is True
    )

    response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
    assert response.status_code == 200
    assert (
        system_state_eventually_equals(
            CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME
        )
        is True
    )
    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 200
    actual = json.loads(response.text)
    waveform_data_points = actual["waveform_data"]["basic_data"]["waveform_data_points"]
    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 200
    response = requests.get(f"{get_api_endpoint()}get_available_data")
    assert response.status_code == 204
    assert is_queue_eventually_empty(da_out) is True

    test_well_index = 0
    x_values = np.array(
        [
            (ROUND_ROBIN_PERIOD * (i + 1) // TIMESTEP_CONVERSION_FACTOR)
            for i in range(
                math.ceil(
                    DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS / ROUND_ROBIN_PERIOD
                )
            )
        ]
    )
    sawtooth_points = signal.sawtooth(
        x_values / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5
    )
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
    pt = PipelineTemplate(
        noise_filter_uuid=BUTTERWORTH_LOWPASS_30_UUID,
        tissue_sampling_period=ROUND_ROBIN_PERIOD,
    )

    pipeline = pt.create_pipeline()
    pipeline.load_raw_gmr_data(test_data, np.zeros(test_data.shape))
    expected_well_data = pipeline.get_compressed_displacement()
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

    test_process_manager.hard_stop_and_join_processes()
    assert is_queue_eventually_empty(da_error_queue) is True


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

    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    okc_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = requests.get(
            f"{get_api_endpoint()}update_settings?customer_account_uuid=curi&recording_directory={expected_recordings_dir}"
        )
        assert response.status_code == 200

        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATING_STATE, 5) is True

        assert (
            system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME)
            is True
        )

        response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
        assert response.status_code == 200

        assert system_state_eventually_equals(BUFFERING_STATE, 5) is True

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

        assert system_state_eventually_equals(RECORDING_STATE, 5) is True
        # response = requests.get(f"{get_api_endpoint()}system_status")
        # assert response.status_code == 200
        # assert response.json()["ui_status_code"] == str(
        #     SYSTEM_STATUS_UUIDS[RECORDING_STATE]
        # )

        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files

        response = requests.get(f"{get_api_endpoint()}shutdown")
        assert response.status_code == 200

    confirm_port_available(get_server_port_number(), timeout=10)

    spied_server_logger.assert_any_call("Flask server successfully shut down.")

    # Eli (12/4/20): currently, Flask immediately shuts down and communicates up to ProcessMonitor to start shutting everything else down. So for now need to sleep a bit before attempting to confirm everything else is shut down
    time.sleep(10)

    spied_logger.assert_any_call("Program exiting")

    assert okc_process.is_alive() is False
    assert fw_process.is_alive() is False
    assert da_process.is_alive() is False
