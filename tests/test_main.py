# -*- coding: utf-8 -*-
import time

from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import prepare_to_shutdown
from mantarray_desktop_app import server
from mantarray_desktop_app import SUBPROCESS_POLL_DELAY_SECONDS
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
import pytest

from .fixtures import fixture_fully_running_app_from_main_entrypoint
from .fixtures import fixture_patched_shared_values_dict
from .fixtures import fixture_patched_start_recording_shared_dict
from .fixtures import fixture_patched_xem_scripts_folder
from .fixtures import fixture_test_process_manager
from .fixtures import fixture_test_process_manager_without_created_processes
from .fixtures_server import fixture_test_client


__fixtures__ = [
    fixture_patched_start_recording_shared_dict,
    fixture_test_client,
    fixture_test_process_manager,
    fixture_patched_shared_values_dict,
    fixture_fully_running_app_from_main_entrypoint,
    fixture_patched_xem_scripts_folder,
    fixture_test_process_manager_without_created_processes,
]


@pytest.fixture(
    scope="function", name="confirm_monitor_found_no_errors_in_subprocesses"
)
def fixture_confirm_monitor_found_no_errors_in_subprocesses(mocker):
    mocker_error_handling_for_subprocess = mocker.spy(
        MantarrayProcessesMonitor, "_handle_error_in_subprocess"
    )
    yield mocker_error_handling_for_subprocess
    assert mocker_error_handling_for_subprocess.call_count == 0


@pytest.mark.slow
def test_prepare_to_shutdown__soft_stops_subprocesses(test_process_manager, mocker):
    test_process_manager.spawn_processes()
    okc_process = test_process_manager.get_ok_comm_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    spied_okc_soft_stop = mocker.spy(okc_process, "soft_stop")
    spied_fw_soft_stop = mocker.spy(fw_process, "soft_stop")
    spied_da_soft_stop = mocker.spy(da_process, "soft_stop")

    prepare_to_shutdown()

    spied_okc_soft_stop.assert_called_once()
    spied_fw_soft_stop.assert_called_once()
    spied_da_soft_stop.assert_called_once()


@pytest.mark.slow
def test_prepare_to_shutdown__waits_correct_amount_of_time_before_hard_stopping_and_joining_processes(
    test_process_manager, mocker
):
    test_process_manager.spawn_processes()
    okc_process = test_process_manager.get_ok_comm_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()
    server_thread = test_process_manager.get_server_thread()

    spied_okc_join = mocker.spy(okc_process, "join")
    spied_fw_join = mocker.spy(fw_process, "join")
    spied_da_join = mocker.spy(da_process, "join")
    spied_server_join = mocker.spy(server_thread, "join")

    mocked_okc_hard_stop = mocker.patch.object(okc_process, "hard_stop", autospec=True)
    mocked_fw_hard_stop = mocker.patch.object(fw_process, "hard_stop", autospec=True)
    mocked_da_hard_stop = mocker.patch.object(da_process, "hard_stop", autospec=True)
    mocked_server_hard_stop = mocker.patch.object(
        server_thread, "hard_stop", autospec=True
    )
    mocked_okc_is_stopped = mocker.patch.object(
        okc_process, "is_stopped", autospec=True, side_effect=[False, True, True]
    )
    mocked_fw_is_stopped = mocker.patch.object(
        fw_process, "is_stopped", autospec=True, side_effect=[False, True]
    )
    mocked_da_is_stopped = mocker.patch.object(
        da_process, "is_stopped", autospec=True, side_effect=[False]
    )

    mocked_counter = mocker.patch.object(
        time,
        "perf_counter",
        autospec=True,
        side_effect=[0, 0, 0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS],
    )
    mocker.patch.object(time, "sleep", autospec=True)

    prepare_to_shutdown()

    mocked_okc_hard_stop.assert_called_once()
    mocked_fw_hard_stop.assert_called_once()
    mocked_da_hard_stop.assert_called_once()
    mocked_server_hard_stop.assert_called_once()
    spied_okc_join.assert_called_once()
    spied_fw_join.assert_called_once()
    spied_da_join.assert_called_once()
    spied_server_join.assert_called_once()
    assert mocked_counter.call_count == 4
    assert mocked_okc_is_stopped.call_count == 3
    assert mocked_fw_is_stopped.call_count == 2
    assert mocked_da_is_stopped.call_count == 1


@pytest.mark.slow
def test_prepare_to_shutdown__sleeps_for_correct_amount_of_time_each_cycle_of_checking_subprocess_status(
    test_process_manager, mocker
):
    test_process_manager.spawn_processes()

    mocker.patch.object(
        test_process_manager, "hard_stop_and_join_processes", autospec=True
    )

    mocker.patch.object(
        time,
        "perf_counter",
        autospec=True,
        side_effect=[0, 0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS],
    )
    mocked_sleep = mocker.patch.object(time, "sleep", autospec=True)

    prepare_to_shutdown()

    mocked_sleep.assert_called_once_with(SUBPROCESS_POLL_DELAY_SECONDS)


@pytest.mark.slow
def test_prepare_to_shutdown__logs_items_in_queues_after_hard_stop(
    test_process_manager, mocker
):
    test_process_manager.spawn_processes()
    okc_process = test_process_manager.get_ok_comm_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    expected_okc_item = "item 1"
    expected_fw_item = "item 2"
    expected_da_item = "item 3"

    mocker.patch.object(
        okc_process, "hard_stop", autospec=True, return_value=expected_okc_item
    )
    mocker.patch.object(
        fw_process, "hard_stop", autospec=True, return_value=expected_fw_item
    )
    mocker.patch.object(
        da_process, "hard_stop", autospec=True, return_value=expected_da_item
    )
    mocker.patch.object(
        time,
        "perf_counter",
        autospec=True,
        side_effect=[0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS],
    )

    mocked_info = mocker.patch.object(main.logger, "info", autospec=True)

    prepare_to_shutdown()

    assert expected_okc_item in mocked_info.call_args[0][0]
    assert expected_fw_item in mocked_info.call_args[0][0]
    assert expected_da_item in mocked_info.call_args[0][0]


def test_route_with_no_url_rule__returns_error_message__and_logs_reponse_to_request(
    test_client, patched_shared_values_dict, mocker
):
    mocked_logger = mocker.spy(server.logger, "info")

    response = test_client.get("/fake_route")
    assert response.status_code == 404
    assert response.status.endswith("Route not implemented") is True

    mocked_logger.assert_called_once_with(
        f"Response to HTTP Request in next log entry: {response.status}"
    )
