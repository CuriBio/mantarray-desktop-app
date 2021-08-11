# -*- coding: utf-8 -*-
from queue import Queue
import threading

from immutabledict import immutabledict
from mantarray_desktop_app import clear_server_singletons
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import get_the_server_manager
from mantarray_desktop_app import LocalServerPortAlreadyInUseError
from mantarray_desktop_app import server
from mantarray_desktop_app import ServerManager
from mantarray_desktop_app import ServerManagerNotInitializedError
from mantarray_desktop_app import ServerManagerSingletonAlreadySetError
import pytest
from stdlib_utils import confirm_port_available

from ..fixtures import fixture_generic_queue_container
from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_server import clear_the_server_manager
from ..fixtures_server import fixture_server_manager
from ..fixtures_server import fixture_test_client
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_of_size

__fixtures__ = [
    fixture_patch_print,
    fixture_server_manager,
    fixture_generic_queue_container,
    fixture_test_client,
]


def test_ServerManager__raises_an_error_if_instantiated_when_singleton_already_set(
    generic_queue_container,
):
    to_main_queue = Queue()
    ServerManager(to_main_queue, generic_queue_container)

    with pytest.raises(ServerManagerSingletonAlreadySetError):
        ServerManager(to_main_queue, generic_queue_container)

    clear_the_server_manager()


def test_ServerManager__init__sets_the_module_singleton_of_the_class_to_new_instance(
    generic_queue_container,
):
    to_main_queue = Queue()
    ServerManager(to_main_queue, generic_queue_container)
    value_after_first_server_init = get_the_server_manager()

    # need to clear the module level singleton before attempting to set it again
    clear_the_server_manager()

    to_main_queue_2 = Queue()
    ServerManager(to_main_queue_2, generic_queue_container)
    value_after_second_server_init = get_the_server_manager()

    assert value_after_second_server_init != value_after_first_server_init

    # clean up
    clear_the_server_manager()


@pytest.mark.timeout(5)
def test_ServerManager__check_port__raises_error_if_port_in_use(server_manager, mocker):
    sm, _ = server_manager
    mocked_is_port_in_use = mocker.patch.object(
        server, "is_port_in_use", autospec=True, side_effect=[True, False]
    )
    with pytest.raises(LocalServerPortAlreadyInUseError, match=str(DEFAULT_SERVER_PORT_NUMBER)):
        sm.check_port()
    mocked_is_port_in_use.assert_called_with(DEFAULT_SERVER_PORT_NUMBER)

    # make sure no error is raised if not in use
    sm.check_port()
    mocked_is_port_in_use.assert_called_with(DEFAULT_SERVER_PORT_NUMBER)


@pytest.mark.timeout(5)
def test_ServerManager__check_port__calls_with_port_number_passed_in_as_kwarg(
    mocker, generic_queue_container
):
    to_main_queue = Queue()
    expected_port = 7654
    sm = ServerManager(to_main_queue, generic_queue_container, port=expected_port)
    spied_is_port_in_use = mocker.spy(server, "is_port_in_use")

    sm.check_port()

    spied_is_port_in_use.assert_called_once_with(expected_port)

    clear_the_server_manager()


@pytest.mark.timeout(10)
def test_ServerManager__shutdown_server__clears_the_server_module_singleton(
    server_manager,
):
    sm, _ = server_manager
    # confirm the precondition
    assert get_the_server_manager() == sm
    sm.shutdown_server()
    with pytest.raises(ServerManagerNotInitializedError):
        get_the_server_manager()


@pytest.mark.timeout(15)
@pytest.mark.slow
def test_ServerManager__shutdown_server__shuts_down_flask_and_socketio__and_sends_message_to_main_queue(
    server_manager,
):
    sm, to_main_queue = server_manager
    sm.shutdown_server()
    confirm_port_available(DEFAULT_SERVER_PORT_NUMBER, timeout=5)  # wait for server to shut down

    assert is_queue_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual.get("communication_type") == "log"
    assert "server" in actual.get("message").lower()


def test_ServerManager__get_values_from_process_monitor__acquires_lock_and_returns_an_immutable_copy(
    mocker, generic_queue_container
):
    to_main_queue = Queue()
    initial_dict = {"some key here": "some other value"}
    lock = threading.Lock()
    # Eli (11/3/20): still unable to test if lock was acquired.
    #   https://stackoverflow.com/questions/60187817/mocking-python-thread-locking  (no responses to question as of 1/19/21)
    #   https://stackoverflow.com/questions/11836436/how-to-mock-a-readonly-property-with-mock/11843806
    #   https://stackoverflow.com/questions/28850070/python-mocking-a-context-manager
    # mocked_lock_aquire=mocker.patch.object(lock,'acquire',new_callable=mocker.PropertyMock)

    # spied_lock_release=mocker.spy(lock,'release')
    sm = ServerManager(
        to_main_queue,
        generic_queue_container,
        values_from_process_monitor=initial_dict,
        lock=lock,
    )

    actual_dict = sm.get_values_from_process_monitor()
    assert isinstance(actual_dict, immutabledict)
    assert actual_dict == initial_dict  # assert same values in it
    assert id(actual_dict) != id(
        initial_dict
    )  # assert they are not actually the same object in memory (it should be a copy)

    # confirm lock was acquired
    # assert mocked_lock_aquire.call_count==1

    clear_the_server_manager()


def test_get_server_address_components__returns_default_port_number_if_server_manager_not_defined(
    mocker,
):
    clear_server_singletons()
    mocker.patch.object(server, "get_the_server_manager", autospec=True, side_effect=NameError)
    _, _, actual_port = server.get_server_address_components()
    assert actual_port == DEFAULT_SERVER_PORT_NUMBER


def test_get_server_address_components__returns_default_port_number_if_server_manager_is_None(
    mocker,
):
    clear_server_singletons()
    _, _, actual_port = server.get_server_address_components()
    assert actual_port == DEFAULT_SERVER_PORT_NUMBER


def test_queue_command_to_main_puts_in_a_copy_of_the_dict(
    server_manager,
):
    _, to_main_queue = server_manager
    test_dict = {"bill": "clinton"}
    server.queue_command_to_main(test_dict)

    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == test_dict
    assert id(actual) != id(test_dict)


def test_queue_command_to_instrument_comm_puts_in_a_mutable_version_of_the_dict(
    server_manager,
):
    test_dict = immutabledict({"al": "gore"})
    server.queue_command_to_instrument_comm(test_dict)
    to_instrument_queue = (
        get_the_server_manager().queue_container().get_communication_to_instrument_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(to_instrument_queue, 1)
    actual = to_instrument_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == test_dict
    assert isinstance(actual, immutabledict) is False
