# -*- coding: utf-8 -*-
import json
from random import randint
import tempfile
import urllib

from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import RecordingFolderDoesNotExistError
from mantarray_desktop_app import server
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
from mantarray_desktop_app import STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS
from mantarray_desktop_app import STIM_MAX_PULSE_DURATION_MICROSECONDS
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import SERIAL_COMM_NICKNAME_BYTES_LENGTH
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
from mantarray_desktop_app.exceptions import LoginFailedError
import pytest

from ..fixtures import fixture_generic_queue_container
from ..fixtures_mc_simulator import create_random_stim_info
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_server import fixture_client_and_server_manager_and_shared_values
from ..fixtures_server import fixture_server_manager
from ..fixtures_server import fixture_test_client
from ..fixtures_server import put_generic_beta_2_start_recording_info_in_dict

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
    shared_values_dict["stimulation_running"] = [False] * 24

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["ui_status_code"] == str(SYSTEM_STATUS_UUIDS[expected_status])
    assert response_json["in_simulation_mode"] == expected_in_simulation


@pytest.mark.parametrize(
    "test_stimulating_value,test_description",
    [
        (True, "returns True when stimulating"),
        (False, "returns False when not stimulating"),
    ],
)
def test_system_status__beta_2_mode__returns_correct_stimulating_value(
    test_stimulating_value, test_description, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["stimulation_running"][0] = test_stimulating_value

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["is_stimulating"] is test_stimulating_value


def test_system_status__beta_1_mode__returns_False_for_stimulating_value(
    client_and_server_manager_and_shared_values,
):
    test_client, *_ = client_and_server_manager_and_shared_values

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["is_stimulating"] is False


def test_system_status__returns_in_simulator_mode_False_as_default_value(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    expected_status = CALIBRATION_NEEDED_STATE
    shared_values_dict["system_status"] = expected_status
    shared_values_dict["stimulation_running"] = [False] * 24

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
    shared_values_dict["stimulation_running"] = [False] * 24

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
    "expected_software_version,actual_software_version,test_description",
    [
        ("1.1.1", "1.1.1", "returns correct response when expected == actual"),
        ("1.1.2", "1.1.1", "returns correct response when expected != actual"),
        (None, "1.1.1", "returns correct response when expected is not given"),
    ],
)
def test_system_status_handles_expected_software_version_correctly(
    expected_software_version,
    actual_software_version,
    test_description,
    client_and_server_manager_and_shared_values,
    mocker,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24
    if expected_software_version is not None:
        shared_values_dict["expected_software_version"] = expected_software_version

    mocker.patch.object(
        server, "get_current_software_version", autospec=True, return_value=actual_software_version
    )
    expected_status_code = (
        200
        if expected_software_version is None or expected_software_version == actual_software_version
        else 520
    )

    response = test_client.get("/system_status")
    assert response.status_code == expected_status_code
    if expected_status_code == 520:
        assert response.status.endswith("Versions of Electron and Flask EXEs do not match") is True


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
    assert response.status.endswith(f"Nickname exceeds {SERIAL_COMM_NICKNAME_BYTES_LENGTH} bytes") is True


@pytest.mark.parametrize(
    "test_system_status",
    [
        SERVER_INITIALIZING_STATE,
        SERVER_READY_STATE,
        INSTRUMENT_INITIALIZING_STATE,
        CALIBRATION_NEEDED_STATE,
        CALIBRATING_STATE,
        CALIBRATED_STATE,
        BUFFERING_STATE,
        LIVE_VIEW_ACTIVE_STATE,
        RECORDING_STATE,
    ],
)
def test_send_single_start_calibration_command__returns_correct_response(
    test_system_status,
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = test_system_status

    expected_status_code = 200 if test_system_status in (CALIBRATION_NEEDED_STATE, CALIBRATED_STATE) else 403

    response = test_client.get("/start_calibration")
    assert response.status_code == expected_status_code
    if expected_status_code == 403:
        assert (
            response.status.endswith(
                "Route cannot be called unless in calibration_needed or calibrated state"
            )
            is True
        )


def test_start_calibration__returns_error_code_and_message_if_called_in_beta_2_mode_while_stimulating(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["beta_2_mode"] = True

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_running"][0] = True  # arbitrary well
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells

    response = test_client.get("/start_calibration")
    assert response.status_code == 403
    assert response.status.endswith("Cannot calibrate while stimulation is running") is True


def test_start_calibration__returns_error_code_and_message_if_called_in_beta_2_mode_while_stimulator_checks_are_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["beta_2_mode"] = True

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells
    # set random circuit status to calculating
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.CALCULATING.name.lower()

    response = test_client.get("/start_calibration")
    assert response.status_code == 403
    assert response.status.endswith("Cannot calibrate while stimulator checks are running") is True


def test_start_stim_checks__returns_error_code_and_message_if_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    response = test_client.post("/start_stim_checks")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode") is True


@pytest.mark.parametrize(
    "test_system_status",
    [
        SERVER_INITIALIZING_STATE,
        SERVER_READY_STATE,
        INSTRUMENT_INITIALIZING_STATE,
        CALIBRATION_NEEDED_STATE,
        CALIBRATING_STATE,
        CALIBRATED_STATE,
        BUFFERING_STATE,
        LIVE_VIEW_ACTIVE_STATE,
        RECORDING_STATE,
    ],
)
def test_start_stim_checks__returns_correct_response(
    test_system_status,
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = test_system_status

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells

    expected_status_code = 200 if test_system_status in (CALIBRATED_STATE) else 403

    response = test_client.post("/start_stim_checks")
    assert response.status_code == expected_status_code
    if expected_status_code == 403:
        assert response.status.endswith("Route cannot be called unless in calibrated state") is True


def test_start_stim_checks__returns_error_code_and_message_if_called_while_stimulating(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["beta_2_mode"] = True

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_running"][0] = True  # arbitrary well
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells

    response = test_client.post("/start_stim_checks")
    assert response.status_code == 403
    assert response.status.endswith("Cannot perform stimulator checks while stimulation is running") is True


def test_set_start_stim_checks__returns_code_and_message_if_checks_are_already_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells
    # set random circuit status to calculating
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.CALCULATING.name.lower()

    response = test_client.post("/start_stim_checks")
    assert response.status_code == 304
    assert response.status.endswith("Stimulator checks already running") is True


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


def test_start_managed_acquisition__returns_error_code_and_message_called_while_stimulator_checks_are_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    board_idx = 0
    shared_values_dict["mantarray_serial_number"] = {
        board_idx: MantarrayMcSimulator.default_mantarray_serial_number
    }

    test_num_wells = 24
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells
    # set random circuit status to calculating
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.CALCULATING.name.lower()

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 403
    assert (
        response.status.endswith("Cannot start managed acquisition while stimulator checks are running")
        is True
    )


def test_get_recordings__returns_error_code_and_message_when_recording_directory_is_not_found(
    client_and_server_manager_and_shared_values,
):
    test_client, _, _ = client_and_server_manager_and_shared_values

    response = test_client.get("/get_recordings")
    assert response.status_code == 400
    assert response.status.endswith("No root recording directory was found") is True


def test_get_recordings__returns_200_with_list_of_directories(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    with tempfile.TemporaryDirectory() as tmp_recording_dir:
        shared_values_dict["config_settings"]["recording_directory"] = tmp_recording_dir

        response = test_client.get("/get_recordings")
        assert response.status_code == 200
        assert response.get_json() == {"recordings_list": [], "root_recording_path": tmp_recording_dir}


def test_start_data_analysis__returns_error_code_and_message_when_recording_directory_is_not_found(
    client_and_server_manager_and_shared_values,
):
    test_client, _, _ = client_and_server_manager_and_shared_values

    response = test_client.post(
        "/start_data_analysis", json={"selected_recordings": ["recording_1", "recording_2"]}
    )
    assert response.status_code == 400
    assert response.status.endswith("Root directories were not found") is True


def test_start_data_analysis__returns_empty_204_response_if_successful(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["config_settings"]["recording_directory"] = "/"

    response = test_client.post(
        "/start_data_analysis", json={"selected_recordings": ["recording_1", "recording_2"]}
    )
    assert response.status_code == 204


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


def test_update_settings__returns_correct_error_code_when_user_auth_fails(test_client, mocker):
    test_error = LoginFailedError(401)

    # mock so test doesn't hit cloud API
    mocked_validate = mocker.patch.object(
        server, "validate_user_credentials", autospec=True, side_effect=test_error
    )

    test_user_creds = {
        "customer_id": "cid",
        "user_name": "user",
        "user_password": "pw",
    }

    response = test_client.get(f"/update_settings?{urllib.parse.urlencode(test_user_creds)}")
    assert response.status_code == 401
    assert repr(test_error) in response.status

    mocked_validate.assert_called_once()
    assert dict(mocked_validate.call_args[0][0]) == test_user_creds


def test_route_error_message_is_logged(mocker, test_client):
    mocked_logger = mocker.spy(server.logger, "info")

    bad_arg = "a"
    expected_error_msg = f"400 Invalid argument given: {bad_arg}"

    response = test_client.get(f"/update_settings?{bad_arg}=")
    assert response.status == expected_error_msg

    assert expected_error_msg in mocked_logger.call_args[0][0]


def test_start_recording__returns_no_error_message_with_multiple_hardware_test_recordings(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)

    params = {
        "plate_barcode": MantarrayMcSimulator.default_plate_barcode,
        "stim_barcode": MantarrayMcSimulator.default_stim_barcode,
        "is_hardware_test_recording": True,
    }
    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(params)}")
    assert response.status_code == 200
    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(params)}")
    assert response.status_code == 200


def test_start_recording__returns_error_code_and_message_if_plate_barcode_is_not_given(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [True] * 24

    response = test_client.get("/start_recording")
    assert response.status_code == 400
    assert response.status.endswith("Request missing 'plate_barcode' parameter") is True


def test_start_recording__returns_error_code_and_message_if_stim_barcode_is_not_given_while_stim_is_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [True] * 24

    response = test_client.get(f"/start_recording?plate_barcode={MantarrayMcSimulator.default_plate_barcode}")
    assert response.status_code == 400
    assert response.status.endswith("Request missing 'stim_barcode' parameter") is True


@pytest.mark.parametrize("test_barcode_type", ["Stim", "Plate"])
@pytest.mark.parametrize(
    "test_barcode,expected_error_message",
    [
        ("M*12345678901", "barcode is incorrect length"),
        ("M*123456789", "barcode is incorrect length"),
        ("MA1234567890", "barcode contains invalid header: 'MA'"),
        ("MB1234567890", "barcode contains invalid header: 'MB'"),
        ("ME1234567890", "barcode contains invalid header: 'ME'"),
        ("M*2021$72144", "barcode contains invalid character: '$'"),
        ("M*20211721)4", "barcode contains invalid character: ')'"),
        ("M*2020172144", "barcode contains invalid year: '2020'"),
        ("M*2021000144", "barcode contains invalid Julian date: '000'"),
        ("M*2021367144", "barcode contains invalid Julian date: '367'"),
    ],
)
def test_start_recording__returns_error_code_and_message_if_barcode_is_invalid(
    test_barcode_type,
    test_barcode,
    expected_error_message,
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [True] * 24

    barcodes = {
        "plate_barcode": MantarrayMcSimulator.default_plate_barcode,
        "stim_barcode": MantarrayMcSimulator.default_stim_barcode,
    }
    barcode_type_letter = "S" if test_barcode_type == "Stim" else "L"
    barcodes[f"{test_barcode_type.lower()}_barcode"] = test_barcode.replace("*", barcode_type_letter)

    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(barcodes)}")
    assert response.status_code == 400
    assert response.status.endswith(f"{test_barcode_type} {expected_error_message}") is True


@pytest.mark.parametrize(
    "test_barcode,expected_error_message",
    [
        (MantarrayMcSimulator.default_stim_barcode, "Plate barcode contains invalid header: 'MS'"),
        (MantarrayMcSimulator.default_plate_barcode, "Stim barcode contains invalid header: 'ML'"),
    ],
)
def test_start_recording__returns_error_code_if_barcode_header_and_type_do_not_match(
    test_barcode, expected_error_message, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)
    shared_values_dict["stimulation_running"] = [True] * 24

    barcodes = {"plate_barcode": test_barcode, "stim_barcode": test_barcode}
    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(barcodes)}")
    assert response.status_code == 400
    assert response.status.endswith(expected_error_message) is True


def test_start_recording__allows_correct_barcode_headers__for_correct_barcode_type(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)
    shared_values_dict["stimulation_running"] = [True] * 24

    barcodes = {
        "plate_barcode": MantarrayMcSimulator.default_plate_barcode,
        "stim_barcode": MantarrayMcSimulator.default_stim_barcode,
    }
    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(barcodes)}")
    assert response.status_code == 200


def test_start_recording__returns_error_code_and_message_if_already_recording(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)
    shared_values_dict["system_status"] = RECORDING_STATE

    params = {
        "plate_barcode": MantarrayMcSimulator.default_plate_barcode,
        "stim_barcode": MantarrayMcSimulator.default_stim_barcode,
    }
    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(params)}")
    assert response.status_code == 304
    assert response.status.endswith("Already recording") is True


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


@pytest.mark.parametrize("test_status", [True, False])
def test_set_stim_status__returns_error_code_and_message_if_called_before_protocols_are_set(
    test_status, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["stimulation_info"] = None

    response = test_client.post(f"/set_stim_status?running={test_status}")
    assert response.status_code == 406
    assert response.status.endswith("Protocols have not been set") is True


@pytest.mark.parametrize(
    "test_system_status",
    set(SYSTEM_STATUS_UUIDS.keys()) - {CALIBRATED_STATE, BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE},
)
def test_set_stim_status__returns_error_code_and_message_if_called_with_true_during_invalid_state(
    test_system_status,
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = test_system_status
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["stimulation_info"] = create_random_stim_info()

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert response.status.endswith(f"Cannot start stimulation while {test_system_status}") is True


def test_set_stim_status__returns_error_code_and_message_if_called_with_true_before_initial_stim_circuit_checks_complete(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_info"] = create_random_stim_info()
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells
    # set random circuit status to None
    shared_values_dict["stimulator_circuit_statuses"][randint(0, test_num_wells - 1)] = None

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert (
        response.status.endswith("Cannot start stimulation before initial stimulator circuit checks complete")
        is True
    )


def test_set_stim_status__returns_error_code_and_message_if_called_with_true_if_any_circuits_are_short(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_info"] = create_random_stim_info()
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells
    # set random circuit status to short
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.SHORT.name.lower()

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert response.status.endswith("Cannot start stimulation when a stimulator has a short circuit") is True


def test_set_stim_status__returns_error_code_and_message_if_called_with_true_while_stim_circuit_checks_are_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_info"] = create_random_stim_info()
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells
    # set random circuit status to calculating
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.CALCULATING.name.lower()

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert (
        response.status.endswith("Cannot start stimulation while running stimulator circuit checks") is True
    )


def test_set_stim_status__returns_code_and_message_if_new_status_is_the_same_as_the_current_status(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_info"] = {}
    shared_values_dict["stimulator_circuit_statuses"] = [
        StimulatorCircuitStatuses.MEDIA.name.lower()
    ] * test_num_wells

    response = test_client.post("/set_stim_status?running=false")
    assert response.status_code == 304
    assert response.status.endswith("Status not updated") is True

    shared_values_dict["stimulation_running"][0] = True  # arbitrary well
    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 304
    assert response.status.endswith("Status not updated") is True


def test_set_protocols__returns_error_code_if_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    response = test_client.post("/set_protocols")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode") is True


def test_set_protocols__returns_error_code_if_called_while_stimulation_is_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["stimulation_running"][1] = True  # arbitrary well

    response = test_client.post("/set_protocols")
    assert response.status_code == 403
    assert response.status.endswith("Cannot change protocols while stimulation is running") is True


@pytest.mark.parametrize(
    "test_system_status",
    set(SYSTEM_STATUS_UUIDS.keys()) - {CALIBRATED_STATE, BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE},
)
def test_set_protocols__returns_error_code_if_called_during_invalid_system_status(
    test_system_status,
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["system_status"] = test_system_status

    response = test_client.post("/set_protocols")
    assert response.status_code == 403
    assert response.status.endswith(f"Cannot change protocols while {test_system_status}") is True


def test_set_protocols__returns_error_code_if_protocol_list_is_empty(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    response = test_client.post("/set_protocols", json={"data": json.dumps({"protocols": []})})
    assert response.status_code == 400
    assert response.status.endswith("Protocol list empty") is True


def test_set_protocols__returns_error_code_if_two_protocols_are_given_with_the_same_id(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    expected_id = "Z"
    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": expected_id,
                "run_until_stopped": False,
                "stimulation_type": "V",
                "subprotocols": [get_random_subprotocol()],
            }
        ]
        * 2,
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(f"Multiple protocols given with ID: {expected_id}") is True


@pytest.mark.parametrize(
    "test_stimulation_type,test_description",
    [
        (None, "return error code with None"),
        (1, "return error code with int"),
        ("A", "return error code with invalid string"),
    ],
)
def test_set_protocols__returns_error_code_with_invalid_stimulation_type(
    client_and_server_manager_and_shared_values, test_stimulation_type, test_description
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_stim_info_dict = {"protocols": [{"protocol_id": "A", "stimulation_type": test_stimulation_type}]}
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(f"Invalid stimulation type: {test_stimulation_type}") is True


@pytest.mark.parametrize(
    "test_subprotocol_item,test_value,test_stim_type,test_description",
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
        ("interphase_interval", -1, "C", "Invalid interphase interval: -1"),
        ("repeat_delay_interval", -1, "C", "Invalid repeat delay interval: -1"),
        (
            "total_active_duration",
            STIM_MAX_PULSE_DURATION_MICROSECONDS // int(1e3) - 1,
            "C",
            "Total active duration less than the duration of the subprotocol",
        ),
    ],
)
def test_set_protocols__returns_error_code_with_single_invalid_subprotocol_value(
    client_and_server_manager_and_shared_values,
    mocker,
    test_subprotocol_item,
    test_value,
    test_stim_type,
    test_description,
):
    mocker.patch.object(server, "queue_command_to_main", autospec=True)

    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_base_charge = (
        STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS if test_stim_type == "V" else STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
    )
    # create an arbitrary protocol to which an invalid value can easily be added
    test_stim_info_dict = {
        "protocols": [
            {
                "stimulation_type": test_stim_type,
                "protocol_id": "A",
                "run_until_stopped": False,
                "subprotocols": [
                    {
                        "phase_one_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS // 4,
                        "phase_one_charge": test_base_charge,
                        "interphase_interval": STIM_MAX_PULSE_DURATION_MICROSECONDS // 2,
                        "phase_two_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS // 4,
                        "phase_two_charge": -test_base_charge,
                        "repeat_delay_interval": STIM_MAX_PULSE_DURATION_MICROSECONDS // 4,
                        "total_active_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                    }
                ],
            }
        ]
    }
    # add bad value
    test_stim_info_dict["protocols"][0]["subprotocols"][0][test_subprotocol_item] = test_value

    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert f"400 {test_description}" in response.status


def test_set_protocols__returns_error_code_when_pulse_duration_is_too_long(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_stim_info_dict = {
        "protocols": [
            {
                "stimulation_type": "V",
                "protocol_id": "A",
                "run_until_stopped": True,
                "subprotocols": [
                    {
                        "phase_one_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS // 2,
                        "phase_one_charge": 0,
                        "interphase_interval": 1,
                        "phase_two_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS // 2,
                        "phase_two_charge": 0,
                        "repeat_delay_interval": STIM_MAX_PULSE_DURATION_MICROSECONDS * 10,
                        "total_active_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS * 20,
                    }
                ],
            }
        ]
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert "400 Pulse duration too long" in response.status


def test_set_protocols__returns_error_code_if_a_single_well_is_missing_from_protocol_assignments(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_num_wells = 24
    protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "A"
        for well_idx in range(test_num_wells)
    }
    missing_well = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(randint(0, 23))
    del protocol_assignments[missing_well]

    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "C",
                "run_until_stopped": True,
                "subprotocols": [get_random_subprotocol()],
            }
        ],
        "protocol_assignments": protocol_assignments,
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert f"400 Protocol assignments missing well {missing_well}" in response.status


@pytest.mark.parametrize(
    "test_well_name,test_description",
    [
        ("Z1", "return error code with invalid well: Z1"),
        ("A99", "return error code with invalid well: A99"),
    ],
)
def test_set_protocols__returns_error_code_with_invalid_well_name(
    client_and_server_manager_and_shared_values, test_well_name, test_description
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "F" for well_idx in range(24)
    }
    protocol_assignments[test_well_name] = "F"
    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": "F",
                "run_until_stopped": False,
                "stimulation_type": "V",
                "subprotocols": [get_random_subprotocol()],
            }
        ],
        "protocol_assignments": protocol_assignments,
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(f"Protocol assignments contain invalid well: {test_well_name}") is True


def test_set_protocols__returns_error_code_if_protocol_assignments_contains_a_single_invalid_protocol_id(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "K" for well_idx in range(24)
    }
    protocol_assignments["A1"] = None  # also make sure at least one well is not assigned a protocol
    # assign invalid protocol ID
    bad_id = "1"
    protocol_assignments["B1"] = "1"

    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": "K",
                "run_until_stopped": False,
                "stimulation_type": "V",
                "subprotocols": [get_random_subprotocol()],
            }
        ],
        "protocol_assignments": protocol_assignments,
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(f"Protocol assignments contain invalid protocol ID: {bad_id}") is True


def test_set_protocols__returns_error_code_if_one_of_the_given_protocols_is_not_assigned_to_any_wells(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_ids = ("L", "M")
    protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): test_ids[0]
        for well_idx in range(24)
    }
    protocol_assignments["D1"] = None  # also make sure at least one well is not assigned a protocol

    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "run_until_stopped": False,
                "stimulation_type": "V",
                "subprotocols": [get_random_subprotocol()],
            }
            for protocol_id in test_ids
        ],
        "protocol_assignments": protocol_assignments,
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(f"Protocol assignments missing protocol ID: {test_ids[1]}") is True


def test_set_protocols__returns_success_code_if_protocols_would_not_be_updated(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": "J",
                "run_until_stopped": False,
                "stimulation_type": "V",
                "subprotocols": [get_random_subprotocol()],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "J" for well_idx in range(24)
        },
    }
    shared_values_dict["stimulation_info"] = test_stim_info_dict

    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 200


def test_latest_software_version__returns_error_code_when_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    response = test_client.post("/latest_software_version")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode") is True


def test_latest_software_version__returns_error_code_when_version_param_is_not_given(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    response = test_client.post("/latest_software_version")
    assert response.status_code == 400
    assert response.status.endswith("Version not specified") is True


def test_latest_software_version__returns_error_code_when_version_string_is_not_a_valid_semantic_version(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    response = test_client.post("/latest_software_version?version=bad")
    assert response.status_code == 400
    assert response.status.endswith("Invalid version string") is True


def test_latest_software_version__returns_ok_when_version_string_is_a_valid_semantic_version(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    response = test_client.post("/latest_software_version?version=1.1.1")
    assert response.status_code == 200


def test_firmware_update_confirmation__returns_error_code_when_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    response = test_client.post("/firmware_update_confirmation")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode") is True
