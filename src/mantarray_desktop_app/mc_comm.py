# -*- coding: utf-8 -*-
"""Mantarray Microcontroller Simulator."""
from __future__ import annotations

import logging
from multiprocessing import Queue
from time import sleep
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .exceptions import SerialCommPacketRegistrationTimoutError
from .instrument_comm import InstrumentCommProcess


class McCommunicationProcess(InstrumentCommProcess):
    """Process that controls communication with the Mantarray Beta 2 Board(s).

    Args:
        board_queues: A tuple (the max number of MC board connections should be pre-defined, so not a mutable list) of tuples of 3 queues. The first queue is for input/communication from the main thread to this sub process, second queue is for communication from this process back to the main thread. Third queue is for streaming communication (largely fo raw data) to the process that controls writing to disk.
        fatal_error_reporter: A queue that reports back any unhandled errors that have caused the process to stop.
        suppress_setup_communication_to_main: if set to true (often during unit tests), messages during the _setup_before_loop will not be put into the queue to communicate back to the main process
    """

    def __init__(
        self,
        # pylint: disable=duplicate-code
        board_queues: Tuple[  # pylint-disable: duplicate-code
            Tuple[
                Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
                Queue[  # pylint: disable=unsubscriptable-object
                    Dict[str, Any]
                ],  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Queue[Any],  # pylint: disable=unsubscriptable-object
            ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            # pylint: disable=duplicate-code
        ],
        fatal_error_reporter: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ],
        # pylint: disable=duplicate-code
        suppress_setup_communication_to_main: bool = False,
        logging_level: int = logging.INFO,
    ):
        # pylint: disable=duplicate-code
        super().__init__(
            board_queues,
            fatal_error_reporter,  # pylint: disable=duplicate-code
            suppress_setup_communication_to_main,
            logging_level,
        )
        self._is_registered_with_serial_comm: List[bool] = [False] * len(
            self._board_queues
        )

    def is_registered_with_serial_comm(self, board_idx: int) -> bool:
        """Mainly for use in testing."""
        is_registered: bool = self._is_registered_with_serial_comm[board_idx]
        return is_registered

    def create_connections_to_all_available_boards(self) -> None:
        raise NotImplementedError()  # Tanner (12/18/21): adding this as a placeholder for now to override abstract method. This method will be defined and the NotImplementedError removed before this class is instantied in any source code

    def _commands_for_each_run_iteration(self) -> None:
        board_idx = 0
        if not self._is_registered_with_serial_comm[board_idx]:
            self._register_magic_word(board_idx)

    def _register_magic_word(self, board_idx: int) -> None:
        board = self._board_connections[board_idx]
        if board is None:
            return

        magic_word_test_bytes = board.read(size=8)
        magic_word_test_bytes_len = len(magic_word_test_bytes)
        if magic_word_test_bytes_len < len(SERIAL_COMM_MAGIC_WORD_BYTES):
            # check for more bytes once every second for up to number of seconds in status beacon period
            for _ in range(SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS):
                num_bytes_remaining = (
                    len(SERIAL_COMM_MAGIC_WORD_BYTES) - magic_word_test_bytes_len
                )
                next_bytes = board.read(size=num_bytes_remaining)
                magic_word_test_bytes += next_bytes
                magic_word_test_bytes_len = len(magic_word_test_bytes)
                if magic_word_test_bytes_len == len(SERIAL_COMM_MAGIC_WORD_BYTES):
                    break
                sleep(1)
            else:
                # if the entire period has passed and no more bytes are available an error has occured with the Mantarray that is considered fatal
                raise SerialCommPacketRegistrationTimoutError()
        while magic_word_test_bytes != SERIAL_COMM_MAGIC_WORD_BYTES:
            next_byte = board.read(size=1)
            magic_word_test_bytes = magic_word_test_bytes[1:] + next_byte
        self._is_registered_with_serial_comm[board_idx] = True
