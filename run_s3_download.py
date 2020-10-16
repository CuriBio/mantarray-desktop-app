# -*- coding: utf-8 -*-
import os

import boto3

s3_resource = boto3.resource("s3")
bucket = s3_resource.Bucket("build-resources-x92toe")
firmware_objects = bucket.objects.filter(Prefix="mantarray/firmware/")
for obj in firmware_objects:
    _, filename = os.path.split(obj.key)
    if (
        ".bit" in filename
    ):  # Tanner (6/10/20): There seems to be a hidden file in the folder causing problems, so doing this just to make sure we only get firmware files
        bucket.download_file(obj.key, os.path.join("src", "firmware", filename))

driver_objects = bucket.objects.filter(Prefix="mantarray/drivers/")
for obj in driver_objects:
    _, filename = os.path.split(obj.key)
    if (
        ".exe" in filename
    ):  # Tanner (10/08/20): firmware folder had an issue with a hidden file, so doing this to avoid the same problem
        bucket.download_file(obj.key, os.path.join("src", "drivers", filename))
