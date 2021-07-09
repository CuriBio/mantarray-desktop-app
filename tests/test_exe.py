# -*- coding: utf-8 -*-
import os
import subprocess
import time

from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import wait_for_subprocesses_to_start
import pytest
import requests
from stdlib_utils import confirm_port_in_use
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import is_system_windows

PATH_OF_CURRENT_FILE = get_current_file_abs_directory()


@pytest.mark.slow
@pytest.mark.only_exe
def test_exe_can_access_xem_script_and_firmware_folders():
    exe_file_name = "mantarray-flask.exe" if is_system_windows() else "mantarray-flask"
    subprocess_args = [os.path.join("dist-python", "mantarray-flask", exe_file_name)]

    sub_process = subprocess.Popen(  # pylint: disable=consider-using-with  # TODO Tanner (6/11/21): should eventually investigate using context manager (with) here
        subprocess_args
    )
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=10)
    wait_for_subprocesses_to_start()
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 30) is True

    response = requests.get(f"{get_api_endpoint()}start_calibration")
    assert response.status_code == 200

    assert system_state_eventually_equals(CALIBRATED_STATE, 30) is True

    response = requests.get(f"{get_api_endpoint()}shutdown")
    assert response.status_code == 200

    time.sleep(7)  # wait for everything to fully shut down

    # assert that the subprocesses closed with an exit code of 0 (no error)
    assert sub_process.poll() == 0
