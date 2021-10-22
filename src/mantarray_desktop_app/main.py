# -*- coding: utf-8 -*-
"""Python Backend controlling Mantarray."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import logging
import multiprocessing
import os
from os import getpid
import platform
import queue
from queue import Queue
import socket
import sys
import threading
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
import uuid

from eventlet.queue import Empty
from stdlib_utils import configure_logging
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import is_port_in_use
from stdlib_utils import resource_path

from .constants import COMPILED_EXE_BUILD_TIMESTAMP
from .constants import CURRENT_SOFTWARE_VERSION
from .constants import DEFAULT_SERVER_PORT_NUMBER
from .constants import SERVER_INITIALIZING_STATE
from .exceptions import InvalidBeta2FlagOptionError
from .exceptions import LocalServerPortAlreadyInUseError
from .exceptions import MultiprocessingNotSetToSpawnError
from .log_formatter import SensitiveFormatter
from .process_manager import MantarrayProcessesManager
from .process_monitor import MantarrayProcessesMonitor
from .server import clear_the_server_manager
from .server import flask_app
from .server import get_server_address_components
from .server import get_the_server_manager
from .server import ServerManagerNotInitializedError
from .server import socketio
from .utils import convert_request_args_to_config_dict
from .utils import redact_sensitive_info_from_path
from .utils import update_shared_dict
from .utils import validate_settings


logger = logging.getLogger(__name__)

_server_port_number = DEFAULT_SERVER_PORT_NUMBER  # pylint:disable=invalid-name # Eli (12/8/20): this is deliberately a module-level singleton


def clear_server_singletons() -> None:
    clear_the_server_manager()
    global _server_port_number  # pylint:disable=global-statement,invalid-name # Eli (12/8/20) this is deliberately setting a module-level singleton
    _server_port_number = DEFAULT_SERVER_PORT_NUMBER


def get_server_port_number() -> int:
    try:
        server_manager = get_the_server_manager()
    except (NameError, ServerManagerNotInitializedError):
        return _server_port_number
    return server_manager.get_port_number()


def _create_process_manager(shared_values_dict: Dict[str, Any]) -> MantarrayProcessesManager:
    base_path = os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir)
    relative_path = "recordings"
    try:
        file_dir = shared_values_dict["config_settings"]["Recording Directory"]
    except KeyError:
        file_dir = resource_path(relative_path, base_path=base_path)

    return MantarrayProcessesManager(file_directory=file_dir, values_to_share_to_server=shared_values_dict)


def _log_system_info() -> None:
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
    system_messages.append(
        f"Platform: {platform.platform()}, Architecture: {platform.architecture()}, Interpreter is 64-bits: {sys.maxsize > 2**32}, System Alias: {platform.system_alias(uname_sys, uname_release, uname_version)}"
    )
    for msg in system_messages:
        logger.info(msg)


def main(
    command_line_args: List[str],
    object_access_for_testing: Optional[Dict[str, Any]] = None,
) -> None:
    # pylint: disable=too-many-locals,too-many-statements  # Tanner (6/17/21): long start up script needed
    """Parse command line arguments and run."""
    if object_access_for_testing is None:
        object_access_for_testing = dict()

    logger.info(command_line_args)

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
        "--port-number",
        type=int,
        help="allow manual setting of server port number",
    )
    parser.add_argument(
        "--log-file-dir",
        type=str,
        help="allow manual setting of the directory in which log files will be stored",
    )
    parser.add_argument(
        "--initial-base64-settings",
        type=str,
        help="allow initial configuration of user settings",
    )
    parser.add_argument(
        "--expected-software-version",
        type=str,
        help="used to make sure flask server and GUI are the same version",
    )
    parser.add_argument(
        "--no-load-firmware",
        action="store_true",
        help="allow app to run from command line when no firmware file is present",
    )
    parser.add_argument(
        "--skip-software-version-verification",
        action="store_true",
        help="override any supplied expected software version and disable the check",
    )
    parser.add_argument(
        "--beta-2-mode",
        action="store_true",
        help="indicates the software will be connecting to a beta 2 mantarray instrument",
    )
    parser.add_argument(
        "--startup-test-options",
        type=str,
        nargs="+",
        choices=["no_flask", "no_subprocesses"],
        help="indicate how much of the main script should not be started",
    )
    parser.add_argument(
        "--stored-customer-ids",
        help="provides stored customer account credentials",
    )
    parsed_args = parser.parse_args(command_line_args)

    if parsed_args.beta_2_mode:
        for invalid_beta_2_option, error_message in (
            (parsed_args.no_load_firmware, "--no-load-firmware"),
            (parsed_args.skip_mantarray_boot_up, "--skip-mantarray-boot-up"),
        ):
            if invalid_beta_2_option:
                raise InvalidBeta2FlagOptionError(error_message)

    startup_options = []
    if parsed_args.startup_test_options:
        startup_options = parsed_args.startup_test_options
    start_subprocesses = "no_subprocesses" not in startup_options
    start_flask = "no_flask" not in startup_options

    if parsed_args.log_level_debug:
        log_level = logging.DEBUG
    path_to_log_folder = parsed_args.log_file_dir
    logging_formatter = SensitiveFormatter(
        "[%(asctime)s UTC] %(name)s-{%(filename)s:%(lineno)d} %(levelname)s - %(message)s"
    )
    configure_logging(
        path_to_log_folder=path_to_log_folder,
        log_file_prefix="mantarray_log",
        log_level=log_level,
        logging_formatter=logging_formatter,
    )

    scrubbed_path_to_log_folder = redact_sensitive_info_from_path(path_to_log_folder)

    msg = f"Mantarray Controller v{CURRENT_SOFTWARE_VERSION} started"
    logger.info(msg)
    msg = f"Build timestamp/version: {COMPILED_EXE_BUILD_TIMESTAMP}"
    logger.info(msg)
    parsed_args_dict = copy.deepcopy(vars(parsed_args))
    # Tanner (1/14/21): parsed_args_dict is only used to log the command line args at the moment, so initial_base64_settings can be deleted and log_file_dir can just be replaced here without affecting anything that actually needs the original value
    del parsed_args_dict["initial_base64_settings"]
    parsed_args_dict["log_file_dir"] = scrubbed_path_to_log_folder
    msg = f"Command Line Args: {parsed_args_dict}".replace(
        r"\\",
        "\\",
    )  # Tanner (1/14/21): Unsure why the back slashes are duplicated when converting the dict to string. Using replace here to remove the duplication, not sure if there is a better way to solve or avoid this problem
    logger.info(msg)
    msg = f"Using directory for log files: {scrubbed_path_to_log_folder}"
    logger.info(msg)

    multiprocessing_start_method = multiprocessing.get_start_method(allow_none=True)
    if multiprocessing_start_method != "spawn":
        raise MultiprocessingNotSetToSpawnError(multiprocessing_start_method)

    shared_values_dict: Dict[str, Any] = dict()
    settings_dict: Dict[str, Any] = dict()

    if parsed_args.initial_base64_settings:
        # Eli (7/15/20): Moved this ahead of the exit for debug_test_post_build so that it could be easily unit tested. The equals signs are adding padding..apparently a quirk in python https://stackoverflow.com/questions/2941995/python-ignore-incorrect-padding-error-when-base64-decoding
        decoded_settings: bytes = base64.urlsafe_b64decode(str(parsed_args.initial_base64_settings) + "===")
        settings_dict = json.loads(decoded_settings)
        validate_settings(settings_dict)

    if parsed_args.expected_software_version:
        if not parsed_args.skip_software_version_verification:
            shared_values_dict["expected_software_version"] = parsed_args.expected_software_version

    log_file_uuid = settings_dict.get("log_file_uuid", uuid.uuid4())
    shared_values_dict["log_file_uuid"] = log_file_uuid

    shared_values_dict["stored_customer_ids"] = parsed_args.stored_customer_ids

    computer_name_hash = hashlib.sha512(socket.gethostname().encode(encoding="UTF-8")).hexdigest()
    shared_values_dict["computer_name_hash"] = computer_name_hash

    shared_values_dict["beta_2_mode"] = parsed_args.beta_2_mode
    if shared_values_dict["beta_2_mode"]:
        shared_values_dict["stimulation_running"] = False
        shared_values_dict["stimulation_protocols"] = None

    msg = f"Log File UUID: {log_file_uuid}"
    logger.info(msg)
    msg = f"SHA512 digest of Computer Name {computer_name_hash}"
    logger.info(msg)

    if parsed_args.debug_test_post_build:
        print(f"Successfully opened and closed application v{CURRENT_SOFTWARE_VERSION}.")  # allow-print
        return

    shared_values_dict["system_status"] = SERVER_INITIALIZING_STATE
    if parsed_args.port_number is not None:
        shared_values_dict["server_port_number"] = parsed_args.port_number
    global _server_port_number  # pylint:disable=global-statement,invalid-name# Eli (12/8/20) this is deliberately setting a global variable
    _server_port_number = shared_values_dict.get("server_port_number", DEFAULT_SERVER_PORT_NUMBER)
    msg = f"Using server port number: {_server_port_number}"
    logger.info(msg)

    if is_port_in_use(_server_port_number):
        raise LocalServerPortAlreadyInUseError(_server_port_number)

    if settings_dict:
        update_shared_dict(shared_values_dict, convert_request_args_to_config_dict(settings_dict))
    _log_system_info()
    logger.info("Spawning subprocesses")

    process_manager = _create_process_manager(shared_values_dict)
    process_manager.set_logging_level(log_level)
    object_access_for_testing["process_manager"] = process_manager
    object_access_for_testing["values_to_share_to_server"] = shared_values_dict

    process_manager.create_processes()
    if start_subprocesses:
        msg = f"Main Process PID: {getpid()}"
        logger.info(msg)
        subprocess_id_dict = process_manager.start_processes()
        for subprocess_name, pid in subprocess_id_dict.items():
            msg = f"{subprocess_name} PID: {pid}"
            logger.info(msg)

    boot_up_after_processes_start = not parsed_args.skip_mantarray_boot_up and not parsed_args.beta_2_mode
    load_firmware_file = not parsed_args.no_load_firmware and not parsed_args.beta_2_mode

    the_lock = threading.Lock()
    process_monitor_error_queue: Queue[str] = queue.Queue()  # pylint: disable=unsubscriptable-object

    process_monitor_thread = MantarrayProcessesMonitor(
        shared_values_dict,  # TODO Tanner (8/23/21): should eventually refactor so that process_monitor gets this from process_manager
        process_manager,
        process_monitor_error_queue,
        the_lock,
        boot_up_after_processes_start=boot_up_after_processes_start,
        load_firmware_file=load_firmware_file,
    )

    object_access_for_testing["process_monitor"] = process_monitor_thread
    logger.info("Starting process monitor thread")
    process_monitor_thread.start()
    logger.info("Starting Flask SocketIO")
    _, host, _ = get_server_address_components()

    data_queue_to_server = process_manager.queue_container().get_data_queue_to_server()

    if start_flask:

        def data_sender() -> None:  # pragma: no cover  # Tanner (6/21/21): code coverage can't follow into start_background_task where this function is run
            while True:
                try:
                    item = data_queue_to_server.get(timeout=0.0001)
                except Empty:
                    continue
                socketio.emit(item["data_type"], item["data_json"])

        object_access_for_testing["data_sender"] = data_sender

        socketio.start_background_task(data_sender)
        socketio.run(
            flask_app,
            host=host,
            port=_server_port_number,
            log=logger,
            log_output=True,
            log_format='%(client_ip)s - - "%(request_line)s" %(status_code)s %(body_length)s - %(wall_seconds).6f',
        )

    logger.info("Server shut down, about to stop processes")
    process_monitor_thread.soft_stop()
    process_monitor_thread.join()
    logger.info("Process monitor shut down")
    logger.info("Program exiting")
    # Tanner (8/23/21): unsure what this line was trying to achieve, so commenting it out for now until if/when problems arise
    # process_manager.set_logging_level(logging.INFO)  # Eli (3/12/20) - this is really hacky...better solution is to allow setting the process manager back to its normal state
