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
import requests
from requests.exceptions import ConnectionError
from stdlib_utils import get_formatted_stack_trace
from stdlib_utils import InfiniteThread
from stdlib_utils import is_port_in_use
from stdlib_utils import print_exception
from stdlib_utils import put_log_message_into_queue

from .constants import DEFAULT_SERVER_PORT_NUMBER
from .exceptions import LocalServerPortAlreadyInUseError
from .queue_utils import _drain_queue

logger = logging.getLogger(__name__)
os.environ[
    "FLASK_ENV"
] = "DEVELOPMENT"  # this removes warnings about running the Werkzeug server (which is not meant for high volume requests, but should be fine for intra-PC communication from a single client)
flask_app = Flask(  # pylint: disable=invalid-name # yes, this is intentionally a singleton, not a constant
    __name__
)
CORS(flask_app)
_shared_values_from_monitor_to_server: Dict[  # pylint: disable=invalid-name # yes, this is intentionally a singleton, not a constant
    str, Any
] = dict()


def get_shared_values_from_monitor_to_server() -> Dict[  # pylint:disable=invalid-name # yeah, it's a little long, but descriptive
    str, Any
]:
    return _shared_values_from_monitor_to_server


def get_server_port_number() -> int:
    shared_values_dict = get_shared_values_from_monitor_to_server()
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
        values_from_process_monitor: Optional[Dict[str, Any]] = None,
        port: int = DEFAULT_SERVER_PORT_NUMBER,
        logging_level: int = logging.INFO,
        lock: Optional[threading.Lock] = None,
    ) -> None:
        if lock is None:
            lock = threading.Lock()
        super().__init__(fatal_error_reporter, lock=lock)
        # super().__init__()
        self._to_main_queue = to_main_queue
        self._fatal_error_reporter = fatal_error_reporter
        self._port = port
        self._logging_level = logging_level
        if values_from_process_monitor is None:
            values_from_process_monitor = dict()
        global _shared_values_from_monitor_to_server  # pylint:disable=global-statement # Eli (10/30/20): deliberately using a module-level singleton
        _shared_values_from_monitor_to_server = values_from_process_monitor
        self._values_from_process_monitor = values_from_process_monitor

    def get_values_from_process_monitor(self) -> Dict[str, Any]:
        raise Exception("do not use this, use getcopy instead")
        return self._values_from_process_monitor

    def get_values_from_process_monitor_copy(self) -> Dict[str, Any]:
        with self._lock:  # Eli (11/3/20): still unable to test if lock was acquired.
            copied_values = deepcopy(self._values_from_process_monitor)
        return copied_values

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
