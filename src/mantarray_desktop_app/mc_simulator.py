# -*- coding: utf-8 -*-
"""Mantarray Microcontroller Simulator."""
from __future__ import annotations

import csv
import logging
from multiprocessing import Queue
from multiprocessing import queues as mpqueues
import os
import queue
import random
from time import perf_counter
from time import perf_counter_ns
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union
from uuid import UUID
from zlib import crc32

from immutabledict import immutabledict
from mantarray_file_manager import BOOTUP_COUNTER_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import PCB_SERIAL_NUMBER_UUID
from mantarray_file_manager import TAMPER_FLAG_UUID
from mantarray_file_manager import TOTAL_WORKING_HOURS_UUID
from nptyping import NDArray
import numpy as np
from scipy import interpolate
from stdlib_utils import drain_queue
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import InfiniteProcess
from stdlib_utils import resource_path

from .constants import DEFAULT_SAMPLING_PERIOD
from .constants import GENERIC_24_WELL_DEFINITION
from .constants import MAX_MC_REBOOT_DURATION_SECONDS
from .constants import MICRO_TO_BASE_CONVERSION
from .constants import MICROSECONDS_PER_CENTIMILLISECOND
from .constants import MICROSECONDS_PER_MILLISECOND
from .constants import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from .constants import SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
from .constants import SERIAL_COMM_BOOT_UP_CODE
from .constants import SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE
from .constants import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from .constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from .constants import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from .constants import SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE
from .constants import SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE
from .constants import SERIAL_COMM_FATAL_ERROR_CODE
from .constants import SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
from .constants import SERIAL_COMM_GET_METADATA_COMMAND_BYTE
from .constants import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from .constants import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from .constants import SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE
from .constants import SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_IDLE_READY_CODE
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE
from .constants import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from .constants import SERIAL_COMM_MAIN_MODULE_ID
from .constants import SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES
from .constants import SERIAL_COMM_METADATA_BYTES_LENGTH
from .constants import SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE
from .constants import SERIAL_COMM_MODULE_ID_INDEX
from .constants import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from .constants import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from .constants import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from .constants import SERIAL_COMM_NUM_DATA_CHANNELS
from .constants import SERIAL_COMM_NUM_SENSORS_PER_WELL
from .constants import SERIAL_COMM_PACKET_TYPE_INDEX
from .constants import SERIAL_COMM_PLATE_EVENT_PACKET_TYPE
from .constants import SERIAL_COMM_REBOOT_COMMAND_BYTE
from .constants import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from .constants import SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
from .constants import SERIAL_COMM_SET_TIME_COMMAND_BYTE
from .constants import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from .constants import SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_START_STIM_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .constants import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from .constants import SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_STOP_STIM_PACKET_TYPE
from .constants import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from .constants import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from .constants import SERIAL_COMM_TIME_SYNC_READY_CODE
from .constants import SERIAL_COMM_TIMESTAMP_BYTES_INDEX
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .constants import STIM_COMPLETE_SUBPROTOCOL_IDX
from .constants import STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
from .constants import STIM_WELL_IDX_TO_MODULE_ID
from .constants import StimStatuses
from .exceptions import SerialCommInvalidSamplingPeriodError
from .exceptions import SerialCommTooManyMissedHandshakesError
from .exceptions import UnrecognizedSerialCommModuleIdError
from .exceptions import UnrecognizedSerialCommPacketTypeError
from .exceptions import UnrecognizedSimulatorTestCommandError
from .serial_comm_utils import convert_bytes_to_config_dict
from .serial_comm_utils import convert_module_id_to_well_name
from .serial_comm_utils import convert_stim_bytes_to_dict
from .serial_comm_utils import convert_to_metadata_bytes
from .serial_comm_utils import convert_to_status_code_bytes
from .serial_comm_utils import convert_well_name_to_module_id
from .serial_comm_utils import create_data_packet
from .serial_comm_utils import create_magnetometer_config_bytes
from .serial_comm_utils import is_null_subprotocol
from .serial_comm_utils import validate_checksum
from .utils import create_magnetometer_config_dict
from .utils import sort_nested_dict


MAGIC_WORD_LEN = len(SERIAL_COMM_MAGIC_WORD_BYTES)
AVERAGE_MC_REBOOT_DURATION_SECONDS = MAX_MC_REBOOT_DURATION_SECONDS / 2
MC_SIMULATOR_BOOT_UP_DURATION_SECONDS = 3


def _perf_counter_us() -> int:
    """Return perf_counter value as microseconds."""
    return perf_counter_ns() // 10 ** 3


def _get_secs_since_last_handshake(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_last_status_beacon(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_reboot_command(command_time: float) -> float:
    return perf_counter() - command_time


def _get_secs_since_boot_up(start_time: float) -> float:
    return perf_counter() - start_time


def _get_secs_since_last_comm_from_pc(last_time: float) -> float:
    return perf_counter() - last_time


def _get_us_since_last_data_packet(last_time_us: int) -> int:
    return _perf_counter_us() - last_time_us


def _get_us_since_subprotocol_start(start_time_us: int) -> int:
    return _perf_counter_us() - start_time_us


# pylint: disable=too-many-instance-attributes
class MantarrayMcSimulator(InfiniteProcess):
    """Simulate a running Mantarray instrument with Microcontroller.

    If a command from the PC triggers an update to the status code, the updated status beacon will be sent after the command response

    Args:
        input_queue: queue bytes sent to the simulator using the `write` method
        output_queue: queue bytes sent from the simulator using the `read` method
        fatal_error_reporter: a queue to report fatal errors back to the main process
        testing_queue: queue used to send commands to the simulator. Should only be used in unit tests
        read_timeout_seconds: number of seconds to wait until read is of desired size before returning how ever many bytes have been read. Timeout should be set to 0 except in unit testing scenarios where necessary
    """

    default_mantarray_nickname = "Mantarray Simulator (MCU)"
    default_mantarray_serial_number = "M02001901"
    default_pcb_serial_number = "TBD"  # TODO Tanner (3/17/21): implement this once the format is determined
    default_firmware_version = "0.0.0"
    default_barcode = "MA190190001"
    default_metadata_values: Dict[UUID, Any] = immutabledict(
        {
            BOOTUP_COUNTER_UUID: 0,
            TOTAL_WORKING_HOURS_UUID: 0,
            TAMPER_FLAG_UUID: 0,
            MANTARRAY_SERIAL_NUMBER_UUID: default_mantarray_serial_number,
            MANTARRAY_NICKNAME_UUID: default_mantarray_nickname,
            PCB_SERIAL_NUMBER_UUID: default_pcb_serial_number,
            MAIN_FIRMWARE_VERSION_UUID: default_firmware_version,
        }
    )
    default_24_well_magnetometer_config: Dict[  # pylint: disable=invalid-name # Tanner (4/29/21): can't think of a shorter name for this value
        int, Dict[int, bool]
    ] = immutabledict(
        create_magnetometer_config_dict(24)
    )
    global_timer_offset_secs = 2.5  # TODO Tanner (11/17/21): figure out if this should be removed

    def __init__(
        self,
        input_queue: Queue[
            bytes
        ],  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        output_queue: Queue[bytes],  # pylint: disable=unsubscriptable-object
        fatal_error_reporter: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        testing_queue: Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
        logging_level: int = logging.INFO,
        read_timeout_seconds: Union[int, float] = 0,
        num_wells: int = 24,
    ) -> None:
        # InfiniteProcess values
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._output_queue = output_queue
        self._input_queue = input_queue
        self._testing_queue = testing_queue
        # serial comm values
        self._read_timeout_seconds = read_timeout_seconds
        self._leftover_read_bytes = bytes(0)
        # plate values
        self._num_wells = num_wells
        # simulator values (not set in _handle_boot_up_config)
        self._time_of_last_status_beacon_secs: Optional[float] = None
        self._time_of_last_handshake_secs: Optional[float] = None
        self._time_of_last_comm_from_pc_secs: Optional[float] = None
        self._ready_to_send_barcode = False
        self._timepoint_of_last_data_packet_us: Optional[int] = None
        self._time_index_us = 0
        self._simulated_data_index = 0
        self._simulated_data: NDArray[np.uint16] = np.array([], dtype=np.uint16)
        self._metadata_dict: Dict[bytes, bytes] = dict()
        self._reset_metadata_dict()
        self._setup_data_interpolator()
        # simulator values (set in _handle_boot_up_config)
        self._reboot_time_secs: Optional[float]
        self._boot_up_time_secs: Optional[float] = None
        self._baseline_time_us: Optional[int]
        self._timepoint_of_time_sync_us: Optional[int]
        self._status_code: int
        self._magnetometer_config: Dict[int, Dict[int, bool]]
        self._sampling_period_us: int
        self._stim_info: Dict[str, Any]
        self._stim_running_statuses: Dict[str, bool]
        self._timepoints_of_subprotocols_start: List[Optional[int]]
        self._stim_time_indices: List[int]
        self._stim_subprotocol_indices: List[int]
        self._reset_stim_running_statuses()
        self._firmware_update_type: Optional[int] = None
        self._firmware_update_idx: Optional[int] = None
        self._firmware_update_bytes: Optional[bytes]
        self._handle_boot_up_config()

    def start(self) -> None:
        for simulator_queue in (self._output_queue, self._input_queue, self._testing_queue):
            if not isinstance(simulator_queue, mpqueues.Queue):
                raise NotImplementedError(
                    "All queues must be standard multiprocessing queues to start this process"
                )
        super().start()

    @property
    def _is_streaming_data(self) -> bool:
        return self._timepoint_of_last_data_packet_us is not None

    @_is_streaming_data.setter
    def _is_streaming_data(self, value: bool) -> None:
        if value:
            self._timepoint_of_last_data_packet_us = _perf_counter_us()
            self._simulated_data_index = 0
            self._time_index_us = self._get_global_timer()
            if self._sampling_period_us == 0:
                raise NotImplementedError("sampling period must be set before streaming data")
            self._simulated_data = self.get_interpolated_data(self._sampling_period_us)
        else:
            self._timepoint_of_last_data_packet_us = None

    @property
    def _is_stimulating(self) -> bool:
        return any(self._stim_running_statuses.values())

    @_is_stimulating.setter
    def _is_stimulating(self, value: bool) -> None:
        # do nothing if already set to given value
        if value is self._is_stimulating:
            return
        if value:
            start_timepoint = _perf_counter_us()
            self._timepoints_of_subprotocols_start = [start_timepoint] * len(self._stim_info["protocols"])
            start_time_index = self._get_global_timer()
            self._stim_time_indices = [start_time_index] * len(self._stim_info["protocols"])
            self._stim_subprotocol_indices = [-1] * len(self._stim_info["protocols"])
            for well_name, protocol_id in self._stim_info["protocol_assignments"].items():
                self._stim_running_statuses[well_name] = protocol_id is not None
        else:
            self._reset_stim_running_statuses()
            self._timepoints_of_subprotocols_start = list()
            self._stim_time_indices = list()
            self._stim_subprotocol_indices = list()

    @property
    def in_waiting(self) -> int:
        """Only use to determine if a read can be done.

        For example, check if this value if non-zero.

        It does not represent the full number of bytes that can be read.
        """
        # Tanner (4/28/21): If McComm ever has a need to know the true value of in_waiting, need to make this value accurate
        if len(self._leftover_read_bytes) == 0:
            try:
                self._leftover_read_bytes = self._output_queue.get(timeout=self._read_timeout_seconds)
            except queue.Empty:
                return 0
        return len(self._leftover_read_bytes)

    def _setup_data_interpolator(self) -> None:
        """Set up the function to interpolate data.

        This function is necessary to handle different sampling periods.

        This function should only be called once.
        """
        relative_path = os.path.join("src", "simulated_data", "simulated_twitch.csv")
        absolute_path = os.path.normcase(os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir))
        file_path = resource_path(relative_path, base_path=absolute_path)
        with open(file_path, newline="") as csvfile:
            simulated_data_timepoints = next(csv.reader(csvfile, delimiter=","))
            simulated_data_values = next(csv.reader(csvfile, delimiter=","))
        self._interpolator = interpolate.interp1d(
            np.array(simulated_data_timepoints, dtype=np.uint64),
            simulated_data_values,
        )

    def _handle_boot_up_config(self, reboot: bool = False) -> None:
        if self._firmware_update_type is not None:
            packet_type = (
                SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE
                if self._firmware_update_type
                else SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE
            )
            self._send_data_packet(SERIAL_COMM_MAIN_MODULE_ID, packet_type, bytes([0, 0, 0]))
        self._reset_start_time()
        self._reboot_time_secs = None
        self._status_code = SERIAL_COMM_BOOT_UP_CODE
        self._reset_magnetometer_config()
        self._baseline_time_us = None
        self._timepoint_of_time_sync_us = None
        self._sampling_period_us = 0
        self._stim_info = {}
        self._is_stimulating = False
        self._firmware_update_type = None
        self._firmware_update_idx = None
        self._firmware_update_bytes = None
        if reboot:
            drain_queue(self._input_queue)
            # only boot up time automatically after a reboot
            self._boot_up_time_secs = perf_counter()
            # after reboot, send status beacon to signal that reboot has completed
            self._send_status_beacon(truncate=False)

    def _reset_metadata_dict(self) -> None:
        for uuid_key, metadata_value in self.default_metadata_values.items():
            self._metadata_dict[uuid_key.bytes] = convert_to_metadata_bytes(metadata_value)

    def _reset_magnetometer_config(self) -> None:
        self._magnetometer_config = dict(self.default_24_well_magnetometer_config)

    def _reset_stim_running_statuses(self) -> None:
        self._stim_running_statuses = {
            convert_module_id_to_well_name(module_id, use_stim_mapping=True): False
            for module_id in range(1, self._num_wells + 1)
        }

    def _get_us_since_time_sync(self) -> int:
        return (
            0
            if self._timepoint_of_time_sync_us is None
            else _perf_counter_us() - self._timepoint_of_time_sync_us
        )

    def get_read_timeout(self) -> Union[int, float]:
        """Mainly for use in unit tests."""
        return self._read_timeout_seconds

    def get_metadata_dict(self) -> Dict[bytes, bytes]:
        """Mainly for use in unit tests."""
        return self._metadata_dict

    def get_status_code(self) -> int:
        """Mainly for use in unit tests."""
        return self._status_code

    def get_eeprom_bytes(self) -> bytes:
        eeprom_dict = {
            "Status Code": self._status_code,
            "Time Sync Value received from PC (microseconds)": self._baseline_time_us,
            "Is Streaming Data": self._is_streaming_data,
            "Sampling Period (microseconds)": self._sampling_period_us,
        }
        return bytes(f" Simulator EEPROM Contents: {str(eeprom_dict)}", encoding="ascii")

    def get_sampling_period_us(self) -> int:
        """Mainly for use in unit tests."""
        return self._sampling_period_us

    def get_magnetometer_config(self) -> Dict[int, Dict[int, bool]]:
        """Mainly for use in unit tests."""
        return self._magnetometer_config

    def get_interpolated_data(self, sampling_period_us: int) -> NDArray[np.uint16]:
        """Return one second (one twitch) of interpolated data."""
        data_indices = np.arange(0, MICRO_TO_BASE_CONVERSION, sampling_period_us)
        return self._interpolator(data_indices).astype(np.uint16)

    def get_stim_info(self) -> Dict[str, Any]:
        """Mainly for use in unit tests."""
        return self._stim_info

    def get_stim_running_statuses(self) -> Dict[str, bool]:
        """Mainly for use in unit tests."""
        return self._stim_running_statuses

    def is_rebooting(self) -> bool:
        """Mainly for use in unit tests."""
        return self._reboot_time_secs is not None

    def get_num_wells(self) -> int:
        return self._num_wells

    def _get_absolute_timer(self) -> int:
        absolute_time: int = self.get_cms_since_init() * MICROSECONDS_PER_CENTIMILLISECOND
        return absolute_time

    def _get_global_timer(self) -> int:
        return self._get_absolute_timer() + int(self.global_timer_offset_secs * MICRO_TO_BASE_CONVERSION)

    def _get_timestamp(self) -> int:
        return (
            self._get_absolute_timer()
            if self._baseline_time_us is None
            else (self._baseline_time_us + self._get_us_since_time_sync())
        )

    def _send_data_packet(
        self,
        module_id: int,
        packet_type: int,
        data_to_send: bytes = bytes(0),
        truncate: bool = False,
    ) -> None:
        timestamp = self._get_timestamp()
        data_packet = create_data_packet(timestamp, module_id, packet_type, data_to_send)
        if truncate:
            trunc_index = random.randint(  # nosec B311 # Tanner (2/4/21): Bandit blacklisted this pseudo-random generator for cryptographic security reasons that do not apply to the desktop app.
                0, len(data_packet) - 1
            )
            data_packet = data_packet[trunc_index:]
        self._output_queue.put_nowait(data_packet)

    def _commands_for_each_run_iteration(self) -> None:
        """Ordered actions to perform each iteration.

        1. Handle any test communication. This must be done first since test comm may cause the simulator to enter a certain state or send a data packet. Test communication should also be processed regardless of the internal state of the simulator.
        2. Check if the simulator is in a fatal error state. If this is the case, the simulator should suspend all other functionality. Currently this state can only be reached through testing commands.
        3. Check if rebooting. The simulator should not be responsive to any commands from the PC while it is rebooting.
        4. Handle communication from the PC.
        5. Send a status beacon if enough time has passed since the previous one was sent.
        6. If streaming is on, check to see how many data packets are ready to be sent and send them if necessary.
        7. If stimulating, send any stimulation data packets that need to be sent.
        8. Check if the handshake from the PC is overdue. This should be done after checking for data sent from the PC since the next packet might be a handshake.
        9. Check if the barcode is ready to send. This is currently the lowest priority.
        """
        self._handle_test_comm()
        if self._status_code == SERIAL_COMM_FATAL_ERROR_CODE:
            return
        # if _reboot_time_secs is not None this means the simulator is in a "reboot" phase
        if self._reboot_time_secs is not None:
            secs_since_reboot = _get_secs_since_reboot_command(self._reboot_time_secs)
            # if secs_since_reboot is less than the reboot duration, simulator is still in the 'reboot' phase. Commands from PC will be ignored and status beacons will not be sent
            if (
                secs_since_reboot < AVERAGE_MC_REBOOT_DURATION_SECONDS
            ):  # Tanner (3/31/21): rebooting should be much faster than the maximum allowed time for rebooting, so arbitrarily picking a simulated reboot duration
                return
            self._handle_boot_up_config(reboot=True)
        elif self._status_code == SERIAL_COMM_BOOT_UP_CODE:
            if self._boot_up_time_secs is None:
                self._boot_up_time_secs = perf_counter()
            boot_up_dur_secs = _get_secs_since_boot_up(self._boot_up_time_secs)
            # if boot_up_dur_secs is less than the boot-up duration, simulator is still booting up
            if boot_up_dur_secs >= MC_SIMULATOR_BOOT_UP_DURATION_SECONDS:
                self._update_status_code(SERIAL_COMM_TIME_SYNC_READY_CODE)
        self._handle_comm_from_pc()
        self._handle_status_beacon()
        if self._is_streaming_data:
            self._handle_sending_data_packets()
        if self._is_stimulating:
            self._handle_stimulation_packets()
        self._check_handshake()
        if self._ready_to_send_barcode:
            self._send_data_packet(
                SERIAL_COMM_MAIN_MODULE_ID,
                SERIAL_COMM_PLATE_EVENT_PACKET_TYPE,
                bytes([1]) + bytes(self.default_barcode, encoding="ascii"),
            )
            self._ready_to_send_barcode = False

    def _handle_comm_from_pc(self) -> None:
        try:
            comm_from_pc = self._input_queue.get_nowait()
        except queue.Empty:
            if self._status_code not in (
                SERIAL_COMM_BOOT_UP_CODE,
                SERIAL_COMM_TIME_SYNC_READY_CODE,
            ):
                self._check_handshake_timeout()
            return
        self._time_of_last_comm_from_pc_secs = perf_counter()

        # validate checksum before handling the communication
        checksum_is_valid = validate_checksum(comm_from_pc)
        if not checksum_is_valid:
            # remove magic word before returning message to PC
            trimmed_comm_from_pc = comm_from_pc[MAGIC_WORD_LEN:]
            self._send_data_packet(
                SERIAL_COMM_MAIN_MODULE_ID,
                SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE,
                trimmed_comm_from_pc,
            )
            return
        module_id = comm_from_pc[SERIAL_COMM_MODULE_ID_INDEX]
        if module_id == SERIAL_COMM_MAIN_MODULE_ID:
            self._process_main_module_command(comm_from_pc)
        else:
            raise UnrecognizedSerialCommModuleIdError(module_id)

    def _check_handshake_timeout(self) -> None:
        if self._time_of_last_comm_from_pc_secs is None:
            return
        secs_since_last_comm_from_pc = _get_secs_since_last_comm_from_pc(self._time_of_last_comm_from_pc_secs)
        if secs_since_last_comm_from_pc >= SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS:
            self._update_status_code(SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE)

    def _process_main_module_command(self, comm_from_pc: bytes) -> None:
        # pylint: disable=too-many-branches  # Tanner (11/15/21): many branches needed here to handle all types of communication. Could try refactoring int smaller methods for similar packet types
        status_code_update: Optional[int] = None

        timestamp_from_pc_bytes = comm_from_pc[
            SERIAL_COMM_TIMESTAMP_BYTES_INDEX : SERIAL_COMM_TIMESTAMP_BYTES_INDEX
            + SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
        ]

        response_body = timestamp_from_pc_bytes
        response_packet_type = SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE

        packet_type = comm_from_pc[SERIAL_COMM_PACKET_TYPE_INDEX]
        if packet_type == SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE:
            command_byte = comm_from_pc[SERIAL_COMM_ADDITIONAL_BYTES_INDEX]
            if command_byte == SERIAL_COMM_REBOOT_COMMAND_BYTE:
                self._reboot_time_secs = perf_counter()
            elif command_byte == SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE:
                response_body += self._update_magnetometer_config(comm_from_pc)
            elif command_byte == SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE:
                is_data_already_streaming = self._is_streaming_data
                response_body += bytes([is_data_already_streaming])
                self._is_streaming_data = True
                if not is_data_already_streaming:
                    response_body += self._time_index_us.to_bytes(8, byteorder="little")
                    response_body += self._sampling_period_us.to_bytes(2, byteorder="little")
                    response_body += create_magnetometer_config_bytes(self._magnetometer_config)
            elif command_byte == SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE:
                response_body += bytes([not self._is_streaming_data])
                self._is_streaming_data = False
            elif command_byte == SERIAL_COMM_GET_METADATA_COMMAND_BYTE:
                metadata_bytes = bytes(0)
                for key, value in self._metadata_dict.items():
                    metadata_bytes += key + value
                response_body += metadata_bytes
            elif command_byte == SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE:
                response_body += self.get_eeprom_bytes()
            elif command_byte == SERIAL_COMM_SET_TIME_COMMAND_BYTE:
                self._baseline_time_us = int.from_bytes(response_body, byteorder="little")
                self._timepoint_of_time_sync_us = _perf_counter_us()
                status_code_update = SERIAL_COMM_IDLE_READY_CODE
                self._ready_to_send_barcode = True
            elif command_byte == SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE:
                start_idx = SERIAL_COMM_ADDITIONAL_BYTES_INDEX + 1
                nickname_bytes = comm_from_pc[start_idx : start_idx + SERIAL_COMM_METADATA_BYTES_LENGTH]
                self._metadata_dict[MANTARRAY_NICKNAME_UUID.bytes] = nickname_bytes
            else:
                # TODO Tanner (3/4/21): Determine what to do if command_byte, module_id, or packet_type are incorrect. It may make more sense to respond with a message rather than raising an error
                raise NotImplementedError(command_byte)
        elif packet_type == SERIAL_COMM_HANDSHAKE_PACKET_TYPE:
            self._time_of_last_handshake_secs = perf_counter()
            response_body += convert_to_status_code_bytes(self._status_code)
        elif packet_type == SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE:
            # command fails if > 24 unique protocols given, the length of the array of protocol IDs != 24, or if > 50 subprotocols are in a single protocol
            stim_info_dict = convert_stim_bytes_to_dict(
                comm_from_pc[SERIAL_COMM_ADDITIONAL_BYTES_INDEX:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES]
            )
            command_failed = (
                self._is_stimulating
                or len(stim_info_dict["protocols"]) > self._num_wells
                or len(stim_info_dict["protocol_assignments"]) != self._num_wells
                or any(
                    len(protocol_dict["subprotocols"]) > STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
                    for protocol_dict in stim_info_dict["protocols"]
                )
            )
            if not command_failed:
                self._stim_info = stim_info_dict
            response_body += bytes([command_failed])
        elif packet_type == SERIAL_COMM_START_STIM_PACKET_TYPE:
            # command fails if protocols are not set or if stimulation is already running
            command_failed = "protocol_assignments" not in self._stim_info or self._is_stimulating
            response_body += bytes([command_failed])
            if not command_failed:
                self._is_stimulating = True
                response_body += self._stim_time_indices[0].to_bytes(8, byteorder="little")
        elif packet_type == SERIAL_COMM_STOP_STIM_PACKET_TYPE:
            # command fails only if stimulation is not currently running
            command_failed = not self._is_stimulating
            response_body += bytes([command_failed])
            if not command_failed:
                self._handle_manual_stim_stop()
                self._is_stimulating = False
        elif packet_type == SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE:
            firmware_type = comm_from_pc[SERIAL_COMM_ADDITIONAL_BYTES_INDEX]
            command_failed = firmware_type not in (0, 1) or self._firmware_update_type is not None
            self._firmware_update_idx = 0
            self._firmware_update_type = firmware_type
            self._firmware_update_bytes = bytes(0)
            response_packet_type = SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
            response_body += bytes([command_failed])
        elif packet_type == SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE:
            if self._firmware_update_bytes is None:
                # Tanner (11/10/21): currently unsure how real board would handle receiving this packet before the previous two firmware packet types
                raise NotImplementedError("_firmware_update_bytes should never be None here")
            if self._firmware_update_idx is None:
                # Tanner (11/10/21): currently unsure how real board would handle receiving this packet before the previous two firmware packet types
                raise NotImplementedError("_firmware_update_idx should never be None here")
            packet_idx = comm_from_pc[SERIAL_COMM_ADDITIONAL_BYTES_INDEX]
            new_firmware_bytes = comm_from_pc[
                SERIAL_COMM_ADDITIONAL_BYTES_INDEX + 1 : -SERIAL_COMM_CHECKSUM_LENGTH_BYTES
            ]
            command_failed = (
                len(new_firmware_bytes) > SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES - 1
                or packet_idx != self._firmware_update_idx
            )
            response_packet_type = SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
            response_body += bytes([command_failed])
            self._firmware_update_bytes += new_firmware_bytes
            self._firmware_update_idx += 1
        elif packet_type == SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE:
            if self._firmware_update_type is None:
                # Tanner (11/10/21): currently unsure how real board would handle receiving this packet before the previous two firmware packet types
                raise NotImplementedError("_firmware_update_type should never be None here")
            if self._firmware_update_bytes is None:
                # Tanner (11/10/21): currently unsure how real board would handle receiving this packet before the previous two firmware packet types
                raise NotImplementedError("_firmware_update_bytes should never be None here")
            response_packet_type = SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE
            received_checksum = int.from_bytes(
                comm_from_pc[SERIAL_COMM_ADDITIONAL_BYTES_INDEX : SERIAL_COMM_ADDITIONAL_BYTES_INDEX + 4],
                byteorder="little",
            )
            calculated_checksum = crc32(self._firmware_update_bytes)
            checksum_failure = received_checksum != calculated_checksum
            response_body += bytes([checksum_failure])
            if not checksum_failure:
                self._reboot_time_secs = perf_counter()
        else:
            module_id = comm_from_pc[SERIAL_COMM_MODULE_ID_INDEX]
            raise UnrecognizedSerialCommPacketTypeError(
                f"Packet Type ID: {packet_type} is not defined for Module ID: {module_id}"
            )
        self._send_data_packet(
            SERIAL_COMM_MAIN_MODULE_ID,
            response_packet_type,
            response_body,
        )
        # update status code (if an update is necessary) after sending command response
        if status_code_update is not None:
            self._update_status_code(status_code_update)

    def _update_magnetometer_config(self, comm_from_pc: bytes) -> bytes:
        update_status_byte = bytes([self._is_streaming_data])
        if self._is_streaming_data:
            # cannot change configuration while data is streaming, so return here
            return update_status_byte
        # check and set sampling period
        sampling_period = int.from_bytes(
            comm_from_pc[SERIAL_COMM_ADDITIONAL_BYTES_INDEX + 1 : SERIAL_COMM_ADDITIONAL_BYTES_INDEX + 3],
            byteorder="little",
        )
        if sampling_period % MICROSECONDS_PER_MILLISECOND != 0:
            raise SerialCommInvalidSamplingPeriodError(sampling_period)
        self._sampling_period_us = sampling_period
        # parse and store magnetometer configuration
        magnetometer_config_bytes = comm_from_pc[
            SERIAL_COMM_ADDITIONAL_BYTES_INDEX + 3 : -SERIAL_COMM_CHECKSUM_LENGTH_BYTES
        ]
        config_dict_updates = convert_bytes_to_config_dict(magnetometer_config_bytes)
        # Tanner (6/2/21): Need to make sure module ID keys are in order
        self._magnetometer_config.update(sort_nested_dict(config_dict_updates))
        return update_status_byte

    def _update_status_code(self, new_code: int) -> None:
        self._status_code = new_code
        self._send_status_beacon()

    def _handle_status_beacon(self) -> None:
        if self._time_of_last_status_beacon_secs is None:
            self._send_status_beacon(truncate=True)
            return
        seconds_elapsed = _get_secs_since_last_status_beacon(self._time_of_last_status_beacon_secs)
        if seconds_elapsed >= SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS:
            self._send_status_beacon(truncate=False)

    def _send_status_beacon(self, truncate: bool = False) -> None:
        self._time_of_last_status_beacon_secs = perf_counter()
        self._send_data_packet(
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
            convert_to_status_code_bytes(self._status_code),
            truncate,
        )

    def _check_handshake(self) -> None:
        if self._time_of_last_handshake_secs is None:
            return
        time_of_last_handshake_secs = _get_secs_since_last_handshake(self._time_of_last_handshake_secs)
        if (
            time_of_last_handshake_secs
            >= SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS * SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
        ):
            raise SerialCommTooManyMissedHandshakesError()

    def _handle_manual_stim_stop(self) -> None:
        num_status_updates = 0
        status_update_bytes = bytes(0)
        stop_time_index = self._get_global_timer()
        for well_name, is_stim_running in self._stim_running_statuses.items():
            if not is_stim_running:
                continue
            num_status_updates += 1
            well_idx = GENERIC_24_WELL_DEFINITION.get_well_index_from_well_name(well_name)
            status_update_bytes += (
                bytes([STIM_WELL_IDX_TO_MODULE_ID[well_idx]])
                + bytes([StimStatuses.FINISHED])
                + stop_time_index.to_bytes(8, byteorder="little")
                + bytes([STIM_COMPLETE_SUBPROTOCOL_IDX])
            )
        self._send_data_packet(
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_STIM_STATUS_PACKET_TYPE,
            bytes([num_status_updates]) + status_update_bytes,
        )

    def _handle_test_comm(self) -> None:
        # pylint: disable=too-many-nested-blocks  # Tanner (11/10/21): unsure why this error is appearing all of a sudden
        try:
            test_comm = self._testing_queue.get_nowait()
        except queue.Empty:
            return

        command = test_comm["command"]
        if command == "raise_error":
            raise test_comm["error"]
        if command == "send_single_beacon":
            self._send_data_packet(
                SERIAL_COMM_MAIN_MODULE_ID,
                SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
                convert_to_status_code_bytes(self._status_code),
            )
        elif command == "add_read_bytes":
            read_bytes = test_comm["read_bytes"]
            if not isinstance(read_bytes, list):
                read_bytes = [read_bytes]
            for read in read_bytes:
                self._output_queue.put_nowait(read)
        elif command == "set_status_code":
            status_code = test_comm["status_code"]
            self._status_code = status_code
            baseline_time = test_comm.get("baseline_time", None)
            if baseline_time is not None:
                if status_code in (
                    SERIAL_COMM_BOOT_UP_CODE,
                    SERIAL_COMM_TIME_SYNC_READY_CODE,
                ):
                    raise NotImplementedError(
                        "baseline_time cannot be set through testing queue in boot up or time sync state"
                    )
                self._baseline_time_us = baseline_time
                self._timepoint_of_time_sync_us = _perf_counter_us()
            # Tanner (4/12/21): simulator has no other way of reaching this state since it has no physical components that can break, so this is the only way to reach this state and the status beacon should be sent automatically
            if status_code == SERIAL_COMM_FATAL_ERROR_CODE:
                self._send_data_packet(
                    SERIAL_COMM_MAIN_MODULE_ID,
                    SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
                    convert_to_status_code_bytes(self._status_code) + self.get_eeprom_bytes(),
                )
        elif command == "set_metadata":
            for key, value in test_comm["metadata_values"].items():
                value_bytes = convert_to_metadata_bytes(value)
                self._metadata_dict[key.bytes] = value_bytes
        elif command == "set_data_streaming_status":
            self._sampling_period_us = test_comm.get("sampling_period", DEFAULT_SAMPLING_PERIOD)
            self._is_streaming_data = test_comm["data_streaming_status"]
            self._simulated_data_index = test_comm.get("simulated_data_index", 0)
        elif command == "set_sampling_period":
            self._sampling_period_us = test_comm["sampling_period"]
        elif command == "set_stim_info":
            self._stim_info = test_comm["stim_info"]
        elif command == "set_stim_status":
            self._is_stimulating = test_comm["status"]
        elif command == "set_firmware_update_type":
            self._firmware_update_type = test_comm["firmware_type"]
        else:
            raise UnrecognizedSimulatorTestCommandError(command)

    def _handle_sending_data_packets(self) -> None:
        """Send the required number of data packets.

        Since this process iterates once per 10 ms, it is possible that
        more than one data packet must be sent.
        """
        if self._timepoint_of_last_data_packet_us is None:  # making mypy happy
            raise NotImplementedError("_timepoint_of_last_data_packet_us should never be None here")
        us_since_last_data_packet = _get_us_since_last_data_packet(self._timepoint_of_last_data_packet_us)
        num_packets_to_send = us_since_last_data_packet // self._sampling_period_us
        if num_packets_to_send == 0:
            return
        simulated_data_len = len(self._simulated_data)

        data_packet_bytes = bytes(0)
        for _ in range(num_packets_to_send):
            # not using _send_data_packet here because it is more efficient to send all packets at once
            data_packet_bytes += create_data_packet(
                self._get_timestamp(),
                SERIAL_COMM_MAIN_MODULE_ID,
                SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
                self._create_data_packet_body(),
            )
            # increment values
            self._time_index_us += self._sampling_period_us
            self._simulated_data_index = (self._simulated_data_index + 1) % simulated_data_len
        self._output_queue.put_nowait(data_packet_bytes)
        # update timepoint
        self._timepoint_of_last_data_packet_us += num_packets_to_send * self._sampling_period_us

    def _create_data_packet_body(self) -> bytes:
        # add time index to data packet body
        data_packet_body = self._time_index_us.to_bytes(
            SERIAL_COMM_TIME_INDEX_LENGTH_BYTES, byteorder="little"
        )
        for module_id in range(1, self._num_wells + 1):
            config_values = list(self._magnetometer_config[module_id].values())
            for sensor_base_idx in range(0, SERIAL_COMM_NUM_DATA_CHANNELS, SERIAL_COMM_NUM_SENSORS_PER_WELL):
                if not any(
                    config_values[sensor_base_idx : sensor_base_idx + SERIAL_COMM_NUM_SENSORS_PER_WELL]
                ):
                    continue
                offset = bytes(SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES)  # use 0 for offset in simulated data
                data_packet_body += offset
                # create data points
                data_value = self._simulated_data[self._simulated_data_index] * np.uint16(
                    SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id] + 1
                )
                data_value_bytes = data_value.tobytes()
                for axis_idx in range(SERIAL_COMM_NUM_CHANNELS_PER_SENSOR):
                    # add data points
                    channel_id = sensor_base_idx + axis_idx
                    if self._magnetometer_config[module_id][channel_id]:
                        data_packet_body += data_value_bytes
        return data_packet_body

    def _handle_stimulation_packets(self) -> None:
        num_status_updates = 0
        packet_bytes = bytes(0)
        for protocol_idx, protocol in enumerate(self._stim_info["protocols"]):
            start_timepoint = self._timepoints_of_subprotocols_start[protocol_idx]
            if start_timepoint is None:
                continue
            subprotocols = protocol["subprotocols"]

            if self._stim_subprotocol_indices[protocol_idx] == -1:
                curr_subprotocol_duration_us = 0
            else:
                curr_subprotocol_duration_us = subprotocols[self._stim_subprotocol_indices[protocol_idx]][
                    "total_active_duration"
                ]
                curr_subprotocol_duration_us *= int(1e3)  # convert from ms to µs
            dur_since_subprotocol_start = _get_us_since_subprotocol_start(start_timepoint)
            while dur_since_subprotocol_start >= curr_subprotocol_duration_us:
                # update time index for subprotocol
                self._stim_time_indices[protocol_idx] += curr_subprotocol_duration_us
                # move on to next subprotocol in protocol
                self._stim_subprotocol_indices[protocol_idx] = (
                    self._stim_subprotocol_indices[protocol_idx] + 1
                ) % len(subprotocols)

                status_bytes = (
                    bytes([self._get_stim_status_value(protocol_idx)])
                    + self._stim_time_indices[protocol_idx].to_bytes(8, byteorder="little")
                    + bytes([self._stim_subprotocol_indices[protocol_idx]])
                )
                protocol_complete = (
                    self._stim_subprotocol_indices[protocol_idx] == 0 and curr_subprotocol_duration_us > 0
                )
                protocol_stopping = not protocol["run_until_stopped"] if protocol_complete else False
                if protocol_complete:
                    protocol_complete_status = (
                        StimStatuses.FINISHED if protocol_stopping else StimStatuses.RESTARTING
                    )
                    protocol_complete_bytes = bytes([protocol_complete_status]) + status_bytes[1:]
                    if protocol_stopping:
                        # change subprotocol idx in status bytes
                        protocol_complete_bytes = protocol_complete_bytes[:-1] + bytes(
                            [STIM_COMPLETE_SUBPROTOCOL_IDX]
                        )

                for well_name, protocol_assigment in self._stim_info["protocol_assignments"].items():
                    if protocol_assigment != protocol_idx:
                        continue
                    module_id = convert_well_name_to_module_id(well_name, use_stim_mapping=True)
                    if protocol_complete:
                        packet_bytes += bytes([module_id]) + protocol_complete_bytes
                        num_status_updates += 1
                        if protocol_stopping:
                            # change subprotocol idx in status bytes
                            continue
                    packet_bytes += bytes([module_id]) + status_bytes
                    num_status_updates += 1  # increment for all statuses
                if protocol_stopping:
                    self._timepoints_of_subprotocols_start[protocol_idx] = None
                    break

                # update timepoints and durations for next iteration
                self._timepoints_of_subprotocols_start[  # type: ignore  # mypy doesn't understand that this value has already been checked to not be None
                    protocol_idx
                ] += curr_subprotocol_duration_us
                dur_since_subprotocol_start -= curr_subprotocol_duration_us
                curr_subprotocol_duration_us = subprotocols[self._stim_subprotocol_indices[protocol_idx]][
                    "total_active_duration"
                ]
                curr_subprotocol_duration_us *= int(1e3)  # convert from ms to µs
        if num_status_updates > 0:
            packet_bytes = bytes([num_status_updates]) + packet_bytes
            self._send_data_packet(
                SERIAL_COMM_MAIN_MODULE_ID,
                SERIAL_COMM_STIM_STATUS_PACKET_TYPE,
                packet_bytes,
            )
        # if all timepoints are None, stimulation has ended
        self._is_stimulating = any(self._timepoints_of_subprotocols_start)

    def _get_stim_status_value(self, protocol_idx: int) -> int:
        subprotocol_idx = self._stim_subprotocol_indices[protocol_idx]
        subprotocol_dict = self._stim_info["protocols"][protocol_idx]["subprotocols"][subprotocol_idx]
        return StimStatuses.NULL if is_null_subprotocol(subprotocol_dict) else StimStatuses.ACTIVE

    def read(self, size: int = 1) -> bytes:
        """Read the given number of bytes from the simulator."""
        # first check leftover bytes from last read
        read_bytes = bytes(0)
        if len(self._leftover_read_bytes) > 0:
            read_bytes = self._leftover_read_bytes
            self._leftover_read_bytes = bytes(0)
        # try to get bytes until either timeout occurs or given size is reached or exceeded
        start = perf_counter()
        read_dur_secs = 0.0
        while len(read_bytes) < size and read_dur_secs <= self._read_timeout_seconds:
            read_dur_secs = perf_counter() - start
            try:
                next_bytes = self._output_queue.get_nowait()
                read_bytes += next_bytes
            except queue.Empty:
                pass
        # if this read exceeds given size then store extra bytes for the next read
        if len(read_bytes) > size:
            size_diff = len(read_bytes) - size
            self._leftover_read_bytes = read_bytes[-size_diff:]
            read_bytes = read_bytes[:-size_diff]
        return read_bytes

    def read_all(self) -> bytes:
        """Read all available bytes from the simulator."""
        read_bytes = bytes(0)
        if len(self._leftover_read_bytes) > 0:
            read_bytes = self._leftover_read_bytes
            self._leftover_read_bytes = bytes(0)
        start = perf_counter()
        read_dur_secs = 0.0
        while read_dur_secs <= self._read_timeout_seconds:
            read_dur_secs = perf_counter() - start
            try:
                next_bytes = self._output_queue.get_nowait()
                read_bytes += next_bytes
            except queue.Empty:
                pass
        return read_bytes

    def write(self, input_item: bytes) -> None:
        self._input_queue.put_nowait(input_item)

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items = {
            "input_queue": drain_queue(self._input_queue),
            "output_queue": drain_queue(self._output_queue),
            "testing_queue": drain_queue(self._testing_queue),
        }
        return queue_items
