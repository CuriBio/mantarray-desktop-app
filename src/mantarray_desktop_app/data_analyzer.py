# -*- coding: utf-8 -*-
"""Analyzing data coming from board."""
from __future__ import annotations

import datetime
import json
import logging
from multiprocessing import Queue
from multiprocessing import queues as mpqueues
import queue
from statistics import stdev
from time import perf_counter
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from mantarray_waveform_analysis import AMPLITUDE_UUID
from mantarray_waveform_analysis import BUTTERWORTH_LOWPASS_30_UUID
from mantarray_waveform_analysis import PipelineTemplate
from mantarray_waveform_analysis import TWITCH_FREQUENCY_UUID
from mantarray_waveform_analysis.exceptions import PeakDetectionError
from nptyping import NDArray
import numpy as np
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import put_log_message_into_queue
from streamz import Stream

from .constants import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from .constants import CONSTRUCT_SENSORS_PER_REF_SENSOR
from .constants import DATA_ANALYZER_BETA_1_BUFFER_SIZE
from .constants import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from .constants import MICRO_TO_BASE_CONVERSION
from .constants import MICROSECONDS_PER_CENTIMILLISECOND
from .constants import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from .constants import REF_INDEX_TO_24_WELL_INDEX
from .constants import SERIAL_COMM_DEFAULT_DATA_CHANNEL
from .exceptions import UnrecognizedCommandFromMainToDataAnalyzerError
from .utils import get_active_wells_from_config


def _get_secs_since_data_creation_start(start: float) -> float:
    return perf_counter() - start


def _get_secs_since_data_analysis_start(start: float) -> float:
    return perf_counter() - start


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
        logging_level: int = logging.INFO,
        beta_2_mode: bool = False,
    ):
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._beta_2_mode = beta_2_mode
        self._board_queues = the_board_queues
        self._comm_from_main_queue = comm_from_main_queue
        self._comm_to_main_queue = comm_to_main_queue
        # performance tracking values
        self._outgoing_data_creation_durations: List[float] = list()
        self._data_analysis_durations: List[float] = list()
        # data streaming values
        self._end_of_data_stream_reached: List[Optional[bool]] = [False] * len(self._board_queues)
        self._data_buffer: Dict[int, Dict[str, Any]] = dict()
        for well_idx in range(24):
            self._data_buffer[well_idx] = {"construct_data": None, "ref_data": None}
        # data analysis items
        self._data_analysis_streams: Dict[int, Tuple[Stream, Stream]] = dict()
        self._data_analysis_stream_zipper: Optional[Stream] = None
        self._active_wells: List[int] = list(range(24))
        self._pipeline_template = PipelineTemplate(
            noise_filter_uuid=BUTTERWORTH_LOWPASS_30_UUID,
            tissue_sampling_period=CONSTRUCT_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND,
        )
        # Beta 1 items
        self._well_offsets: List[Optional[int]] = [None] * 24
        self._calibration_settings: Union[None, Dict[Any, Any]] = None
        # Beta 2 items
        self._beta_2_buffer_size: Optional[int] = None

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

    def get_pipeline_template(self) -> PipelineTemplate:
        return self._pipeline_template

    def get_calibration_settings(self) -> Union[None, Dict[Any, Any]]:
        if self._beta_2_mode:
            raise NotImplementedError("Beta 2 mode does not currently have calibration settings")
        return self._calibration_settings

    def get_active_wells(self) -> List[int]:
        return self._active_wells

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

    def get_pipeline_analysis(self, data_buf: List[List[int]]) -> Dict[Any, Any]:
        """Run analysis on a single well's data."""
        data_buf_arr = np.array(data_buf, dtype=np.int64)
        pipeline = self._pipeline_template.create_pipeline()
        # Tanner (7/14/21): reference data is currently unused by waveform analysis package, so sending zero array instead
        pipeline.load_raw_magnetic_data(data_buf_arr, np.zeros(data_buf_arr.shape))
        analysis_start = perf_counter()
        try:
            analysis_dict = pipeline.get_force_data_metrics(
                metrics_to_create=[AMPLITUDE_UUID, TWITCH_FREQUENCY_UUID]
            )[0]
        except PeakDetectionError:
            # Tanner (7/14/21): this dict will be filtered out by downstream elements of analysis stream
            analysis_dict = {-1: None}
        self._data_analysis_durations.append(_get_secs_since_data_analysis_start(analysis_start))
        return analysis_dict  # type: ignore

    def init_streams(self) -> None:
        """Set up data analysis streams for active wells."""
        ends = []
        for well_idx in self._active_wells:
            source = Stream()
            end = (
                source.accumulate(self.append_data, returns_state=True, start=[[], []])
                .filter(lambda data_buf: len(data_buf[0]) >= self.get_buffer_size())
                .map(self.get_pipeline_analysis)
                .accumulate(check_for_new_twitches, returns_state=True, start=0)
                .map(lambda per_twitch_dict, i=well_idx: (i, per_twitch_dict))
            )

            self._data_analysis_streams[well_idx] = (source, end)
            ends.append(end)

        self._data_analysis_stream_zipper = Stream.zip(*ends)
        self._data_analysis_stream_zipper.sink(self._dump_outgoing_well_metrics)

    def _setup_before_loop(self) -> None:
        super()._setup_before_loop()
        self.init_streams()

    def _commands_for_each_run_iteration(self) -> None:
        self._process_next_command_from_main()
        self._handle_incoming_packet()

        if self._beta_2_mode:
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
                if not self._beta_2_mode:
                    self._end_of_data_stream_reached[0] = False
                drain_queue(self._board_queues[0][1])
                self._well_offsets = [None] * 24
            elif communication["command"] == "stop_managed_acquisition":
                self._end_of_data_stream_reached[0] = True
                for well_index in range(24):
                    self._data_buffer[well_index] = {
                        "construct_data": None,
                        "ref_data": None,
                    }
                self.init_streams()
            elif communication["command"] == "change_magnetometer_config":
                if not self._beta_2_mode:
                    raise NotImplementedError("Beta 1 device does not have a magnetometer config")
                self._active_wells = get_active_wells_from_config(communication["magnetometer_config"])

                sampling_period_us = communication["sampling_period"]
                self._beta_2_buffer_size = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS * int(
                    MICRO_TO_BASE_CONVERSION / sampling_period_us
                )
                self._pipeline_template = PipelineTemplate(
                    noise_filter_uuid=BUTTERWORTH_LOWPASS_30_UUID,
                    # TODO Tanner (8/4/21): for some reason sampling periods > 16000 µs cause errors when creating filters. Need to update waveform analysis package before they will be usable
                    tissue_sampling_period=sampling_period_us,
                )
                self.init_streams()
            else:
                raise UnrecognizedCommandFromMainToDataAnalyzerError(
                    f"Invalid command: {communication['command']} for communication_type: {communication_type}"
                )
            self._comm_to_main_queue.put_nowait(communication)
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
                self._end_of_data_stream_reached[0] = False
            if self._end_of_data_stream_reached[0]:
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
            self._process_stim_packet(packet)
        else:
            raise NotImplementedError(f"Invalid data type from File Writer Process: {data_type}")

    def _process_beta_2_data(self, data_dict: Dict[Any, Any]) -> None:
        outgoing_data = self._create_outgoing_beta_2_data(data_dict)
        self._dump_data_into_queue(outgoing_data)
        for key, well_dict in data_dict.items():
            if not isinstance(key, int):
                continue
            first_channel_data = [
                data_dict["time_indices"],
                well_dict[SERIAL_COMM_DEFAULT_DATA_CHANNEL],
            ]
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

    def _is_buffer_full(self) -> bool:
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
        start = perf_counter()
        waveform_data_points: Dict[int, Dict[str, List[float]]] = dict()
        for well_idx in range(24):
            default_channel_data = data_dict[well_idx][SERIAL_COMM_DEFAULT_DATA_CHANNEL]
            pipeline = self._pipeline_template.create_pipeline()
            pipeline.load_raw_magnetic_data(
                np.array([data_dict["time_indices"], default_channel_data], np.int64),
                np.zeros((2, len(default_channel_data))),
            )
            force_data = pipeline.get_compressed_force()

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

    def _create_outgoing_beta_1_data(self) -> Dict[str, Any]:
        outgoing_data_creation_start = perf_counter()
        outgoing_data: Dict[str, Any] = {"waveform_data": {"basic_data": {"waveform_data_points": None}}}

        basic_waveform_data_points = dict()
        earliest_timepoint: Optional[int] = None
        latest_timepoint: Optional[int] = None
        for well_index in range(24):
            self._normalize_beta_1_data_for_well(well_index)
            pipeline = self._pipeline_template.create_pipeline()
            pipeline.load_raw_magnetic_data(
                self._data_buffer[well_index]["construct_data"],
                np.array(self._data_buffer[well_index]["ref_data"], dtype=np.int32),
            )
            compressed_data = pipeline.get_compressed_force()

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
            self._data_buffer[well_index] = {
                "construct_data": None,
                "ref_data": None,
            }
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
        outgoing_msg = {"data_type": "stimulation", "data_json": outgoing_data_json}
        self._board_queues[0][1].put_nowait(outgoing_msg)

    def _handle_performance_logging(self) -> None:
        performance_metrics: Dict[str, Any] = {"communication_type": "performance_metrics"}
        tracker = self.reset_performance_tracker()
        performance_metrics["longest_iterations"] = sorted(tracker["longest_iterations"])
        performance_metrics["percent_use"] = tracker["percent_use"]
        performance_metrics["data_creation_duration"] = self._outgoing_data_creation_durations[-1]

        if len(self._percent_use_values) > 1:
            performance_metrics["percent_use_metrics"] = self.get_percent_use_metrics()
        name_measurement_list = list()
        if len(self._outgoing_data_creation_durations) > 1:
            name_measurement_list.append(
                (
                    "data_creation_duration_metrics",
                    self._outgoing_data_creation_durations,
                )
            )
        if len(self._data_analysis_durations) > 1:
            name_measurement_list.append(
                (
                    "data_analysis_duration_metrics",
                    self._data_analysis_durations,
                )
            )

        da_measurements: List[
            Union[int, float]
        ]  # Tanner (5/28/20): This type annotation is necessary for mypy to not incorrectly type this variable
        for name, da_measurements in name_measurement_list:
            performance_metrics[name] = {
                "max": max(da_measurements),
                "min": min(da_measurements),
                "stdev": round(stdev(da_measurements), 6),
                "mean": round(sum(da_measurements) / len(da_measurements), 6),
            }
        put_log_message_into_queue(
            logging.INFO,
            performance_metrics,
            self._comm_to_main_queue,
            self.get_logging_level(),
        )

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
            outgoing_metrics[well_idx] = {
                str(AMPLITUDE_UUID): [],
                str(TWITCH_FREQUENCY_UUID): [],
            }
            for twitch_metric_dict in per_twitch_dict.values():
                for metric_id, metric_val in twitch_metric_dict.items():
                    if metric_id == AMPLITUDE_UUID:
                        # convert force amplitude from Newtons to micro Newtons
                        metric_val *= MICRO_TO_BASE_CONVERSION
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
