# -*- coding: utf-8 -*-
"""Process controlling communication with Mantarray Microcontroller."""
from __future__ import annotations

from collections import deque
import datetime
import logging
from multiprocessing import Queue
import queue
from time import perf_counter
from time import sleep
from typing import Any
from typing import Deque
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from zlib import crc32

from mantarray_file_manager import DATETIME_STR_FORMAT
import serial
import serial.tools.list_ports as list_ports
from stdlib_utils import put_log_message_into_queue

from .constants import MAX_MC_REBOOT_DURATION_SECONDS
from .constants import MICROSECONDS_PER_CENTIMILLISECOND
from .constants import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from .constants import SERIAL_COMM_BAUD_RATE
from .constants import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from .constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from .constants import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from .constants import SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE
from .constants import SERIAL_COMM_FATAL_ERROR_CODE
from .constants import SERIAL_COMM_GET_METADATA_COMMAND_BYTE
from .constants import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from .constants import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from .constants import SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE
from .constants import SERIAL_COMM_IDLE_READY_CODE
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE
from .constants import SERIAL_COMM_MAIN_MODULE_ID
from .constants import SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
from .constants import SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES
from .constants import SERIAL_COMM_MIN_PACKET_BODY_SIZE_BYTES
from .constants import SERIAL_COMM_MODULE_ID_INDEX
from .constants import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from .constants import SERIAL_COMM_PACKET_TYPE_INDEX
from .constants import SERIAL_COMM_PLATE_EVENT_PACKET_TYPE
from .constants import SERIAL_COMM_REBOOT_COMMAND_BYTE
from .constants import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from .constants import SERIAL_COMM_SET_TIME_COMMAND_BYTE
from .constants import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from .constants import SERIAL_COMM_SOFT_ERROR_CODE
from .constants import SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .constants import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from .constants import SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_TIME_SYNC_READY_CODE
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .exceptions import InstrumentDataStreamingAlreadyStartedError
from .exceptions import InstrumentDataStreamingAlreadyStoppedError
from .exceptions import InstrumentFatalError
from .exceptions import InstrumentRebootTimeoutError
from .exceptions import InstrumentSoftError
from .exceptions import MagnetometerConfigUpdateWhileDataStreamingError
from .exceptions import MantarrayInstrumentError
from .exceptions import SerialCommCommandResponseTimeoutError
from .exceptions import SerialCommHandshakeTimeoutError
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
from .serial_comm_utils import convert_bytes_to_config_dict
from .serial_comm_utils import convert_to_metadata_bytes
from .serial_comm_utils import convert_to_timestamp_bytes
from .serial_comm_utils import create_data_packet
from .serial_comm_utils import create_magnetometer_config_bytes
from .serial_comm_utils import get_serial_comm_timestamp
from .serial_comm_utils import parse_metadata_bytes
from .serial_comm_utils import validate_checksum
from .utils import check_barcode_is_valid


if 6 < 9:  # pragma: no cover # protect this from zimports deleting the pylint disable statement
    from .data_parsing_cy import (  # pylint: disable=import-error # Tanner (5/12/21): unsure why pylint is unable to recognize cython import
        handle_data_packets,
    )


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


def _get_secs_since_reboot_start(reboot_start_time: float) -> float:
    return perf_counter() - reboot_start_time


# pylint: disable=too-many-instance-attributes
class McCommunicationProcess(InstrumentCommProcess):
    """Process that controls communication with the Mantarray Beta 2 Board(s).

    Args:
        board_queues: A tuple (the max number of MC board connections should be predefined, so not a mutable list) of tuples of 3 queues. The first queue is for input/communication from the main thread to this sub process, second queue is for communication from this process back to the main thread. Third queue is for streaming communication (largely of raw data) to the process that controls writing to disk.
        fatal_error_reporter: A queue that reports back any unhandled errors that have caused the process to stop.
        suppress_setup_communication_to_main: if set to true (often during unit tests), messages during the _setup_before_loop will not be put into the queue to communicate back to the main process
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._error: Optional[Exception] = None
        self._in_simulation_mode = False
        self._simulator_error_queues: List[
            Optional[Queue[Tuple[Exception, str]]]  # pylint: disable=unsubscriptable-object
        ] = [None] * len(self._board_queues)
        self._is_instrument_in_error_state = False
        self._num_wells = 24
        self._is_registered_with_serial_comm: List[bool] = [False] * len(self._board_queues)
        self._auto_get_metadata = False
        self._time_of_last_handshake_secs: Optional[float] = None
        self._time_of_last_beacon_secs: Optional[float] = None
        self._commands_awaiting_response: Deque[  # pylint: disable=unsubscriptable-object
            Dict[str, Any]
        ] = deque()
        self._is_waiting_for_reboot = False  # Tanner (4/1/21): This flag indicates that a reboot command has been sent and a status beacon following reboot completion has not been received. It does not imply that the instrument has begun rebooting.
        self._time_of_reboot_start: Optional[
            float
        ] = None  # Tanner (4/1/21): This value will be None until this process receives a response to a reboot command. It will be set back to None after receiving a status beacon upon reboot completion
        self._magnetometer_config: Dict[int, Dict[int, bool]] = dict()
        self._num_data_channels_on = 0
        self._sampling_period_us = 0
        self._is_data_streaming = False
        self._data_packet_cache = bytes(0)

    def _setup_before_loop(self) -> None:
        super()._setup_before_loop()

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
        if isinstance(
            board, MantarrayMcSimulator
        ):  # pragma: no cover  # Tanner (3/16/21): it's impossible to connect to any serial port in CI, so _setup_before_loop will always be called with a simulator and this if statement will always be true in pytest
            # Tanner (3/16/21): Current assumption is that a live mantarray will be running by the time we connect to it, so starting simulator here and waiting for it to complete start up
            board.start()
            while not board.is_start_up_complete():
                # sleep so as to not relentlessly ping the simulator
                sleep(0.1)
        self._auto_get_metadata = True

    def _teardown_after_loop(self) -> None:
        board_idx = 0
        log_msg = f"Microcontroller Communication Process beginning teardown at {_get_formatted_utc_now()}"
        put_log_message_into_queue(
            logging.INFO,
            log_msg,
            self._board_queues[board_idx][1],
            self.get_logging_level(),
        )
        board = self._board_connections[board_idx]
        if board is not None:
            if self._error is not None and not isinstance(self._error, MantarrayInstrumentError):
                # if error occurred in software, send dump EEPROM command and wait for instrument to respond to command before flushing serial data. If the firmware caught an error in itself the EEPROM contents should already be logged and this command can be skipped here
                self._send_data_packet(
                    board_idx,
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                    bytes([SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE]),
                )
                sleep(1)
            # flush and log remaining serial data
            remaining_serial_data = bytes(0)
            while board.in_waiting > 0:
                remaining_serial_data += board.read(size=SERIAL_COMM_MAX_PACKET_LENGTH_BYTES)
            serial_data_flush_msg = f"Remaining Serial Data {str(remaining_serial_data)}"
            put_log_message_into_queue(
                logging.INFO,
                serial_data_flush_msg,
                self._board_queues[board_idx][1],
                self.get_logging_level(),
            )
            if (
                isinstance(board, MantarrayMcSimulator) and board.is_alive()
            ):  # pragma: no cover  # Tanner (3/19/21): only need to stop and join if the board is a running simulator
                board.hard_stop()  # hard stop to drain all queues of simulator
                board.join()
        super()._teardown_after_loop()

    def _report_fatal_error(self, the_err: Exception) -> None:
        self._error = the_err
        super()._report_fatal_error(the_err)

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
            # don't make new connection if a board is already connected
            if self._board_connections[i] is not None:
                continue
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
                    Queue(), Queue(), Queue(), Queue(), num_wells=self._num_wells
                )
            self.set_board_connection(i, serial_obj)
            msg["is_connected"] = not isinstance(serial_obj, MantarrayMcSimulator)
            msg["timestamp"] = _get_formatted_utc_now()
            to_main_queue.put_nowait(msg)

    def set_board_connection(self, board_idx: int, board: Union[MantarrayMcSimulator, serial.Serial]) -> None:
        super().set_board_connection(board_idx, board)
        self._in_simulation_mode = isinstance(board, MantarrayMcSimulator)
        if self._in_simulation_mode:
            self._simulator_error_queues[board_idx] = board.get_fatal_error_reporter()

    def _send_data_packet(
        self,
        board_idx: int,
        module_id: int,
        packet_type: int,
        data_to_send: bytes = bytes(0),
    ) -> None:
        # TODO Tanner (4/7/21): change timestamp to microseconds when the real Mantarray makes the switch
        data_packet = create_data_packet(
            get_serial_comm_timestamp() // MICROSECONDS_PER_CENTIMILLISECOND,
            module_id,
            packet_type,
            data_to_send,
        )
        board = self._board_connections[board_idx]
        if board is None:
            raise NotImplementedError("Board should not be None when sending a command to it")
        board.write(data_packet)

    def _set_magnetometer_config(
        self, magnetometer_config: Dict[int, Dict[int, bool]], sampling_period: int
    ) -> None:
        self._magnetometer_config = magnetometer_config
        num_data_channels_on = 0
        for config_dict in magnetometer_config.values():
            num_data_channels_on += sum(config_dict.values())
        self._num_data_channels_on = num_data_channels_on
        self._sampling_period_us = sampling_period

    def _commands_for_each_run_iteration(self) -> None:
        """Ordered actions to perform each iteration.

        This process must be responsive to communication from the main process and then the instrument before anything else.

        After reboot command is sent, no more commands should be sent until reboot completes.
        During instrument reboot, should only check for incoming data make sure no commands are awaiting a response.

        1. Before doing anything, simulator errors must be checked for. If they go unchecked before performing comm with the simulator, and error may be raised in this process that masks the simulator's error which is actually the root of the problem.
        2. Process next communication from main. This process's next highest priority is to be responsive to the main process and should check for messages from main first. These messages will let this process know when to send commands to the instrument.
        3. Send handshake to instrument when necessary. Third highest priority is to let the instrument know that this process and the rest of the software are alive and responsive.
        4. Process packets coming from the instrument. This is the highest priority task after sending data to it.
        5. Make sure the beacon is not overdue, unless instrument is rebooting. If the beacon is overdue, it's reasonable to assume something caused the instrument to stop working. This task should happen after handling of sending/receiving data from the instrument and main process.
        6. Make sure commands are not overdue. This task should happen after the instrument has been determined to be working properly.
        7. If rebooting, make sure that the reboot has not taken longer than the max allowed reboot time.
        """
        if self._in_simulation_mode:
            if self._check_simulator_error():
                self.stop()
                return
        if not self._is_waiting_for_reboot:
            self._process_next_communication_from_main()
            self._handle_sending_handshake()
        if self._is_data_streaming:
            self._handle_data_stream()
        else:
            self._handle_comm_from_instrument()
        self._handle_beacon_tracking()
        self._handle_command_tracking()

        if self._is_waiting_for_reboot:
            self._check_reboot_status()

        # process can be soft stopped if no commands in queue from main and no command responses needed from instrument
        self._process_can_be_soft_stopped = (
            not bool(self._commands_awaiting_response)
            and self._board_queues[0][
                0
            ].empty()  # Tanner (3/23/21): consider replacing this with is_queue_eventually_empty
        )

    def _process_next_communication_from_main(self) -> None:
        """Process the next communication sent from the main process.

        Will just return if no communications from main in queue.
        """
        input_queue = self._board_queues[0][0]
        try:
            comm_from_main = input_queue.get_nowait()
        except queue.Empty:
            return
        board_idx = 0
        bytes_to_send: bytes

        communication_type = comm_from_main["communication_type"]
        if communication_type == "mantarray_naming":
            if comm_from_main["command"] == "set_mantarray_nickname":
                nickname = comm_from_main["mantarray_nickname"]
                bytes_to_send = bytes([SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE]) + convert_to_metadata_bytes(
                    nickname
                )
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "to_instrument":
            if comm_from_main["command"] == "reboot":
                bytes_to_send = bytes([SERIAL_COMM_REBOOT_COMMAND_BYTE])
                self._is_waiting_for_reboot = True
            elif comm_from_main["command"] == "dump_eeprom":
                bytes_to_send = bytes([SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE])
            elif comm_from_main["command"] == "start_managed_acquisition":
                bytes_to_send = bytes([SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE])
            elif comm_from_main["command"] == "stop_managed_acquisition":
                bytes_to_send = bytes([SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE])
            elif comm_from_main["command"] == "change_magnetometer_config":
                self._set_magnetometer_config(
                    comm_from_main["magnetometer_config"], comm_from_main["sampling_period"]
                )
                if self._is_data_streaming:
                    raise MagnetometerConfigUpdateWhileDataStreamingError()
                bytes_to_send = bytes([SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE])
                bytes_to_send += comm_from_main["sampling_period"].to_bytes(2, byteorder="little")
                bytes_to_send += create_magnetometer_config_bytes(comm_from_main["magnetometer_config"])
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "metadata_comm":
            bytes_to_send = bytes([SERIAL_COMM_GET_METADATA_COMMAND_BYTE])
        else:
            raise UnrecognizedCommandFromMainToMcCommError(
                f"Invalid communication_type: {communication_type}"
            )

        self._send_data_packet(
            board_idx,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
            bytes_to_send,
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
        seconds_elapsed = _get_secs_since_last_handshake(self._time_of_last_handshake_secs)
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

    def _handle_comm_from_instrument(self) -> None:
        board_idx = 0
        board = self._board_connections[board_idx]
        if board is None:
            return
        if not self._is_registered_with_serial_comm[board_idx]:
            self._register_magic_word(board_idx)
        elif (
            board.in_waiting > 0  # TODO Tanner (5/14/21): consider changing this to min packet size
        ):  # Tanner (4/27/21): If problems occur with reads not being large enough may need to make some min value is present first. 8 bytes for the magic word is probably a good value to start with
            magic_word_bytes = board.read(size=len(SERIAL_COMM_MAGIC_WORD_BYTES))
            if magic_word_bytes != SERIAL_COMM_MAGIC_WORD_BYTES:
                raise SerialCommIncorrectMagicWordFromMantarrayError(str(magic_word_bytes))
        else:
            return
        packet_size_bytes = board.read(size=SERIAL_COMM_PACKET_INFO_LENGTH_BYTES)
        packet_size = int.from_bytes(packet_size_bytes, byteorder="little")
        data_packet_bytes = board.read(size=packet_size)
        # TODO Tanner (3/15/21): eventually make sure the expected number of bytes are read

        # validate checksum before handling the communication. Need to reconstruct the whole packet to get the correct checksum
        full_data_packet = SERIAL_COMM_MAGIC_WORD_BYTES + packet_size_bytes + data_packet_bytes
        is_checksum_valid = validate_checksum(full_data_packet)
        if not is_checksum_valid:
            calculated_checksum = crc32(full_data_packet[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES])
            received_checksum = int.from_bytes(
                full_data_packet[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:],
                byteorder="little",
            )
            raise SerialCommIncorrectChecksumFromInstrumentError(
                f"Checksum Received: {received_checksum}, Checksum Calculated: {calculated_checksum}, Full Data Packet: {str(full_data_packet)}"
            )
        if packet_size < SERIAL_COMM_MIN_PACKET_BODY_SIZE_BYTES:
            raise SerialCommPacketFromMantarrayTooSmallError(
                f"Invalid packet length received: {packet_size}, Full Data Packet: {str(full_data_packet)}"
            )
        module_id = full_data_packet[SERIAL_COMM_MODULE_ID_INDEX]
        if module_id == SERIAL_COMM_MAIN_MODULE_ID:
            self._process_comm_from_instrument(
                module_id,
                full_data_packet[SERIAL_COMM_PACKET_TYPE_INDEX],
                full_data_packet[SERIAL_COMM_ADDITIONAL_BYTES_INDEX:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES],
            )
        else:
            raise UnrecognizedSerialCommModuleIdError(module_id)

    def _process_comm_from_instrument(
        self,
        module_id: int,
        packet_type: int,
        packet_body: bytes,
    ) -> None:
        if packet_type == SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE:
            returned_packet = SERIAL_COMM_MAGIC_WORD_BYTES + packet_body
            raise SerialCommIncorrectChecksumFromPCError(returned_packet)

        board_idx = 0
        if packet_type == SERIAL_COMM_STATUS_BEACON_PACKET_TYPE:
            self._time_of_last_beacon_secs = perf_counter()
            if (
                self._time_of_reboot_start is not None
            ):  # Tanner (4/1/21): want to check that reboot has actually started before considering a status beacon to mean that reboot has completed. It is possible (and has happened in unit tests) where a beacon is received in between sending the reboot command and the instrument actually beginning to reboot
                self._is_waiting_for_reboot = False
                self._time_of_reboot_start = None
                self._board_queues[board_idx][1].put_nowait(
                    {
                        "communication_type": "to_instrument",
                        "command": "reboot",
                        "message": "Instrument completed reboot",
                    }
                )
            status_code = int.from_bytes(
                packet_body[:SERIAL_COMM_STATUS_CODE_LENGTH_BYTES], byteorder="little"
            )
            self._log_status_code(status_code, "Status Beacon")
            if status_code == SERIAL_COMM_FATAL_ERROR_CODE:
                eeprom_contents = packet_body[SERIAL_COMM_STATUS_CODE_LENGTH_BYTES:]
                raise InstrumentFatalError(f"Instrument EEPROM contents: {str(eeprom_contents)}")
            if status_code == SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE:
                raise SerialCommHandshakeTimeoutError()
            if status_code == SERIAL_COMM_SOFT_ERROR_CODE:
                self._send_data_packet(
                    board_idx,
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                    bytes([SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE]),
                )
                self._commands_awaiting_response.append(
                    {
                        "communication_type": "to_instrument",
                        "command": "dump_eeprom",
                        "timepoint": perf_counter(),
                    }
                )
                self._is_instrument_in_error_state = True
            elif status_code == SERIAL_COMM_TIME_SYNC_READY_CODE:
                self._send_data_packet(
                    board_idx,
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                    bytes([SERIAL_COMM_SET_TIME_COMMAND_BYTE])
                    + convert_to_timestamp_bytes(get_serial_comm_timestamp()),
                )
                self._commands_awaiting_response.append(
                    {
                        "communication_type": "to_instrument",
                        "command": "set_time",
                        "timepoint": perf_counter(),
                    }
                )
            elif status_code == SERIAL_COMM_IDLE_READY_CODE and self._auto_get_metadata:
                self._send_data_packet(
                    board_idx,
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                    bytes([SERIAL_COMM_GET_METADATA_COMMAND_BYTE])
                    + convert_to_timestamp_bytes(get_serial_comm_timestamp()),
                )
                self._commands_awaiting_response.append(
                    {
                        "communication_type": "metadata_comm",
                        "command": "get_metadata",
                        "timepoint": perf_counter(),
                    }
                )
                self._auto_get_metadata = False
        elif packet_type == SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE:
            response_data = packet_body[SERIAL_COMM_TIMESTAMP_LENGTH_BYTES:]
            if not self._commands_awaiting_response:
                raise SerialCommUntrackedCommandResponseError(
                    f"Module ID: {module_id}, Packet Type ID: {packet_type}, Packet Body: {str(packet_body)}"
                )
            prev_command = self._commands_awaiting_response.popleft()
            if prev_command["command"] == "handshake":
                status_code = int.from_bytes(response_data, byteorder="little")
                self._log_status_code(status_code, "Handshake Response")
                return
            if prev_command["command"] == "get_metadata":
                prev_command["board_index"] = board_idx
                prev_command["metadata"] = parse_metadata_bytes(response_data)
            elif prev_command["command"] == "reboot":
                prev_command["message"] = "Instrument beginning reboot"
                self._time_of_reboot_start = perf_counter()
            elif prev_command["command"] == "set_time":
                prev_command["message"] = "Instrument time synced with PC"
            elif prev_command["command"] == "dump_eeprom":
                if self._is_instrument_in_error_state:
                    raise InstrumentSoftError(f"Instrument EEPROM contents: {str(response_data)}")
                prev_command["eeprom_contents"] = response_data
            elif prev_command["command"] == "start_managed_acquisition":
                self._is_data_streaming = True
                if response_data[0]:
                    raise InstrumentDataStreamingAlreadyStartedError()
                prev_command["magnetometer_config"] = convert_bytes_to_config_dict(response_data[1:])
                prev_command["timestamp"] = _get_formatted_utc_now()
            elif prev_command["command"] == "stop_managed_acquisition":
                if bool(int.from_bytes(response_data, byteorder="little")):
                    raise InstrumentDataStreamingAlreadyStoppedError()
                self._is_data_streaming = False

            del prev_command[
                "timepoint"
            ]  # main process does not need to know the timepoint and is not expecting this key in the dictionary returned to it
            self._board_queues[board_idx][1].put_nowait(
                prev_command
            )  # Tanner (3/17/21): to be consistent with OkComm, command responses will be sent back to main after the command is acknowledged by the Mantarray
        elif packet_type == SERIAL_COMM_PLATE_EVENT_PACKET_TYPE:
            plate_was_placed = bool(packet_body[0])
            barcode = packet_body[1:].decode("ascii") if plate_was_placed else ""
            barcode_comm = {
                "communication_type": "barcode_comm",
                "board_idx": board_idx,
                "barcode": barcode,
            }
            if plate_was_placed:
                barcode_comm["valid"] = check_barcode_is_valid(barcode)
            self._board_queues[board_idx][1].put_nowait(barcode_comm)
        else:
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
                # if the entire period has passed and no more bytes are available an error has occurred with the Mantarray that is considered fatal
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

    def _handle_data_stream(self) -> None:
        board_idx = 0
        board = self._board_connections[board_idx]
        if board is None:
            raise NotImplementedError("board should never be None here")

        packet_len = SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES + self._num_data_channels_on * 2 + 2
        num_bytes_per_second = packet_len * int(1e6 // self._sampling_period_us)

        self._data_packet_cache += board.read_all()
        if len(self._data_packet_cache) < num_bytes_per_second:
            return

        (
            actual_time_indices,
            actual_data,
            num_data_packets_read,
            other_packet_info,
            unread_bytes,
        ) = handle_data_packets(bytearray(self._data_packet_cache), packet_len)
        self._data_packet_cache = unread_bytes

        # create dict and send to file writer
        fw_item: Dict[Any, Any] = {"time_indices": actual_time_indices[:num_data_packets_read]}
        data_idx = 0
        for module_id, config_dict in self._magnetometer_config.items():
            if not any(config_dict.values()):
                continue
            well_dict = dict()
            for sensor_axis_id, is_channel_on in config_dict.items():
                if not is_channel_on:
                    continue
                well_dict[sensor_axis_id] = actual_data[data_idx][:num_data_packets_read]
                data_idx += 1
            fw_item[module_id - 1] = well_dict
        to_fw_queue = self._board_queues[0][2]
        to_fw_queue.put_nowait(fw_item)
        # check for interrupting packet
        if other_packet_info is not None:
            self._process_comm_from_instrument(
                *other_packet_info[1:],
            )

    def _handle_beacon_tracking(self) -> None:
        if self._time_of_last_beacon_secs is None:
            return
        secs_since_last_beacon_received = _get_secs_since_last_beacon(self._time_of_last_beacon_secs)
        if (
            secs_since_last_beacon_received >= SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
            and not self._is_waiting_for_reboot
        ):
            raise SerialCommStatusBeaconTimeoutError()

    def _handle_command_tracking(self) -> None:
        if not self._commands_awaiting_response:
            return
        oldest_command = self._commands_awaiting_response[0]
        secs_since_command_sent = _get_secs_since_command_sent(oldest_command["timepoint"])
        if secs_since_command_sent >= SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS:
            raise SerialCommCommandResponseTimeoutError(oldest_command["command"])

    def _check_reboot_status(self) -> None:
        if self._time_of_reboot_start is None:
            return
        reboot_dur_secs = _get_secs_since_reboot_start(self._time_of_reboot_start)
        if reboot_dur_secs >= MAX_MC_REBOOT_DURATION_SECONDS:
            raise InstrumentRebootTimeoutError()

    def _log_status_code(self, status_code: int, comm_type: str) -> None:
        log_msg = f"{comm_type} received from instrument. Status Code: {status_code}"
        put_log_message_into_queue(
            logging.INFO,
            log_msg,
            self._board_queues[0][1],
            self.get_logging_level(),
        )

    def _check_simulator_error(self) -> bool:
        board_idx = 0
        simulator_error_queue = self._simulator_error_queues[board_idx]
        if simulator_error_queue is None:  # making mypy happy
            raise NotImplementedError("simulator_error_queue should never be None here")

        simulator_has_error = not simulator_error_queue.empty()
        if simulator_has_error:
            simulator_error_tuple = simulator_error_queue.get(
                timeout=5  # Tanner (4/22/21): setting an arbitrary, very high value here to prevent possible hanging, even though if the queue is not empty it should not hang indefinitely
            )
            self._report_fatal_error(simulator_error_tuple[0])
        return simulator_has_error
