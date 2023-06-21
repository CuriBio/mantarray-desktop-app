#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# -*- mode: python -*-

# the shebang identifies this file as a 'python' 'type' for pre-commit hooks

import inspect
import os
import sys
from stdlib_utils import configure_logging
from stdlib_utils import get_current_file_abs_directory
import scipy

# https://stackoverflow.com/questions/37319911/python-how-to-specify-output-folders-in-pyinstaller-spec-file?rq=1

use_upx = True

configure_logging()
block_cipher = None
# mypy doesn't understand exactly how pyinstaller parses this
sys.modules["FixTk"] = None  # type: ignore

PATH_OF_CURRENT_FILE = os.path.dirname((inspect.stack()[0][1]))


scipy_libs_dir = os.path.join(scipy.__file__, os.pardir, os.pardir, "scipy.libs")


a = Analysis(  # type: ignore # noqa: F821     the 'Analysis' object is special to how pyinstaller reads the file
    [os.path.join("src", "entrypoint.py")],
    pathex=["dist"],
    binaries=[],
    datas=[(os.path.join(scipy_libs_dir, "*"), "scipy.libs")],
    hiddenimports=["scipy.special.cython_special"],
    hookspath=[os.path.join(get_current_file_abs_directory(), "hooks")],
    runtime_hooks=[],
    excludes=["FixTk", "tcl", "tk", "_tkinter", "tkinter", "Tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

print("Modules/packages found during analysis:")  # allow-print
for this_info in sorted(a.pure, key=lambda x: x[0]):
    print(this_info)  # allow-print


pyz = PYZ(  # type: ignore # noqa: F821   the 'PYZ' object is special to how pyinstaller reads the file
    a.pure, a.zipped_data, cipher=block_cipher
)
exe = EXE(  # type: ignore # noqa: F821   the 'EXE' object is special to how pyinstaller reads the file
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="instrument-controller",
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
    name="instrument-controller",
)
