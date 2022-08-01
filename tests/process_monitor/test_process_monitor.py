# -*- coding: utf-8 -*-
import copy
import datetime
import json
import os
import queue
from random import choice
import threading
import time

from freezegun import freeze_time
from mantarray_desktop_app import BARCODE_INVALID_UUID
from mantarray_desktop_app import BARCODE_POLL_PERIOD
from mantarray_desktop_app import BARCODE_UNREADABLE_UUID
from mantarray_desktop_app import BARCODE_VALID_UUID
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATED_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_NEEDED_STATE
from mantarray_desktop_app import CHECKING_FOR_UPDATES_STATE
from mantarray_desktop_app import DOWNLOADING_UPDATES_STATE
from mantarray_desktop_app import get_redacted_string
from mantarray_desktop_app import INSTALLING_UPDATES_STATE
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MantarrayProcessesMonitor
from mantarray_desktop_app import OUTGOING_DATA_BUFFER_SIZE
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import SERVER_INITIALIZING_STATE
from mantarray_desktop_app import SERVER_READY_STATE
from mantarray_desktop_app import ServerManager
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import UPDATE_ERROR_STATE
from mantarray_desktop_app import UPDATES_COMPLETE_STATE
from mantarray_desktop_app import UPDATES_NEEDED_STATE
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
from mantarray_desktop_app.exceptions import InstrumentBadDataError
from mantarray_desktop_app.exceptions import InstrumentConnectionLostError
from mantarray_desktop_app.exceptions import InstrumentCreateConnectionError
from mantarray_desktop_app.exceptions import InstrumentFirmwareError
from mantarray_desktop_app.exceptions import SerialCommCommandProcessingError
from mantarray_desktop_app.exceptions import SerialCommCommandResponseTimeoutError
from mantarray_desktop_app.main_process import process_manager
from mantarray_desktop_app.main_process import process_monitor
from mantarray_desktop_app.main_process.server import queue_command_to_instrument_comm
from mantarray_desktop_app.sub_processes import ok_comm
from mantarray_desktop_app.utils.generic import redact_sensitive_info_from_path
import numpy as np
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import TestingQueue
from xem_wrapper import FrontPanelSimulator

from ..fixtures import fixture_patch_print
from ..fixtures import fixture_test_process_manager_creator
from ..fixtures import get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_simulator import create_random_stim_info
from ..fixtures_ok_comm import fixture_patch_connection_to_board
from ..fixtures_process_monitor import fixture_test_monitor
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_not_empty
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_test_process_manager_creator,
    fixture_test_monitor,
    fixture_patch_connection_to_board,
    fixture_patch_print,
]


def test_MantarrayProcessesMonitor__init__calls_super(mocker, test_process_manager_creator):
    test_process_manager = test_process_manager_creator()

    error_queue = queue.Queue()
    mocked_super_init = mocker.spy(threading.Thread, "__init__")
    MantarrayProcessesMonitor({}, test_process_manager, error_queue, threading.Lock())
    assert mocked_super_init.call_count == 1


@pytest.mark.slow
@pytest.mark.timeout(12)
def test_MantarrayProcessesMonitor__soft_stop_calls_manager_soft_stop_and_join(
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator()
    monitor_thread, *_ = test_monitor(test_process_manager)

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


class MantarrayProcessesMonitorThatRaisesError(MantarrayProcessesMonitor):
    def _commands_for_each_run_iteration(self):
        raise NotImplementedError("Process Monitor Exception")


def test_MantarrayProcessesMonitor__populates_error_queue_when_error_raised(
    test_process_manager_creator, patch_print
):
    test_process_manager = test_process_manager_creator()

    error_queue = TestingQueue()
    test_pm = MantarrayProcessesMonitorThatRaisesError(
        {}, test_process_manager, error_queue, threading.Lock()
    )

    with pytest.raises(NotImplementedError, match="Process Monitor Exception"):
        invoke_process_run_and_check_errors(test_pm)


def test_MantarrayProcessesMonitor__logs_errors_raised_in_own_thread_correctly(
    test_process_manager_creator, mocker, patch_print
):
    expected_stack_trace = "expected stack trace"

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)
    mocker.patch.object(
        process_monitor, "get_formatted_stack_trace", autospec=True, return_value=expected_stack_trace
    )

    test_process_manager = test_process_manager_creator()
    error_queue = TestingQueue()
    test_pm = MantarrayProcessesMonitorThatRaisesError(
        {}, test_process_manager, error_queue, threading.Lock()
    )
    test_pm.run(num_iterations=1)

    expected_error = error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_msg = f"Error raised by Process Monitor\n{expected_stack_trace}\n{expected_error}"

    mocked_logger.assert_called_once_with(expected_msg)


def test_MantarrayProcessesMonitor__when_error_raised_in_own_thread__hard_stops_and_joins_subprocesses_if_running_and_shutsdown_server(
    test_process_manager_creator, mocker, patch_print
):
    test_process_manager = test_process_manager_creator()

    mocker.patch.object(
        test_process_manager, "are_subprocess_start_ups_complete", autospec=True, return_value=True
    )
    mocked_hard_stop_processes = mocker.patch.object(
        test_process_manager, "hard_stop_and_join_processes", autospec=True
    )
    mocked_shutdown_server = mocker.patch.object(test_process_manager, "shutdown_server", autospec=True)

    error_queue = TestingQueue()
    test_pm = MantarrayProcessesMonitorThatRaisesError(
        {}, test_process_manager, error_queue, threading.Lock()
    )
    test_pm.run(num_iterations=1)

    mocked_hard_stop_processes.assert_called_once_with(shutdown_server=False)
    mocked_shutdown_server.assert_called_once()


def test_MantarrayProcessesMonitor__when_error_raised_in_own_thread__shutsdown_server_but_not_subprocesses(
    test_process_manager_creator, mocker, patch_print
):
    test_process_manager = test_process_manager_creator()

    mocker.patch.object(
        test_process_manager, "are_subprocess_start_ups_complete", autospec=True, return_value=False
    )
    mocked_hard_stop_processes = mocker.patch.object(
        test_process_manager, "hard_stop_and_join_processes", autospec=True
    )
    mocked_shutdown_server = mocker.patch.object(test_process_manager, "shutdown_server", autospec=True)

    error_queue = TestingQueue()
    test_pm = MantarrayProcessesMonitorThatRaisesError(
        {}, test_process_manager, error_queue, threading.Lock()
    )
    test_pm.run(num_iterations=1)

    mocked_hard_stop_processes.assert_not_called()
    mocked_shutdown_server.assert_called_once()


def test_MantarrayProcessesMonitor__logs_messages_from_instrument_comm(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    instrument_comm_to_main = test_process_manager.queue_container.from_instrument_comm(0)
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


def test_MantarrayProcessesMonitor__logs_messages_from_file_writer__and_redacts_sensitive_info(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    file_writer_to_main = test_process_manager.queue_container.from_file_writer
    expected_comm = {
        "communication_type": "test",
        "file_path": r"Users\Mantarray\AppData\file_path",
        "file_folder": r"Users\Mantarray\AppData\file_folder",
    }
    file_writer_to_main.put_nowait(copy.deepcopy(expected_comm))
    assert is_queue_eventually_not_empty(file_writer_to_main) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(file_writer_to_main) is True

    expected_comm["file_path"] = redact_sensitive_info_from_path(expected_comm["file_path"])
    expected_comm["file_folder"] = redact_sensitive_info_from_path(expected_comm["file_folder"])
    mocked_logger.assert_called_once_with(
        f"Communication from the File Writer: {expected_comm}".replace(r"\\", "\\")
    )


def test_MantarrayProcessesMonitor__logs_messages_from_data_analyzer(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    data_analyzer_to_main = test_process_manager.queue_container.from_data_analyzer
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


def test_MantarrayProcessesMonitor__handled_completed_mag_analysis_command_correctly_from_data_analyzer(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    queue_to_server_ws = test_process_manager.queue_container.to_server

    data_analyzer_to_main = test_process_manager.queue_container.from_data_analyzer
    expected_comm = {
        "communication_type": "mag_analysis_complete",
        "content": {"data_type": "mag_analysis_complete", "data_json": json.dumps([])},
    }
    data_analyzer_to_main.put_nowait(expected_comm)
    assert is_queue_eventually_not_empty(data_analyzer_to_main) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(data_analyzer_to_main) is True
    ws_message = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert ws_message == {
        "data_type": "mag_analysis_complete",
        "data_json": json.dumps([]),
    }


def test_MantarrayProcessesMonitor__pulls_outgoing_data_from_data_analyzer_and_makes_it_available_to_server(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = LIVE_VIEW_ACTIVE_STATE

    da_data_out_queue = test_process_manager.queue_container.data_analyzer_boards[0][1]
    pm_data_out_queue = test_process_manager.queue_container.to_server

    # add dummy data here. In this test, the item is never actually looked at, so it can be any string value
    expected_json_data = json.dumps({"well": 0, "data": [1, 2, 3, 4, 5]})
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_json_data, da_data_out_queue)

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(da_data_out_queue)
    confirm_queue_is_eventually_of_size(pm_data_out_queue, 1)
    actual = pm_data_out_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_json_data


def test_MantarrayProcessesMonitor__passes_update_upload_status_data_to_server(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    fw_data_out_queue = test_process_manager.queue_container.from_file_writer
    pm_data_out_queue = test_process_manager.queue_container.to_server

    expected_content = {"key": "value"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "update_upload_status",
            "content": expected_content,
        },
        fw_data_out_queue,
    )

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(fw_data_out_queue)
    confirm_queue_is_eventually_of_size(pm_data_out_queue, 1)
    actual = pm_data_out_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_content


@pytest.mark.parametrize(
    "test_error,expected_error_sent",
    [
        # base classes
        (InstrumentCreateConnectionError, InstrumentCreateConnectionError),
        (InstrumentConnectionLostError, InstrumentConnectionLostError),
        (InstrumentBadDataError, InstrumentBadDataError),
        (InstrumentFirmwareError, InstrumentFirmwareError),
        # subclasses
        (SerialCommCommandProcessingError, InstrumentBadDataError),
        (SerialCommCommandResponseTimeoutError, InstrumentConnectionLostError),
    ],
)
def test_MantarrayProcessesMonitor__handles_instrument_related_errors_from_instrument_comm_process_correctly(
    test_error, expected_error_sent, mocker, test_process_manager_creator, test_monitor, patch_print
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    ic_process = test_process_manager.instrument_comm_process
    ic_error_queue = test_process_manager.queue_container.instrument_comm_error
    queue_to_server_ws = test_process_manager.queue_container.to_server

    mocker.patch.object(test_process_manager, "hard_stop_and_join_processes", autospec=True)

    mocker.patch.object(
        ic_process, "_commands_for_each_run_iteration", autospec=True, side_effect=test_error()
    )
    ic_process.run(num_iterations=1)
    confirm_queue_is_eventually_of_size(ic_error_queue, 1)

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)

    ws_msg = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert ws_msg == {
        "data_type": "error",
        "data_json": json.dumps({"error_type": expected_error_sent.__name__}),
    }


@pytest.mark.parametrize(
    "test_system_status", [DOWNLOADING_UPDATES_STATE, INSTALLING_UPDATES_STATE, "anything else"]
)
def test_MantarrayProcessesMonitor__handles_non_instrument_related_errors_from_instrument_comm_process_correctly(
    test_system_status, mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = test_system_status
    ic_error_queue = test_process_manager.queue_container.instrument_comm_error

    mocked_hard_stop_and_join = mocker.patch.object(
        test_process_manager, "hard_stop_and_join_processes", autospec=True
    )

    is_fw_update_error = test_system_status in (
        DOWNLOADING_UPDATES_STATE,
        INSTALLING_UPDATES_STATE,
    )
    expected_system_status = UPDATE_ERROR_STATE if is_fw_update_error else test_system_status

    error_tuple = (Exception(), "error")
    put_object_into_queue_and_raise_error_if_eventually_still_empty(error_tuple, ic_error_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == expected_system_status
    mocked_hard_stop_and_join.assert_called_once_with(shutdown_server=not is_fw_update_error)


def test_MantarrayProcessesMonitor__logs_errors_from_instrument_comm_process(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)
    mocker.patch.object(test_process_manager, "hard_stop_and_join_processes", autospec=True)

    instrument_comm_error_queue = test_process_manager.queue_container.instrument_comm_error
    expected_error = ValueError("something wrong")
    expected_stack_trace = "my stack trace"
    expected_message = f"Error raised by subprocess {test_process_manager.instrument_comm_process}\n{expected_stack_trace}\n{expected_error}"
    instrument_comm_error_queue.put_nowait((expected_error, expected_stack_trace))
    assert is_queue_eventually_not_empty(instrument_comm_error_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(instrument_comm_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__logs_errors_from_file_writer(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)
    mocker.patch.object(test_process_manager, "hard_stop_and_join_processes", autospec=True)

    file_writer_error_queue = test_process_manager.queue_container.file_writer_error
    expected_error = ValueError("something wrong when writing file")
    expected_stack_trace = "my stack trace from writing a file"
    expected_message = f"Error raised by subprocess {test_process_manager.file_writer_process}\n{expected_stack_trace}\n{expected_error}"
    file_writer_error_queue.put_nowait((expected_error, expected_stack_trace))
    assert is_queue_eventually_not_empty(file_writer_error_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(file_writer_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__logs_errors_from_data_analyzer(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)
    mocker.patch.object(test_process_manager, "hard_stop_and_join_processes", autospec=True)

    data_analyzer_error_queue = test_process_manager.queue_container.data_analyzer_error
    expected_error = ValueError("something wrong when analyzing data")
    expected_stack_trace = "my stack trace from analyzing some data"
    expected_message = f"Error raised by subprocess {test_process_manager.data_analyzer_process}\n{expected_stack_trace}\n{expected_error}"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        (expected_error, expected_stack_trace), data_analyzer_error_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(data_analyzer_error_queue) is True
    mocked_logger.assert_any_call(expected_message)


def test_MantarrayProcessesMonitor__hard_stops_and_joins_processes_and_logs_queue_items_when_error_is_raised_in_ok_comm_subprocess(
    mocker, test_process_manager_creator, test_monitor
):
    expected_ok_comm_item = f"ok_comm_queue_item, {str(bytes(4))}"
    expected_file_writer_item = "file_writer_queue_item"
    expected_da_item = "data_analyzer_queue_item"
    expected_server_item = "server_manager_queue_item"

    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    # mock since processes aren't actually started
    mocker.patch.object(process_manager, "_process_can_be_joined", autospec=True, return_value=True)
    mocker.patch.object(process_manager, "_process_failed_to_join", autospec=True, return_value=False)

    mocked_logger = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    okc_process = test_process_manager.instrument_comm_process
    fw_process = test_process_manager.file_writer_process
    da_process = test_process_manager.data_analyzer_process
    server_manager = test_process_manager.server_manager
    mocked_okc_join = mocker.patch.object(okc_process, "join", autospec=True)
    mocked_fw_join = mocker.patch.object(fw_process, "join", autospec=True)
    mocked_da_join = mocker.patch.object(da_process, "join", autospec=True)
    mocked_shutdown_server = mocker.patch.object(server_manager, "shutdown_server", autospec=True)

    ok_comm_error_queue = test_process_manager.queue_container.data_analyzer_error
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        ("error", "stack_trace"), ok_comm_error_queue
    )
    to_instrument_comm = test_process_manager.queue_container.to_instrument_comm(0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_ok_comm_item, to_instrument_comm)
    to_file_writer = test_process_manager.queue_container.to_file_writer
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_file_writer_item, to_file_writer)
    to_data_analyzer = test_process_manager.queue_container.to_data_analyzer
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_da_item, to_data_analyzer)
    server_to_main = test_process_manager.queue_container.from_server
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
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    queue_command_to_instrument_comm(get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION())
    comm_to_instrument_comm = test_process_manager.queue_container.to_instrument_comm(0)
    assert is_queue_eventually_not_empty(comm_to_instrument_comm) is True
    ok_comm_process = test_process_manager.instrument_comm_process
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()

    ok_comm_process.set_board_connection(0, simulator)

    invoke_process_run_and_check_errors(ok_comm_process)
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["utc_timestamps_of_beginning_of_data_acquisition"][0] == datetime.datetime(
        year=2020, month=2, day=27, hour=12, minute=14, second=22, microsecond=336597
    )


def test_MantarrayProcessesMonitor__correctly_sets_system_status_to_live_view_active_only_when_initial_required_number_of_data_dumps_become_available_from_data_analyzer(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    data_analyzer_process = test_process_manager.data_analyzer_process
    da_to_main_queue = test_process_manager.queue_container.from_data_analyzer

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
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    okc_process = test_process_manager.instrument_comm_process
    fw_process = test_process_manager.file_writer_process
    da_process = test_process_manager.data_analyzer_process

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
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    expected_system_status = CALIBRATION_NEEDED_STATE
    shared_values_dict["system_status"] = expected_system_status

    okc_process = test_process_manager.instrument_comm_process
    fw_process = test_process_manager.file_writer_process
    da_process = test_process_manager.data_analyzer_process

    spied_okc_started = mocker.spy(okc_process, "is_start_up_complete")
    spied_fw_started = mocker.spy(fw_process, "is_start_up_complete")
    spied_da_started = mocker.spy(da_process, "is_start_up_complete")

    invoke_process_run_and_check_errors(monitor_thread)
    assert spied_okc_started.call_count == 0
    assert spied_fw_started.call_count == 0
    assert spied_da_started.call_count == 0
    assert shared_values_dict["system_status"] == expected_system_status


def test_MantarrayProcessesMonitor__sets_in_simulation_mode_to_false_when_connected_to_real_board(
    patch_connection_to_board, test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    ok_comm_process = test_process_manager.instrument_comm_process
    container = test_process_manager.queue_container
    instrument_comm_to_main_queue = container.from_instrument_comm(0)

    ok_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(instrument_comm_to_main_queue) is True

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["in_simulation_mode"] is False


def test_MantarrayProcessesMonitor__sets_in_simulation_mode_to_true_when_connected_to_simulator(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    ok_comm_process = test_process_manager.instrument_comm_process
    instrument_comm_to_main_queue = test_process_manager.queue_container.from_instrument_comm(0)

    ok_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(instrument_comm_to_main_queue) is True

    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["in_simulation_mode"] is True


def test_MantarrayProcessesMonitor__sets_system_status_to_needs_calibration_after_start_up_script_completes(
    test_monitor, test_process_manager_creator, mocker
):
    mocked_path_str = os.path.join("tests", "test_xem_scripts", "xem_test_start_up.txt")
    mocker.patch.object(ok_comm, "resource_path", autospec=True, return_value=mocked_path_str)

    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    ok_comm_process = test_process_manager.instrument_comm_process
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_comm_process.set_board_connection(0, simulator)

    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(0)
    to_instrument_comm_queue = test_process_manager.queue_container.to_instrument_comm(0)
    to_instrument_comm_queue.put_nowait({"communication_type": "xem_scripts", "script_type": "start_up"})
    assert is_queue_eventually_not_empty(to_instrument_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_instrument_comm_queue) is True
    # Tanner (6/2/20): number of iterations should be 3 here because xem_scripts sends 3 messages to main, and the third one will contain the system status update
    invoke_process_run_and_check_errors(monitor_thread, num_iterations=3)

    assert shared_values_dict["system_status"] == CALIBRATION_NEEDED_STATE


def test_MantarrayProcessesMonitor__sets_system_status_to_calibrated_after_calibration_script_completes(
    test_monitor, test_process_manager_creator, mocker
):
    mocked_path_str = os.path.join("tests", "test_xem_scripts", "xem_test_start_calibration.txt")
    mocker.patch.object(ok_comm, "resource_path", autospec=True, return_value=mocked_path_str)

    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    ok_comm_process = test_process_manager.instrument_comm_process
    simulator = RunningFIFOSimulator()
    simulator.initialize_board()
    ok_comm_process.set_board_connection(0, simulator)

    ok_comm_process = test_process_manager.instrument_comm_process
    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(0)
    to_instrument_comm_queue = test_process_manager.queue_container.to_instrument_comm(0)
    to_instrument_comm_queue.put_nowait(
        {"communication_type": "xem_scripts", "script_type": "start_calibration"}
    )
    assert is_queue_eventually_not_empty(to_instrument_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_instrument_comm_queue) is True
    # Tanner (6/29/20): number of iterations should be 51 here because xem_scripts sends 51 total messages, the last one containing the system status update
    invoke_process_run_and_check_errors(monitor_thread, num_iterations=51)

    assert shared_values_dict["system_status"] == CALIBRATED_STATE


def test_MantarrayProcessesMonitor__after_beta_2_calibration_files_are_finalized__sets_system_status_to_calibrated_and_stops_managed_acquisition(
    test_monitor, test_process_manager_creator, mocker
):
    board_idx = 0
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = CALIBRATING_STATE

    from_file_writer_queue = test_process_manager.queue_container.from_file_writer
    to_instrument_comm_queue = test_process_manager.queue_container.to_instrument_comm(board_idx)
    to_file_writer_queue = test_process_manager.queue_container.to_file_writer

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "file_finalized", "message": "all_finals_finalized"}, from_file_writer_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == CALIBRATED_STATE

    expected_comm = dict(STOP_MANAGED_ACQUISITION_COMMUNICATION)
    expected_comm["is_calibration_recording"] = True

    confirm_queue_is_eventually_of_size(to_instrument_comm_queue, 1)
    assert to_instrument_comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_comm
    confirm_queue_is_eventually_of_size(to_file_writer_queue, 1)
    assert to_file_writer_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_comm


def test_MantarrayProcessesMonitor__sets_system_status_to_calibrated_after_managed_acquisition_stops__and_resets_data_dump_buffer_size(
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    monitor_thread._data_dump_buffer_size = OUTGOING_DATA_BUFFER_SIZE  # pylint:disable=protected-access

    ok_comm_process = test_process_manager.instrument_comm_process
    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(0)
    to_instrument_comm_queue = test_process_manager.queue_container.to_instrument_comm(0)

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
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    ok_comm_process = test_process_manager.instrument_comm_process
    instrument_comm_to_main_queue = test_process_manager.queue_container.from_instrument_comm(0)

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
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    mc_comm_process = test_process_manager.instrument_comm_process
    instrument_comm_to_main_queue = test_process_manager.queue_container.from_instrument_comm(0)

    mc_comm_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(instrument_comm_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["in_simulation_mode"] is True


def test_MantarrayProcessesMonitor__stores_device_information_from_metadata_comm__and_redacts_nickname_from_log_message(
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    spied_info = mocker.spy(process_monitor.logger, "info")

    board_idx = 0
    instrument_comm_to_main_queue = test_process_manager.queue_container.from_instrument_comm(board_idx)

    metadata_dict = dict(MantarrayMcSimulator.default_metadata_values)
    metadata_dict.update({"status_codes_prior_to_reboot": {"status": "codes"}, "any": "any"})
    metadata_comm_dict = {
        "communication_type": "metadata_comm",
        "command": "get_metadata",
        "metadata": metadata_dict,
        "board_index": board_idx,
    }
    instrument_comm_to_main_queue.put_nowait(metadata_comm_dict)
    assert is_queue_eventually_not_empty(instrument_comm_to_main_queue) is True
    invoke_process_run_and_check_errors(monitor_thread)

    assert (
        shared_values_dict["main_firmware_version"][board_idx]
        == MantarrayMcSimulator.default_main_firmware_version
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

    for call_args in spied_info.call_args_list:
        assert MantarrayMcSimulator.default_mantarray_nickname not in call_args[0][0]


def test_MantarrayProcessesMonitor__does_not_switch_from_INSTRUMENT_INITIALIZING_STATE__in_beta_2_mode_if_required_values_are_not_set(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = INSTRUMENT_INITIALIZING_STATE

    # confirm preconditions
    assert "in_simulation_mode" not in shared_values_dict
    assert "instrument_metadata" not in shared_values_dict

    # run monitor_thread with only in_simulation_mode missing and make sure no state transition occurs
    shared_values_dict["latest_software_version"] = "1.0.0"
    shared_values_dict["instrument_metadata"] = {}
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == INSTRUMENT_INITIALIZING_STATE
    # run monitor_thread with only instrument_metadata missing and make sure no state transition occurs
    del shared_values_dict["instrument_metadata"]
    shared_values_dict["in_simulation_mode"] = True
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == INSTRUMENT_INITIALIZING_STATE
    # run monitor_thread with only latest_software_version missing while not in simulation mode and make sure no state transition occurs
    shared_values_dict["latest_software_version"] = None
    shared_values_dict["instrument_metadata"] = {}
    shared_values_dict["in_simulation_mode"] = False
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == INSTRUMENT_INITIALIZING_STATE


def test_MantarrayProcessesMonitor__enables_sw_auto_install_when_reaching_CALIBRATION_NEEDED_STATE_in_beta_1_mode(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = CALIBRATING_STATE

    board_idx = 0
    from_ic_queue = test_process_manager.queue_container.from_instrument_comm(board_idx)
    queue_to_server_ws = test_process_manager.queue_container.to_server

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "xem_scripts", "status_update": CALIBRATION_NEEDED_STATE}, from_ic_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == CALIBRATION_NEEDED_STATE

    confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)
    ws_message = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert ws_message == {
        "data_type": "sw_update",
        "data_json": json.dumps({"allow_software_update": True}),
    }


@pytest.mark.parametrize(
    "test_simulation_mode,expected_state",
    [(True, CALIBRATION_NEEDED_STATE), (False, CHECKING_FOR_UPDATES_STATE)],
)
def test_MantarrayProcessesMonitor__handles_switch_from_INSTRUMENT_INITIALIZING_STATE_in_beta_2_mode_correctly(
    test_monitor, test_process_manager_creator, test_simulation_mode, expected_state
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = INSTRUMENT_INITIALIZING_STATE

    shared_values_dict["in_simulation_mode"] = test_simulation_mode
    board_idx = 0

    # set other values in shared values dict that would allow for a state transition
    test_serial_number = MantarrayMcSimulator.default_mantarray_serial_number
    test_sw_version = "2.2.2"
    shared_values_dict["instrument_metadata"] = {
        board_idx: {MANTARRAY_SERIAL_NUMBER_UUID: test_serial_number}
    }
    shared_values_dict["latest_software_version"] = test_sw_version

    # run monitor_thread and make sure no state transition occurs
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == expected_state

    to_instrument_comm_queue = test_process_manager.queue_container.to_instrument_comm(board_idx)
    if test_simulation_mode:
        confirm_queue_is_eventually_empty(to_instrument_comm_queue)
    else:
        confirm_queue_is_eventually_of_size(to_instrument_comm_queue, 1)
        command_to_ic = to_instrument_comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert command_to_ic == {
            "communication_type": "firmware_update",
            "command": "get_latest_firmware_versions",
            "serial_number": test_serial_number,
        }


@pytest.mark.parametrize(
    "required_sw_version_available,expected_state_from_sw", [(True, None), (False, CALIBRATION_NEEDED_STATE)]
)
@pytest.mark.parametrize(
    "error,main_fw_update,channel_fw_update,expected_state_from_fw",
    [
        (True, False, False, CALIBRATION_NEEDED_STATE),
        (False, False, False, CALIBRATION_NEEDED_STATE),
        (False, True, False, UPDATES_NEEDED_STATE),
        (False, False, True, UPDATES_NEEDED_STATE),
        (False, True, True, UPDATES_NEEDED_STATE),
    ],
)
def test_MantarrayProcessesMonitor__handles_switch_from_CHECKING_FOR_UPDATES_STATE_in_beta_2_mode_correctly(
    test_monitor,
    test_process_manager_creator,
    error,
    required_sw_version_available,
    main_fw_update,
    channel_fw_update,
    expected_state_from_sw,
    expected_state_from_fw,
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = CHECKING_FOR_UPDATES_STATE

    board_idx = 0
    from_ic_queue = test_process_manager.queue_container.from_instrument_comm(board_idx)
    to_ic_queue = test_process_manager.queue_container.to_instrument_comm(board_idx)
    queue_to_server_ws = test_process_manager.queue_container.to_server

    expected_state = expected_state_from_sw or expected_state_from_fw

    test_current_version = "0.0.0"
    test_new_version = "1.0.0"

    new_main_fw_version = test_new_version if main_fw_update else None
    new_channel_fw_version = test_new_version if channel_fw_update else None

    shared_values_dict["latest_software_version"] = (
        test_new_version if required_sw_version_available else test_current_version
    )
    shared_values_dict["instrument_metadata"] = {
        board_idx: {
            MAIN_FIRMWARE_VERSION_UUID: test_current_version,
            CHANNEL_FIRMWARE_VERSION_UUID: test_current_version,
            MANTARRAY_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_mantarray_serial_number,
        }
    }

    # set up command response
    test_command_response = {
        "communication_type": "firmware_update",
        "command": "get_latest_firmware_versions",
    }
    if error:
        test_command_response["error"] = "some error msg"
    else:
        test_command_response["latest_versions"] = {
            "main-fw": test_new_version if main_fw_update else test_current_version,
            "channel-fw": test_new_version if channel_fw_update else test_current_version,
            "sw": test_new_version,
        }
    # process command response
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command_response, from_ic_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    # check that the system state is correct
    assert shared_values_dict["system_status"] == expected_state
    # check that firmware updating status is stored in shared values dict
    if shared_values_dict["system_status"] == UPDATES_NEEDED_STATE:
        assert shared_values_dict["firmware_updates_needed"] == {
            "main": new_main_fw_version,
            "channel": new_channel_fw_version,
        }

    if shared_values_dict["system_status"] == CALIBRATION_NEEDED_STATE:
        # make sure command not sent to mc_comm
        confirm_queue_is_eventually_empty(to_ic_queue)
        # make sure ws message is handled correctly
        if error:
            confirm_queue_is_eventually_empty(queue_to_server_ws)
        else:
            confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)
            ws_message = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
            assert ws_message == {
                "data_type": "sw_update",
                "data_json": json.dumps({"allow_software_update": True}),
            }
    elif shared_values_dict["system_status"] == UPDATES_NEEDED_STATE:
        # make sure no commands sent to mc_comm yet
        confirm_queue_is_eventually_empty(to_ic_queue)
        # make sure correct ws message is sent
        confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)
        ws_message = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert ws_message == {
            "data_type": "fw_update",
            "data_json": json.dumps(
                {"firmware_update_available": True, "channel_fw_update": channel_fw_update}
            ),
        }


@pytest.mark.parametrize("user_creds_already_stored", [True, False])
@pytest.mark.parametrize("update_accepted", [True, False])
def test_MantarrayProcessesMonitor__handles_switch_from_UPDATES_NEEDED_STATE_in_beta_2_mode_correctly(
    update_accepted, user_creds_already_stored, test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = UPDATES_NEEDED_STATE

    test_customer_id = "id"
    test_user_name = "un"
    test_user_password = "pw"

    user_creds = {
        "customer_id": test_customer_id,
        "user_name": test_user_name,
        "user_password": test_user_password,
    }

    new_main_fw_version = "1.1.0"
    new_channel_fw_version = None
    shared_values_dict["firmware_updates_needed"] = {
        "main": new_main_fw_version,
        "channel": new_channel_fw_version,
    }
    if user_creds_already_stored:
        shared_values_dict["user_creds"] = user_creds

    board_idx = 0
    to_ic_queue = test_process_manager.queue_container.to_instrument_comm(board_idx)

    # run one iteration before customer creds stored
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == UPDATES_NEEDED_STATE
    confirm_queue_is_eventually_empty(to_ic_queue)
    # store update accepted value but not customer creds
    shared_values_dict["firmware_update_accepted"] = update_accepted
    if not update_accepted:
        invoke_process_run_and_check_errors(monitor_thread)
        assert shared_values_dict["system_status"] == CALIBRATION_NEEDED_STATE
        # if update was declined, the rest of this test can be skipped
        return

    assert shared_values_dict["system_status"] == UPDATES_NEEDED_STATE
    # store customer creds and run one more iteration
    if not user_creds_already_stored:
        # confirm precondition
        assert "user_creds" not in shared_values_dict
        # make sure user input prompt message is sent only once
        invoke_process_run_and_check_errors(monitor_thread, num_iterations=2)
        queue_to_server_ws = test_process_manager.queue_container.to_server
        confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)
        assert queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == {
            "data_type": "prompt_user_input",
            "data_json": json.dumps({"input_type": "user_creds"}),
        }
        # run another iteration to make sure system_status is not updated
        invoke_process_run_and_check_errors(monitor_thread)
        assert shared_values_dict["system_status"] == UPDATES_NEEDED_STATE
        shared_values_dict["user_creds"] = user_creds
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == DOWNLOADING_UPDATES_STATE
    confirm_queue_is_eventually_of_size(to_ic_queue, 1)
    start_firmware_download_command = to_ic_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert start_firmware_download_command == {
        "communication_type": "firmware_update",
        "command": "download_firmware_updates",
        "main": new_main_fw_version,
        "channel": new_channel_fw_version,
        "customer_id": test_customer_id,
        "username": test_user_name,
        "password": test_user_password,
    }


@pytest.mark.parametrize(
    "main_fw_update,channel_fw_update",
    [(False, True), (True, False), (True, True)],
)
@pytest.mark.parametrize(
    "error,expected_state",
    [(True, UPDATE_ERROR_STATE), (False, INSTALLING_UPDATES_STATE)],
)
def test_MantarrayProcessesMonitor__handles_switch_from_DOWNLOADING_UPDATES_STATE_in_beta_2_mode_correctly(
    main_fw_update,
    channel_fw_update,
    error,
    expected_state,
    test_monitor,
    test_process_manager_creator,
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = DOWNLOADING_UPDATES_STATE
    shared_values_dict["firmware_updates_needed"] = {
        "main": "1.0.0" if main_fw_update else None,
        "channel": "1.0.0" if channel_fw_update else None,
    }

    board_idx = 0
    from_ic_queue = test_process_manager.queue_container.from_instrument_comm(board_idx)
    to_ic_queue = test_process_manager.queue_container.to_instrument_comm(board_idx)

    test_command_response = {
        "communication_type": "firmware_update",
        "command": "download_firmware_updates",
    }
    if error:
        test_command_response["error"] = "error"
    else:
        test_command_response["message"] = "any"

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command_response, from_ic_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["system_status"] == expected_state
    if error:
        confirm_queue_is_eventually_empty(to_ic_queue)
    else:
        # make sure one or both commands are sent. If both sent, make sure channel is sent first
        expected_commands = [
            {
                "communication_type": "firmware_update",
                "command": "start_firmware_update",
                "firmware_type": firmware_type,
            }
            for firmware_type, update_needed in [("channel", channel_fw_update), ("main", main_fw_update)]
            if update_needed
        ]
        confirm_queue_is_eventually_of_size(to_ic_queue, len(expected_commands))
        actual_commands = drain_queue(to_ic_queue)
        assert actual_commands == expected_commands


@pytest.mark.parametrize(
    "main_fw_update,channel_fw_update",
    [(False, True), (True, False), (True, True)],
)
def test_MantarrayProcessesMonitor__handles_firmware_update_completed_commands_correctly(
    main_fw_update, channel_fw_update, test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = INSTALLING_UPDATES_STATE
    shared_values_dict["firmware_updates_needed"] = {
        "main": "1.0.0" if main_fw_update else None,
        "channel": "1.0.0" if channel_fw_update else None,
    }

    board_idx = 0
    from_ic_queue = test_process_manager.queue_container.from_instrument_comm(board_idx)
    queue_to_server_ws = test_process_manager.queue_container.to_server

    command_responses = [
        {
            "communication_type": "firmware_update",
            "command": "update_completed",
            "firmware_type": firmware_type,
        }
        for firmware_type, update_needed in [("channel", channel_fw_update), ("main", main_fw_update)]
        if update_needed
    ]

    handle_putting_multiple_objects_into_empty_queue(command_responses, from_ic_queue)

    # make sure system_status is not updated and no ws message sent until all command responses are received
    for command_response_num in range(len(command_responses)):
        confirm_queue_is_eventually_empty(queue_to_server_ws)
        assert shared_values_dict["system_status"] == INSTALLING_UPDATES_STATE, command_response_num
        invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["system_status"] == UPDATES_COMPLETE_STATE
    # check that this gets reset
    assert shared_values_dict["firmware_updates_needed"] == {"main": None, "channel": None}
    # make sure that correct ws message is sent
    confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)
    ws_message = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert ws_message == {
        "data_type": "sw_update",
        "data_json": json.dumps({"allow_software_update": True}),
    }


def test_MantarrayProcessesMonitor__ignores_start_firmware_update_command_response(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(beta_2_mode=True, use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = INSTALLING_UPDATES_STATE

    board_idx = 0
    from_ic_queue = test_process_manager.queue_container.from_instrument_comm(board_idx)

    command_response = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": "main",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(command_response, from_ic_queue)
    # run monitor_thread to make sure no errors occur
    invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__calls_boot_up_only_once_after_subprocesses_start_if_boot_up_after_processes_start_is_True(
    test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    mocked_boot_up = mocker.patch.object(test_process_manager, "boot_up_instrument")

    shared_values_dict = {"system_status": SERVER_READY_STATE, "beta_2_mode": False}
    error_queue = TestingQueue()
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
    test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    mocked_boot_up = mocker.patch.object(test_process_manager, "boot_up_instrument")

    shared_values_dict = {"system_status": SERVER_READY_STATE, "beta_2_mode": False}
    error_queue = TestingQueue()
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


def test_MantarrayProcessesMonitor__calls_boot_up_instrument_with_load_firmware_file_False_if_given_in_init__when_boot_up_after_processes_start_is_True(
    test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    mocked_boot_up = mocker.patch.object(test_process_manager, "boot_up_instrument")

    shared_values_dict = {"system_status": SERVER_READY_STATE, "beta_2_mode": False}
    error_queue = TestingQueue()
    the_lock = threading.Lock()
    monitor = MantarrayProcessesMonitor(
        shared_values_dict,
        test_process_manager,
        error_queue,
        the_lock,
        boot_up_after_processes_start=True,
        load_firmware_file=False,
    )

    invoke_process_run_and_check_errors(monitor)
    assert mocked_boot_up.call_count == 1
    assert mocked_boot_up.call_args[1]["load_firmware_file"] is False


def test_MantarrayProcessesMonitor__stores_firmware_versions_during_instrument_boot_up(
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    # Tanner (12/28/20): RunningFIFOSimulator ignores the name of bit file given, so we can mock this out so it will pass in Cloud9
    mocker.patch.object(process_manager, "get_latest_firmware", autospec=True, return_value=None)

    okc_process = test_process_manager.instrument_comm_process
    to_instrument_comm_queue = test_process_manager.queue_container.to_instrument_comm(0)
    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(0)

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
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    spied_info = mocker.spy(process_monitor.logger, "info")

    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(0)

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
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    spied_info = mocker.spy(process_monitor.logger, "info")

    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(0)

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
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    spied_info = mocker.spy(process_monitor.logger, "info")

    from_file_writer_queue = test_process_manager.queue_container.from_file_writer

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
    test_monitor, test_process_manager_creator, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    to_instrument_comm_queue = test_process_manager.queue_container.to_instrument_comm(0)

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

    expected_comm = {"communication_type": "barcode_comm", "command": "start_scan"}

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
    "expected_plate_barcode,test_valid,expected_status,test_description",
    [
        (
            MantarrayMcSimulator.default_plate_barcode,
            True,
            BARCODE_VALID_UUID,
            "stores new valid plate barcode",
        ),
        (
            MantarrayMcSimulator.default_stim_barcode,
            True,
            BARCODE_VALID_UUID,
            "stores new valid stim barcode",
        ),
        ("M$200190000", False, BARCODE_INVALID_UUID, "stores new invalid barcode"),
        ("", None, BARCODE_UNREADABLE_UUID, "stores no barcode"),
    ],
)
def test_MantarrayProcessesMonitor__stores_barcode_sent_from_instrument_comm__and_sends_barcode_update_message_to_frontend__when_no_previously_stored_barcode(
    expected_plate_barcode,
    test_valid,
    expected_status,
    test_description,
    test_monitor,
    test_process_manager_creator,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    expected_board_idx = 0
    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(expected_board_idx)
    queue_to_server_ws = test_process_manager.queue_container.to_server

    barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_plate_barcode,
        "board_idx": expected_board_idx,
    }
    if test_valid is not None:
        barcode_comm["valid"] = test_valid
    if test_valid is False:
        # specifically want test_valid to be False here, not None since invalid barcodes have trailing `\x00`
        barcode_comm["barcode"] += chr(0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(barcode_comm, from_instrument_comm_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    # check shared values dict was updated
    barcode_type = (
        "stim_barcode"
        if expected_plate_barcode == MantarrayMcSimulator.default_stim_barcode
        else "plate_barcode"
    )
    expected_barcode_dict = {barcode_type: expected_plate_barcode, "barcode_status": expected_status}
    assert shared_values_dict["barcodes"][expected_board_idx] == expected_barcode_dict
    # check message was put into queue
    expected_barcode_dict["barcode_status"] = str(expected_barcode_dict["barcode_status"])
    expected_barcode_message = {"data_type": "barcode", "data_json": json.dumps(expected_barcode_dict)}
    confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)
    barcode_msg = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert barcode_msg == expected_barcode_message


@pytest.mark.parametrize(
    "expected_plate_barcode,test_valid,expected_status,test_description",
    [
        (
            MantarrayMcSimulator.default_plate_barcode,
            True,
            BARCODE_VALID_UUID,
            "updates to new valid plate barcode",
        ),
        (
            MantarrayMcSimulator.default_stim_barcode,
            True,
            BARCODE_VALID_UUID,
            "updates to new valid stim barcode",
        ),
        ("M$200190000", False, BARCODE_INVALID_UUID, "updates to new invalid barcode"),
        ("", None, BARCODE_UNREADABLE_UUID, "updates to no barcode"),
    ],
)
def test_MantarrayProcessesMonitor__updates_to_new_barcode_sent_from_instrument_comm__and_sends_barcode_update_message_to_frontend(
    expected_plate_barcode,
    test_valid,
    expected_status,
    test_description,
    test_monitor,
    test_process_manager_creator,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    expected_board_idx = 0
    barcode_type = (
        "stim_barcode"
        if expected_plate_barcode == MantarrayMcSimulator.default_stim_barcode
        else "plate_barcode"
    )
    shared_values_dict["barcodes"] = {
        expected_board_idx: {barcode_type: "old barcode", "barcode_status": None}
    }

    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(expected_board_idx)
    queue_to_server_ws = test_process_manager.queue_container.to_server

    barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_plate_barcode,
        "board_idx": expected_board_idx,
    }
    if test_valid is not None:
        barcode_comm["valid"] = test_valid
    if test_valid is False:
        # specifically want test_valid to be False here, not None since invalid barcodes have trailing `\x00`
        barcode_comm["barcode"] += chr(0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(barcode_comm, from_instrument_comm_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    expected_barcode_dict = {barcode_type: expected_plate_barcode, "barcode_status": expected_status}
    assert shared_values_dict["barcodes"][expected_board_idx] == expected_barcode_dict
    # check message was put into queue
    expected_barcode_dict["barcode_status"] = str(expected_barcode_dict["barcode_status"])
    expected_barcode_message = {"data_type": "barcode", "data_json": json.dumps(expected_barcode_dict)}
    confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)
    barcode_msg = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert barcode_msg == expected_barcode_message


@pytest.mark.parametrize(
    "expected_plate_barcode,test_valid,test_description",
    [
        (
            MantarrayMcSimulator.default_plate_barcode,
            True,
            "does not update to current valid plate barcode",
        ),
        (
            MantarrayMcSimulator.default_stim_barcode,
            True,
            "does not update to current valid stim barcode",
        ),
        ("M$200190000", False, "does not update to current invalid barcode"),
        ("", None, "does not update to current empty barcode"),
    ],
)
def test_MantarrayProcessesMonitor__does_not_update_any_values_or_send_barcode_update_to_frontend__if_new_barcode_matches_current_barcode(
    expected_plate_barcode,
    test_valid,
    test_description,
    test_monitor,
    test_process_manager_creator,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    expected_board_idx = 0
    barcode_type = (
        "stim_barcode"
        if expected_plate_barcode == MantarrayMcSimulator.default_stim_barcode
        else "plate_barcode"
    )
    expected_dict = {barcode_type: expected_plate_barcode, "barcode_status": None}
    shared_values_dict["barcodes"] = {expected_board_idx: expected_dict}

    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(expected_board_idx)
    queue_to_server_ws = test_process_manager.queue_container.to_server

    barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_plate_barcode,
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
    confirm_queue_is_eventually_empty(queue_to_server_ws)


def test_MantarrayProcessesMonitor__trims_beta_1_plate_barcode_string_before_storing_in_shared_values_dict(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    expected_board_idx = 0
    from_instrument_comm_queue = test_process_manager.queue_container.from_instrument_comm(expected_board_idx)

    expected_plate_barcode = "M020090048"
    barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_plate_barcode + chr(0) * 2,
        "board_idx": expected_board_idx,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(barcode_comm, from_instrument_comm_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    assert shared_values_dict["barcodes"][expected_board_idx]["plate_barcode"] == expected_plate_barcode


def test_MantarrayProcessesMonitor__redacts_mantarray_nickname_from_logged_mantarray_naming_ok_comm_messages(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    instrument_comm_to_main = test_process_manager.queue_container.from_instrument_comm(0)

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
    expected_comm["mantarray_nickname"] = get_redacted_string(len(test_nickname))
    mocked_logger.assert_called_once_with(f"Communication from the Instrument Controller: {expected_comm}")


def test_MantarrayProcessesMonitor__redacts_mantarray_nickname_from_logged_board_connection_status_change_ok_comm_messages(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    instrument_comm_to_main = test_process_manager.queue_container.from_instrument_comm(0)

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
    expected_comm["mantarray_nickname"] = get_redacted_string(len(test_nickname))
    mocked_logger.assert_called_once_with(f"Communication from the Instrument Controller: {expected_comm}")


def test_MantarrayProcessesMonitor__drains_data_analyzer_data_out_queue_after_receiving_stop_managed_acquisition_command_receipt(
    test_process_manager_creator,
    test_monitor,
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = CALIBRATED_STATE

    da_data_out_queue = test_process_manager.queue_container.data_analyzer_boards[0][1]
    put_object_into_queue_and_raise_error_if_eventually_still_empty("test_item", da_data_out_queue)

    data_analyzer_to_main = test_process_manager.queue_container.from_data_analyzer
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        STOP_MANAGED_ACQUISITION_COMMUNICATION, data_analyzer_to_main
    )

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(da_data_out_queue)


def test_MantarrayProcessesMonitor__sets_stim_running_statuses_in_shared_values_dict_after_receiving_start_stimulation_command_response_from_instrument_comm(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    test_stim_info = create_random_stim_info()

    shared_values_dict["stimulation_info"] = test_stim_info

    instrument_comm_to_main = test_process_manager.queue_container.from_instrument_comm(0)

    expected_timestamp = datetime.datetime(
        year=2021, month=10, day=19, hour=10, minute=23, second=40, microsecond=123456
    )
    command_response = {
        "communication_type": "stimulation",
        "command": "start_stimulation",
        "timestamp": expected_timestamp,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(command_response, instrument_comm_to_main)

    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["stimulation_running"] == [
        bool(
            test_stim_info["protocol_assignments"][
                GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
            ]
        )
        for well_idx in range(24)
    ]


def test_MantarrayProcessesMonitor__updates_stim_running_statuses_shared_values_dict_after_receiving_stop_stimulation_command_response_from_instrument_comm(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    test_stim_info = create_random_stim_info()

    shared_values_dict["stimulation_info"] = test_stim_info
    shared_values_dict["stimulation_running"] = [
        bool(
            test_stim_info["protocol_assignments"][
                GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
            ]
        )
        for well_idx in range(24)
    ]

    instrument_comm_to_main = test_process_manager.queue_container.from_instrument_comm(0)

    command_response = {"communication_type": "stimulation", "command": "stop_stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(command_response, instrument_comm_to_main)

    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["stimulation_running"] == [False] * 24


def test_MantarrayProcessesMonitor__updates_stimulation_running_list_when_status_update_message_received_from_instrument_comm(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    test_wells_running = {0, 5, 10, 15}
    shared_values_dict["stimulation_running"] = [well_idx in test_wells_running for well_idx in range(24)]

    instrument_comm_to_main = test_process_manager.queue_container.from_instrument_comm(0)

    # stop the first set of wells
    test_wells_to_stop_1 = {0, 10}
    msg_from_ic_1 = {
        "communication_type": "stimulation",
        "command": "status_update",
        "wells_done_stimulating": list(test_wells_to_stop_1),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(msg_from_ic_1, instrument_comm_to_main)
    invoke_process_run_and_check_errors(monitor_thread)
    # make sure that statuses were update correctly and the start timestamp was not cleared
    expected_updated_statuses_1 = [
        well_idx in (test_wells_running - test_wells_to_stop_1) for well_idx in range(24)
    ]
    assert shared_values_dict["stimulation_running"] == expected_updated_statuses_1

    # stop remaining wells
    msg_from_ic_2 = {
        "communication_type": "stimulation",
        "command": "status_update",
        "wells_done_stimulating": list(test_wells_running - test_wells_to_stop_1),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(msg_from_ic_2, instrument_comm_to_main)
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["stimulation_running"] == [False] * 24


def test_MantarrayProcessesMonitor__passes_stim_status_check_results_from_mc_comm_to_websocket_queue__and_stores_them_in_shared_values_dictionary(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    instrument_comm_to_main = test_process_manager.queue_container.from_instrument_comm(0)
    queue_to_server_ws = test_process_manager.queue_container.to_server

    test_num_wells = 24
    possible_stim_statuses = [member.name.lower() for member in StimulatorCircuitStatuses]
    stim_check_results = {well_idx: choice(possible_stim_statuses) for well_idx in range(test_num_wells)}

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "stimulation",
            "command": "start_stim_checks",
            "stimulator_circuit_statuses": stim_check_results,
        },
        instrument_comm_to_main,
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["stimulator_circuit_statuses"] == stim_check_results

    confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)
    ws_message = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert ws_message == {
        "data_type": "stimulator_circuit_statuses",
        "data_json": json.dumps(stim_check_results),
    }


def test_MantarrayProcessesMonitor__passes_corrupt_file_message_from_file_writer_to_websocket_queue(
    test_monitor, test_process_manager_creator
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    file_writer_to_main = test_process_manager.queue_container.from_file_writer
    queue_to_server_ws = test_process_manager.queue_container.to_server

    test_corrupt_files = ["test_file_A1", "test_file_C4"]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "corrupt_file_detected", "corrupt_files": test_corrupt_files},
        file_writer_to_main,
    )
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)

    ws_message = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert ws_message == {
        "data_type": "corrupt_files_alert",
        "data_json": json.dumps({"corrupt_files_found": test_corrupt_files}),
    }
