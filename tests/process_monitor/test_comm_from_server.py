# -*- coding: utf-8 -*-
import copy
import datetime
import tempfile
from uuid import UUID

from freezegun import freeze_time
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_RECORDING_DUR_SECONDS
from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import get_redacted_string
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import process_monitor
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from mantarray_desktop_app import UnrecognizedCommandFromServerToMainError
from mantarray_desktop_app import UnrecognizedMantarrayNamingCommandError
from mantarray_desktop_app import UnrecognizedRecordingCommandError
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_file_manager import BARCODE_IS_FROM_SCANNER_UUID
from mantarray_file_manager import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_file_manager import NOT_APPLICABLE_H5_METADATA
from mantarray_file_manager import PLATE_BARCODE_UUID
from mantarray_file_manager import START_RECORDING_TIME_INDEX_UUID
from mantarray_file_manager import STIMULATION_PROTOCOL_UUID
from mantarray_file_manager import USER_ACCOUNT_ID_UUID
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_BEGINNING_RECORDING_UUID
from mantarray_file_manager import UTC_BEGINNING_STIMULATION_UUID
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import fixture_patch_subprocess_joins
from ..fixtures import fixture_test_process_manager_creator
from ..fixtures import get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_ok_comm import fixture_patch_connection_to_board
from ..fixtures_process_monitor import fixture_test_monitor
from ..fixtures_server import put_generic_beta_2_start_recording_info_in_dict
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_test_process_manager_creator,
    fixture_test_monitor,
    fixture_patch_connection_to_board,
    fixture_patch_subprocess_joins,
    fixture_patch_print,
]


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_nickname_setting_by_setting_shared_values_dictionary_and_passing_command_to_instrument_comm(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_nickname = "The Nautilus"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert test_process_manager.get_values_to_share_to_server()["mantarray_nickname"][0] == expected_nickname

    main_to_instrument_comm = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(main_to_instrument_comm, 1)
    actual_comm = main_to_instrument_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_nickname_update_by_updating_shared_values_dictionary(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert test_process_manager.get_values_to_share_to_server()["mantarray_nickname"][0] == expected_nickname


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_serial_number_setting_by_setting_shared_values_dictionary_and_passing_command_to_instrument_comm(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_serial = "M02001901"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_serial_number",
        "mantarray_serial_number": expected_serial,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert (
        test_process_manager.get_values_to_share_to_server()["mantarray_serial_number"][0] == expected_serial
    )

    main_to_instrument_comm = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(main_to_instrument_comm, 1)
    actual_comm = main_to_instrument_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_serial_number_update_by_updating_shared_values_dictionary(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, svd, *_ = test_monitor(test_process_manager)

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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert (
        test_process_manager.get_values_to_share_to_server()["mantarray_serial_number"][0] == expected_serial
    )


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__raises_error_if_unrecognized_mantarray_naming_command(
    test_process_manager_creator, test_monitor, mocker, patch_print
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_command = "bad_command"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": expected_command,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    with pytest.raises(UnrecognizedMantarrayNamingCommandError, match=expected_command):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_calibration_by_updating_shared_values_dictionary_to_calibrating_state__and_passing_command_to_instrument_comm__when_in_beta_1_mode(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, svd, *_ = test_monitor(test_process_manager)
    svd["beta_2_mode"] = False

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_comm = {
        "communication_type": "xem_scripts",
        "script_type": "start_calibration",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert test_process_manager.get_values_to_share_to_server()["system_status"] == CALIBRATING_STATE

    main_to_instrument_comm = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(main_to_instrument_comm, 1)
    actual_comm = main_to_instrument_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


@freeze_time(
    GENERIC_BETA_2_START_RECORDING_COMMAND["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_RECORDING_UUID
    ]
)
def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_run_calibration_command_when_in_beta_2_mode(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, svd, *_ = test_monitor(test_process_manager)

    put_generic_beta_2_start_recording_info_in_dict(svd)
    # Tanner (12/10/21): deleting since these may not actually be set by the time this route is called
    del svd["utc_timestamps_of_beginning_of_data_acquisition"]
    del svd["config_settings"]["customer_account_id"]
    del svd["config_settings"]["user_account_id"]

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    main_to_ic_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    main_to_fw_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )

    expected_comm = {"communication_type": "calibration", "command": "run_calibration"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)
    assert svd["system_status"] == CALIBRATING_STATE

    confirm_queue_is_eventually_of_size(main_to_ic_queue, 1)
    assert (
        main_to_ic_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == START_MANAGED_ACQUISITION_COMMUNICATION
    )

    confirm_queue_is_eventually_of_size(main_to_fw_queue, 2)

    expected_start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    expected_start_recording_command.update(
        {
            "active_well_indices": list(range(24)),
            "is_calibration_recording": True,
            "timepoint_to_begin_recording_at": 0,
            "stim_running_statuses": [False] * 24,
        }
    )
    expected_start_recording_command["metadata_to_copy_onto_main_file_attributes"].update(
        {
            START_RECORDING_TIME_INDEX_UUID: 0,
            PLATE_BARCODE_UUID: NOT_APPLICABLE_H5_METADATA,
            BARCODE_IS_FROM_SCANNER_UUID: NOT_APPLICABLE_H5_METADATA,
            UTC_BEGINNING_DATA_ACQUISTION_UUID: GENERIC_BETA_2_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ][UTC_BEGINNING_RECORDING_UUID],
            UTC_BEGINNING_STIMULATION_UUID: None,
            STIMULATION_PROTOCOL_UUID: None,
            CUSTOMER_ACCOUNT_ID_UUID: NOT_APPLICABLE_H5_METADATA,
            USER_ACCOUNT_ID_UUID: NOT_APPLICABLE_H5_METADATA,
        }
    )
    assert main_to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_start_recording_command

    expected_stop_recording_command = {
        "communication_type": "recording",
        "command": "stop_recording",
        "timepoint_to_stop_recording_at": CALIBRATION_RECORDING_DUR_SECONDS * MICRO_TO_BASE_CONVERSION,
        "is_calibration_recording": True,
    }
    assert main_to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_stop_recording_command


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_boot_up_by_calling_process_manager_bootup(
    test_process_manager_creator, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocker.patch.object(process_manager, "get_latest_firmware", autospec=True, return_value=None)

    spied_boot_up_instrument = mocker.spy(test_process_manager, "boot_up_instrument")
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_comm = {
        "communication_type": "to_instrument",
        "command": "boot_up",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    spied_boot_up_instrument.assert_called_once()


@pytest.mark.parametrize(
    "test_comm_type,test_description",
    [
        ("to_instrument", "raises error with bad to_instrument command"),
        ("acquisition_manager", "raises error with bad acquisition_manager command"),
    ],
)
def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__raises_error_if_unrecognized_command(
    test_comm_type, test_description, test_process_manager_creator, test_monitor, mocker, patch_print
):

    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_command = "bad_command"
    expected_comm = {
        "communication_type": test_comm_type,
        "command": expected_command,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    with pytest.raises(UnrecognizedCommandFromServerToMainError, match=expected_command):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_managed_acquisition__updates_system_status__puts_command_into_instrument_comm_and_data_analyzer_queues(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        server_to_main_queue,
    )
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    assert shared_values_dict["system_status"] == BUFFERING_STATE

    main_to_instrument_comm = (
        test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    confirm_queue_is_eventually_of_size(main_to_instrument_comm, 1)
    actual_comm = main_to_instrument_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == START_MANAGED_ACQUISITION_COMMUNICATION

    main_to_da = test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    confirm_queue_is_eventually_of_size(main_to_da, 1)
    actual_comm = main_to_da.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == START_MANAGED_ACQUISITION_COMMUNICATION


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_stop_managed_acquisition__puts_command_into_subprocess_queues_in_correct_order(
    test_process_manager_creator, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    main_to_da = test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    main_to_fw = test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    main_to_ic = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)

    mocked_to_ic_put_nowait = mocker.patch.object(main_to_ic, "put_nowait", autospec=True)

    def fw_side_effect(*args, **kwargs):
        assert mocked_to_ic_put_nowait.call_count == 0, "Item passed to IC queue before FW queue"

    mocked_to_fw_put_nowait = mocker.patch.object(
        main_to_fw, "put_nowait", autospec=True, side_effect=fw_side_effect
    )

    def da_side_effect(*args, **kwargs):
        assert mocked_to_ic_put_nowait.call_count == 0, "Item passed to IC queue before DA queue"
        assert mocked_to_fw_put_nowait.call_count == 0, "Item passed to FW queue before DA queue"

    mocked_to_da_put_nowait = mocker.patch.object(
        main_to_da, "put_nowait", autospec=True, side_effect=da_side_effect
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(STOP_MANAGED_ACQUISITION_COMMUNICATION),
        server_to_main_queue,
    )
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)
    mocked_to_da_put_nowait.assert_called_once_with(STOP_MANAGED_ACQUISITION_COMMUNICATION)
    mocked_to_fw_put_nowait.assert_called_once_with(STOP_MANAGED_ACQUISITION_COMMUNICATION)
    mocked_to_ic_put_nowait.assert_called_once_with(STOP_MANAGED_ACQUISITION_COMMUNICATION)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_update_shared_values_by_updating_shared_values_dictionary__and_overriding_existing_value(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    original_id = UUID("e623b13c-05a5-41f2-8526-c2eba8e78e7f")
    new_id = UUID("e7744225-c41c-4bd5-9e32-e79716cc8f40")
    shared_values_dict["config_settings"] = dict()
    shared_values_dict["config_settings"]["user_account_id"] = original_id
    communication = {
        "communication_type": "update_customer_settings",
        "content": {"config_settings": {"user_account_id": new_id}},
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert (
        test_process_manager.get_values_to_share_to_server()["config_settings"]["user_account_id"] == new_id
    )


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_update_shared_values__by_populating_file_writer_queue_when_recording_directory_updated(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        communication = {
            "communication_type": "update_customer_settings",
            "content": {"config_settings": {"recording_directory": expected_recordings_dir}},
        }

        put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)

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
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    expected_timepoint = 55432
    communication = {
        "communication_type": "recording",
        "command": "stop_recording",
        "timepoint_to_stop_recording_at": expected_timepoint,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)
    main_to_fw_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_file_writer()
    )
    confirm_queue_is_eventually_of_size(main_to_fw_queue, 1)

    actual = main_to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == communication
    assert test_process_manager.get_values_to_share_to_server()["system_status"] == LIVE_VIEW_ACTIVE_STATE


@freeze_time(
    datetime.datetime(year=2020, month=11, day=16, hour=15, minute=14, second=44, microsecond=890122)
)
def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_recording__in_hardware_test_mode__by_passing_command_to_file_writer__and_setting_status_to_recording__and_updating_adc_offsets(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)
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
    test_process_manager_creator, test_monitor, mocker, patch_print
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)
    with pytest.raises(UnrecognizedRecordingCommandError, match=expected_command):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_hard_stop_by_hard_stop_and_join_all_processes(
    test_process_manager_creator, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_hard_stop_and_join = mocker.patch.object(
        test_process_manager, "hard_stop_and_join_processes", autospec=True
    )  # Eli (11/17/20): mocking instead of spying because processes can't be joined unless they were actually started, and we're just doing a create_processes here

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    communication = {
        "communication_type": "shutdown",
        "command": "hard_stop",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)
    mocked_hard_stop_and_join.assert_called_once()


@pytest.mark.timeout(15)
@pytest.mark.slow
def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_hard_stop_by_hard_stopping_and_joining_all_processes(
    test_process_manager_creator, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator()
    monitor_thread, *_ = test_monitor(test_process_manager)

    test_process_manager.start_processes()

    okc_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()

    spied_okc_join = mocker.spy(okc_process, "join")
    spied_fw_join = mocker.spy(fw_process, "join")
    spied_da_join = mocker.spy(da_process, "join")

    spied_okc_hard_stop = mocker.spy(okc_process, "hard_stop")
    spied_fw_hard_stop = mocker.spy(fw_process, "hard_stop")
    spied_da_hard_stop = mocker.spy(da_process, "hard_stop")

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    communication = {
        "communication_type": "shutdown",
        "command": "hard_stop",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    spied_okc_hard_stop.assert_called_once()
    spied_fw_hard_stop.assert_called_once()
    spied_da_hard_stop.assert_called_once()
    spied_okc_join.assert_called_once()
    spied_fw_join.assert_called_once()
    spied_da_join.assert_called_once()


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_hard_stop_by_logging_items_in_queues_from_subprocesses(
    test_process_manager_creator, test_monitor, patch_subprocess_joins, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    okc_process = test_process_manager.get_instrument_process()
    fw_process = test_process_manager.get_file_writer_process()
    da_process = test_process_manager.get_data_analyzer_process()
    expected_okc_item = "item 1"
    expected_fw_item = "item 2"
    expected_da_item = "item 3"

    mocker.patch.object(okc_process, "hard_stop", autospec=True, return_value=expected_okc_item)
    mocker.patch.object(fw_process, "hard_stop", autospec=True, return_value=expected_fw_item)
    mocker.patch.object(da_process, "hard_stop", autospec=True, return_value=expected_da_item)

    communication = {
        "communication_type": "shutdown",
        "command": "hard_stop",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)

    mocker.patch.object(
        process_manager,
        "perf_counter",
        autospec=True,
        side_effect=[0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS],
    )

    mocked_monitor_logger_error = mocker.patch.object(process_monitor.logger, "error", autospec=True)

    invoke_process_run_and_check_errors(monitor_thread)

    actual_log_message = mocked_monitor_logger_error.call_args[0][0]
    assert expected_okc_item in actual_log_message
    assert expected_fw_item in actual_log_message
    assert expected_da_item in actual_log_message


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_server_by_stopping_server(
    test_process_manager_creator, test_monitor, patch_subprocess_joins, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    server_manager = test_process_manager.get_server_manager()
    expected_server_item = "server item"

    spied_shutdown_server = mocker.spy(server_manager, "shutdown_server")
    mocker.patch.object(server_manager, "drain_all_queues", autospec=True, return_value=expected_server_item)

    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    communication = {
        "communication_type": "shutdown",
        "command": "shutdown_server",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)

    invoke_process_run_and_check_errors(monitor_thread)
    spied_shutdown_server.assert_called_once()
    # confirm log message is present and remove
    confirm_queue_is_eventually_of_size(server_to_main_queue, 1)
    server_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)


def test_MantarrayProcessesMonitor__logs_messages_from_server__and_redacts_mantarray_nickname(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    to_main_queue = test_process_manager.queue_container().get_communication_queue_from_server_to_main()

    test_nickname = "The Nautilus"
    test_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": test_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_comm, to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(to_main_queue)

    expected_comm = copy.deepcopy(test_comm)
    expected_comm["mantarray_nickname"] = get_redacted_string(len(test_nickname))
    mocked_logger.assert_called_once_with(f"Communication from the Server: {expected_comm}")


def test_MantarrayProcessesMonitor__passes_magnetometer_config_dict_from_server_to_mc_comm_and__data_analyzer(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    main_to_ic_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    main_to_da_queue = (
        test_process_manager.queue_container().get_communication_queue_from_main_to_data_analyzer()
    )

    test_num_wells = 24
    expected_sampling_period = 10000
    expected_config_dict = {
        "magnetometer_config": create_magnetometer_config_dict(test_num_wells),
        "sampling_period": expected_sampling_period,
    }
    test_dict_from_server = {
        "communication_type": "set_magnetometer_config",
        "magnetometer_config_dict": expected_config_dict,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_dict_from_server, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_of_size(main_to_ic_queue, 1)
    confirm_queue_is_eventually_of_size(main_to_da_queue, 1)

    expected_comm = {
        "communication_type": "acquisition_manager",
        "command": "change_magnetometer_config",
    }
    expected_comm.update(expected_config_dict)
    assert main_to_ic_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_comm
    assert main_to_da_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_comm


@pytest.mark.parametrize(
    "test_status,test_description",
    [
        (True, "processes command when status is True"),
        (False, "processes command when status is False"),
    ],
)
def test_MantarrayProcessesMonitor__processes_set_stim_status_command(
    test_status, test_description, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    main_to_ic_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)

    test_well_names = ["A1", "A2", "B1"]
    test_well_indices = [
        GENERIC_24_WELL_DEFINITION.get_well_index_from_well_name(well_name) for well_name in test_well_names
    ]

    shared_values_dict["stimulation_running"] = [
        (not test_status if well_idx in test_well_indices else False) for well_idx in range(24)
    ]
    shared_values_dict["stimulation_info"] = {
        "protocols": [{"protocol_id": "A"}],
        "protocol_assignments": {well_name: "A" for well_name in test_well_names},
    }

    test_command = {
        "communication_type": "stimulation",
        "command": "set_stim_status",
        "status": test_status,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, server_to_main_queue)

    invoke_process_run_and_check_errors(monitor_thread)

    confirm_queue_is_eventually_of_size(main_to_ic_queue, 1)
    actual = main_to_ic_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    expected_command = "start_stimulation" if test_status else "stop_stimulation"
    assert actual == {"communication_type": "stimulation", "command": expected_command}


def test_MantarrayProcessesMonitor__processes_set_protocols_command(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )
    main_to_ic_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(0)

    shared_values_dict["stimulation_running"] = [False] * 24

    test_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": {"protocols": [None] * 3, "protocol_assignments": {"dummy": "values"}},
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, server_to_main_queue)

    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["stimulation_info"] == test_command["stim_info"]

    confirm_queue_is_eventually_of_size(main_to_ic_queue, 1)
    actual = main_to_ic_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == test_command


def test_MantarrayProcessesMonitor__processes_set_latest_software_command(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    server_to_main_queue = (
        test_process_manager.queue_container().get_communication_queue_from_server_to_main()
    )

    shared_values_dict["latest_versions"] = {
        "software": None,
        "main_firmware": None,
        "channel_firmware": None,
    }

    test_version = "1.2.3"
    test_command = {
        "communication_type": "set_latest_software_version",
        "version": test_version,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, server_to_main_queue)

    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["latest_versions"] == {
        "software": test_version,
        "main_firmware": None,
        "channel_firmware": None,
    }
