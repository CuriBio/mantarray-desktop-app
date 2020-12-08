# -*- coding: utf-8 -*-
from queue import Empty

from mantarray_desktop_app import clear_the_server_thread
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import flask_app
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import ServerThread
from mantarray_desktop_app import UTC_BEGINNING_DATA_ACQUISTION_UUID
import pytest
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use

from .fixtures import fixture_generic_queue_container
from .fixtures import fixture_patch_print
from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from .fixtures_process_monitor import fixture_test_monitor

__fixtures__ = [
    fixture_patch_print,
    fixture_generic_queue_container,
    fixture_test_monitor,
]


def _clean_up_server_thread(st, to_main_queue, error_queue) -> None:
    for iter_queue in (error_queue, to_main_queue):
        while True:
            try:
                iter_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
            except Empty:
                break
    # clean up singletons
    clear_the_server_thread()


@pytest.fixture(scope="function", name="server_thread")
def fixture_server_thread(generic_queue_container):
    error_queue = generic_queue_container.get_server_error_queue()
    to_main_queue = (
        generic_queue_container.get_communication_queue_from_server_to_main()
    )

    st = ServerThread(to_main_queue, error_queue, generic_queue_container)

    yield st, to_main_queue, error_queue
    # drain queues to avoid broken pipe errors
    _clean_up_server_thread(st, to_main_queue, error_queue)


@pytest.fixture(scope="function", name="test_client")
def fixture_test_client():
    """Create a test client to call Flask routes.

    Modeled on https://www.patricksoftwareblog.com/testing-a-flask-application-using-pytest/

    Note, the routes require a ServerThread to be created using another fixture or within the test itself before the test Client will be fully functional.
    """
    testing_client = flask_app.test_client()

    # Establish an application context before running the tests.
    ctx = flask_app.app_context()
    ctx.push()
    yield testing_client

    ctx.pop()


@pytest.fixture(scope="function", name="client_and_server_thread_and_shared_values")
def fixture_client_and_server_thread_and_shared_values(server_thread, test_client):

    st, _, _ = server_thread
    shared_values_dict = st._values_from_process_monitor
    yield test_client, server_thread, shared_values_dict


@pytest.fixture(scope="function", name="running_server_thread")
def fixture_running_server_thread(server_thread):
    st, _, _ = server_thread
    confirm_port_available(
        DEFAULT_SERVER_PORT_NUMBER
    )  # confirm port is not already active prior to starting test
    st.start()
    confirm_port_in_use(
        DEFAULT_SERVER_PORT_NUMBER, timeout=3
    )  # wait for server to boot up
    yield server_thread

    # clean up
    st.hard_stop()


@pytest.fixture(scope="function", name="generic_start_recording_info_in_shared_dict")
def fixture_generic_start_recording_info_in_shared_dict(test_monitor,):
    _, shared_values_dict, _, _ = test_monitor
    # _,_, shared_values_dict=client_and_server_thread_and_shared_values
    board_idx = 0
    timestamp = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][UTC_BEGINNING_DATA_ACQUISTION_UUID]
    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [timestamp]
    shared_values_dict["config_settings"] = {
        "Customer Account ID": CURI_BIO_ACCOUNT_UUID,
        "User Account ID": CURI_BIO_USER_ACCOUNT_ID,
    }
    shared_values_dict["adc_gain"] = 32
    shared_values_dict["adc_offsets"] = dict()
    for well_idx in range(24):
        shared_values_dict["adc_offsets"][well_idx] = {
            "construct": well_idx * 2,
            "ref": well_idx * 2 + 1,
        }
    shared_values_dict["main_firmware_version"] = {
        board_idx: RunningFIFOSimulator.default_firmware_version
    }
    shared_values_dict["sleep_firmware_version"] = {board_idx: 2.0}
    shared_values_dict["xem_serial_number"] = {
        board_idx: RunningFIFOSimulator.default_xem_serial_number
    }
    shared_values_dict["mantarray_serial_number"] = {
        board_idx: RunningFIFOSimulator.default_mantarray_serial_number
    }
    shared_values_dict["mantarray_nickname"] = {
        board_idx: RunningFIFOSimulator.default_mantarray_nickname
    }
    yield shared_values_dict
