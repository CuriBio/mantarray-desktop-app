# -*- coding: utf-8 -*-
from queue import Empty

from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import flask_app
from mantarray_desktop_app import ServerThread
import pytest
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use

from .fixtures import fixture_generic_queue_container
from .fixtures import fixture_patch_print
from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS

__fixtures__ = [fixture_patch_print, fixture_generic_queue_container]


def _clean_up_server_thread(st, to_main_queue, error_queue) -> None:
    for iter_queue in (error_queue, to_main_queue):
        while True:
            try:
                iter_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
            except Empty:
                break


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
