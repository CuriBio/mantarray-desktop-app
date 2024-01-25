# -*- coding: utf-8 -*-
"""Handling firmware compatibility checking and downloading."""
import os
from typing import Any
from typing import Dict
from typing import Optional

from mantarray_desktop_app.utils.web_api import get_cloud_api_tokens
import requests
from requests.exceptions import ConnectionError
from requests.models import Response
from semver import VersionInfo

from ..constants import CLOUD_API_ENDPOINT
from ..constants import CURRENT_SOFTWARE_VERSION
from ..constants import SOFTWARE_RELEASE_CHANNEL
from ..exceptions import FirmwareAndSoftwareNotCompatibleError
from ..exceptions import FirmwareDownloadError


IS_PROD = SOFTWARE_RELEASE_CHANNEL == "prod"


def call_firmware_download_route(url: str, error_message: str, **kwargs: Any) -> Response:
    try:
        response = requests.get(url, **kwargs)
    except ConnectionError as e:
        raise FirmwareDownloadError(f"{error_message}") from e

    if response.status_code != 200:
        try:
            message = response.json()["message"]
        except Exception:
            message = response.reason
        raise FirmwareDownloadError(
            f"{error_message}. Status code: {response.status_code}, Reason: {message}"
        )

    return response


def verify_software_firmware_compatibility(main_fw_version: str) -> None:
    check_sw_response = call_firmware_download_route(
        f"https://{CLOUD_API_ENDPOINT}/mantarray/software-range/{main_fw_version}/{IS_PROD}",
        error_message="Error checking software/firmware compatibility",
    )
    range = check_sw_response.json()

    if not (range["min_sw"] <= VersionInfo.parse(CURRENT_SOFTWARE_VERSION) <= range["max_sw"]):
        raise FirmwareAndSoftwareNotCompatibleError(range["max_sw"])


def check_for_local_firmware_versions(fw_update_dir_path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isdir(fw_update_dir_path):
        return None

    fw_versions = {}

    for fw_file_name in os.listdir(fw_update_dir_path):
        if "main" in fw_file_name or "channel" in fw_file_name:
            fw_type, version = os.path.splitext(fw_file_name)[0].split("-")
            fw_versions[f"{fw_type}_fw"] = version

    if not fw_versions:
        return None

    # A version must be returned for both FW types, so if a file for one isn't present just set it to 0.0.0 so no update will occur for it
    fw_versions = {"main_fw": "0.0.0", "channel_fw": "0.0.0", **fw_versions}

    # set software version to whatever the current version is to ensure that the FW updates run
    return {"latest_versions": {"ma_sw": CURRENT_SOFTWARE_VERSION, **fw_versions}, "download": False}


def get_latest_firmware_versions(result_dict: Dict[str, Any], serial_number: str) -> None:
    get_versions_response = call_firmware_download_route(
        f"https://{CLOUD_API_ENDPOINT}/mantarray/versions/{serial_number}/{IS_PROD}",
        error_message="Error getting latest firmware versions",
    )
    result_dict.update({"latest_versions": get_versions_response.json(), "download": True})


def check_versions(
    result_dict: Dict[str, Dict[str, str]],
    serial_number: str,
    main_fw_version: str,
    firmware_update_dir_path: str,
) -> None:
    try:
        if local_firmware_versions := check_for_local_firmware_versions(firmware_update_dir_path):
            result_dict.update(local_firmware_versions)
            return
    except Exception:  # nosec B110
        # catch all errors here to avoid user error preventing the next checks
        pass

    verify_software_firmware_compatibility(main_fw_version)
    get_latest_firmware_versions(result_dict, serial_number)


def download_firmware_updates(
    result_dict: Dict[str, Any],
    main_fw_version: Optional[str],
    channel_fw_version: Optional[str],
    customer_id: Optional[str],
    username: Optional[str],
    password: Optional[str],
    fw_update_dir_path: Optional[str],
) -> None:
    if not main_fw_version and not channel_fw_version:
        raise FirmwareDownloadError("No firmware types specified")

    if fw_update_dir_path:
        for version, fw_type in ((main_fw_version, "main"), (channel_fw_version, "channel")):
            if not version:
                continue
            with open(os.path.join(fw_update_dir_path, f"{fw_type}-{version}.bin"), "rb") as fw_file:
                result_dict[fw_type] = fw_file.read()
    else:
        user_creds = {"customer_id": customer_id, "username": username, "password": password}
        if missing_creds := [cred_name for cred_name, cred_value in user_creds.items() if cred_value is None]:
            raise NotImplementedError(
                f"User creds should never be None here, however {missing_creds} are None"
            )
        # get access token
        tokens, _ = get_cloud_api_tokens(customer_id, username, password)  # type: ignore[arg-type]
        access_token = tokens.access

        # get presigned download URL(s)
        presigned_urls: Dict[str, Optional[str]] = {"main": None, "channel": None}
        for version, fw_type in ((main_fw_version, "main"), (channel_fw_version, "channel")):
            if version:
                download_details = call_firmware_download_route(
                    f"https://{CLOUD_API_ENDPOINT}/mantarray/firmware/{fw_type}/{version}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    error_message=f"Error getting presigned URL for {fw_type} firmware",
                )
                presigned_urls[fw_type] = download_details.json()["presigned_url"]

        # download firmware file(s)
        for fw_type, presigned_url in presigned_urls.items():
            if presigned_url:
                download_response = call_firmware_download_route(
                    presigned_url, error_message=f"Error during download of {fw_type} firmware"
                )
                result_dict[fw_type] = download_response.content
