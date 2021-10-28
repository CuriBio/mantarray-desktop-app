# -*- coding: utf-8 -*-
import copy
import logging
from multiprocessing import Queue
import os
import shutil
from statistics import stdev
import tempfile
import time

from freezegun import freeze_time
import h5py
from mantarray_desktop_app import file_uploader
from mantarray_desktop_app import FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
from mantarray_desktop_app import FileWriterProcess
from mantarray_desktop_app import get_data_slice_within_timepoints
from mantarray_desktop_app import get_time_index_dataset_from_file
from mantarray_desktop_app import get_time_offset_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import MantarrayH5FileCreator
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import UnrecognizedCommandFromMainToFileWriterError
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
import numpy as np
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import fixture_runnable_four_board_file_writer_process
from ..fixtures_file_writer import fixture_running_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_BETA_1_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_NUM_CHANNELS_ENABLED
from ..fixtures_file_writer import GENERIC_NUM_SENSORS_ENABLED
from ..fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_UPDATE_CUSTOMER_SETTINGS
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
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")
    FileWriterProcess((), Queue(), Queue(), error_queue, {})
    mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


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


def test_FileWriterProcess__updates_customer_settings_and_responds_to_main_queue(
    four_board_file_writer_process, mocker
):

    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    spied_to_main = mocker.spy(to_main_queue, "put_nowait")

    invoke_process_run_and_check_errors(file_writer_process)
    spied_to_main.assert_called_with(
        {
            "communication_type": "command_receipt",
            "command": "update_customer_settings",
        }
    )


@pytest.mark.parametrize(
    "auto_delete, auto_upload",
    [
        (True, False),
        (False, True),
        (False, False),
    ],
)
def test_FileWriterProcess__correctly_handles_file_upload_state_and_auto_delete_state_when_starting_new_upload_threads(
    four_board_file_writer_process, auto_delete, auto_upload, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    mocked_delete_files = mocker.patch.object(file_writer_process, "_delete_local_files", autospec=True)
    spied_thread_start = mocker.patch.object(file_uploader.ErrorCatchingThread, "start", autospec=True)
    mocker.patch.object(file_writer_process, "_check_upload_statuses", autospec=True)

    mocked_delete_files.assert_not_called()
    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_delete_local_files"] = auto_delete
    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_upload_on_completion"] = auto_upload
    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    assert (len(mocked_delete_files.call_args_list) > 0) is auto_delete
    assert (len(spied_thread_start.call_args_list) > 0) is auto_upload


@pytest.mark.parametrize(
    "move_called, thread_error",
    [(True, False), (False, True)],
)
def test_FileWriterProcess__exits_status_function_when_newly_failed_files_errors_or_passes(
    four_board_file_writer_process, move_called, thread_error, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]

    mocked_shutil = mocker.patch.object(shutil, "move", autospec=True)
    mocked_thread = mocker.patch.object(file_uploader, "ErrorCatchingThread", autospec=True)
    mocker.patch.object(mocked_thread.name, "is_alive", autospec=True, return_value=False)
    mocker.patch.object(mocked_thread.name, "errors", autospec=True, return_value=thread_error)
    mocker.patch.object(mocked_thread.name, "get_upload_status", autospec=True)
    mocker.patch.object(mocked_thread.name, "join", autospec=True)

    thread_dict = {
        "failed_upload": True,
        "customer_account_id": "test_customer_id",
        "thread": mocked_thread.name,
        "auto_delete": False,
        "file_name": "test_filename",
    }

    file_writer_process._upload_threads_container.append(thread_dict)  # pylint: disable=protected-access
    file_writer_process._check_upload_statuses()  # pylint: disable=protected-access

    assert (len(mocked_shutil.call_args_list) > 0) is move_called
    assert len(file_writer_process._upload_threads_container) == 0  # pylint: disable=protected-access


def test_FileWriterProcess__kicks_off_upload_thread_and_appends_to_container_with_specified_dict_values(
    four_board_file_writer_process, mocker
):

    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_upload_on_completion"] = True
    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_delete_local_files"] = False
    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)

    mocked_check_status = mocker.patch.object(file_writer_process, "_check_upload_statuses", auto_spec=True)
    mocker.patch.object(file_uploader, "ErrorCatchingThread", autospec=True)

    invoke_process_run_and_check_errors(file_writer_process)
    # pylint: disable=protected-access
    assert (
        file_writer_process._upload_threads_container[0]["customer_account_id"] == "test_customer_id"
    )  # pylint: disable=protected-access
    assert (
        file_writer_process._upload_threads_container[0]["failed_upload"] is False
    )  # pylint: disable=protected-access
    assert (
        file_writer_process._upload_threads_container[0]["auto_delete"] is False
    )  # pylint: disable=protected-access
    assert (
        file_writer_process._upload_threads_container[0]["file_name"] == ""
    )  # pylint: disable=protected-access
    mocked_check_status.assert_called_once()


def test_FileWriterProcess__correctly_kicks_off_upload_thread_on_setup_and_appends_to_container_with_specified_dict_values(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)

    mocker.patch.object(os, "listdir", return_value=["73f52be0-368c-42d8-a1fd-660d49ba5604"])
    mocker.patch.object(os.path, "exists", autospec=True, return_value=True)
    mocker.patch.object(file_uploader, "ErrorCatchingThread", autospec=True)

    file_writer_process._process_failed_upload_files_on_setup()  # pylint: disable=protected-access
    # pylint: disable=protected-access
    assert (
        file_writer_process._upload_threads_container[0]["customer_account_id"]
        == "73f52be0-368c-42d8-a1fd-660d49ba5604"
    )  # pylint: disable=protected-access
    assert (
        file_writer_process._upload_threads_container[0]["failed_upload"] is True
    )  # pylint: disable=protected-access
    assert (
        file_writer_process._upload_threads_container[0]["auto_delete"] is False
    )  # pylint: disable=protected-access
    assert (
        file_writer_process._upload_threads_container[0]["file_name"]
        == "73f52be0-368c-42d8-a1fd-660d49ba5604"
    )  # pylint: disable=protected-access


def test_FileWriterProcess__processes_failed_upload_and_moves_zip_file_to_static_dir_w_cust_id(
    mocker, four_board_file_writer_process
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    spied_shutil = mocker.patch.object(shutil, "move", autospec=True)

    mocker.patch.object(os.path, "join", autospec=True)
    mocker.patch.object(os, "makedirs", autospec=True)
    mocker.patch.object(file_uploader.ErrorCatchingThread, "is_alive", autospec=True, return_value=False)
    mocker.patch.object(os.path, "exists", autospec=True, return_value=True)

    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_delete_local_files"] = False
    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_upload_on_completion"] = True
    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    spied_shutil.assert_called_once()


def test_FileWriterProcess__prevent_any_uploads_with_no_stored_customer_settings(
    mocker, four_board_file_writer_process
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    spied_auto_delete = mocker.patch.object(file_writer_process, "_delete_local_files", autospec=True)
    spied_thread_start = mocker.patch.object(file_uploader.ErrorCatchingThread, "start", autospec=True)
    spied_thread_join = mocker.patch.object(file_uploader.ErrorCatchingThread, "join", autospec=True)

    file_writer_process._stored_customer_settings = None  # pylint: disable=protected-access

    file_writer_process._start_new_file_uploads()  # pylint: disable=protected-access
    spied_auto_delete.assert_not_called()
    spied_thread_start.assert_not_called()

    file_writer_process._check_upload_statuses()  # pylint: disable=protected-access
    spied_thread_join.assert_not_called()


@pytest.mark.parametrize(
    "upload_status, auto_delete",
    [("__upload failed", True), ("_upload complete", False)],
)
def test_FileWriterProcess__correctly_handles_when_file_upload_is_successful_and_auto_delete_is_false(
    four_board_file_writer_process, upload_status, auto_delete, mocker
):

    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    spied_delete_files = mocker.spy(file_writer_process, "_delete_local_files")
    mocker.patch.object(os, "listdir", return_value=["test_file"])
    mocker.patch.object(os, "remove", autospec=True)
    mocker.patch.object(os, "rmdir", autospec=True)
    mocker.patch.object(shutil, "move", autospec=True)
    mocker.patch.object(file_uploader.ErrorCatchingThread, "errors", autospec=True, return_value=False)
    mocker.patch.object(file_uploader.ErrorCatchingThread, "is_alive", autospec=True, return_value=False)
    mocker.patch.object(
        file_uploader.ErrorCatchingThread, "get_upload_status", autospec=True, return_value="upload complete"
    )

    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_delete_local_files"] = auto_delete
    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_upload_on_completion"] = True
    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    assert (len(spied_delete_files.call_args_list) > 0) is auto_delete
    assert len(file_writer_process._upload_threads_container) == 0  # pylint: disable=protected-access


def test_FileWriterProcess__setup_before_loop__calls_super(four_board_file_writer_process, mocker):
    # pylint: disable=protected-access

    spied_setup = mocker.spy(InfiniteProcess, "_setup_before_loop")
    spied_uploader = mocker.spy(file_uploader, "uploader")
    file_writer_process = four_board_file_writer_process["fw_process"]
    mocked_file_upload = mocker.patch.object(
        file_writer_process, "_process_failed_upload_files_on_setup", autospec=True
    )

    invoke_process_run_and_check_errors(file_writer_process, perform_setup_before_loop=True)
    spied_setup.assert_called_once()
    spied_uploader.assert_not_called()

    invoke_process_run_and_check_errors(file_writer_process, perform_setup_before_loop=True)
    assert len(mocked_file_upload.call_args_list) == 2


@pytest.mark.parametrize(
    "upload_status, thread_error",
    [("__upload failed", True), ("__upload complete", False)],
)
def test_FileWriterProcess__successfully_updates_upload_status_for_files_if_stored_cust_settings_with_or_without_error(
    four_board_file_writer_process, upload_status, thread_error, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    mocker.patch.object(file_writer_process, "_process_new_failed_upload_files", autospec=True)
    mocker.patch.object(file_uploader.ErrorCatchingThread, "errors", autospec=True, return_value=thread_error)
    mocker.patch.object(file_uploader.ErrorCatchingThread, "is_alive", autospec=True, return_value=False)
    mocker.patch.object(
        file_uploader.ErrorCatchingThread, "get_upload_status", autospec=True, return_value="upload complete"
    )

    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_upload_on_completion"] = True
    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_delete_local_files"] = False
    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    assert file_writer_process._upload_status == upload_status  # pylint: disable=protected-access


def test_FileWriterProcess__does_not_join_upload_thread_if_alive(four_board_file_writer_process, mocker):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    spied_join = mocker.spy(file_uploader.ErrorCatchingThread, "join")
    mocker.patch.object(os.path, "exists", autospec=True, return_value=True)
    mocker.patch.object(os, "listdir", autospec=True, return_value=["73f52be0-368c-42d8-a1fd-660d49ba5604"])

    mocker.patch.object(file_uploader.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_upload_on_completion"] = True
    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_delete_local_files"] = False
    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    spied_join.assert_not_called()


@pytest.mark.timeout(4)
def test_FileWriterProcess__raises_error_if_unrecognized_command_from_main(
    four_board_file_writer_process, mocker, patch_print
):
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
    assert isinstance(raised_error, UnrecognizedCommandFromMainToFileWriterError) is True
    err_str = str(raised_error)
    assert "do the hokey pokey" in err_str


def test_FileWriterProcess_soft_stop_not_allowed_if_command_from_main_still_in_queue(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # The first communication will be processed, but if there is a second one in the queue then the soft stop should be disabled
    this_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
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
        (GENERIC_BETA_1_START_RECORDING_COMMAND, "closes correctly with beta 1 files"),
        (GENERIC_BETA_2_START_RECORDING_COMMAND, "closes correctly with beta 2 files"),
    ],
)
def test_FileWriterProcess__close_all_files(
    test_start_recording_command, test_description, four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    if test_start_recording_command == GENERIC_BETA_2_START_RECORDING_COMMAND:
        file_writer_process.set_beta_2_mode()

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

    expected_iteration_dur = 0.001 * 10 ** 9
    expected_idle_time = expected_iteration_dur * FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
    expected_start_timepoint = 0
    expected_stop_timepoint = 2 * expected_iteration_dur * FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
    expected_latest_percent_use = 100 * (
        1 - expected_idle_time / (expected_stop_timepoint - expected_start_timepoint)
    )
    expected_percent_use_values = [27.4, 42.8, expected_latest_percent_use]
    expected_longest_iterations = [
        expected_iteration_dur for _ in range(file_writer_process.num_longest_iterations)
    ]

    perf_counter_vals = []
    for _ in range(FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES - 1):
        perf_counter_vals.append(0)
        perf_counter_vals.append(expected_iteration_dur)
    perf_counter_vals.append(0)
    perf_counter_vals.append(expected_stop_timepoint)
    perf_counter_vals.append(0)
    mocker.patch.object(time, "perf_counter_ns", autospec=True, side_effect=perf_counter_vals)

    file_writer_process._idle_iteration_time_ns = expected_iteration_dur  # pylint: disable=protected-access
    file_writer_process._minimum_iteration_duration_seconds = (  # pylint: disable=protected-access
        2 * expected_iteration_dur / (10 ** 9)
    )
    file_writer_process._start_timepoint_of_last_performance_measurement = (  # pylint: disable=protected-access
        expected_start_timepoint
    )
    file_writer_process._percent_use_values = expected_percent_use_values[  # pylint: disable=protected-access
        :-1
    ]

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
        "mean": round(sum(expected_percent_use_values) / len(expected_percent_use_values), 6),
    }
    num_longest_iterations = file_writer_process.num_longest_iterations
    assert actual["longest_iterations"] == expected_longest_iterations[-num_longest_iterations:]
    assert "idle_iteration_time_ns" not in actual
    assert "start_timepoint_of_measurements" not in actual


@pytest.mark.parametrize(
    "test_data_packet,test_description",
    [
        (SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0, "does not log recording metrics with beta 1 data"),
        (SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS, "does not log recording metrics with beta 2 data"),
    ],
)
def test_FileWriterProcess__does_not_include_recording_metrics_in_performance_metrics_when_not_recording(
    test_data_packet, test_description, four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    incoming_data_queue = four_board_file_writer_process["board_queues"][0][0]

    if test_data_packet == SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS:
        file_writer_process.set_beta_2_mode()

    # add data packets
    num_packets_to_send = 3  # send arbitrary number of packets
    for _ in range(num_packets_to_send):
        incoming_data_queue.put_nowait(test_data_packet)
    confirm_queue_is_eventually_of_size(incoming_data_queue, num_packets_to_send)
    # set to 0 to speed up test
    file_writer_process._minimum_iteration_duration_seconds = 0  # pylint: disable=protected-access
    # get performance metrics dict
    invoke_process_run_and_check_errors(
        file_writer_process,
        num_iterations=FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES,
        perform_setup_before_loop=True,
    )
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual = actual["message"]
    # make sure recording metrics not present
    assert "num_recorded_data_points_metrics" not in actual
    assert "recording_duration_metrics" not in actual

    # Tanner (6/1/21): avoid BrokenPipeErrors
    drain_queue(four_board_file_writer_process["board_queues"][0][1])


@pytest.mark.slow
@pytest.mark.timeout(200)
def test_FileWriterProcess__does_not_log_percent_use_metrics_in_first_logging_cycle(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    # set to 0 to speed up test
    file_writer_process._minimum_iteration_duration_seconds = 0  # pylint: disable=protected-access

    invoke_process_run_and_check_errors(
        file_writer_process,
        num_iterations=FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES,
        perform_setup_before_loop=True,
    )
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual = actual["message"]
    assert "percent_use_metrics" not in actual


@pytest.mark.slow
@pytest.mark.parametrize(
    "test_beta_version,test_description",
    [
        (1, "logs correctly with beta 1 data"),
        (2, "logs correctly with beta 2 data"),
    ],
)
def test_FileWriterProcess__logs_metrics_of_data_recording_correctly(
    test_beta_version, test_description, four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # set to 0 to speed up test
    file_writer_process._minimum_iteration_duration_seconds = 0  # pylint: disable=protected-access

    num_packets_to_send = 5  # arbitrary value
    if test_beta_version == 1:
        start_recording_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
        data_packet = copy.deepcopy(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)
        num_points_per_packet = data_packet["data"].shape[1]
    else:
        file_writer_process.set_beta_2_mode()
        start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
        data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
        num_points_per_packet = data_packet["time_indices"].shape[0]

    start_recording_command["metadata_to_copy_onto_main_file_attributes"][START_RECORDING_TIME_INDEX_UUID] = 0
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
        file_writer_process, num_iterations=FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
    )
    confirm_queue_is_eventually_empty(board_queues[0][0])

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
        "mean": round(sum(expected_recording_durations) / len(expected_recording_durations), 6),
    }

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
        (GENERIC_BETA_1_START_RECORDING_COMMAND, "calls close with beta 1 files"),
        (GENERIC_BETA_2_START_RECORDING_COMMAND, "calls close with beta 2 files"),
    ],
)
def test_FileWriterProcess_teardown_after_loop__calls_close_all_files__when_still_recording(
    test_start_recording_command, test_description, four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    if test_start_recording_command == GENERIC_BETA_2_START_RECORDING_COMMAND:
        fw_process.set_beta_2_mode()

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_start_recording_command, from_main_queue
    )

    fw_process.soft_stop()
    fw_process.run(perform_setup_before_loop=False, num_iterations=1)

    spied_close_all_files.assert_called_once()


@pytest.mark.parametrize(
    "test_start_recording_command,test_description",
    [
        (GENERIC_BETA_1_START_RECORDING_COMMAND, "calls close with beta 1 files"),
        (GENERIC_BETA_2_START_RECORDING_COMMAND, "calls close with beta 2 files"),
    ],
)
def test_FileWriterProcess_hard_stop__calls_close_all_files__when_still_recording(
    test_start_recording_command, test_description, four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    if test_start_recording_command == GENERIC_BETA_2_START_RECORDING_COMMAND:
        fw_process.set_beta_2_mode()

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


def test_FileWriterProcess_hard_stop__closes_all_beta_1_files_after_stop_recording_before_all_files_are_finalized__and_files_can_be_opened_after_process_stops(
    four_board_file_writer_process, mocker
):
    expected_timestamp = "2020_02_09_190935"
    expected_barcode = GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]

    fw_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    tmp_dir = four_board_file_writer_process["file_dir"]

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_BETA_1_START_RECORDING_COMMAND, from_main_queue
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

    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
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
                    f"{expected_barcode}__{expected_timestamp}",
                    f"{expected_barcode}__{expected_timestamp}__{well_name}.h5",
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
    expected_barcode = GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]

    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    tmp_dir = four_board_file_writer_process["file_dir"]

    spied_close_all_files = mocker.spy(fw_process, "close_all_files")

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_BETA_2_START_RECORDING_COMMAND, from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)

    # fill files with data
    test_num_data_points = 50
    start_timepoint = GENERIC_BETA_2_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    test_data = np.zeros(test_num_data_points, dtype=np.int16)
    data_packet = {
        "data_type": "magnetometer",
        "time_indices": np.arange(start_timepoint, start_timepoint + test_num_data_points, dtype=np.uint64),
        "is_first_packet_of_stream": False,
    }
    for well_idx in range(24):
        channel_dict = {
            "time_offsets": np.zeros((GENERIC_NUM_SENSORS_ENABLED, test_num_data_points), dtype=np.uint16),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: test_data,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: test_data,
        }
        data_packet[well_idx] = channel_dict
    board_queues[0][0].put_nowait(data_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], 1)

    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(board_queues[0][0])

    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
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
                    f"{expected_barcode}__{expected_timestamp}",
                    f"{expected_barcode}__{expected_timestamp}__{well_name}.h5",
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
                    GENERIC_NUM_SENSORS_ENABLED,
                    test_num_data_points,
                ), f"Incorrect time offset data shape for Well {well_name}"
                assert get_tissue_dataset_from_file(this_file).shape == (
                    GENERIC_NUM_CHANNELS_ENABLED,
                    test_num_data_points,
                ), f"Incorrect tissue data shape for Well {well_name}"


def test_FileWriterProcess__ignores_commands_from_main_while_finalizing_beta_1_files_after_stop_recording(
    four_board_file_writer_process, mocker
):
    fw_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_BETA_1_START_RECORDING_COMMAND, from_main_queue
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

    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    # check that command is ignored # Tanner (1/12/21): no particular reason this command needs to be update_directory, but it's easy to test if this gets processed
    expected_new_dir = "dummy_dir"
    update_dir_command = {
        "command": "update_directory",
        "new_directory": expected_new_dir,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(update_dir_command, from_main_queue)
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
    assert fw_process.get_file_directory() == expected_new_dir

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


def test_FileWriterProcess__ignores_commands_from_main_while_finalizing_beta_2_files_after_stop_recording(
    four_board_file_writer_process, mocker
):

    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        GENERIC_BETA_2_START_RECORDING_COMMAND, from_main_queue
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
            "time_offsets": np.zeros((GENERIC_NUM_SENSORS_ENABLED, num_data_points), dtype=np.uint16),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: np.zeros(num_data_points, dtype=np.int16),
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: np.zeros(num_data_points, dtype=np.int16),
        }
        data_packet[well_idx] = channel_dict
    board_queues[0][0].put_nowait(data_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], 1)
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(board_queues[0][0])

    stop_recording_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    # check that command is ignored # Tanner (1/12/21): no particular reason this command needs to be update_directory, but it's easy to test if this gets processed
    expected_new_dir = "dummy_dir"
    update_dir_command = {
        "command": "update_directory",
        "new_directory": expected_new_dir,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(update_dir_command, from_main_queue)
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
    assert fw_process.get_file_directory() == expected_new_dir

    # Tanner (3/8/21): Prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


@pytest.mark.slow
@pytest.mark.timeout(10)
@pytest.mark.parametrize(
    "test_start_recording_command,test_description",
    [
        (GENERIC_BETA_1_START_RECORDING_COMMAND, "tears down correctly with beta 1 files"),
        (GENERIC_BETA_2_START_RECORDING_COMMAND, "tears down correctly with beta 2 files"),
    ],
)
def test_FileWriterProcess_teardown_after_loop__can_teardown_process_while_recording__and_log_stop_recording_message(
    test_start_recording_command, test_description, running_four_board_file_writer_process, mocker
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
