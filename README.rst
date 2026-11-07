
.. image:: https://github.com/CuriBio/mantarray-desktop-app/workflows/Dev/badge.svg?branch=development
   :alt: Development Branch Build

.. image:: https://codecov.io/gh/CuriBio/mantarray-desktop-app/branch/development/graph/badge.svg
  :target: https://codecov.io/gh/CuriBio/mantarray-desktop-app

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/psf/black

.. image:: https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white
   :target: https://github.com/pre-commit/pre-commit
   :alt: pre-commit

NodeJS Dependencies:

.. image:: https://david-dm.org/CuriBio/mantarray-desktop-app/status.svg
   :target: https://david-dm.org/CuriBio/mantarray-desktop-app
   :alt: NodeDependency Status

.. image:: https://david-dm.org/CuriBio/mantarray-desktop-app/dev-status.svg
   :target: https://david-dm.org/CuriBio/mantarray-desktop-app?type=dev
   :alt: NodeDevDependency Status

Controller (Python) Development Setup
=====================================

These steps create a virtual environment at ``controller/.venv`` (ignored by git) with the exact
dependency versions from ``controller/Pipfile.lock``, so that you can run the controller's tests.
They work on Windows, macOS, and Linux.

Prerequisites
-------------

- Python 3.10, the version required by ``controller/Pipfile`` and used by CI. Any installation method
  works (python.org installer, pyenv, Homebrew, apt, etc.).
- git, with access to the CuriBio GitHub organization.

1. Check out the vendored submodule
-----------------------------------

From the repository root:

.. code-block:: bash

    git submodule update --init

The submodule URL uses SSH. If you use HTTPS with GitHub instead, run:

.. code-block:: bash

    git -c url."https://github.com/".insteadOf="git@github.com:" submodule update --init

2. Create and activate the virtual environment
----------------------------------------------

From ``controller/``, create the venv with Python 3.10:

.. code-block:: bash

    python3.10 -m venv .venv      # Windows: py -3.10 -m venv .venv

Then activate it. All remaining steps assume it is active, so ``python``, ``pip``, and ``pipenv``
refer to the venv:

.. code-block:: bash

    source .venv/bin/activate     # macOS / Linux
    .venv\Scripts\Activate.ps1    # Windows PowerShell
    .venv\Scripts\activate.bat    # Windows cmd

3. Install the build tools
--------------------------

.. code-block:: bash

    python -m pip install --upgrade pip
    python -m pip install pipenv==2024.0.1 wheel numpy==1.23.4 cython==0.29.33
    python -m pip install --no-build-isolation --no-deps pulse3d==0.34.3

``pulse3d`` must be installed by hand before the other dependencies. Its ``setup.py`` imports numpy
without declaring it as a build dependency, so a normal install fails with
``ModuleNotFoundError: No module named 'numpy'``. The numpy, Cython, and pulse3d versions here must
match ``controller/Pipfile.lock``. Update them if the lock file changes.

4. Install the locked dependencies
----------------------------------

.. code-block:: bash

    pipenv install --dev --deploy

pipenv detects the active venv and installs into it, which ``pipenv --venv`` confirms.
``--deploy`` aborts if ``Pipfile.lock`` is out of date, instead of re-locking.

5. Download the zlib source
---------------------------

The controller's Cython extension compiles ``crc32.c`` from zlib, which is not committed to the repo.
From ``controller/``:

.. code-block:: bash

    python -c "import io, urllib.request, zipfile; zipfile.ZipFile(io.BytesIO(urllib.request.urlopen('https://downloads.curibio.com/software/zlib-1.3.zip').read())).extractall('src/mantarray_desktop_app')"
    python -c "import os, shutil; d = 'src/mantarray_desktop_app'; os.rename(f'{d}/zlib-1.3', f'{d}/zlib'); shutil.rmtree(f'{d}/__MACOSX', ignore_errors=True)"

This leaves the source at ``controller/src/mantarray_desktop_app/zlib/``.

6. Install the local packages
-----------------------------

.. code-block:: bash

    pip install --no-build-isolation -e vendor/barnacleboard-serial-interface
    pip install --no-build-isolation -e .

The second command compiles the Cython extension (``data_parsing_cy``). ``--no-build-isolation``
compiles it with the locked numpy and Cython versions already in the venv, not the latest releases.

7. Run the tests
----------------

From ``controller/``, with the venv active:

.. code-block:: bash

    pytest                                            # full suite, as CI runs it (minus slow tests)
    pytest --no-cov tests/workers/test_magnet_finder.py   # a subset

The suite enforces 100% coverage, so add ``--no-cov`` when running only some tests. Add
``--include-slow-tests`` to also run the slow tests, as CI does.

To run the same linters and formatters as CI before committing:

.. code-block:: bash

    pre-commit install            # run the hooks automatically on every commit
    pre-commit run --all-files    # or run them manually

Afterwards, you only need to activate the venv (step 2) before running tests. If ``Pipfile.lock``
changes, repeat step 4. If you edit ``data_parsing_cy.pyx``, repeat the last command of step 6.

Troubleshooting
---------------

- **The Cython extension fails to compile with errors such as ``use of undeclared identifier
  'PyDataType_ELSIZE'``.** A ``data_parsing_cy.cpp`` left over from an earlier build was generated
  with a different Cython/numpy version, and it is not regenerated automatically. Delete
  ``src/mantarray_desktop_app/utils/data_parsing_cy.cpp`` and any ``data_parsing_cy*.so`` /
  ``data_parsing_cy*.pyd`` in that folder, then repeat step 6.
- **``invalid command 'bdist_wheel'``.** The ``wheel`` package is missing from the venv. Install it
  (step 3) and retry.
- **pipenv installs into a different environment.** pipenv uses whichever environment the
  ``VIRTUAL_ENV`` variable points to. Make sure ``.venv`` is activated, then confirm that
  ``pipenv --venv`` prints the path to ``controller/.venv``.
- **macOS Monterey.** Run ``export SYSTEM_VERSION_COMPAT=1`` before step 4.
- **A few tests fail on macOS with ``NotImplementedError`` from ``multiprocessing/queues.py``.** This
  is expected. ``multiprocessing.Queue.qsize()`` is not implemented on macOS, and a handful of tests
  rely on it. These failures also bring total coverage below 100%. CI runs on Linux and Windows, where
  these tests pass.
