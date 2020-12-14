# -*- coding: utf-8 -*-
import json

from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import ImproperlyFormattedCustomerAccountUUIDError
from mantarray_desktop_app import ImproperlyFormattedUserAccountUUIDError
from mantarray_desktop_app import RecordingFolderDoesNotExistError
from mantarray_desktop_app import server
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
import pytest

from ..fixtures import fixture_generic_queue_container
from ..fixtures import fixture_test_process_manager
from ..fixtures_process_monitor import fixture_test_monitor
from ..fixtures_server import fixture_client_and_server_thread_and_shared_values
from ..fixtures_server import fixture_generic_start_recording_info_in_shared_dict
from ..fixtures_server import fixture_server_thread
from ..fixtures_server import fixture_test_client
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_client_and_server_thread_and_shared_values,
    fixture_server_thread,
    fixture_test_client,
    fixture_generic_queue_container,
    fixture_generic_start_recording_info_in_shared_dict,
    fixture_test_monitor,
    fixture_test_process_manager,
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
    test_nickname,
    test_description,
    client_and_server_thread_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_thread_and_shared_values

    shared_values_dict["mantarray_nickname"] = dict()

    response = test_client.get(f"/set_mantarray_nickname?nickname={test_nickname}")
    assert response.status_code == 400
    assert response.status.endswith("Nickname exceeds 23 bytes") is True


def test_send_single_start_calibration_command__returns_200(
    client_and_server_thread_and_shared_values,
):
    test_client, _, _ = client_and_server_thread_and_shared_values
    response = test_client.get("/start_calibration")
    assert response.status_code == 200


def test_dev_begin_hardware_script__returns_correct_response(test_client):
    response = test_client.get(
        "/development/begin_hardware_script?script_type=ENUM&version=integer"
    )
    assert response.status_code == 200


def test_dev_end_hardware_script__returns_correct_response(test_client):
    response = test_client.get("/development/end_hardware_script")
    assert response.status_code == 200


def test_send_single_get_available_data_command__returns_correct_error_code_when_no_data_available(
    client_and_server_thread_and_shared_values,
):
    test_client, _, _ = client_and_server_thread_and_shared_values

    response = test_client.get("/get_available_data")
    assert response.status_code == 204


def test_send_single_get_available_data_command__gets_item_from_data_out_queue_when_data_is_available(
    client_and_server_thread_and_shared_values,
):
    test_client, server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = server_info
    expected_response = {
        "waveform_data": {
            "basic_data": [100, 200, 300],
            "data_metrics": "dummy_metrics",
        }
    }

    data_out_queue = test_server.get_data_analyzer_data_out_queue()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        json.dumps(expected_response), data_out_queue
    )

    response = test_client.get("/get_available_data")
    assert response.status_code == 200

    actual = response.get_json()
    assert actual == expected_response


def test_server__handles_logging_after_request_when_get_available_data_is_called(
    client_and_server_thread_and_shared_values, mocker
):
    test_client, server_info, _ = client_and_server_thread_and_shared_values
    test_server, _, _ = server_info

    spied_logger = mocker.spy(server.logger, "info")

    # test_process_manager.create_processes()
    data_out_queue = test_server.get_data_analyzer_data_out_queue()

    test_data = json.dumps(
        {
            "waveform_data": {
                "basic_data": [100, 200, 300],
                "data_metrics": "dummy_metrics",
            }
        }
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_data, data_out_queue
    )

    response = test_client.get("/get_available_data")
    assert response.status_code == 200
    assert "basic_data" not in spied_logger.call_args[0][0]
    assert "waveform_data" in spied_logger.call_args[0][0]
    assert "data_metrics" in spied_logger.call_args[0][0]

    response = test_client.get("/get_available_data")
    assert response.status_code == 204


@pytest.mark.parametrize(
    ",".join(("test_serial_number", "expected_error_message", "test_description")),
    [
        (
            "M120019000",
            "Serial Number exceeds max length",
            "returns error message when too long",
        ),
        (
            "M1200190",
            "Serial Number does not reach min length",
            "returns error message when too short",
        ),
        (
            "M02-36700",
            "Serial Number contains invalid character: '-'",
            "returns error message with invalid character",
        ),
        (
            "M12001900",
            "Serial Number contains invalid header: 'M1'",
            "returns error message with invalid header",
        ),
        (
            "M01901900",
            "Serial Number contains invalid year: '19'",
            "returns error message with year 19",
        ),
        (
            "M02101900",
            "Serial Number contains invalid year: '21'",
            "returns error message with year 21",
        ),
        (
            "M02000000",
            "Serial Number contains invalid Julian date: '000'",
            "returns error message with invalid Julian date 000",
        ),
        (
            "M02036700",
            "Serial Number contains invalid Julian date: '367'",
            "returns error message with invalid Julian date 367",
        ),
    ],
)
def test_set_mantarray_serial_number__returns_error_code_and_message_if_serial_number_is_invalid(
    test_serial_number,
    expected_error_message,
    test_description,
    client_and_server_thread_and_shared_values,
    mocker,
):
    test_client, _, _ = client_and_server_thread_and_shared_values

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={test_serial_number}"
    )
    assert response.status_code == 400
    assert response.status.endswith(expected_error_message) is True


def test_start_managed_acquisition__returns_error_code_and_message_if_mantarray_serial_number_is_empty(
    client_and_server_thread_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_thread_and_shared_values
    board_idx = 0
    shared_values_dict["mantarray_serial_number"] = {board_idx: ""}

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 406
    assert (
        response.status.endswith("Mantarray has not been assigned a Serial Number")
        is True
    )


@pytest.mark.parametrize(
    "test_uuid,test_description",
    [
        (
            "",
            "returns error_message when uuid is empty",
        ),
        (
            "e140e2b-397a-427b-81f3-4f889c5181a9",
            "returns error_message when uuid is invalid",
        ),
    ],
)
def test_update_settings__returns_error_message_for_invalid_customer_account_uuid(
    test_uuid,
    test_description,
    test_client,
):
    response = test_client.get(f"/update_settings?customer_account_uuid={test_uuid}")
    assert response.status_code == 400
    assert (
        response.status.endswith(
            f"{repr(ImproperlyFormattedCustomerAccountUUIDError(test_uuid))}"
        )
        is True
    )


def test_update_settings__returns_error_message_when_recording_directory_does_not_exist(
    test_client,
):
    test_dir = "fake_dir/fake_sub_dir"
    response = test_client.get(f"/update_settings?recording_directory={test_dir}")
    assert response.status_code == 400
    assert (
        response.status.endswith(f"{repr(RecordingFolderDoesNotExistError(test_dir))}")
        is True
    )


def test_update_settings__returns_error_message_when_unexpected_argument_is_given(
    test_client,
):
    test_arg = "bad_arg"
    response = test_client.get(f"/update_settings?{test_arg}=True")
    assert response.status_code == 400
    assert response.status.endswith(f"Invalid argument given: {test_arg}") is True


@pytest.mark.parametrize(
    "test_uuid,test_description",
    [
        (
            "",
            "returns error_message when uuid is empty",
        ),
        (
            "11e140e2b-397a-427b-81f3-4f889c5181a9",
            "returns error_message when uuid is invalid",
        ),
    ],
)
def test_update_settings__returns_error_message_for_invalid_user_account_uuid(
    test_uuid, test_description, test_client
):
    response = test_client.get(f"/update_settings?user_account_uuid={test_uuid}")
    assert response.status_code == 400
    assert (
        response.status.endswith(
            f"{repr(ImproperlyFormattedUserAccountUUIDError(test_uuid))}"
        )
        is True
    )


def test_route_error_message_is_logged(mocker, test_client):
    expected_error_msg = "400 Request missing 'barcode' parameter"

    mocked_logger = mocker.spy(server.logger, "info")

    response = test_client.get("/start_recording")
    assert response.status == expected_error_msg

    assert expected_error_msg in mocked_logger.call_args[0][0]


def test_start_recording__returns_no_error_message_with_multiple_hardware_test_recordings(
    client_and_server_thread_and_shared_values,
    generic_start_recording_info_in_shared_dict,
):
    test_client, _, _ = client_and_server_thread_and_shared_values

    response = test_client.get(
        "/start_recording?barcode=MA200440001&is_hardware_test_recording=True"
    )
    assert response.status_code == 200
    response = test_client.get(
        "/start_recording?barcode=MA200440001&is_hardware_test_recording=True"
    )
    assert response.status_code == 200


def test_start_recording__returns_error_code_and_message_if_user_account_id_not_set(
    test_client, test_monitor, generic_start_recording_info_in_shared_dict
):
    generic_start_recording_info_in_shared_dict["config_settings"][
        "User Account ID"
    ] = ""
    response = test_client.get("/start_recording?barcode=MA200440001")
    assert response.status_code == 406
    assert response.status.endswith("User Account ID has not yet been set") is True


def test_start_recording__returns_error_code_and_message_if_customer_account_id_not_set(
    test_client, test_monitor, generic_start_recording_info_in_shared_dict
):
    generic_start_recording_info_in_shared_dict["config_settings"][
        "Customer Account ID"
    ] = ""
    response = test_client.get("/start_recording?barcode=MA200440001")
    assert response.status_code == 406
    assert response.status.endswith("Customer Account ID has not yet been set") is True


def test_start_recording__returns_error_code_and_message_if_barcode_is_not_given(
    test_client,
):
    response = test_client.get("/start_recording")
    assert response.status_code == 400
    assert response.status.endswith("Request missing 'barcode' parameter") is True


@pytest.mark.parametrize(
    ",".join(("test_barcode", "expected_error_message", "test_description")),
    [
        (
            "MA1234567890",
            "Barcode exceeds max length",
            "returns error message when barcode is too long",
        ),
        (
            "MA1234567",
            "Barcode does not reach min length",
            "returns error message when barcode is too short",
        ),
        (
            "MA21044-001",
            "Barcode contains invalid character: '-'",
            "returns error message when '-' is present",
        ),
        (
            "M$210440001",
            "Barcode contains invalid character: '$'",
            "returns error message when '$' is present",
        ),
        (
            "MZ20044001",
            "Barcode contains invalid header: 'MZ'",
            "returns error message when barcode header is invalid",
        ),
        (
            "MA210440001",
            "Barcode contains invalid year: '21'",
            "returns error message when year is invalid",
        ),
        (
            "MA200000001",
            "Barcode contains invalid Julian date: '000'",
            "returns error message when julian date is too low",
        ),
        (
            "MA20367001",
            "Barcode contains invalid Julian date: '367'",
            "returns error message when julian date is too big",
        ),
        (
            "MA2004400BA",
            "Barcode contains nom-numeric string after Julian date: '00BA'",
            "returns error message when barcode ending is non-numeric",
        ),
        (
            "MA2004400A",
            "Barcode contains nom-numeric string after Julian date: '00A'",
            "returns error message when barcode ending is non-numeric",
        ),
    ],
)
def test_start_recording__returns_error_code_and_message_if_barcode_is_invalid(
    test_client, test_barcode, expected_error_message, test_description
):
    response = test_client.get(f"/start_recording?barcode={test_barcode}")
    assert response.status_code == 400
    assert response.status.endswith(expected_error_message) is True


def test_route_with_no_url_rule__returns_error_message__and_logs_reponse_to_request(
    test_client, mocker
):
    mocked_logger = mocker.spy(server.logger, "info")

    response = test_client.get("/fake_route")
    assert response.status_code == 404
    assert response.status.endswith("Route not implemented") is True

    mocked_logger.assert_called_once_with(
        f"Response to HTTP Request in next log entry: {response.status}"
    )
