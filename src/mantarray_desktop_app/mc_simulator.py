# -*- coding: utf-8 -*-
"""Mantarray Microcontroller Simulator."""
from __future__ import annotations

import logging
from multiprocessing import Queue
import queue
import random
import time
from time import perf_counter
from typing import Any
from typing import Dict
from typing import Optional
from typing import Union
from uuid import UUID

from immutabledict import immutabledict
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import SECONDS_TO_SLEEP_BETWEEN_CHECKING_QUEUE_SIZE

from .constants import BOOTUP_COUNTER_UUID
from .constants import MAX_MC_REBOOT_DURATION_SECONDS
from .constants import PCB_SERIAL_NUMBER_UUID
from .constants import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from .constants import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from .constants import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from .constants import SERIAL_COMM_GET_METADATA_COMMAND_BYTE
from .constants import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from .constants import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MAIN_MODULE_ID
from .constants import SERIAL_COMM_METADATA_BYTES_LENGTH
from .constants import SERIAL_COMM_MODULE_ID_INDEX
from .constants import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from .constants import SERIAL_COMM_PACKET_TYPE_INDEX
from .constants import SERIAL_COMM_REBOOT_COMMAND_BYTE
from .constants import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from .constants import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .constants import SERIAL_COMM_TIMESTAMP_BYTES_INDEX
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .constants import TAMPER_FLAG_UUID
from .constants import TOTAL_WORKING_HOURS_UUID
from .exceptions import SerialCommTooManyMissedHandshakesError
from .exceptions import UnrecognizedSerialCommModuleIdError
from .exceptions import UnrecognizedSerialCommPacketTypeError
from .exceptions import UnrecognizedSimulatorTestCommandError
from .serial_comm_utils import convert_to_metadata_bytes
from .serial_comm_utils import create_data_packet
from .serial_comm_utils import validate_checksum


MAGIC_WORD_LEN = len(SERIAL_COMM_MAGIC_WORD_BYTES)
AVERAGE_MC_REBOOT_DURATION_SECONDS = MAX_MC_REBOOT_DURATION_SECONDS / 2


def _get_secs_since_last_handshake(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_last_status_beacon(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_reboot_command(last_time: float) -> float:
    return perf_counter() - last_time


class MantarrayMcSimulator(InfiniteProcess):
    """Simulate a running Mantarray instrument with Microcontroller.

    Args:
        input_queue: queue bytes sent to the simulator using the `write` method
        output_queue: queue bytes sent from the simulator using the `read` method
        fatal_error_reporter: a queue to report fatal errors back to the main process
        testing_queue: queue used to send commands to the simulator. Should only be used in unit tests
        read_timeout_seconds: number of seconds to wait until read is of desired size before returning how ever many bytes have been read. Timeout should be set to 0 except in unit testing scenarios where necessary
    """

    default_mantarray_nickname = "Mantarray Simulator (MCU)"
    default_mantarray_serial_number = "M02001901"
    default_pcb_serial_number = (
        "TBD"  # TODO Tanner (3/17/21): implement this once the format is determined
    )
    default_firmware_version = "0.0.0"
    default_metadata_values: Dict[UUID, Any] = immutabledict(
        {
            BOOTUP_COUNTER_UUID: 0,
            TOTAL_WORKING_HOURS_UUID: 0,
            TAMPER_FLAG_UUID: 0,
            MANTARRAY_SERIAL_NUMBER_UUID: default_mantarray_serial_number,
            MANTARRAY_NICKNAME_UUID: default_mantarray_nickname,
            PCB_SERIAL_NUMBER_UUID: default_pcb_serial_number,
            MAIN_FIRMWARE_VERSION_UUID: default_firmware_version,
        }
    )

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
        self._time_of_last_status_beacon_secs: Optional[float] = None
        self._time_of_last_handshake_secs: Optional[float] = None
        self._reboot_time_secs: Optional[float] = None
        self._leftover_read_bytes = bytes(0)
        self._read_timeout_seconds = read_timeout_seconds
        self._metadata_dict: Dict[bytes, bytes] = dict()
        self._reset_metadata_dict()
        self._status_code_bits: bytes
        self._reset_status_code_bits()

    @property
    def in_waiting(self) -> int:
        """Only use to determine if a read can be done.

        For example, check if this value if non-zero.

        It does not represent the full number of bytes that can be read.
        """
        if len(self._leftover_read_bytes) == 0:
            try:
                self._leftover_read_bytes = self._output_queue.get_nowait()
            except queue.Empty:
                return 0
        return len(self._leftover_read_bytes)

    def _reset_status_code_bits(self) -> None:
        self._status_code_bits = bytes(4)

    def _reset_metadata_dict(self) -> None:
        for uuid_key, metadata_value in self.default_metadata_values.items():
            self._metadata_dict[uuid_key.bytes] = convert_to_metadata_bytes(
                metadata_value
            )

    def get_metadata_dict(self) -> Dict[bytes, bytes]:
        """Mainly for use in unit tests."""
        return self._metadata_dict

    def _send_data_packet(
        self,
        module_id: int,
        packet_type: int,
        data_to_send: bytes = bytes(0),
        truncate: bool = False,
    ) -> None:
        data_packet = create_data_packet(
            self.get_cms_since_init(), module_id, packet_type, data_to_send
        )
        if truncate:
            trunc_index = random.randint(  # nosec B311 # Tanner (2/4/21): Bandit blacklisted this psuedo-random generator for cryptographic security reasons that do not apply to the desktop app.
                0, len(data_packet) - 1
            )
            data_packet = data_packet[trunc_index:]
        self._output_queue.put_nowait(data_packet)

    def _commands_for_each_run_iteration(self) -> None:
        self._handle_test_comm()
        # if _reboot_time_secs is not None, this means the simulator is in a "reboot" phase
        if self._reboot_time_secs is not None:
            secs_since_reboot = _get_secs_since_reboot_command(self._reboot_time_secs)
            # if secs_since_reboot is less than the reboot duration, simulator is still in the 'reboot' phase. Commands from PC will be ignored and status beacons will not be sent
            if (
                secs_since_reboot < AVERAGE_MC_REBOOT_DURATION_SECONDS
            ):  # Tanner (3/31/21): rebooting should be much faster than the maximum allowed time for rebooting, so arbitrarily picking
                return
            self._handle_reboot_completion()
        self._handle_comm_from_pc()
        self._handle_status_beacon()
        self._check_handshake()

    def _handle_reboot_completion(self) -> None:
        drain_queue(self._input_queue)
        self._reset_start_time()
        self._reboot_time_secs = None
        self._reset_status_code_bits()
        self._send_status_beacon(truncate=False)

    def _handle_comm_from_pc(self) -> None:
        try:
            comm_from_pc = self._input_queue.get_nowait()
        except queue.Empty:
            return

        # validate checksum before handling the communication
        checksum_is_valid = validate_checksum(comm_from_pc)
        if not checksum_is_valid:
            # remove magic word before returning message to PC
            trimmed_comm_from_pc = comm_from_pc[MAGIC_WORD_LEN:]
            self._send_data_packet(
                SERIAL_COMM_MAIN_MODULE_ID,
                SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE,
                trimmed_comm_from_pc,
            )
            return
        module_id = comm_from_pc[SERIAL_COMM_MODULE_ID_INDEX]
        if module_id == SERIAL_COMM_MAIN_MODULE_ID:
            self._process_main_module_command(comm_from_pc)
        else:
            raise UnrecognizedSerialCommModuleIdError(module_id)

    def _process_main_module_command(self, comm_from_pc: bytes) -> None:
        timestamp_from_pc_bytes = comm_from_pc[
            SERIAL_COMM_TIMESTAMP_BYTES_INDEX : SERIAL_COMM_TIMESTAMP_BYTES_INDEX
            + SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
        ]
        response_body = timestamp_from_pc_bytes

        packet_type = comm_from_pc[SERIAL_COMM_PACKET_TYPE_INDEX]
        if packet_type == SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE:
            command_byte = comm_from_pc[SERIAL_COMM_ADDITIONAL_BYTES_INDEX]
            if command_byte == SERIAL_COMM_REBOOT_COMMAND_BYTE:
                self._reboot_time_secs = perf_counter()
            elif command_byte == SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE:
                start_idx = SERIAL_COMM_ADDITIONAL_BYTES_INDEX + 1
                nickname_bytes = comm_from_pc[
                    start_idx : start_idx + SERIAL_COMM_METADATA_BYTES_LENGTH
                ]
                self._metadata_dict[MANTARRAY_NICKNAME_UUID.bytes] = nickname_bytes
            elif command_byte == SERIAL_COMM_GET_METADATA_COMMAND_BYTE:
                metadata_bytes = bytes(0)
                for key, value in self._metadata_dict.items():
                    metadata_bytes += key + value
                response_body += metadata_bytes
            else:
                # TODO Tanner (3/4/21): Determine what to do if command_byte, module_id, or packet_type are incorrect. It may make more sense to respond with a message rather than raising an error
                raise NotImplementedError(command_byte)
        elif packet_type == SERIAL_COMM_HANDSHAKE_PACKET_TYPE:
            self._time_of_last_handshake_secs = perf_counter()
            response_body += self._status_code_bits
        else:
            module_id = comm_from_pc[SERIAL_COMM_MODULE_ID_INDEX]
            raise UnrecognizedSerialCommPacketTypeError(
                f"Packet Type ID: {packet_type} is not defined for Module ID: {module_id}"
            )
        self._send_data_packet(
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
            response_body,
        )

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

    def _check_handshake(self) -> None:
        if self._time_of_last_handshake_secs is None:
            return
        time_of_last_handshake_secs = _get_secs_since_last_handshake(
            self._time_of_last_handshake_secs
        )
        if (
            time_of_last_handshake_secs
            >= SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
            * SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
        ):
            raise SerialCommTooManyMissedHandshakesError()

    def _handle_test_comm(self) -> None:
        try:
            test_comm = self._testing_queue.get_nowait()
        except queue.Empty:
            return

        command = test_comm["command"]
        if command == "send_single_beacon":
            self._send_data_packet(
                SERIAL_COMM_MAIN_MODULE_ID,
                SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
                self._status_code_bits,
            )
        elif command == "add_read_bytes":
            read_bytes = test_comm["read_bytes"]
            if not isinstance(read_bytes, list):
                read_bytes = [read_bytes]
            for read in read_bytes:
                self._output_queue.put_nowait(read)
        elif command == "set_status_code_bits":
            self._status_code_bits = test_comm["status_code_bits"]
        elif command == "set_metadata":
            for key, value in test_comm["metadata_values"].items():
                value_bytes = convert_to_metadata_bytes(value)
                self._metadata_dict[key.bytes] = value_bytes
        else:
            raise UnrecognizedSimulatorTestCommandError(command)

    def read(self, size: int = 1) -> bytes:
        """Read the given number of bytes from the simulator."""
        # first check leftover bytes from last read
        read_bytes = bytes(0)
        if len(self._leftover_read_bytes) > 0:
            read_bytes = self._leftover_read_bytes
            self._leftover_read_bytes = bytes(0)
        # try to get bytes until either timeout occurs or given size is reached or exceeded
        start = perf_counter()
        read_dur_secs = 0.0
        while len(read_bytes) < size and read_dur_secs <= self._read_timeout_seconds:
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
