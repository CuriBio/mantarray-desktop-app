# -*- coding: utf-8 -*-
from multiprocessing import Queue
import time

from mantarray_desktop_app import MantarrayMcSimulator
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import QUEUE_CHECK_TIMEOUT_SECONDS


class MantarrayMcSimulatorSleepAfterWrite(MantarrayMcSimulator):
    """Subclass is specifically for unit tests.

    This subclass allows for a sleep to be performed after writing to the simulator which is useful in unit testing but not desired behavior when this Process is running

    It should not be used in integration level tests.
    """

    def __init__(
        self,
        *args,
        sleep_after_write_seconds=None,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
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
    simulator = MantarrayMcSimulatorSleepAfterWrite(
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        read_timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
        sleep_after_write_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )

    items_dict = {
        "input_queue": input_queue,
        "output_queue": output_queue,
        "error_queue": error_queue,
        "testing_queue": testing_queue,
        "simulator": simulator,
    }
    yield items_dict


class MantarrayMcSimulatorNoBeacons(MantarrayMcSimulatorSleepAfterWrite):
    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )
        self._is_booting_up = False

    def _send_status_beacon(self, truncate=False) -> None:
        self._time_of_last_status_beacon_secs = time.perf_counter()

    def start(self) -> None:
        # Tanner (2/24/21): Need to explicitly redefine this method since pylint considers this implementation to be abstract
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
    simulator = MantarrayMcSimulatorNoBeacons(
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        read_timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
        sleep_after_write_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )

    items_dict = {
        "input_queue": input_queue,
        "output_queue": output_queue,
        "error_queue": error_queue,
        "testing_queue": testing_queue,
        "simulator": simulator,
    }
    yield items_dict


@pytest.fixture(scope="function", name="runnable_mantarray_mc_simulator")
def fixture_runnable_mantarray_mc_simulator():
    testing_queue = Queue()
    error_queue = Queue()
    input_queue = Queue()
    output_queue = Queue()
    simulator = MantarrayMcSimulator(
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        read_timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )

    items_dict = {
        "input_queue": input_queue,
        "output_queue": output_queue,
        "error_queue": error_queue,
        "testing_queue": testing_queue,
        "simulator": simulator,
    }
    yield items_dict

    simulator.stop()
    # Tanner (2/25/21): Remove any beacons remaining in read queue. This is faster than hard_stop which will attempt to drain every queue
    drain_queue(output_queue)

    simulator.join()
