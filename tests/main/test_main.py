# -*- coding: utf-8 -*-
from mantarray_desktop_app import clear_the_server_thread
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import main
from mantarray_desktop_app import ServerThread

from ..fixtures import fixture_generic_queue_container

__fixtures__ = [
    fixture_generic_queue_container,
]


def test_get_server_port_number__returns_default_port_number_if_server_never_instantiated(
    mocker,
):
    mocker.patch.object(
        main, "get_the_server_thread", autospec=True, side_effect=NameError
    )
    assert get_server_port_number() == DEFAULT_SERVER_PORT_NUMBER


def test_get_server_port_number__returns_default_port_number_if_server_has_been_cleared():
    clear_the_server_thread()
    assert get_server_port_number() == DEFAULT_SERVER_PORT_NUMBER


def test_get_server_port_number__returns_port_number_from_server_if_instantiated(
    generic_queue_container,
):
    error_queue = generic_queue_container.get_server_error_queue()
    to_main_queue = (
        generic_queue_container.get_communication_queue_from_server_to_main()
    )
    expected_port = 4321
    ServerThread(
        to_main_queue, error_queue, generic_queue_container, port=expected_port
    )

    assert get_server_port_number() == expected_port
