# -*- coding: utf-8 -*-
import datetime
from multiprocessing import Queue
import tempfile

from freezegun import freeze_time
from mantarray_desktop_app import ADC_GAIN_SETTING_UUID
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_desktop_app import main
from mantarray_desktop_app import MAIN_FIRMWARE_VERSION_UUID
from mantarray_desktop_app import MANTARRAY_NICKNAME_UUID
from mantarray_desktop_app import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_desktop_app import PLATE_BARCODE_UUID
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import REFERENCE_VOLTAGE_UUID
from mantarray_desktop_app import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_desktop_app import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_desktop_app import START_RECORDING_TIME_INDEX_UUID
from mantarray_desktop_app import USER_ACCOUNT_ID_UUID
from mantarray_desktop_app import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_desktop_app import UTC_BEGINNING_RECORDING_UUID
from mantarray_desktop_app import XEM_SERIAL_NUMBER_UUID
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import PIPE_OUT_FIFO

from .fixtures import fixture_fully_running_app_from_main_entrypoint
from .fixtures import fixture_patched_shared_values_dict
from .fixtures import fixture_patched_start_recording_shared_dict
from .fixtures import fixture_test_client
from .fixtures import fixture_test_process_manager
from .fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from .helpers import is_queue_eventually_not_empty


__fixtures__ = [
    fixture_test_process_manager,
    fixture_patched_shared_values_dict,
    fixture_patched_start_recording_shared_dict,
    fixture_fully_running_app_from_main_entrypoint,
    fixture_test_client,
]


@freeze_time(
    datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598
    )
    + datetime.timedelta(
        seconds=GENERIC_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_start_recording_command__populates_queue__with_defaults__24_wells__utcnow_recording_start_time__and_metadata(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_acquisition_timestamp = datetime.datetime(  # pylint: disable=duplicate-code
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598
    )
    expected_recording_timepoint = GENERIC_START_RECORDING_COMMAND[
        "timepoint_to_begin_recording_at"
    ]
    expected_recording_timestamp = expected_acquisition_timestamp + datetime.timedelta(
        seconds=(expected_recording_timepoint / CENTIMILLISECONDS_PER_SECOND)
    )

    patched_start_recording_shared_dict[
        "utc_timestamps_of_beginning_of_data_acquisition"
    ] = [expected_acquisition_timestamp]

    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["command"] == "start_recording"

    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        == expected_acquisition_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_RECORDING_UUID
        ]
        == expected_recording_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            CUSTOMER_ACCOUNT_ID_UUID
        ]
        == patched_start_recording_shared_dict["config_settings"]["Customer Account ID"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            USER_ACCOUNT_ID_UUID
        ]
        == patched_start_recording_shared_dict["config_settings"]["User Account ID"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            START_RECORDING_TIME_INDEX_UUID
        ]
        == expected_recording_timepoint
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            SOFTWARE_BUILD_NUMBER_UUID
        ]
        == COMPILED_EXE_BUILD_TIMESTAMP
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            SOFTWARE_RELEASE_VERSION_UUID
        ]
        == CURRENT_SOFTWARE_VERSION
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            MAIN_FIRMWARE_VERSION_UUID
        ]
        == patched_start_recording_shared_dict["main_firmware_version"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            SLEEP_FIRMWARE_VERSION_UUID
        ]
        == patched_start_recording_shared_dict["sleep_firmware_version"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            XEM_SERIAL_NUMBER_UUID
        ]
        == patched_start_recording_shared_dict["xem_serial_number"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            MANTARRAY_SERIAL_NUMBER_UUID
        ]
        == patched_start_recording_shared_dict["mantarray_serial_number"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            MANTARRAY_NICKNAME_UUID
        ]
        == patched_start_recording_shared_dict["mantarray_nickname"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            REFERENCE_VOLTAGE_UUID
        ]
        == REFERENCE_VOLTAGE
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            ADC_GAIN_SETTING_UUID
        ]
        == patched_start_recording_shared_dict["adc_gain"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"]
        == patched_start_recording_shared_dict["adc_offsets"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][PLATE_BARCODE_UUID]
        == expected_barcode
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            HARDWARE_TEST_RECORDING_UUID
        ]
        is False
    )

    assert (
        communication["timepoint_to_begin_recording_at"]
        == GENERIC_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    )
    assert set(communication["active_well_indices"]) == set(range(24))
    response_json = response.get_json()
    assert response_json["command"] == "start_recording"


def test_start_recording_command__populates_queue__with_correctly_parsed_set_of_well_indices(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&active_well_indices=0,5,8&is_hardware_test_recording=False"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["command"] == "start_recording"
    assert set(communication["active_well_indices"]) == set([0, 8, 5])


def test_start_recording_command__populates_queue__with_given_time_index_parameter(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_time_index = 1000
    barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={barcode}&time_index={expected_time_index}&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["command"] == "start_recording"
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            START_RECORDING_TIME_INDEX_UUID
        ]
        == expected_time_index
    )
    assert communication["timepoint_to_begin_recording_at"] == expected_time_index


def test_start_recording_command__populates_queue__with_correct_adc_offset_values_if_is_hardware_test_recording_is_true(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_adc_offsets = dict()
    for well_idx in range(24):
        expected_adc_offsets[well_idx] = {"construct": 0, "ref": 0}

    barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(f"/start_recording?barcode={barcode}")
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["command"] == "start_recording"
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"]
        == expected_adc_offsets
    )


def test_send_single_read_wire_out_command__populates_queue__and_logs_response(
    test_process_manager, test_client, mocker
):
    board_idx = 0
    expected_ep_addr = 6
    mocked_logger = mocker.patch.object(main.logger, "info", autospec=True)
    response = test_client.get(
        f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(board_idx)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_wire_out"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_wire_out"
    assert response_json["ep_addr"] == expected_ep_addr
    assert response_json["suppress_error"] is True
    mocked_logger.assert_called_once_with(
        f"Response to HTTP Request in next log entry: {response.get_json()}"
    )


def test_send_single_read_wire_out_command_with_hex_notation__populates_queue(
    test_process_manager, test_client
):
    board_idx = 0
    expected_ep_addr = "0x6"
    response = test_client.get(
        f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(board_idx)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_wire_out"
    assert communication["ep_addr"] == 6
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_wire_out"
    assert response_json["ep_addr"] == 6
    assert response_json["suppress_error"] is True


def test_send_single_read_wire_out_command_with_description__populates_queue(
    test_process_manager, test_client
):
    board_idx = 0
    expected_ep_addr = 6
    expected_description = "test"
    response = test_client.get(
        f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}&description={expected_description}"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(board_idx)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_wire_out"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["description"] == expected_description
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_wire_out"
    assert response_json["ep_addr"] == expected_ep_addr
    assert response_json["description"] == expected_description
    assert response_json["suppress_error"] is True


def test_send_single_read_from_fifo_command__populates_queue(
    test_process_manager, test_client, mocker
):
    test_bytearray = produce_data(1, 0)
    fifo = Queue()
    fifo.put(test_bytearray)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    response = test_client.get(
        "/insert_xem_command_into_queue/read_from_fifo?num_words_to_log=72"
    )
    assert response.status_code == 200
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_from_fifo"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    assert response_json["suppress_error"] is True


def test_send_single_read_from_fifo_command_with_hex_notation__populates_queue(
    test_process_manager, test_client, mocker
):
    test_bytearray = produce_data(1, 0)
    fifo = Queue()
    fifo.put(test_bytearray)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    response = test_client.get(
        "/insert_xem_command_into_queue/read_from_fifo?num_words_to_log=0x48"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "read_from_fifo"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "read_from_fifo"
    assert response_json["suppress_error"] is True


def test_send_single_is_spi_running_command__populates_queue(
    test_process_manager, test_client
):
    response = test_client.get("/insert_xem_command_into_queue/is_spi_running")
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "is_spi_running"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "is_spi_running"
    assert response_json["suppress_error"] is True


def test_send_single_get_serial_number_command__populates_queue(
    test_process_manager, test_client
):
    response = test_client.get("/insert_xem_command_into_queue/get_serial_number")
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_serial_number"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_serial_number"
    assert response_json["suppress_error"] is True


def test_send_single_get_device_id_command__populates_queue(
    test_process_manager, test_client
):
    response = test_client.get("/insert_xem_command_into_queue/get_device_id")
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "get_device_id"
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "get_device_id"
    assert response_json["suppress_error"] is True


def test_send_single_set_wire_in_command__populates_queue(
    test_process_manager, test_client
):
    expected_ep_addr = 8
    expected_value = 0x00000010
    expected_mask = 0x00000010
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_wire_in?ep_addr={expected_ep_addr}&value={expected_value}&mask={expected_mask}"
    )
    assert response.status_code == 200
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "set_wire_in"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["value"] == expected_value
    assert communication["mask"] == expected_mask
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "set_wire_in"
    assert response_json["ep_addr"] == expected_ep_addr
    assert response_json["value"] == expected_value
    assert response_json["mask"] == expected_mask
    assert response_json["suppress_error"] is True


def test_send_single_set_wire_in_command__using_hex_notation__populates_queue(
    test_process_manager, test_client
):
    expected_ep_addr = "0x05"
    value = "0x000000a0"
    mask = "0x00000011"
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_wire_in?ep_addr={expected_ep_addr}&value={value}&mask={mask}"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "debug_console"
    assert communication["command"] == "set_wire_in"
    assert communication["ep_addr"] == 5
    assert communication["value"] == 160
    assert communication["mask"] == 17
    assert communication["suppress_error"] is True
    response_json = response.get_json()
    assert response_json["command"] == "set_wire_in"
    assert response_json["ep_addr"] == 5
    assert response_json["value"] == 160
    assert response_json["mask"] == 17
    assert response_json["suppress_error"] is True


def test_send_single_start_managed_acquisition_command__populates_queues(
    test_process_manager, test_client, patched_shared_values_dict
):
    board_idx = 0
    patched_shared_values_dict["mantarray_serial_number"] = {board_idx: "M02001801"}

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "acquisition_manager"
    assert communication["command"] == "start_managed_acquisition"
    response_json = response.get_json()
    assert response_json["command"] == "start_managed_acquisition"

    to_da_queue = (
        test_process_manager.get_communication_queue_from_main_to_data_analyzer()
    )
    assert is_queue_eventually_not_empty(to_da_queue) is True
    comm_to_da = to_da_queue.get_nowait()
    assert comm_to_da["communication_type"] == "acquisition_manager"
    assert comm_to_da["command"] == "start_managed_acquisition"
    response_json = response.get_json()
    assert response_json["command"] == "start_managed_acquisition"


def test_send_single_stop_managed_acquisition_command__populates_queues(
    test_process_manager, test_client
):
    response = test_client.get("/stop_managed_acquisition")
    assert response.status_code == 200

    to_ok_comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(to_ok_comm_queue) is True
    comm_to_ok_comm = to_ok_comm_queue.get_nowait()
    assert comm_to_ok_comm["communication_type"] == "acquisition_manager"
    assert comm_to_ok_comm["command"] == "stop_managed_acquisition"
    response_json = response.get_json()
    assert response_json["command"] == "stop_managed_acquisition"

    to_file_writer_queue = (
        test_process_manager.get_communication_queue_from_main_to_file_writer()
    )
    assert is_queue_eventually_not_empty(to_file_writer_queue) is True
    comm_to_da = to_file_writer_queue.get_nowait()
    assert comm_to_da["communication_type"] == "acquisition_manager"
    assert comm_to_da["command"] == "stop_managed_acquisition"
    response_json = response.get_json()
    assert response_json["command"] == "stop_managed_acquisition"

    to_da_queue = (
        test_process_manager.get_communication_queue_from_main_to_data_analyzer()
    )
    assert is_queue_eventually_not_empty(to_da_queue) is True
    comm_to_da = to_da_queue.get_nowait()
    assert comm_to_da["communication_type"] == "acquisition_manager"
    assert comm_to_da["command"] == "stop_managed_acquisition"
    response_json = response.get_json()
    assert response_json["command"] == "stop_managed_acquisition"


def test_send_single_xem_scripts_command__populates_queue(
    test_process_manager, test_client
):
    expected_script_type = "start_up"
    response = test_client.get(f"/xem_scripts?script_type={expected_script_type}")
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "xem_scripts"
    assert communication["script_type"] == expected_script_type
    response_json = response.get_json()
    assert response_json["script_type"] == expected_script_type


def test_send_single_boot_up_command__populates_queue_with_both_commands(
    test_process_manager, test_client, mocker
):
    expected_script_type = "start_up"
    expected_bit_file_name = "main.bit"
    mocker.patch.object(
        process_manager,
        "get_latest_firmware",
        autospec=True,
        return_value=expected_bit_file_name,
    )

    response = test_client.get("/boot_up")
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)

    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "boot_up_instrument"
    assert communication["command"] == "initialize_board"
    assert communication["bit_file_name"] == expected_bit_file_name
    assert communication["suppress_error"] is False
    assert communication["allow_board_reinitialization"] is False

    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "xem_scripts"
    assert communication["script_type"] == expected_script_type

    expected_boot_up_dict = {
        "communication_type": "boot_up_instrument",
        "command": "initialize_board",
        "bit_file_name": expected_bit_file_name,
        "suppress_error": False,
        "allow_board_reinitialization": False,
    }
    expected_start_up_dict = {
        "communication_type": "xem_scripts",
        "script_type": expected_script_type,
    }
    response_json = response.get_json()
    assert response_json["boot_up_instrument"] == expected_boot_up_dict
    assert response_json["start_up"] == expected_start_up_dict


def test_send_single_set_mantarray_serial_number_command__populates_queue(
    test_process_manager, test_client, patched_shared_values_dict
):
    patched_shared_values_dict["mantarray_serial_number"] = dict()
    expected_serial_number = "M02001901"

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={expected_serial_number}"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_serial_number"
    assert communication["mantarray_serial_number"] == expected_serial_number
    response_json = response.get_json()
    assert response_json["command"] == "set_mantarray_serial_number"
    assert response_json["mantarray_serial_number"] == expected_serial_number


def test_single_update_settings_command_with_recording_dir__populates_file_writer_queue(
    test_process_manager, test_client, patched_shared_values_dict
):
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = test_client.get(
            f"/update_settings?recording_directory={expected_recordings_dir}"
        )
        assert response.status_code == 200

        comm_queue = (
            test_process_manager.get_communication_queue_from_main_to_file_writer()
        )
        assert is_queue_eventually_not_empty(comm_queue) is True
        communication = comm_queue.get_nowait()
        assert communication["command"] == "update_directory"
        assert communication["new_directory"] == expected_recordings_dir
