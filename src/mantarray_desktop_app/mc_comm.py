# -*- coding: utf-8 -*-
"""Process controlling communication with Mantarray Microcontroller."""
from __future__ import annotations

import datetime
from multiprocessing import Queue
from time import sleep
from typing import Any
from typing import List

import serial
import serial.tools.list_ports as list_ports

from .constants import SERIAL_COMM_BAUD_RATE
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .exceptions import SerialCommPacketRegistrationReadEmptyError
from .exceptions import SerialCommPacketRegistrationSearchExhaustedError
from .exceptions import SerialCommPacketRegistrationTimoutError
from .instrument_comm import InstrumentCommProcess
from .mc_simulator import MantarrayMcSimulator


def _get_formatted_utc_now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")


class McCommunicationProcess(InstrumentCommProcess):
    """Process that controls communication with the Mantarray Beta 2 Board(s).

    Args:
        board_queues: A tuple (the max number of MC board connections should be pre-defined, so not a mutable list) of tuples of 3 queues. The first queue is for input/communication from the main thread to this sub process, second queue is for communication from this process back to the main thread. Third queue is for streaming communication (largely fo raw data) to the process that controls writing to disk.
        fatal_error_reporter: A queue that reports back any unhandled errors that have caused the process to stop.
        suppress_setup_communication_to_main: if set to true (often during unit tests), messages during the _setup_before_loop will not be put into the queue to communicate back to the main process
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._is_registered_with_serial_comm: List[bool] = [False] * len(
            self._board_queues
        )

    def is_registered_with_serial_comm(self, board_idx: int) -> bool:
        """Mainly for use in testing."""
        is_registered: bool = self._is_registered_with_serial_comm[board_idx]
        return is_registered

    def create_connections_to_all_available_boards(self) -> None:
        """Create initial connections to boards.

        If a board is not present, a simulator will be put in.
        """
        num_boards_connected = self.determine_how_many_boards_are_connected()
        to_main_queue = self._board_queues[0][1]
        for i in range(num_boards_connected):
            msg = {
                "communication_type": "board_connection_status_change",
                "board_index": i,
            }

            for name in list(list_ports.comports()):
                name = str(name)
                # Tanner (3/15/21): As long as the STM eval board is used in the Mantarray, it will show up as so and we can look for the Mantarray by checking for STM in the name
                if "STM" not in name:
                    continue
                port = name[-5:-1]  # parse out the name of the COM port
                serial_obj = serial.Serial(
                    port=port,
                    baudrate=SERIAL_COMM_BAUD_RATE,
                    bytesize=8,
                    timeout=0,
                    stopbits=serial.STOPBITS_ONE,
                )
                break
            else:
                msg["message"] = "No board detected. Creating simulator."
                serial_obj = MantarrayMcSimulator(
                    Queue(),
                    Queue(),
                    Queue(),
                    Queue(),
                )
            self.set_board_connection(i, serial_obj)
            # TODO Tanner (3/15/21): add serial number and nickname to msg
            msg["is_connected"] = not isinstance(serial_obj, MantarrayMcSimulator)
            msg["timestamp"] = _get_formatted_utc_now()
            to_main_queue.put(msg)

    def _commands_for_each_run_iteration(self) -> None:
        board_idx = 0
        if (
            not self._is_registered_with_serial_comm[board_idx]
            and self._board_connections[board_idx] is not None
        ):
            self._register_magic_word(board_idx)
        # TODO: self._handle..()

    def _register_magic_word(self, board_idx: int) -> None:
        board = self._board_connections[board_idx]
        if board is None:
            raise NotImplementedError("board should never be None here")

        magic_word_len = len(SERIAL_COMM_MAGIC_WORD_BYTES)
        magic_word_test_bytes = board.read(size=magic_word_len)
        magic_word_test_bytes_len = len(magic_word_test_bytes)
        if magic_word_test_bytes_len < magic_word_len:
            # check for more bytes once every second for up to number of seconds in status beacon period
            for _ in range(SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS):
                num_bytes_remaining = magic_word_len - magic_word_test_bytes_len
                next_bytes = board.read(size=num_bytes_remaining)
                magic_word_test_bytes += next_bytes
                magic_word_test_bytes_len = len(magic_word_test_bytes)
                if magic_word_test_bytes_len == magic_word_len:
                    break
                sleep(1)
            else:
                # if the entire period has passed and no more bytes are available an error has occured with the Mantarray that is considered fatal
                raise SerialCommPacketRegistrationTimoutError()
        num_bytes_checked = 0
        while magic_word_test_bytes != SERIAL_COMM_MAGIC_WORD_BYTES:
            next_byte = board.read(size=1)
            if len(next_byte) == 0:
                raise SerialCommPacketRegistrationReadEmptyError()
            magic_word_test_bytes = magic_word_test_bytes[1:] + next_byte
            num_bytes_checked += 1
            if num_bytes_checked > SERIAL_COMM_MAX_PACKET_LENGTH_BYTES:
                raise SerialCommPacketRegistrationSearchExhaustedError()
        self._is_registered_with_serial_comm[board_idx] = True
