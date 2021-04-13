# -*- coding: utf-8 -*-
import datetime
import uuid

from mantarray_desktop_app import ADC_CH_TO_24_WELL_INDEX
from mantarray_desktop_app import ADC_CH_TO_IS_REF_SENSOR
from mantarray_desktop_app import ADC_GAIN
from mantarray_desktop_app import ADC_GAIN_DESCRIPTION_TAG
from mantarray_desktop_app import ADC_OFFSET_DESCRIPTION_TAG
from mantarray_desktop_app import BARCODE_CONFIRM_CLEAR_WAIT_SECONDS
from mantarray_desktop_app import BARCODE_GET_SCAN_WAIT_SECONDS
from mantarray_desktop_app import BARCODE_INVALID_UUID
from mantarray_desktop_app import BARCODE_POLL_PERIOD
from mantarray_desktop_app import BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS
from mantarray_desktop_app import BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS
from mantarray_desktop_app import BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS
from mantarray_desktop_app import BARCODE_SCANNER_TRIGGER_IN_ADDRESS
from mantarray_desktop_app import BARCODE_UNREADABLE_UUID
from mantarray_desktop_app import BARCODE_VALID_UUID
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import CHANNEL_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import CLEAR_BARCODE_TRIG_BIT
from mantarray_desktop_app import CLEARED_BARCODE_VALUE
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CONSTRUCT_SENSORS_PER_REF_SENSOR
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import DEFAULT_USER_CONFIG
from mantarray_desktop_app import FIFO_READ_PRODUCER_CYCLES_PER_ITERATION
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_REF_AMPLITUDE
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_SLEEP_DURATION
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
from mantarray_desktop_app import FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
from mantarray_desktop_app import FIRMWARE_VERSION_WIRE_OUT_ADDRESS
from mantarray_desktop_app import INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MAX_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app import MAX_POSSIBLE_CONNECTED_BOARDS
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MIDSCALE_CODE
from mantarray_desktop_app import MILLIVOLTS_PER_VOLT
from mantarray_desktop_app import NANOSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import NO_PLATE_DETECTED_BARCODE_VALUE
from mantarray_desktop_app import NO_PLATE_DETECTED_UUID
from mantarray_desktop_app import OUTGOING_DATA_BUFFER_SIZE
from mantarray_desktop_app import RAW_TO_SIGNED_CONVERSION_VALUE
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from mantarray_desktop_app import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from mantarray_desktop_app import SERIAL_COMM_BOOT_UP_CODE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_FATAL_ERROR_CODE
from mantarray_desktop_app import SERIAL_COMM_GET_METADATA_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_IDLE_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_DATA_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_METADATA_BYTES_LENGTH
from mantarray_desktop_app import SERIAL_COMM_MIN_PACKET_SIZE_BYTES
from mantarray_desktop_app import SERIAL_COMM_MODULE_ID_INDEX
from mantarray_desktop_app import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from mantarray_desktop_app import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_TYPE_INDEX
from mantarray_desktop_app import SERIAL_COMM_REBOOT_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SET_TIME_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_SOFT_ERROR_CODE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_TIME_SYNC_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_BYTES_INDEX
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_EPOCH
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import START_BARCODE_SCAN_TRIG_BIT
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import SUBPROCESS_POLL_DELAY_SECONDS
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app import VALID_CONFIG_SETTINGS
from mantarray_desktop_app import VALID_SCRIPTING_COMMANDS
from mantarray_desktop_app import WELL_24_INDEX_TO_ADC_AND_CH_INDEX
import numpy as np
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN


def test_default_server_port_number():
    assert DEFAULT_SERVER_PORT_NUMBER == 4567


def test_max_boards():
    assert MAX_POSSIBLE_CONNECTED_BOARDS == 4


def test_fimrware_addresses():
    assert FIRMWARE_VERSION_WIRE_OUT_ADDRESS == 0x21

    assert BARCODE_SCANNER_TRIGGER_IN_ADDRESS == 0x41
    assert BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS == 0x2A
    assert BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS == 0x2B
    assert BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS == 0x2C


def test_barcode_constants():
    assert CLEAR_BARCODE_TRIG_BIT == 0x5
    assert START_BARCODE_SCAN_TRIG_BIT == 0x6
    assert BARCODE_POLL_PERIOD == 15
    assert BARCODE_CONFIRM_CLEAR_WAIT_SECONDS == 0.5
    assert BARCODE_GET_SCAN_WAIT_SECONDS == 6
    assert CLEARED_BARCODE_VALUE == chr(0) * 12
    assert NO_PLATE_DETECTED_BARCODE_VALUE == chr(21) * 12


def test_barcode_UUIDs():
    assert BARCODE_VALID_UUID == uuid.UUID("22d5054a-ede2-4e94-8f74-f4ebaafde247")
    assert BARCODE_INVALID_UUID == uuid.UUID("cec87db3-3181-4b84-8d5e-1643cd00b567")
    assert NO_PLATE_DETECTED_UUID == uuid.UUID("e86ca1d0-2350-4e1b-ad6a-5c78a6c2ed7a")
    assert BARCODE_UNREADABLE_UUID == uuid.UUID("87525976-4c98-4783-a6f2-ae34a89dace6")


def test_default_UUIDs():
    assert CURI_BIO_ACCOUNT_UUID == uuid.UUID("73f52be0-368c-42d8-a1fd-660d49ba5604")
    assert CURI_BIO_USER_ACCOUNT_ID == uuid.UUID("455b93eb-c78f-4494-9f73-d3291130f126")


def test_running_fifo_simulator_constants():
    assert FIFO_READ_PRODUCER_SLEEP_DURATION == (
        (FIFO_READ_PRODUCER_CYCLES_PER_ITERATION * ROUND_ROBIN_PERIOD) / 100000
    )
    assert FIFO_READ_PRODUCER_CYCLES_PER_ITERATION == 20
    assert FIFO_READ_PRODUCER_SAWTOOTH_PERIOD == (
        (100000 // TIMESTEP_CONVERSION_FACTOR) / (2 * np.pi)
    )
    assert FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE == 0xFFFFFFFF
    assert RAW_TO_SIGNED_CONVERSION_VALUE == 2 ** 23
    assert FIFO_READ_PRODUCER_DATA_OFFSET == 0x800000
    assert FIFO_READ_PRODUCER_WELL_AMPLITUDE == 0xA8000
    assert FIFO_READ_PRODUCER_REF_AMPLITUDE == 0x100000


def test_hardware_time_constants():
    assert DATA_FRAME_PERIOD == 20
    assert ROUND_ROBIN_PERIOD == DATA_FRAME_PERIOD * DATA_FRAMES_PER_ROUND_ROBIN
    assert REFERENCE_SENSOR_SAMPLING_PERIOD == ROUND_ROBIN_PERIOD // 4
    assert CONSTRUCT_SENSOR_SAMPLING_PERIOD == ROUND_ROBIN_PERIOD
    assert TIMESTEP_CONVERSION_FACTOR == 5
    assert MICROSECONDS_PER_CENTIMILLISECOND == 10
    assert NANOSECONDS_PER_CENTIMILLISECOND == 10 ** 4


def test_adc_reading_constants():
    assert REFERENCE_VOLTAGE == 2.5
    assert MIDSCALE_CODE == 0x800000
    assert ADC_GAIN == 2
    assert MILLIVOLTS_PER_VOLT == 1000


def test_sensors_and_mappings():
    assert CONSTRUCT_SENSORS_PER_REF_SENSOR == 4
    assert CHANNEL_INDEX_TO_24_WELL_INDEX == {
        0: 0,
        1: 1,
        2: 4,
        3: 5,
        4: 8,
        5: 9,
        6: 12,
        7: 13,
        8: 16,
        9: 17,
        10: 20,
        11: 21,
        12: 7,
        13: 6,
        14: 3,
        15: 2,
        16: 15,
        17: 14,
        18: 11,
        19: 10,
        20: 23,
        21: 22,
        22: 19,
        23: 18,
    }
    assert REF_INDEX_TO_24_WELL_INDEX == {
        0: frozenset([0, 1, 4, 5]),
        1: frozenset([8, 9, 12, 13]),
        2: frozenset([16, 17, 20, 21]),
        3: frozenset([2, 3, 6, 7]),
        4: frozenset([10, 11, 14, 15]),
        5: frozenset([18, 19, 22, 23]),
    }
    assert ADC_CH_TO_24_WELL_INDEX == {
        0: {0: 0, 2: 1, 4: 4, 6: 5},
        1: {0: 8, 2: 9, 4: 12, 6: 13},
        2: {0: 16, 2: 17, 4: 20, 6: 21},
        3: {6: 2, 4: 3, 2: 6, 0: 7},
        4: {6: 10, 4: 11, 2: 14, 0: 15},
        5: {6: 18, 4: 19, 2: 22, 0: 23},
    }
    assert ADC_CH_TO_IS_REF_SENSOR == {
        0: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        1: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        2: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        3: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        4: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        5: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
    }
    for well_idx in range(24):
        adc_num, ch_num = WELL_24_INDEX_TO_ADC_AND_CH_INDEX[well_idx]
        assert ADC_CH_TO_24_WELL_INDEX[adc_num][ch_num] == well_idx


def test_CURRENT_HDF5_FILE_FORMAT_VERSION():
    assert CURRENT_HDF5_FILE_FORMAT_VERSION == "0.4.1"


def test_COMPILED_EXE_BUILD_TIMESTAMP():
    assert COMPILED_EXE_BUILD_TIMESTAMP == "REPLACETHISWITHTIMESTAMPDURINGBUILD"


def test_CURRENT_SOFTWARE_VERSION():
    assert CURRENT_SOFTWARE_VERSION == "REPLACETHISWITHVERSIONDURINGBUILD"


def test_managed_acquisition_commands():
    assert START_MANAGED_ACQUISITION_COMMUNICATION == {
        "communication_type": "to_instrument",
        "command": "start_managed_acquisition",
    }
    assert STOP_MANAGED_ACQUISITION_COMMUNICATION == {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
    }


def test_scripting():
    assert VALID_SCRIPTING_COMMANDS == frozenset(
        [
            "begin_hardware_script",
            "end_hardware_script",
            "set_wire_in",
            "read_wire_out",
            "activate_trigger_in",
            "comm_delay",
            "start_calibration",
        ]
    )
    assert ADC_GAIN_DESCRIPTION_TAG == "adc_gain_setting"
    assert ADC_OFFSET_DESCRIPTION_TAG == "adc_offset_reading"


def test_buffer_size_constants():
    assert DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS == 700000
    assert FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS == 3000000
    assert OUTGOING_DATA_BUFFER_SIZE == 2


def test_performance_logging_constants():
    assert INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES == 20
    assert FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES == 2000


def test_system_status_uuids():
    assert SERVER_INITIALIZING_STATE == "server_initializing"
    assert SERVER_READY_STATE == "server_ready"
    assert INSTRUMENT_INITIALIZING_STATE == "instrument_initializing"
    assert CALIBRATION_NEEDED_STATE == "calibration_needed"
    assert CALIBRATING_STATE == "calibrating"
    assert CALIBRATED_STATE == "calibrated"
    assert BUFFERING_STATE == "buffering"
    assert LIVE_VIEW_ACTIVE_STATE == "live_view_active"
    assert RECORDING_STATE == "recording"
    assert SYSTEM_STATUS_UUIDS == {
        SERVER_INITIALIZING_STATE: uuid.UUID("04471bcf-1a00-4a0d-83c8-4160622f9a25"),
        SERVER_READY_STATE: uuid.UUID("8e24ef4d-2353-4e9d-aa32-4346126e73e3"),
        INSTRUMENT_INITIALIZING_STATE: uuid.UUID(
            "d2e3d386-b760-4c9a-8b2d-410362ff11c4"
        ),
        CALIBRATION_NEEDED_STATE: uuid.UUID("009301eb-625c-4dc4-9e92-1a4d0762465f"),
        CALIBRATING_STATE: uuid.UUID("43c08fc5-ca2f-4dcd-9dff-5e9324cb5dbf"),
        CALIBRATED_STATE: uuid.UUID("b480373b-9466-4fa0-92a6-fa5f8e340d30"),
        BUFFERING_STATE: uuid.UUID("dc774d4b-6bd1-4717-b36e-6df6f1ef6cf4"),
        LIVE_VIEW_ACTIVE_STATE: uuid.UUID("9fbee58e-c6af-49a5-b2e2-5b085eead2ea"),
        RECORDING_STATE: uuid.UUID("1e3d76a2-508d-4c99-8bf5-60dac5cc51fe"),
    }


def test_user_config():
    assert DEFAULT_USER_CONFIG == {
        "Customer Account ID": "",
        "User Account ID": "",
    }
    assert VALID_CONFIG_SETTINGS == frozenset(
        ["customer_account_uuid", "user_account_uuid", "recording_directory"]
    )


def test_shutdown_values():
    assert SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS == 1
    assert SUBPROCESS_POLL_DELAY_SECONDS == 0.025


def test_parallelism_config():
    assert SECONDS_TO_WAIT_WHEN_POLLING_QUEUES == 0.02


def test_serial_comm():
    assert MAX_MC_REBOOT_DURATION_SECONDS == 5

    assert SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES == 3

    assert SERIAL_COMM_TIMESTAMP_EPOCH == datetime.datetime(
        year=2021, month=1, day=1, tzinfo=datetime.timezone.utc
    )

    assert SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS == 5
    assert SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS == 5
    assert SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS == 5
    assert SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS == 6
    assert SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS == 7
    assert SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS == 8

    assert SERIAL_COMM_MAGIC_WORD_BYTES == b"CURI BIO"
    assert SERIAL_COMM_PACKET_INFO_LENGTH_BYTES == 2
    assert SERIAL_COMM_TIMESTAMP_LENGTH_BYTES == 8
    assert SERIAL_COMM_CHECKSUM_LENGTH_BYTES == 4
    assert SERIAL_COMM_STATUS_CODE_LENGTH_BYTES == 4
    assert SERIAL_COMM_MAX_PACKET_LENGTH_BYTES == 2 ** 16
    assert SERIAL_COMM_MAX_DATA_LENGTH_BYTES == (
        SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
        - SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
        - SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
        - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
        - 10
    )
    assert SERIAL_COMM_MIN_PACKET_SIZE_BYTES == (
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
        + SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
        + SERIAL_COMM_CHECKSUM_LENGTH_BYTES
    )
    assert (
        SERIAL_COMM_MAX_TIMESTAMP_VALUE
        == 2 ** (8 * SERIAL_COMM_TIMESTAMP_LENGTH_BYTES) - 1
    )

    assert (
        SERIAL_COMM_TIMESTAMP_BYTES_INDEX
        == len(SERIAL_COMM_MAGIC_WORD_BYTES) + SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
    )
    assert SERIAL_COMM_MODULE_ID_INDEX == 18
    assert SERIAL_COMM_PACKET_TYPE_INDEX == 19
    assert SERIAL_COMM_ADDITIONAL_BYTES_INDEX == 20

    assert SERIAL_COMM_MAIN_MODULE_ID == 0
    assert SERIAL_COMM_STATUS_BEACON_PACKET_TYPE == 0
    assert SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE == 3
    assert SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE == 4
    assert SERIAL_COMM_HANDSHAKE_PACKET_TYPE == 4
    assert SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE == 255
    assert SERIAL_COMM_REBOOT_COMMAND_BYTE == 0
    assert SERIAL_COMM_GET_METADATA_COMMAND_BYTE == 6
    assert SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE == 9

    assert SERIAL_COMM_METADATA_BYTES_LENGTH == 32
    assert SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE == 4
    assert SERIAL_COMM_HANDSHAKE_PACKET_TYPE == 4
    assert SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE == 255
    assert SERIAL_COMM_REBOOT_COMMAND_BYTE == 0
    assert SERIAL_COMM_GET_METADATA_COMMAND_BYTE == 6
    assert SERIAL_COMM_DUMP_EEPROM_COMMAND_BYTE == 7
    assert SERIAL_COMM_SET_TIME_COMMAND_BYTE == 8
    assert SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE == 9

    assert SERIAL_COMM_METADATA_BYTES_LENGTH == 32

    assert SERIAL_COMM_IDLE_READY_CODE == 0
    assert SERIAL_COMM_TIME_SYNC_READY_CODE == 1
    assert SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE == 2
    assert SERIAL_COMM_BOOT_UP_CODE == 3
    assert SERIAL_COMM_FATAL_ERROR_CODE == 4
    assert SERIAL_COMM_SOFT_ERROR_CODE == 5
