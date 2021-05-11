# -*- coding: utf-8 -*-
"""FIFO Read Producer.

To calculate the value for a given construct or reference sensor at a given point timepoint, follow these steps:
    * Create timepoint(s):
        for cycle in range(num_cycles):
            for frame in range(8):
                sample_index = (
                    starting_sample_index
                    + (cycle * (ROUND_ROBIN_PERIOD // TIMESTEP_CONVERSION_FACTOR))
                    + (frame * (DATA_FRAME_PERIOD // TIMESTEP_CONVERSION_FACTOR))
                )
                sample_indices.append(sample_index)
                sawtooth_indices.append(sample_index / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD)
    * Get sawtooth_vals:
        sawtooth_vals = signal.sawtooth(sawtooth_indices, width=0.5)
    * Find data value for Construct Sensor:
        value = FIFO_READ_PRODUCER_DATA_OFFSET + int(FIFO_READ_PRODUCER_WELL_AMPLITUDE * ((well_index + 1) / 24 * 6)) * sawtooth_vals[idx]
    * Find data value for Reference Sensor:
        value = FIFO_READ_PRODUCER_DATA_OFFSET + FIFO_READ_PRODUCER_WELL_AMPLITUDE * (adc_number + 1) * sawtooth_vals[idx]
"""
from __future__ import annotations

from queue import Queue
import struct
import threading
from typing import Any
from typing import Dict

from scipy import signal
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteThread
from xem_wrapper import build_header_magic_number_bytes
from xem_wrapper import HEADER_MAGIC_NUMBER

from .constants import ADC_CH_TO_24_WELL_INDEX
from .constants import DATA_FRAME_PERIOD
from .constants import FIFO_READ_PRODUCER_CYCLES_PER_ITERATION
from .constants import FIFO_READ_PRODUCER_DATA_OFFSET
from .constants import FIFO_READ_PRODUCER_REF_AMPLITUDE
from .constants import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from .constants import FIFO_READ_PRODUCER_SLEEP_DURATION
from .constants import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from .constants import ROUND_ROBIN_PERIOD
from .constants import TIMESTEP_CONVERSION_FACTOR


def produce_data(num_cycles: int, starting_sample_index: int) -> bytearray:
    """Produce a given number of data cycles with given starting index.

    Args:
        num_cycles: number of data cycles to produce
        starting_sample_index: initial sample index of data

    Returns:
        A bytearray containing all data cycles produced
    """
    header_magic_number_bytes = build_header_magic_number_bytes(HEADER_MAGIC_NUMBER)
    # generate indices
    sample_indices = []
    sawtooth_indices = []
    for cycle in range(num_cycles):
        for frame in range(8):
            sample_index = (
                starting_sample_index
                + (cycle * (ROUND_ROBIN_PERIOD // TIMESTEP_CONVERSION_FACTOR))
                + (frame * (DATA_FRAME_PERIOD // TIMESTEP_CONVERSION_FACTOR))
            )
            sample_indices.append(sample_index)
            sawtooth_indices.append(sample_index / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD)
    # generate sawtooth values
    sawtooth_vals = signal.sawtooth(sawtooth_indices, width=0.5)
    # generate bytearray data
    data = bytearray(0)
    for cycle in range(num_cycles):
        for frame in range(8):
            idx = cycle * 8 + frame
            # add header
            data.extend(header_magic_number_bytes)
            # add sample index
            data.extend(struct.pack("<L", sample_indices[idx]))
            # add channel data
            for adc_num in range(6):
                # add metadata byte
                adc_ch_num = frame
                metadata_byte = (adc_num << 4) + adc_ch_num
                data.extend([metadata_byte])
                # add sawtooth data
                is_ref_sensor = adc_ch_num not in ADC_CH_TO_24_WELL_INDEX[adc_num]
                amplitude: int
                if is_ref_sensor:
                    amplitude = FIFO_READ_PRODUCER_REF_AMPLITUDE * (adc_num + 1)
                else:
                    scaling_factor = (ADC_CH_TO_24_WELL_INDEX[adc_num][adc_ch_num] + 1) / 24 * 6
                    amplitude = int(FIFO_READ_PRODUCER_WELL_AMPLITUDE * scaling_factor)
                data_value = FIFO_READ_PRODUCER_DATA_OFFSET + amplitude * sawtooth_vals[idx]
                data_byte = struct.pack("<L", int(data_value))
                data.extend(data_byte[:3])
    return data


class FIFOReadProducer(InfiniteThread):
    """Produce bytearrays of simulated Mantarray FIFO data.

    This thread should be run inside a RunningFIFOSimulator.

    Args:
        data_out_queue: a queue of outgoing data bytearrays to be used by the parent RunningFIFOSimulator
        fatal_error_reporter: a queue to report fatal errors back to the main process
        the_lock: a Threading lock to prevent simultaneous access of the data_out_queue by multiple threads
    """

    def __init__(
        self,
        data_out_queue: Queue[bytearray],  # pylint: disable=unsubscriptable-object
        fatal_error_reporter: Queue[str],  # pylint: disable=unsubscriptable-object
        the_lock: threading.Lock,
    ):
        super().__init__(fatal_error_reporter, the_lock)
        self._data_out_queue = data_out_queue
        self._sample_index = 0
        self._minimum_iteration_duration_seconds = FIFO_READ_PRODUCER_SLEEP_DURATION

    def _commands_for_each_run_iteration(self) -> None:
        data = produce_data(FIFO_READ_PRODUCER_CYCLES_PER_ITERATION, self._sample_index)
        # Tanner (4/30/20) is not sure how to test that we are using a lock here. The purpose of this lock is to ensure that data is not pulled from the queue at the same time it is being added.
        with self._lock:
            self._data_out_queue.put_nowait(data)
        self._sample_index += (
            FIFO_READ_PRODUCER_CYCLES_PER_ITERATION * ROUND_ROBIN_PERIOD
        ) // TIMESTEP_CONVERSION_FACTOR

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items: Dict[str, Any] = dict()
        queue_items["data_out"] = drain_queue(self._data_out_queue)
        return queue_items
