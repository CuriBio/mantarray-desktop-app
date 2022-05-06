# -*- coding: utf-8 -*-
import copy
import json
import os
import shutil

from mantarray_desktop_app import file_writer
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import create_and_close_beta_1_h5_files
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_UPDATE_USER_SETTINGS
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [fixture_patch_print, fixture_four_board_file_writer_process]


def test_FileWriterProcess__updates_customer_settings_and_responds_to_main_queue(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    this_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    invoke_process_run_and_check_errors(file_writer_process)
    assert file_writer_process._user_settings == GENERIC_UPDATE_USER_SETTINGS["config_settings"]

    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == {
        "communication_type": "command_receipt",
        "command": "update_user_settings",
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

    file_writer_process._open_files[0][0] = mocker.MagicMock()
    file_writer_process._user_settings = {"auto_upload_on_completion": True}
    file_writer_process._is_recording_calibration = True

    file_writer_process._finalize_completed_files()
    mocked_start_upload.assert_not_called()


def test_FileWriterProcess__prevent_any_uploads_before_customer_settings_are_stored(
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

    file_writer_process._open_files[0][0] = mocker.MagicMock()

    file_writer_process._finalize_completed_files()
    mocked_start_upload.assert_not_called()


@pytest.mark.parametrize("move_called, thread_error", [(True, False), (False, True)])
def test_FileWriterProcess__exits_status_function_correctly_when_previously_failed_files_errors_or_passes(
    four_board_file_writer_process, move_called, thread_error, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]

    mocked_shutil = mocker.patch.object(shutil, "move", autospec=True)

    mocked_ect = mocker.patch.object(file_writer, "ErrorCatchingThread", autospec=True)
    mocked_ect.return_value.error = "error" if thread_error else None
    mocked_ect.return_value.is_alive.return_value = False

    thread_dict = {
        "failed_upload": True,
        "customer_id": "test_customer_id",
        "user_name": "test_user",
        "thread": mocked_ect.return_value,
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

    this_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)

    invoke_process_run_and_check_errors(file_writer_process)

    mocked_shutil = mocker.patch.object(shutil, "move", autospec=True)
    mocked_test = mocker.patch.object(os.path, "exists", autospec=True, return_value=paths_exist)
    mocked_makedirs = mocker.patch.object(os, "makedirs", autospec=True)

    mocked_ect = mocker.patch.object(file_writer, "ErrorCatchingThread", autospec=True)
    mocked_ect.return_value.error = "error"
    mocked_ect.return_value.is_alive.return_value = False

    thread_dict = {
        "failed_upload": False,
        "customer_id": "test_customer_id",
        "user_name": "test_user",
        "thread": mocked_ect.return_value,
        "auto_delete": False,
        "file_name": "test_filename",
    }

    file_writer_process.get_upload_threads_container().append(thread_dict)
    file_writer_process._check_upload_statuses()  # pylint: disable=protected-access

    assert mocked_shutil.call_count == int(paths_exist)
    assert (mocked_makedirs.call_count == mocked_test.call_count - 1) is not paths_exist
    assert len(file_writer_process.get_upload_threads_container()) == 0


@pytest.mark.parametrize("auto_delete", [True, False])
def test_FileWriterProcess__exits_status_function_correctly_when_newly_failed_files_passes(
    auto_delete, four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    this_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)

    invoke_process_run_and_check_errors(file_writer_process)

    mocked_rmdir = mocker.patch.object(os, "rmdir", autospec=True)
    mocker.patch.object(os, "listdir", autospec=True)

    mocked_ect = mocker.patch.object(file_writer, "ErrorCatchingThread", autospec=True)
    mocked_ect.return_value.error = None
    mocked_ect.return_value.is_alive.return_value = False

    thread_dict = {
        "failed_upload": False,
        "customer_id": "test_customer_id",
        "user_name": "test_user",
        "thread": mocked_ect.return_value,
        "auto_delete": auto_delete,
        "file_name": "test/file/name",
    }

    file_writer_process.get_upload_threads_container().append(thread_dict)
    file_writer_process._check_upload_statuses()  # pylint: disable=protected-access

    assert mocked_rmdir.call_count == int(auto_delete)
    assert len(file_writer_process.get_upload_threads_container()) == 0


def test_FileWriterProcess__does_not_join_upload_thread_if_alive(four_board_file_writer_process, mocker):
    file_writer_process = four_board_file_writer_process["fw_process"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    spied_join = mocker.spy(file_writer.ErrorCatchingThread, "join")
    mocker.patch.object(os.path, "exists", autospec=True, return_value=True)
    mocker.patch.object(os, "listdir", autospec=True, return_value=["73f52be0-368c-42d8-a1fd-660d49ba5604"])

    mocker.patch.object(file_writer.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    GENERIC_UPDATE_USER_SETTINGS["config_settings"]["auto_upload_on_completion"] = True
    GENERIC_UPDATE_USER_SETTINGS["config_settings"]["auto_delete_local_files"] = False
    this_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(file_writer_process)

    spied_join.assert_not_called()


def test_FileWriterProcess__upload_thread_gets_added_to_container_after_all_files_get_finalized(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]

    mocker.patch.object(file_writer.ErrorCatchingThread, "start", autospec=True)
    mocker.patch.object(file_writer.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"]["auto_delete_local_files"] = False
    update_user_settings_command["config_settings"]["auto_upload_on_completion"] = True
    create_and_close_beta_1_h5_files(four_board_file_writer_process, update_user_settings_command)

    board_idx = 0
    assert file_writer_process.get_stop_recording_timestamps()[board_idx] is not None
    assert (
        file_writer_process._is_finalizing_files_after_recording()  # pylint: disable=protected-access
        is False
    )
    assert len(file_writer_process.get_upload_threads_container()) == 1


def test_FileWriterProcess__upload_thread_errors_sent_to_main_correctly(
    four_board_file_writer_process, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    mocked_ect = mocker.patch.object(file_writer, "ErrorCatchingThread", autospec=True)
    mocked_ect.return_value.error = "error"

    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    create_and_close_beta_1_h5_files(four_board_file_writer_process, update_user_settings_command)
    sub_dir_name = file_writer_process.get_sub_dir_name()

    board_idx = 0
    assert file_writer_process.get_stop_recording_timestamps()[board_idx] is not None
    assert file_writer_process._is_finalizing_files_after_recording() is False

    # create and process error
    mocked_ect.return_value.is_alive.return_value = False
    invoke_process_run_and_check_errors(file_writer_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    update_upload_status_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert update_upload_status_msg["communication_type"] == "update_upload_status"
    update_upload_status_json = json.loads(update_upload_status_msg["content"]["data_json"])
    assert update_upload_status_json["file_name"] == sub_dir_name
    assert update_upload_status_json["error"] == mocked_ect.return_value.error


@pytest.mark.parametrize("auto_delete", [True, False])
def test_FileWriterProcess__no_upload_threads_are_started_when_auto_upload_is_false_and_auto_delete_is_true_or_false(
    four_board_file_writer_process, auto_delete, mocker
):
    file_writer_process = four_board_file_writer_process["fw_process"]

    mocked_upload_thread_start = mocker.patch.object(file_writer.ErrorCatchingThread, "start", autospec=True)

    test_well_indices = [4, 5]

    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"]["auto_delete_local_files"] = auto_delete
    update_user_settings_command["config_settings"]["auto_upload_on_completion"] = False
    list_to_main_queue = create_and_close_beta_1_h5_files(
        four_board_file_writer_process,
        update_user_settings_command,
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

    mocked_ect = mocker.patch.object(file_writer, "ErrorCatchingThread", autospec=True)
    mocked_ect.return_value.error = None
    mocked_ect.return_value.is_alive.return_value = True

    update_user_settings_command = copy.deepcopy(GENERIC_UPDATE_USER_SETTINGS)
    update_user_settings_command["config_settings"]["auto_delete_local_files"] = True
    update_user_settings_command["config_settings"]["auto_upload_on_completion"] = True
    create_and_close_beta_1_h5_files(
        four_board_file_writer_process,
        update_user_settings_command,
        active_well_indices=test_well_indices,
    )

    # stop thread and make sure no errors in message to main
    mocked_ect.return_value.is_alive.return_value = False
    invoke_process_run_and_check_errors(file_writer_process)

    # make sure no errors in message to main
    update_upload_status_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert update_upload_status_msg["communication_type"] == "update_upload_status"
    assert "error" not in json.loads(update_upload_status_msg["content"]["data_json"])
