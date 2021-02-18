# -*- coding: utf-8 -*-
from multiprocessing import Queue
import time

from mantarray_desktop_app import MantarrayMCSimulator
import pytest
from stdlib_utils import QUEUE_CHECK_TIMEOUT_SECONDS


@pytest.fixture(scope="function", name="mantarray_mc_simulator")
def fixture_mantarray_mc_simulator():
    input_queue = Queue()
    testing_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    simulator = MantarrayMCSimulator(
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        read_timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
        sleep_after_write_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )

    yield input_queue, output_queue, error_queue, testing_queue, simulator


class MantarrayMCSimulatorNoBeacons(MantarrayMCSimulator):
    def _send_status_beacon(self, truncate=False) -> None:
        self._time_of_last_status_beacon_secs = time.perf_counter()
        self._output_queue.put_nowait(bytes(0))


@pytest.fixture(scope="function", name="mantarray_mc_simulator_no_beacon")
def fixture_mantarray_mc_simulator_no_beacon(mocker):
    testing_queue = Queue()
    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    simulator = MantarrayMCSimulatorNoBeacons(
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        read_timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
        sleep_after_write_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )

    yield input_queue, output_queue, error_queue, testing_queue, simulator
