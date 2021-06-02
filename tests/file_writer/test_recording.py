# -*- coding: utf-8 -*-
import copy
import json
import os

import h5py
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import create_sensor_axis_dict
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import get_reference_dataset_from_file
from mantarray_desktop_app import get_time_index_dataset_from_file
from mantarray_desktop_app import get_time_offset_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import InvalidStopRecordingTimepointError
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_file_manager import ADC_GAIN_SETTING_UUID
from mantarray_file_manager import ADC_REF_OFFSET_UUID
from mantarray_file_manager import ADC_TISSUE_OFFSET_UUID
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import BOOTUP_COUNTER_UUID
from mantarray_file_manager import COMPUTER_NAME_HASH_UUID
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import FILE_FORMAT_VERSION_METADATA_KEY
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import IS_FILE_ORIGINAL_UNTRIMMED_UUID
from mantarray_file_manager import MAGNETOMETER_CONFIGURATION_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import METADATA_UUID_DESCRIPTIONS
from mantarray_file_manager import ORIGINAL_FILE_VERSION_UUID
from mantarray_file_manager import PCB_SERIAL_NUMBER_UUID
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import REF_SAMPLING_PERIOD_UUID
from mantarray_file_manager import REFERENCE_VOLTAGE_UUID
from mantarray_file_manager import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_file_manager import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
from mantarray_file_manager import TAMPER_FLAG_UUID
from mantarray_file_manager import TISSUE_SAMPLING_PERIOD_UUID
from mantarray_file_manager import TOTAL_WELL_COUNT_UUID
from mantarray_file_manager import TOTAL_WORKING_HOURS_UUID
from mantarray_file_manager import TRIMMED_TIME_FROM_ORIGINAL_END_UUID
from mantarray_file_manager import TRIMMED_TIME_FROM_ORIGINAL_START_UUID
from mantarray_file_manager import USER_ACCOUNT_ID_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_BEGINNING_RECORDING_UUID
from mantarray_file_manager import WELL_COLUMN_UUID
from mantarray_file_manager import WELL_INDEX_UUID
from mantarray_file_manager import WELL_NAME_UUID
from mantarray_file_manager import WELL_ROW_UUID
from mantarray_file_manager import XEM_SERIAL_NUMBER_UUID
import numpy as np
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import validate_file_head_crc32

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import fixture_running_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_BETA_1_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_NUM_CHANNELS_ENABLED
from ..fixtures_file_writer import GENERIC_NUM_SENSORS_ENABLED
from ..fixtures_file_writer import GENERIC_REFERENCE_SENSOR_DATA_PACKET
from ..fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_TISSUE_DATA_PACKET
from ..fixtures_file_writer import open_the_generic_h5_file
from ..fixtures_file_writer import WELL_DEF_24
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..parsed_channel_data_packets import SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0
from ..parsed_channel_data_packets import SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS


__fixtures__ = [
    fixture_four_board_file_writer_process,
    fixture_running_four_board_file_writer_process,
    fixture_patch_print,
]


@pytest.mark.timeout(6)
@pytest.mark.parametrize(
    "test_beta_version,test_description",
    [
        (1, "beta 1 mode"),
        (2, "beta 2 mode"),
    ],
)
def test_FileWriterProcess__creates_24_files_named_with_timestamp_barcode_well_index__and_supplied_metadata__set_to_swmr_mode__when_receiving_communication_to_start_recording(
    test_beta_version,
    test_description,
    four_board_file_writer_process,
):
    # Creating 24 files takes a few seconds, so also test that all the metadata and other things are set during this single test
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    # set up expected values
    if test_beta_version == 2:
        file_writer_process.set_beta_2_mode()
    start_recording_command = (
        GENERIC_BETA_1_START_RECORDING_COMMAND
        if test_beta_version == 1
        else GENERIC_BETA_2_START_RECORDING_COMMAND
    )
    data_shape = (0,) if test_beta_version == 1 else (GENERIC_NUM_CHANNELS_ENABLED, 0)
    data_type = np.int32 if test_beta_version == 1 else np.int16
    simulator_class = RunningFIFOSimulator if test_beta_version == 1 else MantarrayMcSimulator
    file_version = (
        CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
        if test_beta_version == 1
        else CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
    )

    timestamp_str = "2020_02_09_190935" if test_beta_version == 1 else "2020_02_09_190359"
    expected_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    actual_set_of_files = set(os.listdir(os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}")))
    assert len(actual_set_of_files) == 24

    expected_set_of_files = set()
    for row_idx in range(4):
        for col_idx in range(6):
            expected_set_of_files.add(
                f"{expected_barcode}__{timestamp_str}__{WELL_DEF_24.get_well_name_from_row_and_column(row_idx, col_idx)}.h5"
            )
    assert actual_set_of_files == expected_set_of_files

    for this_well_idx in range(24):
        # Eli (2/9/20) can't figure out a more elegant way to test this than accessing the private instance variable.  If you open a file using the :code:`swmr=True` kwarg and the file isn't being written that way, no error is raised, and asserting f.swmr_mode is True on the file being read doesn't work (always returns what the kwarg was set as during opening for reading)
        open_files = file_writer_process._open_files  # pylint: disable=protected-access
        this_file_being_written_to = open_files[0][this_well_idx]
        assert this_file_being_written_to.swmr_mode is True

    for well_idx in range(24):
        row_idx, col_idx = WELL_DEF_24.get_row_and_column_from_well_index(well_idx)

        this_file = h5py.File(
            os.path.join(
                file_dir,
                f"{expected_barcode}__{timestamp_str}",
                f"{expected_barcode}__{timestamp_str}__{WELL_DEF_24.get_well_name_from_well_index(well_idx)}.h5",
            ),
            "r",
        )
        # test metadata present in both beta versions
        assert this_file.attrs[str(ORIGINAL_FILE_VERSION_UUID)] == file_version
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
        assert this_file.attrs[str(CUSTOMER_ACCOUNT_ID_UUID)] == str(CURI_BIO_ACCOUNT_UUID)
        assert this_file.attrs[str(USER_ACCOUNT_ID_UUID)] == str(CURI_BIO_USER_ACCOUNT_ID)
        actual_build_id = this_file.attrs[str(SOFTWARE_BUILD_NUMBER_UUID)]
        assert actual_build_id == COMPILED_EXE_BUILD_TIMESTAMP
        assert this_file.attrs[str(SOFTWARE_RELEASE_VERSION_UUID)] == CURRENT_SOFTWARE_VERSION
        assert this_file.attrs[str(MAIN_FIRMWARE_VERSION_UUID)] == simulator_class.default_firmware_version
        assert this_file.attrs[str(MANTARRAY_NICKNAME_UUID)] == simulator_class.default_mantarray_nickname
        assert (
            this_file.attrs[str(MANTARRAY_SERIAL_NUMBER_UUID)]
            == simulator_class.default_mantarray_serial_number
        )

        assert this_file.attrs["Metadata UUID Descriptions"] == json.dumps(str(METADATA_UUID_DESCRIPTIONS))
        assert (
            this_file.attrs[str(WELL_NAME_UUID)] == f"{WELL_DEF_24.get_well_name_from_well_index(well_idx)}"
        )
        assert this_file.attrs[str(WELL_ROW_UUID)] == row_idx
        assert this_file.attrs[str(WELL_COLUMN_UUID)] == col_idx
        assert this_file.attrs[str(WELL_INDEX_UUID)] == WELL_DEF_24.get_well_index_from_row_and_column(
            row_idx, col_idx
        )
        assert this_file.attrs[str(TOTAL_WELL_COUNT_UUID)] == 24
        assert bool(this_file.attrs[str(IS_FILE_ORIGINAL_UNTRIMMED_UUID)]) is True
        assert this_file.attrs[str(TRIMMED_TIME_FROM_ORIGINAL_START_UUID)] == 0
        assert this_file.attrs[str(TRIMMED_TIME_FROM_ORIGINAL_END_UUID)] == 0
        assert (
            this_file.attrs[str(COMPUTER_NAME_HASH_UUID)]
            == start_recording_command["metadata_to_copy_onto_main_file_attributes"][COMPUTER_NAME_HASH_UUID]
        )
        assert (
            bool(this_file.attrs[str(BARCODE_IS_FROM_SCANNER_UUID)])
            is start_recording_command["metadata_to_copy_onto_main_file_attributes"][
                BARCODE_IS_FROM_SCANNER_UUID
            ]
        )
        # test metadata values and datasets not present in both beta versions
        if test_beta_version == 1:
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
            well_config = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
                MAGNETOMETER_CONFIGURATION_UUID
            ][SERIAL_COMM_WELL_IDX_TO_MODULE_ID[well_idx]]
            assert this_file.attrs[str(MAGNETOMETER_CONFIGURATION_UUID)] == json.dumps(
                create_sensor_axis_dict(well_config)
            )
            assert (
                this_file.attrs[str(TISSUE_SAMPLING_PERIOD_UUID)]
                == start_recording_command["metadata_to_copy_onto_main_file_attributes"][
                    TISSUE_SAMPLING_PERIOD_UUID
                ]
            )
            assert (
                this_file.attrs[str(BOOTUP_COUNTER_UUID)]
                == MantarrayMcSimulator.default_metadata_values[BOOTUP_COUNTER_UUID]
            )
            assert (
                this_file.attrs[str(TOTAL_WORKING_HOURS_UUID)]
                == MantarrayMcSimulator.default_metadata_values[TOTAL_WORKING_HOURS_UUID]
            )
            assert (
                this_file.attrs[str(TAMPER_FLAG_UUID)]
                == MantarrayMcSimulator.default_metadata_values[TAMPER_FLAG_UUID]
            )
            assert (
                this_file.attrs[str(PCB_SERIAL_NUMBER_UUID)] == MantarrayMcSimulator.default_pcb_serial_number
            )
            assert get_time_index_dataset_from_file(this_file).shape == (0,)
            assert get_time_index_dataset_from_file(this_file).dtype == "uint64"
            assert get_time_offset_dataset_from_file(this_file).shape == (GENERIC_NUM_SENSORS_ENABLED, 0)
            assert get_time_offset_dataset_from_file(this_file).dtype == "uint16"
        # test data sets
        assert get_reference_dataset_from_file(this_file).shape == data_shape
        assert get_reference_dataset_from_file(this_file).dtype == data_type
        assert get_tissue_dataset_from_file(this_file).shape == data_shape
        assert get_tissue_dataset_from_file(this_file).dtype == data_type


@pytest.mark.timeout(4)
def test_FileWriterProcess__only_creates_file_indices_specified__when_receiving_communication_to_start_recording__and_reports_command_receipt_to_main(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    spied_abspath = mocker.spy(os.path, "abspath")

    timestamp_str = "2020_02_09_190935"
    expected_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    this_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [3, 18]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)
    actual_set_of_files = set(os.listdir(os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}")))
    assert len(actual_set_of_files) == 2

    expected_set_of_files = set(
        [
            f"{expected_barcode}__{timestamp_str}__D1.h5",
            f"{expected_barcode}__{timestamp_str}__C5.h5",
        ]
    )
    assert actual_set_of_files == expected_set_of_files
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    comm_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert comm_to_main["communication_type"] == "command_receipt"
    assert comm_to_main["command"] == "start_recording"
    assert (
        "mp" in comm_to_main["file_folder"]
    )  # cross platform way of checking for 'temp' being part of the file path
    assert expected_barcode in comm_to_main["file_folder"]
    spied_abspath.assert_any_call(
        file_writer_process.get_file_directory()
    )  # Eli (3/16/20): apparently numpy calls this quite frequently, so can only assert_any_call, not assert_called_once_with
    isinstance(comm_to_main["timepoint_to_begin_recording_at"], int)


def test_FileWriterProcess__start_recording__sets_stop_recording_timestamp_to_none__and_tissue_and_reference_finalization_status_to_false__and_is_recording_to_true(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    this_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
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
    this_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
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
    this_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    this_command["timepoint_to_stop_recording_at"] = stop_timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    assert stop_timestamps[0] == stop_timepoint

    confirm_queue_is_eventually_of_size(to_main_queue, 2, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS)
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

    this_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
    this_command[
        "timepoint_to_begin_recording_at"
    ] = 3760000  # Tanner (1/13/21): This can be any arbitrary timepoint after the timepoint of the last data packet sent
    this_command["active_well_indices"] = [expected_well_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)
    assert stop_timestamps[0] is None

    tissue_status, _ = file_writer_process.get_recording_finalization_statuses()
    assert tissue_status[0][expected_well_idx] is False


def test_FileWriterProcess__closes_the_files_and_adds_crc32_checksum_and_sends_communication_to_main_when_all_data_has_been_added_after_recording_stopped(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    spied_h5_close = mocker.spy(
        h5py._hl.files.File,  # pylint:disable=protected-access # this is the only known (Eli 2/27/20) way to access the appropriate type definition
        "close",
    )

    start_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
    start_command["active_well_indices"] = [4, 5]
    num_data_points = 10
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)

    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_idx in range(num_data_points):
        data[0, this_idx] = (
            start_command["timepoint_to_begin_recording_at"] + this_idx * REFERENCE_SENSOR_SAMPLING_PERIOD
        )
        data[1, this_idx] = this_idx * 2

    this_data_packet = copy.deepcopy(GENERIC_REFERENCE_SENSOR_DATA_PACKET)
    this_data_packet["data"] = data
    queue_to_file_writer_from_board_0 = board_queues[0][0]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        queue_to_file_writer_from_board_0,
    )

    # tissue data
    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_idx in range(num_data_points):
        data[0, this_idx] = (
            start_command["timepoint_to_begin_recording_at"]
            + this_idx * CONSTRUCT_SENSOR_SAMPLING_PERIOD
            + DATA_FRAME_PERIOD
        )
        data[1, this_idx] = this_idx * 2

    this_data_packet = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    this_data_packet["data"] = data

    board_queues[0][0].put_nowait(this_data_packet)
    data_packet_for_5 = copy.deepcopy(this_data_packet)
    data_packet_for_5["well_index"] = 5
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        data_packet_for_5,
        board_queues[0][0],
    )

    invoke_process_run_and_check_errors(file_writer_process, num_iterations=3)

    actual_file = open_the_generic_h5_file(file_dir)
    # confirm some data already recorded to file
    actual_data = get_reference_dataset_from_file(actual_file)
    assert actual_data.shape == (10,)
    assert actual_data[4] == 8
    assert actual_data[8] == 16

    actual_data = get_tissue_dataset_from_file(actual_file)
    assert actual_data.shape == (10,)
    assert actual_data[3] == 6
    assert actual_data[9] == 18

    stop_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)

    # reference data
    reference_data_packet_after_stop = copy.deepcopy(GENERIC_REFERENCE_SENSOR_DATA_PACKET)
    data_after_stop = np.zeros((2, num_data_points), dtype=np.int32)
    for this_idx in range(num_data_points):
        data_after_stop[0, this_idx] = (
            stop_command["timepoint_to_stop_recording_at"] + (this_idx - 5) * REFERENCE_SENSOR_SAMPLING_PERIOD
        )
        data_after_stop[1, this_idx] = this_idx * 5
    reference_data_packet_after_stop["data"] = data_after_stop

    board_queues[0][0].put_nowait(reference_data_packet_after_stop)

    # tissue data
    tissue_data_packet_after_stop = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    data_after_stop = np.zeros((2, num_data_points), dtype=np.int32)
    for this_idx in range(num_data_points):
        data_after_stop[0, this_idx] = (
            stop_command["timepoint_to_stop_recording_at"] + this_idx * CONSTRUCT_SENSOR_SAMPLING_PERIOD
        )
    tissue_data_packet_after_stop["data"] = data_after_stop
    board_queues[0][0].put_nowait(tissue_data_packet_after_stop)
    data_packet_for_5 = copy.deepcopy(tissue_data_packet_after_stop)
    data_packet_for_5["well_index"] = 5
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        data_packet_for_5,
        board_queues[0][0],
    )

    invoke_process_run_and_check_errors(file_writer_process, num_iterations=3)

    assert spied_h5_close.call_count == 2
    with open(actual_file.filename, "rb") as actual_file_buffer:
        validate_file_head_crc32(actual_file_buffer)

    to_main_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pop off the initial receipt of start command message
    to_main_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pop off the initial receipt of stop command message

    confirm_queue_is_eventually_of_size(to_main_queue, 2)
    first_comm_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert first_comm_to_main["communication_type"] == "file_finalized"
    assert "_A2" in first_comm_to_main["file_path"]

    second_comm_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert second_comm_to_main["communication_type"] == "file_finalized"
    assert "_B2" in second_comm_to_main["file_path"]


def test_FileWriterProcess__begins_building_data_buffer_when_managed_acquisition_starts(
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
        sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.

    invoke_process_run_and_check_errors(file_writer_process, num_iterations=expected_num_items)
    actual_num_items = len(file_writer_process._data_packet_buffers[0])  # pylint: disable=protected-access
    assert actual_num_items == expected_num_items


def test_FileWriterProcess__clears_leftover_beta_2_data_from_previous_data_stream_from_buffer_when_receiving_first_packet_of_new_stream(
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
        sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    invoke_process_run_and_check_errors(file_writer_process, num_iterations=expected_num_items)
    actual_num_items = len(file_writer_process._data_packet_buffers[0])  # pylint: disable=protected-access
    assert actual_num_items == expected_num_items

    # send packet from new stream to clear old data from buffer
    first_packet_of_new_stream = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    first_packet_of_new_stream["is_first_packet_of_stream"] = True
    board_queues[0][0].put_nowait(first_packet_of_new_stream)
    confirm_queue_is_eventually_of_size(
        board_queues[0][0],
        1,
        sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    invoke_process_run_and_check_errors(file_writer_process)
    actual_num_items = len(file_writer_process._data_packet_buffers[0])  # pylint: disable=protected-access
    assert actual_num_items == 1

    # clean up
    drain_queue(board_queues[0][1])


def test_FileWriterProcess__removes_beta_1_packets_from_data_buffer_that_are_older_than_buffer_memory_size(
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
    confirm_queue_is_eventually_of_size(
        board_queues[0][0], 2, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.

    invoke_process_run_and_check_errors(file_writer_process, num_iterations=2)
    data_packet_buffer = file_writer_process._data_packet_buffers[0]  # pylint: disable=protected-access
    assert len(data_packet_buffer) == 1
    assert data_packet_buffer[0]["is_reference_sensor"] is new_packet["is_reference_sensor"]
    assert data_packet_buffer[0]["well_index"] == new_packet["well_index"]
    np.testing.assert_equal(data_packet_buffer[0]["data"], new_packet["data"])


def test_FileWriterProcess__removes_beta_2_packets_from_data_buffer_that_are_older_than_buffer_memory_size(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    board_queues = four_board_file_writer_process["board_queues"]

    new_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    new_packet["time_indices"] = np.array([FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS + 1], dtype=np.uint64)
    old_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    old_packet["time_indices"] = np.array([0], dtype=np.uint64)

    board_queues[0][0].put_nowait(old_packet)
    board_queues[0][0].put_nowait(new_packet)
    confirm_queue_is_eventually_of_size(
        board_queues[0][0], 2, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.

    invoke_process_run_and_check_errors(file_writer_process, num_iterations=2)
    data_packet_buffer = file_writer_process._data_packet_buffers[0]  # pylint: disable=protected-access
    assert len(data_packet_buffer) == 1
    np.testing.assert_equal(data_packet_buffer[0]["time_indices"], new_packet["time_indices"])


def test_FileWriterProcess__clears_data_buffer_when_stop_managed_acquisition_command_is_received(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    data_packet_buffer = file_writer_process._data_packet_buffers[0]  # pylint: disable=protected-access
    for _ in range(3):
        data_packet_buffer.append(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)

    stop_managed_acquisition_command = {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_managed_acquisition_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    assert len(data_packet_buffer) == 0


def test_FileWriterProcess__records_all_requested_beta_1_data_in_buffer__and_creates_dict_of_latest_data_timepoints_for_open_files__when_start_recording_command_is_received(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    data_packet_buffer = file_writer_process._data_packet_buffers[0]  # pylint: disable=protected-access
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

    start_recording_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = expected_start_timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    expected_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"

    this_file = h5py.File(
        os.path.join(
            file_dir,
            f"{expected_barcode}__{timestamp_str}",
            f"{expected_barcode}__{timestamp_str}__{WELL_DEF_24.get_well_name_from_well_index(expected_well_idx)}.h5",
        ),
        "r",
    )
    assert get_tissue_dataset_from_file(this_file).shape == (expected_num_packets_recorded,)
    assert get_tissue_dataset_from_file(this_file).dtype == "int32"

    expected_latest_timepoint = expected_start_timepoint + expected_num_packets_recorded - 1
    actual_latest_timepoint = file_writer_process.get_file_latest_timepoint(expected_well_idx)
    assert actual_latest_timepoint == expected_latest_timepoint


def test_FileWriterProcess__records_all_requested_beta_2_data_in_buffer__and_creates_dict_of_latest_data_timepoints_for_open_files__when_start_recording_command_is_received(
    four_board_file_writer_process,
):
    # pylint: disable=too-many-locals  # Tanner (5/30/21): many variables needed for this test
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    data_packet_buffer = file_writer_process._data_packet_buffers[0]  # pylint: disable=protected-access
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
    base_data = np.ones(num_data_points_per_packet, dtype=np.int16)
    base_time_offsets = np.ones((GENERIC_NUM_SENSORS_ENABLED, num_data_points_per_packet), dtype=np.uint16)
    for i in range(expected_num_packets_recorded):
        curr_idx = i * num_data_points_per_packet
        data_packet = {
            "time_indices": expected_time_indices[curr_idx : curr_idx + num_data_points_per_packet]
        }
        for well_idx in range(24):
            channel_dict = {
                "time_offsets": base_time_offsets * well_idx,
                SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: base_data * well_idx,
                SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: base_data * well_idx,
            }
            data_packet[well_idx] = channel_dict
        data_packet_buffer.append(data_packet)

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = expected_start_timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    expected_time_offsets_shape = (GENERIC_NUM_SENSORS_ENABLED, expected_total_num_data_points)
    expected_data_shape = (GENERIC_NUM_CHANNELS_ENABLED, expected_total_num_data_points)
    expected_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"
    for well_idx in range(24):
        this_file = h5py.File(
            os.path.join(
                four_board_file_writer_process["file_dir"],
                f"{expected_barcode}__{timestamp_str}",
                f"{expected_barcode}__{timestamp_str}__{WELL_DEF_24.get_well_name_from_well_index(well_idx)}.h5",
            ),
            "r",
        )
        time_index_dataset = get_time_index_dataset_from_file(this_file)
        assert time_index_dataset.dtype == "uint64", f"Incorrect time index dtype for well {well_idx}"
        assert time_index_dataset.shape == (
            expected_total_num_data_points,
        ), f"Incorrect tissue shape for well {well_idx}"
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
            np.ones(expected_time_offsets_shape, dtype=np.int16) * well_idx,
            err_msg=f"Incorrect offsets for well {well_idx}",
        )

        tissue_dataset = get_tissue_dataset_from_file(this_file)
        assert tissue_dataset.dtype == "int16", f"Incorrect tissue dtype for well {well_idx}"
        assert tissue_dataset.shape == expected_data_shape, f"Incorrect tissue shape for well {well_idx}"
        np.testing.assert_array_equal(
            tissue_dataset,
            np.ones(expected_data_shape, dtype=np.int16) * well_idx,
            err_msg=f"Incorrect data for well {well_idx}",
        )

        actual_latest_timepoint = file_writer_process.get_file_latest_timepoint(well_idx)
        assert (
            actual_latest_timepoint == expected_time_indices[-1]
        ), f"Incorrect latest timepoint for well {well_idx}"

        this_file.close()


def test_FileWriterProcess__deletes_recorded_beta_1_well_data_after_stop_time(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    instrument_board_queues = four_board_file_writer_process["board_queues"]
    comm_from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    expected_well_idx = 0
    start_recording_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    start_recording_command["active_well_indices"] = [expected_well_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command,
        comm_from_main_queue,
        sleep_after_put_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    )

    invoke_process_run_and_check_errors(file_writer_process)

    expected_stop_timepoint = 100
    expected_remaining_packets_recorded = 3
    expected_dataset = []
    for i in range(expected_remaining_packets_recorded):
        expected_dataset.append(i)
        data_packet = {
            "is_reference_sensor": False,
            "well_index": expected_well_idx,
            "data": np.array([[i], [i]], dtype=np.int32),
        }
        instrument_board_queues[0][0].put_nowait(data_packet)
    dummy_packets = 2
    for i in range(dummy_packets):
        data_packet = {
            "is_reference_sensor": False,
            "well_index": expected_well_idx,
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
        num_iterations=(expected_remaining_packets_recorded + dummy_packets),
    )

    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    stop_recording_command["timepoint_to_stop_recording_at"] = expected_stop_timepoint
    # ensure queue is empty before putting something else in
    confirm_queue_is_eventually_empty(comm_from_main_queue)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command,
        comm_from_main_queue,
        sleep_after_put_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"

    this_file = h5py.File(
        os.path.join(
            file_dir,
            f"{expected_barcode}__{timestamp_str}",
            f"{expected_barcode}__{timestamp_str}__{WELL_DEF_24.get_well_name_from_well_index(expected_well_idx)}.h5",
        ),
        "r",
    )
    tissue_dataset = get_tissue_dataset_from_file(this_file)
    assert tissue_dataset.shape == (expected_remaining_packets_recorded,)
    assert tissue_dataset.dtype == "int32"
    np.testing.assert_equal(tissue_dataset, np.array(expected_dataset))


def test_FileWriterProcess__deletes_recorded_beta_2_well_data_after_stop_time(
    four_board_file_writer_process,
):
    # pylint: disable=too-many-locals  # Tanner (5/19/21): many variables needed for this test
    file_writer_process = four_board_file_writer_process["fw_process"]
    file_writer_process.set_beta_2_mode()
    instrument_board_queues = four_board_file_writer_process["board_queues"]
    comm_from_main_queue = four_board_file_writer_process["from_main_queue"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command,
        comm_from_main_queue,
        sleep_after_put_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_stop_timepoint = 100
    expected_remaining_packets_recorded = 3
    num_data_points_per_packet = 4
    expected_total_num_data_points = expected_remaining_packets_recorded * num_data_points_per_packet
    base_data = np.zeros(num_data_points_per_packet, dtype=np.int16)
    base_time_offsets = np.zeros((GENERIC_NUM_SENSORS_ENABLED, num_data_points_per_packet), dtype=np.uint16)
    expected_time_indices = np.arange(expected_total_num_data_points, dtype=np.uint64)
    # add packets whose data will remain in the file
    for i in range(expected_remaining_packets_recorded):
        curr_idx = i * num_data_points_per_packet
        data_packet = {
            "time_indices": expected_time_indices[curr_idx : curr_idx + num_data_points_per_packet],
            "is_first_packet_of_stream": False,
        }
        for well_idx in range(24):
            channel_dict = {
                "time_offsets": base_time_offsets + well_idx,
                SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: base_data + well_idx,
                SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: base_data + well_idx,
            }
            data_packet[well_idx] = channel_dict
        instrument_board_queues[0][0].put_nowait(data_packet)
    # add packets whose data will later be removed from the file
    num_dummy_packets = 2
    for i in range(num_dummy_packets):
        first_timepoint = expected_stop_timepoint + 1 + (i * num_data_points_per_packet)
        data_packet = {
            "time_indices": np.arange(
                first_timepoint, first_timepoint + num_data_points_per_packet, dtype=np.uint64
            ),
            "is_first_packet_of_stream": False,
        }
        for well_idx in range(24):
            channel_dict = {
                "time_offsets": base_time_offsets,
                SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: base_data,
                SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: base_data,
            }
            data_packet[well_idx] = channel_dict
        instrument_board_queues[0][0].put_nowait(data_packet)
    # process all packets
    confirm_queue_is_eventually_of_size(
        instrument_board_queues[0][0],
        expected_remaining_packets_recorded + num_dummy_packets,
        sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )
    invoke_process_run_and_check_errors(
        file_writer_process,
        num_iterations=(expected_remaining_packets_recorded + num_dummy_packets),
    )
    confirm_queue_is_eventually_empty(instrument_board_queues[0][0])

    # send stop recording command
    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    stop_recording_command["timepoint_to_stop_recording_at"] = expected_stop_timepoint
    # ensure queue is empty before putting something else in
    confirm_queue_is_eventually_empty(comm_from_main_queue)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command,
        comm_from_main_queue,
        sleep_after_put_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"

    expected_time_offsets_shape = (GENERIC_NUM_SENSORS_ENABLED, expected_total_num_data_points)
    expected_data_shape = (GENERIC_NUM_CHANNELS_ENABLED, expected_total_num_data_points)
    for well_idx in range(24):
        this_file = h5py.File(
            os.path.join(
                four_board_file_writer_process["file_dir"],
                f"{expected_barcode}__{timestamp_str}",
                f"{expected_barcode}__{timestamp_str}__{WELL_DEF_24.get_well_name_from_well_index(well_idx)}.h5",
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
            np.ones(expected_time_offsets_shape, dtype=np.int16) * well_idx,
            err_msg=f"Incorrect offsets for well {well_idx}",
        )

        tissue_dataset = get_tissue_dataset_from_file(this_file)
        assert tissue_dataset.dtype == "int16", f"Incorrect tissue dtype for well {well_idx}"
        assert tissue_dataset.shape == expected_data_shape, f"Incorrect tissue shape for well {well_idx}"
        np.testing.assert_array_equal(
            tissue_dataset,
            np.ones(expected_data_shape, dtype=np.int16) * well_idx,
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
    start_recording_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
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
    assert is_queue_eventually_of_size(
        instrument_board_queues[0][0],
        expected_remaining_packets_recorded + dummy_packets,
        timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )
    invoke_process_run_and_check_errors(
        file_writer_process,
        num_iterations=(expected_remaining_packets_recorded + dummy_packets),
    )

    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    stop_recording_command["timepoint_to_stop_recording_at"] = expected_stop_timepoint
    # confirm the queue is empty before adding another command
    assert is_queue_eventually_empty(comm_from_main_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command, comm_from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_barcode = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]
    timestamp_str = "2020_02_09_190322"

    this_file = h5py.File(
        os.path.join(
            file_dir,
            f"{expected_barcode}__{timestamp_str}",
            f"{expected_barcode}__{timestamp_str}__{WELL_DEF_24.get_well_name_from_well_index(expected_well_idx)}.h5",
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
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    test_well_index = 6
    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [test_well_index]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command,
        from_main_queue,
    )
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    recorded_data_packet = {
        "time_indices": np.array([start_timepoint], dtype=np.uint64),
        "is_first_packet_of_stream": False,
        test_well_index: {
            "time_offsets": np.array([[0], [0]], dtype=np.uint16),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: np.array([0], dtype=np.int16),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: np.array([0], dtype=np.int16),
        },
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        recorded_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
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
