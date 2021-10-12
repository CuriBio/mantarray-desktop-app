# -*- coding: utf-8 -*-
"""Python Flask Server controlling Mantarray.

Custom HTTP Error Codes:

* 304 - Call to /set_stim_status with the current stim status (no updates will be made to status)
* 400 - Call to /start_recording with invalid or missing barcode parameter
* 400 - Call to /set_mantarray_nickname with invalid nickname parameter
* 400 - Call to /update_settings with unexpected argument, invalid account UUID, or a recording directory that doesn't exist
* 400 - Call to /insert_xem_command_into_queue/set_mantarray_serial_number with invalid serial_number parameter
* 400 - Call to /set_magnetometer_config with invalid configuration dict
* 400 - Call to /set_magnetometer_config with invalid or missing sampling period
* 400 - Call to /set_protocols with an invalid protocol or protocol assignments
* 400 - Call to /set_stim_status with missing 'running' status
* 403 - Call to /start_recording with is_hardware_test_recording=False after calling route with is_hardware_test_recording=True (default value)
* 403 - Call to any /insert_xem_command_into_queue/* route when in Beta 2 mode
* 403 - Call to /boot_up when in Beta 2 mode
* 403 - Call to /set_magnetometer_config when in Beta 1 mode
* 403 - Call to /set_magnetometer_config while data is streaming in Beta 2 mode
* 403 - Call to /set_magnetometer_config before instrument finishes initializing in Beta 2 mode
* 403 - Call to /set_protocols when in Beta 1 mode
* 403 - Call to /set_protocols while stimulation is running
* 403 - Call to /set_stim_status when in Beta 1 mode
* 404 - Route not implemented
* 406 - Call to /set_stim_status before protocol is set
* 406 - Call to /start_managed_acquisition before magnetometer configuration is set
* 406 - Call to /start_managed_acquisition when Mantarray device does not have a serial number assigned to it
* 406 - Call to /start_recording before customer_account_uuid and user_account_uuid are set
* 520 - Call to /system_status when Electron and Flask EXE versions don't match
"""
from __future__ import annotations

import copy
from copy import deepcopy
import datetime
import json
import logging
import os
from queue import Queue
import threading
from time import sleep
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple
from typing import Union
from uuid import UUID

from eventlet.queue import LightQueue
from flask import Flask
from flask import request
from flask import Response
from flask_cors import CORS
from flask_socketio import SocketIO
from immutabledict import immutabledict
from mantarray_file_manager import ADC_GAIN_SETTING_UUID
from mantarray_file_manager import BACKEND_LOG_UUID
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import BOOTUP_COUNTER_UUID
from mantarray_file_manager import COMPUTER_NAME_HASH_UUID
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import MAGNETOMETER_CONFIGURATION_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import METADATA_UUID_DESCRIPTIONS
from mantarray_file_manager import PCB_SERIAL_NUMBER_UUID
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import REFERENCE_VOLTAGE_UUID
from mantarray_file_manager import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_file_manager import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
from mantarray_file_manager import TAMPER_FLAG_UUID
from mantarray_file_manager import TISSUE_SAMPLING_PERIOD_UUID
from mantarray_file_manager import TOTAL_WORKING_HOURS_UUID
from mantarray_file_manager import USER_ACCOUNT_ID_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_BEGINNING_RECORDING_UUID
from mantarray_file_manager import XEM_SERIAL_NUMBER_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import requests
from stdlib_utils import drain_queue
from stdlib_utils import is_port_in_use
from stdlib_utils import put_log_message_into_queue

from .constants import BUFFERING_STATE
from .constants import COMPILED_EXE_BUILD_TIMESTAMP
from .constants import CURRENT_SOFTWARE_VERSION
from .constants import DEFAULT_SERVER_PORT_NUMBER
from .constants import GENERIC_24_WELL_DEFINITION
from .constants import INSTRUMENT_INITIALIZING_STATE
from .constants import LIVE_VIEW_ACTIVE_STATE
from .constants import MICRO_TO_BASE_CONVERSION
from .constants import MICROSECONDS_PER_MILLISECOND
from .constants import RECORDING_STATE
from .constants import REFERENCE_VOLTAGE
from .constants import SERIAL_COMM_DEFAULT_DATA_CHANNEL
from .constants import SERIAL_COMM_METADATA_BYTES_LENGTH
from .constants import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from .constants import SERVER_INITIALIZING_STATE
from .constants import SERVER_READY_STATE
from .constants import START_MANAGED_ACQUISITION_COMMUNICATION
from .constants import STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
from .constants import STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS
from .constants import STIM_MAX_PULSE_DURATION_MICROSECONDS
from .constants import STOP_MANAGED_ACQUISITION_COMMUNICATION
from .constants import SUBPROCESS_POLL_DELAY_SECONDS
from .constants import SYSTEM_STATUS_UUIDS
from .constants import VALID_CONFIG_SETTINGS
from .exceptions import ImproperlyFormattedCustomerAccountUUIDError
from .exceptions import ImproperlyFormattedUserAccountUUIDError
from .exceptions import LocalServerPortAlreadyInUseError
from .exceptions import RecordingFolderDoesNotExistError
from .exceptions import ServerManagerNotInitializedError
from .exceptions import ServerManagerSingletonAlreadySetError
from .ok_comm import check_mantarray_serial_number
from .queue_container import MantarrayQueueContainer
from .utils import check_barcode_for_errors
from .utils import convert_request_args_to_config_dict
from .utils import get_current_software_version
from .utils import get_redacted_string
from .utils import validate_magnetometer_config_keys
from .utils import validate_settings


logger = logging.getLogger(__name__)
os.environ[
    "FLASK_ENV"
] = "DEVELOPMENT"  # this removes warnings about running the Werkzeug server (which is not meant for high volume requests, but should be fine for intra-PC communication from a single client)
flask_app = (
    Flask(  # pylint: disable=invalid-name # yes, this is intentionally a global variable, not a constant
        __name__
    )
)
CORS(flask_app)
socketio = SocketIO(flask_app)

_the_server_manager: Optional[  # pylint: disable=invalid-name # Eli (11/3/20) yes, this is intentionally a global variable, not a constant. This is the current best guess at how to allow Flask routes to access some info they need
    "ServerManager"
] = None


def clear_the_server_manager() -> None:
    global _the_server_manager  # pylint:disable=global-statement,invalid-name # Eli (12/8/20) this is deliberately setting a global
    _the_server_manager = None


def get_the_server_manager() -> "ServerManager":
    """Return the global instance."""
    if _the_server_manager is None:
        raise ServerManagerNotInitializedError(
            "This function should not be called when the ServerManager is None and hasn't been initialized yet."
        )
    return _the_server_manager


def get_server_to_main_queue() -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
    Dict[str, Any]
]:
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
    return (
        "http",
        "127.0.0.1",
        port_number,
    )


def get_api_endpoint() -> str:
    protocol, host, port = get_server_address_components()
    return f"{protocol}://{host}:{port}/"


def _get_values_from_process_monitor() -> Dict[str, Any]:
    return get_the_server_manager().get_values_from_process_monitor()


def queue_command_to_instrument_comm(comm_dict: Dict[str, Any]) -> Response:
    """Queue command to send to InstrumentCommProcess and return response.

    This is used by the test suite, so is not designated as private in
    order to make pylint happier.
    """
    to_instrument_comm_queue = (
        get_the_server_manager().queue_container().get_communication_to_instrument_comm_queue(0)
    )
    comm_dict = dict(comm_dict)  # make a mutable version to pass into ok_comm
    to_instrument_comm_queue.put_nowait(comm_dict)
    response = Response(json.dumps(comm_dict), mimetype="application/json")

    return response


def queue_command_to_main(comm_dict: Dict[str, Any]) -> Response:
    """Queue command to send to the main thread and return response.

    This is used by the test suite, so is not designated as private in
    order to make pylint happier.
    """
    to_main_queue = get_server_to_main_queue()

    comm_dict = dict(
        copy.deepcopy(comm_dict)
    )  # Eli (12/8/20): make a copy since sometimes this dictionary can be mutated after the communication gets passed elsewhere. This is relevant since this is a thread queue. Queues between true processes get pickled and in essence already get copied
    # Eli (12/8/20): immutable dicts cannot be JSON serialized, so make a regular dict copy
    to_main_queue.put_nowait(comm_dict)
    response = Response(json.dumps(comm_dict), mimetype="application/json")

    return response


def _get_timestamp_of_acquisition_sample_index_zero() -> datetime.datetime:  # pylint:disable=invalid-name # yeah, it's kind of long, but Eli (2/27/20) doesn't know a good way to shorten it
    shared_values_dict = _get_values_from_process_monitor()
    timestamp_of_sample_idx_zero: datetime.datetime = shared_values_dict[
        "utc_timestamps_of_beginning_of_data_acquisition"
    ][
        0
    ]  # board index 0 hardcoded for now
    return timestamp_of_sample_idx_zero


def _check_scanned_barcode_vs_user_value(barcode: str) -> bool:
    board_idx = 0  # board index 0 hardcoded for now
    shared_values_dict = _get_values_from_process_monitor()
    if "barcodes" not in shared_values_dict:
        # Tanner (1/11/21): Guard against edge case where start_recording route is called before a scanned barcode is stored since this can take up to 15 seconds
        return False
    result: bool = shared_values_dict["barcodes"][board_idx]["plate_barcode"] == barcode
    return result


@flask_app.route("/system_status", methods=["GET"])
def system_status() -> Response:
    """Get the system status and other information.

    in_simulation_mode is only accurate if ui_status_code is '009301eb-625c-4dc4-9e92-1a4d0762465f'

    mantarray_serial_number and mantarray_nickname are only accurate if ui_status_code is '8e24ef4d-2353-4e9d-aa32-4346126e73e3'

    Can be invoked by: curl http://localhost:4567/system_status
    """
    shared_values_dict = _get_values_from_process_monitor()
    current_software_version = get_current_software_version()
    expected_software_version = shared_values_dict.get("expected_software_version", current_software_version)
    if expected_software_version != current_software_version:
        return Response(status="520 Versions of Electron and Flask EXEs do not match")

    board_idx = 0
    status = shared_values_dict["system_status"]
    status_dict = {
        "ui_status_code": str(SYSTEM_STATUS_UUIDS[status]),
        # Tanner (7/1/20): this route may be called before process_monitor adds the following values to shared_values_dict, so default values are needed
        "in_simulation_mode": shared_values_dict.get("in_simulation_mode", False),
        "mantarray_serial_number": shared_values_dict.get("mantarray_serial_number", ""),
        "mantarray_nickname": shared_values_dict.get("mantarray_nickname", ""),
    }
    if (
        "barcodes" in shared_values_dict
        and shared_values_dict["barcodes"][board_idx]["frontend_needs_barcode_update"]
    ):
        status_dict["plate_barcode"] = shared_values_dict["barcodes"][board_idx]["plate_barcode"]
        status_dict["barcode_status"] = str(shared_values_dict["barcodes"][board_idx]["barcode_status"])
        queue_command_to_main(
            {
                "communication_type": "barcode_read_receipt",
                "board_idx": board_idx,
            }
        )

    response = Response(json.dumps(status_dict), mimetype="application/json")

    return response


@flask_app.route("/set_mantarray_nickname", methods=["GET"])
def set_mantarray_nickname() -> Response:
    """Set the 'nickname' of the Mantarray device.

    This route will not overwrite an existing Mantarray Serial Number.

    Can be invoked by: curl http://localhost:4567/set_mantarray_nickname?nickname=My%20Mantarray
    """
    shared_values_dict = _get_values_from_process_monitor()
    max_num_bytes = SERIAL_COMM_METADATA_BYTES_LENGTH if shared_values_dict["beta_2_mode"] else 23

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
    """Start the calibration procedure on the Mantarray.

    Can be invoked by:

    `curl http://localhost:4567/start_calibration`
    """
    comm_dict = {
        "communication_type": "xem_scripts",
        "script_type": "start_calibration",
    }

    response = queue_command_to_main(comm_dict)

    return response


@flask_app.route("/boot_up", methods=["GET"])
def boot_up() -> Response:
    """Initialize XEM then run start up script.

    Can be invoked by: curl http://localhost:4567/boot_up
    """
    comm_dict = {
        "communication_type": "to_instrument",
        "command": "boot_up",
    }

    response = queue_command_to_main(comm_dict)

    return response


@flask_app.route("/update_settings", methods=["GET"])
def update_settings() -> Response:
    """Update the user settings.

    Can be invoked by: curl http://localhost:4567/update_settings?customer_account_uuid=<UUID>&user_account_uuid=<UUID>&recording_directory=recording_dir
    """
    for arg in request.args:
        if arg not in VALID_CONFIG_SETTINGS:
            response = Response(status=f"400 Invalid argument given: {arg}")
            return response

    try:
        validate_settings(request.args)
    except (
        ImproperlyFormattedCustomerAccountUUIDError,
        ImproperlyFormattedUserAccountUUIDError,
        RecordingFolderDoesNotExistError,
    ) as e:
        response = Response(status=f"400 {repr(e)}")
        return response

    queue_command_to_main(
        {
            "communication_type": "update_shared_values_dictionary",
            "content": convert_request_args_to_config_dict(request.args),
        }
    )
    response = Response(json.dumps(request.args), mimetype="application/json")
    return response


@flask_app.route("/set_magnetometer_config", methods=["POST"])
def set_magnetometer_config() -> Response:
    """Set the magnetometer configuration on a Beta 2 Mantarray.

    Not available for Beta 1 instruments.

    Can be invoked by: curl -d '<magnetometer configuration as json>' -H 'Content-Type: application/json' -X POST http://localhost:4567/set_magnetometer_config
    """
    # Tanner (6/3/21): could eventually separate out setting the sampling period into its own route if needed
    shared_values_dict = _get_values_from_process_monitor()
    if not shared_values_dict["beta_2_mode"]:
        return Response(status="403 Route cannot be called in beta 1 mode")
    if _is_data_streaming():
        return Response(status="403 Magnetometer Configuration cannot be changed while data is streaming")
    if not _is_instrument_initialized():
        return Response(
            status="403 Magnetometer Configuration cannot be set until instrument finishes initializing"
        )

    # load configuration
    magnetometer_config_dict_json = request.get_json()
    magnetometer_config_dict = json.loads(
        magnetometer_config_dict_json, object_hook=_fix_magnetometer_config_dict_keys
    )
    # validate sampling period
    try:
        sampling_period = magnetometer_config_dict["sampling_period"]
    except KeyError:
        return Response(status="400 Sampling period not specified")
    if sampling_period % MICROSECONDS_PER_MILLISECOND != 0:
        return Response(status=f"400 Invalid sampling period {sampling_period}")
    # validate configuration dictionary
    num_wells = 24
    error_msg = validate_magnetometer_config_keys(
        magnetometer_config_dict["magnetometer_config"], 1, num_wells + 1
    )
    if error_msg:
        return Response(status=f"400 {error_msg}")

    # make sure default channel is enabled
    for module_dict in magnetometer_config_dict["magnetometer_config"].values():
        module_dict[SERIAL_COMM_DEFAULT_DATA_CHANNEL] = True

    queue_command_to_main(
        {
            "communication_type": "set_magnetometer_config",
            "magnetometer_config_dict": magnetometer_config_dict,
        }
    )

    return Response(magnetometer_config_dict_json, mimetype="application/json")


def _fix_magnetometer_config_dict_keys(magnetometer_config_dict: Dict[str, Any]) -> Dict[Any, Any]:
    fixed_dict = {_fix_json_key(k): v for k, v in magnetometer_config_dict.items()}
    return dict(sorted(fixed_dict.items()))


def _fix_json_key(key: str) -> Union[int, str]:
    try:
        return int(key)
    except ValueError:
        return key


def _is_data_streaming() -> bool:
    current_system_status = _get_values_from_process_monitor()["system_status"]
    return current_system_status in (BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE)


def _is_instrument_initialized() -> bool:
    current_system_status = _get_values_from_process_monitor()["system_status"]
    return current_system_status not in (
        SERVER_INITIALIZING_STATE,
        SERVER_READY_STATE,
        INSTRUMENT_INITIALIZING_STATE,
    )


def _get_stim_info_from_process_monitor() -> Dict[Any, Any]:
    return _get_values_from_process_monitor()["stimulation_info"]  # type: ignore


@flask_app.route("/set_protocols", methods=["POST"])
def set_protocols() -> Response:
    # pylint: disable=too-many-return-statements  # Tanner (8/9/21): lots of error codes that can be returned here
    """Set the stimulation protocols in hardware memory.

    Not available for Beta 1 instruments.

    Can be invoked by: curl -d '<stimulation protocol as json>' -H 'Content-Type: application/json' -X POST http://localhost:4567/set_protocols
    """
    shared_values_dict = _get_values_from_process_monitor()
    if not shared_values_dict["beta_2_mode"]:
        return Response(status="403 Route cannot be called in beta 1 mode")
    if shared_values_dict["stimulation_running"]:
        return Response(status="403 Cannot change protocol while stimulation is running")

    stim_info = json.loads(request.get_json()["data"])

    protocol_list = stim_info["protocols"]
    # make sure at least one protocol is given
    if not protocol_list:
        return Response(status="400 Protocol list empty")
    # validate protocols
    protocol_ids = set()
    for protocol in protocol_list:
        # make sure protocol ID is unique
        if protocol["protocol_id"] in protocol_ids:
            return Response(status=f"400 Multiple protocols given with ID: {protocol['protocol_id']}")
        protocol_ids.add(protocol["protocol_id"])
        # validate stim type
        if protocol["stimulation_type"] not in ("C", "V"):
            return Response(status=f"400 Invalid stimulation type: {protocol['stimulation_type']}")
        max_abs_charge = (
            STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS
            if protocol["stimulation_type"] == "V"
            else STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
        )
        charge_unit = "mV" if protocol["stimulation_type"] == "V" else "µA"
        # validate subprotocol dictionaries
        total_protocol_dur_microsecs = 0
        for subprotocol in protocol["subprotocols"]:
            # subprotocol components
            if subprotocol["phase_one_duration"] <= 0:
                return Response(status=f"400 Invalid phase one duration: {subprotocol['phase_one_duration']}")
            if subprotocol["interphase_interval"] < 0:
                return Response(
                    status=f"400 Invalid interphase interval: {subprotocol['interphase_interval']}"
                )
            if subprotocol["phase_two_duration"] < 0:
                return Response(status=f"400 Invalid phase two duration: {subprotocol['phase_two_duration']}")
            if abs(int(subprotocol["phase_one_charge"])) > max_abs_charge:
                return Response(
                    status=f"400 Invalid phase one charge: {subprotocol['phase_one_charge']} {charge_unit}"
                )
            if abs(int(subprotocol["phase_two_charge"])) > max_abs_charge:
                return Response(
                    status=f"400 Invalid phase two charge: {subprotocol['phase_two_charge']} {charge_unit}"
                )
            # delay before repeating subprotocol
            if subprotocol["repeat_delay_interval"] < 0:
                return Response(
                    status=f"400 Invalid repeat delay interval: {subprotocol['repeat_delay_interval']}"
                )
            # make sure subprotocol duration (not including period after pulse) is not too large unless it is a delay
            single_pulse_dur_microsecs = (
                subprotocol["phase_one_duration"]
                + subprotocol["phase_two_duration"]
                + subprotocol["interphase_interval"]
            )
            if (
                subprotocol["interphase_interval"] > 0 or subprotocol["phase_two_duration"] > 0
            ) and single_pulse_dur_microsecs > STIM_MAX_PULSE_DURATION_MICROSECONDS:
                return Response(status="400 Pulse duration too long")
            # make sure subprotocol is set to run for at least one full pulse
            if subprotocol["total_active_duration"] * int(1e3) < single_pulse_dur_microsecs:
                return Response(status="400 Total active duration less than the duration of the subprotocol")
            # add total time for running this subprotocol to total time of protocol
            total_protocol_dur_microsecs += subprotocol["total_active_duration"]
    # make sure protocol assignments are not missing any wells and do not contain any invalid wells
    protocol_assignments_dict = stim_info["protocol_assignments"]
    expected_well_names = set(
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx) for well_idx in range(24)
    )
    actual_well_names = set(protocol_assignments_dict.keys())
    for well_name in expected_well_names:
        if well_name not in protocol_assignments_dict:
            return Response(status=f"400 Protocol assignments missing well {well_name}")
        actual_well_names.remove(well_name)
    if len(actual_well_names) > 0:
        return Response(status=f"400 Protocol assignments contain invalid well: {actual_well_names.pop()}")
    # make sure all protocol IDs are valid and that no protocols are unassigned
    assigned_ids = set(protocol_assignments_dict.values())
    if None in assigned_ids:
        assigned_ids.remove(None)  # remove since checking for wells with not assignment is unnecessary
    for protocol_id in protocol_ids:
        if protocol_id not in assigned_ids:
            return Response(status=f"400 Protocol assignments missing protocol ID: {protocol_id}")
        assigned_ids.remove(protocol_id)
    if len(assigned_ids) > 0:
        return Response(status=f"400 Protocol assignments contain invalid protocol ID: {assigned_ids.pop()}")

    queue_command_to_main(
        {
            "communication_type": "stimulation",
            "command": "set_protocols",
            "stim_info": stim_info,
        }
    )

    # wait for process monitor to update stim info in shared values dictionary
    while _get_stim_info_from_process_monitor() != stim_info:
        sleep(0.1)

    return Response(json.dumps(stim_info), mimetype="application/json")


@flask_app.route("/set_stim_status", methods=["POST"])
def set_stim_status() -> Response:
    """Start or stop stimulation on hardware.

    Not available for Beta 1 instruments.

    Can be invoked by: curl -X POST http://localhost:4567/set_stim_status?running=true
    """
    shared_values_dict = _get_values_from_process_monitor()
    if not shared_values_dict["beta_2_mode"]:
        return Response(status="403 Route cannot be called in beta 1 mode")

    try:
        status = request.args["running"] in ("true", "True")
    except KeyError:
        return Response(status="400 Request missing 'running' parameter")

    if shared_values_dict["stimulation_info"] is None:
        return Response(status="406 Protocols have not been set")
    if status is shared_values_dict["stimulation_running"]:
        return Response(status="304 Status not updated")

    response = queue_command_to_main(
        {
            "communication_type": "stimulation",
            "command": "set_stim_status",
            "status": status,
        }
    )
    return response


@flask_app.route("/start_recording", methods=["GET"])
def start_recording() -> Response:
    """Tell the FileWriter to begin recording data to disk.

    Can be invoked by: curl http://localhost:4567/start_recording
    curl http://localhost:4567/start_recording?active_well_indices=2,5,9&barcode=MA200440001&time_index=960&is_hardware_test_recording=True

    Args:
        active_well_indices: [Optional, default=all 24] CSV of well indices to record from
        time_index: [Optional, int] centimilliseconds since acquisition began to start the recording at. Defaults to when this command is received
    """
    board_idx = 0

    if "barcode" not in request.args:
        response = Response(status="400 Request missing 'barcode' parameter")
        return response
    barcode = request.args["barcode"]
    error_message = check_barcode_for_errors(barcode)
    if error_message:
        response = Response(status=f"400 {error_message}")
        return response

    shared_values_dict = _get_values_from_process_monitor()
    if not shared_values_dict["config_settings"]["Customer Account ID"]:
        response = Response(status="406 Customer Account ID has not yet been set")
        return response
    if not shared_values_dict["config_settings"]["User Account ID"]:
        response = Response(status="406 User Account ID has not yet been set")
        return response

    is_hardware_test_recording = request.args.get("is_hardware_test_recording", True)
    if isinstance(is_hardware_test_recording, str):
        is_hardware_test_recording = is_hardware_test_recording not in (
            "False",
            "false",
        )

    if shared_values_dict.get("is_hardware_test_recording", False) and not is_hardware_test_recording:
        response = Response(
            status="403 Cannot make standard recordings after previously making hardware test recordings. Server and board must both be restarted before making any more standard recordings"
        )
        return response
    timestamp_of_sample_idx_zero = _get_timestamp_of_acquisition_sample_index_zero()

    begin_timepoint: Union[int, float]
    timestamp_of_begin_recording = datetime.datetime.utcnow()
    if "time_index" in request.args:
        begin_timepoint = int(request.args["time_index"])
    else:
        time_since_index_0 = timestamp_of_begin_recording - timestamp_of_sample_idx_zero
        begin_timepoint = time_since_index_0.total_seconds() * (
            MICRO_TO_BASE_CONVERSION if shared_values_dict["beta_2_mode"] else CENTIMILLISECONDS_PER_SECOND
        )

    are_barcodes_matching = _check_scanned_barcode_vs_user_value(barcode)

    comm_dict: Dict[str, Any] = {
        "communication_type": "recording",
        "command": "start_recording",
        "is_hardware_test_recording": is_hardware_test_recording,
        "metadata_to_copy_onto_main_file_attributes": {
            BACKEND_LOG_UUID: shared_values_dict["log_file_uuid"],
            COMPUTER_NAME_HASH_UUID: shared_values_dict["computer_name_hash"],
            HARDWARE_TEST_RECORDING_UUID: is_hardware_test_recording,
            UTC_BEGINNING_DATA_ACQUISTION_UUID: timestamp_of_sample_idx_zero,
            START_RECORDING_TIME_INDEX_UUID: begin_timepoint,
            UTC_BEGINNING_RECORDING_UUID: timestamp_of_begin_recording,
            CUSTOMER_ACCOUNT_ID_UUID: shared_values_dict["config_settings"]["Customer Account ID"],
            USER_ACCOUNT_ID_UUID: shared_values_dict["config_settings"]["User Account ID"],
            SOFTWARE_BUILD_NUMBER_UUID: COMPILED_EXE_BUILD_TIMESTAMP,
            SOFTWARE_RELEASE_VERSION_UUID: CURRENT_SOFTWARE_VERSION,
            MAIN_FIRMWARE_VERSION_UUID: shared_values_dict["main_firmware_version"][board_idx],
            MANTARRAY_SERIAL_NUMBER_UUID: shared_values_dict["mantarray_serial_number"][board_idx],
            MANTARRAY_NICKNAME_UUID: shared_values_dict["mantarray_nickname"][board_idx],
            PLATE_BARCODE_UUID: barcode,
            BARCODE_IS_FROM_SCANNER_UUID: are_barcodes_matching,
        },
        "timepoint_to_begin_recording_at": begin_timepoint,
    }
    if shared_values_dict["beta_2_mode"]:
        instrument_metadata = shared_values_dict["instrument_metadata"][board_idx]
        magnetometer_config_dict = shared_values_dict["magnetometer_config_dict"]
        comm_dict["metadata_to_copy_onto_main_file_attributes"].update(
            {
                BOOTUP_COUNTER_UUID: instrument_metadata[BOOTUP_COUNTER_UUID],
                TOTAL_WORKING_HOURS_UUID: instrument_metadata[TOTAL_WORKING_HOURS_UUID],
                TAMPER_FLAG_UUID: instrument_metadata[TAMPER_FLAG_UUID],
                PCB_SERIAL_NUMBER_UUID: instrument_metadata[PCB_SERIAL_NUMBER_UUID],
                TISSUE_SAMPLING_PERIOD_UUID: magnetometer_config_dict["sampling_period"],
                MAGNETOMETER_CONFIGURATION_UUID: magnetometer_config_dict["magnetometer_config"],
            }
        )
    else:
        adc_offsets: Dict[int, Dict[str, int]]
        if is_hardware_test_recording:
            adc_offsets = dict()
            for well_idx in range(24):
                adc_offsets[well_idx] = {
                    "construct": 0,
                    "ref": 0,
                }
        else:
            adc_offsets = shared_values_dict["adc_offsets"]
        comm_dict["metadata_to_copy_onto_main_file_attributes"].update(
            {
                SLEEP_FIRMWARE_VERSION_UUID: shared_values_dict["sleep_firmware_version"][board_idx],
                XEM_SERIAL_NUMBER_UUID: shared_values_dict["xem_serial_number"][board_idx],
                REFERENCE_VOLTAGE_UUID: REFERENCE_VOLTAGE,
                ADC_GAIN_SETTING_UUID: shared_values_dict["adc_gain"],
                "adc_offsets": adc_offsets,
            }
        )

    # Tanner (6/11/21): Using magnetometer config to implicitly specify the active well indices in beta 2 mode
    if shared_values_dict["beta_2_mode"]:
        magnetometer_config = shared_values_dict["magnetometer_config_dict"]["magnetometer_config"]
        comm_dict["active_well_indices"] = [
            SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id]
            for module_id, module_config in magnetometer_config.items()
            if any(module_config.values())
        ]
    elif "active_well_indices" in request.args:
        comm_dict["active_well_indices"] = [int(x) for x in request.args["active_well_indices"].split(",")]
    else:
        comm_dict["active_well_indices"] = list(range(24))

    to_main_queue = get_server_to_main_queue()
    to_main_queue.put_nowait(
        copy.deepcopy(comm_dict)
    )  # Eli (3/16/20): apparently when using multiprocessing.Queue you have to be careful when modifying values put into the queue because they might still be editable. So making a copy first
    for this_attr_name, this_attr_value in list(
        comm_dict["metadata_to_copy_onto_main_file_attributes"].items()
    ):
        if this_attr_name == "adc_offsets":
            continue
        if METADATA_UUID_DESCRIPTIONS[this_attr_name].startswith("UTC Timestamp"):
            this_attr_value = this_attr_value.strftime("%Y-%m-%dT%H:%M:%S.%f")
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

    Supplies a specific timepoint that FileWriter should stop at, since there is a lag between what the user sees and what's actively streaming into FileWriter.

    Can be invoked by: curl http://localhost:4567/stop_recording

    Args:
        time_index: [Optional, int] centimilliseconds since acquisition began to end the recording at. defaults to when this command is received
    """
    shared_values_dict = _get_values_from_process_monitor()

    timestamp_of_sample_idx_zero = _get_timestamp_of_acquisition_sample_index_zero()

    stop_timepoint: Union[int, float]
    if "time_index" in request.args:
        stop_timepoint = int(request.args["time_index"])
    else:
        time_since_index_0 = datetime.datetime.utcnow() - timestamp_of_sample_idx_zero
        stop_timepoint = time_since_index_0.total_seconds() * (
            MICRO_TO_BASE_CONVERSION if shared_values_dict["beta_2_mode"] else CENTIMILLISECONDS_PER_SECOND
        )

    comm_dict: Dict[str, Any] = {
        "communication_type": "recording",
        "command": "stop_recording",
        "timepoint_to_stop_recording_at": stop_timepoint,
    }
    response = queue_command_to_main(comm_dict)
    return response


@flask_app.route("/start_managed_acquisition", methods=["GET"])
def start_managed_acquisition() -> Response:
    """Begin "managed" data acquisition (AKA data streaming) on the Mantarray.

    Can be invoked by:

    `curl http://localhost:4567/start_managed_acquisition`
    """
    shared_values_dict = _get_values_from_process_monitor()
    if not shared_values_dict["mantarray_serial_number"][0]:
        response = Response(status="406 Mantarray has not been assigned a Serial Number")
        return response
    if shared_values_dict["beta_2_mode"] and "magnetometer_config_dict" not in shared_values_dict:
        response = Response(status="406 Magnetometer Configuration has not been set yet")
        return response

    response = queue_command_to_main(START_MANAGED_ACQUISITION_COMMUNICATION)
    return response


@flask_app.route("/stop_managed_acquisition", methods=["GET"])
def stop_managed_acquisition() -> Response:
    """Stop "managed" data acquisition on the Mantarray.

    Can be invoked by:

    `curl http://localhost:4567/stop_managed_acquisition`
    """
    response = queue_command_to_main(STOP_MANAGED_ACQUISITION_COMMUNICATION)
    return response


# Single "debug console" commands to send to XEM
@flask_app.route("/insert_xem_command_into_queue/set_mantarray_serial_number", methods=["GET"])
def set_mantarray_serial_number() -> Response:
    """Set the serial number of the Mantarray device.

    This serial number pertains to the Mantarray instrument itself. This is different than the Opal Kelly serial number which pertains only to the XEM.

    This route will overwrite an existing Mantarray Nickname if present

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number=M02001900
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

    Specified bit files should be in same directory as mantarray-flask.exe

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/initialize_board?bit_file_name=main.bit&allow_board_reinitialization=False
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
    """Queue up a command to activate a given trigger-in bit on the XEM.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/activate_trigger_in?ep_addr=0x08&bit=0x00000001"
    """
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

    Mainly to be used in XEM scripting when delays between commands are necessary.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/comm_delay?num_milliseconds=10"
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
    """Designate the beginning of a hardware script in flask log.

    Can be invoked by: curl "http://localhost:4567/development/begin_hardware_script?script_type=ENUM&version=integer"
    """
    return Response(json.dumps({}), mimetype="application/json")


@flask_app.route("/development/end_hardware_script", methods=["GET"])
def dev_end_hardware_script() -> Response:
    """Designate the end of a hardware script in flask log.

    Can be invoked by: curl http://localhost:4567/development/end_hardware_script
    """
    return Response(json.dumps({}), mimetype="application/json")


@flask_app.route("/insert_xem_command_into_queue/get_num_words_fifo", methods=["GET"])
def queue_get_num_words_fifo() -> Response:
    """Queue up a command to set a wire-in value on the XEM.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/get_num_words_fifo
    """
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

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/set_device_id?new_id=""
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
    """Queue up a command to stop running data acquisition on the XEM.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/stop_acquisition
    """
    comm_dict = {
        "communication_type": "debug_console",
        "command": "stop_acquisition",
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/start_acquisition", methods=["GET"])
def queue_start_acquisition() -> Response:
    """Queue up a command to start running data acquisition on the XEM.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/start_acquisition
    """
    comm_dict = {
        "communication_type": "debug_console",
        "command": "start_acquisition",
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/get_serial_number", methods=["GET"])
def queue_get_serial_number() -> Response:
    """Queue up a command to stop running data acquisition on the XEM.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/get_serial_number
    """
    comm_dict = {
        "communication_type": "debug_console",
        "command": "get_serial_number",
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/get_device_id", methods=["GET"])
def queue_get_device_id() -> Response:
    """Queue up a command to get the device ID from the XEM.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/get_device_id
    """
    comm_dict = {
        "communication_type": "debug_console",
        "command": "get_device_id",
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/is_spi_running", methods=["GET"])
def queue_is_spi_running() -> Response:
    """Queue up a command to get SPI running status on the XEM.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/is_spi_running
    """
    comm_dict = {
        "communication_type": "debug_console",
        "command": "is_spi_running",
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/read_from_fifo", methods=["GET"])
def queue_read_from_fifo() -> Response:
    """Queue up a command to read data from the XEM.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/read_from_fifo?num_words_to_log=72
    """
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
    """Queue up a command to set a wire-in value on the XEM.

    Can be invoked by: curl "http://localhost:4567/insert_xem_command_into_queue/set_wire_in?ep_addr=6&value=0x00000010&mask=0x00000010"
    """
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
    """Run a script of XEM commands created from an existing flask log.

    Can be invoked by: curl http://localhost:4567/xem_scripts?script_type=start_up
    """
    script_type = request.args["script_type"]
    comm_dict = {"communication_type": "xem_scripts", "script_type": script_type}

    response = queue_command_to_instrument_comm(comm_dict)

    return response


@flask_app.route("/insert_xem_command_into_queue/read_wire_out", methods=["GET"])
def queue_read_wire_out() -> Response:
    """Queue up a command to read from wire out on the XEM.

    Takes an optional description message for commenting in the the log

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/read_wire_out?ep_addr=0x06&description=description_contents
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

    Does not interact with a XEM. This route shouldn't be used if an attribute of a XEM is needed.

    Can be invoked by: curl http://localhost:4567/insert_xem_command_into_queue/get_status
    """
    comm_dict = {
        "communication_type": "debug_console",
        "command": "get_status",
        "suppress_error": True,
    }

    response = queue_command_to_instrument_comm(comm_dict)

    return response


def shutdown_server() -> None:
    """Stop / shutdown the Flask Server itself.

    Eli (11/18/20): If separate routes call this, then it needs to be
    broken out into a subfunction not decorated as a Flask route.
    """
    logger.info("Calling function to shut down Flask Server.")
    socketio.stop()
    # Tanner (6/20/21): SystemExit is raised here, so no lines after this will execute


@flask_app.route("/stop_server", methods=["GET"])
def stop_server() -> str:
    """Shut down Flask.

    curl http://localhost:4567/stop_server
    """
    shutdown_server()
    # Tanner (6/20/21): SystemExit is raised inside the previous function call, so no lines after this will execute
    return "Server shutting down..."  # pragma: no cover


@flask_app.route("/shutdown", methods=["GET"])
def shutdown() -> Response:
    """Shutdown subprocesses then stop the server.

    curl http://localhost:4567/shutdown
    """
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
        if "system_status" in rule.rule:
            mantarray_nicknames = response_json.get("mantarray_nickname", {})
            for board in mantarray_nicknames:
                mantarray_nicknames[board] = get_redacted_string(len(mantarray_nicknames[board]))
        if "set_mantarray_nickname" in rule.rule:
            response_json["mantarray_nickname"] = get_redacted_string(
                len(response_json["mantarray_nickname"])
            )
        if "start_recording" in rule.rule:
            mantarray_nickname = response_json["metadata_to_copy_onto_main_file_attributes"][
                str(MANTARRAY_NICKNAME_UUID)
            ]
            response_json["metadata_to_copy_onto_main_file_attributes"][
                str(MANTARRAY_NICKNAME_UUID)
            ] = get_redacted_string(len(mantarray_nickname))

    msg = "Response to HTTP Request in next log entry: "
    if response.status_code == 200:
        # Tanner (1/19/21): using json.dumps instead of an f-string here allows us to perform better testing of our log messages by loading the json string to a python dict
        msg += json.dumps(response_json)
    else:
        msg += response.status
    logger.info(msg)
    return response


class ServerManager:
    """Convenience class for managing Flask/SocketIO server."""

    def __init__(
        self,
        to_main_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Dict[str, Any]
        ],
        processes_queue_container: MantarrayQueueContainer,
        values_from_process_monitor: Optional[Dict[str, Any]] = None,
        port: int = DEFAULT_SERVER_PORT_NUMBER,
        logging_level: int = logging.INFO,
        lock: Optional[threading.Lock] = None,
    ) -> None:
        global _the_server_manager  # pylint:disable=global-statement,invalid-name # Eli (1/21/21): deliberately using a module-level global
        if _the_server_manager is not None:
            # TODO Tanner (8/10/21): look into ways to avoid using this as a singleton
            raise ServerManagerSingletonAlreadySetError()

        self._lock = lock if lock is not None else threading.Lock()
        self._queue_container = processes_queue_container
        self._to_main_queue = to_main_queue
        self._port = port
        self._logging_level = logging_level
        if values_from_process_monitor is None:
            values_from_process_monitor = dict()

        _the_server_manager = self
        self._values_from_process_monitor = values_from_process_monitor

    def get_port_number(self) -> int:
        return self._port

    def get_queue_to_main(self) -> Queue[Dict[str, Any]]:  # pylint: disable=unsubscriptable-object
        return self._to_main_queue

    def get_data_queue_to_server(self) -> LightQueue:  # pylint: disable=unsubscriptable-object
        return self._queue_container.get_data_queue_to_server()

    def queue_container(self) -> MantarrayQueueContainer:
        return self._queue_container

    def get_values_from_process_monitor(self) -> Dict[str, Any]:
        """Get an immutable copy of the values.

        In order to maintain thread safety, make a copy while a Lock is
        acquired, only attempt to read from the copy, and don't attempt
        to mutate it.
        """
        # Tanner (8/10/21): not sure if using a lock here is necessary as nothing else accessing this dictionary is using a lock before modifying it
        with self._lock:
            copied_values = deepcopy(self._values_from_process_monitor)
        immutable_version: Dict[str, Any] = immutabledict(copied_values)
        return immutable_version

    def get_logging_level(self) -> int:
        return self._logging_level

    def check_port(self) -> None:
        port = self._port
        if is_port_in_use(port):
            raise LocalServerPortAlreadyInUseError(port)

    def shutdown_server(self) -> None:
        """Shutdown the Flask/SocketIO server."""
        try:
            requests.get(f"{get_api_endpoint()}stop_server")
        except requests.exceptions.ConnectionError:
            message = "Server is shutdown"
        else:
            raise NotImplementedError("Not sure why this happened, nothing should return from /stop_server")
        put_log_message_into_queue(
            logging.INFO,
            message,
            self._to_main_queue,
            self.get_logging_level(),
        )
        clear_the_server_manager()

    def drain_all_queues(self) -> Dict[str, Any]:
        queue_items = dict()

        queue_items["to_main"] = drain_queue(self._to_main_queue)
        queue_items["outgoing_data"] = drain_queue(self.get_data_queue_to_server())
        return queue_items
