# -*- coding: utf-8 -*-
import sys

import boto3


def download_vcn() -> None:
    s3_resource = boto3.resource("s3")
    bucket = s3_resource.Bucket("build-resources-x92toe")
    bucket.download_file("generic/windows/vcn-v0.8.3-windows-amd64.exe", "vcn.exe")


if __name__ == "__main__":
    first_arg = sys.argv[1]
    if first_arg == "download":
        download_vcn()
