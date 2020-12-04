# -*- coding: utf-8 -*-
"""Utility functions for interacting with the fully running app."""
import time

import requests

from .constants import SERVER_INITIALIZING_STATE
from .constants import SYSTEM_STATUS_UUIDS
from .exceptions import SystemStartUpError
from .server import get_api_endpoint


def system_state_eventually_equals(state_name: str, timeout: int) -> bool:
    """Check if system state equals the given state before the timeout."""
    is_desired_state = False
    start = time.perf_counter()
    elapsed_time = 0.0
    while not is_desired_state and elapsed_time < timeout:
        response = requests.get(f"{get_api_endpoint()}system_status")
        is_desired_state = response.json()["ui_status_code"] == str(
            SYSTEM_STATUS_UUIDS[state_name]
        )
        if is_desired_state and response.status_code == 200:
            break
        time.sleep(0.01)  # sleep shortly between relentlessly pinging the server
        elapsed_time = time.perf_counter() - start
    return is_desired_state


def wait_for_subprocesses_to_start() -> None:
    """Wait for subprocesses to complete their start up routines.

    Raises SystemStartUpError if the system takes longer than 5 seconds
    to start up.
    """
    is_status_route_ready = False
    while not is_status_route_ready:
        response = requests.get(f"{get_api_endpoint()}system_status")
        is_status_route_ready = response.status_code == 200
        time.sleep(0.25)  # Don't just relentlessly ping the Flask server

    is_started = False
    start = time.perf_counter()
    elapsed_time = 0.0
    while not is_started and elapsed_time < 10.0:
        response = requests.get(f"{get_api_endpoint()}system_status")
        is_started = response.json()["ui_status_code"] != str(
            SYSTEM_STATUS_UUIDS[SERVER_INITIALIZING_STATE]
        )
        elapsed_time = time.perf_counter() - start
        time.sleep(0.25)  # Don't just relentlessly ping the Flask server

    if not is_started:
        raise SystemStartUpError()
