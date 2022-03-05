# -*- coding: utf-8 -*-
import copy
import json
import os
import shutil

from mantarray_desktop_app import worker_thread
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import create_and_close_beta_1_h5_files
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_UPDATE_CUSTOMER_SETTINGS
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_patch_print,
    fixture_four_board_file_writer_process,
]


def test_FileWriterProcess__updates_customer_settings_and_responds_to_main_queue(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    invoke_process_run_and_check_errors(file_writer_process)
    assert file_writer_process.get_customer_settings() == GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]

    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == {
        "communication_type": "command_receipt",
        "command": "update_customer_settings",
    }


def test_FileWriterProcess__does_not_start_upload_thread_after_all_calibration_files_finalized(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]

    mocker.patch.object(
        file_writer_process,
        "get_recording_finalization_statuses",
        autospec=True,
        return_value=(({0: True},), ({0: True},)),
    )
    # mock so the functions don't actually run
    mocked_start_upload = mocker.patch.object(file_writer_process, "_start_new_file_upload", autospec=True)
    # mocker.patch.object(file_writer, "_finalize_file", autospec=True)

    file_writer_process._open_files[0][0] = mocker.MagicMock()  # pylint: disable=protected-access
    file_writer_process._customer_settings = {"key": "val"}
    file_writer_process._is_recording_calibration = True  # pylint: disable=protected-access

    file_writer_process._finalize_completed_files()  # pylint: disable=protected-access
    mocked_start_upload.assert_not_called()


@pytest.mark.parametrize(
    "move_called, thread_error",
    [(True, False), (False, True)],
)
def test_FileWriterProcess__exits_status_function_correctly_when_previously_failed_files_errors_or_passes(
    four_board_file_writer_process, move_called, thread_error, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]

    mocked_shutil = mocker.patch.object(shutil, "move", autospec=True)

    mocked_thread = mocker.patch.object(worker_thread, "ErrorCatchingThread", autospec=True)
    mocker.patch.object(mocked_thread.name, "is_alive", autospec=True, return_value=False)
    mocker.patch.object(mocked_thread.name, "get_error", autospec=True, return_value="error")
    mocker.patch.object(mocked_thread.name, "errors", autospec=True, return_value=thread_error)
    mocker.patch.object(mocked_thread.name, "join", autospec=True)

    thread_dict = {
        "failed_upload": True,
        "customer_account_id": "test_customer_id",
        "user_account_id": "test_user",
        "thread": mocked_thread.name,
        "auto_delete": False,
        "file_name": "test_filename",
    }

    file_writer_process.get_upload_threads_container().append(thread_dict)
    file_writer_process._check_upload_statuses()  # pylint: disable=protected-access

    assert mocked_shutil.call_count == int(move_called)
    assert len(file_writer_process.get_upload_threads_container()) == 0


@pytest.mark.parametrize("paths_exist", [True, False])
def test_FileWriterProcess__exits_status_function_correctly_when_newly_failed_files_fail(
    four_board_file_writer_process, mocker, paths_exist
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)

    invoke_process_run_and_check_errors(file_writer_process)

    mocked_shutil = mocker.patch.object(shutil, "move", autospec=True)
    mocked_test = mocker.patch.object(os.path, "exists", autospec=True, return_value=paths_exist)
    mocked_makedirs = mocker.patch.object(os, "makedirs", autospec=True)

    mocked_thread = mocker.patch.object(worker_thread, "ErrorCatchingThread", autospec=True)
    mocker.patch.object(mocked_thread.name, "is_alive", autospec=True, return_value=False)
    mocker.patch.object(mocked_thread.name, "get_error", autospec=True, return_value="error")
    mocker.patch.object(mocked_thread.name, "errors", autospec=True, return_value=True)
    mocker.patch.object(mocked_thread.name, "join", autospec=True)

    thread_dict = {
        "failed_upload": False,
        "customer_account_id": "test_customer_id",
        "user_account_id": "test_user",
        "thread": mocked_thread.name,
        "auto_delete": False,
        "file_name": "test_filename",
    }

    file_writer_process.get_upload_threads_container().append(thread_dict)
    file_writer_process._check_upload_statuses()  # pylint: disable=protected-access

    assert mocked_shutil.call_count == int(paths_exist)
    assert (mocked_makedirs.call_count == mocked_test.call_count - 1) == (not paths_exist)
    assert len(file_writer_process.get_upload_threads_container()) == 0


@pytest.mark.parametrize("auto_delete", [True, False])
def test_FileWriterProcess__exits_status_function_correctly_when_newly_failed_files_passes_and_auto_delete_is_true_or_false(
    four_board_file_writer_process, auto_delete, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)

    invoke_process_run_and_check_errors(file_writer_process)

    mocked_rmdir = mocker.patch.object(os, "rmdir", autospec=True)
    mocker.patch.object(os, "listdir", autospec=True)

    mocked_thread = mocker.patch.object(worker_thread, "ErrorCatchingThread", autospec=True)
    mocker.patch.object(mocked_thread.name, "is_alive", autospec=True, return_value=False)
    mocker.patch.object(mocked_thread.name, "errors", autospec=True, return_value=False)
    mocker.patch.object(mocked_thread.name, "join", autospec=True)

    thread_dict = {
        "failed_upload": False,
        "customer_account_id": "test_customer_id",
        "user_account_id": "test_user",
        "thread": mocked_thread.name,
        "auto_delete": auto_delete,
        "file_name": "test_filename",
    }

    file_writer_process.get_upload_threads_container().append(thread_dict)
    file_writer_process._check_upload_statuses()  # pylint: disable=protected-access

    assert mocked_rmdir.call_count == int(auto_delete)
    assert len(file_writer_process.get_upload_threads_container()) == 0


def test_FileWriterProcess__correctly_kicks_off_upload_thread_on_setup_and_appends_to_container_with_specified_dict_values(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)

    mocker.patch.object(os, "listdir", return_value=["test_id"])
    mocker.patch.object(os.path, "exists", autospec=True, return_value=True)
    mocker.patch.object(worker_thread, "ErrorCatchingThread", autospec=True)

    file_writer_process._process_failed_upload_files_on_setup()  # pylint: disable=protected-access
    upload_threads_container = file_writer_process.get_upload_threads_container()
    assert upload_threads_container[0]["customer_account_id"] == "test_id"
    assert upload_threads_container[0]["failed_upload"] is True
    assert upload_threads_container[0]["auto_delete"] is False
    assert upload_threads_container[0]["file_name"] == "test_id"


def test_FileWriterProcess__correctly_kicks_off_upload_thread_on_setup_and_will_only_upload_for_customer_account_in_store_with_password(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)

    mocker.patch.object(os, "listdir", return_value=["wrong_id"])
    mocker.patch.object(os.path, "exists", autospec=True, return_value=True)
    mocker.patch.object(worker_thread, "ErrorCatchingThread", autospec=True)

    file_writer_process._process_failed_upload_files_on_setup()  # pylint: disable=protected-access
    upload_threads_container = file_writer_process.get_upload_threads_container()
    assert len(upload_threads_container) == 0


def test_FileWriterProcess__prevent_any_uploads_with_no_stored_customer_settings(
    mocker, four_board_file_writer_process
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    spied_auto_delete = mocker.patch.object(file_writer_process, "_delete_local_files", autospec=True)
    spied_thread_start = mocker.patch.object(worker_thread.ErrorCatchingThread, "start", autospec=True)
    spied_thread_join = mocker.patch.object(worker_thread.ErrorCatchingThread, "join", autospec=True)

    file_writer_process._stored_customer_settings = None  # pylint: disable=protected-access

    file_writer_process._start_new_file_upload()  # pylint: disable=protected-access
    spied_auto_delete.assert_not_called()
    spied_thread_start.assert_not_called()

    file_writer_process._check_upload_statuses()  # pylint: disable=protected-access
    spied_thread_join.assert_not_called()

    file_writer_process._process_failed_upload_files_on_setup()  # pylint: disable=protected-access


def test_FileWriterProcess__does_not_join_upload_thread_if_alive(four_board_file_writer_process, mocker):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    spied_join = mocker.spy(worker_thread.ErrorCatchingThread, "join")
    mocker.patch.object(os.path, "exists", autospec=True, return_value=True)
    mocker.patch.object(os, "listdir", autospec=True, return_value=["73f52be0-368c-42d8-a1fd-660d49ba5604"])

    mocker.patch.object(worker_thread.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_upload_on_completion"] = True
    GENERIC_UPDATE_CUSTOMER_SETTINGS["config_settings"]["auto_delete_local_files"] = False
    this_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    spied_join.assert_not_called()


def test_FileWriterProcess__upload_thread_gets_added_to_container_after_all_files_get_finalized(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]

    mocker.patch.object(worker_thread.ErrorCatchingThread, "start", autospec=True)
    mocker.patch.object(worker_thread.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    update_customer_settings_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    update_customer_settings_command["config_settings"]["auto_delete_local_files"] = False
    update_customer_settings_command["config_settings"]["auto_upload_on_completion"] = True
    create_and_close_beta_1_h5_files(four_board_file_writer_process, update_customer_settings_command)

    board_idx = 0
    assert file_writer_process.get_stop_recording_timestamps()[board_idx] is not None
    assert (
        file_writer_process._is_finalizing_files_after_recording()  # pylint: disable=protected-access
        is False
    )
    assert len(file_writer_process.get_upload_threads_container()) == 1


def test_FileWriterProcess__upload_errors_sent_to_main_correctly(four_board_file_writer_process, mocker):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    mocker.patch.object(worker_thread.ErrorCatchingThread, "start", autospec=True)
    mocked_thread_is_alive = mocker.patch.object(
        worker_thread.ErrorCatchingThread, "is_alive", autospec=True, return_value=True
    )
    mocked_thread_errors = mocker.patch.object(
        worker_thread.ErrorCatchingThread, "errors", autospec=True, return_value=False
    )
    mocked_thread_err = mocker.patch.object(
        worker_thread.ErrorCatchingThread, "get_error", autospec=True, return_value="mocked_error"
    )

    update_customer_settings_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    update_customer_settings_command["config_settings"]["auto_delete_local_files"] = False
    update_customer_settings_command["config_settings"]["auto_upload_on_completion"] = True
    create_and_close_beta_1_h5_files(four_board_file_writer_process, update_customer_settings_command)
    sub_dir_name = file_writer_process.get_sub_dir_name()

    board_idx = 0
    assert file_writer_process.get_stop_recording_timestamps()[board_idx] is not None
    assert (
        file_writer_process._is_finalizing_files_after_recording()  # pylint: disable=protected-access
        is False
    )

    # create and process error
    mocked_thread_errors.return_value = True
    mocked_thread_is_alive.return_value = False
    mocker.patch.object(worker_thread.ErrorCatchingThread, "join")
    invoke_process_run_and_check_errors(file_writer_process)

    update_upload_status_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert update_upload_status_msg["communication_type"] == "update_upload_status"
    update_upload_status_json = json.loads(update_upload_status_msg["content"]["data_json"])
    assert update_upload_status_json["file_name"] == sub_dir_name
    assert update_upload_status_json["error"] == mocked_thread_err.return_value


@pytest.mark.parametrize("auto_delete", [True, False])
def test_FileWriterProcess__no_upload_threads_are_started_when_auto_upload_is_false_and_auto_delete_is_true_or_false(
    four_board_file_writer_process, auto_delete, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]

    mocked_upload_thread_start = mocker.patch.object(
        worker_thread.ErrorCatchingThread, "start", autospec=True
    )

    test_well_indices = [4, 5]

    update_customer_settings_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    update_customer_settings_command["config_settings"]["auto_delete_local_files"] = auto_delete
    update_customer_settings_command["config_settings"]["auto_upload_on_completion"] = False
    list_to_main_queue = create_and_close_beta_1_h5_files(
        four_board_file_writer_process,
        update_customer_settings_command,
        active_well_indices=test_well_indices,
    )

    mocked_upload_thread_start.assert_not_called()
    assert len(file_writer_process.get_upload_threads_container()) == 0
    num_expected_finalization_msgs = len(test_well_indices)
    for i in range(num_expected_finalization_msgs):
        assert list_to_main_queue[i]["communication_type"] == "file_finalized", i


def test_FileWriterProcess__status_successfully_gets_added_to_main_queue_when_auto_upload_and_delete_are_true_without_error(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    test_well_indices = [10, 20]

    mocker.patch.object(worker_thread.ErrorCatchingThread, "errors", autospec=True, return_value=False)
    mocker.patch.object(worker_thread.ErrorCatchingThread, "start", autospec=True)
    mocker.patch.object(worker_thread.ErrorCatchingThread, "join")
    mocked_thread_is_alive = mocker.patch.object(
        worker_thread.ErrorCatchingThread, "is_alive", autospec=True, return_value=True
    )

    update_customer_settings_command = copy.deepcopy(GENERIC_UPDATE_CUSTOMER_SETTINGS)
    update_customer_settings_command["config_settings"]["auto_delete_local_files"] = True
    update_customer_settings_command["config_settings"]["auto_upload_on_completion"] = True
    create_and_close_beta_1_h5_files(
        four_board_file_writer_process,
        update_customer_settings_command,
        active_well_indices=test_well_indices,
    )

    # stop thread and make sure no errors in message to main
    mocked_thread_is_alive.return_value = False
    invoke_process_run_and_check_errors(file_writer_process)

    # make sure no errors in message to main
    update_upload_status_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert update_upload_status_msg["communication_type"] == "update_upload_status"
    assert "error" not in json.loads(update_upload_status_msg["content"]["data_json"])
