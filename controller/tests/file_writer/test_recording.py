# -*- coding: utf-8 -*-
import copy
import glob
import json
import os
from random import choice
from random import randint

import h5py
from mantarray_desktop_app import CalibrationFilesMissingError
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import FILE_WRITER_BUFFER_SIZE_MICROSECONDS
from mantarray_desktop_app import get_reference_dataset_from_file
from mantarray_desktop_app import get_stimulation_dataset_from_file
from mantarray_desktop_app import get_time_index_dataset_from_file
from mantarray_desktop_app import get_time_offset_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import InvalidStopRecordingTimepointError
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.utils.stimulation import chunk_protocols_in_stim_info
import numpy as np
from pulse3D.constants import ADC_GAIN_SETTING_UUID
from pulse3D.constants import ADC_REF_OFFSET_UUID
from pulse3D.constants import ADC_TISSUE_OFFSET_UUID
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import COMPUTER_NAME_HASH_UUID
from pulse3D.constants import CUSTOMER_ACCOUNT_ID_UUID
from pulse3D.constants import FILE_FORMAT_VERSION_METADATA_KEY
from pulse3D.constants import HARDWARE_TEST_RECORDING_UUID
from pulse3D.constants import INITIAL_MAGNET_FINDING_PARAMS_UUID
from pulse3D.constants import IS_CALIBRATION_FILE_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
from pulse3D.constants import METADATA_UUID_DESCRIPTIONS
from pulse3D.constants import NUM_INITIAL_MICROSECONDS_TO_REMOVE_UUID
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
from pulse3D.constants import WELL_COLUMN_UUID
from pulse3D.constants import WELL_INDEX_UUID
from pulse3D.constants import WELL_NAME_UUID
from pulse3D.constants import WELL_ROW_UUID
from pulse3D.constants import XEM_SERIAL_NUMBER_UUID
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import create_and_close_beta_1_h5_files
from ..fixtures_file_writer import create_simple_beta_2_data_packet
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import fixture_runnable_four_board_file_writer_process
from ..fixtures_file_writer import fixture_running_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_BETA_1_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_STIM_INFO
from ..fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_UPDATE_USER_SETTINGS
from ..fixtures_file_writer import open_the_generic_h5_file
from ..fixtures_file_writer import populate_calibration_folder
from ..fixtures_file_writer import TEST_CUSTOMER_ID
from ..fixtures_file_writer import TEST_USER_NAME
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..parsed_channel_data_packets import SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0
from ..parsed_channel_data_packets import SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS
from ..parsed_channel_data_packets import SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS


__fixtures__ = [
    fixture_four_board_file_writer_process,
    fixture_running_four_board_file_writer_process,
    fixture_runnable_four_board_file_writer_process,
    fixture_patch_print,
]


@pytest.mark.timeout(6)
@pytest.mark.parametrize("test_beta_version", [1, 2])
def test_FileWriterProcess__creates_24_files_named_with_timestamp_barcode_well_index__and_supplied_metadata__set_to_swmr_mode__when_receiving_communication_to_start_recording(
    test_beta_version, four_board_file_writer_process
):
    # Creating 24 files takes a few seconds, so also test that all the metadata and other things are set during this single test
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    # set up expected values
    if test_beta_version == 2:
        file_writer_process.set_beta_2_mode()
        populate_calibration_folder(file_writer_process)
    start_recording_command = dict(
        GENERIC_BETA_1_START_RECORDING_COMMAND
        if test_beta_version == 1
        else GENERIC_BETA_2_START_RECORDING_COMMAND
    )
    data_shape = (0,) if test_beta_version == 1 else (SERIAL_COMM_NUM_DATA_CHANNELS, 0)
    data_type = np.int32 if test_beta_version == 1 else np.uint16
    simulator_class = RunningFIFOSimulator if test_beta_version == 1 else MantarrayMcSimulator
    file_version = (
        CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
        if test_beta_version == 1
        else CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
    )

    timestamp_str = "2020_02_09_190935" if test_beta_version == 1 else "2020_02_09_190359"
    expected_plate_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    actual_set_of_files = set(
        os.listdir(os.path.join(file_dir, f"{expected_plate_barcode}__{timestamp_str}"))
    )
    actual_set_of_files = {
        file_path for file_path in actual_set_of_files if expected_plate_barcode in file_path
    }
    assert len(actual_set_of_files) == 24

    expected_set_of_files = {
        f"{expected_plate_barcode}__{timestamp_str}__{GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)}.h5"
        for well_idx in range(24)
    }
    assert actual_set_of_files == expected_set_of_files

    for well_idx in range(24):
        assert file_writer_process._open_files[0][well_idx].swmr_mode is True, well_idx

    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)

        this_file = h5py.File(
            os.path.join(
                file_dir,
                f"{expected_plate_barcode}__{timestamp_str}",
                f"{expected_plate_barcode}__{timestamp_str}__{well_name}.h5",
            ),
            "r",
        )
        # test metadata present in both beta versions
        assert this_file.attrs[FILE_FORMAT_VERSION_METADATA_KEY] == file_version
        assert bool(this_file.attrs[str(HARDWARE_TEST_RECORDING_UUID)]) is False
        assert this_file.attrs[str(UTC_BEGINNING_DATA_ACQUISTION_UUID)] == "2020-02-09 19:03:22.332597"
        assert (
            this_file.attrs[str(START_RECORDING_TIME_INDEX_UUID)]
            == start_recording_command["metadata_to_copy_onto_main_file_attributes"][
                START_RECORDING_TIME_INDEX_UUID
            ]
        )
        assert this_file.attrs[str(UTC_BEGINNING_RECORDING_UUID)] == start_recording_command[
            "metadata_to_copy_onto_main_file_attributes"
        ][UTC_BEGINNING_RECORDING_UUID].strftime("%Y-%m-%d %H:%M:%S.%f")
        assert this_file.attrs[str(CUSTOMER_ACCOUNT_ID_UUID)] == str(TEST_CUSTOMER_ID)
        assert this_file.attrs[str(USER_ACCOUNT_ID_UUID)] == TEST_USER_NAME
        actual_build_id = this_file.attrs[str(SOFTWARE_BUILD_NUMBER_UUID)]
        assert actual_build_id == COMPILED_EXE_BUILD_TIMESTAMP
        assert this_file.attrs[str(SOFTWARE_RELEASE_VERSION_UUID)] == CURRENT_SOFTWARE_VERSION
        assert this_file.attrs[str(MANTARRAY_NICKNAME_UUID)] == simulator_class.default_mantarray_nickname
        assert (
            this_file.attrs[str(MANTARRAY_SERIAL_NUMBER_UUID)]
            == simulator_class.default_mantarray_serial_number
        )

        assert this_file.attrs["Metadata UUID Descriptions"] == json.dumps(str(METADATA_UUID_DESCRIPTIONS))
        assert this_file.attrs[str(WELL_NAME_UUID)] == well_name
        row_idx, col_idx = GENERIC_24_WELL_DEFINITION.get_row_and_column_from_well_index(well_idx)
        assert this_file.attrs[str(WELL_ROW_UUID)] == row_idx
        assert this_file.attrs[str(WELL_COLUMN_UUID)] == col_idx
        assert this_file.attrs[str(WELL_INDEX_UUID)] == well_idx
        assert this_file.attrs[str(TOTAL_WELL_COUNT_UUID)] == 24
        assert (
            this_file.attrs[str(COMPUTER_NAME_HASH_UUID)]
            == start_recording_command["metadata_to_copy_onto_main_file_attributes"][COMPUTER_NAME_HASH_UUID]
        )
        assert this_file.attrs[str(PLATE_BARCODE_UUID)] == expected_plate_barcode
        assert (
            bool(this_file.attrs[str(PLATE_BARCODE_IS_FROM_SCANNER_UUID)])
            is start_recording_command["metadata_to_copy_onto_main_file_attributes"][
                PLATE_BARCODE_IS_FROM_SCANNER_UUID
            ]
        )
        assert this_file.attrs[str(PLATEMAP_NAME_UUID)] == start_recording_command["platemap"]["name"]
        assert (
            this_file.attrs[str(PLATEMAP_LABEL_UUID)]
            == start_recording_command["platemap"]["labels"][well_idx]
        )
        # test metadata values and datasets not present in both beta versions
        if test_beta_version == 1:
            assert (
                this_file.attrs[str(MAIN_FIRMWARE_VERSION_UUID)]
                == RunningFIFOSimulator.default_firmware_version
            )
            assert this_file.attrs[str(SLEEP_FIRMWARE_VERSION_UUID)] == "0.0.0"
            assert (
                this_file.attrs[str(XEM_SERIAL_NUMBER_UUID)] == RunningFIFOSimulator.default_xem_serial_number
            )
            assert (
                this_file.attrs[str(TISSUE_SAMPLING_PERIOD_UUID)]
                == CONSTRUCT_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
            )
            assert (
                this_file.attrs[str(REF_SAMPLING_PERIOD_UUID)]
                == REFERENCE_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
            )
            assert this_file.attrs[str(REFERENCE_VOLTAGE_UUID)] == REFERENCE_VOLTAGE
            assert this_file.attrs[str(ADC_GAIN_SETTING_UUID)] == 32
            assert (
                this_file.attrs[str(ADC_TISSUE_OFFSET_UUID)]
                == start_recording_command["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"][
                    well_idx
                ]["construct"]
            )
            assert (
                this_file.attrs[str(ADC_REF_OFFSET_UUID)]
                == start_recording_command["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"][
                    well_idx
                ]["ref"]
            )
        else:
            # check that current beta 1 only values are not present
            assert str(SLEEP_FIRMWARE_VERSION_UUID) not in this_file.attrs
            assert str(XEM_SERIAL_NUMBER_UUID) not in this_file.attrs
            assert str(REF_SAMPLING_PERIOD_UUID) not in this_file.attrs
            assert str(ADC_GAIN_SETTING_UUID) not in this_file.attrs
            assert str(ADC_TISSUE_OFFSET_UUID) not in this_file.attrs
            assert str(ADC_REF_OFFSET_UUID) not in this_file.attrs
            # check that beta 2 value are present
            assert (
                this_file.attrs[str(MAIN_FIRMWARE_VERSION_UUID)]
                == MantarrayMcSimulator.default_main_firmware_version
            )
            assert (
                this_file.attrs[str(CHANNEL_FIRMWARE_VERSION_UUID)]
                == MantarrayMcSimulator.default_channel_firmware_version
            )
            assert bool(this_file.attrs[str(IS_CALIBRATION_FILE_UUID)]) is False
            assert (
                this_file.attrs[str(TISSUE_SAMPLING_PERIOD_UUID)]
                == start_recording_command["metadata_to_copy_onto_main_file_attributes"][
                    TISSUE_SAMPLING_PERIOD_UUID
                ]
            )
            assert (
                this_file.attrs[str(BOOT_FLAGS_UUID)]
                == MantarrayMcSimulator.default_metadata_values[BOOT_FLAGS_UUID]
            )
            assert (
                this_file.attrs[str(STIM_BARCODE_UUID)]
                == start_recording_command["metadata_to_copy_onto_main_file_attributes"][STIM_BARCODE_UUID]
            )
            assert (
                bool(this_file.attrs[str(STIM_BARCODE_IS_FROM_SCANNER_UUID)])
                is start_recording_command["metadata_to_copy_onto_main_file_attributes"][
                    STIM_BARCODE_IS_FROM_SCANNER_UUID
                ]
            )
            assert (
                this_file.attrs[str(INITIAL_MAGNET_FINDING_PARAMS_UUID)]
                == start_recording_command["metadata_to_copy_onto_main_file_attributes"][
                    INITIAL_MAGNET_FINDING_PARAMS_UUID
                ]
            )
            assert (
                this_file.attrs[str(NUM_INITIAL_MICROSECONDS_TO_REMOVE_UUID)]
                == start_recording_command["metadata_to_copy_onto_main_file_attributes"][
                    NUM_INITIAL_MICROSECONDS_TO_REMOVE_UUID
                ]
            )
            assert get_time_index_dataset_from_file(this_file).shape == (0,)
            assert get_time_index_dataset_from_file(this_file).dtype == "uint64"
            assert get_time_offset_dataset_from_file(this_file).shape == (SERIAL_COMM_NUM_SENSORS_PER_WELL, 0)
            assert get_time_offset_dataset_from_file(this_file).dtype == "uint16"
        # test data sets
        assert get_reference_dataset_from_file(this_file).shape == data_shape
        assert get_reference_dataset_from_file(this_file).dtype == data_type
        assert get_tissue_dataset_from_file(this_file).shape == data_shape
        assert get_tissue_dataset_from_file(this_file).dtype == data_type


@pytest.mark.parametrize("test_recording_name", ["Test Name", None])
def test_FileWriterProcess__creates_recording_dir_and_files_with_correct_name(
    test_recording_name, four_board_file_writer_process
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    populate_calibration_folder(fw_process)

    this_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    if test_recording_name:
        this_command["recording_name"] = test_recording_name
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)

    invoke_process_run_and_check_errors(fw_process)

    timestamp_str = "2020_02_09_190359"
    expected_plate_barcode = this_command["metadata_to_copy_onto_main_file_attributes"][PLATE_BARCODE_UUID]

    if test_recording_name:
        actual_recording_name = test_recording_name
    else:
        actual_recording_name = f"{expected_plate_barcode}__{timestamp_str}"

    assert os.path.isdir(os.path.join(file_dir, actual_recording_name))


@pytest.mark.timeout(4)
def test_FileWriterProcess__beta_1_mode__only_creates_file_indices_specified__when_receiving_communication_to_start_recording__and_reports_command_receipt_to_main(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    spied_abspath = mocker.spy(os.path, "abspath")

    timestamp_str = "2020_02_09_190935"
    expected_plate_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    this_command = dict(GENERIC_BETA_1_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [3, 18]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)
    actual_set_of_files = set(
        os.listdir(os.path.join(file_dir, f"{expected_plate_barcode}__{timestamp_str}"))
    )
    assert len(actual_set_of_files) == 2

    expected_set_of_files = set(
        [
            f"{expected_plate_barcode}__{timestamp_str}__D1.h5",
            f"{expected_plate_barcode}__{timestamp_str}__C5.h5",
        ]
    )
    assert actual_set_of_files == expected_set_of_files
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    comm_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert comm_to_main["communication_type"] == "command_receipt"
    assert comm_to_main["command"] == "start_recording"
    assert file_dir in comm_to_main["file_folder"]
    assert expected_plate_barcode in comm_to_main["file_folder"]
    spied_abspath.assert_any_call(
        file_writer_process.get_file_directory()
    )  # Eli (3/16/20): apparently numpy calls this quite frequently, so can only assert_any_call, not assert_called_once_with
    assert isinstance(comm_to_main["timepoint_to_begin_recording_at"], int) is True


@pytest.mark.timeout(4)
def test_FileWriterProcess__beta_2_mode__creates_files_for_all_active_wells__when_receiving_communication_to_start_recording__and_reports_command_receipt_to_main(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    populate_calibration_folder(file_writer_process)
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    spied_abspath = mocker.spy(os.path, "abspath")

    timestamp_str = "2020_02_09_190359"
    expected_plate_barcode = GENERIC_BETA_2_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    this_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    # test created files
    actual_set_of_files = set(
        os.listdir(os.path.join(file_dir, f"{expected_plate_barcode}__{timestamp_str}"))
    )
    actual_set_of_files = {
        file_path for file_path in actual_set_of_files if expected_plate_barcode in file_path
    }
    expected_set_of_files = {
        f"{expected_plate_barcode}__{timestamp_str}__{GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)}.h5"
        for well_idx in range(24)
    }
    assert actual_set_of_files == expected_set_of_files
    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        this_file = h5py.File(
            os.path.join(
                file_dir,
                f"{expected_plate_barcode}__{timestamp_str}",
                f"{expected_plate_barcode}__{timestamp_str}__{well_name}.h5",
            ),
            "r",
        )
        assert get_time_offset_dataset_from_file(this_file).shape[0] == SERIAL_COMM_NUM_SENSORS_PER_WELL
        assert get_tissue_dataset_from_file(this_file).shape[0] == SERIAL_COMM_NUM_DATA_CHANNELS

        # make sure stim metadata is correct
        assert this_file.attrs[str(STIMULATION_PROTOCOL_UUID)] == json.dumps(None), well_idx

    # test command receipt
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    comm_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert comm_to_main["communication_type"] == "command_receipt"
    assert comm_to_main["command"] == "start_recording"
    assert file_dir in comm_to_main["file_folder"]
    assert expected_plate_barcode in comm_to_main["file_folder"]
    spied_abspath.assert_any_call(
        file_writer_process.get_file_directory()
    )  # Eli (3/16/20): apparently numpy calls this quite frequently, so can only assert_any_call, not assert_called_once_with
    assert isinstance(comm_to_main["timepoint_to_begin_recording_at"], int) is True


@pytest.mark.timeout(4)
def test_FileWriterProcess__beta_2_mode__creates_files_with_correct_stimulation_metadata__when_receiving_communication_to_start_recording__after_protocols_have_been_set(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    populate_calibration_folder(file_writer_process)
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    expected_stim_info, *chunk_info = chunk_protocols_in_stim_info(GENERIC_STIM_INFO)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": chunk_info[0],
        "max_subprotocol_idx_counts": chunk_info[1],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    # send start_recording command after set_protocols command
    file_timestamp_str = "2020_02_09_190359"
    expected_plate_barcode = GENERIC_BETA_2_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    # process both commands
    invoke_process_run_and_check_errors(file_writer_process, num_iterations=2)

    # test created files
    labeled_protocol_dict = {
        protocol["protocol_id"]: protocol for protocol in expected_stim_info["protocols"]
    }
    expected_protocols = {
        well_name: labeled_protocol_dict.get(protocol_id)
        for well_name, protocol_id in expected_stim_info["protocol_assignments"].items()
    }

    actual_set_of_files = set(
        os.listdir(os.path.join(file_dir, f"{expected_plate_barcode}__{file_timestamp_str}"))
    )
    actual_set_of_files = {
        file_path for file_path in actual_set_of_files if expected_plate_barcode in file_path
    }
    expected_set_of_files = {
        f"{expected_plate_barcode}__{file_timestamp_str}__{GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)}.h5"
        for well_idx in range(24)
    }
    assert actual_set_of_files == expected_set_of_files
    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        this_file = h5py.File(
            os.path.join(
                file_dir,
                f"{expected_plate_barcode}__{file_timestamp_str}",
                f"{expected_plate_barcode}__{file_timestamp_str}__{well_name}.h5",
            ),
            "r",
        )
        assert this_file.attrs[str(STIMULATION_PROTOCOL_UUID)] == json.dumps(
            expected_protocols[well_name]
        ), well_idx


@pytest.mark.timeout(4)
def test_FileWriterProcess__beta_2_mode__creates_files_with_correct_stimulation_metadata__when_receiving_communication_to_start_recording__before_protocols_have_been_set(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    populate_calibration_folder(file_writer_process)
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    # send start_recording command before set_protocols command
    file_timestamp_str = "2020_02_09_190359"
    expected_plate_barcode = GENERIC_BETA_2_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    # send set_protocols command
    expected_stim_info, *chunk_info = chunk_protocols_in_stim_info(GENERIC_STIM_INFO)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": chunk_info[0],
        "max_subprotocol_idx_counts": chunk_info[1],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    # process both commands
    invoke_process_run_and_check_errors(file_writer_process, num_iterations=2)

    # test created files
    labeled_protocol_dict = {
        protocol["protocol_id"]: protocol for protocol in expected_stim_info["protocols"]
    }
    expected_protocols = {
        well_name: labeled_protocol_dict.get(protocol_id)
        for well_name, protocol_id in expected_stim_info["protocol_assignments"].items()
    }

    actual_set_of_files = set(
        os.listdir(os.path.join(file_dir, f"{expected_plate_barcode}__{file_timestamp_str}"))
    )
    actual_set_of_files = {
        file_path for file_path in actual_set_of_files if expected_plate_barcode in file_path
    }
    expected_set_of_files = {
        f"{expected_plate_barcode}__{file_timestamp_str}__{GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)}.h5"
        for well_idx in range(24)
    }
    assert actual_set_of_files == expected_set_of_files
    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        this_file = h5py.File(
            os.path.join(
                file_dir,
                f"{expected_plate_barcode}__{file_timestamp_str}",
                f"{expected_plate_barcode}__{file_timestamp_str}__{well_name}.h5",
            ),
            "r",
        )
        assert this_file.attrs[str(STIMULATION_PROTOCOL_UUID)] == json.dumps(
            expected_protocols[well_name]
        ), well_idx


@pytest.mark.timeout(4)
def test_FileWriterProcess__beta_2_mode__creates_calibration_files_in_correct_folder__when_receiving_communication_to_start_recording(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = file_writer_process.calibration_file_directory

    for start_time_index, timestamp_str in (
        (0, "2020_02_09_190322"),
        (int(10e6), "2020_02_09_190332"),
    ):
        this_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
        this_command["is_calibration_recording"] = True
        # Tanner (12/13/21): only using different start time indices so each recording will have a different timestamp string
        this_command["timepoint_to_begin_recording_at"] = start_time_index

        put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
        invoke_process_run_and_check_errors(file_writer_process)

        # test created files
        actual_set_of_files = set(os.listdir(file_dir))
        expected_set_of_files = {
            f"Calibration__{timestamp_str}__{GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)}.h5"
            for well_idx in range(24)
        }
        assert actual_set_of_files == expected_set_of_files, timestamp_str
        for well_idx in range(24):
            well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
            this_file = h5py.File(
                os.path.join(
                    file_dir,
                    f"Calibration__{timestamp_str}__{well_name}.h5",
                ),
                "r",
            )
            assert (
                bool(this_file.attrs[str(IS_CALIBRATION_FILE_UUID)]) is True
            ), f"timestamp: {timestamp_str}, well_idx: {well_idx}"
            # need to close h5 file objects created in this test function and by FileWriter otherwise errors will be raised on windows
            this_file.close()
        file_writer_process.close_all_files()


def test_FileWriterProcess__beta_2_mode__copies_calibration_files_to_new_recording_folder__when_receiving_communication_to_start_recording(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    timestamp_str = "2020_02_09_190359"
    expected_plate_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]

    # populate calibration folder with recording files for each well
    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        file_path = os.path.join(
            file_writer_process.calibration_file_directory, f"Calibration__{timestamp_str}__{well_name}.h5"
        )
        # create and close file
        with open(file_path, "w"):
            pass

    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    actual_set_of_files = set(
        os.listdir(os.path.join(file_dir, f"{expected_plate_barcode}__{timestamp_str}"))
    )
    assert len(actual_set_of_files) == 24 * 2

    expected_set_of_files = set()
    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        expected_set_of_files.add(f"{expected_plate_barcode}__{timestamp_str}__{well_name}.h5")
        expected_set_of_files.add(f"Calibration__{timestamp_str}__{well_name}.h5")
    assert actual_set_of_files == expected_set_of_files


def test_FileWriterProcess__beta_2_mode__raises_error_if_calibration_files_are_missing__when_receiving_communication_to_start_recording(
    four_board_file_writer_process, patch_print
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    timestamp_str = "2020_02_09_190359"

    # populate calibration folder with recording files for some wells
    for well_idx in range(15):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        file_path = os.path.join(
            file_writer_process.calibration_file_directory, f"Calibration__{timestamp_str}__{well_name}.h5"
        )
        # create and close file
        with open(file_path, "w"):
            pass

    expected_missing_wells = [
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx) for well_idx in range(15, 24)
    ]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    with pytest.raises(CalibrationFilesMissingError) as exc_info:
        invoke_process_run_and_check_errors(file_writer_process)
    assert f"Missing wells: {sorted(expected_missing_wells)}" == str(exc_info.value)


def test_FileWriterProcess__start_recording__sets_stop_recording_timestamp_to_none__and_tissue_and_reference_finalization_status_to_false__and_is_recording_to_true(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    this_command = dict(GENERIC_BETA_1_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [1, 5]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    file_writer_process.get_stop_recording_timestamps()[0] = 2999283

    (
        tissue_status,
        reference_status,
    ) = file_writer_process.get_recording_finalization_statuses()
    tissue_status[0][3] = True
    reference_status[0][3] = True
    tissue_status[0][0] = True
    reference_status[0][0] = True

    invoke_process_run_and_check_errors(file_writer_process)

    stop_timestamps = file_writer_process.get_stop_recording_timestamps()

    assert stop_timestamps[0] is None
    assert set(tissue_status[0].keys()) == set([1, 5])
    assert set(reference_status[0].keys()) == set([1, 5])
    assert tissue_status[0][1] is False
    assert reference_status[0][1] is False
    assert tissue_status[0][5] is False
    assert reference_status[0][5] is False

    assert file_writer_process.is_recording() is True


def test_FileWriterProcess__stop_recording__sets_stop_recording_timestamp_to_timepoint_in_communication__and_communicates_successful_receipt__and_sets_is_recording_to_false__and_start_recording_clears_stop_timestamp_and_finalization_statuses(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    expected_well_idx = 0
    start_timepoint_1 = 440000
    this_command = dict(GENERIC_BETA_1_START_RECORDING_COMMAND)
    this_command["timepoint_to_begin_recording_at"] = start_timepoint_1
    this_command["active_well_indices"] = [expected_well_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    data_packet = {
        "is_reference_sensor": False,
        "well_index": expected_well_idx,
        "data": np.array([[start_timepoint_1], [0]], dtype=np.int32),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(file_writer_process)

    stop_timestamps = file_writer_process.get_stop_recording_timestamps()

    assert stop_timestamps[0] is None

    stop_timepoint = 2968000
    this_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    this_command["timepoint_to_stop_recording_at"] = stop_timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    assert stop_timestamps[0] == stop_timepoint

    confirm_queue_is_eventually_of_size(to_main_queue, 2)
    to_main_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pop off the initial receipt of start command message
    comm_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert comm_to_main["communication_type"] == "command_receipt"
    assert comm_to_main["command"] == "stop_recording"
    assert comm_to_main["timepoint_to_stop_recording_at"] == stop_timepoint

    assert file_writer_process.is_recording() is False

    timepoint_after_stop = 3000000  # Tanner (1/13/21): This just needs to be any timepoint after the stop timepoint in order to finalize the file
    data_packet2 = {
        "is_reference_sensor": False,
        "well_index": expected_well_idx,
        "data": np.array([[timepoint_after_stop], [0]], dtype=np.int32),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(data_packet2, board_queues[0][0])
    invoke_process_run_and_check_errors(file_writer_process)
    # Tanner (1/13/21): A reference data packet is also necessary to finalize the file
    ref_data_packet = {
        "is_reference_sensor": True,
        "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[0],
        "data": np.array([[timepoint_after_stop], [0]], dtype=np.int32),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(ref_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(file_writer_process)

    this_command = dict(GENERIC_BETA_1_START_RECORDING_COMMAND)
    this_command[
        "timepoint_to_begin_recording_at"
    ] = 3760000  # Tanner (1/13/21): This can be any arbitrary timepoint after the timepoint of the last data packet sent
    this_command["active_well_indices"] = [expected_well_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)
    assert stop_timestamps[0] is None

    tissue_status, _ = file_writer_process.get_recording_finalization_statuses()
    assert tissue_status[0][expected_well_idx] is False


def test_FileWriterProcess__closes_the_files_and_sends_communication_to_main_when_all_data_has_been_added_after_recording_stopped(
    four_board_file_writer_process, mocker
):
    file_dir = four_board_file_writer_process["file_dir"]

    spied_h5_close = mocker.spy(h5py.File, "close")

    test_num_data_points = 10
    test_well_index = randint(0, 23)
    test_well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(test_well_index)

    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"]["auto_delete_local_files"] = False
    update_user_settings_command["config_settings"]["auto_upload_on_completion"] = False

    msgs_to_main = create_and_close_beta_1_h5_files(
        four_board_file_writer_process,
        update_user_settings_command,
        num_data_points=test_num_data_points,
        active_well_indices=[test_well_index],
    )

    finalization_msg = msgs_to_main[0]
    assert finalization_msg["communication_type"] == "file_finalized"
    assert f"_{test_well_name}" in finalization_msg["file_path"]

    # corruption check closes file for a second time
    assert spied_h5_close.call_count == 2

    with open_the_generic_h5_file(
        file_dir, well_name=test_well_name, timestamp_str="2020_02_09_190322"
    ) as actual_file:
        actual_tissue_data = get_tissue_dataset_from_file(actual_file)[:]
        actual_ref_data = get_reference_dataset_from_file(actual_file)[:]
    assert actual_tissue_data.shape == (test_num_data_points,)
    assert actual_tissue_data[3] == 6
    assert actual_tissue_data[9] == 18
    assert actual_ref_data.shape == (test_num_data_points,)
    assert actual_ref_data[4] == 8
    assert actual_ref_data[8] == 16


def test_FileWriterProcess__sends_message_to_main_if_a_corrupt_file_is_found_after_a_recording(
    four_board_file_writer_process, mocker
):
    file_dir = four_board_file_writer_process["file_dir"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    test_num_data_points = 10

    def file_se(file_name, open_type, *args, **kwargs):
        yield h5py.File(file_name, open_type)
        raise Exception()

    mocker.patch.object(h5py, "File", autospec=True, side_effect=file_se)

    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"]["auto_delete_local_files"] = False
    update_user_settings_command["config_settings"]["auto_upload_on_completion"] = False
    create_and_close_beta_1_h5_files(
        four_board_file_writer_process,
        update_user_settings_command,
        num_data_points=test_num_data_points,
        active_well_indices=[0],
        check_queue_after_finalization=False,
    )

    assert drain_queue(to_main_queue)[-2] == {
        "communication_type": "corrupt_file_detected",
        "corrupt_files": glob.glob(os.path.join(file_dir, "**", "*.h5"), recursive=True),
    }


def test_FileWriterProcess__does_not_send_message_to_main_if_no_corrupt_files_found_after_a_recording(
    four_board_file_writer_process,
):
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    test_num_data_points = 10

    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"]["auto_delete_local_files"] = False
    update_user_settings_command["config_settings"]["auto_upload_on_completion"] = False
    create_and_close_beta_1_h5_files(
        four_board_file_writer_process,
        update_user_settings_command,
        num_data_points=test_num_data_points,
        active_well_indices=[0],
        check_queue_after_finalization=False,
    )

    assert not [
        msg for msg in drain_queue(to_main_queue) if msg["communication_type"] == "corrupt_file_detected"
    ]


def test_FileWriterProcess__adds_incoming_magnetometer_data_to_internal_buffer(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]

    expected_num_items = 3
    for _ in range(expected_num_items):
        board_queues[0][0].put_nowait(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)
    confirm_queue_is_eventually_of_size(
        board_queues[0][0],
        expected_num_items,
    )

    invoke_process_run_and_check_errors(file_writer_process, num_iterations=expected_num_items)
    actual_num_items = len(file_writer_process._data_packet_buffers[0])
    assert actual_num_items == expected_num_items


def test_FileWriterProcess__does_not_add_incoming_beta_2_magnetometer_data_to_internal_buffer_if_after_stop_timepoint(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    board_queues = four_board_file_writer_process["board_queues"]

    test_data_buffer = file_writer_process._data_packet_buffers[0]

    test_num_items = 4
    packet_len = len(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS["time_indices"])
    for packet_num in range(test_num_items):
        test_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
        start = packet_num * packet_len
        test_packet["time_indices"] = np.arange(start, start + packet_len, dtype=np.uint64)
        board_queues[0][0].put_nowait(test_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], test_num_items)
    invoke_process_run_and_check_errors(file_writer_process, num_iterations=test_num_items - 1)
    assert len(test_data_buffer) == test_num_items - 1

    # send stop managed acquisition command to clear data buffer and set stop timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        STOP_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)
    # send a data packet from the end of the stream and make sure it is not added to buffer
    invoke_process_run_and_check_errors(file_writer_process)
    assert len(test_data_buffer) == 0

    # Tanner (6/19/21): prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


def test_FileWriterProcess__clears_leftover_beta_2_magnetometer_data_of_previous_data_stream_from_buffer_when_receiving_first_packet_of_new_stream(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    board_queues = four_board_file_writer_process["board_queues"]

    # load data into buffer
    expected_num_items = 5
    for _ in range(expected_num_items):
        board_queues[0][0].put_nowait(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    confirm_queue_is_eventually_of_size(
        board_queues[0][0],
        expected_num_items,
    )
    invoke_process_run_and_check_errors(file_writer_process, num_iterations=expected_num_items)
    actual_num_items = len(file_writer_process._data_packet_buffers[0])
    assert actual_num_items == expected_num_items

    # send packet from new stream to clear old data from buffer
    first_packet_of_new_stream = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    first_packet_of_new_stream["is_first_packet_of_stream"] = True
    board_queues[0][0].put_nowait(first_packet_of_new_stream)
    confirm_queue_is_eventually_of_size(
        board_queues[0][0],
        1,
    )
    invoke_process_run_and_check_errors(file_writer_process)
    actual_num_items = len(file_writer_process._data_packet_buffers[0])
    assert actual_num_items == 1

    # clean up
    drain_queue(board_queues[0][1])


def test_FileWriterProcess__removes_beta_1_packets_from_magnetometer_data_buffer_that_are_older_than_buffer_memory_size(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]

    new_packet = {
        "is_reference_sensor": False,
        "well_index": 0,
        "data": np.array([[FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS + 1], [0]], dtype=np.int32),
    }
    old_packet = {
        "is_reference_sensor": True,
        "reference_for_wells": set([0, 1, 4, 5]),
        "data": np.array([[0], [0]], dtype=np.int32),
    }

    board_queues[0][0].put_nowait(old_packet)
    board_queues[0][0].put_nowait(new_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], 2)

    invoke_process_run_and_check_errors(file_writer_process, num_iterations=2)
    data_packet_buffer = file_writer_process._data_packet_buffers[0]
    assert len(data_packet_buffer) == 1
    assert data_packet_buffer[0]["is_reference_sensor"] is new_packet["is_reference_sensor"]
    assert data_packet_buffer[0]["well_index"] == new_packet["well_index"]
    np.testing.assert_equal(data_packet_buffer[0]["data"], new_packet["data"])


def test_FileWriterProcess__removes_beta_2_packets_from_magnetometer_data_buffer_that_are_older_than_buffer_memory_size(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    board_queues = four_board_file_writer_process["board_queues"]

    new_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    new_packet["time_indices"] = np.array([FILE_WRITER_BUFFER_SIZE_MICROSECONDS + 1], dtype=np.uint64)
    old_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    old_packet["time_indices"] = np.array([0], dtype=np.uint64)

    board_queues[0][0].put_nowait(old_packet)
    board_queues[0][0].put_nowait(new_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], 2)

    invoke_process_run_and_check_errors(file_writer_process, num_iterations=2)
    data_packet_buffer = file_writer_process._data_packet_buffers[0]
    assert len(data_packet_buffer) == 1
    np.testing.assert_equal(data_packet_buffer[0]["time_indices"], new_packet["time_indices"])


def test_FileWriterProcess__clears_magnetometer_data_buffer_when_stop_managed_acquisition_command_is_received(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    data_packet_buffer = file_writer_process._data_packet_buffers[0]
    for _ in range(3):
        data_packet_buffer.append(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        STOP_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    assert len(data_packet_buffer) == 0


def test_FileWriterProcess__records_all_requested_beta_1_magnetometer_data_in_buffer__and_creates_dict_of_latest_data_timepoints_for_open_files__when_start_recording_command_is_received(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    data_packet_buffer = file_writer_process._data_packet_buffers[0]
    for _ in range(2):
        data_packet_buffer.append(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)

    expected_start_timepoint = 100
    expected_num_packets_recorded = 3
    expected_well_idx = 0
    for i in range(expected_num_packets_recorded):
        data_packet = {
            "is_reference_sensor": False,
            "well_index": expected_well_idx,
            "data": np.array([[expected_start_timepoint + i], [0]], dtype=np.int32),
        }
        data_packet_buffer.append(data_packet)

    start_recording_command = dict(GENERIC_BETA_1_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = expected_start_timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    expected_plate_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"

    this_file = h5py.File(
        os.path.join(
            file_dir,
            f"{expected_plate_barcode}__{timestamp_str}",
            f"{expected_plate_barcode}__{timestamp_str}__{GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(expected_well_idx)}.h5",
        ),
        "r",
    )
    assert get_tissue_dataset_from_file(this_file).shape == (expected_num_packets_recorded,)
    assert get_tissue_dataset_from_file(this_file).dtype == "int32"

    expected_latest_timepoint = expected_start_timepoint + expected_num_packets_recorded - 1
    actual_latest_timepoint = file_writer_process.get_file_latest_timepoint(expected_well_idx)
    assert actual_latest_timepoint == expected_latest_timepoint


def test_FileWriterProcess__records_all_requested_beta_2_magnetometer_data_in_buffer__and_creates_dict_of_latest_data_timepoints_for_open_files__when_start_recording_command_is_received(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    populate_calibration_folder(file_writer_process)
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    data_packet_buffer = file_writer_process._data_packet_buffers[0]
    # dummy packets that will be ignored
    for _ in range(2):
        data_packet_buffer.append(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    # set up test data packets and add to incoming data queue
    expected_start_timepoint = 100
    expected_num_packets_recorded = 3
    num_data_points_per_packet = 2
    expected_total_num_data_points = expected_num_packets_recorded * num_data_points_per_packet
    expected_time_indices = np.arange(
        expected_start_timepoint, expected_start_timepoint + expected_total_num_data_points, dtype=np.uint64
    )
    base_data = np.ones(num_data_points_per_packet, dtype=np.uint16)
    base_time_offsets = np.ones(
        (SERIAL_COMM_NUM_SENSORS_PER_WELL, num_data_points_per_packet), dtype=np.uint16
    )
    for i in range(expected_num_packets_recorded):
        curr_idx = i * num_data_points_per_packet
        data_packet = {
            "time_indices": expected_time_indices[curr_idx : curr_idx + num_data_points_per_packet]
        }
        for well_idx in range(24):
            channel_dict = {"time_offsets": base_time_offsets * well_idx}
            channel_dict.update(
                {channel_idx: base_data * well_idx for channel_idx in range(SERIAL_COMM_NUM_DATA_CHANNELS)}
            )
            data_packet[well_idx] = channel_dict
        data_packet_buffer.append(data_packet)

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = expected_start_timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    expected_time_offsets_shape = (SERIAL_COMM_NUM_SENSORS_PER_WELL, expected_total_num_data_points)
    expected_data_shape = (SERIAL_COMM_NUM_DATA_CHANNELS, expected_total_num_data_points)
    expected_plate_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"
    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        this_file = h5py.File(
            os.path.join(
                four_board_file_writer_process["file_dir"],
                f"{expected_plate_barcode}__{timestamp_str}",
                f"{expected_plate_barcode}__{timestamp_str}__{well_name}.h5",
            ),
            "r",
        )
        time_index_dataset = get_time_index_dataset_from_file(this_file)
        assert time_index_dataset.dtype == "uint64", f"Incorrect time index dtype for well {well_idx}"
        assert time_index_dataset.shape == (
            expected_total_num_data_points,
        ), f"Incorrect time indices shape for well {well_idx}"
        np.testing.assert_array_equal(
            time_index_dataset,
            expected_time_indices,
            err_msg=f"Incorrect time indices for well {well_idx}",
        )

        time_offset_dataset = get_time_offset_dataset_from_file(this_file)
        assert time_offset_dataset.dtype == "uint16", f"Incorrect offset dtype for well {well_idx}"
        assert (
            time_offset_dataset.shape == expected_time_offsets_shape
        ), f"Incorrect offset shape for well {well_idx}"
        np.testing.assert_array_equal(
            time_offset_dataset,
            np.ones(expected_time_offsets_shape, dtype=np.uint16) * well_idx,
            err_msg=f"Incorrect offsets for well {well_idx}",
        )

        tissue_dataset = get_tissue_dataset_from_file(this_file)
        assert tissue_dataset.dtype == "uint16", f"Incorrect tissue dtype for well {well_idx}"
        assert tissue_dataset.shape == expected_data_shape, f"Incorrect tissue shape for well {well_idx}"
        np.testing.assert_array_equal(
            tissue_dataset,
            np.ones(expected_data_shape, dtype=np.uint16) * well_idx,
            err_msg=f"Incorrect data for well {well_idx}",
        )

        actual_latest_timepoint = file_writer_process.get_file_latest_timepoint(well_idx)
        assert (
            actual_latest_timepoint == expected_time_indices[-1]
        ), f"Incorrect latest timepoint for well {well_idx}"

        this_file.close()


def test_FileWriterProcess__adds_incoming_stim_data_to_internal_buffers(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()

    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    test_stim_info = dict(copy.deepcopy(GENERIC_STIM_INFO))
    test_stim_info["protocol_assignments"] = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", "B"])
        for well_idx in range(24)
    }

    expected_stim_info, *chunk_info = chunk_protocols_in_stim_info(test_stim_info)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": chunk_info[0],
        "max_subprotocol_idx_counts": chunk_info[1],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    expected_num_packets = 3
    expected_num_items = (
        expected_num_packets * SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS["well_statuses"][0].shape[1]
    )
    for _ in range(expected_num_packets):
        board_queues[board_idx][0].put_nowait(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
    confirm_queue_is_eventually_of_size(board_queues[board_idx][0], expected_num_packets)
    invoke_process_run_and_check_errors(file_writer_process, num_iterations=expected_num_packets)

    stim_data_buffers = file_writer_process.get_stim_data_buffers(board_idx)
    for well_idx in range(24):
        well_buffers = stim_data_buffers[well_idx]
        assert len(well_buffers[0]) == expected_num_items, well_idx
        assert len(well_buffers[1]) == expected_num_items, well_idx


def test_FileWriterProcess__clears_stim_data_from_buffers_when_stop_managed_acquisition_command_received(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    board_idx = 0
    for _ in range(3):
        file_writer_process.append_to_stim_data_buffers(
            SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS["well_statuses"]
        )
    stim_data_buffers = file_writer_process.get_stim_data_buffers(board_idx)
    for well_idx in range(24):
        well_buffers = stim_data_buffers[well_idx]
        assert len(well_buffers[0]) > 0, well_idx
        assert len(well_buffers[1]) > 0, well_idx

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        STOP_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    for well_idx in range(24):
        well_buffers = stim_data_buffers[well_idx]
        assert len(well_buffers[0]) == 0, well_idx
        assert len(well_buffers[1]) == 0, well_idx


def test_FileWriterProcess__does_not_add_incoming_stim_data_to_internal_buffer_if_after_stop_timepoint(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    board_queues = four_board_file_writer_process["board_queues"]

    board_idx = 0
    test_stim_buffers = file_writer_process.get_stim_data_buffers(board_idx)

    test_stim_info = dict(copy.deepcopy(GENERIC_STIM_INFO))
    test_stim_info["protocol_assignments"] = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", "B"])
        for well_idx in range(24)
    }

    expected_stim_info, *chunk_info = chunk_protocols_in_stim_info(test_stim_info)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": chunk_info[0],
        "max_subprotocol_idx_counts": chunk_info[1],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    test_num_items = 3
    packet_len = SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS["well_statuses"][0].shape[1]
    for packet_num in range(test_num_items):
        test_packet = copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
        start = packet_num * packet_len
        for well_idx in range(24):
            test_packet["well_statuses"][well_idx][0] = np.arange(start, start + packet_len, dtype=np.uint64)
        board_queues[board_idx][0].put_nowait(test_packet)
    confirm_queue_is_eventually_of_size(board_queues[board_idx][0], test_num_items)
    invoke_process_run_and_check_errors(file_writer_process, num_iterations=test_num_items - 1)

    for well_idx in range(24):
        well_buffers = test_stim_buffers[well_idx]
        assert len(well_buffers[0]) == (test_num_items - 1) * packet_len, well_idx
        assert len(well_buffers[1]) == (test_num_items - 1) * packet_len, well_idx

    # send stop managed acquisition command to clear data buffer and set stop timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        STOP_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)
    # send a data packet from the end of the stream and make sure it is not added to buffer
    invoke_process_run_and_check_errors(file_writer_process)
    for well_idx in range(24):
        well_buffers = test_stim_buffers[well_idx]
        assert len(well_buffers[0]) == 0, well_idx
        assert len(well_buffers[1]) == 0, well_idx

    # Tanner (6/19/21): prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


def test_FileWriterProcess__clears_leftover_stim_data_of_previous_stream_from_buffer_when_receiving_first_packet_of_new_stream(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()

    board_idx = 0
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    board_queues = four_board_file_writer_process["board_queues"][board_idx]

    test_stim_buffers = file_writer_process.get_stim_data_buffers(board_idx)

    test_stim_info = dict(copy.deepcopy(GENERIC_STIM_INFO))
    test_stim_info["protocol_assignments"] = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", "B"])
        for well_idx in range(24)
    }

    expected_stim_info, *chunk_info = chunk_protocols_in_stim_info(test_stim_info)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": chunk_info[0],
        "max_subprotocol_idx_counts": chunk_info[1],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    # load stim data into buffer
    test_num_items = 4
    for _ in range(test_num_items):
        board_queues[0].put_nowait(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
    confirm_queue_is_eventually_of_size(board_queues[0], test_num_items)
    invoke_process_run_and_check_errors(file_writer_process, num_iterations=test_num_items)
    packet_len = SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS["well_statuses"][0].shape[1]
    for well_idx in range(24):
        well_buffers = test_stim_buffers[well_idx]
        assert len(well_buffers[0]) == test_num_items * packet_len, well_idx
        assert len(well_buffers[1]) == test_num_items * packet_len, well_idx

    # send packet from new stream to clear old data from buffer
    first_packet_of_new_stream = copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
    first_packet_of_new_stream["is_first_packet_of_stream"] = True
    board_queues[0].put_nowait(first_packet_of_new_stream)
    confirm_queue_is_eventually_of_size(board_queues[0], 1)
    invoke_process_run_and_check_errors(file_writer_process)
    for well_idx in range(24):
        well_buffers = test_stim_buffers[well_idx]
        assert len(well_buffers[0]) == packet_len, well_idx
        assert len(well_buffers[1]) == packet_len, well_idx

    # clean up
    drain_queue(board_queues[1])


def test_FileWriterProcess__removes_stim_statuses_from_buffer_that_are_no_longer_relevant_to_data_in_magnetometer_data_buffer(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    test_stim_buffers = file_writer_process.get_stim_data_buffers(board_idx)

    test_packet = copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
    test_time_indices = np.arange(
        1, FILE_WRITER_BUFFER_SIZE_MICROSECONDS * 2 + 1, MICRO_TO_BASE_CONVERSION, dtype=np.int64
    )
    for well_idx in range(24):
        test_packet["well_statuses"][well_idx] = np.array(
            [test_time_indices, np.zeros(len(test_time_indices))], dtype=np.int64
        )
    file_writer_process.append_to_stim_data_buffers(test_packet["well_statuses"])

    magnetometer_packet_1 = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    magnetometer_packet_1["time_indices"] = np.array([0], dtype=np.uint64)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(magnetometer_packet_1, board_queues[0])
    invoke_process_run_and_check_errors(file_writer_process)
    for well_idx in range(24):
        well_buffers = test_stim_buffers[well_idx]
        assert len(well_buffers[0]) == len(test_time_indices), well_idx
        assert len(well_buffers[1]) == len(test_time_indices), well_idx

    start_time_index = FILE_WRITER_BUFFER_SIZE_MICROSECONDS + 1
    magnetometer_packet_2 = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    magnetometer_packet_2["time_indices"] = np.array(
        [start_time_index, start_time_index + FILE_WRITER_BUFFER_SIZE_MICROSECONDS], dtype=np.uint64
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(magnetometer_packet_2, board_queues[0])
    invoke_process_run_and_check_errors(file_writer_process)
    for well_idx in range(24):
        well_buffers = test_stim_buffers[well_idx]
        assert len(well_buffers[0]) == len(test_time_indices) // 2, well_idx
        assert len(well_buffers[1]) == len(test_time_indices) // 2, well_idx


def test_FileWriterProcess__records_all_relevant_stim_statuses_in_buffer_when_start_recording_command_is_received(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    populate_calibration_folder(file_writer_process)
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    test_stim_info = dict(copy.deepcopy(GENERIC_STIM_INFO))
    test_stim_info["protocol_assignments"] = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", "B"])
        for well_idx in range(24)
    }

    expected_stim_info, *chunk_info = chunk_protocols_in_stim_info(test_stim_info)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": chunk_info[0],
        "max_subprotocol_idx_counts": chunk_info[1],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    # dummy packets that will be ignored
    for _ in range(2):
        file_writer_process.append_to_stim_data_buffers(
            SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS["well_statuses"]
        )
    # set up test data packets and add to incoming data queue
    expected_start_timepoint = 100
    expected_num_packets_recorded = 3
    num_data_points_per_packet = 2
    expected_total_num_data_points = expected_num_packets_recorded * num_data_points_per_packet
    expected_time_indices = np.arange(
        expected_start_timepoint - 1,
        expected_start_timepoint - 1 + (expected_total_num_data_points * 2),
        2,
        dtype=np.uint64,
    )
    for i in range(expected_num_packets_recorded):
        test_packet = copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)

        curr_idx = i * num_data_points_per_packet
        test_data = np.array(
            [
                expected_time_indices[curr_idx : curr_idx + num_data_points_per_packet],
                np.zeros(num_data_points_per_packet, dtype=np.int64),
            ],
            dtype=np.int64,
        )
        test_packet["well_statuses"] = {well_idx: test_data for well_idx in range(24)}
        file_writer_process.append_to_stim_data_buffers(test_packet["well_statuses"])

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = expected_start_timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    expected_stim_data = np.array(
        [expected_time_indices, np.zeros(expected_total_num_data_points, dtype=np.int64)],
        dtype=np.int64,
    )

    expected_plate_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"
    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        this_file = h5py.File(
            os.path.join(
                four_board_file_writer_process["file_dir"],
                f"{expected_plate_barcode}__{timestamp_str}",
                f"{expected_plate_barcode}__{timestamp_str}__{well_name}.h5",
            ),
            "r",
        )
        stimulation_dataset = get_stimulation_dataset_from_file(this_file)
        assert stimulation_dataset.dtype == "int64", f"Incorrect time index dtype for well {well_idx}"
        assert stimulation_dataset.shape == (
            2,
            expected_total_num_data_points,
        ), f"Incorrect stim data shape for well {well_idx}"
        np.testing.assert_array_equal(
            stimulation_dataset,
            expected_stim_data,
            err_msg=f"Incorrect stimulation data for well {well_idx}",
        )

        this_file.close()


def test_FileWriterProcess__deletes_recorded_beta_1_well_data_after_stop_time(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    instrument_board_queues = four_board_file_writer_process["board_queues"]
    comm_from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    expected_well_indices = [0, 1, 23]
    start_recording_command = dict(GENERIC_BETA_1_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    start_recording_command["active_well_indices"] = expected_well_indices
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command,
        comm_from_main_queue,
    )

    invoke_process_run_and_check_errors(file_writer_process)

    expected_stop_timepoint = 100
    expected_remaining_packets_recorded = 3
    dummy_packets = 2
    expected_dataset = list(range(expected_remaining_packets_recorded))
    for well_idx in expected_well_indices:
        for i in range(expected_remaining_packets_recorded):
            data_packet = {
                "is_reference_sensor": False,
                "well_index": well_idx,
                "data": np.array([[i], [i]], dtype=np.int32),
            }
            instrument_board_queues[0][0].put_nowait(data_packet)
        for i in range(dummy_packets):
            data_packet = {
                "is_reference_sensor": False,
                "well_index": well_idx,
                "data": np.array(
                    [[expected_stop_timepoint + ((i + 1) * ROUND_ROBIN_PERIOD)], [0]],
                    dtype=np.int32,
                ),
            }
            instrument_board_queues[0][0].put_nowait(data_packet)
        confirm_queue_is_eventually_of_size(
            instrument_board_queues[0][0],
            expected_remaining_packets_recorded + dummy_packets,
        )
        invoke_process_run_and_check_errors(
            file_writer_process,
            num_iterations=(expected_remaining_packets_recorded + dummy_packets)
            * 2,  # Tanner (8/19/12): queues items are processed more reliably if running the process more iterations than needed
        )

    stop_recording_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    stop_recording_command["timepoint_to_stop_recording_at"] = expected_stop_timepoint
    # ensure queue is empty before putting something else in
    confirm_queue_is_eventually_empty(comm_from_main_queue)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command,
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_plate_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"

    for well_idx in expected_well_indices:
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        this_file = h5py.File(
            os.path.join(
                file_dir,
                f"{expected_plate_barcode}__{timestamp_str}",
                f"{expected_plate_barcode}__{timestamp_str}__{well_name}.h5",
            ),
            "r",
        )
        tissue_dataset = get_tissue_dataset_from_file(this_file)
        assert tissue_dataset.shape == (expected_remaining_packets_recorded,), well_idx
        assert tissue_dataset.dtype == "int32", well_idx
        np.testing.assert_equal(tissue_dataset, np.array(expected_dataset), err_msg=f"{well_idx}")


def test_FileWriterProcess__deletes_recorded_beta_2_well_data_after_stop_time(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    populate_calibration_folder(file_writer_process)
    instrument_board_queues = four_board_file_writer_process["board_queues"]
    comm_from_main_queue = four_board_file_writer_process["from_main_queue"]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command,
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_stop_timepoint = 100
    expected_remaining_packets_recorded = 3
    num_data_points_per_packet = 4
    expected_total_num_data_points = expected_remaining_packets_recorded * num_data_points_per_packet
    base_data = np.zeros(num_data_points_per_packet, dtype=np.uint16)
    base_time_offsets = np.zeros(
        (SERIAL_COMM_NUM_SENSORS_PER_WELL, num_data_points_per_packet), dtype=np.uint16
    )
    expected_time_indices = np.arange(expected_total_num_data_points, dtype=np.uint64)
    # add packets whose data will remain in the file
    for i in range(expected_remaining_packets_recorded):
        curr_idx = i * num_data_points_per_packet
        data_packet = {
            "data_type": "magnetometer",
            "time_indices": expected_time_indices[curr_idx : curr_idx + num_data_points_per_packet],
            "is_first_packet_of_stream": False,
        }
        for well_idx in range(24):
            channel_dict = {"time_offsets": base_time_offsets + well_idx}
            channel_dict.update(
                {channel_idx: base_data + well_idx for channel_idx in range(SERIAL_COMM_NUM_DATA_CHANNELS)}
            )
            data_packet[well_idx] = channel_dict
        instrument_board_queues[0][0].put_nowait(data_packet)
    # add packets whose data will later be removed from the file
    num_dummy_packets = 2
    for i in range(num_dummy_packets):
        first_timepoint = expected_stop_timepoint + 1 + (i * num_data_points_per_packet)
        data_packet = {
            "data_type": "magnetometer",
            "time_indices": np.arange(
                first_timepoint, first_timepoint + num_data_points_per_packet, dtype=np.uint64
            ),
            "is_first_packet_of_stream": False,
        }
        for well_idx in range(24):
            channel_dict = {"time_offsets": base_time_offsets}
            channel_dict.update(
                {channel_idx: base_data * well_idx for channel_idx in range(SERIAL_COMM_NUM_DATA_CHANNELS)}
            )
            data_packet[well_idx] = channel_dict
        instrument_board_queues[0][0].put_nowait(data_packet)
    # process all packets
    confirm_queue_is_eventually_of_size(
        instrument_board_queues[0][0], expected_remaining_packets_recorded + num_dummy_packets
    )
    invoke_process_run_and_check_errors(
        file_writer_process, num_iterations=(expected_remaining_packets_recorded + num_dummy_packets)
    )
    confirm_queue_is_eventually_empty(instrument_board_queues[0][0])

    # send stop recording command
    stop_recording_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    stop_recording_command["timepoint_to_stop_recording_at"] = expected_stop_timepoint
    # ensure queue is empty before putting something else in
    confirm_queue_is_eventually_empty(comm_from_main_queue)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command, comm_from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_plate_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"

    expected_time_offsets_shape = (SERIAL_COMM_NUM_SENSORS_PER_WELL, expected_total_num_data_points)
    expected_data_shape = (SERIAL_COMM_NUM_DATA_CHANNELS, expected_total_num_data_points)
    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        this_file = h5py.File(
            os.path.join(
                four_board_file_writer_process["file_dir"],
                f"{expected_plate_barcode}__{timestamp_str}",
                f"{expected_plate_barcode}__{timestamp_str}__{well_name}.h5",
            ),
            "r",
        )
        time_index_dataset = get_time_index_dataset_from_file(this_file)
        assert time_index_dataset.dtype == "uint64", f"Incorrect time index dtype for well {well_idx}"
        assert time_index_dataset.shape == (
            expected_total_num_data_points,
        ), f"Incorrect time index shape for well {well_idx}"
        np.testing.assert_array_equal(
            time_index_dataset,
            expected_time_indices,
            err_msg=f"Incorrect time index data for well {well_idx}",
        )

        time_offset_dataset = get_time_offset_dataset_from_file(this_file)
        assert time_offset_dataset.dtype == "uint16", f"Incorrect offset dtype for well {well_idx}"
        assert (
            time_offset_dataset.shape == expected_time_offsets_shape
        ), f"Incorrect offset shape for well {well_idx}"
        np.testing.assert_array_equal(
            time_offset_dataset,
            np.ones(expected_time_offsets_shape, dtype=np.uint16) * well_idx,
            err_msg=f"Incorrect offsets for well {well_idx}",
        )

        tissue_dataset = get_tissue_dataset_from_file(this_file)
        assert tissue_dataset.dtype == "uint16", f"Incorrect tissue dtype for well {well_idx}"
        assert tissue_dataset.shape == expected_data_shape, f"Incorrect tissue shape for well {well_idx}"
        np.testing.assert_array_equal(
            tissue_dataset,
            np.ones(expected_data_shape, dtype=np.uint16) * well_idx,
            err_msg=f"Incorrect tissue data for well {well_idx}",
        )

        this_file.close()


def test_FileWriterProcess__deletes_recorded_reference_data_after_stop_time(
    four_board_file_writer_process,
):
    # TODO Tanner (5/17/21): when reference sensors are added to the Beta 2 instrument, add beta 2 mode to this test
    file_writer_process = four_board_file_writer_process["fw_process"]
    instrument_board_queues = four_board_file_writer_process["board_queues"]
    comm_from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    expected_well_idx = 0
    start_recording_command = dict(GENERIC_BETA_1_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    start_recording_command["active_well_indices"] = [expected_well_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command, comm_from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_stop_timepoint = 100
    expected_remaining_packets_recorded = 3
    expected_dataset = []
    for i in range(expected_remaining_packets_recorded):
        expected_dataset.append(i)
        data_packet = {
            "is_reference_sensor": True,
            "reference_for_wells": set([0, 1, 4, 5]),
            "data": np.array([[i], [i]], dtype=np.int32),
        }
        instrument_board_queues[0][0].put_nowait(data_packet)
    dummy_packets = 2
    for i in range(dummy_packets):
        data_packet = {
            "is_reference_sensor": True,
            "reference_for_wells": set([0, 1, 4, 5]),
            "data": np.array(
                [[expected_stop_timepoint + ((i + 1) * ROUND_ROBIN_PERIOD)], [0]],
                dtype=np.int32,
            ),
        }
        instrument_board_queues[0][0].put_nowait(data_packet)
    confirm_queue_is_eventually_of_size(
        instrument_board_queues[0][0],
        expected_remaining_packets_recorded + dummy_packets,
        timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )
    invoke_process_run_and_check_errors(
        file_writer_process,
        num_iterations=(expected_remaining_packets_recorded + dummy_packets),
    )

    stop_recording_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    stop_recording_command["timepoint_to_stop_recording_at"] = expected_stop_timepoint
    # confirm the queue is empty before adding another command
    confirm_queue_is_eventually_empty(comm_from_main_queue)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command, comm_from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_plate_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"

    this_file = h5py.File(
        os.path.join(
            file_dir,
            f"{expected_plate_barcode}__{timestamp_str}",
            f"{expected_plate_barcode}__{timestamp_str}__{GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(expected_well_idx)}.h5",
        ),
        "r",
    )
    ref_dataset = get_reference_dataset_from_file(this_file)
    assert ref_dataset.shape == (expected_remaining_packets_recorded,)
    assert ref_dataset.dtype == "int32"
    np.testing.assert_equal(ref_dataset, np.array(expected_dataset))


def test_FileWriterProcess__raises_error_if_stop_recording_command_received_with_stop_timepoint_less_than_earliest_timepoint(
    four_board_file_writer_process, patch_print
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    populate_calibration_folder(file_writer_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    test_well_index = 6
    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [test_well_index]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command,
        from_main_queue,
    )
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    recorded_data_packet = {
        "data_type": "magnetometer",
        "time_indices": np.array([start_timepoint], dtype=np.uint64),
        "is_first_packet_of_stream": False,
        test_well_index: {
            "time_offsets": np.array([[0], [0]], dtype=np.uint16),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: np.array([0], dtype=np.uint16),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: np.array([0], dtype=np.int16),
        },
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        recorded_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    stop_recording_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    stop_recording_command["timepoint_to_stop_recording_at"] = start_timepoint - 1
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command,
        from_main_queue,
    )
    with pytest.raises(
        InvalidStopRecordingTimepointError,
        match=str(stop_recording_command["timepoint_to_stop_recording_at"]),
    ):
        invoke_process_run_and_check_errors(file_writer_process)


def test_FileWriterProcess__deletes_recorded_stim_data_after_stop_time(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    populate_calibration_folder(file_writer_process)

    board_idx = 0
    instrument_board_queues = four_board_file_writer_process["board_queues"][board_idx]
    comm_from_main_queue = four_board_file_writer_process["from_main_queue"]

    test_stim_info = dict(copy.deepcopy(GENERIC_STIM_INFO))
    test_stim_info["protocol_assignments"] = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", "B"])
        for well_idx in range(24)
    }

    expected_stim_info, *chunk_info = chunk_protocols_in_stim_info(test_stim_info)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": chunk_info[0],
        "max_subprotocol_idx_counts": chunk_info[1],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        set_protocols_command, comm_from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command,
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_stop_timepoint = 100
    expected_remaining_packets_recorded = 4
    num_data_points_per_packet = 3
    expected_total_num_data_points = expected_remaining_packets_recorded * num_data_points_per_packet
    expected_time_indices = np.arange(expected_total_num_data_points, dtype=np.uint64)
    # add packets whose data will remain in the file
    for i in range(expected_remaining_packets_recorded):
        test_packet = copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
        curr_idx = i * num_data_points_per_packet
        test_data = np.array(
            [
                expected_time_indices[curr_idx : curr_idx + num_data_points_per_packet],
                np.zeros(num_data_points_per_packet, dtype=np.int64),
            ],
            dtype=np.int64,
        )
        test_packet["well_statuses"] = {well_idx: test_data for well_idx in range(24)}
        instrument_board_queues[0].put_nowait(test_packet)
    # add packets whose data will later be removed from the file
    num_dummy_packets = 2
    for i in range(num_dummy_packets):
        test_packet = copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
        first_timepoint = expected_stop_timepoint + 1 + (i * num_data_points_per_packet)
        test_data = np.array(
            [
                np.arange(first_timepoint, first_timepoint + num_data_points_per_packet, dtype=np.uint64),
                np.zeros(num_data_points_per_packet, dtype=np.int64),
            ],
            dtype=np.int64,
        )
        test_packet["well_statuses"] = {well_idx: test_data for well_idx in range(24)}
        instrument_board_queues[0].put_nowait(test_packet)
    # process all packets
    confirm_queue_is_eventually_of_size(
        instrument_board_queues[0], expected_remaining_packets_recorded + num_dummy_packets
    )
    invoke_process_run_and_check_errors(
        file_writer_process, num_iterations=(expected_remaining_packets_recorded + num_dummy_packets)
    )
    confirm_queue_is_eventually_empty(instrument_board_queues[0])

    # add some magnetometer data so errors aren't raised
    test_magnetometer_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    num_time_indices = len(test_magnetometer_packet["time_indices"])
    test_magnetometer_packet["time_indices"] = np.arange(
        expected_stop_timepoint - 1, expected_stop_timepoint - 1 + num_time_indices, dtype=np.uint64
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_magnetometer_packet, instrument_board_queues[0]
    )
    invoke_process_run_and_check_errors(file_writer_process)

    # send stop recording command
    stop_recording_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    stop_recording_command["timepoint_to_stop_recording_at"] = expected_stop_timepoint
    # ensure queue is empty before putting something else in
    confirm_queue_is_eventually_empty(comm_from_main_queue)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command, comm_from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_stim_data = np.array(
        [expected_time_indices, np.zeros(expected_total_num_data_points, dtype=np.int64)],
        dtype=np.int64,
    )

    expected_plate_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"
    for well_idx in range(24):
        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        with h5py.File(
            os.path.join(
                four_board_file_writer_process["file_dir"],
                f"{expected_plate_barcode}__{timestamp_str}",
                f"{expected_plate_barcode}__{timestamp_str}__{well_name}.h5",
            ),
            "r",
        ) as this_file:
            stimulation_dataset = get_stimulation_dataset_from_file(this_file)
            assert stimulation_dataset.dtype == "int64", f"Incorrect time index dtype for well {well_idx}"
            assert stimulation_dataset.shape == (
                2,
                expected_total_num_data_points,
            ), f"Incorrect stim data shape for well {well_idx}"
            np.testing.assert_array_equal(
                stimulation_dataset,
                expected_stim_data,
                err_msg=f"Incorrect stimulation data for well {well_idx}",
            )


def test_FileWriterProcess__stop_recording__immediately_finalizes_any_beta_1_files_that_are_ready(
    four_board_file_writer_process,
):
    test_well_indices = [3, 7, 15]

    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"].update(
        {"auto_delete_local_files": False, "auto_upload_on_completion": True}
    )
    create_and_close_beta_1_h5_files(
        four_board_file_writer_process,
        update_user_settings_command,
        active_well_indices=test_well_indices,
    )


def test_FileWriterProcess__stop_recording__immediately_finalizes_all_beta_2_files_if_ready(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    # store new customer settings
    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"].update(
        {"auto_delete_local_files": False, "auto_upload_on_completion": True}
    )
    this_command = copy.deepcopy(update_user_settings_command)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # remove update settings command receipt

    # create calibration files
    populate_calibration_folder(fw_process)

    # start recording
    active_well_indices = list(range(24))
    start_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_command["timepoint_to_begin_recording_at"] = 0
    start_command["active_well_indices"] = active_well_indices
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # remove start recording command receipt

    # create data
    data_packet = create_simple_beta_2_data_packet(
        start_command["timepoint_to_begin_recording_at"],
        0,
        active_well_indices,
        10,
        is_first_packet_of_stream=True,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    # stop recording
    stop_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    stop_command["timepoint_to_stop_recording_at"] = data_packet["time_indices"][-1]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    # confirm each finalization message, all files finalized, and stop recording receipt are sent
    confirm_queue_is_eventually_of_size(to_main_queue, len(active_well_indices) + 2)


def test_FileWriterProcess__stop_managed_acquisition__finalizes_all_files_if_any_are_still_open(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    # store new customer settings
    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"].update(
        {"auto_delete_local_files": False, "auto_upload_on_completion": True}
    )
    this_command = copy.deepcopy(update_user_settings_command)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # remove update settings command receipt

    # create calibration files
    populate_calibration_folder(fw_process)

    # start recording
    active_well_indices = list(range(24))
    start_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_command["timepoint_to_begin_recording_at"] = 0
    start_command["active_well_indices"] = active_well_indices
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # remove start recording command receipt

    # create data
    data_packet = create_simple_beta_2_data_packet(
        start_command["timepoint_to_begin_recording_at"],
        0,
        active_well_indices,
        10,
        is_first_packet_of_stream=True,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    # stop managed acquisition
    stop_command = dict(STOP_MANAGED_ACQUISITION_COMMUNICATION)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    # confirm each finalization message, all files finalized, and stop recording receipt are sent
    confirm_queue_is_eventually_of_size(to_main_queue, len(active_well_indices) + 2)
