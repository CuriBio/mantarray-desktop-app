# -*- coding: utf-8 -*-
from multiprocessing import Queue as MPQueue
from random import randint
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
from stdlib_utils import TestingQueue


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


def set_simulator_idle_ready(simulator_fixture):
    simulator = simulator_fixture["simulator"]
    testing_queue = simulator_fixture["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": SERIAL_COMM_IDLE_READY_CODE},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)


def get_null_subprotocol(duration):
    return {
        "phase_one_duration": duration,
        "phase_one_charge": 0,
        "interpulse_interval": 0,
        "phase_two_duration": 0,
        # pylint: disable=duplicate-code
        "phase_two_charge": 0,
        "repeat_delay_interval": 0,
        "total_active_duration": duration,
    }


def get_random_pulse_subprotocol():
    return {
        "phase_one_duration": randint(1, 500),
        "phase_one_charge": randint(1, 1000),
        "interpulse_interval": randint(0, 500),
        "phase_two_duration": randint(1, 1000),
        "phase_two_charge": randint(1, 1000),
        "repeat_delay_interval": randint(0, 500),
        "total_active_duration": randint(1500, 3000),
    }


@pytest.fixture(scope="function", name="mantarray_mc_simulator")
def fixture_mantarray_mc_simulator():
    """Fixture is specifically for unit tests.

    It should not be used in integration level tests.
    """
    input_queue = TestingQueue()
    testing_queue = TestingQueue()
    output_queue = TestingQueue()
    error_queue = TestingQueue()
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


class MantarrayMcSimulatorNoBeacons(MantarrayMcSimulator):
    def _send_status_beacon(self, truncate=False) -> None:
        self._time_of_last_status_beacon_secs = time.perf_counter()

    def start(self) -> None:
        raise NotImplementedError("This class is only for unit tests not requiring a running process")


@pytest.fixture(scope="function", name="mantarray_mc_simulator_no_beacon")
def fixture_mantarray_mc_simulator_no_beacon():
    """Fixture is specifically for unit tests.

    It should not be used in integration level tests.
    """
    testing_queue = TestingQueue()
    input_queue = TestingQueue()
    output_queue = TestingQueue()
    error_queue = TestingQueue()
    simulator = MantarrayMcSimulatorNoBeacons(
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


@pytest.fixture(scope="function", name="runnable_mantarray_mc_simulator")
def fixture_runnable_mantarray_mc_simulator():
    testing_queue = MPQueue()
    error_queue = MPQueue()
    input_queue = MPQueue()
    output_queue = MPQueue()
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
    # Tanner (2/25/21): Remove any data packets remaining in read queue. This is faster than hard_stop which will attempt to drain every queue
    drain_queue(output_queue)

    simulator.join()
