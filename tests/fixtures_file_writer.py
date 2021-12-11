# -*- coding: utf-8 -*-

import copy
import datetime
import hashlib
from multiprocessing import Queue as MPQueue
import os
import socket
import tempfile
from typing import Any
from typing import Dict
from typing import Optional
import uuid

import h5py
from labware_domain_models import LabwareDefinition
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import FileWriterProcess
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERIAL_COMM_DEFAULT_DATA_CHANNEL
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_file_manager import ADC_GAIN_SETTING_UUID
from mantarray_file_manager import BACKEND_LOG_UUID
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import Beta1WellFile
from mantarray_file_manager import BOOTUP_COUNTER_UUID
from mantarray_file_manager import COMPUTER_NAME_HASH_UUID
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import MAGNETOMETER_CONFIGURATION_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import PCB_SERIAL_NUMBER_UUID
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import REFERENCE_VOLTAGE_UUID
from mantarray_file_manager import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_file_manager import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
from mantarray_file_manager import STIMULATION_PROTOCOL_UUID
from mantarray_file_manager import TAMPER_FLAG_UUID
from mantarray_file_manager import TISSUE_SAMPLING_PERIOD_UUID
from mantarray_file_manager import TOTAL_WORKING_HOURS_UUID
from mantarray_file_manager import USER_ACCOUNT_ID_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_BEGINNING_RECORDING_UUID
from mantarray_file_manager import UTC_BEGINNING_STIMULATION_UUID
from mantarray_file_manager import WellFile
from mantarray_file_manager import XEM_SERIAL_NUMBER_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import numpy as np
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import TestingQueue

from .fixtures import GENERIC_STORED_CUSTOMER_IDS
from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .fixtures_mc_simulator import get_null_subprotocol
from .fixtures_mc_simulator import get_random_subprotocol
from .helpers import confirm_queue_is_eventually_empty
from .helpers import confirm_queue_is_eventually_of_size
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

WELL_DEF_24 = LabwareDefinition(row_count=4, column_count=6)


GENERIC_ADC_OFFSET_VALUES: Dict[int, Dict[str, int]] = dict()
for this_well_idx in range(24):
    GENERIC_ADC_OFFSET_VALUES[this_well_idx] = {
        "construct": this_well_idx * 2,
        "ref": this_well_idx * 2 + 1,
    }

GENERIC_WELL_MAGNETOMETER_CONFIGURATION = {
    channel_id: channel_id
    in (SERIAL_COMM_DEFAULT_DATA_CHANNEL, SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"])
    for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS)
}
GENERIC_NUM_CHANNELS_ENABLED = sum(GENERIC_WELL_MAGNETOMETER_CONFIGURATION.values())
GENERIC_NUM_SENSORS_ENABLED = 2
GENERIC_BOARD_MAGNETOMETER_CONFIGURATION: Dict[int, Dict[int, bool]] = dict()
for module_id in range(1, 25):
    GENERIC_BOARD_MAGNETOMETER_CONFIGURATION[module_id] = copy.deepcopy(
        GENERIC_WELL_MAGNETOMETER_CONFIGURATION
    )


GENERIC_STIM_PROTOCOL_ASSIGNMENTS: Dict[str, Optional[str]] = {
    GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): None for well_idx in range(24)
}
GENERIC_STIM_PROTOCOL_ASSIGNMENTS["A1"] = "A"
GENERIC_STIM_PROTOCOL_ASSIGNMENTS["B1"] = "B"
GENERIC_STIM_INFO = {
    "protocols": [
        {
            "protocol_id": "A",
            "stimulation_type": "C",
            "run_until_stopped": True,
            "subprotocols": [get_random_subprotocol(), get_null_subprotocol(50000)],  # type: ignore
        },
        {
            "protocol_id": "B",
            "stimulation_type": "V",
            "run_until_stopped": False,
            "subprotocols": [get_random_subprotocol(), get_random_subprotocol()],  # type: ignore
        },
    ],
    "protocol_assignments": GENERIC_STIM_PROTOCOL_ASSIGNMENTS,
}

GENERIC_BASE_START_RECORDING_COMMAND: Dict[str, Any] = {
    "communication_type": "recording",
    "command": "start_recording",
    "timepoint_to_begin_recording_at": 298518 * 125,
    "is_hardware_test_recording": False,
    "metadata_to_copy_onto_main_file_attributes": {
        HARDWARE_TEST_RECORDING_UUID: False,
        UTC_BEGINNING_DATA_ACQUISTION_UUID: datetime.datetime(
            year=2020, month=2, day=9, hour=19, minute=3, second=22, microsecond=332597
        ),
        START_RECORDING_TIME_INDEX_UUID: 298518 * 125,
        CUSTOMER_ACCOUNT_ID_UUID: CURI_BIO_ACCOUNT_UUID,
        USER_ACCOUNT_ID_UUID: CURI_BIO_USER_ACCOUNT_ID,
        SOFTWARE_BUILD_NUMBER_UUID: COMPILED_EXE_BUILD_TIMESTAMP,
        SOFTWARE_RELEASE_VERSION_UUID: CURRENT_SOFTWARE_VERSION,
        PLATE_BARCODE_UUID: "MA200440001",
        BACKEND_LOG_UUID: uuid.UUID("9a3d03f2-1f5a-4ecd-b843-0dc9ecde5f67"),
        COMPUTER_NAME_HASH_UUID: hashlib.sha512(socket.gethostname().encode(encoding="UTF-8")).hexdigest(),
        BARCODE_IS_FROM_SCANNER_UUID: True,
    },
    "active_well_indices": set(range(24)),
}
GENERIC_BETA_1_START_RECORDING_COMMAND = copy.deepcopy(GENERIC_BASE_START_RECORDING_COMMAND)
GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"].update(
    {
        UTC_BEGINNING_RECORDING_UUID: GENERIC_BASE_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][UTC_BEGINNING_DATA_ACQUISTION_UUID]
        + datetime.timedelta(seconds=(298518 * 125 / CENTIMILLISECONDS_PER_SECOND)),
        MAIN_FIRMWARE_VERSION_UUID: RunningFIFOSimulator.default_firmware_version,
        SLEEP_FIRMWARE_VERSION_UUID: "0.0.0",
        MANTARRAY_SERIAL_NUMBER_UUID: RunningFIFOSimulator.default_mantarray_serial_number,
        MANTARRAY_NICKNAME_UUID: RunningFIFOSimulator.default_mantarray_nickname,
        XEM_SERIAL_NUMBER_UUID: RunningFIFOSimulator.default_xem_serial_number,
        REFERENCE_VOLTAGE_UUID: REFERENCE_VOLTAGE,
        ADC_GAIN_SETTING_UUID: 32,
        "adc_offsets": GENERIC_ADC_OFFSET_VALUES,
    }
)
GENERIC_BETA_2_START_RECORDING_COMMAND = copy.deepcopy(GENERIC_BASE_START_RECORDING_COMMAND)
GENERIC_BETA_2_START_RECORDING_COMMAND["stim_running_statuses"] = [
    bool(
        GENERIC_STIM_PROTOCOL_ASSIGNMENTS[GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)]
    )
    for well_idx in range(24)
]
GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"].update(
    {
        UTC_BEGINNING_RECORDING_UUID: GENERIC_BASE_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][UTC_BEGINNING_DATA_ACQUISTION_UUID]
        + datetime.timedelta(seconds=(298518 * 125 / MICRO_TO_BASE_CONVERSION)),
        MAIN_FIRMWARE_VERSION_UUID: MantarrayMcSimulator.default_firmware_version,
        MANTARRAY_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_mantarray_serial_number,
        MANTARRAY_NICKNAME_UUID: MantarrayMcSimulator.default_mantarray_nickname,
        BOOTUP_COUNTER_UUID: MantarrayMcSimulator.default_metadata_values[BOOTUP_COUNTER_UUID],
        TOTAL_WORKING_HOURS_UUID: MantarrayMcSimulator.default_metadata_values[TOTAL_WORKING_HOURS_UUID],
        TAMPER_FLAG_UUID: MantarrayMcSimulator.default_metadata_values[TAMPER_FLAG_UUID],
        PCB_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_pcb_serial_number,
        MAGNETOMETER_CONFIGURATION_UUID: GENERIC_BOARD_MAGNETOMETER_CONFIGURATION,
        TISSUE_SAMPLING_PERIOD_UUID: 10000,
        STIMULATION_PROTOCOL_UUID: GENERIC_STIM_INFO,
        UTC_BEGINNING_STIMULATION_UUID: GENERIC_BASE_START_RECORDING_COMMAND[
            "metadata_to_copy_onto_main_file_attributes"
        ][UTC_BEGINNING_DATA_ACQUISTION_UUID]
        + datetime.timedelta(seconds=5),
    }
)

GENERIC_STOP_RECORDING_COMMAND: Dict[str, Any] = {
    "communication_type": "recording",
    "command": "stop_recording",
    "timepoint_to_stop_recording_at": 302412 * 125,
}

GENERIC_UPDATE_CUSTOMER_SETTINGS: Dict[str, Any] = {
    "command": "update_customer_settings",
    "config_settings": {
        "customer_account_id": "test_customer_id",
        "customer_pass_key": "test_password",
        "customer_username": "test_user",
        "auto_upload_on_completion": True,
        "auto_delete_local_files": False,
    },
}

GENERIC_NUMPY_ARRAY_FOR_TISSUE_DATA_PACKET = np.zeros((2, 50), dtype=np.int32)
for i in range(50):
    GENERIC_NUMPY_ARRAY_FOR_TISSUE_DATA_PACKET[0, i] = i * CONSTRUCT_SENSOR_SAMPLING_PERIOD
    GENERIC_NUMPY_ARRAY_FOR_TISSUE_DATA_PACKET[1, i] = i * 10
GENERIC_TISSUE_DATA_PACKET = {
    "well_index": 4,
    "is_reference_sensor": False,
    "data": GENERIC_NUMPY_ARRAY_FOR_TISSUE_DATA_PACKET,
}

GENERIC_NUMPY_ARRAY_FOR_REFERENCE_DATA_PACKET = np.zeros((2, 50), dtype=np.int32)
for i in range(50):
    GENERIC_NUMPY_ARRAY_FOR_REFERENCE_DATA_PACKET[0, i] = i * REFERENCE_SENSOR_SAMPLING_PERIOD
    GENERIC_NUMPY_ARRAY_FOR_REFERENCE_DATA_PACKET[1, i] = i * 10
GENERIC_REFERENCE_SENSOR_DATA_PACKET = {
    "reference_for_wells": set([0, 1, 4, 5]),
    "is_reference_sensor": True,
    "data": GENERIC_NUMPY_ARRAY_FOR_REFERENCE_DATA_PACKET,
}


def open_the_generic_h5_file(
    file_dir: str, well_name: str = "A2", beta_version: int = 1, timestamp_str: Optional[str] = None
) -> h5py._hl.files.File:  # pylint: disable=protected-access # this is the only type definition Eli (2/24/20) could find for a File
    if timestamp_str is None:
        timestamp_str = "2020_02_09_190935" if beta_version == 1 else "2020_02_09_190359"
    barcode = GENERIC_BASE_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]

    actual_file = h5py.File(
        os.path.join(
            file_dir,
            f"{barcode}__{timestamp_str}",
            f"{barcode}__{timestamp_str}__{well_name}.h5",
        ),
        "r",
    )
    return actual_file


def open_the_generic_h5_file_as_WellFile(
    file_dir: str, well_name: str = "A2", beta_version: int = 1
) -> WellFile:
    timestamp_str = "2020_02_09_190935" if beta_version == 1 else "2020_02_09_190359"
    barcode = GENERIC_BASE_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        PLATE_BARCODE_UUID
    ]

    well_file_class = Beta1WellFile if beta_version == 1 else WellFile
    actual_file = well_file_class(
        os.path.join(
            file_dir,
            f"{barcode}__{timestamp_str}",
            f"{barcode}__{timestamp_str}__{well_name}.h5",
        ),
    )
    return actual_file


def generate_fw_from_main_to_main_board_and_error_queues(num_boards: int = 4, queue_type=TestingQueue):
    error_queue = queue_type()
    from_main = queue_type()
    to_main = queue_type()
    board_queues = tuple(((queue_type(), queue_type()) for _ in range(4)))
    return from_main, to_main, board_queues, error_queue


@pytest.fixture(scope="function", name="four_board_file_writer_process")
def fixture_four_board_file_writer_process():
    (
        from_main,
        to_main,
        board_queues,
        error_queue,
    ) = generate_fw_from_main_to_main_board_and_error_queues()
    with tempfile.TemporaryDirectory() as tmp_dir:
        fw_process = FileWriterProcess(
            board_queues,
            from_main,
            to_main,
            error_queue,
            file_directory=tmp_dir,
            stored_customer_settings={
                "stored_customer_ids": GENERIC_STORED_CUSTOMER_IDS,
                "zipped_recordings_dir": os.path.join(tmp_dir, "zipped_recordings"),
                "failed_uploads_dir": os.path.join(tmp_dir, "failed_uploads"),
            },
        )
        fw_items_dict = {
            "fw_process": fw_process,
            "board_queues": board_queues,
            "from_main_queue": from_main,
            "to_main_queue": to_main,
            "error_queue": error_queue,
            "file_dir": tmp_dir,
        }
        yield fw_items_dict

        if not fw_process.is_alive():
            # Eli (2/10/20): it is important in windows based systems to make sure to close the files before deleting them. be careful about this when running tests in a Linux development environment
            fw_process.close_all_files()


@pytest.fixture(scope="function", name="runnable_four_board_file_writer_process")
def fixture_runnable_four_board_file_writer_process():
    (
        from_main,
        to_main,
        board_queues,
        error_queue,
    ) = generate_fw_from_main_to_main_board_and_error_queues(queue_type=MPQueue)
    with tempfile.TemporaryDirectory() as tmp_dir:
        fw_process = FileWriterProcess(
            board_queues,
            from_main,
            to_main,
            error_queue,
            file_directory=tmp_dir,
            stored_customer_settings={
                "stored_customer_ids": GENERIC_STORED_CUSTOMER_IDS,
                "zipped_recordings_dir": os.path.join(tmp_dir, "zipped_recordings"),
                "failed_uploads_dir": os.path.join(tmp_dir, "failed_uploads"),
            },
        )
        fw_items_dict = {
            "fw_process": fw_process,
            "board_queues": board_queues,
            "from_main_queue": from_main,
            "to_main_queue": to_main,
            "error_queue": error_queue,
            "file_dir": tmp_dir,
        }
        yield fw_items_dict

        if not fw_process.is_alive():
            # Eli (2/10/20): it is important in windows based systems to make sure to close the files before deleting them. be careful about this when running tests in a Linux development environment
            fw_process.close_all_files()


@pytest.fixture(scope="function", name="running_four_board_file_writer_process")
def fixture_running_four_board_file_writer_process(runnable_four_board_file_writer_process):
    fw_process = runnable_four_board_file_writer_process["fw_process"]
    fw_process.start()
    yield runnable_four_board_file_writer_process

    fw_process.stop()
    fw_process.join()


def create_and_close_beta_1_h5_files(
    four_board_file_writer_process,
    update_customer_settings_command,
    num_data_points=10,
    active_well_indices=None,
):
    if not active_well_indices:
        active_well_indices = [0]
    fw_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    to_main_queue = four_board_file_writer_process["to_main_queue"]

    # store new customer settings
    this_command = copy.deepcopy(update_customer_settings_command)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # remove update settings command receipt

    # start recording
    start_command = copy.deepcopy(GENERIC_BETA_1_START_RECORDING_COMMAND)
    start_command["timepoint_to_begin_recording_at"] = 0
    start_command["active_well_indices"] = active_well_indices
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # remove start recording command receipt

    # create data
    tissue_data = np.array([np.arange(num_data_points), np.arange(num_data_points) * 2], dtype=np.int32)
    ref_data = np.array([np.arange(num_data_points), np.arange(num_data_points) * 2], dtype=np.int32)
    # load tissue data
    for well_idx in active_well_indices:
        this_tissue_data_packet = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
        this_tissue_data_packet["data"] = tissue_data
        this_tissue_data_packet["well_index"] = well_idx
        board_queues[0][0].put_nowait(this_tissue_data_packet)
    confirm_queue_is_eventually_of_size(board_queues[0][0], len(active_well_indices))
    invoke_process_run_and_check_errors(fw_process, num_iterations=len(active_well_indices))
    confirm_queue_is_eventually_empty(board_queues[0][0])
    # load ref data
    this_ref_data_packet = copy.deepcopy(GENERIC_REFERENCE_SENSOR_DATA_PACKET)
    this_ref_data_packet["data"] = ref_data
    this_ref_data_packet[
        "reference_for_wells"
    ] = set(  # Tanner (11/9/21): linking this to each active well to simplify function. This is not how real Beta 1 ref data will parsed
        active_well_indices
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(this_ref_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    # stop recording
    stop_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    stop_command["timepoint_to_stop_recording_at"] = tissue_data[0, -1]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    # confirm each finalization message and stop recording receipt are sent
    confirm_queue_is_eventually_of_size(to_main_queue, len(active_well_indices) + 1)
    finalization_messages = drain_queue(to_main_queue)[:-1]

    # drain output queue to avoid BrokenPipeErrors
    drain_queue(board_queues[0][1])

    # tests may want to make assertions on these messages, so returning them
    return finalization_messages
