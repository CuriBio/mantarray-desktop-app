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
from mantarray_desktop_app import STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import MICROS_PER_MILLI
from mantarray_desktop_app.constants import SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app.constants import STIM_MAX_DUTY_CYCLE_PERCENTAGE
from mantarray_desktop_app.constants import STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import VALID_STIMULATION_TYPES
from mantarray_desktop_app.utils.serial_comm import SUBPROTOCOL_BIPHASIC_ONLY_COMPONENTS
from mantarray_desktop_app.utils.stimulation import get_pulse_duty_cycle_dur_us
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty
from stdlib_utils import QUEUE_CHECK_TIMEOUT_SECONDS
from stdlib_utils import TestingQueue

from .helpers import random_bool

MAX_POSTPHASE_INTERVAL_DUR_MICROSECONDS = 2**32 - 1  # max uint32 value

# Tanner (/17/23): arbitrarily deciding to use 10ms as the min pulse duration
MIN_PULSE_DUR_MICROSECONDS = 10 * MICROS_PER_MILLI
MAX_PULSE_DUR_MICROSECONDS = (
    STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS + MAX_POSTPHASE_INTERVAL_DUR_MICROSECONDS
)

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


def get_random_subprotocol(*, allow_loop=False, total_subprotocol_dur_us=None):
    subprotocol_fns = [get_random_stim_delay, get_random_stim_pulse]

    if allow_loop:
        if total_subprotocol_dur_us is not None:
            raise ValueError("Cannot supply total_subprotocol_dur_us if allowing loops")
        subprotocol_fns.append(get_random_stim_loop)

        subprotocol = choice(subprotocol_fns)()
    else:
        subprotocol = choice(subprotocol_fns)(total_subprotocol_dur_us=total_subprotocol_dur_us)

    return subprotocol


def get_random_stim_delay(total_subprotocol_dur_us=None):
    duration_us = total_subprotocol_dur_us
    if duration_us is None:
        # make sure this is a whole number of ms
        duration_ms = randint(
            STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS // MICROS_PER_MILLI,
            STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS // MICROS_PER_MILLI,
        )
        # convert to µs
        duration_us = duration_ms * MICROS_PER_MILLI
    elif not (
        STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS < duration_us < STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS
        or duration_us % MICROS_PER_MILLI != 0
    ):
        raise ValueError(f"Invalid delay duration: {duration_us}")
    return {"type": "delay", "duration": duration_us}


def get_random_stim_pulse(*, pulse_type=None, total_subprotocol_dur_us=None, freq=None, num_cycles=None):
    # validate or randomize pulse type
    if pulse_type is not None:
        if pulse_type not in ("monophasic", "biphasic"):
            raise ValueError(f"Invalid pulse type: {pulse_type}")
        is_biphasic = pulse_type == "biphasic"
    else:
        is_biphasic = random_bool()
        pulse_type = "biphasic" if is_biphasic else "monophasic"

    # validate any params with provided values individually
    if total_subprotocol_dur_us is not None:
        if total_subprotocol_dur_us < STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS:
            raise ValueError(
                f"total_subprotocol_dur_us: {total_subprotocol_dur_us} must be >= {STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS}"
            )
        if total_subprotocol_dur_us > STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS:
            raise ValueError(
                f"total_subprotocol_dur_us: {total_subprotocol_dur_us} must be <= {STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS}"
            )
    if num_cycles is not None:
        if num_cycles <= 0:
            raise ValueError("num_cycles must be > 0")
        if not isinstance(num_cycles, int):
            raise ValueError("num_cycles must be an integer")
    if freq is not None and not (0 < freq < 100):
        raise ValueError("freq must be > 0 and < 100")

    # don't allow all 3 params to be given at once since the 3rd can be implied from the other 2
    if total_subprotocol_dur_us and num_cycles and freq:
        raise ValueError("Can only provide 2/3 of total_subprotocol_dur_us, num_cycles, and freq at a time")

    # validate params together and gerenate random values for those not given
    if total_subprotocol_dur_us is not None:
        if num_cycles:
            # calculate and validate pulse dur
            pulse_dur_us = total_subprotocol_dur_us / num_cycles
            if not pulse_dur_us.is_integer():
                raise ValueError(
                    f"total_subprotocol_dur_us: {total_subprotocol_dur_us} and num_cycles: {num_cycles} are"
                    f" incompatible, they create a non-int pulse duration: {pulse_dur_us}"
                )
            pulse_dur_us = int(pulse_dur_us)
            if not (MIN_PULSE_DUR_MICROSECONDS <= pulse_dur_us <= MAX_PULSE_DUR_MICROSECONDS):
                raise ValueError(
                    f"total_subprotocol_dur_us: {total_subprotocol_dur_us} and num_cycles: {num_cycles} are"
                    f" incompatible, they create a pulse duration: {pulse_dur_us} µs which is not in the"
                    f" range [{MIN_PULSE_DUR_MICROSECONDS}, {MAX_PULSE_DUR_MICROSECONDS}]"
                )
        elif freq:
            # calculate and validate num cycles
            pulse_dur_us = MICRO_TO_BASE_CONVERSION // freq
            num_cycles = total_subprotocol_dur_us / pulse_dur_us
            if not num_cycles.is_integer():
                raise ValueError(
                    f"total_subprotocol_dur_us: {total_subprotocol_dur_us} and freq: {freq} are incompatible,"
                    f" they create a non-int number of cycles: {num_cycles}"
                )
            num_cycles = int(num_cycles)
        else:
            # create random pulse dur and num cycles

            def is_valid_pulse_dur(dur_us):
                return (
                    total_subprotocol_dur_us % dur_us == 0
                    and MIN_PULSE_DUR_MICROSECONDS < dur_us < MAX_PULSE_DUR_MICROSECONDS
                )

            num_cycles, pulse_dur_us = choice(
                [
                    (n, dur_us)
                    for n in range(1, int(total_subprotocol_dur_us**0.5) + 1)
                    if is_valid_pulse_dur(dur_us := total_subprotocol_dur_us // n)
                ]
            )
    elif num_cycles:
        if freq:
            # calculate pulse dur, calculate and validate total_subprotocol_dur_us
            pulse_dur_us = MICRO_TO_BASE_CONVERSION // freq
            total_subprotocol_dur_us = num_cycles * pulse_dur_us
            if not (
                STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
                < total_subprotocol_dur_us
                < STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS
            ):
                raise ValueError(
                    f"num_cycles: {num_cycles} and freq: {freq} are incompatible, they create a"
                    f" total_subprotocol_dur_us: {total_subprotocol_dur_us} which is not in the range"
                    f" [{STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS}, {STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS}]"
                )
        else:
            # calculate random pulse dur
            max_pulse_dur = min(
                math.floor(STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS / num_cycles),
                MAX_PULSE_DUR_MICROSECONDS,
            )
            min_pulse_dur = max(
                math.ceil(STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS / num_cycles), MIN_PULSE_DUR_MICROSECONDS
            )
            pulse_dur_us = randint(min_pulse_dur, max_pulse_dur)
    else:
        # create random pulse dur and num cycles
        if freq:
            pulse_dur_us = MICRO_TO_BASE_CONVERSION // freq
        else:
            pulse_dur_us = randint(MIN_PULSE_DUR_MICROSECONDS, MAX_PULSE_DUR_MICROSECONDS)
        num_cycles = _get_rand_num_cycles_from_pulse_dur(pulse_dur_us)

    # set up randomizer for duty cycle components
    all_pulse_components = {"phase_one_duration", "phase_one_charge", "postphase_interval"}
    if is_biphasic:
        all_pulse_components |= SUBPROTOCOL_BIPHASIC_ONLY_COMPONENTS

    charge_components = {comp for comp in all_pulse_components if "charge" in comp}
    duty_cycle_dur_comps = all_pulse_components - charge_components - {"postphase_interval"}

    min_dur_per_duty_cycle_comp = max(
        1,
        (pulse_dur_us - MAX_POSTPHASE_INTERVAL_DUR_MICROSECONDS) // len(duty_cycle_dur_comps),
    )
    max_dur_per_duty_cycle_comp = min(
        math.floor(pulse_dur_us * STIM_MAX_DUTY_CYCLE_PERCENTAGE), STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS
    ) // len(duty_cycle_dur_comps)

    def _rand_dur_for_duty_cycle_comp():
        return randint(min_dur_per_duty_cycle_comp, max_dur_per_duty_cycle_comp)

    # create pulse dict
    pulse = {"type": pulse_type, "num_cycles": num_cycles}
    # add duration components
    pulse.update({comp: _rand_dur_for_duty_cycle_comp() for comp in duty_cycle_dur_comps})
    pulse["postphase_interval"] = pulse_dur_us - get_pulse_duty_cycle_dur_us(pulse)
    # add charge components
    pulse.update({comp: randint(1, 100) * 10 for comp in charge_components})

    return pulse


def _get_rand_num_cycles_from_pulse_dur(pulse_dur_us):
    max_num_cycles = math.floor(STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS / pulse_dur_us)
    min_num_cycles = math.floor(STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS / pulse_dur_us)
    num_cycles = randint(min_num_cycles, max_num_cycles)
    return num_cycles


def get_random_monophasic_pulse(**kwargs):
    return get_random_stim_pulse(pulse_type="monophasic", **kwargs)


def get_random_biphasic_pulse(**kwargs):
    return get_random_stim_pulse(pulse_type="biphasic", **kwargs)


def get_random_stim_loop():
    raise NotImplementedError("TODO")


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
