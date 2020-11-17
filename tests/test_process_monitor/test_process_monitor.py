# -*- coding: utf-8 -*-
import datetime
import os
import queue
import threading

from freezegun import freeze_time
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import ok_comm
from mantarray_desktop_app import OUTGOING_DATA_BUFFER_SIZE
from mantarray_desktop_app import process_monitor
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.server import queue_command_to_ok_comm
import numpy as np
import pytest
from stdlib_utils import invoke_process_run_and_check_errors
from xem_wrapper import FrontPanelSimulator

from ..fixtures import fixture_test_process_manager
from ..fixtures_ok_comm import fixture_patch_connection_to_board
from ..fixtures_process_monitor import fixture_test_monitor
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_not_empty
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_test_process_manager,
    fixture_test_monitor,
    fixture_patch_connection_to_board,
]


def test_MantarrayProcessesMonitor__init__calls_super(mocker, test_process_manager):
    error_queue = queue.Queue()
    mocked_super_init = mocker.spy(threading.Thread, "__init__")
    MantarrayProcessesMonitor({}, test_process_manager, error_queue, threading.Lock())
    assert mocked_super_init.call_count == 1


@pytest.mark.timeout(10)
def test_MantarrayProcessesMonitor__soft_stop_calls_manager_soft_stop_and_join(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, _, _, _ = test_monitor
    spied_stop = mocker.spy(test_process_manager, "soft_stop_and_join_processes")
    test_process_manager.spawn_processes()
    monitor_thread.start()
    monitor_thread.soft_stop()
    monitor_thread.join()
    assert spied_stop.call_count == 1


def test_MantarrayProcessesMonitor__logs_messages_from_ok_comm(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    test_process_manager.create_processes()

    ok_comm_to_main = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    expected_comm = {
        "communication_type": "debug_console",
        "command": "get_device_id",
        "response": "my_cool_id",
    }
    ok_comm_to_main.put(expected_comm)
    assert is_queue_eventually_not_empty(ok_comm_to_main) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(ok_comm_to_main) is True
    mocked_logger.assert_called_once_with(
        f"Communication from the OpalKelly Controller: {expected_comm}"
    )


def test_MantarrayProcessesMonitor__logs_messages_from_file_writer(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    test_process_manager.create_processes()

    file_writer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_file_writer_to_main()
    )
    expected_comm = {
        "communication_type": "command_receipt",
        "command": "stop_recording",
        "timepoint_to_stop_recording_at": 223,
    }
    file_writer_to_main.put(expected_comm)
    assert is_queue_eventually_not_empty(file_writer_to_main) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(file_writer_to_main) is True
    mocked_logger.assert_called_once_with(
        f"Communication from the File Writer: {expected_comm}"
    )


def test_MantarrayProcessesMonitor__logs_messages_from_server(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    test_process_manager.create_processes()

    to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": "The Nautilus",
    }

    to_main_queue.put(expected_comm)
    assert is_queue_eventually_not_empty(to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(to_main_queue) is True
    mocked_logger.assert_called_once_with(
        f"Communication from the Server: {expected_comm}"
    )


def test_MantarrayProcessesMonitor__logs_messages_from_data_analyzer(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    test_process_manager.create_processes()

    data_analyzer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_data_analyzer_to_main()
    )
    expected_comm = {
        "communication_type": "finalized_data",
        "well_index": 0,
        "data": np.zeros((2, 10)),
    }
    data_analyzer_to_main.put(expected_comm)
    assert is_queue_eventually_not_empty(data_analyzer_to_main) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(data_analyzer_to_main) is True
    mocked_logger.assert_called_once_with(
        f"Communication from the Data Analyzer: {expected_comm}"
    )


def test_MantarrayProcessesMonitor__logs_errors_from_OKComm(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    test_process_manager.spawn_processes()

    ok_comm_error_queue = (
        test_process_manager.queue_container().get_ok_communication_error_queue()
    )
    expected_error = ValueError("something wrong")
    expected_stack_trace = "my stack trace"
    expected_message = f"Error raised by subprocess {test_process_manager.get_ok_comm_process()}\n{expected_stack_trace}\n{expected_error}"
    ok_comm_error_queue.put((expected_error, expected_stack_trace))
    assert is_queue_eventually_not_empty(ok_comm_error_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(ok_comm_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__logs_errors_from_FileWriter(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    test_process_manager.spawn_processes()

    file_writer_error_queue = (
        test_process_manager.queue_container().get_file_writer_error_queue()
    )
    expected_error = ValueError("something wrong when writing file")
    expected_stack_trace = "my stack trace from writing a file"
    expected_message = f"Error raised by subprocess {test_process_manager.get_file_writer_process()}\n{expected_stack_trace}\n{expected_error}"
    file_writer_error_queue.put((expected_error, expected_stack_trace))
    assert is_queue_eventually_not_empty(file_writer_error_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(file_writer_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__logs_errors_from_DataAnalyzer(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    test_process_manager.spawn_processes()

    data_analyzer_error_queue = (
        test_process_manager.queue_container().get_data_analyzer_error_queue()
    )
    expected_error = ValueError("something wrong when analyzing data")
    expected_stack_trace = "my stack trace from analyzing some data"
    expected_message = f"Error raised by subprocess {test_process_manager.get_data_analyzer_process()}\n{expected_stack_trace}\n{expected_error}"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        (expected_error, expected_stack_trace), data_analyzer_error_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(data_analyzer_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__logs_errors_from_ServerThread(
    mocker, test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    test_process_manager.spawn_processes()

    server_error_queue = test_process_manager.queue_container().get_server_error_queue()
    expected_error = KeyError("something wrong inside the server")
    expected_stack_trace = "my stack trace from deep within the server"
    expected_message = f"Error raised by subprocess {test_process_manager.get_server_thread()}\n{expected_stack_trace}\n{expected_error}"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        (expected_error, expected_stack_trace), server_error_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__hard_stops_and_joins_processes_and_logs_queue_items_when_error_is_raised_in_ok_comm_subprocess(
    mocker, test_process_manager, test_monitor
):
    expected_ok_comm_item = "ok_comm_queue_item"
    expected_file_writer_item = "file_writer_queue_item"
    expected_da_item = "data_analyzer_queue_item"
    expected_server_item = "server_thread_queue_item"

    monitor_thread, _, _, _ = test_monitor

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    test_process_manager.create_processes()
    okc_process = test_process_manager.get_ok_comm_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()
    server_thread = test_process_manager.get_server_thread()
    mocked_okc_join = mocker.patch.object(okc_process, "join", autospec=True)
    mocked_fw_join = mocker.patch.object(fw_process, "join", autospec=True)
    mocked_da_join = mocker.patch.object(da_process, "join", autospec=True)
    mocked_server_join = mocker.patch.object(server_thread, "join", autospec=True)

    ok_comm_error_queue = (
        test_process_manager.queue_container().get_data_analyzer_error_queue()
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        ("error", "stack_trace"), ok_comm_error_queue
    )
    ok_comm_to_main = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_ok_comm_item, ok_comm_to_main
    )
    file_writer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_file_writer_item, file_writer_to_main
    )
    data_analyzer_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_da_item, data_analyzer_to_main
    )
    server_to_main = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_server_item, server_to_main
    )

    invoke_process_run_and_check_errors(monitor_thread)

    mocked_okc_join.assert_called_once()
    mocked_fw_join.assert_called_once()
    mocked_da_join.assert_called_once()
    mocked_server_join.assert_called_once()

    actual = mocked_logger.call_args_list[1][0][0]
    assert "Remaining items in process queues: {" in actual
    assert expected_ok_comm_item in actual
    assert expected_file_writer_item in actual
    assert expected_da_item in actual
    assert expected_server_item in actual


@freeze_time(
    datetime.datetime(
        year=2020, month=2, day=27, hour=12, minute=14, second=22, microsecond=336597
    )
)
def test_MantarrayProcessesMonitor__updates_timestamp_in_shared_values_dict_after_receiving_communication_from_start_acquisition(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    test_process_manager.create_processes()
    queue_command_to_ok_comm(START_MANAGED_ACQUISITION_COMMUNICATION)
    comm_to_ok_comm = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    assert is_queue_eventually_not_empty(comm_to_ok_comm) is True
    ok_comm_process = test_process_manager.get_ok_comm_process()
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()

    ok_comm_process.set_board_connection(0, simulator)

    invoke_process_run_and_check_errors(ok_comm_process)
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"][
        0
    ] == datetime.datetime(
        year=2020, month=2, day=27, hour=12, minute=14, second=22, microsecond=336597
    )


def test_MantarrayProcessesMonitor__correctly_sets_system_status_to_live_view_active_only_when_initial_required_number_of_data_dumps_become_available_from_DataAnalyzer(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    test_process_manager.create_processes()
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
    data_analyzer_process._dump_data_into_queue(  # pylint:disable=protected-access
        dummy_data
    )
    assert is_queue_eventually_not_empty(da_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == BUFFERING_STATE

    data_analyzer_process._dump_data_into_queue(  # pylint:disable=protected-access
        dummy_data
    )
    assert is_queue_eventually_not_empty(da_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == LIVE_VIEW_ACTIVE_STATE

    shared_values_dict["system_status"] = RECORDING_STATE
    data_analyzer_process._dump_data_into_queue(  # pylint:disable=protected-access
        dummy_data
    )
    assert is_queue_eventually_not_empty(da_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == RECORDING_STATE


def test_MantarrayProcessesMonitor__sets_system_status_to_server_ready_after_subprocesses_finish_start_up(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    test_process_manager.create_processes()
    okc_process = test_process_manager.get_ok_comm_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    mocked_okc_started = mocker.patch.object(
        okc_process, "is_start_up_complete", side_effect=[True, True]
    )
    mocked_fw_started = mocker.patch.object(
        fw_process, "is_start_up_complete", side_effect=[True, True]
    )
    mocked_da_started = mocker.patch.object(
        da_process, "is_start_up_complete", side_effect=[False, True]
    )

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

    test_process_manager.create_processes()
    okc_process = test_process_manager.get_ok_comm_process()
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

    test_process_manager.create_processes()
    ok_comm_process = test_process_manager.get_ok_comm_process()
    ok_comm_to_main_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )

    ok_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(ok_comm_to_main_queue) is True

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["in_simulation_mode"] is False


def test_MantarrayProcessesMonitor__sets_in_simulation_mode_to_true_when_connected_to_simulator(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    test_process_manager.create_processes()
    ok_comm_process = test_process_manager.get_ok_comm_process()
    ok_comm_to_main_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )

    ok_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(ok_comm_to_main_queue) is True

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["in_simulation_mode"] is True


def test_MantarrayProcessesMonitor__sets_system_status_to_needs_calibration_after_start_up_script_completes(
    test_monitor, test_process_manager, mocker
):
    mocked_path_str = os.path.join("tests", "test_xem_scripts", "xem_test_start_up.txt")
    mocker.patch.object(
        ok_comm, "resource_path", autospec=True, return_value=mocked_path_str
    )

    monitor_thread, shared_values_dict, _, _ = test_monitor
    test_process_manager.create_processes()
    ok_comm_process = test_process_manager.get_ok_comm_process()
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_comm_process.set_board_connection(0, simulator)

    from_ok_comm_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    to_ok_comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    to_ok_comm_queue.put(
        {"communication_type": "xem_scripts", "script_type": "start_up"}
    )
    assert is_queue_eventually_not_empty(to_ok_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_ok_comm_queue) is True
    # Tanner (6/2/20): num iterations should be 3 here because xem_scripts sends 3 messages to main, and the third one will contain the system status update
    invoke_process_run_and_check_errors(monitor_thread, num_iterations=3)

    assert shared_values_dict["system_status"] == CALIBRATION_NEEDED_STATE


def test_MantarrayProcessesMonitor__sets_system_status_to_calibrated_after_calibration_script_completes(
    test_monitor, test_process_manager, mocker
):
    mocked_path_str = os.path.join(
        "tests", "test_xem_scripts", "xem_test_start_calibration.txt"
    )
    mocker.patch.object(
        ok_comm, "resource_path", autospec=True, return_value=mocked_path_str
    )

    monitor_thread, shared_values_dict, _, _ = test_monitor
    test_process_manager.create_processes()
    ok_comm_process = test_process_manager.get_ok_comm_process()
    simulator = RunningFIFOSimulator()
    simulator.initialize_board()
    ok_comm_process.set_board_connection(0, simulator)

    ok_comm_process = test_process_manager.get_ok_comm_process()
    from_ok_comm_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    to_ok_comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    to_ok_comm_queue.put(
        {"communication_type": "xem_scripts", "script_type": "start_calibration"}
    )
    assert is_queue_eventually_not_empty(to_ok_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_ok_comm_queue) is True
    # Tanner (6/29/20): num iterations should be 51 here because xem_scripts sends 51 total messages, the last one containing the system status update
    invoke_process_run_and_check_errors(monitor_thread, num_iterations=51)

    assert shared_values_dict["system_status"] == CALIBRATED_STATE


def test_MantarrayProcessesMonitor__sets_system_status_to_calibrated_after_managed_acquisition_stops__and_resets_data_dump_buffer_size(
    test_monitor, test_process_manager, mocker
):
    monitor_thread, shared_values_dict, _, _ = test_monitor
    monitor_thread._data_dump_buffer_size = (  # pylint:disable=protected-access
        OUTGOING_DATA_BUFFER_SIZE
    )

    test_process_manager.create_processes()
    ok_comm_process = test_process_manager.get_ok_comm_process()
    from_ok_comm_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    to_ok_comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_comm_process.set_board_connection(0, simulator)

    to_ok_comm_queue.put(
        {
            "communication_type": "acquisition_manager",
            "command": "stop_managed_acquisition",
        }
    )
    assert is_queue_eventually_not_empty(to_ok_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_ok_comm_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == CALIBRATED_STATE
    assert monitor_thread._data_dump_buffer_size == 0  # pylint:disable=protected-access


def test_MantarrayProcessesMonitor__stores_device_information_after_connection(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    test_process_manager.create_processes()
    ok_comm_process = test_process_manager.get_ok_comm_process()
    ok_comm_to_main_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )

    ok_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(ok_comm_to_main_queue) is True

    invoke_process_run_and_check_errors(monitor_thread)

    assert (
        shared_values_dict["xem_serial_number"][0]
        == RunningFIFOSimulator.default_xem_serial_number
    )
    assert (
        shared_values_dict["mantarray_serial_number"][0]
        == RunningFIFOSimulator.default_mantarray_serial_number
    )
    assert (
        shared_values_dict["mantarray_nickname"][0]
        == RunningFIFOSimulator.default_mantarray_nickname
    )


def test_MantarrayProcessesMonitor__calls_boot_up_only_once_after_subprocesses_start_if_boot_up_after_processes_start_is_True(
    test_process_manager, mocker
):
    mocked_boot_up = mocker.patch.object(test_process_manager, "boot_up_instrument")

    shared_values_dict = {"system_status": SERVER_READY_STATE}
    error_queue = error_queue = queue.Queue()
    the_lock = threading.Lock()
    monitor = MantarrayProcessesMonitor(
        shared_values_dict,
        test_process_manager,
        error_queue,
        the_lock,
        boot_up_after_processes_start=True,
    )

    test_process_manager.create_processes()
    invoke_process_run_and_check_errors(monitor)
    assert mocked_boot_up.call_count == 1
    invoke_process_run_and_check_errors(monitor)
    assert mocked_boot_up.call_count == 1


def test_MantarrayProcessesMonitor__doesnt_call_boot_up_after_subprocesses_start_if_boot_up_after_processes_start_is_False(
    test_process_manager, mocker
):
    mocked_boot_up = mocker.patch.object(test_process_manager, "boot_up_instrument")

    shared_values_dict = {"system_status": SERVER_READY_STATE}
    error_queue = error_queue = queue.Queue()
    the_lock = threading.Lock()
    monitor = MantarrayProcessesMonitor(
        shared_values_dict,
        test_process_manager,
        error_queue,
        the_lock,
        boot_up_after_processes_start=False,
    )

    test_process_manager.create_processes()
    invoke_process_run_and_check_errors(monitor)
    assert mocked_boot_up.call_count == 0


def test_MantarrayProcessesMonitor__stores_firmware_versions_during_instrument_boot_up(
    test_monitor, test_process_manager
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    test_process_manager.create_processes()

    okc_process = test_process_manager.get_ok_comm_process()
    to_ok_comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    from_ok_comm_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )

    simulator = RunningFIFOSimulator()
    okc_process.set_board_connection(0, simulator)
    test_process_manager.boot_up_instrument()
    assert is_queue_eventually_not_empty(to_ok_comm_queue) is True
    invoke_process_run_and_check_errors(okc_process)

    assert is_queue_eventually_not_empty(from_ok_comm_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert (
        shared_values_dict["main_firmware_version"][0]
        == RunningFIFOSimulator.default_firmware_version
    )
    assert shared_values_dict["sleep_firmware_version"][0] == "0.0.0"
