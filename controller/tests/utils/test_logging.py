# -*- coding: utf-8 -*-
import logging

from mantarray_desktop_app import get_redacted_string
from mantarray_desktop_app import SensitiveFormatter
from mantarray_desktop_app.utils.logging import _custom_filter
import pytest


def test_SensitiveFormatter__redacts_from_set_mantarray_nickname_request_log_entries_correctly():
    test_formatter = SensitiveFormatter("%(message)s")

    base_call = "<any text here>/set_mantarray_nickname?nickname={nickname} HTTP<any text here>"

    test_nickname = "Secret Mantarray Name"
    actual = test_formatter.format(logging.makeLogRecord({"msg": base_call.format(nickname=test_nickname)}))

    assert actual == base_call.format(nickname=get_redacted_string(len(test_nickname)))

    test_unsensitive_log_entry = "<any text here>system_status HTTP<any text here>"
    actual = test_formatter.format(logging.makeLogRecord({"msg": test_unsensitive_log_entry}))
    assert actual == test_unsensitive_log_entry


@pytest.mark.parametrize("test_route", ["login", "update_settings"])
def test_SensitiveFormatter__removes_query_params_correctly(test_route):
    test_formatter = SensitiveFormatter("%(message)s")

    base_call = f"<any text here>/{test_route}?{{params}} HTTP/1.1<any text here>"

    assert test_formatter.format(
        logging.makeLogRecord({"msg": base_call.format(params="nickname=test")})
    ) == base_call.format(params=get_redacted_string(4))


def test_customer_filter__does_not_emit_record_for_system_status_request_when_unnecessary():
    base_call = "<any text here>/system_status<any text here>HTTP/1.1 "

    assert _custom_filter(logging.makeLogRecord({"msg": base_call + "200 "})) is False
    assert _custom_filter(logging.makeLogRecord({"msg": base_call + "520 "})) is True
