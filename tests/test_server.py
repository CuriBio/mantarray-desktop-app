# -*- coding: utf-8 -*-
from queue import Empty
from queue import Queue
from threading import Thread

from flask import Flask
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import get_shared_values_from_monitor_to_server
from mantarray_desktop_app import LocalServerPortAlreadyInUseError
from mantarray_desktop_app import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from mantarray_desktop_app import server
from mantarray_desktop_app import ServerThread
import pytest

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .helpers import is_queue_eventually_of_size


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


def test_ServerThread__init__calls_super(mocker):
    error_queue = Queue()
    to_main_queue = Queue()
    mocked_super_init = mocker.spy(Thread, "__init__")
    ServerThread(to_main_queue, error_queue)
    assert mocked_super_init.call_count == 1


def test_ServerThread__init__sets_the_module_values_from_process_monitor_to_new_dict():
    value_at_start_of_test = get_shared_values_from_monitor_to_server()
    error_queue = Queue()
    to_main_queue = Queue()
    st = ServerThread(to_main_queue, error_queue)
    value_after_server_start = get_shared_values_from_monitor_to_server()
    assert value_after_server_start == dict()
    assert id(value_after_server_start) != id(
        value_at_start_of_test
    )  # dictionary is/equality checks return true for empty dicts, so need to check the memory address using `id`
    
    _clean_up_server_thread(st,to_main_queue,error_queue)


@pytest.mark.timeout(5)
def test_ServerThread__check_port__raises_error_if_port_in_use(server_thread, mocker):
    st, _, _ = server_thread
    mocked_is_port_in_use = mocker.patch.object(
        server, "is_port_in_use", autospec=True, return_value=True
    )
    with pytest.raises(
        LocalServerPortAlreadyInUseError, match=str(DEFAULT_SERVER_PORT_NUMBER)
    ):
        st.check_port()

    mocked_is_port_in_use.assert_called_once_with(DEFAULT_SERVER_PORT_NUMBER)


@pytest.mark.timeout(5)
def test_ServerThread__check_port__calls_with_port_number_passed_in_as_kwarg(mocker):
    error_queue = Queue()
    to_main_queue = Queue()
    expected_port = 7654
    st = ServerThread(to_main_queue, error_queue, port=expected_port)
    spied_is_port_in_use = mocker.spy(server, "is_port_in_use")

    st.check_port()

    spied_is_port_in_use.assert_called_once_with(expected_port)

    _clean_up_server_thread(st, to_main_queue, error_queue)


def test_ServerThread_start__puts_error_into_queue_if_port_in_use(
    server_thread, patch_print, mocker
):
    st, _, error_queue = server_thread

    mocker.patch.object(server, "is_port_in_use", autospec=True, return_value=True)

    st.start()
    assert is_queue_eventually_of_size(error_queue, 1,) is True
    e, _ = error_queue.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
    assert isinstance(e, LocalServerPortAlreadyInUseError)


class DummyException(Exception):
    pass


def test_ServerThread_start__puts_error_into_queue_if_flask_run_raises_error(
    server_thread, patch_print, mocker
):
    st, _, error_queue = server_thread
    expected_error_msg = "Wherefore art thou Romeo"
    mocker.patch.object(
        Flask, "run", autospec=True, side_effect=DummyException(expected_error_msg)
    )

    st.start()
    assert is_queue_eventually_of_size(error_queue, 1,) is True
    e, msg = error_queue.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
    assert isinstance(e, DummyException)
    assert expected_error_msg in msg
