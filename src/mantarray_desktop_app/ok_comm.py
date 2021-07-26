# -*- coding: utf-8 -*-
"""Controlling communication with the OpalKelly FPGA Boards."""
from __future__ import annotations

import datetime
import functools
from functools import partial
import logging
import math
from multiprocessing import Queue
import os
import queue
from statistics import stdev
import struct
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import numpy as np
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import get_formatted_stack_trace
from stdlib_utils import put_log_message_into_queue
from stdlib_utils import resource_path
from xem_wrapper import check_header
from xem_wrapper import convert_sample_idx
from xem_wrapper import convert_wire_value
from xem_wrapper import DATA_FRAME_SIZE_WORDS
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN
from xem_wrapper import FrontPanelBase
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import OpalKellyNoDeviceFoundError
from xem_wrapper import open_board

from .constants import ADC_GAIN_DESCRIPTION_TAG
from .constants import BARCODE_CONFIRM_CLEAR_WAIT_SECONDS
from .constants import BARCODE_GET_SCAN_WAIT_SECONDS
from .constants import CALIBRATED_STATE
from .constants import CALIBRATION_NEEDED_STATE
from .constants import CLEARED_BARCODE_VALUE
from .constants import DATA_FRAME_PERIOD
from .constants import INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
from .constants import NO_PLATE_DETECTED_BARCODE_VALUE
from .constants import REF_INDEX_TO_24_WELL_INDEX
from .constants import TIMESTEP_CONVERSION_FACTOR
from .constants import VALID_SCRIPTING_COMMANDS
from .exceptions import BarcodeNotClearedError
from .exceptions import BarcodeScannerNotRespondingError
from .exceptions import FirmwareFileNameDoesNotMatchWireOutVersionError
from .exceptions import FirstManagedReadLessThanOneRoundRobinError
from .exceptions import InstrumentCommIncorrectHeaderError
from .exceptions import InvalidDataFramePeriodError
from .exceptions import InvalidScriptCommandError
from .exceptions import MismatchedScriptTypeError
from .exceptions import ScriptDoesNotContainEndCommandError
from .exceptions import UnrecognizedCommandToInstrumentError
from .exceptions import UnrecognizedCommTypeFromMainToInstrumentError
from .exceptions import UnrecognizedDataFrameFormatNameError
from .exceptions import UnrecognizedDebugConsoleCommandError
from .exceptions import UnrecognizedMantarrayNamingCommandError
from .fifo_simulator import RunningFIFOSimulator
from .instrument_comm import InstrumentCommProcess
from .mantarray_front_panel import MantarrayFrontPanel
from .utils import _trim_barcode
from .utils import check_barcode_is_valid

if 6 < 9:  # pragma: no cover # protect this from zimports deleting the pylint disable statement
    from .data_parsing_cy import (  # pylint: disable=import-error # Tanner (8/25/20): unsure why pylint is unable to recognize cython import...
        parse_sensor_bytes,
    )


def _get_formatted_utc_now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")


def _get_dur_since_barcode_clear(clear_time: float) -> float:
    return time.perf_counter() - clear_time


def execute_debug_console_command(
    front_panel: FrontPanelBase, communication: Dict[str, Any]
) -> Union[None, int, str, Dict[str, Any], List[str]]:
    """Execute a command from the debug console."""
    callable_to_execute = None
    command = communication["command"]
    if command == "initialize_board":
        bit_file_name = communication["bit_file_name"]
        allow_board_reinitialization = communication.get("allow_board_reinitialization", False)
        callable_to_execute = functools.partial(
            front_panel.initialize_board,
            bit_file_name=bit_file_name,
            allow_board_reinitialization=allow_board_reinitialization,
        )
    elif command == "read_wire_out":
        callable_to_execute = _create_read_wire_out_callable(front_panel, communication)
    elif command == "read_from_fifo":
        full_read = front_panel.read_from_fifo()
        total_num_words = len(full_read) // 4
        unformatted_words = struct.unpack(f"<{total_num_words}L", full_read)
        num_words_to_log = min(total_num_words, communication["num_words_to_log"])
        formatted_read = list()
        for i in range(num_words_to_log):
            formatted_read.append(hex(unformatted_words[i]))
        return formatted_read
    elif command == "get_serial_number":
        callable_to_execute = functools.partial(front_panel.get_serial_number)
    elif command == "get_device_id":
        callable_to_execute = functools.partial(front_panel.get_device_id)
    elif command == "set_device_id":
        new_id = communication["new_id"]
        callable_to_execute = functools.partial(front_panel.set_device_id, new_id)
    elif command == "set_wire_in":
        callable_to_execute = _create_set_wire_in_callable(front_panel, communication)
    elif command == "activate_trigger_in":
        callable_to_execute = _create_activate_trigger_in_callable(front_panel, communication)
    elif command == "get_num_words_fifo":
        callable_to_execute = functools.partial(front_panel.get_num_words_fifo)
    elif command == "get_status":
        status_dict = {}
        status_dict[
            "is_spi_running"
        ] = (
            front_panel._is_spi_running  # pylint: disable=protected-access # adding method to access this instance attribute specifically rather than the value from the XEM.
        )
        status_dict["is_board_initialized"] = front_panel.is_board_initialized()
        status_dict["bit_file_name"] = front_panel.get_bit_file_name()
        return status_dict
    elif command == "is_spi_running":
        callable_to_execute = functools.partial(front_panel.is_spi_running)
    elif command == "start_acquisition":
        callable_to_execute = functools.partial(front_panel.start_acquisition)
    elif command == "stop_acquisition":
        callable_to_execute = functools.partial(front_panel.stop_acquisition)
    elif command == "comm_delay":
        return _comm_delay(communication)
    if callable_to_execute is None:
        raise UnrecognizedDebugConsoleCommandError(communication)
    try:
        response: Union[None, int, str, Dict[str, Any], List[str]] = callable_to_execute()
    except Exception as e:  # pylint: disable=broad-except # The deliberate goal of this is to catch everything and return the error
        suppress_error = communication.get("suppress_error", False)
        if suppress_error:
            stack_trace = get_formatted_stack_trace(e)
            return f"{e}\n{stack_trace}"
        raise e
    return response


def _create_set_wire_in_callable(front_panel: FrontPanelBase, communication: Dict[str, Any]) -> partial[None]:
    """Create a callable for set_wire_in."""
    ep_addr = communication["ep_addr"]
    value = communication["value"]
    mask = communication["mask"]
    return functools.partial(front_panel.set_wire_in, ep_addr, value, mask)


def _create_read_wire_out_callable(
    front_panel: FrontPanelBase, communication: Dict[str, Any]
) -> partial[None]:
    """Create a callable for read_wire_out."""
    ep_addr = communication["ep_addr"]
    return functools.partial(front_panel.read_wire_out, ep_addr)


def _create_activate_trigger_in_callable(
    front_panel: FrontPanelBase, communication: Dict[str, Any]
) -> partial[None]:
    """Create a callable for activate_trigger_in."""
    ep_addr = communication["ep_addr"]
    bit = communication["bit"]
    return functools.partial(front_panel.activate_trigger_in, ep_addr, bit)


def _comm_delay(
    communication: Dict[str, Any],
) -> str:
    """Pause communications to XEM for given number of milliseconds."""
    num_milliseconds = communication["num_milliseconds"]
    sleep_val = num_milliseconds / 1000
    time.sleep(sleep_val)
    return f"Delayed for {num_milliseconds} milliseconds"


def parse_gain(value: int) -> int:
    """Return ADC gain from set_wire_in value."""
    gain_bits = value & 0x7
    gain_value: int = 2 ** gain_bits
    return gain_value


def parse_data_frame(data_bytes: bytearray, data_format_name: str) -> Dict[int, Any]:
    """Convert bytearray block from XEM buffer into formatted data.

    Args:
        data_bytes: a data block from the FIFO buffer
        data_format_name: a designation of how this is encoded so it can be parsed correctly
    Returns:
        A dictionary where the key is the channel index
    """
    if not check_header(data_bytes[:8]):
        raise InstrumentCommIncorrectHeaderError()

    formatted_data: Dict[int, Any] = dict()
    if data_format_name == "two_channels_32_bit__single_sample_index__with_reference":
        sample_index = convert_sample_idx(data_bytes[8:12])
        ints = struct.unpack("<4L", data_bytes[12:])
        formatted_data[0] = np.zeros((1, 3), dtype=np.int32)
        formatted_data[0][0] = [sample_index, ints[1], ints[0]]

        formatted_data[1] = np.zeros((1, 3), dtype=np.int32)
        formatted_data[1][0] = [sample_index, ints[3], ints[2]]
        return formatted_data
    if data_format_name == "six_channels_32_bit__single_sample_index":
        sample_index = convert_sample_idx(data_bytes[8:12]) * TIMESTEP_CONVERSION_FACTOR
        for byte_idx in range(6):
            # setup indices
            start_byte_idx = 12 + byte_idx * 4
            end_byte_idx = start_byte_idx + 4
            # add data
            formatted_data[byte_idx] = (
                sample_index,
                data_bytes[start_byte_idx:end_byte_idx],
            )
        return formatted_data

    raise UnrecognizedDataFrameFormatNameError(data_format_name)


def build_file_writer_objects(
    data_bytes: bytearray,
    data_format_name: str,
    logging_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ],
    logging_threshold: int,
) -> Dict[Any, Dict[str, Any]]:
    """Take raw data from the XEM and format into dicts for the FileWriter.

    Args:
        data_bytes: raw data coming from the XEM FIFO.
        data_format_name: a designation of how this is encoded so it can be parsed correctly
        logging_queue: a queue to put log messages into
        logging_threshold: the threshold that determines whether messages get put in the queue or not

    Returns:
        A list of dicts to be put into the incoming data queue of the FileWriter
    """
    # break up data into frames
    data_frames = []
    msg = f"Timestamp: {_get_formatted_utc_now()} Beginning to parse FIFO bytes"
    put_log_message_into_queue(logging.DEBUG, msg, logging_queue, logging_threshold)

    for start_idx in range(0, len(data_bytes), DATA_FRAME_SIZE_WORDS * 4):
        end_idx = start_idx + (DATA_FRAME_SIZE_WORDS * 4)
        data_frames.append(data_bytes[start_idx:end_idx])

    msg = f"Timestamp: {_get_formatted_utc_now()} {len(data_frames)} data frames found."
    put_log_message_into_queue(logging.DEBUG, msg, logging_queue, logging_threshold)

    if data_format_name == "six_channels_32_bit__single_sample_index":
        # initialize dictionary of channels
        channel_dicts: Dict[Any, Dict[str, Any]] = dict()
        # add construct sensors to dict
        for ch_num in range(24):
            channel_dicts[ch_num] = {
                "is_reference_sensor": False,
                "well_index": ch_num,
                "data": None,
            }
        # add reference sensors to dict
        for ref_num in range(6):
            channel_dicts[f"ref{ref_num}"] = {
                "is_reference_sensor": True,
                "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[ref_num],
                "data": None,
            }
        # begin parsing data frame by frame
        first_frame_sample_idx: int
        for frame_idx, frame in enumerate(data_frames):
            formatted_data = parse_data_frame(frame, data_format_name)
            msg = (
                f"Timestamp: {_get_formatted_utc_now()} Parsed data frame index {frame_idx}: {formatted_data}"
            )
            if frame_idx == 0:
                first_frame_sample_idx = formatted_data[0][0]
            elif frame_idx == 1:
                _check_data_frame_period(
                    first_frame_sample_idx,
                    formatted_data[0][0],
                    logging_queue,
                    logging_threshold,
                )
            for ch_num in range(6):
                sample_index = formatted_data[ch_num][0]
                # parse sensor_data
                sensor_data_bytes = formatted_data[ch_num][1]
                is_reference_sensor, index, sensor_value = parse_sensor_bytes(sensor_data_bytes)
                # add data to correct channel or reference key in dict
                key = f"ref{index}" if is_reference_sensor else index
                if channel_dicts[key]["data"] is not None:
                    channel_dicts[key]["data"][0].append(sample_index)
                    channel_dicts[key]["data"][1].append(sensor_value)
                else:
                    channel_dicts[key]["data"] = [[sample_index], [sensor_value]]
        for key in channel_dicts:
            # Tanner (8/26/20): concatenating arrays is slow, so using faster append method of python lists until all data is added then converting to array.
            channel_dicts[key]["data"] = np.array(channel_dicts[key]["data"], dtype=np.int32)
        return channel_dicts

    raise UnrecognizedDataFrameFormatNameError(data_format_name)


def _check_data_frame_period(
    first_frame_sample_idx: int,
    second_frame_sample_idx: int,
    logging_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ],
    logging_threshold: int,
) -> None:
    period = second_frame_sample_idx - first_frame_sample_idx
    if period != DATA_FRAME_PERIOD:
        msg = f"Detected period between first two data frames of FIFO read: {period} does not matched expected value: {DATA_FRAME_PERIOD}. Actual time indices: {hex(first_frame_sample_idx)}, {hex(second_frame_sample_idx)}"
        if logging_threshold >= logging.INFO:
            raise InvalidDataFramePeriodError(msg)
        put_log_message_into_queue(
            logging.DEBUG,
            msg,
            logging_queue,
            logging_threshold,
        )


def parse_scripting_log_line(log_line: str) -> Dict[str, Any]:
    """Parse a log line for a XEM command and arguments."""
    start_index = log_line.find("mGET")
    end_index = log_line.find("HTTP") - 1
    route = log_line[start_index:end_index]
    split_route_str = route.split("/")
    route_command = split_route_str[-1]

    command_args_pair = route_command.split("?")
    command = command_args_pair[0]
    if command not in VALID_SCRIPTING_COMMANDS:
        raise InvalidScriptCommandError(f"Invalid scripting command: '{command}'")
    command_dict: Dict[str, Any] = {"command": command}
    arg_value_pairs = command_args_pair[1]

    args = list()
    values = list()
    for pair in arg_value_pairs.split("&"):
        items = pair.split("=")
        args.append(items[0])
        values.append(items[1])

    num_args = len(args)
    for i in range(num_args):
        arg = args[i]
        value = values[i] if arg in ("script_type", "description") else int(values[i], 0)
        command_dict[arg] = value

    return command_dict


def parse_scripting_log(script_type: str) -> Dict[str, Any]:
    """Parse a log to run to create a sequence of XEM commands."""
    file_name = f"xem_{script_type}.txt"
    relative_path = os.path.join("src", "xem_scripts", file_name)
    absolute_path = os.path.normcase(os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir))
    file_path = resource_path(relative_path, base_path=absolute_path)

    command_list: List[Dict[str, Any]] = list()
    script_dict = {"script_type": script_type, "command_list": command_list}
    is_parsing = False
    with open(file_path, "r") as log_file:
        is_script_done = False
        for line in log_file:
            if is_parsing:
                if "end_hardware_script" in line:
                    is_script_done = True
                    break
                if "mGET" in line:
                    command_list.append(parse_scripting_log_line(line))
            elif "begin_hardware_script" in line:
                script_details = parse_scripting_log_line(line)
                if script_details["script_type"] != script_type:
                    log_script_type = script_details["script_type"]
                    raise MismatchedScriptTypeError(
                        f"Script type in log: '{log_script_type}' does not match file name: '{script_type}'"
                    )
                script_dict["version"] = script_details["version"]
                is_parsing = True
        if not is_script_done:
            raise ScriptDoesNotContainEndCommandError()
    return script_dict


def check_mantarray_serial_number(serial_number: str) -> str:
    """Check that a Mantarray Serial Number is valid."""
    if len(serial_number) > 9:
        return "Serial Number exceeds max length"
    if len(serial_number) < 9:
        return "Serial Number does not reach min length"
    if serial_number[:2] != "M0":
        return f"Serial Number contains invalid header: '{serial_number[:2]}'"
    for char in serial_number[2:]:
        if not char.isnumeric():
            return f"Serial Number contains invalid character: '{char}'"
    if int(serial_number[2:4]) < 20:
        return f"Serial Number contains invalid year: '{serial_number[2:4]}'"
    if int(serial_number[4:7]) < 1 or int(serial_number[4:7]) > 366:
        return f"Serial Number contains invalid Julian date: '{serial_number[4:7]}'"
    return ""


# pylint: disable=too-many-instance-attributes
class OkCommunicationProcess(InstrumentCommProcess):
    """Process that controls communication with the OpalKelly Board(s).

    Args:
        board_queues: A tuple (the max number of board connections should be predefined, so not a mutable list) of tuples of 3 queues. The first queue is for input/communication from the main thread to this sub process, second queue is for communication from this process back to the main thread. Third queue is for streaming communication (largely of raw data) to the process that controls writing to disk.
        fatal_error_reporter: A queue that reports back any unhandled errors that have caused the process to stop.
        suppress_setup_communication_to_main: if set to true (often during unit testing), messages during the _setup_before_loop will not be put into the queue to communicate back to the main process
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._data_frame_format = "six_channels_32_bit__single_sample_index"
        self._time_of_last_fifo_read: List[Union[None, datetime.datetime]] = [None] * len(self._board_queues)
        self._timepoint_of_last_fifo_read: List[Union[None, float]] = [None] * len(self._board_queues)
        self._reads_since_last_logging: List[int] = [0] * len(self._board_queues)
        self._is_managed_acquisition_running = [False] * len(self._board_queues)
        self._is_first_managed_read = [False] * len(self._board_queues)
        self._fifo_read_durations: List[float] = list()
        self._fifo_read_lengths: List[int] = list()
        self._data_parsing_durations: List[float] = list()
        self._durations_between_acquisition: List[float] = list()
        self._barcode_scan_start_time: List[Optional[float]] = [
            None,
            None,
        ]
        self._is_barcode_cleared = [False, False]
        self._performance_logging_cycles = INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
        self._fifo_read_period = 1

    def create_connections_to_all_available_boards(self) -> None:
        """Create initial connections to boards.

        If a board is not present, a simulator will be put in.
        """
        num_connected_boards = self.determine_how_many_boards_are_connected()
        comm_to_main_queue = self._board_queues[0][1]
        for i in range(num_connected_boards):
            msg = {
                "communication_type": "board_connection_status_change",
                "board_index": i,
            }
            try:
                xem = open_board()
                front_panel_constructor = functools.partial(MantarrayFrontPanel, xem)
            except OpalKellyNoDeviceFoundError:
                front_panel_constructor = functools.partial(RunningFIFOSimulator, {})
                msg["message"] = "No board detected. Creating simulator."
            this_front_panel = front_panel_constructor()
            self.set_board_connection(i, this_front_panel)
            msg["is_connected"] = isinstance(this_front_panel, MantarrayFrontPanel)
            msg["timestamp"] = _get_formatted_utc_now()
            msg["xem_serial_number"] = this_front_panel.get_serial_number()
            device_id = this_front_panel.get_device_id()
            if not check_mantarray_serial_number(device_id[:9]):
                msg["mantarray_serial_number"] = device_id[:9]
                msg["mantarray_nickname"] = device_id[9:]
            else:
                msg["mantarray_serial_number"] = ""
                msg["mantarray_nickname"] = device_id
            comm_to_main_queue.put_nowait(msg)

    def _setup_before_loop(self) -> None:
        super()._setup_before_loop()
        msg = {
            "communication_type": "log",
            "message": f'OpalKelly Communication Process initiated at {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")}',
        }
        comm_to_main_queue = self._board_queues[0][1]
        if not self._suppress_setup_communication_to_main:
            comm_to_main_queue.put_nowait(msg)
        board_connections = self.get_board_connections_list()
        if isinstance(board_connections[0], FrontPanelSimulator):
            # If the board has already been set to be a simulator (i.e. by a unit test), then don't attempt to make a new connection.
            return
        self.create_connections_to_all_available_boards()

    def _teardown_after_loop(self) -> None:
        msg = f"OpalKelly Communication Process beginning teardown at {_get_formatted_utc_now()}"
        put_log_message_into_queue(
            logging.INFO,
            msg,
            self._board_queues[0][1],
            self.get_logging_level(),
        )
        if self._is_managed_acquisition_running[0]:
            msg = "Board acquisition still running. Stopping acquisition to complete teardown"
            put_log_message_into_queue(
                logging.INFO,
                msg,
                self._board_queues[0][1],
                self.get_logging_level(),
            )
            self._is_managed_acquisition_running[0] = False
            board_connections = self.get_board_connections_list()
            if board_connections[0] is None:
                raise NotImplementedError("Board should not be None while managed acquisition is running")
            board_connections[0].stop_acquisition()
        super()._teardown_after_loop()

    def _commands_for_each_run_iteration(self) -> None:
        self._process_next_communication_from_main()
        self._handle_barcode_scan()

        if self._is_managed_acquisition_running[0]:
            board_connections = self.get_board_connections_list()
            if board_connections[0] is None:
                raise NotImplementedError("Board should not be None while managed acquisition is running")
            now = datetime.datetime.utcnow()
            if self._time_of_last_fifo_read[0] is None:
                # Use now if no previous reads
                self._time_of_last_fifo_read[0] = now
                self._timepoint_of_last_fifo_read[0] = time.perf_counter()
            elif self._is_ready_to_read_from_fifo(now):
                if self._reads_since_last_logging[0] is None:
                    raise NotImplementedError(
                        "_reads_since_last_logging should always be an int value while managed acquisition is running"
                    )
                if self._timepoint_of_last_fifo_read[0] is None:
                    raise NotImplementedError(
                        "_timepoint_of_last_fifo_read should always be a float value while managed acquisition is running"
                    )
                self._dump_data_dicts_into_queue()
                self._reads_since_last_logging[0] += 1

                now_timepoint = time.perf_counter()
                duration_between_acquisition = now_timepoint - self._timepoint_of_last_fifo_read[0]
                self._durations_between_acquisition.append(duration_between_acquisition)

                if self._reads_since_last_logging[0] >= self._performance_logging_cycles:
                    self._handle_performance_logging()
                    self._reads_since_last_logging[0] = 0
                self._timepoint_of_last_fifo_read[0] = now_timepoint
                self._time_of_last_fifo_read[0] = now
        else:
            self._timepoint_of_last_fifo_read[0] = None
            self._time_of_last_fifo_read[0] = None

    def _is_ready_to_read_from_fifo(self, now: datetime.datetime) -> bool:
        if self._time_of_last_fifo_read[0] is None:
            raise NotImplementedError(
                "_reads_since_last_logging should always be an int value while managed acquisition is running"
            )
        return now - self._time_of_last_fifo_read[0] > datetime.timedelta(seconds=self._fifo_read_period)

    def _process_next_communication_from_main(self) -> None:
        """Process the next communication sent from the main process.

        Will just return if no communications in queue.
        """
        input_queue = self._board_queues[0][0]
        try:
            this_communication = input_queue.get_nowait()
        except queue.Empty:
            return

        communication_type = this_communication["communication_type"]

        if communication_type == "debug_console":
            self._handle_debug_console_comm(this_communication)
        elif communication_type == "boot_up_instrument":
            self._boot_up_instrument(this_communication)
        elif communication_type == "to_instrument":
            self._handle_to_instrument_comm(this_communication)
        elif communication_type == "xem_scripts":
            self._handle_xem_scripts_comm(this_communication)
        elif communication_type == "mantarray_naming":
            self._handle_mantarray_naming_comm(this_communication)
        elif this_communication["communication_type"] == "barcode_comm":
            board_idx = 0
            board = self.get_board_connections_list()[board_idx]
            if board is None:
                raise NotImplementedError("Board should not be None when communicating with barcode scanner")
            if not board.is_board_initialized():
                # Tanner (12/10/20): This is to handle --skip-mantarray-boot-up which will not automatically initialize the board
                self._send_barcode_to_main(board_idx, "", False)
            else:
                self._reset_barcode_values()
                self._barcode_scan_start_time[0] = time.perf_counter()
                board.clear_barcode_scanner()
        else:
            raise UnrecognizedCommTypeFromMainToInstrumentError(communication_type)
        if not input_queue.empty():
            self._process_can_be_soft_stopped = False

    def _handle_barcode_scan(self) -> None:
        if self._barcode_scan_start_time[0] is None:
            return
        board_idx = 0
        board = self.get_board_connections_list()[board_idx]
        if board is None:
            raise NotImplementedError("Board should not be None when communicating with barcode scanner")

        if isinstance(board, FrontPanelSimulator):
            barcode = board.get_barcode()
            self._send_barcode_to_main(board_idx, barcode, True)
            return

        scan_attempt = 0 if self._barcode_scan_start_time[1] is None else 1
        start_time = self._barcode_scan_start_time[scan_attempt]
        if start_time is None:  # Tanner (12/7/20): making mypy happy
            raise NotImplementedError(
                "the barcode_scan_start_time value should never be None past this point"
            )
        dur_since_barcode_clear = _get_dur_since_barcode_clear(start_time)
        if dur_since_barcode_clear >= BARCODE_GET_SCAN_WAIT_SECONDS:
            barcode = board.get_barcode()
            if barcode == CLEARED_BARCODE_VALUE:
                raise BarcodeScannerNotRespondingError()

            trimmed_barcode = _trim_barcode(barcode)
            if check_barcode_is_valid(trimmed_barcode):
                self._send_barcode_to_main(board_idx, trimmed_barcode, True)
                return
            if scan_attempt == 1:
                if barcode == NO_PLATE_DETECTED_BARCODE_VALUE:
                    barcode = ""
                self._send_barcode_to_main(board_idx, barcode, False)
                return

            msg = (
                "No plate detected, retrying scan"
                if barcode == NO_PLATE_DETECTED_BARCODE_VALUE
                else f"Invalid barcode detected: {barcode}, retrying scan"
            )
            put_log_message_into_queue(
                logging.INFO,
                msg,
                self._board_queues[0][1],
                self.get_logging_level(),
            )
            board.clear_barcode_scanner()
            self._barcode_scan_start_time[1] = time.perf_counter()
        elif (
            dur_since_barcode_clear >= BARCODE_CONFIRM_CLEAR_WAIT_SECONDS
            and not self._is_barcode_cleared[scan_attempt]
        ):
            barcode = board.get_barcode()
            if barcode != CLEARED_BARCODE_VALUE:
                raise BarcodeNotClearedError(barcode)
            self._is_barcode_cleared[scan_attempt] = True
            board.start_barcode_scan()

    def _send_barcode_to_main(self, board_idx: int, barcode: str, is_valid: bool) -> None:
        comm_to_main_queue = self._board_queues[0][1]
        barcode_comm_dict: Dict[str, Union[str, bool, int]] = {
            "communication_type": "barcode_comm",
            "board_idx": board_idx,
            "barcode": barcode,
        }
        if barcode:
            barcode_comm_dict["valid"] = is_valid
        comm_to_main_queue.put_nowait(barcode_comm_dict)
        self._reset_barcode_values()

    def _reset_barcode_values(self) -> None:
        self._barcode_scan_start_time[0] = None
        self._barcode_scan_start_time[1] = None
        self._is_barcode_cleared[0] = False
        self._is_barcode_cleared[1] = False

    def _handle_debug_console_comm(self, this_communication: Dict[str, Any]) -> None:
        response_queue = self._board_queues[0][1]
        front_panel = self.get_board_connections_list()[0]
        response = execute_debug_console_command(front_panel, this_communication)
        this_communication["response"] = response
        if isinstance(response, int) and not isinstance(response, bool):
            # bool is a subclass of int so we must make sure we check for them
            this_communication["hex_converted_response"] = hex(response)
        response_queue.put_nowait(this_communication)

    def _boot_up_instrument(self, this_communication: Dict[str, Any]) -> None:
        board = self.get_board_connections_list()[0]
        if board is None:
            raise NotImplementedError("Board should not be None when booting up instrument")
        execute_debug_console_command(board, this_communication)
        this_communication["board_index"] = 0

        main_firmware_version = board.get_firmware_version()
        if isinstance(board, MantarrayFrontPanel):
            bit_file_name = this_communication["bit_file_name"]
            # Tanner (7/27/20): it is assumed that only paths to bit files with valid names will passed into this function. If a messy error occurs here, check that the name of bit file is properly formatted (mantarray_#_#_#.bit) and that the path exists
            version_in_file_name = (
                os.path.splitext(os.path.split(bit_file_name)[1])[0].split("_", 1)[1].replace("_", ".")
            )
            if version_in_file_name != main_firmware_version:
                raise FirmwareFileNameDoesNotMatchWireOutVersionError(
                    f"File name: {bit_file_name}, Version from wire_out value: {main_firmware_version}"
                )
        this_communication["main_firmware_version"] = main_firmware_version
        this_communication["sleep_firmware_version"] = "0.0.0"

        response_queue = self._board_queues[0][1]
        response_queue.put_nowait(this_communication)

    def _handle_to_instrument_comm(self, this_communication: Dict[str, Any]) -> None:
        response_queue = self._board_queues[0][1]
        board = self.get_board_connections_list()[0]
        if board is None:
            raise NotImplementedError("Board should not be None when starting/stopping managed acquisition")
        if this_communication["command"] == "start_managed_acquisition":
            self._is_managed_acquisition_running[0] = True
            self._is_first_managed_read[0] = True
            board.start_acquisition()
            this_communication["timestamp"] = datetime.datetime.utcnow()
        elif this_communication["command"] == "stop_managed_acquisition":
            self._is_managed_acquisition_running[0] = False
            board.stop_acquisition()
        else:
            raise UnrecognizedCommandToInstrumentError(this_communication["command"])
        response_queue.put_nowait(this_communication)

    def _handle_xem_scripts_comm(self, this_communication: Dict[str, Any]) -> None:
        response_queue = self._board_queues[0][1]
        front_panel = self.get_board_connections_list()[0]
        script_type = this_communication["script_type"]
        script_dict = parse_scripting_log(script_type)

        version = script_dict["version"]
        this_communication["response"] = f"Running {script_type} script v{version}..."
        response_queue.put_nowait(this_communication)

        gain_value = None
        for command_dict in script_dict["command_list"]:
            command = command_dict["command"]
            callable_to_execute = None
            if command == "set_wire_in":
                callable_to_execute = _create_set_wire_in_callable(front_panel, command_dict)
                description = command_dict.get("description", "")
                if ADC_GAIN_DESCRIPTION_TAG in description and gain_value is None:
                    gain_value = parse_gain(command_dict["value"])
            elif command == "read_wire_out":
                callable_to_execute = _create_read_wire_out_callable(front_panel, command_dict)
            elif command == "activate_trigger_in":
                callable_to_execute = _create_activate_trigger_in_callable(front_panel, command_dict)

            if command == "comm_delay":
                comm_delay_command_response = _comm_delay(command_dict)
                comm_delay_response = {
                    "communication_type": this_communication["communication_type"],
                    "script_type": this_communication["script_type"],
                    "response": comm_delay_command_response,
                }
                response_queue.put_nowait(comm_delay_response)
            elif callable_to_execute is not None:
                script_response: Optional[int] = callable_to_execute()
                if script_response is not None:
                    # read_wire_out is the only xem command with a returned value
                    converted_response = convert_wire_value(script_response)
                    wire_out_response = {
                        "communication_type": this_communication["communication_type"],
                        "script_type": this_communication["script_type"],
                        "wire_out_addr": command_dict["ep_addr"],
                        "wire_out_value": converted_response,
                    }
                    description = command_dict.get("description", None)
                    if description is not None:
                        wire_out_response["description"] = description
                    response_queue.put_nowait(wire_out_response)
            else:
                raise NotImplementedError("callable_to_execute should only be None if command == comm_delay")
        done_message: Dict[str, Union[str, int]] = {
            "communication_type": "xem_scripts",
            "response": f"'{script_type}' script complete.",
        }
        if script_type == "start_calibration":
            done_message["status_update"] = CALIBRATED_STATE
        elif script_type == "start_up":
            done_message["status_update"] = CALIBRATION_NEEDED_STATE
            if gain_value is None:
                raise NotImplementedError(
                    "gain_value must always be an integer after running start_up script"
                )
            done_message["adc_gain"] = gain_value
        response_queue.put_nowait(done_message)

    def _handle_mantarray_naming_comm(self, this_communication: Dict[str, Any]) -> None:
        response_queue = self._board_queues[0][1]
        board = self.get_board_connections_list()[0]
        if board is None:
            raise NotImplementedError("Board should not be None when setting a new nickname or serial number")
        if this_communication["command"] == "set_mantarray_nickname":
            nickname = this_communication["mantarray_nickname"]
            device_id = board.get_device_id()
            serial_number = device_id[:9]
            if not check_mantarray_serial_number(serial_number):
                board.set_device_id(f"{serial_number}{nickname}")
            else:
                board.set_device_id(nickname)
        elif this_communication["command"] == "set_mantarray_serial_number":
            serial_number = this_communication["mantarray_serial_number"]
            board.set_device_id(serial_number)
        else:
            raise UnrecognizedMantarrayNamingCommandError(this_communication["command"])
        response_queue.put_nowait(this_communication)

    def _dump_data_dicts_into_queue(self) -> None:
        """Pull data from the XEM FIFO, reformat, and push it to the queue."""
        board = self.get_board_connections_list()[0]
        if board is None:
            raise NotImplementedError("Board should not be None while managed acquisition is running")
        logging_threshold = self.get_logging_level()
        comm_to_main_queue = self._board_queues[0][1]

        num_words_in_fifo = board.get_num_words_fifo()
        msg = f"Timestamp: {_get_formatted_utc_now()} {num_words_in_fifo} words in the FIFO currently."
        put_log_message_into_queue(
            logging.DEBUG,
            msg,
            comm_to_main_queue,
            logging_threshold,
        )

        msg = f"Timestamp: {_get_formatted_utc_now()} About to read from FIFO"
        put_log_message_into_queue(
            logging.DEBUG,
            msg,
            comm_to_main_queue,
            logging_threshold,
        )

        read_start = time.perf_counter()
        raw_data = board.read_from_fifo()
        read_dur = time.perf_counter() - read_start
        self._fifo_read_durations.append(read_dur)
        self._fifo_read_lengths.append(len(raw_data))

        put_log_message_into_queue(
            logging.DEBUG,
            f"Timestamp: {_get_formatted_utc_now()} After reading from FIFO",
            comm_to_main_queue,
            logging_threshold,
        )

        put_log_message_into_queue(
            logging.DEBUG,
            f"Timestamp: {_get_formatted_utc_now()} Raw data pulled from FIFO was {len(raw_data)} bytes",
            comm_to_main_queue,
            logging_threshold,
        )

        if self._is_first_managed_read[0]:
            first_round_robin_len = DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN * 4
            if len(raw_data) < first_round_robin_len:
                e = FirstManagedReadLessThanOneRoundRobinError()
                self._log_fifo_read_and_error(logging.ERROR, raw_data, e)
                raise e

            first_round_robin_data = raw_data[:first_round_robin_len]
            raw_data = raw_data[first_round_robin_len:]
            self._is_first_managed_read[0] = False

            try:
                build_file_writer_objects(
                    first_round_robin_data,
                    self._data_frame_format,
                    comm_to_main_queue,
                    logging_threshold,
                )
            except UnrecognizedDataFrameFormatNameError as e:
                raise e
            except Exception as e:  # pylint: disable=broad-except # The deliberate goal of this is to catch everything and log the error
                self._log_fifo_read_and_error(logging.DEBUG, first_round_robin_data, e)

        try:
            data_parse_start = time.perf_counter()
            channel_dicts = build_file_writer_objects(
                raw_data,
                self._data_frame_format,
                comm_to_main_queue,
                logging_threshold,
            )
            data_parse_dur = time.perf_counter() - data_parse_start
            self._data_parsing_durations.append(data_parse_dur)
        except UnrecognizedDataFrameFormatNameError as e:
            raise e
        except Exception as e:  # pylint: disable=broad-except # The deliberate goal of this is to catch everything and log the error
            self._log_fifo_read_and_error(logging.ERROR, raw_data, e)

            rounded_num_words = math.ceil(len(raw_data) / 4)
            unformatted_words = struct.unpack(f"<{rounded_num_words}L", raw_data)
            formatted_read = list()
            for i in range(rounded_num_words):
                formatted_read.append(hex(unformatted_words[i]))
            put_log_message_into_queue(
                logging.ERROR,
                f"Converted words: {formatted_read}",
                comm_to_main_queue,
                logging_threshold,
            )

            raise e

        for data in channel_dicts.values():
            self._board_queues[0][2].put_nowait(data)

    def _log_fifo_read_and_error(self, logging_level: int, fifo_read: bytearray, error: Exception) -> None:
        stack_trace = get_formatted_stack_trace(error)
        put_log_message_into_queue(
            logging_level,
            f"Timestamp: {_get_formatted_utc_now()} Raw data pulled from FIFO was {len(fifo_read)} bytes: {fifo_read}",
            self._board_queues[0][1],
            self.get_logging_level(),
        )

        put_log_message_into_queue(
            logging_level,
            f"{error}\n{stack_trace}",
            self._board_queues[0][1],
            self.get_logging_level(),
        )

    def _handle_performance_logging(self) -> None:
        performance_metrics: Dict[str, Any] = {
            "communication_type": "performance_metrics",
        }
        okc_measurements: List[
            Union[int, float]
        ]  # Tanner (5/28/20): This type annotation and the 'ignore' on the following line are necessary for mypy to not incorrectly type this variable
        for name, okc_measurements in (  # type: ignore
            (
                "fifo_read_num_bytes",
                self._fifo_read_lengths,
            ),
            (
                "fifo_read_duration",
                self._fifo_read_durations,
            ),
            (
                "data_parsing_duration",
                self._data_parsing_durations,
            ),
            (
                "duration_between_acquisition",
                self._durations_between_acquisition,
            ),
        ):
            performance_metrics[name] = {
                "max": max(okc_measurements),
                "min": min(okc_measurements),
                "stdev": round(stdev(okc_measurements), 6),
                "mean": round(sum(okc_measurements) / len(okc_measurements), 6),
            }

        tracker = self.reset_performance_tracker()
        performance_metrics["percent_use"] = tracker["percent_use"]
        performance_metrics["longest_iterations"] = sorted(tracker["longest_iterations"])
        if len(self._percent_use_values) > 1:
            performance_metrics["percent_use_metrics"] = self.get_percent_use_metrics()
        put_log_message_into_queue(
            logging.INFO,
            performance_metrics,
            self._board_queues[0][1],
            self.get_logging_level(),
        )
