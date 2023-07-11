# -*- coding: utf-8 -*-
from mantarray_desktop_app import clear_the_server_manager
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import main
from mantarray_desktop_app import ServerManager
from stdlib_utils import drain_queue
from stdlib_utils import TestingQueue

from ..fixtures import fixture_fully_running_app_from_main_entrypoint
from ..fixtures import fixture_generic_queue_container
from ..fixtures_socketio import fixture_fsio_test_client_creator

__fixtures__ = [
    fixture_generic_queue_container,
    fixture_fully_running_app_from_main_entrypoint,
    fixture_fsio_test_client_creator,
]


def test_get_server_port_number__returns_default_port_number_if_server_never_instantiated(
    mocker,
):
    mocker.patch.object(main, "get_the_server_manager", autospec=True, side_effect=NameError)
    assert get_server_port_number() == DEFAULT_SERVER_PORT_NUMBER


def test_get_server_port_number__returns_default_port_number_if_server_has_been_cleared():
    clear_the_server_manager()
    assert get_server_port_number() == DEFAULT_SERVER_PORT_NUMBER


def test_get_server_port_number__returns_port_number_from_flask_if_instantiated(
    generic_queue_container,
):
    to_main_queue = generic_queue_container.from_flask
    expected_port = 4321

    ServerManager(to_main_queue, generic_queue_container, port=expected_port)

    assert get_server_port_number() == expected_port

    clear_the_server_manager()


def test_set_up_socketio_handlers__sets_up_socketio_events_correctly(mocker, fsio_test_client_creator):
    mocked_start_bg_task = mocker.patch.object(main.socketio, "start_background_task", autospec=True)

    websocket_queue = TestingQueue()
    process_monitor_queque = TestingQueue()

    data_sender = main._set_up_socketio_handlers(websocket_queue, process_monitor_queque)

    test_clients = []
    try:
        # make sure background thread is started correctly after first connection
        test_clients.append(fsio_test_client_creator(main.socketio, main.flask_app))
        mocked_start_bg_task.assert_called_once_with(data_sender)
        # make sure background thread is not restarted correctly after second connection
        test_clients.append(fsio_test_client_creator(main.socketio, main.flask_app))
        mocked_start_bg_task.assert_called_once_with(data_sender)
    finally:
        # Tanner (1/18/22): wrap in finally block so that clients are disconnected even if the test fails
        for client in test_clients:
            if client.connected:
                client.disconnect()
    # make sure tombstone message only sent once
    assert drain_queue(websocket_queue) == [{"data_type": "tombstone"}]
