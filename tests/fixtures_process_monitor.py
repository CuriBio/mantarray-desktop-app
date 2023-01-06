# -*- coding: utf-8 -*-
import queue
import threading

from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
import pytest


@pytest.fixture(scope="function", name="test_monitor")
def fixture_test_monitor():
    def _foo(process_manager):
        svd = process_manager.values_to_share_to_server
        svd["system_status"] = SERVER_INITIALIZING_STATE
        error_queue = error_queue = queue.Queue()
        the_lock = threading.Lock()
        monitor = MantarrayProcessesMonitor(svd, process_manager, error_queue, the_lock)
        return monitor, svd, error_queue, the_lock

    yield _foo
