# -*- coding: utf-8 -*-
"""Handling firmware download process."""
from typing import Any
from typing import Dict
from typing import Optional

from mantarray_desktop_app.utils.web_api import get_cloud_api_tokens
import requests
from requests.exceptions import ConnectionError
from requests.models import Response

from ..constants import CLOUD_API_ENDPOINT
from ..exceptions import FirmwareDownloadError


def call_firmware_download_route(url: str, error_message: str, **kwargs: Any) -> Response:
    try:
        response = requests.get(url, **kwargs)
    except ConnectionError as e:
        raise FirmwareDownloadError(f"{error_message}") from e
    if response.status_code != 200:
        raise FirmwareDownloadError(
            f"{error_message} Status code: {response.status_code}, Reason: {response.reason}"
        )
    return response


def get_latest_firmware_versions(
    result_dict: Dict[str, Dict[str, str]],
    serial_number: str,
) -> None:
    response = requests.get(
        f"https://{CLOUD_API_ENDPOINT}/mantarray/firmware_latest", params={"serial_number": serial_number}
    )
    response_json = response.json()
    result_dict["latest_versions"].update(response_json["latest_versions"])


def download_firmware_updates(
    result_dict: Dict[str, Any],
    main_fw_version: Optional[str],
    channel_fw_version: Optional[str],
    customer_id: str,
    username: str,
    password: str,
) -> None:
    if main_fw_version is None and channel_fw_version is None:
        raise FirmwareDownloadError("No firmware types specified")
    # get access token
    access_token = get_cloud_api_tokens(customer_id, username, password).access
    # get presigned download URL(s)
    presigned_urls: Dict[str, Optional[str]] = {"main": None, "channel": None}
    for version, fw_type in ((main_fw_version, "main"), (channel_fw_version, "channel")):
        if version is not None:
            download_details = call_firmware_download_route(
                f"https://{CLOUD_API_ENDPOINT}/mantarray/firmware_download",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"firmware_version": version, "firmware_type": fw_type},
                error_message=f"Error getting presigned URL for {fw_type} firmware",
            )
            presigned_urls[fw_type] = download_details.json()["presigned_url"]
    # download firmware file(s)
    for fw_type, presigned_url in presigned_urls.items():
        if presigned_url is not None:
            download_response = call_firmware_download_route(
                presigned_url, error_message=f"Error during download of {fw_type} firmware"
            )
            result_dict[fw_type] = download_response.content