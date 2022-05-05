# -*- coding: utf-8 -*-
"""Handling upload of data files."""
import base64
import hashlib
import os
from time import sleep
from typing import Any
from typing import Dict
import zipfile

from mantarray_desktop_app.exceptions import CloudAnalysisJobFailedError
import requests

from .constants import CLOUD_API_ENDPOINT
from .constants import CLOUD_PULSE3D_ENDPOINT


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


def get_access_token(customer_id: str, user_name: str, password: str) -> str:
    """Generate user specific token.

    Args:
        customer_id: current user's customer account id.
        user_name: current user.
        password: current user's password.
    """
    login_response = requests.post(
        f"https://{CLOUD_API_ENDPOINT}/users/login",
        json={"customer_id": customer_id, "username": user_name, "password": password},
    )
    access_token: str = login_response.json()["access_token"]
    return access_token


def get_upload_details(
    access_token: str,
    file_name: str,
    customer_id: str,
    file_md5: str,
    upload_type: str,
) -> Dict[Any, Any]:
    """Post to generate post specific parameters.

    Args:
        access_token: user specific token.
        file_name: zip file name.
        customer_id: current customer account id for file to upload.
        file_md5: md5 hash.
        upload_type: determines if it's a log file or recording that is being uploaded.
    """
    route = "uploads" if upload_type == "recording" else "logs"
    upload_response = requests.post(
        f"https://{CLOUD_PULSE3D_ENDPOINT}/{route}",
        json={"filename": file_name, "md5s": file_md5, "customer_id": customer_id},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    upload_details: Dict[Any, Any] = upload_response.json()
    return upload_details


def upload_file_to_s3(file_path: str, file_name: str, upload_details: Dict[Any, Any]) -> None:
    """Post to upload zip file to s3 using post specific parameters.

    Args:
        file_path: path to zip file.
        file_name: zip file name.
        upload_details: dictionary containing post specific parameters.
    """
    with open(file_path, "rb") as file_to_upload:
        files = {"file": (file_name, file_to_upload)}
        requests.post(upload_details["params"]["url"], data=upload_details["params"]["fields"], files=files)


def start_analysis(access_token: str, upload_id: str) -> str:
    """Post to start cloud analysis of an uploaded file.

    Args:
        upload_id: UUID str of uploaded file

    Returns:
        The ID of the job created to run analysis on the uploaded file
    """
    jobs_response = requests.post(
        f"https://{CLOUD_PULSE3D_ENDPOINT}/jobs",
        json={"upload_id": upload_id},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    jobs_id: str = jobs_response.json()["id"]
    return jobs_id


def get_analysis_status(access_token: str, job_id: str) -> Dict[str, str]:
    response = requests.get(
        f"https://{CLOUD_PULSE3D_ENDPOINT}/jobs",
        params={"job_ids": job_id},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    job_dict: Dict[str, str] = response.json()["jobs"][0]

    if error := job_dict.get("error"):
        raise CloudAnalysisJobFailedError(error)
    return job_dict


def download_analysis_from_s3(presigned_url: str, file_name: str) -> None:
    """Get analysis from s3 and download to local directory.

    Args:
        presigned_url: URL to get s3 analysis.
        file_name: file name to write to locally.
    """
    download_response = requests.get(presigned_url)
    file_name_no_ext = os.path.splitext(file_name)[0]
    download_file_path = os.path.join(os.path.expanduser("~"), "downloads", f"{file_name_no_ext}.xlsx")

    with open(download_file_path, "wb") as content:
        content.write(download_response.content)


def uploader(
    file_directory: str,
    file_name: str,
    zipped_recordings_dir: str,
    customer_id: str,
    user_name: str,
    password: str,
) -> None:
    """Initiate and handle file upload process.

    Args:
        file_directory: root recording directory.
        file_name: sub directory for h5 files to create zip file name.
        zipped_recordings_dir: static zipped recording directory to store zip files.
        customer_id: current customer's account id.
        user_name: current user's account id.
        password: current user's account password.
    """
    upload_type = "recording" if "/recordings" in file_directory else "logs"

    file_path = os.path.join(os.path.abspath(file_directory), file_name)
    # Failed uploads will call function with zip file, not directory of well data
    if os.path.isdir(file_path):
        if upload_type == "recording":
            # store zipped files under user specific sub dir of static zipped dir
            user_recordings_dir = os.path.join(zipped_recordings_dir, user_name)
            if not os.path.exists(user_recordings_dir):
                os.makedirs(user_recordings_dir)
            dir_to_store_zips = user_recordings_dir
        else:
            # store zipped files in whatever dir was given
            dir_to_store_zips = zipped_recordings_dir

        zipped_file_path = create_zip_file(file_directory, file_name, dir_to_store_zips)
        file_name += ".zip"
    else:
        zipped_file_path = file_path

    access_token = get_access_token(customer_id, user_name, password)
    file_md5 = get_file_md5(zipped_file_path)
    upload_details = get_upload_details(access_token, file_name, customer_id, file_md5, upload_type)
    upload_file_to_s3(zipped_file_path, file_name, upload_details)

    if upload_type == "logs":
        return

    analysis_job_id = start_analysis(access_token, upload_details["id"])
    # wait for analysis to complete
    while (status_dict := get_analysis_status(access_token, analysis_job_id))["status"] == "pending":
        sleep(5)

    download_analysis_from_s3(status_dict["url"], file_name)
