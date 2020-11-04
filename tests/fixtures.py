# -*- coding: utf-8 -*-


import os
from shutil import copy
import tempfile
import threading
from typing import List
from typing import Optional

from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import flask_app
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import main
from mantarray_desktop_app import MantarrayProcessesManager
from mantarray_desktop_app import MantarrayQueueContainer
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import set_mantarray_processes_monitor
from mantarray_desktop_app import UTC_BEGINNING_DATA_ACQUISTION_UUID
import pytest
import requests
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import is_port_in_use
from stdlib_utils import resource_path

from .fixtures_file_writer import GENERIC_START_RECORDING_COMMAND

QUEUE_CHECK_TIMEOUT_SECONDS = 1.1  # for is_queue_eventually_of_size, is_queue_eventually_not_empty, is_queue_eventually_empty, put_object_into_queue_and_raise_error_if_eventually_still_empty, etc. # Eli (10/28/20) issue encountered where even 0.5 seconds was insufficient, so raising to 1 second


@pytest.fixture(scope="function", name="patched_shared_values_dict")
def fixture_patched_shared_values_dict(mocker):
    the_dict = main.get_shared_values_between_server_and_monitor()
    mocker.patch.dict(the_dict)
    yield the_dict


@pytest.fixture(scope="function", name="generic_queue_container")
def fixture_generic_queue_container():
    qc = MantarrayQueueContainer()
    yield qc

    # drain all the queues to avoid broken pipe errors
    # ...maybe this is a bad idea and the things using it should take more responsibility...if the timeout is 1.1 seconds per queue this could get long quickly


@pytest.fixture(scope="function", name="patch_print")
def fixture_patch_print(mocker):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console


@pytest.fixture(scope="function", name="patched_start_recording_shared_dict")
def fixture_patched_start_recording_shared_dict(mocker):
    the_dict = main.get_shared_values_between_server_and_monitor()
    mocker.patch.dict(the_dict)
    board_idx = 0
    timestamp = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][UTC_BEGINNING_DATA_ACQUISTION_UUID]
    the_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [timestamp]
    the_dict["config_settings"] = {
        "Customer Account ID": CURI_BIO_ACCOUNT_UUID,
        "User Account ID": CURI_BIO_USER_ACCOUNT_ID,
    }
    the_dict["adc_gain"] = 32
    the_dict["adc_offsets"] = dict()
    for well_idx in range(24):
        the_dict["adc_offsets"][well_idx] = {
            "construct": well_idx * 2,
            "ref": well_idx * 2 + 1,
        }
    the_dict["main_firmware_version"] = {
        board_idx: RunningFIFOSimulator.default_firmware_version
    }
    the_dict["sleep_firmware_version"] = {board_idx: 2.0}
    the_dict["xem_serial_number"] = {
        board_idx: RunningFIFOSimulator.default_xem_serial_number
    }
    the_dict["mantarray_serial_number"] = {
        board_idx: RunningFIFOSimulator.default_mantarray_serial_number
    }
    the_dict["mantarray_nickname"] = {
        board_idx: RunningFIFOSimulator.default_mantarray_nickname
    }
    yield the_dict


@pytest.fixture(scope="function", name="fully_running_app_from_main_entrypoint")
def fixture_fully_running_app_from_main_entrypoint(mocker, patched_shared_values_dict):
    mocked_configure_logging = mocker.patch.object(
        main, "configure_logging", autospec=True
    )

    dict_to_yield = (
        {}
    )  # Declare the dictionary up here so that the thread can be accessed after the yield even though it is declared inside the subfunction

    def _foo(command_line_args: Optional[List[str]] = None):
        if command_line_args is None:
            command_line_args = []
        main_thread = threading.Thread(target=main.main, args=[command_line_args])
        main_thread.start()

        confirm_port_in_use(
            get_server_port_number(), timeout=3
        )  # wait for server to boot up
        dict_to_yield["main_thread"] = main_thread
        dict_to_yield["mocked_configure_logging"] = mocked_configure_logging
        return dict_to_yield

    yield _foo

    # yield main_thread
    # some tests may perform the shutdown on their own to assert things about the shutdown behavior. So only attempt shutdown if server is still running.
    if is_port_in_use(get_server_port_number()):
        response = requests.get(f"{get_api_endpoint()}shutdown")
        assert response.status_code == 200
    dict_to_yield["main_thread"].join()
    confirm_port_available(get_server_port_number())
    # clean up singletons
    set_mantarray_processes_monitor(None)


@pytest.fixture(scope="function", name="test_client")
def fixture_test_client():
    """Create a test client to call Flask routes.

    Modeled on https://www.patricksoftwareblog.com/testing-a-flask-application-using-pytest/
    """
    testing_client = flask_app.test_client()

    # Establish an application context before running the tests.
    ctx = flask_app.app_context()
    ctx.push()

    yield testing_client  # this is where the testing happens!

    ctx.pop()


@pytest.fixture(scope="function", name="test_process_manager")
def fixture_test_process_manager(mocker):
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = MantarrayProcessesManager(file_directory=tmp_dir)
        manager.create_processes()
        mocker.patch.object(
            main, "get_mantarray_process_manager", autospec=True, return_value=manager
        )
        yield manager

        fw = manager.get_file_writer_process()
        if not fw.is_alive():
            # Eli (2/10/20): it is important in windows based systems to make sure to close the files before deleting them. be careful about this when running tests in a linux dev environment
            fw.close_all_files()


@pytest.fixture(scope="function", name="test_process_manager_without_created_processes")
def fixture_test_process_manager_without_created_processes(mocker):
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = MantarrayProcessesManager(file_directory=tmp_dir)

        mocker.patch.object(
            main, "get_mantarray_process_manager", autospec=True, return_value=manager
        )
        yield manager

        fw = manager.get_file_writer_process()
        if not fw.is_alive():
            # Eli (2/10/20): it is important in windows based systems to make sure to close the files before deleting them. be careful about this when running tests in a linux dev environment
            fw.close_all_files()


@pytest.fixture(scope="function", name="patched_test_xem_scripts_folder")
def fixture_patched_test_xem_scripts_folder():
    relative_path = "src"
    absolute_path = os.path.dirname(get_current_file_abs_directory())
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
    absolute_path = os.path.dirname(get_current_file_abs_directory())
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
    absolute_path = os.path.dirname(get_current_file_abs_directory())
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
        os.path.join("test_firmware", patched_firmware)
    )
    mocker.patch.object(
        process_manager,
        "get_latest_firmware",
        autospec=True,
        return_value=patched_firmware_path,
    )
    yield patched_firmware_path
