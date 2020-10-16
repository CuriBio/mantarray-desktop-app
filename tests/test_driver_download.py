# -*- coding: utf-8 -*-
import os

import pytest
from stdlib_utils import get_current_file_abs_directory


@pytest.mark.only_run_in_ci
def test_correct_driver_exe_is_downloaded__and_put_in_correct_folder():
    path_to_drivers_folder = os.path.normcase(
        os.path.join(
            os.path.dirname(get_current_file_abs_directory()), "src", "drivers",
        )
    )
    assert "FrontPanelUSB-DriverOnly-5.2.2.exe" in os.listdir(path_to_drivers_folder)
