# -*- coding: utf-8 -*-
import copy
import logging
from multiprocessing import Queue
import os
import tempfile
import time

from freezegun import freeze_time
import h5py
from mantarray_desktop_app import FileWriterProcess
from mantarray_desktop_app import get_data_slice_within_timepoints
from mantarray_desktop_app import get_time_index_dataset_from_file
from mantarray_desktop_app import get_time_offset_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import MantarrayH5FileCreator
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import UnrecognizedCommandFromMainToFileWriterError
from mantarray_desktop_app.constants import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app.sub_processes import file_writer
import numpy as np
from pulse3D.constants import PLATE_BARCODE_UUID
from pulse3D.constants import START_RECORDING_TIME_INDEX_UUID
import pytest
from stdlib_utils import create_metrics_stats
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import create_and_close_beta_1_h5_files
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import fixture_runnable_four_board_file_writer_process
from ..fixtures_file_writer import fixture_running_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_BETA_1_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_UPDATE_RECORDING_NAME_COMMAND
from ..fixtures_file_writer import GENERIC_UPDATE_USER_SETTINGS
from ..fixtures_file_writer import populate_calibration_folder
from ..fixtures_file_writer import WELL_DEF_24
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_empty
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..parsed_channel_data_packets import SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0
from ..parsed_channel_data_packets import SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS


__fixtures__ = [
    fixture_patch_print,
    fixture_four_board_file_writer_process,
    fixture_runnable_four_board_file_writer_process,
    fixture_running_four_board_file_writer_process,
]


def test_get_data_slice_within_timepoints__raises_not_implemented_error_if_no_first_valid_index_found(
    patch_print,
):
    test_data = np.array([[1, 2, 3], [0, 0, 0]])
    min_timepoint = 4
    with pytest.raises(
        NotImplementedError,
        match=f"No timepoint >= the min timepoint of {min_timepoint} was found. All data passed to this function should contain at least one valid timepoint",
    ):
        get_data_slice_within_timepoints(test_data, min_timepoint)


def test_get_data_slice_within_timepoints__raises_not_implemented_error_if_no_last_valid_index_found(
    patch_print,
):
    test_data = np.array([[11, 12, 13], [0, 0, 0]])
    min_timepoint = 0
    max_timepoint = 10
    with pytest.raises(
        NotImplementedError,
        match=f"No timepoint <= the max timepoint of {max_timepoint} was found. All data passed to this function should contain at least one valid timepoint",
    ):
        get_data_slice_within_timepoints(test_data, min_timepoint, max_timepoint=max_timepoint)


def test_FileWriterProcess_super_is_called_during_init(mocker):
    error_queue = Queue()
    spied_init = mocker.spy(InfiniteProcess, "__init__")
    with tempfile.TemporaryDirectory() as tmpdir:
        FileWriterProcess((), Queue(), Queue(), error_queue, file_directory=tmpdir)
    spied_init.assert_called_once_with(mocker.ANY, error_queue, logging_level=logging.INFO)


def test_FileWriterProcess__creates_temp_dir_for_calibration_files_in_beta_2_mode_and_stores_dir_name(mocker):
    with tempfile.TemporaryDirectory() as tmpdir:
        spied_temp_dir = mocker.spy(file_writer.tempfile, "TemporaryDirectory")

        fw_process_beta_1 = FileWriterProcess(
            (), Queue(), Queue(), Queue(), file_directory=tmpdir, beta_2_mode=False
        )
        assert "calibration_file_directory" not in vars(fw_process_beta_1)
        spied_temp_dir.assert_not_called()

        fw_process_beta_2 = FileWriterProcess(
            (), Queue(), Queue(), Queue(), file_directory=tmpdir, beta_2_mode=True
        )
        spied_temp_dir.assert_called_once()
        assert fw_process_beta_2.calibration_file_directory == spied_temp_dir.spy_return.name


def test_FileWriterProcess_soft_stop_not_allowed_if_incoming_data_still_in_queue_for_board_0(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]

    # The first communication will be processed, but if there is a second one in the queue then the soft stop should be disabled
    board_queues[0][0].put_nowait(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0,
        board_queues[0][0],
    )

    confirm_queue_is_eventually_of_size(board_queues[0][0], 2)

    file_writer_process.soft_stop()
    invoke_process_run_and_check_errors(file_writer_process)
    assert file_writer_process.is_stopped() is False

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(board_queues[0][0])


def test_FileWriterProcess__setup_before_loop__calls_super(four_board_file_writer_process, mocker):
    spied_setup = mocker.spy(InfiniteProcess, "_setup_before_loop")
    file_writer_process = four_board_file_writer_process["fw_process"]

    invoke_process_run_and_check_errors(file_writer_process, perform_setup_before_loop=True)
    spied_setup.assert_called_once()


def test_FileWriterProcess__setup_before_loop__creates_recording_dirs_if_they_dont_exist(
    four_board_file_writer_process, mocker
):
    spied_check_dirs = mocker.spy(FileWriterProcess, "_check_dirs")
    file_writer_process = four_board_file_writer_process["fw_process"]

    invoke_process_run_and_check_errors(file_writer_process, perform_setup_before_loop=True)
    spied_check_dirs.assert_called_once()


@pytest.mark.timeout(4)
def test_FileWriterProcess__raises_error_if_unrecognized_command_from_main(
    four_board_file_writer_process, patch_print
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    error_queue = four_board_file_writer_process["error_queue"]

    test_command = "bad"

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": test_command}, from_main_queue
    )
    file_writer_process.run(num_iterations=1)
    confirm_queue_is_eventually_of_size(error_queue, 1)

    raised_error, _ = error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert isinstance(raised_error, UnrecognizedCommandFromMainToFileWriterError) is True
    err_str = str(raised_error)
    assert test_command in err_str


@pytest.mark.parametrize("new_dir_exists", [True, False])
@pytest.mark.parametrize("failed_exists", [True, False])
@pytest.mark.parametrize("zipped_exists", [True, False])
def test_FileWriterProcess__creates_new_subfolders_correctly_when_updating_file_dir(
    new_dir_exists, failed_exists, zipped_exists, four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    def isdir_se(dir_name):
        if "zipped" in dir_name:
            return zipped_exists
        if "failed" in dir_name:
            return failed_exists
        return new_dir_exists

    mocked_isdir = mocker.patch.object(os.path, "isdir", autospec=True, side_effect=isdir_se)
    mocked_makedirs = mocker.patch.object(os, "makedirs", autospec=True)

    expected_new_dir = "dummy_dir"
    update_dir_command = {"command": "update_directory", "new_directory": expected_new_dir}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(update_dir_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    assert mocked_isdir.call_count == 3
    assert mocked_makedirs.call_count == sum([not new_dir_exists, not zipped_exists, not failed_exists])
    for dir_name, exists in (
        (expected_new_dir, new_dir_exists),
        (os.path.join(expected_new_dir, "zipped"), zipped_exists),
        (os.path.join(expected_new_dir, "failed_uploads"), failed_exists),
    ):
        if exists:
            assert mocker.call(dir_name) not in mocked_makedirs.call_args_list
        else:
            mocked_makedirs.assert_any_call(dir_name)


def test_FileWriterProcess__recording_dirs_update_correctly(four_board_file_writer_process, mocker):
    fw_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # mock so no dirs are created
    mocker.patch.object(os.path, "isdir", autospec=True, return_value=True)

    expected_new_dir = "dummy_dir"
    update_dir_command = {"command": "update_directory", "new_directory": expected_new_dir}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(update_dir_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    assert fw_process._file_directory == expected_new_dir
    assert fw_process._zipped_files_dir == os.path.join(expected_new_dir, "zipped")
    assert fw_process._failed_uploads_dir == os.path.join(expected_new_dir, "failed_uploads")


def test_FileWriterProcess__soft_stop_not_allowed_if_command_from_main_still_in_queue(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # The first communication will be processed, but if there is a second one in the queue then the soft stop should be disabled
    this_command = dict(GENERIC_BETA_1_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [1]
    from_main_queue.put_nowait(this_command)
    from_main_queue.put_nowait(copy.deepcopy(this_command))
    confirm_queue_is_eventually_of_size(from_main_queue, 2)
    file_writer_process.soft_stop()
    invoke_process_run_and_check_errors(file_writer_process)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)
    assert file_writer_process.is_stopped() is False

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(from_main_queue)


@pytest.mark.parametrize(
    "test_start_recording_command,test_description",
    [
        (dict(GENERIC_BETA_1_START_RECORDING_COMMAND), "closes correctly with beta 1 files"),
        (dict(GENERIC_BETA_2_START_RECORDING_COMMAND), "closes correctly with beta 2 files"),
    ],
)
def test_FileWriterProcess__close_all_files(
    test_start_recording_command, test_description, four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    if test_start_recording_command == GENERIC_BETA_2_START_RECORDING_COMMAND:
        file_writer_process.set_beta_2_mode()
        populate_calibration_folder(file_writer_process)

    this_command = copy.deepcopy(test_start_recording_command)
    this_command["active_well_indices"] = [3, 18]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)
    open_files = file_writer_process._open_files  # pylint: disable=protected-access
    spied_file_3 = mocker.spy(open_files[0][3], "close")
    spied_file_18 = mocker.spy(open_files[0][18], "close")
    file_writer_process.close_all_files()
    assert spied_file_3.call_count == 1
    assert spied_file_18.call_count == 1


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
            put_object_into_queue_and_raise_error_if_eventually_still_empty(item, iter_queue)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_from_main, from_main_queue)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_to_main, to_main_queue)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_error, error_queue)

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
            is_queue_eventually_empty(iter_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS) is True
        ), f"Queue at index {iter_queue_idx} was not empty"

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

    # set these two values so that performance metrics are created and sent to main
    file_writer_process._logging_level = logging.DEBUG
    file_writer_process._is_recording = True

    # set this to 0 to speed up the test
    file_writer_process._minimum_iteration_duration_seconds = 0

    test_num_iterations = file_writer_process._iterations_per_logging_cycle * 2

    invoke_process_run_and_check_errors(file_writer_process, num_iterations=test_num_iterations)
    confirm_queue_is_eventually_of_size(to_main_queue, 2)
    actual = drain_queue(to_main_queue)[-1]["message"]

    assert actual["communication_type"] == "performance_metrics"

    assert "percent_use" in actual
    assert "percent_use_metrics" in actual
    assert "longest_iterations" in actual

    assert "idle_iteration_time_ns" not in actual
    assert "start_timepoint_of_measurements" not in actual


@pytest.mark.slow
@pytest.mark.timeout(20)
def test_FileWriterProcess__does_not_log_percent_use_metrics_in_first_logging_cycle(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    # set these two values so that performance metrics are created and sent to main
    file_writer_process._logging_level = logging.DEBUG
    file_writer_process._is_recording = True

    # set to 0 to speed up test
    file_writer_process._minimum_iteration_duration_seconds = 0

    invoke_process_run_and_check_errors(
        file_writer_process,
        num_iterations=file_writer_process._iterations_per_logging_cycle,
        perform_setup_before_loop=True,
    )
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    actual = drain_queue(to_main_queue)[-1]["message"]
    assert "percent_use_metrics" not in actual


@pytest.mark.parametrize("beta_2_mode", [True, False])
def test_FileWriterProcess__logs_metrics_of_data_recording_correctly(
    beta_2_mode, four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # set log level to debug performance metrics are created and sent to main
    file_writer_process._logging_level = logging.DEBUG

    # set to 0 to speed up test
    file_writer_process._minimum_iteration_duration_seconds = 0

    num_packets_to_send = 5  # arbitrary value
    if beta_2_mode:
        file_writer_process.set_beta_2_mode()
        populate_calibration_folder(file_writer_process)

        start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
        data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
        num_points_per_packet = data_packet["time_indices"].shape[0]
    else:
        start_recording_command = dict(GENERIC_BETA_1_START_RECORDING_COMMAND)
        data_packet = copy.deepcopy(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)
        num_points_per_packet = data_packet["data"].shape[1]

    # convert to regular dict and modify value
    start_recording_command["metadata_to_copy_onto_main_file_attributes"] = {
        **start_recording_command["metadata_to_copy_onto_main_file_attributes"],
        START_RECORDING_TIME_INDEX_UUID: 0,
    }

    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process, perform_setup_before_loop=True)
    # Tanner (9/10/20): remove start_recording confirmation
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    num_points_list = [num_points_per_packet] * num_packets_to_send
    for _ in range(num_packets_to_send):
        board_queues[0][0].put_nowait(data_packet)

    confirm_queue_is_eventually_of_size(board_queues[0][0], num_packets_to_send)
    expected_recording_durations = list(range(num_packets_to_send))
    perf_counter_vals = [
        0 if i % 2 == 0 else expected_recording_durations[i // 2] for i in range(num_packets_to_send * 2)
    ]
    mocker.patch.object(time, "perf_counter", autospec=True, side_effect=perf_counter_vals)

    invoke_process_run_and_check_errors(
        file_writer_process, num_iterations=file_writer_process._iterations_per_logging_cycle
    )
    confirm_queue_is_eventually_empty(board_queues[0][0])

    actual = drain_queue(to_main_queue)[-1]["message"]
    assert (
        "num_recorded_data_points_metrics" in actual
    ), f"Message did not contain key: 'num_recorded_data_points_metrics', Full message dict: {actual}"
    assert actual["num_recorded_data_points_metrics"] == create_metrics_stats(num_points_list)
    assert actual["recording_duration_metrics"] == create_metrics_stats(expected_recording_durations)

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


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
    assert actual["message"] == "File Writer Process beginning teardown at 2020-07-20 15:09:22.654321"


def test_FileWriterProcess_teardown_after_loop__does_not_call_close_all_files__when_not_recording(
    four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")

    fw_process.soft_stop()
    fw_process.run(perform_setup_before_loop=False, num_iterations=1)

    spied_close_all_files.assert_not_called()


@pytest.mark.parametrize(
    "test_start_recording_command,test_description",
    [
        (dict(GENERIC_BETA_1_START_RECORDING_COMMAND), "calls close with beta 1 files"),
        (dict(GENERIC_BETA_2_START_RECORDING_COMMAND), "calls close with beta 2 files"),
    ],
)
def test_FileWriterProcess_teardown_after_loop__calls_close_all_files__when_still_recording(
    test_start_recording_command, test_description, four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    if test_start_recording_command == GENERIC_BETA_2_START_RECORDING_COMMAND:
        fw_process.set_beta_2_mode()
        populate_calibration_folder(fw_process)

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_start_recording_command, from_main_queue
    )

    fw_process.soft_stop()
    fw_process.run(perform_setup_before_loop=False, num_iterations=1)

    spied_close_all_files.assert_called_once()


def test_FileWriterProcess_teardown_after_loop__beta_2_mode__destroys_temp_dir_for_calibration_recordings(
    four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    spied_cleanup = mocker.spy(fw_process._calibration_folder, "cleanup")  # pylint: disable=protected-access

    fw_process.soft_stop()
    fw_process.run(perform_setup_before_loop=False, num_iterations=1)
    spied_cleanup.assert_called_once()


@pytest.mark.parametrize(
    "test_start_recording_command,test_description",
    [
        (dict(GENERIC_BETA_1_START_RECORDING_COMMAND), "calls close with beta 1 files"),
        (dict(GENERIC_BETA_2_START_RECORDING_COMMAND), "calls close with beta 2 files"),
    ],
)
def test_FileWriterProcess_hard_stop__calls_close_all_files__when_still_recording(
    test_start_recording_command, test_description, four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    if test_start_recording_command == GENERIC_BETA_2_START_RECORDING_COMMAND:
        fw_process.set_beta_2_mode()
        populate_calibration_folder(fw_process)

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_start_recording_command, from_main_queue
    )
    fw_process.run(
        perform_setup_before_loop=False,
        num_iterations=1,
        perform_teardown_after_loop=False,
    )
    assert spied_close_all_files.call_count == 0  # confirm precondition
    fw_process.hard_stop()

    spied_close_all_files.assert_called_once()


@pytest.mark.parametrize("auto_upload", [True, False])
def test_FileWriterProcess_process_update_recording_name_command__handles_auto_upload_correctly(
    auto_upload, four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # mock so auto upload doesn't actually happen
    mocked_start_upload = mocker.patch.object(file_writer_process, "_start_new_file_upload", autospec=True)

    # complete a recording so the update_recording_name command can be processed correctly
    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"]["auto_upload_on_completion"] = auto_upload
    create_and_close_beta_1_h5_files(four_board_file_writer_process, update_user_settings_command)

    update_rec_name_command = dict(GENERIC_UPDATE_RECORDING_NAME_COMMAND)
    update_rec_name_command["default_name"] = file_writer_process._current_recording_dir
    put_object_into_queue_and_raise_error_if_eventually_still_empty(update_rec_name_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    assert mocked_start_upload.call_count == int(auto_upload)

    new_rec_name = GENERIC_UPDATE_RECORDING_NAME_COMMAND["new_name"]

    if auto_upload:
        confirm_queue_is_eventually_of_size(to_main_queue, 2)
        auto_upload_confirmation = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert auto_upload_confirmation == {
            "communication_type": "log",
            "log_level": 20,
            "message": f"Started auto upload for file {new_rec_name}",
        }
    else:
        confirm_queue_is_eventually_of_size(to_main_queue, 1)

    update_rec_name_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert update_rec_name_response == {
        "command": "update_recording_name",
        "communication_type": "command_receipt",
        "recording_path": os.path.join(file_writer_process._file_directory, new_rec_name),
    }


def test_FileWriterProcess_process_update_recording_name_command__renames_recording_dir_and_h5_files_after_all_files_are_closed(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    spied_rename = mocker.spy(os, "rename")

    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"]["auto_upload_on_completion"] = False
    create_and_close_beta_1_h5_files(four_board_file_writer_process, update_user_settings_command)
    assert file_writer_process.get_stop_recording_timestamps()[0] is not None
    assert file_writer_process._is_finalizing_files_after_recording() is False

    # needs to be the same name to pass conditional
    update_recording_name_command = dict(GENERIC_UPDATE_RECORDING_NAME_COMMAND)
    update_recording_name_command["default_name"] = file_writer_process.get_sub_dir_name()

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        update_recording_name_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    # called once for directory and once for well A1
    assert len(spied_rename.call_args_list) == 2
    new_sub_dir_name = file_writer_process.get_sub_dir_name()
    assert new_sub_dir_name == update_recording_name_command["new_name"]

    drain_queue(to_main_queue)


def test_FileWriterProcess_process_update_recording_name_command__will_not_rename_if_directory_does_not_exist(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    update_recording_name_command = dict(GENERIC_UPDATE_RECORDING_NAME_COMMAND)
    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"]["auto_upload_on_completion"] = False
    update_user_settings_command["config_settings"]["auto_delete_local_files"] = True

    create_and_close_beta_1_h5_files(four_board_file_writer_process, update_user_settings_command)
    assert file_writer_process.get_stop_recording_timestamps()[0] is not None
    assert file_writer_process._is_finalizing_files_after_recording() is False

    # needs to be the same name to pass conditional
    sub_dir_name = file_writer_process.get_sub_dir_name()
    update_recording_name_command["default_name"] = sub_dir_name
    mocker.patch.object(os.path, "exists", return_value=False)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        update_recording_name_command, from_main_queue
    )
    invoke_process_run_and_check_errors(file_writer_process, 1)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    drain_queue(to_main_queue)


def test_FileWriterProcess_hard_stop__closes_all_beta_1_files_after_stop_recording_before_all_files_are_finalized__and_files_can_be_opened_after_process_stops(
    four_board_file_writer_process, mocker
):
    expected_timestamp = "2020_02_09_190935"
    expected_plate_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]

    fw_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    tmp_dir = four_board_file_writer_process["file_dir"]

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(GENERIC_BETA_1_START_RECORDING_COMMAND), from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)

    # fill files with data
    start_timepoint = GENERIC_BETA_1_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    test_data = np.array([[start_timepoint], [0]], dtype=np.int32)
    for i in range(24):
        tissue_data_packet = {
            "well_index": i,
            "is_reference_sensor": False,
            "data": test_data,
        }
        board_queues[0][0].put_nowait(tissue_data_packet)
    for i in range(6):
        ref_data_packet = {
            "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[i],
            "is_reference_sensor": True,
            "data": test_data,
        }
        board_queues[0][0].put_nowait(ref_data_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], 30)

    # set to 0 to speed up test
    fw_process._minimum_iteration_duration_seconds = 0  # pylint: disable=protected-access
    invoke_process_run_and_check_errors(fw_process, num_iterations=30)
    confirm_queue_is_eventually_empty(board_queues[0][0])

    stop_recording_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    assert spied_close_all_files.call_count == 0  # confirm precondition
    fw_process.hard_stop()
    spied_close_all_files.assert_called_once()

    # confirm files can be opened and files contains at least one piece of metadata and the correct tissue data
    for row_idx in range(4):
        for col_idx in range(6):
            well_name = WELL_DEF_24.get_well_name_from_row_and_column(row_idx, col_idx)
            with h5py.File(
                os.path.join(
                    tmp_dir,
                    f"{expected_plate_barcode}__{expected_timestamp}",
                    f"{expected_plate_barcode}__{expected_timestamp}__{well_name}.h5",
                ),
                "r",
            ) as this_file:
                assert (
                    str(START_RECORDING_TIME_INDEX_UUID) in this_file.attrs
                ), f"START_RECORDING_TIME_INDEX_UUID missing for Well {well_name}"
                assert get_tissue_dataset_from_file(this_file).shape == (
                    test_data.shape[1],
                ), f"Incorrect tissue data shape for Well {well_name}"


def test_FileWriterProcess_hard_stop__closes_all_beta_2_files_after_stop_recording_before_all_files_are_finalized__and_files_can_be_opened_after_process_stops(
    four_board_file_writer_process, mocker
):
    expected_timestamp = "2020_02_09_190359"
    expected_plate_barcode = GENERIC_BETA_2_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]

    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    tmp_dir = four_board_file_writer_process["file_dir"]

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(GENERIC_BETA_2_START_RECORDING_COMMAND), from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)

    # fill files with data
    test_num_data_points = 50
    start_timepoint = GENERIC_BETA_2_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    test_data = np.zeros(test_num_data_points, dtype=np.uint16)
    data_packet = {
        "data_type": "magnetometer",
        "time_indices": np.arange(start_timepoint, start_timepoint + test_num_data_points, dtype=np.uint64),
        "is_first_packet_of_stream": False,
    }
    for well_idx in range(24):
        channel_dict = {
            "time_offsets": np.zeros(
                (SERIAL_COMM_NUM_SENSORS_PER_WELL, test_num_data_points), dtype=np.uint16
            ),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: test_data,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: test_data,
        }
        data_packet[well_idx] = channel_dict
    board_queues[0][0].put_nowait(data_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], 1)

    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(board_queues[0][0])

    stop_recording_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    assert spied_close_all_files.call_count == 0  # confirm precondition
    fw_process.hard_stop()
    spied_close_all_files.assert_called_once()

    # confirm files can be opened and files contains at least one piece of metadata and the correct tissue data
    for row_idx in range(4):
        for col_idx in range(6):
            well_name = WELL_DEF_24.get_well_name_from_row_and_column(row_idx, col_idx)
            with h5py.File(
                os.path.join(
                    tmp_dir,
                    f"{expected_plate_barcode}__{expected_timestamp}",
                    f"{expected_plate_barcode}__{expected_timestamp}__{well_name}.h5",
                ),
                "r",
            ) as this_file:
                assert (
                    str(START_RECORDING_TIME_INDEX_UUID) in this_file.attrs
                ), f"START_RECORDING_TIME_INDEX_UUID missing for Well {well_name}"
                assert get_time_index_dataset_from_file(this_file).shape == (
                    test_num_data_points,
                ), f"Incorrect time index data shape for Well {well_name}"
                assert get_time_offset_dataset_from_file(this_file).shape == (
                    SERIAL_COMM_NUM_SENSORS_PER_WELL,
                    test_num_data_points,
                ), f"Incorrect time offset data shape for Well {well_name}"
                assert get_tissue_dataset_from_file(this_file).shape == (
                    SERIAL_COMM_NUM_DATA_CHANNELS,
                    test_num_data_points,
                ), f"Incorrect tissue data shape for Well {well_name}"


def test_FileWriterProcess__ignores_commands_from_main_while_finalizing_beta_1_files_after_stop_recording(
    four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    spied_process_update_name_command = mocker.patch.object(
        fw_process, "_process_update_name_command", autospec=True
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(GENERIC_BETA_1_START_RECORDING_COMMAND), from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)

    # fill files with data
    start_timepoint = GENERIC_BETA_1_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
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
    confirm_queue_is_eventually_of_size(board_queues[0][0], 30)

    # set to 0 to speed up test
    fw_process._minimum_iteration_duration_seconds = 0  # pylint: disable=protected-access
    invoke_process_run_and_check_errors(fw_process, num_iterations=30)
    confirm_queue_is_eventually_empty(board_queues[0][0])

    stop_recording_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    # check that command is ignored
    # Lucy (6/15/22) this is the expected next command after stop recording to rename and kick off upload thread
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_UPDATE_RECORDING_NAME_COMMAND, from_main_queue
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
    confirm_queue_is_eventually_of_size(board_queues[0][0], 30)

    invoke_process_run_and_check_errors(fw_process, num_iterations=30)
    confirm_queue_is_eventually_empty(board_queues[0][0])
    # check command is still ignored
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    # now all files should be finalized, confirm command is now processed
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(from_main_queue)
    spied_process_update_name_command.assert_called_once()

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


def test_FileWriterProcess__ignores_commands_from_main_while_finalizing_beta_2_files_after_stop_recording(
    four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    spied_process_update_name_command = mocker.patch.object(
        fw_process, "_process_update_name_command", autospec=True
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(GENERIC_BETA_2_START_RECORDING_COMMAND), from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)

    # fill files with data
    num_data_points = 100
    start_timepoint = GENERIC_BETA_2_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    data_packet = {
        "data_type": "magnetometer",
        "time_indices": np.arange(start_timepoint, start_timepoint + num_data_points, dtype=np.uint64),
        "is_first_packet_of_stream": False,
    }
    for well_idx in range(24):
        channel_dict = {
            "time_offsets": np.zeros((SERIAL_COMM_NUM_SENSORS_PER_WELL, num_data_points), dtype=np.uint16),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: np.zeros(num_data_points, dtype=np.uint16),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: np.zeros(num_data_points, dtype=np.uint16),
        }
        data_packet[well_idx] = channel_dict
    board_queues[0][0].put_nowait(data_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], 1)
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(board_queues[0][0])

    stop_recording_command = dict(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    # check that command is ignored
    # Lucy (6/15/22) this is the expected next command after stop recording to rename and kick off upload thread
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_UPDATE_RECORDING_NAME_COMMAND, from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    # add data past stop point so files will be finalized
    stop_timepoint = GENERIC_STOP_RECORDING_COMMAND["timepoint_to_stop_recording_at"]
    final_data_packet = copy.deepcopy(data_packet)
    final_data_packet["time_indices"] = np.arange(
        stop_timepoint, stop_timepoint + num_data_points, dtype=np.uint64
    )
    board_queues[0][0].put_nowait(final_data_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], 1)
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(board_queues[0][0])
    # check command is still ignored
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    # now all files should be finalized, confirm command is now processed
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(from_main_queue)
    spied_process_update_name_command.assert_called_once()
    # also confirm message sent to indicate all files have been finalized
    assert drain_queue(to_main_queue)[-2] == {
        "communication_type": "file_finalized",
        "message": "all_finals_finalized",
    }

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


@pytest.mark.slow
@pytest.mark.timeout(10)
@pytest.mark.parametrize(
    "test_start_recording_command,test_description",
    [
        (dict(GENERIC_BETA_1_START_RECORDING_COMMAND), "tears down correctly with beta 1 files"),
        (dict(GENERIC_BETA_2_START_RECORDING_COMMAND), "tears down correctly with beta 2 files"),
    ],
)
def test_FileWriterProcess_teardown_after_loop__can_teardown_process_while_recording__and_log_stop_recording_message(
    test_start_recording_command,
    test_description,
    running_four_board_file_writer_process,
    mocker,
    patch_print,
):
    fw_process = running_four_board_file_writer_process["fw_process"]
    to_main_queue = running_four_board_file_writer_process["to_main_queue"]
    from_main_queue = running_four_board_file_writer_process["from_main_queue"]

    if test_start_recording_command == GENERIC_BETA_2_START_RECORDING_COMMAND:
        fw_process.set_beta_2_mode()

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_start_recording_command, from_main_queue
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
