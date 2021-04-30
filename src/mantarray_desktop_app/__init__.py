# -*- coding: utf-8 -*-
"""Docstring."""

from . import fifo_read_producer
from . import fifo_simulator
from . import file_writer
from . import firmware_manager
from . import main
from . import mc_comm
from . import mc_simulator
from . import ok_comm
from . import process_manager
from . import process_monitor
from . import server
from . import utils
from .constants import ADC_CH_TO_24_WELL_INDEX
from .constants import ADC_CH_TO_IS_REF_SENSOR
from .constants import ADC_GAIN
from .constants import ADC_GAIN_DESCRIPTION_TAG
from .constants import ADC_OFFSET_DESCRIPTION_TAG
from .constants import BARCODE_CONFIRM_CLEAR_WAIT_SECONDS
from .constants import BARCODE_GET_SCAN_WAIT_SECONDS
from .constants import BARCODE_INVALID_UUID
from .constants import BARCODE_POLL_PERIOD
from .constants import BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS
from .constants import BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS
from .constants import BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS
from .constants import BARCODE_SCANNER_TRIGGER_IN_ADDRESS
from .constants import BARCODE_UNREADABLE_UUID
from .constants import BARCODE_VALID_UUID
from .constants import BUFFERING_STATE
from .constants import CALIBRATED_STATE
from .constants import CALIBRATING_STATE
from .constants import CALIBRATION_NEEDED_STATE
from .constants import CHANNEL_INDEX_TO_24_WELL_INDEX
from .constants import CLEAR_BARCODE_TRIG_BIT
from .constants import CLEARED_BARCODE_VALUE
from .constants import COMPILED_EXE_BUILD_TIMESTAMP
from .constants import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from .constants import CONSTRUCT_SENSORS_PER_REF_SENSOR
from .constants import CURI_BIO_ACCOUNT_UUID
from .constants import CURI_BIO_USER_ACCOUNT_ID
from .constants import CURRENT_HDF5_FILE_FORMAT_VERSION
from .constants import CURRENT_SOFTWARE_VERSION
from .constants import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from .constants import DATA_FRAME_PERIOD
from .constants import DEFAULT_SERVER_PORT_NUMBER
from .constants import DEFAULT_USER_CONFIG
from .constants import FIFO_READ_PRODUCER_CYCLES_PER_ITERATION
from .constants import FIFO_READ_PRODUCER_DATA_OFFSET
from .constants import FIFO_READ_PRODUCER_REF_AMPLITUDE
from .constants import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from .constants import FIFO_READ_PRODUCER_SLEEP_DURATION
from .constants import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from .constants import FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
from .constants import FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS
from .constants import FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
from .constants import FIRMWARE_VERSION_WIRE_OUT_ADDRESS
from .constants import INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
from .constants import INSTRUMENT_INITIALIZING_STATE
from .constants import LIVE_VIEW_ACTIVE_STATE
from .constants import MAX_MC_REBOOT_DURATION_SECONDS
from .constants import MAX_POSSIBLE_CONNECTED_BOARDS
from .constants import MICROSECONDS_PER_CENTIMILLISECOND
from .constants import MICROSECONDS_PER_MILLISECOND
from .constants import MIDSCALE_CODE
from .constants import MILLIVOLTS_PER_VOLT
from .constants import NANOSECONDS_PER_CENTIMILLISECOND
from .constants import NO_PLATE_DETECTED_BARCODE_VALUE
from .constants import NO_PLATE_DETECTED_UUID
from .constants import OUTGOING_DATA_BUFFER_SIZE
from .constants import RAW_TO_SIGNED_CONVERSION_VALUE
from .constants import RECORDING_STATE
from .constants import REF_INDEX_TO_24_WELL_INDEX
from .constants import REFERENCE_SENSOR_SAMPLING_PERIOD
from .constants import REFERENCE_VOLTAGE
from .constants import ROUND_ROBIN_PERIOD
from .constants import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from .constants import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from .constants import SERIAL_COMM_BAUD_RATE
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
from .constants import SERIAL_COMM_MAIN_MODULE_ID
from .constants import SERIAL_COMM_MAX_DATA_LENGTH_BYTES
from .constants import SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
from .constants import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from .constants import SERIAL_COMM_METADATA_BYTES_LENGTH
from .constants import SERIAL_COMM_MIN_PACKET_SIZE_BYTES
from .constants import SERIAL_COMM_MODULE_ID_INDEX
from .constants import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from .constants import SERIAL_COMM_NUM_DATA_CHANNELS
from .constants import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from .constants import SERIAL_COMM_PACKET_TYPE_INDEX
from .constants import SERIAL_COMM_PLATE_EVENT_PACKET_TYPE
from .constants import SERIAL_COMM_REBOOT_COMMAND_BYTE
from .constants import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from .constants import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from .constants import SERIAL_COMM_SET_TIME_COMMAND_BYTE
from .constants import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from .constants import SERIAL_COMM_SOFT_ERROR_CODE
from .constants import SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from .constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from .constants import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from .constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from .constants import SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE
from .constants import SERIAL_COMM_STREAM_MODE_CHANGED_BYTE
from .constants import SERIAL_COMM_STREAM_MODE_UNCHANGED_BYTE
from .constants import SERIAL_COMM_TIME_SYNC_READY_CODE
from .constants import SERIAL_COMM_TIMESTAMP_BYTES_INDEX
from .constants import SERIAL_COMM_TIMESTAMP_EPOCH
from .constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from .constants import SERVER_INITIALIZING_STATE
from .constants import SERVER_READY_STATE
from .constants import START_BARCODE_SCAN_TRIG_BIT
from .constants import START_MANAGED_ACQUISITION_COMMUNICATION
from .constants import STOP_MANAGED_ACQUISITION_COMMUNICATION
from .constants import SUBPROCESS_POLL_DELAY_SECONDS
from .constants import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from .constants import SYSTEM_STATUS_UUIDS
from .constants import TIMESTEP_CONVERSION_FACTOR
from .constants import VALID_CONFIG_SETTINGS
from .constants import VALID_SCRIPTING_COMMANDS
from .constants import WELL_24_INDEX_TO_ADC_AND_CH_INDEX
from .data_analyzer import convert_24_bit_codes_to_voltage
from .data_analyzer import DataAnalyzerProcess
from .exceptions import AttemptToAddCyclesWhileSPIRunningError
from .exceptions import AttemptToInitializeFIFOReadsError
from .exceptions import BarcodeNotClearedError
from .exceptions import BarcodeScannerNotRespondingError
from .exceptions import FirmwareFileNameDoesNotMatchWireOutVersionError
from .exceptions import FirstManagedReadLessThanOneRoundRobinError
from .exceptions import ImproperlyFormattedCustomerAccountUUIDError
from .exceptions import ImproperlyFormattedUserAccountUUIDError
from .exceptions import InstrumentCommIncorrectHeaderError
from .exceptions import InstrumentDataStreamingAlreadyStartedError
from .exceptions import InstrumentDataStreamingAlreadyStoppedError
from .exceptions import InstrumentFatalError
from .exceptions import InstrumentRebootTimeoutError
from .exceptions import InstrumentSoftError
from .exceptions import InvalidBeta2FlagOptionError
from .exceptions import InvalidDataFramePeriodError
from .exceptions import InvalidDataTypeFromOkCommError
from .exceptions import InvalidScriptCommandError
from .exceptions import LocalServerPortAlreadyInUseError
from .exceptions import MantarrayInstrumentError
from .exceptions import MismatchedScriptTypeError
from .exceptions import MultiprocessingNotSetToSpawnError
from .exceptions import RecordingFolderDoesNotExistError
from .exceptions import ScriptDoesNotContainEndCommandError
from .exceptions import SerialCommCommandResponseTimeoutError
from .exceptions import SerialCommHandshakeTimeoutError
from .exceptions import SerialCommIncorrectChecksumFromInstrumentError
from .exceptions import SerialCommIncorrectChecksumFromPCError
from .exceptions import SerialCommIncorrectMagicWordFromMantarrayError
from .exceptions import SerialCommInvalidSamplingPeriodError
from .exceptions import SerialCommMetadataValueTooLargeError
from .exceptions import SerialCommPacketFromMantarrayTooSmallError
from .exceptions import SerialCommPacketRegistrationReadEmptyError
from .exceptions import SerialCommPacketRegistrationSearchExhaustedError
from .exceptions import SerialCommPacketRegistrationTimoutError
from .exceptions import SerialCommStatusBeaconTimeoutError
from .exceptions import SerialCommTooManyMissedHandshakesError
from .exceptions import SerialCommUntrackedCommandResponseError
from .exceptions import ServerThreadNotInitializedError
from .exceptions import ServerThreadSingletonAlreadySetError
from .exceptions import SystemStartUpError
from .exceptions import UnrecognizedCommandFromMainToFileWriterError
from .exceptions import UnrecognizedCommandFromMainToMcCommError
from .exceptions import UnrecognizedCommandToInstrumentError
from .exceptions import UnrecognizedCommTypeFromMainToDataAnalyzerError
from .exceptions import UnrecognizedCommTypeFromMainToInstrumentError
from .exceptions import UnrecognizedDataFrameFormatNameError
from .exceptions import UnrecognizedDebugConsoleCommandError
from .exceptions import UnrecognizedMantarrayNamingCommandError
from .exceptions import UnrecognizedRecordingCommandError
from .exceptions import UnrecognizedSerialCommModuleIdError
from .exceptions import UnrecognizedSerialCommPacketTypeError
from .exceptions import UnrecognizedSimulatorTestCommandError
from .fifo_read_producer import FIFOReadProducer
from .fifo_read_producer import produce_data
from .fifo_simulator import RunningFIFOSimulator
from .file_writer import FileWriterProcess
from .file_writer import get_data_slice_within_timepoints
from .file_writer import get_reference_dataset_from_file
from .file_writer import get_tissue_dataset_from_file
from .file_writer import MantarrayH5FileCreator
from .firmware_manager import get_latest_firmware
from .firmware_manager import get_latest_firmware_name
from .firmware_manager import get_latest_firmware_version
from .firmware_manager import sort_firmware_files
from .instrument_comm import InstrumentCommProcess
from .main import clear_server_singletons
from .main import get_server_port_number
from .mantarray_front_panel import MantarrayFrontPanel
from .mantarray_front_panel import MantarrayFrontPanelMixIn
from .mc_comm import McCommunicationProcess
from .mc_simulator import MantarrayMcSimulator
from .ok_comm import build_file_writer_objects
from .ok_comm import check_mantarray_serial_number
from .ok_comm import execute_debug_console_command
from .ok_comm import OkCommunicationProcess
from .ok_comm import parse_data_frame
from .ok_comm import parse_gain
from .ok_comm import parse_scripting_log
from .ok_comm import parse_scripting_log_line
from .process_manager import MantarrayProcessesManager
from .process_monitor import MantarrayProcessesMonitor
from .queue_container import MantarrayQueueContainer
from .serial_comm_utils import convert_bitmask_to_config_dict
from .serial_comm_utils import convert_metadata_bytes_to_str
from .serial_comm_utils import convert_to_metadata_bytes
from .serial_comm_utils import convert_to_status_code_bytes
from .serial_comm_utils import convert_to_timestamp_bytes
from .serial_comm_utils import create_data_packet
from .serial_comm_utils import create_magnetometer_config_bytes
from .serial_comm_utils import create_sensor_axis_bitmask
from .serial_comm_utils import get_serial_comm_timestamp
from .serial_comm_utils import parse_metadata_bytes
from .serial_comm_utils import validate_checksum
from .server import clear_the_server_thread
from .server import flask_app
from .server import get_api_endpoint
from .server import get_the_server_thread
from .server import ServerThread
from .system_utils import system_state_eventually_equals
from .system_utils import wait_for_subprocesses_to_start
from .utils import check_barcode_for_errors
from .utils import create_magnetometer_config_dict
from .utils import get_current_software_version
from .utils import redact_sensitive_info_from_path

if (
    6 < 9
):  # pragma: no cover # protect this from zimports deleting the pylint disable statement
    from .data_parsing_cy import (  # pylint: disable=import-error # Tanner (8/25/20) unsure why pylint is unable to recognize cython import...
        parse_adc_metadata_byte,
        parse_little_endian_int24,
        parse_sensor_bytes,
    )

__all__ = [
    "main",
    "utils",
    "flask_app",
    "MultiprocessingNotSetToSpawnError",
    "LocalServerPortAlreadyInUseError",
    "UnrecognizedDebugConsoleCommandError",
    "UnrecognizedCommandFromMainToFileWriterError",
    "UnrecognizedDataFrameFormatNameError",
    "get_server_port_number",
    "process_manager",
    "MantarrayProcessesManager",
    "MantarrayProcessesMonitor",
    "get_api_endpoint",
    "MAX_POSSIBLE_CONNECTED_BOARDS",
    "ok_comm",
    "process_monitor",
    "file_writer",
    "MantarrayH5FileCreator",
    "get_tissue_dataset_from_file",
    "get_reference_dataset_from_file",
    "get_data_slice_within_timepoints",
    "execute_debug_console_command",
    "OkCommunicationProcess",
    "parse_data_frame",
    "parse_little_endian_int24",
    "parse_sensor_bytes",
    "CHANNEL_INDEX_TO_24_WELL_INDEX",
    "COMPILED_EXE_BUILD_TIMESTAMP",
    "REF_INDEX_TO_24_WELL_INDEX",
    "ADC_CH_TO_24_WELL_INDEX",
    "DATA_FRAME_PERIOD",
    "CONSTRUCT_SENSOR_SAMPLING_PERIOD",
    "REFERENCE_SENSOR_SAMPLING_PERIOD",
    "CURRENT_HDF5_FILE_FORMAT_VERSION",
    "CURRENT_SOFTWARE_VERSION",
    "START_MANAGED_ACQUISITION_COMMUNICATION",
    "STOP_MANAGED_ACQUISITION_COMMUNICATION",
    "parse_adc_metadata_byte",
    "MIDSCALE_CODE",
    "REFERENCE_VOLTAGE",
    "MILLIVOLTS_PER_VOLT",
    "convert_24_bit_codes_to_voltage",
    "FileWriterProcess",
    "InvalidDataTypeFromOkCommError",
    "build_file_writer_objects",
    "UnrecognizedCommTypeFromMainToInstrumentError",
    "fifo_simulator",
    "RunningFIFOSimulator",
    "AttemptToInitializeFIFOReadsError",
    "fifo_read_producer",
    "FIFOReadProducer",
    "FIFO_READ_PRODUCER_SLEEP_DURATION",
    "FIFO_READ_PRODUCER_CYCLES_PER_ITERATION",
    "ADC_GAIN",
    "FIFO_READ_PRODUCER_SAWTOOTH_PERIOD",
    "ROUND_ROBIN_PERIOD",
    "AttemptToAddCyclesWhileSPIRunningError",
    "produce_data",
    "TIMESTEP_CONVERSION_FACTOR",
    "FirstManagedReadLessThanOneRoundRobinError",
    "parse_scripting_log_line",
    "parse_scripting_log",
    "MismatchedScriptTypeError",
    "InvalidScriptCommandError",
    "VALID_SCRIPTING_COMMANDS",
    "DataAnalyzerProcess",
    "CONSTRUCT_SENSORS_PER_REF_SENSOR",
    "DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS",
    "FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE",
    "RAW_TO_SIGNED_CONVERSION_VALUE",
    "INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES",
    "SYSTEM_STATUS_UUIDS",
    "DEFAULT_USER_CONFIG",
    "firmware_manager",
    "sort_firmware_files",
    "get_latest_firmware",
    "get_latest_firmware_version",
    "redact_sensitive_info_from_path",
    "ADC_GAIN_DESCRIPTION_TAG",
    "parse_gain",
    "system_state_eventually_equals",
    "wait_for_subprocesses_to_start",
    "SystemStartUpError",
    "SERVER_INITIALIZING_STATE",
    "CALIBRATION_NEEDED_STATE",
    "CALIBRATING_STATE",
    "CALIBRATED_STATE",
    "BUFFERING_STATE",
    "LIVE_VIEW_ACTIVE_STATE",
    "RECORDING_STATE",
    "SERVER_READY_STATE",
    "INSTRUMENT_INITIALIZING_STATE",
    "UnrecognizedCommTypeFromMainToDataAnalyzerError",
    "FIFO_READ_PRODUCER_DATA_OFFSET",
    "FIFO_READ_PRODUCER_WELL_AMPLITUDE",
    "FIFO_READ_PRODUCER_REF_AMPLITUDE",
    "ADC_OFFSET_DESCRIPTION_TAG",
    "ADC_CH_TO_IS_REF_SENSOR",
    "UnrecognizedMantarrayNamingCommandError",
    "check_mantarray_serial_number",
    "FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES",
    "FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS",
    "OUTGOING_DATA_BUFFER_SIZE",
    "get_latest_firmware_name",
    "InvalidDataFramePeriodError",
    "MICROSECONDS_PER_CENTIMILLISECOND",
    "DEFAULT_SERVER_PORT_NUMBER",
    "CURI_BIO_ACCOUNT_UUID",
    "CURI_BIO_USER_ACCOUNT_ID",
    "MantarrayFrontPanelMixIn",
    "MantarrayFrontPanel",
    "ImproperlyFormattedCustomerAccountUUIDError",
    "ImproperlyFormattedUserAccountUUIDError",
    "RecordingFolderDoesNotExistError",
    "VALID_CONFIG_SETTINGS",
    "FIRMWARE_VERSION_WIRE_OUT_ADDRESS",
    "SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS",
    "SUBPROCESS_POLL_DELAY_SECONDS",
    "ScriptDoesNotContainEndCommandError",
    "WELL_24_INDEX_TO_ADC_AND_CH_INDEX",
    "FirmwareFileNameDoesNotMatchWireOutVersionError",
    "SECONDS_TO_WAIT_WHEN_POLLING_QUEUES",
    "ServerThread",
    "server",
    "get_the_server_thread",
    "clear_the_server_thread",
    "clear_server_singletons",
    "MantarrayQueueContainer",
    "BARCODE_SCANNER_TRIGGER_IN_ADDRESS",
    "BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS",
    "BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS",
    "BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS",
    "BARCODE_POLL_PERIOD",
    "BARCODE_CONFIRM_CLEAR_WAIT_SECONDS",
    "BarcodeNotClearedError",
    "CLEARED_BARCODE_VALUE",
    "CLEAR_BARCODE_TRIG_BIT",
    "START_BARCODE_SCAN_TRIG_BIT",
    "BARCODE_GET_SCAN_WAIT_SECONDS",
    "check_barcode_for_errors",
    "BarcodeScannerNotRespondingError",
    "NO_PLATE_DETECTED_BARCODE_VALUE",
    "BARCODE_VALID_UUID",
    "BARCODE_INVALID_UUID",
    "NO_PLATE_DETECTED_UUID",
    "BARCODE_UNREADABLE_UUID",
    "UnrecognizedRecordingCommandError",
    "UnrecognizedCommandToInstrumentError",
    "get_current_software_version",
    "ServerThreadNotInitializedError",
    "ServerThreadSingletonAlreadySetError",
    "mc_simulator",
    "MantarrayMcSimulator",
    "create_data_packet",
    "SERIAL_COMM_MAGIC_WORD_BYTES",
    "SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS",
    "UnrecognizedSimulatorTestCommandError",
    "NANOSECONDS_PER_CENTIMILLISECOND",
    "InstrumentCommProcess",
    "InstrumentCommIncorrectHeaderError",
    "SERIAL_COMM_STATUS_BEACON_PACKET_TYPE",
    "SERIAL_COMM_MAIN_MODULE_ID",
    "SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE",
    "SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE",
    "SERIAL_COMM_HANDSHAKE_PACKET_TYPE",
    "SERIAL_COMM_MODULE_ID_INDEX",
    "SERIAL_COMM_PACKET_TYPE_INDEX",
    "UnrecognizedSerialCommModuleIdError",
    "UnrecognizedSerialCommPacketTypeError",
    "McCommunicationProcess",
    "SERIAL_COMM_CHECKSUM_LENGTH_BYTES",
    "SERIAL_COMM_TIMESTAMP_LENGTH_BYTES",
    "SerialCommPacketRegistrationTimoutError",
    "SerialCommIncorrectMagicWordFromMantarrayError",
    "SerialCommPacketRegistrationReadEmptyError",
    "SERIAL_COMM_MAX_PACKET_LENGTH_BYTES",
    "SerialCommPacketRegistrationSearchExhaustedError",
    "SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE",
    "SERIAL_COMM_REBOOT_COMMAND_BYTE",
    "MAX_MC_REBOOT_DURATION_SECONDS",
    "mc_comm",
    "validate_checksum",
    "SerialCommIncorrectChecksumFromInstrumentError",
    "SERIAL_COMM_BAUD_RATE",
    "SerialCommIncorrectChecksumFromPCError",
    "SERIAL_COMM_ADDITIONAL_BYTES_INDEX",
    "convert_to_metadata_bytes",
    "SERIAL_COMM_METADATA_BYTES_LENGTH",
    "SerialCommMetadataValueTooLargeError",
    "SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE",
    "SERIAL_COMM_GET_METADATA_COMMAND_BYTE",
    "parse_metadata_bytes",
    "convert_metadata_bytes_to_str",
    "SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS",
    "UnrecognizedCommandFromMainToMcCommError",
    "SERIAL_COMM_MIN_PACKET_SIZE_BYTES",
    "SerialCommPacketFromMantarrayTooSmallError",
    "SERIAL_COMM_PACKET_INFO_LENGTH_BYTES",
    "SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS",
    "SERIAL_COMM_TIMESTAMP_BYTES_INDEX",
    "SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES",
    "SerialCommTooManyMissedHandshakesError",
    "SERIAL_COMM_MAX_TIMESTAMP_VALUE",
    "SerialCommUntrackedCommandResponseError",
    "SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS",
    "SerialCommCommandResponseTimeoutError",
    "SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS",
    "SerialCommStatusBeaconTimeoutError",
    "InstrumentRebootTimeoutError",
    "SERIAL_COMM_STATUS_CODE_LENGTH_BYTES",
    "SERIAL_COMM_IDLE_READY_CODE",
    "SERIAL_COMM_TIME_SYNC_READY_CODE",
    "SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE",
    "SERIAL_COMM_BOOT_UP_CODE",
    "SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS",
    "SerialCommHandshakeTimeoutError",
    "convert_to_status_code_bytes",
    "SERIAL_COMM_MAX_DATA_LENGTH_BYTES",
    "SERIAL_COMM_SET_TIME_COMMAND_BYTE",
    "convert_to_timestamp_bytes",
    "get_serial_comm_timestamp",
    "SERIAL_COMM_TIMESTAMP_EPOCH",
    "SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE",
    "SERIAL_COMM_FATAL_ERROR_CODE",
    "SERIAL_COMM_SOFT_ERROR_CODE",
    "MantarrayInstrumentError",
    "InstrumentFatalError",
    "InstrumentSoftError",
    "SERIAL_COMM_START_DATA_STREAMING_COMMAND_BYTE",
    "SERIAL_COMM_STOP_DATA_STREAMING_COMMAND_BYTE",
    "SERIAL_COMM_STREAM_MODE_CHANGED_BYTE",
    "SERIAL_COMM_STREAM_MODE_UNCHANGED_BYTE",
    "InstrumentDataStreamingAlreadyStartedError",
    "InstrumentDataStreamingAlreadyStoppedError",
    "SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE",
    "SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE",
    "MICROSECONDS_PER_MILLISECOND",
    "SerialCommInvalidSamplingPeriodError",
    "InvalidBeta2FlagOptionError",
    "SERIAL_COMM_PLATE_EVENT_PACKET_TYPE",
    "create_magnetometer_config_dict",
    "create_sensor_axis_bitmask",
    "create_magnetometer_config_bytes",
    "SERIAL_COMM_NUM_DATA_CHANNELS",
    "convert_bitmask_to_config_dict",
]
