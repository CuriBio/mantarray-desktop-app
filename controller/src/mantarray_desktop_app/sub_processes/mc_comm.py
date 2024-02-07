# -*- coding: utf-8 -*-
"""Process controlling communication with Mantarray Microcontroller."""
from __future__ import annotations

import copy
import datetime
from enum import auto
from enum import Enum
import logging
from multiprocessing import Queue
import queue
import struct
from time import perf_counter
from time import sleep
import traceback
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
from typing import Union
from zlib import crc32

from nptyping import NDArray
import numpy as np
from pulse3D.constants import DATETIME_STR_FORMAT
import serial
import serial.tools.list_ports as list_ports
from stdlib_utils import create_metrics_stats
from stdlib_utils import put_log_message_into_queue
from wakepy import set_keepawake
from wakepy import unset_keepawake

from .instrument_comm import InstrumentCommProcess
from ..constants import CURI_VID
from ..constants import DEFAULT_SAMPLING_PERIOD
from ..constants import GENERIC_24_WELL_DEFINITION
from ..constants import MAX_CHANNEL_FIRMWARE_UPDATE_DURATION_SECONDS
from ..constants import MAX_MAIN_FIRMWARE_UPDATE_DURATION_SECONDS
from ..constants import MAX_MC_REBOOT_DURATION_SECONDS
from ..constants import MICRO_TO_BASE_CONVERSION
from ..constants import NUM_INITIAL_SECONDS_TO_DROP
from ..constants import PERFOMANCE_LOGGING_PERIOD_SECS
from ..constants import SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE
from ..constants import SERIAL_COMM_BAUD_RATE
from ..constants import SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
from ..constants import SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE
from ..constants import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from ..constants import SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE
from ..constants import SERIAL_COMM_ERROR_ACK_PACKET_TYPE
from ..constants import SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
from ..constants import SERIAL_COMM_GET_ERROR_DETAILS_PACKET_TYPE
from ..constants import SERIAL_COMM_GET_METADATA_PACKET_TYPE
from ..constants import SERIAL_COMM_GOING_DORMANT_PACKET_TYPE
from ..constants import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from ..constants import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from ..constants import SERIAL_COMM_MAGIC_WORD_BYTES
from ..constants import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from ..constants import SERIAL_COMM_MAX_FULL_PACKET_LENGTH_BYTES
from ..constants import SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES
from ..constants import SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE
from ..constants import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from ..constants import SERIAL_COMM_NUM_DATA_CHANNELS
from ..constants import SERIAL_COMM_NUM_SENSORS_PER_WELL
from ..constants import SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES
from ..constants import SERIAL_COMM_PLATE_EVENT_PACKET_TYPE
from ..constants import SERIAL_COMM_REBOOT_PACKET_TYPE
from ..constants import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from ..constants import SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
from ..constants import SERIAL_COMM_SET_NICKNAME_PACKET_TYPE
from ..constants import SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE
from ..constants import SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
from ..constants import SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE
from ..constants import SERIAL_COMM_START_STIM_PACKET_TYPE
from ..constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from ..constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from ..constants import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from ..constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from ..constants import SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE
from ..constants import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from ..constants import SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE
from ..constants import SERIAL_COMM_STOP_STIM_PACKET_TYPE
from ..constants import STIM_COMPLETE_SUBPROTOCOL_IDX
from ..constants import STIM_MODULE_ID_TO_WELL_IDX
from ..constants import StimulatorCircuitStatuses
from ..constants import STM_VID
from ..exceptions import FirmwareAndSoftwareNotCompatibleError
from ..exceptions import FirmwareGoingDormantError
from ..exceptions import FirmwareUpdateCommandFailedError
from ..exceptions import FirmwareUpdateTimeoutError
from ..exceptions import IncorrectInstrumentConnectedError
from ..exceptions import InstrumentDataStreamingAlreadyStartedError
from ..exceptions import InstrumentDataStreamingAlreadyStoppedError
from ..exceptions import InstrumentFirmwareError
from ..exceptions import InstrumentRebootTimeoutError
from ..exceptions import InvalidCommandFromMainError
from ..exceptions import SamplingPeriodUpdateWhileDataStreamingError
from ..exceptions import SerialCommCommandProcessingError
from ..exceptions import SerialCommCommandResponseTimeoutError
from ..exceptions import SerialCommIncorrectChecksumFromPCError
from ..exceptions import SerialCommPacketRegistrationReadEmptyError
from ..exceptions import SerialCommPacketRegistrationSearchExhaustedError
from ..exceptions import SerialCommPacketRegistrationTimeoutError
from ..exceptions import SerialCommStatusBeaconTimeoutError
from ..exceptions import SerialCommUntrackedCommandResponseError
from ..exceptions import StimulationProtocolUpdateFailedError
from ..exceptions import StimulationProtocolUpdateWhileStimulatingError
from ..exceptions import StimulationStatusUpdateFailedError
from ..exceptions import UnrecognizedCommandFromMainToMcCommError
from ..exceptions import UnrecognizedSerialCommPacketTypeError
from ..simulators.mc_simulator import MantarrayMcSimulator
from ..utils.data_parsing_cy import parse_magnetometer_data
from ..utils.data_parsing_cy import parse_stim_data
from ..utils.data_parsing_cy import sort_serial_packets
from ..utils.generic import check_barcode_is_valid
from ..utils.generic import CommandTracker
from ..utils.generic import set_this_process_high_priority
from ..utils.serial_comm import convert_semver_str_to_bytes
from ..utils.serial_comm import convert_status_code_bytes_to_dict
from ..utils.serial_comm import convert_stim_dict_to_bytes
from ..utils.serial_comm import convert_stimulator_check_bytes_to_dict
from ..utils.serial_comm import create_data_packet
from ..utils.serial_comm import get_serial_comm_timestamp
from ..utils.serial_comm import parse_instrument_event_info
from ..utils.serial_comm import parse_metadata_bytes
from ..workers.firmware_downloader import check_versions
from ..workers.firmware_downloader import download_firmware_updates
from ..workers.worker_thread import ErrorCatchingThread


COMMAND_PACKET_TYPES = frozenset(
    [
        SERIAL_COMM_REBOOT_PACKET_TYPE,
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        SERIAL_COMM_START_STIM_PACKET_TYPE,
        SERIAL_COMM_STOP_STIM_PACKET_TYPE,
        SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE,
        SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE,
        SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE,
        SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE,
        SERIAL_COMM_GET_METADATA_PACKET_TYPE,
        SERIAL_COMM_SET_NICKNAME_PACKET_TYPE,
        SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE,
        SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE,
        SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE,
    ]
)


class MetadataStatuses(Enum):
    SKIP = auto()
    NEED = auto()
    ERROR = auto()


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


def _get_secs_since_last_data_sort(last_sort_time: float) -> float:
    return perf_counter() - last_sort_time


def _get_secs_since_last_data_read(last_read_time: float) -> float:
    return perf_counter() - last_read_time


def _get_secs_since_last_mag_data_parse(last_parse_time: float) -> float:
    return perf_counter() - last_parse_time


def _get_dur_of_data_read_secs(start: float) -> float:
    return perf_counter() - start


def _get_dur_of_data_sort_secs(start: float) -> float:
    return perf_counter() - start


def _get_dur_of_mag_data_parse_secs(start: float) -> float:
    return perf_counter() - start


def _is_simulator(board_connection: Any) -> bool:
    return isinstance(board_connection, MantarrayMcSimulator)


# TODO remove print_exception in stdlib_utils and then remove patch_print in tests
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
        self._simulator_error_queues: List[Optional[Queue[Tuple[Exception, str]]]] = [None] * len(
            self._board_queues
        )
        self._num_wells = 24
        self._is_registered_with_serial_comm: List[bool] = [False] * len(self._board_queues)
        self._metadata_status = MetadataStatuses.SKIP
        self._time_of_last_handshake_secs: Optional[float] = None
        self._time_of_last_beacon_secs: Optional[float] = None
        self._handshake_sent_after_beacon_missed = False
        self._commands_awaiting_response = CommandTracker()
        self._hardware_test_mode = hardware_test_mode
        # reboot values
        self._is_setting_nickname = False
        self._is_waiting_for_reboot = False  # Tanner (4/1/21): This flag indicates that a reboot command has been sent and a status beacon following reboot completion has not been received. It does not imply that the instrument has begun rebooting.
        self._time_of_reboot_start: Optional[
            float
        ] = None  # Tanner (4/1/21): This value will be None until this process receives a response to a reboot command. It will be set back to None after receiving a status beacon upon reboot completion
        # firmware updating values
        self._latest_versions: Optional[Dict[str, str]] = None
        self._fw_update_worker_thread: Optional[ErrorCatchingThread] = None
        self._fw_update_thread_dict: Optional[Dict[str, Any]] = None
        self._is_updating_firmware = False
        self._firmware_update_type = ""
        self._main_firmware_update_bytes: Optional[bytes] = None
        self._channel_firmware_update_bytes: Optional[bytes] = None
        self._firmware_file_contents: Optional[bytes] = None
        self._firmware_packet_idx: Optional[int] = None
        self._firmware_checksum: Optional[int] = None
        self._time_of_firmware_update_start: Optional[
            float
        ] = None  # Tanner (11/17/21): This value will only be a float when from the moment the end of firmware packet is received to the moment the firmware update complete packet is received
        # data streaming values
        self._base_global_time_of_data_stream = 0
        self._sampling_period_us = DEFAULT_SAMPLING_PERIOD
        self._is_data_streaming = False
        self._has_data_packet_been_sent = False
        self._discarding_beginning_of_data_stream = True
        self._serial_packet_cache = bytes(0)
        self._mag_data_cache_dict: Dict[str, Union[bytearray, int]]
        self._reset_mag_data_cache()
        # stimulation values
        self._well_stim_assignments: Dict[int, int] = {}
        self._wells_actively_stimulating: Set[int] = set()
        self._stim_status_buffers: Dict[int, Any]
        self._reset_stim_status_buffers()
        self._has_stim_packet_been_sent = False
        # performance tracking values
        self._iterations_per_logging_cycle = int(
            PERFOMANCE_LOGGING_PERIOD_SECS / self._minimum_iteration_duration_seconds
        )
        self._iterations_since_last_logging: List[int] = [0] * len(self._board_queues)
        self._performance_tracking_values: Dict[str, List[Any]]
        self._reset_performance_tracking_values()
        self._timepoints_of_prev_actions: Dict[str, Optional[float]]
        self._reset_timepoints_of_prev_actions()

    @property
    def _num_mag_packets_per_second(self) -> int:
        return MICRO_TO_BASE_CONVERSION // self._sampling_period_us

    @property
    def _is_stimulating(self) -> bool:
        return len(self._wells_actively_stimulating) > 0

    @_is_stimulating.setter
    def _is_stimulating(self, value: bool) -> None:
        if value:
            self._wells_actively_stimulating = set(well for well in self._well_stim_assignments)
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
        if _is_simulator(board):
            # Tanner (3/16/21): Current assumption is that a live mantarray will be running by the time we connect to it, so starting simulator here and waiting for it to complete start up
            board.start()  # type: ignore
            while not board.is_start_up_complete():  # type: ignore
                # sleep so as to not relentlessly ping the simulator
                sleep(0.1)
        else:
            # if connected to a real board, then make sure this process has a high priority
            set_this_process_high_priority()
            # also make sure that the computer does not put itself to sleep
            set_keepawake(keep_screen_awake=True)

        self._metadata_status = MetadataStatuses.NEED

    def _teardown_after_loop(self) -> None:
        board_idx = 0
        log_msg = f"Microcontroller Communication Process beginning teardown at {_get_formatted_utc_now()}"
        put_log_message_into_queue(
            logging.INFO, log_msg, self._board_queues[board_idx][1], self.get_logging_level()
        )
        board = self._board_connections[board_idx]
        if board is not None:
            # log any data in cache, flush and log remaining serial data
            put_log_message_into_queue(
                logging.INFO,
                f"Duration (seconds) since events: {self._get_dur_since_events()}. "
                f"Remaining serial data in cache: {list(self._serial_packet_cache)}, "
                f"in buffer: {list(board.read_all())}",
                self._board_queues[board_idx][1],
                self.get_logging_level(),
            )
            if _is_simulator(board):
                if board.is_alive():
                    board.hard_stop()  # hard stop to drain all queues of simulator
                    board.join()
            else:
                # turn off keepawake now that the process is exiting
                unset_keepawake()

                if self._error and isinstance(self._error, InstrumentFirmwareError):
                    self._send_data_packet(board_idx, SERIAL_COMM_ERROR_ACK_PACKET_TYPE, track_command=False)

        super()._teardown_after_loop()

    def _get_dur_since_events(self) -> Dict[str, float | str]:
        event_timepoints = {
            "status_beacon_received": self._time_of_last_beacon_secs,
            "handshake_sent": self._time_of_last_handshake_secs,
            **self._timepoints_of_prev_actions,
        }
        current_timepoint = perf_counter()
        return {
            event_name: ("No occurrence" if event_timepoint is None else current_timepoint - event_timepoint)
            for event_name, event_timepoint in event_timepoints.items()
        }

    def _report_fatal_error(self, err: Exception, formatted_stack_trace: Optional[str] = None) -> None:
        self._error = (
            err if not isinstance(err, SerialCommCommandProcessingError) else err.__cause__  # type: ignore
        )
        # TODO put the following code into InfiniteProcess._report_fatal_error in stdlib_utils
        if not formatted_stack_trace:
            formatted_stack_trace = "".join(traceback.format_exception(None, err, err.__traceback__))
        if isinstance(self._fatal_error_reporter, queue.Queue):
            raise NotImplementedError("The error reporter for InfiniteProcess cannot be a threading queue")
        self._fatal_error_reporter.put_nowait((err, formatted_stack_trace))

    def _reset_mag_data_cache(self) -> None:
        self._mag_data_cache_dict = {"raw_bytes": bytearray(0), "num_packets": 0}

    def _reset_stim_status_buffers(self) -> None:
        self._stim_status_buffers = {well_idx: [[], []] for well_idx in range(self._num_wells)}

    def _reset_performance_tracking_values(self) -> None:
        self._reset_performance_measurements()
        self._performance_tracking_values = {
            key: list()
            for key in (
                "period_between_reading",
                "data_read_duration",
                "num_bytes_read",
                "period_between_sorting",
                "sorting_duration",
                "num_packets_sorted",
                "period_between_mag_data_parsing",
                "mag_data_parsing_duration",
                "num_mag_packets_parsed",
            )
        }

    def _reset_timepoints_of_prev_actions(self) -> None:
        self._timepoints_of_prev_actions = {
            key: None
            for key in (
                "data_read",
                "packet_sort",
                "mag_data_parse",
                "stim_data_parse",
                "command_sent",
                "command_response_received",
            )
        }

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
            msg = {"communication_type": "board_connection_status_change", "board_index": i}
            serial_obj, msg["message"] = self._create_board_connection()
            self.set_board_connection(i, serial_obj)
            msg["is_connected"] = not _is_simulator(serial_obj)
            msg["timestamp"] = _get_formatted_utc_now()
            to_main_queue.put_nowait(msg)

    def _create_board_connection(self) -> Tuple[Union[MantarrayMcSimulator, serial.Serial], str]:
        for port_info in list_ports.comports():
            # Tanner (6/14/21): attempt to connect to any device with the STM vendor ID
            if port_info.vid in (STM_VID, CURI_VID):
                conn_msg = f"Board detected with description: {port_info.description}"
                serial_conn = serial.Serial(
                    port=port_info.name,
                    baudrate=SERIAL_COMM_BAUD_RATE,
                    bytesize=8,
                    timeout=0,
                    stopbits=serial.STOPBITS_ONE,
                )
                return serial_conn, conn_msg
        # create simulator as no serial connection could be made
        creating_sim_msg = "No board detected. Creating simulator."
        simulator = MantarrayMcSimulator(Queue(), Queue(), Queue(), Queue(), num_wells=self._num_wells)
        return simulator, creating_sim_msg

    def set_board_connection(self, board_idx: int, board: Union[MantarrayMcSimulator, serial.Serial]) -> None:
        super().set_board_connection(board_idx, board)
        self._in_simulation_mode = _is_simulator(board)
        if self._in_simulation_mode:
            self._simulator_error_queues[board_idx] = board.get_fatal_error_reporter()

    def _send_data_packet(
        self, board_idx: int, packet_type: int, data_to_send: bytes = bytes(0), track_command: bool = True
    ) -> None:
        if track_command:
            self._timepoints_of_prev_actions["command_sent"] = perf_counter()

        data_packet = create_data_packet(get_serial_comm_timestamp(), packet_type, data_to_send)
        board = self._board_connections[board_idx]
        if board is None:
            raise NotImplementedError("Board should not be None when sending a command to it")

        write_len = board.write(data_packet)
        if write_len == 0:
            put_log_message_into_queue(
                logging.INFO,
                "Serial data write reporting no bytes written",
                self._board_queues[board_idx][1],
                self.get_logging_level(),
            )

    def _commands_for_each_run_iteration(self) -> None:
        """Ordered actions to perform each iteration.

        This process must be responsive to communication from the main process and then the instrument before anything else.

        After reboot command is sent, no more commands should be sent until reboot completes.
        During instrument reboot, should only check for incoming data make sure no commands are awaiting a response.

        1. Before doing anything, simulator errors must be checked for. If they go unchecked before performing comm with the simulator, and error may be raised in this process that masks the simulator's error which is actually the root of the problem.
        2. Process next communication from main. This process's next highest priority is to be responsive to the main process and should check for messages from main first. These messages will let this process know when to send commands to the instrument. Ignore messages from main if conducting a firmware update
        3. Send handshake to instrument when necessary. Third highest priority is to let the instrument know that this process and the rest of the software are alive and responsive.
        4. Sync with the magic word coming from the instrument. If this is already done, then process packets coming from the instrument. This is the highest priority task after sending data to it.
        5. Handle performance tracking if data is streaming
        6. Make sure the beacon is not overdue, unless instrument is rebooting. If the beacon is overdue, it's reasonable to assume something caused the instrument to stop working. This task should happen after handling of sending/receiving data from the instrument and main process.
        7. Make sure commands are not overdue. This task should happen after the instrument has been determined to be working properly.
        8. If rebooting or waiting for firmware update to complete, make sure that the reboot has not taken longer than the max allowed reboot time.
        9. Check on the status of any worker threads.
        """
        board_idx = 0

        if self._in_simulation_mode:
            if self._check_simulator_error():
                self.stop()
                return

        if (
            not self._is_updating_firmware
            and not self._is_setting_nickname
            and not self._is_waiting_for_reboot
        ):
            self._process_next_communication_from_main()

        self._handle_sending_handshake()

        if not self._is_registered_with_serial_comm[board_idx]:
            self._register_magic_word(board_idx)
        else:
            self._handle_data_stream()

            if self._is_data_streaming or self._is_stimulating:
                # handle performance logging if ready
                self._iterations_since_last_logging[board_idx] += 1
                if self._iterations_since_last_logging[board_idx] > self._iterations_per_logging_cycle:
                    self._handle_performance_logging()
                    self._iterations_since_last_logging[board_idx] = 0

        self._handle_beacon_tracking()
        self._handle_command_tracking()

        if self._is_waiting_for_reboot:
            self._check_reboot_status()
        elif self._is_updating_firmware:
            self._check_firmware_update_status()

        self._check_worker_thread()

        # process can be soft stopped if no commands in queue from main and no command responses needed from instrument
        self._process_can_be_soft_stopped = (
            not bool(self._commands_awaiting_response)
            and self._board_queues[0][0].empty()
            # TODO prevent soft stop if rebooting, updating firmware, or there is an active worker thread
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
        bytes_to_send = bytes(0)
        packet_type = None

        communication_type = comm_from_main["communication_type"]
        if communication_type == "mantarray_naming":
            if comm_from_main["command"] == "set_mantarray_nickname":
                packet_type = SERIAL_COMM_SET_NICKNAME_PACKET_TYPE
                bytes_to_send = bytes(
                    comm_from_main["mantarray_nickname"], "utf-8"
                )  # TODO append '\x00' until it is 13 bytes long if needed
                self._is_setting_nickname = True
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "to_instrument":
            if comm_from_main["command"] == "reboot":
                packet_type = SERIAL_COMM_REBOOT_PACKET_TYPE
                self._is_waiting_for_reboot = True
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "acquisition_manager":
            if comm_from_main["command"] == "start_managed_acquisition":
                self._reset_timepoints_of_prev_actions()
                self._iterations_since_last_logging = [0] * len(self._board_queues)
                packet_type = SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE
            elif comm_from_main["command"] == "stop_managed_acquisition":
                packet_type = SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE
            elif comm_from_main["command"] == "set_sampling_period":
                if self._is_data_streaming:
                    raise SamplingPeriodUpdateWhileDataStreamingError()
                packet_type = SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE
                bytes_to_send = comm_from_main["sampling_period"].to_bytes(2, byteorder="little")
                self._sampling_period = comm_from_main["sampling_period"]
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "stimulation":
            if comm_from_main["command"] == "start_stim_checks":
                packet_type = SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE
                bytes_to_send = struct.pack(
                    f"<{self._num_wells}?",
                    *[
                        STIM_MODULE_ID_TO_WELL_IDX[module_id] in comm_from_main["well_indices"]
                        for module_id in range(self._num_wells)
                    ],
                )
            elif comm_from_main["command"] == "set_protocols":
                packet_type = SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
                bytes_to_send = convert_stim_dict_to_bytes(comm_from_main["stim_info"])

                if self._is_stimulating and not self._hardware_test_mode:
                    raise StimulationProtocolUpdateWhileStimulatingError()

                protocols = comm_from_main["stim_info"]["protocols"]
                protocol_assignments = comm_from_main["stim_info"]["protocol_assignments"]

                protocol_id_to_idx = {protocol["protocol_id"]: idx for idx, protocol in enumerate(protocols)}
                self._well_stim_assignments = {
                    GENERIC_24_WELL_DEFINITION.get_well_index_from_well_name(well_name): protocol_id_to_idx[
                        protocol_id
                    ]
                    for well_name, protocol_id in protocol_assignments.items()
                    if protocol_id is not None
                }
            elif comm_from_main["command"] == "start_stimulation":
                packet_type = SERIAL_COMM_START_STIM_PACKET_TYPE
            elif comm_from_main["command"] == "stop_stimulation":
                packet_type = SERIAL_COMM_STOP_STIM_PACKET_TYPE
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "metadata_comm":
            packet_type = SERIAL_COMM_GET_METADATA_PACKET_TYPE
        elif communication_type == "firmware_update":
            if comm_from_main["command"] == "check_versions":
                # set up worker thread
                self._fw_update_thread_dict = {
                    "communication_type": "firmware_update",
                    "command": comm_from_main["command"],
                }
                self._fw_update_worker_thread = ErrorCatchingThread(
                    target=check_versions,
                    args=(
                        self._fw_update_thread_dict,
                        comm_from_main["serial_number"],
                        comm_from_main["main_fw_version"],
                        comm_from_main["fw_update_dir_path"],
                    ),
                    use_error_repr=False,
                )
                self._fw_update_worker_thread.start()
            elif comm_from_main["command"] == "download_firmware_updates":
                if not comm_from_main["main"] and not comm_from_main["channel"]:
                    raise InvalidCommandFromMainError(
                        "Cannot download firmware files if neither firmware type needs an update"
                    )
                # set up worker thread
                self._fw_update_thread_dict = {
                    "communication_type": "firmware_update",
                    "command": comm_from_main["command"],
                    "main": None,
                    "channel": None,
                }
                self._fw_update_worker_thread = ErrorCatchingThread(
                    target=download_firmware_updates,
                    args=(
                        self._fw_update_thread_dict,
                        comm_from_main["main"],
                        comm_from_main["channel"],
                        comm_from_main["customer_id"],
                        comm_from_main["username"],
                        comm_from_main["password"],
                        comm_from_main["fw_update_dir_path"],
                    ),
                )
                self._fw_update_worker_thread.start()
            elif comm_from_main["command"] == "start_firmware_update":
                packet_type = SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
                self._firmware_update_type = comm_from_main["firmware_type"]
                bytes_to_send = bytes([self._firmware_update_type == "channel"])
                if self._latest_versions is None:
                    raise NotImplementedError("_latest_versions should never be None here")
                bytes_to_send += convert_semver_str_to_bytes(
                    self._latest_versions[f"{self._firmware_update_type}_fw"]
                )
                # store correct firmware bytes
                if self._firmware_update_type == "channel":
                    self._firmware_file_contents = self._channel_firmware_update_bytes
                    self._channel_firmware_update_bytes = None
                else:
                    self._firmware_file_contents = self._main_firmware_update_bytes
                    self._main_firmware_update_bytes = None
                # mypy check
                if self._firmware_file_contents is None:
                    raise NotImplementedError("_firmware_file_contents should never be None here")
                bytes_to_send += len(self._firmware_file_contents).to_bytes(4, byteorder="little")
                # set up values for firmware update
                self._firmware_packet_idx = 0
                self._is_updating_firmware = True
                self._firmware_checksum = crc32(self._firmware_file_contents)
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        elif communication_type == "test":  # pragma: no cover
            if comm_from_main["command"] == "trigger_firmware_error":
                packet_type = 103
                bytes_to_send = bytes(comm_from_main["first_two_status_codes"])
            else:
                raise UnrecognizedCommandFromMainToMcCommError(
                    f"Invalid command: {comm_from_main['command']} for communication_type: {communication_type}"
                )
        else:
            raise UnrecognizedCommandFromMainToMcCommError(
                f"Invalid communication_type: {communication_type}"
            )

        if packet_type is not None:
            self._send_data_packet(board_idx, packet_type, bytes_to_send)
            self._add_command_to_track(packet_type, comm_from_main)

    def _add_command_to_track(self, packet_type: int, command_dict: Dict[str, Any]) -> None:
        command_dict["timepoint"] = perf_counter()
        self._commands_awaiting_response.add(packet_type, command_dict)

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
                "firmware_type": self._firmware_update_type,
            }
            self._firmware_file_contents = None
            self._firmware_checksum = None
        else:
            if self._firmware_file_contents is None:  # making mypy happy
                raise NotImplementedError("_firmware_file_contents should never be None here")
            packet_type = SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
            bytes_to_send = (
                bytes([self._firmware_packet_idx])
                + self._firmware_file_contents[: SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES - 1]
            )
            command_dict = {
                "communication_type": "firmware_update",
                "command": "send_firmware_data",
                "firmware_type": self._firmware_update_type,
                "packet_index": self._firmware_packet_idx,
            }
            self._firmware_file_contents = self._firmware_file_contents[
                SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES - 1 :
            ]
        self._send_data_packet(board_idx, packet_type, bytes_to_send)
        self._add_command_to_track(packet_type, command_dict)

    def _handle_sending_handshake(self) -> None:
        board_idx = 0
        if self._board_connections[board_idx] is None:
            return
        if self._has_initial_handshake_been_sent():
            seconds_elapsed = _get_secs_since_last_handshake(self._time_of_last_handshake_secs)  # type: ignore
            if seconds_elapsed < SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS:
                return
        self._send_handshake(board_idx)

    def _has_initial_handshake_been_sent(self) -> bool:
        # Extracting this into its own method to make mocking in tests easier
        return self._time_of_last_handshake_secs is not None

    def _send_handshake(self, board_idx: int) -> None:
        self._time_of_last_handshake_secs = perf_counter()
        self._send_data_packet(board_idx, SERIAL_COMM_HANDSHAKE_PACKET_TYPE, track_command=False)

    def _process_comm_from_instrument(self, packet_type: int, packet_payload: bytes) -> None:
        if packet_type == SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE:
            returned_packet = SERIAL_COMM_MAGIC_WORD_BYTES + packet_payload
            raise SerialCommIncorrectChecksumFromPCError(returned_packet)

        board_idx = 0

        if packet_type == SERIAL_COMM_STATUS_BEACON_PACKET_TYPE:
            self._process_status_beacon(packet_payload)
        elif packet_type == SERIAL_COMM_HANDSHAKE_PACKET_TYPE:
            status_codes_dict = convert_status_code_bytes_to_dict(packet_payload)
            self._handle_status_codes(status_codes_dict, "Handshake Response")
        elif packet_type == SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE:
            raise NotImplementedError(
                "Should never receive magnetometer data packets when not streaming data"
            )
        elif packet_type == SERIAL_COMM_GOING_DORMANT_PACKET_TYPE:
            going_dormant_reason = packet_payload[0]
            raise FirmwareGoingDormantError(going_dormant_reason)
        elif packet_type in COMMAND_PACKET_TYPES:
            try:
                prev_command = self._commands_awaiting_response.pop(packet_type)
            except ValueError:
                raise SerialCommUntrackedCommandResponseError(
                    f"Packet Type ID: {packet_type}, Packet Body: {str(packet_payload)}"
                )

            response_data = packet_payload
            if prev_command["command"] == "get_metadata":
                prev_command["board_index"] = board_idx
                prev_command["metadata"] = metadata = parse_metadata_bytes(response_data)
                if self._metadata_status == MetadataStatuses.ERROR:
                    raise InstrumentFirmwareError(f"Error Details: {metadata}")
                if metadata.pop("is_stingray"):
                    raise IncorrectInstrumentConnectedError()
            elif prev_command["command"] == "reboot":
                prev_command["message"] = "Instrument beginning reboot"
                self._time_of_reboot_start = perf_counter()
            elif prev_command["command"] == "set_mantarray_nickname":
                self._is_setting_nickname = False
                # set up values for reboot
                self._is_waiting_for_reboot = True
                self._time_of_reboot_start = perf_counter()
            elif prev_command["command"] == "start_managed_acquisition":
                self._reset_mag_data_cache()
                self._is_data_streaming = True
                self._has_stim_packet_been_sent = False
                self._has_data_packet_been_sent = False
                self._discarding_beginning_of_data_stream = True
                if response_data[0]:
                    if not self._hardware_test_mode:
                        raise InstrumentDataStreamingAlreadyStartedError()
                    prev_command["hardware_test_message"] = "Data stream already started"  # pragma: no cover
                else:
                    self._base_global_time_of_data_stream = int.from_bytes(
                        response_data[1:9], byteorder="little"
                    )
                prev_command["timestamp"] = datetime.datetime.utcnow()
                # Tanner (6/11/21): This helps prevent against status beacon timeouts with beacons that come just after the data stream begins but before 1 second of data is available
                self._time_of_last_beacon_secs = perf_counter()
            elif prev_command["command"] == "stop_managed_acquisition":
                self._is_data_streaming = False
                if response_data[0]:
                    if not self._hardware_test_mode:
                        raise InstrumentDataStreamingAlreadyStoppedError()
                    prev_command["hardware_test_message"] = "Data stream already stopped"  # pragma: no cover
            elif prev_command["command"] == "start_stim_checks":
                stimulator_check_dict = convert_stimulator_check_bytes_to_dict(response_data)

                stimulator_circuit_statuses: Dict[int, str] = {}
                adc_readings: Dict[int, Tuple[int, int]] = {}

                for module_id, (adc8, adc9, status_int) in enumerate(zip(*stimulator_check_dict.values())):
                    well_idx = STIM_MODULE_ID_TO_WELL_IDX[module_id]
                    if well_idx not in prev_command["well_indices"]:
                        continue
                    status_str = list(StimulatorCircuitStatuses)[status_int + 1].name.lower()
                    stimulator_circuit_statuses[well_idx] = status_str
                    adc_readings[well_idx] = (adc8, adc9)

                prev_command["stimulator_circuit_statuses"] = stimulator_circuit_statuses
                prev_command["adc_readings"] = adc_readings
            elif prev_command["command"] == "set_protocols":
                if response_data[0]:
                    if not self._hardware_test_mode:
                        raise StimulationProtocolUpdateFailedError()
                    prev_command["hardware_test_message"] = "Command failed"  # pragma: no cover
                # delete stim info so it is not logged again
                del prev_command["stim_info"]
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
            # Tanner (2/4/22): currently unused in favor of SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE, but plan to switch back to this packet type when the instrument is able to detect whether or not a plate was placed or removed
            plate_was_placed = bool(packet_payload[0])
            barcode = packet_payload[1:].decode("ascii") if plate_was_placed else ""
            barcode_comm = {"communication_type": "barcode_comm", "board_idx": board_idx, "barcode": barcode}
            if plate_was_placed:
                barcode_comm["valid"] = check_barcode_is_valid(barcode, True)
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
            # set up values for reboot
            self._is_waiting_for_reboot = True
            self._time_of_reboot_start = perf_counter()
        elif packet_type == SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE:
            barcode = packet_payload.decode("ascii")
            barcode_comm = {
                "communication_type": "barcode_comm",
                "board_idx": board_idx,
                "barcode": barcode,
                "valid": check_barcode_is_valid(barcode, True),
            }
            self._board_queues[board_idx][1].put_nowait(barcode_comm)
        elif packet_type == SERIAL_COMM_GET_ERROR_DETAILS_PACKET_TYPE:
            error_details = parse_instrument_event_info(packet_payload)
            raise InstrumentFirmwareError(f"Error Details: {error_details}")
        else:
            raise UnrecognizedSerialCommPacketTypeError(f"Packet Type ID: {packet_type} is not defined")

        if packet_type not in (
            # beacons + handshakes tracked separately, going dormant packet will raise an error and does not need to be tracked
            SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
            SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
            SERIAL_COMM_GOING_DORMANT_PACKET_TYPE,
        ):
            self._timepoints_of_prev_actions["command_response_received"] = perf_counter()

    def _process_status_beacon(self, packet_payload: bytes) -> None:
        status_codes_dict = convert_status_code_bytes_to_dict(
            packet_payload[:SERIAL_COMM_STATUS_CODE_LENGTH_BYTES]
        )
        self._handle_status_codes(status_codes_dict, "Status Beacon")

    def _register_magic_word(self, board_idx: int) -> None:
        board = self._board_connections[board_idx]
        if board is None:
            return

        # read bytes once every second until enough bytes have been read or timeout occurs
        # Tanner (3/16/21): issue seen with simulator taking slightly longer than status beacon period to send next data packet
        magic_word_len = len(SERIAL_COMM_MAGIC_WORD_BYTES)
        seconds_remaining = SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS + 4
        magic_word_test_bytes = board.read(size=magic_word_len)
        while (num_bytes_remaining := magic_word_len - len(magic_word_test_bytes)) and seconds_remaining:
            magic_word_test_bytes += board.read(size=num_bytes_remaining)
            seconds_remaining -= 1
            sleep(1)
        if len(magic_word_test_bytes) != magic_word_len:
            # if the entire period has passed and no more bytes are available an error has occurred with the Mantarray that is considered fatal
            raise SerialCommPacketRegistrationTimeoutError(list(magic_word_test_bytes))

        # read more bytes until the magic word is registered, the timeout value is reached, or the maximum number of bytes are read
        num_bytes_checked = 0
        start = perf_counter()
        while (
            magic_word_test_bytes != SERIAL_COMM_MAGIC_WORD_BYTES
            and _get_secs_since_read_start(start) < SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
        ):
            # read 0 or 1 bytes, depending on what is available in serial port
            next_byte = board.read(size=1)
            num_bytes_checked += len(next_byte)
            if next_byte:
                # only want to run this append expression if a byte was read
                magic_word_test_bytes = magic_word_test_bytes[1:] + next_byte
            if num_bytes_checked > SERIAL_COMM_MAX_FULL_PACKET_LENGTH_BYTES:
                # A magic word should be encountered if this many bytes are read. If not, we can assume there was a problem with the mantarray
                raise SerialCommPacketRegistrationSearchExhaustedError()
        # if this point is reached and the magic word has not been found, then at some point no additional bytes were being read, so raise error
        if magic_word_test_bytes != SERIAL_COMM_MAGIC_WORD_BYTES:
            raise SerialCommPacketRegistrationReadEmptyError()
        self._is_registered_with_serial_comm[board_idx] = True

        # put the magic word bytes into the cache so the next data packet can be read properly
        self._serial_packet_cache = SERIAL_COMM_MAGIC_WORD_BYTES
        # immediately process this packet since it would otherwise be skipped in _commands_for_each_run_iteration
        self._handle_data_stream()

    def _handle_data_stream(self) -> None:
        board_idx = 0
        board = self._board_connections[board_idx]
        if not board:
            raise NotImplementedError("board should never be None here")

        new_performance_tracking_values: Dict[str, Any] = dict()

        if self._timepoints_of_prev_actions["data_read"] is not None:
            new_performance_tracking_values["period_between_reading"] = _get_secs_since_last_data_read(
                self._timepoints_of_prev_actions["data_read"]
            )
        self._timepoints_of_prev_actions["data_read"] = perf_counter()
        # read bytes from serial buffer
        try:
            data_read_bytes = board.read_all()
        except serial.SerialException as e:
            put_log_message_into_queue(
                logging.INFO,
                f"Serial data read failed: {e}. Trying one more time",
                self._board_queues[board_idx][1],
                self.get_logging_level(),
            )
            data_read_bytes = board.read_all()

        new_performance_tracking_values["data_read_duration"] = _get_dur_of_data_read_secs(
            self._timepoints_of_prev_actions["data_read"]  # type: ignore
        )
        new_performance_tracking_values["num_bytes_read"] = len(data_read_bytes)

        # append all bytes to cache
        self._serial_packet_cache += data_read_bytes
        # return if not at least 1 complete packet available
        if len(self._serial_packet_cache) < SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES:
            return

        if self._timepoints_of_prev_actions["packet_sort"] is not None:
            new_performance_tracking_values["period_between_sorting"] = _get_secs_since_last_data_sort(
                self._timepoints_of_prev_actions["packet_sort"]
            )
        self._timepoints_of_prev_actions["packet_sort"] = perf_counter()
        # sort packets by into packet type groups: magnetometer data, stim status, other
        sorted_packet_dict = sort_serial_packets(bytearray(self._serial_packet_cache))
        new_performance_tracking_values["sorting_duration"] = _get_dur_of_data_sort_secs(
            self._timepoints_of_prev_actions["packet_sort"]  # type: ignore
        )
        new_performance_tracking_values["num_packets_sorted"] = sorted_packet_dict["num_packets_sorted"]

        # update unsorted bytes
        self._serial_packet_cache = sorted_packet_dict["unread_bytes"]

        # process any other packets
        for other_packet_info in sorted_packet_dict["other_packet_info"]:
            timestamp, packet_type, packet_payload = other_packet_info
            try:
                self._process_comm_from_instrument(packet_type, packet_payload)
            except (
                IncorrectInstrumentConnectedError,
                InstrumentFirmwareError,
                FirmwareGoingDormantError,
                SerialCommUntrackedCommandResponseError,
                SerialCommIncorrectChecksumFromPCError,
                InstrumentDataStreamingAlreadyStartedError,
                InstrumentDataStreamingAlreadyStoppedError,
                StimulationProtocolUpdateFailedError,
                StimulationStatusUpdateFailedError,
                FirmwareUpdateCommandFailedError,
            ):
                raise
            except Exception as e:
                raise SerialCommCommandProcessingError(
                    f"Timestamp: {timestamp}, Packet Type: {packet_type}, Payload: {packet_payload}"
                ) from e

        # create dict and send to file writer if any stream packets were found
        self._handle_mag_data_packets(sorted_packet_dict["magnetometer_stream_info"])
        self._handle_stim_packets(sorted_packet_dict["stim_stream_info"])

        self._update_performance_metrics(new_performance_tracking_values)

    # Tanner (10/15/21): if performance needs to be improved, consider converting some of this function to cython
    def _handle_mag_data_packets(self, mag_stream_info: Dict[str, Union[bytes, int]]) -> None:
        # don't update cache if not streaming or there are no packets to add
        if not (self._is_data_streaming and mag_stream_info["num_packets"]):
            return
        # update cache values
        for key, value in mag_stream_info.items():
            self._mag_data_cache_dict[key] += value  # type: ignore

        # don't parse and send to file writer unless there is at least 1 second worth of data
        if self._mag_data_cache_dict["num_packets"] < self._num_mag_packets_per_second:  # type: ignore
            return

        new_performance_tracking_values: Dict[str, Any] = dict()

        if self._timepoints_of_prev_actions["mag_data_parse"] is not None:
            new_performance_tracking_values[
                "period_between_mag_data_parsing"
            ] = _get_secs_since_last_mag_data_parse(self._timepoints_of_prev_actions["mag_data_parse"])
        self._timepoints_of_prev_actions["mag_data_parse"] = perf_counter()
        # parse magnetometer data
        parsed_mag_data_dict = parse_magnetometer_data(
            *self._mag_data_cache_dict.values(), self._base_global_time_of_data_stream
        )
        new_performance_tracking_values["mag_data_parsing_duration"] = _get_dur_of_mag_data_parse_secs(
            self._timepoints_of_prev_actions["mag_data_parse"]  # type: ignore
        )

        time_indices, time_offsets, data = parsed_mag_data_dict.values()

        new_performance_tracking_values["num_mag_packets_parsed"] = len(time_indices)

        is_first_packet = not self._has_data_packet_been_sent

        if self._discarding_beginning_of_data_stream:
            earliest_allowed_time_index = NUM_INITIAL_SECONDS_TO_DROP * MICRO_TO_BASE_CONVERSION
            if time_indices[-1] >= earliest_allowed_time_index:
                self._discarding_beginning_of_data_stream = False
                self._base_global_time_of_data_stream += int(time_indices[-1])

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
        else:
            data_slice = slice(0, self._mag_data_cache_dict["num_packets"])
            mag_data_packet: Dict[Any, Any] = {
                "data_type": "magnetometer",
                "time_indices": time_indices[data_slice],
                "is_first_packet_of_stream": is_first_packet,
            }

            time_offset_idx = 0
            for module_id in range(self._num_wells):
                time_offset_slice = slice(time_offset_idx, time_offset_idx + SERIAL_COMM_NUM_SENSORS_PER_WELL)
                time_offset_idx += SERIAL_COMM_NUM_SENSORS_PER_WELL

                well_dict: Dict[Any, Any] = {"time_offsets": time_offsets[time_offset_slice, data_slice]}

                data_idx = module_id * SERIAL_COMM_NUM_DATA_CHANNELS
                for channel_idx in range(SERIAL_COMM_NUM_DATA_CHANNELS):
                    well_dict[channel_idx] = data[data_idx + channel_idx, data_slice]

                well_idx = SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id]
                mag_data_packet[well_idx] = well_dict

            self._dump_mag_data_packet(mag_data_packet)

        # reset cache now that all mag data has been parsed
        self._reset_mag_data_cache()

        self._update_performance_metrics(new_performance_tracking_values)

    def _dump_mag_data_packet(self, mag_data_packet: Dict[Any, Any]) -> None:
        to_fw_queue = self._board_queues[0][2]
        to_fw_queue.put_nowait(mag_data_packet)
        self._has_data_packet_been_sent = True

    def _handle_stim_packets(self, stim_stream_info: Dict[str, Union[bytes, int]]) -> None:
        if not stim_stream_info["num_packets"]:
            return

        self._timepoints_of_prev_actions["stim_data_parse"] = perf_counter()

        protocol_statuses: Dict[int, Any] = parse_stim_data(*stim_stream_info.values())

        well_statuses: Dict[int, Any] = {}

        for well_idx in range(self._num_wells):
            protocol_idx = self._well_stim_assignments.get(well_idx)

            if protocol_idx not in protocol_statuses:
                continue

            stim_statuses = protocol_statuses[protocol_idx]
            well_statuses[well_idx] = stim_statuses.copy()
            for i in range(2):
                self._stim_status_buffers[well_idx][i] = self._stim_status_buffers[well_idx][i][-1:]
                self._stim_status_buffers[well_idx][i].extend(stim_statuses[i])

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

        if self._is_data_streaming and not self._discarding_beginning_of_data_stream:
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
        if (
            self._time_of_last_beacon_secs is None
            or self._is_waiting_for_reboot
            or self._is_updating_firmware
            or self._is_setting_nickname
        ):
            return
        secs_since_last_beacon_received = _get_secs_since_last_beacon(self._time_of_last_beacon_secs)
        if (
            secs_since_last_beacon_received >= SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS + 1
            and not self._handshake_sent_after_beacon_missed
        ):
            board_idx = 0
            put_log_message_into_queue(
                logging.INFO,
                "Status Beacon overdue. Sending handshake now to prompt a response.",
                self._board_queues[board_idx][1],
                self.get_logging_level(),
            )
            self._send_handshake(board_idx)
            self._handshake_sent_after_beacon_missed = True
        elif secs_since_last_beacon_received >= SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS:
            raise SerialCommStatusBeaconTimeoutError()

    def _handle_command_tracking(self) -> None:
        try:
            oldest_command = self._commands_awaiting_response.oldest()
        except IndexError:
            return

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

    def _handle_status_codes(self, status_codes_dict: Dict[str, int], comm_type: str) -> None:
        self._time_of_last_beacon_secs = perf_counter()
        self._handshake_sent_after_beacon_missed = False

        board_idx = 0

        is_error_code_present = any(status_codes_dict.values())

        # Tanner (7/17/23): need to retrieve metadata after the first status beacon is received, and before handling any error codes
        if self._metadata_status == MetadataStatuses.NEED:
            self._send_data_packet(board_idx, SERIAL_COMM_GET_METADATA_PACKET_TYPE)
            self._add_command_to_track(
                SERIAL_COMM_GET_METADATA_PACKET_TYPE,
                {"communication_type": "metadata_comm", "command": "get_metadata"},
            )
            self._metadata_status = MetadataStatuses.ERROR if is_error_code_present else MetadataStatuses.SKIP

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

        status_codes_msg = f"{comm_type} received from instrument. Status Codes: {status_codes_dict}"
        put_log_message_into_queue(
            logging.ERROR if is_error_code_present else logging.DEBUG,
            status_codes_msg,
            self._board_queues[board_idx][1],
            self.get_logging_level(),
        )

        if is_error_code_present:
            put_log_message_into_queue(
                logging.ERROR,
                "Retrieving error details from instrument",
                self._board_queues[board_idx][1],
                self.get_logging_level(),
            )
            self._send_data_packet(board_idx, SERIAL_COMM_GET_ERROR_DETAILS_PACKET_TYPE)
            self._add_command_to_track(
                SERIAL_COMM_GET_ERROR_DETAILS_PACKET_TYPE,
                {"communication_type": "error_retrieval", "command": "get_error_details"},
            )

    def _check_simulator_error(self) -> bool:
        board_idx = 0
        simulator_error_queue = self._simulator_error_queues[board_idx]
        if simulator_error_queue is None:  # making mypy happy
            raise NotImplementedError("simulator_error_queue should never be None here")

        simulator_has_error = not simulator_error_queue.empty()
        if simulator_has_error:
            # Tanner (4/22/21): setting an arbitrary, very high timeout value here to prevent possible hanging, even though if the queue is not empty it should not hang indefinitely
            self._report_fatal_error(*simulator_error_queue.get(timeout=5))
        return simulator_has_error

    def _check_worker_thread(self) -> None:
        if self._fw_update_worker_thread is None or self._fw_update_worker_thread.is_alive():
            return

        self._fw_update_worker_thread.join()

        if self._fw_update_thread_dict is None:
            raise NotImplementedError("_fw_update_thread_dict should never be None here")

        to_main_queue = self._board_queues[0][1]
        if error := self._fw_update_worker_thread.error:
            if isinstance(error, Exception):
                if isinstance(error, FirmwareAndSoftwareNotCompatibleError):
                    raise error
                # pull out error message to send to main
                error = error.args[0]
            error_dict = {
                "communication_type": self._fw_update_thread_dict["communication_type"],
                "command": self._fw_update_thread_dict["command"],
                "error": error,
            }
            to_main_queue.put_nowait(error_dict)
        else:
            if self._fw_update_thread_dict["command"] == "check_versions":
                self._latest_versions = copy.deepcopy(self._fw_update_thread_dict["latest_versions"])
            elif self._fw_update_thread_dict["command"] == "download_firmware_updates":
                # pop firmware bytes out of dict and store
                self._main_firmware_update_bytes = self._fw_update_thread_dict.pop("main")
                self._channel_firmware_update_bytes = self._fw_update_thread_dict.pop("channel")
                # add message
                self._fw_update_thread_dict["message"] = "Updates downloaded, ready to install"
            else:
                raise NotImplementedError(
                    f"Invalid worker thread command: {self._fw_update_thread_dict['command']}"
                )
            to_main_queue.put_nowait(self._fw_update_thread_dict)
        # clear values
        self._fw_update_worker_thread = None
        self._fw_update_thread_dict = None

    def _update_performance_metrics(self, new_performance_tracking_values: Dict[str, Any]) -> None:
        for metric_name, metric_value in new_performance_tracking_values.items():
            self._performance_tracking_values[metric_name].append(metric_value)

    def _handle_performance_logging(self) -> None:
        if logging.DEBUG >= self._logging_level:  # pragma: no cover
            performance_metrics: Dict[str, Any] = {"communication_type": "performance_metrics"}
            for metric_name, metric_values in self._performance_tracking_values.items():
                performance_metrics[metric_name] = None
                if len(metric_values) > 2:
                    performance_metrics[metric_name] = create_metrics_stats(metric_values)
            self._send_performance_metrics(performance_metrics)
        self._reset_performance_tracking_values()
