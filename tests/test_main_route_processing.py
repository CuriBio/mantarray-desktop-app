# -*- coding: utf-8 -*-
import datetime
from multiprocessing import Queue
import os
import tempfile

from freezegun import freeze_time
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import get_api_endpoint
from mantarray_desktop_app import get_mantarray_process_manager
from mantarray_desktop_app import get_mantarray_processes_monitor
from mantarray_desktop_app import get_server_port_number
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import PLATE_BARCODE_UUID
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import system_state_eventually_equals
from mantarray_desktop_app import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_desktop_app import wait_for_subprocesses_to_start
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import pytest
import requests
from stdlib_utils import confirm_port_in_use
from xem_wrapper import FrontPanelSimulator

from .fixtures import fixture_fully_running_app_from_main_entrypoint
from .fixtures import fixture_patched_firmware_folder
from .fixtures import fixture_patched_shared_values_dict
from .fixtures import fixture_patched_short_calibration_script
from .fixtures import fixture_patched_start_recording_shared_dict
from .fixtures import fixture_patched_test_xem_scripts_folder
from .fixtures import fixture_patched_xem_scripts_folder
from .fixtures import fixture_test_client
from .fixtures import fixture_test_process_manager
from .fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from .helpers import is_queue_eventually_empty
from .helpers import is_queue_eventually_not_empty

__fixtures__ = [
    fixture_fully_running_app_from_main_entrypoint,
    fixture_patched_shared_values_dict,
    fixture_test_client,
    fixture_test_process_manager,
    fixture_patched_start_recording_shared_dict,
    fixture_patched_xem_scripts_folder,
    fixture_patched_firmware_folder,
    fixture_patched_xem_scripts_folder,
    fixture_patched_short_calibration_script,
    fixture_patched_test_xem_scripts_folder,
]


@pytest.mark.slow
@freeze_time(
    GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ]
    + datetime.timedelta(
        seconds=GENERIC_START_RECORDING_COMMAND[  # pylint: disable=duplicate-code
            "timepoint_to_begin_recording_at"
        ]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_start_recording_command__gets_processed__and_creates_a_file__and_updates_shared_values_dict(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    timestamp_str = (
        GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        + datetime.timedelta(
            seconds=GENERIC_START_RECORDING_COMMAND[  # pylint: disable=duplicate-code
                "timepoint_to_begin_recording_at"
            ]
            / CENTIMILLISECONDS_PER_SECOND
        )
    ).strftime("%Y_%m_%d_%H%M%S")

    test_process_manager.start_processes()

    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&active_well_indices=3&is_hardware_test_recording=False"
    )
    assert response.status_code == 200

    assert patched_start_recording_shared_dict["system_status"] == RECORDING_STATE
    assert patched_start_recording_shared_dict["is_hardware_test_recording"] is False

    test_process_manager.soft_stop_and_join_processes()
    error_queue = test_process_manager.get_file_writer_error_queue()

    assert is_queue_eventually_empty(error_queue) is True
    file_dir = test_process_manager.get_file_writer_process().get_file_directory()
    actual_files = os.listdir(
        os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}")
    )
    assert actual_files == [f"{expected_barcode}__2020_02_09_190935__D1.h5"]


@pytest.mark.slow
@freeze_time(
    GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ]
)
def test_start_recording_command__gets_processed_with_given_time_index_parameter(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_time_index = 10000000
    timestamp_str = (
        GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        + datetime.timedelta(
            seconds=(expected_time_index / CENTIMILLISECONDS_PER_SECOND)
        )
    ).strftime("%Y_%m_%d_%H%M%S")
    patched_start_recording_shared_dict[  # pylint: disable=duplicate-code
        "utc_timestamps_of_beginning_of_data_acquisition"
    ] = [
        GENERIC_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
    ]

    test_process_manager.start_processes()

    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&active_well_indices=3&time_index={expected_time_index}"
    )
    assert response.status_code == 200

    assert patched_start_recording_shared_dict["system_status"] == RECORDING_STATE
    assert patched_start_recording_shared_dict["is_hardware_test_recording"] is True

    test_process_manager.soft_stop_and_join_processes()
    error_queue = test_process_manager.get_file_writer_error_queue()

    assert is_queue_eventually_empty(error_queue) is True
    file_dir = test_process_manager.get_file_writer_process().get_file_directory()
    actual_files = os.listdir(
        os.path.join(file_dir, f"{expected_barcode}__{timestamp_str}")
    )
    assert actual_files == [f"{expected_barcode}__{timestamp_str}__D1.h5"]


@pytest.mark.slow
def test_send_single_read_wire_out_command__gets_processed(
    test_process_manager, test_client
):
    board_idx = 0
    expected_ep_addr = 7
    wire_queue = Queue()
    expected_wire_out_response = 33
    wire_queue.put(expected_wire_out_response)

    simulator = FrontPanelSimulator({"wire_outs": {expected_ep_addr: wire_queue}})
    simulator.initialize_board()
    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    test_route = (
        f"/insert_xem_command_into_queue/read_wire_out?ep_addr={expected_ep_addr}"
    )
    response = test_client.get(test_route)
    assert response.status_code == 200

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(board_idx)
    assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        board_idx
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get_nowait()
    assert communication["command"] == "read_wire_out"
    assert communication["ep_addr"] == expected_ep_addr
    assert communication["response"] == expected_wire_out_response
    assert communication["hex_converted_response"] == hex(expected_wire_out_response)


@pytest.mark.slow
def test_send_single_set_wire_in_command__gets_processed(
    test_process_manager, test_client
):
    expected_ep_addr = 6
    expected_value = 0x00000011
    expected_mask = 0x00000011

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get(
        f"/insert_xem_command_into_queue/set_wire_in?ep_addr={expected_ep_addr}&value={expected_value}&mask={expected_mask}"
    )
    assert response.status_code == 200

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    communication = comm_from_ok_queue.get_nowait()
    assert communication["command"] == "set_wire_in"
    assert communication["ep_addr"] == expected_ep_addr


@pytest.mark.slow
def test_send_single_get_status_command__gets_processed(
    test_process_manager, test_client
):
    expected_response = {
        "is_spi_running": False,
        "is_board_initialized": False,
        "bit_file_name": None,
    }
    simulator = FrontPanelSimulator({})

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/get_status")
    assert response.status_code == 200

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get_nowait()
    assert communication["command"] == "get_status"
    assert communication["response"] == expected_response


@pytest.mark.slow
def test_send_single_start_managed_acquisition_command__sets_system_status_to_buffering__and_clears_data_analyzer_outgoing_queue(
    test_process_manager, test_client, patched_shared_values_dict
):
    board_idx = 0
    patched_shared_values_dict["mantarray_serial_number"] = {
        board_idx: RunningFIFOSimulator.default_mantarray_serial_number
    }

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    dummy_data = {"well_index": 0, "data": [[0, 1], [100, 200]]}
    outgoing_data_queue = test_process_manager.get_data_analyzer_data_out_queue()
    outgoing_data_queue.put(dummy_data)
    assert is_queue_eventually_not_empty(outgoing_data_queue)

    test_process_manager.start_processes()

    response = test_client.get("/start_managed_acquisition")
    assert response.status_code == 200

    assert patched_shared_values_dict["system_status"] == BUFFERING_STATE

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_empty(comm_queue) is True
    to_da_queue = (
        test_process_manager.get_communication_queue_from_main_to_data_analyzer()
    )
    assert is_queue_eventually_empty(to_da_queue) is True
    assert is_queue_eventually_empty(outgoing_data_queue)

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message
    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get_nowait()
    assert communication["command"] == "start_managed_acquisition"
    assert communication["timestamp"] - datetime.datetime.utcnow() < datetime.timedelta(
        0, 5
    )

    comm_from_da_queue = (
        test_process_manager.get_communication_queue_from_data_analyzer_to_main()
    )
    assert is_queue_eventually_not_empty(comm_from_da_queue) is True
    communication = comm_from_da_queue.get_nowait()
    assert communication["command"] == "start_managed_acquisition"


@pytest.mark.slow
def test_send_single_stop_managed_acquisition_command__gets_processed(
    test_process_manager, test_client
):
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    simulator.start_acquisition()

    ok_process = test_process_manager.get_ok_comm_process()
    ok_process.set_board_connection(0, simulator)

    test_process_manager.start_processes()

    response = test_client.get("/stop_managed_acquisition")
    assert response.status_code == 200

    test_process_manager.soft_stop_and_join_processes()
    to_ok_comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_empty(to_ok_comm_queue) is True
    to_file_writer_queue = (
        test_process_manager.get_communication_queue_from_main_to_file_writer()
    )
    assert is_queue_eventually_empty(to_file_writer_queue) is True
    to_da_queue = (
        test_process_manager.get_communication_queue_from_main_to_data_analyzer()
    )
    assert is_queue_eventually_empty(to_da_queue) is True

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message
    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get_nowait()
    assert communication["command"] == "stop_managed_acquisition"

    comm_from_file_writer_queue = (
        test_process_manager.get_communication_queue_from_file_writer_to_main()
    )
    assert is_queue_eventually_not_empty(comm_from_file_writer_queue) is True
    communication = comm_from_file_writer_queue.get_nowait()
    assert communication["communication_type"] == "command_receipt"
    assert communication["command"] == "stop_managed_acquisition"

    comm_from_da_queue = (
        test_process_manager.get_communication_queue_from_data_analyzer_to_main()
    )
    assert is_queue_eventually_not_empty(comm_from_da_queue) is True
    communication = comm_from_da_queue.get_nowait()
    assert communication["command"] == "stop_managed_acquisition"


@pytest.mark.slow
def test_send_xem_scripts_command__gets_processed(
    test_process_manager, test_client, patched_test_xem_scripts_folder, mocker
):
    expected_script_type = "test_script"

    test_process_manager.start_processes()

    response = test_client.get("/insert_xem_command_into_queue/initialize_board")
    assert response.status_code == 200
    response = test_client.get(f"/xem_scripts?script_type={expected_script_type}")
    assert response.status_code == 200
    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message
    comm_from_ok_queue.get_nowait()  # pull ok_comm connect to board message
    comm_from_ok_queue.get_nowait()  # pull initialize board response message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    script_communication = comm_from_ok_queue.get_nowait()
    assert script_communication["script_type"] == expected_script_type
    assert f"Running {expected_script_type} script" in script_communication["response"]

    done_message = comm_from_ok_queue.get_nowait()
    teardown_message = comm_from_ok_queue.get_nowait()
    while is_queue_eventually_not_empty(comm_from_ok_queue):
        done_message = teardown_message
        teardown_message = comm_from_ok_queue.get_nowait()
    assert done_message["communication_type"] == "xem_scripts"
    assert done_message["response"] == f"'{expected_script_type}' script complete."


@pytest.mark.timeout(20)
@pytest.mark.slow
def test_send_xem_scripts_command__gets_processed_in_fully_running_app(
    fully_running_app_from_main_entrypoint,
    patched_xem_scripts_folder,
    patched_shared_values_dict,
):
    _ = fully_running_app_from_main_entrypoint(["--skip-mantarray-boot-up"])
    port = get_server_port_number()
    confirm_port_in_use(port, timeout=5)
    wait_for_subprocesses_to_start()

    test_process_manager = get_mantarray_process_manager()
    test_process_monitor = get_mantarray_processes_monitor()
    monitor_error_queue = test_process_monitor.get_fatal_error_reporter()

    response = requests.get(
        f"{get_api_endpoint()}insert_xem_command_into_queue/initialize_board"
    )
    assert response.status_code == 200

    expected_script_type = "start_up"
    response = requests.get(
        f"{get_api_endpoint()}xem_scripts?script_type={expected_script_type}"
    )
    assert response.status_code == 200
    assert system_state_eventually_equals(CALIBRATION_NEEDED_STATE, 5)

    ok_comm_process = test_process_manager.get_ok_comm_process()
    ok_comm_process.soft_stop()
    ok_comm_process.join()

    expected_gain_value = 16
    assert patched_shared_values_dict["adc_gain"] == expected_gain_value
    assert is_queue_eventually_empty(monitor_error_queue) is True


@pytest.mark.slow
def test_send_single_boot_up_command__gets_processed_and_sets_system_status_to_instrument_initializing(
    patched_shared_values_dict,
    patched_xem_scripts_folder,
    patched_firmware_folder,
    test_process_manager,
    test_client,
):
    expected_script_type = "start_up"
    expected_bit_file_name = patched_firmware_folder

    test_process_manager.start_processes()
    response = test_client.get("/boot_up")
    assert response.status_code == 200
    assert patched_shared_values_dict["system_status"] == INSTRUMENT_INITIALIZING_STATE
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True

    test_process_manager.soft_stop_and_join_processes()
    assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message
    comm_from_ok_queue.get_nowait()  # pull ok_comm connect to board message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    initialize_board_communication = comm_from_ok_queue.get_nowait()
    assert initialize_board_communication["command"] == "initialize_board"
    assert expected_bit_file_name in initialize_board_communication["bit_file_name"]
    assert initialize_board_communication["allow_board_reinitialization"] is False

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True

    script_communication = comm_from_ok_queue.get_nowait()
    assert script_communication["communication_type"] == "xem_scripts"
    assert script_communication["script_type"] == expected_script_type
    assert f"Running {expected_script_type} script" in script_communication["response"]


@pytest.mark.slow
def test_send_single_boot_up_command__populates_ok_comm_error_queue_if_bit_file_cannot_be_found(
    patched_shared_values_dict, test_process_manager, test_client, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    mocker.patch.object(
        process_manager, "get_latest_firmware", autospec=True, return_value="fake.bit"
    )

    test_process_manager.start_processes()
    response = test_client.get("/boot_up")
    assert response.status_code == 200
    assert patched_shared_values_dict["system_status"] == INSTRUMENT_INITIALIZING_STATE
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_not_empty(comm_queue) is True

    test_process_manager.soft_stop_and_join_processes()
    assert is_queue_eventually_not_empty(comm_queue) is True

    ok_comm_error_queue = test_process_manager.get_ok_communication_error_queue()
    assert is_queue_eventually_not_empty(ok_comm_error_queue) is True

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message
    comm_from_ok_queue.get_nowait()  # pull ok_comm connect to board message
    comm_from_ok_queue.get_nowait()  # pull ok_comm teardown message
    assert is_queue_eventually_empty(comm_from_ok_queue) is True


@pytest.mark.slow
def test_send_single_set_mantarray_serial_number_command__gets_processed_and_stores_serial_number_in_shared_values_dict(
    test_process_manager, test_client, patched_shared_values_dict
):
    patched_shared_values_dict["mantarray_serial_number"] = dict()
    expected_serial_number = "M02001901"

    test_process_manager.start_processes()
    response = test_client.get(
        f"/insert_xem_command_into_queue/set_mantarray_serial_number?serial_number={expected_serial_number}"
    )
    assert response.status_code == 200
    assert (
        patched_shared_values_dict["mantarray_serial_number"][0]
        == expected_serial_number
    )

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.get_communication_to_ok_comm_queue(0)
    assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message
    comm_from_ok_queue.get_nowait()  # pull ok_comm connect to board message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get_nowait()
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_serial_number"
    assert communication["mantarray_serial_number"] == expected_serial_number


@pytest.mark.slow
def test_single_update_settings_command_with_recording_dir__gets_processed_by_FileWriter(
    test_process_manager, test_client, patched_shared_values_dict
):
    test_process_manager.start_processes()
    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        response = test_client.get(
            f"/update_settings?recording_directory={expected_recordings_dir}"
        )
        assert response.status_code == 200

        test_process_manager.soft_stop_and_join_processes()
        to_fw_queue = (
            test_process_manager.get_communication_queue_from_main_to_file_writer()
        )
        assert is_queue_eventually_empty(to_fw_queue) is True

        from_fw_queue = (
            test_process_manager.get_communication_queue_from_file_writer_to_main()
        )
        assert is_queue_eventually_not_empty(from_fw_queue) is True
        communication = from_fw_queue.get_nowait()
        assert communication["command"] == "update_directory"
        assert communication["new_directory"] == expected_recordings_dir
