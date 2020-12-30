# -*- coding: utf-8 -*-
"""Docstring."""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple
from typing import Union
import uuid

from stdlib_utils import InfiniteProcess
from stdlib_utils import InfiniteThread

from .constants import ADC_CH_TO_24_WELL_INDEX
from .constants import ADC_CH_TO_IS_REF_SENSOR
from .constants import ADC_OFFSET_DESCRIPTION_TAG
from .constants import BARCODE_INVALID_UUID
from .constants import BARCODE_POLL_PERIOD
from .constants import BARCODE_UNREADABLE_UUID
from .constants import BARCODE_VALID_UUID
from .constants import BUFFERING_STATE
from .constants import CALIBRATED_STATE
from .constants import CALIBRATING_STATE
from .constants import INSTRUMENT_INITIALIZING_STATE
from .constants import LIVE_VIEW_ACTIVE_STATE
from .constants import RECORDING_STATE
from .constants import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from .constants import SERVER_INITIALIZING_STATE
from .constants import SERVER_READY_STATE
from .exceptions import UnrecognizedCommandToInstrumentError
from .exceptions import UnrecognizedMantarrayNamingCommandError
from .exceptions import UnrecognizedRecordingCommandError
from .process_manager import MantarrayProcessesManager
from .server import ServerThread
from .utils import attempt_to_get_recording_directory_from_new_dict
from .utils import redact_sensitive_info_from_path
from .utils import update_shared_dict

logger = logging.getLogger(__name__)


def _get_barcode_clear_time() -> float:
    return time.perf_counter()


def _get_dur_since_last_barcode_clear(last_clear_time: float) -> float:
    return time.perf_counter() - last_clear_time


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
        self._last_barcode_clear_time: Optional[float] = None

    def _check_and_handle_file_writer_to_main_queue(self) -> None:
        process_manager = self._process_manager
        file_writer_to_main = (
            process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
        )
        try:
            communication = file_writer_to_main.get(
                timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
            )
        except queue.Empty:
            return

        # Eli (2/12/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
        msg = f"Communication from the File Writer: {communication}"
        with self._lock:
            logger.info(msg)

    def _check_and_handle_server_to_main_queue(self) -> None:
        process_manager = self._process_manager
        to_main_queue = (
            process_manager.queue_container().get_communication_queue_from_server_to_main()
        )
        try:
            communication = to_main_queue.get(
                timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
            )
        except queue.Empty:
            return

        # Eli (2/12/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
        msg = f"Communication from the Server: {communication}"
        with self._lock:
            logger.info(msg)

        communication_type = communication["communication_type"]
        shared_values_dict = self._values_to_share_to_server
        if communication_type == "mantarray_naming":
            command = communication["command"]
            if command == "set_mantarray_nickname":
                if "mantarray_nickname" not in shared_values_dict:
                    shared_values_dict["mantarray_nickname"] = dict()
                shared_values_dict["mantarray_nickname"][0] = communication[
                    "mantarray_nickname"
                ]
            elif command == "set_mantarray_serial_number":
                if "mantarray_serial_number" not in shared_values_dict:
                    shared_values_dict["mantarray_serial_number"] = dict()
                shared_values_dict["mantarray_serial_number"][0] = communication[
                    "mantarray_serial_number"
                ]
            else:
                raise UnrecognizedMantarrayNamingCommandError(command)

            self._put_communication_into_ok_comm_queue(communication)
        elif communication_type == "shutdown":
            command = communication["command"]
            if command == "soft_stop":
                self._process_manager.soft_stop_processes_except_server()
            else:
                self._process_manager.are_processes_stopped()

                self._hard_stop_and_join_processes_and_log_leftovers()
        elif communication_type == "update_shared_values_dictionary":
            new_values = communication["content"]
            new_recording_directory: Optional[
                str
            ] = attempt_to_get_recording_directory_from_new_dict(new_values)

            if new_recording_directory is not None:
                to_file_writer_queue = (
                    process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
                )
                to_file_writer_queue.put(
                    {
                        "command": "update_directory",
                        "new_directory": new_recording_directory,
                    }
                )
                process_manager.set_file_directory(new_recording_directory)
            update_shared_dict(shared_values_dict, new_values)
        elif communication_type == "xem_scripts":
            # Tanner (12/28/20): start_calibration is the only xem_scripts command that will come from server. This comm type will be removed/replaced in beta 2 so not adding handling for unrecognized command.
            shared_values_dict["system_status"] = CALIBRATING_STATE
            self._put_communication_into_ok_comm_queue(communication)
        elif communication_type == "recording":
            command = communication["command"]
            main_to_fw_queue = (
                self._process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
            )

            if command == "stop_recording":
                shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE
            elif command == "start_recording":
                shared_values_dict["system_status"] = RECORDING_STATE
                is_hardware_test_recording = communication.get(
                    "is_hardware_test_recording", False
                )
                shared_values_dict[
                    "is_hardware_test_recording"
                ] = is_hardware_test_recording
                if is_hardware_test_recording:
                    shared_values_dict["adc_offsets"] = communication[
                        "metadata_to_copy_onto_main_file_attributes"
                    ]["adc_offsets"]
            else:
                raise UnrecognizedRecordingCommandError(command)
            main_to_fw_queue.put(communication)
        elif communication_type == "to_instrument":
            command = communication["command"]
            if command == "boot_up":
                self._process_manager.boot_up_instrument()
            elif command == "start_managed_acquisition":
                shared_values_dict["system_status"] = BUFFERING_STATE
                main_to_ok_comm_queue = self._process_manager.queue_container().get_communication_to_ok_comm_queue(
                    0
                )
                main_to_da_queue = (
                    self._process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
                )

                main_to_ok_comm_queue.put(communication)
                main_to_da_queue.put(communication)
            else:
                raise UnrecognizedCommandToInstrumentError(command)
        elif communication_type == "barcode_read_receipt":
            board_idx = communication["board_idx"]
            self._values_to_share_to_server["barcodes"][board_idx][
                "frontend_needs_barcode_update"
            ] = False

    def _put_communication_into_ok_comm_queue(
        self, communication: Dict[str, Any]
    ) -> None:
        main_to_ok_comm_queue = (
            self._process_manager.queue_container().get_communication_to_ok_comm_queue(
                0
            )
        )
        main_to_ok_comm_queue.put(communication)

    def _check_and_handle_data_analyzer_to_main_queue(self) -> None:
        process_manager = self._process_manager

        data_analyzer_to_main = (
            process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
        )
        try:
            communication = data_analyzer_to_main.get(
                timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
            )
        except queue.Empty:
            return

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

    def _check_and_handle_ok_comm_to_main_queue(self) -> None:
        process_manager = self._process_manager
        ok_comm_to_main = process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
            0
        )
        try:
            communication = ok_comm_to_main.get(
                timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
            )
        except queue.Empty:
            return
        if "bit_file_name" in communication:
            communication["bit_file_name"] = redact_sensitive_info_from_path(
                communication["bit_file_name"]
            )
        if "response" in communication:
            if (
                communication["response"] is not None
                and "bit_file_name" in communication["response"]
            ):
                communication["response"][
                    "bit_file_name"
                ] = redact_sensitive_info_from_path(
                    communication["response"]["bit_file_name"]
                )
        msg = f"Communication from the OpalKelly Controller: {communication}".replace(
            r"\\", "\\"
        )
        # Eli (2/12/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
        # msg = f"Communication from the OpalKelly Controller: {communication}"
        with self._lock:
            logger.info(msg)
        communication_type = communication["communication_type"]

        if "command" in communication:
            command = communication["command"]

        if communication_type in ["acquisition_manager", "to_instrument"]:
            if command == "start_managed_acquisition":
                self._values_to_share_to_server[
                    "utc_timestamps_of_beginning_of_data_acquisition"
                ] = [communication["timestamp"]]
            if command == "stop_managed_acquisition":
                self._values_to_share_to_server["system_status"] = CALIBRATED_STATE
                self._data_dump_buffer_size = 0
        elif communication_type == "board_connection_status_change":
            board_idx = communication["board_index"]
            self._values_to_share_to_server["in_simulation_mode"] = not communication[
                "is_connected"
            ]
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
                self._values_to_share_to_server["adc_gain"] = communication["adc_gain"]
            description = communication.get("description", "")
            if ADC_OFFSET_DESCRIPTION_TAG in description:
                parsed_description = description.split("__")
                adc_index = int(parsed_description[1][-1])
                ch_index = int(parsed_description[2][-1])
                offset_val = communication["wire_out_value"]
                self._add_offset_to_shared_dict(adc_index, ch_index, offset_val)
        elif communication_type == "barcode_comm":
            if "barcodes" not in self._values_to_share_to_server:
                self._values_to_share_to_server["barcodes"] = dict()
            board_idx = communication["board_idx"]
            if board_idx not in self._values_to_share_to_server["barcodes"]:
                self._values_to_share_to_server["barcodes"][board_idx] = dict()
            elif (
                self._values_to_share_to_server["barcodes"][board_idx]["plate_barcode"]
                == communication["barcode"]
            ):
                return
            valid = communication.get("valid", None)
            barcode_status: uuid.UUID
            if valid is None:
                barcode_status = BARCODE_UNREADABLE_UUID
            elif valid:
                barcode_status = BARCODE_VALID_UUID
            else:
                barcode_status = BARCODE_INVALID_UUID
            self._values_to_share_to_server["barcodes"][board_idx] = {
                "plate_barcode": communication["barcode"],
                "barcode_status": barcode_status,
                "frontend_needs_barcode_update": True,
            }

    def _commands_for_each_run_iteration(self) -> None:
        """Execute additional commands inside the run loop."""
        process_manager = self._process_manager

        # any potential errors should be handled first
        for iter_error_queue, iter_process in (
            (
                process_manager.queue_container().get_ok_communication_error_queue(),
                process_manager.get_instrument_process(),
            ),
            (
                process_manager.queue_container().get_file_writer_error_queue(),
                process_manager.get_file_writer_process(),
            ),
            (
                process_manager.queue_container().get_data_analyzer_error_queue(),
                process_manager.get_data_analyzer_process(),
            ),
            (
                process_manager.queue_container().get_server_error_queue(),
                process_manager.get_server_thread(),
            ),
        ):
            try:
                communication = iter_error_queue.get(
                    timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
                )
            except queue.Empty:
                continue
            self._handle_error_in_subprocess(iter_process, communication)

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
            process_manager.boot_up_instrument()

        self._check_and_handle_ok_comm_to_main_queue()
        self._check_and_handle_file_writer_to_main_queue()
        self._check_and_handle_data_analyzer_to_main_queue()
        self._check_and_handle_server_to_main_queue()

        to_ok_comm = (
            self._process_manager.queue_container().get_communication_to_ok_comm_queue(
                0
            )
        )

        if self._last_barcode_clear_time is None:
            self._last_barcode_clear_time = _get_barcode_clear_time()
        if (
            _get_dur_since_last_barcode_clear(self._last_barcode_clear_time)
            >= BARCODE_POLL_PERIOD
        ):
            to_ok_comm = (
                process_manager.queue_container().get_communication_to_ok_comm_queue(0)
            )
            barcode_poll_comm = {
                "communication_type": "barcode_comm",
                "command": "start_scan",
            }
            to_ok_comm.put(barcode_poll_comm)
            self._last_barcode_clear_time = _get_barcode_clear_time()

    def _check_subprocess_start_up_statuses(self) -> None:
        process_manager = self._process_manager
        shared_values_dict = self._values_to_share_to_server
        if process_manager.are_subprocess_start_ups_complete():
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
        process: Union[InfiniteProcess, ServerThread],
        error_communication: Tuple[Exception, str],
    ) -> None:
        this_err, this_stack_trace = error_communication
        msg = f"Error raised by subprocess {process}\n{this_stack_trace}\n{this_err}"
        # Eli (2/12/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
        with self._lock:
            logger.error(msg)
        self._hard_stop_and_join_processes_and_log_leftovers()

    def _hard_stop_and_join_processes_and_log_leftovers(self) -> None:
        process_items = self._process_manager.hard_stop_and_join_processes()
        msg = f"Remaining items in process queues: {process_items}"
        # Tanner (5/21/20) is not sure how to test that a lock is being acquired...so be careful about refactoring this
        with self._lock:
            logger.error(msg)

    def soft_stop(self) -> None:
        self._process_manager.soft_stop_and_join_processes()
        super().soft_stop()
