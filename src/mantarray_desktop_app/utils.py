# -*- coding: utf-8 -*-
"""Misc utility functions."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from typing import Dict
from typing import Optional

from flatten_dict import flatten
from flatten_dict import unflatten
from immutable_data_validation import is_uuid
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import is_frozen_as_exe

from .constants import CURI_BIO_ACCOUNT_UUID
from .constants import CURI_BIO_USER_ACCOUNT_ID
from .constants import CURRENT_SOFTWARE_VERSION
from .exceptions import ImproperlyFormattedCustomerAccountUUIDError
from .exceptions import ImproperlyFormattedUserAccountUUIDError
from .exceptions import RecordingFolderDoesNotExistError

logger = logging.getLogger(__name__)


def validate_settings(settings_dict: Dict[str, Any]) -> None:
    """Check if potential new user configuration settings are valid.

    Args:
        settings_dict: dictionary containing the new user configuration settings.
    """
    customer_account_uuid = settings_dict.get("customer_account_uuid", None)
    user_account_uuid = settings_dict.get("user_account_uuid", None)
    recording_directory = settings_dict.get("recording_directory", None)

    if customer_account_uuid is not None:
        if customer_account_uuid == "curi":
            customer_account_uuid = str(CURI_BIO_ACCOUNT_UUID)
            user_account_uuid = str(CURI_BIO_USER_ACCOUNT_ID)
        elif not is_uuid(customer_account_uuid):
            raise ImproperlyFormattedCustomerAccountUUIDError(customer_account_uuid)
    if user_account_uuid is not None:
        if not is_uuid(user_account_uuid):
            raise ImproperlyFormattedUserAccountUUIDError(user_account_uuid)
    if recording_directory is not None:
        if not os.path.isdir(recording_directory):
            raise RecordingFolderDoesNotExistError(recording_directory)


def convert_request_args_to_config_dict(request_args: Dict[str, Any]) -> Dict[str, Any]:
    """Convert from request/CLI inputs to standard dictionary format.

    Args should be validated before being passed to this function.
    """
    customer_account_uuid = request_args.get("customer_account_uuid", None)
    user_account_uuid = request_args.get("user_account_uuid", None)
    recording_directory = request_args.get("recording_directory", None)
    out_dict: Dict[str, Any] = {"config_settings": {}}
    if customer_account_uuid is not None:
        if customer_account_uuid == "curi":
            customer_account_uuid = str(CURI_BIO_ACCOUNT_UUID)
            user_account_uuid = str(CURI_BIO_USER_ACCOUNT_ID)
        out_dict["config_settings"]["Customer Account ID"] = customer_account_uuid
    if user_account_uuid is not None:
        out_dict["config_settings"]["User Account ID"] = user_account_uuid
    if recording_directory is not None:
        out_dict["config_settings"]["Recording Directory"] = recording_directory
    return out_dict


def attempt_to_get_recording_directory_from_new_dict(  # pylint:disable=invalid-name # Eli (12/8/20) I know this is a long name, can try and shorten later
    new_dict: Dict[str, Any]
) -> Optional[str]:
    """Attempt to get the recording directory from the dict of new values."""
    try:
        directory = new_dict["config_settings"]["Recording Directory"]
    except KeyError:
        return None
    if not isinstance(directory, str):
        raise NotImplementedError("The directory should always be a string")
    return directory


def update_shared_dict(
    shared_values_dict: Dict[str, Any], new_info_dict: Dict[str, Any]
) -> None:
    """Update the dictionary and log any critical changes.

    Because this is a nested dictionary, make sure to flatten and then
    unflatten it to ensure full updates.
    """
    flattened_new_dict = flatten(new_info_dict)
    flattened_shared_dict = flatten(shared_values_dict)
    flattened_shared_dict.update(flattened_new_dict)
    updated_shared_dict = unflatten(flattened_shared_dict)
    shared_values_dict.update(updated_shared_dict)

    new_recording_directory: Optional[
        str
    ] = attempt_to_get_recording_directory_from_new_dict(new_info_dict)

    if new_recording_directory is not None:
        scrubbed_recordings_dir = redact_sensitive_info_from_path(
            new_recording_directory
        )
        msg = f"Using directory for recording files: {scrubbed_recordings_dir}"
        logger.info(msg)


def redact_sensitive_info_from_path(file_path: Optional[str]) -> Optional[str]:
    """Scrubs username from file path to protect sensitive info."""
    if file_path is None:
        return None
    split_path = re.split(r"(Users\\)(.*)(\\AppData)", file_path)
    if len(split_path) != 5:
        return "*" * len(file_path)
    scrubbed_path = split_path[0] + split_path[1]
    scrubbed_path += "*" * len(split_path[2])
    scrubbed_path += split_path[3] + split_path[4]
    return scrubbed_path


def get_current_software_version() -> str:
    """Return the current software version.

    Returns the constant if running in a bundle. Otherwise reads it from
    package.json
    """
    if is_frozen_as_exe():
        return CURRENT_SOFTWARE_VERSION
    path_to_package_json = os.path.join(
        get_current_file_abs_directory(), os.pardir, os.pardir, "package.json"
    )
    with open(path_to_package_json) as in_file:
        parsed_json = json.load(in_file)
        version = parsed_json["version"]
        if not isinstance(version, str):
            raise NotImplementedError(
                f"The version in package.json should always be a string. It was: {version}"
            )
        return version
