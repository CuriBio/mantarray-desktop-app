# -*- coding: utf-8 -*-
"""Process controlling communication with Mantarray Microcontroller."""
from __future__ import annotations

from collections import deque
import datetime
import logging
from multiprocessing import Queue
import queue
from time import perf_counter
from time import perf_counter_ns
from time import sleep
from typing import Any
from typing import Deque
from typing import Dict
from typing import List
from typing import Optional
from zlib import crc32

from mantarray_file_manager import DATETIME_STR_FORMAT
import serial
import serial.tools.list_ports as list_ports
from stdlib_utils import put_log_message_into_queue

from .constants import NANOSECONDS_PER_CENTIMILLISECOND
from .constants import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from .constants import SERIAL_COMM_BAUD_RATE
from .constants import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from .constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from .constants import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from .constants import SERIAL_COMM_GET_METADATA_COMMAND_BYTE
from .constants import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from .constants import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MAIN_MODULE_ID
from .constants import SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
from .constants import SERIAL_COMM_MIN_PACKET_SIZE_BYTES
from .constants import SERIAL_COMM_MODULE_ID_INDEX
from .constants import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from .constants import SERIAL_COMM_PACKET_TYPE_INDEX
from .constants import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from .constants import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .constants import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .exceptions import SerialCommCommandResponseTimeoutError
from .exceptions import SerialCommIncorrectChecksumFromInstrumentError
from .exceptions import SerialCommIncorrectChecksumFromPCError
from .exceptions import SerialCommIncorrectMagicWordFromMantarrayError
from .exceptions import SerialCommPacketFromMantarrayTooSmallError
from .exceptions import SerialCommPacketRegistrationReadEmptyError
from .exceptions import SerialCommPacketRegistrationSearchExhaustedError
from .exceptions import SerialCommPacketRegistrationTimoutError
from .exceptions import SerialCommStatusBeaconTimeoutError
from .exceptions import SerialCommUntrackedCommandResponseError
from .exceptions import UnrecognizedCommandFromMainToMcCommError
from .exceptions import UnrecognizedSerialCommModuleIdError
from .exceptions import UnrecognizedSerialCommPacketTypeError
from .instrument_comm import InstrumentCommProcess
from .mc_simulator import MantarrayMcSimulator
from .serial_comm_utils import convert_to_metadata_bytes
from .serial_comm_utils import create_data_packet
from .serial_comm_utils import parse_metadata_bytes
from .serial_comm_utils import validate_checksum


def _get_formatted_utc_now() -> str:
    return datetime.datetime.utcnow().strftime(DATETIME_STR_FORMAT)


def _get_seconds_since_read_start(start: float) -> float:
    return perf_counter() - start


def _get_secs_since_last_handshake(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_last_beacon(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_command_sent(command_timestamp: float) -> float:
    return perf_counter() - command_timestamp


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
        self._init_time_ns: Optional[int] = None
        self._time_of_last_handshake_secs: Optional[float] = None
        self._time_of_last_beacon_secs: Optional[float] = None
        self._commands_awaiting_response: Deque[  # pylint: disable=unsubscriptable-object
            Dict[str, Any]
        ] = deque()

    def _reset_start_time(self) -> None:
        # TODO Tanner (3/19/21): Consider moving this functionality to InfiniteProcess since it applies to all running processes. See note in _setup_before_loop from 2/2/21
        self._init_time_ns = perf_counter_ns()

    def _setup_before_loop(self) -> None:
        # Tanner (2/2/21): Comparing perf_counter_ns values in a subprocess to those in the parent process have unexpected behavior in windows, so storing the initialization time after the process has been created in order to avoid issues
        self._reset_start_time()

        msg = {
            "communication_type": "log",
            "message": f"Microcontroller Communication Process initiated at {_get_formatted_utc_now()}",
        }
        to_main_queue = self._board_queues[0][1]
        if not self._suppress_setup_communication_to_main:
            to_main_queue.put_nowait(msg)
        self.create_connections_to_all_available_boards()

        board_idx = 0
        board = self._board_connections[board_idx]
        # Tanner (3/17/21): In the future, may want to create pyserial subclass and add start(), is_start_up_complete(), and some other version of .in_waiting that just returns a bool of whether or not there are bytes available to read
        if isinstance(
            board, MantarrayMcSimulator
        ):  # pragma: no cover  # Tanner (3/16/21): it's impossible to connect to any serial port in CI, so _setup_before_loop will always be called with a simulator and this if statement will always be true in pytest
            # Tanner (3/16/21): Current assumption is that a live mantarray will be running by the time we connect to it, so starting simulator here and waiting for it to complete start up
            board.start()
            while not board.is_start_up_complete():
                # sleep so as to not relentlessly ping the simulator
                sleep(0.1)

    def _teardown_after_loop(self) -> None:
        log_msg = f"Microcontroller Communication Process beginning teardown at {_get_formatted_utc_now()}"
        put_log_message_into_queue(
            logging.INFO,
            log_msg,
            self._board_queues[0][1],
            self.get_logging_level(),
        )
        board = self._board_connections[0]
        if (
            isinstance(board, MantarrayMcSimulator) and board.is_alive()
        ):  # pragma: no cover  # Tanner (3/19/21): only need to stop and join if the board is a running simulator
            board.hard_stop()  # hard stop to drain all queues of simulator
            board.join()
        super()._teardown_after_loop()

    def get_cms_since_init(self) -> int:
        if self._init_time_ns is None:
            return 0
        # pylint: disable=duplicate-code  # TODO Tanner (3/19/21): Consider moving this functionality to InfiniteProcess since it applies to multiple processes
        ns_since_init = perf_counter_ns() - self._init_time_ns
        return ns_since_init // NANOSECONDS_PER_CENTIMILLISECOND

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
                msg["message"] = f"Board detected with port name: {name}"
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
            # TODO Tanner (3/15/21): At some point during this process starting up, need to get serial number and nickname (maybe just all metadata?) and return to main since it can't be done until magic word is registered
            msg["is_connected"] = not isinstance(serial_obj, MantarrayMcSimulator)
            msg["timestamp"] = _get_formatted_utc_now()
            to_main_queue.put_nowait(msg)

    def _send_data_packet(
        self,
        board_idx: int,
        module_id: int,
        packet_type: int,
        data_to_send: bytes = bytes(0),
    ) -> None:
        data_packet = create_data_packet(
            self.get_cms_since_init(), module_id, packet_type, data_to_send
        )
        board = self._board_connections[board_idx]
        if board is None:
            raise NotImplementedError(
                "Board should not be None when processing a command from main"
            )
        board.write(data_packet)

    def _commands_for_each_run_iteration(self) -> None:
        """Ordered actions to perform each iteration.

        This process must be responsive to communication from the main process and then the instrument before anything else.

        1. Process next communication from main. This process's highest priority is to be responsive to the main process and should check for messages from main first. These messages will let this process know when to send commands to the instrument.Process
        2. Send handshake to instrument when necessary. Second highest priority is to let the instrument know that this process and the rest of the software are alive and responsive.
        3. Process data coming from the instrument. Processing data coming from the instrument is the highest priority task after sending data to it.
        4. Make sure the beacon is not overdue. If the beacon were overdue, it's reasonable to assume something caused the instrument to stop working. This task should happen after handling of sending/receiving data from the instrument and main process.
        5. Make sure commands are not overdue. This task should happen after the instrument has been determined to be working properly.
        """
        self._process_next_communication_from_main()
        self._handle_sending_handshake()
        self._handle_incoming_data()
        self._handle_beacon_tracking()
        self._handle_command_tracking()

        # process can be soft stopped if no commands in queue from main and no command responses needed from instrument
        self._process_can_be_soft_stopped = (
            not bool(self._commands_awaiting_response)
            and self._board_queues[0][
                0
            ].empty()  # Tanner (3/23/21): consider replacing this with is_queue_eventually_empty
        )

    def _process_next_communication_from_main(self) -> None:
        """Process the next communication sent from the main process.

        Will just return if no comms from main in queue.
        """
        input_queue = self._board_queues[0][0]
        try:
            comm_from_main = input_queue.get_nowait()
        except queue.Empty:
            return
        board_idx = 0

        communication_type = comm_from_main["communication_type"]
        if communication_type == "mantarray_naming":
            if comm_from_main["command"] == "set_mantarray_nickname":
                nickname = comm_from_main["mantarray_nickname"]
                self._send_data_packet(
                    board_idx,
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                    bytes([SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE])
                    + convert_to_metadata_bytes(nickname),
                )
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "to_instrument":
            if comm_from_main["command"] == "get_metadata":
                self._send_data_packet(
                    board_idx,
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                    bytes([SERIAL_COMM_GET_METADATA_COMMAND_BYTE]),
                )
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        else:
            raise UnrecognizedCommandFromMainToMcCommError(
                f"Invalid communication_type: {communication_type}"
            )

        comm_from_main["timepoint"] = perf_counter()
        self._commands_awaiting_response.append(comm_from_main)

    def _handle_sending_handshake(self) -> None:
        board_idx = 0
        if self._board_connections[board_idx] is None:
            return
        if self._time_of_last_handshake_secs is None:
            self._send_handshake(board_idx)
            return
        seconds_elapsed = _get_secs_since_last_handshake(
            self._time_of_last_handshake_secs
        )
        if seconds_elapsed >= SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS:
            self._send_handshake(board_idx)

    def _send_handshake(self, board_idx: int) -> None:
        self._time_of_last_handshake_secs = perf_counter()
        self._send_data_packet(
            board_idx,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
        )
        self._commands_awaiting_response.append(
            {"command": "handshake", "timepoint": self._time_of_last_handshake_secs}
        )

    def _handle_incoming_data(self) -> None:
        board_idx = 0
        board = self._board_connections[board_idx]
        if board is None:
            return
        if not self._is_registered_with_serial_comm[board_idx]:
            self._register_magic_word(board_idx)
        elif board.in_waiting > 0:
            magic_word_bytes = board.read(size=len(SERIAL_COMM_MAGIC_WORD_BYTES))
            if magic_word_bytes != SERIAL_COMM_MAGIC_WORD_BYTES:
                raise SerialCommIncorrectMagicWordFromMantarrayError(
                    str(magic_word_bytes)
                )
        else:
            return
        packet_size_bytes = board.read(size=SERIAL_COMM_PACKET_INFO_LENGTH_BYTES)
        packet_size = int.from_bytes(packet_size_bytes, byteorder="little")
        data_packet_bytes = board.read(size=packet_size)
        # TODO Tanner (3/15/21): eventually make sure the expected number of bytes are read

        # validate checksum before handling the communication. Need to reconstruct the whole packet to get the correct checksum
        full_data_packet = (
            SERIAL_COMM_MAGIC_WORD_BYTES + packet_size_bytes + data_packet_bytes
        )
        is_checksum_valid = validate_checksum(full_data_packet)
        if not is_checksum_valid:
            calculated_checksum = crc32(
                full_data_packet[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES]
            )
            received_checksum = int.from_bytes(
                full_data_packet[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:],
                byteorder="little",
            )
            raise SerialCommIncorrectChecksumFromInstrumentError(
                f"Checksum Received: {received_checksum}, Checksum Calculated: {calculated_checksum}, Full Data Packet: {str(full_data_packet)}"
            )
        if packet_size < SERIAL_COMM_MIN_PACKET_SIZE_BYTES:
            raise SerialCommPacketFromMantarrayTooSmallError(
                f"Invalid packet length received: {packet_size}, Full Data Packet: {str(full_data_packet)}"
            )
        module_id = full_data_packet[SERIAL_COMM_MODULE_ID_INDEX]
        if module_id == SERIAL_COMM_MAIN_MODULE_ID:
            self._process_main_module_comm(full_data_packet)
        else:
            raise UnrecognizedSerialCommModuleIdError(module_id)

    def _process_main_module_comm(self, comm_from_instrument: bytes) -> None:
        packet_body = comm_from_instrument[
            SERIAL_COMM_ADDITIONAL_BYTES_INDEX:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES
        ]

        packet_type = comm_from_instrument[SERIAL_COMM_PACKET_TYPE_INDEX]
        if packet_type == SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE:
            returned_packet = SERIAL_COMM_MAGIC_WORD_BYTES + packet_body
            raise SerialCommIncorrectChecksumFromPCError(returned_packet)

        if packet_type == SERIAL_COMM_STATUS_BEACON_PACKET_TYPE:
            self._time_of_last_beacon_secs = perf_counter()
            # TODO Tanner (3/17/21): Implement this in a story dedicated to parsing/handling errors codes in status beacons and handshakes
        elif packet_type == SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE:
            response_data = packet_body[SERIAL_COMM_TIMESTAMP_LENGTH_BYTES:]
            if not self._commands_awaiting_response:
                raise SerialCommUntrackedCommandResponseError(
                    f"Full Data Packet: {str(comm_from_instrument)}"
                )
            prev_command = self._commands_awaiting_response.popleft()
            if prev_command["command"] == "handshake":
                # see note above: Tanner (3/17/21)
                return
            if prev_command["command"] == "get_metadata":
                prev_command["metadata"] = parse_metadata_bytes(response_data)
            del prev_command[
                "timepoint"
            ]  # main process does not need to know the timepoint and is not expecting this key in the dictionary returned to it
            self._board_queues[0][1].put_nowait(
                prev_command
            )  # Tanner (3/17/21): to be consistent with OkComm, command responses will be sent back to main after the command is acknowledged by the Mantarray
        else:
            module_id = comm_from_instrument[SERIAL_COMM_MODULE_ID_INDEX]
            raise UnrecognizedSerialCommPacketTypeError(
                f"Packet Type ID: {packet_type} is not defined for Module ID: {module_id}"
            )

    def _register_magic_word(self, board_idx: int) -> None:
        board = self._board_connections[board_idx]
        if board is None:
            raise NotImplementedError("board should never be None here")

        magic_word_len = len(SERIAL_COMM_MAGIC_WORD_BYTES)
        magic_word_test_bytes = board.read(size=magic_word_len)
        magic_word_test_bytes_len = len(magic_word_test_bytes)
        # wait for at least 8 bytes to be read
        if magic_word_test_bytes_len < magic_word_len:
            # check for more bytes once every second for up to four seconds longer than number of seconds in status beacon period # Tanner (3/16/21): issue seen with simulator taking slightly longer than status beacon period to send next data packet
            for _ in range(SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS + 4):
                num_bytes_remaining = magic_word_len - magic_word_test_bytes_len
                next_bytes = board.read(size=num_bytes_remaining)
                magic_word_test_bytes += next_bytes
                magic_word_test_bytes_len = len(magic_word_test_bytes)
                if magic_word_test_bytes_len == magic_word_len:
                    break
                sleep(1)
            else:
                # if the entire period has passed and no more bytes are available an error has occured with the Mantarray that is considered fatal
                raise SerialCommPacketRegistrationTimoutError(magic_word_test_bytes)
        # read more bytes until the magic word is registered, the timeout value is reached, or the maximum number of bytes are read
        num_bytes_checked = 0
        read_dur_secs = 0.0
        start = perf_counter()
        while (
            magic_word_test_bytes != SERIAL_COMM_MAGIC_WORD_BYTES
            and read_dur_secs < SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
        ):
            next_byte = board.read(size=1)
            if len(next_byte) == 1:
                magic_word_test_bytes = magic_word_test_bytes[1:] + next_byte
                num_bytes_checked += 1
                # A magic word should be encountered if this many bytes are read. If not, we can assume there was a problem with the mantarray
                if num_bytes_checked > SERIAL_COMM_MAX_PACKET_LENGTH_BYTES:
                    raise SerialCommPacketRegistrationSearchExhaustedError()
            read_dur_secs = _get_seconds_since_read_start(start)
        # if this point is reached and the magic word has not been found, then at some point no additional bytes were being read
        if magic_word_test_bytes != SERIAL_COMM_MAGIC_WORD_BYTES:
            raise SerialCommPacketRegistrationReadEmptyError()
        self._is_registered_with_serial_comm[board_idx] = True

    def _handle_beacon_tracking(self) -> None:
        if self._time_of_last_beacon_secs is None:
            return
        secs_since_last_beacon_received = _get_secs_since_last_beacon(
            self._time_of_last_beacon_secs
        )
        if secs_since_last_beacon_received >= SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS:
            raise SerialCommStatusBeaconTimeoutError()

    def _handle_command_tracking(self) -> None:
        if not self._commands_awaiting_response:
            return
        oldest_command = self._commands_awaiting_response[0]
        secs_since_command_sent = _get_secs_since_command_sent(
            oldest_command["timepoint"]
        )
        if secs_since_command_sent >= SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS:
            raise SerialCommCommandResponseTimeoutError(oldest_command["command"])
