# -*- coding: utf-8 -*-
from queue import Empty
from queue import Queue

from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import flask_app
from mantarray_desktop_app import ServerThread
import pytest
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use

from .fixtures import fixture_patch_print
from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS

__fixtures__ = [fixture_patch_print]


def _clean_up_server_thread(st, to_main_queue, error_queue) -> None:
    for iter_queue in (error_queue, to_main_queue):
        while True:
            try:
                iter_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
            except Empty:
                break


@pytest.fixture(scope="function", name="server_thread")
def fixture_server_thread():
    error_queue = Queue()
    to_main_queue = Queue()
    st = ServerThread(to_main_queue, error_queue)
    yield st, to_main_queue, error_queue
    # drain queues to avoid broken pipe errors
    _clean_up_server_thread(st, to_main_queue, error_queue)


@pytest.fixture(scope="function", name="client_and_server_thread_and_shared_values")
def fixture_client_and_server_thread_and_shared_values(server_thread):
    """Create a test client to call Flask routes.

    Modeled on https://www.patricksoftwareblog.com/testing-a-flask-application-using-pytest/
    """

    testing_client = flask_app.test_client()

    # Establish an application context before running the tests.
    ctx = flask_app.app_context()
    ctx.push()
    st, _, _ = server_thread
    shared_values_dict = st._values_from_process_monitor
    yield testing_client, server_thread, shared_values_dict  # this is where the testing happens!

    ctx.pop()


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
