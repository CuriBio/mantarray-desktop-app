# -*- coding: utf-8 -*-
"""Process controlling communication with Mantarray Microcontroller."""
from __future__ import annotations

from collections import deque
import copy
import datetime
import logging
from multiprocessing import Queue
import queue
from statistics import stdev
from time import perf_counter
from time import sleep
from typing import Any
from typing import Deque
from typing import Dict
from typing import FrozenSet
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
from typing import Union
from zlib import crc32

from mantarray_file_manager import DATETIME_STR_FORMAT
from nptyping import NDArray
import numpy as np
import serial
import serial.tools.list_ports as list_ports
from stdlib_utils import put_log_message_into_queue

from .constants import DEFAULT_MAGNETOMETER_CONFIG
from .constants import DEFAULT_SAMPLING_PERIOD
from .constants import GENERIC_24_WELL_DEFINITION
from .constants import INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
from .constants import MAX_CHANNEL_FIRMWARE_UPDATE_DURATION_SECONDS
from .constants import MAX_MAIN_FIRMWARE_UPDATE_DURATION_SECONDS
from .constants import MAX_MC_REBOOT_DURATION_SECONDS
from .constants import NUM_INITIAL_PACKETS_TO_DROP
from .constants import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from .constants import SERIAL_COMM_BAUD_RATE
from .constants import SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
from .constants import SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE
from .constants import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from .constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from .constants import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from .constants import SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE
from .constants import SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE
from .constants import SERIAL_COMM_FATAL_ERROR_CODE
from .constants import SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
from .constants import SERIAL_COMM_GET_METADATA_COMMAND_BYTE
from .constants import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from .constants import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from .constants import SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE
from .constants import SERIAL_COMM_IDLE_READY_CODE
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE
from .constants import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from .constants import SERIAL_COMM_MAIN_MODULE_ID
from .constants import SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES
from .constants import SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
from .constants import SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE
from .constants import SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES
from .constants import SERIAL_COMM_MIN_PACKET_BODY_SIZE_BYTES
from .constants import SERIAL_COMM_MODULE_ID_INDEX
from .constants import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from .constants import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from .constants import SERIAL_COMM_NUM_DATA_CHANNELS
from .constants import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from .constants import SERIAL_COMM_PACKET_TYPE_INDEX
from .constants import SERIAL_COMM_PLATE_EVENT_PACKET_TYPE
from .constants import SERIAL_COMM_REBOOT_COMMAND_BYTE
from .constants import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from .constants import SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
from .constants import SERIAL_COMM_SET_TIME_COMMAND_BYTE
from .constants import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from .constants import SERIAL_COMM_SOFT_ERROR_CODE
from .constants import SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_START_STIM_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .constants import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from .constants import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from .constants import SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_STOP_STIM_PACKET_TYPE
from .constants import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from .constants import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from .constants import SERIAL_COMM_TIME_SYNC_READY_CODE
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .constants import STIM_COMPLETE_SUBPROTOCOL_IDX
from .constants import STM_VID
from .exceptions import FirmwareUpdateCommandFailedError
from .exceptions import FirmwareUpdateTimeoutError
from .exceptions import InstrumentDataStreamingAlreadyStartedError
from .exceptions import InstrumentDataStreamingAlreadyStoppedError
from .exceptions import InstrumentFatalError
from .exceptions import InstrumentRebootTimeoutError
from .exceptions import InstrumentSoftError
from .exceptions import InvalidCommandFromMainError
from .exceptions import MagnetometerConfigUpdateWhileDataStreamingError
from .exceptions import MantarrayInstrumentError
from .exceptions import SerialCommCommandResponseTimeoutError
from .exceptions import SerialCommHandshakeTimeoutError
from .exceptions import SerialCommIncorrectChecksumFromInstrumentError
from .exceptions import SerialCommIncorrectChecksumFromPCError
from .exceptions import SerialCommIncorrectMagicWordFromMantarrayError
from .exceptions import SerialCommNotEnoughAdditionalBytesReadError
from .exceptions import SerialCommPacketFromMantarrayTooSmallError
from .exceptions import SerialCommPacketRegistrationReadEmptyError
from .exceptions import SerialCommPacketRegistrationSearchExhaustedError
from .exceptions import SerialCommPacketRegistrationTimeoutError
from .exceptions import SerialCommStatusBeaconTimeoutError
from .exceptions import SerialCommUntrackedCommandResponseError
from .exceptions import StimulationProtocolUpdateFailedError
from .exceptions import StimulationProtocolUpdateWhileStimulatingError
from .exceptions import StimulationStatusUpdateFailedError
from .exceptions import UnrecognizedCommandFromMainToMcCommError
from .exceptions import UnrecognizedSerialCommModuleIdError
from .exceptions import UnrecognizedSerialCommPacketTypeError
from .firmware_downloader import download_firmware_updates
from .firmware_downloader import get_latest_firmware_versions
from .instrument_comm import InstrumentCommProcess
from .mc_simulator import MantarrayMcSimulator
from .serial_comm_utils import convert_bytes_to_config_dict
from .serial_comm_utils import convert_stim_dict_to_bytes
from .serial_comm_utils import convert_to_metadata_bytes
from .serial_comm_utils import convert_to_timestamp_bytes
from .serial_comm_utils import create_data_packet
from .serial_comm_utils import create_magnetometer_config_bytes
from .serial_comm_utils import get_serial_comm_timestamp
from .serial_comm_utils import parse_metadata_bytes
from .serial_comm_utils import validate_checksum
from .utils import check_barcode_is_valid
from .utils import create_active_channel_per_sensor_list
from .utils import set_this_process_high_priority
from .utils import sort_nested_dict
from .worker_thread import ErrorCatchingThread


if 6 < 9:  # pragma: no cover # protect this from zimports deleting the pylint disable statement
    from .data_parsing_cy import (  # pylint: disable=import-error # Tanner (5/12/21): unsure why pylint is unable to recognize cython import
        handle_data_packets,
    )


def _get_formatted_utc_now() -> str:
    return datetime.datetime.utcnow().strftime(DATETIME_STR_FORMAT)


def _get_secs_since_read_start(start: float) -> float:
    return perf_counter() - start


def _get_secs_since_last_handshake(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_last_beacon(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_command_sent(command_timepoint: float) -> float:
    return perf_counter() - command_timepoint


def _get_secs_since_reboot_start(reboot_start_time: float) -> float:
    return perf_counter() - reboot_start_time


def _get_firmware_update_dur_secs(command_time: float) -> float:
    return perf_counter() - command_time


def _get_secs_since_last_data_parse(last_parse_time: float) -> float:
    return perf_counter() - last_parse_time


def _get_dur_of_data_read_secs(start: float) -> float:
    return perf_counter() - start


def _get_dur_of_data_parse_secs(start: float) -> float:
    return perf_counter() - start


# pylint: disable=too-many-instance-attributes
class McCommunicationProcess(InstrumentCommProcess):
    """Process that controls communication with the Mantarray Beta 2 Board(s).

    Args:
        board_queues: A tuple (the max number of MC board connections should be predefined, so not a mutable list) of tuples of 3 queues. The first queue is for input/communication from the main thread to this sub process, second queue is for communication from this process back to the main thread. Third queue is for streaming communication (largely of raw data) to the process that controls writing to disk.
        fatal_error_reporter: A queue that reports back any unhandled errors that have caused the process to stop.
        suppress_setup_communication_to_main: if set to true (often during unit tests), messages during the _setup_before_loop will not be put into the queue to communicate back to the main process
    """

    def __init__(self, *args: Any, hardware_test_mode: bool = False, **kwargs: Any):
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
        self._auto_set_magnetometer_config = False
        self._time_of_last_handshake_secs: Optional[float] = None
        self._time_of_last_beacon_secs: Optional[float] = None
        self._commands_awaiting_response: Deque[  # pylint: disable=unsubscriptable-object
            Dict[str, Any]
        ] = deque()
        self._is_waiting_for_reboot = False  # Tanner (4/1/21): This flag indicates that a reboot command has been sent and a status beacon following reboot completion has not been received. It does not imply that the instrument has begun rebooting.
        self._time_of_reboot_start: Optional[
            float
        ] = None  # Tanner (4/1/21): This value will be None until this process receives a response to a reboot command. It will be set back to None after receiving a status beacon upon reboot completion
        self._hardware_test_mode = hardware_test_mode
        # firmware updating values
        self._fw_update_worker_thread: Optional[ErrorCatchingThread] = None
        self._fw_update_thread_dict: Optional[Dict[str, Any]] = None
        self._is_updating_firmware = False
        self._firmware_update_type = ""
        self._firmware_file_contents: Optional[bytes] = None
        self._firmware_packet_idx: Optional[int] = None
        self._firmware_checksum: Optional[int] = None
        self._time_of_firmware_update_start: Optional[
            float
        ] = None  # Tanner (11/17/21): This value will only be a float when from the moment the end of firmware packet is received to the moment the firmware update complete packet is received
        # data streaming values
        self._base_global_time_of_data_stream = 0
        self._magnetometer_config: Dict[int, Dict[Any, Any]] = dict()
        self._active_sensors_list: List[int] = list()
        self._packet_len = 0
        self._sampling_period_us = 0
        self._is_data_streaming = False
        self._is_stopping_data_stream = False
        self._has_data_packet_been_sent = False
        self._data_packet_cache = bytes(0)
        # stimulation values
        self._wells_assigned_a_protocol: FrozenSet[int] = frozenset()
        self._wells_actively_stimulating: Set[int] = set()
        self._stim_status_buffers: Dict[int, Any]
        self._reset_stim_status_buffers()
        self._has_stim_packet_been_sent = False
        # performance tracking values
        self._performance_logging_cycles = INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
        self._parses_since_last_logging: List[int] = [0] * len(self._board_queues)
        self._durations_between_parsing: List[float] = list()
        self._timepoint_of_prev_data_parse_secs: Optional[float] = None
        self._data_read_durations: List[float] = list()
        self._data_read_lengths: List[int] = list()
        self._data_parsing_durations: List[float] = list()
        self._data_parsing_num_packets_produced: List[int] = list()

    @property
    def _is_stimulating(self) -> bool:
        return len(self._wells_actively_stimulating) > 0

    @_is_stimulating.setter
    def _is_stimulating(self, value: bool) -> None:
        if value:
            self._wells_actively_stimulating = set(well for well in self._wells_assigned_a_protocol)
        else:
            self._wells_actively_stimulating = set()

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
        if isinstance(board, MantarrayMcSimulator):
            # Tanner (3/16/21): Current assumption is that a live mantarray will be running by the time we connect to it, so starting simulator here and waiting for it to complete start up
            board.start()
            while not board.is_start_up_complete():
                # sleep so as to not relentlessly ping the simulator
                sleep(0.1)
        else:
            # if connected to a real board, then make sure this process has a high priority
            set_this_process_high_priority()
        self._auto_set_magnetometer_config = True
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
            if (
                self._error is not None
                and not isinstance(self._error, MantarrayInstrumentError)
                and not self._hardware_test_mode  # TODO Tanner (6/11/21): remove this last condition once real instrument implements dump EEPROM command
            ):
                # if error occurred in software, send dump EEPROM command and wait for instrument to respond to command before flushing serial data. If the firmware caught an error in itself the EEPROM contents should already be logged and this command can be skipped here
                self._send_data_packet(
                    board_idx,
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                    bytes([SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE]),
                )
                sleep(1)
            # flush and log remaining serial data
            remaining_serial_data = board.read_all()
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

    def _reset_stim_status_buffers(self) -> None:
        self._stim_status_buffers = {well_idx: [[], []] for well_idx in range(self._num_wells)}

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

            for port_info in list_ports.comports():
                # Tanner (6/14/21): attempt to connect to any device with the STM vendor ID
                if port_info.vid != STM_VID:
                    continue
                msg["message"] = f"Board detected with description: {port_info.description}"
                serial_obj = serial.Serial(
                    port=port_info.name,
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
        data_packet = create_data_packet(
            get_serial_comm_timestamp(),
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
        # Tanner (6/2/21): Need to make sure module ID keys are in order
        self._magnetometer_config = sort_nested_dict(copy.deepcopy(magnetometer_config))
        self._sampling_period_us = sampling_period
        self._active_sensors_list = create_active_channel_per_sensor_list(self._magnetometer_config)
        for module_dict in self._magnetometer_config.values():
            config_values = list(module_dict.values())
            num_sensors_active = 0
            for sensor_base_idx in range(
                0, SERIAL_COMM_NUM_DATA_CHANNELS, SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
            ):
                is_sensor_active = any(
                    config_values[sensor_base_idx : sensor_base_idx + SERIAL_COMM_NUM_CHANNELS_PER_SENSOR]
                )
                num_sensors_active += int(is_sensor_active)
            module_dict["num_sensors_active"] = num_sensors_active
        total_active_channels = sum(self._active_sensors_list)
        total_active_sensors = len(self._active_sensors_list)
        self._packet_len = (
            SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES
            + total_active_channels * 2
            + total_active_sensors * SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
            + SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
        )

    def _commands_for_each_run_iteration(self) -> None:
        """Ordered actions to perform each iteration.

        This process must be responsive to communication from the main process and then the instrument before anything else.

        After reboot command is sent, no more commands should be sent until reboot completes.
        During instrument reboot, should only check for incoming data make sure no commands are awaiting a response.

        1. Before doing anything, simulator errors must be checked for. If they go unchecked before performing comm with the simulator, and error may be raised in this process that masks the simulator's error which is actually the root of the problem.
        2. Process next communication from main. This process's next highest priority is to be responsive to the main process and should check for messages from main first. These messages will let this process know when to send commands to the instrument. Ignore messages from main if conducting a firmware update
        3. Send handshake to instrument when necessary. Third highest priority is to let the instrument know that this process and the rest of the software are alive and responsive.
        4. Process packets coming from the instrument. This is the highest priority task after sending data to it.
        5. Make sure the beacon is not overdue, unless instrument is rebooting. If the beacon is overdue, it's reasonable to assume something caused the instrument to stop working. This task should happen after handling of sending/receiving data from the instrument and main process.
        6. Make sure commands are not overdue. This task should happen after the instrument has been determined to be working properly.
        7. If rebooting or waiting for firmware update to complete, make sure that the reboot has not taken longer than the max allowed reboot time.
        8. Check on the status of any worker threads.
        """
        if self._in_simulation_mode:
            if self._check_simulator_error():
                self.stop()
                return

        if not self._is_updating_firmware and not self._is_waiting_for_reboot:
            self._process_next_communication_from_main()
            self._handle_sending_handshake()

        if self._is_data_streaming or self._is_stimulating:
            self._handle_streams()
        else:
            self._handle_comm_from_instrument()

        self._handle_beacon_tracking()
        self._handle_command_tracking()

        if self._is_waiting_for_reboot:
            self._check_reboot_status()
        elif self._is_updating_firmware:
            self._check_firmware_update_status()

        self._check_worker_thread()

        # process can be soft stopped if no commands in queue from main and no command responses needed from instrument
        self._process_can_be_soft_stopped = (  # TODO prevent soft stop if rebooting, updating firmware, or there is an active worker thread
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
        send_packet_to_instrument = True
        bytes_to_send = bytes(0)
        packet_type = SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE

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
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "acquisition_manager":
            if comm_from_main["command"] == "start_managed_acquisition":
                bytes_to_send = bytes([SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE])
            elif comm_from_main["command"] == "stop_managed_acquisition":
                self._is_stopping_data_stream = True
                bytes_to_send = bytes([SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE])
            elif comm_from_main["command"] == "change_magnetometer_config":
                if self._is_data_streaming:
                    raise MagnetometerConfigUpdateWhileDataStreamingError()
                bytes_to_send = bytes([SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE])
                bytes_to_send += comm_from_main["sampling_period"].to_bytes(2, byteorder="little")
                bytes_to_send += create_magnetometer_config_bytes(comm_from_main["magnetometer_config"])
                self._set_magnetometer_config(
                    comm_from_main["magnetometer_config"], comm_from_main["sampling_period"]
                )
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "stimulation":
            if comm_from_main["command"] == "set_protocols":
                packet_type = SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
                bytes_to_send = convert_stim_dict_to_bytes(comm_from_main["stim_info"])
                if self._is_stimulating and not self._hardware_test_mode:
                    raise StimulationProtocolUpdateWhileStimulatingError()
                protocol_assignments = comm_from_main["stim_info"]["protocol_assignments"]
                self._wells_assigned_a_protocol = frozenset(
                    GENERIC_24_WELL_DEFINITION.get_well_index_from_well_name(well_name)
                    for well_name, protocol_id in protocol_assignments.items()
                    if protocol_id is not None
                )
            elif comm_from_main["command"] == "start_stimulation":
                packet_type = SERIAL_COMM_START_STIM_PACKET_TYPE
            elif comm_from_main["command"] == "stop_stimulation":
                packet_type = SERIAL_COMM_STOP_STIM_PACKET_TYPE
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "metadata_comm":
            bytes_to_send = bytes([SERIAL_COMM_GET_METADATA_COMMAND_BYTE])
        elif communication_type == "firmware_update":
            if comm_from_main["command"] == "get_latest_firmware_versions":
                send_packet_to_instrument = False
                # set up worker thread
                self._fw_update_thread_dict = {
                    "communication_type": "firmware_update",
                    "command": "get_latest_firmware_versions",
                    "latest_firmware_versions": {},
                }
                self._fw_update_worker_thread = ErrorCatchingThread(
                    target=get_latest_firmware_versions,
                    args=(
                        self._fw_update_thread_dict,
                        comm_from_main["latest_software_version"],
                        comm_from_main["main_firmware_version"],
                    ),
                )
                self._fw_update_worker_thread.start()
            elif comm_from_main["command"] == "download_firmware_updates":
                if not comm_from_main["main"] and not comm_from_main["channel"]:
                    raise InvalidCommandFromMainError(
                        "Cannot download firmware files if neither firmware type needs an update"
                    )
                send_packet_to_instrument = False
                # set up worker thread
                self._fw_update_thread_dict = {
                    "communication_type": "firmware_update",
                    "command": "download_firmware_updates",
                    "main": None,
                    "channel": None,
                }
                self._fw_update_worker_thread = ErrorCatchingThread(
                    target=download_firmware_updates,
                    args=(
                        self._fw_update_thread_dict,
                        comm_from_main["main"],
                        comm_from_main["channel"],
                        comm_from_main["username"],
                        comm_from_main["password"],
                    ),
                )
                self._fw_update_worker_thread.start()
            elif comm_from_main["command"] == "start_firmware_update":
                packet_type = SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
                self._firmware_update_type = comm_from_main["firmware_type"]
                bytes_to_send = bytes([self._firmware_update_type == "channel"])
                # TODO update this
                with open(comm_from_main["file_path"], "rb") as firmware_file:
                    self._firmware_file_contents = firmware_file.read()
                bytes_to_send += len(self._firmware_file_contents).to_bytes(4, byteorder="little")
                self._firmware_packet_idx = 0
                self._is_updating_firmware = True
                self._firmware_checksum = crc32(self._firmware_file_contents)
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        else:
            raise UnrecognizedCommandFromMainToMcCommError(
                f"Invalid communication_type: {communication_type}"
            )

        if send_packet_to_instrument:
            self._send_data_packet(
                board_idx,
                SERIAL_COMM_MAIN_MODULE_ID,
                packet_type,
                bytes_to_send,
            )
            self._add_command_to_track(comm_from_main)

    def _add_command_to_track(self, command_dict: Dict[str, Any]) -> None:
        command_dict["timepoint"] = perf_counter()
        self._commands_awaiting_response.append(command_dict)

    def _handle_firmware_update(self) -> None:
        board_idx = 0
        # making mypy happy
        if self._firmware_checksum is None:
            raise NotImplementedError("_firmware_checksum should never be None here")
        if self._firmware_packet_idx is None:
            raise NotImplementedError("_firmware_packet_idx should never be None here")
        if self._firmware_file_contents is None:
            raise NotImplementedError("_firmware_file_contents should never be None here")

        command_dict: Dict[str, Any]
        if len(self._firmware_file_contents) == 0:
            packet_type = SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE
            bytes_to_send = self._firmware_checksum.to_bytes(4, byteorder="little")
            command_dict = {
                "communication_type": "firmware_update",
                "command": "end_of_firmware_update",
            }
            self._firmware_file_contents = None
            self._firmware_checksum = None
        else:
            if self._firmware_file_contents is None:  # making mypy happy
                raise NotImplementedError("_firmware_file_contents should never be None here")
            packet_type = SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
            bytes_to_send = (
                bytes([self._firmware_packet_idx])
                + self._firmware_file_contents[: SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES - 1]
            )
            command_dict = {
                "communication_type": "firmware_update",
                "command": "send_firmware_data",
                "packet_index": self._firmware_packet_idx,
            }
            self._firmware_file_contents = self._firmware_file_contents[
                SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES - 1 :
            ]
        self._send_data_packet(board_idx, SERIAL_COMM_MAIN_MODULE_ID, packet_type, bytes_to_send)
        self._add_command_to_track(command_dict)

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
        self._add_command_to_track({"command": "handshake"})

    def _handle_comm_from_instrument(self) -> None:
        board_idx = 0
        board = self._board_connections[board_idx]
        if board is None:
            return
        if not self._is_registered_with_serial_comm[board_idx]:
            self._register_magic_word(board_idx)
        elif board.in_waiting >= SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES:
            magic_word_bytes = board.read(size=len(SERIAL_COMM_MAGIC_WORD_BYTES))
            if magic_word_bytes != SERIAL_COMM_MAGIC_WORD_BYTES:
                raise SerialCommIncorrectMagicWordFromMantarrayError(str(magic_word_bytes))
        else:
            return
        packet_size_bytes = board.read(size=SERIAL_COMM_PACKET_INFO_LENGTH_BYTES)
        packet_size = int.from_bytes(packet_size_bytes, byteorder="little")
        data_packet_bytes = board.read(size=packet_size)
        # check that the expected number of bytes are read. Read function will never return more bytes than requested, but can return less bytes than requested if not enough are present before the read timeout
        if len(data_packet_bytes) < packet_size:
            # Tanner (10/22/21): if problems with not enough bytes being read persist, then try reading one more time before raising error
            raise SerialCommNotEnoughAdditionalBytesReadError(
                f"Expected Size: {packet_size}, Actual Size: {len(data_packet_bytes)}, {data_packet_bytes}"  # type: ignore
            )
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
        # pylint: disable=too-many-branches, too-many-statements
        if packet_type == SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE:
            returned_packet = SERIAL_COMM_MAGIC_WORD_BYTES + packet_body
            raise SerialCommIncorrectChecksumFromPCError(returned_packet)

        board_idx = 0
        if packet_type == SERIAL_COMM_STATUS_BEACON_PACKET_TYPE:
            self._process_status_beacon(packet_body)
        elif packet_type == SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE:
            raise NotImplementedError(
                "Should never receive magnetometer data packets when not streaming data"
            )
        elif packet_type in (
            SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
            SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
            SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
            SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE,
        ):
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
                self._has_stim_packet_been_sent = False
                self._has_data_packet_been_sent = False
                if response_data[0]:
                    if not self._hardware_test_mode:
                        raise InstrumentDataStreamingAlreadyStartedError()
                    prev_command["hardware_test_message"] = "Data stream already started"  # pragma: no cover
                else:
                    self._base_global_time_of_data_stream = int.from_bytes(
                        response_data[1:9], byteorder="little"
                    )
                    prev_command["sampling_period"] = int.from_bytes(response_data[9:11], byteorder="little")
                    prev_command["magnetometer_config"] = convert_bytes_to_config_dict(response_data[11:])
                prev_command["timestamp"] = datetime.datetime.utcnow()
                # Tanner (6/11/21): This helps prevent against status beacon timeouts with beacons that come just after the data stream begins but before 1 second of data is available
                self._time_of_last_beacon_secs = perf_counter()
                # send any buffered stim statuses
                well_statuses: Dict[int, Any] = {}
                for well_idx in range(self._num_wells):
                    stim_statuses = self._stim_status_buffers[well_idx]
                    if len(stim_statuses[0]) == 0 or stim_statuses[1][-1] == STIM_COMPLETE_SUBPROTOCOL_IDX:
                        continue
                    well_statuses[well_idx] = np.array(
                        [stim_statuses[0][-1:], stim_statuses[1][-1:]], dtype=np.int64
                    )
                    well_statuses[well_idx][0] -= self._base_global_time_of_data_stream

                if well_statuses:
                    self._dump_stim_packet(well_statuses)
            elif prev_command["command"] == "stop_managed_acquisition":
                if response_data[0]:
                    if not self._hardware_test_mode:
                        raise InstrumentDataStreamingAlreadyStoppedError()
                    prev_command["hardware_test_message"] = "Data stream already stopped"  # pragma: no cover
                self._is_stopping_data_stream = False
                self._is_data_streaming = False
            elif prev_command["command"] == "set_protocols":
                if response_data[0]:
                    if not self._hardware_test_mode:
                        raise StimulationProtocolUpdateFailedError()
                    prev_command["hardware_test_message"] = "Command failed"  # pragma: no cover
            elif prev_command["command"] == "start_stimulation":
                # Tanner (10/25/21): if needed, can save _base_global_time_of_data_stream here
                if response_data[0]:
                    if not self._hardware_test_mode:
                        raise StimulationStatusUpdateFailedError("start_stimulation")
                    prev_command["hardware_test_message"] = "Command failed"  # pragma: no cover
                prev_command["timestamp"] = datetime.datetime.utcnow()
                self._is_stimulating = True
            elif prev_command["command"] == "stop_stimulation":
                if response_data[0]:
                    if not self._hardware_test_mode:
                        raise StimulationStatusUpdateFailedError("stop_stimulation")
                    prev_command["hardware_test_message"] = "Command failed"  # pragma: no cover
                self._is_stimulating = False
                self._reset_stim_status_buffers()
            elif prev_command["command"] in (
                "start_firmware_update",
                "send_firmware_data",
                "end_of_firmware_update",
            ):
                if response_data[0]:
                    error_msg = prev_command["command"]
                    if error_msg == "send_firmware_data":
                        error_msg += f", packet index: {self._firmware_packet_idx}"
                    raise FirmwareUpdateCommandFailedError(error_msg)
                if prev_command["command"] == "end_of_firmware_update":
                    # Tanner (11/16/21): reset here instead of with the other firmware update values so that the error message above can include the packet index
                    self._firmware_packet_idx = None
                    self._time_of_firmware_update_start = perf_counter()
                else:
                    if prev_command["command"] == "send_firmware_data":
                        if self._firmware_packet_idx is None:  # making mypy happy
                            raise NotImplementedError("_firmware_file_contents should never be None here")
                        self._firmware_packet_idx += 1
                    self._handle_firmware_update()

            # main process does not need to know the timepoint and is not expecting this key in the dictionary returned to it
            del prev_command["timepoint"]
            # Tanner (3/17/21): to be consistent with OkComm, command responses will be sent back to main after the command is acknowledged by the Mantarray
            self._board_queues[board_idx][1].put_nowait(prev_command)
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
        elif packet_type == SERIAL_COMM_STIM_STATUS_PACKET_TYPE:
            raise NotImplementedError("Should never receive stim status packets when not stimulating")
        elif packet_type in (
            SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE,
            SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE,
        ):
            self._board_queues[board_idx][1].put_nowait(
                {
                    "communication_type": "firmware_update",
                    "command": "update_completed",
                    "firmware_type": self._firmware_update_type,
                }
            )
            self._firmware_update_type = ""
            self._is_updating_firmware = False
            self._time_of_firmware_update_start = None
            self._time_of_last_beacon_secs = perf_counter()
        else:
            raise UnrecognizedSerialCommPacketTypeError(
                f"Packet Type ID: {packet_type} is not defined for Module ID: {module_id}"
            )

    def _process_status_beacon(self, packet_body: bytes) -> None:
        board_idx = 0
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
        status_code = int.from_bytes(packet_body[:SERIAL_COMM_STATUS_CODE_LENGTH_BYTES], byteorder="little")
        self._log_status_code(status_code, "Status Beacon")
        if status_code == SERIAL_COMM_FATAL_ERROR_CODE:
            error_msg = ""
            if (
                not self._hardware_test_mode
            ):  # pragma: no cover  # TODO Tanner (6/11/21): remove this condition once real instrument implements dump EEPROM command
                eeprom_contents = packet_body[SERIAL_COMM_STATUS_CODE_LENGTH_BYTES:]
                error_msg = f"Instrument EEPROM contents: {str(eeprom_contents)}"
            raise InstrumentFatalError(error_msg)
        if status_code == SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE:
            raise SerialCommHandshakeTimeoutError()
        if status_code == SERIAL_COMM_SOFT_ERROR_CODE:
            if not self._hardware_test_mode:
                self._send_data_packet(
                    board_idx,
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                    bytes([SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE]),
                )
                self._add_command_to_track(
                    {
                        "communication_type": "to_instrument",
                        "command": "dump_eeprom",
                    }
                )
                self._is_instrument_in_error_state = True
            else:  # pragma: no cover
                raise InstrumentSoftError()
        elif status_code == SERIAL_COMM_TIME_SYNC_READY_CODE:
            self._send_data_packet(
                board_idx,
                SERIAL_COMM_MAIN_MODULE_ID,
                SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                bytes([SERIAL_COMM_SET_TIME_COMMAND_BYTE])
                + convert_to_timestamp_bytes(get_serial_comm_timestamp()),
            )
            self._add_command_to_track(
                {
                    "communication_type": "to_instrument",
                    "command": "set_time",
                }
            )
        elif status_code == SERIAL_COMM_IDLE_READY_CODE:
            # Tanner (8/5/21): not explicitly unit tested, but magnetometer config should be sent before automatic metadata collection
            if self._auto_set_magnetometer_config:
                initial_config_copy = copy.deepcopy(DEFAULT_MAGNETOMETER_CONFIG)
                self._set_magnetometer_config(initial_config_copy, DEFAULT_SAMPLING_PERIOD)
                bytes_to_send = bytes([SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE])
                bytes_to_send += DEFAULT_SAMPLING_PERIOD.to_bytes(2, byteorder="little")
                bytes_to_send += create_magnetometer_config_bytes(initial_config_copy)
                self._send_data_packet(
                    board_idx,
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                    bytes_to_send,
                )

                self._add_command_to_track(
                    {
                        "communication_type": "default_magnetometer_config",
                        "command": "change_magnetometer_config",
                        "magnetometer_config_dict": {
                            "magnetometer_config": initial_config_copy,
                            "sampling_period": DEFAULT_SAMPLING_PERIOD,
                        },
                    }
                )
                self._auto_set_magnetometer_config = False
            if self._auto_get_metadata:
                if (
                    not self._in_simulation_mode
                ):  # pragma: no cover  # TODO Tanner (6/11/21): remove this once get_metadata command is implemented on real board
                    self._board_queues[0][1].put_nowait(
                        {
                            "communication_type": "metadata_comm",
                            "board_index": 0,
                            "metadata": MantarrayMcSimulator.default_metadata_values,
                        }
                    )
                else:
                    self._send_data_packet(
                        board_idx,
                        SERIAL_COMM_MAIN_MODULE_ID,
                        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
                        bytes([SERIAL_COMM_GET_METADATA_COMMAND_BYTE])
                        + convert_to_timestamp_bytes(get_serial_comm_timestamp()),
                    )
                    self._add_command_to_track(
                        {
                            "communication_type": "metadata_comm",
                            "command": "get_metadata",
                        }
                    )
                self._auto_get_metadata = False

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
                raise SerialCommPacketRegistrationTimeoutError(magic_word_test_bytes)
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
            read_dur_secs = _get_secs_since_read_start(start)
        # if this point is reached and the magic word has not been found, then at some point no additional bytes were being read
        if magic_word_test_bytes != SERIAL_COMM_MAGIC_WORD_BYTES:
            raise SerialCommPacketRegistrationReadEmptyError()
        self._is_registered_with_serial_comm[board_idx] = True

    def _handle_streams(self) -> None:
        board_idx = 0
        board = self._board_connections[board_idx]
        if board is None:
            raise NotImplementedError("board should never be None here")

        data_read_start = perf_counter()
        data_read_bytes = board.read_all()
        self._data_read_durations.append(_get_dur_of_data_read_secs(data_read_start))
        self._data_read_lengths.append(len(data_read_bytes))

        self._data_packet_cache += data_read_bytes
        # If stopping data stream, make sure at least 1 byte is available.
        # Otherwise, wait for at least 1 second of data

        return_cond = len(self._data_packet_cache) == 0
        # if streaming data and not stopping yet, need to make sure at least one second of data is present
        if self._is_data_streaming and not self._is_stopping_data_stream:
            num_bytes_per_second = self._packet_len * int(1e6 // self._sampling_period_us)
            return_cond |= len(self._data_packet_cache) < num_bytes_per_second
        if return_cond:
            return

        # TODO Tanner (10/22/21): add stim packet parsing to metrics once real stream is implemented
        # update performance tracking values
        self._parses_since_last_logging[board_idx] += 1
        if self._timepoint_of_prev_data_parse_secs is None:
            self._timepoint_of_prev_data_parse_secs = perf_counter()
        else:
            self._durations_between_parsing.append(
                _get_secs_since_last_data_parse(self._timepoint_of_prev_data_parse_secs)
            )

        data_parsing_start = perf_counter()
        parsed_packet_dict = handle_data_packets(
            bytearray(self._data_packet_cache),
            self._active_sensors_list,
            self._base_global_time_of_data_stream,
        )
        self._data_parsing_durations.append(_get_dur_of_data_parse_secs(data_parsing_start))
        self._data_parsing_num_packets_produced.append(
            parsed_packet_dict["magnetometer_data"]["num_data_packets"]
        )

        self._data_packet_cache = parsed_packet_dict["unread_bytes"]

        # process any other packets
        for other_packet_info in parsed_packet_dict["other_packet_info"]:
            self._process_comm_from_instrument(*other_packet_info[1:])
        # create dict and send to file writer if any packets were read
        self._dump_data_packets(parsed_packet_dict["magnetometer_data"])
        self._handle_stim_packets(parsed_packet_dict["stim_data"])

        # handle performance logging if ready
        if self._parses_since_last_logging[board_idx] >= self._performance_logging_cycles:
            self._handle_performance_logging()
            self._parses_since_last_logging[board_idx] = 0

    def _dump_data_packets(self, parsed_packet_dict: Dict[str, Any]) -> None:
        # Tanner (10/15/21): if performance needs to be improved, consider converting some of this function to cython
        (
            time_indices,
            time_offsets,
            data,
            num_data_packets_read,
        ) = parsed_packet_dict.values()
        # Tanner (5/25/21): it is possible 0 data packets are read when stopping data stream
        if num_data_packets_read == 0:
            return

        is_first_packet = not self._has_data_packet_been_sent
        data_start_idx = NUM_INITIAL_PACKETS_TO_DROP if is_first_packet else 0
        data_slice = slice(data_start_idx, num_data_packets_read)

        fw_item: Dict[Any, Any] = {
            "data_type": "magnetometer",
            "time_indices": time_indices[data_slice],
            "is_first_packet_of_stream": is_first_packet,
        }
        data_idx = 0
        time_offset_idx = 0
        for module_id, config_dict in self._magnetometer_config.items():
            num_sensors_active = config_dict["num_sensors_active"]
            if num_sensors_active == 0:
                continue
            time_offset_slice = slice(time_offset_idx, time_offset_idx + num_sensors_active)
            well_dict = {"time_offsets": time_offsets[time_offset_slice, data_slice]}
            time_offset_idx += num_sensors_active
            for config_key, config_value in config_dict.items():
                if not config_value or config_key == "num_sensors_active":
                    continue
                well_dict[config_key] = data[data_idx][data_slice]
                data_idx += 1
            well_idx = SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id]
            fw_item[well_idx] = well_dict
        to_fw_queue = self._board_queues[0][2]
        to_fw_queue.put_nowait(fw_item)
        self._has_data_packet_been_sent = True

    def _handle_stim_packets(self, well_statuses: Dict[int, Any]) -> None:
        for well_idx in range(self._num_wells):
            stim_statuses = well_statuses.get(well_idx, [[], []])
            for i in range(2):
                self._stim_status_buffers[well_idx][i] = self._stim_status_buffers[well_idx][i][-1:]
                self._stim_status_buffers[well_idx][i].extend(stim_statuses[i])
        if not well_statuses:
            return
        wells_done_stimulating = [
            well_idx
            for well_idx, status_updates_arr in well_statuses.items()
            if status_updates_arr[1][-1] == STIM_COMPLETE_SUBPROTOCOL_IDX
        ]
        if wells_done_stimulating:
            self._wells_actively_stimulating -= set(wells_done_stimulating)
            to_main_queue = self._board_queues[0][1]
            to_main_queue.put_nowait(
                {
                    "communication_type": "stimulation",
                    "command": "status_update",
                    "wells_done_stimulating": wells_done_stimulating,
                }
            )

        if self._is_data_streaming and not self._is_stopping_data_stream:
            for stim_status_updates in well_statuses.values():
                stim_status_updates[0] -= self._base_global_time_of_data_stream
            self._dump_stim_packet(well_statuses)

    def _dump_stim_packet(self, well_statuses: NDArray[(2, Any), int]) -> None:
        to_fw_queue = self._board_queues[0][2]
        to_fw_queue.put_nowait(
            {
                "data_type": "stimulation",
                "well_statuses": well_statuses,
                "is_first_packet_of_stream": not self._has_stim_packet_been_sent,
            }
        )
        self._has_stim_packet_been_sent = True

    def _handle_beacon_tracking(self) -> None:
        if self._time_of_last_beacon_secs is None:
            return
        secs_since_last_beacon_received = _get_secs_since_last_beacon(self._time_of_last_beacon_secs)
        if (
            secs_since_last_beacon_received >= SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
            and not self._is_waiting_for_reboot
            and not self._is_updating_firmware
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

    def _check_firmware_update_status(self) -> None:
        if self._time_of_firmware_update_start is None:
            return
        update_dur_secs = _get_firmware_update_dur_secs(self._time_of_firmware_update_start)
        timeout_dur = (
            MAX_MAIN_FIRMWARE_UPDATE_DURATION_SECONDS
            if self._firmware_update_type == "main"
            else MAX_CHANNEL_FIRMWARE_UPDATE_DURATION_SECONDS
        )
        if update_dur_secs >= timeout_dur:
            raise FirmwareUpdateTimeoutError(self._firmware_update_type)

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

    def _check_worker_thread(self) -> None:
        if self._fw_update_worker_thread is None or self._fw_update_worker_thread.is_alive():
            return
        if self._fw_update_thread_dict is None:
            raise NotImplementedError("_fw_update_thread_dict should never be None here")
        to_main_queue = self._board_queues[0][1]
        if self._fw_update_worker_thread.errors():
            error_dict = {
                "communication_type": self._fw_update_thread_dict["communication_type"],
                "command": self._fw_update_thread_dict["command"],
                "error": self._fw_update_worker_thread.get_error(),
            }
            to_main_queue.put_nowait(error_dict)
        else:
            to_main_queue.put_nowait(self._fw_update_thread_dict)
        # clear values
        self._fw_update_worker_thread = None
        self._fw_update_thread_dict = None

    def _handle_performance_logging(self) -> None:
        performance_metrics: Dict[str, Any] = {"communication_type": "performance_metrics"}
        mc_measurements: List[
            Union[int, float]
        ]  # Tanner (5/28/20): This type annotation and the 'ignore' on the following line are necessary for mypy to not incorrectly type this variable
        for name, mc_measurements in (  # type: ignore
            ("data_read_num_bytes", self._data_read_lengths),
            ("data_read_duration", self._data_read_durations),
            ("data_parsing_duration", self._data_parsing_durations),
            ("data_parsing_num_packets_produced", self._data_parsing_num_packets_produced),
            ("duration_between_parsing", self._durations_between_parsing),
        ):
            performance_metrics[name] = {
                "max": max(mc_measurements),
                "min": min(mc_measurements),
                "stdev": round(stdev(mc_measurements), 6),
                "mean": round(sum(mc_measurements) / len(mc_measurements), 6),
            }
        self._send_performance_metrics(performance_metrics)
