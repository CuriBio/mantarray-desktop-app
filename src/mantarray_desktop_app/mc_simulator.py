# -*- coding: utf-8 -*-
"""Mantarray Microcontroller Simulator."""
from __future__ import annotations

import logging
from multiprocessing import Queue
import queue
import time
from typing import Any
from typing import Dict

from stdlib_utils import InfiniteProcess

from .constants import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS


def _get_dur_since_last_status_beacon(last_time: float) -> float:
    return time.perf_counter() - last_time


class MantarrayMCSimulator(InfiniteProcess):
    """Simulate a running Mantarray machine with Microcontroller.

    Args:
        arg1: does something
    """

    def __init__(
        self,
        input_queue: Queue[bytes],  # pylint: disable=unsubscriptable-object
        output_queue: Queue[bytes],  # pylint: disable=unsubscriptable-object
        fatal_error_reporter: Queue[  # pylint: disable=unsubscriptable-object
            Dict[str, Any]
        ],
        testing_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        logging_level: int = logging.INFO,
    ) -> None:
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._output_queue = output_queue
        self._input_queue = input_queue
        self._testing_queue = testing_queue
        self._init_time = time.perf_counter_ns()
        self._send_status_beacon()

    def get_dur_since_init(self) -> int:
        return time.perf_counter_ns() - self._init_time

    def _get_timestamp_bytes(self) -> bytes:
        return self.get_dur_since_init().to_bytes(8, "little")

    def _send_status_beacon(self) -> None:
        status_beacon = SERIAL_COMM_MAGIC_WORD_BYTES
        status_beacon += self._get_timestamp_bytes()
        status_beacon += b"\x00\x00\x04"
        status_beacon += bytes(4)
        self._output_queue.put(status_beacon)
        self._time_of_last_status_beacon = time.perf_counter()

    def _commands_for_each_run_iteration(self) -> None:
        self._handle_status_beacon()

    def _handle_status_beacon(self) -> None:
        dur = _get_dur_since_last_status_beacon(self._time_of_last_status_beacon)
        if dur >= SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS:
            self._send_status_beacon()

    def read(self) -> bytes:
        try:
            next_packet = self._output_queue.get(
                timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
            )
            return next_packet
        except queue.Empty:
            return bytes(0)

    def write(self, input_item: bytes) -> None:
        self._input_queue.put(input_item)
