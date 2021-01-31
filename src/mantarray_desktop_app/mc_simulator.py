# -*- coding: utf-8 -*-
"""Mantarray Microcontroller Simulator."""
import logging
from multiprocessing import Queue
import queue
from typing import Any
from typing import Dict

from stdlib_utils import InfiniteProcess

from .constants import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES


class MantarrayMCSimulator(InfiniteProcess):
    """Simulate a running Mantarray machine with Microcontroller.

    Args:
        arg1: does something
    """

    def __init__(
        self,
        input_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        output_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
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

    def read(self) -> Any:
        try:
            next_packet = self._output_queue.get(
                timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
            )
        except queue.Empty:
            return bytearray(0)

        return next_packet

    def write(self, input_item: Any) -> None:
        self._input_queue.put(input_item)
