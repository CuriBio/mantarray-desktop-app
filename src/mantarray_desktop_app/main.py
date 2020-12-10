# -*- coding: utf-8 -*-
"""Python Backend controlling Mantarray."""
from __future__ import annotations

import argparse
import base64
import json
import logging
import multiprocessing
import os
import platform
import queue
from queue import Queue
import sys
import threading
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from stdlib_utils import configure_logging
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import resource_path

from .constants import COMPILED_EXE_BUILD_TIMESTAMP
from .constants import CURRENT_SOFTWARE_VERSION
from .constants import DEFAULT_SERVER_PORT_NUMBER
from .constants import SERVER_INITIALIZING_STATE
from .exceptions import MultiprocessingNotSetToSpawnError
from .process_manager import MantarrayProcessesManager
from .process_monitor import MantarrayProcessesMonitor
from .server import clear_the_server_thread
from .server import get_the_server_thread
from .server import ServerThreadNotInitializedError
from .utils import convert_request_args_to_config_dict
from .utils import update_shared_dict


logger = logging.getLogger(__name__)

_server_port_number = DEFAULT_SERVER_PORT_NUMBER  # pylint:disable=invalid-name # Eli (12/8/20): this is deliberately a module-level singleton


def clear_server_singletons() -> None:
    clear_the_server_thread()
    global _server_port_number  # pylint:disable=global-statement,invalid-name # Eli (12/8/20) this is deliberately setting a module-level singleton
    _server_port_number = DEFAULT_SERVER_PORT_NUMBER


def get_server_port_number() -> int:
    try:
        server_thread = get_the_server_thread()
    except (NameError, ServerThreadNotInitializedError):
        return _server_port_number
    return server_thread.get_port_number()


def _create_process_manager(
    shared_values_dict: Dict[str, Any]
) -> MantarrayProcessesManager:
    base_path = os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir)
    relative_path = "recordings"
    try:
        file_dir = shared_values_dict["config_settings"]["Recording Directory"]
    except KeyError:
        file_dir = resource_path(relative_path, base_path=base_path)

    return MantarrayProcessesManager(
        file_directory=file_dir, values_to_share_to_server=shared_values_dict
    )


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


def main(
    command_line_args: List[str],
    object_access_for_testing: Optional[Dict[str, Any]] = None,
) -> None:
    """Parse command line arguments and run."""
    if object_access_for_testing is None:
        object_access_for_testing = dict()
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
    # TODO (Eli 11/16/20): fix all Command Line Arguments to be consistently kebab-case
    parser.add_argument(
        "--port_number",
        type=int,
        help="allow manual setting of server port number",
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

    shared_values_dict: Dict[
        str, Any
    ] = dict()  # = get_shared_values_between_server_and_monitor()
    shared_values_dict["system_status"] = SERVER_INITIALIZING_STATE
    if parsed_args.port_number is not None:
        shared_values_dict["server_port_number"] = parsed_args.port_number
    global _server_port_number  # pylint:disable=global-statement,invalid-name# Eli (12/8/20) this is deliberately setting a global singleton
    _server_port_number = shared_values_dict.get(
        "server_port_number", DEFAULT_SERVER_PORT_NUMBER
    )
    msg = f"Using server port number: {_server_port_number}"
    logger.info(msg)

    if parsed_args.initial_base64_settings:
        settings_dict = json.loads(decoded_settings)
        # validate_settings(settings_dict) # TODO (Eli 12/3/20): unit test and add this
        update_shared_dict(
            shared_values_dict, convert_request_args_to_config_dict(settings_dict)
        )
    _log_system_info()
    logger.info("Spawning subprocesses and starting server thread")

    process_manager = _create_process_manager(shared_values_dict)
    process_manager.set_logging_level(log_level)
    object_access_for_testing["process_manager"] = process_manager
    object_access_for_testing["values_to_share_to_server"] = shared_values_dict
    process_manager.spawn_processes()

    boot_up_after_processes_start = not parsed_args.skip_mantarray_boot_up

    the_lock = threading.Lock()
    process_monitor_error_queue: Queue[  # pylint: disable=unsubscriptable-object
        str
    ] = queue.Queue()

    process_monitor_thread = MantarrayProcessesMonitor(
        shared_values_dict,
        process_manager,
        process_monitor_error_queue,
        the_lock,
        boot_up_after_processes_start=boot_up_after_processes_start,
    )

    object_access_for_testing["process_monitor"] = process_monitor_thread
    # set_mantarray_processes_monitor(process_monitor_thread)
    logger.info("Starting process monitor thread")
    process_monitor_thread.start()
    server_thread = process_manager.get_server_thread()
    server_thread.join()
    logger.info("Server shut down, about to stop processes")
    process_monitor_thread.soft_stop()
    process_monitor_thread.join()
    logger.info("Process monitor shut down")
    logger.info("Program exiting")
    process_manager.set_logging_level(
        logging.INFO
    )  # Eli (3/12/20) - this is really hacky...better solution is to allow setting the process manager back to its normal state
