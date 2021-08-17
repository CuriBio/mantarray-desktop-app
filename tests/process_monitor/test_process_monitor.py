# -*- coding: utf-8 -*-
import copy
import datetime
import json
import os
import queue
import threading
import time

from freezegun import freeze_time
from mantarray_desktop_app import BARCODE_INVALID_UUID
from mantarray_desktop_app import BARCODE_POLL_PERIOD
from mantarray_desktop_app import BARCODE_UNREADABLE_UUID
from mantarray_desktop_app import BARCODE_VALID_UUID
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import IncorrectMagnetometerConfigFromInstrumentError
from mantarray_desktop_app import INITIAL_MAGNETOMETER_CONFIG
from mantarray_desktop_app import INITIAL_SAMPLING_PERIOD
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import ok_comm
from mantarray_desktop_app import OUTGOING_DATA_BUFFER_SIZE
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import process_monitor
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import ServerManager
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.server import queue_command_to_instrument_comm
import numpy as np
import pytest
from stdlib_utils import invoke_process_run_and_check_errors
from xem_wrapper import FrontPanelSimulator

from ..fixtures import fixture_patch_print
from ..fixtures import fixture_test_process_manager
from ..fixtures import fixture_test_process_manager_beta_2_mode
from ..fixtures import get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_ok_comm import fixture_patch_connection_to_board
from ..fixtures_process_monitor import fixture_test_monitor
from ..fixtures_process_monitor import fixture_test_monitor_beta_2_mode
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_not_empty
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_test_process_manager,
    fixture_test_process_manager_beta_2_mode,
    fixture_test_monitor,
    fixture_test_monitor_beta_2_mode,
    fixture_patch_connection_to_board,
    fixture_patch_print,
]


def test_MantarrayProcessesMonitor__init__calls_super(mocker, test_process_manager):
    error_queue = queue.Queue()
    mocked_super_init = mocker.spy(threading.Thread, "__init__")
    MantarrayProcessesMonitor({}, test_process_manager, error_queue, threading.Lock())
    assert mocked_super_init.call_count == 1


@pytest.mark.timeout(12)
def test_MantarrayProcessesMonitor__soft_stop_calls_manager_soft_stop_and_join(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, _, _, _ = test_monitor

    # mock to avoid issues with test hanging
    mocker.patch.object(ServerManager, "shutdown_server", autospec=True)

    spied_stop = mocker.spy(test_process_manager, "soft_stop_and_join_processes")
    test_process_manager.start_processes()
    monitor_thread.start()

    time.sleep(
        0.5
    )  # Eli (12/10/20): give time for the ProcessMonitor to consume the start up messages from the queues of the subprocesses before attempting to join them

    monitor_thread.soft_stop()
    monitor_thread.join()
    assert spied_stop.call_count == 1


def test_MantarrayProcessesMonitor__logs_messages_from_instrument_comm(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    instrument_comm_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    expected_comm = {
        "communication_type": "debug_console",
        "command": "get_device_id",
        "response": "my_cool_id",
    }
    instrument_comm_to_main.put_nowait(expected_comm)
    assert is_queue_eventually_not_empty(instrument_comm_to_main) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(instrument_comm_to_main) is True
    mocked_logger.assert_called_once_with(f"Communication from the Instrument Controller: {expected_comm}")


def test_MantarrayProcessesMonitor__logs_messages_from_file_writer(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    file_writer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
    )
    expected_comm = {
        "communication_type": "command_receipt",
        "command": "stop_recording",
        "timepoint_to_stop_recording_at": 223,
    }
    file_writer_to_main.put_nowait(expected_comm)
    assert is_queue_eventually_not_empty(file_writer_to_main) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(file_writer_to_main) is True
    mocked_logger.assert_called_once_with(f"Communication from the File Writer: {expected_comm}")


def test_MantarrayProcessesMonitor__logs_messages_from_data_analyzer(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    data_analyzer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
    )
    expected_comm = {
        "communication_type": "finalized_data",
        "well_index": 0,
        "data": np.zeros((2, 10)),
    }
    data_analyzer_to_main.put_nowait(expected_comm)
    assert is_queue_eventually_not_empty(data_analyzer_to_main) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(data_analyzer_to_main) is True
    mocked_logger.assert_called_once_with(f"Communication from the Data Analyzer: {expected_comm}")


def test_MantarrayProcessesMonitor__pulls_outgoing_data_from_data_analyzer_and_makes_it_available_to_server(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE

    da_data_out_queue = test_process_manager.queue_container().get_data_analyzer_board_queues()[0][1]
    pm_data_out_queue = test_process_manager.queue_container().get_data_queue_to_server()

    # add dummy data here. In this test, the item is never actually looked at, so it can be any string value
    expected_json_data = json.dumps({"well": 0, "data": [1, 2, 3, 4, 5]})
    da_data_out_queue.put_nowait(expected_json_data)
    confirm_queue_is_eventually_of_size(
        da_data_out_queue, 1, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(da_data_out_queue)
    confirm_queue_is_eventually_of_size(pm_data_out_queue, 1)
    actual = pm_data_out_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_json_data


def test_MantarrayProcessesMonitor__logs_errors_from_instrument_comm_process(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    test_process_manager.start_processes()

    instrument_comm_error_queue = (
        test_process_manager.queue_container().get_instrument_communication_error_queue()
    )
    expected_error = ValueError("something wrong")
    expected_stack_trace = "my stack trace"
    expected_message = f"Error raised by subprocess {test_process_manager.get_instrument_process()}\n{expected_stack_trace}\n{expected_error}"
    instrument_comm_error_queue.put_nowait((expected_error, expected_stack_trace))
    assert is_queue_eventually_not_empty(instrument_comm_error_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(instrument_comm_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__logs_errors_from_file_writer(mocker, test_process_manager, test_monitor):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    test_process_manager.start_processes()

    file_writer_error_queue = test_process_manager.queue_container().get_file_writer_error_queue()
    expected_error = ValueError("something wrong when writing file")
    expected_stack_trace = "my stack trace from writing a file"
    expected_message = f"Error raised by subprocess {test_process_manager.get_file_writer_process()}\n{expected_stack_trace}\n{expected_error}"
    file_writer_error_queue.put_nowait((expected_error, expected_stack_trace))
    assert is_queue_eventually_not_empty(file_writer_error_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(file_writer_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__logs_errors_from_data_analyzer(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    test_process_manager.start_processes()

    data_analyzer_error_queue = test_process_manager.queue_container().get_data_analyzer_error_queue()
    expected_error = ValueError("something wrong when analyzing data")
    expected_stack_trace = "my stack trace from analyzing some data"
    expected_message = f"Error raised by subprocess {test_process_manager.get_data_analyzer_process()}\n{expected_stack_trace}\n{expected_error}"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        (expected_error, expected_stack_trace), data_analyzer_error_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(data_analyzer_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__hard_stops_and_joins_processes_and_logs_queue_items_when_error_is_raised_in_ok_comm_subprocess(
    mocker, test_process_manager, test_monitor
):
    expected_ok_comm_item = "ok_comm_queue_item"
    expected_file_writer_item = "file_writer_queue_item"
    expected_da_item = "data_analyzer_queue_item"
    expected_server_item = "server_manager_queue_item"

    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    okc_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()
    server_manager = test_process_manager.get_server_manager()
    mocked_okc_join = mocker.patch.object(okc_process, "join", autospec=True)
    mocked_fw_join = mocker.patch.object(fw_process, "join", autospec=True)
    mocked_da_join = mocker.patch.object(da_process, "join", autospec=True)
    mocked_shutdown_server = mocker.patch.object(server_manager, "shutdown_server", autospec=True)

    ok_comm_error_queue = test_process_manager.queue_container().get_data_analyzer_error_queue()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        ("error", "stack_trace"), ok_comm_error_queue
    )
    instrument_to_main = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_ok_comm_item, instrument_to_main)
    file_writer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_file_writer_item, file_writer_to_main
    )
    data_analyzer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_da_item, data_analyzer_to_main)
    server_to_main = test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_server_item, server_to_main)

    invoke_process_run_and_check_errors(monitor_thread)

    mocked_okc_join.assert_called_once()
    mocked_fw_join.assert_called_once()
    mocked_da_join.assert_called_once()
    mocked_shutdown_server.assert_called_once()

    actual = mocked_logger.call_args_list[1][0][0]
    assert "Remaining items in process queues: {" in actual
    assert expected_ok_comm_item in actual
    assert expected_file_writer_item in actual
    assert expected_da_item in actual
    assert expected_server_item in actual


@freeze_time(datetime.datetime(year=2020, month=2, day=27, hour=12, minute=14, second=22, microsecond=336597))
def test_MantarrayProcessesMonitor__updates_timestamp_in_shared_values_dict_after_receiving_communication_from_start_acquisition(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    queue_command_to_instrument_comm(get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION())
    comm_to_instrument_comm = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    assert is_queue_eventually_not_empty(comm_to_instrument_comm) is True
    ok_comm_process = test_process_manager.get_instrument_process()
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()

    ok_comm_process.set_board_connection(0, simulator)

    invoke_process_run_and_check_errors(ok_comm_process)
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"][0] == datetime.datetime(
        year=2020, month=2, day=27, hour=12, minute=14, second=22, microsecond=336597
    )


def test_MantarrayProcessesMonitor__correctly_sets_system_status_to_live_view_active_only_when_initial_required_number_of_data_dumps_become_available_from_data_analyzer(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    data_analyzer_process = test_process_manager.get_data_analyzer_process()
    da_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
    )

    dummy_data = {
        "well5": [1, 2, 3],
        "earliest_timepoint": 1,
        "latest_timepoint": 3,
    }

    shared_values_dict["system_status"] = BUFFERING_STATE
    data_analyzer_process._dump_data_into_queue(dummy_data)  # pylint:disable=protected-access
    assert is_queue_eventually_not_empty(da_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == BUFFERING_STATE

    data_analyzer_process._dump_data_into_queue(dummy_data)  # pylint:disable=protected-access
    assert is_queue_eventually_not_empty(da_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == LIVE_VIEW_ACTIVE_STATE

    shared_values_dict["system_status"] = RECORDING_STATE
    data_analyzer_process._dump_data_into_queue(dummy_data)  # pylint:disable=protected-access
    assert is_queue_eventually_not_empty(da_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == RECORDING_STATE


def test_MantarrayProcessesMonitor__sets_system_status_to_server_ready_after_subprocesses_finish_start_up(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    okc_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    mocked_okc_started = mocker.patch.object(okc_process, "is_start_up_complete", side_effect=[True, True])
    mocked_fw_started = mocker.patch.object(fw_process, "is_start_up_complete", side_effect=[True, True])
    mocked_da_started = mocker.patch.object(da_process, "is_start_up_complete", side_effect=[False, True])

    invoke_process_run_and_check_errors(monitor_thread)
    assert mocked_okc_started.call_count == 1
    assert mocked_fw_started.call_count == 1
    assert mocked_da_started.call_count == 1
    assert shared_values_dict["system_status"] == SERVER_INITIALIZING_STATE

    invoke_process_run_and_check_errors(monitor_thread)
    assert mocked_okc_started.call_count == 2
    assert mocked_fw_started.call_count == 2
    assert mocked_da_started.call_count == 2
    assert shared_values_dict["system_status"] == SERVER_READY_STATE


def test_MantarrayProcessesMonitor__does_not_check_start_up_status_after_subprocesses_finish_start_up(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    expected_system_status = CALIBRATION_NEEDED_STATE
    shared_values_dict["system_status"] = expected_system_status

    okc_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    spied_okc_started = mocker.spy(okc_process, "is_start_up_complete")
    spied_fw_started = mocker.spy(fw_process, "is_start_up_complete")
    spied_da_started = mocker.spy(da_process, "is_start_up_complete")

    invoke_process_run_and_check_errors(monitor_thread)
    assert spied_okc_started.call_count == 0
    assert spied_fw_started.call_count == 0
    assert spied_da_started.call_count == 0
    assert shared_values_dict["system_status"] == expected_system_status


def test_MantarrayProcessesMonitor__sets_in_simulation_mode_to_false_when_connected_to_real_board(
    patch_connection_to_board, test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    ok_comm_process = test_process_manager.get_instrument_process()
    container = test_process_manager.queue_container()
    instrument_comm_to_main_queue = container.get_communication_queue_from_instrument_comm_to_main(0)

    ok_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(instrument_comm_to_main_queue) is True

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["in_simulation_mode"] is False


def test_MantarrayProcessesMonitor__sets_in_simulation_mode_to_true_when_connected_to_simulator(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    ok_comm_process = test_process_manager.get_instrument_process()
    instrument_comm_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    ok_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(instrument_comm_to_main_queue) is True

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["in_simulation_mode"] is True


def test_MantarrayProcessesMonitor__sets_system_status_to_needs_calibration_after_start_up_script_completes(
    test_monitor, test_process_manager, mocker
):
    mocked_path_str = os.path.join("tests", "test_xem_scripts", "xem_test_start_up.txt")
    mocker.patch.object(ok_comm, "resource_path", autospec=True, return_value=mocked_path_str)

    monitor_thread, shared_values_dict, _, _ = test_monitor

    ok_comm_process = test_process_manager.get_instrument_process()
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_comm_process.set_board_connection(0, simulator)

    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    to_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    to_instrument_comm_queue.put_nowait({"communication_type": "xem_scripts", "script_type": "start_up"})
    assert is_queue_eventually_not_empty(to_instrument_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_instrument_comm_queue) is True
    # Tanner (6/2/20): number of iterations should be 3 here because xem_scripts sends 3 messages to main, and the third one will contain the system status update
    invoke_process_run_and_check_errors(monitor_thread, num_iterations=3)

    assert shared_values_dict["system_status"] == CALIBRATION_NEEDED_STATE


def test_MantarrayProcessesMonitor__sets_system_status_to_calibrated_after_calibration_script_completes(
    test_monitor, test_process_manager, mocker
):
    mocked_path_str = os.path.join("tests", "test_xem_scripts", "xem_test_start_calibration.txt")
    mocker.patch.object(ok_comm, "resource_path", autospec=True, return_value=mocked_path_str)

    monitor_thread, shared_values_dict, _, _ = test_monitor
    ok_comm_process = test_process_manager.get_instrument_process()
    simulator = RunningFIFOSimulator()
    simulator.initialize_board()
    ok_comm_process.set_board_connection(0, simulator)

    ok_comm_process = test_process_manager.get_instrument_process()
    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    to_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    to_instrument_comm_queue.put_nowait(
        {"communication_type": "xem_scripts", "script_type": "start_calibration"}
    )
    assert is_queue_eventually_not_empty(to_instrument_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_instrument_comm_queue) is True
    # Tanner (6/29/20): number of iterations should be 51 here because xem_scripts sends 51 total messages, the last one containing the system status update
    invoke_process_run_and_check_errors(monitor_thread, num_iterations=51)

    assert shared_values_dict["system_status"] == CALIBRATED_STATE


def test_MantarrayProcessesMonitor__sets_system_status_to_calibrated_after_managed_acquisition_stops__and_resets_data_dump_buffer_size(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    monitor_thread._data_dump_buffer_size = OUTGOING_DATA_BUFFER_SIZE  # pylint:disable=protected-access

    ok_comm_process = test_process_manager.get_instrument_process()
    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    to_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_comm_process.set_board_connection(0, simulator)

    to_instrument_comm_queue.put_nowait(STOP_MANAGED_ACQUISITION_COMMUNICATION)
    assert is_queue_eventually_not_empty(to_instrument_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_instrument_comm_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == CALIBRATED_STATE
    assert monitor_thread._data_dump_buffer_size == 0  # pylint:disable=protected-access


def test_MantarrayProcessesMonitor__stores_device_information_after_connection__in_beta_1_mode(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    ok_comm_process = test_process_manager.get_instrument_process()
    instrument_comm_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    ok_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(instrument_comm_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["xem_serial_number"][0] == RunningFIFOSimulator.default_xem_serial_number
    assert (
        shared_values_dict["mantarray_serial_number"][0]
        == RunningFIFOSimulator.default_mantarray_serial_number
    )
    assert shared_values_dict["mantarray_nickname"][0] == RunningFIFOSimulator.default_mantarray_nickname


def test_MantarrayProcessesMonitor__sets_in_simulation_mode_after_connection__in_beta_2_mode(
    test_monitor_beta_2_mode, test_process_manager_beta_2_mode
):
    monitor_thread, shared_values_dict, _, _ = test_monitor_beta_2_mode

    mc_comm_process = test_process_manager_beta_2_mode.get_instrument_process()
    instrument_comm_to_main_queue = test_process_manager_beta_2_mode.queue_container().get_communication_queue_from_instrument_comm_to_main(
        0
    )

    mc_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(instrument_comm_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["in_simulation_mode"] is True


def test_MantarrayProcessesMonitor__stores_device_information_from_metadata_comm__and_updates_system_status(
    test_monitor_beta_2_mode, test_process_manager_beta_2_mode
):
    monitor_thread, shared_values_dict, _, _ = test_monitor_beta_2_mode
    shared_values_dict["system_status"] = INSTRUMENT_INITIALIZING_STATE

    board_idx = 0

    instrument_comm_to_main_queue = test_process_manager_beta_2_mode.queue_container().get_communication_queue_from_instrument_comm_to_main(
        board_idx
    )

    metadata_comm_dict = {
        "communication_type": "metadata_comm",
        "command": "get_metadata",
        "metadata": MantarrayMcSimulator.default_metadata_values,
        "board_index": board_idx,
    }
    instrument_comm_to_main_queue.put_nowait(metadata_comm_dict)
    assert is_queue_eventually_not_empty(instrument_comm_to_main_queue) is True
    invoke_process_run_and_check_errors(
        monitor_thread,
        num_iterations=2,  # one cycle to retrieve metadata, one cycle to update system_status
    )
    assert shared_values_dict["system_status"] == CALIBRATION_NEEDED_STATE

    assert (
        shared_values_dict["main_firmware_version"][board_idx]
        == MantarrayMcSimulator.default_firmware_version
    )
    assert (
        shared_values_dict["mantarray_serial_number"][board_idx]
        == MantarrayMcSimulator.default_mantarray_serial_number
    )
    assert (
        shared_values_dict["mantarray_nickname"][board_idx] == MantarrayMcSimulator.default_mantarray_nickname
    )
    assert (
        shared_values_dict["instrument_metadata"][board_idx] == MantarrayMcSimulator.default_metadata_values
    )


def test_MantarrayProcessesMonitor__calls_boot_up_only_once_after_subprocesses_start_if_boot_up_after_processes_start_is_True(
    test_process_manager, mocker
):
    mocked_boot_up = mocker.patch.object(test_process_manager, "boot_up_instrument")

    shared_values_dict = {
        "system_status": SERVER_READY_STATE,
        "beta_2_mode": False,
    }
    error_queue = error_queue = queue.Queue()
    the_lock = threading.Lock()
    monitor = MantarrayProcessesMonitor(
        shared_values_dict,
        test_process_manager,
        error_queue,
        the_lock,
        boot_up_after_processes_start=True,
    )

    invoke_process_run_and_check_errors(monitor)
    assert mocked_boot_up.call_count == 1
    invoke_process_run_and_check_errors(monitor)
    assert mocked_boot_up.call_count == 1


def test_MantarrayProcessesMonitor__doesnt_call_boot_up_after_subprocesses_start_if_boot_up_after_processes_start_is_False(
    test_process_manager, mocker
):
    mocked_boot_up = mocker.patch.object(test_process_manager, "boot_up_instrument")

    shared_values_dict = {
        "system_status": SERVER_READY_STATE,
        "beta_2_mode": False,
    }
    error_queue = error_queue = queue.Queue()
    the_lock = threading.Lock()
    monitor = MantarrayProcessesMonitor(
        shared_values_dict,
        test_process_manager,
        error_queue,
        the_lock,
        boot_up_after_processes_start=False,
    )

    invoke_process_run_and_check_errors(monitor)
    assert mocked_boot_up.call_count == 0


def test_MantarrayProcessesMonitor__stores_firmware_versions_during_instrument_boot_up(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    # Tanner (12/28/20): RunningFIFOSimulator ignores the name of bit file given, so we can mock this out so it will pass in Cloud9
    mocker.patch.object(process_manager, "get_latest_firmware", autospec=True, return_value=None)

    okc_process = test_process_manager.get_instrument_process()
    to_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    simulator = RunningFIFOSimulator()
    okc_process.set_board_connection(0, simulator)
    test_process_manager.boot_up_instrument()
    assert is_queue_eventually_not_empty(to_instrument_comm_queue) is True
    invoke_process_run_and_check_errors(okc_process)

    assert is_queue_eventually_not_empty(from_instrument_comm_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["main_firmware_version"][0] == RunningFIFOSimulator.default_firmware_version
    assert shared_values_dict["sleep_firmware_version"][0] == "0.0.0"


def test_MantarrayProcessesMonitor__scrubs_username_from_bit_file_name_in_get_status_log_message(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, _, _, _ = test_monitor
    spied_info = mocker.spy(process_monitor.logger, "info")

    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    test_communication = {
        "communication_type": "debug_console",
        "command": "get_status",
        "response": {
            "is_spi_running": False,
            "is_board_initialized": True,
            "bit_file_name": r"Users\username\AppData\main.bit",
        },
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(test_communication), from_instrument_comm_queue
    )

    invoke_process_run_and_check_errors(monitor_thread)

    expected_scrubbed_path = r"Users\********\AppData\main.bit"
    assert expected_scrubbed_path in spied_info.call_args[0][0]


def test_MantarrayProcessesMonitor__scrubs_username_from_bit_file_name_in_boot_up_instrument_log_message(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, _, _, _ = test_monitor
    spied_info = mocker.spy(process_monitor.logger, "info")

    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    test_communication = {
        "communication_type": "boot_up_instrument",
        "command": "initialize_board",
        "suppress_error": False,
        "allow_board_reinitialization": False,
        "board_index": 0,
        "main_firmware_version": "1.1.1",
        "sleep_firmware_version": "0.0.0",
        "bit_file_name": r"Users\username1\AppData\main.bit",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(test_communication), from_instrument_comm_queue
    )

    invoke_process_run_and_check_errors(monitor_thread)

    expected_scrubbed_path = r"Users\*********\AppData\main.bit"
    assert expected_scrubbed_path in spied_info.call_args[0][0]


def test_MantarrayProcessesMonitor__scrubs_username_from_finalized_recording_files_in_log_message(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, _, _, _ = test_monitor
    spied_info = mocker.spy(process_monitor.logger, "info")

    from_file_writer_queue = (
        test_process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
    )

    test_communication = {
        "communication_type": "file_finalized",
        "file_path": r"Users\Curi Customer\AppData\Roaming\MantarrayController\recordings\recorded_file.h5",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(test_communication), from_file_writer_queue
    )

    invoke_process_run_and_check_errors(monitor_thread)

    expected_scrubbed_path = (
        r"Users\*************\AppData\Roaming\MantarrayController\recordings\recorded_file.h5"
    )
    assert expected_scrubbed_path in spied_info.call_args[0][0]


def test_MantarrayProcessesMonitor__sends_two_barcode_poll_commands_to_OKComm_at_correct_time_intervals(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, _, _, _ = test_monitor
    to_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )

    expected_time_1 = 0
    expected_time_2 = 15

    mocker.patch.object(
        process_monitor,
        "_get_barcode_clear_time",
        autospec=True,
        side_effect=[expected_time_1, expected_time_2, None],
    )
    mocked_get_dur = mocker.patch.object(
        process_monitor,
        "_get_dur_since_last_barcode_clear",
        autospec=True,
        side_effect=[
            BARCODE_POLL_PERIOD - 1,
            BARCODE_POLL_PERIOD,
            BARCODE_POLL_PERIOD - 1,
            BARCODE_POLL_PERIOD,
        ],
    )

    expected_comm = {
        "communication_type": "barcode_comm",
        "command": "start_scan",
    }

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(to_instrument_comm_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_of_size(to_instrument_comm_queue, 1)
    actual = to_instrument_comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_comm

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(to_instrument_comm_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_of_size(to_instrument_comm_queue, 1)
    actual = to_instrument_comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_comm

    assert mocked_get_dur.call_args_list[0][0][0] == expected_time_1
    assert mocked_get_dur.call_args_list[1][0][0] == expected_time_1
    assert mocked_get_dur.call_args_list[2][0][0] == expected_time_2
    assert mocked_get_dur.call_args_list[3][0][0] == expected_time_2


@pytest.mark.parametrize(
    "expected_barcode,test_valid,expected_status,test_description",
    [
        ("MA200190000", True, BARCODE_VALID_UUID, "stores new valid barcode"),
        ("M$200190000", False, BARCODE_INVALID_UUID, "stores new invalid barcode"),
        ("", None, BARCODE_UNREADABLE_UUID, "stores no barcode"),
    ],
)
def test_MantarrayProcessesMonitor__stores_barcode_sent_from_instrument_comm__and_no_previously_stored_barcode(
    expected_barcode,
    test_valid,
    expected_status,
    test_description,
    test_monitor,
    test_process_manager,
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    expected_board_idx = 0
    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(
            expected_board_idx
        )
    )

    barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_barcode,
        "board_idx": expected_board_idx,
    }
    if test_valid is not None:
        barcode_comm["valid"] = test_valid
    if test_valid is False:
        # specifically want test_valid to be False here, not None since invalid barcodes have trailing `\x00`
        barcode_comm["barcode"] += chr(0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(barcode_comm, from_instrument_comm_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["barcodes"][expected_board_idx] == {
        "plate_barcode": expected_barcode,
        "barcode_status": expected_status,
        "frontend_needs_barcode_update": True,
    }


@pytest.mark.parametrize(
    "expected_barcode,test_valid,expected_status,test_description",
    [
        ("MA200190000", True, BARCODE_VALID_UUID, "updates to new valid barcode"),
        ("M$200190000", False, BARCODE_INVALID_UUID, "updates to new invalid barcode"),
        ("", None, BARCODE_UNREADABLE_UUID, "updates to no barcode"),
    ],
)
def test_MantarrayProcessesMonitor__updates_to_new_barcode_sent_from_instrument_comm(
    expected_barcode,
    test_valid,
    expected_status,
    test_description,
    test_monitor,
    test_process_manager,
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    expected_board_idx = 0
    shared_values_dict["barcodes"] = {
        expected_board_idx: {
            "plate_barcode": "old barcode",
            "barcode_status": None,
            "frontend_needs_barcode_update": None,
        }
    }

    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(
            expected_board_idx
        )
    )

    barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_barcode,
        "board_idx": expected_board_idx,
    }
    if test_valid is not None:
        barcode_comm["valid"] = test_valid
    if test_valid is False:
        # specifically want test_valid to be False here, not None since invalid barcodes have trailing `\x00`
        barcode_comm["barcode"] += chr(0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(barcode_comm, from_instrument_comm_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["barcodes"][expected_board_idx] == {
        "plate_barcode": expected_barcode,
        "barcode_status": expected_status,
        "frontend_needs_barcode_update": True,
    }


@pytest.mark.parametrize(
    "expected_barcode,test_valid,test_update,test_description",
    [
        ("MA200190000", True, False, "does not update to current valid barcode"),
        ("M$200190000", False, True, "does not update to current invalid barcode"),
        ("", None, False, "does not update to current empty barcode"),
    ],
)
def test_MantarrayProcessesMonitor__does_not_update_any_values_if_new_barcode_matches_current_barcode(
    expected_barcode,
    test_valid,
    test_update,
    test_description,
    test_monitor,
    test_process_manager,
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    expected_board_idx = 0
    expected_dict = {
        "plate_barcode": expected_barcode,
        "barcode_status": None,
        "frontend_needs_barcode_update": test_update,
    }
    shared_values_dict["barcodes"] = {expected_board_idx: expected_dict}

    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(
            expected_board_idx
        )
    )

    barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_barcode,
        "board_idx": expected_board_idx,
    }
    if test_valid is not None:
        barcode_comm["valid"] = test_valid
    if test_valid is False:
        # specifically want test_valid to be False here, not None since invalid barcodes have trailing `\x00`
        barcode_comm["barcode"] += chr(0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(barcode_comm, from_instrument_comm_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["barcodes"][expected_board_idx] == expected_dict


def test_MantarrayProcessesMonitor__trims_barcode_string_before_storing_in_shared_values_dict(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    expected_board_idx = 0
    from_instrument_comm_queue = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(
            expected_board_idx
        )
    )

    expected_barcode = "M020090048"
    barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_barcode + chr(0) * 2,
        "board_idx": expected_board_idx,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(barcode_comm, from_instrument_comm_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["barcodes"][expected_board_idx]["plate_barcode"] == expected_barcode


def test_MantarrayProcessesMonitor__redacts_mantarray_nickname_from_logged_mantarray_naming_ok_comm_messages(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    instrument_comm_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    test_nickname = "MyMantarray"
    test_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": test_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_comm, instrument_comm_to_main)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(instrument_comm_to_main)

    expected_comm = copy.deepcopy(test_comm)
    expected_comm["mantarray_nickname"] = "*" * len(test_nickname)
    mocked_logger.assert_called_once_with(f"Communication from the Instrument Controller: {expected_comm}")


def test_MantarrayProcessesMonitor__redacts_mantarray_nickname_from_logged_board_connection_status_change_ok_comm_messages(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    instrument_comm_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )

    test_nickname = "MyOtherMantarray"
    test_comm = {
        "communication_type": "board_connection_status_change",
        "board_index": 0,
        "is_connected": True,
        "mantarray_serial_number": RunningFIFOSimulator.default_mantarray_serial_number,
        "xem_serial_number": RunningFIFOSimulator.default_xem_serial_number,
        "mantarray_nickname": test_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_comm, instrument_comm_to_main)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(instrument_comm_to_main)

    expected_comm = copy.deepcopy(test_comm)
    expected_comm["mantarray_nickname"] = "*" * len(test_nickname)
    mocked_logger.assert_called_once_with(f"Communication from the Instrument Controller: {expected_comm}")


def test_MantarrayProcessesMonitor__raises_error_if_config_dict_in_start_data_stream_command_response_from_instrument_does_not_match_expected_value(
    test_process_manager, test_monitor, patch_print
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    queues = test_process_manager.queue_container()
    ic_to_main_queue = queues.get_communication_queue_from_instrument_comm_to_main(0)

    test_num_wells = 24
    expected_config_dict = create_magnetometer_config_dict(test_num_wells)
    shared_values_dict["magnetometer_config_dict"] = {
        "magnetometer_config": copy.deepcopy(expected_config_dict)
    }
    shared_values_dict["beta_2_mode"] = True

    # Tanner (5/22/21): `x ^= True` flips the Boolean value of x. Doing this guards against changes to the default configuration value
    expected_config_dict[1][SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]] ^= True
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "to_instrument",
            "command": "start_managed_acquisition",
            "magnetometer_config": expected_config_dict,
            "timestamp": None,
        },
        ic_to_main_queue,
    )
    with pytest.raises(IncorrectMagnetometerConfigFromInstrumentError):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__drains_data_analyzer_data_out_queue_after_receiving_stop_managed_acquisition_command_receipt(
    test_process_manager,
    test_monitor,
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    shared_values_dict["system_status"] = CALIBRATED_STATE

    da_data_out_queue = test_process_manager.queue_container().get_data_analyzer_board_queues()[0][1]
    put_object_into_queue_and_raise_error_if_eventually_still_empty("test_item", da_data_out_queue)

    data_analyzer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        STOP_MANAGED_ACQUISITION_COMMUNICATION, data_analyzer_to_main
    )

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(da_data_out_queue)


def test_MantarrayProcessesMonitor__updates_magnetometer_config_after_receiving_default_config_message_from_mc_comm(
    test_process_manager,
    test_monitor,
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    expected_magnetometer_config_dict = {
        "magnetometer_config": copy.deepcopy(INITIAL_MAGNETOMETER_CONFIG),
        "sampling_period": INITIAL_SAMPLING_PERIOD,
    }

    instrument_comm_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    main_to_da = test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    main_to_ic = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)

    default_config_comm = {
        "communication_type": "default_magnetometer_config",
        "command": "change_magnetometer_config",
        "magnetometer_config_dict": expected_magnetometer_config_dict,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        default_config_comm, instrument_comm_to_main
    )
    invoke_process_run_and_check_errors(monitor_thread)

    # make sure update was stored
    assert shared_values_dict["magnetometer_config_dict"] == expected_magnetometer_config_dict
    # make sure update was passed to data analyzer
    confirm_queue_is_eventually_of_size(main_to_da, 1)
    comm_to_da = main_to_da.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_comm_to_da = {
        "communication_type": "to_instrument",
        "command": "change_magnetometer_config",
    }
    expected_comm_to_da.update(expected_magnetometer_config_dict)
    assert comm_to_da == expected_comm_to_da
    # make sure update was not sent back to mc_comm
    confirm_queue_is_eventually_empty(main_to_ic)


def test_MantarrayProcessesMonitor__updates_stimulation_running_status_after_mc_comm_sends_message_indicating_all_protocols_have_concluded(
    test_process_manager,
    test_monitor,
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    shared_values_dict["stimulation_running"] = True

    instrument_comm_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(0)
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "stimulation",
            "command": "concluding_stim_protocol",
            "all_protocols_complete": True,
        },
        instrument_comm_to_main,
    )

    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["stimulation_running"] is False
