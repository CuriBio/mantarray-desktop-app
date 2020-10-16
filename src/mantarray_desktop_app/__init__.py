# -*- coding: utf-8 -*-
"""Docstring."""

from . import fifo_read_producer
from . import fifo_simulator
from . import file_writer
from . import firmware_manager
from . import main
from . import ok_comm
from . import process_manager
from . import process_monitor
from .constants import ADC_CH_TO_24_WELL_INDEX
from .constants import ADC_CH_TO_IS_REF_SENSOR
from .constants import ADC_GAIN
from .constants import ADC_GAIN_DESCRIPTION_TAG
from .constants import ADC_GAIN_SETTING_UUID
from .constants import ADC_OFFSET_DESCRIPTION_TAG
from .constants import ADC_REF_OFFSET_UUID
from .constants import ADC_TISSUE_OFFSET_UUID
from .constants import BUFFERING_STATE
from .constants import CALIBRATED_STATE
from .constants import CALIBRATING_STATE
from .constants import CALIBRATION_NEEDED_STATE
from .constants import CHANNEL_INDEX_TO_24_WELL_INDEX
from .constants import COMPILED_EXE_BUILD_TIMESTAMP
from .constants import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from .constants import CONSTRUCT_SENSORS_PER_REF_SENSOR
from .constants import CURI_BIO_ACCOUNT_UUID
from .constants import CURI_BIO_USER_ACCOUNT_ID
from .constants import CURRENT_HDF5_FILE_FORMAT_VERSION
from .constants import CURRENT_SOFTWARE_VERSION
from .constants import CUSTOMER_ACCOUNT_ID_UUID
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
from .constants import INSTRUMENT_INITIALIZING_STATE
from .constants import LIVE_VIEW_ACTIVE_STATE
from .constants import MAIN_FIRMWARE_VERSION_UUID
from .constants import MANTARRAY_NICKNAME_UUID
from .constants import MANTARRAY_SERIAL_NUMBER_UUID
from .constants import MAX_POSSIBLE_CONNECTED_BOARDS
from .constants import MICROSECONDS_PER_CENTIMILLISECOND
from .constants import MIDSCALE_CODE
from .constants import MILLIVOLTS_PER_VOLT
from .constants import OK_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
from .constants import OUTGOING_DATA_BUFFER_SIZE
from .constants import PLATE_BARCODE_UUID
from .constants import RAW_TO_SIGNED_CONVERSION_VALUE
from .constants import RECORDING_STATE
from .constants import REF_INDEX_TO_24_WELL_INDEX
from .constants import REF_SAMPLING_PERIOD_UUID
from .constants import REFERENCE_SENSOR_SAMPLING_PERIOD
from .constants import REFERENCE_VOLTAGE
from .constants import REFERENCE_VOLTAGE_UUID
from .constants import ROUND_ROBIN_PERIOD
from .constants import SERVER_INITIALIZING_STATE
from .constants import SERVER_READY_STATE
from .constants import SLEEP_FIRMWARE_VERSION_UUID
from .constants import SOFTWARE_RELEASE_VERSION_UUID
from .constants import START_MANAGED_ACQUISITION_COMMUNICATION
from .constants import START_RECORDING_TIME_INDEX_UUID
from .constants import SUBPROCESS_POLL_DELAY_SECONDS
from .constants import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from .constants import SYSTEM_STATUS_UUIDS
from .constants import TIMESTEP_CONVERSION_FACTOR
from .constants import TISSUE_SAMPLING_PERIOD_UUID
from .constants import TOTAL_WELL_COUNT_UUID
from .constants import USER_ACCOUNT_ID_UUID
from .constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from .constants import UTC_BEGINNING_RECORDING_UUID
from .constants import UTC_FIRST_REF_DATA_POINT_UUID
from .constants import UTC_FIRST_TISSUE_DATA_POINT_UUID
from .constants import VALID_CONFIG_SETTINGS
from .constants import VALID_SCRIPTING_COMMANDS
from .constants import WELL_24_INDEX_TO_ADC_AND_CH_INDEX
from .constants import WELL_COLUMN_UUID
from .constants import WELL_INDEX_UUID
from .constants import WELL_NAME_UUID
from .constants import WELL_ROW_UUID
from .constants import XEM_SERIAL_NUMBER_UUID
from .data_analyzer import convert_24_bit_codes_to_voltage
from .data_analyzer import DataAnalyzerProcess
from .exceptions import AttemptToAddCyclesWhileSPIRunningError
from .exceptions import AttemptToInitializeFIFOReadsError
from .exceptions import FirmwareFileNameDoesNotMatchWireOutVersionError
from .exceptions import FirstManagedReadLessThanOneRoundRobinError
from .exceptions import ImproperlyFormattedCustomerAccountUUIDError
from .exceptions import ImproperlyFormattedUserAccountUUIDError
from .exceptions import InvalidDataFramePeriodError
from .exceptions import InvalidDataTypeFromOkCommError
from .exceptions import InvalidScriptCommandError
from .exceptions import LocalServerPortAlreadyInUseError
from .exceptions import MismatchedScriptTypeError
from .exceptions import MultiprocessingNotSetToSpawnError
from .exceptions import RecordingFolderDoesNotExistError
from .exceptions import ScriptDoesNotContainEndCommandError
from .exceptions import SystemStartUpError
from .exceptions import UnrecognizedAcquisitionManagerCommandError
from .exceptions import UnrecognizedCommandFromMainToFileWriterError
from .exceptions import UnrecognizedCommTypeFromMainToDataAnalyzerError
from .exceptions import UnrecognizedCommTypeFromMainToOKCommError
from .exceptions import UnrecognizedDataFrameFormatNameError
from .exceptions import UnrecognizedDebugConsoleCommandError
from .exceptions import UnrecognizedMantarrayNamingCommandError
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
from .main import flask_app
from .main import get_api_endpoint
from .main import get_server_port_number
from .main import get_shared_values_between_server_and_monitor
from .main import prepare_to_shutdown
from .main import start_server
from .main import start_server_in_thread
from .mantarray_front_panel import MantarrayFrontPanel
from .mantarray_front_panel import MantarrayFrontPanelMixIn
from .ok_comm import build_file_writer_objects
from .ok_comm import check_mantarray_serial_number
from .ok_comm import execute_debug_console_command
from .ok_comm import OkCommunicationProcess
from .ok_comm import parse_data_frame
from .ok_comm import parse_gain
from .ok_comm import parse_scripting_log
from .ok_comm import parse_scripting_log_line
from .process_manager import get_mantarray_process_manager
from .process_manager import MantarrayProcessesManager
from .process_monitor import get_mantarray_processes_monitor
from .process_monitor import MantarrayProcessesMonitor
from .process_monitor import set_mantarray_processes_monitor
from .system_utils import system_state_eventually_equals
from .system_utils import wait_for_subprocesses_to_start

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
    "get_shared_values_between_server_and_monitor",
    "flask_app",
    "MultiprocessingNotSetToSpawnError",
    "LocalServerPortAlreadyInUseError",
    "UnrecognizedDebugConsoleCommandError",
    "UnrecognizedCommandFromMainToFileWriterError",
    "UnrecognizedDataFrameFormatNameError",
    "start_server",
    "get_server_port_number",
    "process_manager",
    "MantarrayProcessesManager",
    "get_mantarray_process_manager",
    "set_mantarray_processes_monitor",
    "get_mantarray_processes_monitor",
    "MantarrayProcessesMonitor",
    "start_server_in_thread",
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
    "parse_adc_metadata_byte",
    "MIDSCALE_CODE",
    "REFERENCE_VOLTAGE",
    "MILLIVOLTS_PER_VOLT",
    "convert_24_bit_codes_to_voltage",
    "FileWriterProcess",
    "InvalidDataTypeFromOkCommError",
    "build_file_writer_objects",
    "UnrecognizedCommTypeFromMainToOKCommError",
    "UnrecognizedAcquisitionManagerCommandError",
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
    "OK_COMM_PERFOMANCE_LOGGING_NUM_CYCLES",
    "SYSTEM_STATUS_UUIDS",
    "DEFAULT_USER_CONFIG",
    "firmware_manager",
    "sort_firmware_files",
    "get_latest_firmware",
    "get_latest_firmware_version",
    "UTC_BEGINNING_DATA_ACQUISTION_UUID",
    "START_RECORDING_TIME_INDEX_UUID",
    "CUSTOMER_ACCOUNT_ID_UUID",
    "USER_ACCOUNT_ID_UUID",
    "SOFTWARE_RELEASE_VERSION_UUID",
    "MAIN_FIRMWARE_VERSION_UUID",
    "SLEEP_FIRMWARE_VERSION_UUID",
    "XEM_SERIAL_NUMBER_UUID",
    "MANTARRAY_NICKNAME_UUID",
    "REFERENCE_VOLTAGE_UUID",
    "WELL_NAME_UUID",
    "WELL_ROW_UUID",
    "WELL_COLUMN_UUID",
    "WELL_INDEX_UUID",
    "TOTAL_WELL_COUNT_UUID",
    "REF_SAMPLING_PERIOD_UUID",
    "TISSUE_SAMPLING_PERIOD_UUID",
    "ADC_GAIN_DESCRIPTION_TAG",
    "parse_gain",
    "ADC_GAIN_SETTING_UUID",
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
    "PLATE_BARCODE_UUID",
    "FIFO_READ_PRODUCER_DATA_OFFSET",
    "FIFO_READ_PRODUCER_WELL_AMPLITUDE",
    "FIFO_READ_PRODUCER_REF_AMPLITUDE",
    "ADC_OFFSET_DESCRIPTION_TAG",
    "ADC_TISSUE_OFFSET_UUID",
    "ADC_REF_OFFSET_UUID",
    "ADC_CH_TO_IS_REF_SENSOR",
    "UnrecognizedMantarrayNamingCommandError",
    "check_mantarray_serial_number",
    "MANTARRAY_SERIAL_NUMBER_UUID",
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
    "prepare_to_shutdown",
    "FIRMWARE_VERSION_WIRE_OUT_ADDRESS",
    "SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS",
    "SUBPROCESS_POLL_DELAY_SECONDS",
    "ScriptDoesNotContainEndCommandError",
    "UTC_BEGINNING_RECORDING_UUID",
    "UTC_FIRST_TISSUE_DATA_POINT_UUID",
    "UTC_FIRST_REF_DATA_POINT_UUID",
    "WELL_24_INDEX_TO_ADC_AND_CH_INDEX",
    "FirmwareFileNameDoesNotMatchWireOutVersionError",
]
