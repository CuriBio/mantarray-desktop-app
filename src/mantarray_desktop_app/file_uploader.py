# -*- coding: utf-8 -*-
"""Handling upload of data files."""
import base64
import hashlib
import threading
from typing import Any
from typing import Dict
from typing import Optional

import requests


def get_file_md5(file_name: str) -> str:
    with open(file_name, "r") as file_to_read:
        contents = file_to_read.read()
        md5 = hashlib.md5(  # nosec B303 # Tanner (2/4/21): Bandit blacklisted this hash function for cryptographic security reasons that do not apply to the desktop app.
            contents.encode()
        ).digest()
        md5s = base64.b64encode(md5).decode()
    return md5s


def get_access_token(customer_account_id: str, password: str) -> str:
    get_auth_response = requests.post(
        "https://<TODO>.execute-api.us-east-1.amazonaws.com/prod-lambda-gw-stage/get_auth",
        json={"username": customer_account_id, "password": password},
    )
    # TODO check response
    get_auth_response_json = get_auth_response.json()
    access_token: str = get_auth_response_json["access_token"]
    return access_token


def get_upload_details(access_token: str, file_name: str, file_md5: str) -> Dict[Any, Any]:
    sdk_upload_response = requests.post(
        "https://<TODO>.execute-api.us-east-1.amazonaws.com/prod-lambda-gw-stage/sdk_upload",
        json={"file_name": file_name},
        headers={"Authorization": f"Bearer {access_token}", "Content-MD5": file_md5},
    )
    upload_details: Dict[Any, Any] = sdk_upload_response.json()
    # TODO check response
    return upload_details


def upload_file_to_s3(file_name: str, upload_details: Dict[Any, Any]) -> None:
    with open(file_name, "rb") as file_to_upload:
        files = {"file": (file_name, file_to_upload)}
        requests.post(
            upload_details["presigned_params"]["url"],
            data=upload_details["presigned_params"]["fields"],
            files=files,
        )
        # TODO check response


def uploader(file_name: str, customer_account_id: str, password: str) -> None:
    access_token = get_access_token(customer_account_id, password)

    file_md5 = get_file_md5(file_name)
    upload_details = get_upload_details(access_token, file_name, file_md5)

    upload_file_to_s3(file_name, upload_details)

    # upload_id = upload_details["upload_id"]
    # status_response = requests.get(
    #     f"https://<TODO>.execute-api.us-east-1.amazonaws.com/prod-lambda-gw-stage/get_sdk_status?upload_id={upload_id}",
    #     headers={"Authorization": f"Bearer {access_token}"}
    # )
    # # TODO check response
    # status_response_json = status_response.json()
    # status = status_response_json


class ErrorCatchingThread(threading.Thread):
    """Catch errors to make available to caller thread."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.error: Optional[Exception] = None

    def run(self) -> None:
        try:
            super().run()
        except Exception as e:  # pylint: disable=broad-except  # Tanner (10/8/21): deliberately trying to catch all exceptions here
            self.error = e
