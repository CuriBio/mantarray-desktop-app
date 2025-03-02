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
import struct
from time import perf_counter
from time import perf_counter_ns
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from uuid import UUID
from zlib import crc32

from immutabledict import immutabledict
from nptyping import NDArray
import numpy as np
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import INITIAL_MAGNET_FINDING_PARAMS_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
from scipy import interpolate
from stdlib_utils import drain_queue
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import InfiniteProcess
from stdlib_utils import resource_path

from ..constants import DEFAULT_SAMPLING_PERIOD
from ..constants import GOING_DORMANT_HANDSHAKE_TIMEOUT_CODE
from ..constants import MAX_MC_REBOOT_DURATION_SECONDS
from ..constants import MICRO_TO_BASE_CONVERSION
from ..constants import MICROS_PER_MILLI
from ..constants import MICROSECONDS_PER_CENTIMILLISECOND
from ..constants import SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE
from ..constants import SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
from ..constants import SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE
from ..constants import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from ..constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from ..constants import SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE
from ..constants import SERIAL_COMM_ERROR_ACK_PACKET_TYPE
from ..constants import SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
from ..constants import SERIAL_COMM_GET_ERROR_DETAILS_PACKET_TYPE
from ..constants import SERIAL_COMM_GET_METADATA_PACKET_TYPE
from ..constants import SERIAL_COMM_GOING_DORMANT_PACKET_TYPE
from ..constants import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from ..constants import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from ..constants import SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS
from ..constants import SERIAL_COMM_MAGIC_WORD_BYTES
from ..constants import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from ..constants import SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES
from ..constants import SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE
from ..constants import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from ..constants import SERIAL_COMM_NICKNAME_BYTES_LENGTH
from ..constants import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from ..constants import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from ..constants import SERIAL_COMM_NUM_SENSORS_PER_WELL
from ..constants import SERIAL_COMM_OKAY_CODE
from ..constants import SERIAL_COMM_PACKET_TYPE_INDEX
from ..constants import SERIAL_COMM_PAYLOAD_INDEX
from ..constants import SERIAL_COMM_REBOOT_PACKET_TYPE
from ..constants import SERIAL_COMM_SET_NICKNAME_PACKET_TYPE
from ..constants import SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE
from ..constants import SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
from ..constants import SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE
from ..constants import SERIAL_COMM_START_STIM_PACKET_TYPE
from ..constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from ..constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from ..constants import SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE
from ..constants import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from ..constants import SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE
from ..constants import SERIAL_COMM_STOP_STIM_PACKET_TYPE
from ..constants import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from ..constants import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from ..constants import STIM_COMPLETE_SUBPROTOCOL_IDX
from ..constants import STIM_WELL_IDX_TO_MODULE_ID
from ..constants import StimProtocolStatuses
from ..exceptions import SerialCommInvalidSamplingPeriodError
from ..exceptions import SerialCommTooManyMissedHandshakesError
from ..exceptions import UnrecognizedSerialCommPacketTypeError
from ..exceptions import UnrecognizedSimulatorTestCommandError
from ..utils.serial_comm import convert_adc_readings_to_circuit_status
from ..utils.serial_comm import convert_instrument_event_info_to_bytes
from ..utils.serial_comm import convert_metadata_to_bytes
from ..utils.serial_comm import convert_stim_bytes_to_dict
from ..utils.serial_comm import create_data_packet
from ..utils.serial_comm import is_null_subprotocol
from ..utils.serial_comm import validate_checksum
from ..utils.stimulation import get_subprotocol_dur_us
from ..utils.stimulation import StimulationProtocolManager


MAGIC_WORD_LEN = len(SERIAL_COMM_MAGIC_WORD_BYTES)
AVERAGE_MC_REBOOT_DURATION_SECONDS = MAX_MC_REBOOT_DURATION_SECONDS / 2
SIMULATOR_BARCODE_SEND_PERIOD_SECS = 5


def _perf_counter_us() -> int:
    """Return perf_counter value as microseconds."""
    return perf_counter_ns() // 10**3


def _get_secs_since_read_start(start: float) -> float:
    return perf_counter() - start


def _get_secs_since_last_handshake(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_last_status_beacon(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_last_barcode_scan(last_time: float) -> float:
    return perf_counter() - last_time


def _get_secs_since_reboot_command(command_time: float) -> float:
    return perf_counter() - command_time


def _get_secs_since_last_comm_from_pc(last_time: float) -> float:
    return perf_counter() - last_time


def _get_us_since_last_data_packet(last_time_us: int) -> int:
    return _perf_counter_us() - last_time_us


def _get_us_since_subprotocol_start(start_time_us: int) -> int:
    return _perf_counter_us() - start_time_us


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

    # values for V1 instrument as of 6/17/22
    initial_magnet_finding_params: immutabledict[str, int] = immutabledict(
        {"X": 0, "Y": 2, "Z": -5, "REMN": 1200}
    )

    default_mantarray_nickname = "Mantarray Sim"
    default_mantarray_serial_number = "MA2022001000"
    default_main_firmware_version = "0.0.0"
    default_channel_firmware_version = "0.0.0"
    default_plate_barcode = "ML22001000-2"
    default_stim_barcode = "MS22001000-2"
    default_event_info = immutabledict(
        {
            "prev_main_status_update_timestamp": 1,
            "prev_channel_status_update_timestamp": 2,
            "start_of_prev_mag_data_stream_timestamp": 3,
            "start_of_prev_stim_timestamp": 4,
            "prev_handshake_received_timestamp": 5,
            "prev_system_going_dormant_timestamp": 6,
            "mag_data_stream_active": False,
            "stim_active": False,
            "pc_connection_status": 1,
            "prev_barcode_scanned": default_plate_barcode,
        }
    )
    default_metadata_values: immutabledict[UUID, Any] = immutabledict(
        {
            BOOT_FLAGS_UUID: 0b00000000,
            MANTARRAY_SERIAL_NUMBER_UUID: default_mantarray_serial_number,
            MANTARRAY_NICKNAME_UUID: default_mantarray_nickname,
            MAIN_FIRMWARE_VERSION_UUID: default_main_firmware_version,
            CHANNEL_FIRMWARE_VERSION_UUID: default_channel_firmware_version,
            INITIAL_MAGNET_FINDING_PARAMS_UUID: initial_magnet_finding_params,
            "is_stingray": False,
            **default_event_info,
        }
    )
    default_adc_reading = 0xFF00
    global_timer_offset_secs = 2.5  # TODO Tanner (11/17/21): figure out if this should be removed

    def __init__(
        self,
        input_queue: Queue[bytes],
        output_queue: Queue[bytes],
        fatal_error_reporter: Queue[Dict[str, Any]],
        testing_queue: Queue[Dict[str, Any]],
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
        self._time_of_last_barcode_send_secs: Optional[float] = None
        self._timepoint_of_last_data_packet_us: Optional[int] = None
        self._time_index_us = 0
        self._is_first_data_stream = True
        self._simulated_data_index = 0
        self._simulated_data: NDArray[np.uint16] = np.array([], dtype=np.uint16)
        self._metadata_dict: Dict[UUID | str, Any] = dict()
        self._reset_metadata_dict()
        self._setup_data_interpolator()
        # simulator values (set in _handle_boot_up_config)
        self._time_of_last_handshake_secs: Optional[float] = None
        self._time_of_last_comm_from_pc_secs: Optional[float] = None
        self._reboot_again = False
        self._reboot_time_secs: Optional[float]
        self._boot_up_time_secs: Optional[float] = None
        self._status_codes: List[int]
        self._sampling_period_us: int
        self._adc_readings: List[Tuple[int, int]]
        self._stim_info: Dict[str, Any]
        # TODO move all the stim info below into StimulationProtocolManager?
        self._stim_running_statuses: List[bool] = []
        self._timepoints_of_subprotocols_start: List[Optional[int]]
        self._stim_time_indices: List[int]
        self._stim_subprotocol_managers: List[StimulationProtocolManager]
        self._firmware_update_type: Optional[int] = None
        self._firmware_update_idx: Optional[int] = None
        self._firmware_update_bytes: Optional[bytes]
        self._new_nickname: Optional[str] = None
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
        return any(self._stim_running_statuses)

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
            self._stim_subprotocol_managers = [
                StimulationProtocolManager(protocol["subprotocols"])
                for protocol in self._stim_info["protocols"]
            ]
            self._stim_running_statuses = [True] * len(self._stim_info["protocols"])
        else:
            self._timepoints_of_subprotocols_start = list()
            self._stim_time_indices = list()
            self._stim_subprotocol_managers = list()
            for protocol_idx in range(len(self._stim_info["protocols"])):
                self._stim_running_statuses[protocol_idx] = False

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
        absolute_path = os.path.normcase(
            os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir, os.pardir)
        )
        file_path = resource_path(relative_path, base_path=absolute_path)
        with open(file_path, newline="") as csvfile:
            simulated_data_timepoints = next(csv.reader(csvfile, delimiter=","))
            simulated_data_values = next(csv.reader(csvfile, delimiter=","))
        self._interpolator = interpolate.interp1d(
            np.array(simulated_data_timepoints, dtype=np.uint64), simulated_data_values
        )

    def _handle_boot_up_config(self, reboot: bool = False) -> None:
        self._time_of_last_handshake_secs = None
        self._time_of_last_comm_from_pc_secs = None
        self._reset_start_time()
        self._reboot_time_secs = None
        self._status_codes = [SERIAL_COMM_OKAY_CODE] * (self._num_wells + 2)
        self._sampling_period_us = DEFAULT_SAMPLING_PERIOD
        self._adc_readings = [(self.default_adc_reading, self.default_adc_reading)] * self._num_wells
        self._stim_info = {}
        self._is_stimulating = False
        self._firmware_update_idx = None
        self._firmware_update_bytes = None
        if reboot:
            if self._firmware_update_type is not None:
                packet_type = (
                    SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE
                    if self._firmware_update_type
                    else SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE
                )
                self._send_data_packet(
                    packet_type, bytes([0, 0, 0])  # TODO make this the new firmware version
                )
            elif self._new_nickname is not None:
                self._send_data_packet(
                    SERIAL_COMM_SET_NICKNAME_PACKET_TYPE,
                    # TODO should send timestamp here
                )
                self._metadata_dict[MANTARRAY_NICKNAME_UUID] = self._new_nickname
                self._new_nickname = None
            # only set boot up time automatically after a reboot
            self._boot_up_time_secs = perf_counter()
            # after reboot, if not rebooting again, send status beacon to signal that reboot has completed
            if not self._reboot_again:
                self._send_status_beacon(truncate=False)
        self._firmware_update_type = None

    def _reset_metadata_dict(self) -> None:
        self._metadata_dict = dict(self.default_metadata_values)

    def get_interpolated_data(self, sampling_period_us: int) -> NDArray[np.uint16]:
        """Return one second (one twitch) of interpolated data."""
        data_indices = np.arange(0, MICRO_TO_BASE_CONVERSION, sampling_period_us)
        return self._interpolator(data_indices).astype(np.uint16)

    def is_rebooting(self) -> bool:
        return self._reboot_time_secs is not None

    def _get_absolute_timer(self) -> int:
        absolute_time: int = self.get_cms_since_init() * MICROSECONDS_PER_CENTIMILLISECOND
        return absolute_time

    def _get_global_timer(self) -> int:
        return self._get_absolute_timer() + int(self.global_timer_offset_secs * MICRO_TO_BASE_CONVERSION)

    def _get_timestamp(self) -> int:
        return self._get_absolute_timer()

    def _send_data_packet(
        self, packet_type: int, data_to_send: bytes = bytes(0), truncate: bool = False
    ) -> None:
        timestamp = self._get_timestamp()
        data_packet = create_data_packet(timestamp, packet_type, data_to_send)
        if truncate:
            trunc_index = random.randint(  # nosec B311 # Tanner (2/4/21): Bandit blacklisted this pseudo-random generator for cryptographic security reasons that do not apply to the desktop app.
                0, len(data_packet) - 1
            )
            data_packet = data_packet[trunc_index:]
        self._output_queue.put_nowait(data_packet)

    def _commands_for_each_run_iteration(self) -> None:
        """Ordered actions to perform each iteration.

        1. Handle any test communication. This must be done first since test comm may cause the simulator to enter a certain state or send a data packet. Test communication should also be processed regardless of the internal state of the simulator.
        2. Check if rebooting. The simulator should not be responsive to any commands from the PC while it is rebooting.
        3. Handle communication from the PC.
        4. Send a status beacon if enough time has passed since the previous one was sent.
        5. If streaming is on, check to see how many data packets are ready to be sent and send them if necessary.
        6. If stimulating, send any stimulation data packets that need to be sent.
        7. Check if the handshake from the PC is overdue. This should be done after checking for data sent from the PC since the next packet might be a handshake.
        8. Check if the barcode is ready to send. This is currently the lowest priority.
        """
        self._handle_test_comm()

        if self.is_rebooting():  # Tanner (1/24/22): currently checks if self._reboot_time_secs is not None
            secs_since_reboot = _get_secs_since_reboot_command(self._reboot_time_secs)  # type: ignore
            # if secs_since_reboot is less than the reboot duration, simulator is still in the 'reboot' phase. Commands from PC will be ignored and status beacons will not be sent
            if (
                secs_since_reboot < AVERAGE_MC_REBOOT_DURATION_SECONDS
            ):  # Tanner (3/31/21): rebooting should be much faster than the maximum allowed time for rebooting, so arbitrarily picking a simulated reboot duration
                return
            self._handle_boot_up_config(reboot=True)
            if self._reboot_again:
                self._reboot_time_secs = perf_counter()
            self._reboot_again = False
        self._handle_comm_from_pc()
        self._handle_status_beacon()
        if self._is_streaming_data:
            self._handle_magnetometer_data_packet()
        if self._is_stimulating:
            self._handle_stimulation_packets()
        self._check_handshake()
        self._handle_barcodes()

    def _handle_comm_from_pc(self) -> None:
        try:
            comm_from_pc = self._input_queue.get_nowait()
        except queue.Empty:
            self._check_handshake_timeout()
            return
        self._time_of_last_comm_from_pc_secs = perf_counter()

        # validate checksum before handling the communication
        checksum_is_valid = validate_checksum(comm_from_pc)
        if not checksum_is_valid:
            # remove magic word before returning message to PC
            trimmed_comm_from_pc = comm_from_pc[MAGIC_WORD_LEN:]
            self._send_data_packet(SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE, trimmed_comm_from_pc)
            return
        self._process_main_module_command(comm_from_pc)

    def _check_handshake_timeout(self) -> None:
        if self._time_of_last_comm_from_pc_secs is None:
            return
        secs_since_last_comm_from_pc = _get_secs_since_last_comm_from_pc(self._time_of_last_comm_from_pc_secs)
        if secs_since_last_comm_from_pc >= SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS:
            self._time_of_last_comm_from_pc_secs = None
            # Tanner (3/23/22): real board will also stop stimulation and magnetometer data streaming here, but adding this to the simulator is not entirely necessary as there is no risk to leaving these processes on
            self._send_data_packet(
                SERIAL_COMM_GOING_DORMANT_PACKET_TYPE, bytes([GOING_DORMANT_HANDSHAKE_TIMEOUT_CODE])
            )

    def _process_main_module_command(self, comm_from_pc: bytes) -> None:
        # Tanner (11/15/21): many branches needed here to handle all types of communication. Could try refactoring int smaller methods for similar packet types
        send_response = True

        response_body = bytes(0)

        packet_type = comm_from_pc[SERIAL_COMM_PACKET_TYPE_INDEX]
        if packet_type == SERIAL_COMM_REBOOT_PACKET_TYPE:
            self._reboot_time_secs = perf_counter()
        elif packet_type == SERIAL_COMM_HANDSHAKE_PACKET_TYPE:
            self._time_of_last_handshake_secs = perf_counter()
            response_body += bytes(self._status_codes)
        elif packet_type == SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE:
            # command fails if > 24 unique protocols given, the length of the array of protocol IDs != 24, or if > 50 subprotocols are in a single protocol
            stim_info_dict = convert_stim_bytes_to_dict(
                comm_from_pc[SERIAL_COMM_PAYLOAD_INDEX:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES]
            )
            # TODO handle too many subprotocols?
            command_failed = self._is_stimulating or len(stim_info_dict["protocols"]) > self._num_wells
            if not command_failed:
                self._stim_info = stim_info_dict
            response_body += bytes([command_failed])
        elif packet_type == SERIAL_COMM_START_STIM_PACKET_TYPE:
            # command fails if protocols are not set or if stimulation is already running
            command_failed = "protocol_assignments" not in self._stim_info or self._is_stimulating
            response_body += bytes([command_failed])
            if not command_failed:
                self._is_stimulating = True
        elif packet_type == SERIAL_COMM_STOP_STIM_PACKET_TYPE:
            # command fails only if stimulation is not currently running
            command_failed = not self._is_stimulating
            response_body += bytes([command_failed])
            if not command_failed:
                self._handle_manual_stim_stop()
                self._is_stimulating = False
        elif packet_type == SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE:
            # Tanner (4/8/22): currently assuming that stim checks will take a negligible amount of time
            for module_readings in self._adc_readings:
                status = convert_adc_readings_to_circuit_status(*module_readings)
                response_body += struct.pack("<HHB", *module_readings, status) * 2
        elif packet_type == SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE:
            response_body += self._update_sampling_period(comm_from_pc)
        elif packet_type == SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE:
            is_data_already_streaming = self._is_streaming_data
            response_body += bytes([is_data_already_streaming])
            self._is_streaming_data = True
            if not is_data_already_streaming:
                response_body += self._time_index_us.to_bytes(8, byteorder="little")
        elif packet_type == SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE:
            response_body += bytes([not self._is_streaming_data])
            if self._is_streaming_data and self._is_first_data_stream:
                self._is_first_data_stream = False
                if self._time_of_last_barcode_send_secs is None:  # pragma: no cover
                    self._time_of_last_barcode_send_secs = 0
            self._is_streaming_data = False
        elif packet_type == SERIAL_COMM_GET_METADATA_PACKET_TYPE:
            response_body += convert_metadata_to_bytes(self._metadata_dict)
        elif packet_type == SERIAL_COMM_SET_NICKNAME_PACKET_TYPE:
            send_response = False
            start_idx = SERIAL_COMM_PAYLOAD_INDEX
            nickname_bytes = comm_from_pc[start_idx : start_idx + SERIAL_COMM_NICKNAME_BYTES_LENGTH]
            self._new_nickname = nickname_bytes.decode("utf-8")
            self._reboot_time_secs = perf_counter()
            self._reboot_again = True
        elif packet_type == SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE:
            firmware_type = comm_from_pc[SERIAL_COMM_PAYLOAD_INDEX]
            command_failed = firmware_type not in (0, 1) or self._firmware_update_type is not None
            # TODO store new FW version and number of bytes in FW
            self._firmware_update_idx = 0
            self._firmware_update_type = firmware_type
            self._firmware_update_bytes = bytes(0)
            response_body += bytes([command_failed])
        elif packet_type == SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE:
            if self._firmware_update_bytes is None:
                # Tanner (11/10/21): currently unsure how real board would handle receiving this packet before the previous two firmware packet types
                raise NotImplementedError("_firmware_update_bytes should never be None here")
            if self._firmware_update_idx is None:
                # Tanner (11/10/21): currently unsure how real board would handle receiving this packet before the previous two firmware packet types
                raise NotImplementedError("_firmware_update_idx should never be None here")
            packet_idx = comm_from_pc[SERIAL_COMM_PAYLOAD_INDEX]
            new_firmware_bytes = comm_from_pc[
                SERIAL_COMM_PAYLOAD_INDEX + 1 : -SERIAL_COMM_CHECKSUM_LENGTH_BYTES
            ]
            command_failed = (
                len(new_firmware_bytes) > SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES - 1
                or packet_idx != self._firmware_update_idx
            )
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
            received_checksum = int.from_bytes(
                comm_from_pc[SERIAL_COMM_PAYLOAD_INDEX : SERIAL_COMM_PAYLOAD_INDEX + 4], byteorder="little"
            )
            calculated_checksum = crc32(self._firmware_update_bytes)
            checksum_failure = received_checksum != calculated_checksum
            response_body += bytes([checksum_failure])
            if not checksum_failure:
                self._reboot_time_secs = perf_counter()
                self._reboot_again = True
        elif packet_type == SERIAL_COMM_GET_ERROR_DETAILS_PACKET_TYPE:  # pragma: no cover
            response_body += convert_instrument_event_info_to_bytes(self.default_event_info)
        elif packet_type == SERIAL_COMM_ERROR_ACK_PACKET_TYPE:  # pragma: no cover
            # Tanner (3/24/22): As of right now, simulator does not need to handle this message at all, so it is the responsibility of tests to prompt simulator to go through the rest of the error handling procedure
            pass
        else:
            raise UnrecognizedSerialCommPacketTypeError(f"Packet Type ID: {packet_type} is not defined")
        if send_response:
            self._send_data_packet(packet_type, response_body)

    def _update_sampling_period(self, comm_from_pc: bytes) -> bytes:
        update_status_byte = bytes([self._is_streaming_data])
        if self._is_streaming_data:
            # cannot change configuration while data is streaming, so return here
            return update_status_byte
        # check and set sampling period
        sampling_period = int.from_bytes(
            comm_from_pc[SERIAL_COMM_PAYLOAD_INDEX : SERIAL_COMM_PAYLOAD_INDEX + 2], byteorder="little"
        )
        if sampling_period % MICROS_PER_MILLI != 0:
            raise SerialCommInvalidSamplingPeriodError(sampling_period)
        self._sampling_period_us = sampling_period
        return update_status_byte

    def _handle_status_beacon(self) -> None:
        if self._time_of_last_status_beacon_secs is None:
            self._send_status_beacon(truncate=True)
            return
        seconds_elapsed = _get_secs_since_last_status_beacon(self._time_of_last_status_beacon_secs)
        if seconds_elapsed >= SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS:
            self._send_status_beacon(truncate=False)

    def _send_status_beacon(self, truncate: bool = False) -> None:
        self._time_of_last_status_beacon_secs = perf_counter()
        self._send_data_packet(SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, bytes(self._status_codes), truncate)

    def _check_handshake(self) -> None:
        if self._time_of_last_handshake_secs is None:
            return
        time_of_last_handshake_secs = _get_secs_since_last_handshake(self._time_of_last_handshake_secs)
        if (
            time_of_last_handshake_secs
            >= SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS * SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
        ):
            raise SerialCommTooManyMissedHandshakesError()

    def _handle_barcodes(self) -> None:
        if self._time_of_last_barcode_send_secs is None:
            return
        if (
            _get_secs_since_last_barcode_scan(self._time_of_last_barcode_send_secs)
            >= SIMULATOR_BARCODE_SEND_PERIOD_SECS
        ):
            self._send_barcodes()

    def _send_barcodes(self) -> None:
        self._time_of_last_barcode_send_secs = perf_counter()
        self._send_data_packet(
            SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE, bytes(self.default_plate_barcode, encoding="ascii")
        )
        self._send_data_packet(
            SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE, bytes(self.default_stim_barcode, encoding="ascii")
        )

    def _handle_manual_stim_stop(self) -> None:
        num_status_updates = 0
        status_update_bytes = bytes(0)
        stop_time_index = self._get_global_timer()
        for protocol_idx, is_stim_running in enumerate(self._stim_running_statuses):
            if not is_stim_running:
                continue

            num_status_updates += 1
            status_update_bytes += (
                bytes([protocol_idx])
                + stop_time_index.to_bytes(8, byteorder="little")
                + bytes([StimProtocolStatuses.FINISHED])
                + bytes([STIM_COMPLETE_SUBPROTOCOL_IDX])
            )
        self._send_data_packet(
            SERIAL_COMM_STIM_STATUS_PACKET_TYPE, bytes([num_status_updates]) + status_update_bytes
        )

    def _handle_test_comm(self) -> None:
        try:
            test_comm = self._testing_queue.get_nowait()
        except queue.Empty:
            return

        command = test_comm["command"]
        if command == "raise_error":
            raise test_comm["error"]
        if command == "send_single_beacon":
            self._send_data_packet(SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, bytes(self._status_codes))
        elif command == "add_read_bytes":
            read_bytes = test_comm["read_bytes"]
            if not isinstance(read_bytes, list):
                read_bytes = [read_bytes]
            for read in read_bytes:
                self._output_queue.put_nowait(read)
        elif command == "set_status_code":
            status_codes = test_comm["status_codes"]
            self._status_codes = status_codes
        elif command == "set_data_streaming_status":
            self._sampling_period_us = test_comm.get("sampling_period", DEFAULT_SAMPLING_PERIOD)
            self._is_streaming_data = test_comm["data_streaming_status"]
            self._simulated_data_index = test_comm.get("simulated_data_index", 0)
        elif command == "set_sampling_period":
            self._sampling_period_us = test_comm["sampling_period"]
        elif command == "set_adc_readings":
            for well_idx, adc_readings in enumerate(test_comm["adc_readings"]):
                module_id = STIM_WELL_IDX_TO_MODULE_ID[well_idx]
                self._adc_readings[module_id] = adc_readings
        elif command == "set_stim_info":
            self._stim_info = test_comm["stim_info"]
        elif command == "set_stim_status":
            self._is_stimulating = test_comm["status"]
        elif command == "set_firmware_update_type":
            self._firmware_update_type = test_comm["firmware_type"]
        else:
            raise UnrecognizedSimulatorTestCommandError(command)

    def _handle_magnetometer_data_packet(self) -> None:
        """Send the required number of data packets.

        Since this process iterates once per 10 ms, it is possible that
        more than one data packet must be sent.
        """
        if self._timepoint_of_last_data_packet_us is None:  # making mypy happy
            raise NotImplementedError("_timepoint_of_last_data_packet_us should never be None here")
        us_since_last_data_packet = _get_us_since_last_data_packet(self._timepoint_of_last_data_packet_us)
        num_packets_to_send = us_since_last_data_packet // self._sampling_period_us
        if num_packets_to_send < 1:
            return
        simulated_data_len = len(self._simulated_data)

        data_packet_bytes = bytes(0)
        for _ in range(num_packets_to_send):
            # not using _send_data_packet here because it is more efficient to send all packets at once
            data_packet_bytes += create_data_packet(
                self._get_timestamp(),
                SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
                self._create_magnetometer_data_payload(),
            )
            # increment values
            self._time_index_us += self._sampling_period_us
            self._simulated_data_index = (self._simulated_data_index + 1) % simulated_data_len
        self._output_queue.put_nowait(data_packet_bytes)
        # update timepoint
        self._timepoint_of_last_data_packet_us += num_packets_to_send * self._sampling_period_us

    def _create_magnetometer_data_payload(self) -> bytes:
        # add time index to data packet body
        magnetometer_data_payload = self._time_index_us.to_bytes(
            SERIAL_COMM_TIME_INDEX_LENGTH_BYTES, byteorder="little"
        )
        for module_id in range(self._num_wells):
            # add offset of 0 since this is simulated data
            time_offset = bytes(SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES)
            # create data point value
            data_value = self._simulated_data[self._simulated_data_index] * np.uint16(
                SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id] + 1
            )
            # add data points
            well_sensor_data = time_offset + (data_value.tobytes() * SERIAL_COMM_NUM_CHANNELS_PER_SENSOR)
            well_data = well_sensor_data * SERIAL_COMM_NUM_SENSORS_PER_WELL
            magnetometer_data_payload += well_data
        return magnetometer_data_payload

    def _handle_stimulation_packets(self) -> None:
        num_status_updates = 0
        packet_bytes = bytes(0)

        for protocol_idx, protocol in enumerate(self._stim_info["protocols"]):
            start_timepoint = self._timepoints_of_subprotocols_start[protocol_idx]
            if start_timepoint is None:
                continue

            subprotocol_manager = self._stim_subprotocol_managers[protocol_idx]

            if subprotocol_manager.idx() == -1:
                curr_subprotocol_duration_us = 0
            else:
                curr_subprotocol_duration_us = get_subprotocol_dur_us(subprotocol_manager.current())

            dur_since_subprotocol_start = _get_us_since_subprotocol_start(start_timepoint)
            while dur_since_subprotocol_start >= curr_subprotocol_duration_us:
                # update time index for subprotocol
                self._stim_time_indices[protocol_idx] += curr_subprotocol_duration_us
                # need to check if the protocol is complete before advancing to the next protocol
                protocol_complete = subprotocol_manager.complete()
                # move on to next subprotocol in this protocol
                curr_subprotocol = subprotocol_manager.advance()

                packet_bytes += bytes([protocol_idx])
                num_status_updates += 1  # increment for all statuses

                packet_bytes += self._stim_time_indices[protocol_idx].to_bytes(8, byteorder="little")

                if not protocol["run_until_stopped"] and protocol_complete:
                    # protocol stopping
                    packet_bytes += bytes([StimProtocolStatuses.FINISHED, STIM_COMPLETE_SUBPROTOCOL_IDX])
                    self._stim_running_statuses[protocol_idx] = False
                    self._timepoints_of_subprotocols_start[protocol_idx] = None
                    break
                else:
                    stim_status = (
                        StimProtocolStatuses.NULL
                        if is_null_subprotocol(curr_subprotocol)
                        else StimProtocolStatuses.ACTIVE
                    )
                    packet_bytes += bytes([stim_status, subprotocol_manager.idx()])

                    # update timepoints and durations for next iteration
                    self._timepoints_of_subprotocols_start[protocol_idx] += curr_subprotocol_duration_us  # type: ignore
                    dur_since_subprotocol_start -= curr_subprotocol_duration_us
                    curr_subprotocol_duration_us = get_subprotocol_dur_us(curr_subprotocol)

        if num_status_updates > 0:
            packet_bytes = bytes([num_status_updates]) + packet_bytes
            self._send_data_packet(SERIAL_COMM_STIM_STATUS_PACKET_TYPE, packet_bytes)

        # if all timepoints are None, stimulation has ended
        self._is_stimulating = any(self._timepoints_of_subprotocols_start)

    def _continue_reading(self, read_bytes: bytes, read_size: Optional[int], read_dur_secs: float) -> bool:
        continue_reading = True
        if read_size:
            continue_reading &= len(read_bytes) < read_size
        if self._read_timeout_seconds:
            continue_reading &= read_dur_secs < self._read_timeout_seconds
        return continue_reading

    def _read(self, size: Optional[int] = None) -> bytes:
        if size is not None and size < 0:  # pragma: no cover
            raise ValueError("size must be >= 0")

        # first check leftover bytes from last read
        read_bytes = bytes(0)
        if self._leftover_read_bytes:
            read_bytes = self._leftover_read_bytes
            self._leftover_read_bytes = bytes(0)

        # try to get bytes until either timeout occurs or given size is reached or exceeded
        start = perf_counter()
        read_dur_secs = 0.0
        while self._continue_reading(read_bytes, size, read_dur_secs):
            read_dur_secs = _get_secs_since_read_start(start)
            try:
                next_bytes = self._output_queue.get_nowait()
            except queue.Empty:
                if not self._read_timeout_seconds:
                    break
            else:
                read_bytes += next_bytes

        return read_bytes

    def read(self, size: int = 1) -> bytes:
        """Read the given number of bytes from the simulator."""
        read_bytes = self._read(size)

        # if this read exceeds given size then store extra bytes for the next read
        if len(read_bytes) > size:
            size_diff = len(read_bytes) - size
            self._leftover_read_bytes = read_bytes[-size_diff:]
            read_bytes = read_bytes[:-size_diff]
        return read_bytes

    def read_all(self) -> bytes:
        """Read all available bytes from the simulator."""
        return self._read()

    def write(self, input_item: bytes) -> int:
        self._input_queue.put_nowait(input_item)
        return len(input_item)

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items = {
            "input_queue": drain_queue(self._input_queue),
            "output_queue": drain_queue(self._output_queue),
            "testing_queue": drain_queue(self._testing_queue),
        }
        return queue_items
