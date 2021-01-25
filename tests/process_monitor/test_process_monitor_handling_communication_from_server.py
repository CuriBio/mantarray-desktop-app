# -*- coding: utf-8 -*-
import datetime
import tempfile
from uuid import UUID

from freezegun import freeze_time
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import process_monitor
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from mantarray_desktop_app import UnrecognizedCommandToInstrumentError
from mantarray_desktop_app import UnrecognizedMantarrayNamingCommandError
from mantarray_desktop_app import UnrecognizedRecordingCommandError
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_subprocess_joins
from ..fixtures import fixture_test_process_manager
from ..fixtures import get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_ok_comm import fixture_patch_connection_to_board
from ..fixtures_process_monitor import fixture_test_monitor
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_empty
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_test_process_manager,
    fixture_test_monitor,
    fixture_patch_connection_to_board,
    fixture_patch_subprocess_joins,
]


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_nickname_setting_by_setting_shared_values_dictionary_and_passing_command_to_ok_comm(
    test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_nickname = "The Nautilus"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_comm, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert (
        test_process_manager.get_values_to_share_to_server()["mantarray_nickname"][0]
        == expected_nickname
    )

    main_to_ok_comm = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(main_to_ok_comm, 1)
    actual_comm = main_to_ok_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_nickname_update_by_updating_shared_values_dictionary(
    test_process_manager, test_monitor
):
    monitor_thread, shared_values_dict, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    shared_values_dict["mantarray_nickname"] = {0: "The Nautilus 1"}
    expected_nickname = "The Nautilus 2"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_comm, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert (
        test_process_manager.get_values_to_share_to_server()["mantarray_nickname"][0]
        == expected_nickname
    )


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_serial_number_setting_by_setting_shared_values_dictionary_and_passing_command_to_ok_comm(
    test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_serial = "M02001901"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_serial_number",
        "mantarray_serial_number": expected_serial,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_comm, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True

    assert (
        test_process_manager.get_values_to_share_to_server()["mantarray_serial_number"][
            0
        ]
        == expected_serial
    )

    main_to_ok_comm = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(main_to_ok_comm, 1)
    actual_comm = main_to_ok_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_serial_number_update_by_updating_shared_values_dictionary(
    test_process_manager, test_monitor
):
    monitor_thread, svd, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    svd["mantarray_serial_number"] = {0: "M02001901"}
    expected_serial = "M02001902"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_serial_number",
        "mantarray_serial_number": expected_serial,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_comm, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True

    assert (
        test_process_manager.get_values_to_share_to_server()["mantarray_serial_number"][
            0
        ]
        == expected_serial
    )


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__raises_error_if_unrecognized_mantarray_naming_command(
    test_process_manager, test_monitor, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_command = "bad_command"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": expected_command,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_comm, server_to_main_queue
    )
    with pytest.raises(UnrecognizedMantarrayNamingCommandError, match=expected_command):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_calibration_by_updating_shared_values_dictionary_and_passing_command_to_ok_comm(
    test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_comm = {
        "communication_type": "xem_scripts",
        "script_type": "start_calibration",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_comm, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True

    assert (
        test_process_manager.get_values_to_share_to_server()["system_status"]
        == CALIBRATING_STATE
    )

    main_to_ok_comm = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(main_to_ok_comm, 1)
    actual_comm = main_to_ok_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_boot_up_by_calling_process_manager_bootup(
    test_process_manager, test_monitor, mocker
):
    monitor_thread, _, _, _ = test_monitor

    mocker.patch.object(
        process_manager, "get_latest_firmware", autospec=True, return_value=None
    )

    test_process_manager.create_processes()
    spied_boot_up_instrument = mocker.spy(test_process_manager, "boot_up_instrument")
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_comm = {
        "communication_type": "to_instrument",
        "command": "boot_up",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_comm, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True

    spied_boot_up_instrument.assert_called_once()

    # clean up the instrument subprocess to avoid broken pipe errors
    test_process_manager.get_instrument_process().hard_stop()


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__raises_error_if_unrecognized_to_instrument_command(
    test_process_manager, test_monitor, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_command = "bad_command"
    expected_comm = {
        "communication_type": "to_instrument",
        "command": expected_command,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_comm, server_to_main_queue
    )
    with pytest.raises(UnrecognizedCommandToInstrumentError, match=expected_command):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_managed_acquisition__updates_system_status__puts_command_into_ok_comm_and_data_analyzer_queues(
    test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        server_to_main_queue,
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    assert shared_values_dict["system_status"] == BUFFERING_STATE

    main_to_ok_comm = (
        test_process_manager.queue_container().get_communication_to_ok_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(main_to_ok_comm, 1)
    actual_comm = main_to_ok_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == START_MANAGED_ACQUISITION_COMMUNICATION

    main_to_da = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    )
    confirm_queue_is_eventually_of_size(main_to_da, 1)
    actual_comm = main_to_da.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == START_MANAGED_ACQUISITION_COMMUNICATION

    # clean up the instrument subprocess to avoid broken pipe errors
    test_process_manager.get_instrument_process().hard_stop()


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_update_shared_values_by_updating_shared_values_dictionary__and_overriding_existing_value(
    test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    original_id = UUID("e623b13c-05a5-41f2-8526-c2eba8e78e7f")
    new_id = UUID("e7744225-c41c-4bd5-9e32-e79716cc8f40")
    shared_values_dict["config_settings"] = dict()
    shared_values_dict["config_settings"]["User Account ID"] = original_id
    communication = {
        "communication_type": "update_shared_values_dictionary",
        "content": {"config_settings": {"User Account ID": new_id}},
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        communication, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True

    assert (
        test_process_manager.get_values_to_share_to_server()["config_settings"][
            "User Account ID"
        ]
        == new_id
    )


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_update_shared_values__by_populating_file_writer_queue_when_recording_directory_updated(
    test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor
    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        communication = {
            "communication_type": "update_shared_values_dictionary",
            "content": {
                "config_settings": {"Recording Directory": expected_recordings_dir}
            },
        }

        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            communication, server_to_main_queue
        )

        invoke_process_run_and_check_errors(monitor_thread)

        to_file_writer_queue = (
            test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
        )
        confirm_queue_is_eventually_of_size(to_file_writer_queue, 1)
        communication = to_file_writer_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert communication["command"] == "update_directory"
        assert communication["new_directory"] == expected_recordings_dir
        assert test_process_manager.get_file_directory() == expected_recordings_dir


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_stop_recording__by_passing_command_to_file_writer__and_setting_status_to_live_view_active(
    test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_timepoint = 55432
    communication = {
        "communication_type": "recording",
        "command": "stop_recording",
        "timepoint_to_stop_recording_at": expected_timepoint,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        communication, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True
    main_to_fw_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    confirm_queue_is_eventually_of_size(main_to_fw_queue, 1)

    actual = main_to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == communication
    assert (
        test_process_manager.get_values_to_share_to_server()["system_status"]
        == LIVE_VIEW_ACTIVE_STATE
    )


@freeze_time(
    datetime.datetime(
        year=2020, month=11, day=16, hour=15, minute=14, second=44, microsecond=890122
    )
)
def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_recording__in_hardware_test_mode__by_passing_command_to_file_writer__and_setting_status_to_recording__and_updating_adc_offsets(
    test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    # expected_timepoint = 55432
    adc_offsets = dict()
    for well_idx in range(24):
        adc_offsets[well_idx] = {
            "construct": 0,
            "ref": 0,
        }

    communication = {
        "communication_type": "recording",
        "command": "start_recording",
        "is_hardware_test_recording": True,
        "metadata_to_copy_onto_main_file_attributes": {"adc_offsets": adc_offsets},
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        communication, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True
    main_to_fw_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    confirm_queue_is_eventually_of_size(main_to_fw_queue, 1)

    actual = main_to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == communication

    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    assert shared_values_dict["is_hardware_test_recording"] is True
    assert shared_values_dict["system_status"] == RECORDING_STATE
    assert (
        shared_values_dict["adc_offsets"]
        == communication["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"]
    )


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__raises_error_if_unrecognized_recording_command(
    test_process_manager, test_monitor, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    adc_offsets = dict()
    for well_idx in range(24):
        adc_offsets[well_idx] = {
            "construct": 0,
            "ref": 0,
        }

    expected_command = "bad_command"
    communication = {
        "communication_type": "recording",
        "command": expected_command,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        communication, server_to_main_queue
    )
    with pytest.raises(UnrecognizedRecordingCommandError, match=expected_command):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_soft_stop__by_soft_stopping_everything_except_the_server(
    test_process_manager, test_monitor, mocker
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()
    mocked_soft_stop_processes_except_server = mocker.patch.object(
        test_process_manager, "soft_stop_processes_except_server", autospec=True
    )  # Eli (11/17/20): mocking instead of spying because processes can't be joined unless they were actaully started, and we're just doing a create_processes here

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    communication = {
        "communication_type": "shutdown",
        "command": "soft_stop",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        communication, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True

    mocked_soft_stop_processes_except_server.assert_called_once()


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_hard_stop_by_hard_stop_and_join_all_processes(
    test_process_manager, test_monitor, mocker
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()
    mocked_are_processes_stopped = mocker.patch.object(
        test_process_manager, "are_processes_stopped", autospec=True
    )  # Eli (11/17/20): mocking instead of spying because processes can't be joined unless they were actaully started, and we're just doing a create_processes here
    mocked_hard_stop_and_join = mocker.patch.object(
        test_process_manager, "hard_stop_and_join_processes", autospec=True
    )  # Eli (11/17/20): mocking instead of spying because processes can't be joined unless they were actaully started, and we're just doing a create_processes here

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    communication = {
        "communication_type": "shutdown",
        "command": "hard_stop",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        communication, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True
    mocked_are_processes_stopped.assert_called_once()
    mocked_hard_stop_and_join.assert_called_once()


@pytest.mark.timeout(10)
@pytest.mark.slow
def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_hard_stop__by_soft_stop_then_checking_if_processes_are_stopped_for_desired_time_and_then_finally_hard_stop_and_join_all_processes(
    test_process_manager, test_monitor, mocker
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.start_processes()

    okc_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()
    server_thread = test_process_manager.get_server_thread()

    spied_okc_join = mocker.spy(okc_process, "join")
    spied_fw_join = mocker.spy(fw_process, "join")
    spied_da_join = mocker.spy(da_process, "join")
    spied_server_join = mocker.spy(server_thread, "join")

    spied_okc_hard_stop = mocker.spy(okc_process, "hard_stop")
    spied_fw_hard_stop = mocker.spy(fw_process, "hard_stop")
    spied_da_hard_stop = mocker.spy(da_process, "hard_stop")
    spied_server_hard_stop = mocker.spy(server_thread, "hard_stop")

    mocked_okc_is_stopped = mocker.patch.object(
        okc_process, "is_stopped", autospec=True, side_effect=[False, True, True]
    )
    mocked_server_is_stopped = mocker.patch.object(
        server_thread, "is_stopped", side_effect=[False, True, True, True]
    )
    mocked_fw_is_stopped = mocker.patch.object(
        fw_process, "is_stopped", autospec=True, side_effect=[False, True]
    )
    mocked_da_is_stopped = mocker.patch.object(
        da_process, "is_stopped", autospec=True, return_value=False
    )

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    communication = {
        "communication_type": "shutdown",
        "command": "hard_stop",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        communication, server_to_main_queue
    )

    mocked_counter = mocker.patch.object(
        process_manager,
        "perf_counter",
        autospec=True,
        side_effect=[0, 0, 0, 0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS],
    )

    mocker.patch.object(process_manager, "sleep", autospec=True)  # speed up test

    invoke_process_run_and_check_errors(monitor_thread)

    assert is_queue_eventually_empty(server_to_main_queue) is True

    spied_okc_hard_stop.assert_called_once()
    spied_fw_hard_stop.assert_called_once()
    spied_da_hard_stop.assert_called_once()
    spied_server_hard_stop.assert_called_once()
    spied_okc_join.assert_called_once()
    spied_fw_join.assert_called_once()
    spied_da_join.assert_called_once()
    spied_server_join.assert_called_once()

    assert mocked_counter.call_count == 5
    assert mocked_okc_is_stopped.call_count == 3
    assert mocked_server_is_stopped.call_count == 4
    assert mocked_fw_is_stopped.call_count == 2
    assert mocked_da_is_stopped.call_count == 1


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_hard_stop__by_logging_items_in_queues_from_subprocesses(
    test_process_manager, test_monitor, patch_subprocess_joins, mocker
):
    monitor_thread, _, _, _ = test_monitor

    okc_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()
    server_thread = test_process_manager.get_server_thread()
    expected_okc_item = "item 1"
    expected_fw_item = "item 2"
    expected_da_item = "item 3"
    expected_server_item = "item 4"

    mocker.patch.object(
        okc_process, "hard_stop", autospec=True, return_value=expected_okc_item
    )
    mocker.patch.object(
        fw_process, "hard_stop", autospec=True, return_value=expected_fw_item
    )
    mocker.patch.object(
        da_process, "hard_stop", autospec=True, return_value=expected_da_item
    )
    mocker.patch.object(
        server_thread, "hard_stop", autospec=True, return_value=expected_server_item
    )

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    communication = {
        "communication_type": "shutdown",
        "command": "hard_stop",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        communication, server_to_main_queue
    )

    mocker.patch.object(
        process_manager,
        "perf_counter",
        autospec=True,
        side_effect=[0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS],
    )

    mocked_monitor_logger_error = mocker.patch.object(
        process_monitor.logger, "error", autospec=True
    )

    invoke_process_run_and_check_errors(monitor_thread)

    assert is_queue_eventually_empty(server_to_main_queue) is True

    actual_log_message = mocked_monitor_logger_error.call_args[0][0]
    assert expected_okc_item in actual_log_message
    assert expected_fw_item in actual_log_message
    assert expected_da_item in actual_log_message
    assert expected_server_item in actual_log_message
