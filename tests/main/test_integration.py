# -*- coding: utf-8 -*-
import base64
import datetime
import json
import os
import tempfile
import time

from freezegun import freeze_time
import h5py
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app import FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import get_stimulation_dataset_from_file
from mantarray_desktop_app import get_time_index_dataset_from_file
from mantarray_desktop_app import get_time_offset_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import NUM_INITIAL_PACKETS_TO_DROP
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import wait_for_subprocesses_to_start
from mantarray_desktop_app import WELL_24_INDEX_TO_ADC_AND_CH_INDEX
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
from mantarray_desktop_app.main_process import process_monitor
from mantarray_desktop_app.main_process import server
from mantarray_desktop_app.utils import generic
from mantarray_desktop_app.utils.web_api import AuthTokens
from pulse3D.constants import ADC_GAIN_SETTING_UUID
from pulse3D.constants import ADC_REF_OFFSET_UUID
from pulse3D.constants import ADC_TISSUE_OFFSET_UUID
from pulse3D.constants import BACKEND_LOG_UUID
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import COMPUTER_NAME_HASH_UUID
from pulse3D.constants import CUSTOMER_ACCOUNT_ID_UUID
from pulse3D.constants import FILE_FORMAT_VERSION_METADATA_KEY
from pulse3D.constants import HARDWARE_TEST_RECORDING_UUID
from pulse3D.constants import INITIAL_MAGNET_FINDING_PARAMS_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
from pulse3D.constants import METADATA_UUID_DESCRIPTIONS
from pulse3D.constants import PLATE_BARCODE_IS_FROM_SCANNER_UUID
from pulse3D.constants import PLATE_BARCODE_UUID
from pulse3D.constants import PLATEMAP_LABEL_UUID
from pulse3D.constants import PLATEMAP_NAME_UUID
from pulse3D.constants import REF_SAMPLING_PERIOD_UUID
from pulse3D.constants import REFERENCE_VOLTAGE_UUID
from pulse3D.constants import SLEEP_FIRMWARE_VERSION_UUID
from pulse3D.constants import SOFTWARE_BUILD_NUMBER_UUID
from pulse3D.constants import SOFTWARE_RELEASE_VERSION_UUID
from pulse3D.constants import START_RECORDING_TIME_INDEX_UUID
from pulse3D.constants import STIM_BARCODE_IS_FROM_SCANNER_UUID
from pulse3D.constants import STIM_BARCODE_UUID
from pulse3D.constants import STIMULATION_PROTOCOL_UUID
from pulse3D.constants import TISSUE_SAMPLING_PERIOD_UUID
from pulse3D.constants import TOTAL_WELL_COUNT_UUID
from pulse3D.constants import USER_ACCOUNT_ID_UUID
from pulse3D.constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from pulse3D.constants import UTC_BEGINNING_RECORDING_UUID
from pulse3D.constants import UTC_FIRST_REF_DATA_POINT_UUID
from pulse3D.constants import UTC_FIRST_TISSUE_DATA_POINT_UUID
from pulse3D.constants import WELL_COLUMN_UUID
from pulse3D.constants import WELL_INDEX_UUID
from pulse3D.constants import WELL_NAME_UUID
from pulse3D.constants import WELL_ROW_UUID
from pulse3D.constants import XEM_SERIAL_NUMBER_UUID
import pytest
import requests
from stdlib_utils import confirm_port_available

from ..fixtures import fixture_fully_running_app_from_main_entrypoint
from ..fixtures import fixture_patched_firmware_folder
from ..fixtures import fixture_patched_xem_scripts_folder
from ..fixtures_file_writer import GENERIC_BETA_1_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_PLATEMAP_INFO
from ..fixtures_mc_simulator import get_random_stim_delay
from ..fixtures_mc_simulator import get_random_stim_pulse
from ..fixtures_server import convert_formatted_platemap_to_query_param
from ..fixtures_server import fixture_test_socketio_client
from ..helpers import confirm_queue_is_eventually_empty

__fixtures__ = [
    fixture_fully_running_app_from_main_entrypoint,
    fixture_patched_xem_scripts_folder,
    fixture_patched_firmware_folder,
    fixture_test_socketio_client,
]

INTEGRATION_TEST_TIMEOUT = 300
CALIBRATION_NEEDED_WAIT_TIME = 20
CALIBRATED_WAIT_TIME = 40
LIVE_VIEW_ACTIVE_WAIT_TIME = 150
STOP_MANAGED_ACQUISITION_WAIT_TIME = 40
FIRST_METRIC_WAIT_TIME = 20
PROTOCOL_COMPLETION_WAIT_TIME = 30


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


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
@freeze_time(datetime.datetime(year=2020, month=7, day=16, hour=14, minute=19, second=55, microsecond=313309))
def test_full_datapath_and_recorded_files_in_beta_1_mode(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    fully_running_app_from_main_entrypoint,
    test_socketio_client,
    mocker,
):
    # mock this so test doesn't actually try to hit cloud API
    mocked_get_tokens = mocker.patch.object(server, "validate_user_credentials", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})

    expected_time = datetime.datetime.now()
    # Tanner (12/29/20): mock these in order to make assertions on timestamps in the metadata
    for mod in (server, generic):
        mocker.patch.object(
            mod, "_get_timestamp_of_acquisition_sample_index_zero", return_value=expected_time
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        expected_recordings_dir = os.path.join(tmp_dir, "recordings")
        expected_analysis_output_dir = os.path.join(tmp_dir, "time_force_data")
        test_dict = {
            "recording_directory": expected_recordings_dir,
            "mag_analysis_output_dir": expected_analysis_output_dir,
            "log_file_id": str(
                GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                    BACKEND_LOG_UUID
                ]
            ),
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
        command_line_args = [f"--initial-base64-settings={b64_encoded}"]

        app_info = fully_running_app_from_main_entrypoint(command_line_args)
        assert system_state_eventually_equals(SERVER_INITIALIZING_STATE, 10) is True
        sio, msg_list_container = test_socketio_client()
        wait_for_subprocesses_to_start()

        test_process_manager = app_info["object_access_inside_main"]["process_manager"]
        svd = app_info["object_access_inside_main"]["values_to_share_to_server"]

        # Tanner (12/30/20): Auto boot-up is completed when system reaches calibration_needed state
        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, CALIBRATION_NEEDED_WAIT_TIME) is True

        da_out = test_process_manager.queue_container.get_data_analyzer_data_out_queue()

        # Tanner (12/30/20): Start calibration in order to run managed_acquisition
        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

        user_dict = {"customer_id": "test_id", "user_password": "test_password", "user_name": "test_user"}
        response = requests.get(f"{get_api_endpoint()}login", params=user_dict)
        assert response.status_code == 200

        # Tanner (9/15/22): barcodes can take a while to be scanned in beta 1 mode
        start = time.perf_counter()
        while time.perf_counter() - start < 15:
            if "barcodes" in svd:
                break
            time.sleep(0.5)

        expected_plate_barcode_1 = GENERIC_BETA_1_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][PLATE_BARCODE_UUID]

        # Tanner (12/30/20): start managed_acquisition in order to get data moving through data path
        response = requests.get(
            f"{get_api_endpoint()}start_managed_acquisition?plate_barcode={expected_plate_barcode_1}"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

        expected_start_index_cms_1 = 960
        start_recording_params_1 = {
            "plate_barcode": expected_plate_barcode_1,
            "time_index": expected_start_index_cms_1 * MICROSECONDS_PER_CENTIMILLISECOND,
            "platemap": convert_formatted_platemap_to_query_param(GENERIC_PLATEMAP_INFO),
            "is_hardware_test_recording": False,
        }
        response = requests.get(f"{get_api_endpoint()}start_recording", params=start_recording_params_1)
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
        expected_stop_index_cms_1 = expected_start_index_cms_1 + int(2 * CENTIMILLISECONDS_PER_SECOND)
        response = requests.get(f"{get_api_endpoint()}stop_recording?time_index={expected_stop_index_cms_1}")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True

        # Tanner (12/30/20): Stop managed_acquisition now that we have a known min amount of data available
        response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True
        # Tanner (7/14/21): Beta 1 data packets are sent once per second, so there should be at least one data packet for every second needed to run analysis, but sometimes the final data packet doesn't get sent in time
        assert len(msg_list_container["waveform_data"]) >= MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 1
        confirm_queue_is_eventually_empty(da_out, timeout_seconds=5)

        # Tanner (6/1/21): Use new barcode for second set of recordings, change experiment code from '000' to '001'
        expected_plate_barcode_2 = expected_plate_barcode_1.replace("000", "001")
        # Tanner (6/1/21): Make sure managed_acquisition can be restarted
        response = requests.get(
            f"{get_api_endpoint()}start_managed_acquisition?plate_barcode={expected_plate_barcode_2}"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(BUFFERING_STATE, 5) is True
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

        # Tanner (5/25/21): Start at a different timepoint to create a different timestamp in the names of the second set of files
        expected_start_index_cms_2 = expected_start_index_cms_1 + int(CENTIMILLISECONDS_PER_SECOND)
        # Tanner (6/1/21): Start recording with second barcode to create second set of files
        start_recording_params_2 = {
            "plate_barcode": expected_plate_barcode_2,
            "time_index": expected_start_index_cms_2 * MICROSECONDS_PER_CENTIMILLISECOND,
            "is_hardware_test_recording": False,
        }
        response = requests.get(f"{get_api_endpoint()}start_recording", params=start_recording_params_2)
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 3) is True

        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files

        expected_stop_index_cms_2 = expected_start_index_cms_2 + int(1.5 * CENTIMILLISECONDS_PER_SECOND)
        response = requests.get(f"{get_api_endpoint()}stop_recording?time_index={expected_stop_index_cms_2}")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True

        # Tanner (6/1/21): Stop managed_acquisition
        response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True
        confirm_queue_is_eventually_empty(da_out, timeout_seconds=5)

        # Tanner (6/21/21): disconnect here to avoid problems with attempting to disconnect after the server stops
        sio.disconnect()

        # Tanner (6/15/20): Processes must be joined to avoid h5 errors with reading files, so hard-stopping before joining
        remaining_queue_items = test_process_manager.hard_stop_and_join_processes()
        # Tanner (12/31/20): Make sure that there were no errors in Data Analyzer
        da_error_list = remaining_queue_items["data_analyzer_items"]["fatal_error_reporter"]
        assert len(da_error_list) == 0

        expected_timestamp_1 = "2020_07_16_141955"
        actual_set_of_files_1 = set(
            os.listdir(
                os.path.join(expected_recordings_dir, f"{expected_plate_barcode_1}__{expected_timestamp_1}")
            )
        )
        assert len(actual_set_of_files_1) == 24

        # test first recording for all data and metadata
        for well_idx in range(24):
            well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
            with h5py.File(
                os.path.join(
                    expected_recordings_dir,
                    f"{expected_plate_barcode_1}__{expected_timestamp_1}",
                    f"{expected_plate_barcode_1}__{expected_timestamp_1}__{well_name}.h5",
                ),
                "r",
            ) as this_file:
                assert bool(this_file.attrs[str(HARDWARE_TEST_RECORDING_UUID)]) is False
                assert this_file.attrs[str(SOFTWARE_BUILD_NUMBER_UUID)] == COMPILED_EXE_BUILD_TIMESTAMP
                assert (
                    this_file.attrs[FILE_FORMAT_VERSION_METADATA_KEY]
                    == CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
                )
                assert this_file.attrs[str(UTC_BEGINNING_DATA_ACQUISTION_UUID)] == expected_time.strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )
                assert this_file.attrs[str(START_RECORDING_TIME_INDEX_UUID)] == expected_start_index_cms_1
                assert this_file.attrs[str(UTC_BEGINNING_RECORDING_UUID)] == expected_time.strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )
                assert this_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == (
                    expected_time
                    + datetime.timedelta(
                        seconds=(
                            expected_start_index_cms_1
                            + WELL_24_INDEX_TO_ADC_AND_CH_INDEX[well_idx][1] * DATA_FRAME_PERIOD
                        )
                        / CENTIMILLISECONDS_PER_SECOND
                    )
                ).strftime("%Y-%m-%d %H:%M:%S.%f")
                assert this_file.attrs[str(UTC_FIRST_REF_DATA_POINT_UUID)] == (
                    expected_time
                    + datetime.timedelta(
                        seconds=(expected_start_index_cms_1 + DATA_FRAME_PERIOD)
                        / CENTIMILLISECONDS_PER_SECOND
                    )
                ).strftime("%Y-%m-%d %H:%M:%S.%f")
                assert this_file.attrs[str(USER_ACCOUNT_ID_UUID)] == "test_user"
                assert this_file.attrs[str(CUSTOMER_ACCOUNT_ID_UUID)] == "test_id"
                assert this_file.attrs[str(ADC_GAIN_SETTING_UUID)] == 16
                assert this_file.attrs[str(ADC_TISSUE_OFFSET_UUID)] == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
                assert this_file.attrs[str(ADC_REF_OFFSET_UUID)] == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
                assert this_file.attrs[str(REFERENCE_VOLTAGE_UUID)] == REFERENCE_VOLTAGE
                assert this_file.attrs[str(SLEEP_FIRMWARE_VERSION_UUID)] == "0.0.0"
                assert (
                    this_file.attrs[str(MAIN_FIRMWARE_VERSION_UUID)]
                    == RunningFIFOSimulator.default_firmware_version
                )
                assert (
                    this_file.attrs[str(MANTARRAY_SERIAL_NUMBER_UUID)]
                    == RunningFIFOSimulator.default_mantarray_serial_number
                )
                assert (
                    this_file.attrs[str(MANTARRAY_NICKNAME_UUID)]
                    == RunningFIFOSimulator.default_mantarray_nickname
                )
                assert (
                    this_file.attrs[str(XEM_SERIAL_NUMBER_UUID)]
                    == RunningFIFOSimulator.default_xem_serial_number
                )
                assert this_file.attrs[str(SOFTWARE_RELEASE_VERSION_UUID)] == CURRENT_SOFTWARE_VERSION

                assert this_file.attrs[str(WELL_NAME_UUID)] == well_name
                assert this_file.attrs["Metadata UUID Descriptions"] == json.dumps(
                    str(METADATA_UUID_DESCRIPTIONS)
                )
                assert this_file.attrs[str(TOTAL_WELL_COUNT_UUID)] == 24
                row_idx, col_idx = GENERIC_24_WELL_DEFINITION.get_row_and_column_from_well_index(well_idx)
                assert this_file.attrs[str(WELL_ROW_UUID)] == row_idx
                assert this_file.attrs[str(WELL_COLUMN_UUID)] == col_idx
                assert this_file.attrs[str(WELL_INDEX_UUID)] == well_idx
                assert (
                    this_file.attrs[str(TISSUE_SAMPLING_PERIOD_UUID)]
                    == CONSTRUCT_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
                )
                assert (
                    this_file.attrs[str(REF_SAMPLING_PERIOD_UUID)]
                    == REFERENCE_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
                )
                assert this_file.attrs[str(BACKEND_LOG_UUID)] == str(
                    GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        BACKEND_LOG_UUID
                    ]
                )
                assert (
                    this_file.attrs[str(COMPUTER_NAME_HASH_UUID)]
                    == GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        COMPUTER_NAME_HASH_UUID
                    ]
                )
                assert this_file.attrs[str(PLATE_BARCODE_UUID)] == expected_plate_barcode_1
                assert (
                    bool(this_file.attrs[str(PLATE_BARCODE_IS_FROM_SCANNER_UUID)])
                    is GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        PLATE_BARCODE_IS_FROM_SCANNER_UUID
                    ]
                )
                assert (
                    this_file.attrs[str(PLATEMAP_NAME_UUID)]
                    == GENERIC_BETA_1_START_RECORDING_COMMAND["platemap"]["name"]
                )
                assert (
                    this_file.attrs[str(PLATEMAP_LABEL_UUID)]
                    == GENERIC_BETA_1_START_RECORDING_COMMAND["platemap"]["labels"][well_idx]
                )

        expected_timestamp_2 = "2020_07_16_141956"
        actual_set_of_files_2 = set(
            os.listdir(
                os.path.join(expected_recordings_dir, f"{expected_plate_barcode_2}__{expected_timestamp_2}")
            )
        )
        assert len(actual_set_of_files_2) == 24

        # Tanner (12/30/20): test second recording (only make sure it contains waveform data)
        for well_idx in range(24):
            well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
            with h5py.File(
                os.path.join(
                    expected_recordings_dir,
                    f"{expected_plate_barcode_2}__{expected_timestamp_2}",
                    f"{expected_plate_barcode_2}__{expected_timestamp_2}__{well_name}.h5",
                ),
                "r",
            ) as this_file:
                assert str(START_RECORDING_TIME_INDEX_UUID) in this_file.attrs
                assert this_file.attrs[str(START_RECORDING_TIME_INDEX_UUID)] == expected_start_index_cms_2
                assert str(UTC_FIRST_TISSUE_DATA_POINT_UUID) in this_file.attrs
                assert str(UTC_FIRST_REF_DATA_POINT_UUID) in this_file.attrs
                actual_tissue_data = get_tissue_dataset_from_file(this_file)
                assert actual_tissue_data.shape[0] > 0


@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
@freeze_time(datetime.datetime(year=2021, month=5, day=24, hour=21, minute=23, second=4, microsecond=141738))
def test_full_datapath_and_recorded_files_in_beta_2_mode(
    fully_running_app_from_main_entrypoint, test_socketio_client, mocker
):
    # mock this value so that only 2 seconds of recorded data are needed to complete calibration
    mocker.patch.object(process_monitor, "CALIBRATION_RECORDING_DUR_SECONDS", 2)

    expected_time = datetime.datetime.now()
    # Tanner (12/29/20): mock these in order to make assertions on timestamps in the metadata
    for mod in (server, generic):
        mocker.patch.object(
            mod, "_get_timestamp_of_acquisition_sample_index_zero", return_value=expected_time
        )

    # mock this so test doesn't actually try to hit cloud API
    mocked_get_tokens = mocker.patch.object(server, "validate_user_credentials", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})

    test_protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
            "A" if well_idx % 2 == 0 else "B"
        )
        for well_idx in range(24)
    }
    # both protocols will be 3 seconds long
    test_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "V",
                "run_until_stopped": True,
                "subprotocols": [
                    get_random_stim_pulse(total_subprotocol_dur_us=MICRO_TO_BASE_CONVERSION),
                    get_random_stim_delay(MICRO_TO_BASE_CONVERSION // 2),
                    get_random_stim_pulse(total_subprotocol_dur_us=MICRO_TO_BASE_CONVERSION),
                    get_random_stim_delay(MICRO_TO_BASE_CONVERSION // 2),
                ],
            },
            {
                "protocol_id": "B",
                "stimulation_type": "C",
                "run_until_stopped": False,
                "subprotocols": [
                    get_random_stim_pulse(total_subprotocol_dur_us=MICRO_TO_BASE_CONVERSION) for _ in range(3)
                ],
            },
        ],
        "protocol_assignments": test_protocol_assignments,
    }
    expected_num_protocol_b_packets = len(test_stim_info["protocols"][1]["subprotocols"]) + 1

    with tempfile.TemporaryDirectory() as tmp_dir:
        expected_recordings_dir = os.path.join(tmp_dir, "recordings")
        expected_analysis_output_dir = os.path.join(tmp_dir, "time_force_data")
        test_dict = {
            "recording_directory": expected_recordings_dir,
            "mag_analysis_output_dir": expected_analysis_output_dir,
            "log_file_id": str(
                GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                    BACKEND_LOG_UUID
                ]
            ),
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
        command_line_args = ["--beta-2-mode", f"--initial-base64-settings={b64_encoded}"]

        app_info = fully_running_app_from_main_entrypoint(command_line_args)
        assert system_state_eventually_equals(SERVER_INITIALIZING_STATE, 10) is True
        sio, msg_list_container = test_socketio_client()
        wait_for_subprocesses_to_start()

        test_process_manager = app_info["object_access_inside_main"]["process_manager"]
        shared_values_dict = app_info["object_access_inside_main"]["values_to_share_to_server"]

        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, CALIBRATION_NEEDED_WAIT_TIME) is True

        da_out = test_process_manager.queue_container.get_data_analyzer_data_out_queue()

        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

        user_dict = {"customer_id": "test_id", "user_password": "test_password", "user_name": "test_user"}
        response = requests.get(f"{get_api_endpoint()}login", params=user_dict)
        assert response.status_code == 200

        expected_plate_barcode_1 = GENERIC_BETA_2_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][PLATE_BARCODE_UUID]

        # run stimulator checks
        response = requests.post(
            f"{get_api_endpoint()}start_stim_checks",
            json={
                "well_indices": list(range(24)),
                "plate_barcode": expected_plate_barcode_1,
                "stim_barcode": MantarrayMcSimulator.default_stim_barcode,
            },
        )
        assert response.status_code == 200
        # wait for checks to complete
        while shared_values_dict["stimulator_circuit_statuses"] != {
            well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(24)
        }:
            time.sleep(0.5)

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

        # Tanner (6/1/21): Start managed_acquisition in order to start recording
        response = requests.get(
            f"{get_api_endpoint()}start_managed_acquisition?plate_barcode={expected_plate_barcode_1}"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(BUFFERING_STATE, 5) is True
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True
        expected_start_index_1 = NUM_INITIAL_PACKETS_TO_DROP * DEFAULT_SAMPLING_PERIOD
        start_recording_params_1 = {
            "plate_barcode": expected_plate_barcode_1,
            "stim_barcode": MantarrayMcSimulator.default_stim_barcode,
            "time_index": expected_start_index_1,
            "platemap": convert_formatted_platemap_to_query_param(GENERIC_PLATEMAP_INFO),
            "is_hardware_test_recording": False,
        }
        response = requests.get(f"{get_api_endpoint()}start_recording", params=start_recording_params_1)
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
        # Tanner (10/28/21): Stim data should also have been sent by the time the first metric is sent, so test that too
        assert len(msg_list_container["stimulation_data"]) > 0

        # Tanner (6/1/21): End recording at a known timepoint
        expected_stop_index_1 = expected_start_index_1 + (2 * MICRO_TO_BASE_CONVERSION)
        response = requests.get(f"{get_api_endpoint()}stop_recording?time_index={expected_stop_index_1}")
        assert response.status_code == 200
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, 3) is True

        # Tanner (7/14/21): Stop managed_acquisition now that we have a known min amount of data available
        response = requests.get(f"{get_api_endpoint()}stop_managed_acquisition")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATED_STATE, STOP_MANAGED_ACQUISITION_WAIT_TIME) is True
        # Tanner (7/14/21): Beta 2 data packets are currently sent once per second, so there should be at least one data packet for every second needed to run analysis, but sometimes the final data packet doesn't get sent in time
        assert len(msg_list_container["waveform_data"]) >= MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 1
        confirm_queue_is_eventually_empty(da_out, timeout_seconds=5)

        # Tanner (10/22/21): Stop stimulation
        response = requests.post(f"{get_api_endpoint()}set_stim_status?running=false")
        assert response.status_code == 200
        assert stimulation_running_status_eventually_equals(False, 4) is True

        # Tanner (6/1/21): Use new barcode for second set of recordings, change experiment code from '000' to '001'
        expected_plate_barcode_2 = expected_plate_barcode_1.replace("000", "001")
        # Tanner (6/1/21): Make sure managed_acquisition can be restarted
        response = requests.get(
            f"{get_api_endpoint()}start_managed_acquisition?plate_barcode={expected_plate_barcode_2}"
        )
        assert response.status_code == 200
        assert system_state_eventually_equals(BUFFERING_STATE, 5) is True
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

        # Tanner (9/15/22): let data stream for a few seconds before starting to ensure that first stim packet idx falls within recording range
        time.sleep(3)

        # Tanner (9/15/22): Clear stim container before restarting stimulation
        msg_list_container["stimulation_data"].clear()

        # Tanner (10/22/21): Restart stimulation
        response = requests.post(f"{get_api_endpoint()}set_stim_status?running=true")
        assert response.status_code == 200
        assert stimulation_running_status_eventually_equals(True, 4) is True

        # Tanner (5/25/21): Start at a different timepoint to create a different timestamp in the names of the second set of files
        expected_start_index_2 = 2 * MICRO_TO_BASE_CONVERSION
        # Tanner (6/1/21): Start recording with second barcode to create second set of files
        start_recording_params_2 = {
            "plate_barcode": expected_plate_barcode_2,
            "stim_barcode": MantarrayMcSimulator.default_stim_barcode,
            "time_index": expected_start_index_2,
            "is_hardware_test_recording": False,
        }
        response = requests.get(f"{get_api_endpoint()}start_recording", params=start_recording_params_2)
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 3) is True

        # Tanner (9/16/22): Protocol B in this test is assigned to odd numbered wells and must complete in order for this test to pass, so need to wait for all the stim messages from those wells to come through
        final_protocol_b_timepoint = None
        start = time.perf_counter()
        while time.perf_counter() - start < PROTOCOL_COMPLETION_WAIT_TIME:
            protocol_b_messages = [
                msg
                for msg_json in msg_list_container["stimulation_data"]
                if "1" in (msg := json.loads(msg_json))
            ]
            # using >= in case something very weird happens and more than the expected number of packets are sent
            if len(protocol_b_messages) >= expected_num_protocol_b_packets:
                final_protocol_b_timepoint = protocol_b_messages[-1]["1"][0][0]
                break
            time.sleep(0.5)
        assert (
            final_protocol_b_timepoint is not None
        ), "timeout while waiting for all protocol B stim packets to be sent through websocket"

        expected_stop_index_2 = final_protocol_b_timepoint
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
        confirm_queue_is_eventually_empty(da_out, timeout_seconds=5)

        # Tanner (6/19/21): disconnect here to avoid problems with attempting to disconnect after the server stops
        sio.disconnect()

        # Tanner (6/15/20): Processes must be joined to avoid h5 errors with reading files, so hard-stopping before joining
        test_process_manager.hard_stop_and_join_processes()

        expected_timestamp_1 = "2021_05_24_212304"
        actual_set_of_files_1 = set(
            os.listdir(
                os.path.join(expected_recordings_dir, f"{expected_plate_barcode_1}__{expected_timestamp_1}")
            )
        )
        assert len(actual_set_of_files_1) == 48
        assert len([file_name for file_name in actual_set_of_files_1 if "Calibration" in file_name]) == 24
        assert len([file_name for file_name in actual_set_of_files_1 if "Calibration" not in file_name]) == 24

        # test first recording for all data and metadata
        num_recorded_data_points_1 = (
            expected_stop_index_1 - expected_start_index_1
        ) // DEFAULT_SAMPLING_PERIOD + 1
        for well_idx in range(24):
            well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
            with h5py.File(
                os.path.join(
                    expected_recordings_dir,
                    f"{expected_plate_barcode_1}__{expected_timestamp_1}",
                    f"{expected_plate_barcode_1}__{expected_timestamp_1}__{well_name}.h5",
                ),
                "r",
            ) as this_file:
                # test metadata values
                assert bool(this_file.attrs[str(HARDWARE_TEST_RECORDING_UUID)]) is False
                assert this_file.attrs[str(SOFTWARE_BUILD_NUMBER_UUID)] == COMPILED_EXE_BUILD_TIMESTAMP
                assert (
                    this_file.attrs[FILE_FORMAT_VERSION_METADATA_KEY]
                    == CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
                )
                assert this_file.attrs[str(UTC_BEGINNING_DATA_ACQUISTION_UUID)] == expected_time.strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )
                assert this_file.attrs[str(START_RECORDING_TIME_INDEX_UUID)] == expected_start_index_1
                assert this_file.attrs[str(UTC_BEGINNING_RECORDING_UUID)] == expected_time.strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )
                assert this_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == (
                    expected_time + datetime.timedelta(microseconds=expected_start_index_1)
                ).strftime("%Y-%m-%d %H:%M:%S.%f")
                assert this_file.attrs[str(USER_ACCOUNT_ID_UUID)] == "test_user"
                assert this_file.attrs[str(CUSTOMER_ACCOUNT_ID_UUID)] == "test_id"
                assert (
                    this_file.attrs[str(MAIN_FIRMWARE_VERSION_UUID)]
                    == MantarrayMcSimulator.default_main_firmware_version
                )
                assert (
                    this_file.attrs[str(CHANNEL_FIRMWARE_VERSION_UUID)]
                    == MantarrayMcSimulator.default_channel_firmware_version
                )
                assert (
                    this_file.attrs[str(MANTARRAY_SERIAL_NUMBER_UUID)]
                    == MantarrayMcSimulator.default_mantarray_serial_number
                )
                assert (
                    this_file.attrs[str(MANTARRAY_NICKNAME_UUID)]
                    == MantarrayMcSimulator.default_mantarray_nickname
                )
                assert this_file.attrs[str(SOFTWARE_RELEASE_VERSION_UUID)] == CURRENT_SOFTWARE_VERSION
                assert (
                    this_file.attrs[str(BOOT_FLAGS_UUID)]
                    == MantarrayMcSimulator.default_metadata_values[BOOT_FLAGS_UUID]
                )

                assert this_file.attrs[str(WELL_NAME_UUID)] == well_name
                assert this_file.attrs["Metadata UUID Descriptions"] == json.dumps(
                    str(METADATA_UUID_DESCRIPTIONS)
                )
                assert this_file.attrs[str(TOTAL_WELL_COUNT_UUID)] == 24
                row_idx, col_idx = GENERIC_24_WELL_DEFINITION.get_row_and_column_from_well_index(well_idx)
                assert this_file.attrs[str(WELL_ROW_UUID)] == row_idx
                assert this_file.attrs[str(WELL_COLUMN_UUID)] == col_idx
                assert this_file.attrs[str(WELL_INDEX_UUID)] == well_idx
                assert this_file.attrs[str(TISSUE_SAMPLING_PERIOD_UUID)] == DEFAULT_SAMPLING_PERIOD
                assert this_file.attrs[str(BACKEND_LOG_UUID)] == str(
                    GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        BACKEND_LOG_UUID
                    ]
                )
                assert (
                    this_file.attrs[str(COMPUTER_NAME_HASH_UUID)]
                    == GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        COMPUTER_NAME_HASH_UUID
                    ]
                )
                protocol_idx = well_idx % 2
                assert this_file.attrs[str(STIMULATION_PROTOCOL_UUID)] == json.dumps(
                    test_stim_info["protocols"][protocol_idx]
                ), well_idx
                assert this_file.attrs[str(PLATE_BARCODE_UUID)] == expected_plate_barcode_1
                assert (
                    bool(this_file.attrs[str(PLATE_BARCODE_IS_FROM_SCANNER_UUID)])
                    is GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        PLATE_BARCODE_IS_FROM_SCANNER_UUID
                    ]
                )
                assert (
                    this_file.attrs[str(STIM_BARCODE_UUID)]
                    == GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        STIM_BARCODE_UUID
                    ]
                )
                assert (
                    bool(this_file.attrs[str(STIM_BARCODE_IS_FROM_SCANNER_UUID)])
                    is GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        STIM_BARCODE_IS_FROM_SCANNER_UUID
                    ]
                )
                assert (
                    this_file.attrs[str(INITIAL_MAGNET_FINDING_PARAMS_UUID)]
                    == GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                        INITIAL_MAGNET_FINDING_PARAMS_UUID
                    ]
                )
                assert (
                    this_file.attrs[str(PLATEMAP_NAME_UUID)]
                    == GENERIC_BETA_2_START_RECORDING_COMMAND["platemap"]["name"]
                )
                assert (
                    this_file.attrs[str(PLATEMAP_LABEL_UUID)]
                    == GENERIC_BETA_2_START_RECORDING_COMMAND["platemap"]["labels"][well_idx]
                )
                # test recorded magnetometer data
                actual_time_index_data = get_time_index_dataset_from_file(this_file)
                assert actual_time_index_data.shape == (num_recorded_data_points_1,)
                assert actual_time_index_data[0] == expected_start_index_1
                assert actual_time_index_data[-1] == expected_stop_index_1
                actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
                assert actual_time_offset_data.shape == (
                    SERIAL_COMM_NUM_SENSORS_PER_WELL,
                    num_recorded_data_points_1,
                )
                actual_tissue_data = get_tissue_dataset_from_file(this_file)
                assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, num_recorded_data_points_1)
                # test recorded stim data
                actual_stim_data = get_stimulation_dataset_from_file(this_file)
                assert actual_stim_data.shape[0] == 2
                if well_idx % 2 == 0:
                    assert actual_stim_data.shape[1] > 0, well_idx
                else:
                    assert actual_stim_data.shape[1] == 0, well_idx

        expected_timestamp_2 = "2021_05_24_212306"
        actual_set_of_files_2 = set(
            os.listdir(
                os.path.join(expected_recordings_dir, f"{expected_plate_barcode_2}__{expected_timestamp_2}")
            )
        )
        assert len(actual_set_of_files_2) == 48
        assert len([file_name for file_name in actual_set_of_files_2 if "Calibration" in file_name]) == 24
        assert len([file_name for file_name in actual_set_of_files_2 if "Calibration" not in file_name]) == 24
        # Tanner (12/30/20): test second recording (only make sure it contains waveform data)
        num_recorded_data_points_2 = (
            expected_stop_index_2 - expected_start_index_2
        ) // DEFAULT_SAMPLING_PERIOD + 1
        for well_idx in range(24):
            well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
            with h5py.File(
                os.path.join(
                    expected_recordings_dir,
                    f"{expected_plate_barcode_2}__{expected_timestamp_2}",
                    f"{expected_plate_barcode_2}__{expected_timestamp_2}__{well_name}.h5",
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
                # test recorded magnetometer data
                actual_time_index_data = get_time_index_dataset_from_file(this_file)
                assert actual_time_index_data.shape == (num_recorded_data_points_2,), f"Well {well_idx}"
                assert actual_time_index_data[0] == expected_start_index_2
                # Tanner (9/15/22): Since the final stim time index is now used as the stop time index, the final mag time index should be within one sampling period before the stop time index
                assert expected_stop_index_2 - actual_time_index_data[-1] <= DEFAULT_SAMPLING_PERIOD
                actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
                assert actual_time_offset_data.shape == (
                    SERIAL_COMM_NUM_SENSORS_PER_WELL,
                    num_recorded_data_points_2,
                )
                actual_tissue_data = get_tissue_dataset_from_file(this_file)
                assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, num_recorded_data_points_2)
                # test recorded stim data
                actual_stim_data = get_stimulation_dataset_from_file(this_file)
                assert actual_stim_data.shape[0] == 2
                if well_idx % 2 == 0:
                    # since this protocol is not set to stop running after a certain amount of time, assert that a min value was reached rather than an exact number
                    assert actual_stim_data.shape[1] >= 5, well_idx
                else:
                    assert actual_stim_data.shape[1] == 4, well_idx


# TODO Tanner (9/15/22): change this test so it uses beta 2 mode
@pytest.mark.slow
@pytest.mark.timeout(INTEGRATION_TEST_TIMEOUT)
def test_app_shutdown__in_worst_case_while_recording_is_running(
    patched_xem_scripts_folder,
    patched_firmware_folder,
    test_socketio_client,
    fully_running_app_from_main_entrypoint,
    mocker,
):
    # mock this so test doesn't actually try to hit cloud API
    mocked_get_tokens = mocker.patch.object(server, "validate_user_credentials", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})

    spied_logger = mocker.spy(main.logger, "info")
    # Tanner (12/29/20): Not making assertions on files, but still need a TemporaryDirectory to hold them
    with tempfile.TemporaryDirectory() as tmp_dir:
        recording_dir = os.path.join(tmp_dir, "recordings")
        expected_analysis_output_dir = os.path.join(tmp_dir, "time_force_data")
        test_dict = {
            "recording_directory": recording_dir,
            "mag_analysis_output_dir": expected_analysis_output_dir,
            "log_file_id": str(
                GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
                    BACKEND_LOG_UUID
                ]
            ),
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
        command_line_args = [f"--initial-base64-settings={b64_encoded}"]

        app_info = fully_running_app_from_main_entrypoint(command_line_args)
        assert system_state_eventually_equals(SERVER_INITIALIZING_STATE, 10) is True
        sio, _ = test_socketio_client()
        wait_for_subprocesses_to_start()
        test_process_manager = app_info["object_access_inside_main"]["process_manager"]

        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, CALIBRATION_NEEDED_WAIT_TIME) is True

        okc_process = test_process_manager.instrument_comm_process
        fw_process = test_process_manager.file_writer_process
        da_process = test_process_manager.data_analyzer_process

        user_dict = {"customer_id": "test_id", "user_password": "test_password", "user_name": "test_user"}
        response = requests.get(f"{get_api_endpoint()}login", params=user_dict)
        assert response.status_code == 200

        # Tanner (12/30/20): Start calibration in order to run managed_acquisition
        response = requests.get(f"{get_api_endpoint()}start_calibration")
        assert response.status_code == 200
        assert system_state_eventually_equals(CALIBRATING_STATE, 5) is True

        assert system_state_eventually_equals(CALIBRATED_STATE, CALIBRATED_WAIT_TIME) is True

        expected_plate_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][PLATE_BARCODE_UUID]
        # Tanner (12/30/20): start managed_acquisition in order to start recording
        response = requests.get(
            f"{get_api_endpoint()}start_managed_acquisition?plate_barcode={expected_plate_barcode}"
        )
        assert response.status_code == 200

        # Tanner (12/30/20): managed_acquisition will take system through buffering state and then to live_view active state before recording can start
        assert system_state_eventually_equals(BUFFERING_STATE, 5) is True
        assert system_state_eventually_equals(LIVE_VIEW_ACTIVE_STATE, LIVE_VIEW_ACTIVE_WAIT_TIME) is True

        start_recording_params = {
            "plate_barcode": expected_plate_barcode,
            "is_hardware_test_recording": False,
        }
        response = requests.get(f"{get_api_endpoint()}start_recording", params=start_recording_params)
        assert response.status_code == 200
        assert system_state_eventually_equals(RECORDING_STATE, 5) is True

        time.sleep(3)  # Tanner (6/15/20): This allows data to be written to files

        # Tanner (1/10/23): disconnect here to avoid problems with attempting to disconnect after calling /shutdown
        sio.disconnect()

        # Tanner (12/29/20): Shutdown now that data is being acquired and actively written to files, which means each subprocess is doing something
        response = requests.get(f"{get_api_endpoint()}shutdown")
        assert response.status_code == 200

        # Tanner (12/30/20): Confirming the port is available to make sure that the Flask server has shutdown
        confirm_port_available(get_server_port_number(), timeout=10)

        # Tanner (1/18/23): socketio has problems shutting down on windows, so need a large timeout
        program_exit_wait_time_secs = 150
        for _ in range(program_exit_wait_time_secs):
            try:
                # Tanner (12/30/20): This is the very last log message before the app is completely shutdown
                spied_logger.assert_any_call("Program exiting")
                program_exit_not_found_error = None
            except AssertionError as e:
                program_exit_not_found_error = e
                time.sleep(1)
        if program_exit_not_found_error:
            raise program_exit_not_found_error

        # Tanner (12/29/20): If these are alive, this means that zombie processes will be created when the compiled desktop app EXE is running, so this assertion helps make sure that that won't happen
        assert okc_process.is_alive() is False
        assert fw_process.is_alive() is False
        assert da_process.is_alive() is False


# TODO Tanner (1/18/21): eventually remove Beta 1 integration tests and add one for a successful auto FW update
