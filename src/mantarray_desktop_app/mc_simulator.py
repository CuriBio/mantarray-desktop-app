# -*- coding: utf-8 -*-
"""Mantarray Microcontroller Simulator."""
from __future__ import annotations

import logging
from multiprocessing import Queue
import queue
import random
import time
from time import perf_counter
from time import perf_counter_ns
from typing import Any
from typing import Dict
from typing import Optional
from typing import Union
from zlib import crc32

from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import SECONDS_TO_SLEEP_BETWEEN_CHECKING_QUEUE_SIZE

from .constants import NANOSECONDS_PER_CENTIMILLISECOND
from .constants import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from .constants import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from .constants import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MAIN_MODULE_ID
from .constants import SERIAL_COMM_MODULE_ID_INDEX
from .constants import SERIAL_COMM_PACKET_TYPE_INDEX
from .constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .exceptions import UnrecognizedSerialCommModuleIdError
from .exceptions import UnrecognizedSerialCommPacketTypeError
from .exceptions import UnrecognizedSimulatorTestCommandError


def _get_secs_since_last_status_beacon(last_time: float) -> float:
    return perf_counter() - last_time


def _get_checksum_bytes(packet: bytes) -> bytes:
    return crc32(packet).to_bytes(4, byteorder="little")


def _get_packet_length_bytes(packet: bytes) -> bytes:
    # add 4 for checksum at end of packet
    packet_length = len(packet) + 4
    return packet_length.to_bytes(2, byteorder="little")


class MantarrayMCSimulator(InfiniteProcess):
    """Simulate a running Mantarray instrument with Microcontroller.

    Args:
        input_queue: queue bytes sent to the simulator using the `write` method
        output_queue: queue bytes sent from the simulator using the `read` method
        fatal_error_reporter: a queue to report fatal errors back to the main process
        testing_queue: queue used to send commands to the simulator. Should only be used in unit tests
        read_timeout_seconds: number of seconds to wait until read is of desired size before returning how ever many bytes have been read. Timeout should be set to 0 unless a non-zero value is necessary for unit testing
    """

    def __init__(
        self,
        input_queue: Queue[
            bytes
        ],  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        output_queue: Queue[bytes],  # pylint: disable=unsubscriptable-object
        fatal_error_reporter: Queue[  # pylint: disable=unsubscriptable-object
            Dict[str, Any]
        ],
        testing_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        logging_level: int = logging.INFO,
        read_timeout_seconds: Union[int, float] = 0,
    ) -> None:
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._output_queue = output_queue
        self._input_queue = input_queue
        self._testing_queue = testing_queue
        self._init_time_ns: Optional[int] = None
        self._time_of_last_status_beacon_secs: Optional[float] = None
        self._leftover_read_bytes: Optional[bytes] = None
        self._read_timeout_seconds = read_timeout_seconds
        self._status_code_bits = bytes(4)

    def _setup_before_loop(self) -> None:
        # Tanner (2/2/21): Comparing perf_counter_ns values in a subprocess to those in the parent process have unexpected behavior in windows, so storing the initialization time after the process has been created in order to avoid issues
        self._init_time_ns = perf_counter_ns()

    def get_cms_since_init(self) -> int:
        if self._init_time_ns is None:
            return 0
        ns_since_init = perf_counter_ns() - self._init_time_ns
        return ns_since_init // NANOSECONDS_PER_CENTIMILLISECOND

    def _get_cms_timestamp_bytes(self) -> bytes:
        return self.get_cms_since_init().to_bytes(8, byteorder="little")

    def _send_data_packet(
        self,
        module_id: int,
        packet_type: int,
        data_to_send: bytes,
        truncate: bool = False,
    ) -> None:
        packet_body = self._get_cms_timestamp_bytes()
        packet_body += bytes([module_id, packet_type])
        packet_body += data_to_send
        num_bytes_in_content = _get_packet_length_bytes(packet_body)

        data_packet = SERIAL_COMM_MAGIC_WORD_BYTES
        data_packet += num_bytes_in_content
        data_packet += packet_body
        data_packet += _get_checksum_bytes(data_packet)
        if truncate:
            trunc_end = (
                int.from_bytes(num_bytes_in_content, byteorder="little")
                + len(SERIAL_COMM_MAGIC_WORD_BYTES)
                + 1
            )
            trunc_index = random.randint(  # nosec B311 # Tanner (2/4/21): Bandit blacklisted this psuedo-random generator for cryptographic security reasons that do not apply to the desktop app.
                0, trunc_end
            )
            data_packet = data_packet[trunc_index:]
        self._output_queue.put_nowait(data_packet)

    def _commands_for_each_run_iteration(self) -> None:
        self._handle_comm_from_pc()
        self._handle_status_beacon()
        self._handle_test_comm()

    def _handle_comm_from_pc(self) -> None:
        try:
            comm_from_pc = self._input_queue.get_nowait()
        except queue.Empty:
            return

        module_id = comm_from_pc[SERIAL_COMM_MODULE_ID_INDEX]
        packet_type = comm_from_pc[SERIAL_COMM_PACKET_TYPE_INDEX]
        if module_id == SERIAL_COMM_MAIN_MODULE_ID:
            if packet_type == SERIAL_COMM_HANDSHAKE_PACKET_TYPE:
                expected_checksum = crc32(comm_from_pc[:-4])
                actual_checksum = int.from_bytes(comm_from_pc[-4:], byteorder="little")
                if actual_checksum == expected_checksum:
                    self._send_data_packet(
                        SERIAL_COMM_MAIN_MODULE_ID,
                        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
                        self._status_code_bits,
                    )
                    return
                # remove magic word before returning message to PC
                magic_word_len = len(SERIAL_COMM_MAGIC_WORD_BYTES)
                trimmed_comm_from_pc = comm_from_pc[magic_word_len:]
                self._send_data_packet(
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE,
                    trimmed_comm_from_pc,
                )
            else:
                raise UnrecognizedSerialCommPacketTypeError(
                    f"Packet Type ID: {packet_type} is not defined for Module ID: {module_id}"
                )
        else:
            raise UnrecognizedSerialCommModuleIdError(module_id)

    def _handle_status_beacon(self) -> None:
        if self._time_of_last_status_beacon_secs is None:
            self._send_status_beacon(truncate=True)
            return
        seconds_elapsed = _get_secs_since_last_status_beacon(
            self._time_of_last_status_beacon_secs
        )
        if seconds_elapsed >= SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS:
            self._send_status_beacon(truncate=False)

    def _send_status_beacon(self, truncate: bool = False) -> None:
        self._time_of_last_status_beacon_secs = perf_counter()
        self._send_data_packet(
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
            self._status_code_bits,
            truncate,
        )

    def _handle_test_comm(self) -> None:
        try:
            test_comm = self._testing_queue.get_nowait()
        except queue.Empty:
            return

        command = test_comm["command"]
        if command == "add_read_bytes":
            self._output_queue.put_nowait(test_comm["read_bytes"])
        else:
            raise UnrecognizedSimulatorTestCommandError(command)

    def read(self, size: int = 1) -> bytes:
        """Read the given number of bytes from the simulator."""
        # first check leftover bytes from last read
        read_bytes = bytes(0)
        if self._leftover_read_bytes is not None:
            read_bytes = self._leftover_read_bytes
            self._leftover_read_bytes = None
        # try to get bytes until either timeout occurs or given size is reached or exceeded
        start = perf_counter()
        read_dur_secs = 0.0
        while len(read_bytes) < size and read_dur_secs < self._read_timeout_seconds:
            read_dur_secs = perf_counter() - start
            try:
                next_bytes = self._output_queue.get_nowait()
                read_bytes += next_bytes
            except queue.Empty:
                pass
            time.sleep(SECONDS_TO_SLEEP_BETWEEN_CHECKING_QUEUE_SIZE)
        # if this read exceeds given size then store extra bytes for the next read
        if len(read_bytes) > size:
            size_diff = len(read_bytes) - size
            self._leftover_read_bytes = read_bytes[-size_diff:]
            read_bytes = read_bytes[:-size_diff]
        return read_bytes

    def write(self, input_item: bytes) -> None:
        self._input_queue.put_nowait(input_item)

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items = {
            "input_queue": drain_queue(self._input_queue),
            "output_queue": drain_queue(self._output_queue),
            "testing_queue": drain_queue(self._testing_queue),
        }
        return queue_items
