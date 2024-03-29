# -*- coding: utf-8 -*-
from collections import defaultdict
import json
import urllib

from mantarray_desktop_app import clear_the_server_manager
from mantarray_desktop_app import flask_app
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import ServerManager
from pulse3D.constants import BACKEND_LOG_UUID
from pulse3D.constants import COMPUTER_NAME_HASH_UUID
from pulse3D.constants import PLATE_BARCODE_UUID
from pulse3D.constants import STIM_BARCODE_UUID
from pulse3D.constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
import pytest
import socketio as python_socketio
from stdlib_utils import confirm_port_in_use

from .fixtures import fixture_generic_queue_container
from .fixtures import fixture_patch_print
from .fixtures_file_writer import GENERIC_BETA_1_START_RECORDING_COMMAND
from .fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from .fixtures_file_writer import TEST_CUSTOMER_ID
from .fixtures_file_writer import TEST_USER_NAME
from .fixtures_process_monitor import fixture_test_monitor

__fixtures__ = [
    fixture_patch_print,
    fixture_generic_queue_container,
    fixture_test_monitor,
]


def convert_formatted_platemap_to_query_param(formatted_platemap_info):
    platemap = {"map_name": formatted_platemap_info["name"]}

    intermediate_labels = defaultdict(list)
    for well_idx, label_name in enumerate(formatted_platemap_info["labels"]):
        intermediate_labels[label_name].append(well_idx)

    platemap["labels"] = [
        {"name": label_name, "wells": wells} for label_name, wells in intermediate_labels.items()
    ]

    return urllib.parse.quote_plus(json.dumps(platemap))


@pytest.fixture(scope="function", name="server_manager")
def fixture_server_manager(generic_queue_container):
    # Tanner (8/10/21): it is the responsibility of tests using this fixture to drain the queues used
    to_main_queue = generic_queue_container.from_flask

    sm = ServerManager(to_main_queue, generic_queue_container)
    shared_values_dict = sm._values_from_process_monitor
    # Tanner (4/23/21): Many routes require these values to be in the shared values dictionary. They are normally set during app start up, so manually setting here
    shared_values_dict["system_status"] = SERVER_READY_STATE
    shared_values_dict["log_file_id"] = "log-ID"
    shared_values_dict["beta_2_mode"] = False
    shared_values_dict["config_settings"] = dict()

    yield sm, to_main_queue

    clear_the_server_manager()


@pytest.fixture(scope="function", name="test_client")
def fixture_test_client():
    """Create a test client to call Flask routes.

    Modeled on https://www.patricksoftwareblog.com/testing-a-flask-application-using-pytest/
    """
    testing_client = flask_app.test_client()

    # Establish an application context before running the tests.
    ctx = flask_app.app_context()
    ctx.push()
    yield testing_client

    ctx.pop()


@pytest.fixture(scope="function", name="client_and_server_manager_and_shared_values")
def fixture_client_and_server_manager_and_shared_values(server_manager, test_client):
    sm, _ = server_manager
    shared_values_dict = sm._values_from_process_monitor
    yield test_client, server_manager, shared_values_dict


def put_generic_beta_1_start_recording_info_in_dict(shared_values_dict):
    shared_values_dict["system_status"] = SERVER_READY_STATE
    shared_values_dict["beta_2_mode"] = False

    board_idx = 0
    timestamp = GENERIC_BETA_1_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ]
    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [timestamp]
    shared_values_dict["config_settings"] = {"customer_id": TEST_CUSTOMER_ID, "user_name": TEST_USER_NAME}
    shared_values_dict["adc_gain"] = 32
    shared_values_dict["adc_offsets"] = dict()
    for well_idx in range(24):
        shared_values_dict["adc_offsets"][well_idx] = {
            "construct": well_idx * 2,
            "ref": well_idx * 2 + 1,
        }
    shared_values_dict["main_firmware_version"] = {board_idx: RunningFIFOSimulator.default_firmware_version}
    shared_values_dict["sleep_firmware_version"] = {board_idx: 2.0}
    shared_values_dict["xem_serial_number"] = {board_idx: RunningFIFOSimulator.default_xem_serial_number}
    shared_values_dict["mantarray_serial_number"] = {
        board_idx: RunningFIFOSimulator.default_mantarray_serial_number
    }
    shared_values_dict["mantarray_nickname"] = {board_idx: RunningFIFOSimulator.default_mantarray_nickname}
    shared_values_dict["log_file_id"] = GENERIC_BETA_1_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][BACKEND_LOG_UUID]
    shared_values_dict["computer_name_hash"] = GENERIC_BETA_1_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][COMPUTER_NAME_HASH_UUID]
    shared_values_dict["barcodes"] = {
        board_idx: {
            "plate_barcode": GENERIC_BETA_1_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ][PLATE_BARCODE_UUID]
        }
    }


def put_generic_beta_2_start_recording_info_in_dict(shared_values_dict):
    shared_values_dict["system_status"] = SERVER_READY_STATE
    shared_values_dict["beta_2_mode"] = True

    board_idx = 0
    num_wells = 24

    timestamp = GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ]
    shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"] = [timestamp]
    shared_values_dict["config_settings"] = {"customer_id": TEST_CUSTOMER_ID, "user_name": TEST_USER_NAME}
    shared_values_dict["main_firmware_version"] = {
        board_idx: MantarrayMcSimulator.default_main_firmware_version
    }
    shared_values_dict["mantarray_serial_number"] = {
        board_idx: MantarrayMcSimulator.default_mantarray_serial_number
    }
    shared_values_dict["mantarray_nickname"] = {board_idx: MantarrayMcSimulator.default_mantarray_nickname}
    shared_values_dict["log_file_id"] = GENERIC_BETA_2_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][BACKEND_LOG_UUID]
    shared_values_dict["computer_name_hash"] = GENERIC_BETA_2_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][COMPUTER_NAME_HASH_UUID]
    shared_values_dict["barcodes"] = {
        board_idx: {
            "plate_barcode": GENERIC_BETA_2_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ][PLATE_BARCODE_UUID],
            "stim_barcode": GENERIC_BETA_2_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ][STIM_BARCODE_UUID],
        }
    }
    shared_values_dict["instrument_metadata"] = {board_idx: MantarrayMcSimulator.default_metadata_values}

    shared_values_dict["stimulation_running"] = [False] * num_wells
    shared_values_dict["stimulation_info"] = None
    shared_values_dict["stimulator_circuit_statuses"] = {}


@pytest.fixture(scope="function", name="test_socketio_client")
def fixture_test_socketio_client():
    msg_list_container = {key: list() for key in ("waveform_data", "twitch_metrics", "stimulation_data")}

    sio = python_socketio.Client()

    @sio.on("waveform_data")
    def waveform_data_handler(data):
        msg_list_container["waveform_data"].append(data)

    @sio.on("twitch_metrics")
    def twitch_metrics_handler(data):
        msg_list_container["twitch_metrics"].append(data)

    @sio.on("stimulation_data")
    def stimulation_handler(data):
        msg_list_container["stimulation_data"].append(data)

    def _connect_client_to_ws_server():
        confirm_port_in_use(get_server_port_number(), timeout=4)  # wait for server to boot up
        sio.connect(get_api_endpoint(), wait_timeout=10)
        return sio, msg_list_container

    yield _connect_client_to_ws_server

    if sio.connected:
        sio.disconnect()
