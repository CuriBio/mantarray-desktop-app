# -*- coding: utf-8 -*-
import base64
import datetime
import json
import logging
import multiprocessing
from multiprocessing import Queue
import platform
import sys
import tempfile
import threading
import time
from unittest.mock import ANY

from freezegun import freeze_time
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_mantarray_process_manager
from mantarray_desktop_app import get_mantarray_processes_monitor
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import get_shared_values_between_server_and_monitor
from mantarray_desktop_app import ImproperlyFormattedCustomerAccountUUIDError
from mantarray_desktop_app import ImproperlyFormattedUserAccountUUIDError
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import LocalServerPortAlreadyInUseError
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import MultiprocessingNotSetToSpawnError
from mantarray_desktop_app import prepare_to_shutdown
from mantarray_desktop_app import process_monitor
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import RecordingFolderDoesNotExistError
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import start_server
from mantarray_desktop_app import SUBPROCESS_POLL_DELAY_SECONDS
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
from mantarray_desktop_app import wait_for_subprocesses_to_start
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import pytest
import requests
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import is_queue_eventually_empty
from stdlib_utils import is_queue_eventually_not_empty
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import PIPE_OUT_FIFO

from .fixtures import fixture_fully_running_app_from_main_entrypoint
from .fixtures import fixture_patched_shared_values_dict
from .fixtures import fixture_patched_start_recording_shared_dict
from .fixtures import fixture_patched_xem_scripts_folder
from .fixtures import fixture_test_client
from .fixtures import fixture_test_process_manager
from .fixtures import fixture_test_process_manager_without_created_processes
from .fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND


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


@freeze_time(
    datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332597
    )
    + datetime.timedelta(
        seconds=GENERIC_STOP_RECORDING_COMMAND["timepoint_to_stop_recording_at"]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_stop_recording_command__is_received_by_file_writer__with_default__utcnow_recording_stop_time(
    test_process_manager, test_client, mocker, patched_shared_values_dict
):
    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332597
    )

    patched_shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [
        expected_acquisition_timestamp
    ]

    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    response = test_client.get("/stop_recording")
    assert response.status_code == 200
    assert is_queue_eventually_not_empty(comm_queue) is True

    response_json = response.get_json()
    assert response_json["command"] == "stop_recording"

    file_writer_process = test_process_manager.get_file_writer_process()
    invoke_process_run_and_check_errors(file_writer_process)

    assert is_queue_eventually_empty(comm_queue) is True

    file_writer_to_main = (
        test_process_manager.get_communication_queue_from_file_writer_to_main()
    )
    assert is_queue_eventually_not_empty(file_writer_to_main) is True

    communication = file_writer_to_main.get_nowait()
    assert communication["command"] == "stop_recording"

    assert (
        communication["timepoint_to_stop_recording_at"]
        == GENERIC_STOP_RECORDING_COMMAND["timepoint_to_stop_recording_at"]
    )


def test_stop_recording_command__is_received_by_file_writer__with_given_time_index_parameter(
    test_process_manager, test_client, mocker, patched_shared_values_dict
):
    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332597
    )
    patched_shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [
        expected_acquisition_timestamp
    ]

    expected_time_index = 1000
    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    response = test_client.get(f"/stop_recording?time_index={expected_time_index}")
    assert response.status_code == 200
    assert is_queue_eventually_not_empty(comm_queue) is True

    response_json = response.get_json()
    assert response_json["command"] == "stop_recording"

    file_writer_process = test_process_manager.get_file_writer_process()
    invoke_process_run_and_check_errors(file_writer_process)

    assert is_queue_eventually_empty(comm_queue) is True

    file_writer_to_main = (
        test_process_manager.get_communication_queue_from_file_writer_to_main()
    )
    assert is_queue_eventually_not_empty(file_writer_to_main) is True

    communication = file_writer_to_main.get_nowait()
    assert communication["command"] == "stop_recording"

    assert communication["timepoint_to_stop_recording_at"] == expected_time_index


def test_stop_recording_command__sets_system_status_to_live_view_active(
    test_process_manager, test_client, patched_shared_values_dict
):
    expected_acquisition_timestamp = datetime.datetime(
        year=2020, month=6, day=2, hour=17, minute=9, second=22, microsecond=362490
    )
    patched_shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [
        expected_acquisition_timestamp
    ]

    response = test_client.get("/stop_recording")
    assert response.status_code == 200

    assert patched_shared_values_dict["system_status"] == LIVE_VIEW_ACTIVE_STATE


@pytest.mark.parametrize(
    """test_num_words_to_log,test_description""",
    [
        (1, "logs 1 word"),
        (72, "logs 72 words"),
        (73, "logs 72 words given 73 num words to log"),
    ],
)
def test_read_from_fifo_command__is_received_by_ok_comm__with_correct_num_words_to_log(
    test_num_words_to_log, test_description, test_process_manager, test_client
):
    test_bytearray = produce_data(1, 0)
    fifo = Queue()
    fifo.put(test_bytearray)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)

    response = test_client.get(
        f"/insert_xem_command_into_queue/read_from_fifo?num_words_to_log={test_num_words_to_log}"
    )
    assert response.status_code == 200
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    assert is_queue_eventually_not_empty(comm_queue) is True

    invoke_process_run_and_check_errors(ok_process)

    assert is_queue_eventually_empty(comm_queue) is True

    ok_comm_to_main = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    assert is_queue_eventually_not_empty(ok_comm_to_main) is True

    communication = ok_comm_to_main.get_nowait()
    assert communication["command"] == "read_from_fifo"
    assert communication["num_words_to_log"] == test_num_words_to_log


def test_dev_begin_hardware_script__returns_correct_response(test_client):
    response = test_client.get(
        "/development/begin_hardware_script?script_type=ENUM&version=integer"
    )
    assert response.status_code == 200


def test_dev_end_hardware_script__returns_correct_response(test_client):
    response = test_client.get("/development/end_hardware_script")
    assert response.status_code == 200


def test_send_single_get_available_data_command__gets_item_from_data_out_queue_when_data_is_available(
    test_process_manager, test_client
):
    expected_response = {
        "waveform_data": {
            "basic_data": [100, 200, 300],
            "data_metrics": "dummy_metrics",
        }
    }

    data_out_queue = test_process_manager.get_data_analyzer_data_out_queue()
    data_out_queue.put(json.dumps(expected_response))
    assert is_queue_eventually_not_empty(data_out_queue) is True

    response = test_client.get("/get_available_data")
    assert response.status_code == 200

    actual = response.get_json()
    assert actual == expected_response


def test_send_single_get_available_data_command__returns_correct_error_code_when_no_data_available(
    test_process_manager, test_client
):
    response = test_client.get("/get_available_data")
    assert response.status_code == 204


@pytest.mark.parametrize(
    """expected_status,expected_in_simulation,test_description""",
    [
        (BUFFERING_STATE, False, "correctly returns buffering and False"),
        (CALIBRATION_NEEDED_STATE, True, "correctly returns buffering and True"),
        (CALIBRATING_STATE, False, "correctly returns calibrating and False"),
    ],
)
def test_system_status__returns_correct_state_and_simulation_values(
    test_client,
    patched_shared_values_dict,
    expected_status,
    expected_in_simulation,
    test_description,
):
    patched_shared_values_dict["system_status"] = expected_status
    patched_shared_values_dict["in_simulation_mode"] = expected_in_simulation

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["ui_status_code"] == str(SYSTEM_STATUS_UUIDS[expected_status])
    assert response_json["in_simulation_mode"] == expected_in_simulation


def test_system_status__returns_in_simulator_mode_False_as_default_value(
    test_client, patched_shared_values_dict
):
    expected_status = CALIBRATION_NEEDED_STATE
    patched_shared_values_dict["system_status"] = expected_status

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["ui_status_code"] == str(SYSTEM_STATUS_UUIDS[expected_status])
    assert response_json["in_simulation_mode"] is False


@pytest.mark.parametrize(
    """expected_serial,expected_nickname,test_description""",
    [
        (None, "A Mantarray", "correctly returns None and nickname"),
        ("M02002000", None, "correctly returns serial number and None"),
    ],
)
def test_system_status__returns_correct_serial_number_and_nickname_with_empty_string_as_default(
    expected_serial,
    expected_nickname,
    test_description,
    test_client,
    patched_shared_values_dict,
):
    patched_shared_values_dict["system_status"] = SERVER_READY_STATE

    if expected_serial:
        patched_shared_values_dict["mantarray_serial_number"] = expected_serial
    if expected_nickname:
        patched_shared_values_dict["mantarray_nickname"] = expected_nickname

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    if expected_serial:
        assert response_json["mantarray_serial_number"] == expected_serial
    else:
        assert response_json["mantarray_serial_number"] == ""
    if expected_nickname:
        assert response_json["mantarray_nickname"] == expected_nickname
    else:
        assert response_json["mantarray_nickname"] == ""


def test_main__handles_logging_after_request_when_get_available_data_is_called(
    test_process_manager, test_client, mocker
):
    spied_logger = mocker.spy(main.logger, "info")

    test_process_manager.create_processes()
    data_out_queue = test_process_manager.get_data_analyzer_data_out_queue()

    test_data = json.dumps(
        {
            "waveform_data": {
                "basic_data": [100, 200, 300],
                "data_metrics": "dummy_metrics",
            }
        }
    )
    data_out_queue.put(test_data)
    assert is_queue_eventually_not_empty(data_out_queue) is True

    response = test_client.get("/get_available_data")
    assert response.status_code == 200
    assert "basic_data" not in spied_logger.call_args[0][0]
    assert "waveform_data" in spied_logger.call_args[0][0]
    assert "data_metrics" in spied_logger.call_args[0][0]

    response = test_client.get("/get_available_data")
    assert response.status_code == 204


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


@pytest.mark.parametrize(
    "test_serial_number,expected_error_message,test_description",
    [
        (
            "M120019000",
            "Serial Number exceeds max length",
            "returns error message when too long",
        ),
        (
            "M1200190",
            "Serial Number does not reach min length",
            "returns error message when too short",
        ),
        (
            "M02-36700",
            "Serial Number contains invalid character: '-'",
            "returns error message with invalid character",
        ),
        (
            "M12001900",
            "Serial Number contains invalid header: 'M1'",
            "returns error message with invalid header",
        ),
        (
            "M01901900",
            "Serial Number contains invalid year: '19'",
            "returns error message with year 19",
        ),
        (
            "M02101900",
            "Serial Number contains invalid year: '21'",
            "returns error message with year 21",
        ),
        (
            "M02000000",
            "Serial Number contains invalid Julian date: '000'",
            "returns error message with invalid Julian date 000",
        ),
        (
            "M02036700",
            "Serial Number contains invalid Julian date: '367'",
            "returns error message with invalid Julian date 367",
        ),
    ],
)
def test_set_mantarray_serial_number__returns_error_code_and_message_if_serial_number_is_invalid(
    test_client,
    test_serial_number,
    expected_error_message,
    test_description,
    patched_shared_values_dict,
):
    patched_shared_values_dict["mantarray_serial_number"] = dict()

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={test_serial_number}"
    )
    assert response.status_code == 400
    assert response.status.endswith(expected_error_message) is True


@pytest.mark.parametrize(
    "test_nickname,test_decsription",
    [
        ("123456789012345678901234", "raises error with no unicode characters"),
        ("1234567890123456789012à", "raises error with unicode character"),
    ],
)
def test_set_mantarray_serial_number__returns_error_code_and_message_if_serial_number_is_too_many_bytes(
    test_nickname, test_decsription, test_client, patched_shared_values_dict
):
    patched_shared_values_dict["mantarray_nickname"] = dict()

    response = test_client.get(f"/set_mantarray_nickname?nickname={test_nickname}")
    assert response.status_code == 400
    assert response.status.endswith("Nickname exceeds 23 bytes") is True


def test_start_managed_acquisition__returns_error_code_and_message_if_mantarray_serial_number_is_empty(
    test_client, patched_shared_values_dict
):
    board_idx = 0
    patched_shared_values_dict["mantarray_serial_number"] = {board_idx: ""}

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 406
    assert (
        response.status.endswith("Mantarray has not been assigned a Serial Number")
        is True
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


@pytest.mark.parametrize(
    "test_uuid,test_description",
    [
        ("", "returns error_message when uuid is empty",),
        (
            "e140e2b-397a-427b-81f3-4f889c5181a9",
            "returns error_message when uuid is invalid",
        ),
    ],
)
def test_update_settings__returns_error_message_for_invalid_customer_account_uuid(
    test_uuid, test_description, test_client, patched_shared_values_dict, mocker
):
    response = test_client.get(f"/update_settings?customer_account_uuid={test_uuid}")
    assert response.status_code == 400
    assert (
        response.status.endswith(
            f"{repr(ImproperlyFormattedCustomerAccountUUIDError(test_uuid))}"
        )
        is True
    )


@pytest.mark.parametrize(
    "test_uuid,test_description",
    [
        ("", "returns error_message when uuid is empty",),
        (
            "11e140e2b-397a-427b-81f3-4f889c5181a9",
            "returns error_message when uuid is invalid",
        ),
    ],
)
def test_update_settings__returns_error_message_for_invalid_user_account_uuid(
    test_uuid, test_description, test_client, patched_shared_values_dict, mocker
):
    response = test_client.get(f"/update_settings?user_account_uuid={test_uuid}")
    assert response.status_code == 400
    assert (
        response.status.endswith(
            f"{repr(ImproperlyFormattedUserAccountUUIDError(test_uuid))}"
        )
        is True
    )


def test_update_settings__returns_error_message_when_recording_directory_does_not_exist(
    test_client, patched_shared_values_dict
):
    test_dir = "fake_dir/fake_sub_dir"
    response = test_client.get(f"/update_settings?recording_directory={test_dir}")
    assert response.status_code == 400
    assert (
        response.status.endswith(f"{repr(RecordingFolderDoesNotExistError(test_dir))}")
        is True
    )


def test_update_settings__returns_error_message_when_unexpected_argument_is_given(
    test_client, patched_shared_values_dict
):
    test_arg = "bad_arg"
    response = test_client.get(f"/update_settings?{test_arg}=True")
    assert response.status_code == 400
    assert response.status.endswith(f"Invalid argument given: {test_arg}") is True


def test_update_settings__stores_values_in_shared_values_dict__and_recordings_folder_in_file_writer_and_process_manager__and_logs_recording_folder(
    test_client, patched_shared_values_dict, test_process_manager, mocker
):
    spied_info_logger = mocker.spy(main.logger, "info")
    expected_customer_uuid = "2dc06596-9cea-46a2-9ddd-a0d8a0f13584"
    expected_user_uuid = "21875600-ca08-44c4-b1ea-0877b3c63ca7"
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = test_client.get(
            f"/update_settings?customer_account_uuid={expected_customer_uuid}&user_account_uuid={expected_user_uuid}&recording_directory={expected_recordings_dir}"
        )
        assert response.status_code == 200

        assert (
            patched_shared_values_dict["config_settings"]["Customer Account ID"]
            == expected_customer_uuid
        )
        assert (
            patched_shared_values_dict["config_settings"]["User Account ID"]
            == expected_user_uuid
        )
        assert (
            patched_shared_values_dict["config_settings"]["Recording Directory"]
            == expected_recordings_dir
        )
        assert test_process_manager.get_file_directory() == expected_recordings_dir

        spied_info_logger.assert_any_call(
            f"Using directory for recording files: {expected_recordings_dir}"
        )


def test_update_settings__replaces_only_new_values_in_shared_values_dict(
    test_client, patched_shared_values_dict, test_process_manager, mocker
):
    expected_customer_uuid = "b357cab5-adba-4cc3-a805-93b0b57a6d72"
    expected_user_uuid = "05dab94c-88dc-4505-ae4f-be6fa4a6f5f0"

    patched_shared_values_dict["config_settings"] = {
        "Customer Account ID": "2dc06596-9cea-46a2-9ddd-a0d8a0f13584",
        "User Account ID": expected_user_uuid,
    }
    response = test_client.get(
        f"/update_settings?customer_account_uuid={expected_customer_uuid}"
    )
    assert response.status_code == 200

    assert (
        patched_shared_values_dict["config_settings"]["Customer Account ID"]
        == expected_customer_uuid
    )
    assert (
        patched_shared_values_dict["config_settings"]["User Account ID"]
        == expected_user_uuid
    )


def test_update_settings__replaces_curi_with_default_account_uuids(
    test_client, patched_shared_values_dict
):
    response = test_client.get("/update_settings?customer_account_uuid=curi")
    assert response.status_code == 200

    assert patched_shared_values_dict["config_settings"]["Customer Account ID"] == str(
        CURI_BIO_ACCOUNT_UUID
    )
    assert patched_shared_values_dict["config_settings"]["User Account ID"] == str(
        CURI_BIO_USER_ACCOUNT_ID
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
