# -*- coding: utf-8 -*-
"""Setup configuration."""

import os

from setuptools import Extension
from setuptools import find_packages
from setuptools import setup

# make sure to have installed the Python dev module: sudo apt-get install python3.7-dev

try:
    from Cython.Build import cythonize
except ImportError:
    USE_CYTHON = False
else:
    USE_CYTHON = True

ext = ".pyx" if USE_CYTHON else ".cpp"
extensions = [
    Extension(
        "mantarray_desktop_app.data_parsing_cy",
        [os.path.join("src", "mantarray_desktop_app", "data_parsing_cy") + ext],
    )
]

if USE_CYTHON:
    # cythonizing data_parsing_cy.pyx with kwarg annotate=True will help when optimizing the code by enabling generation of the html annotation file
    extensions = cythonize(extensions, annotate=False)

setup(
    name="mantarray_desktop_app",
    version="0.4.0",
    description="Windows Desktop App for viewing and recording data from a Mantarray Instrument.",
    url="https://github.com/curibio/mantarray-desktop-app",
    author="Curi Bio",
    author_email="contact@curibio.com",
    license="MIT",
    packages=find_packages("src"),
    package_dir={"": "src"},
    install_requires=[],
    ext_modules=extensions,
)
