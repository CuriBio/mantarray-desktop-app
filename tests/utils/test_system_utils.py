# -*- coding: utf-8 -*-
import time

from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
from mantarray_desktop_app import SystemStartUpError
from mantarray_desktop_app import wait_for_subprocesses_to_start
from mantarray_desktop_app.utils import system
import pytest
import requests
from requests import Response


@pytest.fixture(scope="function", name="patch_api_endpoint")
def fixture_patch_api_endpoint(mocker):
    dummy_api_endpoint = "blahblah"
    mocker.patch.object(
        system, "get_api_endpoint", autospec=True, return_value=dummy_api_endpoint
    )  # Eli (11/18/20) mocking so that the ServerManager doesn't need to be started
    yield dummy_api_endpoint


def test_system_state_eventually_equals__returns_True_after_system_state_equals_given_value(
    mocker, patch_api_endpoint
):
    expected_state = CALIBRATED_STATE
    mocked_status_values = [
        {"ui_status_code": str(SYSTEM_STATUS_UUIDS[CALIBRATING_STATE])},
        {"ui_status_code": str(SYSTEM_STATUS_UUIDS[CALIBRATING_STATE])},
        {"ui_status_code": str(SYSTEM_STATUS_UUIDS[expected_state])},
    ]

    # mocker.patch.object(system_utils,'get_api_endpoint',autospec=True,return_value=dummy_api_endpoint) # Eli (11/18/20) mocking so that the ServerManager doesn't need to be started
    dummy_response = Response()
    mocker.patch.object(dummy_response, "json", side_effect=mocked_status_values)
    mocker.patch.object(system, "sleep", autospec=True)  # mock this to run the test faster
    mocked_get = mocker.patch.object(system.requests, "get", autospec=True, return_value=dummy_response)

    result = system_state_eventually_equals(expected_state, 2)
    assert result is True

    num_calls = len(mocked_status_values)
    expected_calls = [mocker.call(f"{patch_api_endpoint}system_status") for _ in range(num_calls)]
    mocked_get.assert_has_calls(expected_calls)


def test_system_state_eventually_equals__returns_False_after_timeout_is_reached(mocker, patch_api_endpoint):
    test_timeout = 1
    mocked_counter_vals = [0, test_timeout]
    mocker.patch.object(time, "perf_counter", side_effect=mocked_counter_vals)

    mocked_json = {"ui_status_code": str(SYSTEM_STATUS_UUIDS[CALIBRATION_NEEDED_STATE])}
    dummy_response = Response()
    mocker.patch.object(dummy_response, "json", return_value=mocked_json)
    mocked_get = mocker.patch.object(system.requests, "get", autospec=True, return_value=dummy_response)

    result = system_state_eventually_equals(RECORDING_STATE, test_timeout)
    assert result is False

    mocked_get.assert_called_once()


def test_wait_for_subprocesses_to_start__waits_until_system_status_route_is_ready_and_state_equals_server_ready(
    mocker, patch_api_endpoint
):
    mocked_responses = [Response() for _ in range(6)]
    mocked_status_codes = [500, 123, 200, 200, 200, 200]
    mocked_json = [
        {"ui_status_code": str(SYSTEM_STATUS_UUIDS[SERVER_INITIALIZING_STATE])},
        {"ui_status_code": str(SYSTEM_STATUS_UUIDS[SERVER_INITIALIZING_STATE])},
        {"ui_status_code": str(SYSTEM_STATUS_UUIDS[SERVER_INITIALIZING_STATE])},
        {"ui_status_code": str(SYSTEM_STATUS_UUIDS[SERVER_INITIALIZING_STATE])},
        {"ui_status_code": str(SYSTEM_STATUS_UUIDS[SERVER_INITIALIZING_STATE])},
        {"ui_status_code": str(SYSTEM_STATUS_UUIDS[SERVER_READY_STATE])},
    ]
    for i, response in enumerate(mocked_responses):
        mocker.patch.object(response, "json", return_value=mocked_json[i])
        mocker.patch.multiple(response, status_code=mocked_status_codes[i])
    mocked_get = mocker.patch.object(system.requests, "get", autospec=True, side_effect=mocked_responses)
    num_get_calls = len(mocked_responses)
    expected_get_calls = [mocker.call(f"{patch_api_endpoint}system_status") for _ in range(num_get_calls)]

    wait_for_subprocesses_to_start()

    num_get_calls = len(mocked_status_codes)
    mocked_get.assert_has_calls(expected_get_calls)


def test_wait_for_subprocesses_to_start__raises_error_if_state_does_not_reach_server_ready(
    mocker, patch_api_endpoint
):
    mocked_json = {"ui_status_code": str(SYSTEM_STATUS_UUIDS[SERVER_INITIALIZING_STATE])}
    mocked_response = Response()
    mocker.patch.multiple(mocked_response, status_code=200)
    mocker.patch.object(mocked_response, "json", return_value=mocked_json)
    mocker.patch.object(time, "perf_counter", side_effect=[0, 20])
    mocker.patch.object(system.requests, "get", autospec=True, return_value=mocked_response)
    mocker.patch.object(system, "system_state_eventually_equals", return_value=False)

    with pytest.raises(SystemStartUpError):
        wait_for_subprocesses_to_start()


def test_wait_for_subprocesses_to_start__raises_error_if_server_is_never_able_to_be_connected_to(
    mocker,
):
    mocker.patch.object(time, "perf_counter", side_effect=[0, 20])
    mocker.patch.object(
        system.requests,
        "get",
        autospec=True,
        side_effect=requests.exceptions.ConnectionError,
    )

    with pytest.raises(SystemStartUpError):
        wait_for_subprocesses_to_start()
