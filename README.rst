IMPORTANT: before using this template to create a repo that will be published to PyPI, check that the desired name of the repo is available on PyPI.

After creating a copy of this template, change the name of the package in `setup.py`, `setup.cfg`, `pytest.ini`, `MANIFEST.in`, `codebuild_formation.yaml` and the subfolder within the `src` directory.  In the Readme, change the all the `python-github-template` in links to point to the new repo name.
Before CodeBuild can automatically publish to PyPI, the package must be registered using command `twine register`: https://twine.readthedocs.io/en/latest/#twine-register

Steps to create repo:
   - Log in as Curi-Bio-CI
   - Select python-github-template as template
   - Check box that says `include all branches`
   - Set repo to public
   - Publish repo
   - To stop error messages about `main` and `development` branches not sharing any history, clone the repo, checkout development and run `git rebase -i origin/master` then `git push -f`
   - In Actions -> Dev: click Run workflow. Wait until workflow finishes
   - In Settings -> Security & analysis: enable Dependabot security updates
   - In Setting -> Options, under Merge Button:
      - Make sure "automatically delete head branches" is checked
      - Make sure "squash merging" and "rebase merging" are NOT checked
   - In Settings -> Branches:
      - Add Rule with [dm][ea][vi][en]* specified as Branch pattern name
         - check Require pull requests reviews before merging
         - check Dismiss stale pull requests
         - check Require Review from Code Owners
         - check Require status checks before merging
         - Under status checks, check all of the python checks (4 total)
         - check Include administrators
         - check Restrict who can push to matching branches

.. image:: https://img.shields.io/pypi/v/python-github-template.svg
    :target: https://pypi.org/project/python-github-template/

.. image:: https://pepy.tech/badge/python-github-template
  :target: https://pepy.tech/project/python-github-template

.. image:: https://img.shields.io/pypi/pyversions/python-github-template.svg
    :target: https://pypi.org/project/python-github-template/

.. image:: https://github.com/CuriBio/python-github-template/workflows/Dev/badge.svg?branch=development
   :alt: Development Branch Build

.. image:: https://codecov.io/gh/CuriBio/python-github-template/branch/development/graph/badge.svg
  :target: https://codecov.io/gh/CuriBio/python-github-template

..
   If this library uses readthedocs then put that badge here
   .. image:: https://readthedocs.org/projects/python-github-template/badge/?version=latest
     :target: https://python-github-template.readthedocs.io/en/latest/?badge=latest
     :alt: Documentation Status


.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/psf/black

.. image:: https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white
   :target: https://github.com/pre-commit/pre-commit
   :alt: pre-commit