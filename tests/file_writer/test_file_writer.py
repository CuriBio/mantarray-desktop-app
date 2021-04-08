# -*- coding: utf-8 -*-
import copy
import json
import logging
from multiprocessing import Queue
import os
from statistics import stdev
import tempfile
import time

from freezegun import freeze_time
import h5py
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
from mantarray_desktop_app import FileWriterProcess
from mantarray_desktop_app import get_data_slice_within_timepoints
from mantarray_desktop_app import get_reference_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import InvalidDataTypeFromOkCommError
from mantarray_desktop_app import MantarrayH5FileCreator
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import UnrecognizedCommandFromMainToFileWriterError
from mantarray_file_manager import ADC_GAIN_SETTING_UUID
from mantarray_file_manager import ADC_REF_OFFSET_UUID
from mantarray_file_manager import ADC_TISSUE_OFFSET_UUID
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import COMPUTER_NAME_HASH
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import IS_FILE_ORIGINAL_UNTRIMMED_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import METADATA_UUID_DESCRIPTIONS
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
from mantarray_file_manager import WELL_COLUMN_UUID
from mantarray_file_manager import WELL_INDEX_UUID
from mantarray_file_manager import WELL_NAME_UUID
from mantarray_file_manager import WELL_ROW_UUID
from mantarray_file_manager import XEM_SERIAL_NUMBER_UUID
import numpy as np
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import validate_file_head_crc32

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import fixture_running_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_REFERENCE_SENSOR_DATA_PACKET
from ..fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_TISSUE_DATA_PACKET
from ..fixtures_file_writer import open_the_generic_h5_file
from ..fixtures_file_writer import WELL_DEF_24
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..parsed_channel_data_packets import SIMPLE_CONSTRUCT_DATA_FROM_WELL_0


__fixtures__ = [
    fixture_four_board_file_writer_process,
    fixture_running_four_board_file_writer_process,
]


def test_get_data_slice_within_timepoints__raises_not_implemented_error_if_no_first_valid_index_found():
    test_data = np.array([[1, 2, 3], [0, 0, 0]])
    min_timepoint = 4
    with pytest.raises(
        NotImplementedError,
        match=f"No timepoint >= the min timepoint of {min_timepoint} was found. All data passed to this function should contain at least one valid timepoint",
    ):
        get_data_slice_within_timepoints(test_data, min_timepoint)


def test_get_data_slice_within_timepoints__raises_not_implemented_error_if_no_last_valid_index_found():
    test_data = np.array([[11, 12, 13], [0, 0, 0]])
    min_timepoint = 0
    max_timepoint = 10
    with pytest.raises(
        NotImplementedError,
        match=f"No timepoint <= the max timepoint of {max_timepoint} was found. All data passed to this function should contain at least one valid timepoint",
    ):
        get_data_slice_within_timepoints(
            test_data, min_timepoint, max_timepoint=max_timepoint
        )


def test_FileWriterProcess_super_is_called_during_init(mocker):
    error_queue = Queue()
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")
    FileWriterProcess((), Queue(), Queue(), error_queue)
    mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


def test_FileWriterProcess_setup_before_loop__calls_super(
    four_board_file_writer_process, mocker
):
    spied_setup = mocker.spy(InfiniteProcess, "_setup_before_loop")

    fw_process = four_board_file_writer_process["fw_process"]
    invoke_process_run_and_check_errors(fw_process, perform_setup_before_loop=True)
    spied_setup.assert_called_once()


def test_FileWriterProcess_soft_stop_not_allowed_if_incoming_data_still_in_queue_for_board_0(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]

    # The first communication will be processed, but if there is a second one in the queue then the soft stop should be disabled
    board_queues[0][0].put_nowait(SIMPLE_CONSTRUCT_DATA_FROM_WELL_0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        SIMPLE_CONSTRUCT_DATA_FROM_WELL_0,
        board_queues[0][0],
    )

    confirm_queue_is_eventually_of_size(
        board_queues[0][0], 2, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.

    file_writer_process.soft_stop()
    invoke_process_run_and_check_errors(file_writer_process)
    assert file_writer_process.is_stopped() is False

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(board_queues[0][0])


def test_FileWriterProcess__raises_error_if_not_a_dict_is_passed_through_the_queue_for_board_0_from_instrument_comm(
    four_board_file_writer_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        "a string is not a dictionary",
        board_queues[0][0],
    )
    with pytest.raises(
        InvalidDataTypeFromOkCommError, match="a string is not a dictionary"
    ):
        invoke_process_run_and_check_errors(file_writer_process)


@pytest.mark.timeout(4)
def test_FileWriterProcess__raises_error_if_unrecognized_command_from_main(
    four_board_file_writer_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    error_queue = four_board_file_writer_process["error_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "do the hokey pokey"},
        from_main_queue,
    )
    file_writer_process.run(num_iterations=1)
    confirm_queue_is_eventually_of_size(error_queue, 1)

    raised_error, _ = error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert (
        isinstance(raised_error, UnrecognizedCommandFromMainToFileWriterError) is True
    )
    err_str = str(raised_error)
    assert "do the hokey pokey" in err_str


def test_FileWriterProcess_soft_stop_not_allowed_if_command_from_main_still_in_queue(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # The first communication will be processed, but if there is a second one in the queue then the soft stop should be disabled
    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [1]
    from_main_queue.put_nowait(this_command)
    from_main_queue.put_nowait(copy.deepcopy(this_command))
    confirm_queue_is_eventually_of_size(
        from_main_queue, 2, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # Eli (2/1/21): Even though the queue has been confirmed to be of size 2 in the above line, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    file_writer_process.soft_stop()
    invoke_process_run_and_check_errors(file_writer_process)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)
    assert file_writer_process.is_stopped() is False

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(from_main_queue)


def test_FileWriterProcess__close_all_files(four_board_file_writer_process, mocker):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [3, 18]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)
    open_files = file_writer_process._open_files  # pylint: disable=protected-access
    spied_file_3 = mocker.spy(open_files[0][3], "close")
    spied_file_18 = mocker.spy(open_files[0][18], "close")
    file_writer_process.close_all_files()
    assert spied_file_3.call_count == 1
    assert spied_file_18.call_count == 1


@pytest.mark.timeout(6)
def test_FileWriterProcess__creates_24_files_named_with_timestamp_barcode_well_index__and_supplied_metadata__set_to_swmr_mode__when_receiving_communication_to_start_recording(
    four_board_file_writer_process,
):
    # Creating 24 files takes a few seconds, so also test that all the metadata and other things are set during this single test
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    timestamp_str = "2020_02_09_190935"
    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_START_RECORDING_COMMAND, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    actual_set_of_files = set(
        os.listdir(os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}"))
    )
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
        assert (
            this_file.attrs["File Format Version"] == CURRENT_HDF5_FILE_FORMAT_VERSION
        )
        assert bool(this_file.attrs[str(HARDWARE_TEST_RECORDING_UUID)]) is False
        assert (
            this_file.attrs[str(UTC_BEGINNING_DATA_ACQUISTION_UUID)]
            == "2020-02-09 19:03:22.332597"
        )
        assert (
            this_file.attrs[str(START_RECORDING_TIME_INDEX_UUID)]
            == GENERIC_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ][START_RECORDING_TIME_INDEX_UUID]
        )
        assert this_file.attrs[
            str(UTC_BEGINNING_RECORDING_UUID)
        ] == GENERIC_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][
            UTC_BEGINNING_RECORDING_UUID
        ].strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )
        assert this_file.attrs[str(CUSTOMER_ACCOUNT_ID_UUID)] == str(
            CURI_BIO_ACCOUNT_UUID
        )
        assert this_file.attrs[str(USER_ACCOUNT_ID_UUID)] == str(
            CURI_BIO_USER_ACCOUNT_ID
        )
        actual_build_id = this_file.attrs[str(SOFTWARE_BUILD_NUMBER_UUID)]
        assert actual_build_id == COMPILED_EXE_BUILD_TIMESTAMP
        assert (
            this_file.attrs[str(SOFTWARE_RELEASE_VERSION_UUID)]
            == CURRENT_SOFTWARE_VERSION
        )
        assert (
            this_file.attrs[str(MAIN_FIRMWARE_VERSION_UUID)]
            == RunningFIFOSimulator.default_firmware_version
        )
        assert this_file.attrs[str(SLEEP_FIRMWARE_VERSION_UUID)] == "0.0.0"
        assert (
            this_file.attrs[str(XEM_SERIAL_NUMBER_UUID)]
            == RunningFIFOSimulator.default_xem_serial_number
        )
        assert (
            this_file.attrs[str(MANTARRAY_NICKNAME_UUID)]
            == RunningFIFOSimulator.default_mantarray_nickname
        )
        assert (
            this_file.attrs[str(MANTARRAY_SERIAL_NUMBER_UUID)]
            == RunningFIFOSimulator.default_mantarray_serial_number
        )
        assert this_file.attrs[str(REFERENCE_VOLTAGE_UUID)] == REFERENCE_VOLTAGE
        assert this_file.attrs[str(ADC_GAIN_SETTING_UUID)] == 32
        assert (
            this_file.attrs[str(ADC_TISSUE_OFFSET_UUID)]
            == GENERIC_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ]["adc_offsets"][well_idx]["construct"]
        )
        assert (
            this_file.attrs[str(ADC_REF_OFFSET_UUID)]
            == GENERIC_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ]["adc_offsets"][well_idx]["ref"]
        )

        assert this_file.attrs["Metadata UUID Descriptions"] == json.dumps(
            str(METADATA_UUID_DESCRIPTIONS)
        )
        assert (
            this_file.attrs[str(WELL_NAME_UUID)]
            == f"{WELL_DEF_24.get_well_name_from_well_index(well_idx)}"
        )
        assert this_file.attrs[str(WELL_ROW_UUID)] == row_idx
        assert this_file.attrs[str(WELL_COLUMN_UUID)] == col_idx
        assert this_file.attrs[
            str(WELL_INDEX_UUID)
        ] == WELL_DEF_24.get_well_index_from_row_and_column(row_idx, col_idx)
        assert this_file.attrs[str(TOTAL_WELL_COUNT_UUID)] == 24
        assert bool(this_file.attrs[str(IS_FILE_ORIGINAL_UNTRIMMED_UUID)]) is True
        assert this_file.attrs[str(TRIMMED_TIME_FROM_ORIGINAL_START_UUID)] == 0
        assert this_file.attrs[str(TRIMMED_TIME_FROM_ORIGINAL_END_UUID)] == 0
        assert (
            this_file.attrs[str(REF_SAMPLING_PERIOD_UUID)]
            == REFERENCE_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
        )
        assert (
            this_file.attrs[str(TISSUE_SAMPLING_PERIOD_UUID)]
            == CONSTRUCT_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
        )
        assert (
            this_file.attrs[str(COMPUTER_NAME_HASH)]
            == GENERIC_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ][COMPUTER_NAME_HASH]
        )
        assert (
            bool(this_file.attrs[str(BARCODE_IS_FROM_SCANNER_UUID)])
            is GENERIC_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ][BARCODE_IS_FROM_SCANNER_UUID]
        )

        assert this_file["reference_sensor_readings"].shape == (0,)
        assert this_file["reference_sensor_readings"].dtype == "int32"
        assert get_tissue_dataset_from_file(this_file).shape == (0,)
        assert get_tissue_dataset_from_file(this_file).dtype == "int32"


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
    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [3, 18]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)
    actual_set_of_files = set(
        os.listdir(os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}"))
    )
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

    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [1, 5]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command, from_main_queue
    )
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


def test_FileWriterProcess__stop_recording_sets_stop_recording_timestamp_to_timepoint_in_communication_and_communicates_successful_receipt_and_sets_is_recording_to_false__and_start_recording_clears_stop_timestamp_and_finalization_statuses(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    expected_well_idx = 0
    start_timepoint_1 = 440000
    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["timepoint_to_begin_recording_at"] = start_timepoint_1
    this_command["active_well_indices"] = [expected_well_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    data_packet = {
        "is_reference_sensor": False,
        "well_index": expected_well_idx,
        "data": np.array([[start_timepoint_1], [0]], dtype=np.int32),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        data_packet, board_queues[0][0]
    )
    invoke_process_run_and_check_errors(file_writer_process)

    stop_timestamps = file_writer_process.get_stop_recording_timestamps()

    assert stop_timestamps[0] is None

    stop_timepoint = 2968000
    this_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    this_command["timepoint_to_stop_recording_at"] = stop_timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    assert stop_timestamps[0] == stop_timepoint

    confirm_queue_is_eventually_of_size(
        to_main_queue, 2, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )
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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        data_packet2, board_queues[0][0]
    )
    invoke_process_run_and_check_errors(file_writer_process)
    # Tanner (1/13/21): A reference data packet is also necessary to finalize the file
    ref_data_packet = {
        "is_reference_sensor": True,
        "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[0],
        "data": np.array([[timepoint_after_stop], [0]], dtype=np.int32),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        ref_data_packet, board_queues[0][0]
    )
    invoke_process_run_and_check_errors(file_writer_process)

    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command[
        "timepoint_to_begin_recording_at"
    ] = 3760000  # Tanner (1/13/21): This can be any arbitrary timepoint after the timepoint of the last data packet sent
    this_command["active_well_indices"] = [expected_well_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)
    assert stop_timestamps[0] is None

    tissue_status, _ = file_writer_process.get_recording_finalization_statuses()
    assert tissue_status[0][expected_well_idx] is False


def test_FileWriterProcess__closes_the_files_and_adds_crc32_checksum_and_sends_communication_to_main_when_all_data_has_been_added_after_recording_stopped(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    spied_h5_close = mocker.spy(
        h5py._hl.files.File,  # pylint:disable=protected-access # this is the only known (Eli 2/27/20) way to access the appropriate type definition
        "close",
    )

    start_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    start_command["active_well_indices"] = [4, 5]
    num_data_points = 10
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_command, from_main_queue
    )

    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_idx in range(num_data_points):
        data[0, this_idx] = (
            start_command["timepoint_to_begin_recording_at"]
            + this_idx * REFERENCE_SENSOR_SAMPLING_PERIOD
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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_command, from_main_queue
    )

    # reference data
    reference_data_packet_after_stop = copy.deepcopy(
        GENERIC_REFERENCE_SENSOR_DATA_PACKET
    )
    data_after_stop = np.zeros((2, num_data_points), dtype=np.int32)
    for this_idx in range(num_data_points):
        data_after_stop[0, this_idx] = (
            stop_command["timepoint_to_stop_recording_at"]
            + (this_idx - 5) * REFERENCE_SENSOR_SAMPLING_PERIOD
        )
        data_after_stop[1, this_idx] = this_idx * 5
    reference_data_packet_after_stop["data"] = data_after_stop

    board_queues[0][0].put_nowait(reference_data_packet_after_stop)

    # tissue data
    tissue_data_packet_after_stop = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    data_after_stop = np.zeros((2, num_data_points), dtype=np.int32)
    for this_idx in range(num_data_points):
        data_after_stop[0, this_idx] = (
            stop_command["timepoint_to_stop_recording_at"]
            + this_idx * CONSTRUCT_SENSOR_SAMPLING_PERIOD
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


def test_FileWriterProcess__drain_all_queues__drains_all_queues_except_error_queue_and_returns__all_items(
    four_board_file_writer_process,
):
    expected = [[0, 1], [2, 3], [4, 5], [6, 7]]
    expected_error = "error"
    expected_from_main = "from_main"
    expected_to_main = "to_main"

    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    error_queue = four_board_file_writer_process["error_queue"]
    for i, board in enumerate(board_queues):
        for j, iter_queue in enumerate(board):
            item = expected[i][j]
            put_object_into_queue_and_raise_error_if_eventually_still_empty(
                item, iter_queue
            )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_from_main, from_main_queue
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_to_main, to_main_queue
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_error, error_queue
    )

    actual = file_writer_process._drain_all_queues()  # pylint:disable=protected-access

    confirm_queue_is_eventually_of_size(error_queue, 1)
    actual_error = error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_error == expected_error

    for iter_queue_idx, iter_queue in enumerate(
        (
            board_queues[0][0],
            board_queues[0][1],
            board_queues[1][0],
            board_queues[2][0],
            board_queues[3][0],
            from_main_queue,
            to_main_queue,
        )
    ):
        assert (
            iter_queue_idx,
            is_queue_eventually_empty(
                iter_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
            ),
        ) == (iter_queue_idx, True)

    assert actual["board_0"]["instrument_comm_to_file_writer"] == [expected[0][0]]
    assert actual["board_0"]["file_writer_to_data_analyzer"] == [expected[0][1]]
    assert actual["board_1"]["instrument_comm_to_file_writer"] == [expected[1][0]]
    assert actual["board_2"]["instrument_comm_to_file_writer"] == [expected[2][0]]
    assert actual["board_3"]["instrument_comm_to_file_writer"] == [expected[3][0]]
    assert actual["from_main_to_file_writer"] == [expected_from_main]
    assert actual["from_file_writer_to_main"] == [expected_to_main]


@pytest.mark.slow
def test_FileWriterProcess__logs_performance_metrics_after_appropriate_number_of_run_cycles(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    expected_iteration_dur = 0.001 * 10 ** 9
    expected_idle_time = (
        expected_iteration_dur * FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
    )
    expected_start_timepoint = 0
    expected_stop_timepoint = (
        2 * expected_iteration_dur * FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
    )
    expected_latest_percent_use = 100 * (
        1 - expected_idle_time / (expected_stop_timepoint - expected_start_timepoint)
    )
    expected_percent_use_values = [27.4, 42.8, expected_latest_percent_use]
    expected_longest_iterations = [
        expected_iteration_dur
        for _ in range(file_writer_process.num_longest_iterations)
    ]

    perf_counter_vals = []
    for _ in range(FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES - 1):
        perf_counter_vals.append(0)
        perf_counter_vals.append(expected_iteration_dur)
    perf_counter_vals.append(0)
    perf_counter_vals.append(expected_stop_timepoint)
    perf_counter_vals.append(0)
    mocker.patch.object(
        time, "perf_counter_ns", autospec=True, side_effect=perf_counter_vals
    )

    file_writer_process._idle_iteration_time_ns = (  # pylint: disable=protected-access
        expected_iteration_dur
    )
    file_writer_process._minimum_iteration_duration_seconds = (  # pylint: disable=protected-access
        2 * expected_iteration_dur / (10 ** 9)
    )
    file_writer_process._start_timepoint_of_last_performance_measurement = (  # pylint: disable=protected-access
        expected_start_timepoint
    )
    file_writer_process._percent_use_values = (  # pylint: disable=protected-access
        expected_percent_use_values[:-1]
    )

    invoke_process_run_and_check_errors(
        file_writer_process, num_iterations=FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
    )
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual = actual["message"]

    assert actual["communication_type"] == "performance_metrics"
    assert actual["percent_use"] == expected_latest_percent_use
    assert actual["percent_use_metrics"] == {
        "max": max(expected_percent_use_values),
        "min": min(expected_percent_use_values),
        "stdev": round(stdev(expected_percent_use_values), 6),
        "mean": round(
            sum(expected_percent_use_values) / len(expected_percent_use_values), 6
        ),
    }
    num_longest_iterations = file_writer_process.num_longest_iterations
    assert (
        actual["longest_iterations"]
        == expected_longest_iterations[-num_longest_iterations:]
    )
    assert "idle_iteration_time_ns" not in actual
    assert "start_timepoint_of_measurements" not in actual


@pytest.mark.slow
@pytest.mark.timeout(200)
def test_FileWriterProcess__does_not_log_percent_use_metrics_in_first_logging_cycle(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    file_writer_process._minimum_iteration_duration_seconds = (  # pylint: disable=protected-access
        0
    )

    invoke_process_run_and_check_errors(
        file_writer_process,
        num_iterations=FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES,
        perform_setup_before_loop=True,
    )
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual = actual["message"]
    assert "percent_use_metrics" not in actual


def test_FileWriterProcess__logs_metrics_of_data_recording_when_recording(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    file_writer_process._minimum_iteration_duration_seconds = (  # pylint: disable=protected-access
        0
    )

    start_recording_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        START_RECORDING_TIME_INDEX_UUID
    ] = 0
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command, from_main_queue
    )
    invoke_process_run_and_check_errors(
        file_writer_process, perform_setup_before_loop=True
    )
    to_main_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # Tanner (9/10/20): remove start_recording confirmation

    num_points_list = list()
    for i in range(24):
        num_points = (i + 1) * 2
        num_points_list.append(num_points)
        well_packet = {
            "well_index": 4,
            "is_reference_sensor": False,
            "data": np.zeros((2, num_points)),
        }
        board_queues[0][0].put_nowait(well_packet)
    for i in range(6):
        num_points = 5
        num_points_list.append(num_points)
        ref_packet = {
            "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[i],
            "is_reference_sensor": True,
            "data": np.zeros((2, num_points)),
        }
        board_queues[0][0].put_nowait(ref_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], 30)
    expected_recording_durations = list(range(30))
    perf_counter_vals = [
        0 if i % 2 == 0 else expected_recording_durations[i // 2] for i in range(60)
    ]
    mocker.patch.object(
        time, "perf_counter", autospec=True, side_effect=perf_counter_vals
    )

    invoke_process_run_and_check_errors(
        file_writer_process, num_iterations=FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
    )

    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual = actual["message"]
    assert (
        "num_recorded_data_points_metrics" in actual
    ), f"Message did not contain key: 'num_recorded_data_points_metrics', Full message dict: {actual}"
    assert actual["num_recorded_data_points_metrics"] == {
        "max": max(num_points_list),
        "min": min(num_points_list),
        "stdev": round(stdev(num_points_list), 6),
        "mean": round(sum(num_points_list) / len(num_points_list), 6),
    }
    assert actual["recording_duration_metrics"] == {
        "max": max(expected_recording_durations),
        "min": min(expected_recording_durations),
        "stdev": round(stdev(expected_recording_durations), 6),
        "mean": round(
            sum(expected_recording_durations) / len(expected_recording_durations), 6
        ),
    }

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


def test_FileWriterProcess__begins_building_data_buffer_when_managed_acquisition_starts(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]

    expected_num_items = 3
    for _ in range(expected_num_items):
        board_queues[0][0].put_nowait(SIMPLE_CONSTRUCT_DATA_FROM_WELL_0)
    confirm_queue_is_eventually_of_size(
        board_queues[0][0],
        expected_num_items,
        sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.

    invoke_process_run_and_check_errors(
        file_writer_process, num_iterations=expected_num_items
    )

    actual_num_items = len(
        file_writer_process._data_packet_buffers[0]  # pylint: disable=protected-access
    )
    assert actual_num_items == expected_num_items


def test_FileWriterProcess__removes_packets_from_data_buffer_that_are_older_than_buffer_memory_size(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]

    new_packet = {
        "is_reference_sensor": False,
        "well_index": 0,
        "data": np.array(
            [[FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS + 1], [0]], dtype=np.int32
        ),
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

    # Eli (12/10/20): the new version of black is forcing the pylint note to be moved away from the relevant line
    # fmt: off
    data_packet_buffer = file_writer_process._data_packet_buffers[0]  # pylint: disable=protected-access
    # fmt: on
    assert len(data_packet_buffer) == 1
    assert (
        data_packet_buffer[0]["is_reference_sensor"]
        is new_packet["is_reference_sensor"]
    )
    assert data_packet_buffer[0]["well_index"] == new_packet["well_index"]
    np.testing.assert_equal(data_packet_buffer[0]["data"], new_packet["data"])


def test_FileWriterProcess__clears_data_buffer_when_stop_managed_acquisition_command_is_received(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # Eli (12/10/20): the new version of black is forcing the pylint note to be moved away from the relevant line
    # fmt: off
    data_packet_buffer = file_writer_process._data_packet_buffers[0]  # pylint: disable=protected-access
    # fmt: on
    for _ in range(3):
        data_packet_buffer.append(SIMPLE_CONSTRUCT_DATA_FROM_WELL_0)

    stop_managed_acquisition_command = {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_managed_acquisition_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    assert len(data_packet_buffer) == 0


def test_FileWriterProcess__records_all_requested_data_in_buffer__and_creates_dict_of_latest_data_timepoints_for_open_files__when_start_recording_command_is_received(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    # Eli (12/10/20): the new version of black is forcing the pylint note to be moved away from the relevant line
    # fmt: off
    data_packet_buffer = file_writer_process._data_packet_buffers[0]  # pylint: disable=protected-access
    # fmt: on
    for _ in range(2):
        data_packet_buffer.append(SIMPLE_CONSTRUCT_DATA_FROM_WELL_0)

    expected_start_timepoint = 100
    expected_packets_recorded = 3
    expected_well_idx = 0
    for i in range(expected_packets_recorded):
        data_packet = {
            "is_reference_sensor": False,
            "well_index": expected_well_idx,
            "data": np.array([[expected_start_timepoint + i], [0]], dtype=np.int32),
        }
        data_packet_buffer.append(data_packet)

    start_recording_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    start_recording_command[
        "timepoint_to_begin_recording_at"
    ] = expected_start_timepoint
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_barcode = start_recording_command[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    timestamp_str = "2020_02_09_190322"

    this_file = h5py.File(
        os.path.join(
            file_dir,
            f"{expected_barcode}__{timestamp_str}",
            f"{expected_barcode}__{timestamp_str}__{WELL_DEF_24.get_well_name_from_well_index(expected_well_idx)}.h5",
        ),
        "r",
    )
    assert get_tissue_dataset_from_file(this_file).shape == (expected_packets_recorded,)
    assert get_tissue_dataset_from_file(this_file).dtype == "int32"

    expected_latest_timepoint = expected_start_timepoint + expected_packets_recorded - 1
    actual_latest_timepoint = file_writer_process.get_file_latest_timepoint(
        expected_well_idx
    )
    assert actual_latest_timepoint == expected_latest_timepoint


def test_FileWriterProcess__deletes_recorded_well_data_after_stop_time(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    instrument_board_queues = four_board_file_writer_process["board_queues"]
    comm_from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    expected_well_idx = 0
    start_recording_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    start_recording_command["active_well_indices"] = [expected_well_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command,
        comm_from_main_queue,
        sleep_after_put_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    )

    invoke_process_run_and_check_errors(file_writer_process)

    expected_timepoint = 100
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
                [[expected_timepoint + ((i + 1) * ROUND_ROBIN_PERIOD)], [0]],
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
    stop_recording_command["timepoint_to_stop_recording_at"] = expected_timepoint
    # ensure queue is empty before putting something else in
    confirm_queue_is_eventually_empty(comm_from_main_queue)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command,
        comm_from_main_queue,
        sleep_after_put_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_barcode = start_recording_command[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
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


def test_FileWriterProcess__deletes_recorded_reference_data_after_stop_time(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    instrument_board_queues = four_board_file_writer_process["board_queues"]
    comm_from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    expected_well_idx = 0
    start_recording_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    start_recording_command["active_well_indices"] = [expected_well_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command, comm_from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_timepoint = 100
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
                [[expected_timepoint + ((i + 1) * ROUND_ROBIN_PERIOD)], [0]],
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
    stop_recording_command["timepoint_to_stop_recording_at"] = expected_timepoint
    # confirm the queue is empty before adding another command
    assert is_queue_eventually_empty(
        comm_from_main_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command, comm_from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_barcode = start_recording_command[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
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


def test_FileWriterProcess_teardown_after_loop__sets_teardown_complete_event(
    four_board_file_writer_process,
    mocker,
):
    fw_process = four_board_file_writer_process["fw_process"]

    fw_process.soft_stop()
    fw_process.run(perform_setup_before_loop=False, num_iterations=1)

    assert fw_process.is_teardown_complete() is True


@freeze_time("2020-07-20 15:09:22.654321")
def test_FileWriterProcess_teardown_after_loop__puts_teardown_log_message_into_queue(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    fw_process.soft_stop()
    fw_process.run(perform_setup_before_loop=False, num_iterations=1)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert (
        actual["message"]
        == "File Writer Process beginning teardown at 2020-07-20 15:09:22.654321"
    )


def test_FileWriterProcess_teardown_after_loop__does_not_call_close_all_files__when_not_recording(
    four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")

    fw_process.soft_stop()
    fw_process.run(perform_setup_before_loop=False, num_iterations=1)

    spied_close_all_files.assert_not_called()


def test_FileWriterProcess_teardown_after_loop__calls_close_all_files__when_still_recording(
    four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_START_RECORDING_COMMAND, from_main_queue
    )

    fw_process.soft_stop()
    fw_process.run(perform_setup_before_loop=False, num_iterations=1)

    spied_close_all_files.assert_called_once()


def test_FileWriterProcess_hard_stop__calls_close_all_files__when_still_recording(
    four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_START_RECORDING_COMMAND, from_main_queue
    )
    fw_process.run(
        perform_setup_before_loop=False,
        num_iterations=1,
        perform_teardown_after_loop=False,
    )
    assert spied_close_all_files.call_count == 0  # confirm precondition
    fw_process.hard_stop()

    spied_close_all_files.assert_called_once()


def test_FileWriterProcess_hard_stop__closes_all_files_after_stop_recording_before_all_files_are_finalized__and_files_can_be_opened_after_process_stops(
    four_board_file_writer_process, mocker
):
    expected_timestamp = "2020_02_09_190935"
    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]

    fw_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    tmp_dir = four_board_file_writer_process["file_dir"]

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_START_RECORDING_COMMAND, from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)

    # fill files with data
    start_timepoint = GENERIC_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    data = np.array([[start_timepoint], [0]], dtype=np.int32)
    for i in range(24):
        tissue_data_packet = {
            "well_index": i,
            "is_reference_sensor": False,
            "data": data,
        }
        board_queues[0][0].put_nowait(tissue_data_packet)
    for i in range(6):
        ref_data_packet = {
            "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[i],
            "is_reference_sensor": True,
            "data": data,
        }
        board_queues[0][0].put_nowait(ref_data_packet)
    confirm_queue_is_eventually_of_size(
        board_queues[0][0], 30, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.

    invoke_process_run_and_check_errors(fw_process, num_iterations=30)
    confirm_queue_is_eventually_empty(board_queues[0][0])

    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command, from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)

    assert spied_close_all_files.call_count == 0  # confirm precondition
    fw_process.hard_stop()
    spied_close_all_files.assert_called_once()

    # confirm files can be opened and files contains at least one piece of metadata
    for row_idx in range(4):
        for col_idx in range(6):
            with h5py.File(
                os.path.join(
                    tmp_dir,
                    f"{expected_barcode}__{expected_timestamp}",
                    f"{expected_barcode}__{expected_timestamp}__{WELL_DEF_24.get_well_name_from_row_and_column(row_idx, col_idx)}.h5",
                ),
                "r",
            ) as this_file:
                assert str(START_RECORDING_TIME_INDEX_UUID) in this_file.attrs


def test_FileWriterProcess__ignores_commands_from_main_while_finalizing_files_after_stop_recording(
    four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_START_RECORDING_COMMAND, from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)

    # fill files with data
    start_timepoint = GENERIC_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    first_data = np.array([[start_timepoint], [0]], dtype=np.int32)
    for i in range(24):
        tissue_data_packet = {
            "well_index": i,
            "is_reference_sensor": False,
            "data": first_data,
        }
        board_queues[0][0].put_nowait(tissue_data_packet)
    for i in range(6):
        ref_data_packet = {
            "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[i],
            "is_reference_sensor": True,
            "data": first_data,
        }
        board_queues[0][0].put_nowait(ref_data_packet)
    confirm_queue_is_eventually_of_size(
        board_queues[0][0], 30, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.

    invoke_process_run_and_check_errors(fw_process, num_iterations=30)
    confirm_queue_is_eventually_empty(board_queues[0][0])

    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_recording_command, from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)

    # check that command is ignored # Tanner (1/12/21): no particular reason this command needs to be update_directory, but it's easy to test if this gets processed
    expected_new_dir = "dummy_dir"
    update_dir_command = {
        "command": "update_directory",
        "new_directory": expected_new_dir,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        update_dir_command, from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    # add data past stop point so files will be finalized
    stop_timepoint = GENERIC_STOP_RECORDING_COMMAND["timepoint_to_stop_recording_at"]
    last_data = np.array([[stop_timepoint], [0]], dtype=np.int32)
    for i in range(24):
        final_tissue_data_packet = {
            "well_index": i,
            "is_reference_sensor": False,
            "data": last_data,
        }
        board_queues[0][0].put_nowait(final_tissue_data_packet)
    for i in range(6):
        final_ref_data_packet = {
            "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[i],
            "is_reference_sensor": True,
            "data": last_data,
        }
        board_queues[0][0].put_nowait(final_ref_data_packet)
    confirm_queue_is_eventually_of_size(
        board_queues[0][0], 30, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # Eli (2/1/21): Even though the queue size has been confirmed, this extra sleep appears necessary to ensure that the subprocess can pull from the queue consistently using `get_nowait`. Not sure why this is required.
    invoke_process_run_and_check_errors(fw_process, num_iterations=30)
    confirm_queue_is_eventually_empty(board_queues[0][0])
    # check command is still ignored
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    # now all files should be finalized, confirm command is now processed
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(from_main_queue)
    assert fw_process.get_file_directory() == expected_new_dir

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


@pytest.mark.slow
@pytest.mark.timeout(10)
def test_FileWriterProcess_teardown_after_loop__can_teardown_process_while_recording__and_log_stop_recording_message(
    running_four_board_file_writer_process,
):
    fw_process = running_four_board_file_writer_process["fw_process"]
    to_main_queue = running_four_board_file_writer_process["to_main_queue"]
    from_main_queue = running_four_board_file_writer_process["from_main_queue"]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_START_RECORDING_COMMAND, from_main_queue
    )

    fw_process.soft_stop()
    fw_process.join()

    queue_items = drain_queue(to_main_queue)

    actual = queue_items[-1]
    assert (
        actual["message"]
        == "Data is still be written to file. Stopping recording and closing files to complete teardown"
    )


def test_MantarrayH5FileCreator__sets_file_name_and_userblock_size():
    with tempfile.TemporaryDirectory() as tmp_dir:
        expected_filename = os.path.join(tmp_dir, "myfile.h5")
        test_file = MantarrayH5FileCreator(expected_filename)
        assert test_file.userblock_size == 512
        assert test_file.filename == expected_filename
        test_file.close()  # Eli (8/11/20): always make sure to explicitly close the files or tests can fail on windows
