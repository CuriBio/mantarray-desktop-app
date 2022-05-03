# -*- coding: utf-8 -*-
import datetime
from enum import Enum
from enum import IntEnum
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
from mantarray_desktop_app import CALIBRATION_RECORDING_DUR_SECONDS
from mantarray_desktop_app import CHECKING_FOR_UPDATES_STATE
from mantarray_desktop_app import CLEAR_BARCODE_TRIG_BIT
from mantarray_desktop_app import CLEARED_BARCODE_VALUE
from mantarray_desktop_app import CLOUD_ENDPOINT_USER_OPTION
from mantarray_desktop_app import CLOUD_ENDPOINT_VALID_OPTIONS
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CONSTRUCT_SENSORS_PER_REF_SENSOR
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import DATA_ANALYZER_BETA_1_BUFFER_SIZE
from mantarray_desktop_app import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app import DEFAULT_SERVER_PORT_NUMBER
from mantarray_desktop_app import DEFAULT_USER_CONFIG
from mantarray_desktop_app import DOWNLOADING_UPDATES_STATE
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_REF_AMPLITUDE
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
from mantarray_desktop_app import FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES
from mantarray_desktop_app import FIRMWARE_VERSION_WIRE_OUT_ADDRESS
from mantarray_desktop_app import INSTALLING_UPDATES_STATE
from mantarray_desktop_app import INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MAX_CHANNEL_FIRMWARE_UPDATE_DURATION_SECONDS
from mantarray_desktop_app import MAX_MAIN_FIRMWARE_UPDATE_DURATION_SECONDS
from mantarray_desktop_app import MAX_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app import MAX_POSSIBLE_CONNECTED_BOARDS
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MICROSECONDS_PER_MILLISECOND
from mantarray_desktop_app import MIDSCALE_CODE
from mantarray_desktop_app import MILLIVOLTS_PER_VOLT
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import NANOSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import NO_PLATE_DETECTED_BARCODE_VALUE
from mantarray_desktop_app import NO_PLATE_DETECTED_UUID
from mantarray_desktop_app import NUM_INITIAL_PACKETS_TO_DROP
from mantarray_desktop_app import OUTGOING_DATA_BUFFER_SIZE
from mantarray_desktop_app import RAW_TO_SIGNED_CONVERSION_VALUE
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from mantarray_desktop_app import SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_BAUD_RATE
from mantarray_desktop_app import SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_COMMAND_FAILURE_BYTE
from mantarray_desktop_app import SERIAL_COMM_COMMAND_SUCCESS_BYTE
from mantarray_desktop_app import SERIAL_COMM_DATA_SAMPLE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_DEFAULT_DATA_CHANNEL
from mantarray_desktop_app import SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_ERROR_ACK_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_GET_METADATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_GOING_DORMANT_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_LENGTH_BYTES_CY
from mantarray_desktop_app import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MAX_FULL_PACKET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_METADATA_BYTES_LENGTH
from mantarray_desktop_app import SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from mantarray_desktop_app import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from mantarray_desktop_app import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from mantarray_desktop_app import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR_CY
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app import SERIAL_COMM_OKAY_CODE
from mantarray_desktop_app import SERIAL_COMM_PACKET_BASE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_HEADER_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_TYPE_INDEX
from mantarray_desktop_app import SERIAL_COMM_PACKET_TYPE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PAYLOAD_INDEX
from mantarray_desktop_app import SERIAL_COMM_PLATE_EVENT_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_REBOOT_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import SERIAL_COMM_SET_NICKNAME_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_START_STIM_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STOP_STIM_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_BYTES_INDEX
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_EPOCH
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import START_BARCODE_SCAN_TRIG_BIT
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import STIM_COMPLETE_SUBPROTOCOL_IDX
from mantarray_desktop_app import STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS
from mantarray_desktop_app import STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS
from mantarray_desktop_app import STIM_MAX_PULSE_DURATION_MICROSECONDS
from mantarray_desktop_app import STIM_NO_PROTOCOL_ASSIGNED
from mantarray_desktop_app import StimProtocolStatuses
from mantarray_desktop_app import STM_VID
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import SUBPROCESS_JOIN_TIMEOUT_SECONDS
from mantarray_desktop_app import SUBPROCESS_POLL_DELAY_SECONDS
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app import UPDATE_ERROR_STATE
from mantarray_desktop_app import UPDATES_COMPLETE_STATE
from mantarray_desktop_app import UPDATES_NEEDED_STATE
from mantarray_desktop_app import VALID_CONFIG_SETTINGS
from mantarray_desktop_app import VALID_SCRIPTING_COMMANDS
from mantarray_desktop_app import WELL_24_INDEX_TO_ADC_AND_CH_INDEX
from mantarray_desktop_app.constants import ALL_VALID_BARCODE_HEADERS
from mantarray_desktop_app.constants import BARCODE_HEADERS
from mantarray_desktop_app.constants import BARCODE_LEN
from mantarray_desktop_app.constants import SERIAL_COMM_NICKNAME_BYTES_LENGTH
from mantarray_desktop_app.constants import SERIAL_COMM_SERIAL_NUMBER_BYTES_LENGTH
from mantarray_desktop_app.constants import SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE
from mantarray_desktop_app.constants import STIM_OPEN_CIRCUIT_THRESHOLD_OHMS
from mantarray_desktop_app.constants import STIM_SHORT_CIRCUIT_THRESHOLD_OHMS
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
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

    assert BARCODE_LEN == 12
    assert CLEARED_BARCODE_VALUE == chr(0) * BARCODE_LEN
    assert NO_PLATE_DETECTED_BARCODE_VALUE == chr(21) * BARCODE_LEN
    assert BARCODE_HEADERS == {"plate_barcode": "ML", "stim_barcode": "MS"}
    assert ALL_VALID_BARCODE_HEADERS == frozenset(BARCODE_HEADERS.values())


def test_barcode_UUIDs():
    assert BARCODE_VALID_UUID == uuid.UUID("22d5054a-ede2-4e94-8f74-f4ebaafde247")
    assert BARCODE_INVALID_UUID == uuid.UUID("cec87db3-3181-4b84-8d5e-1643cd00b567")
    assert NO_PLATE_DETECTED_UUID == uuid.UUID("e86ca1d0-2350-4e1b-ad6a-5c78a6c2ed7a")
    assert BARCODE_UNREADABLE_UUID == uuid.UUID("87525976-4c98-4783-a6f2-ae34a89dace6")


def test_default_UUIDs():
    assert CURI_BIO_ACCOUNT_UUID == uuid.UUID("73f52be0-368c-42d8-a1fd-660d49ba5604")
    assert CURI_BIO_USER_ACCOUNT_ID == uuid.UUID("455b93eb-c78f-4494-9f73-d3291130f126")


def test_running_fifo_simulator_constants():
    assert FIFO_READ_PRODUCER_SAWTOOTH_PERIOD == ((100000 // TIMESTEP_CONVERSION_FACTOR) / (2 * np.pi))
    assert FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE == 0xFFFFFFFF
    assert RAW_TO_SIGNED_CONVERSION_VALUE == 2**23
    assert (
        FIFO_READ_PRODUCER_DATA_OFFSET == MIDSCALE_CODE + 0xB000 + FIFO_READ_PRODUCER_WELL_AMPLITUDE * 24 // 2
    )
    assert FIFO_READ_PRODUCER_WELL_AMPLITUDE == 0x1014
    assert FIFO_READ_PRODUCER_REF_AMPLITUDE == 0x100


def test_hardware_time_constants():
    assert DATA_FRAME_PERIOD == 20
    assert ROUND_ROBIN_PERIOD == DATA_FRAME_PERIOD * DATA_FRAMES_PER_ROUND_ROBIN
    assert REFERENCE_SENSOR_SAMPLING_PERIOD == ROUND_ROBIN_PERIOD // 4
    assert CONSTRUCT_SENSOR_SAMPLING_PERIOD == ROUND_ROBIN_PERIOD
    assert TIMESTEP_CONVERSION_FACTOR == 5
    assert MICROSECONDS_PER_CENTIMILLISECOND == 10
    assert NANOSECONDS_PER_CENTIMILLISECOND == 10**4
    assert MICROSECONDS_PER_MILLISECOND == 10**3


def test_adc_reading_constants():
    assert REFERENCE_VOLTAGE == 2.5
    assert MIDSCALE_CODE == 0x800000
    assert ADC_GAIN == 2
    assert MILLIVOLTS_PER_VOLT == 1000


def test_sensors_and_mappings():
    assert CONSTRUCT_SENSORS_PER_REF_SENSOR == 4
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


def test_current_file_versions():
    assert CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION == "0.4.2"
    assert CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION == "1.0.3"


def test_COMPILED_EXE_BUILD_TIMESTAMP():
    assert COMPILED_EXE_BUILD_TIMESTAMP == "REPLACETHISWITHTIMESTAMPDURINGBUILD"


def test_CURRENT_SOFTWARE_VERSION():
    assert CURRENT_SOFTWARE_VERSION == "REPLACETHISWITHVERSIONDURINGBUILD"


def test_CLOUD_ENDPOINT_USER_OPTION():
    assert CLOUD_ENDPOINT_USER_OPTION == "REPLACETHISWITHENDPOINTDURINGBUILD"


def test_CLOUD_ENDPOINT_VALID_OPTIONS():
    assert CLOUD_ENDPOINT_VALID_OPTIONS == {"test": "curibio-test", "prod": "curibio"}


def test_managed_acquisition_commands():
    assert START_MANAGED_ACQUISITION_COMMUNICATION == {
        "communication_type": "acquisition_manager",
        "command": "start_managed_acquisition",
    }
    assert STOP_MANAGED_ACQUISITION_COMMUNICATION == {
        "communication_type": "acquisition_manager",
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
    assert MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS == 10
    assert DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS == 1000000
    assert FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS == 3000000

    assert OUTGOING_DATA_BUFFER_SIZE == 2
    assert (
        DATA_ANALYZER_BETA_1_BUFFER_SIZE == DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS // ROUND_ROBIN_PERIOD
    )


def test_performance_logging_constants():
    assert INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES == 20
    assert FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES == 2000


def test_system_status_uuids():
    assert SERVER_INITIALIZING_STATE == "server_initializing"
    assert SERVER_READY_STATE == "server_ready"
    assert INSTRUMENT_INITIALIZING_STATE == "instrument_initializing"
    assert CHECKING_FOR_UPDATES_STATE == "checking_for_updates"
    assert CALIBRATION_NEEDED_STATE == "calibration_needed"
    assert CALIBRATING_STATE == "calibrating"
    assert CALIBRATED_STATE == "calibrated"
    assert BUFFERING_STATE == "buffering"
    assert LIVE_VIEW_ACTIVE_STATE == "live_view_active"
    assert RECORDING_STATE == "recording"
    assert UPDATES_NEEDED_STATE == "updates_needed"
    assert DOWNLOADING_UPDATES_STATE == "downloading_updates"
    assert INSTALLING_UPDATES_STATE == "installing_updates"
    assert UPDATES_COMPLETE_STATE == "updates_complete"
    assert UPDATE_ERROR_STATE == "update_error"
    assert SYSTEM_STATUS_UUIDS == {
        SERVER_INITIALIZING_STATE: uuid.UUID("04471bcf-1a00-4a0d-83c8-4160622f9a25"),
        SERVER_READY_STATE: uuid.UUID("8e24ef4d-2353-4e9d-aa32-4346126e73e3"),
        INSTRUMENT_INITIALIZING_STATE: uuid.UUID("d2e3d386-b760-4c9a-8b2d-410362ff11c4"),
        CHECKING_FOR_UPDATES_STATE: uuid.UUID("04fd6f6b-ee9e-4656-aae4-0b9584791f36"),
        CALIBRATION_NEEDED_STATE: uuid.UUID("009301eb-625c-4dc4-9e92-1a4d0762465f"),
        CALIBRATING_STATE: uuid.UUID("43c08fc5-ca2f-4dcd-9dff-5e9324cb5dbf"),
        CALIBRATED_STATE: uuid.UUID("b480373b-9466-4fa0-92a6-fa5f8e340d30"),
        BUFFERING_STATE: uuid.UUID("dc774d4b-6bd1-4717-b36e-6df6f1ef6cf4"),
        LIVE_VIEW_ACTIVE_STATE: uuid.UUID("9fbee58e-c6af-49a5-b2e2-5b085eead2ea"),
        RECORDING_STATE: uuid.UUID("1e3d76a2-508d-4c99-8bf5-60dac5cc51fe"),
        UPDATES_NEEDED_STATE: uuid.UUID("d6dcf2a9-b6ea-4d4e-9423-500f91a82a2f"),
        DOWNLOADING_UPDATES_STATE: uuid.UUID("b623c5fa-af01-46d3-9282-748e19fe374c"),
        INSTALLING_UPDATES_STATE: uuid.UUID("19c9c2d6-0de4-4334-8cb3-a4c7ab0eab00"),
        UPDATES_COMPLETE_STATE: uuid.UUID("31f8fbc9-9b41-4191-8598-6462b7490789"),
        UPDATE_ERROR_STATE: uuid.UUID("33742bfc-d354-4ae5-88b6-2b3cee23aff8"),
    }


def test_user_config():
    assert DEFAULT_USER_CONFIG == {
        "customer_id": "",
        "user_id": "",
    }
    assert VALID_CONFIG_SETTINGS == frozenset(
        [
            "customer_id",
            "user_password",
            "user_id",
            "recording_directory",
            "auto_upload",
            "auto_delete",
        ]
    )


def test_shutdown_values():
    assert SUBPROCESS_JOIN_TIMEOUT_SECONDS == 3
    assert SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS == 1
    assert SUBPROCESS_POLL_DELAY_SECONDS == 0.025


def test_parallelism_config():
    assert SECONDS_TO_WAIT_WHEN_POLLING_QUEUES == 0.02


def test_data_stream_values():
    assert NUM_INITIAL_PACKETS_TO_DROP == 2


def test_serial_comm():
    assert STM_VID == 1155
    assert SERIAL_COMM_BAUD_RATE == int(5e6)

    assert MAX_MC_REBOOT_DURATION_SECONDS == 10
    assert MAX_MAIN_FIRMWARE_UPDATE_DURATION_SECONDS == 60
    assert MAX_CHANNEL_FIRMWARE_UPDATE_DURATION_SECONDS == 600

    assert SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES == 3

    assert SERIAL_COMM_TIMESTAMP_EPOCH == datetime.datetime(
        year=2021, month=1, day=1, tzinfo=datetime.timezone.utc
    )

    assert SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS == 5
    assert SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS == 5
    assert SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS == 8
    assert SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS == 10
    assert SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS == 10
    assert SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS == 10

    assert SERIAL_COMM_MAGIC_WORD_BYTES == b"CURI BIO"
    assert SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES == 2
    assert SERIAL_COMM_TIMESTAMP_LENGTH_BYTES == 8
    assert SERIAL_COMM_PACKET_TYPE_LENGTH_BYTES == 1
    assert SERIAL_COMM_CHECKSUM_LENGTH_BYTES == 4

    assert SERIAL_COMM_TIME_INDEX_LENGTH_BYTES == 8
    assert SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES == 2
    assert SERIAL_COMM_DATA_SAMPLE_LENGTH_BYTES == 2

    assert SERIAL_COMM_PACKET_HEADER_LENGTH_BYTES == (
        len(SERIAL_COMM_MAGIC_WORD_BYTES) + SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
    )
    assert SERIAL_COMM_PACKET_BASE_LENGTH_BYTES == (
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + SERIAL_COMM_PACKET_TYPE_LENGTH_BYTES
    )
    assert SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES == (
        SERIAL_COMM_PACKET_HEADER_LENGTH_BYTES
        + SERIAL_COMM_PACKET_BASE_LENGTH_BYTES
        + SERIAL_COMM_CHECKSUM_LENGTH_BYTES
    )

    assert SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES == 20000 - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
    assert SERIAL_COMM_MAX_FULL_PACKET_LENGTH_BYTES == (
        SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES + SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES
    )

    assert SERIAL_COMM_STATUS_CODE_LENGTH_BYTES == 4
    assert SERIAL_COMM_MAX_TIMESTAMP_VALUE == 2 ** (8 * SERIAL_COMM_TIMESTAMP_LENGTH_BYTES) - 1

    assert (
        SERIAL_COMM_TIMESTAMP_BYTES_INDEX
        == len(SERIAL_COMM_MAGIC_WORD_BYTES) + SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
    )
    assert (
        SERIAL_COMM_PACKET_TYPE_INDEX
        == SERIAL_COMM_TIMESTAMP_BYTES_INDEX + SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
    )
    assert SERIAL_COMM_PAYLOAD_INDEX == SERIAL_COMM_PACKET_TYPE_INDEX + 1

    assert SERIAL_COMM_STATUS_BEACON_PACKET_TYPE == 0
    assert SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE == 1
    assert SERIAL_COMM_REBOOT_PACKET_TYPE == 2
    assert SERIAL_COMM_HANDSHAKE_PACKET_TYPE == 4
    assert SERIAL_COMM_PLATE_EVENT_PACKET_TYPE == 6
    assert SERIAL_COMM_GOING_DORMANT_PACKET_TYPE == 10
    assert SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE == 20
    assert SERIAL_COMM_START_STIM_PACKET_TYPE == 21
    assert SERIAL_COMM_STOP_STIM_PACKET_TYPE == 22
    assert SERIAL_COMM_STIM_STATUS_PACKET_TYPE == 23
    assert SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE == 27
    assert SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE == 50
    assert SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE == 52
    assert SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE == 53
    assert SERIAL_COMM_GET_METADATA_PACKET_TYPE == 60
    assert SERIAL_COMM_SET_NICKNAME_PACKET_TYPE == 62
    assert SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE == 70
    assert SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE == 71
    assert SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE == 72
    assert SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE == 73
    assert SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE == 74
    assert SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE == 90
    assert SERIAL_COMM_ERROR_ACK_PACKET_TYPE == 254
    assert SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE == 255

    assert SERIAL_COMM_COMMAND_SUCCESS_BYTE == 0
    assert SERIAL_COMM_COMMAND_FAILURE_BYTE == 1

    assert SERIAL_COMM_METADATA_BYTES_LENGTH == 64
    assert SERIAL_COMM_NICKNAME_BYTES_LENGTH == 13
    assert SERIAL_COMM_SERIAL_NUMBER_BYTES_LENGTH == 12

    assert SERIAL_COMM_OKAY_CODE == 0

    assert SERIAL_COMM_NUM_DATA_CHANNELS == 9
    assert SERIAL_COMM_NUM_CHANNELS_PER_SENSOR == 3
    assert SERIAL_COMM_NUM_SENSORS_PER_WELL == 3
    assert (
        SERIAL_COMM_NUM_DATA_CHANNELS
        == SERIAL_COMM_NUM_CHANNELS_PER_SENSOR * SERIAL_COMM_NUM_SENSORS_PER_WELL
    )

    assert SERIAL_COMM_DEFAULT_DATA_CHANNEL == SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]
    assert DEFAULT_SAMPLING_PERIOD == 10000

    assert STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS == int(100e3)
    assert STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS == int(1.2e3)
    assert STIM_MAX_PULSE_DURATION_MICROSECONDS == int(50e3)

    assert STIM_COMPLETE_SUBPROTOCOL_IDX == 255

    assert STIM_NO_PROTOCOL_ASSIGNED == 255

    assert STIM_OPEN_CIRCUIT_THRESHOLD_OHMS == 20000
    assert STIM_SHORT_CIRCUIT_THRESHOLD_OHMS == 10

    assert issubclass(StimulatorCircuitStatuses, Enum) is True
    assert StimulatorCircuitStatuses.CALCULATING.value == "calculating"
    assert StimulatorCircuitStatuses.OPEN.value == "open"
    assert StimulatorCircuitStatuses.SHORT.value == "short"
    assert StimulatorCircuitStatuses.MEDIA.value == "media"

    assert issubclass(StimProtocolStatuses, IntEnum) is True
    assert StimProtocolStatuses.ACTIVE == 0
    assert StimProtocolStatuses.NULL == 1
    assert StimProtocolStatuses.RESTARTING == 2
    assert StimProtocolStatuses.FINISHED == 3
    assert StimProtocolStatuses.ERROR == 4


def test_cython_constants():
    assert SERIAL_COMM_MAGIC_WORD_LENGTH_BYTES_CY == len(SERIAL_COMM_MAGIC_WORD_BYTES)
    assert SERIAL_COMM_NUM_CHANNELS_PER_SENSOR_CY == SERIAL_COMM_NUM_CHANNELS_PER_SENSOR


def test_beta_2_mappings():
    assert SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE == {
        "A": {"X": 0, "Y": 1, "Z": 2},
        "B": {"X": 3, "Y": 4, "Z": 5},
        "C": {"X": 6, "Y": 7, "Z": 8},
    }
    assert SERIAL_COMM_WELL_IDX_TO_MODULE_ID == {
        well_idx: module_id for module_id, well_idx in SERIAL_COMM_MODULE_ID_TO_WELL_IDX.items()
    }
    assert SERIAL_COMM_MODULE_ID_TO_WELL_IDX == {module_id: module_id - 1 for module_id in range(1, 25)}
    for well_idx in range(24):
        module_id = SERIAL_COMM_WELL_IDX_TO_MODULE_ID[well_idx]
        well_idx_from_module_id = SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id]
        assert well_idx_from_module_id == well_idx


def test_calibration_constants():
    assert CALIBRATION_RECORDING_DUR_SECONDS == 30
