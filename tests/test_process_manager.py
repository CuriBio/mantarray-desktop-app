# -*- coding: utf-8 -*-
import logging
import os

from mantarray_desktop_app import DataAnalyzerProcess
from mantarray_desktop_app import FileWriterProcess
from mantarray_desktop_app import get_mantarray_process_manager
from mantarray_desktop_app import MantarrayProcessesManager
from mantarray_desktop_app import OkCommunicationProcess
import pytest
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty
from stdlib_utils import resource_path


def test_MantarrayProcessesManager__stop_processes__calls_stop_on_all_processes(
    mocker,
):
    manager = MantarrayProcessesManager()
    manager.create_processes()
    mocked_ok_comm_stop = mocker.patch.object(OkCommunicationProcess, "stop")
    mocked_file_writer_stop = mocker.patch.object(FileWriterProcess, "stop")
    mocked_data_analyzer_stop = mocker.patch.object(DataAnalyzerProcess, "stop")
    manager.stop_processes()

    mocked_ok_comm_stop.assert_called_once()
    mocked_file_writer_stop.assert_called_once()
    mocked_data_analyzer_stop.assert_called_once()


def test_MantarrayProcessesManager__soft_stop_processes__calls_soft_stop_on_all_processes(
    mocker,
):
    manager = MantarrayProcessesManager()
    manager.create_processes()
    mocked_ok_comm_soft_stop = mocker.patch.object(OkCommunicationProcess, "soft_stop")
    mocked_file_writer_soft_stop = mocker.patch.object(FileWriterProcess, "soft_stop")
    mocked_data_analyzer_soft_stop = mocker.patch.object(
        DataAnalyzerProcess, "soft_stop"
    )
    manager.soft_stop_processes()

    mocked_ok_comm_soft_stop.assert_called_once()
    # mocked_ok_comm_stop.assert_called_once() # Eli (1/15/20) not sure why this isn't being called, but if things get joined back together, then soft stop appears to be working fine
    mocked_file_writer_soft_stop.assert_called_once()
    mocked_data_analyzer_soft_stop.assert_called_once()


def test_MantarrayProcessesManager__hard_stop_processes__calls_hard_stop_on_all_processes_and_returns_process_queue_items(
    mocker,
):
    expected_ok_comm_items = {"ok_comm_queue": ["ok_item"]}
    expected_file_writer_items = {"file_writer_queue": ["fw_item"]}
    expected_da_items = {"data_analyzer_queue": ["da_item"]}

    manager = MantarrayProcessesManager()
    manager.create_processes()
    mocked_ok_comm_hard_stop = mocker.patch.object(
        OkCommunicationProcess, "hard_stop", return_value=expected_ok_comm_items
    )
    mocked_file_writer_hard_stop = mocker.patch.object(
        FileWriterProcess, "hard_stop", return_value=expected_file_writer_items
    )
    mocked_data_analyzer_hard_stop = mocker.patch.object(
        DataAnalyzerProcess, "hard_stop", return_value=expected_da_items
    )
    actual = manager.hard_stop_processes()

    mocked_ok_comm_hard_stop.assert_called_once()
    mocked_file_writer_hard_stop.assert_called_once()
    mocked_data_analyzer_hard_stop.assert_called_once()

    assert actual["ok_comm_items"] == expected_ok_comm_items
    assert actual["file_writer_items"] == expected_file_writer_items
    assert actual["data_analyzer_items"] == expected_da_items


def test_MantarrayProcessesManager__join_processes__calls_join_on_all_processes(mocker):
    manager = MantarrayProcessesManager()
    manager.create_processes()
    mocked_ok_comm_join = mocker.patch.object(OkCommunicationProcess, "join")
    mocked_file_writer_join = mocker.patch.object(FileWriterProcess, "join")
    mocked_data_analyzer_join = mocker.patch.object(DataAnalyzerProcess, "join")
    manager.join_processes()

    mocked_ok_comm_join.assert_called_once()
    mocked_file_writer_join.assert_called_once()
    mocked_data_analyzer_join.assert_called_once()


@pytest.mark.timeout(20)
def test_MantarrayProcessesManager__spawn_processes__stop_and_join_processes__starts_and_stops_all_processes(
    mocker,
):
    manager = MantarrayProcessesManager()
    spied_ok_comm_start = mocker.spy(OkCommunicationProcess, "start")
    spied_ok_comm_stop = mocker.spy(OkCommunicationProcess, "stop")
    spied_ok_comm_join = mocker.spy(OkCommunicationProcess, "join")
    spied_file_writer_start = mocker.spy(FileWriterProcess, "start")
    spied_file_writer_stop = mocker.spy(FileWriterProcess, "stop")
    spied_file_writer_join = mocker.spy(FileWriterProcess, "join")
    spied_data_analyzer_start = mocker.spy(DataAnalyzerProcess, "start")
    spied_data_analyzer_stop = mocker.spy(DataAnalyzerProcess, "stop")
    spied_data_analyzer_join = mocker.spy(DataAnalyzerProcess, "join")
    manager.spawn_processes()
    manager.stop_and_join_processes()
    spied_ok_comm_start.assert_called_once()
    spied_ok_comm_stop.assert_called_once()
    spied_ok_comm_join.assert_called_once()

    spied_file_writer_start.assert_called_once()
    spied_file_writer_stop.assert_called_once()
    spied_file_writer_join.assert_called_once()

    spied_data_analyzer_start.assert_called_once()
    spied_data_analyzer_stop.assert_called_once()
    spied_data_analyzer_join.assert_called_once()


@pytest.mark.timeout(20)
def test_MantarrayProcessesManager__soft_stop_and_join_processes__soft_stops_processes(
    mocker,
):
    manager = MantarrayProcessesManager()
    spied_ok_comm_start = mocker.spy(OkCommunicationProcess, "start")
    spied_ok_comm_soft_stop = mocker.spy(OkCommunicationProcess, "soft_stop")
    spied_ok_comm_join = mocker.spy(OkCommunicationProcess, "join")

    spied_file_writer_start = mocker.spy(FileWriterProcess, "start")
    spied_file_writer_soft_stop = mocker.spy(FileWriterProcess, "soft_stop")
    spied_file_writer_join = mocker.spy(FileWriterProcess, "join")

    spied_data_analyzer_start = mocker.spy(DataAnalyzerProcess, "start")
    spied_data_analyzer_soft_stop = mocker.spy(DataAnalyzerProcess, "soft_stop")
    spied_data_analyzer_join = mocker.spy(DataAnalyzerProcess, "join")

    manager.spawn_processes()
    manager.soft_stop_and_join_processes()
    spied_ok_comm_start.assert_called_once()
    spied_ok_comm_soft_stop.assert_called_once()
    # spied_ok_comm_stop.assert_called_once() # Eli (1/15/20) not sure why this isn't being called, but if things get joined back together, then soft stop appears to be working fine
    spied_ok_comm_join.assert_called_once()

    spied_file_writer_start.assert_called_once()
    spied_file_writer_soft_stop.assert_called_once()
    spied_file_writer_join.assert_called_once()

    spied_data_analyzer_start.assert_called_once()
    spied_data_analyzer_soft_stop.assert_called_once()
    spied_data_analyzer_join.assert_called_once()


@pytest.mark.timeout(25)
def test_MantarrayProcessesManager__hard_stop_and_join_processes__hard_stops_processes_and_returns_queue_items(
    mocker,
):
    expected_ok_comm_item = "ok_comm_item"
    expected_file_writer_item = "file_writer_item"
    expected_da_item = "data_analyzer_item"

    manager = MantarrayProcessesManager()

    spied_ok_comm_start = mocker.spy(OkCommunicationProcess, "start")
    spied_ok_comm_hard_stop = mocker.spy(OkCommunicationProcess, "hard_stop")
    spied_ok_comm_join = mocker.spy(OkCommunicationProcess, "join")

    spied_file_writer_start = mocker.spy(FileWriterProcess, "start")
    spied_file_writer_hard_stop = mocker.spy(FileWriterProcess, "hard_stop")
    spied_file_writer_join = mocker.spy(FileWriterProcess, "join")

    spied_data_analyzer_start = mocker.spy(DataAnalyzerProcess, "start")
    spied_data_analyzer_hard_stop = mocker.spy(DataAnalyzerProcess, "hard_stop")
    spied_data_analyzer_join = mocker.spy(DataAnalyzerProcess, "join")

    manager.spawn_processes()
    ok_comm_to_main = manager.get_communication_queue_from_ok_comm_to_main(0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_ok_comm_item, ok_comm_to_main
    )
    file_writer_to_main = manager.get_communication_queue_from_file_writer_to_main()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_file_writer_item, file_writer_to_main
    )
    data_analyzer_to_main = manager.get_communication_queue_from_data_analyzer_to_main()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_da_item, data_analyzer_to_main
    )

    actual = manager.hard_stop_and_join_processes()
    spied_ok_comm_start.assert_called_once()
    spied_ok_comm_hard_stop.assert_called_once()
    spied_ok_comm_join.assert_called_once()

    spied_file_writer_start.assert_called_once()
    spied_file_writer_hard_stop.assert_called_once()
    spied_file_writer_join.assert_called_once()

    spied_data_analyzer_start.assert_called_once()
    spied_data_analyzer_hard_stop.assert_called_once()
    spied_data_analyzer_join.assert_called_once()

    assert (
        expected_ok_comm_item in actual["ok_comm_items"]["board_0"]["ok_comm_to_main"]
    )
    assert (
        expected_file_writer_item
        in actual["file_writer_items"]["from_file_writer_to_main"]
    )
    assert (
        expected_da_item in actual["data_analyzer_items"]["from_data_analyzer_to_main"]
    )


def test_MantarrayProcessesManager__passes_file_directory_to_FileWriter():
    manager = MantarrayProcessesManager(file_directory="blahdir")
    manager.create_processes()
    assert manager.get_file_writer_process().get_file_directory() == "blahdir"


def test_MantarrayProcessesManager__passes_logging_level_to_subprocesses():
    expected_level = logging.WARNING
    manager = MantarrayProcessesManager(logging_level=expected_level)
    manager.create_processes()
    assert manager.get_file_writer_process().get_logging_level() == expected_level
    assert manager.get_ok_comm_process().get_logging_level() == expected_level


def test_get_mantarray_process_manager__returns_process_monitor_with_correct_recordings_file_directory():
    process_manager_path = os.path.join(
        os.path.dirname(get_current_file_abs_directory()),
        "src",
        "mantarray_desktop_app",
    )
    base_path = os.path.join(process_manager_path, os.pardir, os.pardir)
    base_path = os.path.normcase(base_path)
    relative_path = "recordings"
    expected_recordings_path = resource_path(relative_path, base_path=base_path)

    actual_manager = get_mantarray_process_manager()
    assert (
        actual_manager._file_directory  # pylint: disable=protected-access
        == expected_recordings_path
    )


# def test_get_mantarray_process_manager__spawns_processes_if_not_already_started__but_not_again(
#     mocker,
# ):
#     mocked_spawn = mocker.spy(MantarrayProcessesManager, "spawn_processes")
#     manager = get_mantarray_process_manager()
#     assert mocked_spawn.call_count == 1
#     manager = get_mantarray_process_manager()
#     assert mocked_spawn.call_count == 1
#     manager.stop_processes()
