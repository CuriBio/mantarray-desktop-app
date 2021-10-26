# -*- coding: utf-8 -*-
"""Misc utility functions."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from flatten_dict import flatten
from flatten_dict import unflatten
from immutable_data_validation import is_uuid
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import is_frozen_as_exe

from .constants import CURRENT_SOFTWARE_VERSION
from .constants import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from .constants import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from .constants import SERIAL_COMM_NUM_DATA_CHANNELS
from .constants import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from .exceptions import ImproperlyFormattedCustomerAccountIDError
from .exceptions import ImproperlyFormattedCustomerAccountPasskeyError
from .exceptions import ImproperlyFormattedUserAccountUUIDError
from .exceptions import InvalidCustomerAccountIDError
from .exceptions import InvalidCustomerPasskeyError
from .exceptions import RecordingFolderDoesNotExistError

logger = logging.getLogger(__name__)


def validate_settings(settings_dict: Dict[str, Any]) -> None:
    """Check if potential new user configuration settings are valid.

    Args:
        settings_dict: dictionary containing the new user configuration settings.
    """
    customer_account_uuid = settings_dict.get("customer_account_uuid", None)
    customer_pass_key = settings_dict.get("customer_pass_key", None)
    user_account_uuid = settings_dict.get("user_account_uuid", None)
    recording_directory = settings_dict.get("recording_directory", None)

    if customer_account_uuid is not None:
        if not isinstance(customer_account_uuid, str):
            raise ImproperlyFormattedCustomerAccountIDError(customer_account_uuid)
    if customer_pass_key is not None:
        if not isinstance(customer_pass_key, str):
            raise ImproperlyFormattedCustomerAccountPasskeyError(customer_pass_key)
    if user_account_uuid is not None:
        if not is_uuid(user_account_uuid):
            raise ImproperlyFormattedUserAccountUUIDError(user_account_uuid)
    if recording_directory is not None:
        if not os.path.isdir(recording_directory):
            raise RecordingFolderDoesNotExistError(recording_directory)


def validate_customer_credentials(request_args: Dict[str, Any], shared_values_dict: Dict[str, Any]) -> None:
    """Check if new customer credentials exist in stored pairs.

    Args:
        request_args: dictionary containing the new user configuration settings.
        shared_values_dict: dictionary containing stored customer settings.
    """
    customer_account_uuid = request_args.get("customer_account_uuid", None)
    customer_pass_key = request_args.get("customer_pass_key", None)
    stored_customer_ids = shared_values_dict["stored_customer_settings"]["stored_customer_ids"]

    if customer_account_uuid is not None:
        if customer_account_uuid in stored_customer_ids:
            valid_creds = stored_customer_ids[customer_account_uuid] == customer_pass_key
            if not valid_creds:
                raise InvalidCustomerPasskeyError(customer_pass_key)
        else:
            raise InvalidCustomerAccountIDError(customer_account_uuid)


def convert_request_args_to_config_dict(request_args: Dict[str, Any]) -> Dict[str, Any]:
    """Convert from request/CLI inputs to standard dictionary format.

    Args should be validated before being passed to this function.
    """
    customer_account_uuid = request_args.get("customer_account_uuid", None)
    customer_pass_key = request_args.get("customer_pass_key", None)
    user_account_uuid = request_args.get("user_account_uuid", None)
    recording_directory = request_args.get("recording_directory", None)
    auto_upload_on_completion = request_args.get("auto_upload", None)
    auto_delete_local_files = request_args.get("auto_delete", None)

    out_dict: Dict[str, Any] = {"config_settings": {}}
    if customer_account_uuid is not None:
        out_dict["config_settings"]["customer_account_id"] = customer_account_uuid
    if customer_pass_key is not None:
        out_dict["config_settings"]["customer_pass_key"] = customer_pass_key
    if user_account_uuid is not None:
        out_dict["config_settings"]["user_account_id"] = user_account_uuid
    if recording_directory is not None:
        out_dict["config_settings"]["recording_directory"] = recording_directory
    if auto_upload_on_completion is not None:
        auto_upload_bool = auto_upload_on_completion.lower() == "true"
        out_dict["config_settings"]["auto_upload_on_completion"] = auto_upload_bool
    if auto_delete_local_files is not None:
        auto_delete_bool = auto_delete_local_files.lower() == "true"
        out_dict["config_settings"]["auto_delete_local_files"] = auto_delete_bool

    return out_dict


def attempt_to_get_recording_directory_from_new_dict(  # pylint:disable=invalid-name # Eli (12/8/20) I know this is a long name, can try and shorten later
    new_dict: Dict[str, Any]
) -> Optional[str]:
    """Attempt to get the recording directory from the dict of new values."""
    try:
        directory = new_dict["config_settings"]["recording_directory"]
    except KeyError:
        return None
    if not isinstance(directory, str):
        raise NotImplementedError("The directory should always be a string")
    return directory


def update_shared_dict(shared_values_dict: Dict[str, Any], new_info_dict: Dict[str, Any]) -> None:
    """Update the dictionary and log any critical changes.

    Because this is a nested dictionary, make sure to flatten and then
    unflatten it to ensure full updates.
    """
    flattened_new_dict = flatten(new_info_dict)
    flattened_shared_dict = flatten(shared_values_dict)
    flattened_shared_dict.update(flattened_new_dict)
    updated_shared_dict = unflatten(flattened_shared_dict)
    shared_values_dict.update(updated_shared_dict)

    new_recording_directory: Optional[str] = attempt_to_get_recording_directory_from_new_dict(new_info_dict)

    if new_recording_directory is not None:
        scrubbed_recordings_dir = redact_sensitive_info_from_path(new_recording_directory)
        msg = f"Using directory for recording files: {scrubbed_recordings_dir}"
        logger.info(msg)


def redact_sensitive_info_from_path(file_path: Optional[str]) -> Optional[str]:
    """Scrubs username from file path to protect sensitive info."""
    if file_path is None:
        return None
    split_path = re.split(r"(Users\\)(.*)(\\AppData)", file_path)
    if len(split_path) != 5:
        return get_redacted_string(len(file_path))
    scrubbed_path = split_path[0] + split_path[1]
    scrubbed_path += get_redacted_string(len(split_path[2]))
    scrubbed_path += split_path[3] + split_path[4]
    return scrubbed_path


def get_redacted_string(length: int) -> str:
    return "*" * length


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


# Tanner (12/30/20): Need to support this function until barcodes are no longer accepted in /start_recording route. Creating a wrapper function `check_barcode_is_valid` to make the transition easier once this function is removed
def check_barcode_for_errors(barcode: str) -> str:
    """Return error message if barcode contains an error."""
    return _check_new_barcode(barcode) if barcode[:2] == "ML" else _check_old_barcode(barcode)


def _check_new_barcode(barcode: str) -> str:
    """Check new barcode format (ML)."""
    if len(barcode) != 12:
        return "Barcode is incorrect length"
    for char in barcode[2:]:
        if not char.isnumeric():
            return f"Barcode contains invalid character: '{char}'"
    if int(barcode[2:6]) < 2021:
        return f"Barcode contains invalid year: '{barcode[2:6]}'"
    if int(barcode[6:9]) < 1 or int(barcode[6:9]) > 366:
        return f"Barcode contains invalid Julian date: '{barcode[6:9]}'"
    kit_id_remainder = int(barcode[9:]) % 4
    if kit_id_remainder not in (0, 1):
        return f"Barcode contains invalid kit ID: '{barcode[9:]}'"
    return ""


def _check_old_barcode(barcode: str) -> str:
    """Check old barcode format."""
    if len(barcode) > 11:
        return "Barcode exceeds max length"
    if len(barcode) < 10:
        return "Barcode does not reach min length"
    for char in barcode:
        if not char.isalnum():
            return f"Barcode contains invalid character: '{char}'"
    if barcode[:2] not in ("MA", "MB", "ME"):
        return f"Barcode contains invalid header: '{barcode[:2]}'"
    if not barcode[2:4].isnumeric():
        return f"Barcode contains invalid year: '{barcode[2:4]}'"
    if not barcode[4:7].isnumeric() or int(barcode[4:7]) < 1 or int(barcode[4:7]) > 366:
        return f"Barcode contains invalid Julian date: '{barcode[4:7]}'"
    if not barcode[7:].isnumeric():
        return f"Barcode contains nom-numeric string after Julian date: '{barcode[7:]}'"
    return ""


def check_barcode_is_valid(barcode: str) -> bool:
    error_msg = check_barcode_for_errors(barcode)
    return error_msg == ""


def _trim_barcode(barcode: str) -> str:
    """Trim the trailing 1 or 2 ASCII NULL (0x00) characters off barcode."""
    if barcode[11] != chr(0):
        return barcode
    if barcode[10] != chr(0):
        return barcode[:11]
    return barcode[:10]


def create_magnetometer_config_dict(num_wells: int) -> Dict[int, Dict[int, bool]]:
    """Create default magnetometer configuration dictionary.

    The default magnetometer state is off, represented in this dict by
    False.
    """
    magnetometer_config_dict = dict()
    for module_id in range(1, num_wells + 1):
        module_dict = dict()
        for sensor_axis_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
            module_dict[sensor_axis_id] = False
        magnetometer_config_dict[module_id] = module_dict
    return magnetometer_config_dict


def validate_magnetometer_config_keys(
    magnetometer_config_dict: Dict[Any, Any],
    start_key: int,
    stop_key: int,
    key_name: str = "module ID",
    error_msg_addition: str = "",
) -> str:
    """Validate keys of magnetometer configuration dictionary."""
    key_iter = iter(sorted(magnetometer_config_dict.keys()))
    for expected_key in range(start_key, stop_key):
        try:
            actual_key = next(key_iter)
        except StopIteration:
            return f"Configuration dictionary is missing {key_name} {expected_key}" + error_msg_addition
        if actual_key < expected_key:
            return f"Configuration dictionary has invalid {key_name} {actual_key}" + error_msg_addition
        if actual_key > expected_key:
            return f"Configuration dictionary is missing {key_name} {expected_key}" + error_msg_addition

        item = magnetometer_config_dict[actual_key]
        if isinstance(item, dict):
            error_msg = validate_magnetometer_config_keys(
                item,
                0,
                SERIAL_COMM_NUM_DATA_CHANNELS,
                key_name="channel ID",
                error_msg_addition=f" for {key_name} {actual_key}",
            )
            if not error_msg:
                continue
            return error_msg
    try:
        invalid_key = next(key_iter)
        return f"Configuration dictionary has invalid {key_name} {invalid_key}" + error_msg_addition
    except StopIteration:
        return ""


def get_active_wells_from_config(magnetometer_config: Dict[int, Dict[int, bool]]) -> List[int]:
    """Get ascending list of enabled wells.

    Enabled wells are those who have at least one channel enabled in the
    given magnetometer configuration dictionary.
    """
    active_well_list = []
    for module_id, config_dict in magnetometer_config.items():
        if not any(config_dict.values()):
            continue
        well_idx = SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id]
        active_well_list.append(well_idx)
    return sorted(active_well_list)


def create_active_channel_per_sensor_list(  # pylint: disable=invalid-name  # Tanner (5/27/21): it's a little long but descriptive
    magnetometer_config: Dict[int, Dict[int, bool]]
) -> List[int]:
    """Convert magnetometer configuration dictionary to list.

    Contains one entry per sensor with at least one channel enabled.
    Each entry is the number of channels enabled for that sensor.

    Reflects structure of data packet body for given configuration.
    """
    active_sensor_channels_list = []
    for config_dict in magnetometer_config.values():
        config_values = list(config_dict.values())
        for sensor_base_idx in range(0, SERIAL_COMM_NUM_DATA_CHANNELS, SERIAL_COMM_NUM_CHANNELS_PER_SENSOR):
            num_channels_for_sensor = sum(
                config_values[sensor_base_idx : sensor_base_idx + SERIAL_COMM_NUM_CHANNELS_PER_SENSOR]
            )
            if num_channels_for_sensor == 0:
                continue
            active_sensor_channels_list.append(num_channels_for_sensor)
    return active_sensor_channels_list


def create_sensor_axis_dict(module_config: Dict[int, bool]) -> Dict[str, List[str]]:
    sensor_axis_dict: Dict[str, List[str]] = dict()
    for sensor, axis_dict in SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE.items():
        axis_list = []
        for axis, channel_id in axis_dict.items():
            if module_config[channel_id]:
                axis_list.append(axis)
        if axis_list:
            sensor_axis_dict[sensor] = axis_list
    return sensor_axis_dict


# TODO Tanner (6/2/21): move this to stdlib_utils
def sort_nested_dict(dict_to_sort: Dict[Any, Any]) -> Dict[Any, Any]:
    dict_to_sort = dict(sorted(dict_to_sort.items()))
    for key, value in dict_to_sort.items():
        if isinstance(value, dict):
            dict_to_sort[key] = sort_nested_dict(value)
    return dict_to_sort
