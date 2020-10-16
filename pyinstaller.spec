#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# -*- mode: python -*-

# the shebang identifies this file as a 'python' 'type' for pre-commit hooks

import inspect
import os
import sys
from stdlib_utils import configure_logging
from mantarray_desktop_app import get_latest_firmware

# import PyInstaller.config # https://stackoverflow.com/questions/37319911/python-how-to-specify-output-folders-in-pyinstaller-spec-file?rq=1

# PyInstaller.config.CONF["distpath"] = "python-dist"
# PyInstaller.config.CONF["workpath"] = "pyinstaller-build"
use_upx = True

configure_logging()
block_cipher = None
# mypy doesn't understand exactly how pyinstaller parses this
sys.modules["FixTk"] = None  # type: ignore

PATH_OF_CURRENT_FILE = os.path.dirname((inspect.stack()[0][1]))
LATEST_FIRMWARE_FILE = get_latest_firmware()
print(f"Latest firmware file: {LATEST_FIRMWARE_FILE}")
# print("Files in current directory (recursive):")
# for root, dirs, files in os.walk("."):
#     for name in files:
#         print(os.path.join(root, name))
#     for name in dirs:
#         print(os.path.join(root, name))


a = Analysis(  # type: ignore # noqa: F821     the 'Analysis' object is special to how pyinstaller reads the file
    [os.path.join("src", "entrypoint.py")],
    pathex=["dist"],
    binaries=[],
    datas=[
        (
            os.path.join("src", "xem_scripts", "*.txt"),
            os.path.join("src", "xem_scripts"),
        ),
        (
            os.path.join("src", "firmware", LATEST_FIRMWARE_FILE),
            os.path.join("src", "firmware"),
        ),
        (
            os.path.join("src", "drivers", "FrontPanelUSB-DriverOnly-5.2.2.exe"),
            os.path.join("src", "drivers"),
        ),
    ],
    hiddenimports=["xem_wrapper._windows._ok", "scipy.special.cython_special"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["FixTk", "tcl", "tk", "_tkinter", "tkinter", "Tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

# print("Modules/packages found during analysis:")
# for this_info in sorted(a.pure, key=lambda x: x[0]):
#     print(this_info)


pyz = PYZ(  # type: ignore # noqa: F821   the 'PYZ' object is special to how pyinstaller reads the file
    a.pure, a.zipped_data, cipher=block_cipher
)
exe = EXE(  # type: ignore # noqa: F821   the 'EXE' object is special to how pyinstaller reads the file
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="mantarray-flask",
    debug=False,
    strip=False,
    upx=use_upx,
    console=True,
)
coll = COLLECT(  # type: ignore # noqa: F821   the 'COLLECT' object is special to how pyinstaller reads the file
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=use_upx,
    upx_exclude=[
        "vcruntime140.dll",  # UPX breaks this dll  https://github.com/pyinstaller/pyinstaller/pull/3821
        "qwindows.dll",  # UPX also has trouble with PyQt https://github.com/upx/upx/issues/107
    ],
    name="mantarray-flask",
)
