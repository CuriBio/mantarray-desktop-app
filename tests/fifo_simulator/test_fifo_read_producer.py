# -*- coding: utf-8 -*-
import queue
import struct
import threading

from mantarray_desktop_app import ADC_CH_TO_24_WELL_INDEX
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_REF_AMPLITUDE
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import FIFOReadProducer
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app.simulators import fifo_read_producer
import pytest
from scipy import signal
from stdlib_utils import invoke_process_run_and_check_errors
from xem_wrapper import build_header_magic_number_bytes
from xem_wrapper import HEADER_MAGIC_NUMBER

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..helpers import is_queue_eventually_empty
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


def test_FIFOReadProducer__super_is_called_during_init(mocker):
    data_out_queue = queue.Queue()
    error_queue = queue.Queue()
    mocked_super_init = mocker.spy(threading.Thread, "__init__")
    FIFOReadProducer(data_out_queue, error_queue, threading.Lock())
    assert mocked_super_init.call_count == 1


def test_FIFOReadProducer__increments_sample_idx_by_correct_number_of_round_robin_periods_each_iteration(
    mocker,
):
    data_out_queue = queue.Queue()
    error_queue = queue.Queue()
    producer_thread = FIFOReadProducer(data_out_queue, error_queue, threading.Lock())
    assert producer_thread._sample_index == 0

    expected_num_cycles = 21
    expected_cms_of_data = expected_num_cycles * ROUND_ROBIN_PERIOD
    mocker.patch.object(
        fifo_read_producer, "_get_cms_since_last_data_packet", side_effect=[expected_cms_of_data]
    )

    invoke_process_run_and_check_errors(producer_thread)
    assert producer_thread._sample_index * TIMESTEP_CONVERSION_FACTOR == expected_cms_of_data

    # clean up the queues to avoid BrokenPipe errors
    producer_thread.hard_stop()


def test_FIFOReadProducer__puts_sawtooth_waveform_in_data_out_queue_each_iteration_with_increasing_sample_idx(
    mocker,
):
    expected_num_cycles_1 = 30
    expected_num_cycles_2 = 17
    mocker.patch.object(
        fifo_read_producer,
        "_get_cms_since_last_data_packet",
        side_effect=[expected_num_cycles_1 * ROUND_ROBIN_PERIOD, expected_num_cycles_2 * ROUND_ROBIN_PERIOD],
    )

    expected_read_1 = produce_data(expected_num_cycles_1, 0)
    expected_read_2 = produce_data(
        expected_num_cycles_2,
        (expected_num_cycles_1 * ROUND_ROBIN_PERIOD) // TIMESTEP_CONVERSION_FACTOR,
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
            20,
            0,
            "returns correct bytearray given 20 cycles starting at sample index 0",
        ),
        (
            20,
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
                        + amplitude * signal.sawtooth(t / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5) * -1
                    )
                else:
                    scaling_factor = ADC_CH_TO_24_WELL_INDEX[adc_num][adc_ch_num] + 1
                    amplitude = FIFO_READ_PRODUCER_WELL_AMPLITUDE * scaling_factor
                    data_value = (
                        FIFO_READ_PRODUCER_DATA_OFFSET
                        + amplitude * signal.sawtooth(t / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5) * -1
                    )
                test_data_byte = struct.pack("<L", int(data_value))
                expected_data.extend(test_data_byte[:3])

    actual = produce_data(test_num_cycles, test_starting_sample_index)
    assert actual == expected_data


def test_FIFOReadProducter_hard_stop__drains_the_fifo_queue():
    data_out_queue = queue.Queue()
    error_queue = queue.Queue()
    producer_thread = FIFOReadProducer(data_out_queue, error_queue, threading.Lock())
    put_object_into_queue_and_raise_error_if_eventually_still_empty("blah", data_out_queue)
    actual_stop_results = producer_thread.hard_stop()
    assert is_queue_eventually_empty(data_out_queue)

    assert "data_out" in actual_stop_results
    assert actual_stop_results["data_out"] == ["blah"]
