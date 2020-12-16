# -*- coding: utf-8 -*-
"""Constants for the Mantarray GUI.

The following constants are based off the geometry of Mantarray Board Rev 2

* CHANNEL_INDEX_TO_24_WELL_INDEX
* REF_INDEX_TO_24_WELL_INDEX
* ADC_CH_TO_24_WELL_INDEX
* ADC_CH_TO_IS_REF_SENSOR
* WELL_24_INDEX_TO_ADC_AND_CH_INDEX
"""
from typing import Dict
from typing import Tuple
import uuid

from immutabledict import immutabledict
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import numpy as np
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN

CURRENT_SOFTWARE_VERSION = "0.4.0"

COMPILED_EXE_BUILD_TIMESTAMP = "REPLACETHISWITHTIMESTAMPDURINGBUILD"

CURRENT_HDF5_FILE_FORMAT_VERSION = "0.4.0"

DEFAULT_SERVER_PORT_NUMBER = 4567

MAX_POSSIBLE_CONNECTED_BOARDS = 4

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

# TODO (Eli 12/8/20): make all potentially mutable constants explicitly immutable (e.g. immutabledicts)

DEFAULT_USER_CONFIG = immutabledict(
    {
        "Customer Account ID": "",
        "User Account ID": "",
    }
)
VALID_CONFIG_SETTINGS = frozenset(
    ["customer_account_uuid", "user_account_uuid", "recording_directory"]
)

DATA_FRAME_PERIOD = 20  # in centimilliseconds
ROUND_ROBIN_PERIOD = DATA_FRAME_PERIOD * DATA_FRAMES_PER_ROUND_ROBIN
TIMESTEP_CONVERSION_FACTOR = 5  # Mantarray firmware represents time indices in units of 5 cms, so we must multiply sample index from hardware by this conversion factor to get value in cms

MICROSECONDS_PER_CENTIMILLISECOND = 10

FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE = 0xFFFFFFFF
FIFO_READ_PRODUCER_CYCLES_PER_ITERATION = (
    20  # how many cycles of data the fifo_read_producer generates before sleeping
)
FIFO_READ_PRODUCER_SLEEP_DURATION = (
    FIFO_READ_PRODUCER_CYCLES_PER_ITERATION * ROUND_ROBIN_PERIOD
) / CENTIMILLISECONDS_PER_SECOND
FIFO_READ_PRODUCER_SAWTOOTH_PERIOD = (
    CENTIMILLISECONDS_PER_SECOND // TIMESTEP_CONVERSION_FACTOR
) / (
    2 * np.pi
)  # in board timesteps (1/5 of a centimillisecond)
FIFO_READ_PRODUCER_DATA_OFFSET = 0x800000
FIFO_READ_PRODUCER_WELL_AMPLITUDE = 0xA8000
FIFO_READ_PRODUCER_REF_AMPLITUDE = 0x100000

MIDSCALE_CODE = 0x800000
REFERENCE_VOLTAGE = 2.5  # TODO Tanner (7/16/20): remove this once the read_wire_out value is implemented
ADC_GAIN = 2
RAW_TO_SIGNED_CONVERSION_VALUE = 2 ** 23  # subtract this value from raw hardware data
MILLIVOLTS_PER_VOLT = 1000

REFERENCE_SENSOR_SAMPLING_PERIOD = ROUND_ROBIN_PERIOD // 4
CONSTRUCT_SENSOR_SAMPLING_PERIOD = ROUND_ROBIN_PERIOD

DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS = 7 * CENTIMILLISECONDS_PER_SECOND
OUTGOING_DATA_BUFFER_SIZE = 2
FILE_WRITER_BUFFER_SIZE_CENTIMILLISECONDS = 30 * CENTIMILLISECONDS_PER_SECOND

OK_COMM_PERFOMANCE_LOGGING_NUM_CYCLES = 20
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
ADC_GAIN_DESCRIPTION_TAG = (
    "adc_gain_setting"  # specifically used for parsing gain value from xem_scripts
)
ADC_OFFSET_DESCRIPTION_TAG = (
    "adc_offset_reading"  # specifically used for parsing offset values from xem_scripts
)

CONSTRUCT_SENSORS_PER_REF_SENSOR = 4
CHANNEL_INDEX_TO_24_WELL_INDEX = {  # may be unnecessary
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
# Eli (12/10/20): having some trouble converting these to immutable dicts as Cython doesn't seem to like it. Could maybe make a mutable copy right before passing to Cython
REF_INDEX_TO_24_WELL_INDEX = {
    0: frozenset([0, 1, 4, 5]),
    1: frozenset([8, 9, 12, 13]),
    2: frozenset([16, 17, 20, 21]),
    3: frozenset([2, 3, 6, 7]),
    4: frozenset([10, 11, 14, 15]),
    5: frozenset([18, 19, 22, 23]),
}
ADC_CH_TO_24_WELL_INDEX = {
    0: {0: 0, 2: 1, 4: 4, 6: 5},
    1: {0: 8, 2: 9, 4: 12, 6: 13},
    2: {0: 16, 2: 17, 4: 20, 6: 21},
    3: {6: 2, 4: 3, 2: 6, 0: 7},
    4: {6: 10, 4: 11, 2: 14, 0: 15},
    5: {6: 18, 4: 19, 2: 22, 0: 23},
}
ADC_CH_TO_IS_REF_SENSOR = {
    0: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
    1: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
    2: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
    3: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
    4: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
    5: {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False, 7: True},
}
WELL_24_INDEX_TO_ADC_AND_CH_INDEX: Dict[int, Tuple[int, int]] = dict()
for adc_num in range(6):
    for ch_num in range(0, 8, 2):
        well_idx = ADC_CH_TO_24_WELL_INDEX[adc_num][ch_num]
        WELL_24_INDEX_TO_ADC_AND_CH_INDEX[well_idx] = (adc_num, ch_num)

# Communications from Main to Subprocesses
START_MANAGED_ACQUISITION_COMMUNICATION = immutabledict(
    {
        "communication_type": "to_instrument",
        "command": "start_managed_acquisition",
    }
)

SERVER_INITIALIZING_STATE = "server_initializing"
SERVER_READY_STATE = "server_ready"
INSTRUMENT_INITIALIZING_STATE = "instrument_initializing"
CALIBRATION_NEEDED_STATE = "calibration_needed"
CALIBRATING_STATE = "calibrating"
CALIBRATED_STATE = "calibrated"
BUFFERING_STATE = "buffering"
LIVE_VIEW_ACTIVE_STATE = "live_view_active"
RECORDING_STATE = "recording"
SYSTEM_STATUS_UUIDS = immutabledict(
    {
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
)

SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS = 1
SUBPROCESS_POLL_DELAY_SECONDS = 0.025

SECONDS_TO_WAIT_WHEN_POLLING_QUEUES = 0.02  # Due to the unreliablity of the .empty() .qsize() methods in queues, switched to a .get(timeout=) approach for polling the queues in the subprocesses.  Eli (10/26/20): 0.01 seconds was still causing sporadic failures in Linux CI in Github, so bumped to 0.02 seconds.
