# -*- coding: utf-8 -*-
"""Python Flask Server controlling Mantarray."""
from __future__ import annotations

import copy
from copy import deepcopy
from datetime import datetime
import json
import logging
import os
from queue import Queue
from time import sleep
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple
from typing import Union
import urllib.parse
from uuid import UUID

from flask import Flask
from flask import request
from flask import Response
from flask_cors import CORS
from flask_socketio import SocketIO
from immutabledict import immutabledict
from mantarray_desktop_app.main_process.shared_values import SharedValues
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import NOT_APPLICABLE_H5_METADATA
import requests
from semver import VersionInfo
from stdlib_utils import drain_queue
from stdlib_utils import is_port_in_use

from .queue_container import MantarrayQueueContainer
from ..constants import BUFFERING_STATE
from ..constants import CALIBRATED_STATE
from ..constants import CALIBRATING_STATE
from ..constants import CALIBRATION_NEEDED_STATE
from ..constants import DEFAULT_SERVER_PORT_NUMBER
from ..constants import GENERIC_24_WELL_DEFINITION
from ..constants import LIVE_VIEW_ACTIVE_STATE
from ..constants import MICRO_TO_BASE_CONVERSION
from ..constants import MICROSECONDS_PER_CENTIMILLISECOND
from ..constants import RECORDING_STATE
from ..constants import SERIAL_COMM_NICKNAME_BYTES_LENGTH
from ..constants import START_MANAGED_ACQUISITION_COMMUNICATION
from ..constants import StimulatorCircuitStatuses
from ..constants import STOP_MANAGED_ACQUISITION_COMMUNICATION
from ..constants import SUBPROCESS_POLL_DELAY_SECONDS
from ..constants import SYSTEM_STATUS_UUIDS
from ..constants import SystemActionTransitionStates
from ..constants import VALID_CONFIG_SETTINGS
from ..constants import VALID_STIMULATION_TYPES
from ..exceptions import InvalidSubprotocolError
from ..exceptions import LocalServerPortAlreadyInUseError
from ..exceptions import LoginFailedError
from ..exceptions import ServerManagerNotInitializedError
from ..exceptions import ServerManagerSingletonAlreadySetError
from ..sub_processes.ok_comm import check_mantarray_serial_number
from ..utils.generic import _check_scanned_barcode_vs_user_value
from ..utils.generic import _create_start_recording_command
from ..utils.generic import _get_timestamp_of_acquisition_sample_index_zero
from ..utils.generic import check_barcode_for_errors
from ..utils.generic import convert_request_args_to_config_dict
from ..utils.generic import get_current_software_version
from ..utils.generic import get_info_of_recordings
from ..utils.generic import get_redacted_string
from ..utils.generic import redact_sensitive_info_from_path
from ..utils.generic import validate_recording_directory
from ..utils.generic import validate_user_credentials
from ..utils.stimulation import validate_stim_subprotocol

logger = logging.getLogger(__name__)
os.environ[
    "FLASK_ENV"
] = "DEVELOPMENT"  # this removes warnings about running the Werkzeug server (which is not meant for high volume requests, but should be fine for intra-PC communication from a single client)
flask_app = Flask(__name__)
CORS(flask_app)
socketio = SocketIO(flask_app)

_the_server_manager: Optional[  # Eli (11/3/20) yes, this is intentionally a global variable, not a constant. This is the current best guess at how to allow Flask routes to access some info they need
    "ServerManager"
] = None


def clear_the_server_manager() -> None:
    global _the_server_manager  # Eli (12/8/20) this is deliberately setting a global
    _the_server_manager = None


def get_the_server_manager() -> "ServerManager":
    """Return the global instance."""
    if _the_server_manager is None:
        raise ServerManagerNotInitializedError(
            "This function should not be called when the ServerManager is None and hasn't been initialized yet."
        )
    return _the_server_manager


def get_server_to_main_queue() -> Queue[Dict[str, Any]]:
    return get_the_server_manager().get_queue_to_main()


def get_server_address_components() -> Tuple[str, str, int]:
    """Get Flask server address components.

    Returns:
        protocol (i.e. HTTP), host (i.e. 127.0.0.1), port (i.e. 4567)
    """
    try:
        port_number = get_the_server_manager().get_port_number()
    except (NameError, ServerManagerNotInitializedError):
        port_number = DEFAULT_SERVER_PORT_NUMBER
    return ("http", "127.0.0.1", port_number)


def get_api_endpoint() -> str:
    protocol, host, port = get_server_address_components()
    return f"{protocol}://{host}:{port}/"


def _get_values_from_process_monitor() -> Dict[str, Any]:
    return get_the_server_manager().get_values_from_process_monitor()


def queue_command_to_instrument_comm(comm_dict: Dict[str, Any]) -> Response:
    """Queue command to send to InstrumentCommProcess and return response."""
    to_instrument_comm_queue = get_the_server_manager().queue_container.to_instrument_comm(0)
    comm_dict = dict(comm_dict)  # make a mutable version to pass into ok_comm
    to_instrument_comm_queue.put_nowait(comm_dict)
    response = Response(json.dumps(comm_dict), mimetype="application/json")

    return response


def queue_command_to_main(comm_dict: Dict[str, Any]) -> Response:
    """Queue command to send to the main thread and return response."""
    to_main_queue = get_server_to_main_queue()

    comm_dict = dict(
        copy.deepcopy(comm_dict)
    )  # Eli (12/8/20): make a copy since sometimes this dictionary can be mutated after the communication gets passed elsewhere. This is relevant since this is a thread queue. Queues between true processes get pickled and in essence already get copied
    # Eli (12/8/20): immutable dicts cannot be JSON serialized, so make a regular dict copy
    to_main_queue.put_nowait(comm_dict)
    response = Response(json.dumps(comm_dict), mimetype="application/json")

    return response


def _get_no_op_response() -> Response:
    return Response(status="304 no-op")


@flask_app.route("/system_status", methods=["GET"])
def system_status() -> Response:
    """Get the system status and other information.

    in_simulation_mode is only accurate if ui_status_code is '009301eb-625c-4dc4-9e92-1a4d0762465f'

    mantarray_serial_number and mantarray_nickname are only accurate if ui_status_code is '8e24ef4d-2353-4e9d-aa32-4346126e73e3'
    """
    shared_values_dict = _get_values_from_process_monitor()
    current_software_version = get_current_software_version()
    expected_software_version = shared_values_dict.get("expected_software_version", current_software_version)
    if expected_software_version != current_software_version:
        return Response(
            status=f"520 Versions of Electron and Flask EXEs do not match. Expected: {expected_software_version}"
        )

    status = shared_values_dict["system_status"]
    status_dict = {
        "ui_status_code": str(SYSTEM_STATUS_UUIDS[status]),
        "is_stimulating": shared_values_dict["beta_2_mode"] and _is_stimulating_on_any_well(),
        "log_file_id": shared_values_dict["log_file_id"],
        # Tanner (7/1/20): this route may be called before process_monitor adds the following values to shared_values_dict, so default values are needed
        "in_simulation_mode": shared_values_dict.get("in_simulation_mode", False),
        "mantarray_serial_number": shared_values_dict.get("mantarray_serial_number", ""),
        "mantarray_nickname": shared_values_dict.get("mantarray_nickname", ""),
    }

    response = Response(json.dumps(status_dict), mimetype="application/json")

    return response


@flask_app.route("/latest_software_version", methods=["POST"])
def set_latest_software_version() -> Response:
    """Set the latest available software version."""
    try:
        version = request.args["version"]
        # check if version is a valid semantic version string. ValueError will be raised if not
        VersionInfo.parse(version)
    except KeyError:
        return Response(status="400 Version not specified")
    except ValueError:
        return Response(status="400 Invalid version string")

    comm_dict = {"communication_type": "set_latest_software_version", "version": version}

    response = queue_command_to_main(comm_dict)
    return response


@flask_app.route("/firmware_update_confirmation", methods=["POST"])
def firmware_update_confirmation() -> Response:
    """Confirm whether or not user wants to proceed with FW update."""
    if not _get_values_from_process_monitor()["beta_2_mode"]:
        return Response(status="403 Route cannot be called in beta 1 mode")
    update_accepted = request.args["update_accepted"] in ("true", "True")
    comm_dict = {"communication_type": "firmware_update_confirmation", "update_accepted": update_accepted}

    response = queue_command_to_main(comm_dict)
    return response


@flask_app.route("/set_mantarray_nickname", methods=["GET"])
def set_mantarray_nickname() -> Response:
    """Set the 'nickname' of the Mantarray device.

    This route will not overwrite an existing Mantarray Serial Number.
    """
    shared_values_dict = _get_values_from_process_monitor()
    max_num_bytes = SERIAL_COMM_NICKNAME_BYTES_LENGTH if shared_values_dict["beta_2_mode"] else 23

    nickname = request.args["nickname"]
    if len(nickname.encode("utf-8")) > max_num_bytes:
        return Response(status=f"400 Nickname exceeds {max_num_bytes} bytes")

    comm_dict = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": nickname,
    }
    response = queue_command_to_main(comm_dict)

    return response


@flask_app.route("/start_calibration", methods=["GET"])
def start_calibration() -> Response:
    """Start the calibration procedure on the Mantarray."""
    shared_values_dict = _get_values_from_process_monitor()
    if shared_values_dict["system_status"] == CALIBRATING_STATE:
        return _get_no_op_response()

    if shared_values_dict["system_status"] not in (CALIBRATION_NEEDED_STATE, CALIBRATED_STATE):
        return Response(status="403 Route cannot be called unless in calibration_needed or calibrated state")
    if shared_values_dict["beta_2_mode"]:
        if _are_stimulator_checks_running():
            return Response(status="403 Cannot calibrate while stimulator checks are running")
        if _is_stimulating_on_any_well():
            return Response(status="403 Cannot calibrate while stimulation is running")

    if shared_values_dict["beta_2_mode"]:
        comm_dict = {"communication_type": "calibration", "command": "run_calibration"}
    else:
        comm_dict = {"communication_type": "xem_scripts", "script_type": "start_calibration"}
    response = queue_command_to_main(comm_dict)

    return response


@flask_app.route("/start_stim_checks", methods=["POST"])
def start_stim_checks() -> Response:
    """Start the stimulator impedence checks on the Mantarray.

    Not available for Beta 1 instruments.
    """
    shared_values_dict = _get_values_from_process_monitor()
    if not shared_values_dict["beta_2_mode"]:
        return Response(status="403 Route cannot be called in beta 1 mode")
    if shared_values_dict["system_status"] != CALIBRATED_STATE:
        return Response(status="403 Route cannot be called unless in calibrated state")
    if _is_stimulating_on_any_well():
        return Response(status="403 Cannot perform stimulator checks while stimulation is running")
    if _are_stimulator_checks_running():
        return _get_no_op_response()

    request_body = request.get_json()
    try:
        well_indices = request_body["well_indices"]
    except Exception:
        return Response(status="400 Request body missing 'well_indices'")
    if not well_indices:
        return Response(status="400 No well indices given")

    # check if barcodes were manually entered and match
    barcode_dict: Dict[str, Any] = {}
    for barcode_type in ("plate_barcode", "stim_barcode"):
        barcode = request_body.get(barcode_type)
        barcode_dict.update({barcode_type: barcode})
        if isinstance(barcode, str):
            barcode_dict[f"{barcode_type}_is_from_scanner"] = _check_scanned_barcode_vs_user_value(
                barcode, barcode_type, shared_values_dict
            )
        else:
            barcode_dict[f"{barcode_type}_is_from_scanner"] = False

    response = queue_command_to_main(
        {
            "communication_type": "stimulation",
            "command": "start_stim_checks",
            "well_indices": [int(well_idx) for well_idx in well_indices],
            **barcode_dict,
        }
    )
    return response


@flask_app.route("/boot_up", methods=["GET"])
def boot_up() -> Response:
    """Initialize XEM then run start up script."""
    comm_dict = {"communication_type": "to_instrument", "command": "boot_up"}

    response = queue_command_to_main(comm_dict)

    return response


@flask_app.route("/get_recordings", methods=["GET"])
def get_recordings() -> Response:
    """Get list of recordings from root recordings directory."""
    try:
        recording_dir = _get_values_from_process_monitor()["config_settings"]["recording_directory"]
    except KeyError:
        return Response(status="400 No root recording directory was found")

    recording_info_list = get_info_of_recordings(recording_dir)
    response_dict = {"recordings_list": recording_info_list, "root_recording_path": recording_dir}

    return Response(json.dumps(response_dict), mimetype="application/json")


@flask_app.route("/start_data_analysis", methods=["POST"])
def run_mag_finding_analysis() -> Response:
    """Route recieves list of recording paths to run analysis on locally."""
    try:
        config_setting = _get_values_from_process_monitor()["config_settings"]
        recording_rootdir = config_setting["recording_directory"]
    except KeyError:
        return Response(status="400 Root directories were not found")

    recording_paths = [
        os.path.join(recording_rootdir, dirname) for dirname in request.get_json()["selected_recordings"]
    ]

    queue_command_to_main(
        {
            "communication_type": "mag_finding_analysis",
            "command": "start_mag_analysis",
            "recordings": recording_paths,
        }
    )

    return Response(status=204)


@flask_app.route("/update_settings", methods=["GET"])
def update_settings() -> Response:
    """Update the customer/user settings."""
    for arg in request.args:
        if arg not in VALID_CONFIG_SETTINGS:
            return Response(status=f"400 Invalid argument given: {arg}")
    try:
        _get_values_from_process_monitor()["user_creds"]
    except KeyError:
        return Response(status="400 User is not logged in")

    queue_command_to_main(
        {
            "communication_type": "update_user_settings",
            "content": convert_request_args_to_config_dict(request.args),
        }
    )

    return Response(status=204)


@flask_app.route("/update_recording_dir", methods=["GET"])
def update_recording_dir() -> Response:  # pragma: no cover
    rec_dir = request.args["recording_directory"]

    success = validate_recording_directory(rec_dir)

    if success:
        settings = {"recording_directory": rec_dir}
        queue_command_to_main({"communication_type": "update_user_settings", "content": settings})

    return Response(json.dumps({"success": success}), mimetype="application/json", status=200)


@flask_app.route("/login", methods=["GET"])
def login_user() -> Response:
    """Login user."""
    for arg in request.args:
        if arg not in VALID_CONFIG_SETTINGS:
            return Response(status=f"400 Invalid argument given: {arg}")

    try:
        auth_response = validate_user_credentials(request.args)
    except LoginFailedError as e:
        return Response(json.dumps(str(e)), status=f"401 {repr(e)}")
    except requests.exceptions.ConnectionError:  # pragma: no cover
        return Response(json.dumps({"err": "network"}), mimetype="application/json")

    queue_command_to_main(
        {
            "communication_type": "update_user_settings",
            "content": convert_request_args_to_config_dict(request.args),
        }
    )

    response = {"usage_quota": auth_response[1]} if auth_response is not None else auth_response
    return Response(json.dumps(response), mimetype="application/json")


def _is_recording() -> bool:
    current_system_status = _get_values_from_process_monitor()["system_status"]
    return current_system_status == RECORDING_STATE  # type: ignore  # mypy doesn't think this is a bool


def _get_stim_info_from_process_monitor() -> Dict[Any, Any]:
    return _get_values_from_process_monitor()["stimulation_info"]  # type: ignore


def _is_stimulating_on_any_well() -> bool:
    return any(_get_values_from_process_monitor()["stimulation_running"])


def _are_stimulator_checks_running() -> bool:
    stimulator_circuit_statuses = _get_values_from_process_monitor()["stimulator_circuit_statuses"]
    return any(
        status == StimulatorCircuitStatuses.CALCULATING.name.lower()
        for status in stimulator_circuit_statuses.values()
    )


def _are_initial_stimulator_checks_complete() -> bool:
    return bool(_get_values_from_process_monitor()["stimulator_circuit_statuses"])


def _are_any_stimulator_circuits_short() -> bool:
    stimulator_circuit_statuses = _get_values_from_process_monitor()["stimulator_circuit_statuses"]
    return any(
        status == StimulatorCircuitStatuses.SHORT.name.lower()
        for status in stimulator_circuit_statuses.values()
    )


@flask_app.route("/set_protocols", methods=["POST"])
def set_protocols() -> Response:
    """Set the stimulation protocols in hardware memory.

    Not available for Beta 1 instruments.
    """
    if not _get_values_from_process_monitor()["beta_2_mode"]:
        return Response(status="403 Route cannot be called in beta 1 mode")
    if _is_stimulating_on_any_well():
        return Response(status="403 Cannot change protocols while stimulation is running")
    system_status = _get_values_from_process_monitor()["system_status"]

    if system_status not in (CALIBRATED_STATE, BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE):
        return Response(status=f"403 Cannot change protocols while {system_status}")

    stim_info = json.loads(request.get_json()["data"])

    protocol_list = stim_info["protocols"]
    # make sure at least one protocol is given
    if not protocol_list:
        return Response(status="400 Protocol list empty")

    # validate protocols
    given_protocol_ids = set()
    for protocol in protocol_list:
        # make sure protocol ID is unique
        protocol_id = protocol["protocol_id"]
        if protocol_id in given_protocol_ids:
            return Response(status=f"400 Multiple protocols given with ID: {protocol_id}")

        given_protocol_ids.add(protocol_id)

        # validate stim type
        stim_type = protocol["stimulation_type"]
        if stim_type not in VALID_STIMULATION_TYPES:
            return Response(status=f"400 Protocol {protocol_id}, Invalid stimulation type: {stim_type}")

        # validate subprotocol dictionaries
        try:
            for idx, subprotocol in enumerate(protocol["subprotocols"]):
                validate_stim_subprotocol(subprotocol, stim_type, protocol_id, idx)

        except InvalidSubprotocolError as e:
            return Response(status=str(e))

    protocol_assignments_dict = stim_info["protocol_assignments"]
    # make sure protocol assignments are not missing any wells and do not contain any invalid wells
    all_well_names = set(
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx) for well_idx in range(24)
    )

    given_well_names = set(protocol_assignments_dict.keys())
    if missing_wells := all_well_names - given_well_names:
        return Response(status=f"400 Protocol assignments missing wells: {missing_wells}")
    if invalid_wells := given_well_names - all_well_names:
        return Response(status=f"400 Protocol assignments contain invalid wells: {invalid_wells}")
    # make sure all protocol IDs are valid and that no protocols are unassigned
    assigned_ids = set(pid for pid in protocol_assignments_dict.values() if pid)
    if missing_protocol_ids := given_protocol_ids - assigned_ids:
        return Response(status=f"400 Protocol assignments missing protocol IDs: {missing_protocol_ids}")
    if invalid_protocol_ids := assigned_ids - given_protocol_ids:
        return Response(
            status=f"400 Protocol assignments contain invalid protocol IDs: {sorted(invalid_protocol_ids)}"
        )

    queue_command_to_main(
        {"communication_type": "stimulation", "command": "set_protocols", "stim_info": stim_info}
    )
    # wait for process monitor to update stim info in shared values dictionary
    while _get_stim_info_from_process_monitor() != stim_info:
        sleep(0.1)

    return Response(json.dumps(stim_info), mimetype="application/json")


@flask_app.route("/set_stim_status", methods=["POST"])
def set_stim_status() -> Response:
    """Start or stop stimulation on hardware.

    Not available for Beta 1 instruments.
    """
    shared_values_dict = _get_values_from_process_monitor()
    if not shared_values_dict["beta_2_mode"]:
        return Response(status="403 Route cannot be called in beta 1 mode")

    try:
        stim_status = request.args["running"] in ("true", "True")
    except KeyError:
        return Response(status="400 Request missing 'running' parameter")

    if shared_values_dict["stimulation_info"] is None:
        return Response(status="406 Protocols have not been set")
    system_status = shared_values_dict["system_status"]
    if stim_status:
        if system_status not in (CALIBRATED_STATE, BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE):
            return Response(status=f"403 Cannot start stimulation while {system_status}")
        if not _are_initial_stimulator_checks_complete():
            return Response(
                status="403 Cannot start stimulation before initial stimulator circuit checks complete"
            )
        if _are_stimulator_checks_running():
            return Response(status="403 Cannot start stimulation while running stimulator circuit checks")
        if _are_any_stimulator_circuits_short():
            return Response(status="403 Cannot start stimulation when a stimulator has a short circuit")

    action_transition = (
        SystemActionTransitionStates.STARTING if stim_status else SystemActionTransitionStates.STOPPING
    )
    if (
        stim_status is _is_stimulating_on_any_well()
        or shared_values_dict["system_action_transitions"]["stimulation"] == action_transition
    ):
        return _get_no_op_response()

    response = queue_command_to_main(
        {"communication_type": "stimulation", "command": "set_stim_status", "status": stim_status}
    )
    return response


@flask_app.route("/start_recording", methods=["GET"])
def start_recording() -> Response:
    """Tell the FileWriter to begin recording data to file.

    Args:
        active_well_indices: [Optional, default=all 24] CSV of well indices to record from
        time_index: [Optional, int] microseconds since acquisition began to start the recording at. Defaults to when this command is received
    """
    shared_values_dict = _get_values_from_process_monitor()

    barcodes_to_check = ["plate_barcode"]
    if shared_values_dict["beta_2_mode"] and _is_stimulating_on_any_well():
        barcodes_to_check.append("stim_barcode")
    # check that all required params are given before validating
    for barcode_type in barcodes_to_check:
        if barcode_type not in request.args:
            return Response(status=f"400 Request missing '{barcode_type}' parameter")
    # validate params separately
    for barcode_type in barcodes_to_check:
        barcode = request.args[barcode_type]
        if error_message := check_barcode_for_errors(
            barcode, shared_values_dict["beta_2_mode"], barcode_type
        ):
            barcode_label = barcode_type.split("_")[0].title()
            return Response(status=f"400 {barcode_label} {error_message}")
    barcodes = {
        "plate_barcode": request.args["plate_barcode"],
        "stim_barcode": request.args.get("stim_barcode", NOT_APPLICABLE_H5_METADATA),
    }

    if _is_recording():
        return _get_no_op_response()

    # TODO remove this arg and don't store it in H5 files once Beta 1 is phased out
    is_hardware_test_recording = request.args.get("is_hardware_test_recording", True)
    if isinstance(is_hardware_test_recording, str):
        is_hardware_test_recording = is_hardware_test_recording.lower() == "true"
    if shared_values_dict.get("is_hardware_test_recording", False) and not is_hardware_test_recording:
        return Response(
            status="403 Cannot make standard recordings after previously making hardware test recordings. Server and board must both be restarted before making any more standard recordings"
        )

    if "active_well_indices" in request.args and not shared_values_dict["beta_2_mode"]:
        active_well_indices = [int(x) for x in request.args["active_well_indices"].split(",")]
    else:
        active_well_indices = list(range(24))

    time_index_str = request.args.get("time_index", None)

    if platemap := request.args.get("platemap"):
        platemap_info = json.loads(urllib.parse.unquote_plus(platemap))
    else:
        platemap_info = None

    comm_dict = _create_start_recording_command(
        shared_values_dict,
        recording_name=request.args.get("recording_name"),
        time_index=time_index_str,
        active_well_indices=active_well_indices,
        barcodes=barcodes,
        platemap_info=platemap_info,
        is_hardware_test_recording=is_hardware_test_recording,
        plate_barcode_entry_time=request.args.get("plate_barcode_entry_time"),
        stim_barcode_entry_time=request.args.get("stim_barcode_entry_time"),
    )

    to_main_queue = get_server_to_main_queue()
    to_main_queue.put_nowait(
        copy.deepcopy(comm_dict)
    )  # Eli (3/16/20): apparently when using multiprocessing.Queue you have to be careful when modifying values put into the queue because they might still be editable. So making a copy first

    # fixing values here for response, not for message to main
    for this_attr_name, this_attr_value in list(
        comm_dict["metadata_to_copy_onto_main_file_attributes"].items()
    ):
        if this_attr_name == "adc_offsets":
            continue
        if isinstance(this_attr_value, datetime):
            this_attr_value = this_attr_value.strftime("%Y-%m-%d %H:%M:%S.%f")
            comm_dict["metadata_to_copy_onto_main_file_attributes"][this_attr_name] = this_attr_value
        if isinstance(this_attr_value, UUID):
            this_attr_value = str(this_attr_value)
        del comm_dict["metadata_to_copy_onto_main_file_attributes"][this_attr_name]
        this_attr_name = str(this_attr_name)
        comm_dict["metadata_to_copy_onto_main_file_attributes"][this_attr_name] = this_attr_value
    response = Response(json.dumps(comm_dict), mimetype="application/json")
    return response


@flask_app.route("/stop_recording", methods=["GET"])
def stop_recording() -> Response:
    """Tell the FileWriter to stop recording data to disk.

    Supplies a specific time index that FileWriter should stop at, since there is a lag between what the user sees and what's actively streaming into FileWriter.


    Args:
        time_index: [Optional, int] microseconds since acquisition began to end the recording at. defaults to when this command is received
    """
    shared_values_dict = _get_values_from_process_monitor()

    timestamp_of_sample_idx_zero = _get_timestamp_of_acquisition_sample_index_zero(shared_values_dict)

    if not _is_recording():
        return _get_no_op_response()

    stop_time_index: Union[int, float]
    if "time_index" in request.args:
        stop_time_index = int(request.args["time_index"])
        if not shared_values_dict["beta_2_mode"]:
            stop_time_index /= MICROSECONDS_PER_CENTIMILLISECOND
    else:
        time_since_index_0 = datetime.utcnow() - timestamp_of_sample_idx_zero
        stop_time_index = time_since_index_0.total_seconds() * (
            MICRO_TO_BASE_CONVERSION if shared_values_dict["beta_2_mode"] else CENTIMILLISECONDS_PER_SECOND
        )

    comm_dict: Dict[str, Any] = {
        "communication_type": "recording",
        "command": "stop_recording",
        "timepoint_to_stop_recording_at": stop_time_index,
    }
    response = queue_command_to_main(comm_dict)
    return response


@flask_app.route("/update_recording_name", methods=["POST"])
def update_recording_name() -> Response:
    """Route updates recording name after stop recording."""
    shared_values_dict = _get_values_from_process_monitor()
    recording_dir = shared_values_dict["config_settings"]["recording_directory"]

    new_recording_name = request.args["new_name"].strip()
    snapshot_enabled = request.args["snapshot_enabled"] == "true"

    if not shared_values_dict["beta_2_mode"] and snapshot_enabled:
        return Response(status="403 Cannot run recording snapshot in Beta 1 mode")
    if not request.args.get("replace_existing") and os.path.exists(
        os.path.join(recording_dir, new_recording_name)
    ):
        return Response(status="403 Recording name already exists")

    request_body = request.get_json()

    comm = {
        "communication_type": "recording",
        "command": "update_recording_name",
        "new_name": new_recording_name,
        "default_name": request.args["default_name"],
        "snapshot_enabled": snapshot_enabled,
        "user_defined_metadata": request_body["user_defined_metadata"],
    }

    response = queue_command_to_main(comm)
    return response


@flask_app.route("/start_managed_acquisition", methods=["GET"])
def start_managed_acquisition() -> Response:
    """Begin "managed" data acquisition (AKA data streaming) on the Mantarray.

    Can be invoked by:
    """
    shared_values_dict = _get_values_from_process_monitor()

    plate_barcode = request.args.get("plate_barcode")
    if not plate_barcode:
        return Response(status="400 Request missing 'plate_barcode' parameter")
    if error_message := check_barcode_for_errors(
        plate_barcode, shared_values_dict["beta_2_mode"], "plate_barcode"
    ):
        return Response(status=f"400 Plate {error_message}")

    if not shared_values_dict["mantarray_serial_number"][0]:
        response = Response(status="406 Mantarray has not been assigned a Serial Number")
        return response
    if shared_values_dict["beta_2_mode"] and _are_stimulator_checks_running():
        return Response(status="403 Cannot start managed acquisition while stimulator checks are running")

    if shared_values_dict["system_status"] in (BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE):
        return _get_no_op_response()

    command = {**START_MANAGED_ACQUISITION_COMMUNICATION, "barcode": plate_barcode}
    response = queue_command_to_main(command)

    return response


@flask_app.route("/stop_managed_acquisition", methods=["GET"])
def stop_managed_acquisition() -> Response:
    """Stop "managed" data acquisition on the Mantarray."""
    shared_values_dict = _get_values_from_process_monitor()

    status = shared_values_dict["system_status"]

    if (
        status == CALIBRATED_STATE
        or shared_values_dict["system_action_transitions"]["live_view"]
        == SystemActionTransitionStates.STOPPING
    ):
        return _get_no_op_response()
    if status not in (BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE):
        return Response(status=f"403 Cannot stop managed acquisition while in {status} state")

    response = queue_command_to_main(dict(STOP_MANAGED_ACQUISITION_COMMUNICATION))
    return response


# Single "debug console" commands to send to XEM
@flask_app.route("/insert_xem_command_into_queue/set_mantarray_serial_number", methods=["GET"])
def set_mantarray_serial_number() -> Response:
    """Set the serial number of the Mantarray device.

    This serial number pertains to the Mantarray instrument itself. This is different than the Opal Kelly serial number which pertains only to the XEM.

    This route will overwrite an existing Mantarray Nickname if present.
    """
    serial_number = request.args["serial_number"]
    error_message = check_mantarray_serial_number(serial_number)
    if error_message:
        response = Response(status=f"400 {error_message}")
        return response

    comm_dict = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_serial_number",
        "mantarray_serial_number": serial_number,
    }
    response = queue_command_to_main(comm_dict)
    return response


@flask_app.route("/insert_xem_command_into_queue/initialize_board", methods=["GET"])
def queue_initialize_board() -> Response:
    """Queue up a command to initialize the XEM.

    Specified bit files should be in same directory as mantarray-
    flask.exe
    """
    bit_file_name = request.args.get("bit_file_name", None)
    allow_board_reinitialization = request.args.get("allow_board_reinitialization", False)
    if isinstance(allow_board_reinitialization, str):
        allow_board_reinitialization = allow_board_reinitialization == "True"
    comm_dict = {
        "communication_type": "debug_console",
        "command": "initialize_board",
        "bit_file_name": bit_file_name,
        "allow_board_reinitialization": allow_board_reinitialization,
        "suppress_error": True,
    }
    response = queue_command_to_instrument_comm(comm_dict)
    return response


@flask_app.route("/insert_xem_command_into_queue/activate_trigger_in", methods=["GET"])
def queue_activate_trigger_in() -> Response:
    """Queue up a command to activate a given trigger-in bit on the XEM."""
    ep_addr = int(request.args["ep_addr"], 0)
    bit = int(request.args["bit"], 0)
    comm_dict = {
        "communication_type": "debug_console",
        "command": "activate_trigger_in",
        "ep_addr": ep_addr,
        "bit": bit,
        "suppress_error": True,
    }
    response = queue_command_to_instrument_comm(comm_dict)
    return response


@flask_app.route("/insert_xem_command_into_queue/comm_delay", methods=["GET"])
def queue_comm_delay() -> Response:
    """Queue a command delay communication to the XEM for a period of time.

    Mainly to be used in XEM scripting when delays between commands are
    necessary.
    """
    num_milliseconds = int(request.args["num_milliseconds"])
    comm_dict = {
        "communication_type": "debug_console",
        "command": "comm_delay",
        "num_milliseconds": num_milliseconds,
        "suppress_error": True,
    }
    response = queue_command_to_instrument_comm(comm_dict)
    return response


@flask_app.route("/development/begin_hardware_script", methods=["GET"])
def dev_begin_hardware_script() -> Response:
    """Designate the beginning of a hardware script in flask log."""
    return Response(json.dumps({}), mimetype="application/json")


@flask_app.route("/development/end_hardware_script", methods=["GET"])
def dev_end_hardware_script() -> Response:
    """Designate the end of a hardware script in flask log."""
    return Response(json.dumps({}), mimetype="application/json")


@flask_app.route("/insert_xem_command_into_queue/get_num_words_fifo", methods=["GET"])
def queue_get_num_words_fifo() -> Response:
    """Queue up a command to set a wire-in value on the XEM."""
    comm_dict = {
        "communication_type": "debug_console",
        "command": "get_num_words_fifo",
        "suppress_error": True,
    }
    response = queue_command_to_instrument_comm(comm_dict)
    return response


@flask_app.route("/insert_xem_command_into_queue/set_device_id", methods=["GET"])
def queue_set_device_id() -> Response:
    """Queue up a command to set the device ID on the XEM.

    Do not use this route to set Mantarray Device Nicknames or Serial Numbers.

    This route should be used cautiously as it will overwrite an existing Mantarray serial number / ID stored in the XEM.
    """
    new_id = request.args["new_id"]
    comm_dict = {
        "communication_type": "debug_console",
        "command": "set_device_id",
        "new_id": new_id,
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/stop_acquisition", methods=["GET"])
def queue_stop_acquisition() -> Response:
    """Queue up a command to stop running data acquisition on the XEM."""
    comm_dict = {"communication_type": "debug_console", "command": "stop_acquisition", "suppress_error": True}

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/start_acquisition", methods=["GET"])
def queue_start_acquisition() -> Response:
    """Queue up a command to start running data acquisition on the XEM."""
    comm_dict = {
        "communication_type": "debug_console",
        "command": "start_acquisition",
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/get_serial_number", methods=["GET"])
def queue_get_serial_number() -> Response:
    """Queue up a command to stop running data acquisition on the XEM."""
    comm_dict = {
        "communication_type": "debug_console",
        "command": "get_serial_number",
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/get_device_id", methods=["GET"])
def queue_get_device_id() -> Response:
    """Queue up a command to get the device ID from the XEM."""
    comm_dict = {"communication_type": "debug_console", "command": "get_device_id", "suppress_error": True}

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/is_spi_running", methods=["GET"])
def queue_is_spi_running() -> Response:
    """Queue up a command to get SPI running status on the XEM."""
    comm_dict = {"communication_type": "debug_console", "command": "is_spi_running", "suppress_error": True}

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/read_from_fifo", methods=["GET"])
def queue_read_from_fifo() -> Response:
    """Queue up a command to read data from the XEM."""
    num_words_to_log = int(request.args["num_words_to_log"], 0)
    comm_dict = {
        "communication_type": "debug_console",
        "command": "read_from_fifo",
        "num_words_to_log": num_words_to_log,
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/set_wire_in", methods=["GET"])
def queue_set_wire_in() -> Response:
    """Queue up a command to set a wire-in value on the XEM."""
    ep_addr = int(request.args["ep_addr"], 0)
    value = int(request.args["value"], 0)
    mask = int(request.args["mask"], 0)
    comm_dict = {
        "communication_type": "debug_console",
        "command": "set_wire_in",
        "ep_addr": ep_addr,
        "value": value,
        "mask": mask,
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/xem_scripts", methods=["GET"])
def run_xem_script() -> Response:
    """Run a script of XEM commands created from an existing flask log."""
    script_type = request.args["script_type"]
    comm_dict = {"communication_type": "xem_scripts", "script_type": script_type}

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/read_wire_out", methods=["GET"])
def queue_read_wire_out() -> Response:
    """Queue up a command to read from wire out on the XEM.

    Takes an optional description message for commenting in the the log
    """
    ep_addr = int(request.args["ep_addr"], 0)
    comm_dict = {
        "communication_type": "debug_console",
        "command": "read_wire_out",
        "ep_addr": ep_addr,
        "suppress_error": True,
    }
    description = request.args.get("description", None)
    if description is not None:
        comm_dict["description"] = description

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/get_status", methods=["GET"])
def queue_get_status() -> Response:
    """Queue up a command to get instance attributes of FrontPanelBase object.

    Does not interact with a XEM. This route shouldn't be used if an
    attribute of a XEM is needed.
    """
    comm_dict = {"communication_type": "debug_console", "command": "get_status", "suppress_error": True}

    response = queue_command_to_instrument_comm(comm_dict)

    return response


def shutdown_server() -> None:
    """Stop / shutdown the Flask Server itself."""
    logger.info("Calling function to shut down Flask Server.")
    socketio.stop()
    # Tanner (6/20/21): SystemExit is raised here, so no lines after this will execute


@flask_app.route("/stop_server", methods=["GET"])
def stop_server() -> str:
    """Shut down Flask."""
    shutdown_server()
    # Tanner (6/20/21): SystemExit is raised inside the previous function call, so no lines after this will execute
    return "Server shutting down..."  # pragma: no cover


@flask_app.route("/shutdown", methods=["GET"])
def shutdown() -> Response:
    """Shutdown subprocesses then stop the server."""
    queue_command_to_main({"communication_type": "shutdown", "command": "hard_stop"})
    wait_for_subprocesses_to_stop()

    response = queue_command_to_main({"communication_type": "shutdown", "command": "shutdown_server"})
    return response


def wait_for_subprocesses_to_stop() -> None:
    while _get_values_from_process_monitor().get("subprocesses_running", False):
        sleep(SUBPROCESS_POLL_DELAY_SECONDS)


@flask_app.before_request
def before_request() -> Optional[Response]:
    rule = request.url_rule
    if rule is None:
        return None  # this will be caught and handled in after_request
    if "insert_xem_command_into_queue" in rule.rule or "boot_up" in rule.rule:
        shared_values_dict = _get_values_from_process_monitor()
        if shared_values_dict["beta_2_mode"]:
            return Response(status="403 Route cannot be called in beta 2 mode")
    return None


@flask_app.after_request
def after_request(response: Response) -> Response:
    """Log request and handle any necessary response clean up."""
    rule = request.url_rule
    response_json = response.get_json()
    if rule is None:
        response = Response(status="404 Route not implemented")
    elif response.status_code == 200:
        if "set_mantarray_nickname" in rule.rule:
            response_json["mantarray_nickname"] = get_redacted_string(
                len(response_json["mantarray_nickname"])
            )
        elif "start_recording" in rule.rule:
            mantarray_nickname = response_json["metadata_to_copy_onto_main_file_attributes"][
                str(MANTARRAY_NICKNAME_UUID)
            ]
            response_json["metadata_to_copy_onto_main_file_attributes"][
                str(MANTARRAY_NICKNAME_UUID)
            ] = get_redacted_string(len(mantarray_nickname))
        elif "login" in rule.rule:
            response_json["user_password"] = get_redacted_string(4)
        elif "get_recordings" in rule.rule:
            response_json["recordings_list"] = f"<{len(response_json['recordings_list'])} recordings found>"
            response_json["root_recording_path"] = redact_sensitive_info_from_path(
                response_json["root_recording_path"]
            )
    msg = "Response to HTTP Request in next log entry: "
    if response.status_code == 200:
        # Tanner (1/19/21): using json.dumps instead of an f-string here allows us to perform better testing of our log messages by loading the json string to a python dict
        msg += json.dumps(response_json)
    else:
        msg += response.status
    if not (rule is not None and "system_status" in rule.rule and response.status_code == 200):
        logger.info(msg)
    return response


class ServerManager:
    """Convenience class for managing Flask/SocketIO server."""

    def __init__(
        self,
        to_main_queue: Queue[Dict[str, Any]],
        queue_container: MantarrayQueueContainer,
        values_from_process_monitor: Optional[SharedValues] = None,
        port: int = DEFAULT_SERVER_PORT_NUMBER,
        logging_level: int = logging.INFO,
    ) -> None:
        global _the_server_manager
        if _the_server_manager is not None:
            # TODO Tanner (8/10/21): look into ways to avoid using this as a singleton
            raise ServerManagerSingletonAlreadySetError()

        self.queue_container = queue_container
        self._to_main_queue = to_main_queue
        self._port = port
        self._logging_level = logging_level

        # tests might not pass in a value for this, so just use a regular dict in that case
        self._values_from_process_monitor: Union[Dict[str, Any], SharedValues] = (
            values_from_process_monitor or dict()  # type: ignore
        )

        _the_server_manager = self

    def get_port_number(self) -> int:
        return self._port

    def get_queue_to_main(self) -> Queue[Dict[str, Any]]:
        return self._to_main_queue

    def get_values_from_process_monitor(self) -> Dict[str, Any]:
        """Get an immutable copy of the values."""
        if isinstance(self._values_from_process_monitor, SharedValues):
            copied_values = self._values_from_process_monitor.deepcopy()
        else:
            # tests might use a regular dict, so keeping this here
            copied_values = deepcopy(self._values_from_process_monitor)
        immutable_version = immutabledict(copied_values)
        return immutable_version  # type: ignore

    def get_logging_level(self) -> int:
        return self._logging_level

    def check_port(self) -> None:
        port = self._port
        if is_port_in_use(port):
            raise LocalServerPortAlreadyInUseError(port)

    def shutdown_server(self) -> None:
        """Shutdown the Flask/SocketIO server."""
        logger.info("Calling /stop_server")
        try:
            r = requests.get(f"{get_api_endpoint()}stop_server")
        except requests.exceptions.ConnectionError as e:
            logger.info(f"Server successfully shutting down: {repr(e)}")
        else:
            logger.error(f"Unknown issue, /stop_server returned a response: {r.json()}")
        clear_the_server_manager()

    def drain_all_queues(self) -> Dict[str, Any]:
        queue_items = dict()

        queue_items["to_main"] = drain_queue(self._to_main_queue)
        queue_items["outgoing_data"] = drain_queue(self.queue_container.to_websocket)
        return queue_items
