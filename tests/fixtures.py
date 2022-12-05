# -*- coding: utf-8 -*-
import base64
import json
from multiprocessing import Queue as MPQueue
import os
from shutil import copy
import tempfile
import threading
import time
from time import perf_counter
from time import sleep
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from mantarray_desktop_app import clear_server_singletons
from mantarray_desktop_app import clear_the_server_manager
from mantarray_desktop_app import DataAnalyzerProcess
from mantarray_desktop_app import FileWriterProcess
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayProcessesManager
from mantarray_desktop_app import MantarrayQueueContainer
from mantarray_desktop_app import OkCommunicationProcess
from mantarray_desktop_app.main_process import process_manager
from mantarray_desktop_app.main_process import queue_container
import pytest
import requests
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import is_port_in_use
from stdlib_utils import resource_path
from stdlib_utils import TestingQueue


PATH_TO_CURRENT_FILE = get_current_file_abs_directory()
QUEUE_CHECK_TIMEOUT_SECONDS = 1.3  # for is_queue_eventually_of_size, is_queue_eventually_not_empty, is_queue_eventually_empty, put_object_into_queue_and_raise_error_if_eventually_still_empty, etc. # Eli (10/28/20) issue encountered where even 0.5 seconds was insufficient, so raising to 1 second # Eli (12/10/20) issue encountered where 1.1 second was not enough, so now 1.2 seconds # Eli (12/15/20): issue in test_ServerManager_start__puts_error_into_queue_if_flask_run_raises_error in Windows Github where 1.2 was not enough, so now 1.3
GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS = 20
GENERIC_STORED_CUSTOMER_ID = {"id": "test_id", "password": "test_password"}


def generate_board_and_error_queues(num_boards: int = 4, queue_type=MPQueue):
    error_queue = queue_type()

    board_queues = tuple(((queue_type(), queue_type(), queue_type()) for _ in range(num_boards)))
    return board_queues, error_queue


def get_generic_base64_args(
    recording_directory: Optional[str] = None, analysis_output_dir: Optional[str] = None
) -> str:
    if not recording_directory:
        recording_directory = os.path.join(get_current_file_abs_directory(), "recordings")
    if not analysis_output_dir:
        analysis_output_dir = os.path.join(get_current_file_abs_directory(), "time_force_data")

    test_dict = {
        "log_file_id": "any",
        "recording_directory": recording_directory,
        "mag_analysis_output_dir": analysis_output_dir,
    }
    json_str = json.dumps(test_dict)
    b64_encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
    return f"--initial-base64-settings={b64_encoded}"


@pytest.fixture(scope="function", name="generic_queue_container")
def fixture_generic_queue_container():
    qc = MantarrayQueueContainer()
    yield qc
    # don't drain any queues in this fixture. Tests should drain queues themselves in order to avoid BrokenPipeErrors


@pytest.fixture(scope="function", name="patch_print")
def fixture_patch_print(mocker):
    # TODO should probably just patch the error printing function instead of a builtin function
    mocker.patch("builtins.print", autospec=True)  # don't print all the error messages to console


@pytest.fixture(scope="function", name="fully_running_app_from_main_entrypoint")
def fixture_fully_running_app_from_main_entrypoint(mocker):
    mocked_configure_logging = mocker.patch.object(main, "configure_logging", autospec=True)

    # Declare the dictionary up here so that the thread can be accessed after the yield even though it is declared inside the subfunction
    dict_to_yield = {}

    def _foo(command_line_args: Optional[List[str]] = None):
        if command_line_args is None:
            command_line_args = []
        if not any("--initial-base64-settings=" in arg for arg in command_line_args):
            command_line_args.append(get_generic_base64_args())

        thread_access_inside_main: Dict[str, Any] = dict()
        main_thread = threading.Thread(
            target=main.main,
            args=[command_line_args],
            kwargs={"object_access_for_testing": thread_access_inside_main},
        )
        main_thread.start()
        # if just testing main script, just wait for it to complete. Otherwise, wait until server is up and running
        if "--debug-test-post-build" in command_line_args:
            raise NotImplementedError(
                "fully_running_app_from_main_entrypoint currently does not except '--debug-test-post-build' in cmd line args"
            )
        if "--startup-test-options" in command_line_args:
            mocked_socketio_run = mocker.patch.object(main.socketio, "run", autospec=True)
            dict_to_yield["mocked_socketio_run"] = mocked_socketio_run
            while main_thread.is_alive():
                time.sleep(0.5)
        else:
            time.sleep(1)  # wait for the server to initialize so that the port number could be updated
            confirm_port_in_use(get_server_port_number(), timeout=4)  # wait for server to boot up
        dict_to_yield["main_thread"] = main_thread
        dict_to_yield["mocked_configure_logging"] = mocked_configure_logging
        dict_to_yield["object_access_inside_main"] = thread_access_inside_main
        return dict_to_yield

    yield _foo

    # some tests may perform the shutdown on their own to assert things about the shutdown behavior. So only attempt shutdown if server is still running.
    if is_port_in_use(get_server_port_number()):
        try:
            response = requests.get(f"{get_api_endpoint()}shutdown")
            assert response.status_code == 200
        except requests.exceptions.ConnectionError:
            # Tanner (6/21/21): sometimes the server takes a few seconds to shut down, so guard against case where it shuts down before processing this request
            pass
    if main_thread := dict_to_yield.get("main_thread"):
        main_thread.join()
    confirm_port_available(get_server_port_number(), timeout=5)
    # clean up singletons
    clear_server_singletons()


@pytest.fixture(scope="function", name="test_process_manager_creator")
def fixture_test_process_manager_creator(mocker):
    object_access_dict = {}

    def _foo(beta_2_mode=False, create_processes=True, use_testing_queues=False):
        if use_testing_queues:
            mocker.patch.object(queue_container, "Queue", autospec=True, side_effect=lambda: TestingQueue())

        with tempfile.TemporaryDirectory() as tmp_dir:
            recording_dir = os.path.join(tmp_dir, "recordings")
            mag_analysis_output_dir = os.path.join(tmp_dir, "time_force_data")
            manager = MantarrayProcessesManager(
                values_to_share_to_server={
                    "beta_2_mode": beta_2_mode,
                    "config_settings": {
                        "recording_directory": recording_dir,
                        "mag_analysis_output_dir": mag_analysis_output_dir,
                    },
                },
            )
            if use_testing_queues:
                mocker.patch.object(
                    manager,
                    "start_processes",
                    autospec=True,
                    side_effect=NotImplementedError(
                        "Cannot start processes when using a process_manager fixture setup with TestingQueues"
                    ),
                )
            if create_processes:
                manager.create_processes()
                object_access_dict["fw_process"] = manager.file_writer_process
            return manager

    yield _foo

    fw_process = object_access_dict.get("fw_process", None)
    if fw_process is not None and not fw_process.is_alive():
        # Eli (2/10/20): it is important in windows based systems to make sure to close the files before deleting them. be careful about this when running tests in a Linux development environment
        fw_process.close_all_files()

    # clean up the server singleton
    clear_the_server_manager()


def start_processes_and_wait_for_start_ups_to_complete(
    test_manager: MantarrayProcessesManager,
) -> None:
    timeout_seconds = 12
    test_manager.start_processes()
    start_time = perf_counter()
    while True:
        sleep(0.5)
        if test_manager.are_subprocess_start_ups_complete():
            return
        if perf_counter() - start_time > timeout_seconds:
            raise Exception(f"Subprocesses were not started within the timeout of {timeout_seconds} seconds")


@pytest.fixture(scope="function", name="patch_subprocess_joins")
def fixture_patch_subprocess_joins(mocker):
    mocker.patch.object(OkCommunicationProcess, "join", autospec=True)
    mocker.patch.object(FileWriterProcess, "join", autospec=True)
    mocker.patch.object(DataAnalyzerProcess, "join", autospec=True)


@pytest.fixture(scope="function", name="patch_subprocess_is_stopped_to_false")
def fixture_patch_subprocess_is_stopped_to_false(mocker):
    mocker.patch.object(OkCommunicationProcess, "is_stopped", autospec=True, return_value=False)
    mocker.patch.object(FileWriterProcess, "is_stopped", autospec=True, return_value=False)
    mocker.patch.object(DataAnalyzerProcess, "is_stopped", autospec=True, return_value=False)


@pytest.fixture(scope="function", name="patched_test_xem_scripts_folder")
def fixture_patched_test_xem_scripts_folder():
    relative_path = "src"
    absolute_path = os.path.dirname(PATH_TO_CURRENT_FILE)
    src_path = os.path.join(absolute_path, relative_path)

    real_path = os.path.join(src_path, "xem_scripts")
    tmp_path = os.path.join(src_path, "tmp_xem_scripts")
    os.rename(real_path, tmp_path)

    os.mkdir(real_path)
    test_start_cal_path = resource_path(os.path.join("test_xem_scripts", "xem_test_script.txt"))
    copy(test_start_cal_path, os.path.join(real_path, "xem_test_script.txt"))

    yield real_path, tmp_path

    for file in os.listdir(real_path):
        file_path = os.path.join(real_path, file)
        os.remove(file_path)

    os.rmdir(real_path)
    os.rename(tmp_path, real_path)


@pytest.fixture(scope="function", name="patched_xem_scripts_folder")
def fixture_patched_xem_scripts_folder():
    relative_path = "src"
    absolute_path = os.path.dirname(PATH_TO_CURRENT_FILE)
    src_path = os.path.join(absolute_path, relative_path)

    real_path = os.path.join(src_path, "xem_scripts")
    tmp_path = os.path.join(src_path, "tmp_xem_scripts")
    os.rename(real_path, tmp_path)

    os.mkdir(real_path)
    test_start_up_path = resource_path(os.path.join("test_xem_scripts", "xem_test_start_up.txt"))
    copy(test_start_up_path, os.path.join(real_path, "xem_start_up.txt"))
    test_start_cal_path = resource_path(os.path.join("test_xem_scripts", "xem_test_start_calibration.txt"))
    copy(test_start_cal_path, os.path.join(real_path, "xem_start_calibration.txt"))

    yield real_path, tmp_path

    for file in os.listdir(real_path):
        file_path = os.path.join(real_path, file)
        os.remove(file_path)
    os.rmdir(real_path)
    os.rename(tmp_path, real_path)


@pytest.fixture(scope="function", name="patched_short_calibration_script")
def fixture_patched_short_calibration_script():
    # Tanner (6/29/20): This fixture should only be used in tests that don't rely on the actual read_wire_outs providing the ADC offset values
    relative_path = "src"
    absolute_path = os.path.dirname(PATH_TO_CURRENT_FILE)
    src_path = os.path.join(absolute_path, relative_path)

    real_path = os.path.join(src_path, "xem_scripts")
    tmp_path = os.path.join(src_path, "tmp_xem_scripts")
    os.rename(real_path, tmp_path)

    os.mkdir(real_path)
    test_short_cal_path = resource_path(os.path.join("test_xem_scripts", "xem_test_short_calibration.txt"))
    copy(test_short_cal_path, os.path.join(real_path, "xem_start_calibration.txt"))

    yield real_path, tmp_path

    for file in os.listdir(real_path):
        file_path = os.path.join(real_path, file)
        os.remove(file_path)
    os.rmdir(real_path)
    os.rename(tmp_path, real_path)


@pytest.fixture(scope="function", name="patched_firmware_folder")
def fixture_patched_firmware_folder(mocker):
    patched_firmware = "test_2_3_4.bit"
    patched_firmware_path = resource_path(
        os.path.join(PATH_TO_CURRENT_FILE, "test_firmware", patched_firmware)
    )
    mocker.patch.object(
        process_manager,
        "get_latest_firmware",
        autospec=True,
        return_value=patched_firmware_path,
    )
    yield patched_firmware_path
