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

from .fixtures import fixture_fully_running_app_from_main_entrypoint
from .fixtures import fixture_patched_firmware_folder
from .fixtures import fixture_patched_shared_values_dict
from .fixtures import fixture_patched_xem_scripts_folder
from .fixtures import fixture_test_client
from .fixtures import fixture_test_process_manager
from .fixtures import fixture_test_process_manager_without_created_processes
from .fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from .helpers import is_queue_eventually_empty

__fixtures__ = [
    fixture_fully_running_app_from_main_entrypoint,
    fixture_test_client,
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


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
def test_full_datapath(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    test_process_manager,
    test_client,
    fully_running_app_from_main_entrypoint,
):
    _ = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    da_error_queue = test_process_manager.get_data_analyzer_error_queue()
    da_out = test_process_manager.get_data_analyzer_data_out_queue()

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
    test_process_manager,
    test_client,
    fully_running_app_from_main_entrypoint,
    mocker,
):
    spied_logger = mocker.spy(main.logger, "info")

    _ = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    okc_process = test_process_manager.get_ok_comm_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = requests.get(
            f"{get_api_endpoint()}update_settings?customer_account_uuid=curi&recording_directory={expected_recordings_dir}"
        )
        assert response.status_code == 200

        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        response = requests.get(f"{get_api_endpoint()}system_status")
        assert response.status_code == 200
        assert response.json()["ui_status_code"] == str(
            SYSTEM_STATUS_UUIDS[CALIBRATING_STATE]
        )
        assert (
            system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME)
            is True
        )

        response = requests.get(f"{get_api_endpoint()}start_managed_acquisition")
        assert response.status_code == 200
        response = requests.get(f"{get_api_endpoint()}system_status")
        assert response.status_code == 200
        assert response.json()["ui_status_code"] == str(
            SYSTEM_STATUS_UUIDS[BUFFERING_STATE]
        )
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
        response = requests.get(f"{get_api_endpoint()}system_status")
        assert response.status_code == 200
        assert response.json()["ui_status_code"] == str(
            SYSTEM_STATUS_UUIDS[RECORDING_STATE]
        )

        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files

        response = requests.get(f"{get_api_endpoint()}shutdown")
        assert response.status_code == 200

    confirm_port_available(get_server_port_number(), timeout=10)

    spied_logger.assert_any_call("Successful exit")
    spied_logger.assert_any_call("Program exiting")

    assert okc_process.is_alive() is False
    assert fw_process.is_alive() is False
    assert da_process.is_alive() is False
