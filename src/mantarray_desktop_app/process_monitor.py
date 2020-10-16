# -*- coding: utf-8 -*-
"""Docstring."""
from __future__ import annotations

import logging
from multiprocessing import Queue
import queue
import threading
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple

from stdlib_utils import InfiniteProcess
from stdlib_utils import InfiniteThread

from .constants import ADC_CH_TO_24_WELL_INDEX
from .constants import ADC_CH_TO_IS_REF_SENSOR
from .constants import ADC_OFFSET_DESCRIPTION_TAG
from .constants import BUFFERING_STATE
from .constants import CALIBRATED_STATE
from .constants import INSTRUMENT_INITIALIZING_STATE
from .constants import LIVE_VIEW_ACTIVE_STATE
from .constants import SERVER_INITIALIZING_STATE
from .constants import SERVER_READY_STATE
from .process_manager import MantarrayProcessesManager

logger = logging.getLogger(__name__)


class MantarrayProcessesMonitor(InfiniteThread):
    """Monitors the responses from all subprocesses.

    The subprocesses must be started separately. This allows better
    separation and unit testing.
    """

    def __init__(
        self,
        values_to_share_to_server: Dict[str, Any],
        process_manager: MantarrayProcessesManager,
        fatal_error_reporter: queue.Queue[
            str
        ],  # pylint: disable=unsubscriptable-object
        the_lock: threading.Lock,
        boot_up_after_processes_start: bool = False,
    ) -> None:
        super().__init__(fatal_error_reporter, lock=the_lock)
        self._values_to_share_to_server = values_to_share_to_server
        self._process_manager = process_manager
        self._boot_up_after_processes_start = boot_up_after_processes_start
        self._data_dump_buffer_size = 0

    def _commands_for_each_run_iteration(self) -> None:
        """Execute additional commands inside the run loop."""
        if (
            self._values_to_share_to_server["system_status"]
            == SERVER_INITIALIZING_STATE
        ):
            self._check_subprocess_start_up_statuses()
        elif (
            self._values_to_share_to_server["system_status"] == SERVER_READY_STATE
            and self._boot_up_after_processes_start
        ):
            self._values_to_share_to_server[
                "system_status"
            ] = INSTRUMENT_INITIALIZING_STATE
            self._process_manager.boot_up_instrument()

        process_manager = self._process_manager
        ok_comm_to_main = process_manager.get_communication_queue_from_ok_comm_to_main(
            0
        )
        if not ok_comm_to_main.empty():
            communication = ok_comm_to_main.get_nowait()
            # Eli (2/12/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
            msg = f"Communication from the OpalKelly Controller: {communication}"
            with self._lock:
                logger.info(msg)
            communication_type = communication["communication_type"]

            if "command" in communication:
                command = communication["command"]

            if communication_type == "acquisition_manager":
                if command == "start_managed_acquisition":
                    self._values_to_share_to_server[
                        "utc_timestamps_of_beginning_of_data_acquisition"
                    ] = [communication["timestamp"]]
                if command == "stop_managed_acquisition":
                    self._values_to_share_to_server["system_status"] = CALIBRATED_STATE
                    self._data_dump_buffer_size = 0
            elif communication_type == "board_connection_status_change":
                board_idx = communication["board_index"]
                self._values_to_share_to_server[
                    "in_simulation_mode"
                ] = not communication["is_connected"]
                self._values_to_share_to_server["mantarray_serial_number"] = {
                    board_idx: communication["mantarray_serial_number"]
                }
                self._values_to_share_to_server["mantarray_nickname"] = {
                    board_idx: communication["mantarray_nickname"]
                }
                self._values_to_share_to_server["xem_serial_number"] = {
                    board_idx: communication["xem_serial_number"]
                }
            elif communication_type == "boot_up_instrument":
                board_idx = communication["board_index"]
                self._values_to_share_to_server["main_firmware_version"] = {
                    board_idx: communication["main_firmware_version"]
                }
                self._values_to_share_to_server["sleep_firmware_version"] = {
                    board_idx: communication["sleep_firmware_version"]
                }
            elif communication_type == "xem_scripts":
                if "status_update" in communication:
                    self._values_to_share_to_server["system_status"] = communication[
                        "status_update"
                    ]
                if "adc_gain" in communication:
                    self._values_to_share_to_server["adc_gain"] = communication[
                        "adc_gain"
                    ]
                description = communication.get("description", "")
                if ADC_OFFSET_DESCRIPTION_TAG in description:
                    parsed_description = description.split("__")
                    adc_index = int(parsed_description[1][-1])
                    ch_index = int(parsed_description[2][-1])
                    offset_val = communication["wire_out_value"]
                    self._add_offset_to_shared_dict(adc_index, ch_index, offset_val)

        file_writer_to_main = (
            process_manager.get_communication_queue_from_file_writer_to_main()
        )
        if not file_writer_to_main.empty():
            communication = file_writer_to_main.get_nowait()
            # Eli (2/12/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
            msg = f"Communication from the File Writer: {communication}"
            with self._lock:
                logger.info(msg)

        data_analyzer_to_main = (
            process_manager.get_communication_queue_from_data_analyzer_to_main()
        )
        if not data_analyzer_to_main.empty():
            communication = data_analyzer_to_main.get_nowait()
            # Eli (2/12/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
            msg = f"Communication from the Data Analyzer: {communication}"
            with self._lock:
                logger.info(msg)

            communication_type = communication["communication_type"]
            if communication_type == "data_available":
                if self._values_to_share_to_server["system_status"] == BUFFERING_STATE:
                    self._data_dump_buffer_size += 1
                    if self._data_dump_buffer_size == 2:
                        self._values_to_share_to_server[
                            "system_status"
                        ] = LIVE_VIEW_ACTIVE_STATE

        for this_error_queue, this_process in (
            (
                process_manager.get_ok_communication_error_queue(),
                process_manager.get_ok_comm_process(),
            ),
            (
                process_manager.get_file_writer_error_queue(),
                process_manager.get_file_writer_process(),
            ),
            (
                process_manager.get_data_analyzer_error_queue(),
                process_manager.get_data_analyzer_process(),
            ),
        ):
            if this_error_queue.empty() is False:
                self._handle_error_in_subprocess(this_process, this_error_queue)

    def _check_subprocess_start_up_statuses(self) -> None:
        process_manager = self._process_manager
        shared_values_dict = self._values_to_share_to_server
        processes: Tuple[InfiniteProcess, InfiniteProcess, InfiniteProcess] = (
            process_manager.get_ok_comm_process(),
            process_manager.get_file_writer_process(),
            process_manager.get_data_analyzer_process(),
        )
        if all(p.is_start_up_complete() for p in processes):
            shared_values_dict["system_status"] = SERVER_READY_STATE

    def _add_offset_to_shared_dict(
        self, adc_index: int, ch_index: int, offset_val: int
    ) -> None:
        if "adc_offsets" not in self._values_to_share_to_server:
            self._values_to_share_to_server["adc_offsets"] = dict()
        adc_offsets = self._values_to_share_to_server["adc_offsets"]

        is_ref_sensor = ADC_CH_TO_IS_REF_SENSOR[adc_index][ch_index]
        if is_ref_sensor:
            well_index = ADC_CH_TO_24_WELL_INDEX[adc_index][ch_index - 1]
        else:
            well_index = ADC_CH_TO_24_WELL_INDEX[adc_index][ch_index]
        if well_index not in adc_offsets:
            adc_offsets[well_index] = dict()
        offset_key = "ref" if is_ref_sensor else "construct"
        adc_offsets[well_index][offset_key] = offset_val

    def _handle_error_in_subprocess(
        self,
        process: InfiniteProcess,
        error_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ],
    ) -> None:
        # pylint: disable=no-self-use # will use self soon. and this needs to be spied on frequently, so don't want to change namespace
        this_err, this_stack_trace = error_queue.get_nowait()
        msg = f"Error raised by subprocess {process}\n{this_stack_trace}\n{this_err}"
        # Eli (2/12/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
        with self._lock:
            logger.error(msg)
        process_items = self._process_manager.hard_stop_and_join_processes()
        msg = f"Remaining items in process queues: {process_items}"
        # Tanner (5/21/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
        with self._lock:
            logger.error(msg)

    def soft_stop(self) -> None:
        self._process_manager.soft_stop_and_join_processes()
        super().soft_stop()


the_mantarray_processes_monitor: Optional[  # pylint: disable=invalid-name # this is a singleton
    MantarrayProcessesMonitor
] = None


def set_mantarray_processes_monitor(
    processes_monitor: MantarrayProcessesMonitor,
) -> None:
    global the_mantarray_processes_monitor  # pylint: disable=global-statement,invalid-name #for the singleton
    the_mantarray_processes_monitor = processes_monitor


def get_mantarray_processes_monitor() -> Optional[MantarrayProcessesMonitor]:
    return the_mantarray_processes_monitor
