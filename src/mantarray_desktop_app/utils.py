# -*- coding: utf-8 -*-
"""Misc utility functions."""
from __future__ import annotations

import logging
import os
from typing import Any
from typing import Dict

from immutable_data_validation import is_uuid

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


def update_shared_dict(
    shared_values_dict: Dict[str, Any], new_info_dict: Dict[str, Any]
) -> None:
    """Update the dictionary and log any critical changes."""
    shared_values_dict.update(new_info_dict)
