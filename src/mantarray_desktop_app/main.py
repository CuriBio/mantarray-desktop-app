# -*- coding: utf-8 -*-
"""Python Flask Server controlling Mantarray.

Custom HTTP Error Codes:

* 204 - Call to /get_available_data when no available data in outgoing data queue from Data Analyzer.
* 400 - Call to /start_recording with invalid or missing barcode parameter
* 400 - Call to /set_mantarray_nickname with invalid nickname parameter
* 400 - Call to /update_settings with unexpected argument, invalid account UUID, or a recording directory that doesn't exist
* 400 - Call to /insert_xem_command_into_queue/set_mantarray_serial_number with invalid serial_number parameter
* 403 - Call to /start_recording with is_hardware_test_recording=False after calling route with is_hardware_test_recording=True (default value)
* 404 - Route not implemented
* 406 - Call to /start_managed_acquisition when Mantarray device does not have a serial number assigned to it
* 406 - Call to /start_recording before customer_account_uuid and user_account_uuid are set
* 452 -
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime
import json
import logging
import multiprocessing
import os
import platform
import queue
from queue import Queue
import sys
import threading
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from typing import Union
from uuid import UUID

from flask import Flask
from flask import request
from flask import Response
from flask_cors import CORS
from immutable_data_validation import is_uuid
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import METADATA_UUID_DESCRIPTIONS
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
from stdlib_utils import configure_logging
from stdlib_utils import InfiniteLoopingParallelismMixIn
from stdlib_utils import is_port_in_use

from .constants import ADC_GAIN_SETTING_UUID
from .constants import BUFFERING_STATE
from .constants import COMPILED_EXE_BUILD_TIMESTAMP
from .constants import CURI_BIO_ACCOUNT_UUID
from .constants import CURI_BIO_USER_ACCOUNT_ID
from .constants import CURRENT_SOFTWARE_VERSION
from .constants import CUSTOMER_ACCOUNT_ID_UUID
from .constants import DEFAULT_SERVER_PORT_NUMBER
from .constants import INSTRUMENT_INITIALIZING_STATE
from .constants import LIVE_VIEW_ACTIVE_STATE
from .constants import MAIN_FIRMWARE_VERSION_UUID
from .constants import MANTARRAY_NICKNAME_UUID
from .constants import MANTARRAY_SERIAL_NUMBER_UUID
from .constants import PLATE_BARCODE_UUID
from .constants import RECORDING_STATE
from .constants import REFERENCE_VOLTAGE
from .constants import REFERENCE_VOLTAGE_UUID
from .constants import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from .constants import SERVER_INITIALIZING_STATE
from .constants import SLEEP_FIRMWARE_VERSION_UUID
from .constants import SOFTWARE_RELEASE_VERSION_UUID
from .constants import START_MANAGED_ACQUISITION_COMMUNICATION
from .constants import START_RECORDING_TIME_INDEX_UUID
from .constants import SUBPROCESS_POLL_DELAY_SECONDS
from .constants import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from .constants import USER_ACCOUNT_ID_UUID
from .constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from .constants import UTC_BEGINNING_RECORDING_UUID
from .constants import VALID_CONFIG_SETTINGS
from .constants import XEM_SERIAL_NUMBER_UUID
from .exceptions import ImproperlyFormattedCustomerAccountUUIDError
from .exceptions import ImproperlyFormattedUserAccountUUIDError
from .exceptions import LocalServerPortAlreadyInUseError
from .exceptions import MultiprocessingNotSetToSpawnError
from .exceptions import RecordingFolderDoesNotExistError
from .ok_comm import check_mantarray_serial_number
from .process_manager import get_mantarray_process_manager
from .process_monitor import MantarrayProcessesMonitor
from .process_monitor import set_mantarray_processes_monitor

logger = logging.getLogger(__name__)
os.environ[
    "FLASK_ENV"
] = "DEVELOPMENT"  # this removes warnings about running the Werkzeug server (which is not meant for high volume requests, but should be fine for intra-PC communication from a single client)
flask_app = Flask(  # pylint: disable=invalid-name # yes, this is intentionally a singleton, not a constant
    __name__
)
CORS(flask_app)


_shared_values_between_server_and_process_monitor: Dict[  # pylint: disable=invalid-name # yes, this is intentionally a singleton, not a constant
    str, Any
] = dict()


def get_shared_values_between_server_and_monitor() -> Dict[  # pylint:disable=invalid-name # yeah, it's a little long, but descriptive
    str, Any
]:
    return _shared_values_between_server_and_process_monitor


def get_server_port_number() -> int:
    shared_values_dict = get_shared_values_between_server_and_monitor()
    return shared_values_dict.get("server_port_number", DEFAULT_SERVER_PORT_NUMBER)


def get_server_address_components() -> Tuple[str, str, int]:
    """Get Flask server address components.

    Returns:
        protocol (i.e. http), host (i.e. 127.0.0.1), port (i.e. 4567)
    """
    return "http", "127.0.0.1", get_server_port_number()


def get_api_endpoint() -> str:
    protocol, host, port = get_server_address_components()
    return f"{protocol}://{host}:{port}/"


def _check_barcode_for_errors(barcode: str) -> str:
    if len(barcode) > 11:
        return "Barcode exceeds max length"
    if len(barcode) < 10:
        return "Barcode does not reach min length"
    for char in barcode:
        if not char.isalnum():
            return f"Barcode contains invalid character: '{char}'"
    if barcode[:2] != "MA" and barcode[:2] != "MB" and barcode[:2] != "M1":
        return f"Barcode contains invalid header: '{barcode[:2]}'"
    if int(barcode[2:4]) != 20:
        return f"Barcode contains invalid year: '{barcode[2:4]}'"
    if int(barcode[4:7]) < 1 or int(barcode[4:7]) > 366:
        return f"Barcode contains invalid Julian date: '{barcode[4:7]}'"
    if not barcode[7:].isnumeric():
        return f"Barcode contains nom-numeric string after Julian date: '{barcode[7:]}'"
    return ""


def prepare_to_shutdown() -> None:
    """Stop and clean up subprocesses before shutting down."""
    manager = get_mantarray_process_manager()
    manager.soft_stop_processes()
    processes: Tuple[
        InfiniteLoopingParallelismMixIn,
        InfiniteLoopingParallelismMixIn,
        InfiniteLoopingParallelismMixIn,
    ] = (
        manager.get_ok_comm_process(),
        manager.get_file_writer_process(),
        manager.get_data_analyzer_process(),
    )

    start = time.perf_counter()
    are_processes_stopped = all(p.is_stopped() for p in processes)
    while (
        not are_processes_stopped
        and time.perf_counter() - start < SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
    ):
        are_processes_stopped = all(p.is_stopped() for p in processes)
        time.sleep(SUBPROCESS_POLL_DELAY_SECONDS)
    process_items = manager.hard_stop_and_join_processes()
    msg = f"Remaining items in process queues: {process_items}"
    logger.info(msg)


def shutdown_server() -> None:
    """Shut down Flask.

    Obtained from https://stackoverflow.com/questions/15562446/how-to-stop-flask-application-without-using-ctrl-c
    """
    shutdown_function = request.environ.get("werkzeug.server.shutdown")
    if shutdown_function is None:
        raise NotImplementedError("Not running with the Werkzeug Server")
    logger.info("Calling function to shut down Flask Server")
    shutdown_function()
    logger.info("Cleaning up the rest of the program before quitting.")
    prepare_to_shutdown()
    logger.info("Successful exit")


@flask_app.after_request
def after_request(response: Response) -> Response:
    """Log request and handle any necessary response clean up."""
    rule = request.url_rule
    response_json = response.get_json()
    if rule is None:
        response = Response(status="404 Route not implemented")
    elif "get_available_data" in rule.rule and response.status_code == 200:
        del response_json["waveform_data"]["basic_data"]

    msg = "Response to HTTP Request in next log entry: "
    if response.status_code == 200:
        msg += f"{response_json}"
    else:
        msg += response.status
    logger.info(msg)
    return response


@flask_app.route("/shutdown", methods=["GET"])
def shutdown() -> str:
    # curl http://localhost:4567/shutdown
    shutdown_server()
    return "Server shutting down..."


def _get_timestamp_of_acquisition_sample_index_zero() -> datetime.datetime:  # pylint:disable=invalid-name # yeah, it's kind of long, but Eli (2/27/20) doesn't know a good way to shorten it
    shared_values_dict = get_shared_values_between_server_and_monitor()
    timestamp_of_sample_idx_zero: datetime.datetime = shared_values_dict[
        "utc_timestamps_of_beginning_of_data_acquisition"
    ][
        0
    ]  # board index 0 hardcoded for now
    return timestamp_of_sample_idx_zero


@flask_app.route("/boot_up", methods=["GET"])
def boot_up() -> Response:
    """Initialize XEM then run start up script.

    Can be invoked by: curl http://localhost:4567/boot_up
    """
    shared_values_dict = get_shared_values_between_server_and_monitor()
    shared_values_dict["system_status"] = INSTRUMENT_INITIALIZING_STATE

    manager = get_mantarray_process_manager()
    response_dict = manager.boot_up_instrument()
    response = Response(json.dumps(response_dict), mimetype="application/json")

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
    if "barcode" not in request.args:
        response = Response(status="400 Request missing 'barcode' parameter")
        return response
    barcode = request.args["barcode"]
    error_message = _check_barcode_for_errors(barcode)
    if error_message:
        response = Response(status=f"400 {error_message}")
        return response

    shared_values_dict = get_shared_values_between_server_and_monitor()
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
    if (
        shared_values_dict.get("is_hardware_test_recording", False)
        and not is_hardware_test_recording
    ):
        response = Response(
            status="403 Cannot make standard recordings after previously making hardware test recordings. Server and board must both be restarted before making any more standard recordings"
        )
        return response
    shared_values_dict["is_hardware_test_recording"] = is_hardware_test_recording
    if is_hardware_test_recording:
        adc_offsets = dict()
        for well_idx in range(24):
            adc_offsets[well_idx] = {
                "construct": 0,
                "ref": 0,
            }
        shared_values_dict["adc_offsets"] = adc_offsets

    timestamp_of_sample_idx_zero = _get_timestamp_of_acquisition_sample_index_zero()

    shared_values_dict["system_status"] = RECORDING_STATE

    begin_timepoint: Union[int, float]
    timestamp_of_begin_recording = datetime.datetime.utcnow()
    if "time_index" in request.args:
        begin_timepoint = int(request.args["time_index"])
    else:
        time_since_index_0 = timestamp_of_begin_recording - timestamp_of_sample_idx_zero
        begin_timepoint = (
            time_since_index_0.total_seconds() * CENTIMILLISECONDS_PER_SECOND
        )

    comm_dict: Dict[str, Any] = {
        "command": "start_recording",
        "metadata_to_copy_onto_main_file_attributes": {
            HARDWARE_TEST_RECORDING_UUID: is_hardware_test_recording,
            UTC_BEGINNING_DATA_ACQUISTION_UUID: timestamp_of_sample_idx_zero,
            START_RECORDING_TIME_INDEX_UUID: begin_timepoint,
            UTC_BEGINNING_RECORDING_UUID: timestamp_of_begin_recording,
            CUSTOMER_ACCOUNT_ID_UUID: shared_values_dict["config_settings"][
                "Customer Account ID"
            ],
            USER_ACCOUNT_ID_UUID: shared_values_dict["config_settings"][
                "User Account ID"
            ],
            SOFTWARE_BUILD_NUMBER_UUID: COMPILED_EXE_BUILD_TIMESTAMP,
            SOFTWARE_RELEASE_VERSION_UUID: CURRENT_SOFTWARE_VERSION,
            MAIN_FIRMWARE_VERSION_UUID: shared_values_dict["main_firmware_version"][0],
            SLEEP_FIRMWARE_VERSION_UUID: shared_values_dict["sleep_firmware_version"][
                0
            ],
            XEM_SERIAL_NUMBER_UUID: shared_values_dict["xem_serial_number"][0],
            MANTARRAY_SERIAL_NUMBER_UUID: shared_values_dict["mantarray_serial_number"][
                0
            ],
            MANTARRAY_NICKNAME_UUID: shared_values_dict["mantarray_nickname"][0],
            REFERENCE_VOLTAGE_UUID: REFERENCE_VOLTAGE,
            ADC_GAIN_SETTING_UUID: shared_values_dict["adc_gain"],
            "adc_offsets": shared_values_dict["adc_offsets"],
            PLATE_BARCODE_UUID: barcode,
        },
        "timepoint_to_begin_recording_at": begin_timepoint,
    }

    if "active_well_indices" in request.args:
        comm_dict["active_well_indices"] = [
            int(x) for x in request.args["active_well_indices"].split(",")
        ]
    else:
        comm_dict["active_well_indices"] = list(range(24))

    manager = get_mantarray_process_manager()
    to_file_writer_queue = manager.get_communication_queue_from_main_to_file_writer()
    to_file_writer_queue.put(
        copy.deepcopy(comm_dict)
    )  # Eli (3/16/20): apparently when using multiprocessing.Queue you have to be careful when modifying values put into the queue because they might still be editable. So making a copy first
    for this_attr_name, this_attr_value in list(
        comm_dict["metadata_to_copy_onto_main_file_attributes"].items()
    ):
        if this_attr_name == "adc_offsets":
            continue
        if METADATA_UUID_DESCRIPTIONS[this_attr_name].startswith("UTC Timestamp"):
            this_attr_value = this_attr_value.strftime("%Y-%m-%dT%H:%M:%S.%f")
            comm_dict["metadata_to_copy_onto_main_file_attributes"][
                this_attr_name
            ] = this_attr_value
        if isinstance(this_attr_value, UUID):
            this_attr_value = str(this_attr_value)
        del comm_dict["metadata_to_copy_onto_main_file_attributes"][this_attr_name]
        this_attr_name = str(this_attr_name)
        comm_dict["metadata_to_copy_onto_main_file_attributes"][
            this_attr_name
        ] = this_attr_value

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

    shared_values_dict = get_shared_values_between_server_and_monitor()
    shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE

    comm_dict: Dict[str, Any] = {
        "command": "stop_recording",
    }

    stop_timepoint: Union[int, float]
    if "time_index" in request.args:
        stop_timepoint = int(request.args["time_index"])
    else:
        time_since_index_0 = datetime.datetime.utcnow() - timestamp_of_sample_idx_zero
        stop_timepoint = (
            time_since_index_0.total_seconds() * CENTIMILLISECONDS_PER_SECOND
        )
    comm_dict["timepoint_to_stop_recording_at"] = stop_timepoint

    manager = get_mantarray_process_manager()
    to_file_writer_queue = manager.get_communication_queue_from_main_to_file_writer()
    to_file_writer_queue.put(comm_dict)

    response = Response(json.dumps(comm_dict), mimetype="application/json")

    return response


@flask_app.route("/start_managed_acquisition", methods=["GET"])
def start_managed_acquisition() -> Response:
    """Begin "managed" data acquisition on the XEM.

    Can be invoked by:

    `curl http://localhost:4567/start_managed_acquisition`
    """
    shared_values_dict = get_shared_values_between_server_and_monitor()
    if not shared_values_dict["mantarray_serial_number"][0]:
        response = Response(
            status="406 Mantarray has not been assigned a Serial Number"
        )
        return response

    shared_values_dict["system_status"] = BUFFERING_STATE

    manager = get_mantarray_process_manager()
    to_da_queue = manager.get_communication_queue_from_main_to_data_analyzer()
    to_da_queue.put(START_MANAGED_ACQUISITION_COMMUNICATION)

    response = queue_command_to_ok_comm(START_MANAGED_ACQUISITION_COMMUNICATION)

    return response


@flask_app.route("/stop_managed_acquisition", methods=["GET"])
def stop_managed_acquisition() -> Response:
    """Stop "managed" data acquisition on the XEM.

    Can be invoked by:

    `curl http://localhost:4567/stop_managed_acquisition`
    """
    comm_dict = {
        "communication_type": "acquisition_manager",
        "command": "stop_managed_acquisition",
    }
    manager = get_mantarray_process_manager()
    to_da_queue = manager.get_communication_queue_from_main_to_data_analyzer()
    to_da_queue.put(comm_dict)
    to_file_writer_queue = manager.get_communication_queue_from_main_to_file_writer()
    to_file_writer_queue.put(comm_dict)

    response = queue_command_to_ok_comm(comm_dict)
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

    response = queue_command_to_ok_comm(comm_dict)

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

    response = queue_command_to_ok_comm(comm_dict)

    return response


@flask_app.route("/xem_scripts", methods=["GET"])
def run_xem_script() -> Response:
    """Run a script of XEM commands created from an existing flask log.

    Can be invoked by curl http://localhost:4567/xem_scripts?script_type=start_up
    """
    script_type = request.args["script_type"]
    comm_dict = {"communication_type": "xem_scripts", "script_type": script_type}

    response = queue_command_to_ok_comm(comm_dict)

    return response


@flask_app.route("/get_available_data", methods=["GET"])
def get_available_data() -> Response:
    """Get available data if any from Data Analyzer.

    Can be invoked by curl http://localhost:4567/get_available_data
    """
    manager = get_mantarray_process_manager()
    data_out_queue = manager.get_data_analyzer_data_out_queue()
    try:
        data = data_out_queue.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
    except queue.Empty:
        return Response(status=204)

    response = Response(data, mimetype="application/json")

    return response


@flask_app.route(
    "/insert_xem_command_into_queue/set_mantarray_serial_number", methods=["GET"]
)
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

    board_idx = 0
    shared_values_dict = get_shared_values_between_server_and_monitor()
    shared_values_dict["mantarray_serial_number"][board_idx] = serial_number

    comm_dict = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_serial_number",
        "mantarray_serial_number": serial_number,
    }

    response = queue_command_to_ok_comm(comm_dict)

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
        _update_settings(request.args)
    except (
        ImproperlyFormattedCustomerAccountUUIDError,
        ImproperlyFormattedUserAccountUUIDError,
        RecordingFolderDoesNotExistError,
    ) as e:
        response = Response(status=f"400 {repr(e)}")
        return response

    shared_values_dict = get_shared_values_between_server_and_monitor()
    response = Response(
        json.dumps(shared_values_dict["config_settings"]), mimetype="application/json"
    )
    return response


def _update_settings(
    settings_dict: Dict[str, Any], is_initial_settings: bool = False
) -> None:
    """Update the user configuration settings.

    Args:
        settings_dict: dictionary containing the new user configuration settings.
        is_initial_settings: boolean kwarg of whether not these are the initial values being set. This should only ever be set to True when using settings passed in from command line arguments on app start up
    """
    customer_account_uuid = settings_dict.get("customer_account_uuid", None)
    user_account_uuid = settings_dict.get("user_account_uuid", None)
    recording_directory = settings_dict.get("recording_directory", None)

    shared_values_dict = get_shared_values_between_server_and_monitor()
    if "config_settings" not in shared_values_dict:
        shared_values_dict["config_settings"] = dict()

    if customer_account_uuid is not None:
        if customer_account_uuid == "curi":
            customer_account_uuid = str(CURI_BIO_ACCOUNT_UUID)
            user_account_uuid = str(CURI_BIO_USER_ACCOUNT_ID)
        elif not is_uuid(customer_account_uuid):
            raise ImproperlyFormattedCustomerAccountUUIDError(customer_account_uuid)
        shared_values_dict["config_settings"][
            "Customer Account ID"
        ] = customer_account_uuid
    if user_account_uuid is not None:
        if not is_uuid(user_account_uuid):
            raise ImproperlyFormattedUserAccountUUIDError(user_account_uuid)
        shared_values_dict["config_settings"]["User Account ID"] = user_account_uuid
    if recording_directory is not None:
        if not os.path.isdir(recording_directory):
            raise RecordingFolderDoesNotExistError(recording_directory)
        shared_values_dict["config_settings"][
            "Recording Directory"
        ] = recording_directory
        process_manager = get_mantarray_process_manager()
        process_manager.set_file_directory(recording_directory)
        if not is_initial_settings:
            comm_to_file_writer = (
                process_manager.get_communication_queue_from_main_to_file_writer()
            )
            file_dir_comm = {
                "command": "update_directory",
                "new_directory": recording_directory,
            }
            comm_to_file_writer.put(file_dir_comm)

        msg = f"Using directory for recording files: {recording_directory}"
        logger.info(msg)


def start_server() -> None:
    _, host, port = get_server_address_components()
    if is_port_in_use(port):
        raise LocalServerPortAlreadyInUseError()
    flask_app.run(host=host, port=port)
    # Note (Eli 1/14/20) it appears with the current method of using werkzeug.server.shutdown that nothing after this line will ever be executed. somehow the program exists before returning from app.run


def start_server_in_thread() -> threading.Thread:
    server_thread = threading.Thread(target=start_server, name="server_thread")
    server_thread.start()
    return server_thread


def main(command_line_args: List[str]) -> None:
    """Parse command line arguments and run."""
    log_level = logging.INFO
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug-test-post-build",
        action="store_true",
        help="simple test to run after building executable to confirm libraries are linked/imported correctly",
    )
    parser.add_argument(
        "--log-level-debug",
        action="store_true",
        help="sets the loggers to be more verbose and log DEBUG level pieces of information",
    )
    parser.add_argument(
        "--skip-mantarray-boot-up",
        action="store_true",
        help="bypasses automatic run of boot_up for hardware testing",
    )
    parser.add_argument(
        "--port_number", type=int, help="allow manual setting of server port number",
    )
    parser.add_argument(
        "--log_file_dir",
        type=str,
        help="allow manual setting of the directory in which log files will be stored",
    )
    parser.add_argument(
        "--initial-base64-settings",
        type=str,
        help="allow initial configuration of user settings",
    )
    parsed_args = parser.parse_args(command_line_args)

    if parsed_args.log_level_debug:
        log_level = logging.DEBUG
    path_to_log_folder = parsed_args.log_file_dir
    configure_logging(
        path_to_log_folder=path_to_log_folder,
        log_file_prefix="mantarray_log",
        log_level=log_level,
    )

    msg = f"Mantarray Controller v{CURRENT_SOFTWARE_VERSION} started"
    logger.info(msg)
    msg = f"Build timestamp/version: {COMPILED_EXE_BUILD_TIMESTAMP}"
    logger.info(msg)
    msg = f"Command Line Args: {vars(parsed_args)}"
    logger.info(msg)
    msg = f"Using directory for log files: {path_to_log_folder}"
    logger.info(msg)
    multiprocessing_start_method = multiprocessing.get_start_method(allow_none=True)
    if multiprocessing_start_method != "spawn":
        raise MultiprocessingNotSetToSpawnError(multiprocessing_start_method)

    decoded_settings: bytes
    if parsed_args.initial_base64_settings:
        # Eli (7/15/20): Moved this ahead of the exit for debug_test_post_build so that it could be easily unit tested. The equals signs are adding padding..apparently a quirk in python https://stackoverflow.com/questions/2941995/python-ignore-incorrect-padding-error-when-base64-decoding
        decoded_settings = base64.urlsafe_b64decode(
            str(parsed_args.initial_base64_settings) + "==="
        )

    if parsed_args.debug_test_post_build:
        print("Successfully opened and closed application.")  # allow-print
        return

    shared_values_dict = get_shared_values_between_server_and_monitor()
    shared_values_dict["system_status"] = SERVER_INITIALIZING_STATE
    if parsed_args.port_number is not None:
        shared_values_dict["server_port_number"] = parsed_args.port_number
    msg = f"Using server port number: {get_server_port_number()}"
    logger.info(msg)

    if parsed_args.initial_base64_settings:
        settings_dict = json.loads(decoded_settings)
        _update_settings(settings_dict, is_initial_settings=True)

    system_messages = list()
    uname = platform.uname()
    uname_sys = getattr(uname, "system")
    uname_release = getattr(uname, "release")
    uname_version = getattr(uname, "version")
    system_messages.append(f"System: {uname_sys}")
    system_messages.append(f"Release: {uname_release}")
    system_messages.append(f"Version: {uname_version}")
    system_messages.append(f"Machine: {getattr(uname, 'machine')}")
    system_messages.append(f"Processor: {getattr(uname, 'processor')}")
    system_messages.append(f"Win 32 Ver: {platform.win32_ver()}")
    system_messages.append(f"Platform: {platform.platform()}")
    system_messages.append(f"Architecture: {platform.architecture()}")
    system_messages.append(f"Interpreter is 64-bits: {sys.maxsize > 2**32}")
    system_messages.append(
        f"System Alias: {platform.system_alias(uname_sys, uname_release, uname_version)}"
    )
    system_messages.append(f"Python Version: {platform.python_version_tuple()}")
    system_messages.append(f"Python Implementation: {platform.python_implementation()}")
    system_messages.append(f"Python Build: {platform.python_build()}")
    system_messages.append(f"Python Compiler: {platform.python_compiler()}")
    for msg in system_messages:
        logger.info(msg)
    logger.info("Spawning subprocesses")
    process_manager = get_mantarray_process_manager()
    process_manager.set_logging_level(log_level)
    process_manager.spawn_processes()

    boot_up_after_processes_start = not parsed_args.skip_mantarray_boot_up

    the_lock = threading.Lock()
    process_monitor_error_queue: Queue[  # pylint: disable=unsubscriptable-object
        str
    ] = queue.Queue()
    process_monitor_thread = MantarrayProcessesMonitor(
        get_shared_values_between_server_and_monitor(),
        process_manager,
        process_monitor_error_queue,
        the_lock,
        boot_up_after_processes_start=boot_up_after_processes_start,
    )
    set_mantarray_processes_monitor(process_monitor_thread)
    logger.info("Starting process monitor thread")
    process_monitor_thread.start()
    logger.info("Starting server thread")
    server_thread = start_server_in_thread()
    server_thread.join()
    logger.info("Server shut down, about to stop processes")
    process_monitor_thread.soft_stop()
    process_monitor_thread.join()
    logger.info("Process monitor shut down")
    logger.info("Program exiting")
    process_manager.set_logging_level(
        logging.INFO
    )  # Eli (3/12/20) - this is really hacky...better solution is to allow setting the process manager back to its normal state
