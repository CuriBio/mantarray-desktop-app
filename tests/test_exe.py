# -*- coding: utf-8 -*-
from datetime import datetime
import os
import subprocess

from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import wait_for_subprocesses_to_start
from mantarray_desktop_app.constants import DEFAULT_SERVER_PORT_NUMBER
import pytest
import requests
from stdlib_utils import confirm_port_available
from stdlib_utils import confirm_port_in_use
from stdlib_utils import is_system_windows

from .fixtures import get_generic_base64_args


def _print_with_timestamp(msg):
    print(f"[PYTEST {datetime.utcnow().strftime('%H:%M:%S.%f')}] - {msg}")  # allow-print


@pytest.mark.slow
@pytest.mark.only_exe
@pytest.mark.timeout(300)
def test_exe__can_launch_server_and_shutdown():
    # make sure all the server instances launched during the unit tests have closed
    confirm_port_available(DEFAULT_SERVER_PORT_NUMBER, timeout=10)

    exe_file_name = "mantarray-flask.exe" if is_system_windows() else "mantarray-flask"

    subprocess_args = [
        os.path.join("dist-python", "mantarray-flask", exe_file_name),
        get_generic_base64_args(),
        "--beta-2-mode",
    ]

    with subprocess.Popen(subprocess_args) as sub_process:
        _print_with_timestamp("confirm port is in use")
        confirm_port_in_use(DEFAULT_SERVER_PORT_NUMBER, timeout=30)
        _print_with_timestamp("waiting for subprocesses to start")
        wait_for_subprocesses_to_start()
        _print_with_timestamp("waiting for calibration_needed state")
        assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 30)

        _print_with_timestamp("shutting down")
        response = requests.get(f"{get_api_endpoint()}shutdown")
        assert response.status_code == 200

        _print_with_timestamp("waiting for subprocess to terminate")
        # wait for subprocess to fully terminate and make sure the exit code is 0 (no error)
        assert sub_process.wait() == 0
        _print_with_timestamp("subprocess terminated")

    _print_with_timestamp("done")
