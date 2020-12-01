# -*- coding: utf-8 -*-
import base64
import json
import logging
import tempfile
import threading
import time

from freezegun import freeze_time
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import prepare_to_shutdown
from mantarray_desktop_app import process_monitor
from mantarray_desktop_app import server
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import SUBPROCESS_POLL_DELAY_SECONDS
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import wait_for_subprocesses_to_start
import pytest
import requests
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use

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


@pytest.mark.timeout(15)
@freeze_time("2020-07-21 21:51:36.704515")
def test_main_can_launch_server_and_processes_and_initial_boot_up_of_ok_comm_process_gets_logged__default_exe_execution(
    mocker, confirm_monitor_found_no_errors_in_subprocesses, patched_shared_values_dict,
):
    mocked_process_monitor_info_logger = mocker.patch.object(
        process_monitor.logger, "info", autospec=True,
    )

    mocker.patch.object(main, "configure_logging", autospec=True)
    mocked_main_info_logger = mocker.patch.object(main.logger, "info", autospec=True)
    main_thread = threading.Thread(
        target=main.main, args=[[]], name="thread_for_main_function_in_test"
    )
    main_thread.start()

    confirm_port_in_use(
        get_server_port_number(), timeout=3
    )  # wait for server to boot up
    wait_for_subprocesses_to_start()

    requests.get(f"{get_api_endpoint()}shutdown")

    main_thread.join()
    confirm_port_available(get_server_port_number())

    expected_initiated_str = "OpalKelly Communication Process initiated at"
    assert any(
        [
            expected_initiated_str in call[0][0]
            for call in mocked_process_monitor_info_logger.call_args_list
        ]
    )
    expected_connection_str = "Communication from the OpalKelly Controller: {'communication_type': 'board_connection_status_change'"
    assert any(
        [
            expected_connection_str in call[0][0]
            for call in mocked_process_monitor_info_logger.call_args_list
        ]
    )

    mocked_main_info_logger.assert_any_call(
        f"Build timestamp/version: {COMPILED_EXE_BUILD_TIMESTAMP}"
    )


@pytest.mark.slow
def test_main__calls_boot_up_function_upon_launch(
    patched_xem_scripts_folder,
    fully_running_app_from_main_entrypoint,
    mocker,
    test_process_manager,
):
    spied_boot_up = mocker.spy(test_process_manager, "boot_up_instrument")

    _ = fully_running_app_from_main_entrypoint()
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=5)
    wait_for_subprocesses_to_start()

    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True
    spied_boot_up.assert_called_once()


@pytest.mark.slow
def test_main__does_not_call_boot_up_function_upon_launch_if_command_line_arg_passed(
    patched_shared_values_dict,
    patched_xem_scripts_folder,
    fully_running_app_from_main_entrypoint,
    mocker,
    test_process_manager,
):
    spied_boot_up = mocker.spy(test_process_manager, "boot_up_instrument")

    _ = fully_running_app_from_main_entrypoint(["--skip-mantarray-boot-up"])
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=5)
    wait_for_subprocesses_to_start()

    assert system_state_eventually_equals(SERVER_READY_STATE, 5) is True
    spied_boot_up.assert_not_called()


@pytest.mark.slow
def test_main__stores_and_logs_directory_for_log_files_from_command_line_arguments(
    mocker, patched_shared_values_dict
):
    spied_info_logger = mocker.spy(main.logger, "info")
    mocked_configure = mocker.patch.object(main, "configure_logging", autospec=True)

    expected_log_dir = r"C:\Users\Curi Bio\MantarrayController"
    command_line_args = [f"--log_file_dir={expected_log_dir}"]
    main_thread = threading.Thread(
        target=main.main,
        args=[command_line_args],
        name="thread_for_main_function_in_test",
    )
    main_thread.start()
    confirm_port_in_use(get_server_port_number(), timeout=3)
    requests.get(f"{get_api_endpoint()}shutdown")
    main_thread.join()

    mocked_configure.assert_called_once_with(
        path_to_log_folder=expected_log_dir,
        log_file_prefix="mantarray_log",
        log_level=logging.INFO,
    )
    spied_info_logger.assert_any_call(
        f"Using directory for log files: {expected_log_dir}"
    )


@pytest.mark.slow
def test_main__stores_and_logs_user_settings_and_recordings_folder_from_command_line_arguments(
    mocker, patched_shared_values_dict, test_process_manager_without_created_processes
):
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        test_dict = {
            "customer_account_uuid": "14b9294a-9efb-47dd-a06e-8247e982e196",
            "user_account_uuid": "0288efbc-7705-4946-8815-02701193f766",
            "recording_directory": expected_recordings_dir,
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")

        command_line_args = [f"--initial-base64-settings={b64_encoded}"]
        main_thread = threading.Thread(
            target=main.main,
            args=[command_line_args],
            name="thread_for_main_function_in_test",
        )
        main_thread.start()
        confirm_port_in_use(get_server_port_number(), timeout=3)
        requests.get(f"{get_api_endpoint()}shutdown")
        main_thread.join()

        assert (
            patched_shared_values_dict["config_settings"]["Customer Account ID"]
            == "14b9294a-9efb-47dd-a06e-8247e982e196"
        )
        assert (
            patched_shared_values_dict["config_settings"]["User Account ID"]
            == "0288efbc-7705-4946-8815-02701193f766"
        )
        assert (
            patched_shared_values_dict["config_settings"]["Recording Directory"]
            == expected_recordings_dir
        )


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
