# -*- coding: utf-8 -*-
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
import pytest

from ..fixtures import fixture_generic_queue_container
from ..fixtures_server import fixture_client_and_server_thread_and_shared_values
from ..fixtures_server import fixture_server_thread
from ..fixtures_server import fixture_test_client

__fixtures__ = [
    fixture_client_and_server_thread_and_shared_values,
    fixture_server_thread,
    fixture_generic_queue_container,
    fixture_test_client,
]


@pytest.mark.parametrize(
    ",".join(("expected_status", "expected_in_simulation", "test_description")),
    [
        (BUFFERING_STATE, False, "correctly returns buffering and False"),
        (CALIBRATION_NEEDED_STATE, True, "correctly returns buffering and True"),
        (CALIBRATING_STATE, False, "correctly returns calibrating and False"),
    ],
)
def test_system_status__returns_correct_state_and_simulation_values(
    expected_status,
    expected_in_simulation,
    test_description,
    client_and_server_thread_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_thread_and_shared_values
    shared_values_dict["system_status"] = expected_status
    shared_values_dict["in_simulation_mode"] = expected_in_simulation

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["ui_status_code"] == str(SYSTEM_STATUS_UUIDS[expected_status])
    assert response_json["in_simulation_mode"] == expected_in_simulation


def test_system_status__returns_in_simulator_mode_False_as_default_value(
    client_and_server_thread_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_thread_and_shared_values
    expected_status = CALIBRATION_NEEDED_STATE
    shared_values_dict["system_status"] = expected_status

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["ui_status_code"] == str(SYSTEM_STATUS_UUIDS[expected_status])
    assert response_json["in_simulation_mode"] is False


@pytest.mark.parametrize(
    ",".join(("expected_serial", "expected_nickname", "test_description")),
    [
        (None, "A Mantarray", "correctly returns None and nickname"),
        ("M02002000", None, "correctly returns serial number and None"),
    ],
)
def test_system_status__returns_correct_serial_number_and_nickname_with_empty_string_as_default(
    expected_serial,
    expected_nickname,
    test_description,
    client_and_server_thread_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_thread_and_shared_values
    shared_values_dict["system_status"] = SERVER_READY_STATE

    if expected_serial:
        shared_values_dict["mantarray_serial_number"] = expected_serial
    if expected_nickname:
        shared_values_dict["mantarray_nickname"] = expected_nickname

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    if expected_serial:
        assert response_json["mantarray_serial_number"] == expected_serial
    else:
        assert response_json["mantarray_serial_number"] == ""
    if expected_nickname:
        assert response_json["mantarray_nickname"] == expected_nickname
    else:
        assert response_json["mantarray_nickname"] == ""


@pytest.mark.parametrize(
    ",".join(("test_nickname", "test_description")),
    [
        ("123456789012345678901234", "raises error with no unicode characters"),
        ("1234567890123456789012à", "raises error with unicode character"),
    ],
)
def test_set_mantarray_serial_number__returns_error_code_and_message_if_serial_number_is_too_many_bytes(
    test_nickname, test_description, client_and_server_thread_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_thread_and_shared_values

    shared_values_dict["mantarray_nickname"] = dict()

    response = test_client.get(f"/set_mantarray_nickname?nickname={test_nickname}")
    assert response.status_code == 400
    assert response.status.endswith("Nickname exceeds 23 bytes") is True


def test_send_single_start_calibration_command__returns_200(
    client_and_server_thread_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_thread_and_shared_values
    response = test_client.get("/start_calibration")
    assert response.status_code == 200
