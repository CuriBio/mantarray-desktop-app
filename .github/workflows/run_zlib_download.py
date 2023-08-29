# -*- coding: utf-8 -*-
import os
import zipfile

import requests


# assuming this is being run from controller/
controller_folder_path = os.path.join("src", "mantarray_desktop_app")
zlib_folder_path = os.path.join(controller_folder_path, "zlib")

r = requests.get("https://www.zlib.net/zlib13.zip", allow_redirects=True)
with open(zlib_folder_path + ".zip", "wb") as zlib_zip:
    zlib_zip.write(r.content)

with zipfile.ZipFile(zlib_folder_path + ".zip", "r") as zip_ref:
    zip_ref.extractall(controller_folder_path)

os.rename(f"{zlib_folder_path}-1.3", zlib_folder_path)
