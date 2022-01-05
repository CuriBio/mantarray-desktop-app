# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import logging
import multiprocessing
import platform
import socket
import sys
import tempfile
import time
from unittest.mock import ANY
import uuid

from freezegun import freeze_time
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_redacted_string
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import InvalidBeta2FlagOptionError
from mantarray_desktop_app import LocalServerPortAlreadyInUseError
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import MultiprocessingNotSetToSpawnError
from mantarray_desktop_app import process_monitor
from mantarray_desktop_app import redact_sensitive_info_from_path
from mantarray_desktop_app import SensitiveFormatter
from mantarray_desktop_app import wait_for_subprocesses_to_start
from mantarray_desktop_app.server import get_server_address_components
import pytest
import requests
from stdlib_utils import confirm_port_available

from ..fixtures import fixture_fully_running_app_from_main_entrypoint
from ..fixtures import fixture_patched_firmware_folder
from ..fixtures import fixture_patched_xem_scripts_folder
from ..fixtures import GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS
from ..fixtures import GENERIC_STORED_CUSTOMER_ID


__fixtures__ = [
    fixture_fully_running_app_from_main_entrypoint,
    fixture_patched_xem_scripts_folder,
    fixture_patched_firmware_folder,
]


@pytest.fixture(scope="function", name="confirm_monitor_found_no_errors_in_subprocesses")
def fixture_confirm_monitor_found_no_errors_in_subprocesses(mocker):
    mocker_error_handling_for_subprocess = mocker.spy(
        MantarrayProcessesMonitor, "_handle_error_in_subprocess"
    )
    yield mocker_error_handling_for_subprocess
    assert mocker_error_handling_for_subprocess.call_count == 0


def test_main__stores_and_logs_port_number_from_command_line_arguments(
    mocker, fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    spied_info_logger = mocker.spy(main.logger, "info")

    expected_port_number = 1234
    command_line_args = [
        f"--port-number={expected_port_number}",
        "--startup-test-options",
        "no_subprocesses",
        "no_flask",
    ]
    fully_running_app_from_main_entrypoint(command_line_args)

    actual = get_server_port_number()
    assert actual == expected_port_number
    spied_info_logger.assert_any_call(f"Using server port number: {expected_port_number}")


def test_main__redacts_log_file_dir_from_log_message_of_command_line_args(mocker):
    with tempfile.TemporaryDirectory() as expected_log_file_dir:
        spied_info_logger = mocker.spy(main.logger, "info")
        main.main(
            [
                "--debug-test-post-build",
                f"--log-file-dir={expected_log_file_dir}",
            ]
        )

        redacted_log_file_dir = redact_sensitive_info_from_path(expected_log_file_dir)
        for call_args in spied_info_logger.call_args_list:
            if "Command Line Args:" in call_args[0][0]:
                assert f"'log_file_dir': '{redacted_log_file_dir}'" in call_args[0][0]
                break
        else:
            assert False, "Command Line Args not found in any log message"


def test_main__logs_command_line_arguments(mocker):

    spied_info_logger = mocker.spy(main.logger, "info")

    main.main(["--debug-test-post-build", "--log-level-debug"])

    expected_cmd_line_args_dict = {
        "debug_test_post_build": True,
        "log_level_debug": True,
        "skip_mantarray_boot_up": False,
        "port_number": None,
        "log_file_dir": None,
        "initial_base64_settings": None,
        "expected_software_version": None,
        "no_load_firmware": False,
        "skip_software_version_verification": False,
        "beta_2_mode": False,
        "startup_test_options": None,
    }
    spied_info_logger.assert_any_call(f"Command Line Args: {expected_cmd_line_args_dict}")

    for call_args in spied_info_logger.call_args_list:
        assert "initial_base64_settings" not in call_args[0]


@pytest.mark.timeout(2)
def test_main_argparse_debug_test_post_build(mocker):
    # fails by hanging because Server would be started opened if not handled
    mocker.patch.object(main, "configure_logging", autospec=True)
    main.main(["--debug-test-post-build"])


@pytest.mark.timeout(2)
def test_main_configures_logging(mocker):
    spied_sf_init = mocker.spy(SensitiveFormatter, "__init__")
    mocked_configure_logging = mocker.patch.object(main, "configure_logging", autospec=True)
    main.main(["--debug-test-post-build"])
    mocked_configure_logging.assert_called_once_with(
        path_to_log_folder=None,
        log_file_prefix="mantarray_log",
        log_level=logging.INFO,
        logging_formatter=ANY,
    )

    spied_sf_init.assert_called_once_with(
        ANY, "[%(asctime)s UTC] %(name)s-{%(filename)s:%(lineno)d} %(levelname)s - %(message)s"
    )
    formatter = mocked_configure_logging.call_args[1]["logging_formatter"]
    assert isinstance(formatter, SensitiveFormatter)


def test_main__logs_system_info__and_software_version_at_very_start(
    mocker,
):
    with tempfile.TemporaryDirectory() as tmp:
        spied_info_logger = mocker.spy(main.logger, "info")
        expected_uuid = "c7d3e956-cfc3-42df-94d9-b3a19cf1529c"
        test_dict = {
            "log_file_uuid": expected_uuid,
            "stored_customer_id": GENERIC_STORED_CUSTOMER_ID,
            "user_account_id": "455b93eb-c78f-4494-9f73-d3291130f126",
            "zipped_recordings_dir": f"/{tmp}/zipped_recordings_dir",
            "failed_uploads_dir": f"/{tmp}/failed_uploads_dir",
            "recording_directory": f"/{tmp}",
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
        main.main(
            [
                f"--initial-base64-settings={b64_encoded}",
                "--startup-test-options",
                "no_subprocesses",
                "no_flask",
            ]
        )

        expected_name_hash = hashlib.sha512(socket.gethostname().encode(encoding="UTF-8")).hexdigest()
        spied_info_logger.assert_any_call(f"Log File UUID: {expected_uuid}")
        spied_info_logger.assert_any_call(f"SHA512 digest of Computer Name {expected_name_hash}")
        spied_info_logger.assert_any_call(f"Mantarray Controller v{CURRENT_SOFTWARE_VERSION} started")

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
        spied_info_logger.assert_any_call(
            f"Platform: {platform.platform()}, Architecture: {platform.architecture()}, Interpreter is 64-bits: {sys.maxsize > 2**32}, System Alias: {platform.system_alias(uname_sys, uname_release, uname_version)}"
        )


def test_main__raises_error_if_multiprocessing_start_method_not_spawn(mocker):
    mocked_get_start_method = mocker.patch.object(
        multiprocessing, "get_start_method", autospec=True, return_value="fork"
    )
    mocker.patch.object(main, "configure_logging", autospec=True)
    with pytest.raises(MultiprocessingNotSetToSpawnError, match=r"'fork'"):
        main.main(["--debug-test-post-build"])
    mocked_get_start_method.assert_called_once_with(allow_none=True)


def test_main_configures_process_manager_logging_level_and_standard_logging_level_to_debug_when_command_line_arg_passed(
    mocker, fully_running_app_from_main_entrypoint
):
    app_info = fully_running_app_from_main_entrypoint(
        ["--log-level-debug", "--startup-test-options", "no_subprocesses", "no_flask"]
    )
    mocked_configure_logging = app_info["mocked_configure_logging"]

    mocked_configure_logging.assert_called_once_with(
        path_to_log_folder=None, log_file_prefix=ANY, log_level=logging.DEBUG, logging_formatter=ANY
    )
    process_manager = app_info["object_access_inside_main"]["process_manager"]
    assert process_manager.get_logging_level() == logging.DEBUG


def test_main_configures_process_manager_logging_level_and_standard_logging_level_to_info_by_default(
    mocker, fully_running_app_from_main_entrypoint, patched_xem_scripts_folder
):
    app_info = fully_running_app_from_main_entrypoint(
        ["--startup-test-options", "no_subprocesses", "no_flask"]
    )
    mocked_configure_logging = app_info["mocked_configure_logging"]

    mocked_configure_logging.assert_called_once_with(
        path_to_log_folder=None, log_file_prefix=ANY, log_level=logging.INFO, logging_formatter=ANY
    )
    process_manager = app_info["object_access_inside_main"]["process_manager"]
    assert process_manager.get_logging_level() == logging.INFO


@pytest.mark.slow
@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS * 1.5)
@freeze_time("2020-07-21 21:51:36.704515")
def test_main_can_launch_server_and_processes__and_initial_boot_up_of_ok_comm_process_gets_logged__default_exe_execution(
    mocker,
    confirm_monitor_found_no_errors_in_subprocesses,
    fully_running_app_from_main_entrypoint,
    patched_firmware_folder,
):
    expected_main_pid = 1010
    mocker.patch.object(main, "getpid", autospec=True, return_value=expected_main_pid)

    mocked_process_monitor_info_logger = mocker.patch.object(
        process_monitor.logger,
        "info",
        autospec=True,
    )
    mocked_main_info_logger = mocker.patch.object(main.logger, "info", autospec=True)

    app_info = fully_running_app_from_main_entrypoint()
    wait_for_subprocesses_to_start()
    test_process_manager = app_info["object_access_inside_main"]["process_manager"]

    expected_initiated_str = "OpalKelly Communication Process initiated at"
    assert any(
        (expected_initiated_str in call[0][0] for call in mocked_process_monitor_info_logger.call_args_list)
    )

    time.sleep(
        0.5
    )  # Eli (12/9/20): There was periodic failure of asserting that this log message had been made, so trying to sleep a tiny amount to allow more time for the log message to be processed
    expected_connection_str = "Communication from the Instrument Controller: {'communication_type': 'board_connection_status_change'"
    assert any(
        (expected_connection_str in call[0][0] for call in mocked_process_monitor_info_logger.call_args_list)
    )

    mocked_main_info_logger.assert_any_call(f"Build timestamp/version: {COMPILED_EXE_BUILD_TIMESTAMP}")

    mocked_main_info_logger.assert_any_call(f"Main Process PID: {expected_main_pid}")
    mocked_main_info_logger.assert_any_call(
        f"Instrument Comm PID: {test_process_manager.get_instrument_process().pid}"
    )
    mocked_main_info_logger.assert_any_call(
        f"File Writer PID: {test_process_manager.get_file_writer_process().pid}"
    )
    mocked_main_info_logger.assert_any_call(
        f"Data Analyzer PID: {test_process_manager.get_data_analyzer_process().pid}"
    )

    shutdown_response = requests.get(f"{get_api_endpoint()}shutdown")
    assert shutdown_response.status_code == 200
    confirm_port_available(get_server_port_number(), timeout=5)  # wait for shutdown to complete


def test_main_entrypoint__correctly_assigns_shared_values_dictionary_to_process_monitor_and_process_manager(
    fully_running_app_from_main_entrypoint, mocker
):
    app_info = fully_running_app_from_main_entrypoint(
        ["--startup-test-options", "no_subprocesses", "no_flask"]
    )

    object_access_dict = app_info["object_access_inside_main"]
    shared_values_dict = object_access_dict["values_to_share_to_server"]
    test_process_monitor = object_access_dict["process_monitor"]
    assert (
        test_process_monitor._values_to_share_to_server  # pylint: disable=protected-access
        is shared_values_dict
    )
    test_process_manager = object_access_dict["process_manager"]
    assert test_process_manager.get_values_to_share_to_server() is shared_values_dict


@pytest.mark.parametrize(
    "send_command_line_arg,test_description",
    [
        (True, "creates MantarrayProcessesMonitor correctly when skipping boot up"),
        (False, "creates MantarrayProcessesMonitor correctly when not skipping boot up"),
    ],
)
def test_main__correctly_indicates_to_process_monitor_if_subprocesses_should_automatically_be_booted_up_from_cmd_line_arg_to_skip(
    send_command_line_arg,
    test_description,
    mocker,
):
    spied_init = mocker.spy(MantarrayProcessesMonitor, "__init__")

    cmd_line_args = ["--startup-test-options", "no_subprocesses", "no_flask"]
    if send_command_line_arg:
        cmd_line_args.append("--skip-mantarray-boot-up")
    main.main(cmd_line_args)
    assert spied_init.call_args[1]["boot_up_after_processes_start"] is not send_command_line_arg


@pytest.mark.parametrize(
    "send_command_line_arg,test_description",
    [
        (True, "creates MantarrayProcessesMonitor correctly when loading file"),
        (False, "creates MantarrayProcessesMonitor correctly when not loading file"),
    ],
)
def test_main__correctly_indicates_to_process_monitor_that_ok_comm_automatically_load_firmware_file_to_board_from_cmd_line_arg(
    send_command_line_arg, test_description, mocker
):
    spied_init = mocker.spy(MantarrayProcessesMonitor, "__init__")

    cmd_line_args = ["--startup-test-options", "no_subprocesses", "no_flask"]
    if send_command_line_arg:
        cmd_line_args.append("--no-load-firmware")
    main.main(cmd_line_args)
    assert spied_init.call_args[1]["load_firmware_file"] is not send_command_line_arg


def test_main__stores_and_logs_directory_for_log_files_from_command_line_arguments__and_scrubs_username_if_given(
    mocker, fully_running_app_from_main_entrypoint
):
    spied_info_logger = mocker.spy(main.logger, "info")

    expected_log_dir = r"C:\Users\Curi Bio\AppData\Local\Programs\MantarrayController"
    expected_scrubbed_log_dir = expected_log_dir.replace("Curi Bio", get_redacted_string(len("Curi Bio")))
    command_line_args = [
        f"--log-file-dir={expected_log_dir}",
        "--startup-test-options",
        "no_subprocesses",
        "no_flask",
    ]
    app_info = fully_running_app_from_main_entrypoint(command_line_args)

    app_info["mocked_configure_logging"].assert_called_once_with(
        path_to_log_folder=expected_log_dir,
        log_file_prefix="mantarray_log",
        log_level=logging.INFO,
        logging_formatter=ANY,
    )
    spied_info_logger.assert_any_call(f"Using directory for log files: {expected_scrubbed_log_dir}")


def test_main__stores_and_logs_directory_for_log_files_from_command_line_arguments__when_not_matching_expected_windows_file_path(
    mocker, fully_running_app_from_main_entrypoint
):
    spied_info_logger = mocker.spy(main.logger, "info")

    expected_log_dir = r"C:\Programs\MantarrayController"
    expected_scrubbed_log_dir = get_redacted_string(len(expected_log_dir))
    command_line_args = [
        f"--log-file-dir={expected_log_dir}",
        "--startup-test-options",
        "no_subprocesses",
        "no_flask",
    ]
    app_info = fully_running_app_from_main_entrypoint(command_line_args)

    app_info["mocked_configure_logging"].assert_called_once_with(
        path_to_log_folder=expected_log_dir,
        log_file_prefix="mantarray_log",
        log_level=logging.INFO,
        logging_formatter=ANY,
    )
    spied_info_logger.assert_any_call(f"Using directory for log files: {expected_scrubbed_log_dir}")


def test_main__stores_values_from_command_line_arguments(mocker, fully_running_app_from_main_entrypoint):
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        test_dict = {
            "stored_customer_id": GENERIC_STORED_CUSTOMER_ID,
            "user_account_id": "455b93eb-c78f-4494-9f73-d3291130f126",
            "recording_directory": expected_recordings_dir,
            "zipped_recordings_dir": f"{expected_recordings_dir}/zipped_recordings",
            "failed_uploads_dir": f"{expected_recordings_dir}/failed_uploads",
            "log_file_uuid": "91dbb151-0867-44da-a595-bd303f91927d",
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")

        command_line_args = [
            f"--initial-base64-settings={b64_encoded}",
            "--startup-test-options",
            "no_subprocesses",
            "no_flask",
        ]
        app_info = fully_running_app_from_main_entrypoint(command_line_args)

        shared_values_dict = app_info["object_access_inside_main"]["values_to_share_to_server"]
        assert shared_values_dict["beta_2_mode"] is False
        actual_config_settings = shared_values_dict["config_settings"]

        assert actual_config_settings["recording_directory"] == expected_recordings_dir
        assert shared_values_dict["log_file_uuid"] == "91dbb151-0867-44da-a595-bd303f91927d"
        assert "stored_customer_id" in shared_values_dict["stored_customer_settings"]
        assert (
            shared_values_dict["computer_name_hash"]
            == hashlib.sha512(socket.gethostname().encode(encoding="UTF-8")).hexdigest()
        )


def test_main__generates_log_file_uuid_if_none_passed_in_cmd_line_args(
    mocker, fully_running_app_from_main_entrypoint
):
    expected_log_file_uuid = uuid.UUID("ab2e730b-8be5-440b-81f8-b268c7fb3584")
    mocker.patch.object(uuid, "uuid4", autospec=True, return_value=expected_log_file_uuid)
    with tempfile.TemporaryDirectory() as tmp:
        test_dict = {
            "stored_customer_id": GENERIC_STORED_CUSTOMER_ID,
            "user_account_id": "455b93eb-c78f-4494-9f73-d3291130f126",
            "zipped_recordings_dir": f"/{tmp}/zipped_recordings",
            "failed_uploads_dir": f"/{tmp}/failed_uploads",
            "recording_directory": f"/{tmp}",
            "log_file_uuid": str(expected_log_file_uuid),
        }
        json_str = json.dumps(test_dict)
        b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")

        command_line_args = [
            f"--initial-base64-settings={b64_encoded}",
            "--startup-test-options",
            "no_subprocesses",
            "no_flask",
        ]
        app_info = fully_running_app_from_main_entrypoint(command_line_args)

        shared_values_dict = app_info["object_access_inside_main"]["values_to_share_to_server"]
        assert shared_values_dict["log_file_uuid"] == str(expected_log_file_uuid)


def test_main__puts_server_into_error_mode_if_expected_software_version_is_incorrect(mocker):
    access_dict = {}
    main.main(
        ["--expected-software-version=0.0.0", "--startup-test-options", "no_flask", "no_subprocesses"],
        object_access_for_testing=access_dict,
    )
    shared_values_dict = access_dict["values_to_share_to_server"]
    assert shared_values_dict["expected_software_version"] == "0.0.0"


def test_main__when_launched_with_an_expected_software_version_but_also_the_flag_to_skip_the_check_does_not_put_expected_software_version_in_shared_values_dict():
    access_dict = {}
    main.main(
        [
            "--expected-software-version=0.0.0",
            "--skip-software-version-verification",
            "--startup-test-options",
            "no_flask",
            "no_subprocesses",
        ],
        object_access_for_testing=access_dict,
    )
    shared_values_dict = access_dict["values_to_share_to_server"]
    assert "expected_software_version" not in shared_values_dict


@pytest.mark.timeout(GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS)
def test_main__full_launch_script_runs_as_expected(fully_running_app_from_main_entrypoint, mocker):
    spied_info = mocker.spy(main.logger, "info")
    mocked_start_bg_task = mocker.patch.object(main.socketio, "start_background_task", autospec=True)

    app_info = fully_running_app_from_main_entrypoint(
        ["--startup-test-options", "no_subprocesses", "--beta-2-mode"]
    )

    shared_values_dict = app_info["object_access_inside_main"]["values_to_share_to_server"]
    assert shared_values_dict["latest_versions"] == {
        "software": None,
        "main_firmware": None,
        "channel_firmware": None,
    }
    assert shared_values_dict["utc_timestamps_of_beginning_of_stimulation"] == [None]
    assert shared_values_dict["stimulation_running"] == [False] * 24
    assert shared_values_dict["stimulation_info"] is None

    # assert log messages were called in correct order
    expected_info_calls = iter(
        [
            "Spawning subprocesses",
            "Starting process monitor thread",
            "Starting Flask SocketIO",
            "Server shut down, about to stop processes",
            "Process monitor shut down",
            "Program exiting",
        ]
    )
    next_call_args = next(expected_info_calls)
    for call_args in spied_info.call_args_list:
        if next_call_args not in call_args[0]:
            continue
        try:
            next_call_args = next(expected_info_calls)
        except StopIteration:
            break
    else:
        assert False, f"Message: '{next_call_args}' not found"

    # make sure background thread was started correctly
    mocked_start_bg_task.assert_called_once_with(app_info["object_access_inside_main"]["data_sender"])
    # assert Flask was started correctly
    _, host, port = get_server_address_components()
    mocked_socketio_run = app_info["mocked_socketio_run"]
    mocked_socketio_run.assert_called_once_with(
        main.flask_app,
        host=host,
        port=port,
        log=main.logger,
        log_output=True,
        log_format='%(client_ip)s - - "%(request_line)s" %(status_code)s %(body_length)s - %(wall_seconds).6f',
    )


def test_main__raises_error_if_port_in_use_before_starting_socketio(mocker):
    mocked_socketio_run = mocker.patch.object(main.socketio, "run", autospec=True)
    mocker.patch.object(main, "is_port_in_use", autospec=True, return_value=True)

    port = get_server_port_number()
    with pytest.raises(LocalServerPortAlreadyInUseError, match=str(port)):
        main.main(["--startup-test-options", "no_subprocesses", "--beta-2-mode"])
    mocked_socketio_run.assert_not_called()


def test_main__disallows_cmd_line_args_that_do_not_apply_to_beta_2__when_in_beta_2_mode():
    with pytest.raises(InvalidBeta2FlagOptionError, match="--skip-mantarray-boot-up"):
        main.main(["--skip-mantarray-boot-up", "--beta-2-mode", "--debug-test-post-build"])
    with pytest.raises(InvalidBeta2FlagOptionError, match="--no-load-firmware"):
        main.main(["--no-load-firmware", "--beta-2-mode", "--debug-test-post-build"])
