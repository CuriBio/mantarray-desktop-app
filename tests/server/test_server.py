# -*- coding: utf-8 -*-
from queue import Queue
import threading

from eventlet.green import threading as green_threading
from immutabledict import immutabledict
from mantarray_desktop_app import clear_server_singletons
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import get_the_server_thread
from mantarray_desktop_app import LocalServerPortAlreadyInUseError
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import server
from mantarray_desktop_app import ServerThread
from mantarray_desktop_app import ServerThreadNotInitializedError
from mantarray_desktop_app import ServerThreadSingletonAlreadySetError
from mantarray_desktop_app import socketio
import pytest
from stdlib_utils import confirm_parallelism_is_stopped
from stdlib_utils import confirm_port_available
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_generic_queue_container
from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_server import _clean_up_server_thread
from ..fixtures_server import fixture_running_server_thread
from ..fixtures_server import fixture_server_thread
from ..fixtures_server import fixture_test_client
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_patch_print,
    fixture_server_thread,
    fixture_running_server_thread,
    fixture_generic_queue_container,
    fixture_test_client,
]


def test_ServerThread__init__calls_super(mocker, generic_queue_container):
    error_queue = Queue()
    to_main_queue = Queue()
    mocked_super_init = mocker.spy(
        green_threading.Thread,  # pylint: disable=no-member  # Tanner (6/21/21): not sure why pylint can't find this eventlet class
        "__init__",
    )
    st = ServerThread(to_main_queue, error_queue, generic_queue_container)
    assert mocked_super_init.call_count == 1

    _clean_up_server_thread(st, to_main_queue, error_queue)


def test_ServerThread__Given_the_server_thread_module_singleton_is_not_None__When_the_ServerThread_is_instantiated__Then_it_raises_an_error(
    generic_queue_container,
):
    error_queue = Queue()
    to_main_queue = Queue()
    st_1 = ServerThread(to_main_queue, error_queue, generic_queue_container)

    with pytest.raises(ServerThreadSingletonAlreadySetError):
        ServerThread(to_main_queue, error_queue, generic_queue_container)

    _clean_up_server_thread(st_1, to_main_queue, error_queue)


def test_ServerThread__init__sets_the_module_singleton_of_the_thread_to_new_instance(
    generic_queue_container,
):
    error_queue = Queue()
    to_main_queue = Queue()
    st = ServerThread(to_main_queue, error_queue, generic_queue_container)
    value_after_first_server_init = get_the_server_thread()

    _clean_up_server_thread(
        st, to_main_queue, error_queue
    )  # need to clear the module level singleton before attempting to set it again

    error_queue_2 = Queue()
    to_main_queue_2 = Queue()
    st_2 = ServerThread(to_main_queue_2, error_queue_2, generic_queue_container)
    value_after_second_server_init = get_the_server_thread()

    assert value_after_second_server_init != value_after_first_server_init

    # clean up
    _clean_up_server_thread(st_2, to_main_queue_2, error_queue_2)


@pytest.mark.timeout(5)
def test_ServerThread__check_port__raises_error_if_port_in_use(server_thread, mocker):
    st, _, _ = server_thread
    mocked_is_port_in_use = mocker.patch.object(
        server, "is_port_in_use", autospec=True, side_effect=[True, False]
    )
    with pytest.raises(LocalServerPortAlreadyInUseError, match=str(DEFAULT_SERVER_PORT_NUMBER)):
        st.check_port()
    mocked_is_port_in_use.assert_called_with(DEFAULT_SERVER_PORT_NUMBER)

    # make sure no error is raised if not in use
    st.check_port()
    mocked_is_port_in_use.assert_called_with(DEFAULT_SERVER_PORT_NUMBER)


@pytest.mark.timeout(5)
def test_ServerThread__check_port__calls_with_port_number_passed_in_as_kwarg(mocker, generic_queue_container):
    error_queue = Queue()
    to_main_queue = Queue()
    expected_port = 7654
    st = ServerThread(to_main_queue, error_queue, generic_queue_container, port=expected_port)
    spied_is_port_in_use = mocker.spy(server, "is_port_in_use")

    st.check_port()

    spied_is_port_in_use.assert_called_once_with(expected_port)

    _clean_up_server_thread(st, to_main_queue, error_queue)


@pytest.mark.timeout(
    10
)  # the test hangs in the current implementation (using _teardown_after_loop) if the super()._teardown_after_loop isn't called, so the timeout confirms that it was implemented correctly
def test_ServerThread__Given_the_server_thread_is_running__When_it_is_hard_stopped__Then_the_module_level_singleton_is_cleared(
    running_server_thread,
):
    # since the current implementation uses _teardown_after_l
    st, _, _ = running_server_thread
    # confirm the precondition
    assert get_the_server_thread() == st
    st.hard_stop()
    with pytest.raises(ServerThreadNotInitializedError):
        get_the_server_thread()


@pytest.mark.timeout(
    10
)  # the test hangs in the current implementation (using _teardown_after_loop) if the super()._teardown_after_loop isn't called, so the timeout confirms that it was implemented correctly
def test_ServerThread__Given_the_server_thread_is_running__When_it_is_soft_stopped__Then_the_module_level_singleton_is_cleared(
    running_server_thread,
):
    st, _, _ = running_server_thread
    # confirm the precondition
    assert get_the_server_thread() == st
    st.soft_stop()
    confirm_parallelism_is_stopped(st, timeout_seconds=1)
    with pytest.raises(ServerThreadNotInitializedError):
        get_the_server_thread()


class DummyException(Exception):
    pass


@pytest.mark.timeout(15)
@pytest.mark.slow
def test_ServerThread__stop__shuts_down_flask_and_sends_message_to_main_queue(
    running_server_thread,
):
    st, to_main_queue, _ = running_server_thread
    st.stop()
    confirm_port_available(DEFAULT_SERVER_PORT_NUMBER, timeout=5)  # wait for server to shut down

    assert is_queue_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual.get("communication_type") == "log"
    assert "server" in actual.get("message").lower()


def test_ServerThread__soft_stop__shuts_down_flask_and_sends_message_to_main_queue(
    running_server_thread,
):
    st, to_main_queue, _ = running_server_thread
    st.soft_stop()
    confirm_port_available(DEFAULT_SERVER_PORT_NUMBER, timeout=5)  # wait for server to shut down

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
    assert "server" in actual.get("message").lower()


def test_ServerThread__hard_stop__drains_to_main_queue_and_data_queue_from_process_monitor(
    server_thread,
):
    st, to_main_queue, _ = server_thread
    from_pm_queue = st.get_data_queue_to_server()

    expected_message = "It tolls for thee"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_message, to_main_queue)

    expected_da_object = {"somedata": 173}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_da_object, from_pm_queue)

    actual_dict_of_queue_items = st.hard_stop()

    assert is_queue_eventually_empty(to_main_queue)
    assert is_queue_eventually_empty(from_pm_queue)

    assert actual_dict_of_queue_items["to_main"][0] == expected_message
    assert actual_dict_of_queue_items["outgoing_data"][0] == expected_da_object


def test_ServerThread__get_values_from_process_monitor__acquires_lock_and_returns_an_immutable_copy(
    mocker, generic_queue_container
):
    error_queue = Queue()
    to_main_queue = Queue()
    initial_dict = {"some key here": "some other value"}
    lock = threading.Lock()
    # Eli (11/3/20): still unable to test if lock was acquired.
    #   https://stackoverflow.com/questions/60187817/mocking-python-thread-locking  (no responses to question as of 1/19/21)
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


def test_get_server_address_components__returns_default_port_number_if_server_thread_not_defined(
    mocker,
):
    clear_server_singletons()
    mocker.patch.object(server, "get_the_server_thread", autospec=True, side_effect=NameError)
    _, _, actual_port = server.get_server_address_components()
    assert actual_port == DEFAULT_SERVER_PORT_NUMBER


def test_get_server_address_components__returns_default_port_number_if_server_thread_is_None(
    mocker,
):
    clear_server_singletons()
    _, _, actual_port = server.get_server_address_components()
    assert actual_port == DEFAULT_SERVER_PORT_NUMBER


def test_server_queue_command_to_main_puts_in_a_copy_of_the_dict(
    server_thread,
):
    _, to_main_queue, _ = server_thread
    test_dict = {"bill": "clinton"}
    server.queue_command_to_main(test_dict)

    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == test_dict
    assert id(actual) != id(test_dict)


def test_server_queue_command_to_instrument_comm_puts_in_a_mutable_version_of_the_dict(
    server_thread,
):
    test_dict = immutabledict({"al": "gore"})
    server.queue_command_to_instrument_comm(test_dict)
    to_instrument_queue = (
        get_the_server_thread().queue_container().get_communication_to_instrument_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(to_instrument_queue, 1)
    actual = to_instrument_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == test_dict
    assert isinstance(actual, immutabledict) is False


def test_ServerThread__sends_available_data_from_data_in_queue(generic_queue_container, mocker):
    msg_list = list()

    def append_msg(msg):
        msg_list.append(msg)

    mocker.patch.object(socketio, "send", autospec=True, side_effect=append_msg)

    error_queue = Queue()
    to_main_queue = Queue()
    initial_dict = {"mantarray_serial_number": {0: MantarrayMcSimulator.default_mantarray_serial_number}}
    st = ServerThread(
        to_main_queue,
        error_queue,
        generic_queue_container,
        values_from_process_monitor=initial_dict,
    )

    dummy_data = {"well_idx": 0, "data": [10, 11, 12, 13, 14]}
    data_to_server_queue = generic_queue_container.get_data_queue_to_server()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(dummy_data, data_to_server_queue)
    invoke_process_run_and_check_errors(st)
    confirm_queue_is_eventually_empty(data_to_server_queue)

    assert msg_list == [dummy_data]

    # drain queues to avoid broken pipe errors
    _clean_up_server_thread(st, to_main_queue, error_queue)
