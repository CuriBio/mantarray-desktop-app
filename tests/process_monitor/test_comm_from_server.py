# -*- coding: utf-8 -*-
import copy
import datetime
import json
import tempfile

from freezegun import freeze_time
from mantarray_desktop_app import BUFFERING_STATE
from mantarray_desktop_app import CALIBRATING_STATE
from mantarray_desktop_app import CALIBRATION_RECORDING_DUR_SECONDS
from mantarray_desktop_app import get_redacted_string
from mantarray_desktop_app import LIVE_VIEW_ACTIVE_STATE
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import RECORDING_STATE
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from mantarray_desktop_app import UnrecognizedCommandFromServerToMainError
from mantarray_desktop_app import UnrecognizedMantarrayNamingCommandError
from mantarray_desktop_app import UnrecognizedRecordingCommandError
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
from mantarray_desktop_app.constants import UPDATES_NEEDED_STATE
from mantarray_desktop_app.main_process import process_manager
from mantarray_desktop_app.main_process import process_monitor
from pulse3D.constants import CUSTOMER_ACCOUNT_ID_UUID
from pulse3D.constants import INITIAL_MAGNET_FINDING_PARAMS_UUID
from pulse3D.constants import NOT_APPLICABLE_H5_METADATA
from pulse3D.constants import PLATE_BARCODE_IS_FROM_SCANNER_UUID
from pulse3D.constants import PLATE_BARCODE_UUID
from pulse3D.constants import START_RECORDING_TIME_INDEX_UUID
from pulse3D.constants import STIM_BARCODE_IS_FROM_SCANNER_UUID
from pulse3D.constants import STIM_BARCODE_UUID
from pulse3D.constants import USER_ACCOUNT_ID_UUID
from pulse3D.constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from pulse3D.constants import UTC_BEGINNING_RECORDING_UUID
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

    server_to_main_queue = test_process_manager.queue_container.from_server
    expected_nickname = "The Nautilus"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert test_process_manager.values_to_share_to_server["mantarray_nickname"][0] == expected_nickname

    main_to_instrument_comm = test_process_manager.queue_container.to_instrument_comm(0)
    confirm_queue_is_eventually_of_size(main_to_instrument_comm, 1)
    actual_comm = main_to_instrument_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_nickname_update_by_updating_shared_values_dictionary(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server
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

    assert test_process_manager.values_to_share_to_server["mantarray_nickname"][0] == expected_nickname


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_serial_number_setting_by_setting_shared_values_dictionary_and_passing_command_to_instrument_comm(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server
    expected_serial = "M02001901"
    expected_comm = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_serial_number",
        "mantarray_serial_number": expected_serial,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert test_process_manager.values_to_share_to_server["mantarray_serial_number"][0] == expected_serial

    main_to_instrument_comm = test_process_manager.queue_container.to_instrument_comm(0)
    confirm_queue_is_eventually_of_size(main_to_instrument_comm, 1)
    actual_comm = main_to_instrument_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == expected_comm


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_serial_number_update_by_updating_shared_values_dictionary(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, svd, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server
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

    assert test_process_manager.values_to_share_to_server["mantarray_serial_number"][0] == expected_serial


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__raises_error_if_unrecognized_mantarray_naming_command(
    test_process_manager_creator, test_monitor, mocker, patch_print
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server
    expected_command = "bad_command"
    expected_comm = {"communication_type": "mantarray_naming", "command": expected_command}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    with pytest.raises(UnrecognizedMantarrayNamingCommandError, match=expected_command):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_calibration_by_updating_shared_values_dictionary_to_calibrating_state__and_passing_command_to_instrument_comm__when_in_beta_1_mode(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, svd, *_ = test_monitor(test_process_manager)
    svd["beta_2_mode"] = False

    server_to_main_queue = test_process_manager.queue_container.from_server
    expected_comm = {"communication_type": "xem_scripts", "script_type": "start_calibration"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert test_process_manager.values_to_share_to_server["system_status"] == CALIBRATING_STATE

    main_to_instrument_comm = test_process_manager.queue_container.to_instrument_comm(0)
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
    del svd["config_settings"]["customer_id"]
    del svd["config_settings"]["user_name"]

    server_to_main_queue = test_process_manager.queue_container.from_server
    main_to_ic_queue = test_process_manager.queue_container.to_instrument_comm(0)
    main_to_fw_queue = test_process_manager.queue_container.to_file_writer

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
        }
    )
    expected_start_recording_command["metadata_to_copy_onto_main_file_attributes"].update(
        {
            START_RECORDING_TIME_INDEX_UUID: 0,
            PLATE_BARCODE_UUID: NOT_APPLICABLE_H5_METADATA,
            PLATE_BARCODE_IS_FROM_SCANNER_UUID: NOT_APPLICABLE_H5_METADATA,
            STIM_BARCODE_UUID: NOT_APPLICABLE_H5_METADATA,
            STIM_BARCODE_IS_FROM_SCANNER_UUID: NOT_APPLICABLE_H5_METADATA,
            UTC_BEGINNING_DATA_ACQUISTION_UUID: GENERIC_BETA_2_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ][UTC_BEGINNING_RECORDING_UUID],
            CUSTOMER_ACCOUNT_ID_UUID: NOT_APPLICABLE_H5_METADATA,
            USER_ACCOUNT_ID_UUID: NOT_APPLICABLE_H5_METADATA,
            INITIAL_MAGNET_FINDING_PARAMS_UUID: GENERIC_BETA_2_START_RECORDING_COMMAND[
                "metadata_to_copy_onto_main_file_attributes"
            ][INITIAL_MAGNET_FINDING_PARAMS_UUID],
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


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__passes_start_stim_checks_command_to_mc_comm__and_resets_results(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, svd, *_ = test_monitor(test_process_manager)

    test_wells = [1, 2, 3]
    svd["stimulator_circuit_statuses"] = {}

    start_stim_checks_command = {
        "communication_type": "stimulation",
        "command": "start_stim_checks",
        "well_indices": test_wells,
    }

    server_to_main_queue = test_process_manager.queue_container.from_server
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_stim_checks_command, server_to_main_queue
    )
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert svd["stimulator_circuit_statuses"] == {
        well_idx: StimulatorCircuitStatuses.CALCULATING.name.lower() for well_idx in test_wells
    }

    main_to_ic_queue = test_process_manager.queue_container.to_instrument_comm(0)
    confirm_queue_is_eventually_of_size(main_to_ic_queue, 1)
    assert main_to_ic_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == start_stim_checks_command


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_boot_up_by_calling_process_manager_bootup(
    test_process_manager_creator, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocker.patch.object(process_manager, "get_latest_firmware", autospec=True, return_value=None)

    spied_boot_up_instrument = mocker.spy(test_process_manager, "boot_up_instrument")
    server_to_main_queue = test_process_manager.queue_container.from_server
    expected_comm = {"communication_type": "to_instrument", "command": "boot_up"}
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

    server_to_main_queue = test_process_manager.queue_container.from_server
    expected_command = "bad_command"
    expected_comm = {"communication_type": test_comm_type, "command": expected_command}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_comm, server_to_main_queue)
    with pytest.raises(UnrecognizedCommandFromServerToMainError, match=expected_command):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_managed_acquisition__updates_system_status__puts_command_into_instrument_comm_and_data_analyzer_queues(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        server_to_main_queue,
    )
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)
    shared_values_dict = test_process_manager.values_to_share_to_server
    assert shared_values_dict["system_status"] == BUFFERING_STATE

    main_to_instrument_comm = test_process_manager.queue_container.to_instrument_comm(0)
    confirm_queue_is_eventually_of_size(main_to_instrument_comm, 1)
    actual_comm = main_to_instrument_comm.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == START_MANAGED_ACQUISITION_COMMUNICATION

    main_to_da = test_process_manager.queue_container.to_data_analyzer
    confirm_queue_is_eventually_of_size(main_to_da, 1)
    actual_comm = main_to_da.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_comm == START_MANAGED_ACQUISITION_COMMUNICATION


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_stop_managed_acquisition__puts_command_into_subprocess_queues_in_correct_order(
    test_process_manager_creator, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server

    main_to_da = test_process_manager.queue_container.to_data_analyzer
    main_to_fw = test_process_manager.queue_container.to_file_writer
    main_to_ic = test_process_manager.queue_container.to_instrument_comm(0)

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


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_update_shared_values_by_updating_shared_values_dictionary__and_sends_update_message_to_file_writer(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server

    new_customer_id = "new_cid"
    new_username = "new_un"
    new_pass_key = "new_pw"

    shared_values_dict["user_creds"] = {
        "customer_id": "old_cid",
        "user_name": "old_un",
        "user_password": "old_pw",
    }

    shared_values_dict["config_settings"] = copy.deepcopy(shared_values_dict["user_creds"])
    shared_values_dict["config_settings"].update(
        {"auto_upload_on_completion": False, "auto_delete_local_files": True, "pulse3d_version": "1.2.3"}
    )

    comm_from_server = {
        "communication_type": "update_user_settings",
        "content": {
            "customer_id": new_customer_id,
            "user_name": new_username,
            "user_password": new_pass_key,
            "auto_upload_on_completion": True,
            "auto_delete_local_files": False,
            "pulse3d_version": "6.7.9",
        },
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(comm_from_server, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    assert shared_values_dict["config_settings"] == comm_from_server["content"]
    assert shared_values_dict["user_creds"] == {
        "customer_id": new_customer_id,
        "user_name": new_username,
        "user_password": new_pass_key,
    }

    to_file_writer_queue = test_process_manager.queue_container.to_file_writer
    confirm_queue_is_eventually_of_size(to_file_writer_queue, 1)
    comm_from_fw = to_file_writer_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert comm_from_fw == {"command": "update_user_settings", "config_settings": comm_from_server["content"]}


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_update_shared_values__by_populating_file_writer_queue_when_recording_directory_updated(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server

    with tempfile.TemporaryDirectory() as expected_recordings_dir:
        communication = {
            "communication_type": "update_user_settings",
            "content": {"recording_directory": expected_recordings_dir},
        }

        put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)

        invoke_process_run_and_check_errors(monitor_thread)

        to_file_writer_queue = test_process_manager.queue_container.to_file_writer
        confirm_queue_is_eventually_of_size(to_file_writer_queue, 1)
        communication = to_file_writer_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert communication["command"] == "update_directory"
        assert communication["new_directory"] == expected_recordings_dir


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_stop_recording__by_passing_command_to_file_writer__and_setting_status_to_live_view_active(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server
    expected_timepoint = 55432
    communication = {
        "communication_type": "recording",
        "command": "stop_recording",
        "timepoint_to_stop_recording_at": expected_timepoint,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)
    main_to_fw_queue = test_process_manager.queue_container.to_file_writer
    confirm_queue_is_eventually_of_size(main_to_fw_queue, 1)

    actual = main_to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == communication
    assert test_process_manager.values_to_share_to_server["system_status"] == LIVE_VIEW_ACTIVE_STATE


@freeze_time(
    datetime.datetime(year=2020, month=11, day=16, hour=15, minute=14, second=44, microsecond=890122)
)
def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_start_recording__in_hardware_test_mode__by_passing_command_to_file_writer__and_setting_status_to_recording__and_updating_adc_offsets(
    test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server
    # expected_timepoint = 55432
    adc_offsets = dict()
    for well_idx in range(24):
        adc_offsets[well_idx] = {"construct": 0, "ref": 0}

    communication = {
        "communication_type": "recording",
        "command": "start_recording",
        "is_hardware_test_recording": True,
        "metadata_to_copy_onto_main_file_attributes": {"adc_offsets": adc_offsets},
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)
    main_to_fw_queue = test_process_manager.queue_container.to_file_writer
    confirm_queue_is_eventually_of_size(main_to_fw_queue, 1)

    actual = main_to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == communication

    shared_values_dict = test_process_manager.values_to_share_to_server
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

    server_to_main_queue = test_process_manager.queue_container.from_server
    adc_offsets = dict()
    for well_idx in range(24):
        adc_offsets[well_idx] = {"construct": 0, "ref": 0}

    expected_command = "bad_command"
    communication = {"communication_type": "recording", "command": expected_command}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)
    with pytest.raises(UnrecognizedRecordingCommandError, match=expected_command):
        invoke_process_run_and_check_errors(monitor_thread)


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__adds_update_recording_name_comm_fw(
    test_process_manager_creator, test_monitor, mocker, patch_print
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    server_to_main_queue = test_process_manager.queue_container.from_server
    main_to_fw_queue = test_process_manager.queue_container.to_file_writer

    communication = {
        "communication_type": "recording",
        "command": "update_recording_name",
        "new_name": "new_recording_name",
        "default_name": "old_recording_name",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)

    confirm_queue_is_eventually_of_size(main_to_fw_queue, 1)
    assert main_to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == communication


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_hard_stop_by_hard_stop_and_join_all_processes(
    test_process_manager_creator, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_hard_stop_and_join = mocker.patch.object(
        test_process_manager, "hard_stop_and_join_processes", autospec=True
    )  # Eli (11/17/20): mocking instead of spying because processes can't be joined unless they were actually started, and we're just doing a create_processes here

    server_to_main_queue = test_process_manager.queue_container.from_server

    communication = {"communication_type": "shutdown", "command": "hard_stop"}
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

    okc_process = test_process_manager.instrument_comm_process
    fw_process = test_process_manager.file_writer_process
    da_process = test_process_manager.data_analyzer_process

    spied_okc_join = mocker.spy(okc_process, "join")
    spied_fw_join = mocker.spy(fw_process, "join")
    spied_da_join = mocker.spy(da_process, "join")

    spied_okc_hard_stop = mocker.spy(okc_process, "hard_stop")
    spied_fw_hard_stop = mocker.spy(fw_process, "hard_stop")
    spied_da_hard_stop = mocker.spy(da_process, "hard_stop")

    server_to_main_queue = test_process_manager.queue_container.from_server

    communication = {"communication_type": "shutdown", "command": "hard_stop"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)

    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_empty(server_to_main_queue)

    spied_okc_hard_stop.assert_called_once()
    spied_fw_hard_stop.assert_called_once()
    spied_da_hard_stop.assert_called_once()
    spied_okc_join.assert_called_once()
    spied_fw_join.assert_called_once()
    spied_da_join.assert_called_once()


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_hard_stop_by_info_logging_items_in_queues_from_subprocesses(
    test_process_manager_creator, test_monitor, patch_subprocess_joins, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    server_to_main_queue = test_process_manager.queue_container.from_server

    okc_process = test_process_manager.instrument_comm_process
    fw_process = test_process_manager.file_writer_process
    da_process = test_process_manager.data_analyzer_process
    expected_okc_item = "item 1"
    expected_fw_item = "item 2"
    expected_da_item = "item 3"

    mocker.patch.object(okc_process, "hard_stop", autospec=True, return_value=expected_okc_item)
    mocker.patch.object(fw_process, "hard_stop", autospec=True, return_value=expected_fw_item)
    mocker.patch.object(da_process, "hard_stop", autospec=True, return_value=expected_da_item)

    communication = {"communication_type": "shutdown", "command": "hard_stop"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)

    mocker.patch.object(
        process_manager,
        "perf_counter",
        autospec=True,
        side_effect=[0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS],
    )

    mocked_monitor_logger_info = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    invoke_process_run_and_check_errors(monitor_thread)

    actual_log_message = mocked_monitor_logger_info.call_args[0][0]
    assert expected_okc_item in actual_log_message
    assert expected_fw_item in actual_log_message
    assert expected_da_item in actual_log_message


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_hard_stop_by__uploading_files_after_hard_stopping_and_joining_subprocesses(
    test_process_manager_creator, test_monitor, patch_subprocess_joins, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    server_to_main_queue = test_process_manager.queue_container.from_server

    shared_values_dict["config_settings"] = {"config": "settings"}

    mocked_hard_stop_and_join = mocker.patch.object(
        monitor_thread, "_hard_stop_and_join_processes_and_log_leftovers", autospec=True
    )

    def se(*args):
        mocked_hard_stop_and_join.assert_called_once()

    mocked_upload = mocker.patch.object(
        process_monitor, "upload_log_files_to_s3", autospec=True, side_effect=se
    )

    communication = {"communication_type": "shutdown", "command": "hard_stop"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)

    invoke_process_run_and_check_errors(monitor_thread)

    mocked_upload.assert_called_once_with(shared_values_dict["config_settings"])


def test_MantarrayProcessesMonitor__check_and_handle_server_to_main_queue__handles_shutdown_server_by_stopping_server(
    test_process_manager_creator, test_monitor, patch_subprocess_joins, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    server_to_main_queue = test_process_manager.queue_container.from_server

    shared_values_dict["config_settings"] = {}

    server_manager = test_process_manager.server_manager
    expected_server_item = "server item"

    spied_shutdown_server = mocker.spy(server_manager, "shutdown_server")
    mocker.patch.object(server_manager, "drain_all_queues", autospec=True, return_value=expected_server_item)

    server_to_main_queue = test_process_manager.queue_container.from_server

    communication = {"communication_type": "shutdown", "command": "shutdown_server"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(communication, server_to_main_queue)

    invoke_process_run_and_check_errors(monitor_thread)
    spied_shutdown_server.assert_called_once()


def test_MantarrayProcessesMonitor__logs_messages_from_server__and_redacts_mantarray_nickname(
    mocker, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)

    mocked_logger = mocker.patch.object(process_monitor.logger, "info", autospec=True)

    to_main_queue = test_process_manager.queue_container.from_server

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
    server_to_main_queue = test_process_manager.queue_container.from_server
    main_to_ic_queue = test_process_manager.queue_container.to_instrument_comm(0)

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

    test_command = {"communication_type": "stimulation", "command": "set_stim_status", "status": test_status}
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
    server_to_main_queue = test_process_manager.queue_container.from_server
    main_to_ic_queue = test_process_manager.queue_container.to_instrument_comm(0)
    main_to_fw_queue = test_process_manager.queue_container.to_file_writer

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
    assert main_to_ic_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == test_command
    confirm_queue_is_eventually_of_size(main_to_fw_queue, 1)
    assert main_to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == test_command


@pytest.mark.parametrize(
    "comm_type, command, queue_size",
    [
        ("mag_finding_analysis", "start_mag_analysis", 1),
        ("mag_finding_analysis", "other_command", 0),
        ("mag_analysis", "start_mag_analysis", 0),
    ],
)
def test_MantarrayProcessesMonitor__processes_start_mag_analysis_command(
    test_process_manager_creator, test_monitor, comm_type, command, queue_size
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, *_ = test_monitor(test_process_manager)
    server_to_main_queue = test_process_manager.queue_container.from_server
    main_to_da_queue = test_process_manager.queue_container.to_data_analyzer

    test_command = {
        "communication_type": comm_type,
        "command": command,
        "content": {},
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, server_to_main_queue)
    invoke_process_run_and_check_errors(monitor_thread)
    confirm_queue_is_eventually_of_size(main_to_da_queue, queue_size)


@pytest.mark.parametrize(
    "new_version,current_version,update_available",
    [
        ("1.0.0", "NOTASEMVER", False),
        ("1.0.0", "1.0.1", False),
        ("1.0.0", "1.0.0", False),
        ("1.0.1", "1.0.0", True),
    ],
)
def test_MantarrayProcessesMonitor__processes_set_latest_software_version_command(
    new_version, current_version, update_available, test_process_manager_creator, test_monitor, mocker
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    server_to_main_queue = test_process_manager.queue_container.from_server
    queue_to_server_ws = test_process_manager.queue_container.to_server

    mocker.patch.object(process_monitor, "CURRENT_SOFTWARE_VERSION", current_version)

    shared_values_dict["latest_software_version"] = None

    test_command = {"communication_type": "set_latest_software_version", "version": new_version}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, server_to_main_queue)

    # make sure value is stored
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["latest_software_version"] == new_version
    # make sure correct message sent to FE
    confirm_queue_is_eventually_of_size(queue_to_server_ws, 1)
    ws_message = queue_to_server_ws.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert ws_message == {
        "data_type": "sw_update",
        "data_json": json.dumps({"software_update_available": update_available}),
    }


@pytest.mark.parametrize("update_accepted", [True, False])
def test_MantarrayProcessesMonitor__processes_firmware_update_confirmation_command(
    update_accepted, test_process_manager_creator, test_monitor
):
    test_process_manager = test_process_manager_creator(use_testing_queues=True)
    monitor_thread, shared_values_dict, *_ = test_monitor(test_process_manager)
    shared_values_dict["system_status"] = UPDATES_NEEDED_STATE

    server_to_main_queue = test_process_manager.queue_container.from_server

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "firmware_update_confirmation", "update_accepted": update_accepted},
        server_to_main_queue,
    )
    invoke_process_run_and_check_errors(monitor_thread)
    assert shared_values_dict["firmware_update_accepted"] is update_accepted
    # make sure system status was not updated
    assert shared_values_dict["system_status"] == UPDATES_NEEDED_STATE
