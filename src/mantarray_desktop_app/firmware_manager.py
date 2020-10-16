# -*- coding: utf-8 -*-
"""Functions for managing firmware files.

These should only be called in pyinstaller.spec
"""
import os
from os import listdir
from typing import List
from typing import Tuple

from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import resource_path


def _get_firmware_dir() -> str:
    absolute_path = os.path.normcase(
        os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir)
    )
    relative_path = os.path.join("src", "firmware")
    firmware_path: str = resource_path(relative_path, base_path=absolute_path)
    return firmware_path


def sort_firmware_files() -> List[str]:
    firmware_dir = _get_firmware_dir()
    firmware_files = listdir(firmware_dir)
    return sorted(firmware_files)


def get_latest_firmware_name() -> str:
    return sort_firmware_files()[-1]


def get_latest_firmware_version() -> Tuple[int, int, int]:
    """Return a tuple of the latest firmware version."""
    firmware_file = get_latest_firmware_name()
    version_strings = firmware_file.split(".")[0].split("_")[1:]
    version_list = list()
    for ver in version_strings:
        version_list.append(int(ver))
    version_tuple = (
        version_list[0],
        version_list[1],
        version_list[2],
    )  # Tanner (6/10/20): defining the tuple this way is necessary for mypy to understand it is not a variable length tuple
    return version_tuple


def get_latest_firmware() -> str:
    """Return the latest file in the firmware folder.

    This function does not perform any validation of the name of the
    file being returned.
    """
    firmware_dir = _get_firmware_dir()
    firmware_files = listdir(firmware_dir)
    latest_firmware_file = sorted(firmware_files)[-1]
    latest_firmware_file_path = os.path.join(firmware_dir, latest_firmware_file)
    return latest_firmware_file_path
