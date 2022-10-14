# -*- coding: utf-8 -*-
"""Analyzing data coming from board."""
from __future__ import annotations

import datetime
from functools import partial
import json
import logging
from multiprocessing import Queue
from multiprocessing import queues as mpqueues
import os
import queue
from time import perf_counter
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from uuid import UUID

from immutabledict import immutabledict
from mantarray_magnet_finding.utils import calculate_magnetic_flux_density_from_memsic
from nptyping import NDArray
import numpy as np
from pulse3D.compression_cy import compress_filtered_magnetic_data
from pulse3D.constants import AMPLITUDE_UUID
from pulse3D.constants import BUTTERWORTH_LOWPASS_30_UUID
from pulse3D.constants import MEMSIC_CENTER_OFFSET
from pulse3D.constants import TWITCH_FREQUENCY_UUID
from pulse3D.exceptions import PeakDetectionError
from pulse3D.magnet_finding import fix_dropped_samples
from pulse3D.metrics import TwitchAmplitude
from pulse3D.metrics import TwitchFrequency
from pulse3D.peak_detection import find_twitch_indices
from pulse3D.peak_detection import peak_detector
from pulse3D.transforms import apply_noise_filtering
from pulse3D.transforms import calculate_displacement_from_voltage
from pulse3D.transforms import calculate_force_from_displacement
from pulse3D.transforms import calculate_voltage_from_gmr
from pulse3D.transforms import create_filter
from pulse3D.transforms import get_stiffness_factor
from pulse3D.utils import get_experiment_id
from stdlib_utils import create_metrics_stats
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import put_log_message_into_queue
from streamz import Stream

from ..constants import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from ..constants import CONSTRUCT_SENSORS_PER_REF_SENSOR
from ..constants import DATA_ANALYZER_BETA_1_BUFFER_SIZE
from ..constants import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from ..constants import DEFAULT_SAMPLING_PERIOD
from ..constants import MICRO_TO_BASE_CONVERSION
from ..constants import MICROSECONDS_PER_CENTIMILLISECOND
from ..constants import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from ..constants import MM_PER_MT_Z_AXIS_SENSOR_0
from ..constants import PERFOMANCE_LOGGING_PERIOD_SECS
from ..constants import REF_INDEX_TO_24_WELL_INDEX
from ..constants import SERIAL_COMM_DEFAULT_DATA_CHANNEL
from ..exceptions import StartManagedAcquisitionWithoutBarcodeError
from ..exceptions import UnrecognizedCommandFromMainToDataAnalyzerError
from ..workers.magnet_finder import run_magnet_finding_alg
from ..workers.worker_thread import ErrorCatchingThread


METRIC_CALCULATORS = immutabledict(
    {
        AMPLITUDE_UUID: TwitchAmplitude(rounded=False),
        TWITCH_FREQUENCY_UUID: TwitchFrequency(rounded=False),
    }
)


def calculate_displacement_from_magnetic_flux_density(
    magnetic_flux_data: NDArray[(2, Any), np.float64],
) -> NDArray[(2, Any), np.float64]:
    """Convert magnetic flux density to displacement.

    Conversion values were obtained 06/13/2022 by Kevin Gray

    Args:
        magnetic_flux_data: time and magnetic flux density numpy array.

    Returns:
        A 2D array of time vs Displacement (mm)
    """
    sample_in_milliteslas = magnetic_flux_data[1, :]
    time = magnetic_flux_data[0, :]

    # calculate displacement
    sample_in_mm = sample_in_milliteslas * MM_PER_MT_Z_AXIS_SENSOR_0

    return np.vstack((time, sample_in_mm)).astype(np.float64)


def get_force_signal(
    raw_signal: NDArray[(2, Any), np.int64],
    filter_coefficients: NDArray[(2, Any), np.float64],
    plate_barcode: str,
    well_idx: int,
    compress: bool = True,
    is_beta_2_data: bool = True,
) -> NDArray[(2, Any), np.float64]:
    if is_beta_2_data:
        filtered_memsic = apply_noise_filtering(raw_signal, filter_coefficients)
        if compress:
            filtered_memsic = compress_filtered_magnetic_data(filtered_memsic)
        # can't pass time indices to calculate_magnetic_flux_density_from_memsic
        mfd = np.array(
            [filtered_memsic[0], calculate_magnetic_flux_density_from_memsic(filtered_memsic[1])],
            dtype=np.float64,
        )
        displacement = calculate_displacement_from_magnetic_flux_density(mfd)
    else:
        filtered_gmr = apply_noise_filtering(raw_signal, filter_coefficients)
        if compress:
            filtered_gmr = compress_filtered_magnetic_data(filtered_gmr)
        voltage = calculate_voltage_from_gmr(filtered_gmr)
        displacement = calculate_displacement_from_voltage(voltage)
    post_stiffness_factor = get_stiffness_factor(get_experiment_id(plate_barcode), well_idx)
    return calculate_force_from_displacement(displacement, post_stiffness_factor, in_mm=is_beta_2_data)


def live_data_metrics(
    peak_and_valley_indices: Tuple[NDArray[int], NDArray[int]],
    filtered_data: NDArray[(2, Any), int],
) -> Dict[int, Dict[UUID, Any]]:
    """Find all data metrics for individual twitches and averages.

    Need to use this function until `data_metrics` function in pulse3D
    can handle metric creation in real time. Currently has an issue with pandas DataFrames
    being very slow.

    Args:
        peak_and_valley_indices: a tuple of integer value arrays representing the time indices of peaks and valleys within the data
        filtered_data: a 2D array of the time and voltage data after it has gone through noise cancellation
        rounded: whether to round estimates to the nearest int
        metrics_to_create: list of desired metrics

    Returns:
        main_twitch_dict: a dictionary of individual peak metrics in which the twitch timepoint is accompanied by a dictionary in which the UUIDs for each twitch metric are the key and with its accompanying value as the value. For the Twitch Width metric UUID, another dictionary is stored in which the key is the percentage of the way down and the value is another dictionary in which the UUIDs for the rising coord, falling coord or width value are stored with the value as an int for the width value or a tuple of ints for the x/y coordinates
    """
    # create main dictionaries
    main_twitch_dict: Dict[int, Dict[UUID, Any]] = dict()

    # get values needed for metrics creation
    twitch_indices = find_twitch_indices(peak_and_valley_indices)
    num_twitches = len(twitch_indices)
    time_series = filtered_data[0, :]

    # create top level dict
    twitch_peak_indices = tuple(twitch_indices.keys())
    main_twitch_dict = {time_series[twitch_peak_indices[i]]: dict() for i in range(num_twitches)}

    # create metrics
    for metric_uuid in (TWITCH_FREQUENCY_UUID, AMPLITUDE_UUID):
        metric_df = METRIC_CALCULATORS[metric_uuid].fit(
            peak_and_valley_indices, filtered_data, twitch_indices
        )
        for twitch_idx, metric_value in metric_df.to_dict().items():
            time_index = time_series[twitch_idx]
            main_twitch_dict[time_index][metric_uuid] = metric_value

    return main_twitch_dict


def check_for_new_twitches(
    latest_time_index: int, per_twitch_metrics: Dict[int, Any]
) -> Tuple[int, Dict[Any, Any]]:
    """Pass only new twitches through the data stream."""
    # Tanner (7/14/21): if issues come up with peaks being reported twice, could try storing peak of and valley after the latest twitch and use those values to check for new twitches
    time_index_list = list(per_twitch_metrics.keys())

    if time_index_list[-1] <= latest_time_index:
        return latest_time_index, {}

    for twitch_time_index in time_index_list:
        if twitch_time_index <= latest_time_index:
            del per_twitch_metrics[twitch_time_index]
    return time_index_list[-1], per_twitch_metrics


def _get_secs_since_data_creation_start(start: float) -> float:
    return perf_counter() - start


def _get_secs_since_data_analysis_start(start: float) -> float:
    return perf_counter() - start


def _drain_board_queues(
    board_queues: Tuple[Queue[Any], Queue[Any]],  # pylint: disable=unsubscriptable-object
) -> Dict[str, List[Any]]:
    board_dict = {
        "file_writer_to_data_analyzer": drain_queue(board_queues[0]),
        "outgoing_data": drain_queue(board_queues[1]),
    }
    return board_dict


# pylint: disable=too-many-instance-attributes
class DataAnalyzerProcess(InfiniteProcess):
    """Process that analyzes data.

    Args:
        board_queues: A tuple (the max number of board connections should be predefined, so not a mutable list) of tuples of 2 queues. The first queue is for incoming data for that board that should be analyzed. The second queue is for finalized outgoing data to main process
        from_main_queue: a queue of communication from the main process
        to_main_queue: a queue to put general communication back to main
        fatal_error_reporter: a queue to report fatal errors back to the main process
        mag_analysis_output_dir: directory to write time force csv to
    """

    def __init__(
        self,
        the_board_queues: Tuple[
            Tuple[Queue[Any], Queue[Any]],  # pylint: disable=unsubscriptable-object
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ],
        comm_from_main_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        comm_to_main_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        fatal_error_reporter: Queue[Tuple[Exception, str]],  # pylint: disable=unsubscriptable-object
        *,
        mag_analysis_output_dir: str,
        logging_level: int = logging.INFO,
        beta_2_mode: bool = False,
    ):
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._beta_2_mode = beta_2_mode
        self._board_queues = the_board_queues
        self._comm_from_main_queue = comm_from_main_queue
        self._comm_to_main_queue = comm_to_main_queue
        # data streaming values
        self._end_of_data_stream_reached: Tuple[Dict[str, bool], ...] = tuple(
            {"mag": False, "stim": False} for _ in range(len(self._board_queues))
        )
        self._data_buffer: Dict[int, Dict[str, Any]] = dict()
        for well_idx in range(24):
            self._data_buffer[well_idx] = {"construct_data": None, "ref_data": None}
        # data analysis items
        self._barcode: Optional[str] = None
        self._data_analysis_streams: Dict[int, Tuple[Stream, Stream]] = dict()
        self._data_analysis_stream_zipper: Optional[Stream] = None
        self._active_wells: List[int] = list(range(24))
        self._filter_coefficients = create_filter(  # updated in set_sampling_period if in beta 2 mode
            BUTTERWORTH_LOWPASS_30_UUID, CONSTRUCT_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
        )
        # Beta 1 items
        self._well_offsets: List[Union[int, float, None]] = [None] * 24
        self._calibration_settings: Union[None, Dict[Any, Any]] = None
        # Beta 2 items
        self._beta_2_buffer_size: Optional[int] = None  # set in set_sampling_period if in beta 2 mode
        # Magnet finding alg items
        self._mag_finder_output_dir: str = mag_analysis_output_dir
        self._mag_finder_worker_thread: Optional[Any] = None
        self._mag_finder_thread_dict: Optional[Dict[str, Any]] = None
        # performance tracking values
        self._outgoing_data_creation_durations: List[float]
        self._data_analysis_durations: List[float]
        self._reset_performance_tracking_values()

    def _reset_performance_tracking_values(self) -> None:
        self._reset_performance_measurements()
        self._outgoing_data_creation_durations = list()
        self._data_analysis_durations = list()

    def _check_dirs(self) -> None:
        if not os.path.isdir(self._mag_finder_output_dir):
            os.makedirs(self._mag_finder_output_dir)

    def start(self) -> None:
        for board_queue_tuple in self._board_queues:
            for da_queue in board_queue_tuple:
                if not isinstance(da_queue, mpqueues.Queue):
                    raise NotImplementedError(
                        "All queues must be standard multiprocessing queues to start this process"
                    )
        for da_queue in (self._comm_from_main_queue, self._comm_to_main_queue):
            if not isinstance(da_queue, mpqueues.Queue):
                raise NotImplementedError(
                    "All queues must be standard multiprocessing queues to start this process"
                )
        super().start()

    def get_calibration_settings(self) -> Union[None, Dict[Any, Any]]:
        if self._beta_2_mode:
            raise NotImplementedError("Beta 2 mode does not currently have calibration settings")
        return self._calibration_settings

    def get_buffer_size(self) -> int:
        return self._beta_2_buffer_size if self._beta_2_mode else DATA_ANALYZER_BETA_1_BUFFER_SIZE  # type: ignore

    def append_data(
        self, data_buf: List[List[int]], new_data: NDArray[(2, Any), int]
    ) -> Tuple[List[List[int]], List[List[int]]]:
        # Tanner (7/12/21): using lists here since list.extend is faster than ndarray.concatenate
        data_buf[0].extend(new_data[0])
        data_buf[1].extend(new_data[1])
        data_buf[0] = data_buf[0][-self.get_buffer_size() :]
        data_buf[1] = data_buf[1][-self.get_buffer_size() :]
        return data_buf, data_buf

    def get_twitch_analysis(self, data_buf: List[List[int]], well_idx: int) -> Dict[int, Any]:
        """Run analysis on a single well's data."""
        if not self._barcode:
            raise NotImplementedError("_barcode should never be None here")

        data_buf_arr = np.array(data_buf, dtype=np.int64)
        analysis_start = perf_counter()
        force = get_force_signal(
            data_buf_arr,
            self._filter_coefficients,
            self._barcode,
            well_idx,
            compress=False,
            is_beta_2_data=self._beta_2_mode,
        )
        try:
            peak_detection_results = peak_detector(force)
            analysis_dict = live_data_metrics(peak_detection_results, force)
        except PeakDetectionError:
            # Tanner (7/14/21): this dict will be filtered out by downstream elements of analysis stream
            analysis_dict = {-1: None}  # type: ignore
        self._data_analysis_durations.append(_get_secs_since_data_analysis_start(analysis_start))
        return analysis_dict

    def init_streams(self) -> None:
        """Set up data analysis streams for active wells."""
        ends = []
        for well_idx in self._active_wells:
            source = Stream()
            end = (
                source.accumulate(self.append_data, returns_state=True, start=[[], []])
                .filter(lambda data_buf: len(data_buf[0]) >= self.get_buffer_size())
                .map(partial(self.get_twitch_analysis, well_idx=well_idx))
                .accumulate(check_for_new_twitches, returns_state=True, start=0)
                .map(lambda per_twitch_dict, i=well_idx: (i, per_twitch_dict))
            )

            self._data_analysis_streams[well_idx] = (source, end)
            ends.append(end)

        self._data_analysis_stream_zipper = Stream.zip(*ends)
        self._data_analysis_stream_zipper.sink(self._dump_outgoing_well_metrics)

    def set_sampling_period(self, sampling_period: int) -> None:
        if not self._beta_2_mode:
            raise NotImplementedError("Beta 1 device cannot change sampling period")
        sampling_period_us = sampling_period
        self._beta_2_buffer_size = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS * int(
            MICRO_TO_BASE_CONVERSION / sampling_period_us
        )
        self._filter_coefficients = create_filter(BUTTERWORTH_LOWPASS_30_UUID, sampling_period_us)
        self.init_streams()

    def _setup_before_loop(self) -> None:
        super()._setup_before_loop()
        if self._beta_2_mode:
            self.set_sampling_period(DEFAULT_SAMPLING_PERIOD)
            self._check_dirs()
        else:
            self.init_streams()

    def _commands_for_each_run_iteration(self) -> None:
        self._process_next_command_from_main()
        self._handle_incoming_packet()
        if self._beta_2_mode:
            self._check_mag_analysis_statuses()
            return

        if self._is_data_from_each_well_present():
            outgoing_data = self._create_outgoing_beta_1_data()
            self._dump_data_into_queue(outgoing_data)

    def _process_next_command_from_main(self) -> None:
        input_queue = self._comm_from_main_queue
        try:
            communication = input_queue.get_nowait()
        except queue.Empty:
            return

        communication_type = communication["communication_type"]
        if communication_type == "calibration":
            self._calibration_settings = communication["calibration_settings"]
        elif communication_type == "acquisition_manager":
            if communication["command"] == "start_managed_acquisition":
                self._barcode = communication["barcode"]
                if not self._barcode:
                    raise StartManagedAcquisitionWithoutBarcodeError()
                if not self._beta_2_mode:
                    self._end_of_data_stream_reached[0]["mag"] = False
                    self._end_of_data_stream_reached[0]["stim"] = False
                drain_queue(self._board_queues[0][1])
                self._well_offsets = [None] * 24
            elif communication["command"] == "stop_managed_acquisition":
                self._barcode = None
                self._end_of_data_stream_reached[0]["mag"] = True
                self._end_of_data_stream_reached[0]["stim"] = True
                for well_index in range(24):
                    self._data_buffer[well_index] = {"construct_data": None, "ref_data": None}
                self.init_streams()
            elif communication["command"] == "set_sampling_period":
                self.set_sampling_period(communication["sampling_period"])
            else:
                raise UnrecognizedCommandFromMainToDataAnalyzerError(
                    f"Invalid command: {communication['command']} for communication_type: {communication_type}"
                )
            self._comm_to_main_queue.put_nowait(communication)
        elif communication_type == "mag_finding_analysis":
            if not self._beta_2_mode:
                raise NotImplementedError("mag finding analysis does not work with beta 1 data")
            if communication["command"] == "start_mag_analysis":
                recordings = communication["recordings"]
                self._run_magnet_finding_alg(recordings)
            elif communication["command"] == "start_recording_snapshot":
                recording = communication["recording_path"]
                self._start_recording_snapshot_analysis(recording)
            else:
                raise UnrecognizedCommandFromMainToDataAnalyzerError(
                    f"Invalid command: {communication['command']} for communication_type: {communication_type}"
                )
        else:
            raise UnrecognizedCommandFromMainToDataAnalyzerError(communication_type)

    def _handle_incoming_packet(self) -> None:
        input_queue = self._board_queues[0][0]
        try:
            packet = input_queue.get_nowait()
        except queue.Empty:
            return

        data_type = "magnetometer" if not self._beta_2_mode else packet["data_type"]
        if data_type == "magnetometer":
            if self._beta_2_mode and packet["is_first_packet_of_stream"]:
                self._end_of_data_stream_reached[0]["mag"] = False
            if self._end_of_data_stream_reached[0]["mag"]:
                return

            if self._beta_2_mode:
                self._process_beta_2_data(packet)
            else:
                packet["data"][0] *= MICROSECONDS_PER_CENTIMILLISECOND
                if not packet["is_reference_sensor"]:
                    well_idx = packet["well_index"]
                    self._data_analysis_streams[well_idx][0].emit(packet["data"])
                self._load_memory_into_buffer(packet)
        elif data_type == "stimulation":
            if packet["is_first_packet_of_stream"]:
                self._end_of_data_stream_reached[0]["stim"] = False
            if self._end_of_data_stream_reached[0]["stim"]:
                return
            self._process_stim_packet(packet)
        else:
            raise NotImplementedError(f"Invalid data type from File Writer Process: {data_type}")

    def _process_beta_2_data(self, data_dict: Dict[Any, Any]) -> None:
        # flip and normalize data first so FE receives waveform data quickly
        for key, well_dict in data_dict.items():
            # filter out any keys that are not well indices
            if not isinstance(key, int):
                continue
            self._normalize_beta_2_data_for_well(key, well_dict)
        outgoing_data = self._create_outgoing_beta_2_data(data_dict)
        self._dump_data_into_queue(outgoing_data)
        # send data through analysis stream
        for key, well_dict in data_dict.items():
            # filter out any keys that are not well indices
            if not isinstance(key, int):
                continue
            first_channel_data = [data_dict["time_indices"], well_dict[SERIAL_COMM_DEFAULT_DATA_CHANNEL]]
            self._data_analysis_streams[key][0].emit(first_channel_data)
        self._handle_performance_logging()

    def _load_memory_into_buffer(self, data_dict: Dict[Any, Any]) -> None:
        if data_dict["is_reference_sensor"]:
            reverse = False
            for ref in range(3, 6):
                if data_dict["reference_for_wells"] == REF_INDEX_TO_24_WELL_INDEX[ref]:
                    reverse = True
            corresponding_well_indices = sorted(list(data_dict["reference_for_wells"]), reverse=reverse)

            ref_data_len = len(data_dict["data"][0])
            for ref_data_index in range(ref_data_len):
                data_pair = data_dict["data"][:, ref_data_index].reshape((2, 1))
                well_index = corresponding_well_indices[ref_data_index % CONSTRUCT_SENSORS_PER_REF_SENSOR]
                if self._data_buffer[well_index]["ref_data"] is None:
                    # Tanner (9/1/20): Using lists here since it is faster to extend a list than concatenate two arrays
                    self._data_buffer[well_index]["ref_data"] = (
                        data_pair[0].tolist(),
                        data_pair[1].tolist(),
                    )
                else:
                    self._data_buffer[well_index]["ref_data"][0].extend(data_pair[0])
                    self._data_buffer[well_index]["ref_data"][1].extend(data_pair[1])
        else:
            well_index = data_dict["well_index"]
            if self._data_buffer[well_index]["construct_data"] is None:
                self._data_buffer[well_index]["construct_data"] = (
                    data_dict["data"][0].tolist(),
                    data_dict["data"][1].tolist(),
                )
            else:
                self._data_buffer[well_index]["construct_data"][0].extend(data_dict["data"][0])
                self._data_buffer[well_index]["construct_data"][1].extend(data_dict["data"][1])

    def is_buffer_full(self) -> bool:
        """Only used in unit tests at the moment."""
        for data_pair in self._data_buffer.values():
            if data_pair["construct_data"] is None or data_pair["ref_data"] is None:
                return False
            construct_duration = data_pair["construct_data"][0][-1] - data_pair["construct_data"][0][0]
            ref_duration = data_pair["ref_data"][0][-1] - data_pair["ref_data"][0][0]
            if (
                construct_duration < DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
                or ref_duration < DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
            ):
                return False
        return True

    def _is_data_from_each_well_present(self) -> bool:
        for data_pair in self._data_buffer.values():
            if data_pair["construct_data"] is None or data_pair["ref_data"] is None:
                return False
        return True

    def _create_outgoing_beta_2_data(self, data_dict: Dict[Any, Any]) -> Dict[str, Any]:
        if not self._barcode:
            raise NotImplementedError("_barcode should never be None here")

        start = perf_counter()
        waveform_data_points: Dict[int, Dict[str, List[float]]] = dict()
        for well_idx in range(24):
            default_channel_data = data_dict[well_idx][SERIAL_COMM_DEFAULT_DATA_CHANNEL]
            force_data = get_force_signal(
                np.array([data_dict["time_indices"], default_channel_data], np.int64),
                self._filter_coefficients,
                self._barcode,
                well_idx,
            )

            # convert arrays to lists for json conversion later
            waveform_data_points[well_idx] = {
                "x_data_points": force_data[0].tolist(),
                "y_data_points": (force_data[1] * MICRO_TO_BASE_CONVERSION).tolist(),
            }

        outgoing_data_creation_dur_secs = _get_secs_since_data_creation_start(start)
        self._outgoing_data_creation_durations.append(outgoing_data_creation_dur_secs)

        # create formatted dict
        outgoing_data: Dict[str, Any] = {
            "waveform_data": {"basic_data": {"waveform_data_points": waveform_data_points}},
            "earliest_timepoint": data_dict["time_indices"][0].item(),
            "latest_timepoint": data_dict["time_indices"][-1].item(),
            "num_data_points": len(data_dict["time_indices"]),
        }
        return outgoing_data

    def _normalize_beta_2_data_for_well(self, well_idx: int, well_dict: Dict[Any, Any]) -> None:
        if self._well_offsets[well_idx] is None:
            self._well_offsets[well_idx] = min(well_dict[SERIAL_COMM_DEFAULT_DATA_CHANNEL])
        well_data = fix_dropped_samples(well_dict[SERIAL_COMM_DEFAULT_DATA_CHANNEL])
        well_dict[SERIAL_COMM_DEFAULT_DATA_CHANNEL] = (
            (well_data.astype(np.int32) - self._well_offsets[well_idx]) + MEMSIC_CENTER_OFFSET
        ).astype(np.uint16)

    def _create_outgoing_beta_1_data(self) -> Dict[str, Any]:
        if not self._barcode:
            raise NotImplementedError("_barcode should never be None here")

        outgoing_data_creation_start = perf_counter()
        outgoing_data: Dict[str, Any] = {"waveform_data": {"basic_data": {"waveform_data_points": None}}}

        basic_waveform_data_points = dict()
        earliest_timepoint: Optional[int] = None
        latest_timepoint: Optional[int] = None
        for well_index in range(24):
            self._normalize_beta_1_data_for_well(well_index)
            compressed_data = get_force_signal(
                self._data_buffer[well_index]["construct_data"],
                self._filter_coefficients,
                self._barcode,
                well_index,
                is_beta_2_data=False,
            )

            basic_waveform_data_points[well_index] = {
                "x_data_points": compressed_data[0].tolist(),
                "y_data_points": (compressed_data[1] * MICRO_TO_BASE_CONVERSION).tolist(),
            }  # Tanner (4/23/20): json cannot by default serialize numpy arrays, so we must convert to a list
            if earliest_timepoint is None or compressed_data[0][0] < earliest_timepoint:
                # Tanner (4/23/20): json cannot by default serialize type numpy types, so we must use the item as native type
                earliest_timepoint = compressed_data[0][0].item()
            if latest_timepoint is None or compressed_data[0][-1] > latest_timepoint:
                # Tanner (4/23/20): json cannot by default serialize numpy types, so we must use the item as native type
                latest_timepoint = compressed_data[0][-1].item()
            self._data_buffer[well_index] = {"construct_data": None, "ref_data": None}
        outgoing_data_creation_dur = perf_counter() - outgoing_data_creation_start
        self._outgoing_data_creation_durations.append(outgoing_data_creation_dur)
        self._handle_performance_logging()

        outgoing_data["waveform_data"]["basic_data"]["waveform_data_points"] = basic_waveform_data_points
        outgoing_data["earliest_timepoint"] = earliest_timepoint
        outgoing_data["latest_timepoint"] = latest_timepoint
        return outgoing_data

    def _normalize_beta_1_data_for_well(self, well_idx: int) -> None:
        tissue_data = np.array(self._data_buffer[well_idx]["construct_data"], dtype=np.int32)
        if self._well_offsets[well_idx] is None:
            self._well_offsets[well_idx] = max(tissue_data[1])
        tissue_data[1] = (tissue_data[1] - self._well_offsets[well_idx]) * -1
        self._data_buffer[well_idx]["construct_data"] = tissue_data

    def _process_stim_packet(self, stim_packet: Dict[Any, Any]) -> None:
        # Tanner (6/21/21): converting to json may not be necessary for outgoing data, check with frontend
        outgoing_data_json = json.dumps(
            {
                well_idx: stim_status_arr.tolist()
                for well_idx, stim_status_arr in stim_packet["well_statuses"].items()
            }
        )
        outgoing_msg = {"data_type": "stimulation_data", "data_json": outgoing_data_json}
        self._board_queues[0][1].put_nowait(outgoing_msg)

    def _run_magnet_finding_alg(self, recordings: List[str]) -> None:
        # Tanner (9/16/22): assuming these values are needed in the FE, so keeping them here after refactor
        self._mag_finder_thread_dict = {"recordings": recordings, "output_dir": self._mag_finder_output_dir}

        self._mag_finder_worker_thread = ErrorCatchingThread(
            target=run_magnet_finding_alg,
            args=(self._mag_finder_thread_dict, recordings, self._mag_finder_output_dir),
        )
        self._mag_finder_worker_thread.start()

    def _check_mag_analysis_statuses(self) -> None:
        if not self._mag_finder_worker_thread or self._mag_finder_worker_thread.is_alive():
            return

        if self._mag_finder_worker_thread is None:
            raise NotImplementedError("_fw_update_thread_dict should never be None here")

        self._mag_finder_worker_thread.join()

        outgoing_msg = {
            "data_type": "data_analysis_complete",
            "data_json": json.dumps(self._mag_finder_thread_dict),
        }
        self._comm_to_main_queue.put_nowait(
            {"communication_type": "mag_analysis_complete", "content": outgoing_msg}
        )

        # clear values
        self._mag_finder_worker_thread = None
        self._mag_finder_thread_dict = None

    def _start_recording_snapshot_analysis(self, recording_path: str) -> None:
        # TODO (9/16/22): this should be run in a thread so that this process is still responsive to main
        snapshot_dfs = run_magnet_finding_alg({}, [recording_path], end_time=5)
        snapshot_dict = snapshot_dfs[0].to_dict()
        snapshot_list = [list(snapshot_dict[key].values()) for key in snapshot_dict.keys()]

        mag_analysis_msg = {"time": snapshot_list[0], "force": snapshot_list[1:]}
        outgoing_msg = {"data_type": "recording_snapshot", "data_json": json.dumps(mag_analysis_msg)}

        self._comm_to_main_queue.put_nowait(
            {"communication_type": "mag_analysis_complete", "content": outgoing_msg}
        )

    def _handle_performance_logging(self) -> None:  # pragma: no cover
        if logging.DEBUG >= self._logging_level:
            performance_metrics: Dict[str, Any] = {"communication_type": "performance_metrics"}
            tracker = self.reset_performance_tracker()
            performance_metrics["longest_iterations"] = sorted(tracker["longest_iterations"])
            performance_metrics["percent_use"] = tracker["percent_use"]
            performance_metrics["data_creation_duration"] = self._outgoing_data_creation_durations[-1]

            if len(self._percent_use_values) > 1:
                performance_metrics["percent_use_metrics"] = self.get_percent_use_metrics()
            name_measurement_list = list()
            if len(self._outgoing_data_creation_durations) >= 1:
                name_measurement_list.append(
                    ("data_creation_duration_metrics", self._outgoing_data_creation_durations)
                )
            if len(self._data_analysis_durations) >= 1:
                name_measurement_list.append(
                    ("data_analysis_duration_metrics", self._data_analysis_durations)
                )

            da_measurements: List[Union[int, float]]
            for name, da_measurements in name_measurement_list:
                performance_metrics[name] = create_metrics_stats(da_measurements)
            put_log_message_into_queue(
                logging.INFO,
                performance_metrics,
                self._comm_to_main_queue,
                self.get_logging_level(),
            )
            if len(self._outgoing_data_creation_durations) >= PERFOMANCE_LOGGING_PERIOD_SECS:
                self._reset_performance_tracking_values()
        else:
            self._reset_performance_tracking_values()

    def _dump_data_into_queue(self, outgoing_data: Dict[str, Any]) -> None:
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")
        if self._beta_2_mode:
            num_data_points = outgoing_data["num_data_points"]
        else:
            num_data_points = (
                outgoing_data["latest_timepoint"] - outgoing_data["earliest_timepoint"]
            ) // CONSTRUCT_SENSOR_SAMPLING_PERIOD
        self._comm_to_main_queue.put_nowait(
            {
                "communication_type": "data_available",
                "timestamp": timestamp,
                "num_data_points": num_data_points,
                "earliest_timepoint": outgoing_data["earliest_timepoint"],
                "latest_timepoint": outgoing_data["latest_timepoint"],
            }
        )
        # Tanner (6/21/21): converting to json may no longer be necessary here
        outgoing_data_json = json.dumps(outgoing_data)
        outgoing_msg = {"data_type": "waveform_data", "data_json": outgoing_data_json}
        self._board_queues[0][1].put_nowait(outgoing_msg)

    def _dump_outgoing_well_metrics(self, well_tuples: Tuple[Tuple[int, Dict[int, Any]], ...]) -> None:
        outgoing_metrics: Dict[int, Dict[str, List[Any]]] = dict()
        for well_idx, per_twitch_dict in well_tuples:
            if not per_twitch_dict:
                # Tanner (7/15/21): in Beta 1 mode, wells with no analyzable data will still be passed through analysis stream, so catching the empty metric dicts here
                continue
            outgoing_metrics[well_idx] = {str(AMPLITUDE_UUID): [], str(TWITCH_FREQUENCY_UUID): []}
            for twitch_metric_dict in per_twitch_dict.values():
                for metric_id, metric_val in twitch_metric_dict.items():
                    outgoing_metrics[well_idx][str(metric_id)].append(metric_val)

        outgoing_metrics_json = json.dumps(outgoing_metrics)
        outgoing_msg = {"data_type": "twitch_metrics", "data_json": outgoing_metrics_json}
        self._board_queues[0][1].put_nowait(outgoing_msg)

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items: Dict[str, Any] = dict()
        for i, board in enumerate(self._board_queues):
            queue_items[f"board_{i}"] = _drain_board_queues(board)
        queue_items["from_main_to_data_analyzer"] = drain_queue(self._comm_from_main_queue)
        queue_items["from_data_analyzer_to_main"] = drain_queue(self._comm_to_main_queue)
        return queue_items
