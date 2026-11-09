![Development Branch Build](https://github.com/CuriBio/mantarray-desktop-app/workflows/Dev/badge.svg?branch=development)
[![codecov](https://codecov.io/gh/CuriBio/mantarray-desktop-app/branch/development/graph/badge.svg)](https://codecov.io/gh/CuriBio/mantarray-desktop-app)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

NodeJS Dependencies:

[![NodeDependency Status](https://david-dm.org/CuriBio/mantarray-desktop-app/status.svg)](https://david-dm.org/CuriBio/mantarray-desktop-app)
[![NodeDevDependency Status](https://david-dm.org/CuriBio/mantarray-desktop-app/dev-status.svg)](https://david-dm.org/CuriBio/mantarray-desktop-app?type=dev)

# Controller (Python) Development Setup

These steps create a virtual environment at `controller/.venv` with the exact
dependency versions from `controller/Pipfile.lock`, so that you can run the controller's tests.
They work on Windows, macOS, and Linux.

## Prerequisites

- Python 3.10, the version required by `controller/Pipfile` and used by CI. Any installation method
  works (python.org installer, pyenv, Homebrew, apt, etc.).
  - We recommend pyenv. It allows you to switch between python versions easily
- git, with access to the CuriBio GitHub organization.
- The [GitHub CLI](https://cli.github.com/) (`gh`), logged in with `gh auth login`.

## 1. Clone the repository and its submodule

```bash
gh repo clone CuriBio/mantarray-desktop-app
cd mantarray-desktop-app
git submodule update --init
```

The submodule that needs to be updated is in `controller/vendor/barnacleboard-serial-interface`

## 2. Create and activate the virtual environment

From `controller/`, create the venv with Python 3.10:

```bash
python3.10 -m venv .venv      # Windows: py -3.10 -m venv .venv
```

Then activate it. All remaining steps assume it is active, so `python`, `pip`, and `pipenv`
refer to the venv:

```bash
source .venv/bin/activate       # macOS / Linux
.venv\Scripts\Activate.ps1      # Windows PowerShell
.venv\Scripts\activate.bat      # Windows cmd
```

## 3. Install the build tools

```bash
python -m pip install --upgrade pip
python -m pip install pipenv==2024.0.1 wheel numpy==1.23.4 cython==0.29.33
python -m pip install --no-build-isolation --no-deps pulse3d==0.34.3
```

`pulse3d` must be installed by hand before the other dependencies. Its `setup.py` imports numpy
without declaring it as a build dependency, so a normal install fails with
`ModuleNotFoundError: No module named 'numpy'`. The numpy, Cython, and pulse3d versions here must
match `controller/Pipfile.lock`. Update them if the lock file changes.

## 4. Install the locked dependencies

```bash
pipenv install --dev --deploy
```

pipenv detects the active venv and installs into it, which `pipenv --venv` confirms.
`--deploy` aborts if `Pipfile.lock` is out of date, instead of re-locking.

## 5. Download the zlib source

The controller's Cython extension compiles `crc32.c` from zlib, which is not committed to the repo.
From `controller/`:

```bash
python -c "import io, urllib.request, zipfile; zipfile.ZipFile(io.BytesIO(urllib.request.urlopen('https://downloads.curibio.com/software/zlib-1.3.zip').read())).extractall('src/mantarray_desktop_app')"
python -c "import os, shutil; d = 'src/mantarray_desktop_app'; os.rename(f'{d}/zlib-1.3', f'{d}/zlib'); shutil.rmtree(f'{d}/__MACOSX', ignore_errors=True)"
```

This leaves the source at `controller/src/mantarray_desktop_app/zlib/`.

## 6. Install the local packages

```bash
pip install --no-build-isolation -e vendor/barnacleboard-serial-interface
pip install --no-build-isolation -e .
```

The second command compiles the Cython extension (`data_parsing_cy`). `--no-build-isolation`
compiles it with the locked numpy and Cython versions already in the venv, not the latest releases.

## 7. Run the tests

From `controller/`, with the venv active:

```bash
pytest      # full suite, as CI runs it (minus slow tests)
pytest --no-cov tests/workers/test_magnet_finder.py     # a subset
```

The suite enforces 100% coverage, so add `--no-cov` when running only some tests. Add
`--include-slow-tests` to also run the slow tests, as CI does.

To run the same linters and formatters as CI before committing:

```bash
pre-commit install            # run the hooks automatically on every commit
pre-commit run --all-files    # or run them manually
```

Afterwards, you only need to activate the venv (step 2) before running tests. If `Pipfile.lock`
changes, repeat step 4. If you edit `data_parsing_cy.pyx`, repeat the last command of step 6.

## Troubleshooting

- **The Cython extension fails to compile with errors such as `use of undeclared identifier 'PyDataType_ELSIZE'`.** A `data_parsing_cy.cpp` left over from an earlier build was generated
  with a different Cython/numpy version, and it is not regenerated automatically. Delete
  `src/mantarray_desktop_app/utils/data_parsing_cy.cpp` and any `data_parsing_cy*.so` /
  `data_parsing_cy*.pyd` in that folder, then repeat step 6.
- **`invalid command 'bdist_wheel'`.** The `wheel` package is missing from the venv. Install it
  (step 3) and retry.
- **pipenv installs into a different environment.** pipenv uses whichever environment the
  `VIRTUAL_ENV` variable points to. Make sure `.venv` is activated, then confirm that
  `pipenv --venv` prints the path to `controller/.venv`.
- **macOS Monterey.** Run `export SYSTEM_VERSION_COMPAT=1` before step 4.
- **A few tests fail on macOS with `NotImplementedError` from `multiprocessing/queues.py`.** This
  is expected. `multiprocessing.Queue.qsize()` is not implemented on macOS, and a handful of tests
  rely on it. These failures also bring total coverage below 100%. CI runs on Linux and Windows, where
  these tests pass.
