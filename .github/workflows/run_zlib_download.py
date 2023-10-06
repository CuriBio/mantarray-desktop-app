# -*- coding: utf-8 -*-
import os
import shutil
import zipfile

import boto3

s3_resource = boto3.resource("s3")
bucket = s3_resource.Bucket("downloads.curibio.com")

# assuming this is being run from controller/
controller_folder_path = os.path.join("src", "mantarray_desktop_app")

filename = "zlib-1.3.zip"
zlib_zip_path = os.path.join(controller_folder_path, filename)
bucket.download_file(f"software/{filename}", zlib_zip_path)

zlib_folder_path = os.path.join(controller_folder_path, "zlib")
with zipfile.ZipFile(zlib_zip_path, "r") as zip_ref:
    zip_ref.extractall(controller_folder_path)

os.rename(f"{zlib_folder_path}-1.3", zlib_folder_path)

if "__MACOSX" in os.listdir(controller_folder_path):
    shutil.rmtree(os.path.join(controller_folder_path, "__MACOSX"))
