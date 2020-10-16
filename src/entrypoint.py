# -*- coding: utf-8 -*-
"""Entrypoint for the executable.

Eli (11/7/19): It seems to work best to avoid import errors if the
entrypoint is outside the main package folder.
"""
import multiprocessing
import sys

import mantarray_desktop_app

if __name__ == "__main__":
    multiprocessing.freeze_support()  # This line is not unit tested (Eli 12/24/19 unsure how to test something in this codeblock), but is critical to allow multiprocessing to work in complied PyInstaller bundles https://kite.com/python/docs/multiprocessing.freeze_support
    multiprocessing.set_start_method(
        "spawn"
    )  # This line is not explicitly unit tested, but an error will be thrown in the main.main script if it is not executed. Windows only allows this start method, so need to make sure that in all development environments it is being tested in this mode.
    mantarray_desktop_app.main.main(sys.argv[1:])
