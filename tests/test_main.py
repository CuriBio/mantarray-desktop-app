# -*- coding: utf-8 -*-
import base64
import json
import logging
import multiprocessing
import platform
import sys
import tempfile
import threading
import time
from unittest.mock import ANY

from freezegun import freeze_time
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_mantarray_process_manager
from mantarray_desktop_app import get_mantarray_processes_monitor
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import get_shared_values_between_server_and_monitor
from mantarray_desktop_app import ImproperlyFormattedCustomerAccountUUIDError
from mantarray_desktop_app import ImproperlyFormattedUserAccountUUIDError
from mantarray_desktop_app import LocalServerPortAlreadyInUseError
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import MultiprocessingNotSetToSpawnError
from mantarray_desktop_app import prepare_to_shutdown
from mantarray_desktop_app import process_monitor
from mantarray_desktop_app import RecordingFolderDoesNotExistError
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import start_server
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
from .fixtures import fixture_test_client
from .fixtures import fixture_test_process_manager
from .fixtures import fixture_test_process_manager_without_created_processes


__fixtures__ = [
    fixture_patched_start_recording_shared_dict,
    fixture_test_client,
    fixture_test_process_manager,
    fixture_patched_shared_values_dict,
    fixture_fully_running_app_from_main_entrypoint,
    fixture_patched_xem_scripts_folder,
    fixture_test_process_manager_without_created_processes,
]


@pytest.mark.timeout(15)
def test_main_can_launch_server_with_no_args_from_entrypoint__default_exe_execution(
    mocker, fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    spied_prepare_to_shutdown = mocker.spy(main, "prepare_to_shutdown")

    _ = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()

    shutdown_response = requests.get(f"{get_api_endpoint()}shutdown")
    assert shutdown_response.status_code == 200
    confirm_port_available(
        get_server_port_number(), timeout=5
    )  # wait for shutdown to complete

    spied_prepare_to_shutdown.assert_called_once_with()


@pytest.mark.timeout(20)
@pytest.mark.slow
def test_main_entrypoint__correctly_assigns_shared_values_dictionary_to_process_monitor__and_sets_the_process_monitor_singleton(
    fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    # Eli (3/11/20): there was a bug where we only passed an empty dict during the constructor of the ProcessMonitor in the main() function. So this test was created specifically to guard against that regression.
    _ = fully_running_app_from_main_entrypoint([])
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=5)
    wait_for_subprocesses_to_start()
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5) is True

    the_process_monitor = get_mantarray_processes_monitor()
    assert isinstance(the_process_monitor, MantarrayProcessesMonitor)

    shared_values_dict = get_shared_values_between_server_and_monitor()
    assert "in_simulation_mode" in shared_values_dict


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


@pytest.mark.timeout(1)
def test_main_argparse_debug_test_post_build(mocker):
    # fails by hanging because Server would be started opened if not handled
    mocker.patch.object(main, "configure_logging", autospec=True)
    main.main(["--debug-test-post-build"])


def test_main_configures_logging(mocker):
    mocked_configure_logging = mocker.patch.object(
        main, "configure_logging", autospec=True
    )
    main.main(["--debug-test-post-build"])
    mocked_configure_logging.assert_called_once_with(
        path_to_log_folder=None, log_file_prefix="mantarray_log", log_level=logging.INFO
    )


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
    process_manager = get_mantarray_process_manager()
    process_manager_logging_level = process_manager.get_logging_level()
    assert process_manager_logging_level == logging.INFO


@pytest.mark.timeout(15)
def test_main_configures_process_manager_logging_level__and_standard_logging_level__to_debug_when_command_line_arg_passed(
    mocker, fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    app_info = fully_running_app_from_main_entrypoint(["--log-level-debug"])
    mocked_configure_logging = app_info["mocked_configure_logging"]

    mocked_configure_logging.assert_called_once_with(
        path_to_log_folder=None, log_file_prefix=ANY, log_level=logging.DEBUG
    )
    process_manager = get_mantarray_process_manager()
    process_manager_logging_level = process_manager.get_logging_level()
    assert process_manager_logging_level == logging.DEBUG


def test_main__raises_error_if_multiprocessing_start_method_not_spawn(mocker):
    mocked_get_start_method = mocker.patch.object(
        multiprocessing, "get_start_method", autospec=True, return_value="fork"
    )
    mocker.patch.object(main, "configure_logging", autospec=True)
    with pytest.raises(MultiprocessingNotSetToSpawnError, match=r"'fork'"):
        main.main(["--debug-test-post-build"])
    mocked_get_start_method.assert_called_once_with(allow_none=True)


def test_main__logs_system_info__and_software_version_at_very_start(
    mocker, patched_shared_values_dict
):
    spied_info_logger = mocker.spy(main.logger, "info")
    main_thread = threading.Thread(
        target=main.main, args=[[]], name="thread_for_main_function_in_test"
    )
    main_thread.start()
    confirm_port_in_use(
        get_server_port_number(), timeout=3
    )  # wait for server to boot up
    requests.get(f"{get_api_endpoint()}shutdown")
    main_thread.join()

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


@pytest.mark.timeout(1)
def test_start_server__raises_error_if_port_unavailable(mocker):
    mocker.patch.object(main, "is_port_in_use", autospec=True, return_value=True)
    with pytest.raises(LocalServerPortAlreadyInUseError):
        start_server()


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


@pytest.mark.parametrize(
    "test_barcode,expected_error_message,test_description",
    [
        (
            "MA1234567890",
            "Barcode exceeds max length",
            "returns error message when barcode is too long",
        ),
        (
            "MA1234567",
            "Barcode does not reach min length",
            "returns error message when barcode is too short",
        ),
        (
            "MA21044-001",
            "Barcode contains invalid character: '-'",
            "returns error message when '-' is present",
        ),
        (
            "M$210440001",
            "Barcode contains invalid character: '$'",
            "returns error message when '$' is present",
        ),
        (
            "MZ20044001",
            "Barcode contains invalid header: 'MZ'",
            "returns error message when barcode header is invalid",
        ),
        (
            "MA210440001",
            "Barcode contains invalid year: '21'",
            "returns error message when year is invalid",
        ),
        (
            "MA200000001",
            "Barcode contains invalid Julian date: '000'",
            "returns error message when julian date is too low",
        ),
        (
            "MA20367001",
            "Barcode contains invalid Julian date: '367'",
            "returns error message when julian date is too big",
        ),
        (
            "MA2004400BA",
            "Barcode contains nom-numeric string after Julian date: '00BA'",
            "returns error message when barcode ending is non-numeric",
        ),
        (
            "MA2004400A",
            "Barcode contains nom-numeric string after Julian date: '00A'",
            "returns error message when barcode ending is non-numeric",
        ),
    ],
)
def test_start_recording__returns_error_code_and_message_if_barcode_is_invalid(
    test_client, test_barcode, expected_error_message, test_description
):
    response = test_client.get(f"/start_recording?barcode={test_barcode}")
    assert response.status_code == 400
    assert response.status.endswith(expected_error_message) is True


def test_start_recording__returns_error_code_and_message_if_barcode_is_not_given(
    test_client,
):
    response = test_client.get("/start_recording")
    assert response.status_code == 400
    assert response.status.endswith("Request missing 'barcode' parameter") is True


def test_start_recording__returns_error_code_and_message_if_customer_account_id_not_set(
    test_client, patched_start_recording_shared_dict
):
    patched_start_recording_shared_dict["config_settings"]["Customer Account ID"] = ""
    response = test_client.get("/start_recording?barcode=MA200440001")
    assert response.status_code == 406
    assert response.status.endswith("Customer Account ID has not yet been set") is True


def test_start_recording__returns_error_code_and_message_if_user_account_id_not_set(
    test_client, patched_start_recording_shared_dict
):
    patched_start_recording_shared_dict["config_settings"]["User Account ID"] = ""
    response = test_client.get("/start_recording?barcode=MA200440001")
    assert response.status_code == 406
    assert response.status.endswith("User Account ID has not yet been set") is True


def test_start_recording__returns_error_code_and_message_if_called_with_is_hardware_test_mode_false_when_previously_true(
    test_client, patched_start_recording_shared_dict, test_process_manager
):
    test_process_manager.create_processes()

    response = test_client.get(
        "/start_recording?barcode=MA200440001&is_hardware_test_recording=True"
    )
    assert response.status_code == 200
    response = test_client.get(
        "/start_recording?barcode=MA200440001&is_hardware_test_recording=False"
    )
    assert response.status_code == 403
    assert (
        response.status.endswith(
            "Cannot make standard recordings after previously making hardware test recordings. Server and board must both be restarted before making any more standard recordings"
        )
        is True
    )


def test_start_recording__returns_no_error_message_with_multiple_hardware_test_recordings(
    test_client, patched_start_recording_shared_dict, test_process_manager
):
    test_process_manager.create_processes()

    response = test_client.get(
        "/start_recording?barcode=MA200440001&is_hardware_test_recording=True"
    )
    assert response.status_code == 200
    response = test_client.get(
        "/start_recording?barcode=MA200440001&is_hardware_test_recording=True"
    )
    assert response.status_code == 200


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


@pytest.mark.slow
def test_main__stores_and_logs_port_number_from_command_line_arguments(
    mocker, patched_shared_values_dict
):
    spied_info_logger = mocker.spy(main.logger, "info")

    expected_port_number = 1234
    command_line_args = [f"--port_number={expected_port_number}"]
    main_thread = threading.Thread(
        target=main.main,
        args=[command_line_args],
        name="thread_for_main_function_in_test",
    )
    main_thread.start()
    confirm_port_in_use(expected_port_number, timeout=3)
    requests.get(f"{get_api_endpoint()}shutdown")
    main_thread.join()

    actual = get_server_port_number()
    assert actual == expected_port_number
    spied_info_logger.assert_any_call(
        f"Using server port number: {expected_port_number}"
    )


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
def test_main__raises_error_when_invalid_customer_account_uuid_is_passed_in_cmd_line_args(
    mocker, patched_shared_values_dict
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


@pytest.mark.slow
def test_main__raises_error_when_invalid_user_account_uuid_is_passed_in_cmd_line_args(
    mocker, patched_shared_values_dict
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


@pytest.mark.slow
def test_main__raises_error_when_invalid_recording_folder_is_passed_in_cmd_line_args(
    mocker, patched_shared_values_dict
):
    expected_recordings_dir = "fake directory"
    test_dict = {
        "recording_directory": expected_recordings_dir,
    }
    json_str = json.dumps(test_dict)
    b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
    command_line_args = [f"--initial-base64-settings={b64_encoded}"]
    with pytest.raises(RecordingFolderDoesNotExistError, match=expected_recordings_dir):
        main.main(command_line_args)


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

    spied_okc_join = mocker.spy(okc_process, "join")
    spied_fw_join = mocker.spy(fw_process, "join")
    spied_da_join = mocker.spy(da_process, "join")

    mocked_okc_hard_stop = mocker.patch.object(okc_process, "hard_stop", autospec=True)
    mocked_fw_hard_stop = mocker.patch.object(fw_process, "hard_stop", autospec=True)
    mocked_da_hard_stop = mocker.patch.object(da_process, "hard_stop", autospec=True)
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
    spied_okc_join.assert_called_once()
    spied_fw_join.assert_called_once()
    spied_da_join.assert_called_once()
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
    mocked_logger = mocker.spy(main.logger, "info")

    response = test_client.get("/fake_route")
    assert response.status_code == 404
    assert response.status.endswith("Route not implemented") is True

    mocked_logger.assert_called_once_with(
        f"Response to HTTP Request in next log entry: {response.status}"
    )


def test_route_error_message_is_logged(mocker, test_client):
    expected_error_msg = "400 Request missing 'barcode' parameter"

    mocked_logger = mocker.spy(main.logger, "info")

    response = test_client.get("/start_recording")
    assert response.status == expected_error_msg

    assert expected_error_msg in mocked_logger.call_args[0][0]
