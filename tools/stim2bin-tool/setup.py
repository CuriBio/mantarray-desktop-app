# -*- coding: utf-8 -*-
from setuptools import setup

setup(
    name="stim2bin",
    version="0.1",
    packages=["stim2bin"],
    install_requires=[
        "eventlet==0.31.0",
        "flask==1.1.2",
        "flask-cors==3.0.10",
        "Flask-SocketIO==5.1.1",
        "h5py==3.7.0",
        "immutabledict==1.3.0",
        "immutable-data-validation==0.2.1",
        "labware-domain-models==0.3.1",
        "itsdangerous==2.0.1",
        "Jinja2==3.0.3",
        "jsonschema==4.1.0",
        "nptyping==1.4.4",
        "numpy==1.22.4",
        "psutil==5.8.0",
        "pyserial==3.5",
        "scipy==1.8.1",
        "secrets-manager==0.4",
        "semver==2.13.0",
        "stdlib-utils==0.5.2",
        "streamz==0.6.2",
        "wakepy==0.5.0",
        "werkzeug==3.0.1",
        "xem-wrapper==0.3.0",
        "pulse3d==0.24.7",
    ],
    zip_safe=False,
    entry_points={
        "console_scripts": ["stim2bin=stim2bin:main"],
    },
)
