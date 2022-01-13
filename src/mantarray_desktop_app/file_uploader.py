# -*- coding: utf-8 -*-
"""Handling upload of data files."""
import base64
import hashlib
import os
from time import sleep
from typing import Any
from typing import Dict
from typing import Optional
import zipfile

import requests

from .constants import CLOUD_API_ENDPOINT


def get_file_md5(file_path: str) -> str:
    """Generate md5 of zip file.

    Args:
        file_path: path to zip file.
    """
    with open(file_path, "rb") as file_to_read:
        contents = file_to_read.read()
        md5 = hashlib.md5(  # nosec B303 # Tanner (2/4/21): Bandit blacklisted this hash function for cryptographic security reasons that do not apply to the desktop app.
            contents
        ).digest()
        md5s = base64.b64encode(md5).decode()
    return md5s


def get_access_token(customer_account_id: str, password: str) -> str:
    """Generate user specific token.

    Args:
        customer_account_id: current customer account id.
        password: current customer account password.
    """
    get_auth_response = requests.post(
        f"https://{CLOUD_API_ENDPOINT}/get_auth",
        json={"username": customer_account_id, "password": password},
    )

    get_auth_response_json = get_auth_response.json()
    access_token: str = get_auth_response_json["access_token"]
    return access_token


def get_upload_details(
    access_token: str,
    file_name: str,
    customer_account_id: str,
    file_md5: str,
    user_account_id: Optional[str],
    upload_type: str,
) -> Dict[Any, Any]:
    """Post to generate post specific parameters.

    Args:
        access_token: user specific token.
        file_name: zip file name.
        customer_account_id: current customer account id for file to upload.
        user_account_id: current customer user_account_id for file to upload.
        file_md5: md5 hash.
        upload_type: determines if it's a log file or recording that is being uploaded.
    """
    object_key = (
        f"{customer_account_id}/{user_account_id}/{file_name}"
        if user_account_id is not None
        else f"{customer_account_id}/{file_name}"
    )

    sdk_upload_response = requests.post(
        f"https://{CLOUD_API_ENDPOINT}/sdk_upload",
        json={"file_name": object_key, "upload_type": upload_type},
        headers={"Authorization": f"Bearer {access_token}", "Content-MD5": file_md5},
    )

    upload_details: Dict[Any, Any] = sdk_upload_response.json()
    return upload_details


def upload_file_to_s3(file_path: str, file_name: str, upload_details: Dict[Any, Any]) -> None:
    """Post and upload zip file to s3 using post specific parameters.

    Args:
        file_path: path to zip file.
        file_name: zip file name.
        upload_details: dictionary containing post specific parameters.
    """
    with open(file_path, "rb") as file_to_upload:
        files = {"file": (file_name, file_to_upload)}
        requests.post(
            upload_details["presigned_params"]["url"],
            data=upload_details["presigned_params"]["fields"],
            files=files,
        )


def create_zip_file(file_directory: str, file_name: str, zipped_recordings_dir: str) -> str:
    """Walk through h5 files and writes to new zip file.

    Args:
        file_directory: root recording directory.
        file_name: sub directory for h5 files to create zip file name.
        zipped_recordings_dir: static zipped recording directory to store zip files.
    """
    file_directory_path = os.path.join(os.path.abspath(file_directory), file_name)
    file_paths = []
    # Loop errors without directories present
    for root, _, files in os.walk(file_directory_path):
        for filename in files:
            # Create the full file path by using OS module
            h5_file_path = os.path.join(root, filename)
            file_paths.append(h5_file_path)

    zipped_file_path: str = os.path.join(zipped_recordings_dir, f"{file_name}.zip")

    # writing files to a zip file
    with zipfile.ZipFile(zipped_file_path, "w") as zip_file:
        # writing each file one by one
        for file in file_paths:
            zip_file.write(file)

    return zipped_file_path


def get_sdk_status(access_token: str, upload_details: Dict[Any, Any]) -> str:
    """Request current upload status of file.

    Args:
        access_token: user specific token.
        upload_details: dictionary containing s3 upload id.
    """
    upload_id = upload_details["upload_id"]
    status_response = requests.get(
        f"https://{CLOUD_API_ENDPOINT}/get_sdk_status?upload_id={upload_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    response = status_response.json()
    upload_status: str = response["status"]
    return upload_status


def download_analysis_from_s3(presigned_url: str, file_name: str) -> None:
    """Get analysis from s3 and download to local directory.

    Args:
        presigned_url: URL to get s3 analysis.
        file_name: file name to write to locally.
    """
    file = requests.get(presigned_url)
    no_ext_file_name = file_name.split(".zip")[0]
    xlsx_file_path = os.path.join(os.path.expanduser("~"), "downloads", f"{no_ext_file_name}.xlsx")

    with open(xlsx_file_path, "wb") as content:
        content.write(file.content)


def uploader(
    file_directory: str,
    file_name: str,
    zipped_recordings_dir: str,
    customer_account_id: str,
    password: str,
    user_account_id: Optional[str] = None,
    max_num_loops: int = 0,
) -> None:
    """Initiate and handle file upload process.

    Args:
        file_directory: root recording directory.
        file_name: sub directory for h5 files to create zip file name.
        zipped_recordings_dir: static zipped recording directory to store zip files.
        customer_account_id: current customer account id for user.
        password: current customer account password for user.
        user_account_id: current user_account_id assigned for user.
        max_num_loops: to break loop in testing.
    """
    file_path = os.path.join(os.path.abspath(file_directory), file_name)
    if "/recordings" in file_directory:
        upload_type = "sdk"
    else:
        upload_type = "logs"
    # Failed uploads will call function with zip file, not directory of well data
    if os.path.isdir(file_path):
        # store zipped files under customer specific and static zipped directory
        zipped_dir = os.path.join(zipped_recordings_dir, customer_account_id)
        if not os.path.exists(zipped_dir):
            os.makedirs(zipped_dir)
        if user_account_id is not None:
            zipped_dir = os.path.join(zipped_dir, user_account_id)
            if not os.path.exists(zipped_dir):
                os.makedirs(zipped_dir)

        zipped_file_path = create_zip_file(file_directory, file_name, zipped_dir)
        file_name = f"{file_name}.zip"
    else:
        zipped_file_path = file_path

    access_token = get_access_token(customer_account_id, password)
    file_md5 = get_file_md5(file_path=zipped_file_path)
    upload_details = get_upload_details(
        access_token=access_token,
        file_name=file_name,
        customer_account_id=customer_account_id,
        user_account_id=user_account_id,
        file_md5=file_md5,
        upload_type=upload_type,
    )

    upload_file_to_s3(file_path=zipped_file_path, file_name=file_name, upload_details=upload_details)

    if upload_type == "sdk":
        num_of_loops = 0
        while True:
            upload_status: str = get_sdk_status(access_token=access_token, upload_details=upload_details)
            # for testing, had to put first to cover if max loops is already zero
            if max_num_loops > 0:
                num_of_loops += 1
                if num_of_loops >= max_num_loops:
                    break

            if "https" in upload_status:
                break

            if "error" in upload_status:
                raise Exception(upload_status)

            sleep(5)

    download_analysis_from_s3(upload_status, file_name)
