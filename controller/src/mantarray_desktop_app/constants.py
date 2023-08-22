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
from typing import FrozenSet
from typing import Tuple
import uuid

from immutabledict import immutabledict
from labware_domain_models import LabwareDefinition
import numpy as np
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN

CURRENT_SOFTWARE_VERSION = "REPLACETHISWITHVERSIONDURINGBUILD"
COMPILED_EXE_BUILD_TIMESTAMP = "REPLACETHISWITHTIMESTAMPDURINGBUILD"
SOFTWARE_RELEASE_CHANNEL = "REPLACETHISWITHRELEASECHANNELDURINGBUILD"

# Cloud APIs
CLOUD_ENDPOINT_USER_OPTION = "REPLACETHISWITHENDPOINTDURINGBUILD"
CLOUD_ENDPOINT_VALID_OPTIONS: immutabledict[str, str] = immutabledict(
    {"test": "curibio-test", "prod": "curibio"}
)
CLOUD_DOMAIN = CLOUD_ENDPOINT_VALID_OPTIONS.get(CLOUD_ENDPOINT_USER_OPTION, "curibio-test")
CLOUD_API_ENDPOINT = f"apiv2.{CLOUD_DOMAIN}.com"
CLOUD_PULSE3D_ENDPOINT = f"pulse3d.{CLOUD_DOMAIN}.com"

# File Versions
CURRENT_BETA1_HDF5_FILE_FORMAT_VERSION = "0.4.2"
CURRENT_BETA2_HDF5_FILE_FORMAT_VERSION = "1.4.0"

# General
DEFAULT_SERVER_PORT_NUMBER = 4567

MAX_POSSIBLE_CONNECTED_BOARDS = 4

GENERIC_24_WELL_DEFINITION = LabwareDefinition(row_count=4, column_count=6)

DEFAULT_USER_CONFIG: immutabledict[str, str] = immutabledict({"customer_id": "", "user_name": ""})
VALID_CONFIG_SETTINGS = frozenset(
    [
        "customer_id",
        "user_name",
        "user_password",
        "recording_directory",
        "auto_upload",
        "auto_delete",
        "pulse3d_version",
    ]
)

BARCODE_HEADERS: immutabledict[str, str] = immutabledict({"plate_barcode": "ML", "stim_barcode": "MS"})
ALL_VALID_BARCODE_HEADERS = frozenset(BARCODE_HEADERS.values())

MICROSECONDS_PER_CENTIMILLISECOND = 10

MICROS_PER_MILLI = int(1e3)
MICRO_TO_BASE_CONVERSION = int(1e6)


# Beta 1 values
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

BARCODE_LEN = 12
CLEARED_BARCODE_VALUE = chr(0) * BARCODE_LEN
NO_PLATE_DETECTED_BARCODE_VALUE = chr(21) * BARCODE_LEN

BARCODE_VALID_UUID = uuid.UUID("22d5054a-ede2-4e94-8f74-f4ebaafde247")
BARCODE_INVALID_UUID = uuid.UUID("cec87db3-3181-4b84-8d5e-1643cd00b567")
NO_PLATE_DETECTED_UUID = uuid.UUID("e86ca1d0-2350-4e1b-ad6a-5c78a6c2ed7a")
BARCODE_UNREADABLE_UUID = uuid.UUID("87525976-4c98-4783-a6f2-ae34a89dace6")

DATA_FRAME_PERIOD = 20  # in centimilliseconds
ROUND_ROBIN_PERIOD = DATA_FRAME_PERIOD * DATA_FRAMES_PER_ROUND_ROBIN
TIMESTEP_CONVERSION_FACTOR = 5  # Mantarray Beta 1.7 firmware represents time indices in units of 5 cms, so we must multiply sample indices from hardware by this conversion factor to get value in cms

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

RAW_TO_SIGNED_CONVERSION_VALUE = 2**23  # subtract this value from raw hardware data
MILLIVOLTS_PER_VOLT = 1000

MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS = 10
DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS = (
    MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS * CENTIMILLISECONDS_PER_SECOND
)
DATA_ANALYZER_BETA_1_BUFFER_SIZE = DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS // ROUND_ROBIN_PERIOD
OUTGOING_DATA_BUFFER_SIZE = 2
FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS = 30 * CENTIMILLISECONDS_PER_SECOND
FILE_WRITER_BUFFER_SIZE_MICROSECONDS = 30 * MICRO_TO_BASE_CONVERSION

PERFOMANCE_LOGGING_PERIOD_SECS = 20
OK_COMM_PERFOMANCE_LOGGING_NUM_CYCLES = 20

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
REF_INDEX_TO_24_WELL_INDEX: immutabledict[int, FrozenSet[int]] = immutabledict(
    {
        0: frozenset([0, 1, 4, 5]),
        1: frozenset([8, 9, 12, 13]),
        2: frozenset([16, 17, 20, 21]),
        3: frozenset([2, 3, 6, 7]),
        4: frozenset([10, 11, 14, 15]),
        5: frozenset([18, 19, 22, 23]),
    }
)
ADC_CH_TO_24_WELL_INDEX: immutabledict[int, Dict[int, int]] = immutabledict(
    {
        0: {0: 0, 2: 1, 4: 4, 6: 5},
        1: {0: 8, 2: 9, 4: 12, 6: 13},
        2: {0: 16, 2: 17, 4: 20, 6: 21},
        3: {6: 2, 4: 3, 2: 6, 0: 7},
        4: {6: 10, 4: 11, 2: 14, 0: 15},
        5: {6: 18, 4: 19, 2: 22, 0: 23},
    }
)
ADC_CH_TO_IS_REF_SENSOR: immutabledict[int, Dict[int, bool]] = immutabledict(
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
START_MANAGED_ACQUISITION_COMMUNICATION: immutabledict[str, str] = immutabledict(
    {"communication_type": "acquisition_manager", "command": "start_managed_acquisition", "barcode": None}
)
STOP_MANAGED_ACQUISITION_COMMUNICATION: immutabledict[str, str] = immutabledict(
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

SYSTEM_STATUS_UUIDS: immutabledict[str, uuid.UUID] = immutabledict(
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


class SystemActionTransitionStates(Enum):
    STARTING = "starting"
    STOPPING = "stopping"


SUBPROCESS_JOIN_TIMEOUT_SECONDS = 3
SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS = 1
SUBPROCESS_POLL_DELAY_SECONDS = 0.025

SECONDS_TO_WAIT_WHEN_POLLING_QUEUES = 0.02  # Due to the unreliability of the :method:`.empty()` :method:`.qsize()` methods in queues, switched to a :method:`.get(timeout=)` approach for polling the queues in the subprocesses.  Eli (10/26/20): 0.01 seconds was still causing sporadic failures in Linux CI in Github, so bumped to 0.02 seconds.


# Beta 2 Values
NUM_INITIAL_PACKETS_TO_DROP = 2  # TODO remove this
NUM_INITIAL_SECONDS_TO_DROP = 3
NUM_INITIAL_MICROSECONDS_TO_PAD = 50000

# Serial Communication Values
STM_VID = 1155
CURI_VID = 1027
SERIAL_COMM_BAUD_RATE = int(5e6)

MAX_MC_REBOOT_DURATION_SECONDS = 15
MAX_MAIN_FIRMWARE_UPDATE_DURATION_SECONDS = 60
MAX_CHANNEL_FIRMWARE_UPDATE_DURATION_SECONDS = 600

SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES = 3

SERIAL_COMM_TIMESTAMP_EPOCH = datetime.datetime(year=2021, month=1, day=1, tzinfo=datetime.timezone.utc)

SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS = 5
SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS = 5
SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS = 8
# Tanner (3/22/22): The following values are probably much larger than they need to be, not sure best duration of time to use now that a command might be sent right before or during a FW reboot initiated automatically by a FW error
SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS = SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS * 2
SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS = SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS * 2
SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS = 10

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

SERIAL_COMM_STATUS_CODE_LENGTH_BYTES = 2 + 24  # main micro, idx of thread with error, 24 wells
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
SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE = 27
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
SERIAL_COMM_GET_ERROR_DETAILS_PACKET_TYPE = 253
SERIAL_COMM_ERROR_ACK_PACKET_TYPE = 254
SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE = 255

# Mantarray Status Codes
SERIAL_COMM_OKAY_CODE = 0
# Command Response Info
SERIAL_COMM_COMMAND_SUCCESS_BYTE = 0
SERIAL_COMM_COMMAND_FAILURE_BYTE = 1
# Going Dormant Codes
GOING_DORMANT_HANDSHAKE_TIMEOUT_CODE = 0

# Magnetometer configuration
SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE: immutabledict[str, Dict[str, int]] = immutabledict(
    {"A": {"X": 0, "Y": 1, "Z": 2}, "B": {"X": 3, "Y": 4, "Z": 5}, "C": {"X": 6, "Y": 7, "Z": 8}}
)
SERIAL_COMM_NUM_CHANNELS_PER_SENSOR = 3
SERIAL_COMM_NUM_SENSORS_PER_WELL = 3
SERIAL_COMM_NUM_DATA_CHANNELS = SERIAL_COMM_NUM_SENSORS_PER_WELL * SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
SERIAL_COMM_DEFAULT_DATA_CHANNEL = SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Z"]
DEFAULT_SAMPLING_PERIOD = 10000  # valid as of 4/12/22

# Stimulation
STIM_MAX_ABSOLUTE_CURRENT_MICROAMPS = int(100e3)
STIM_MAX_ABSOLUTE_VOLTAGE_MILLIVOLTS = int(1.2e3)

STIM_MAX_DUTY_CYCLE_PERCENTAGE = 0.8
STIM_MAX_DUTY_CYCLE_DURATION_MICROSECONDS = int(50e3)

STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS = int(100e3)
STIM_MAX_SUBPROTOCOL_DURATION_MICROSECONDS = 24 * 60 * 60 * MICRO_TO_BASE_CONVERSION  # 24hrs

# Protocol Chunking
STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MINS = 1
STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS = (
    STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MINS * 60 * MICRO_TO_BASE_CONVERSION
)

STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL = 50

STIM_COMPLETE_SUBPROTOCOL_IDX = 255

STIM_NO_PROTOCOL_ASSIGNED = 255

# Stimulator Impedance Thresholds
STIM_OPEN_CIRCUIT_THRESHOLD_OHMS = 20000
STIM_SHORT_CIRCUIT_THRESHOLD_OHMS = 10

# Stim Subprotocols
VALID_STIMULATION_TYPES = frozenset(["C", "V"])
VALID_SUBPROTOCOL_TYPES = frozenset(["delay", "monophasic", "biphasic", "loop"])

# does not include subprotocol idx
STIM_PULSE_BYTES_LEN = 29


# Stim Checks
class StimulatorCircuitStatuses(IntEnum):
    CALCULATING = -1
    MEDIA = 0
    OPEN = 1
    SHORT = 2
    ERROR = 3


class StimProtocolStatuses(IntEnum):
    ACTIVE = 0
    NULL = 1
    FINISHED = 2
    ERROR = 3


# Metadata
SERIAL_COMM_METADATA_BYTES_LENGTH = 128
SERIAL_COMM_NICKNAME_BYTES_LENGTH = 13
SERIAL_COMM_SERIAL_NUMBER_BYTES_LENGTH = 12


# Mappings

# fmt: off
SERIAL_COMM_WELL_IDX_TO_MODULE_ID: immutabledict[int, int] = immutabledict(
    {
        well_idx: module_id
        for well_idx, module_id in enumerate(
            [
                3, 2, 1, 0,  # A1 - D1
                7, 6, 5, 4,  # A2 - D2
                11, 10, 9, 8,  # A3 - D3
                15, 14, 13, 12,  # A4 - D4
                19, 18, 17, 16,  # A5 - D5
                23, 22, 21, 20   # A6 - D6
            ]
        )
    }
)
# fmt: on
SERIAL_COMM_MODULE_ID_TO_WELL_IDX: immutabledict[int, int] = immutabledict(
    {module_id: well_idx for well_idx, module_id in SERIAL_COMM_WELL_IDX_TO_MODULE_ID.items()}
)

# fmt: off
STIM_MODULE_ID_TO_WELL_IDX: immutabledict[int, int] = immutabledict(
    {
        module_id: well_idx
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
STIM_WELL_IDX_TO_MODULE_ID: immutabledict[int, int] = immutabledict(
    {well_idx: module_id for module_id, well_idx in STIM_MODULE_ID_TO_WELL_IDX.items()}
)


# Calibration
CALIBRATION_RECORDING_DUR_SECONDS = 30

# Live View Conversion (last updated 1/19/23)
POST_STIFFNESS_TO_MM_PER_MT_Z_AXIS_SENSOR_0 = immutabledict(
    {
        1: 8,
        # Tanner (1/19/23): using 1x stiffness value for 3x, 6x, 9x since they are currently unknown
        3: 8,
        6: 8,
        9: 8,
        12: 6.896551,
    }
)

# Recording Snapshot
RECORDING_SNAPSHOT_DUR_SECS = 5
