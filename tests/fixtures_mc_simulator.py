# -*- coding: utf-8 -*-
import math
from multiprocessing import Queue as MPQueue
from random import choice
from random import randint
import time

from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_OKAY_CODE
from mantarray_desktop_app import STIM_MAX_PULSE_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import MICROS_PER_MILLIS
from mantarray_desktop_app.constants import SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app.constants import STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import VALID_STIMULATION_TYPES
from mantarray_desktop_app.utils.serial_comm import SUBPROTOCOL_BIPHASIC_ONLY_COMPONENTS
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty
from stdlib_utils import QUEUE_CHECK_TIMEOUT_SECONDS
from stdlib_utils import TestingQueue

from .helpers import random_bool

STATUS_BEACON_SIZE_BYTES = SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES + SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
HANDSHAKE_RESPONSE_SIZE_BYTES = STATUS_BEACON_SIZE_BYTES

TEST_HANDSHAKE_TIMESTAMP = 12345
TEST_HANDSHAKE = create_data_packet(TEST_HANDSHAKE_TIMESTAMP, SERIAL_COMM_HANDSHAKE_PACKET_TYPE, bytes(0))

DEFAULT_SIMULATOR_STATUS_CODES = bytes([SERIAL_COMM_OKAY_CODE] * (24 + 2))


def random_stim_type():
    return choice(list(VALID_STIMULATION_TYPES))


def random_time_index():
    return randint(100, 0xFFFFFFFFFF)


def random_time_offset():
    return randint(0, 0xFFFF)


def random_data_value():
    return randint(0, 0xFFFF)


def random_timestamp():
    return randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)


def get_random_subprotocol():
    return choice([get_random_stim_delay, get_random_stim_pulse])()


def get_random_stim_delay(duration_us=None):
    if duration_us is None:
        # make sure this is a whole number of ms
        duration_ms = randint(
            STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS // MICROS_PER_MILLIS,
            STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS // MICROS_PER_MILLIS,
        )
        # convert to µs
        duration_us = duration_ms * MICROS_PER_MILLIS
    elif not (
        STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS < duration_us < STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS
        or duration_us % MICROS_PER_MILLIS != 0
    ):
        raise ValueError(f"Invalid delay duration: {duration_us}")
    return {"type": "delay", "duration": duration_us}


def get_random_stim_pulse(
    *, allow_errors=False, pulse_type=None, total_subprotocol_dur_us=None, **provided_components
):
    if pulse_type is not None:
        if pulse_type not in ("monophasic", "biphasic"):
            raise ValueError(f"Invalid pulse type: {pulse_type}")
    else:
        # if a biphasic component is provided then the pulse must be biphasic, o/w choose randomly
        contains_biphasic_component = bool(set(provided_components) & SUBPROTOCOL_BIPHASIC_ONLY_COMPONENTS)
        is_biphasic = contains_biphasic_component or random_bool()
        pulse_type = "biphasic" if is_biphasic else "monophasic"

    all_valid_components = {"phase_one_duration", "phase_one_charge", "postphase_interval", "num_cycles"}
    if is_biphasic:
        all_valid_components |= SUBPROTOCOL_BIPHASIC_ONLY_COMPONENTS

    charge_components = {comp for comp in all_valid_components if "charge" in comp}
    duration_components = all_valid_components - charge_components - {"num_cycles"}
    pulse_dur_components = duration_components - {"postphase_interval"}

    total_provided_dur_us = sum(provided_components.get(comp, 0) for comp in duration_components)

    if not allow_errors:
        if invalid_components := set(provided_components) - all_valid_components:
            raise ValueError(f"Invalid {pulse_type} pulse component(s): {invalid_components}")
        if total_provided_dur_us > STIM_MAX_PULSE_DURATION_MICROSECONDS:
            raise ValueError(f"Given {pulse_type} pulse component(s) exceed max pulse duration")
        if total_subprotocol_dur_us is not None:
            if total_subprotocol_dur_us < total_provided_dur_us:
                raise ValueError(
                    f"total_subprotocol_dur_us: {total_subprotocol_dur_us} < sum of durs of provided components: {total_provided_dur_us}"
                )
            for providable_component in ("postphase_interval", "num_cycles"):
                if providable_component in provided_components:
                    raise ValueError(
                        f"Cannot provide both total_subprotocol_dur_us and {providable_component}"
                    )
        # TODO validate charge, will need to take a charge type param to do this

    if total_subprotocol_dur_us is not None:
        max_dur = min(STIM_MAX_PULSE_DURATION_MICROSECONDS, total_subprotocol_dur_us)
    else:
        max_dur = STIM_MAX_PULSE_DURATION_MICROSECONDS
    remaining_dur = max_dur - total_provided_dur_us
    max_dur_per_component = remaining_dur // len(duration_components)

    def _rand_dur():
        if max_dur_per_component < 1:
            return 0
        return randint(1, max_dur_per_component)

    pulse = {"type": pulse_type}
    pulse.update({comp: provided_components.get(comp, randint(1, 100) * 10) for comp in charge_components})
    pulse.update({comp: provided_components.get(comp, _rand_dur()) for comp in pulse_dur_components})

    if total_subprotocol_dur_us is not None:
        pulse_dur = sum(pulse[comp] for comp in pulse_dur_components)

        factor_pairs = [
            (i, total_subprotocol_dur_us // i)
            for i in range(1, int(total_subprotocol_dur_us**0.5) + 1)
            if total_subprotocol_dur_us % i == 0
        ]
        compatible_factors = [pair for pair in factor_pairs if any(f >= pulse_dur for f in pair)]
        random_factor_pair = choice(compatible_factors)
        random_cycle_dur = choice([f for f in random_factor_pair if f >= pulse_dur])

        pulse["postphase_interval"] = random_cycle_dur - pulse_dur
        pulse["num_cycles"] = total_subprotocol_dur_us // random_cycle_dur
    else:
        pulse["postphase_interval"] = provided_components.get("postphase_interval", _rand_dur())
        pulse["num_cycles"] = provided_components.get("num_cycles", _get_num_cycles(pulse))

    return pulse


def _get_num_cycles(pulse):
    total_dur = sum(v for k, v in pulse.items() if k != "type")

    min_num_cycles = math.ceil(STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS / total_dur)
    max_num_cycles = math.floor(STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS / total_dur)

    return randint(min_num_cycles, max_num_cycles)


def get_random_monophasic_pulse(**kwargs):
    return get_random_stim_pulse(pulse_type="monophasic", **kwargs)


def get_random_biphasic_pulse(**kwargs):
    return get_random_stim_pulse(pulse_type="biphasic", **kwargs)


def create_random_stim_info():
    protocol_ids = (None, "A", "B", "C", "D")
    return {
        "protocols": [
            {
                "protocol_id": pid,
                "stimulation_type": random_stim_type(),
                "run_until_stopped": choice([True, False]),
                "subprotocols": [
                    choice([get_random_stim_pulse(), get_random_stim_delay(50 * MICRO_TO_BASE_CONVERSION)])
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
    simulator = MantarrayMcSimulator(input_queue, output_queue, error_queue, testing_queue)

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
    simulator = MantarrayMcSimulatorNoBeacons(input_queue, output_queue, error_queue, testing_queue)

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

    # only join if the process has actually been started. Sometimes a test will fail before this happens in which case join will raise an error
    if simulator.is_alive():
        simulator.join()
