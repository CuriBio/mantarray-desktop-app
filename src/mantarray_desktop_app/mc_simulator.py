# -*- coding: utf-8 -*-
"""Mantarray Microcontroller Simulator."""
from __future__ import annotations

import csv
import logging
from multiprocessing import Queue
import os
import queue
import random
from time import perf_counter
from time import perf_counter_ns
from typing import Any
from typing import Dict
from typing import Optional
from typing import Union
from uuid import UUID

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

from .constants import CENTIMILLISECONDS_PER_SECOND
from .constants import MAX_MC_REBOOT_DURATION_SECONDS
from .constants import MICROSECONDS_PER_CENTIMILLISECOND
from .constants import MICROSECONDS_PER_MILLISECOND
from .constants import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from .constants import SERIAL_COMM_BOOT_UP_CODE
from .constants import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from .constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from .constants import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from .constants import SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE
from .constants import SERIAL_COMM_FATAL_ERROR_CODE
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
from .constants import SERIAL_COMM_METADATA_BYTES_LENGTH
from .constants import SERIAL_COMM_MODULE_ID_INDEX
from .constants import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from .constants import SERIAL_COMM_NUM_DATA_CHANNELS
from .constants import SERIAL_COMM_PACKET_TYPE_INDEX
from .constants import SERIAL_COMM_PLATE_EVENT_PACKET_TYPE
from .constants import SERIAL_COMM_REBOOT_COMMAND_BYTE
from .constants import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from .constants import SERIAL_COMM_SET_TIME_COMMAND_BYTE
from .constants import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from .constants import SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .constants import SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from .constants import SERIAL_COMM_TIME_SYNC_READY_CODE
from .constants import SERIAL_COMM_TIMESTAMP_BYTES_INDEX
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .exceptions import SerialCommInvalidSamplingPeriodError
from .exceptions import SerialCommTooManyMissedHandshakesError
from .exceptions import UnrecognizedSerialCommModuleIdError
from .exceptions import UnrecognizedSerialCommPacketTypeError
from .exceptions import UnrecognizedSimulatorTestCommandError
from .serial_comm_utils import convert_bytes_to_config_dict
from .serial_comm_utils import convert_to_metadata_bytes
from .serial_comm_utils import convert_to_status_code_bytes
from .serial_comm_utils import create_data_packet
from .serial_comm_utils import create_magnetometer_config_bytes
from .serial_comm_utils import validate_checksum
from .utils import create_magnetometer_config_dict


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


def _get_secs_since_reboot_command(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_boot_up(start_time: float) -> float:
    return perf_counter() - start_time


def _get_secs_since_last_comm_from_pc(last_time: float) -> float:
    return perf_counter() - last_time


def _get_us_since_last_data_packet(last_time_us: int) -> int:
    return _perf_counter_us() - last_time_us


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
        self._simulated_data: NDArray[np.int16] = np.array([], dtype=np.int16)
        self._metadata_dict: Dict[bytes, bytes] = dict()
        self._reset_metadata_dict()
        self._setup_data_interpolator()
        # simulator values (set in _handle_boot_up_config)
        self._reboot_time_secs: Optional[float]
        self._status_code: int
        self._magnetometer_config: Dict[int, Dict[int, bool]]
        self._baseline_time_usec: Optional[int]
        self._timepoint_of_time_sync_us: Optional[int]
        self._sampling_period_us: int
        self._boot_up_time_secs: Optional[float] = None
        self._handle_boot_up_config()

    @property
    def _is_streaming_data(self) -> bool:
        return self._timepoint_of_last_data_packet_us is not None

    @_is_streaming_data.setter
    def _is_streaming_data(self, value: bool) -> None:
        if value:
            self._timepoint_of_last_data_packet_us = _perf_counter_us()
            self._simulated_data_index = 0
            self._time_index_us = 0
            if self._sampling_period_us == 0:
                # TODO Tanner (5/13/21): Need to determine what to do if sampling period is not set when data begins streaming
                raise NotImplementedError("sampling period must be set before streaming data")
            self._simulated_data = self.get_interpolated_data(self._sampling_period_us)
        else:
            self._timepoint_of_last_data_packet_us = None

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
            np.array(simulated_data_timepoints, dtype=np.uint64) // MICROSECONDS_PER_CENTIMILLISECOND,
            simulated_data_values,
        )

    def _handle_boot_up_config(self, reboot: bool = False) -> None:
        self._reset_start_time()
        self._reboot_time_secs = None
        self._status_code = SERIAL_COMM_BOOT_UP_CODE
        self._reset_magnetometer_config()
        self._baseline_time_usec = None
        self._timepoint_of_time_sync_us = None
        self._sampling_period_us = 0
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

    def _get_us_since_time_sync(self) -> int:
        return (
            0
            if self._timepoint_of_time_sync_us is None
            else _perf_counter_us() - self._timepoint_of_time_sync_us
        )

    def get_metadata_dict(self) -> Dict[bytes, bytes]:
        """Mainly for use in unit tests."""
        return self._metadata_dict

    def get_status_code(self) -> int:
        """Mainly for use in unit tests."""
        return self._status_code

    def get_eeprom_bytes(self) -> bytes:
        eeprom_dict = {
            "Status Code": self._status_code,
            "Time Sync Value received from PC (microseconds)": self._baseline_time_usec,
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

    def get_interpolated_data(self, sampling_period_us: int) -> NDArray[np.int16]:
        """Return one second (one twitch) of interpolated data."""
        data_indices = np.arange(
            0,
            CENTIMILLISECONDS_PER_SECOND,
            sampling_period_us // MICROSECONDS_PER_CENTIMILLISECOND,
        )
        return self._interpolator(data_indices).astype(np.int16)

    def get_num_wells(self) -> int:
        return self._num_wells

    def _get_timestamp(self) -> int:
        timestamp: int = (
            self.get_cms_since_init()
            if self._baseline_time_usec is None
            else (self._baseline_time_usec + self._get_us_since_time_sync())
            // MICROSECONDS_PER_CENTIMILLISECOND
        )
        return timestamp

    def _send_data_packet(
        self,
        module_id: int,
        packet_type: int,
        data_to_send: bytes = bytes(0),
        truncate: bool = False,
    ) -> None:
        # TODO Tanner (4/7/21): convert timestamp to microseconds once real board makes the switch
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
        7. Check if the handshake from the PC is overdue. This should be done after checking for data sent from the PC since the next packet might be a handshake.
        8. Check if the barcode is ready to send. This is currently the lowest priority.
        """
        self._handle_test_comm()
        if self._status_code == SERIAL_COMM_FATAL_ERROR_CODE:
            return
        # if _reboot_time_secs is not None, this means the simulator is in a "reboot" phase
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
        status_code_update: Optional[int] = None

        timestamp_from_pc_bytes = comm_from_pc[
            SERIAL_COMM_TIMESTAMP_BYTES_INDEX : SERIAL_COMM_TIMESTAMP_BYTES_INDEX
            + SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
        ]
        response_body = timestamp_from_pc_bytes
        packet_type = comm_from_pc[SERIAL_COMM_PACKET_TYPE_INDEX]
        if packet_type == SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE:
            command_byte = comm_from_pc[SERIAL_COMM_ADDITIONAL_BYTES_INDEX]
            if command_byte == SERIAL_COMM_REBOOT_COMMAND_BYTE:
                self._reboot_time_secs = perf_counter()
            elif command_byte == SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE:
                response_body += self._update_magnetometer_config(comm_from_pc)
            elif command_byte == SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE:
                response_byte = int(self._is_streaming_data)
                response_body += bytes([response_byte])
                if not self._is_streaming_data:
                    response_body += create_magnetometer_config_bytes(self._magnetometer_config)
                self._is_streaming_data = True
            elif command_byte == SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE:
                response_byte = int(not self._is_streaming_data)
                response_body += bytes([response_byte])
                self._is_streaming_data = False
            elif command_byte == SERIAL_COMM_GET_METADATA_COMMAND_BYTE:
                metadata_bytes = bytes(0)
                for key, value in self._metadata_dict.items():
                    metadata_bytes += key + value
                response_body += metadata_bytes
            elif command_byte == SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE:
                response_body += self.get_eeprom_bytes()
            elif command_byte == SERIAL_COMM_SET_TIME_COMMAND_BYTE:
                self._baseline_time_usec = int.from_bytes(response_body, byteorder="little")
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
        else:
            module_id = comm_from_pc[SERIAL_COMM_MODULE_ID_INDEX]
            raise UnrecognizedSerialCommPacketTypeError(
                f"Packet Type ID: {packet_type} is not defined for Module ID: {module_id}"
            )
        self._send_data_packet(
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
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
        magnetometer_config_bytes = comm_from_pc[  #
            SERIAL_COMM_ADDITIONAL_BYTES_INDEX + 3 : -SERIAL_COMM_CHECKSUM_LENGTH_BYTES
        ]
        config_dict_updates = convert_bytes_to_config_dict(magnetometer_config_bytes)
        self._magnetometer_config.update(config_dict_updates)
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

    def _handle_test_comm(self) -> None:
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
                self._baseline_time_usec = baseline_time
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
            self._sampling_period_us = test_comm.get("sampling_period", 10000)
            self._is_streaming_data = test_comm["data_streaming_status"]
        elif command == "set_sampling_period":
            self._sampling_period_us = test_comm["sampling_period"]
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
        simulated_data_len = len(self._simulated_data)
        num_packets_to_send = us_since_last_data_packet // self._sampling_period_us
        if num_packets_to_send == 0:
            return

        data_packet_bytes = bytes(0)
        for _ in range(num_packets_to_send):
            data_packet_body = (self._time_index_us // MICROSECONDS_PER_CENTIMILLISECOND).to_bytes(
                SERIAL_COMM_TIME_INDEX_LENGTH_BYTES, byteorder="little"
            )
            for well_idx in range(self._num_wells):
                if not any(self._magnetometer_config[well_idx + 1].values()):
                    continue
                data_value = self._simulated_data[self._simulated_data_index] * np.int16(well_idx + 1)
                data_value_bytes = data_value.tobytes()
                for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
                    if self._magnetometer_config[well_idx + 1][channel_id]:
                        data_packet_body += data_value_bytes
            # not using _send_data_packet here because it is more efficient to send all packets at once
            data_packet_bytes += create_data_packet(
                self._get_timestamp(),
                SERIAL_COMM_MAIN_MODULE_ID,
                SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
                data_packet_body,
            )
            # increment values
            self._time_index_us += self._sampling_period_us
            self._simulated_data_index = (self._simulated_data_index + 1) % simulated_data_len
        self._output_queue.put_nowait(data_packet_bytes)
        # update timepoint
        self._timepoint_of_last_data_packet_us += num_packets_to_send * self._sampling_period_us

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
