# -*- coding: utf-8 -*-
"""Misc utility functions."""
from __future__ import annotations

import logging
import os
from typing import Any
from typing import Dict
from typing import Optional

from flatten_dict import flatten
from flatten_dict import unflatten
from immutable_data_validation import is_uuid

from .constants import CURI_BIO_ACCOUNT_UUID
from .constants import CURI_BIO_USER_ACCOUNT_ID
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
    """Perform conversion from request/CLI inputs to standard dictionary
    format."""
    validate_settings(request_args)
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

    new_recording_directory: Optional[str] = None
    try:
        new_recording_directory = new_info_dict["config_settings"][
            "Recording Directory"
        ]
    except KeyError:
        pass
    if new_recording_directory is not None:
        msg = f"Using directory for recording files: {new_recording_directory}"
        logger.info(msg)
