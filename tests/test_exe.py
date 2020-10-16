# -*- coding: utf-8 -*-
import subprocess

from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import wait_for_subprocesses_to_start
import pytest
import requests
from stdlib_utils import confirm_port_in_use


@pytest.mark.only_exe
def test_exe_can_access_xem_script_and_firmware_folders():
    # Tanner (6/18/20): These lines are necessary when testing outside of CodeBuild because no .exe exists
    # import os
    # from stdlib_utils import get_current_file_abs_directory
    # subprocess.Popen(os.path.join(get_current_file_abs_directory(), "src", "entrypoint.py"))
    subprocess.Popen("dist-python/mantarray-flask/mantarray-flask.exe")
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=5)
    wait_for_subprocesses_to_start()
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 30) is True

    response = requests.get(f"{get_api_endpoint()}start_calibration")
    assert response.status_code == 200

    assert system_state_eventually_equals(CALIBRATED_STATE, 30) is True

    response = requests.get(f"{get_api_endpoint()}shutdown")
    assert response.status_code == 200
