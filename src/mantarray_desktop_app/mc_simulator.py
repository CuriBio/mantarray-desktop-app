# -*- coding: utf-8 -*-
"""Mantarray Microcontroller Simulator."""
from __future__ import annotations

import logging
from multiprocessing import Queue
import queue
import random
import time
from typing import Any
from typing import Dict
from typing import Optional

from stdlib_utils import InfiniteProcess

from .constants import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .exceptions import UnrecognizedSimulatorTestCommandError


def _get_dur_since_last_status_beacon(last_time: float) -> float:
    return time.perf_counter() - last_time


class MantarrayMCSimulator(InfiniteProcess):
    """Simulate a running Mantarray instrument with Microcontroller.

    Args:
        input_queue: queue bytes sent to the simulator using the `write` method
        output_queue: queue bytes sent from the simulator using the `read` method
        fatal_error_reporter: a queue to report fatal errors back to the main process
        testing_queue: queue used to send commands to the simulator. Should only be used in unit tests
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
        self._time_of_last_status_beacon: Optional[float] = None
        self._leftover_read_bytes: Optional[bytes] = None

    def get_dur_since_init(self) -> int:
        return time.perf_counter_ns() - self._init_time

    def _get_timestamp_bytes(self) -> bytes:
        return self.get_dur_since_init().to_bytes(8, "little")

    def _send_status_beacon(self, truncate: bool = False) -> None:
        self._time_of_last_status_beacon = time.perf_counter()
        status_beacon = SERIAL_COMM_MAGIC_WORD_BYTES
        status_beacon += self._get_timestamp_bytes()
        status_beacon += b"\x00\x00\x04"
        status_beacon += bytes(4)
        if truncate:
            trunc_index = random.randint(0, 10)  # nosec
            status_beacon = status_beacon[trunc_index:]
        self._output_queue.put(status_beacon)

    def _commands_for_each_run_iteration(self) -> None:
        self._handle_status_beacon()
        self._handle_test_comm()

    def _handle_status_beacon(self) -> None:
        if self._time_of_last_status_beacon is None:
            self._send_status_beacon(truncate=True)
            return
        dur = _get_dur_since_last_status_beacon(self._time_of_last_status_beacon)
        if dur >= SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS:
            self._send_status_beacon()

    def _handle_test_comm(self) -> None:
        try:
            test_comm = self._testing_queue.get_nowait()
        except queue.Empty:
            return

        command = test_comm["command"]
        if command == "add_read_bytes":
            self._output_queue.put(test_comm["read_bytes"])
        else:
            raise UnrecognizedSimulatorTestCommandError(command)

    def read(self, size: int = 1) -> bytes:
        """Read the given number of bytes from the simulator."""
        empty = False
        try:
            next_packet = self._output_queue.get(
                timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
            )
        except queue.Empty:
            if self._leftover_read_bytes is None:
                return bytes(0)
            empty = True

        if self._leftover_read_bytes is not None:
            if empty:
                next_packet = self._leftover_read_bytes
            else:
                next_packet = self._leftover_read_bytes + next_packet
            self._leftover_read_bytes = None
        if len(next_packet) > size:
            size_diff = len(next_packet) - size
            self._leftover_read_bytes = next_packet[-size_diff:]
            next_packet = next_packet[:-size_diff]
        return next_packet

    def write(self, input_item: bytes) -> None:
        self._input_queue.put(input_item)
