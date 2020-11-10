# -*- coding: utf-8 -*-
from mantarray_desktop_app import CALIBRATING_STATE
import numpy as np
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_test_process_manager
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_ok_comm import fixture_patch_connection_to_board
from ..fixtures_process_monitor import fixture_test_monitor
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_of_size
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
    assert is_queue_eventually_of_size(main_to_ok_comm, 1)
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
    assert is_queue_eventually_of_size(main_to_ok_comm, 1)
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
    assert is_queue_eventually_of_size(main_to_ok_comm, 1)
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
