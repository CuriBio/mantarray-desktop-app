# -*- coding: utf-8 -*-
"""Constants for the Mantarray GUI.

The following constants are based off the geometry of Mantarray Board Rev 2

* REF_INDEX_TO_24_WELL_INDEX
* ADC_CH_TO_24_WELL_INDEX
* ADC_CH_TO_IS_REF_SENSOR
* WELL_24_INDEX_TO_ADC_AND_CH_INDEX
"""
import datetime
from enum import Enum
from enum import IntEnum
from typing import Dict
from typing import Tuple
import uuid

from immutabledict import immutabledict
from labware_domain_models import LabwareDefinition
import numpy as np
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN

CURRENT_SOFTWARE_VERSION = "REPLACETHISWITHVERSIONDURINGBUILD"

COMPILED_EXE_BUILD_TIMESTAMP = "REPLACETHISWITHTIMESTAMPDURINGBUILD"

# Cloud API
CLOUD_API_ENDPOINT_USER_OPTION = "REPLACETHISWITHENDPOINTDURINGBUILD"
CLOUD_API_ENDPOINT_VALID_OPTIONS = immutabledict(
    {
        "test": "curibio-test",
        "modl": "curibio-modl",
        "prod": "curibio",
    }
)
CLOUD_API_ENDPOINT = (
    f"api.{CLOUD_API_ENDPOINT_VALID_OPTIONS.get(CLOUD_API_ENDPOINT_USER_OPTION, 'curibio-test')}.com"
)

CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION = "0.4.2"
CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION = "1.0.2"


DEFAULT_SERVER_PORT_NUMBER = 4567

MAX_POSSIBLE_CONNECTED_BOARDS = 4

GENERIC_24_WELL_DEFINITION = LabwareDefinition(row_count=4, column_count=6)

FIRMWARE_VERSION_WIRE_OUT_ADDRESS = 0x21
BARCODE_SCANNER_TRIGGER_IN_ADDRESS = 0x41
BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS = 0x2A
BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS = 0x2B
BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS = 0x2C

CLEAR_BARCODE_TRIG_BIT = 0x5
START_BARCODE_SCAN_TRIG_BIT = 0x6

BARCODE_POLL_PERIOD = 15
BARCODE_CONFIRM_CLEAR_WAIT_SECONDS = 0.5
BARCODE_GET_SCAN_WAIT_SECONDS = 6

CLEARED_BARCODE_VALUE = chr(0) * 12
NO_PLATE_DETECTED_BARCODE_VALUE = chr(21) * 12

BARCODE_VALID_UUID = uuid.UUID("22d5054a-ede2-4e94-8f74-f4ebaafde247")
BARCODE_INVALID_UUID = uuid.UUID("cec87db3-3181-4b84-8d5e-1643cd00b567")
NO_PLATE_DETECTED_UUID = uuid.UUID("e86ca1d0-2350-4e1b-ad6a-5c78a6c2ed7a")
BARCODE_UNREADABLE_UUID = uuid.UUID("87525976-4c98-4783-a6f2-ae34a89dace6")

CURI_BIO_ACCOUNT_UUID = uuid.UUID("73f52be0-368c-42d8-a1fd-660d49ba5604")
CURI_BIO_USER_ACCOUNT_ID = uuid.UUID("455b93eb-c78f-4494-9f73-d3291130f126")

DEFAULT_USER_CONFIG = immutabledict({"customer_account_id": "", "user_account_id": ""})
VALID_CONFIG_SETTINGS = frozenset(
    [
        "customer_account_uuid",
        "user_account_id",
        "customer_pass_key",
        "recording_directory",
        "auto_upload",
        "auto_delete",
    ]
)

DATA_FRAME_PERIOD = 20  # in centimilliseconds
ROUND_ROBIN_PERIOD = DATA_FRAME_PERIOD * DATA_FRAMES_PER_ROUND_ROBIN
TIMESTEP_CONVERSION_FACTOR = 5  # Mantarray firmware represents time indices in units of 5 cms, so we must multiply sample index from hardware by this conversion factor to get value in cms

MICROSECONDS_PER_CENTIMILLISECOND = 10
NANOSECONDS_PER_CENTIMILLISECOND = 10 ** 4
MICROSECONDS_PER_MILLISECOND = 10 ** 3

MICRO_TO_BASE_CONVERSION = int(1e6)

# Beta 1 values
MIDSCALE_CODE = 0x800000
REFERENCE_VOLTAGE = 2.5
ADC_GAIN = 2
REFERENCE_SENSOR_SAMPLING_PERIOD = ROUND_ROBIN_PERIOD // 4
CONSTRUCT_SENSOR_SAMPLING_PERIOD = ROUND_ROBIN_PERIOD

FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE = 0xFFFFFFFF

FIFO_READ_PRODUCER_SAWTOOTH_PERIOD = (CENTIMILLISECONDS_PER_SECOND // TIMESTEP_CONVERSION_FACTOR) / (
    2 * np.pi
)  # in board timesteps (1/5 of a centimillisecond)
FIFO_READ_PRODUCER_WELL_AMPLITUDE = 0x1014  # this value chosen so the force of the max well is 100 µN
FIFO_READ_PRODUCER_REF_AMPLITUDE = (
    0x100  # this value will likely never be used in analysis or demos/simulation
)
FIFO_READ_PRODUCER_DATA_OFFSET = (  # 0xB000 chosen through empirical testing
    MIDSCALE_CODE + 0xB000 + FIFO_READ_PRODUCER_WELL_AMPLITUDE * 24 // 2
)

RAW_TO_SIGNED_CONVERSION_VALUE = 2 ** 23  # subtract this value from raw hardware data
MILLIVOLTS_PER_VOLT = 1000

MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS = 10
DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS = (
    MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS * CENTIMILLISECONDS_PER_SECOND
)
DATA_ANALYZER_BETA_1_BUFFER_SIZE = DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS // ROUND_ROBIN_PERIOD
OUTGOING_DATA_BUFFER_SIZE = 2
FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS = 30 * CENTIMILLISECONDS_PER_SECOND
FILE_WRITER_BUFFER_SIZE_MICROSECONDS = 30 * MICRO_TO_BASE_CONVERSION

INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES = 20
FILE_WRITER_PERFOMANCE_LOGGING_NUM_CYCLES = int(
    20 / 0.01
)  # 20 seconds / FileWriterProcess minimum_iteration_duration_seconds

VALID_SCRIPTING_COMMANDS = frozenset(
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
ADC_GAIN_DESCRIPTION_TAG = "adc_gain_setting"  # specifically used for parsing gain value from xem_scripts
ADC_OFFSET_DESCRIPTION_TAG = (
    "adc_offset_reading"  # specifically used for parsing offset values from xem_scripts
)

CONSTRUCT_SENSORS_PER_REF_SENSOR = 4
REF_INDEX_TO_24_WELL_INDEX = immutabledict(
    {
        0: frozenset([0, 1, 4, 5]),
        1: frozenset([8, 9, 12, 13]),
        2: frozenset([16, 17, 20, 21]),
        3: frozenset([2, 3, 6, 7]),
        4: frozenset([10, 11, 14, 15]),
        5: frozenset([18, 19, 22, 23]),
    }
)
ADC_CH_TO_24_WELL_INDEX = immutabledict(
    {
        0: {0: 0, 2: 1, 4: 4, 6: 5},
        1: {0: 8, 2: 9, 4: 12, 6: 13},
        2: {0: 16, 2: 17, 4: 20, 6: 21},
        3: {6: 2, 4: 3, 2: 6, 0: 7},
        4: {6: 10, 4: 11, 2: 14, 0: 15},
        5: {6: 18, 4: 19, 2: 22, 0: 23},
    }
)
ADC_CH_TO_IS_REF_SENSOR = immutabledict(
    {
        0: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        1: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        2: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        3: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        4: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
        5: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
    }
)
WELL_24_INDEX_TO_ADC_AND_CH_INDEX: Dict[int, Tuple[int, int]] = dict()
for adc_num in range(6):
    for ch_num in range(0, 8, 2):
        well_idx = ADC_CH_TO_24_WELL_INDEX[adc_num][ch_num]
        WELL_24_INDEX_TO_ADC_AND_CH_INDEX[well_idx] = (adc_num, ch_num)

# Communications from Main to Subprocesses
START_MANAGED_ACQUISITION_COMMUNICATION = immutabledict(
    {"communication_type": "acquisition_manager", "command": "start_managed_acquisition"}
)
STOP_MANAGED_ACQUISITION_COMMUNICATION = immutabledict(
    {"communication_type": "acquisition_manager", "command": "stop_managed_acquisition"}
)

# boot up states
SERVER_INITIALIZING_STATE = "server_initializing"
SERVER_READY_STATE = "server_ready"
INSTRUMENT_INITIALIZING_STATE = "instrument_initializing"
CHECKING_FOR_UPDATES_STATE = "checking_for_updates"
# normal operation states
CALIBRATION_NEEDED_STATE = "calibration_needed"
CALIBRATING_STATE = "calibrating"
CALIBRATED_STATE = "calibrated"
BUFFERING_STATE = "buffering"
LIVE_VIEW_ACTIVE_STATE = "live_view_active"
RECORDING_STATE = "recording"
# updating states
UPDATES_NEEDED_STATE = "updates_needed"
DOWNLOADING_UPDATES_STATE = "downloading_updates"
INSTALLING_UPDATES_STATE = "installing_updates"
UPDATES_COMPLETE_STATE = "updates_complete"
UPDATE_ERROR_STATE = "update_error"

SYSTEM_STATUS_UUIDS = immutabledict(
    {
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
)

SUBPROCESS_JOIN_TIMEOUT_SECONDS = 3
SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS = 1
SUBPROCESS_POLL_DELAY_SECONDS = 0.025

SECONDS_TO_WAIT_WHEN_POLLING_QUEUES = 0.02  # Due to the unreliability of the :method:`.empty()` :method:`.qsize()` methods in queues, switched to a :method:`.get(timeout=)` approach for polling the queues in the subprocesses.  Eli (10/26/20): 0.01 seconds was still causing sporadic failures in Linux CI in Github, so bumped to 0.02 seconds.


# Beta 2 Values
NUM_INITIAL_PACKETS_TO_DROP = 2

# Serial Communication Values
STM_VID = 1155
SERIAL_COMM_BAUD_RATE = int(5e6)

MAX_MC_REBOOT_DURATION_SECONDS = 10
MAX_MAIN_FIRMWARE_UPDATE_DURATION_SECONDS = 60
MAX_CHANNEL_FIRMWARE_UPDATE_DURATION_SECONDS = 600

SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES = 3

SERIAL_COMM_TIMESTAMP_EPOCH = datetime.datetime(year=2021, month=1, day=1, tzinfo=datetime.timezone.utc)

SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS = 5
SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS = 5
SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS = 8
# Tanner (3/22/22): The following values are probably much larger than they need to be, not sure best duration of time to use now that a command might be sent right before or during a FW reboot initiated automatically by a FW error
SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS = 10
SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS = 10
SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS = 10

# general packet components
SERIAL_COMM_MAGIC_WORD_BYTES = b"CURI BIO"
SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES = 2
SERIAL_COMM_TIMESTAMP_LENGTH_BYTES = 8
SERIAL_COMM_PACKET_TYPE_LENGTH_BYTES = 1
SERIAL_COMM_CHECKSUM_LENGTH_BYTES = 4


SERIAL_COMM_PACKET_HEADER_LENGTH_BYTES = (
    len(SERIAL_COMM_MAGIC_WORD_BYTES) + SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
)
SERIAL_COMM_PACKET_BASE_LENGTH_BYTES = (
    SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + SERIAL_COMM_PACKET_TYPE_LENGTH_BYTES
)
SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES = (
    SERIAL_COMM_PACKET_HEADER_LENGTH_BYTES
    + SERIAL_COMM_PACKET_BASE_LENGTH_BYTES
    + SERIAL_COMM_CHECKSUM_LENGTH_BYTES
)

SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES = 20000 - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
SERIAL_COMM_MAX_FULL_PACKET_LENGTH_BYTES = (
    SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES + SERIAL_COMM_MAX_PAYLOAD_LENGTH_BYTES
)

SERIAL_COMM_STATUS_CODE_LENGTH_BYTES = 4
# data stream components
SERIAL_COMM_TIME_INDEX_LENGTH_BYTES = 8
SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES = 2
SERIAL_COMM_DATA_SAMPLE_LENGTH_BYTES = 2

SERIAL_COMM_MAX_TIMESTAMP_VALUE = 2 ** (8 * SERIAL_COMM_TIMESTAMP_LENGTH_BYTES) - 1

SERIAL_COMM_TIMESTAMP_BYTES_INDEX = (
    len(SERIAL_COMM_MAGIC_WORD_BYTES) + SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
)
SERIAL_COMM_PACKET_TYPE_INDEX = SERIAL_COMM_TIMESTAMP_BYTES_INDEX + SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
SERIAL_COMM_PAYLOAD_INDEX = SERIAL_COMM_PACKET_TYPE_INDEX + 1

# Packet Types
# General
SERIAL_COMM_STATUS_BEACON_PACKET_TYPE = 0
SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE = 1
SERIAL_COMM_REBOOT_PACKET_TYPE = 2
SERIAL_COMM_HANDSHAKE_PACKET_TYPE = 4
SERIAL_COMM_PLATE_EVENT_PACKET_TYPE = 6
SERIAL_COMM_GOING_DORMANT_PACKET_TYPE = 10
# Stimulation
SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE = 20
SERIAL_COMM_START_STIM_PACKET_TYPE = 21
SERIAL_COMM_STOP_STIM_PACKET_TYPE = 22
SERIAL_COMM_STIM_STATUS_PACKET_TYPE = 23
# Magnetometer
SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE = 50
SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE = 52
SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE = 53
# Metadata
SERIAL_COMM_GET_METADATA_PACKET_TYPE = 60
SERIAL_COMM_SET_NICKNAME_PACKET_TYPE = 62
# Firmware Updating
SERIAL_COMM_BEGIN_FIRMWARE_UPDATE_PACKET_TYPE = 70
SERIAL_COMM_FIRMWARE_UPDATE_PACKET_TYPE = 71
SERIAL_COMM_END_FIRMWARE_UPDATE_PACKET_TYPE = 72
SERIAL_COMM_CF_UPDATE_COMPLETE_PACKET_TYPE = 73
SERIAL_COMM_MF_UPDATE_COMPLETE_PACKET_TYPE = 74
# Barcode
SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE = 90
# Errors
SERIAL_COMM_ERROR_PING_PONG_PACKET_TYPE = 254
SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE = 255

# Mantarray Status Codes
SERIAL_COMM_OKAY_CODE = 0
# Command Response Info
SERIAL_COMM_COMMAND_SUCCESS_BYTE = 0
SERIAL_COMM_COMMAND_FAILURE_BYTE = 1
# Going Dormant Codes
GOING_DORMANT_HANDSHAKE_TIMEOUT_CODE = 0

# Magnetometer configuration
SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE = immutabledict(
    {
        "A": {"X": 0, "Y": 1, "Z": 2},
        "B": {"X": 3, "Y": 4, "Z": 5},
        "C": {"X": 6, "Y": 7, "Z": 8},
    }
)
SERIAL_COMM_NUM_CHANNELS_PER_SENSOR = 3
SERIAL_COMM_NUM_SENSORS_PER_WELL = 3
SERIAL_COMM_NUM_DATA_CHANNELS = SERIAL_COMM_NUM_SENSORS_PER_WELL * SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
SERIAL_COMM_DEFAULT_DATA_CHANNEL = SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]
# default config values as of 3/7/22
DEFAULT_SAMPLING_PERIOD = 10000

# Stimulation
STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS = int(100e3)
STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS = int(1.2e3)
STIM_MAX_PULSE_DURATION_MICROSECONDS = int(50e3)
STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL = 50
STIM_COMPLETE_SUBPROTOCOL_IDX = 255
STIM_NO_PROTOCOL_ASSIGNED = 255


class StimulatorCircuitStatuses(Enum):
    OPEN = "open"
    CLOSED = "closed"
    MEDIA = "media"


class StimProtocolStatuses(IntEnum):
    ACTIVE = 0
    NULL = 1
    RESTARTING = 2
    FINISHED = 3
    ERROR = 4


# Metadata
SERIAL_COMM_METADATA_BYTES_LENGTH = 64
SERIAL_COMM_NICKNAME_BYTES_LENGTH = 13
SERIAL_COMM_SERIAL_NUMBER_BYTES_LENGTH = 12

# Mappings
SERIAL_COMM_WELL_IDX_TO_MODULE_ID = immutabledict({well_idx: well_idx + 1 for well_idx in range(24)})
SERIAL_COMM_MODULE_ID_TO_WELL_IDX = immutabledict(
    {module_id: well_idx for well_idx, module_id in SERIAL_COMM_WELL_IDX_TO_MODULE_ID.items()}
)

# Tanner (12/28/21): The following two mappings are only needed due to a hardware issue with the Beta 2.2. They can eventually be removed in a future hardware iteration
# fmt: off
STIM_MODULE_ID_TO_WELL_IDX = immutabledict(
    {
        module_id + 1: well_idx
        for module_id, well_idx in enumerate(
            [
                3, 7, 11, 15, 19, 23,  # D wells
                2, 6, 10, 14, 18, 22,  # C wells
                1, 5, 9, 13, 17, 21,   # B wells
                0, 4, 8, 12, 16, 20    # A wells
            ]
        )
    }
)
# fmt: on
STIM_WELL_IDX_TO_MODULE_ID = immutabledict(
    {module_id: well_idx for well_idx, module_id in STIM_MODULE_ID_TO_WELL_IDX.items()}
)


# Calibration
CALIBRATION_RECORDING_DUR_SECONDS = 30
