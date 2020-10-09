# -*- coding: utf-8 -*-
"""Pytest configuration."""
import sys
from typing import List

from _pytest.config import Config
from _pytest.config.argparsing import Parser
from _pytest.python import Function
import pytest

sys.dont_write_bytecode = True


def pytest_addoption(parser: Parser) -> None:
    parser.addoption(
        "--full-ci",
        action="store_true",
        default=False,
        help="run tests that are marked as only for CI",
    )
    parser.addoption(
        "--include-slow-tests",
        action="store_true",
        default=False,
        help="run tests that are a bit slow",
    )


def pytest_collection_modifyitems(config: Config, items: List[Function]) -> None:
    if not config.getoption("--full-ci"):
        skip_ci_only = pytest.mark.skip(
            reason="these tests are skipped unless --full-ci option is set"
        )
        for item in items:
            if "only_run_in_ci" in item.keywords:
                item.add_marker(skip_ci_only)

    if not config.getoption("--include-slow-tests"):
        skip_slow = pytest.mark.skip(
            reason="these tests are skipped unless --include-slow-tests option is set"
        )
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
