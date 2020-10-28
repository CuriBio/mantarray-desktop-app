# -*- coding: utf-8 -*-
import uuid

from mantarray_desktop_app import ADC_CH_TO_24_WELL_INDEX
from mantarray_desktop_app import ADC_CH_TO_IS_REF_SENSOR
from mantarray_desktop_app import ADC_GAIN
from mantarray_desktop_app import ADC_GAIN_DESCRIPTION_TAG
from mantarray_desktop_app import ADC_GAIN_SETTING_UUID
from mantarray_desktop_app import ADC_OFFSET_DESCRIPTION_TAG
from mantarray_desktop_app import ADC_REF_OFFSET_UUID
from mantarray_desktop_app import ADC_TISSUE_OFFSET_UUID
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import CHANNEL_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CONSTRUCT_SENSORS_PER_REF_SENSOR
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_HDF5_FILE_FORMAT_VERSION
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import CUSTOMER_ACCOUNT_ID_UUID
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
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MAIN_FIRMWARE_VERSION_UUID
from mantarray_desktop_app import MANTARRAY_NICKNAME_UUID
from mantarray_desktop_app import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_desktop_app import MAX_POSSIBLE_CONNECTED_BOARDS
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MIDSCALE_CODE
from mantarray_desktop_app import MILLIVOLTS_PER_VOLT
from mantarray_desktop_app import OK_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
from mantarray_desktop_app import OUTGOING_DATA_BUFFER_SIZE
from mantarray_desktop_app import PLATE_BARCODE_UUID
from mantarray_desktop_app import RAW_TO_SIGNED_CONVERSION_VALUE
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import REF_SAMPLING_PERIOD_UUID
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import REFERENCE_VOLTAGE_UUID
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_desktop_app import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import START_RECORDING_TIME_INDEX_UUID
from mantarray_desktop_app import SUBPROCESS_POLL_DELAY_SECONDS
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from mantarray_desktop_app import SYSTEM_STATUS_UUIDS
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app import TISSUE_SAMPLING_PERIOD_UUID
from mantarray_desktop_app import TOTAL_WELL_COUNT_UUID
from mantarray_desktop_app import USER_ACCOUNT_ID_UUID
from mantarray_desktop_app import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_desktop_app import UTC_BEGINNING_RECORDING_UUID
from mantarray_desktop_app import UTC_FIRST_REF_DATA_POINT_UUID
from mantarray_desktop_app import UTC_FIRST_TISSUE_DATA_POINT_UUID
from mantarray_desktop_app import VALID_CONFIG_SETTINGS
from mantarray_desktop_app import VALID_SCRIPTING_COMMANDS
from mantarray_desktop_app import WELL_24_INDEX_TO_ADC_AND_CH_INDEX
from mantarray_desktop_app import WELL_COLUMN_UUID
from mantarray_desktop_app import WELL_INDEX_UUID
from mantarray_desktop_app import WELL_NAME_UUID
from mantarray_desktop_app import WELL_ROW_UUID
from mantarray_desktop_app import XEM_SERIAL_NUMBER_UUID
import numpy as np
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN


def test_default_server_port_number():
    assert DEFAULT_SERVER_PORT_NUMBER == 4567


def test_max_boards():
    assert MAX_POSSIBLE_CONNECTED_BOARDS == 4


def test_firmware():
    assert FIRMWARE_VERSION_WIRE_OUT_ADDRESS == 0x21


def test_default_UUIDs():
    assert CURI_BIO_ACCOUNT_UUID == uuid.UUID("73f52be0-368c-42d8-a1fd-660d49ba5604")
    assert CURI_BIO_USER_ACCOUNT_ID == uuid.UUID("455b93eb-c78f-4494-9f73-d3291130f126")


def test_metadata_UUIDs():
    assert UTC_BEGINNING_DATA_ACQUISTION_UUID == uuid.UUID(
        "98c67f22-013b-421a-831b-0ea55df4651e"
    )
    assert START_RECORDING_TIME_INDEX_UUID == uuid.UUID(
        "e41422b3-c903-48fd-9856-46ff56a6534c"
    )
    assert UTC_BEGINNING_RECORDING_UUID == uuid.UUID(
        "d2449271-0e84-4b45-a28b-8deab390b7c2"
    )
    assert UTC_FIRST_TISSUE_DATA_POINT_UUID == uuid.UUID(
        "b32fb8cb-ebf8-4378-a2c0-f53a27bc77cc"
    )
    assert UTC_FIRST_REF_DATA_POINT_UUID == uuid.UUID(
        "7cc07b2b-4146-4374-b8f3-1c4d40ff0cf7"
    )
    assert CUSTOMER_ACCOUNT_ID_UUID == uuid.UUID("4927c810-fbf4-406f-a848-eba5308576e6")
    assert USER_ACCOUNT_ID_UUID == uuid.UUID("7282cf00-2b6e-4202-9d9e-db0c73c3a71f")
    assert SOFTWARE_RELEASE_VERSION_UUID == uuid.UUID(
        "432fc3c1-051b-4604-bc3d-cc0d0bd75368"
    )
    assert MAIN_FIRMWARE_VERSION_UUID == uuid.UUID(
        "faa48a0c-0155-4234-afbf-5e5dbaa59537"
    )
    assert SLEEP_FIRMWARE_VERSION_UUID == uuid.UUID(
        "3a816076-90e4-4437-9929-dc910724a49d"
    )
    assert XEM_SERIAL_NUMBER_UUID == uuid.UUID("e5f5b134-60c7-4881-a531-33aa0edba540")
    assert MANTARRAY_NICKNAME_UUID == uuid.UUID("0cdec9bb-d2b4-4c5b-9dd5-6a49766c5ed4")
    assert MANTARRAY_SERIAL_NUMBER_UUID == uuid.UUID(
        "83720d36-b941-4d85-9b39-1d817799edd6"
    )
    assert REFERENCE_VOLTAGE_UUID == uuid.UUID("0b3f3f56-0cc7-45f0-b748-9b9de480cba8")
    assert WELL_NAME_UUID == uuid.UUID("6d78f3b9-135a-4195-b014-e74dee70387b")
    assert WELL_ROW_UUID == uuid.UUID("da82fe73-16dd-456a-ac05-0b70fb7e0161")
    assert WELL_COLUMN_UUID == uuid.UUID("7af25a0a-8253-4d32-98c4-3c2ca0d83906")
    assert WELL_INDEX_UUID == uuid.UUID("cd89f639-1e36-4a13-a5ed-7fec6205f779")
    assert TOTAL_WELL_COUNT_UUID == uuid.UUID("7ca73e1c-9555-4eca-8281-3f844b5606dc")
    assert ADC_GAIN_SETTING_UUID == uuid.UUID("a3c3bb32-9b92-4da1-8ed8-6c09f9c816f8")
    assert ADC_TISSUE_OFFSET_UUID == uuid.UUID("41069860-159f-49f2-a59d-401783c1ecb4")
    assert ADC_REF_OFFSET_UUID == uuid.UUID("dc10066c-abf2-42b6-9b94-5e52d1ea9bfc")
    assert REF_SAMPLING_PERIOD_UUID == uuid.UUID("48aa034d-8775-453f-b135-75a983d6b553")
    assert TISSUE_SAMPLING_PERIOD_UUID == uuid.UUID(
        "f629083a-3724-4100-8ece-c03e637ac19c"
    )
    assert PLATE_BARCODE_UUID == uuid.UUID("cf60afef-a9f0-4bc3-89e9-c665c6bb6941")


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
    assert CURRENT_HDF5_FILE_FORMAT_VERSION == "0.3.3"


def test_COMPILED_EXE_BUILD_TIMESTAMP():
    assert COMPILED_EXE_BUILD_TIMESTAMP == "REPLACETHISWITHTIMESTAMPDURINGBUILD"


def test_CURRENT_SOFTWARE_VERSION():
    assert CURRENT_SOFTWARE_VERSION == "0.3.8"


def test_START_MANAGED_ACQUISITION_COMMUNICATION():
    assert START_MANAGED_ACQUISITION_COMMUNICATION == {
        "communication_type": "acquisition_manager",
        "command": "start_managed_acquisition",
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
    assert OK_COMM_PERFOMANCE_LOGGING_NUM_CYCLES == 20
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
