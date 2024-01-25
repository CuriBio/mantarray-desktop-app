# -*- coding: utf-8 -*-
import argparse
import base64
import hashlib
import json
import os
import sys

import boto3
import requests


"""
To use this independently, you'll still need to generate the static files for export manually before running this script.
"""


def get_version():
    with open("package.json") as f:
        package_dict = json.loads(f.read())
        return package_dict["version"].split("-pre")[0]


def upload(bucket, parsed_args):
    for file_name in [
        os.path.join(parsed_args.build_dir, parsed_args.file),
        f"{os.path.join(parsed_args.build_dir, parsed_args.file)}.blockmap",
        f"{os.path.join(parsed_args.build_dir, parsed_args.channel)}.yml",
    ]:
        _upload_file_to_s3(bucket, f"software/mantarray/{file_name}", file_name)


def _upload_file_to_s3(bucket, key, file) -> None:
    print(f"Uploading {bucket}/{key}...")  # allow-print

    s3_client = boto3.client("s3")
    try:
        with open(file, "rb") as f:
            contents = f.read()
            md5 = hashlib.md5(contents).digest()  # nosec
            md5s = base64.b64encode(md5).decode()
            s3_client.put_object(Body=f, Bucket=bucket, Key=key, ContentMD5=md5s)

    except Exception as e:
        print(f"Failed to upload file {bucket}/{key}: {repr(e)}")  # allow-print
        raise
    else:
        print(f"Successfully uploaded {bucket}/{key}")  # allow-print


def update_cloud():
    print("Getting controller version")  # allow-print
    controller_version_no_pre = get_version()
    print(f"Found controller version: {controller_version_no_pre}")  # allow-print

    print("Logging into CB cloud")  # allow-print
    response = requests.post(
        "https://apiv2.curibio.com/users/login",
        json={
            "customer_id": "curibio",
            "username": os.environ["CLOUD_ACCOUNT_USERNAME"],
            "password": os.environ["CLOUD_ACCOUNT_PASSWORD"],
            "client_type": "ma-controller-ci",
        },
    )
    response_json = response.json()
    if response.status_code != 200:
        raise Exception(f"Error logging in: {response.status_code}, {response_json['detail']}")
    print("Login successful")  # allow-print

    access_token = response_json["tokens"]["access"]["token"]

    print("Updating SW versions in cloud")  # allow-print
    response = requests.post(
        f"https://apiv2.curibio.com/mantarray/software/mantarray/{controller_version_no_pre}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    response_json = response.json()
    if response.status_code != 200:
        raise Exception(f"Error updating SW versions: {response.status_code}, {response_json['detail']}")
    print("SW version update successful")  # allow-print


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=str, help="the dir containing the exe")
    parser.add_argument("--file", type=str, help="the name of the exe file")
    parser.add_argument("--channel", type=str, help="the release channel")

    parsed_args = parser.parse_args(sys.argv[1:])

    upload("downloads.curibio.com", parsed_args)
    update_cloud()
