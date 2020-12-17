# -*- coding: utf-8 -*-
import os
import sys
from typing import List

import boto3
from botocore.config import Config

if os != sys:  # need to protect the #nosec comment from being deleted by zimports
    import subprocess  # nosec # B404 security implications are considered


def download_vcn() -> None:
    s3_resource = boto3.resource("s3")
    bucket = s3_resource.Bucket("build-resources-x92toe")
    bucket.download_file("generic/windows/vcn-v0.8.3-windows-amd64.exe", "vcn.exe")


def _set_vcn_environment_parameters() -> None:
    my_config = Config(  # based on https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html
        region_name="us-east-1",
        signature_version="v4",
        retries={"max_attempts": 10, "mode": "standard"},
    )

    ssm_client = boto3.client("ssm", config=my_config)
    for param_name, environ_name in (
        ("vcn_notarization_password", "vcn_notarization_password"),
        ("vcn_password", "vcn_password"),
        ("vcn_username", "VCN_USER"),
    ):
        # Eli (12/16/20): ran into odd permission errors trying to use `get_parameter`, so switching to `get_parameters`
        value = ssm_client.get_parameters(
            Names=[f"/CodeBuild/general/{param_name}"], WithDecryption=True
        )["Parameters"][0]["Value"]
        os.environ[environ_name.upper()] = value


def _run_subprocess(args: List[str]) -> None:
    print(f"About to run with args: {args}")  # allow-print
    results = subprocess.run(args)  # nosec # B603 shell is false, but input is secure
    if results.returncode != 0:
        sys.exit(results.returncode)


def login() -> None:
    _set_vcn_environment_parameters()
    _run_subprocess(["vcn.exe", "login"])


def notarize(file_path: str) -> None:
    _set_vcn_environment_parameters()
    _run_subprocess(["vcn.exe", "notarize", file_path, "--silent", "--public"])


def authenticate(file_path: str) -> None:
    _set_vcn_environment_parameters()
    _run_subprocess(["vcn.exe", "authenticate", file_path])


if __name__ == "__main__":
    first_arg = sys.argv[1]
    if first_arg == "download":
        download_vcn()
    elif first_arg == "login":
        login()
    elif first_arg == "notarize":
        notarize(sys.argv[2])
    elif first_arg == "authenticate":
        authenticate(sys.argv[2])
