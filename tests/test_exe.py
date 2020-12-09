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

PATH_OF_CURRENT_FILE = get_current_file_abs_directory()


@pytest.mark.slow
# @pytest.mark.only_exe
def test_exe_can_access_xem_script_and_firmware_folders():
    # Eli (10/21/20): other parts of CI ensure that the EXE actually exists, so this can be run on the source file and the exe both to ensure we can catch test failures earlier
    subprocess_args = [
        os.path.join("dist-python", "mantarray-flask", "mantarray-flask.exe")
    ]
    if not os.path.isfile(subprocess_args[0]):
        path_to_entrypoint = os.path.abspath(
            os.path.join(
                get_current_file_abs_directory(), os.pardir, "src", "entrypoint.py"
            )
        )
        if not os.path.isfile(path_to_entrypoint):
            # Eli (12/9/20): the path to entrypoint.py was different somehow in Windows containers for GitHub actions, so leaving this here for future possible debugging
            print(  # allow-print
                f"\nfile path that does not exist: {path_to_entrypoint}"
            )
            print(  # allow-print
                f"path of current file: {get_current_file_abs_directory()}"
            )
            print(  # allow-print
                f"path of parent directory: {os.path.abspath(os.path.join(get_current_file_abs_directory(), os.pardir))}"
            )
            print(  # allow-print
                f"contents of parent directory: {os.listdir(os.path.abspath(os.path.join(get_current_file_abs_directory(), os.pardir)))}"
            )
            print(  # allow-print
                f'contents of src directory: {os.listdir(os.path.abspath(os.path.join(get_current_file_abs_directory(), os.pardir,"src")))}'
            )
            assert (
                "file does not exist"
                == "Apparently the path to entrypoint.py is incorrect"
            )

        subprocess_args = ["python", path_to_entrypoint]

    sub_process = subprocess.Popen(subprocess_args)
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=10)
    wait_for_subprocesses_to_start()
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 30) is True

    response = requests.get(f"{get_api_endpoint()}start_calibration")
    assert response.status_code == 200

    assert system_state_eventually_equals(CALIBRATED_STATE, 30) is True

    response = requests.get(f"{get_api_endpoint()}shutdown")
    assert response.status_code == 200

    time.sleep(5)  # wait for everything to fully shut down

    # assert that the subprocesses closed with an exit code of 0 (no error)
    assert sub_process.poll() == 0
