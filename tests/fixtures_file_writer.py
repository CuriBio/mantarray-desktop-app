# -*- coding: utf-8 -*-


import datetime
import hashlib
from multiprocessing import Queue
import os
import socket
import tempfile
from typing import Any
from typing import Dict
from typing import Tuple
import uuid

import h5py
from labware_domain_models import LabwareDefinition
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import CURI_BIO_ACCOUNT_UUID
from mantarray_desktop_app import CURI_BIO_USER_ACCOUNT_ID
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import FileWriterProcess
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_file_manager import ADC_GAIN_SETTING_UUID
from mantarray_file_manager import BACKEND_LOG_UUID
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import COMPUTER_NAME_HASH_UUID
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import REFERENCE_VOLTAGE_UUID
from mantarray_file_manager import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_file_manager import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
from mantarray_file_manager import USER_ACCOUNT_ID_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_BEGINNING_RECORDING_UUID
from mantarray_file_manager import WellFile
from mantarray_file_manager import XEM_SERIAL_NUMBER_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import numpy as np
import pytest

WELL_DEF_24 = LabwareDefinition(row_count=4, column_count=6)


GENERIC_ADC_OFFSET_VALUES: Dict[int, Dict[str, int]] = dict()
for well_idx in range(24):
    GENERIC_ADC_OFFSET_VALUES[well_idx] = {
        "construct": well_idx * 2,
        "ref": well_idx * 2 + 1,
    }
GENERIC_START_RECORDING_COMMAND: Dict[str, Any] = {
    "command": "start_recording",
    "timepoint_to_begin_recording_at": 298518 * 125,
    "metadata_to_copy_onto_main_file_attributes": {
        HARDWARE_TEST_RECORDING_UUID: False,
        UTC_BEGINNING_DATA_ACQUISTION_UUID: datetime.datetime(
            year=2020, month=2, day=9, hour=19, minute=3, second=22, microsecond=332597
        ),
        START_RECORDING_TIME_INDEX_UUID: 298518 * 125,
        UTC_BEGINNING_RECORDING_UUID: datetime.datetime(
            year=2020, month=2, day=9, hour=19, minute=3, second=22, microsecond=332597
        )
        + datetime.timedelta(seconds=(298518 * 125 / CENTIMILLISECONDS_PER_SECOND)),
        CUSTOMER_ACCOUNT_ID_UUID: CURI_BIO_ACCOUNT_UUID,
        USER_ACCOUNT_ID_UUID: CURI_BIO_USER_ACCOUNT_ID,
        SOFTWARE_BUILD_NUMBER_UUID: COMPILED_EXE_BUILD_TIMESTAMP,
        SOFTWARE_RELEASE_VERSION_UUID: CURRENT_SOFTWARE_VERSION,
        MAIN_FIRMWARE_VERSION_UUID: RunningFIFOSimulator.default_firmware_version,
        SLEEP_FIRMWARE_VERSION_UUID: "0.0.0",
        XEM_SERIAL_NUMBER_UUID: RunningFIFOSimulator.default_xem_serial_number,
        MANTARRAY_SERIAL_NUMBER_UUID: RunningFIFOSimulator.default_mantarray_serial_number,
        MANTARRAY_NICKNAME_UUID: RunningFIFOSimulator.default_mantarray_nickname,
        REFERENCE_VOLTAGE_UUID: REFERENCE_VOLTAGE,
        ADC_GAIN_SETTING_UUID: 32,
        "adc_offsets": GENERIC_ADC_OFFSET_VALUES,
        PLATE_BARCODE_UUID: "MA200440001",
        BACKEND_LOG_UUID: uuid.UUID("9a3d03f2-1f5a-4ecd-b843-0dc9ecde5f67"),
        COMPUTER_NAME_HASH_UUID: hashlib.sha512(
            socket.gethostname().encode(encoding="UTF-8")
        ).hexdigest(),
        BARCODE_IS_FROM_SCANNER_UUID: True,
    },
    "active_well_indices": set(range(24)),
}

GENERIC_STOP_RECORDING_COMMAND: Dict[str, Any] = {
    "communication_type": "recording",
    "command": "stop_recording",
    "timepoint_to_stop_recording_at": 302412 * 125,
}


GENERIC_NUMPY_ARRAY_FOR_TISSUE_DATA_PACKET = np.zeros((2, 50), dtype=np.int32)
for i in range(50):
    GENERIC_NUMPY_ARRAY_FOR_TISSUE_DATA_PACKET[0, i] = (
        i * CONSTRUCT_SENSOR_SAMPLING_PERIOD
    )
    GENERIC_NUMPY_ARRAY_FOR_TISSUE_DATA_PACKET[1, i] = i * 10
GENERIC_TISSUE_DATA_PACKET = {
    "well_index": 4,
    "is_reference_sensor": False,
    "data": GENERIC_NUMPY_ARRAY_FOR_TISSUE_DATA_PACKET,
}

GENERIC_NUMPY_ARRAY_FOR_REFERENCE_DATA_PACKET = np.zeros((2, 50), dtype=np.int32)
for i in range(50):
    GENERIC_NUMPY_ARRAY_FOR_REFERENCE_DATA_PACKET[0, i] = (
        i * REFERENCE_SENSOR_SAMPLING_PERIOD
    )
    GENERIC_NUMPY_ARRAY_FOR_REFERENCE_DATA_PACKET[1, i] = i * 10
GENERIC_REFERENCE_SENSOR_DATA_PACKET = {
    "reference_for_wells": set([0, 1, 4, 5]),
    "is_reference_sensor": True,
    "data": GENERIC_NUMPY_ARRAY_FOR_REFERENCE_DATA_PACKET,
}


def open_the_generic_h5_file(
    file_dir: str, well_name: str = "A2"
) -> h5py._hl.files.File:  # pylint: disable=protected-access # this is the only type definition Eli (2/24/20) could find for a File
    timestamp_str = "2020_02_09_190935"
    barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]

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
    file_dir: str, well_name: str = "A2"
) -> WellFile:
    timestamp_str = "2020_02_09_190935"
    barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]

    actual_file = WellFile(
        os.path.join(
            file_dir,
            f"{barcode}__{timestamp_str}",
            f"{barcode}__{timestamp_str}__{well_name}.h5",
        ),
    )
    return actual_file


def generate_fw_from_main_to_main_board_and_error_queues(num_boards: int = 4):
    error_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Tuple[Exception, str]
    ] = Queue()

    from_main: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ] = Queue()
    to_main: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ] = Queue()

    board_queues: Tuple[  # pylint-disable: duplicate-code
        Tuple[
            Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Any
            ],
            Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Any
            ],
        ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
    ] = tuple(((Queue(), Queue()) for _ in range(4)))
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
            board_queues, from_main, to_main, error_queue, file_directory=tmp_dir
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
def fixture_running_four_board_file_writer_process(four_board_file_writer_process):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.start()
    yield four_board_file_writer_process

    fw_process.stop()
    fw_process.join()
