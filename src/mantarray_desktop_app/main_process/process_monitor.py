# -*- coding: utf-8 -*-
"""Handling communication between subprocesses and main process."""
from __future__ import annotations

import copy
import datetime
import json
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

from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
from stdlib_utils import drain_queue
from stdlib_utils import get_formatted_stack_trace
from stdlib_utils import InfiniteProcess
from stdlib_utils import InfiniteThread

from .process_manager import MantarrayProcessesManager
from .server import ServerManager
from .shared_values import SharedValues
from ..constants import ADC_CH_TO_24_WELL_INDEX
from ..constants import ADC_CH_TO_IS_REF_SENSOR
from ..constants import ADC_OFFSET_DESCRIPTION_TAG
from ..constants import BARCODE_INVALID_UUID
from ..constants import BARCODE_LEN
from ..constants import BARCODE_POLL_PERIOD
from ..constants import BARCODE_UNREADABLE_UUID
from ..constants import BARCODE_VALID_UUID
from ..constants import BUFFERING_STATE
from ..constants import CALIBRATED_STATE
from ..constants import CALIBRATING_STATE
from ..constants import CALIBRATION_NEEDED_STATE
from ..constants import CALIBRATION_RECORDING_DUR_SECONDS
from ..constants import CHECKING_FOR_UPDATES_STATE
from ..constants import CURRENT_SOFTWARE_VERSION
from ..constants import DOWNLOADING_UPDATES_STATE
from ..constants import GENERIC_24_WELL_DEFINITION
from ..constants import INSTALLING_UPDATES_STATE
from ..constants import INSTRUMENT_INITIALIZING_STATE
from ..constants import LIVE_VIEW_ACTIVE_STATE
from ..constants import MICRO_TO_BASE_CONVERSION
from ..constants import RECORDING_STATE
from ..constants import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from ..constants import SERVER_INITIALIZING_STATE
from ..constants import SERVER_READY_STATE
from ..constants import StimulatorCircuitStatuses
from ..constants import STOP_MANAGED_ACQUISITION_COMMUNICATION
from ..constants import UPDATE_ERROR_STATE
from ..constants import UPDATES_COMPLETE_STATE
from ..constants import UPDATES_NEEDED_STATE
from ..exceptions import InstrumentError
from ..exceptions import UnrecognizedCommandFromServerToMainError
from ..exceptions import UnrecognizedMantarrayNamingCommandError
from ..exceptions import UnrecognizedRecordingCommandError
from ..utils.generic import _compare_semver
from ..utils.generic import _create_start_recording_command
from ..utils.generic import _trim_barcode
from ..utils.generic import get_redacted_string
from ..utils.generic import redact_sensitive_info_from_path
from ..utils.generic import upload_log_files_to_s3

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
        values_to_share_to_server: SharedValues,
        process_manager: MantarrayProcessesManager,
        fatal_error_reporter: queue.Queue[str],  # pylint: disable=unsubscriptable-object
        the_lock: threading.Lock,
        boot_up_after_processes_start: bool = False,
        load_firmware_file: bool = True,
    ) -> None:
        super().__init__(fatal_error_reporter, lock=the_lock)
        self._values_to_share_to_server = values_to_share_to_server
        self._process_manager = process_manager
        self._boot_up_after_processes_start = boot_up_after_processes_start
        self._load_firmware_file = load_firmware_file
        self._data_dump_buffer_size = 0
        self._last_barcode_clear_time: Optional[float] = None

    def _report_fatal_error(self, the_err: Exception) -> None:
        super()._report_fatal_error(the_err)
        stack_trace = get_formatted_stack_trace(the_err)
        msg = f"Error raised by Process Monitor\n{stack_trace}\n{the_err}"
        # Tanner (3/9/22): not sure the lock is necessary or even doing anything here as nothing else acquires this lock before logging
        with self._lock:
            logger.error(msg)
        if self._process_manager.are_subprocess_start_ups_complete():
            self._hard_stop_and_join_processes_and_log_leftovers(shutdown_server=False)
        self._process_manager.shutdown_server()

    def _check_and_handle_file_writer_to_main_queue(self) -> None:
        process_manager = self._process_manager
        file_writer_to_main = (
            process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
        )
        try:
            communication = file_writer_to_main.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
        except queue.Empty:
            return

        communication_type = communication["communication_type"]
        if communication_type == "update_upload_status":
            self._queue_websocket_message(communication["content"])
        elif communication_type == "file_finalized":
            if (
                self._values_to_share_to_server["system_status"] == CALIBRATING_STATE
                and communication.get("message", None) == "all_finals_finalized"
            ):
                self._values_to_share_to_server["system_status"] = CALIBRATED_STATE
                # stop managed acquisition
                main_to_ic_queue = (
                    self._process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
                )
                main_to_fw_queue = (
                    self._process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
                )
                # need to send stop command to the process the furthest downstream the data path first then move upstream
                stop_managed_acquisition_comm: Dict[str, Any] = dict(STOP_MANAGED_ACQUISITION_COMMUNICATION)
                stop_managed_acquisition_comm["is_calibration_recording"] = True
                main_to_fw_queue.put_nowait(stop_managed_acquisition_comm)
                main_to_ic_queue.put_nowait(stop_managed_acquisition_comm)
        elif communication_type == "corrupt_file_detected":
            corrupt_files = communication["corrupt_files"]
            self._queue_websocket_message(
                {
                    "data_type": "corrupt_files_alert",
                    "data_json": json.dumps({"corrupt_files_found": corrupt_files}),
                }
            )

        # Tanner (12/13/21): redact file/folder path after handling comm in case the actual file path is needed
        for sensitive_field in ("file_path", "file_folder"):
            if sensitive_field in communication:
                communication[sensitive_field] = redact_sensitive_info_from_path(
                    communication[sensitive_field]
                )
        # Tanner (1/11/21): Unsure why the back slashes are duplicated when converting the communication dict to string. Using replace here to remove the duplication, not sure if there is a better way to solve or avoid this problem
        msg = f"Communication from the File Writer: {communication}".replace(r"\\", "\\")
        # Tanner (3/9/22): not sure the lock is necessary or even doing anything here as nothing else acquires this lock before logging
        with self._lock:
            logger.info(msg)

    def _check_and_handle_server_to_main_queue(self) -> None:
        # pylint: disable=too-many-branches, too-many-statements  # Tanner (4/23/21): temporarily need to add more than the allowed number of branches in order to support Beta 1 mode during transition to Beta 2 mode
        process_manager = self._process_manager
        to_main_queue = process_manager.queue_container().get_communication_queue_from_server_to_main()
        try:
            communication = to_main_queue.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
        except queue.Empty:
            return

        msg: str
        if "mantarray_nickname" in communication:
            # Tanner (1/20/21): items in communication dict are used after this log message is generated, so need to create a copy of the dict when redacting info
            comm_copy = copy.deepcopy(communication)
            comm_copy["mantarray_nickname"] = get_redacted_string(len(comm_copy["mantarray_nickname"]))
            msg = f"Communication from the Server: {comm_copy}"
        elif "update_user_settings" == communication["communication_type"]:
            comm_copy = copy.deepcopy(communication)
            comm_copy["content"]["user_password"] = get_redacted_string(4)
            msg = f"Communication from the Server: {comm_copy}"
        else:
            msg = f"Communication from the Server: {communication}"
        # Tanner (3/9/22): not sure the lock is necessary or even doing anything here as nothing else acquires this lock before logging
        with self._lock:
            logger.info(msg)

        communication_type = communication["communication_type"]
        shared_values_dict = self._values_to_share_to_server
        if communication_type == "mantarray_naming":
            command = communication["command"]
            if command == "set_mantarray_nickname":
                if "mantarray_nickname" not in shared_values_dict:
                    shared_values_dict["mantarray_nickname"] = dict()
                shared_values_dict["mantarray_nickname"][0] = communication["mantarray_nickname"]
            elif command == "set_mantarray_serial_number":
                if "mantarray_serial_number" not in shared_values_dict:
                    shared_values_dict["mantarray_serial_number"] = dict()
                shared_values_dict["mantarray_serial_number"][0] = communication["mantarray_serial_number"]
            else:
                raise UnrecognizedMantarrayNamingCommandError(command)
            self._put_communication_into_instrument_comm_queue(communication)
        elif communication_type == "shutdown":
            command = communication["command"]
            if command == "hard_stop":
                self._hard_stop_and_join_processes_and_log_leftovers(shutdown_server=False, error=False)
                upload_log_files_to_s3(self._values_to_share_to_server["config_settings"])
            elif command == "shutdown_server":
                self._process_manager.shutdown_server()
            else:
                raise NotImplementedError(f"Unrecognized shutdown command from Server: {command}")
        elif communication_type == "update_user_settings":
            new_values = communication["content"]
            if new_recording_directory := new_values.get("recording_directory"):
                to_file_writer_queue = (
                    process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
                )
                to_file_writer_queue.put_nowait(
                    {"command": "update_directory", "new_directory": new_recording_directory}
                )

                scrubbed_recordings_dir = redact_sensitive_info_from_path(new_recording_directory)
                logger.info(f"Using directory for recording files: {scrubbed_recordings_dir}")
            if "customer_id" in new_values:
                # TODO Tanner (5/5/22): should probably combine this with config_settings
                shared_values_dict["user_creds"] = {
                    "customer_id": new_values["customer_id"],
                    "user_name": new_values["user_name"],
                    "user_password": new_values["user_password"],
                }
                to_file_writer_queue = (
                    process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
                )
                to_file_writer_queue.put_nowait(
                    {"command": "update_user_settings", "config_settings": new_values}
                )
            shared_values_dict["config_settings"].update(new_values)
        elif communication_type == "set_latest_software_version":
            shared_values_dict["latest_software_version"] = communication["version"]
            # send message to FE if an update is available
            try:
                software_update_available = _compare_semver(
                    communication["version"], CURRENT_SOFTWARE_VERSION
                )
            except ValueError:
                software_update_available = False
            self._queue_websocket_message(
                {
                    "data_type": "sw_update",
                    "data_json": json.dumps({"software_update_available": software_update_available}),
                }
            )
        elif communication_type == "firmware_update_confirmation":
            shared_values_dict["firmware_update_accepted"] = communication["update_accepted"]
        elif communication_type == "stimulation":
            command = communication["command"]
            if command == "set_stim_status":
                self._put_communication_into_instrument_comm_queue(
                    {
                        "communication_type": communication_type,
                        "command": "start_stimulation" if communication["status"] else "stop_stimulation",
                    }
                )
            elif command == "set_protocols":
                self._values_to_share_to_server["stimulation_info"] = communication["stim_info"]
                self._put_communication_into_instrument_comm_queue(communication)
            elif command == "start_stim_checks":
                self._values_to_share_to_server["stimulator_circuit_statuses"] = {
                    well_idx: StimulatorCircuitStatuses.CALCULATING.name.lower()
                    for well_idx in communication["well_indices"]
                }
                self._put_communication_into_instrument_comm_queue(communication)
            else:
                # Tanner (8/9/21): could make this a custom error if needed
                raise NotImplementedError(f"Unrecognized stimulation command from Server: {command}")
        elif communication_type == "xem_scripts":
            # Tanner (12/28/20): start_calibration is the only xem_scripts command that will come from server (called directly from /start_calibration). This comm type will be removed/replaced in beta 2 so not adding handling for unrecognized command.
            if shared_values_dict["beta_2_mode"]:
                raise NotImplementedError("XEM scripts cannot be run when in Beta 2 mode")
            shared_values_dict["system_status"] = CALIBRATING_STATE
            self._put_communication_into_instrument_comm_queue(communication)
        elif communication_type == "calibration":
            # Tanner (12/10/21): run_calibration is currently the only calibration command
            shared_values_dict["system_status"] = CALIBRATING_STATE
            self._put_communication_into_instrument_comm_queue(
                {"communication_type": "acquisition_manager", "command": "start_managed_acquisition"}
            )

            if isinstance(shared_values_dict, SharedValues):
                shared_values_dict_copy = shared_values_dict.deepcopy()
            else:
                # tests might use a regular dict, so keeping this here
                shared_values_dict_copy = copy.deepcopy(shared_values_dict)  # type: ignore

            # Tanner (12/10/21): set this manually here since a start_managed_acquisition command response has not been received yet
            shared_values_dict_copy["utc_timestamps_of_beginning_of_data_acquisition"] = [
                datetime.datetime.utcnow()
            ]

            main_to_fw_queue = (
                self._process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
            )
            main_to_fw_queue.put_nowait(
                _create_start_recording_command(shared_values_dict_copy, is_calibration_recording=True)
            )
            main_to_fw_queue.put_nowait(
                {
                    "communication_type": "recording",
                    "command": "stop_recording",
                    "timepoint_to_stop_recording_at": CALIBRATION_RECORDING_DUR_SECONDS
                    * MICRO_TO_BASE_CONVERSION,
                    "is_calibration_recording": True,
                }
            )
        elif communication_type == "recording":
            command = communication["command"]
            main_to_fw_queue = (
                self._process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
            )

            if command == "stop_recording":
                shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE
            elif command == "start_recording":
                shared_values_dict["system_status"] = RECORDING_STATE
                is_hardware_test_recording = communication.get("is_hardware_test_recording", False)
                shared_values_dict["is_hardware_test_recording"] = is_hardware_test_recording
                if is_hardware_test_recording:
                    shared_values_dict["adc_offsets"] = communication[
                        "metadata_to_copy_onto_main_file_attributes"
                    ]["adc_offsets"]
            elif command == "update_recording_name":
                pass
            else:
                raise UnrecognizedRecordingCommandError(command)
            main_to_fw_queue.put_nowait(communication)
        elif communication_type == "to_instrument":
            # Tanner (8/25/21): 'to_instrument' communication type should be reserved for commands that are only sent to the instrument communication process
            command = communication["command"]
            if command == "boot_up":
                self._process_manager.boot_up_instrument()
            else:
                raise UnrecognizedCommandFromServerToMainError(
                    f"Invalid command: {command} for communication_type: {communication_type}"
                )
        elif communication_type == "acquisition_manager":
            main_to_ic_queue = (
                self._process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
            )
            main_to_da_queue = (
                self._process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
            )
            command = communication["command"]
            if command == "start_managed_acquisition":
                shared_values_dict["system_status"] = BUFFERING_STATE
                main_to_ic_queue.put_nowait(communication)
                main_to_da_queue.put_nowait(communication)
            elif command == "stop_managed_acquisition":
                main_to_fw_queue = (
                    self._process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
                )
                # need to send stop command to the process the furthest downstream the data path first then move upstream
                main_to_da_queue.put_nowait(communication)
                main_to_fw_queue.put_nowait(communication)
                main_to_ic_queue.put_nowait(communication)
            else:
                raise UnrecognizedCommandFromServerToMainError(
                    f"Invalid command: {command} for communication_type: {communication_type}"
                )
        elif communication_type == "mag_finding_analysis":
            if communication["command"] == "start_mag_analysis":
                main_to_da_queue = (
                    self._process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
                )
                main_to_da_queue.put_nowait(communication)

    def _put_communication_into_instrument_comm_queue(self, communication: Dict[str, Any]) -> None:
        main_to_instrument_comm_queue = (
            self._process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
        )
        main_to_instrument_comm_queue.put_nowait(communication)

    def _check_and_handle_data_analyzer_to_main_queue(self) -> None:
        process_manager = self._process_manager

        data_analyzer_to_main = (
            process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
        )
        try:
            communication = data_analyzer_to_main.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
        except queue.Empty:
            return

        # Tanner (3/9/22): not sure the lock is necessary or even doing anything here as nothing else acquires this lock before logging
        msg = f"Communication from the Data Analyzer: {communication}"
        with self._lock:
            logger.info(msg)

        communication_type = communication["communication_type"]
        if communication_type == "data_available":
            if self._values_to_share_to_server["system_status"] == BUFFERING_STATE:
                self._data_dump_buffer_size += 1
                if self._data_dump_buffer_size == 2:
                    self._values_to_share_to_server["system_status"] = LIVE_VIEW_ACTIVE_STATE
        elif communication_type == "mag_analysis_complete":
            self._queue_websocket_message(communication["content"])
        elif communication_type == "acquisition_manager":
            if communication["command"] == "stop_managed_acquisition":
                # fmt: off
                # remove any leftover outgoing items
                da_data_out_queue = (
                    self._process_manager.queue_container().get_data_analyzer_board_queues()[0][1]
                )
                # fmt: on
                drain_queue(da_data_out_queue)

    def _check_and_handle_data_analyzer_data_out_queue(self) -> None:
        da_data_out_queue = self._process_manager.queue_container().get_data_analyzer_board_queues()[0][1]
        try:
            outgoing_data_json = da_data_out_queue.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
        except queue.Empty:
            return
        self._queue_websocket_message(outgoing_data_json)

    def _check_and_handle_instrument_comm_to_main_queue(self) -> None:
        # pylint: disable=too-many-branches,too-many-statements  # TODO Tanner (10/25/21): refactor this into smaller methods
        process_manager = self._process_manager
        board_idx = 0
        instrument_comm_to_main = (
            process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(board_idx)
        )
        try:
            communication = instrument_comm_to_main.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
        except queue.Empty:
            return

        if "bit_file_name" in communication:
            communication["bit_file_name"] = redact_sensitive_info_from_path(communication["bit_file_name"])
        if "response" in communication:
            if communication["response"] is not None and "bit_file_name" in communication["response"]:
                communication["response"]["bit_file_name"] = redact_sensitive_info_from_path(
                    communication["response"]["bit_file_name"]
                )

        communication_type = communication["communication_type"]

        if "mantarray_nickname" in communication:
            # Tanner (1/20/21): items in communication dict are used after this log message is generated, so need to create a copy of the dict when redacting info
            comm_copy = copy.deepcopy(communication)
            comm_copy["mantarray_nickname"] = get_redacted_string(len(comm_copy["mantarray_nickname"]))
            msg = f"Communication from the Instrument Controller: {comm_copy}"
        elif communication_type == "metadata_comm":
            # Tanner (1/20/21): items in communication dict are used after this log message is generated, so need to create a copy of the dict when redacting info
            comm_copy = copy.deepcopy(communication)
            comm_copy["metadata"][MANTARRAY_NICKNAME_UUID] = get_redacted_string(
                len(comm_copy["metadata"][MANTARRAY_NICKNAME_UUID])
            )
            msg = f"Communication from the Instrument Controller: {comm_copy}"
        else:
            # Tanner (1/11/21): Unsure why the back slashes are duplicated when converting the communication dict to string. Using replace here to remove the duplication, not sure if there is a better way to solve or avoid this problem
            msg = f"Communication from the Instrument Controller: {communication}"
        msg = msg.replace(r"\\", "\\")
        # Tanner (3/9/22): not sure the lock is necessary or even doing anything here as nothing else acquires this lock before logging
        with self._lock:
            logger.info(msg)

        command = communication.get("command")

        if communication_type == "acquisition_manager":
            if command == "start_managed_acquisition":
                self._values_to_share_to_server["utc_timestamps_of_beginning_of_data_acquisition"] = [
                    communication["timestamp"]
                ]
            elif command == "stop_managed_acquisition":
                if not communication.get("is_calibration_recording", False):
                    self._values_to_share_to_server["system_status"] = CALIBRATED_STATE
                    self._data_dump_buffer_size = 0
            else:
                raise NotImplementedError(
                    f"Unrecognized acquisition_manager command from Instrument Comm: {command}"
                )
        elif communication_type == "stimulation":
            if command == "start_stimulation":
                stim_running_list = [False] * 24
                protocol_assignments = self._values_to_share_to_server["stimulation_info"][
                    "protocol_assignments"
                ]
                for well_name, assignment in protocol_assignments.items():
                    if not assignment:
                        continue
                    well_idx = GENERIC_24_WELL_DEFINITION.get_well_index_from_well_name(well_name)
                    stim_running_list[well_idx] = True
                self._values_to_share_to_server["stimulation_running"] = stim_running_list
            elif command == "stop_stimulation":
                self._values_to_share_to_server["stimulation_running"] = [False] * 24
            elif command == "status_update":
                # ignore stim status updates if stim was already stopped manually
                for well_idx in communication["wells_done_stimulating"]:
                    self._values_to_share_to_server["stimulation_running"][well_idx] = False
            elif command == "start_stim_checks":
                key = "stimulator_circuit_statuses"
                stimulator_circuit_statuses = communication[key]
                self._values_to_share_to_server[key] = stimulator_circuit_statuses
                self._queue_websocket_message(
                    {"data_type": key, "data_json": json.dumps(stimulator_circuit_statuses)}
                )
        elif communication_type == "board_connection_status_change":
            board_idx = communication["board_index"]
            self._values_to_share_to_server["in_simulation_mode"] = not communication["is_connected"]
            if self._values_to_share_to_server["beta_2_mode"]:
                return  # Tanner (4/25/21): Beta 2 Mantarray Instrument cannot send these values until the board is completely initialized, so just returning here
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
                self._values_to_share_to_server["system_status"] = communication["status_update"]
                if communication["status_update"] == CALIBRATION_NEEDED_STATE:
                    self._send_enable_sw_auto_install_message()
            if "adc_gain" in communication:
                self._values_to_share_to_server["adc_gain"] = communication["adc_gain"]
            if ADC_OFFSET_DESCRIPTION_TAG in (description := communication.get("description", "")):
                parsed_description = description.split("__")
                adc_index = int(parsed_description[1][-1])
                ch_index = int(parsed_description[2][-1])
                offset_val = communication["wire_out_value"]
                self._add_offset_to_shared_dict(adc_index, ch_index, offset_val)
        elif communication_type == "barcode_comm":
            barcode = communication["barcode"]
            if not self._values_to_share_to_server["beta_2_mode"] and len(barcode) == BARCODE_LEN:
                # Tanner (1/27/21): invalid barcodes will be sent untrimmed from ok_comm so the full string is logged, so trimming them here in order to always send trimmed barcodes to frontend.
                barcode = _trim_barcode(barcode)
            if "barcodes" not in self._values_to_share_to_server:
                self._values_to_share_to_server["barcodes"] = dict()
            board_idx = communication["board_idx"]
            barcode_type = "stim_barcode" if barcode.startswith("MS") else "plate_barcode"
            if board_idx not in self._values_to_share_to_server["barcodes"]:
                self._values_to_share_to_server["barcodes"][board_idx] = dict()
            elif self._values_to_share_to_server["barcodes"][board_idx].get(barcode_type, None) == barcode:
                return
            # TODO Tanner (2/7/22): consider removing barcode_status after Beta 1 mode phased out
            valid = communication.get("valid", None)
            barcode_status: uuid.UUID
            if valid is None:
                barcode_status = BARCODE_UNREADABLE_UUID
            elif valid:
                barcode_status = BARCODE_VALID_UUID
            else:
                barcode_status = BARCODE_INVALID_UUID

            board_barcode_dict = {barcode_type: barcode, "barcode_status": barcode_status}
            self._values_to_share_to_server["barcodes"][board_idx].update(board_barcode_dict)
            # send message to FE
            barcode_dict_copy = copy.deepcopy(board_barcode_dict)
            barcode_dict_copy["barcode_status"] = str(barcode_dict_copy["barcode_status"])
            barcode_update_message = {"data_type": "barcode", "data_json": json.dumps(barcode_dict_copy)}
            self._queue_websocket_message(barcode_update_message)
        elif communication_type == "metadata_comm":
            board_idx = communication["board_index"]
            # remove keys that aren't UUIDs as these don't need to be stored. They are only included in the comm so that the values are logged
            for key in list(communication["metadata"].keys()):
                if not isinstance(key, uuid.UUID):
                    communication["metadata"].pop(key)
            self._values_to_share_to_server["instrument_metadata"] = {board_idx: communication["metadata"]}
            # TODO Tanner (4/23/21): eventually these three following values won't need their own fields as they will be accessible through the above entry in shared_values_dict. Need to keep these until Beta 1 is phased out though
            self._values_to_share_to_server["main_firmware_version"] = {
                board_idx: communication["metadata"][MAIN_FIRMWARE_VERSION_UUID]
            }
            self._values_to_share_to_server["mantarray_serial_number"] = {
                board_idx: communication["metadata"][MANTARRAY_SERIAL_NUMBER_UUID]
            }
            self._values_to_share_to_server["mantarray_nickname"] = {
                board_idx: communication["metadata"][MANTARRAY_NICKNAME_UUID]
            }
        elif communication_type == "firmware_update":
            if command == "get_latest_firmware_versions":
                if "error" in communication:
                    self._values_to_share_to_server["system_status"] = CALIBRATION_NEEDED_STATE
                else:
                    required_sw_for_fw = communication["latest_versions"]["sw"]
                    latest_main_fw = communication["latest_versions"]["main-fw"]
                    latest_channel_fw = communication["latest_versions"]["channel-fw"]
                    min_sw_version_unavailable = _compare_semver(
                        required_sw_for_fw, self._values_to_share_to_server["latest_software_version"]
                    )
                    main_fw_update_needed = _compare_semver(
                        latest_main_fw,
                        self._values_to_share_to_server["instrument_metadata"][board_idx][
                            MAIN_FIRMWARE_VERSION_UUID
                        ],
                    )
                    channel_fw_update_needed = _compare_semver(
                        latest_channel_fw,
                        self._values_to_share_to_server["instrument_metadata"][board_idx][
                            CHANNEL_FIRMWARE_VERSION_UUID
                        ],
                    )
                    if (main_fw_update_needed or channel_fw_update_needed) and not min_sw_version_unavailable:
                        self._values_to_share_to_server["firmware_updates_needed"] = {
                            "main": latest_main_fw if main_fw_update_needed else None,
                            "channel": latest_channel_fw if channel_fw_update_needed else None,
                        }
                        self._values_to_share_to_server["system_status"] = UPDATES_NEEDED_STATE
                        self._queue_websocket_message(
                            {
                                "data_type": "fw_update",
                                "data_json": json.dumps(
                                    {
                                        "firmware_update_available": True,
                                        "channel_fw_update": channel_fw_update_needed,
                                    }
                                ),
                            }
                        )
                    else:
                        # if no updates found, enable auto install of SW update and switch to calibration needed state
                        self._send_enable_sw_auto_install_message()
                        self._values_to_share_to_server["system_status"] = CALIBRATION_NEEDED_STATE
            elif command == "download_firmware_updates":
                if "error" in communication:
                    self._values_to_share_to_server["system_status"] = UPDATE_ERROR_STATE
                else:
                    self._values_to_share_to_server["system_status"] = INSTALLING_UPDATES_STATE
                    to_instrument_comm_queue = (
                        self._process_manager.queue_container().get_communication_to_instrument_comm_queue(
                            board_idx
                        )
                    )
                    # Tanner (1/13/22): send both firmware update commands at once, and make sure channel is sent first. If both are sent, the second will be ignored until the first install completes
                    for firmware_type in ("channel", "main"):
                        new_version = self._values_to_share_to_server["firmware_updates_needed"][
                            firmware_type
                        ]
                        if new_version is not None:
                            to_instrument_comm_queue.put_nowait(
                                {
                                    "communication_type": "firmware_update",
                                    "command": "start_firmware_update",
                                    "firmware_type": firmware_type,
                                }
                            )
            elif command == "update_completed":
                firmware_type = communication["firmware_type"]
                self._values_to_share_to_server["firmware_updates_needed"][firmware_type] = None
                if all(
                    val is None for val in self._values_to_share_to_server["firmware_updates_needed"].values()
                ):
                    self._send_enable_sw_auto_install_message()
                    self._values_to_share_to_server["system_status"] = UPDATES_COMPLETE_STATE

    def _start_firmware_update(self) -> None:
        self._values_to_share_to_server["system_status"] = DOWNLOADING_UPDATES_STATE
        board_idx = 0
        to_instrument_comm_queue = (
            self._process_manager.queue_container().get_communication_to_instrument_comm_queue(board_idx)
        )
        to_instrument_comm_queue.put_nowait(
            {
                "communication_type": "firmware_update",
                "command": "download_firmware_updates",
                "main": self._values_to_share_to_server["firmware_updates_needed"]["main"],
                "channel": self._values_to_share_to_server["firmware_updates_needed"]["channel"],
                "customer_id": self._values_to_share_to_server["user_creds"]["customer_id"],
                "username": self._values_to_share_to_server["user_creds"]["user_name"],
                "password": self._values_to_share_to_server["user_creds"]["user_password"],
            }
        )

    def _commands_for_each_run_iteration(self) -> None:
        """Execute additional commands inside the run loop."""
        process_manager = self._process_manager
        board_idx = 0

        # check for errors first
        for iter_error_queue, iter_process in (
            (
                process_manager.queue_container().get_instrument_communication_error_queue(),
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
        ):
            try:
                communication = iter_error_queue.get(timeout=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES)
            except queue.Empty:
                continue
            self._handle_error_in_subprocess(iter_process, communication)

        # make sure system status is up to date
        if self._values_to_share_to_server["system_status"] == SERVER_INITIALIZING_STATE:
            self._check_subprocess_start_up_statuses()
        elif self._values_to_share_to_server["system_status"] == SERVER_READY_STATE:
            if self._values_to_share_to_server["beta_2_mode"]:
                self._values_to_share_to_server["system_status"] = INSTRUMENT_INITIALIZING_STATE
            elif self._boot_up_after_processes_start:
                self._values_to_share_to_server["system_status"] = INSTRUMENT_INITIALIZING_STATE
                process_manager.boot_up_instrument(load_firmware_file=self._load_firmware_file)
        elif (
            self._values_to_share_to_server["beta_2_mode"]
            and self._values_to_share_to_server["system_status"] == INSTRUMENT_INITIALIZING_STATE
        ):
            if (
                "in_simulation_mode" not in self._values_to_share_to_server
                or "instrument_metadata" not in self._values_to_share_to_server
            ):
                pass  # need to wait for these values before proceeding with state transition
            elif self._values_to_share_to_server["in_simulation_mode"]:
                self._values_to_share_to_server["system_status"] = CALIBRATION_NEEDED_STATE
            elif self._values_to_share_to_server["latest_software_version"] is not None:
                self._values_to_share_to_server["system_status"] = CHECKING_FOR_UPDATES_STATE
                # send command to instrument comm process to check for firmware updates
                serial_number = self._values_to_share_to_server["instrument_metadata"][board_idx][
                    MANTARRAY_SERIAL_NUMBER_UUID
                ]
                to_instrument_comm_queue = (
                    self._process_manager.queue_container().get_communication_to_instrument_comm_queue(
                        board_idx
                    )
                )
                to_instrument_comm_queue.put_nowait(
                    {
                        "communication_type": "firmware_update",
                        "command": "get_latest_firmware_versions",
                        "serial_number": serial_number,
                    }
                )
        elif self._values_to_share_to_server["system_status"] == UPDATES_NEEDED_STATE:
            if "firmware_update_accepted" not in self._values_to_share_to_server:
                pass  # need to wait for this value
            elif self._values_to_share_to_server["firmware_update_accepted"]:
                if "user_creds" in self._values_to_share_to_server:
                    if "customer_id" in self._values_to_share_to_server["user_creds"]:
                        self._start_firmware_update()
                else:
                    # Tanner (1/25/22): setting this value to empty dict to indicate that user input prompt has been sent
                    self._values_to_share_to_server["user_creds"] = {}
                    self._send_user_creds_prompt_message()
            else:
                self._values_to_share_to_server["system_status"] = CALIBRATION_NEEDED_STATE

        # check/handle comm from the server and each subprocess
        self._check_and_handle_instrument_comm_to_main_queue()
        self._check_and_handle_file_writer_to_main_queue()
        self._check_and_handle_data_analyzer_to_main_queue()
        self._check_and_handle_server_to_main_queue()

        # if managed acquisition is running, check for available data
        if self._values_to_share_to_server["system_status"] in (
            BUFFERING_STATE,
            LIVE_VIEW_ACTIVE_STATE,
            RECORDING_STATE,
        ):
            self._check_and_handle_data_analyzer_data_out_queue()

        # update status of subprocesses
        self._values_to_share_to_server[
            "subprocesses_running"
        ] = self._process_manager.get_subprocesses_running_status()

        # handle barcode polling. This should be removed once the physical instrument is able to detect plate placement/removal on its own. The Beta 2 instrument will be able to do this on its own from the start, so no need to send barcode comm in Beta 2 mode.
        if not self._values_to_share_to_server["beta_2_mode"]:
            if self._last_barcode_clear_time is None:
                self._last_barcode_clear_time = _get_barcode_clear_time()
            if _get_dur_since_last_barcode_clear(self._last_barcode_clear_time) >= BARCODE_POLL_PERIOD:
                to_instrument_comm = (
                    process_manager.queue_container().get_communication_to_instrument_comm_queue(board_idx)
                )
                barcode_poll_comm = {"communication_type": "barcode_comm", "command": "start_scan"}
                to_instrument_comm.put_nowait(barcode_poll_comm)
                self._last_barcode_clear_time = _get_barcode_clear_time()

    def _check_subprocess_start_up_statuses(self) -> None:
        process_manager = self._process_manager
        shared_values_dict = self._values_to_share_to_server
        if process_manager.are_subprocess_start_ups_complete():
            shared_values_dict["system_status"] = SERVER_READY_STATE

    def _add_offset_to_shared_dict(self, adc_index: int, ch_index: int, offset_val: int) -> None:
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

    def _send_user_creds_prompt_message(self) -> None:
        self._queue_websocket_message(
            {"data_type": "prompt_user_input", "data_json": json.dumps({"input_type": "user_creds"})}
        )

    def _send_enable_sw_auto_install_message(self) -> None:
        self._queue_websocket_message(
            {"data_type": "sw_update", "data_json": json.dumps({"allow_software_update": True})}
        )

    def _queue_websocket_message(self, message_dict: Dict[str, Any]) -> None:
        data_to_server_queue = self._process_manager.queue_container().get_data_queue_to_server()
        data_to_server_queue.put_nowait(message_dict)

    def _handle_error_in_subprocess(
        self,
        process: Union[InfiniteProcess, ServerManager],
        error_communication: Tuple[Exception, str],
    ) -> None:
        this_err, this_stack_trace = error_communication
        msg = f"Error raised by subprocess {process}\n{this_stack_trace}\n{this_err}"
        # Tanner (3/9/22): not sure the lock is necessary or even doing anything here as nothing else acquires this lock before logging
        with self._lock:
            logger.error(msg)

        shutdown_server = True

        if process == self._process_manager.get_instrument_process() and isinstance(
            this_err, InstrumentError
        ):
            this_err_type_mro = type(this_err).mro()
            instrument_sub_error_class = this_err_type_mro[this_err_type_mro.index(InstrumentError) - 1]
            instrument_sub_error_name = instrument_sub_error_class.__name__
            self._queue_websocket_message(
                {"data_type": "error", "data_json": json.dumps({"error_type": instrument_sub_error_name})}
            )
        elif self._values_to_share_to_server["system_status"] in (
            DOWNLOADING_UPDATES_STATE,
            INSTALLING_UPDATES_STATE,
        ):
            self._values_to_share_to_server["system_status"] = UPDATE_ERROR_STATE
            shutdown_server = False

        self._hard_stop_and_join_processes_and_log_leftovers(shutdown_server=shutdown_server)

    def _hard_stop_and_join_processes_and_log_leftovers(
        self, shutdown_server: bool = True, error: bool = True
    ) -> None:
        process_items = self._process_manager.hard_stop_and_join_processes(shutdown_server=shutdown_server)
        msg = f"Remaining items in process queues: {process_items}".replace(r"\\", "\\")
        # Tanner (3/9/22): not sure the lock is necessary or even doing anything here as nothing else acquires this lock before logging
        with self._lock:
            if error:
                logger.error(msg)
            else:
                logger.info(msg)

    def soft_stop(self) -> None:
        self._process_manager.soft_stop_and_join_processes()
        super().soft_stop()
