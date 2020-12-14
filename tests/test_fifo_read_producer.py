# -*- coding: utf-8 -*-
import queue
import struct
import threading
import time

from mantarray_desktop_app import ADC_CH_TO_24_WELL_INDEX
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_CYCLES_PER_ITERATION
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_REF_AMPLITUDE
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_SLEEP_DURATION
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import FIFOReadProducer
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
import pytest
from pytest import approx
from scipy import signal
from stdlib_utils import invoke_process_run_and_check_errors
from xem_wrapper import build_header_magic_number_bytes
from xem_wrapper import HEADER_MAGIC_NUMBER

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .helpers import is_queue_eventually_empty
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


def test_FIFOReadProducer__super_is_called_during_init(mocker):
    data_out_queue = queue.Queue()
    error_queue = queue.Queue()
    mocked_super_init = mocker.spy(threading.Thread, "__init__")
    FIFOReadProducer(data_out_queue, error_queue, threading.Lock())
    assert mocked_super_init.call_count == 1


def test_FIFOReadProducer__sleeps_for_correct_duration_every_cycle(mocker):
    test_start_timepoint = 0
    test_stop_timepoint = 10
    dummy_val = -1
    expected_sleep_time = (
        FIFO_READ_PRODUCER_SLEEP_DURATION
        - (test_stop_timepoint - test_start_timepoint) / 10 ** 9
    )

    # Tanner (4/28/20): dummy vals are for calls to perf_counter_ns in setup and second iteration respectively.
    counter_vals = [dummy_val, test_start_timepoint, test_stop_timepoint, dummy_val]

    mocked_sleep = mocker.patch.object(time, "sleep", autospec=True)
    mocker.patch.object(time, "perf_counter_ns", side_effect=counter_vals)

    data_out_queue = queue.Queue()
    error_queue = queue.Queue()
    producer_thread = FIFOReadProducer(data_out_queue, error_queue, threading.Lock())

    # Tanner (4/30/20): num_iterations=2 so that we check for idle time once. There is no check on the final iteration.
    invoke_process_run_and_check_errors(producer_thread, num_iterations=2)

    mocked_sleep_first_call = mocked_sleep.call_args_list[0]
    assert mocked_sleep_first_call[0][0] == approx(expected_sleep_time)

    # clean up the queues to avoid BrokenPipe errors
    producer_thread.hard_stop()


def test_FIFOReadProducer__increments_sample_idx_by_correct_number_of_round_robin_periods_each_iteration():
    data_out_queue = queue.Queue()
    error_queue = queue.Queue()
    producer_thread = FIFOReadProducer(data_out_queue, error_queue, threading.Lock())
    assert producer_thread._sample_index == 0  # pylint: disable=protected-access
    invoke_process_run_and_check_errors(producer_thread)
    assert (
        producer_thread._sample_index  # pylint: disable=protected-access
        * TIMESTEP_CONVERSION_FACTOR
        == FIFO_READ_PRODUCER_CYCLES_PER_ITERATION * ROUND_ROBIN_PERIOD
    )

    # clean up the queues to avoid BrokenPipe errors
    producer_thread.hard_stop()


def test_FIFOReadProducer__puts_sawtooth_waveform_in_data_out_queue_each_iteration_with_increasing_sample_idx():
    expected_read_1 = produce_data(FIFO_READ_PRODUCER_CYCLES_PER_ITERATION, 0)
    expected_read_2 = produce_data(
        FIFO_READ_PRODUCER_CYCLES_PER_ITERATION,
        (FIFO_READ_PRODUCER_CYCLES_PER_ITERATION * ROUND_ROBIN_PERIOD)
        // TIMESTEP_CONVERSION_FACTOR,
    )

    data_out_queue = queue.Queue()
    error_queue = queue.Queue()
    producer_thread = FIFOReadProducer(data_out_queue, error_queue, threading.Lock())

    invoke_process_run_and_check_errors(producer_thread, num_iterations=2)

    actual_1 = data_out_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_1 == expected_read_1
    actual_2 = data_out_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_2 == expected_read_2

    # clean up the queues to avoid BrokenPipe errors
    producer_thread.hard_stop()


@pytest.mark.parametrize(
    """test_num_cycles,test_starting_sample_index,test_description""",
    [
        (0, 0, "returns correct bytearray given 0 cycles starting at sample index 0"),
        (1, 0, "returns correct bytearray given 1 cycle starting at sample index 0"),
        (
            FIFO_READ_PRODUCER_CYCLES_PER_ITERATION,
            0,
            "returns correct bytearray given 20 cycles starting at sample index 0",
        ),
        (
            FIFO_READ_PRODUCER_CYCLES_PER_ITERATION,
            20000,
            "returns correct bytearray given 20 cycles starting at sample index 20000",
        ),
    ],
)
def test_produce_data__returns_correct_bytearray_with_given_num_cycles_and_starting_sample_index(
    test_num_cycles, test_starting_sample_index, test_description
):
    expected_data = bytearray(0)
    for cycle in range(test_num_cycles):
        for frame in range(8):
            # add header
            expected_data.extend(build_header_magic_number_bytes(HEADER_MAGIC_NUMBER))
            sample_index = (
                test_starting_sample_index
                + (cycle * (ROUND_ROBIN_PERIOD // TIMESTEP_CONVERSION_FACTOR))
                + (frame * (DATA_FRAME_PERIOD // TIMESTEP_CONVERSION_FACTOR))
            )
            # add sample index
            expected_data.extend(struct.pack("<L", sample_index))
            # add channel data
            for adc_num in range(6):
                # add metadata byte
                adc_ch_num = frame
                metadata_byte = (adc_num << 4) + adc_ch_num
                expected_data.extend([metadata_byte])
                # add sawtooth data
                is_ref_sensor = adc_ch_num not in ADC_CH_TO_24_WELL_INDEX[adc_num]
                data_value = 0
                t = sample_index
                if is_ref_sensor:
                    amplitude = FIFO_READ_PRODUCER_REF_AMPLITUDE * (adc_num + 1)
                    data_value = (
                        FIFO_READ_PRODUCER_DATA_OFFSET
                        + amplitude
                        * signal.sawtooth(
                            t / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5
                        )
                    )
                else:
                    scaling_factor = (
                        (ADC_CH_TO_24_WELL_INDEX[adc_num][adc_ch_num] + 1) / 24 * 6
                    )
                    amplitude = FIFO_READ_PRODUCER_WELL_AMPLITUDE * scaling_factor
                    data_value = (
                        FIFO_READ_PRODUCER_DATA_OFFSET
                        + amplitude
                        * signal.sawtooth(
                            t / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5
                        )
                    )
                test_data_byte = struct.pack("<L", int(data_value))
                expected_data.extend(test_data_byte[:3])

    actual = produce_data(test_num_cycles, test_starting_sample_index)
    assert actual == expected_data


def test_FIFOReadProducter_hard_stop__drains_the_fifo_queue():
    data_out_queue = queue.Queue()
    error_queue = queue.Queue()
    producer_thread = FIFOReadProducer(data_out_queue, error_queue, threading.Lock())
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        "blah", data_out_queue
    )
    actual_stop_results = producer_thread.hard_stop()
    assert is_queue_eventually_empty(data_out_queue)

    assert "data_out" in actual_stop_results
    assert actual_stop_results["data_out"] == ["blah"]
