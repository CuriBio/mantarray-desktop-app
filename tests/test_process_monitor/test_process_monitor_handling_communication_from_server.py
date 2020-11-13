# -*- coding: utf-8 -*-
import tempfile
from uuid import UUID

from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
import numpy as np
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_test_process_manager
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_ok_comm import fixture_patch_connection_to_board
from ..fixtures_process_monitor import fixture_test_monitor
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_empty
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_test_process_manager,
    fixture_test_monitor,
    fixture_patch_connection_to_board,
]


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_nickname_update_by_updating_shared_values_dictionary_and_passing_command_to_ok_comm(
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
    assert is_queue_eventually_empty(server_to_main_queue) is True

    assert (
        test_process_manager.get_values_to_share_to_server()["mantarray_nickname"][0]
        == expected_nickname
    )

    main_to_ok_comm = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    confirm_queue_is_eventually_of_size(main_to_ok_comm, 1)
    actual_comm = main_to_ok_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_serial_number_update_by_updating_shared_values_dictionary_and_passing_command_to_ok_comm(
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

    main_to_ok_comm = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    confirm_queue_is_eventually_of_size(main_to_ok_comm, 1)
    actual_comm = main_to_ok_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


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

    main_to_ok_comm = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    confirm_queue_is_eventually_of_size(main_to_ok_comm, 1)
    actual_comm = main_to_ok_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_boot_up_by_calling_process_manager_bootup(
    test_process_manager, test_monitor, mocker
):
    monitor_thread, _, _, _ = test_monitor

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


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_managed_acquisition__updates_system_status__puts_command_into_ok_comm_and_data_analyzer_queues(
    test_process_manager, test_monitor
):
    monitor_thread, _, _, _ = test_monitor

    test_process_manager.create_processes()
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        START_MANAGED_ACQUISITION_COMMUNICATION, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert is_queue_eventually_empty(server_to_main_queue) is True
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    assert shared_values_dict["system_status"] == BUFFERING_STATE

    main_to_ok_comm = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
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
