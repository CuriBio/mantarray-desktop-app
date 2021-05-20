# -*- coding: utf-8 -*-
"""Analyzing data coming from board."""
from __future__ import annotations

import datetime
import json
import logging
from multiprocessing import Queue
import queue
from statistics import stdev
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from mantarray_waveform_analysis import BUTTERWORTH_LOWPASS_30_UUID
from mantarray_waveform_analysis import PipelineTemplate
from nptyping import NDArray
import numpy as np
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import put_log_message_into_queue

from .constants import ADC_GAIN
from .constants import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from .constants import CONSTRUCT_SENSORS_PER_REF_SENSOR
from .constants import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from .constants import MILLIVOLTS_PER_VOLT
from .constants import REF_INDEX_TO_24_WELL_INDEX
from .constants import REFERENCE_VOLTAGE
from .exceptions import UnrecognizedCommandToInstrumentError
from .exceptions import UnrecognizedCommTypeFromMainToDataAnalyzerError


def convert_24_bit_codes_to_voltage(codes: NDArray[int]) -> NDArray[float]:
    """Convert 'signed' 24-bit values from an ADC to measured voltage."""
    voltages = codes.astype(np.float32) * 2 ** -23 * (REFERENCE_VOLTAGE / ADC_GAIN) * MILLIVOLTS_PER_VOLT
    return voltages


def _drain_board_queues(  # pylint: disable=duplicate-code
    board: Tuple[
        Queue[Any],  # pylint: disable=unsubscriptable-object
        Queue[Any],  # pylint: disable=unsubscriptable-object
    ],
) -> Dict[str, List[Any]]:  # pylint: disable=duplicate-code
    board_dict = dict()
    board_dict["file_writer_to_data_analyzer"] = drain_queue(board[0])
    board_dict["outgoing_data"] = drain_queue(board[1])
    return board_dict


class DataAnalyzerProcess(InfiniteProcess):
    """Process that analyzes data.

    Args:
        board_queues: A tuple (the max number of board connections should be predefined, so not a mutable list) of tuples of 2 queues. The first queue is for incoming data for that board that should be analyzed. The second queue is for finalized outgoing data to main process
        from_main_queue: a queue of communication from the main process
        to_main_queue: a queue to put general communication back to main
        fatal_error_reporter: a queue to report fatal errors back to the main process
    """

    # pylint: disable=duplicate-code # Eli (12/8/20): I can't figure out how to use mypy type aliases correctly...but the type definitions are triggering duplicate code warnings
    def __init__(  # pylint: disable=duplicate-code # Eli (12/8/20): I can't figure out how to use mypy type aliases correctly...but the type definitions are triggering duplicate code warnings
        self,
        the_board_queues: Tuple[
            Tuple[
                Queue[Any],  # pylint: disable=unsubscriptable-object
                Queue[  # pylint: disable=unsubscriptable-object,duplicate-code # https://github.com/PyCQA/pylint/issues/1498
                    Any
                ],  # pylint: disable=duplicate-code
            ],
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ],
        comm_from_main_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        comm_to_main_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        fatal_error_reporter: Queue[Tuple[Exception, str]],  # pylint: disable=unsubscriptable-object
        logging_level: int = logging.INFO,
        beta_2_mode: bool = False,
    ):
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._board_queues = the_board_queues
        self._comm_from_main_queue = comm_from_main_queue
        self._comm_to_main_queue = comm_to_main_queue
        self._calibration_settings: Union[None, Dict[Any, Any]] = None
        self._is_managed_acquisition_running = False
        self._data_buffer: Dict[int, Dict[str, Any]] = dict()
        self._outgoing_data_creation_durations: List[float] = list()
        for index in range(24):
            self._data_buffer[index] = {"construct_data": None, "ref_data": None}
        self._pipeline_template = PipelineTemplate(
            noise_filter_uuid=BUTTERWORTH_LOWPASS_30_UUID,
            tissue_sampling_period=CONSTRUCT_SENSOR_SAMPLING_PERIOD,
        )
        self._beta_2_mode = beta_2_mode

    def get_calibration_settings(self) -> Union[None, Dict[Any, Any]]:
        return self._calibration_settings

    def _commands_for_each_run_iteration(self) -> None:
        self._process_next_command_from_main()
        # TODO Tanner (6/30/20): Apply sensor sensitivity calibration settings once they are fleshed out.  # Tanner (5/19/21): This TODO may be unnecessary now
        self._load_memory_into_buffer()
        if self._is_buffer_full():
            outgoing_data = self._create_outgoing_data()
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
        elif communication_type == "to_instrument":
            if communication["command"] == "start_managed_acquisition":
                self._is_managed_acquisition_running = True
                drain_queue(self._board_queues[0][1])
            elif communication["command"] == "stop_managed_acquisition":
                self._is_managed_acquisition_running = False
                for well_index in range(24):
                    self._data_buffer[well_index] = {
                        "construct_data": None,
                        "ref_data": None,
                    }
            else:
                raise UnrecognizedCommandToInstrumentError(communication["command"])
            self._comm_to_main_queue.put_nowait(communication)
        else:
            raise UnrecognizedCommTypeFromMainToDataAnalyzerError(communication_type)

    def _load_memory_into_buffer(self) -> None:
        input_queue = self._board_queues[0][0]
        try:
            data_dict = input_queue.get_nowait()
        except queue.Empty:
            return

        if not self._is_managed_acquisition_running:
            return

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

    def _create_outgoing_data(self) -> Dict[str, Any]:
        outgoing_data_creation_start = time.perf_counter()
        outgoing_data: Dict[str, Any] = {
            "waveform_data": {
                "basic_data": {"waveform_data_points": None},
                # TODO Tanner (4/21/20): Add data_metrics once possible
                "data_metrics": dict(),
            },
        }

        basic_waveform_data_points = dict()
        earliest_timepoint: Optional[int] = None
        latest_timepoint: Optional[int] = None
        analysis_durations = list()
        for well_index in range(24):
            start = time.perf_counter()
            pipeline = self._pipeline_template.create_pipeline()
            pipeline.load_raw_gmr_data(
                np.array(self._data_buffer[well_index]["construct_data"], dtype=np.int32),
                np.array(self._data_buffer[well_index]["ref_data"], dtype=np.int32),
            )
            compressed_data = pipeline.get_compressed_displacement()
            analysis_dur = time.perf_counter() - start
            analysis_durations.append(analysis_dur)

            basic_waveform_data_points[well_index] = {
                "x_data_points": compressed_data[0].tolist(),
                "y_data_points": (compressed_data[1] * MILLIVOLTS_PER_VOLT).tolist(),
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
        outgoing_data_creation_dur = time.perf_counter() - outgoing_data_creation_start
        self._outgoing_data_creation_durations.append(outgoing_data_creation_dur)
        self._handle_performance_logging(analysis_durations)

        outgoing_data["waveform_data"]["basic_data"]["waveform_data_points"] = basic_waveform_data_points
        outgoing_data["earliest_timepoint"] = earliest_timepoint
        outgoing_data["latest_timepoint"] = latest_timepoint
        return outgoing_data

    def _handle_performance_logging(self, analysis_durations: List[float]) -> None:
        performance_metrics: Dict[str, Any] = {
            "communication_type": "performance_metrics",
        }
        tracker = self.reset_performance_tracker()
        performance_metrics["longest_iterations"] = sorted(tracker["longest_iterations"])
        performance_metrics["percent_use"] = tracker["percent_use"]
        performance_metrics["data_creating_duration"] = self._outgoing_data_creation_durations[-1]

        name_measurement_list = [("analysis_durations", analysis_durations)]
        if len(self._percent_use_values) > 1:
            performance_metrics["percent_use_metrics"] = self.get_percent_use_metrics()
        if len(self._outgoing_data_creation_durations) > 1:
            name_measurement_list.append(
                (
                    "data_creating_duration_metrics",
                    self._outgoing_data_creation_durations,
                )
            )
        da_measurements: List[
            Union[int, float]
        ]  # Tanner (5/28/20): This type annotation and the 'ignore' on the following line are necessary for mypy to not incorrectly type this variable
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
        outgoing_data_json = json.dumps(outgoing_data)
        self._board_queues[0][1].put_nowait(outgoing_data_json)

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items: Dict[str, Any] = dict()
        for i, board in enumerate(self._board_queues):
            queue_items[f"board_{i}"] = _drain_board_queues(board)
        queue_items["from_main_to_data_analyzer"] = drain_queue(self._comm_from_main_queue)
        queue_items["from_data_analyzer_to_main"] = drain_queue(self._comm_to_main_queue)
        return queue_items
