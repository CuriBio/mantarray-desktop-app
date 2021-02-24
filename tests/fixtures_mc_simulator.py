# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue
import time

from mantarray_desktop_app import MantarrayMCSimulator
import pytest
from stdlib_utils import QUEUE_CHECK_TIMEOUT_SECONDS


class MantarrayMCSimulatorSleepAfterWrite(MantarrayMCSimulator):
    """Subclass is specifically for unit tests.

    It should not be used in integration level tests.
    """

    def __init__(
        self,
        input_queue,
        output_queue,
        fatal_error_reporter,
        testing_queue,
        logging_level=logging.INFO,
        read_timeout_seconds=0,
        sleep_after_write_seconds=None,
    ):
        super().__init__(
            input_queue,
            output_queue,
            fatal_error_reporter,
            testing_queue,
            logging_level,
            read_timeout_seconds,
        )
        self._sleep_after_write_seconds = sleep_after_write_seconds

    def write(self, input_item):
        super().write(input_item)
        if self._sleep_after_write_seconds is not None:
            time.sleep(self._sleep_after_write_seconds)

    def start(self) -> None:
        raise NotImplementedError(
            "This class is only for unit tests not requiring a running process"
        )


@pytest.fixture(scope="function", name="mantarray_mc_simulator")
def fixture_mantarray_mc_simulator():
    """Fixture is specifically for unit tests.

    It should not be used in integration level tests.
    """
    input_queue = Queue()
    testing_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    simulator = MantarrayMCSimulatorSleepAfterWrite(
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        read_timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
        sleep_after_write_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )

    yield input_queue, output_queue, error_queue, testing_queue, simulator


class MantarrayMCSimulatorNoBeacons(MantarrayMCSimulatorSleepAfterWrite):
    def _send_status_beacon(self, truncate=False) -> None:
        self._time_of_last_status_beacon_secs = time.perf_counter()
        self._output_queue.put_nowait(bytes(0))

    def start(self) -> None:
        raise NotImplementedError(
            "This class is only for unit tests not requiring a running process"
        )


@pytest.fixture(scope="function", name="mantarray_mc_simulator_no_beacon")
def fixture_mantarray_mc_simulator_no_beacon():
    """Fixture is specifically for unit tests.

    It should not be used in integration level tests.
    """
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


@pytest.fixture(scope="function", name="runnable_mantarray_mc_simulator")
def fixture_runnable_mantarray_mc_simulator():
    testing_queue = Queue()
    error_queue = Queue()
    input_queue = Queue()
    output_queue = Queue()
    simulator = MantarrayMCSimulator(
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        read_timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )

    yield input_queue, output_queue, error_queue, testing_queue, simulator

    simulator.hard_stop()
    simulator.join()
