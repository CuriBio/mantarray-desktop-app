# -*- coding: utf-8 -*-
"""Functions for managing firmware files.

These should only be called in pyinstaller.spec
"""
import os
from os import listdir
import re
from typing import List
from typing import Tuple

from semver import VersionInfo
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import resource_path

SEMVER_REGEX = re.compile(r"\_(\d+)\_(\d+)_(\d+)\.bit$")


def _get_firmware_dir() -> str:
    absolute_path = os.path.normcase(
        os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir)
    )
    relative_path = os.path.join("src", "firmware")
    firmware_path: str = resource_path(relative_path, base_path=absolute_path)
    return firmware_path


def _get_semver_from_firmware_filename(filename: str) -> VersionInfo:
    match = SEMVER_REGEX.search(filename)
    if not match:
        raise NotImplementedError(
            f"The following file in the firmware folder did not match the specified format: {filename}"
        )
    return VersionInfo.parse(f"{match.group(1)}.{match.group(2)}.{match.group(3)}")


def sort_firmware_files() -> List[str]:
    firmware_dir = _get_firmware_dir()
    firmware_files = listdir(firmware_dir)
    if (
        ".gitkeep" in firmware_files
    ):  # Eli (12/17/20): remove this file (which is in the real firmware folder) as it makes sorting by semver complicated
        firmware_files.remove(".gitkeep")
    firmware_files.sort(key=_get_semver_from_firmware_filename)
    return firmware_files


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
    firmware_files = sort_firmware_files()
    latest_firmware_file = firmware_files[-1]
    latest_firmware_file_path = os.path.join(_get_firmware_dir(), latest_firmware_file)
    return latest_firmware_file_path
