# -*- coding: utf-8 -*-
import itertools
import json
import math
import os
from random import choice
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
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
from mantarray_desktop_app import STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS
from mantarray_desktop_app import STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import SERIAL_COMM_NICKNAME_BYTES_LENGTH
from mantarray_desktop_app.constants import STIM_MAX_DUTY_CYCLE_PERCENTAGE
from mantarray_desktop_app.constants import STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
from mantarray_desktop_app.constants import SystemActionTransitionStates
from mantarray_desktop_app.exceptions import LoginFailedError
from mantarray_desktop_app.main_process import server
from mantarray_desktop_app.utils.stimulation import get_pulse_duty_cycle_dur_us
from mantarray_desktop_app.utils.stimulation import SUBPROTOCOL_DUTY_CYCLE_DUR_COMPONENTS
from pulse3D.constants import MAX_MINI_SKM_EXPERIMENT_ID
from pulse3D.constants import MAX_VARIABLE_EXPERIMENT_ID
import pytest
from tests.fixtures_file_writer import GENERIC_STIM_INFO

from ..fixtures import fixture_generic_queue_container
from ..fixtures_mc_simulator import create_random_stim_info
from ..fixtures_mc_simulator import get_random_biphasic_pulse
from ..fixtures_mc_simulator import get_random_monophasic_pulse
from ..fixtures_mc_simulator import get_random_stim_pulse
from ..fixtures_mc_simulator import random_stim_type
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


def random_protocol_id():
    return chr(randint(ord("A"), ord("Z")))


@pytest.mark.parametrize(
    ",".join(("expected_status", "expected_in_simulation", "test_description")),
    [
        (BUFFERING_STATE, False, "correctly returns buffering and False"),
        (CALIBRATION_NEEDED_STATE, True, "correctly returns buffering and True"),
        (CALIBRATING_STATE, False, "correctly returns calibrating and False"),
    ],
)
def test_system_status__returns_correct_state_and_simulation_values(
    expected_status, expected_in_simulation, test_description, client_and_server_manager_and_shared_values
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


def test_system_status__returns_correct_log_file_id(client_and_server_manager_and_shared_values):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["log_file_id"] == shared_values_dict["log_file_id"]


@pytest.mark.parametrize(
    "test_stimulating_value,test_description",
    [(True, "returns True when stimulating"), (False, "returns False when not stimulating")],
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
    client_and_server_manager_and_shared_values, mocker
):
    test_client, *_ = client_and_server_manager_and_shared_values
    spied_server_logger = mocker.spy(server.logger, "info")

    response = test_client.get("/system_status")
    assert response.status_code == 200

    response_json = response.get_json()
    assert response_json["is_stimulating"] is False

    assert len(spied_server_logger.call_args_list) == 0


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
    expected_serial, expected_nickname, test_description, client_and_server_manager_and_shared_values
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

    spied_server_logger = mocker.spy(server.logger, "info")
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
        assert response.status.endswith(
            f"Versions of Electron and Flask EXEs do not match. Expected: {expected_software_version}"
        )
        assert len(spied_server_logger.call_args_list) > 0


@pytest.mark.parametrize(
    ",".join(("test_nickname", "test_description")),
    [
        ("123456789012345678901234", "returns error with no unicode characters"),
        ("1234567890123456789012à", "returns error with unicode character"),
    ],
)
def test_set_mantarray_nickname__returns_error_code_and_message_if_nickname_is_too_many_bytes__in_beta_1_mode(
    test_nickname, test_description, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values

    shared_values_dict["beta_2_mode"] = False
    shared_values_dict["mantarray_nickname"] = dict()

    response = test_client.get(f"/set_mantarray_nickname?nickname={test_nickname}")
    assert response.status_code == 400
    assert response.status.endswith("Nickname exceeds 23 bytes")


@pytest.mark.parametrize(
    ",".join(("test_nickname", "test_description")),
    [
        ("123456789012345678901234567890123", "returns error with no unicode characters"),
        ("1234567890123456789012345678901à", "returns error with unicode character"),
    ],
)
def test_set_mantarray_nickname__returns_error_code_and_message_if_nickname_is_too_many_bytes__in_beta_2_mode(
    test_nickname, test_description, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values

    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["mantarray_nickname"] = dict()

    response = test_client.get(f"/set_mantarray_nickname?nickname={test_nickname}")
    assert response.status_code == 400
    assert response.status.endswith(f"Nickname exceeds {SERIAL_COMM_NICKNAME_BYTES_LENGTH} bytes")


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
    test_system_status, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = test_system_status

    if test_system_status in (CALIBRATION_NEEDED_STATE, CALIBRATED_STATE):
        expected_status_code = 200
    elif test_system_status in CALIBRATING_STATE:
        expected_status_code = 304
    else:
        expected_status_code = 403

    response = test_client.get("/start_calibration")
    assert response.status_code == expected_status_code


def test_start_calibration__returns_error_code_and_message_if_called_in_beta_2_mode_while_stimulating(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["beta_2_mode"] = True

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_running"][0] = True  # arbitrary well
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }

    response = test_client.get("/start_calibration")
    assert response.status_code == 403
    assert response.status.endswith("Cannot calibrate while stimulation is running")


def test_start_calibration__returns_error_code_and_message_if_called_in_beta_2_mode_while_stimulator_checks_are_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["beta_2_mode"] = True

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }
    # set random circuit status to calculating
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.CALCULATING.name.lower()

    response = test_client.get("/start_calibration")
    assert response.status_code == 403
    assert response.status.endswith("Cannot calibrate while stimulator checks are running")


def test_start_stim_checks__returns_error_code_and_message_if_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    response = test_client.post("/start_stim_checks")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode")


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
    test_system_status, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = test_system_status

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }

    test_stim_barcode = MantarrayMcSimulator.default_stim_barcode
    test_plate_barcode = MantarrayMcSimulator.default_plate_barcode

    expected_status_code = 200 if test_system_status == CALIBRATED_STATE else 403

    response = test_client.post(
        "/start_stim_checks",
        json={"well_indices": [0], "plate_barcode": test_plate_barcode, "stim_barcode": test_stim_barcode},
    )
    assert response.status_code == expected_status_code
    if expected_status_code == 403:
        assert response.status.endswith("Route cannot be called unless in calibrated state")


def test_start_stim_checks__returns_error_code_and_message_if_called_while_stimulating(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["beta_2_mode"] = True

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_running"][0] = True  # arbitrary well
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }

    response = test_client.post("/start_stim_checks")
    assert response.status_code == 403
    assert response.status.endswith("Cannot perform stimulator checks while stimulation is running")


def test_set_start_stim_checks__returns_code_and_message_if_checks_are_already_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }
    # set random circuit status to calculating
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.CALCULATING.name.lower()

    response = test_client.post("/start_stim_checks")
    assert response.status_code == 304


def test_start_stim_checks__returns_error_code_and_message_if_called_without_well_indices_in_body(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["beta_2_mode"] = True

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = {}

    response = test_client.post("/start_stim_checks")
    assert response.status_code == 400
    assert response.status.endswith("Request body missing 'well_indices'")


def test_start_stim_checks__returns_error_code_and_message_if_called_with_empty_well_indices_list(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["beta_2_mode"] = True

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulator_circuit_statuses"] = {}

    test_stim_barcode = MantarrayMcSimulator.default_stim_barcode
    test_plate_barcode = MantarrayMcSimulator.default_plate_barcode

    response = test_client.post(
        "/start_stim_checks",
        json={"well_indices": [], "plate_barcode": test_plate_barcode, "stim_barcode": test_stim_barcode},
    )
    assert response.status_code == 400
    assert response.status.endswith("No well indices given")


def test_update_recording_name__returns_error_code_if_recording_name_exists(
    client_and_server_manager_and_shared_values, mocker
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["config_settings"]["recording_directory"] = "/test/recording/directory"

    mocker.patch.object(os.path, "exists", return_value=True)

    response = test_client.post(
        "/update_recording_name?new_name=new_recording_name&default_name=old_name&snapshot_enabled=false"
    )
    assert response.status_code == 403
    assert response.status.endswith("Recording name already exists")


def test_update_recording_name__returns_error_code_if_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values, mocker
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False
    shared_values_dict["config_settings"]["recording_directory"] = "/test/recording/directory"

    mocker.patch.object(os.path, "exists", return_value=True)

    response = test_client.post(
        "/update_recording_name?new_name=new_recording_name&default_name=old_name&snapshot_enabled=true"
    )
    assert response.status_code == 403
    assert response.status.endswith("Cannot run recording snapshot in Beta 1 mode")


def test_update_recording_name__returns_ok_if_recording_name_doesnt_exist(
    client_and_server_manager_and_shared_values, mocker
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["config_settings"]["recording_directory"] = "/test/recording/directory"

    mocker.patch.object(os.path, "exists", return_value=False)

    response = test_client.post(
        "/update_recording_name?new_name=new_recording_name&default_name=old_name&snapshot_enabled=true",
        json={"user_defined_metadata": "any"},
    )
    assert response.status_code == 200


def test_dev_begin_hardware_script__returns_correct_response(test_client):
    response = test_client.get("/development/begin_hardware_script?script_type=ENUM&version=integer")
    assert response.status_code == 200


def test_dev_end_hardware_script__returns_correct_response(test_client):
    response = test_client.get("/development/end_hardware_script")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "test_serial_number,expected_error_message",
    [
        ("M120019000", "Serial Number exceeds max length"),
        ("M1200190", "Serial Number does not reach min length"),
        ("M02-36700", "Serial Number contains invalid character: '-'"),
        ("M12001900", "Serial Number contains invalid header: 'M1'"),
        ("M01901900", "Serial Number contains invalid year: '19'"),
        ("M02000000", "Serial Number contains invalid Julian date: '000'"),
        ("M02036700", "Serial Number contains invalid Julian date: '367'"),
    ],
)
def test_set_mantarray_serial_number__returns_error_code_and_message_if_serial_number_is_invalid(
    test_serial_number, expected_error_message, client_and_server_manager_and_shared_values
):
    test_client, *_ = client_and_server_manager_and_shared_values

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={test_serial_number}"
    )
    assert response.status_code == 400
    assert response.status.endswith(expected_error_message)


def test_start_managed_acquisition__returns_error_code_and_message_if_plate_barcode_is_not_given(
    client_and_server_manager_and_shared_values,
):
    test_client, *_ = client_and_server_manager_and_shared_values

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 400
    assert response.status.endswith("Request missing 'plate_barcode' parameter")


def test_start_managed_acquisition__returns_error_code_if_barcode_header_and_type_do_not_match(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    # using a stim barcode instead of a plate barcode will trigger the error here
    test_barcode = MantarrayMcSimulator.default_stim_barcode

    response = test_client.get(f"/start_managed_acquisition?plate_barcode={test_barcode}")
    assert response.status_code == 400
    assert response.status.endswith("Plate barcode contains invalid header: 'MS'")


def test_start_managed_acquisition__returns_error_code_and_message_if_mantarray_serial_number_is_empty(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    board_idx = 0
    shared_values_dict["mantarray_serial_number"] = {board_idx: ""}

    test_barcode = MantarrayMcSimulator.default_plate_barcode

    response = test_client.get(f"/start_managed_acquisition?plate_barcode={test_barcode}")
    assert response.status_code == 406
    assert response.status.endswith("Mantarray has not been assigned a Serial Number")


@pytest.mark.parametrize("test_system_status", [BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE])
def test_start_managed_acquisition__returns_error_code_if_already_running(
    test_system_status, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = test_system_status
    shared_values_dict["mantarray_serial_number"] = {0: MantarrayMcSimulator.default_mantarray_serial_number}
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(24)
    }

    response = test_client.get(
        f"/start_managed_acquisition?plate_barcode={MantarrayMcSimulator.default_plate_barcode}"
    )
    assert response.status_code == 304


def test_start_managed_acquisition__returns_no_error_when_mini_barcode_is_used(
    client_and_server_manager_and_shared_values, mocker
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["mantarray_serial_number"] = {0: MantarrayMcSimulator.default_mantarray_serial_number}
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(24)
    }

    exp_id = randint(MAX_VARIABLE_EXPERIMENT_ID + 1, MAX_MINI_SKM_EXPERIMENT_ID)
    test_mini_barcode = f"ML22001{exp_id}-2"

    response = test_client.get(f"/start_managed_acquisition?plate_barcode={test_mini_barcode}")
    assert response.status_code == 200


def test_start_managed_acquisition__returns_error_code_and_message_called_while_stimulator_checks_are_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    test_barcode = MantarrayMcSimulator.default_plate_barcode

    board_idx = 0
    shared_values_dict["mantarray_serial_number"] = {
        board_idx: MantarrayMcSimulator.default_mantarray_serial_number
    }

    test_num_wells = 24
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }
    # set random circuit status to calculating
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.CALCULATING.name.lower()

    response = test_client.get(f"/start_managed_acquisition?plate_barcode={test_barcode}")
    assert response.status_code == 403
    assert response.status.endswith("Cannot start managed acquisition while stimulator checks are running")


def test_stop_managed_acquisition__returns_error_code_if_called_in_incorrect_state(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = choice([CALIBRATION_NEEDED_STATE, CALIBRATING_STATE])
    shared_values_dict["system_action_transitions"] = {"live_view": None}

    response = test_client.get("/stop_managed_acquisition")
    assert response.status_code == 403


def test_stop_managed_acquisition__returns_error_code_if_not_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["system_action_transitions"] = {"live_view": None}

    response = test_client.get("/stop_managed_acquisition")
    assert response.status_code == 304


def test_stop_managed_acquisition__returns_error_code_if_stopping(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE
    shared_values_dict["system_action_transitions"] = {"live_view": SystemActionTransitionStates.STOPPING}

    response = test_client.get("/stop_managed_acquisition")
    assert response.status_code == 304


def test_get_recordings__returns_error_code_and_message_when_recording_directory_is_not_found(
    client_and_server_manager_and_shared_values,
):
    test_client, *_ = client_and_server_manager_and_shared_values

    response = test_client.get("/get_recordings")
    assert response.status_code == 400
    assert response.status.endswith("No root recording directory was found")


def test_get_recordings__returns_200_with_list_of_directories(client_and_server_manager_and_shared_values):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    with tempfile.TemporaryDirectory() as tmp_recording_dir:
        shared_values_dict["config_settings"]["recording_directory"] = tmp_recording_dir

        response = test_client.get("/get_recordings")
        assert response.status_code == 200
        assert response.get_json() == {"recordings_list": [], "root_recording_path": tmp_recording_dir}


def test_start_data_analysis__returns_error_code_and_message_when_recording_directory_is_not_found(
    client_and_server_manager_and_shared_values,
):
    test_client, *_ = client_and_server_manager_and_shared_values

    response = test_client.post(
        "/start_data_analysis", json={"selected_recordings": ["recording_1", "recording_2"]}
    )
    assert response.status_code == 400
    assert response.status.endswith("Root directories were not found")


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
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    #  mock a user being logged in
    shared_values_dict["user_creds"] = {}
    test_dir = "fake_dir/fake_sub_dir"

    response = test_client.get(f"/update_settings?recording_directory={test_dir}")
    assert response.status_code == 400
    assert response.status.endswith(f"{repr(RecordingFolderDoesNotExistError(test_dir))}")


def test_update_settings__returns_error_message_when_user_is_not_logged_in(
    client_and_server_manager_and_shared_values,
):
    test_client, *_ = client_and_server_manager_and_shared_values
    #  mock a user being logged in
    test_dir = "fake_dir/fake_sub_dir"
    response = test_client.get(f"/update_settings?recording_directory={test_dir}")

    assert response.status_code == 400
    assert response.status.endswith("400 User is not logged in")


@pytest.mark.parametrize("endpoint", ["update_settings", "login"])
def test_update_settings_login__returns_error_message_when_unexpected_argument_is_given(
    test_client, endpoint
):
    test_arg = "bad_arg"
    response = test_client.get(f"/{endpoint}?{test_arg}=True")
    assert response.status_code == 400
    assert response.status.endswith(f"Invalid argument given: {test_arg}")


def test_login__returns_correct_error_code_when_user_auth_fails(test_client, mocker):
    test_error = LoginFailedError(401)

    # mock so test doesn't hit cloud API
    mocked_validate = mocker.patch.object(
        server, "validate_user_credentials", autospec=True, side_effect=test_error
    )

    test_user_creds = {"customer_id": "cid", "user_name": "user", "user_password": "pw"}

    response = test_client.get(f"/login?{urllib.parse.urlencode(test_user_creds)}")
    assert response.status_code == 401
    assert repr(test_error) in response.status

    mocked_validate.assert_called_once()
    assert dict(mocked_validate.call_args[0][0]) == test_user_creds


def test_route_error_message_is_logged(mocker, test_client):
    mocked_logger = mocker.spy(server.logger, "info")

    bad_arg = "a"
    expected_error_msg = f"Invalid argument given: {bad_arg}"

    response = test_client.get(f"/update_settings?{bad_arg}=")
    assert response.status_code == 400
    assert expected_error_msg in response.status

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
    assert response.status.endswith("Request missing 'plate_barcode' parameter")


def test_start_recording__returns_error_code_and_message_if_stim_barcode_is_not_given_while_stim_is_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [True] * 24

    response = test_client.get(f"/start_recording?plate_barcode={MantarrayMcSimulator.default_plate_barcode}")
    assert response.status_code == 400
    assert response.status.endswith("Request missing 'stim_barcode' parameter")


def test_start_recording__returns_no_error_when_mini_barcode_is_sent(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)
    shared_values_dict["stimulation_running"] = [True] * 24

    exp_id = randint(MAX_VARIABLE_EXPERIMENT_ID + 1, MAX_MINI_SKM_EXPERIMENT_ID)
    barcodes = {
        "plate_barcode": f"ML22001{exp_id}-2",
        "stim_barcode": MantarrayMcSimulator.default_stim_barcode,
    }

    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(barcodes)}")
    assert response.status_code == 200


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
        ("M*2021172200", "variable stiffness barcodes are not allowed"),
    ],
)
def test_start_recording__returns_error_code_and_message_if_barcode_is_invalid(
    test_barcode_type, test_barcode, expected_error_message, client_and_server_manager_and_shared_values
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
    assert response.status.endswith(f"{test_barcode_type} {expected_error_message}")


@pytest.mark.parametrize(
    "test_barcode,expected_error_message",
    [
        ("ML222123199-1", "barcode is incorrect length"),
        ("ML222-1", "barcode is incorrect length"),
        ("MA22123199-1", "barcode contains invalid header: 'MA'"),
        ("MB22123199-1", "barcode contains invalid header: 'MB'"),
        ("ME22123199-1", "barcode contains invalid header: 'ME'"),
        ("ML221$3199-1", "barcode contains invalid character: '$'"),
        ("ML20123199-1", "barcode contains invalid year: '20'"),
        ("ML22444199-1", "barcode contains invalid Julian date: '444'"),
        ("ML22123999-1", "barcode contains invalid experiment id: '999'"),
        ("ML22123199-2", "barcode contains invalid last digit: '2'"),
        ("ML22123299-1", "variable stiffness barcodes are not allowed"),
    ],
)
def test_start_recording__returns_error_code_and_message_if_new_barcode_beta_1_mode_scheme_is_invalid(
    test_barcode, expected_error_message, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    barcodes = {"plate_barcode": test_barcode}

    response = test_client.get(f"/start_recording?{urllib.parse.urlencode(barcodes)}")
    assert response.status_code == 400
    assert response.status.endswith(f"Plate {expected_error_message}")


@pytest.mark.parametrize("test_barcode_type", ["Stim", "Plate"])
@pytest.mark.parametrize(
    "test_barcode,expected_error_message",
    [
        ("M*222123199-1", "barcode is incorrect length"),
        ("M*222-1", "barcode is incorrect length"),
        ("MA22123199-2", "barcode contains invalid header: 'MA'"),
        ("MB22123199-2", "barcode contains invalid header: 'MB'"),
        ("ME22123199-2", "barcode contains invalid header: 'ME'"),
        ("M*221$3199-2", "barcode contains invalid character: '$'"),
        ("M*20123199-2", "barcode contains invalid year: '20'"),
        ("M*22444199-2", "barcode contains invalid Julian date: '444'"),
        ("M*22123999-2", "barcode contains invalid experiment id: '999'"),
        ("M*22123199-1", "barcode contains invalid last digit: '1'"),
        ("M*22123299-2", "variable stiffness barcodes are not allowed"),
    ],
)
def test_start_recording__returns_error_code_and_message_if_new_barcode_beta_2_mode_scheme_is_invalid(
    test_barcode_type, test_barcode, expected_error_message, client_and_server_manager_and_shared_values
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
    assert response.status.endswith(f"{test_barcode_type} {expected_error_message}")


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
    assert response.status.endswith(expected_error_message)


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


def test_start_recording__returns_error_code_if_already_recording(
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


def test_stop_recording__returns_error_code_if_not_recording(client_and_server_manager_and_shared_values):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    put_generic_beta_2_start_recording_info_in_dict(shared_values_dict)
    shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE

    response = test_client.get("/stop_recording")
    assert response.status_code == 304


def test_route_with_no_url_rule__returns_error_message__and_logs_reponse_to_request(test_client, mocker):
    mocked_logger = mocker.spy(server.logger, "info")

    response = test_client.get("/fake_route")
    assert response.status_code == 404
    assert response.status.endswith("Route not implemented")

    mocked_logger.assert_called_once_with(f"Response to HTTP Request in next log entry: {response.status}")


def test_insert_xem_command_into_queue_routes__return_error_code_and_message_if_called_in_beta_2_mode(
    client_and_server_manager_and_shared_values, mocker
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values

    spied_queue_set_device_id = mocker.spy(server, "queue_set_device_id")

    shared_values_dict["beta_2_mode"] = True

    response = test_client.get("/insert_xem_command_into_queue/set_device_id")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 2 mode")

    spied_queue_set_device_id.assert_not_called()


def test_boot_up__return_error_code_and_message_if_called_in_beta_2_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    response = test_client.get("/boot_up")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 2 mode")


def test_set_stim_status__returns_error_code_if_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode")


def test_set_stim_status__returns_error_code_and_message_if_running_arg_is_not_given(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    response = test_client.post("/set_stim_status")
    assert response.status_code == 400
    assert response.status.endswith("Request missing 'running' parameter")


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
    assert response.status.endswith("Protocols have not been set")


@pytest.mark.parametrize(
    "test_system_status",
    set(SYSTEM_STATUS_UUIDS.keys())
    - {CALIBRATED_STATE, BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE},
)
def test_set_stim_status__returns_error_code_and_message_if_called_with_true_during_invalid_state(
    test_system_status, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = test_system_status
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["stimulation_info"] = create_random_stim_info()

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert response.status.endswith(f"Cannot start stimulation while {test_system_status}")


def test_set_stim_status__returns_error_code_and_message_if_called_with_true_before_initial_stim_circuit_checks_complete(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_info"] = create_random_stim_info()
    shared_values_dict["stimulator_circuit_statuses"] = {}

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert response.status.endswith(
        "Cannot start stimulation before initial stimulator circuit checks complete"
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
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }
    # set random circuit status to short
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.SHORT.name.lower()

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert response.status.endswith("Cannot start stimulation when a stimulator has a short circuit")


def test_set_stim_status__returns_error_code_and_message_if_called_with_true_while_stim_circuit_checks_are_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE

    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_info"] = create_random_stim_info()
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }
    # set random circuit status to calculating
    shared_values_dict["stimulator_circuit_statuses"][
        randint(0, test_num_wells - 1)
    ] = StimulatorCircuitStatuses.CALCULATING.name.lower()

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 403
    assert response.status.endswith("Cannot start stimulation while running stimulator circuit checks")


def test_set_stim_status__returns_code_and_message_if_new_status_is_the_same_as_the_current_status(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    test_num_wells = 24
    shared_values_dict["stimulation_running"] = [False] * test_num_wells
    shared_values_dict["stimulation_info"] = {}
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }

    response = test_client.post("/set_stim_status?running=false")
    assert response.status_code == 304

    shared_values_dict["stimulation_running"][0] = True  # arbitrary well
    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 304


@pytest.mark.parametrize(
    "test_system_status", {CALIBRATED_STATE, BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE}
)
def test_set_stim_status__returns_no_error_code_if_called_correctly__with_true(
    test_system_status, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values

    test_num_wells = 24

    shared_values_dict["system_action_transitions"] = {"stimulation": None}
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = test_system_status
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["stimulation_info"] = create_random_stim_info()
    shared_values_dict["stimulator_circuit_statuses"] = {
        well_idx: StimulatorCircuitStatuses.MEDIA.name.lower() for well_idx in range(test_num_wells)
    }

    response = test_client.post("/set_stim_status?running=true")
    assert response.status_code == 200


def test_set_protocols__returns_error_code_if_called_in_beta_1_mode(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = False

    response = test_client.post("/set_protocols")
    assert response.status_code == 403
    assert response.status.endswith("Route cannot be called in beta 1 mode")


def test_set_protocols__returns_error_code_if_called_while_stimulation_is_running(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["stimulation_running"][1] = True  # arbitrary well

    response = test_client.post("/set_protocols")
    assert response.status_code == 403
    assert response.status.endswith("Cannot change protocols while stimulation is running")


@pytest.mark.parametrize(
    "test_system_status",
    set(SYSTEM_STATUS_UUIDS.keys())
    - {CALIBRATED_STATE, BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE},
)
def test_set_protocols__returns_error_code_if_called_during_invalid_system_status(
    test_system_status, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["system_status"] = test_system_status

    response = test_client.post("/set_protocols")
    assert response.status_code == 403
    assert response.status.endswith(f"Cannot change protocols while {test_system_status}")


def test_set_protocols__returns_error_code_if_protocol_list_is_empty(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    response = test_client.post("/set_protocols", json={"data": json.dumps({"protocols": []})})
    assert response.status_code == 400
    assert response.status.endswith("Protocol list empty")


def test_set_protocols__returns_error_code_if_two_protocols_are_given_with_the_same_id(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    expected_id = random_protocol_id()
    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": expected_id,
                "run_until_stopped": False,
                "stimulation_type": "V",
                "subprotocols": [get_random_stim_pulse()],
            }
        ]
        * 2
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(f"Multiple protocols given with ID: {expected_id}")


@pytest.mark.parametrize("test_stimulation_type", [None, 1, "A"])
def test_set_protocols__returns_error_code_with_invalid_stimulation_type(
    client_and_server_manager_and_shared_values, test_stimulation_type
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_stim_info_dict = {
        "protocols": [{"protocol_id": random_protocol_id(), "stimulation_type": test_stimulation_type}]
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(f"Invalid stimulation type: {test_stimulation_type}")


def test_set_protocols__returns_error_if_invalid_subprotocol_type_given(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_subprotocol_type = "bad_type"
    test_protocol_id = random_protocol_id()

    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": test_protocol_id,
                "stimulation_type": random_stim_type(),
                "subprotocols": [{"type": test_subprotocol_type}],
            }
        ]
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(
        f"Protocol {test_protocol_id}, Subprotocol 0, Invalid subprotocol type: {test_subprotocol_type}"
    )


@pytest.mark.parametrize(
    "test_subprotocol_type,test_subprotocol_component,test_value,test_stim_type,expected_error_message",
    [
        (
            "delay",
            "duration",
            STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS - 1,
            random_stim_type(),
            "Subprotocol duration not long enough",
        ),
        (
            "delay",
            "duration",
            STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS + 1,
            random_stim_type(),
            "Subprotocol duration too long",
        ),
        ("monophasic", "phase_one_duration", 0, random_stim_type(), "Invalid phase one duration: 0"),
        ("monophasic", "phase_one_duration", -1, random_stim_type(), "Invalid phase one duration: -1"),
        ("biphasic", "phase_one_duration", 0, random_stim_type(), "Invalid phase one duration: 0"),
        ("biphasic", "phase_one_duration", -1, random_stim_type(), "Invalid phase one duration: -1"),
        (
            "monophasic",
            "phase_one_charge",
            STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS + 1,
            "C",
            f"Invalid phase one charge: {STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS + 1}",
        ),
        (
            "monophasic",
            "phase_one_charge",
            -STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS - 1,
            "C",
            f"Invalid phase one charge: {-STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS - 1}",
        ),
        (
            "monophasic",
            "phase_one_charge",
            STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS + 1,
            "V",
            f"Invalid phase one charge: {STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS + 1}",
        ),
        (
            "monophasic",
            "phase_one_charge",
            -STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS - 1,
            "V",
            f"Invalid phase one charge: {-STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS - 1}",
        ),
        ("biphasic", "interphase_interval", -1, random_stim_type(), "Invalid interphase interval: -1"),
        (
            "biphasic",
            "phase_two_charge",
            STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS + 1,
            "C",
            f"Invalid phase two charge: {STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS + 1}",
        ),
        (
            "biphasic",
            "phase_two_charge",
            -STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS - 1,
            "C",
            f"Invalid phase two charge: {-STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS - 1}",
        ),
        (
            "biphasic",
            "phase_two_charge",
            STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS + 1,
            "V",
            f"Invalid phase two charge: {STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS + 1}",
        ),
        (
            "biphasic",
            "phase_two_charge",
            -STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS - 1,
            "V",
            f"Invalid phase two charge: {-STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS - 1}",
        ),
        ("biphasic", "phase_two_duration", -1, random_stim_type(), "Invalid phase two duration: -1"),
        ("monophasic", "postphase_interval", -1, random_stim_type(), "Invalid postphase interval: -1"),
        ("biphasic", "postphase_interval", -1, random_stim_type(), "Invalid postphase interval: -1"),
    ],
)
def test_set_protocols__returns_error_code_with_single_invalid_subprotocol_value(
    client_and_server_manager_and_shared_values,
    mocker,
    test_subprotocol_type,
    test_subprotocol_component,
    test_value,
    test_stim_type,
    expected_error_message,
):
    mocker.patch.object(server, "queue_command_to_main", autospec=True)

    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    # create an arbitrary protocol to which an invalid value can easily be added
    test_base_charge = (
        STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS if test_stim_type == "V" else STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
    )
    test_subprotocol = {"type": test_subprotocol_type}

    if test_subprotocol_type == "delay":
        test_subprotocol["duration"] = STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
    else:
        test_subprotocol.update(
            {
                "phase_one_duration": STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS,
                "phase_one_charge": test_base_charge,
                "postphase_interval": 0,
                "num_cycles": 1,
            }
        )
        if test_subprotocol_type == "biphasic":
            test_subprotocol.update(
                {
                    "phase_one_duration": STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS // 3,
                    "interphase_interval": STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS // 3,
                    "phase_two_duration": STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS // 3,
                    "phase_two_charge": -test_base_charge,
                }
            )

    # add bad value
    test_subprotocol[test_subprotocol_component] = test_value

    # create stim info
    test_protocol_id = random_protocol_id()
    test_stim_info_dict = {
        "protocols": [
            {
                "stimulation_type": test_stim_type,
                "protocol_id": test_protocol_id,
                "run_until_stopped": False,
                "subprotocols": [test_subprotocol],
            }
        ]
    }

    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert f"Protocol {test_protocol_id}, Subprotocol 0, {expected_error_message}" in response.status


@pytest.mark.parametrize(
    "test_subprotocol_type,test_subprotocol_component,is_too_long",
    itertools.product(["monophasic", "biphasic"], ["postphase_interval", "num_cycles"], [True, False]),
)
def test_set_protocol__returns_error_code_with_invalid_subprotocol_duration_for_pulse(
    client_and_server_manager_and_shared_values,
    mocker,
    test_subprotocol_type,
    test_subprotocol_component,
    is_too_long,
):
    mocker.patch.object(server, "queue_command_to_main", autospec=True)

    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_stim_type = random_stim_type()

    # create an arbitrary protocol to which an invalid value can easily be added
    test_base_charge = (
        STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS if test_stim_type == "V" else STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
    )

    test_num_cycles = 2

    test_subprotocol_comp_dur = STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS // (2 * test_num_cycles)
    test_subprotocol = {
        "type": test_subprotocol_type,
        "phase_one_charge": test_base_charge,
        "phase_one_duration": test_subprotocol_comp_dur,
        "postphase_interval": test_subprotocol_comp_dur,
        "num_cycles": test_num_cycles,
    }
    if test_subprotocol_type == "biphasic":
        # the number of duration components doubled, so cut this value in half
        test_subprotocol_comp_dur //= 2
        test_subprotocol.update(
            {
                "phase_two_charge": -test_base_charge,
                "phase_one_duration": test_subprotocol_comp_dur,
                "interphase_interval": test_subprotocol_comp_dur,
                "phase_two_duration": test_subprotocol_comp_dur,
                "postphase_interval": test_subprotocol_comp_dur,
            }
        )

    bad_values = {
        "num_cycles": {
            True: (
                2 * STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS // STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
                + 1
            ),
            False: 1,
        },
        "postphase_interval": {
            True: (STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS // 2 - test_subprotocol_comp_dur + 1),
            False: test_subprotocol_comp_dur - 1,
        },
    }
    test_subprotocol[test_subprotocol_component] = bad_values[test_subprotocol_component][is_too_long]

    # create stim info
    test_protocol_id = random_protocol_id()
    test_stim_info_dict = {
        "protocols": [
            {
                "stimulation_type": test_stim_type,
                "protocol_id": test_protocol_id,
                "run_until_stopped": False,
                "subprotocols": [test_subprotocol],
            }
        ]
    }

    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400

    expected_error_message = (
        "Subprotocol duration too long" if is_too_long else "Subprotocol duration not long enough"
    )
    assert f"Protocol {test_protocol_id}, Subprotocol 0, {expected_error_message}" in response.status


@pytest.mark.parametrize("test_pulse_fn", [get_random_biphasic_pulse, get_random_monophasic_pulse])
def test_set_protocols__returns_error_code_when_duty_cycle_exceeds_the_max_duration_limit(
    test_pulse_fn, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_pulse = test_pulse_fn()

    comp_to_lengthen = choice([comp for comp in SUBPROTOCOL_DUTY_CYCLE_DUR_COMPONENTS if comp in test_pulse])
    test_pulse[comp_to_lengthen] += (
        STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS + 1 - get_pulse_duty_cycle_dur_us(test_pulse)
    )

    test_protocol_id = random_protocol_id()
    test_stim_info_dict = {
        "protocols": [
            {
                "stimulation_type": "V",
                "protocol_id": test_protocol_id,
                "run_until_stopped": True,
                "subprotocols": [test_pulse],
            }
        ]
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert f"Protocol {test_protocol_id}, Subprotocol 0, Duty cycle duration too long" in response.status


@pytest.mark.parametrize("test_pulse_fn", [get_random_biphasic_pulse, get_random_monophasic_pulse])
def test_set_protocols__returns_error_code_when_duty_cycle_exceeds_max_percentage_limit(
    test_pulse_fn, client_and_server_manager_and_shared_values
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    # set up pulse so that it is short enough for the 80% duty cycle limit to be lower than the max duty cycle duration limit
    test_pulse_duration_us = (
        math.floor(STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS / STIM_MAX_DUTY_CYCLE_PERCENTAGE) - 1
    )
    test_num_cycles = randint(10, 20)
    test_subprotocol_dur = test_pulse_duration_us * test_num_cycles
    test_pulse = test_pulse_fn(total_subprotocol_dur_us=test_subprotocol_dur, num_cycles=test_num_cycles)

    max_duty_cycle_dur_us = STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS - 1
    dur_us_to_move_to_duty_cycle = max_duty_cycle_dur_us + 1 - get_pulse_duty_cycle_dur_us(test_pulse)

    comp_to_lengthen = choice([comp for comp in SUBPROTOCOL_DUTY_CYCLE_DUR_COMPONENTS if comp in test_pulse])
    test_pulse[comp_to_lengthen] += dur_us_to_move_to_duty_cycle
    test_pulse["postphase_interval"] -= dur_us_to_move_to_duty_cycle

    test_protocol_id = random_protocol_id()
    test_stim_info_dict = {
        "protocols": [
            {
                "stimulation_type": "V",
                "protocol_id": test_protocol_id,
                "run_until_stopped": True,
                "subprotocols": [test_pulse],
            }
        ]
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert (
        f"Protocol {test_protocol_id}, Subprotocol 0, Duty cycle exceeds {int(STIM_MAX_DUTY_CYCLE_PERCENTAGE * 100)}%"
        in response.status
    )


@pytest.mark.parametrize("test_missing_wells", [{"A1"}, {"C4", "D6"}])
def test_set_protocols__returns_error_code_if_any_well_is_missing_from_protocol_assignments(
    client_and_server_manager_and_shared_values, test_missing_wells
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_num_wells = 24
    test_protocol_id = random_protocol_id()
    protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): test_protocol_id
        for well_idx in range(test_num_wells)
    }
    for well_name in test_missing_wells:
        del protocol_assignments[well_name]

    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": test_protocol_id,
                "stimulation_type": "C",
                "run_until_stopped": True,
                "subprotocols": [get_random_stim_pulse()],
            }
        ],
        "protocol_assignments": protocol_assignments,
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert "Protocol assignments missing wells:" in response.status
    for well in test_missing_wells:
        assert f"'{well}'" in response.status


@pytest.mark.parametrize(
    "test_well_names,test_bad_names",
    [({"Z1"}, {"Z1"}), ({"C4", "A99"}, {"A99"}), ({"G6", "L2"}, {"G6", "L2"})],
)
def test_set_protocols__returns_error_code_with_invalid_well_name(
    client_and_server_manager_and_shared_values, test_well_names, test_bad_names
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_protocol_id = random_protocol_id()
    protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): test_protocol_id
        for well_idx in range(24)
    }
    protocol_assignments.update({well: test_protocol_id for well in test_well_names})

    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": test_protocol_id,
                "run_until_stopped": False,
                "stimulation_type": "V",
                "subprotocols": [get_random_stim_pulse()],
            }
        ],
        "protocol_assignments": protocol_assignments,
    }

    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert "Protocol assignments contain invalid wells:" in response.status
    for well in test_bad_names:
        assert f"'{well}'" in response.status


@pytest.mark.parametrize("test_invalid_ids", [{"B"}, {"B", "C"}])
def test_set_protocols__returns_error_code_if_protocol_assignments_contains_any_invalid_protocol_ids(
    client_and_server_manager_and_shared_values, test_invalid_ids
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "A" for well_idx in range(24)
    }
    protocol_assignments["A1"] = None  # also make sure at least one well is not assigned a protocol
    for i, invalid_id in enumerate(test_invalid_ids, 2):
        protocol_assignments[f"A{i}"] = invalid_id

    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": "A",
                "run_until_stopped": False,
                "stimulation_type": "V",
                "subprotocols": [get_random_stim_pulse()],
            }
        ],
        "protocol_assignments": protocol_assignments,
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(
        f"Protocol assignments contain invalid protocol IDs: {sorted(test_invalid_ids)}"
    )


@pytest.mark.parametrize("test_ids,test_unassigned_ids", [({"A", "B"}, {"A", "B"}), ({"A", "B"}, {"B"})])
def test_set_protocols__returns_error_code_if_any_of_the_given_protocols_are_not_assigned_to_any_wells(
    client_and_server_manager_and_shared_values, test_ids, test_unassigned_ids
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_ids_to_assign = list(test_ids - test_unassigned_ids)

    if test_ids_to_assign:
        protocol_assignments = {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): test_ids_to_assign[
                well_idx % len(test_ids_to_assign)
            ]
            for well_idx in range(24)
        }
        protocol_assignments["D1"] = None  # also make sure at least one well is not assigned a protocol
    else:
        protocol_assignments = {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): None for well_idx in range(24)
        }

    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "run_until_stopped": False,
                "stimulation_type": random_stim_type(),
                "subprotocols": [get_random_stim_pulse()],
            }
            for protocol_id in test_ids
        ],
        "protocol_assignments": protocol_assignments,
    }
    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 400
    assert response.status.endswith(f"Protocol assignments missing protocol IDs: {test_unassigned_ids}")


def test_set_protocols__returns_success_code_if_protocols_would_not_be_updated(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["system_status"] = CALIBRATED_STATE
    shared_values_dict["stimulation_running"] = [False] * 24

    test_protocol_id = random_protocol_id()
    test_stim_info_dict = {
        "protocols": [
            {
                "protocol_id": test_protocol_id,
                "run_until_stopped": False,
                "stimulation_type": "V",
                "subprotocols": [get_random_stim_pulse()],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): test_protocol_id
            for well_idx in range(24)
        },
    }
    shared_values_dict["stimulation_info"] = test_stim_info_dict

    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info_dict)})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "test_system_status", {CALIBRATED_STATE, BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE}
)
def test_set_protocols__returns_no_error_code_if_called_correctly(
    test_system_status, client_and_server_manager_and_shared_values, mocker
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True
    shared_values_dict["stimulation_running"] = [False] * 24
    shared_values_dict["system_status"] = test_system_status

    test_stim_info = dict(GENERIC_STIM_INFO)

    # patch so route doesn't hang forever
    mocker.patch.object(
        server, "_get_stim_info_from_process_monitor", autospec=True, return_value=test_stim_info
    )

    response = test_client.post("/set_protocols", json={"data": json.dumps(test_stim_info)})
    assert response.status_code == 200


def test_latest_software_version__returns_error_code_when_version_param_is_not_given(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    response = test_client.post("/latest_software_version")
    assert response.status_code == 400
    assert response.status.endswith("Version not specified")


def test_latest_software_version__returns_error_code_when_version_string_is_not_a_valid_semantic_version(
    client_and_server_manager_and_shared_values,
):
    test_client, _, shared_values_dict = client_and_server_manager_and_shared_values
    shared_values_dict["beta_2_mode"] = True

    response = test_client.post("/latest_software_version?version=bad")
    assert response.status_code == 400
    assert response.status.endswith("Invalid version string")


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
    assert response.status.endswith("Route cannot be called in beta 1 mode")
