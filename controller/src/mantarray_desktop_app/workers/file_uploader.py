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

from ..constants import CLOUD_PULSE3D_ENDPOINT
from ..exceptions import CloudAnalysisJobFailedError
from ..exceptions import PresignedUploadFailedError
from ..exceptions import RecordingUploadMissingPulse3dVersionError
from ..utils.web_api import WebWorker


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
        for file_path in file_paths:
            zip_file.write(file_path, os.path.basename(file_path))

    return zipped_file_path


def get_file_md5(file_path: str) -> str:
    """Generate md5 of zip file.

    Args:
        file_path: path to zip file.
    """
    with open(file_path, "rb") as file_to_read:
        contents = file_to_read.read()
        md5 = hashlib.md5(  # nosec B324 B303 # Tanner (2/4/21): Bandit blacklisted this hash function for cryptographic security reasons that do not apply to the desktop app.
            contents
        ).digest()
        md5s = base64.b64encode(md5).decode()
    return md5s


def get_upload_details(access_token: str, file_name: str, file_md5: str, upload_type: str) -> Dict[Any, Any]:
    """Post to generate post specific parameters.

    Args:
        access_token: user specific token.
        file_name: zip file name.
        file_md5: md5 hash.
        upload_type: determines if it's a log file or recording that is being uploaded.
    """
    # Tanner (7/5/22): sending mantarray as upload type for both kinds of uploads for now
    route = "uploads" if upload_type == "recording" else "logs"
    response = requests.post(
        f"https://{CLOUD_PULSE3D_ENDPOINT}/{route}",
        json={"filename": file_name, "md5s": file_md5, "upload_type": "pulse3d"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    upload_details: Dict[Any, Any] = response.json()
    return upload_details


def upload_file_to_s3(file_path: str, file_name: str, upload_details: Dict[Any, Any]) -> None:
    """Post to upload zip file to s3 using post specific parameters.

    Args:
        file_path: path to zip file.
        file_name: zip file name.
        upload_details: dictionary containing post specific parameters.
    """
    with open(file_path, "rb") as file_handle:
        files = {"file": (file_name, file_handle)}
        response = requests.post(
            upload_details["params"]["url"], data=upload_details["params"]["fields"], files=files
        )

    if response.status_code != 204:
        raise PresignedUploadFailedError(f"{response.status_code} {response.reason}")


def start_analysis(access_token: str, upload_id: str, version: str) -> Dict[str, Any]:
    """Post to start cloud analysis of an uploaded file.

    Args:
        access_token: the JWT used in the request
        upload_id: UUID str of uploaded file
        version: the version of pulse3d to use in the analysis job

    Returns:
        The ID of the job created to run analysis on the uploaded file
    """
    response = requests.post(
        f"https://{CLOUD_PULSE3D_ENDPOINT}/jobs",
        json={"upload_id": upload_id, "version": version},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    job_details: Dict[str, Any] = response.json()
    return job_details


def download_analysis_from_s3(presigned_url: str, file_name: str) -> None:
    """Get analysis from s3 and download to local directory.

    Args:
        presigned_url: URL to get s3 analysis.
        file_name: file name to write to locally.
    """
    response = requests.get(presigned_url)
    file_name_no_ext = os.path.splitext(file_name)[0]
    download_file_path = os.path.join(os.path.expanduser("~"), "downloads", f"{file_name_no_ext}.xlsx")

    with open(download_file_path, "wb") as content:
        content.write(response.content)


class FileUploader(WebWorker):
    """Initiate and handle file upload process.

    Args:
        file_directory: root recording directory.
        file_name: sub directory for h5 files to create zip file name.
        zipped_recordings_dir: static zipped recording directory to store zip files.
        customer_id: current user's customer account id.
        user_name: current user's account id.
        password: current user's password.
    """

    def __init__(
        self,
        file_directory: str,
        file_name: str,
        zipped_recordings_dir: str,
        customer_id: str,
        user_name: str,
        password: str,
        pulse3d_version: Optional[str] = None,
    ) -> None:
        super().__init__(customer_id, user_name, password)
        self.file_directory = file_directory
        self.file_name = file_name
        self.zipped_recordings_dir = zipped_recordings_dir
        self.upload_type = "recording" if "recording" in self.file_directory else "logs"

        # this value is only needed for recording uploads
        if self.upload_type == "recording":
            if not pulse3d_version:
                raise RecordingUploadMissingPulse3dVersionError(file_name)
            self.pulse3d_version = pulse3d_version

    def job(self) -> None:
        # TODO Tanner (5/27/22): Should probably just pass in the upload type

        file_path = os.path.join(os.path.abspath(self.file_directory), self.file_name)
        # Failed uploads will call function with zip file, not directory of well data

        if os.path.isdir(file_path):
            if self.upload_type == "recording":
                # store zipped files under user specific sub dir of static zipped dir
                user_recordings_dir = os.path.join(self.zipped_recordings_dir, self.user_name)
                if not os.path.exists(user_recordings_dir):
                    os.makedirs(user_recordings_dir)

                dir_to_store_zips = user_recordings_dir
            else:
                # store zipped files in whatever dir was given
                dir_to_store_zips = self.zipped_recordings_dir

            zipped_file_path = create_zip_file(self.file_directory, self.file_name, dir_to_store_zips)
            self.file_name += ".zip"
        else:
            zipped_file_path = file_path

        # upload file
        file_md5 = get_file_md5(zipped_file_path)
        upload_details = get_upload_details(self.tokens.access, self.file_name, file_md5, self.upload_type)

        upload_file_to_s3(zipped_file_path, self.file_name, upload_details)

        # nothing else to do if just uploading a log file
        if self.upload_type == "logs":
            return

        # start analysis and wait for analysis to complete
        job_details = start_analysis(self.tokens.access, upload_details["id"], self.pulse3d_version)

        if error_type := job_details.get("error"):
            # if job fails because job limit has been reached, error will be returned and needs to be raised
            raise CloudAnalysisJobFailedError(error_type)

        while (status_dict := self.get_analysis_status(job_details["id"]))["status"] in (
            "pending",
            "running",
        ):
            sleep(5)

        # download analysis of file
        download_analysis_from_s3(status_dict["url"], self.file_name)

    def get_analysis_status(self, job_id: str) -> Dict[str, str]:
        response = self.request_with_refresh(
            lambda: requests.get(
                f"https://{CLOUD_PULSE3D_ENDPOINT}/jobs",
                params={"job_ids": job_id},
                headers={"Authorization": f"Bearer {self.tokens.access}"},
            )
        )

        if error := response.json().get("error"):
            raise CloudAnalysisJobFailedError(error)

        job_dict: Dict[str, str] = response.json()["jobs"][0]

        if error_info := job_dict.get("error_info"):
            raise CloudAnalysisJobFailedError(error_info)

        return job_dict
