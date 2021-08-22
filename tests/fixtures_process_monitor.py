# -*- coding: utf-8 -*-
import queue
import threading

from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
import pytest


@pytest.fixture(scope="function", name="test_monitor")
def fixture_test_monitor():

    def _foo(process_manager):
        the_dict = process_manager.get_values_to_share_to_server()
        the_dict["system_status"] = SERVER_INITIALIZING_STATE
        error_queue = error_queue = queue.Queue()
        the_lock = threading.Lock()
        monitor = MantarrayProcessesMonitor(the_dict, process_manager, error_queue, the_lock)
        return monitor, the_dict, error_queue, the_lock

    yield _foo
