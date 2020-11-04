# -*- coding: utf-8 -*-
from queue import Queue
import threading
from threading import Thread

from flask import Flask
from immutabledict import immutabledict
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import get_the_server_thread
from mantarray_desktop_app import LocalServerPortAlreadyInUseError
from mantarray_desktop_app import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from mantarray_desktop_app import server
from mantarray_desktop_app import ServerThread
import pytest
from stdlib_utils import confirm_port_available

from ..fixtures import fixture_generic_queue_container
from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_server import _clean_up_server_thread
from ..fixtures_server import fixture_running_server_thread
from ..fixtures_server import fixture_server_thread
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_patch_print,
    fixture_server_thread,
    fixture_running_server_thread,
    fixture_generic_queue_container,
]


def test_ServerThread__init__calls_super(mocker, generic_queue_container):
    error_queue = Queue()
    to_main_queue = Queue()
    mocked_super_init = mocker.spy(Thread, "__init__")
    ServerThread(to_main_queue, error_queue, generic_queue_container)
    assert mocked_super_init.call_count == 1


def test_ServerThread__init__sets_the_module_singleton_of_the_thread_to_new_instance(
    generic_queue_container,
):
    error_queue = Queue()
    to_main_queue = Queue()
    st = ServerThread(to_main_queue, error_queue, generic_queue_container)
    value_after_first_server_init = get_the_server_thread()

    error_queue_2 = Queue()
    to_main_queue_2 = Queue()
    st_2 = ServerThread(to_main_queue_2, error_queue_2, generic_queue_container)
    value_after_second_server_init = get_the_server_thread()

    assert value_after_second_server_init != value_after_first_server_init

    # clean up
    _clean_up_server_thread(st, to_main_queue, error_queue)
    _clean_up_server_thread(st_2, to_main_queue_2, error_queue_2)


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
def test_ServerThread__check_port__calls_with_port_number_passed_in_as_kwarg(
    mocker, generic_queue_container
):
    error_queue = Queue()
    to_main_queue = Queue()
    expected_port = 7654
    st = ServerThread(
        to_main_queue, error_queue, generic_queue_container, port=expected_port
    )
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


@pytest.mark.timeout(15)
@pytest.mark.slow
def test_ServerThread__stop__shuts_down_flask_and_sends_message_to_main_queue(
    running_server_thread,
):
    st, to_main_queue, _ = running_server_thread
    st.stop()
    confirm_port_available(
        DEFAULT_SERVER_PORT_NUMBER, timeout=5
    )  # wait for server to shut down

    assert is_queue_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual.get("communication_type") == "log"
    assert "server" in actual.get("message").lower()


def test_ServerThread__soft_stop__shuts_down_flask_and_sends_message_to_main_queue(
    running_server_thread,
):
    st, to_main_queue, _ = running_server_thread
    st.soft_stop()
    confirm_port_available(
        DEFAULT_SERVER_PORT_NUMBER, timeout=5
    )  # wait for server to shut down

    assert is_queue_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual.get("communication_type") == "log"
    assert "server" in actual.get("message").lower()


def test_ServerThread__stop__does_not_raise_error_if_server_already_stopped_and_sends_message_to_main_queue(
    server_thread,
):
    st, to_main_queue, _ = server_thread
    st.stop()

    assert is_queue_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual.get("communication_type") == "log"
    assert "not running" in actual.get("message").lower()


def test_ServerThread__hard_stop__shuts_down_flask_and_drains_to_main_queue(
    running_server_thread,
):
    st, to_main_queue, _ = running_server_thread
    expected_message = "It tolls for thee"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_message, to_main_queue
    )
    actual_dict_of_queue_items = st.hard_stop()
    confirm_port_available(
        DEFAULT_SERVER_PORT_NUMBER, timeout=5
    )  # wait for server to shut down

    assert is_queue_eventually_empty(to_main_queue)

    assert actual_dict_of_queue_items["to_main"][0] == expected_message


def test_ServerThread__get_values_from_process_monitor__acquires_lock_and_returns_an_immutable_copy(
    mocker, generic_queue_container
):
    error_queue = Queue()
    to_main_queue = Queue()
    initial_dict = {"some key here": "some other value"}
    lock = threading.Lock()
    # Eli (11/3/20): still unable to test if lock was acquired.
    #   https://stackoverflow.com/questions/60187817/mocking-python-thread-locking  (no responses to question as of 11/3/20)
    #   https://stackoverflow.com/questions/11836436/how-to-mock-a-readonly-property-with-mock/11843806
    #   https://stackoverflow.com/questions/28850070/python-mocking-a-context-manager
    # mocked_lock_aquire=mocker.patch.object(lock,'acquire',new_callable=mocker.PropertyMock)

    # spied_lock_release=mocker.spy(lock,'release')
    st = ServerThread(
        to_main_queue,
        error_queue,
        generic_queue_container,
        values_from_process_monitor=initial_dict,
        lock=lock,
    )

    actual_dict = st.get_values_from_process_monitor()
    assert isinstance(actual_dict, immutabledict)
    assert actual_dict == initial_dict  # assert same values in it
    assert id(actual_dict) != id(
        initial_dict
    )  # assert they are not actually the same object in memory (it should be a copy)

    # confirm lock was acquired
    # assert mocked_lock_aquire.call_count==1

    # drain queues to avoid broken pipe errors
    _clean_up_server_thread(st, to_main_queue, error_queue)
