# -*- coding: utf-8 -*-
"""Recording data to file and uploading to cloud analysis."""
from __future__ import annotations

from collections import deque
import datetime
import glob
import json
import logging
from multiprocessing import Queue
from multiprocessing import queues as mpqueues
import os
import queue
import shutil
import tempfile
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
from mantarray_desktop_app.workers.file_uploader import FileUploader
from nptyping import NDArray
import numpy as np
from pulse3D.constants import ADC_REF_OFFSET_UUID
from pulse3D.constants import ADC_TISSUE_OFFSET_UUID
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from pulse3D.constants import IS_CALIBRATION_FILE_UUID
from pulse3D.constants import METADATA_UUID_DESCRIPTIONS
from pulse3D.constants import PLATE_BARCODE_UUID
from pulse3D.constants import PLATEMAP_LABEL_UUID
from pulse3D.constants import PLATEMAP_NAME_UUID
from pulse3D.constants import REF_SAMPLING_PERIOD_UUID
from pulse3D.constants import REFERENCE_SENSOR_READINGS
from pulse3D.constants import STIMULATION_PROTOCOL_UUID
from pulse3D.constants import STIMULATION_READINGS
from pulse3D.constants import TIME_INDICES
from pulse3D.constants import TIME_OFFSETS
from pulse3D.constants import TISSUE_SAMPLING_PERIOD_UUID
from pulse3D.constants import TISSUE_SENSOR_READINGS
from pulse3D.constants import TOTAL_WELL_COUNT_UUID
from pulse3D.constants import USER_DEFINED_METADATA_UUID
from pulse3D.constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from pulse3D.constants import UTC_FIRST_REF_DATA_POINT_UUID
from pulse3D.constants import UTC_FIRST_TISSUE_DATA_POINT_UUID
from pulse3D.constants import WELL_COLUMN_UUID
from pulse3D.constants import WELL_INDEX_UUID
from pulse3D.constants import WELL_NAME_UUID
from pulse3D.constants import WELL_ROW_UUID
from pulse3D.plate_recording import MantarrayH5FileCreator
from stdlib_utils import create_metrics_stats
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import put_log_message_into_queue

from ..constants import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from ..constants import CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
from ..constants import CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
from ..constants import FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS
from ..constants import FILE_WRITER_BUFFER_SIZE_MICROSECONDS
from ..constants import GENERIC_24_WELL_DEFINITION
from ..constants import MICRO_TO_BASE_CONVERSION
from ..constants import MICROSECONDS_PER_CENTIMILLISECOND
from ..constants import PERFOMANCE_LOGGING_PERIOD_SECS
from ..constants import REFERENCE_SENSOR_SAMPLING_PERIOD
from ..constants import ROUND_ROBIN_PERIOD
from ..constants import SERIAL_COMM_NUM_DATA_CHANNELS
from ..constants import SERIAL_COMM_NUM_SENSORS_PER_WELL
from ..constants import STIM_COMPLETE_SUBPROTOCOL_IDX
from ..exceptions import CalibrationFilesMissingError
from ..exceptions import InvalidStopRecordingTimepointError
from ..exceptions import UnrecognizedCommandFromMainToFileWriterError
from ..workers.worker_thread import ErrorCatchingThread


def _get_formatted_utc_now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")


def get_time_index_dataset_from_file(the_file: h5py.File) -> h5py.Dataset:
    """Return the dataset for time indices from the H5 file object."""
    return the_file[TIME_INDICES]


def get_time_offset_dataset_from_file(the_file: h5py.File) -> h5py.Dataset:
    """Return the dataset for time offsets from the H5 file object."""
    return the_file[TIME_OFFSETS]


def get_tissue_dataset_from_file(the_file: h5py.File) -> h5py.Dataset:
    """Return the dataset for tissue sensor data from the H5 file object."""
    return the_file[TISSUE_SENSOR_READINGS]


def get_reference_dataset_from_file(the_file: h5py.File) -> h5py.Dataset:
    """Return the dataset for reference sensor data from the H5 file object."""
    return the_file[REFERENCE_SENSOR_READINGS]


def get_stimulation_dataset_from_file(the_file: h5py.File) -> h5py.Dataset:
    return the_file[STIMULATION_READINGS]


def get_data_slice_within_timepoints(
    time_value_arr: NDArray[(2, Any), int], min_timepoint: int, max_timepoint: Optional[int] = None
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
    first_valid_index_in_packet, last_valid_index_in_packet = _find_bounds(
        time_value_arr[0], min_timepoint, max_timepoint
    )
    values = time_value_arr[1]
    index_to_slice_to = last_valid_index_in_packet + 1
    out_arr = values[first_valid_index_in_packet:index_to_slice_to]
    out_first_timepoint = time_value_arr[0, first_valid_index_in_packet]
    out_last_timepoint = time_value_arr[0, last_valid_index_in_packet]
    return out_arr, out_first_timepoint, out_last_timepoint


def _find_bounds(
    time_arr: NDArray[(1, Any), int], min_timepoint: int, max_timepoint: Optional[int] = None
) -> Tuple[int, int]:
    length_of_data = time_arr.shape[0]
    last_valid_index_in_packet = length_of_data - 1
    """Return a tuple of the first and last valid indices."""
    if time_arr[-1] == min_timepoint:
        return -1, last_valid_index_in_packet

    if time_arr[0] == min_timepoint:
        first_valid_index_in_packet = 0
    else:
        try:
            first_valid_index_in_packet = next(i for i, time in enumerate(time_arr) if time > min_timepoint)
        except StopIteration as e:
            raise NotImplementedError(
                f"No timepoint >= the min timepoint of {min_timepoint} was found. All data passed to this function should contain at least one valid timepoint"
            ) from e
        first_valid_index_in_packet = max(0, first_valid_index_in_packet - 1)

    if max_timepoint is not None:
        try:
            last_valid_index_in_packet = next(
                length_of_data - 1 - i
                for i, time in enumerate(time_arr[first_valid_index_in_packet:][::-1])
                if time <= max_timepoint
            )
        except StopIteration as e:
            raise NotImplementedError(
                f"No timepoint <= the max timepoint of {max_timepoint} was found. All data passed to this function should contain at least one valid timepoint"
            ) from e
    return first_valid_index_in_packet, last_valid_index_in_packet


def _find_last_valid_data_index(
    latest_timepoint: int, latest_index: int, stop_recording_timestamp: int
) -> int:
    while latest_timepoint > stop_recording_timestamp:
        latest_index -= 1
        latest_timepoint -= ROUND_ROBIN_PERIOD
    return latest_index


def _find_earliest_valid_stim_status_index(
    time_index_buffer: List[int], earliest_magnetometer_time_idx: int
) -> int:
    if not time_index_buffer:
        raise NotImplementedError("time_index_buffer should never be empty here")

    idx = len(time_index_buffer) - 1
    while idx > 0 and time_index_buffer[idx] > earliest_magnetometer_time_idx:
        idx -= 1
    return idx


def _drain_board_queues(board: Tuple[Queue[Any], Queue[Any]]) -> Dict[str, List[Any]]:
    board_dict = dict()
    board_dict["instrument_comm_to_file_writer"] = drain_queue(board[0])
    board_dict["file_writer_to_data_analyzer"] = drain_queue(board[1])
    return board_dict


class FileWriterProcess(InfiniteProcess):
    """Process that writes data to disk and uploads H5 files to the cloud.

    Args:
        board_queues: A tuple (the max number of board connections should be predefined, so not a mutable list) of tuples of 2 queues. The first queue is for incoming data for that board that should be saved to disk. The second queue is for outgoing data for that board that has been saved to disk.
        from_main_queue: A queue of communication from the main process.
        to_main_queue: A queue to put general communication back to main (including file names of finished files into so the uploader can begin uploading).
        fatal_error_reporter: A queue to report fatal errors back to the main process.
        file_directory: A static directory for recordings created in Electron.

    Attributes:
        _open_files: Holding all files currently open and being written to. A tuple (for each board) holding a dict keyed by well index that contains the H5 file object
        _start_recording_timestamps: Each index for each board. Will be None if board is not actively recording to file. Otherwise a tuple of the timestamp for index 0 in the SPI, and an int of how many centimilliseconds later recording was requested to begin at
        _stop_recording_timestamps: Each index for each board. Will be None if board has not received request to stop recording. Otherwise an int of how many centimilliseconds after SPI index 0 the recording was requested to stop at
        _tissue_data_finalized_for_recording: Each index for each board. A dict where they key is the well index. When start recording begins, dict is cleared, and all active well indices for recording are inserted as False. They become True after a stop_recording has been initiated and all data up to the stop point has successfully been written to file.
        _reference_data_finalized_for_recording: Each index for each board. A dict where they key is the well index. When start recording begins, dict is cleared, and all active well indices for recording are inserted as False. They become True after a stop_recording has been initiated and all data up to the stop point has successfully been written to file.
        _end_of_data_stream_reached: A Boolean for each board board queue on whether data is still getting streamed or not, set to False.
        _user_settings: A dictionary of the current user credentials, auto upload and auto delete settings that get stored from the update user settings command from the main queue.
        _sub_dir_name: The directory where the H5 files are written to inside the recording directory.
        _upload_threads_container: A list that contains active upload threads that get looped through every iteration.
    """

    def __init__(
        self,
        board_queues: Tuple[Tuple[Queue[Any], Queue[Any]], ...],
        from_main_queue: Queue[Dict[str, Any]],
        to_main_queue: Queue[Dict[str, Any]],
        fatal_error_reporter: Queue[Tuple[Exception, str]],
        *,
        file_directory: str,
        logging_level: int = logging.INFO,
        beta_2_mode: bool = False,
    ):
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._board_queues = board_queues
        self._from_main_queue = from_main_queue
        self._to_main_queue = to_main_queue
        self._beta_2_mode = beta_2_mode
        self._num_wells = 24
        # upload values
        self._user_settings: Dict[str, Any] = {
            "auto_upload_on_completion": False,
            "auto_delete_local_files": False,
        }
        self._current_recording_dir: Optional[str] = None
        self._upload_threads_container: List[Dict[str, Any]] = list()
        # general recording values
        self._file_directory = file_directory
        self._is_recording = False
        self._open_files: Tuple[Dict[int, h5py.File], ...] = tuple(
            dict() for _ in range(len(self._board_queues))
        )
        self._end_of_data_stream_reached: List[Optional[bool]] = [False] * len(self._board_queues)
        self._start_recording_timestamps: List[Optional[Tuple[datetime.datetime, int]]] = list(
            [None] * len(self._board_queues)
        )
        self._stop_recording_timestamps: List[Optional[int]] = list([None] * len(self._board_queues))
        if beta_2_mode:
            # set calibration recording values if in Beta 2 mode
            self.set_beta_2_mode()
        self._is_recording_calibration = False
        # magnetometer data recording values
        self._data_packet_buffers: Tuple[Deque[Dict[str, Any]], ...] = tuple(
            deque() for _ in range(len(self._board_queues))
        )
        self._latest_data_timepoints: Tuple[Dict[int, int], ...] = tuple(
            dict() for _ in range(len(self._board_queues))
        )
        # TODO Tanner (3/2/22): once beta 1 support is dropped, should either remove these values or refactor it into one value for every file
        self._tissue_data_finalized_for_recording: Tuple[Dict[int, bool], ...] = tuple(
            [dict()] * len(self._board_queues)
        )
        self._reference_data_finalized_for_recording: Tuple[Dict[int, bool], ...] = tuple(
            dict() for _ in range(len(self._board_queues))
        )
        # stimulation data recording values
        self._stim_info: Dict[str, Any] = {}
        self._end_of_stim_stream_reached: List[Optional[bool]] = [False] * len(self._board_queues)
        self._stim_data_buffers: Tuple[Dict[int, Tuple[Deque[int], Deque[int]]], ...] = tuple(
            {well_idx: (deque(), deque()) for well_idx in range(self._num_wells)}
            for _ in range(len(self._board_queues))
        )
        self._subprotocol_idx_mappings: Dict[str, Dict[int, int]] = {}
        self._max_original_subprotocol_idx_counts: Dict[str, Tuple[int, ...]] = {}
        self._curr_original_subprotocol_idx_for_wells: List[Optional[int]]
        self._curr_original_subprotocol_count_for_wells: List[Optional[int]]
        self._reset_stim_idx_counters()
        # performance tracking values
        self._iterations_per_logging_cycle = int(
            PERFOMANCE_LOGGING_PERIOD_SECS / self._minimum_iteration_duration_seconds
        )
        self._iterations_since_last_logging = 0
        self._num_recorded_points: List[int]
        self._recording_durations: List[float]
        self._reset_performance_tracking_values()

    def _reset_performance_tracking_values(self) -> None:
        self._reset_performance_measurements()
        self._num_recorded_points = list()
        self._recording_durations = list()

    def _reset_stim_idx_counters(self) -> None:
        self._curr_original_subprotocol_idx_for_wells = [None] * self._num_wells
        self._curr_original_subprotocol_count_for_wells = [None] * self._num_wells

    @property
    def _file_directory(self) -> str:
        return self.__file_directory

    @_file_directory.setter
    def _file_directory(self, value: str) -> None:
        self.__file_directory = value
        if self.is_start_up_complete():
            self._check_dirs()

    @property
    def _zipped_files_dir(self) -> str:
        return os.path.join(self._file_directory, "zipped")

    @property
    def _failed_uploads_dir(self) -> str:
        return os.path.join(self._file_directory, "failed_uploads")

    def _check_dirs(self) -> None:
        for new_dir in (self._file_directory, self._zipped_files_dir, self._failed_uploads_dir):
            if not os.path.isdir(new_dir):
                os.makedirs(new_dir)

    def start(self) -> None:
        for board_queue_tuple in self._board_queues:
            for fw_queue in board_queue_tuple:
                if not isinstance(fw_queue, mpqueues.Queue):
                    raise NotImplementedError(
                        "All queues must be standard multiprocessing queues to start this process"
                    )
        for fw_queue in (self._from_main_queue, self._to_main_queue):
            if not isinstance(fw_queue, mpqueues.Queue):
                raise NotImplementedError(
                    "All queues must be standard multiprocessing queues to start this process"
                )
        super().start()

    def get_recording_finalization_statuses(
        self,
    ) -> Tuple[Tuple[Dict[int, bool], ...], Tuple[Dict[int, bool], ...]]:
        return (self._tissue_data_finalized_for_recording, self._reference_data_finalized_for_recording)

    def close_all_files(self) -> None:
        """Close all open H5 files.

        This should only be used in emergencies to preserve data. It is
        not the recommended way to finalize and close a file. Use
        _finalize_completed_files
        """
        for this_file in self._open_files[0].values():
            this_file.close()

    def get_stop_recording_timestamps(self) -> List[Optional[int]]:
        return self._stop_recording_timestamps

    def get_file_latest_timepoint(self, well_idx: int) -> int:
        return self._latest_data_timepoints[0][well_idx]

    def _board_has_open_files(self, board_idx: int) -> bool:
        return len(self._open_files[board_idx].keys()) > 0

    def _is_finalizing_files_after_recording(self) -> bool:
        return self._board_has_open_files(0) and not self._is_recording

    def get_file_directory(self) -> str:
        """Mainly for use in unit tests.

        This will not return the correct value after updating the file
        directory of a running process.
        """
        return self._file_directory

    def is_recording(self) -> bool:
        """Mainly for use in unit tests.

        This will not return the correct value after updating it for a
        of a running process.
        """
        return self._is_recording

    def set_beta_2_mode(self) -> None:
        self._beta_2_mode = True
        self._calibration_folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.calibration_file_directory = self._calibration_folder.name

    def get_upload_threads_container(self) -> List[Dict[str, Any]]:
        """For use in unit tests."""
        return self._upload_threads_container

    def get_stim_data_buffers(self, board_idx: int) -> Dict[int, Tuple[Deque[int], Deque[int]]]:
        """For use in unit tests."""
        return self._stim_data_buffers[board_idx]

    def get_sub_dir_name(self) -> Optional[str]:
        """For use in unit tests."""
        return self._current_recording_dir

    def _setup_before_loop(self) -> None:
        super()._setup_before_loop()
        self._check_dirs()

    def _teardown_after_loop(self) -> None:
        msg = f"File Writer Process beginning teardown at {_get_formatted_utc_now()}"
        put_log_message_into_queue(logging.INFO, msg, self._to_main_queue, self.get_logging_level())
        if self._board_has_open_files(0):
            msg = (
                "Data is still be written to file. Stopping recording and closing files to complete teardown"
            )
            put_log_message_into_queue(logging.INFO, msg, self._to_main_queue, self.get_logging_level())
            self.close_all_files()
        # clean up temporary calibration recording folder
        if self._beta_2_mode:
            self._calibration_folder.cleanup()

        super()._teardown_after_loop()

    def _commands_for_each_run_iteration(self) -> None:
        if not self._is_finalizing_files_after_recording():
            self._process_next_command_from_main()
        self._process_next_incoming_packet()
        self._update_buffers()
        self._finalize_completed_files()
        self._check_upload_statuses()

        if self._is_recording:
            self._iterations_since_last_logging += 1
            if self._iterations_since_last_logging >= self._iterations_per_logging_cycle:
                self._handle_performance_logging()
                self._iterations_since_last_logging = 0

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
                    "timepoint_to_begin_recording_at": communication["timepoint_to_begin_recording_at"],
                    "file_folder": communication["abs_path_to_file_folder"],
                }
            )
        elif command == "stop_recording":
            self._process_stop_recording_command(communication)
            to_main.put_nowait(
                {
                    "communication_type": "command_receipt",
                    "command": "stop_recording",
                    "timepoint_to_stop_recording_at": communication["timepoint_to_stop_recording_at"],
                }
            )
        elif command == "update_recording_name":
            self._process_update_name_command(communication)
            if self._current_recording_dir is None:
                raise NotImplementedError("self._current_recording_dir should never be None here")
            to_main.put_nowait(
                {
                    "communication_type": (
                        "mag_finding_analysis" if communication["snapshot_enabled"] else "command_receipt"
                    ),
                    "command": "update_recording_name",
                    "recording_path": os.path.join(self._file_directory, self._current_recording_dir),
                }
            )
        elif command == "stop_managed_acquisition":
            board_idx = 0
            self._data_packet_buffers[board_idx].clear()
            self._clear_stim_data_buffers()
            self._end_of_data_stream_reached[board_idx] = True
            self._end_of_stim_stream_reached[board_idx] = True
            to_main.put_nowait(
                {"communication_type": "command_receipt", "command": "stop_managed_acquisition"}
            )
            self._is_recording_calibration = False
            # set all finalization statuses to True since no more data will be coming in
            for well_idx in self._tissue_data_finalized_for_recording[board_idx].keys():
                self._tissue_data_finalized_for_recording[board_idx][well_idx] = True
            for well_idx in self._reference_data_finalized_for_recording[board_idx].keys():
                self._reference_data_finalized_for_recording[board_idx][well_idx] = True
        elif command == "update_directory":
            self._file_directory = communication["new_directory"]
            to_main.put_nowait(
                {
                    "communication_type": "command_receipt",
                    "command": "update_directory",
                    "new_directory": communication["new_directory"],
                }
            )
        elif command == "update_user_settings":
            self._user_settings.update(communication["config_settings"])
            to_main.put_nowait({"communication_type": "command_receipt", "command": "update_user_settings"})
        elif command == "set_protocols":
            self._stim_info = communication["stim_info"]
            self._subprotocol_idx_mappings = communication["subprotocol_idx_mappings"]
            self._max_original_subprotocol_idx_counts = communication["max_subprotocol_idx_counts"]
            self._add_protocols_to_recording_files()
        else:
            raise UnrecognizedCommandFromMainToFileWriterError(command)
        if not input_queue.empty():
            self._process_can_be_soft_stopped = False

    def _process_start_recording_command(self, communication: Dict[str, Any]) -> None:
        self._is_recording = True
        self._is_recording_calibration = communication["is_calibration_recording"]

        board_idx = 0

        attrs_to_copy = communication["metadata_to_copy_onto_main_file_attributes"]
        barcode = attrs_to_copy[PLATE_BARCODE_UUID]
        sample_idx_zero_timestamp = attrs_to_copy[UTC_BEGINNING_DATA_ACQUISTION_UUID]

        self._start_recording_timestamps[board_idx] = (
            sample_idx_zero_timestamp,
            communication["timepoint_to_begin_recording_at"],
        )
        timedelta_to_recording_start = datetime.timedelta(
            seconds=communication["timepoint_to_begin_recording_at"]
            / (MICRO_TO_BASE_CONVERSION if self._beta_2_mode else CENTIMILLISECONDS_PER_SECOND)
        )

        recording_start_timestamp = (
            attrs_to_copy[UTC_BEGINNING_DATA_ACQUISTION_UUID] + timedelta_to_recording_start
        )
        recording_start_timestamp_str = recording_start_timestamp.strftime("%Y_%m_%d_%H%M%S")

        if self._is_recording_calibration:
            if not self._beta_2_mode:
                raise NotImplementedError("Cannot make a calibration recording in Beta 1 mode")
            file_folder_dir = self.calibration_file_directory
            file_prefix = f"Calibration__{recording_start_timestamp_str}"
            # delete all existing calibration files
            for file in os.listdir(file_folder_dir):
                os.remove(os.path.join(file_folder_dir, file))
        else:
            # create folder
            recording_name: str = communication.get(
                "recording_name", f"{barcode}__{recording_start_timestamp_str}"
            )
            self._current_recording_dir = recording_name
            file_folder_dir = os.path.join(os.path.abspath(self._file_directory), self._current_recording_dir)
            os.makedirs(file_folder_dir)
            file_prefix = self._current_recording_dir
            # copy beta 2 calibration files into new recording folder
            if self._beta_2_mode:
                calibration_file_paths = glob.glob(os.path.join(self.calibration_file_directory, "*.h5"))
                well_names_found = {file_path.split(".h5")[0][-2:] for file_path in calibration_file_paths}
                all_well_names = {
                    GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
                    for well_idx in range(self._num_wells)
                }
                if well_names_found != all_well_names:
                    missing_well_names = sorted(all_well_names - well_names_found)
                    raise CalibrationFilesMissingError(f"Missing wells: {missing_well_names}")
                for file_path in calibration_file_paths:
                    shutil.copy(file_path, file_folder_dir)

        communication["abs_path_to_file_folder"] = file_folder_dir

        tissue_status, reference_status = self.get_recording_finalization_statuses()
        tissue_status[board_idx].clear()
        reference_status[board_idx].clear()
        for this_well_idx in communication["active_well_indices"]:
            well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(this_well_idx)
            file_path = os.path.join(file_folder_dir, f"{file_prefix}__{well_name}.h5")
            file_version = (
                CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
                if self._beta_2_mode
                else CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
            )
            this_file = MantarrayH5FileCreator(file_path, file_format_version=file_version)
            self._open_files[board_idx][this_well_idx] = this_file

            this_file.attrs[str(WELL_NAME_UUID)] = well_name
            this_row, this_col = GENERIC_24_WELL_DEFINITION.get_row_and_column_from_well_index(this_well_idx)
            this_file.attrs[str(WELL_ROW_UUID)] = this_row
            this_file.attrs[str(WELL_COLUMN_UUID)] = this_col
            this_file.attrs[str(WELL_INDEX_UUID)] = this_well_idx
            if not self._beta_2_mode:
                this_file.attrs[str(REF_SAMPLING_PERIOD_UUID)] = (
                    REFERENCE_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
                )
                this_file.attrs[str(TISSUE_SAMPLING_PERIOD_UUID)] = (
                    CONSTRUCT_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
                )
            else:
                this_file.attrs[str(IS_CALIBRATION_FILE_UUID)] = self._is_recording_calibration
            this_file.attrs[str(TOTAL_WELL_COUNT_UUID)] = 24
            this_file.attrs[str(PLATEMAP_NAME_UUID)] = communication["platemap"]["name"]
            this_file.attrs[str(PLATEMAP_LABEL_UUID)] = communication["platemap"]["labels"][this_well_idx]

            for this_attr_name, this_attr_value in attrs_to_copy.items():
                if this_attr_name == "adc_offsets":
                    this_file.attrs[str(ADC_TISSUE_OFFSET_UUID)] = this_attr_value[this_well_idx]["construct"]
                    this_file.attrs[str(ADC_REF_OFFSET_UUID)] = this_attr_value[this_well_idx]["ref"]
                    continue
                # apply custom formatting to UTC datetime value
                if isinstance(this_attr_value, datetime.datetime):
                    this_attr_value = this_attr_value.strftime("%Y-%m-%d %H:%M:%S.%f")
                # UUIDs must be stored as strings
                this_attr_name = str(this_attr_name)
                if isinstance(this_attr_value, UUID):
                    this_attr_value = str(this_attr_value)
                this_file.attrs[this_attr_name] = this_attr_value
            # Tanner (6/12/20): We must convert UUIDs to strings to allow them to be compatible with H5 and JSON
            this_file.attrs["Metadata UUID Descriptions"] = json.dumps(str(METADATA_UUID_DESCRIPTIONS))

            # Tanner (5/17/21): Not sure what 100 * 3600 * 12 represents, should make it a constant or add comment if/when it is determined
            max_data_len = 100 * 3600 * 12
            if self._beta_2_mode:
                data_shape = (SERIAL_COMM_NUM_DATA_CHANNELS, 0)
                maxshape = (SERIAL_COMM_NUM_DATA_CHANNELS, max_data_len)
                data_dtype = "uint16"
                # beta 2 files must also store time indices and time offsets
                this_file.create_dataset(
                    TIME_INDICES, (0,), maxshape=(max_data_len,), dtype="uint64", chunks=True
                )
                this_file.create_dataset(
                    TIME_OFFSETS,
                    (SERIAL_COMM_NUM_SENSORS_PER_WELL, 0),
                    maxshape=(SERIAL_COMM_NUM_SENSORS_PER_WELL, max_data_len),
                    dtype="uint16",
                    chunks=True,
                )
                this_file.create_dataset(
                    STIMULATION_READINGS, (2, 0), maxshape=(2, max_data_len), dtype="int64", chunks=True
                )
            else:
                data_shape = (0,)  # type: ignore  # mypy doesn't like this for some reason
                maxshape = (max_data_len,)  # type: ignore  # mypy doesn't like this for some reason
                data_dtype = "int32"
            # create datasets present in files for both beta versions
            this_file.create_dataset(
                REFERENCE_SENSOR_READINGS, data_shape, maxshape=maxshape, dtype=data_dtype, chunks=True
            )
            this_file.create_dataset(
                TISSUE_SENSOR_READINGS, data_shape, maxshape=maxshape, dtype=data_dtype, chunks=True
            )
            this_file.swmr_mode = True

            tissue_status[board_idx][this_well_idx] = False
            # TODO Tanner (5/19/21): replace this with False when ref data is added to beta 2 files
            reference_status[board_idx][this_well_idx] = self._beta_2_mode

        self._add_protocols_to_recording_files()

        self.get_stop_recording_timestamps()[board_idx] = None
        data_packet_buffer = self._data_packet_buffers[board_idx]
        for data_packet in data_packet_buffer:
            self._handle_recording_of_data_packet(data_packet)
        if self._beta_2_mode:
            stim_data_buffers = self._stim_data_buffers[board_idx]
            for well_idx, well_buffers in stim_data_buffers.items():
                if well_buffers[0]:
                    self._handle_recording_of_stim_statuses(well_idx, np.array(well_buffers))

    def _process_stop_recording_command(self, communication: Dict[str, Any]) -> None:
        self._is_recording = False

        board_idx = 0
        stop_recording_timepoint = communication["timepoint_to_stop_recording_at"]
        self.get_stop_recording_timestamps()[board_idx] = stop_recording_timepoint
        # no further action needed if this is stopping a calibration recording
        if communication.get("is_calibration_recording", False):
            return

        for this_well_idx in self._open_files[board_idx].keys():
            this_file = self._open_files[board_idx][this_well_idx]
            latest_timepoint = self.get_file_latest_timepoint(this_well_idx)
            if self._beta_2_mode:
                # find num points needed to remove from magnetometer datasets
                time_index_dataset = get_time_index_dataset_from_file(this_file)
                try:
                    num_indices_to_remove = next(
                        i
                        for i, time in enumerate(reversed(time_index_dataset))
                        if time <= stop_recording_timepoint
                    )
                except StopIteration as e:
                    raise InvalidStopRecordingTimepointError(
                        f"The timepoint {stop_recording_timepoint} is earlier than all recorded timepoints"
                    ) from e
                # trim off data after stop recording timepoint
                magnetometer_datasets = [
                    time_index_dataset,
                    get_time_offset_dataset_from_file(this_file),
                    get_tissue_dataset_from_file(this_file),
                ]
                for dataset in magnetometer_datasets:
                    dataset_shape = list(dataset.shape)
                    dataset_shape[-1] -= num_indices_to_remove
                    dataset.resize(dataset_shape)

                # find num points needed to remove from stimulation datasets
                stimulation_dataset = get_stimulation_dataset_from_file(this_file)
                try:
                    num_indices_to_remove = next(
                        i
                        for i, time in enumerate(reversed(stimulation_dataset[0]))
                        if time <= stop_recording_timepoint
                    )
                except StopIteration:
                    num_indices_to_remove = 0
                # trim off data after stop recording timepoint
                dataset_shape = list(stimulation_dataset.shape)
                dataset_shape[-1] -= num_indices_to_remove
                stimulation_dataset.resize(dataset_shape)
            else:
                datasets = [
                    get_tissue_dataset_from_file(this_file),
                    get_reference_dataset_from_file(this_file),
                ]
                # update finalization status
                for dataset in datasets:
                    last_index_of_valid_data = _find_last_valid_data_index(
                        latest_timepoint, dataset.shape[0] - 1, stop_recording_timepoint
                    )
                    new_data = dataset[: last_index_of_valid_data + 1]
                    dataset.resize(new_data.shape)
            finalization_status = bool(  # need to convert from numpy._bool to regular bool
                latest_timepoint >= stop_recording_timepoint
            )
            self._tissue_data_finalized_for_recording[board_idx][this_well_idx] = finalization_status
            # TODO Tanner (3/2/22): if/when beta 2 ref data is added update the follow line
            self._reference_data_finalized_for_recording[board_idx][this_well_idx] = (
                self._beta_2_mode or finalization_status
            )
        # finalize here instead of waiting for next packet
        self._finalize_completed_files()

    def _finalize_completed_files(self) -> None:
        """Finalize H5 files.

        Go through and see if any open files are ready to be closed.
        Close them, and communicate to main.

        It's possible that this could be optimized in the future by only being called when the finalization status of something has changed.
        """
        tissue_status, reference_status = self.get_recording_finalization_statuses()
        # return if no files open
        if len(self._open_files[0]) == 0:
            return

        list_of_corrupt_files = []  # keeps track of all files unable to be open and read

        for this_well_idx in list(
            self._open_files[0].keys()
        ):  # make a copy of the keys since they may be deleted during the run
            # if this_well_idx in tissue_status[0]: # Tanner (7/22/20): This line was apparently always True. If problems start showing up later, likely due to this line being removed
            if not (tissue_status[0][this_well_idx] and reference_status[0][this_well_idx]):
                continue
            this_file = self._open_files[0][this_well_idx]
            # grab filename before closing h5 file otherwise it will error
            file_name = this_file.filename
            this_file.close()

            # after h5 close, reopen them and attempt to read. If not possible then add file to list
            try:
                with h5py.File(file_name, "r"):
                    pass  # if file opens, then there is no corruption
            except Exception:
                list_of_corrupt_files.append(file_name)

            self._to_main_queue.put_nowait({"communication_type": "file_finalized", "file_path": file_name})
            del self._open_files[0][this_well_idx]
        # if no files open anymore, then send message to main indicating that all files have been finalized
        if len(self._open_files[0]) == 0:
            self._to_main_queue.put_nowait(
                {"communication_type": "file_finalized", "message": "all_finals_finalized"}
            )
            # if corrupt files present then send message to main
            if list_of_corrupt_files:
                self._to_main_queue.put_nowait(
                    {"communication_type": "corrupt_file_detected", "corrupt_files": list_of_corrupt_files}
                )

    def _process_next_incoming_packet(self) -> None:
        """Process the next incoming packet for that board.

        If no data present, will just return.

        If multiple boards are implemented, a kwarg board_idx:int=0 can be added.
        """
        board_idx = 0
        input_queue = self._board_queues[board_idx][0]
        try:
            data_packet = input_queue.get_nowait()
        except queue.Empty:
            return

        data_type = "magnetometer" if not self._beta_2_mode else data_packet["data_type"]
        if data_type == "magnetometer":
            self._process_magnetometer_data_packet(data_packet)
        elif data_type == "stimulation":
            self._process_stim_data_packet(data_packet)
        else:
            raise NotImplementedError(f"Invalid data type from Instrument Comm Process: {data_type}")

        if not input_queue.empty():
            self._process_can_be_soft_stopped = False

    def _process_magnetometer_data_packet(self, data_packet: Dict[Any, Any]) -> None:
        # Tanner (5/25/21): Creating this log message takes a long time so only do it if we are actually logging. TODO: Should probably refactor this function to something more efficient eventually
        if logging.DEBUG >= self.get_logging_level() and self._beta_2_mode:  # pragma: no cover
            num_data_points = data_packet["time_indices"].shape[0]
            data_packet_info = {
                "num_data_points": num_data_points,
                "is_first_packet_of_stream": data_packet["is_first_packet_of_stream"],
            }
            if num_data_points:
                data_packet_info["first_timepoint"] = data_packet["time_indices"][0]
                data_packet_info["last_timepoint"] = data_packet["time_indices"][-1]
            put_log_message_into_queue(
                logging.DEBUG,
                f"Timestamp: {_get_formatted_utc_now()} Received a data packet from InstrumentCommProcess. Details: {data_packet_info}",
                self._to_main_queue,
                self.get_logging_level(),
            )

        board_idx = 0
        output_queue = self._board_queues[board_idx][1]
        if self._beta_2_mode and data_packet["is_first_packet_of_stream"]:
            self._end_of_data_stream_reached[board_idx] = False
            self._data_packet_buffers[board_idx].clear()
        if not (self._beta_2_mode and self._end_of_data_stream_reached[board_idx]):
            self._data_packet_buffers[board_idx].append(data_packet)
            if not self._is_recording_calibration:
                output_queue.put_nowait(data_packet)

        # Tanner (5/17/21): This code was not previously guarded by this if statement. If issues start occurring with recorded data or performance metrics, check here first
        if self._is_recording or self._board_has_open_files(board_idx):
            self._num_recorded_points.append(
                data_packet["time_indices"].shape[0] if self._beta_2_mode else data_packet["data"].shape[1]
            )

            start = time.perf_counter()
            self._handle_recording_of_data_packet(data_packet)
            recording_dur = time.perf_counter() - start
            self._recording_durations.append(recording_dur)

    def _handle_recording_of_data_packet(self, data_packet: Dict[Any, Any]) -> None:
        if self._beta_2_mode:
            self._process_beta_2_data_packet(data_packet)
        else:
            is_reference_sensor = data_packet["is_reference_sensor"]
            if is_reference_sensor:
                well_indices_to_process = data_packet["reference_for_wells"]
            else:
                well_indices_to_process = set([data_packet["well_index"]])
            for this_well_idx in well_indices_to_process:
                data_packet["well_index"] = this_well_idx
                if this_well_idx in self._open_files[0]:
                    self._process_beta_1_data_packet_for_open_file(data_packet)

    def _process_beta_2_data_packet(self, data_packet: Dict[Union[str, int], Any]) -> None:
        """Process a Beta 2 data packet for a file that is known to be open."""
        board_idx = 0
        this_start_recording_timestamps = self._start_recording_timestamps[board_idx]
        if this_start_recording_timestamps is None:  # check needed for mypy to be happy
            raise NotImplementedError("Something wrong in the code. This should never be none.")

        time_indices = data_packet["time_indices"]
        timepoint_to_start_recording_at = this_start_recording_timestamps[1]
        if time_indices[-1] < timepoint_to_start_recording_at:
            return
        is_final_packet = False
        stop_recording_timestamp = self.get_stop_recording_timestamps()[board_idx]
        if stop_recording_timestamp is not None:
            is_final_packet = time_indices[-1] >= stop_recording_timestamp
            if is_final_packet:
                for well_idx in self._open_files[board_idx].keys():
                    self._tissue_data_finalized_for_recording[board_idx][well_idx] = True
            if time_indices[0] >= stop_recording_timestamp:
                return

        packet_must_be_trimmed = is_final_packet or time_indices[0] < timepoint_to_start_recording_at
        if packet_must_be_trimmed:
            first_idx_of_new_data, last_idx_of_new_data = _find_bounds(
                time_indices, timepoint_to_start_recording_at, max_timepoint=stop_recording_timestamp
            )
            time_indices = time_indices[first_idx_of_new_data : last_idx_of_new_data + 1]
        new_data_size = time_indices.shape[0]

        for well_idx, this_file in self._open_files[board_idx].items():
            # record new time indices
            time_index_dataset = get_time_index_dataset_from_file(this_file)
            previous_data_size = time_index_dataset.shape[0]
            time_index_dataset.resize((previous_data_size + time_indices.shape[0],))
            time_index_dataset[previous_data_size:] = time_indices
            # record new time offsets
            time_offsets = data_packet[well_idx]["time_offsets"]
            if packet_must_be_trimmed:
                time_offsets = time_offsets[:, first_idx_of_new_data : last_idx_of_new_data + 1]
            time_offset_dataset = get_time_offset_dataset_from_file(this_file)
            previous_data_size = time_offset_dataset.shape[1]
            time_offset_dataset.resize((time_offsets.shape[0], previous_data_size + time_offsets.shape[1]))
            time_offset_dataset[:, previous_data_size:] = time_offsets
            # record new tissue data
            tissue_dataset = get_tissue_dataset_from_file(this_file)
            if tissue_dataset.shape[1] == 0:
                this_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] = (
                    this_start_recording_timestamps[0]
                    + datetime.timedelta(seconds=time_indices[0] / MICRO_TO_BASE_CONVERSION)
                ).strftime("%Y-%m-%d %H:%M:%S.%f")
            tissue_dataset.resize((tissue_dataset.shape[0], previous_data_size + new_data_size))

            well_data_dict = data_packet[well_idx]
            well_keys = list(well_data_dict.keys())
            well_keys.remove("time_offsets")
            for data_channel_idx, channel_id in enumerate(sorted(well_keys)):
                new_data = well_data_dict[channel_id]
                if packet_must_be_trimmed:
                    new_data = new_data[first_idx_of_new_data : last_idx_of_new_data + 1]
                tissue_dataset[data_channel_idx, previous_data_size:] = new_data

            self._latest_data_timepoints[0][well_idx] = time_indices[-1]

    def _process_beta_1_data_packet_for_open_file(self, data_packet: Dict[str, Any]) -> None:
        """Process a Beta 1 data packet for a file that is known to be open."""
        this_start_recording_timestamps = self._start_recording_timestamps[0]
        if this_start_recording_timestamps is None:  # check needed for mypy to be happy
            raise NotImplementedError("Something wrong in the code. This should never be none.")

        this_data = data_packet["data"]
        last_timepoint_in_data_packet = this_data[0, -1]
        timepoint_to_start_recording_at = this_start_recording_timestamps[1]
        if last_timepoint_in_data_packet < timepoint_to_start_recording_at:
            return
        first_timepoint_in_data_packet = this_data[0, 0]

        is_reference_sensor = data_packet["is_reference_sensor"]
        stop_recording_timestamp = self.get_stop_recording_timestamps()[0]
        if stop_recording_timestamp is not None:
            if last_timepoint_in_data_packet >= stop_recording_timestamp:
                if is_reference_sensor:
                    well_indices = data_packet["reference_for_wells"]
                    for this_well_idx in well_indices:
                        if this_well_idx in self._reference_data_finalized_for_recording[0]:
                            self._reference_data_finalized_for_recording[0][this_well_idx] = True
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

        new_data, first_timepoint_of_new_data, last_timepoint_of_new_data = get_data_slice_within_timepoints(
            this_data, timepoint_to_start_recording_at, max_timepoint=stop_recording_timestamp
        )

        if this_dataset.shape == (0,):
            this_file.attrs[recording_timestamp_attr_name] = (
                this_start_recording_timestamps[0]
                + datetime.timedelta(seconds=first_timepoint_of_new_data / CENTIMILLISECONDS_PER_SECOND)
            ).strftime("%Y-%m-%d %H:%M:%S.%f")
        previous_data_size = this_dataset.shape[0]
        this_dataset.resize((previous_data_size + new_data.shape[0],))
        this_dataset[previous_data_size:] = new_data

        self._latest_data_timepoints[0][this_well_idx] = last_timepoint_of_new_data

    def _process_stim_data_packet(self, stim_packet: Dict[Any, Any]) -> None:
        if logging.DEBUG >= self.get_logging_level():  # pragma: no cover
            put_log_message_into_queue(
                logging.DEBUG,
                f"Timestamp: {_get_formatted_utc_now()} Received a stim packet from InstrumentCommProcess: {stim_packet}",
                self._to_main_queue,
                self.get_logging_level(),
            )

        board_idx = 0
        if stim_packet["is_first_packet_of_stream"]:
            self._end_of_stim_stream_reached[board_idx] = False
            self._clear_stim_data_buffers()
            self._reset_stim_idx_counters()
        if not self._end_of_stim_stream_reached[board_idx]:
            self.append_to_stim_data_buffers(stim_packet["well_statuses"])
            output_queue = self._board_queues[board_idx][1]
            if reduced_well_statuses := self._reduce_subprotocol_chunks(stim_packet["well_statuses"]):
                output_queue.put_nowait({**stim_packet, "well_statuses": reduced_well_statuses})

        if self._is_recording or self._board_has_open_files(board_idx):
            # TODO Tanner (10/21/21): once real stim traces are sent from instrument, add performance metrics
            for well_idx, well_statuses in stim_packet["well_statuses"].items():
                self._handle_recording_of_stim_statuses(well_idx, well_statuses)

    def _reduce_subprotocol_chunks(self, well_statuses: Dict[int, Any]) -> Dict[int, Any]:
        reduced_well_statuses = {}
        for well_idx, well_status_arr in well_statuses.items():
            well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
            assigned_protocol_id = self._stim_info["protocol_assignments"][well_name]

            timepoint_well_status_pairs = []
            for timepoint, chunked_subprotocol_idx in well_status_arr.T:
                original_subprotocol_idx = self._convert_subprotocol_idx(
                    assigned_protocol_id, chunked_subprotocol_idx
                )

                if original_subprotocol_idx == STIM_COMPLETE_SUBPROTOCOL_IDX:
                    timepoint_well_status_pairs.append((timepoint, original_subprotocol_idx))
                    continue

                # update idx and reset count if subprotocol idx changed
                if original_subprotocol_idx != self._curr_original_subprotocol_idx_for_wells[well_idx]:
                    self._curr_original_subprotocol_idx_for_wells[well_idx] = original_subprotocol_idx
                    self._curr_original_subprotocol_count_for_wells[well_idx] = -1

                curr_count = self._curr_original_subprotocol_count_for_wells[well_idx]
                max_count = self._max_original_subprotocol_idx_counts[assigned_protocol_id][
                    original_subprotocol_idx
                ]
                self._curr_original_subprotocol_count_for_wells[well_idx] = (curr_count + 1) % max_count  # type: ignore

                # filter out intermediate idxs
                if self._curr_original_subprotocol_count_for_wells[well_idx] == 0:
                    timepoint_well_status_pairs.append((timepoint, original_subprotocol_idx))

            if timepoint_well_status_pairs:
                reduced_well_statuses[well_idx] = np.array(timepoint_well_status_pairs, dtype=np.int64).T

        return reduced_well_statuses

    def _handle_recording_of_stim_statuses(
        self, well_idx: int, stim_data_arr: NDArray[(2, Any), int]
    ) -> None:
        board_idx = 0
        if well_idx not in self._open_files[board_idx]:
            return

        well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
        assigned_protocol_id = self._stim_info["protocol_assignments"][well_name]

        stim_data_arr[1] = np.array(
            [
                self._convert_subprotocol_idx(assigned_protocol_id, chunked_subprotocol_idx)
                for chunked_subprotocol_idx in stim_data_arr[1]
            ]
        )

        this_start_recording_timestamps = self._start_recording_timestamps[board_idx]
        if this_start_recording_timestamps is None:  # check needed for mypy to be happy
            raise NotImplementedError("Something wrong in the code. This should never be none.")

        stop_recording_timestamp = self.get_stop_recording_timestamps()[board_idx]
        if stop_recording_timestamp is not None and stim_data_arr[0, 0] >= stop_recording_timestamp:
            return

        # remove unneeded status updates
        earliest_magnetometer_time_idx = this_start_recording_timestamps[1]
        earliest_valid_index = _find_earliest_valid_stim_status_index(
            stim_data_arr[0].tolist(), earliest_magnetometer_time_idx
        )
        stim_data_arr = stim_data_arr[:, earliest_valid_index:]
        # update dataset in h5 file
        this_well_file = self._open_files[board_idx][well_idx]
        stimulation_dataset = get_stimulation_dataset_from_file(this_well_file)
        previous_data_size = stimulation_dataset.shape[1]
        stimulation_dataset.resize((2, previous_data_size + stim_data_arr.shape[1]))
        stimulation_dataset[:, previous_data_size:] = stim_data_arr

    def _convert_subprotocol_idx(self, protocol_id: str, chunked_subprotocol_idx: int) -> int:
        return (
            chunked_subprotocol_idx
            if chunked_subprotocol_idx == STIM_COMPLETE_SUBPROTOCOL_IDX
            else self._subprotocol_idx_mappings[protocol_id][chunked_subprotocol_idx]
        )

    def _update_buffers(self) -> None:
        board_idx = 0
        data_packet_buffer = self._data_packet_buffers[board_idx]
        if not data_packet_buffer:
            return

        # update magnetometer data buffer
        if self._beta_2_mode:
            curr_buffer_memory_size = (
                data_packet_buffer[-1]["time_indices"][0] - data_packet_buffer[0]["time_indices"][0]
            )
            max_buffer_memory_size = FILE_WRITER_BUFFER_SIZE_MICROSECONDS
        else:
            curr_buffer_memory_size = (
                data_packet_buffer[-1]["data"][0, 0] - data_packet_buffer[0]["data"][0, 0]
            )
            max_buffer_memory_size = FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS
        if curr_buffer_memory_size > max_buffer_memory_size:
            data_packet_buffer.popleft()

        if not self._beta_2_mode:
            return

        # update stim data buffer
        earliest_magnetometer_time_idx = data_packet_buffer[0]["time_indices"][0]
        stim_data_buffers = self._stim_data_buffers[board_idx]
        for well_buffers in stim_data_buffers.values():
            if not well_buffers[0]:
                continue
            earliest_valid_index = _find_earliest_valid_stim_status_index(
                list(well_buffers[0]), earliest_magnetometer_time_idx
            )
            for well_buffer in well_buffers:
                buffer_slice = list(well_buffer)[earliest_valid_index:]
                # clearing and then extending instead of creating a new deque
                well_buffer.clear()
                well_buffer.extend(buffer_slice)

    def append_to_stim_data_buffers(self, well_statuses: Dict[int, Any]) -> None:
        """Public solely for use in unit testing."""
        board_idx = 0
        for well_idx, status_updates_arr in well_statuses.items():
            well_buffers = self._stim_data_buffers[board_idx][well_idx]
            well_buffers[0].extend(status_updates_arr[0])
            well_buffers[1].extend(status_updates_arr[1])

    def _clear_stim_data_buffers(self) -> None:
        board_idx = 0
        for well_buffers in self._stim_data_buffers[board_idx].values():
            well_buffers[0].clear()
            well_buffers[1].clear()

    def _add_protocols_to_recording_files(self) -> None:
        board_idx = 0

        if self._stim_info:
            labeled_protocol_dict = {
                protocol["protocol_id"]: protocol for protocol in self._stim_info["protocols"]
            }
            for well_idx, well_h5_file in self._open_files[board_idx].items():
                well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
                assigned_protocol_id = self._stim_info["protocol_assignments"][well_name]
                protocol_json = json.dumps(labeled_protocol_dict.get(assigned_protocol_id))
                well_h5_file.attrs[str(STIMULATION_PROTOCOL_UUID)] = protocol_json
        else:
            for well_h5_file in self._open_files[board_idx].values():
                well_h5_file.attrs[str(STIMULATION_PROTOCOL_UUID)] = json.dumps(None)

    def _handle_performance_logging(self) -> None:
        if logging.DEBUG >= self._logging_level:  # pragma: no cover
            performance_metrics: Dict[str, Any] = {"communication_type": "performance_metrics"}
            performance_tracker = self.reset_performance_tracker()
            performance_metrics["percent_use"] = performance_tracker["percent_use"]
            performance_metrics["longest_iterations"] = sorted(performance_tracker["longest_iterations"])
            if len(self._percent_use_values) > 1:
                performance_metrics["percent_use_metrics"] = self.get_percent_use_metrics()
            if len(self._num_recorded_points) > 1 and len(self._recording_durations) > 1:
                fw_measurements: List[Union[int, float]]
                for name, fw_measurements in (  # type: ignore
                    ("num_recorded_data_points_metrics", self._num_recorded_points),
                    ("recording_duration_metrics", self._recording_durations),
                ):
                    performance_metrics[name] = create_metrics_stats(fw_measurements)

            put_log_message_into_queue(
                logging.INFO, performance_metrics, self._to_main_queue, self.get_logging_level()
            )
        self._reset_performance_tracking_values()

    def _start_new_file_upload(self) -> None:
        """Upload file recordings to the cloud.

        Processes upload thread and if successful, the upload status
        will get updated and will delete local files if set to true. If
        unsuccessful, the file will get placed in failed_uploads
        directory to process later.
        """
        if self._current_recording_dir is None:
            raise NotImplementedError("_current_recording_dir should never be None here")

        auto_delete = self._user_settings["auto_delete_local_files"]
        customer_id = self._user_settings["customer_id"]
        user_name = self._user_settings["user_name"]

        file_uploader = FileUploader(
            "recording",
            self._file_directory,
            self._current_recording_dir,
            self._zipped_files_dir,
            customer_id,
            user_name,
            self._user_settings["user_password"],
            self._user_settings["pulse3d_version"],
        )

        upload_thread = ErrorCatchingThread(target=file_uploader)
        upload_thread.start()

        thread_dict = {
            "failed_upload": False,
            "customer_id": customer_id,
            "user_name": user_name,
            "thread": upload_thread,
            "auto_delete": auto_delete,
            "file_name": self._current_recording_dir,
            "file_uploader": file_uploader,
        }
        self._upload_threads_container.append(thread_dict)

    def _delete_local_files(self, sub_dir: Optional[str]) -> None:
        """Call after upload if true.

        Deletes entire recording directory containing h5 files.
        """
        if sub_dir is None:
            raise NotImplementedError("sub_dir should never be None here")

        file_folder_dir = os.path.join(os.path.abspath(self._file_directory), sub_dir)

        # Remove recording directory and all .h5 files
        for file in os.listdir(file_folder_dir):
            os.remove(os.path.join(file_folder_dir, file))

        os.rmdir(file_folder_dir)
        # TODO Lucy (12/11/2021): remove zip file

    def _process_new_failed_upload_files(self, sub_dir: str) -> None:
        """Call when a file upload errors.

        If none exists, creates user directory in failed_uploads to
        place failed .zip files to process next start.
        """
        user_name = self._user_settings["user_name"]

        user_failed_uploads_dir = os.path.join(self._failed_uploads_dir, user_name)
        if not os.path.exists(user_failed_uploads_dir):
            os.makedirs(user_failed_uploads_dir)

        file_name = f"{sub_dir}.zip"
        zipped_file = os.path.join(self._zipped_files_dir, user_name, file_name)
        updated_zipped_file = os.path.join(self._failed_uploads_dir, user_name, file_name)

        # store failed zip file in failed uploads directory to check at next startup
        if os.path.exists(zipped_file):
            shutil.move(zipped_file, updated_zipped_file)

    def _check_upload_statuses(self) -> None:
        """Loops through active upload threads.

        Checks if thread is alive and if not, processes error or result.
        Moves files according.
        """
        for thread_dict in self._upload_threads_container:
            thread = thread_dict["thread"]
            previously_failed_upload = thread_dict["failed_upload"]
            user_name = thread_dict["user_name"]
            auto_delete = thread_dict["auto_delete"]
            file_name = thread_dict["file_name"]

            if thread.is_alive():
                continue

            thread.join()
            upload_status = dict()
            upload_status["file_name"] = os.path.splitext(file_name)[0]

            if thread.error:
                upload_status["error"] = thread.error
                if not previously_failed_upload:
                    self._process_new_failed_upload_files(sub_dir=file_name)

                failed_action = thread_dict["file_uploader"].current_action
                upload_status["error_msg"] = f"Failed to {failed_action}"
            else:
                if previously_failed_upload:
                    shutil.move(
                        os.path.join(self._failed_uploads_dir, user_name, file_name),
                        os.path.join(self._zipped_files_dir, user_name),
                    )
                elif auto_delete:
                    self._delete_local_files(sub_dir=file_name)

            self._upload_threads_container.remove(thread_dict)
            outgoing_msg = {"data_type": "upload_status", "data_json": json.dumps(upload_status)}
            self._to_main_queue.put_nowait(
                {"communication_type": "update_upload_status", "content": outgoing_msg}
            )

    def _process_update_name_command(self, comm: Dict[str, str]) -> None:
        """Rename recording directory and h5 files to kick off auto upload."""
        if self._current_recording_dir is None:
            raise NotImplementedError("self._current_recording_dir should never be None here")

        old_recording_path = os.path.join(self._file_directory, self._current_recording_dir)

        # first, add user defined metadata
        for filename in os.listdir(old_recording_path):
            if "calibration" in filename.lower():  # pragma: no cover
                continue

            file_path = os.path.join(old_recording_path, filename)
            with h5py.File(file_path, "r+") as h5_file:
                h5_file.attrs[str(USER_DEFINED_METADATA_UUID)] = json.dumps(comm["user_defined_metadata"])

        # only perform if new name is different from the original default name
        if self._current_recording_dir == comm["default_name"] != comm["new_name"]:
            new_recording_path = os.path.join(self._file_directory, comm["new_name"])
            if os.path.exists(new_recording_path):
                # remove current recording if it already exists
                shutil.rmtree(new_recording_path)

            # rename directory
            os.rename(old_recording_path, new_recording_path)
            self._current_recording_dir = comm["new_name"]

            for filename in os.listdir(new_recording_path):
                # replace everything but the well name
                new_filename = filename.replace(comm["default_name"], comm["new_name"])
                old_file_path = os.path.join(new_recording_path, filename)
                new_file_path = os.path.join(new_recording_path, new_filename)
                os.rename(old_file_path, new_file_path)

        # after all files are finalized, upload them if necessary
        if self._user_settings["auto_upload_on_completion"]:
            self._start_new_file_upload()
            msg = f"Started auto upload for file {self._current_recording_dir}"
            put_log_message_into_queue(logging.INFO, msg, self._to_main_queue, self.get_logging_level())
        elif self._user_settings["auto_delete_local_files"]:
            self._delete_local_files(sub_dir=self._current_recording_dir)

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items: Dict[str, Any] = dict()
        for i, board in enumerate(self._board_queues):
            queue_items[f"board_{i}"] = _drain_board_queues(board)
        queue_items["from_main_to_file_writer"] = drain_queue(self._from_main_queue)
        queue_items["from_file_writer_to_main"] = drain_queue(self._to_main_queue)
        return queue_items
