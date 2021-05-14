# -*- coding: utf-8 -*-
import os
import zipfile

import requests


zlib_folder_path = os.path.join("src", "zlib")

r = requests.get("https://www.zlib.net/zlib1211.zip", allow_redirects=True)
with open(zlib_folder_path + ".zip", "wb") as zlib_zip:
    zlib_zip.write(r.content)

with zipfile.ZipFile(zlib_folder_path + ".zip", "r") as zip_ref:
    zip_ref.extractall("src")

os.rename(os.path.join("src", "zlib-1.2.11"), zlib_folder_path)
