# -*- coding: utf-8 -*-
"""Utility functions for interacting with the fully running app."""
import time
from time import sleep
from typing import Optional

import requests
from requests import Response

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
        is_desired_state = response.json()["ui_status_code"] == str(SYSTEM_STATUS_UUIDS[state_name])
        if is_desired_state and response.status_code == 200:
            break
        sleep(0.5)  # Don't just relentlessly ping the Flask server
        elapsed_time = time.perf_counter() - start
    return is_desired_state


def wait_for_subprocesses_to_start() -> None:
    """Wait for subprocesses to complete their start up routines.

    Raises SystemStartUpError if the system takes longer than 20 seconds
    to start up.
    """
    start = time.perf_counter()
    elapsed_time = 0.0
    response: Optional[Response]
    while elapsed_time < 20:
        try:
            response = requests.get(f"{get_api_endpoint()}system_status")
        except requests.exceptions.ConnectionError:
            response = None
        if response is not None:
            if response.json()["ui_status_code"] != str(SYSTEM_STATUS_UUIDS[SERVER_INITIALIZING_STATE]):
                return
        elapsed_time = time.perf_counter() - start
        sleep(
            0.75
        )  # Don't just relentlessly ping the Flask server # Eli (1/4/21): 0.5 seconds of sleep still resulted in server errors sporadically, so raised it to 0.75 seconds

    raise SystemStartUpError()
