# -*- coding: utf-8 -*-
import logging

from mantarray_desktop_app import clear_the_server_manager
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import main
from mantarray_desktop_app import SensitiveFormatter
from mantarray_desktop_app import ServerManager

from ..fixtures import fixture_generic_queue_container
from ..fixtures_server import clear_the_server_manager()

__fixtures__ = [
    fixture_generic_queue_container,
]


def test_get_server_port_number__returns_default_port_number_if_server_never_instantiated(
    mocker,
):
    mocker.patch.object(main, "get_the_server_manager", autospec=True, side_effect=NameError)
    assert get_server_port_number() == DEFAULT_SERVER_PORT_NUMBER


def test_get_server_port_number__returns_default_port_number_if_server_has_been_cleared():
    clear_the_server_manager()
    assert get_server_port_number() == DEFAULT_SERVER_PORT_NUMBER


def test_get_server_port_number__returns_port_number_from_server_if_instantiated(
    generic_queue_container,
):
    to_main_queue = generic_queue_container.get_communication_queue_from_server_to_main()
    expected_port = 4321
    sm = ServerManager(to_main_queue, generic_queue_container, port=expected_port)

    assert get_server_port_number() == expected_port

    clear_the_server_manager()


def test_SensitiveFormatter__redacts_from_request_log_entries_correctly():
    test_formatter = SensitiveFormatter("%(message)s")

    test_nickname = "Secret Mantarray Name"
    test_sensitive_log_entry = (
        f"<any text here>set_mantarray_nickname?nickname={test_nickname} HTTP<any text here>"
    )
    actual = test_formatter.format(logging.makeLogRecord({"msg": test_sensitive_log_entry}))

    redacted_nickname = "*" * len(test_nickname)
    expected_message_with_redaction = (
        f"<any text here>set_mantarray_nickname?nickname={redacted_nickname} HTTP<any text here>"
    )
    assert actual == expected_message_with_redaction

    test_unsensitive_log_entry = "<any text here>system_status HTTP<any text here>"
    actual = test_formatter.format(logging.makeLogRecord({"msg": test_unsensitive_log_entry}))
    assert actual == test_unsensitive_log_entry
