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

from copy import deepcopy
import json
import logging
import os
from queue import Queue
import threading
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple

from flask import Flask
from flask import request
from flask import Response
from flask_cors import CORS
from immutabledict import immutabledict
import requests
from requests.exceptions import ConnectionError
from stdlib_utils import get_formatted_stack_trace
from stdlib_utils import InfiniteThread
from stdlib_utils import is_port_in_use
from stdlib_utils import print_exception
from stdlib_utils import put_log_message_into_queue

from .constants import DEFAULT_SERVER_PORT_NUMBER
from .constants import SYSTEM_STATUS_UUIDS
from .exceptions import LocalServerPortAlreadyInUseError
from .queue_container import MantarrayQueueContainer
from .queue_utils import _drain_queue

logger = logging.getLogger(__name__)
os.environ[
    "FLASK_ENV"
] = "DEVELOPMENT"  # this removes warnings about running the Werkzeug server (which is not meant for high volume requests, but should be fine for intra-PC communication from a single client)
flask_app = Flask(  # pylint: disable=invalid-name # yes, this is intentionally a singleton, not a constant
    __name__
)
CORS(flask_app)

_the_server_thread: "ServerThread"  # pylint: disable=invalid-name # Eli (11/3/20) yes, this is intentionally a singleton, not a constant. This is the current best guess at how to allow Flask routes to access some info they need


def get_the_server_thread() -> "ServerThread":
    """Return the singleton instance."""
    return _the_server_thread


def get_server_port_number() -> int:
    return get_the_server_thread().get_port_number()


def get_server_address_components() -> Tuple[str, str, int]:
    """Get Flask server address components.

    Returns:
        protocol (i.e. http), host (i.e. 127.0.0.1), port (i.e. 4567)
    """
    return "http", "127.0.0.1", get_server_port_number()


def get_api_endpoint() -> str:
    protocol, host, port = get_server_address_components()
    return f"{protocol}://{host}:{port}/"


def _get_values_from_process_monitor() -> Dict[str, Any]:
    return get_the_server_thread().get_values_from_process_monitor()


@flask_app.route("/system_status", methods=["GET"])
def system_status() -> Response:
    """Get the system status and other information.

    in_simulation_mode is only accurate if ui_status_code is '009301eb-625c-4dc4-9e92-1a4d0762465f'

    mantarray_serial_number and mantarray_nickname are only accurate if ui_status_code is '8e24ef4d-2353-4e9d-aa32-4346126e73e3'

    Can be invoked by: curl http://localhost:4567/system_status
    """
    shared_values_dict = _get_values_from_process_monitor()

    status = shared_values_dict["system_status"]
    status_dict = {
        "ui_status_code": str(SYSTEM_STATUS_UUIDS[status]),
        # Tanner (7/1/20): this route may be called before process_monitor adds the following values to shared_values_dict, so default values are needed
        "in_simulation_mode": shared_values_dict.get("in_simulation_mode", False),
        "mantarray_serial_number": shared_values_dict.get(
            "mantarray_serial_number", ""
        ),
        "mantarray_nickname": shared_values_dict.get("mantarray_nickname", ""),
    }

    response = Response(json.dumps(status_dict), mimetype="application/json")

    return response


@flask_app.route("/stop_server", methods=["GET"])
def stop_server() -> str:
    """Shut down Flask.

    Obtained from https://stackoverflow.com/questions/15562446/how-to-stop-flask-application-without-using-ctrl-c
    curl http://localhost:4567/stop_server
    """
    shutdown_function = request.environ.get("werkzeug.server.shutdown")
    if shutdown_function is None:
        raise NotImplementedError("Not running with the Werkzeug Server")
    logger.info("Calling function to shut down Flask Server.")
    shutdown_function()
    logger.info("Flask server successfully shut down.")
    return "Server shutting down..."


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


# TODO (Eli 11/3/20): refactor stdlib utils to separate some of the more generic multiprocessing functionality out of the "InfiniteLooping" mixin so that it could be included here without all the other things
class ServerThread(InfiniteThread):
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
        if lock is None:
            lock = threading.Lock()

        super().__init__(fatal_error_reporter, lock=lock)
        self._queue_container = processes_queue_container
        self._to_main_queue = to_main_queue
        self._port = port
        self._logging_level = logging_level
        if values_from_process_monitor is None:
            values_from_process_monitor = dict()
        global _the_server_thread  # pylint:disable=global-statement # Eli (10/30/20): deliberately using a module-level singleton
        _the_server_thread = self
        self._values_from_process_monitor = values_from_process_monitor

    def get_port_number(self) -> int:
        return self._port

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

    def run(self) -> None:
        try:
            _, host, _ = get_server_address_components()
            self.check_port()
            flask_app.run(host=host, port=self._port)
            # Note (Eli 1/14/20) it appears with the current method of using werkzeug.server.shutdown that nothing after this line will ever be executed. somehow the program exists before returning from app.run
        except Exception as e:  # pylint: disable=broad-except # The deliberate goal of this is to catch everything and put it into the error queue
            print_exception(e, "0d6e8031-6653-47d7-8490-8c28f92494c3")
            formatted_stack_trace = get_formatted_stack_trace(e)
            self._fatal_error_reporter.put_nowait((e, formatted_stack_trace))

    def _shutdown_server(self) -> None:
        http_route = f"{get_api_endpoint()}stop_server"
        try:
            response = requests.get(http_route)
            msg = "Server has been successfully shutdown."
        except ConnectionError:
            msg = f"Server was not running on {http_route} during shutdown attempt."

        put_log_message_into_queue(
            logging.INFO, msg, self._to_main_queue, self.get_logging_level(),
        )

    def stop(self) -> None:
        self._shutdown_server()

    def soft_stop(self) -> None:
        self._shutdown_server()

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items = dict()

        queue_items["to_main"] = _drain_queue(self._to_main_queue)
        return queue_items
