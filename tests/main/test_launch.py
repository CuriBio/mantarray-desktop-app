# -*- coding: utf-8 -*-
import base64
import json
import logging
import multiprocessing
import platform
import sys
import tempfile
import threading
from unittest.mock import ANY

from freezegun import freeze_time
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import ImproperlyFormattedCustomerAccountUUIDError
from mantarray_desktop_app import ImproperlyFormattedUserAccountUUIDError
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayProcessesManager
from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import MultiprocessingNotSetToSpawnError
from mantarray_desktop_app import process_monitor
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import wait_for_subprocesses_to_start
import pytest
import requests
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use

from ..fixtures import fixture_fully_running_app_from_main_entrypoint
from ..fixtures import fixture_patched_xem_scripts_folder
from ..fixtures import fixture_test_process_manager
from ..fixtures import GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
from ..fixtures_server import fixture_test_client


__fixtures__ = [
    fixture_test_client,
    fixture_test_process_manager,
    fixture_fully_running_app_from_main_entrypoint,
    fixture_patched_xem_scripts_folder,
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


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_main__stores_and_logs_port_number_from_command_line_arguments(
    mocker, fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    spied_info_logger = mocker.spy(main.logger, "info")

    expected_port_number = 1234
    command_line_args = [f"--port_number={expected_port_number}"]
    fully_running_app_from_main_entrypoint(command_line_args)

    actual = get_server_port_number()
    assert actual == expected_port_number
    spied_info_logger.assert_any_call(
        f"Using server port number: {expected_port_number}"
    )


def test_main__handles_base64_command_line_argument_with_padding_issue(mocker):
    expected_command_line_args = [
        "--debug-test-post-build",
        "--initial-base64-settings=eyJyZWNvcmRpbmdfZGlyZWN0b3J5IjoiL2hvbWUvdWJ1bnR1Ly5jb25maWcvTWFudGFycmF5Q29udHJvbGxlci9yZWNvcmRpbmdzIn0",
    ]
    spied_info_logger = mocker.spy(main.logger, "info")
    main.main(expected_command_line_args)

    spied_info_logger.assert_any_call(
        "Command Line Args: {'debug_test_post_build': True, 'log_level_debug': False, 'skip_mantarray_boot_up': False, 'port_number': None, 'log_file_dir': None, 'initial_base64_settings': 'eyJyZWNvcmRpbmdfZGlyZWN0b3J5IjoiL2hvbWUvdWJ1bnR1Ly5jb25maWcvTWFudGFycmF5Q29udHJvbGxlci9yZWNvcmRpbmdzIn0'}"
    )


def test_main__logs_command_line_arguments(mocker):
    expected_command_line_args = ["--debug-test-post-build", "--log-level-debug"]
    spied_info_logger = mocker.spy(main.logger, "info")
    main_thread = threading.Thread(
        target=main.main,
        args=[expected_command_line_args],
        name="thread_for_main_function_in_test",
    )
    main_thread.start()
    main_thread.join()

    spied_info_logger.assert_any_call(
        "Command Line Args: {'debug_test_post_build': True, 'log_level_debug': True, 'skip_mantarray_boot_up': False, 'port_number': None, 'log_file_dir': None, 'initial_base64_settings': None}"
    )


@pytest.mark.timeout(1)
def test_main_argparse_debug_test_post_build(mocker):
    # fails by hanging because Server would be started opened if not handled
    mocker.patch.object(main, "configure_logging", autospec=True)
    main.main(["--debug-test-post-build"])


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
def test_main_configures_logging(mocker):
    mocked_configure_logging = mocker.patch.object(
        main, "configure_logging", autospec=True
    )
    main.main(["--debug-test-post-build"])
    mocked_configure_logging.assert_called_once_with(
        path_to_log_folder=None, log_file_prefix="mantarray_log", log_level=logging.INFO
    )


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
def test_main__logs_system_info__and_software_version_at_very_start(
    mocker, fully_running_app_from_main_entrypoint, patched_xem_scripts_folder,
):
    spied_info_logger = mocker.spy(main.logger, "info")

    fully_running_app_from_main_entrypoint([])

    assert CURRENT_SOFTWARE_VERSION in spied_info_logger.call_args_list[0][0][0]

    uname = platform.uname()
    uname_sys = getattr(uname, "system")
    uname_release = getattr(uname, "release")
    uname_version = getattr(uname, "version")
    spied_info_logger.assert_any_call(f"System: {uname_sys}")
    spied_info_logger.assert_any_call(f"Release: {uname_release}")
    spied_info_logger.assert_any_call(f"Version: {uname_version}")
    spied_info_logger.assert_any_call(f"Machine: {getattr(uname, 'machine')}")
    spied_info_logger.assert_any_call(f"Processor: {getattr(uname, 'processor')}")
    spied_info_logger.assert_any_call(f"Win 32 Ver: {platform.win32_ver()}")
    spied_info_logger.assert_any_call(f"Platform: {platform.platform()}")
    spied_info_logger.assert_any_call(f"Architecture: {platform.architecture()}")
    spied_info_logger.assert_any_call(f"Interpreter is 64-bits: {sys.maxsize > 2**32}")
    spied_info_logger.assert_any_call(
        f"System Alias: {platform.system_alias(uname_sys, uname_release, uname_version)}"
    )
    spied_info_logger.assert_any_call(
        f"Python Version: {platform.python_version_tuple()}"
    )
    spied_info_logger.assert_any_call(
        f"Python Implementation: {platform.python_implementation()}"
    )
    spied_info_logger.assert_any_call(f"Python Build: {platform.python_build()}")
    spied_info_logger.assert_any_call(f"Python Compiler: {platform.python_compiler()}")


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_main__raises_error_when_invalid_customer_account_uuid_is_passed_in_cmd_line_args(
    mocker,
):
    invalid_uuid = "14b9294a-9efb-47dd"
    test_dict = {
        "customer_account_uuid": invalid_uuid,
    }
    json_str = json.dumps(test_dict)
    b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
    command_line_args = [f"--initial-base64-settings={b64_encoded}"]
    with pytest.raises(ImproperlyFormattedCustomerAccountUUIDError, match=invalid_uuid):
        main.main(command_line_args)


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_main__raises_error_when_invalid_user_account_uuid_is_passed_in_cmd_line_args(
    mocker,
):
    invalid_uuid = "not a uuid"
    test_dict = {
        "user_account_uuid": invalid_uuid,
    }
    json_str = json.dumps(test_dict)
    b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
    command_line_args = [f"--initial-base64-settings={b64_encoded}"]
    with pytest.raises(ImproperlyFormattedUserAccountUUIDError, match=invalid_uuid):
        main.main(command_line_args)


def test_main__raises_error_if_multiprocessing_start_method_not_spawn(mocker):
    mocked_get_start_method = mocker.patch.object(
        multiprocessing, "get_start_method", autospec=True, return_value="fork"
    )
    mocker.patch.object(main, "configure_logging", autospec=True)
    with pytest.raises(MultiprocessingNotSetToSpawnError, match=r"'fork'"):
        main.main(["--debug-test-post-build"])
    mocked_get_start_method.assert_called_once_with(allow_none=True)


@pytest.mark.timeout(15)
def test_main_configures_process_manager_logging_level__and_standard_logging_level__to_debug_when_command_line_arg_passed(
    mocker, fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    app_info = fully_running_app_from_main_entrypoint(["--log-level-debug"])
    mocked_configure_logging = app_info["mocked_configure_logging"]

    mocked_configure_logging.assert_called_once_with(
        path_to_log_folder=None, log_file_prefix=ANY, log_level=logging.DEBUG
    )
    process_manager = app_info["object_access_inside_main"]["process_manager"]
    process_manager_logging_level = process_manager.get_logging_level()
    assert process_manager_logging_level == logging.DEBUG


@pytest.mark.slow
@pytest.mark.timeout(20)
def test_main_configures_process_manager_logging_level__and_standard_logging_level__to_info_by_default(
    mocker, fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    app_info = fully_running_app_from_main_entrypoint([])
    mocked_configure_logging = app_info["mocked_configure_logging"]

    mocked_configure_logging.assert_called_once_with(
        path_to_log_folder=None, log_file_prefix=ANY, log_level=logging.INFO
    )
    process_manager = app_info["object_access_inside_main"]["process_manager"]
    process_manager_logging_level = process_manager.get_logging_level()
    assert process_manager_logging_level == logging.INFO


@pytest.mark.timeout(15)
def test_main_can_launch_server_with_no_args_from_entrypoint__default_exe_execution(
    fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    _ = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()

    shutdown_response = requests.get(f"{get_api_endpoint()}shutdown")
    assert shutdown_response.status_code == 200
    confirm_port_available(
        get_server_port_number(), timeout=5
    )  # wait for shutdown to complete


@pytest.mark.timeout(20)
@pytest.mark.slow
def test_main_entrypoint__correctly_assigns_shared_values_dictionary_to_process_monitor(  # __and_sets_the_process_monitor_singleton(
    fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    # Eli (11/24/20): removed concept of process monitor singleton...hopfeully doesn't cause problems # Eli (3/11/20): there was a bug where we only passed an empty dict during the constructor of the ProcessMonitor in the main() function. So this test was created specifically to guard against that regression.
    app_info = fully_running_app_from_main_entrypoint([])
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=5)
    wait_for_subprocesses_to_start()
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    # the_process_monitor = get_mantarray_processes_monitor()
    # assert isinstance(the_process_monitor, MantarrayProcessesMonitor)

    shared_values_dict = app_info["object_access_inside_main"][
        "values_to_share_to_server"
    ]
    assert "in_simulation_mode" in shared_values_dict


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_main__calls_boot_up_function_upon_launch(
    patched_xem_scripts_folder, fully_running_app_from_main_entrypoint, mocker,
):
    spied_boot_up = mocker.spy(MantarrayProcessesManager, "boot_up_instrument")

    fully_running_app_from_main_entrypoint()
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=5)
    wait_for_subprocesses_to_start()

    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True
    spied_boot_up.assert_called_once()


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_main__stores_and_logs_directory_for_log_files_from_command_line_arguments(
    mocker, fully_running_app_from_main_entrypoint
):
    spied_info_logger = mocker.spy(main.logger, "info")

    expected_log_dir = r"C:\Users\Curi Bio\MantarrayController"
    command_line_args = [f"--log_file_dir={expected_log_dir}"]
    app_info = fully_running_app_from_main_entrypoint(command_line_args)

    app_info["mocked_configure_logging"].assert_called_once_with(
        path_to_log_folder=expected_log_dir,
        log_file_prefix="mantarray_log",
        log_level=logging.INFO,
    )
    spied_info_logger.assert_any_call(
        f"Using directory for log files: {expected_log_dir}"
    )


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_main__stores_and_logs_user_settings_and_recordings_folder_from_command_line_arguments(
    mocker, fully_running_app_from_main_entrypoint
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
        app_info = fully_running_app_from_main_entrypoint(command_line_args)

        shared_values_dict = app_info["object_access_inside_main"][
            "values_to_share_to_server"
        ]

        assert (
            shared_values_dict["config_settings"]["Customer Account ID"]
            == "14b9294a-9efb-47dd-a06e-8247e982e196"
        )
        assert (
            shared_values_dict["config_settings"]["User Account ID"]
            == "0288efbc-7705-4946-8815-02701193f766"
        )
        assert (
            shared_values_dict["config_settings"]["Recording Directory"]
            == expected_recordings_dir
        )


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
@pytest.mark.slow
def test_main__does_not_call_boot_up_function_upon_launch_if_command_line_arg_passed(
    fully_running_app_from_main_entrypoint, mocker,
):
    spied_boot_up = mocker.spy(MantarrayProcessesManager, "boot_up_instrument")

    fully_running_app_from_main_entrypoint(["--skip-mantarray-boot-up"])
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=5)
    wait_for_subprocesses_to_start()

    assert system_state_eventually_equals(SERVER_READY_STATE, 5) is True
    spied_boot_up.assert_not_called()


@pytest.mark.timeout(15)
@freeze_time("2020-07-21 21:51:36.704515")
def test_main_can_launch_server_and_processes_and_initial_boot_up_of_ok_comm_process_gets_logged__default_exe_execution(
    mocker,
    confirm_monitor_found_no_errors_in_subprocesses,
    fully_running_app_from_main_entrypoint,
):
    mocked_process_monitor_info_logger = mocker.patch.object(
        process_monitor.logger, "info", autospec=True,
    )

    mocked_main_info_logger = mocker.patch.object(main.logger, "info", autospec=True)
    fully_running_app_from_main_entrypoint()

    wait_for_subprocesses_to_start()

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
