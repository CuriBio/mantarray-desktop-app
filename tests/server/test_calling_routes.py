# -*- coding: utf-8 -*-
import json

from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import ImproperlyFormattedCustomerAccountUUIDError
from mantarray_desktop_app import ImproperlyFormattedUserAccountUUIDError
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import RecordingFolderDoesNotExistError
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import server
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
from mantarray_desktop_app import STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS
from mantarray_desktop_app import STIM_MAX_PULSE_DURATION_MICROSECONDS
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
import pytest

from ..fixtures import fixture_generic_queue_container
from ..fixtures_server import fixture_client_and_server_manager_and_shared_values
from ..fixtures_server import fixture_server_manager
from ..fixtures_server import fixture_test_client
from ..fixtures_server import put_generic_beta_1_start_recording_info_in_dict

__fixtures__ = [
    fixture_client_and_server_manager_and_shared_values,
    fixture_server_manager,
    fixture_test_client,
    fixture_generic_queue_container,
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
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = expected_status
    shared_values_dict["in_simulation_mode"] = expected_in_simulation

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["ui_status_code"] == str(SYSTEM_STATUS_UUIDS[expected_status])
    assert response_json["in_simulation_mode"] == expected_in_simulation


def test_system_status__returns_in_simulator_mode_False_as_default_value(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
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
def test_system_status__returns_correct_serial_number_and_nickname_in_dict_with_empty_string_as_default(
    expected_serial,
    expected_nickname,
    test_description,
    client_and_server_manager_and_shared_values,
):
    board_idx = 0
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = SERVER_READY_STATE

    if expected_serial:
        shared_values_dict["mantarray_serial_number"] = {board_idx: expected_serial}
    if expected_nickname:
        shared_values_dict["mantarray_nickname"] = {board_idx: expected_nickname}

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    if expected_serial:
        assert response_json["mantarray_serial_number"][str(board_idx)] == expected_serial
    else:
        assert response_json["mantarray_serial_number"] == ""
    if expected_nickname:
        assert response_json["mantarray_nickname"][str(board_idx)] == expected_nickname
    else:
        assert response_json["mantarray_nickname"] == ""


@pytest.mark.parametrize(
    ",".join(("test_nickname", "test_description")),
    [
        ("123456789012345678901234", "returns error with no unicode characters"),
        ("1234567890123456789012à", "returns error with unicode character"),
    ],
)
def test_set_mantarray_nickname__returns_error_code_and_message_if_nickname_is_too_many_bytes__in_beta_1_mode(
    test_nickname,
    test_description,
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values

    shared_values_dict["beta_2_mode"] = False
    shared_values_dict["mantarray_nickname"] = dict()

    response = test_client.get(f"/set_mantarray_nickname?nickname={test_nickname}")
    assert response.status_code == 400
    assert response.status.endswith("Nickname exceeds 23 bytes") is True


@pytest.mark.parametrize(
    ",".join(("test_nickname", "test_description")),
    [
        (
            "123456789012345678901234567890123",
            "returns error with no unicode characters",
        ),
        ("1234567890123456789012345678901à", "returns error with unicode character"),
    ],
)
def test_set_mantarray_nickname__returns_error_code_and_message_if_nickname_is_too_many_bytes__in_beta_2_mode(
    test_nickname,
    test_description,
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values

    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["mantarray_nickname"] = dict()

    response = test_client.get(f"/set_mantarray_nickname?nickname={test_nickname}")
    assert response.status_code == 400
    assert response.status.endswith("Nickname exceeds 32 bytes") is True


def test_send_single_start_calibration_command__returns_200(
    client_and_server_manager_and_shared_values,
):
    test_client, _, _ = client_and_server_manager_and_shared_values
    response = test_client.get("/start_calibration")
    assert response.status_code == 200


def test_dev_begin_hardware_script__returns_correct_response(test_client):
    response = test_client.get("/development/begin_hardware_script?script_type=ENUM&version=integer")
    assert response.status_code == 200


def test_dev_end_hardware_script__returns_correct_response(test_client):
    response = test_client.get("/development/end_hardware_script")
    assert response.status_code == 200


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
    client_and_server_manager_and_shared_values,
    mocker,
):
    test_client, _, _ = client_and_server_manager_and_shared_values

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={test_serial_number}"
    )
    assert response.status_code == 400
    assert response.status.endswith(expected_error_message) is True


def test_start_managed_acquisition__returns_error_code_and_message_if_mantarray_serial_number_is_empty(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    board_idx = 0
    shared_values_dict["mantarray_serial_number"] = {board_idx: ""}

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 406
    assert response.status.endswith("Mantarray has not been assigned a Serial Number") is True


@pytest.mark.parametrize(
    "test_uuid,test_description",
    [
        (
            "",
            "returns error_message when uuid is empty",
        ),
        (
            "e140e2b-397a-427b-81f3-4f889c5181a9",
            "returns error_message when uuid is missing one char",
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
    assert response.status.endswith(f"{repr(ImproperlyFormattedCustomerAccountUUIDError(test_uuid))}") is True


def test_update_settings__returns_error_message_when_recording_directory_does_not_exist(
    test_client,
):
    test_dir = "fake_dir/fake_sub_dir"
    response = test_client.get(f"/update_settings?recording_directory={test_dir}")
    assert response.status_code == 400
    assert response.status.endswith(f"{repr(RecordingFolderDoesNotExistError(test_dir))}") is True


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
            "returns error_message when uuid is missing one char",
        ),
    ],
)
def test_update_settings__returns_error_message_for_invalid_user_account_uuid(
    test_uuid, test_description, test_client
):
    response = test_client.get(f"/update_settings?user_account_uuid={test_uuid}")
    assert response.status_code == 400
    assert response.status.endswith(f"{repr(ImproperlyFormattedUserAccountUUIDError(test_uuid))}") is True


def test_route_error_message_is_logged(mocker, test_client):
    expected_error_msg = "400 Request missing 'barcode' parameter"

    mocked_logger = mocker.spy(server.logger, "info")

    response = test_client.get("/start_recording")
    assert response.status == expected_error_msg

    assert expected_error_msg in mocked_logger.call_args[0][0]


def test_start_recording__returns_no_error_message_with_multiple_hardware_test_recordings(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)

    response = test_client.get("/start_recording?barcode=MA200440001&is_hardware_test_recording=True")
    assert response.status_code == 200
    response = test_client.get("/start_recording?barcode=MA200440001&is_hardware_test_recording=True")
    assert response.status_code == 200


def test_start_recording__returns_error_code_and_message_if_user_account_id_not_set(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)
    shared_values_dict["config_settings"]["User Account ID"] = ""

    response = test_client.get("/start_recording?barcode=MA200440001")
    assert response.status_code == 406
    assert response.status.endswith("User Account ID has not yet been set") is True


def test_start_recording__returns_error_code_and_message_if_customer_account_id_not_set(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)
    shared_values_dict["config_settings"]["Customer Account ID"] = ""

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
            "returns error message when pre-ML barcode is too long",
        ),
        (
            "",
            "Barcode does not reach min length",
            "returns error message when barcode is empty",
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
            "M120044001",
            "Barcode contains invalid header: 'M1'",
            "returns error message when barcode header is invalid",
        ),
        (
            "MC20044001",
            "Barcode contains invalid header: 'MC'",
            "returns error message when barcode header is invalid",
        ),
        (
            "MD20044001",
            "Barcode contains invalid header: 'MD'",
            "returns error message when barcode header is invalid",
        ),
        (
            "MAS10440001",
            "Barcode contains invalid year: 'S1'",
            "returns error message when year is contains non-numeric character",
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
            "MA203P2001",
            "Barcode contains invalid Julian date: '3P2'",
            "returns error message when julian date contains non-numeric value",
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
        # new barcode format
        (
            "ML12345678901",
            "Barcode is incorrect length",
            "returns error message when ML barcode is too long",
        ),
        (
            "ML123456789",
            "Barcode is incorrect length",
            "returns error message when ML barcode is too short",
        ),
        (
            "ML2021$72144",
            "Barcode contains invalid character: '$'",
            "returns error message when '$' is present in ML barcode",
        ),
        (
            "ML2020172144",
            "Barcode contains invalid year: '2020'",
            "returns error message when ML barcode contains invalid year",
        ),
        (
            "ML2021000144",
            "Barcode contains invalid Julian date: '000'",
            "returns error message when ML barcode contains Julian date: '000'",
        ),
        (
            "ML2021367144",
            "Barcode contains invalid Julian date: '367'",
            "returns error message when ML barcode contains Julian date: '367'",
        ),
        (
            "ML2021172002",
            "Barcode contains invalid kit ID: '002'",
            "returns error message when ML barcode contains kit ID: '002'",
        ),
        (
            "ML2021172003",
            "Barcode contains invalid kit ID: '003'",
            "returns error message when ML barcode contains kit ID: '003'",
        ),
    ],
)
def test_start_recording__returns_error_code_and_message_if_barcode_is_invalid(
    test_client,
    test_barcode,
    expected_error_message,
    test_description,
):
    response = test_client.get(f"/start_recording?barcode={test_barcode}")
    assert response.status_code == 400
    assert response.status.endswith(expected_error_message) is True


@pytest.mark.parametrize(
    "test_barcode,test_description",
    [
        (
            "MA210440001",
            "allows year to be 21",
        ),
        (
            "MA190440001",
            "allows year to be 19",
        ),
    ],
)
def test_start_recording__allows_years_other_than_20_in_barcode(
    test_barcode, test_description, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)

    response = test_client.get(f"/start_recording?barcode={test_barcode}")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "test_barcode,test_description",
    [
        (
            "MA200440001",
            "allows header 'MA'",
        ),
        (
            "ME200440001",
            "allows header 'ME'",
        ),
        (
            "MB200440001",
            "allows header 'MB'",
        ),
        (
            "ML2021172144",
            "allows header 'ML'",
        ),
    ],
)
def test_start_recording__allows_correct_barcode_headers(
    test_barcode, test_description, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)
    response = test_client.get(f"/start_recording?barcode={test_barcode}")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "test_barcode,test_description",
    [
        (
            "ML2021172004",
            "allows kit ID '004'",
        ),
        (
            "ML2021172001",
            "allows kit ID '001'",
        ),
    ],
)
def test_start_recording__allows_correct_kit_ids_in_ML_barcodes(
    test_barcode, test_description, test_client, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_1_start_recording_info_in_dict(shared_values_dict)
    response = test_client.get(f"/start_recording?barcode={test_barcode}")
    assert response.status_code == 200


def test_route_with_no_url_rule__returns_error_message__and_logs_reponse_to_request(test_client, mocker):
    mocked_logger = mocker.spy(server.logger, "info")

    response = test_client.get("/fake_route")
    assert response.status_code == 404
    assert response.status.endswith("Route not implemented") is True

    mocked_logger.assert_called_once_with(f"Response to HTTP Request in next log entry: {response.status}")


def test_insert_xem_command_into_queue_routes__return_error_code_and_message_if_called_in_beta_2_mode(
    client_and_server_manager_and_shared_values, mocker
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values

    spied_queue_set_device_id = mocker.spy(server, "queue_set_device_id")

    shared_values_dict["beta_2_mode"] = True

    response = test_client.get("/insert_xem_command_into_queue/set_device_id")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 2 mode") is True

    spied_queue_set_device_id.assert_not_called()


def test_boot_up__return_error_code_and_message_if_called_in_beta_2_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    response = test_client.get("/boot_up")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 2 mode") is True


def test_set_magnetometer_config__returns_error_code_if_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False
    shared_values_dict["system_status"] = CALIBRATED_STATE

    response = test_client.post("/set_magnetometer_config")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode") is True


def test_set_magnetometer_config__returns_error_code_if_called_with_config_dict_missing_module_id(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    bad_config = create_magnetometer_config_dict(test_num_wells - 1)
    test_config_dict = {
        "magnetometer_config": bad_config,
        "sampling_period": 10000,
    }

    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 400
    assert response.status.endswith(f"Configuration dictionary is missing module ID {test_num_wells}") is True


def test_set_magnetometer_config__returns_error_code_if_called_with_config_dict_missing_channel_id(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    bad_config = create_magnetometer_config_dict(test_num_wells)
    missing_channel_id = 0
    del bad_config[test_num_wells][missing_channel_id]
    test_config_dict = {
        "magnetometer_config": bad_config,
        "sampling_period": 10000,
    }

    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 400
    assert (
        response.status.endswith(
            f"Configuration dictionary is missing channel ID {missing_channel_id} for module ID {test_num_wells}"
        )
        is True
    )


def test_set_magnetometer_config__returns_error_code_if_called_with_config_dict_that_has_invalid_module_id(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    bad_config = create_magnetometer_config_dict(test_num_wells + 1)
    test_config_dict = {
        "magnetometer_config": bad_config,
        "sampling_period": 10000,
    }
    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 400
    assert (
        response.status.endswith(f"Configuration dictionary has invalid module ID {test_num_wells + 1}")
        is True
    )

    bad_key = 0
    bad_config[bad_key] = True
    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 400
    assert response.status.endswith(f"Configuration dictionary has invalid module ID {bad_key}") is True


def test_set_magnetometer_config__returns_error_code_if_called_with_config_dict_that_has_invalid_channel_id(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    bad_config = create_magnetometer_config_dict(test_num_wells)
    bad_config[test_num_wells][SERIAL_COMM_NUM_DATA_CHANNELS] = False
    test_config_dict = {
        "magnetometer_config": bad_config,
        "sampling_period": 20000,
    }
    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 400
    assert (
        response.status.endswith(
            f"Configuration dictionary has invalid channel ID {SERIAL_COMM_NUM_DATA_CHANNELS} for module ID {test_num_wells}"
        )
        is True
    )

    bad_key = -1
    bad_config[test_num_wells][bad_key] = True
    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 400
    assert (
        response.status.endswith(
            f"Configuration dictionary has invalid channel ID {bad_key} for module ID {test_num_wells}"
        )
        is True
    )


def test_set_magnetometer_config__returns_error_code_if_called_sampling_period_is_not_given_or_is_invalid(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    config_dict = create_magnetometer_config_dict(test_num_wells)
    test_config_dict = {
        "magnetometer_config": config_dict,
    }
    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 400
    assert response.status.endswith("Sampling period not specified") is True

    bad_sampling_period = 1
    test_config_dict["sampling_period"] = bad_sampling_period
    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 400
    assert response.status.endswith(f"Invalid sampling period {bad_sampling_period}") is True


@pytest.mark.parametrize(
    "test_system_status,test_description",
    [
        (BUFFERING_STATE, "returns error code in buffering state"),
        (LIVE_VIEW_ACTIVE_STATE, "returns error code in live view active state"),
        (RECORDING_STATE, "returns error code in recording state"),
    ],
)
def test_set_magnetometer_config__returns_error_code_if_called_while_data_is_streaming(
    test_system_status,
    test_description,
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = test_system_status

    test_num_wells = 24
    test_config_dict = {
        "magnetometer_config": create_magnetometer_config_dict(test_num_wells),
        "sampling_period": 100000,
    }
    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 403
    assert (
        response.status.endswith("Magnetometer Configuration cannot be changed while data is streaming")
        is True
    )


@pytest.mark.parametrize(
    "test_system_status,test_description",
    [
        (SERVER_INITIALIZING_STATE, "returns error code in server initializing state"),
        (SERVER_READY_STATE, "returns error code in server ready state"),
        (INSTRUMENT_INITIALIZING_STATE, "returns error code in instrument initializing state"),
    ],
)
def test_set_magnetometer_config__returns_error_code_if_called_before_instrument_finishes_initialization(
    test_system_status,
    test_description,
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = test_system_status

    test_num_wells = 24
    test_config_dict = {
        "magnetometer_config": create_magnetometer_config_dict(test_num_wells),
        "sampling_period": 100000,
    }
    response = test_client.post("/set_magnetometer_config", json=json.dumps(test_config_dict))
    assert response.status_code == 403
    assert (
        response.status.endswith(
            "Magnetometer Configuration cannot be set until instrument finishes initializing"
        )
        is True
    )


def test_start_managed_acquisition__returns_error_code_if_called_in_beta_2_mode_before_magnetometer_configuration_is_set(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["mantarray_serial_number"] = MantarrayMcSimulator.default_mantarray_serial_number
    shared_values_dict["system_status"] = CALIBRATED_STATE

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 406
    assert response.status.endswith("Magnetometer Configuration has not been set yet") is True


def test_set_stim_status__returns_error_code_if_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode") is True


def test_set_stim_status__returns_error_code_and_message_if_running_arg_is_not_given(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    response = test_client.post("/set_stim_status")
    assert response.status_code == 400
    assert response.status.endswith("Request missing 'running' parameter") is True


def test_set_stim_status__returns_error_code_and_message_if_set_to_true_before_a_protocol_is_set(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = False
    shared_values_dict["stimulation_protocols"] = None

    response = test_client.post("/set_stim_status?running=True")
    assert response.status_code == 406
    assert response.status.endswith("Protocol has not been set") is True


def test_set_stim_status__returns_code_and_message_if_new_status_is_the_same_as_the_current_status(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    shared_values_dict["stimulation_running"] = False
    response = test_client.post("/set_stim_status?running=false")
    assert response.status_code == 304
    assert response.status.endswith("Status not updated") is True

    shared_values_dict["stimulation_running"] = True
    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 304
    assert response.status.endswith("Status not updated") is True


def test_set_protocol__returns_error_code_if_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    response = test_client.post("/set_protocol")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode") is True


def test_set_protocol__returns_error_code_if_called_while_stimulation_is_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = True

    response = test_client.post("/set_protocol")
    assert response.status_code == 403
    assert response.status.endswith("Cannot change protocol while stimulation is running") is True


def test_set_protocol__returns_error_code_if_protocol_list_does_not_contain_enough_items(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = False

    response = test_client.post("/set_protocol", json=json.dumps({"protocols": [None] * 23}))
    assert response.status_code == 400
    assert response.status.endswith("Not enough protocols for all 24 wells") is True


@pytest.mark.parametrize(
    "test_stimulation_type,test_description",
    [
        (None, "return error code with None"),
        (1, "return error code with int"),
        ("A", "return error code with invalid string"),
    ],
)
def test_set_protocol__returns_error_code_with_invalid_stimulation_type(
    client_and_server_manager_and_shared_values, test_stimulation_type, test_description
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = False

    test_protocol_dict = {"protocols": [{"stimulation_type": test_stimulation_type}] * 24}
    response = test_client.post("/set_protocol", json=json.dumps(test_protocol_dict))
    assert response.status_code == 400
    assert response.status.endswith(f"Invalid stimulation type: {test_stimulation_type}") is True


@pytest.mark.parametrize(
    "test_well_number,test_description",
    [
        ("Z1", "return error code with well Z1"),
        ("A99", "return error code with well A99"),
    ],
)
def test_set_protocol__returns_error_code_with_invalid_well_number(
    client_and_server_manager_and_shared_values, test_well_number, test_description
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = False

    test_protocol_dict = {"protocols": [{"stimulation_type": "C", "well_number": test_well_number}] * 24}
    response = test_client.post("/set_protocol", json=json.dumps(test_protocol_dict))
    assert response.status_code == 400
    assert response.status.endswith(f"Invalid well: {test_well_number}") is True


@pytest.mark.parametrize(
    "test_pulse_item,test_value,test_stim_type,test_description",
    [
        (
            "phase_one_charge",
            STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS + 1,
            "C",
            f"Invalid phase one charge: {STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS + 1} µA",
        ),
        (
            "phase_one_charge",
            -STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS - 1,
            "C",
            f"Invalid phase one charge: {-STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS - 1} µA",
        ),
        (
            "phase_two_charge",
            STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS + 1,
            "C",
            f"Invalid phase two charge: {STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS + 1} µA",
        ),
        (
            "phase_two_charge",
            -STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS - 1,
            "C",
            f"Invalid phase two charge: {-STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS - 1} µA",
        ),
        (
            "phase_one_charge",
            STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS + 1,
            "V",
            f"Invalid phase one charge: {STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS + 1} mV",
        ),
        (
            "phase_one_charge",
            -STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS - 1,
            "V",
            f"Invalid phase one charge: {-STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS - 1} mV",
        ),
        (
            "phase_two_charge",
            STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS + 1,
            "V",
            f"Invalid phase two charge: {STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS + 1} mV",
        ),
        (
            "phase_two_charge",
            -STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS - 1,
            "V",
            f"Invalid phase two charge: {-STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS - 1} mV",
        ),
        ("phase_one_duration", 0, "C", "Invalid phase one duration: 0"),
        ("phase_one_duration", -1, "C", "Invalid phase one duration: -1"),
        ("phase_two_duration", -1, "C", "Invalid phase two duration: -1"),
        ("interpulse_interval", -1, "C", "Invalid interpulse interval: -1"),
        ("repeat_delay_interval", -1, "C", "Invalid repeat delay interval: -1"),
        (
            "total_active_duration",
            STIM_MAX_PULSE_DURATION_MICROSECONDS - 1,
            "C",
            "Total active duration less than the duration of the pulse",
        ),
    ],
)
def test_set_protocol__returns_error_code_with_single_invalid_pulse_value(
    client_and_server_manager_and_shared_values,
    mocker,
    test_pulse_item,
    test_value,
    test_stim_type,
    test_description,
):
    mocker.patch.object(server, "queue_command_to_main", autospec=True)

    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = False

    test_base_charge = (
        STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS if test_stim_type == "V" else STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
    )
    # create an arbitrary protocol to which an invalid value can easily be added
    test_protocol_dict = {
        "protocols": [
            {
                "stimulation_type": test_stim_type,
                "well_number": "A1",
                "total_protocol_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                "pulses": [
                    {
                        "phase_one_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS // 4,
                        "phase_one_charge": test_base_charge,
                        "interpulse_interval": STIM_MAX_PULSE_DURATION_MICROSECONDS // 2,
                        "phase_two_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS // 4,
                        "phase_two_charge": -test_base_charge,
                        "repeat_delay_interval": STIM_MAX_PULSE_DURATION_MICROSECONDS // 4,
                        "total_active_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                    }
                ],
            }
        ]
        * 24
    }
    # add bad value
    test_protocol_dict["protocols"][0]["pulses"][0][test_pulse_item] = test_value

    response = test_client.post("/set_protocol", json=json.dumps(test_protocol_dict))
    assert f"400 {test_description}" in response.status


@pytest.mark.parametrize(
    "test_protocol_dur,test_description",
    [
        (-2, "returns error code with -2"),
        (0, "returns error code with 0"),
        (STIM_MAX_PULSE_DURATION_MICROSECONDS * 2 - 1, "returns error code when 1 µs too short"),
    ],
)
def test_set_protocol__returns_error_code_with_invalid_total_protocol_duration(
    client_and_server_manager_and_shared_values, test_protocol_dur, test_description
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = False

    test_protocol_dict = {
        "protocols": [
            {
                "stimulation_type": "V",
                "well_number": "A1",
                "total_protocol_duration": test_protocol_dur,
                "pulses": [
                    {
                        "phase_one_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                        "phase_one_charge": 0,
                        "interpulse_interval": 0,
                        "phase_two_duration": 0,
                        "phase_two_charge": 0,
                        "repeat_delay_interval": 0,
                        "total_active_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                    }
                ]
                * 2,
            }
        ]
        * 24
    }
    response = test_client.post("/set_protocol", json=json.dumps(test_protocol_dict))
    assert "400 Total protocol duration less than duration of all pulses" in response.status


def test_set_protocol__returns_error_code_when_pulse_duration_is_too_long(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = False

    test_protocol_dict = {
        "protocols": [
            {
                "stimulation_type": "V",
                "well_number": "A1",
                "total_protocol_duration": -1,
                "pulses": [
                    {
                        "phase_one_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS // 2,
                        "phase_one_charge": 0,
                        "interpulse_interval": 1,
                        "phase_two_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS // 2,
                        "phase_two_charge": 0,
                        "repeat_delay_interval": STIM_MAX_PULSE_DURATION_MICROSECONDS * 10,
                        "total_active_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS * 20,
                    }
                ],
            }
        ]
        * 24
    }
    response = test_client.post("/set_protocol", json=json.dumps(test_protocol_dict))
    assert "400 Pulse duration too long" in response.status
