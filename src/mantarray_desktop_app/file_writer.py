# -*- coding: utf-8 -*-
"""Controlling communication with the OpalKelly FPGA Boards."""
from __future__ import annotations

from collections import deque
import datetime
import json
import logging
from multiprocessing import Queue
import os
import queue
from statistics import stdev
import time
from typing import Any
from typing import Deque
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from uuid import UUID

import h5py
from labware_domain_models import LabwareDefinition
from mantarray_file_manager import ADC_REF_OFFSET_UUID
from mantarray_file_manager import ADC_TISSUE_OFFSET_UUID
from mantarray_file_manager import IS_FILE_ORIGINAL_UNTRIMMED_UUID
from mantarray_file_manager import MantarrayH5FileCreator
from mantarray_file_manager import METADATA_UUID_DESCRIPTIONS
from mantarray_file_manager import ORIGINAL_FILE_VERSION_UUID
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import REF_SAMPLING_PERIOD_UUID
from mantarray_file_manager import REFERENCE_SENSOR_READINGS
from mantarray_file_manager import TISSUE_SAMPLING_PERIOD_UUID
from mantarray_file_manager import TISSUE_SENSOR_READINGS
from mantarray_file_manager import TOTAL_WELL_COUNT_UUID
from mantarray_file_manager import TRIMMED_TIME_FROM_ORIGINAL_END_UUID
from mantarray_file_manager import TRIMMED_TIME_FROM_ORIGINAL_START_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_FIRST_REF_DATA_POINT_UUID
from mantarray_file_manager import UTC_FIRST_TISSUE_DATA_POINT_UUID
from mantarray_file_manager import WELL_COLUMN_UUID
from mantarray_file_manager import WELL_INDEX_UUID
from mantarray_file_manager import WELL_NAME_UUID
from mantarray_file_manager import WELL_ROW_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
from nptyping import NDArray
from stdlib_utils import compute_crc32_and_write_to_file_head
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import put_log_message_into_queue

from .constants import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from .constants import CURRENT_HDF5_FILE_FORMAT_VERSION
from .constants import FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS
from .constants import FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
from .constants import MICROSECONDS_PER_CENTIMILLISECOND
from .constants import REFERENCE_SENSOR_SAMPLING_PERIOD
from .constants import ROUND_ROBIN_PERIOD
from .exceptions import InvalidDataTypeFromOkCommError
from .exceptions import UnrecognizedCommandFromMainToFileWriterError

GENERIC_24_WELL_DEFINITION = LabwareDefinition(row_count=4, column_count=6)


def _get_formatted_utc_now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")


def get_tissue_dataset_from_file(
    the_file: h5py.File,
) -> h5py.Dataset:
    """Return the dataset for tissue sensor data from the H5 file object."""
    return the_file[TISSUE_SENSOR_READINGS]


def get_reference_dataset_from_file(
    the_file: h5py.File,
) -> h5py.Dataset:
    """Return the dataset for reference sensor data from the H5 file object."""
    return the_file[REFERENCE_SENSOR_READINGS]


def get_data_slice_within_timepoints(
    time_value_arr: NDArray[(2, Any), int],
    min_timepoint: int,
    max_timepoint: Optional[int] = None,
) -> Tuple[NDArray[(2, Any), int], int, int]:
    """Get just the section of data that is relevant.

    It is assumed that at least some of this data will be relevant.

    Args:
        time_value_arr: a 2D array with first dimension being time and second being values
        min_timepoint: the minimum timepoint to consider data valid to be included in the output array
        max_timepoint: any time >= to this will not be included. If None, then constraint will be ignored

    Returns:
        A tuple of just the values array, the timepoint of the first data point that matched the value, and the timepoint of the last data point that matched the value
    """
    length_of_data = time_value_arr.shape[1]
    first_valid_index_in_packet: int
    try:
        first_valid_index_in_packet = next(
            i for i, time in enumerate(time_value_arr[0]) if time >= min_timepoint
        )
    except StopIteration as e:
        raise NotImplementedError(
            f"No timepoint >= the min timepoint of {min_timepoint} was found. All data passed to this function should contain at least one valid timepoint"
        ) from e
    last_valid_index_in_packet = length_of_data - 1
    if max_timepoint is not None:
        try:
            last_valid_index_in_packet = next(
                length_of_data - 1 - i
                for i, time in enumerate(
                    time_value_arr[0][first_valid_index_in_packet:][::-1]
                )
                if time <= max_timepoint
            )
        except StopIteration as e:
            raise NotImplementedError(
                f"No timepoint <= the max timepoint of {max_timepoint} was found. All data passed to this function should contain at least one valid timepoint"
            ) from e
    values = time_value_arr[1]
    index_to_slice_to = last_valid_index_in_packet + 1
    out_arr = values[first_valid_index_in_packet:index_to_slice_to]
    out_first_timepoint = time_value_arr[0, first_valid_index_in_packet]
    out_last_timepoint = time_value_arr[0, last_valid_index_in_packet]
    return out_arr, out_first_timepoint, out_last_timepoint


def _find_last_valid_data_index(
    latest_timepoint: int, latest_index: int, stop_recording_timestamp: int
) -> int:
    while latest_timepoint > stop_recording_timestamp:
        latest_index -= 1
        latest_timepoint -= ROUND_ROBIN_PERIOD
    return latest_index


def _drain_board_queues(
    board: Tuple[
        Queue[Any],  # pylint: disable=unsubscriptable-object
        Queue[Any],  # pylint: disable=unsubscriptable-object
    ],
) -> Dict[str, List[Any]]:
    board_dict = dict()
    board_dict["instrument_comm_to_file_writer"] = drain_queue(board[0])
    board_dict["file_writer_to_data_analyzer"] = drain_queue(board[1])
    return board_dict


# pylint: disable=too-many-instance-attributes
class FileWriterProcess(InfiniteProcess):
    """Process that writes data to disk.

    Args:
        board_queues: A tuple (the max number of board connections should be predefined, so not a mutable list) of tuples of 2 queues. The first queue is for incoming data for that board that should be saved to disk. The second queue is for outgoing data for that board that has been saved to disk.
        from_main_queue: a queue of communication from the main process
        to_main_queue: a queue to put general communication back to main (including file names of finished files into so the uploader can begin uploading)
        fatal_error_reporter: a queue to report fatal errors back to the main process

    Attributes:
        _open_files: Holding all files currently open and being written to. A tuple (for each board) holding a dict keyed by well index that contains the H5 file object
        _start_recording_timestamps: Each index for each board. Will be None if board is not actively recording to file. Otherwise a tuple of the timestamp for index 0 in the SPI, and an int of how many centimilliseconds later recording was requested to begin at
        _stop_recording_timestamps: Each index for each board. Will be None if board has not received request to stop recording. Otherwise an int of how many centimilliseconds after SPI index 0 the recording was requested to stop at
        _tissue_data_finalized_for_recording: Each index for each board. A dict where they key is the well index. When start recording begins, dict is cleared, and all active well indices for recording are inserted as False. They become True after a stop_recording has been initiated and all data up to the stop point has successfully been written to file.
    """

    def __init__(
        self,
        board_queues: Tuple[
            Tuple[
                Queue[Any],  # pylint: disable=unsubscriptable-object
                Queue[Any],  # pylint: disable=unsubscriptable-object
            ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ],
        from_main_queue: Queue[  # pylint: disable=unsubscriptable-object
            Dict[str, Any]
        ],
        to_main_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        fatal_error_reporter: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ],
        file_directory: str = "",
        logging_level: int = logging.INFO,
        beta_2_mode: bool = False,
    ):
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._board_queues = board_queues
        self._from_main_queue = from_main_queue
        self._to_main_queue = to_main_queue
        self._file_directory = file_directory
        self._open_files: Tuple[
            Dict[int, h5py._hl.files.File],
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ] = tuple([{}] * len(self._board_queues))
        self._data_packet_buffers: Tuple[
            Deque[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
            ...,  # noqa: W504 # flake8 doesn't understand the 3 dots for type definition
        ] = tuple(deque() for _ in range(len(self._board_queues)))
        self._latest_data_timepoints: Tuple[
            Dict[int, int],
            ...,  # noqa: W504 # flake8 doesn't understand the 3 dots for type definition
        ] = tuple(dict() for _ in range(len(self._board_queues)))
        self._is_recording = False
        self._start_recording_timestamps: List[
            Optional[Tuple[datetime.datetime, int]]
        ] = list([None] * len(self._board_queues))
        self._stop_recording_timestamps: List[Optional[int]] = list(
            [None] * len(self._board_queues)
        )
        self._tissue_data_finalized_for_recording: Tuple[Dict[int, bool], ...] = tuple(
            [dict()] * len(self._board_queues)
        )
        self._reference_data_finalized_for_recording: Tuple[
            Dict[int, bool],
            ...,  # noqa: W504 # flake8 doesn't understand the 3 dots for type definition
        ] = tuple([dict()] * len(self._board_queues))
        self._iterations_since_last_logging = 0
        self._num_recorded_points: List[int] = list()
        self._recording_durations: List[float] = list()
        self._beta_2_mode = beta_2_mode

    def get_recording_finalization_statuses(
        self,
    ) -> Tuple[Tuple[Dict[int, bool], ...], Tuple[Dict[int, bool], ...]]:
        return (
            self._tissue_data_finalized_for_recording,
            self._reference_data_finalized_for_recording,
        )

    def close_all_files(self) -> None:
        """Close all open H5 files.

        This should only be used in emergencies to preserve data. It is
        not the recommended way to finalize and close a file. Use
        _finalize_completed_files
        """
        for _, this_file in self._open_files[0].items():
            this_file.close()

    def get_file_directory(self) -> str:
        return self._file_directory

    def get_stop_recording_timestamps(self) -> List[Optional[int]]:
        return self._stop_recording_timestamps

    def get_file_latest_timepoint(self, well_idx: int) -> int:
        return self._latest_data_timepoints[0][well_idx]

    def is_recording(self) -> bool:
        return self._is_recording

    def _board_has_open_files(self, board_idx: int) -> bool:
        return len(self._open_files[board_idx].keys()) > 0

    def _is_finalizing_files_after_recording(self) -> bool:
        return self._board_has_open_files(0) and not self._is_recording

    def _teardown_after_loop(self) -> None:
        to_main_queue = self._to_main_queue
        msg = f"File Writer Process beginning teardown at {_get_formatted_utc_now()}"
        put_log_message_into_queue(
            logging.INFO,
            msg,
            to_main_queue,
            self.get_logging_level(),
        )
        if self._board_has_open_files(0):
            msg = "Data is still be written to file. Stopping recording and closing files to complete teardown"
            put_log_message_into_queue(
                logging.INFO,
                msg,
                to_main_queue,
                self.get_logging_level(),
            )
            self.close_all_files()
        super()._teardown_after_loop()

    def _commands_for_each_run_iteration(self) -> None:
        if not self._is_finalizing_files_after_recording():
            self._process_next_command_from_main()
        self._process_next_data_packet()
        self._update_data_packet_buffers()
        self._finalize_completed_files()

        self._iterations_since_last_logging += 1
        if (
            self._iterations_since_last_logging
            >= FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
        ):
            self._handle_performance_logging()
            self._iterations_since_last_logging = 0

    def _finalize_completed_files(self) -> None:
        """Finalize H5 files.

        Go through and see if any open files are ready to be closed.
        Close them, and communicate to main.

        It's possible that this could be optimized in the future by only being called when the finalization status of something has changed.
        """
        tissue_status, reference_status = self.get_recording_finalization_statuses()

        for this_well_idx in list(
            self._open_files[0].keys()
        ):  # make a copy of the keys since they may be deleted during the run
            # if this_well_idx in tissue_status[0]: # Tanner (7/22/20): This line was apparently always True. If problems start showing up later, likely due to this line being removed
            if tissue_status[0][this_well_idx] and reference_status[0][this_well_idx]:
                this_file = self._open_files[0][this_well_idx]
                # the file name cannot be accessed after the file has been closed
                this_filename = this_file.filename
                this_file.close()
                with open(this_filename, "rb+") as file_buffer:
                    compute_crc32_and_write_to_file_head(file_buffer)
                to_main_queue = self._to_main_queue
                to_main_queue.put_nowait(
                    {
                        "communication_type": "file_finalized",
                        "file_path": this_filename,
                    }
                )
                del self._open_files[0][this_well_idx]

    def _process_start_recording_command(self, communication: Dict[str, Any]) -> None:
        self._is_recording = True

        attrs_to_copy = communication["metadata_to_copy_onto_main_file_attributes"]
        barcode = attrs_to_copy[PLATE_BARCODE_UUID]
        sample_idx_zero_timestamp = attrs_to_copy[UTC_BEGINNING_DATA_ACQUISTION_UUID]
        self._start_recording_timestamps[0] = (
            sample_idx_zero_timestamp,
            communication["timepoint_to_begin_recording_at"],
        )
        timedelta_to_recording_start = datetime.timedelta(
            seconds=communication["timepoint_to_begin_recording_at"]
            / CENTIMILLISECONDS_PER_SECOND
        )

        recording_start_timestamp = (
            attrs_to_copy[UTC_BEGINNING_DATA_ACQUISTION_UUID]
            + timedelta_to_recording_start
        )
        recording_start_timestamp_str = (recording_start_timestamp).strftime(
            "%Y_%m_%d_%H%M%S"
        )
        sub_dir_name = f"{barcode}__{recording_start_timestamp_str}"

        file_folder_dir = os.path.join(
            os.path.abspath(self._file_directory), sub_dir_name
        )
        communication["abs_path_to_file_folder"] = file_folder_dir
        os.makedirs(file_folder_dir)

        tissue_status, reference_status = self.get_recording_finalization_statuses()
        tissue_status[0].clear()
        reference_status[0].clear()
        for this_well_idx in communication["active_well_indices"]:
            file_path = os.path.join(
                self._file_directory,
                sub_dir_name,
                f"{sub_dir_name}__{GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(this_well_idx)}.h5",
            )
            this_file = MantarrayH5FileCreator(
                file_path, file_format_version=CURRENT_HDF5_FILE_FORMAT_VERSION
            )
            self._open_files[0][this_well_idx] = this_file
            this_file.attrs[
                str(ORIGINAL_FILE_VERSION_UUID)
            ] = CURRENT_HDF5_FILE_FORMAT_VERSION
            this_file.attrs[
                str(WELL_NAME_UUID)
            ] = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(this_well_idx)
            (
                this_row,
                this_col,
            ) = GENERIC_24_WELL_DEFINITION.get_row_and_column_from_well_index(
                this_well_idx
            )
            this_file.attrs[str(WELL_ROW_UUID)] = this_row
            this_file.attrs[str(WELL_COLUMN_UUID)] = this_col
            this_file.attrs[str(WELL_INDEX_UUID)] = this_well_idx
            this_file.attrs[str(REF_SAMPLING_PERIOD_UUID)] = (
                REFERENCE_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
            )
            this_file.attrs[str(TISSUE_SAMPLING_PERIOD_UUID)] = (
                CONSTRUCT_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
            )
            this_file.attrs[str(TOTAL_WELL_COUNT_UUID)] = 24
            this_file.attrs[str(IS_FILE_ORIGINAL_UNTRIMMED_UUID)] = True
            this_file.attrs[str(TRIMMED_TIME_FROM_ORIGINAL_START_UUID)] = 0
            this_file.attrs[str(TRIMMED_TIME_FROM_ORIGINAL_END_UUID)] = 0

            for this_attr_name, this_attr_value in attrs_to_copy.items():
                if this_attr_name == "adc_offsets":
                    this_file.attrs[str(ADC_TISSUE_OFFSET_UUID)] = this_attr_value[
                        this_well_idx
                    ]["construct"]
                    this_file.attrs[str(ADC_REF_OFFSET_UUID)] = this_attr_value[
                        this_well_idx
                    ]["ref"]
                    continue
                if METADATA_UUID_DESCRIPTIONS[this_attr_name].startswith(
                    "UTC Timestamp"
                ):
                    this_attr_value = this_attr_value.strftime("%Y-%m-%d %H:%M:%S.%f")
                this_attr_name = str(this_attr_name)
                if isinstance(this_attr_value, UUID):
                    this_attr_value = str(this_attr_value)
                this_file.attrs[this_attr_name] = this_attr_value
            # Tanner (6/12/20): We must convert UUIDs to strings to allow them to be compatible with H5 and JSON
            this_file.attrs["Metadata UUID Descriptions"] = json.dumps(
                str(METADATA_UUID_DESCRIPTIONS)
            )

            this_file.create_dataset(
                REFERENCE_SENSOR_READINGS,
                (0,),
                maxshape=(100 * 3600 * 12,),
                dtype="int32",
                chunks=True,
            )
            this_file.create_dataset(
                TISSUE_SENSOR_READINGS,
                (0,),
                maxshape=(100 * 3600 * 12,),
                dtype="int32",
                chunks=True,
            )
            this_file.swmr_mode = True

            tissue_status[0][this_well_idx] = False
            reference_status[0][this_well_idx] = False

        self.get_stop_recording_timestamps()[0] = None
        data_packet_buffer = self._data_packet_buffers[0]
        for data_packet in data_packet_buffer:
            self._handle_recording_of_packet(data_packet)

    def _process_stop_recording_command(self, communication: Dict[str, Any]) -> None:
        self._is_recording = False

        stop_recording_timestamp = communication["timepoint_to_stop_recording_at"]
        self.get_stop_recording_timestamps()[0] = stop_recording_timestamp
        for this_well_idx in self._open_files[0].keys():
            this_file = self._open_files[0][this_well_idx]
            latest_timepoint = self.get_file_latest_timepoint(this_well_idx)
            tissue_dataset = get_tissue_dataset_from_file(this_file)
            ref_dataset = get_reference_dataset_from_file(this_file)
            for dataset in (tissue_dataset, ref_dataset):
                last_index_of_valid_data = _find_last_valid_data_index(
                    latest_timepoint,
                    dataset.shape[0] - 1,
                    stop_recording_timestamp,
                )
                index_to_slice_to = last_index_of_valid_data + 1
                new_data = dataset[:index_to_slice_to]
                dataset.resize((new_data.shape[0],))

    def _process_next_command_from_main(self) -> None:
        input_queue = self._from_main_queue
        try:
            communication = input_queue.get_nowait()
        except queue.Empty:
            return

        to_main = self._to_main_queue
        logging_threshold = self.get_logging_level()
        put_log_message_into_queue(
            logging.DEBUG,
            f"Timestamp: {_get_formatted_utc_now()} Received a command from Main: {communication}",
            to_main,
            logging_threshold,
        )

        command = communication["command"]
        if command == "start_recording":
            self._process_start_recording_command(communication)
            to_main.put_nowait(
                {
                    "communication_type": "command_receipt",
                    "command": "start_recording",
                    "timepoint_to_begin_recording_at": communication[
                        "timepoint_to_begin_recording_at"
                    ],
                    "file_folder": communication["abs_path_to_file_folder"],
                }
            )

        elif command == "stop_recording":
            self._process_stop_recording_command(communication)
            to_main.put_nowait(
                {
                    "communication_type": "command_receipt",
                    "command": "stop_recording",
                    "timepoint_to_stop_recording_at": communication[
                        "timepoint_to_stop_recording_at"
                    ],
                }
            )
        elif command == "stop_managed_acquisition":
            self._data_packet_buffers[0].clear()
            to_main.put_nowait(
                {
                    "communication_type": "command_receipt",
                    "command": "stop_managed_acquisition",
                }
            )
        elif command == "update_directory":
            self._file_directory = communication["new_directory"]
            to_main.put_nowait(
                {
                    "communication_type": "command_receipt",
                    "command": "update_directory",
                    "new_directory": communication["new_directory"],
                }
            )
        else:
            raise UnrecognizedCommandFromMainToFileWriterError(command)
        if not input_queue.empty():
            self._process_can_be_soft_stopped = False

    def _process_data_packet_for_open_file(self, data_packet: Dict[str, Any]) -> None:
        """Process a data packet for a file that is known to be open."""
        this_start_recording_timestamps = self._start_recording_timestamps[0]
        stop_recording_timestamp = self.get_stop_recording_timestamps()[0]
        if this_start_recording_timestamps is None:  # check needed for mypy to be happy
            raise NotImplementedError(
                "Something wrong in the code. This should never be none."
            )

        this_data = data_packet["data"]
        last_timepoint_in_data_packet = this_data[0, -1]
        first_timepoint_in_data_packet = this_data[0, 0]
        timepoint_to_start_recording_at = this_start_recording_timestamps[1]
        if last_timepoint_in_data_packet < timepoint_to_start_recording_at:
            return
        is_reference_sensor = data_packet["is_reference_sensor"]

        if stop_recording_timestamp is not None:

            if last_timepoint_in_data_packet >= stop_recording_timestamp:
                if is_reference_sensor:
                    well_indices = data_packet["reference_for_wells"]
                    for this_well_idx in well_indices:
                        if (
                            this_well_idx
                            in self._reference_data_finalized_for_recording[0]
                        ):
                            self._reference_data_finalized_for_recording[0][
                                this_well_idx
                            ] = True
                else:
                    this_well_idx = data_packet["well_index"]
                    self._tissue_data_finalized_for_recording[0][this_well_idx] = True

            if first_timepoint_in_data_packet >= stop_recording_timestamp:
                return

        this_well_idx = data_packet["well_index"]
        this_file = self._open_files[0][this_well_idx]

        if is_reference_sensor:
            this_dataset = get_reference_dataset_from_file(this_file)
            recording_timestamp_attr_name = str(UTC_FIRST_REF_DATA_POINT_UUID)
        else:
            this_dataset = get_tissue_dataset_from_file(this_file)
            recording_timestamp_attr_name = str(UTC_FIRST_TISSUE_DATA_POINT_UUID)

        (
            new_data,
            first_timepoint_of_new_data,
            last_timepoint_of_new_data,
        ) = get_data_slice_within_timepoints(
            this_data,
            timepoint_to_start_recording_at,
            max_timepoint=stop_recording_timestamp,
        )

        if this_dataset.shape == (0,):
            this_file.attrs[recording_timestamp_attr_name] = (
                this_start_recording_timestamps[0]
                + datetime.timedelta(
                    seconds=first_timepoint_of_new_data / CENTIMILLISECONDS_PER_SECOND
                )
            ).strftime("%Y-%m-%d %H:%M:%S.%f")

        previous_data_size = this_dataset.shape[0]
        this_dataset.resize((previous_data_size + new_data.shape[0],))

        this_dataset[previous_data_size:] = new_data

        self._latest_data_timepoints[0][this_well_idx] = last_timepoint_of_new_data

    def _process_next_data_packet(self) -> None:
        """Process the next incoming data packet for that board.

        If no data present, will just return.

        If multiple boards are implemented, a kwarg board_idx:int=0 can be added.
        """
        input_queue = self._board_queues[0][0]
        try:
            data_packet = input_queue.get_nowait()
        except queue.Empty:
            return

        to_main = self._to_main_queue

        logging_threshold = self.get_logging_level()

        put_log_message_into_queue(
            logging.DEBUG,
            f"Timestamp: {_get_formatted_utc_now()} Received a data packet from OpalKelly Controller: {data_packet}",
            to_main,
            logging_threshold,
        )

        if not isinstance(data_packet, dict):
            # (Eli 3/2/20) - we had a bug where an integer was being passed through the Queue and the default Python error was extremely unhelpful in debugging. So this explicit error was added.
            raise InvalidDataTypeFromOkCommError(
                f"The object received from OkComm was not a dictionary, it was a {data_packet.__class__} with the value: {data_packet}"
            )

        self._data_packet_buffers[0].append(data_packet)

        output_queue = self._board_queues[0][1]
        output_queue.put_nowait(data_packet)

        self._num_recorded_points.append(data_packet["data"].shape[1])
        start = time.perf_counter()
        self._handle_recording_of_packet(data_packet)
        recording_dur = time.perf_counter() - start
        self._recording_durations.append(recording_dur)

        if not input_queue.empty():
            self._process_can_be_soft_stopped = False

    def _handle_recording_of_packet(self, data_packet: Dict[str, Any]) -> None:
        is_reference_sensor = data_packet["is_reference_sensor"]
        if is_reference_sensor:
            well_indices_to_process = data_packet["reference_for_wells"]
        else:
            well_indices_to_process = set([data_packet["well_index"]])
        for this_well_idx in well_indices_to_process:
            data_packet["well_index"] = this_well_idx
            if this_well_idx in self._open_files[0]:
                self._process_data_packet_for_open_file(data_packet)

    def _update_data_packet_buffers(self) -> None:
        data_packet_buffer = self._data_packet_buffers[0]
        if not data_packet_buffer:
            return
        buffer_memory_size = (
            data_packet_buffer[-1]["data"][0, 0] - data_packet_buffer[0]["data"][0, 0]
        )
        if buffer_memory_size > FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS:
            data_packet_buffer.popleft()

    def _handle_performance_logging(self) -> None:
        performance_metrics: Dict[str, Any] = {
            "communication_type": "performance_metrics",
        }
        performance_tracker = self.reset_performance_tracker()
        performance_metrics["percent_use"] = performance_tracker["percent_use"]
        performance_metrics["longest_iterations"] = sorted(
            performance_tracker["longest_iterations"]
        )
        if len(self._percent_use_values) > 1:
            performance_metrics["percent_use_metrics"] = self.get_percent_use_metrics()
        if len(self._num_recorded_points) > 1 and len(self._recording_durations) > 1:
            fw_measurements: List[
                Union[int, float]
            ]  # Tanner (5/28/20): This type annotation and the 'ignore' on the following line are necessary for mypy to not incorrectly type this variable
            for name, fw_measurements in (  # type: ignore
                ("num_recorded_data_points_metrics", self._num_recorded_points),
                ("recording_duration_metrics", self._recording_durations),
            ):
                performance_metrics[name] = {
                    "max": max(fw_measurements),
                    "min": min(fw_measurements),
                    "stdev": round(stdev(fw_measurements), 6),
                    "mean": round(sum(fw_measurements) / len(fw_measurements), 6),
                }

        put_log_message_into_queue(
            logging.INFO,
            performance_metrics,
            self._to_main_queue,
            self.get_logging_level(),
        )

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items: Dict[str, Any] = dict()
        for i, board in enumerate(self._board_queues):
            queue_items[f"board_{i}"] = _drain_board_queues(board)
        queue_items["from_main_to_file_writer"] = drain_queue(self._from_main_queue)
        queue_items["from_file_writer_to_main"] = drain_queue(self._to_main_queue)
        return queue_items
