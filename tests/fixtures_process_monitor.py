# -*- coding: utf-8 -*-
import queue
import threading

from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
import pytest

from .fixtures import fixture_test_process_manager

__fixtures__ = [fixture_test_process_manager]


@pytest.fixture(scope="function", name="test_monitor")
def fixture_test_monitor(test_process_manager):
    the_dict = test_process_manager.get_values_to_share_to_server()
    the_dict["system_status"] = SERVER_INITIALIZING_STATE
    error_queue = error_queue = queue.Queue()
    the_lock = threading.Lock()
    monitor = MantarrayProcessesMonitor(the_dict, test_process_manager, error_queue, the_lock)
    yield monitor, the_dict, error_queue, the_lock

    # cleanup queues to avoid BrokenPipe errors
    monitor.hard_stop()


@pytest.fixture(scope="function", name="test_monitor_beta_2_mode")
def fixture_test_monitor_beta_2_mode(test_process_manager_beta_2_mode):
    the_dict = test_process_manager_beta_2_mode.get_values_to_share_to_server()
    the_dict["system_status"] = SERVER_INITIALIZING_STATE
    error_queue = error_queue = queue.Queue()
    the_lock = threading.Lock()
    monitor = MantarrayProcessesMonitor(the_dict, test_process_manager_beta_2_mode, error_queue, the_lock)
    yield monitor, the_dict, error_queue, the_lock

    # cleanup queues to avoid BrokenPipe errors
    monitor.hard_stop()
