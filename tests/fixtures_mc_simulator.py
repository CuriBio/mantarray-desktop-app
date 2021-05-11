# -*- coding: utf-8 -*-
from multiprocessing import Queue
import time

from mantarray_desktop_app import convert_to_status_code_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import SERIAL_COMM_BOOT_UP_CODE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_IDLE_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty
from stdlib_utils import QUEUE_CHECK_TIMEOUT_SECONDS


STATUS_BEACON_SIZE_BYTES = 28
HANDSHAKE_RESPONSE_SIZE_BYTES = 36

TEST_HANDSHAKE_TIMESTAMP = 12345
TEST_HANDSHAKE = create_data_packet(
    TEST_HANDSHAKE_TIMESTAMP,
    SERIAL_COMM_MAIN_MODULE_ID,
    SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
    bytes(0),
)

DEFAULT_SIMULATOR_STATUS_CODE = convert_to_status_code_bytes(SERIAL_COMM_BOOT_UP_CODE)


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
        raise NotImplementedError("This class is only for unit tests not requiring a running process")


def set_simulator_idle_ready(simulator_fixture):
    simulator = simulator_fixture["simulator"]
    testing_queue = simulator_fixture["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": SERIAL_COMM_IDLE_READY_CODE},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)


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
    def _send_status_beacon(self, truncate=False) -> None:
        self._time_of_last_status_beacon_secs = time.perf_counter()

    def start(self) -> None:
        # Tanner (2/24/21): Need to explicitly redefine this method since pylint considers this implementation to be abstract
        raise NotImplementedError("This class is only for unit tests not requiring a running process")


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
