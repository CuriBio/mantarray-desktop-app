# -*- coding: utf-8 -*-


from multiprocessing import Queue
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
from typing import Tuple

from mantarray_desktop_app import clear_server_singletons
from mantarray_desktop_app import clear_the_server_thread
from mantarray_desktop_app import DataAnalyzerProcess
from mantarray_desktop_app import FileWriterProcess
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayProcessesManager
from mantarray_desktop_app import MantarrayQueueContainer
from mantarray_desktop_app import OkCommunicationProcess
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import ServerThread
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
import pytest
import requests
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import is_port_in_use
from stdlib_utils import resource_path


PATH_TO_CURRENT_FILE = get_current_file_abs_directory()
QUEUE_CHECK_TIMEOUT_SECONDS = 1.3  # for is_queue_eventually_of_size, is_queue_eventually_not_empty, is_queue_eventually_empty, put_object_into_queue_and_raise_error_if_eventually_still_empty, etc. # Eli (10/28/20) issue encountered where even 0.5 seconds was insufficient, so raising to 1 second # Eli (12/10/20) issue encountered where 1.1 second was not enough, so now 1.2 seconds # Eli (12/15/20): issue in test_ServerThread_start__puts_error_into_queue_if_flask_run_raises_error in Windows Github where 1.2 was not enough, so now 1.3
GENERIC_MAIN_LAUNCH_TIMEOUT_SECONDS = 15


def generate_board_and_error_queues(num_boards: int = 4):
    error_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Tuple[Exception, str]
    ] = Queue()

    board_queues: Tuple[  # pylint-disable: duplicate-code
        Tuple[
            Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
            Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
            Queue[Any],  # pylint: disable=unsubscriptable-object
        ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
    ] = tuple(
        (
            (
                Queue(),
                Queue(),
                Queue(),
            )
            for _ in range(num_boards)
        )
    )
    return board_queues, error_queue


@pytest.fixture(scope="function", name="generic_queue_container")
def fixture_generic_queue_container():
    qc = MantarrayQueueContainer()
    yield qc
    # don't drain any queues in this fixture. Tests should drain queues themselves in order to avoid BrokenPipeErrors


@pytest.fixture(scope="function", name="patch_print")
def fixture_patch_print(mocker):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console


@pytest.fixture(scope="function", name="fully_running_app_from_main_entrypoint")
def fixture_fully_running_app_from_main_entrypoint(mocker):
    mocked_configure_logging = mocker.patch.object(
        main, "configure_logging", autospec=True
    )

    dict_to_yield = (
        {}
    )  # Declare the dictionary up here so that the thread can be accessed after the yield even though it is declared inside the subfunction

    def _foo(command_line_args: Optional[List[str]] = None):
        if command_line_args is None:
            command_line_args = []
        thread_access_inside_main: Dict[str, Any] = dict()
        main_thread = threading.Thread(
            target=main.main,
            args=[command_line_args],
            kwargs={"object_access_for_testing": thread_access_inside_main},
        )
        main_thread.start()
        time.sleep(
            1
        )  # wait for the server to initialize so that the port number could be updated
        confirm_port_in_use(
            get_server_port_number(), timeout=4
        )  # wait for server to boot up
        dict_to_yield["main_thread"] = main_thread
        dict_to_yield["mocked_configure_logging"] = mocked_configure_logging
        dict_to_yield["object_access_inside_main"] = thread_access_inside_main
        return dict_to_yield

    yield _foo

    # some tests may perform the shutdown on their own to assert things about the shutdown behavior. So only attempt shutdown if server is still running.
    if is_port_in_use(get_server_port_number()):
        response = requests.get(f"{get_api_endpoint()}shutdown")
        assert response.status_code == 200
    dict_to_yield["main_thread"].join()
    confirm_port_available(get_server_port_number(), timeout=5)
    # clean up singletons
    clear_server_singletons()


@pytest.fixture(scope="function", name="test_process_manager")
def fixture_test_process_manager(mocker):
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = MantarrayProcessesManager(file_directory=tmp_dir)
        manager.create_processes()
        yield manager

        fw = manager.get_file_writer_process()
        if not fw.is_alive():
            # Eli (2/10/20): it is important in windows based systems to make sure to close the files before deleting them. be careful about this when running tests in a Linux development environment
            fw.close_all_files()

    # clean up the server singleton
    clear_the_server_thread()


@pytest.fixture(scope="function", name="test_process_manager_beta_2_mode")
def fixture_test_process_manager_beta_2_mode(mocker):
    # TODO Tanner (4/23/21): remove this fixture once beta 1 is phased out
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = MantarrayProcessesManager(
            file_directory=tmp_dir, values_to_share_to_server={"beta_2_mode": True}
        )
        manager.create_processes()
        yield manager

        fw = manager.get_file_writer_process()
        if not fw.is_alive():
            # Eli (2/10/20): it is important in windows based systems to make sure to close the files before deleting them. be careful about this when running tests in a Linux development environment
            fw.close_all_files()

    # clean up the server singleton
    clear_the_server_thread()


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
            raise Exception(
                f"Subprocesses were not started within the timeout of {timeout_seconds} seconds"
            )


@pytest.fixture(scope="function", name="patch_subprocess_joins")
def fixture_patch_subprocess_joins(mocker):
    mocker.patch.object(OkCommunicationProcess, "join", autospec=True)
    mocker.patch.object(FileWriterProcess, "join", autospec=True)
    mocker.patch.object(DataAnalyzerProcess, "join", autospec=True)
    mocker.patch.object(ServerThread, "join", autospec=True)


@pytest.fixture(scope="function", name="patch_subprocess_is_stopped_to_false")
def fixture_patch_subprocess_is_stopped_to_false(mocker):
    mocker.patch.object(
        OkCommunicationProcess, "is_stopped", autospec=True, return_value=False
    )
    mocker.patch.object(
        FileWriterProcess, "is_stopped", autospec=True, return_value=False
    )
    mocker.patch.object(
        DataAnalyzerProcess, "is_stopped", autospec=True, return_value=False
    )
    mocker.patch.object(ServerThread, "is_stopped", autospec=True, return_value=False)


@pytest.fixture(scope="function", name="test_process_manager_without_created_processes")
def fixture_test_process_manager_without_created_processes(mocker):
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = MantarrayProcessesManager(file_directory=tmp_dir)

        yield manager

        fw = manager.get_file_writer_process()
        if not fw.is_alive():
            # Eli (2/10/20): it is important in windows based systems to make sure to close the files before deleting them. be careful about this when running tests in a Linux development environment
            fw.close_all_files()


@pytest.fixture(scope="function", name="patched_test_xem_scripts_folder")
def fixture_patched_test_xem_scripts_folder():
    relative_path = "src"
    absolute_path = os.path.dirname(PATH_TO_CURRENT_FILE)
    src_path = os.path.join(absolute_path, relative_path)

    real_path = os.path.join(src_path, "xem_scripts")
    tmp_path = os.path.join(src_path, "tmp_xem_scripts")
    os.rename(real_path, tmp_path)

    os.mkdir(real_path)
    test_start_cal_path = resource_path(
        os.path.join("test_xem_scripts", "xem_test_script.txt")
    )
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
    test_start_up_path = resource_path(
        os.path.join("test_xem_scripts", "xem_test_start_up.txt")
    )
    copy(test_start_up_path, os.path.join(real_path, "xem_start_up.txt"))
    test_start_cal_path = resource_path(
        os.path.join("test_xem_scripts", "xem_test_start_calibration.txt")
    )
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
    test_short_cal_path = resource_path(
        os.path.join("test_xem_scripts", "xem_test_short_calibration.txt")
    )
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


def get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION():
    return dict(START_MANAGED_ACQUISITION_COMMUNICATION)
