# -*- coding: utf-8 -*-
"""Handling upload of data files."""
import base64
import hashlib
import os
from threading import Thread
from typing import Any
from typing import Dict
from typing import Optional
import zipfile

import requests


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
        password: current cusotmer account password.
    """
    get_auth_response = requests.post(
        "https://<TODO>.execute-api.us-east-1.amazonaws.com/prod-lambda-gw-stage/get_auth",
        json={"username": customer_account_id, "password": password},
    )

    get_auth_response_json = get_auth_response.json()
    access_token: str = get_auth_response_json["access_token"]
    return access_token


def get_upload_details(access_token: str, file_name: str, file_md5: str) -> Dict[Any, Any]:
    """Post to generate presigned parameters.

    Args:
        access_token: user specific token.
        file_name: zip file name.
        file_md5: md5 hash.
    """
    sdk_upload_response = requests.post(
        "https://<TODO>.execute-api.us-east-1.amazonaws.com/prod-lambda-gw-stage/sdk_upload",
        json={"file_name": file_name},
        headers={"Authorization": f"Bearer {access_token}", "Content-MD5": file_md5},
    )

    upload_details: Dict[Any, Any] = sdk_upload_response.json()
    return upload_details


def upload_file_to_s3(file_path: str, file_name: str, upload_details: Dict[Any, Any]) -> None:
    """Post and upload zip file to s3 using presigned parameters.

    Args:
        file_path: path to zip file.
        file_name: zip file name.
        upload_details: dictionary containing presigned parameters.
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
    for root, directories, files in os.walk(file_directory_path):
        for filename in files:
            # Create the full file path by using OS module and checking if h5
            h5_file_path = os.path.join(root, filename)
            # if h5py.is_hdf5(h5_file_path):
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
        f"https://<TODO>.execute-api.us-east-1.amazonaws.com/prod-lambda-gw-stage/get_sdk_status?upload_id={upload_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    response = status_response.json()
    upload_status: str = response["status"]
    return upload_status


def uploader(
    file_directory: str,
    file_name: str,
    zipped_recordings_dir: str,
    customer_account_id: str,
    password: str,
) -> str:
    """Initiate and handle file upload process.

    Args:
        file_directory: root recording directory.
        file_name: sub directory for h5 files to create zip file name.
        zipped_recordings_dir: static zipped recording directory to store zip files.
        customer_account_id: current customer account id for cognito user.
        password: current customer account password for cognito user.
    """
    file_path = os.path.join(os.path.abspath(file_directory), file_name)
    # Failed uploads will call function with zip file, not directory of well data
    if os.path.isdir(file_path):
        # store zipped files under customer specific and static zipped directory
        customer_zipped_recordings_dir = os.path.join(zipped_recordings_dir, customer_account_id)
        zipped_file_path = create_zip_file(file_directory, file_name, customer_zipped_recordings_dir)
        file_name = f"{file_name}.zip"
    else:
        zipped_file_path = file_path

    access_token = get_access_token(customer_account_id, password)
    file_md5 = get_file_md5(file_path=zipped_file_path)
    upload_details = get_upload_details(access_token=access_token, file_name=file_name, file_md5=file_md5)
    upload_file_to_s3(file_path=zipped_file_path, file_name=file_name, upload_details=upload_details)
    upload_status: str = get_sdk_status(access_token=access_token, upload_details=upload_details)

    return upload_status


class ErrorCatchingThread(Thread):
    """Catch errors to make available to caller thread."""

    def __init__(self, target: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.result: Optional[str] = None
        self.error: Optional[Exception] = None
        self._target: Any = target
        self._args: Optional[Any]
        self._kwargs: Optional[Any]

    def run(self) -> None:
        if self._target is not None:
            try:
                self.result = self._target(*self._args, **self._kwargs)
                super().run()
            except Exception as e:  # pylint: disable=broad-except  # Tanner (10/8/21): deliberately trying to catch all exceptions here
                self.error = e

    # for testing
    def errors(self) -> bool:
        return self.errors is not None

    def get_upload_status(self) -> Optional[str]:
        return self.result
