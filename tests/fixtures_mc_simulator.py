# -*- coding: utf-8 -*-
from multiprocessing import Queue as MPQueue
from random import choice
from random import randint
import time

from mantarray_desktop_app import convert_to_status_code_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import SERIAL_COMM_BOOT_UP_CODE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_IDLE_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
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


def random_time_index():
    return randint(100, 0xFFFFFFFFFF)


def random_time_offset():
    return randint(0, 0xFFFF)


def random_data_value():
    return randint(0, 0xFFFF)


def random_timestamp():
    return randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)


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
        "interphase_interval": 0,
        "phase_two_duration": 0,
        # pylint: disable=duplicate-code
        "phase_two_charge": 0,
        "repeat_delay_interval": 0,
        "total_active_duration": duration,
    }


def get_random_subprotocol(**kwargs):
    return {
        "phase_one_duration": kwargs.get("phase_one_duration", randint(1, 16000)),
        "phase_one_charge": kwargs.get("phase_one_charge", randint(1, 100) * 10),
        "interphase_interval": kwargs.get("interphase_interval", randint(0, 16000)),
        "phase_two_duration": kwargs.get("phase_two_duration", randint(1, 16000)),
        "phase_two_charge": kwargs.get("phase_two_charge", randint(1, 100) * 10),
        "repeat_delay_interval": kwargs.get("repeat_delay_interval", randint(0, 50000)),
        "total_active_duration": kwargs.get("total_active_duration", randint(2000, 3000)),
    }


def create_random_stim_info():
    protocol_ids = (None, "A", "B", "C", "D")
    return {
        "protocols": [
            {
                "protocol_id": pid,
                "stimulation_type": choice(["C", "V"]),
                "run_until_stopped": choice([True, False]),
                "subprotocols": [
                    choice([get_random_subprotocol(), get_null_subprotocol(50000)])
                    for _ in range(randint(1, 2))
                ],
            }
            for pid in protocol_ids[1:]
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(protocol_ids)
            for well_idx in range(24)
        },
    }


def set_stim_info_and_start_stimulating(simulator_fixture, stim_info):
    simulator = simulator_fixture["simulator"]
    testing_queue = simulator_fixture["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_stim_info", "stim_info": stim_info}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_stim_status", "status": True}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # remove all bytes sent from initial subprotocol status update
    simulator.read_all()


def create_converted_stim_info(stim_info):
    protocol_ids = set()
    for protocol in stim_info["protocols"]:
        if protocol["protocol_id"] not in protocol_ids:
            protocol_ids.add(protocol["protocol_id"])
        del protocol["protocol_id"]

    protocol_ids = sorted(list(protocol_ids))
    converted_protocol_assignments = {
        well_name: (None if protocol_id is None else protocol_ids.index(protocol_id))
        for well_name, protocol_id in stim_info["protocol_assignments"].items()
    }
    stim_info["protocol_assignments"] = converted_protocol_assignments
    return stim_info


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
