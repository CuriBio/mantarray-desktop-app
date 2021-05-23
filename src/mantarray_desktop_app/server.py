# -*- coding: utf-8 -*-
"""Python Flask Server controlling Mantarray.

Custom HTTP Error Codes:

* 204 - Call to /get_available_data when no available data in outgoing data queue from Data Analyzer
* 400 - Call to /start_recording with invalid or missing barcode parameter
* 400 - Call to /set_mantarray_nickname with invalid nickname parameter
* 400 - Call to /update_settings with unexpected argument, invalid account UUID, or a recording directory that doesn't exist
* 400 - Call to /insert_xem_command_into_queue/set_mantarray_serial_number with invalid serial_number parameter
* 400 - Call to /set_magnetometer_config with invalid configuration dict
* 400 - Call to /set_magnetometer_config with invalid or missing sampling period
* 403 - Call to /start_recording with is_hardware_test_recording=False after calling route with is_hardware_test_recording=True (default value)
* 403 - Call to any /insert_xem_command_into_queue/* route when in Beta 2 mode
* 403 - Call to /boot_up when in Beta 2 mode
* 403 - Call to /set_magnetometer_config when in Beta 1 mode
* 403 - Call to /set_magnetometer_config while data is streaming in Beta 2 mode
* 404 - Route not implemented
* 406 - Call to /start_managed_acquisition before magnetometer configuration is set
* 406 - Call to /start_managed_acquisition when Mantarray device does not have a serial number assigned to it
* 406 - Call to /start_recording before customer_account_uuid and user_account_uuid are set
* 520 - Electron and Flask EXE versions don't match
"""
from __future__ import annotations

import copy
from copy import deepcopy
import datetime
import json
import logging
import multiprocessing
import os
from queue import Empty
from queue import Queue
import threading
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple
from typing import Union
from uuid import UUID

from flask import Flask
from flask import request
from flask import Response
from flask_cors import CORS
from immutabledict import immutabledict
from mantarray_file_manager import ADC_GAIN_SETTING_UUID
from mantarray_file_manager import BACKEND_LOG_UUID
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import COMPUTER_NAME_HASH_UUID
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import METADATA_UUID_DESCRIPTIONS
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import REFERENCE_VOLTAGE_UUID
from mantarray_file_manager import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_file_manager import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
from mantarray_file_manager import USER_ACCOUNT_ID_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_BEGINNING_RECORDING_UUID
from mantarray_file_manager import XEM_SERIAL_NUMBER_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import requests
from stdlib_utils import drain_queue
from stdlib_utils import get_formatted_stack_trace
from stdlib_utils import InfiniteThread
from stdlib_utils import is_port_in_use
from stdlib_utils import print_exception
from stdlib_utils import put_log_message_into_queue

from .constants import BUFFERING_STATE
from .constants import COMPILED_EXE_BUILD_TIMESTAMP
from .constants import CURRENT_SOFTWARE_VERSION
from .constants import DEFAULT_SERVER_PORT_NUMBER
from .constants import LIVE_VIEW_ACTIVE_STATE
from .constants import MICROSECONDS_PER_MILLISECOND
from .constants import RECORDING_STATE
from .constants import REFERENCE_VOLTAGE
from .constants import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from .constants import SERIAL_COMM_METADATA_BYTES_LENGTH
from .constants import START_MANAGED_ACQUISITION_COMMUNICATION
from .constants import STOP_MANAGED_ACQUISITION_COMMUNICATION
from .constants import SYSTEM_STATUS_UUIDS
from .constants import VALID_CONFIG_SETTINGS
from .exceptions import ImproperlyFormattedCustomerAccountUUIDError
from .exceptions import ImproperlyFormattedUserAccountUUIDError
from .exceptions import LocalServerPortAlreadyInUseError
from .exceptions import RecordingFolderDoesNotExistError
from .exceptions import ServerThreadNotInitializedError
from .exceptions import ServerThreadSingletonAlreadySetError
from .ok_comm import check_mantarray_serial_number
from .queue_container import MantarrayQueueContainer
from .request_handler import MantarrayRequestHandler
from .utils import check_barcode_for_errors
from .utils import convert_request_args_to_config_dict
from .utils import get_current_software_version
from .utils import validate_magnetometer_config_keys
from .utils import validate_settings

logger = logging.getLogger(__name__)
os.environ[
    "FLASK_ENV"
] = "DEVELOPMENT"  # this removes warnings about running the Werkzeug server (which is not meant for high volume requests, but should be fine for intra-PC communication from a single client)
flask_app = Flask(  # pylint: disable=invalid-name # yes, this is intentionally a singleton, not a constant
    __name__
)
CORS(flask_app)

_the_server_thread: Optional[  # pylint: disable=invalid-name # Eli (11/3/20) yes, this is intentionally a singleton, not a constant. This is the current best guess at how to allow Flask routes to access some info they need
    "ServerThread"
] = None


def clear_the_server_thread() -> None:
    global _the_server_thread  # pylint:disable=global-statement,invalid-name # Eli (12/8/20) this is deliberately setting a module-level singleton
    _the_server_thread = None


def get_the_server_thread() -> "ServerThread":
    """Return the singleton instance."""
    if _the_server_thread is None:
        raise ServerThreadNotInitializedError(
            "This function should not be called when the ServerThread is None and hasn't been initialized yet."
        )
    return _the_server_thread


def get_server_to_main_queue() -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
    Dict[str, Any]
]:
    return get_the_server_thread().get_queue_to_main()


def get_server_address_components() -> Tuple[str, str, int]:
    """Get Flask server address components.

    Returns:
        protocol (i.e. HTTP), host (i.e. 127.0.0.1), port (i.e. 4567)
    """
    try:
        port_number = get_the_server_thread().get_port_number()
    except (NameError, ServerThreadNotInitializedError):
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
    return get_the_server_thread().get_values_from_process_monitor()


def queue_command_to_instrument_comm(comm_dict: Dict[str, Any]) -> Response:
    """Queue command to send to InstrumentCommProcess and return response.

    This is used by the test suite, so is not designated as private in
    order to make pylint happier.
    """
    to_instrument_comm_queue = (
        get_the_server_thread().queue_container().get_communication_to_instrument_comm_queue(0)
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
    if (
        "expected_software_version" in shared_values_dict
        and shared_values_dict["expected_software_version"] != get_current_software_version()
    ):
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


@flask_app.route("/get_available_data", methods=["GET"])
def get_available_data() -> Response:
    """Get available data if any from Data Analyzer.

    Can be invoked by curl http://localhost:4567/get_available_data
    """
    server_thread = get_the_server_thread()
    data_out_queue = server_thread.get_data_analyzer_data_out_queue()
    try:
        data = data_out_queue.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
    except Empty:
        return Response(status=204)

    response = Response(data, mimetype="application/json")

    return response


@flask_app.route("/set_mantarray_nickname", methods=["GET"])
def set_mantarray_nickname() -> Response:
    """Set the 'nickname' of the Mantarray device.

    This route will not overwrite an existing Mantarray Serial Number.

    Can be invoked by curl 'http://localhost:4567/set_mantarray_nickname?nickname=My Mantarray'
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

    Can be invoked by curl http://localhost:4567/update_settings?customer_account_uuid=<UUID>&user_account_uuid=<UUID>&recording_directory=recording_dir
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
    """
    if not _get_values_from_process_monitor()["beta_2_mode"]:
        return Response(status="403 Route cannot be called in beta 1 mode")
    if _is_data_streaming():
        return Response(status="403 Magnetometer Configuration cannot be changed while data is streaming")
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

    queue_command_to_main(
        {
            "communication_type": "set_magnetometer_config",
            "magnetometer_config_dict": magnetometer_config_dict,
        }
    )

    return Response(magnetometer_config_dict_json, mimetype="application/json")


def _fix_magnetometer_config_dict_keys(magnetometer_config_dict: Dict[str, Any]) -> Dict[Any, Any]:
    return {_fix_json_key(k): v for k, v in magnetometer_config_dict.items()}


def _fix_json_key(key: str) -> Union[int, str]:
    try:
        return int(key)
    except ValueError:
        return key


def _is_data_streaming() -> bool:
    current_system_status = _get_values_from_process_monitor()["system_status"]
    return current_system_status in (BUFFERING_STATE, LIVE_VIEW_ACTIVE_STATE, RECORDING_STATE)


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
    # TODO Tanner (4/23/21): Need to update this route after Beta 2 file format is figured out
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
    timestamp_of_sample_idx_zero = _get_timestamp_of_acquisition_sample_index_zero()

    begin_timepoint: Union[int, float]
    timestamp_of_begin_recording = datetime.datetime.utcnow()
    if "time_index" in request.args:
        begin_timepoint = int(request.args["time_index"])
    else:
        time_since_index_0 = timestamp_of_begin_recording - timestamp_of_sample_idx_zero
        begin_timepoint = time_since_index_0.total_seconds() * CENTIMILLISECONDS_PER_SECOND

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
            SLEEP_FIRMWARE_VERSION_UUID: shared_values_dict["sleep_firmware_version"][board_idx],
            XEM_SERIAL_NUMBER_UUID: shared_values_dict["xem_serial_number"][board_idx],
            MANTARRAY_SERIAL_NUMBER_UUID: shared_values_dict["mantarray_serial_number"][board_idx],
            MANTARRAY_NICKNAME_UUID: shared_values_dict["mantarray_nickname"][board_idx],
            REFERENCE_VOLTAGE_UUID: REFERENCE_VOLTAGE,
            ADC_GAIN_SETTING_UUID: shared_values_dict["adc_gain"],
            "adc_offsets": adc_offsets,
            PLATE_BARCODE_UUID: barcode,
            BARCODE_IS_FROM_SCANNER_UUID: are_barcodes_matching,
        },
        "timepoint_to_begin_recording_at": begin_timepoint,
    }

    if "active_well_indices" in request.args:
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
    timestamp_of_sample_idx_zero = _get_timestamp_of_acquisition_sample_index_zero()

    comm_dict: Dict[str, Any] = {
        "communication_type": "recording",
        "command": "stop_recording",
    }

    stop_timepoint: Union[int, float]
    if "time_index" in request.args:
        stop_timepoint = int(request.args["time_index"])
    else:
        time_since_index_0 = datetime.datetime.utcnow() - timestamp_of_sample_idx_zero
        stop_timepoint = time_since_index_0.total_seconds() * CENTIMILLISECONDS_PER_SECOND
    comm_dict["timepoint_to_stop_recording_at"] = stop_timepoint

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
    if "magnetometer_config_dict" not in shared_values_dict:
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
    comm_dict = STOP_MANAGED_ACQUISITION_COMMUNICATION
    server_thread = get_the_server_thread()
    to_da_queue = server_thread.queue_container().get_communication_queue_from_main_to_data_analyzer()
    to_da_queue.put_nowait(comm_dict)
    to_file_writer_queue = server_thread.queue_container().get_communication_queue_from_main_to_file_writer()
    to_file_writer_queue.put_nowait(comm_dict)

    response = queue_command_to_instrument_comm(comm_dict)
    return response


# Single "debug console" commands to send to XEM
@flask_app.route("/insert_xem_command_into_queue/set_mantarray_serial_number", methods=["GET"])
def set_mantarray_serial_number() -> Response:
    """Set the serial number of the Mantarray device.

    This serial number pertains to the Mantarray instrument itself. This is different than the Opal Kelly serial number which pertains only to the XEM.

    This route will overwrite an existing Mantarray Nickname if present

    Can be invoked by curl http://localhost:4567/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number=M02001900
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

    Can be invoked by curl "http://localhost:4567/development/begin_hardware_script?script_type=ENUM&version=integer"
    """
    return Response(json.dumps({}), mimetype="application/json")


@flask_app.route("/development/end_hardware_script", methods=["GET"])
def dev_end_hardware_script() -> Response:
    """Designate the end of a hardware script in flask log.

    Can be invoked by curl http://localhost:4567/development/end_hardware_script
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

    Can be invoked by curl http://localhost:4567/xem_scripts?script_type=start_up
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
    shutdown_function = request.environ.get("werkzeug.server.shutdown")
    if shutdown_function is None:
        raise NotImplementedError("Not running with the Werkzeug Server")
    logger.info("Calling function to shut down Flask Server.")
    shutdown_function()
    logger.info("Flask server successfully shut down.")


@flask_app.route("/stop_server", methods=["GET"])
def stop_server() -> str:
    """Shut down Flask.

    Obtained from https://stackoverflow.com/questions/15562446/how-to-stop-flask-application-without-using-ctrl-c
    curl http://localhost:4567/stop_server
    """
    shutdown_server()
    return "Server shutting down..."


@flask_app.route("/shutdown", methods=["GET"])
def shutdown() -> Response:
    # curl http://localhost:4567/shutdown
    queue_command_to_main({"communication_type": "shutdown", "command": "soft_stop"})
    response = queue_command_to_main({"communication_type": "shutdown", "command": "hard_stop"})
    shutdown_server()
    return response


@flask_app.route("/health_check", methods=["GET"])
def health_check() -> Response:
    # curl http://localhost:4567/health_check
    return Response(status=200)


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
        if "get_available_data" in rule.rule:
            del response_json["waveform_data"]["basic_data"]
        if "system_status" in rule.rule:
            mantarray_nicknames = response_json.get("mantarray_nickname", {})
            for board in mantarray_nicknames:
                mantarray_nicknames[board] = "*" * len(mantarray_nicknames[board])
        if "set_mantarray_nickname" in rule.rule:
            response_json["mantarray_nickname"] = "*" * len(response_json["mantarray_nickname"])
        if "start_recording" in rule.rule:
            mantarray_nickname = response_json["metadata_to_copy_onto_main_file_attributes"][
                str(MANTARRAY_NICKNAME_UUID)
            ]
            response_json["metadata_to_copy_onto_main_file_attributes"][
                str(MANTARRAY_NICKNAME_UUID)
            ] = "*" * len(mantarray_nickname)

    msg = "Response to HTTP Request in next log entry: "
    if response.status_code == 200:
        # Tanner (1/19/21): using json.dumps instead of an f-string here allows us to perform better testing of our log messages by loading the json string to a python dict
        msg += json.dumps(response_json)
    else:
        msg += response.status
    logger.info(msg)
    return response


# TODO (Eli 11/3/20): refactor :package:`stdlib-utils` to separate some of the more generic multiprocessing functionality out of the "InfiniteLooping" mixin so that it could be included here without all the other things
class ServerThread(InfiniteThread):
    """Thread to run the Flask server."""

    def __init__(
        self,
        to_main_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Dict[str, Any]
        ],
        fatal_error_reporter: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ],
        processes_queue_container: MantarrayQueueContainer,  # TODO (Eli 11/4/20): This should eventually be removed as it tightly couples the independent processes together. Ideally all messages should go from server to main and then be routed where they need to by the ProcessMonitor
        values_from_process_monitor: Optional[Dict[str, Any]] = None,
        port: int = DEFAULT_SERVER_PORT_NUMBER,
        logging_level: int = logging.INFO,
        lock: Optional[threading.Lock] = None,
    ) -> None:
        global _the_server_thread  # pylint:disable=global-statement,invalid-name # Eli (1/21/21): deliberately using a module-level singleton
        if _the_server_thread is not None:
            raise ServerThreadSingletonAlreadySetError()

        if lock is None:
            lock = threading.Lock()

        super().__init__(fatal_error_reporter, lock=lock)
        self._queue_container = processes_queue_container
        self._to_main_queue = to_main_queue
        self._port = port
        self._logging_level = logging_level
        if values_from_process_monitor is None:
            values_from_process_monitor = dict()

        _the_server_thread = self
        self._values_from_process_monitor = values_from_process_monitor

    def get_port_number(self) -> int:
        return self._port

    def get_queue_to_main(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._to_main_queue

    def queue_container(self) -> MantarrayQueueContainer:
        return self._queue_container

    def get_values_from_process_monitor(self) -> Dict[str, Any]:
        """Get an immutable copy of the values.

        In order to maintain thread safety, make a copy while a Lock is
        acquired, only attempt to read from the copy, and don't attempt
        to mutate it.
        """
        with self._lock:  # Eli (11/3/20): still unable to test if lock was acquired.
            copied_values = deepcopy(self._values_from_process_monitor)
        immutable_version: Dict[str, Any] = immutabledict(copied_values)
        return immutable_version

    def get_logging_level(self) -> int:
        return self._logging_level

    def check_port(self) -> None:
        port = self._port
        if is_port_in_use(port):
            raise LocalServerPortAlreadyInUseError(port)

    # TODO Eli (12/8/20): refactor so there's something other than InfiniteThread this can inherit from which retains the other abilities for communication but not the infinite looping
    def run(  # pylint:disable=arguments-differ # Eli (12/8/20): this should be fixed by a refactor, see TODO above
        self,
    ) -> None:
        try:
            _, host, _ = get_server_address_components()
            self.check_port()
            flask_app.run(
                host=host,
                port=self._port,
                request_handler=MantarrayRequestHandler,
                threaded=True,
            )
            # Note (Eli 1/14/20) it appears with the current method of using werkzeug.server.shutdown that nothing after this line will ever be executed. somehow the program exists before returning from app.run
        except Exception as e:  # pylint: disable=broad-except # The deliberate goal of this is to catch everything and put it into the error queue
            print_exception(e, "0d6e8031-6653-47d7-8490-8c28f92494c3")
            formatted_stack_trace = get_formatted_stack_trace(e)
            self._fatal_error_reporter.put_nowait((e, formatted_stack_trace))

    def _shutdown_server(self) -> None:
        http_route = f"{get_api_endpoint()}stop_server"
        try:
            requests.get(http_route)
            message = "Server has been successfully shutdown."
        except requests.exceptions.ConnectionError:
            message = f"Server was not running on {http_route} during shutdown attempt."
        put_log_message_into_queue(
            logging.INFO,
            message,
            self._to_main_queue,
            self.get_logging_level(),
        )

    def stop(self) -> None:
        """Stop the thread.

        Because there is no actual infinite loop running here, the
        super().stop() needs to be called to activate the right events
        being set.
        """
        self._shutdown_server()
        self._teardown_after_loop()
        super().stop()

    def soft_stop(self) -> None:
        self.stop()

    def get_data_analyzer_data_out_queue(
        self,
    ) -> multiprocessing.Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        # TODO (Eli 11/5/20): Even after the QueueContainer is removed, this queue should be made available to the server thread through the init as it needs this to pass data to the Frontend app
        return self._queue_container.get_data_analyzer_data_out_queue()

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items = dict()

        queue_items["to_main"] = drain_queue(self._to_main_queue)
        queue_items["from_data_analyzer"] = drain_queue(self.get_data_analyzer_data_out_queue())
        return queue_items

    def _teardown_after_loop(self) -> None:
        clear_the_server_thread()
        super()._teardown_after_loop()
