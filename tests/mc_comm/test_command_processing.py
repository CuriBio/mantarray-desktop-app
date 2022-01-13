# -*- coding: utf-8 -*-
import copy
import queue
from random import choice
import time

from mantarray_desktop_app import convert_to_metadata_bytes
from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import InvalidCommandFromMainError
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import UnrecognizedCommandFromMainToMcCommError
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.firmware_downloader import download_firmware_updates
from mantarray_desktop_app.firmware_downloader import get_latest_firmware_versions
from mantarray_desktop_app.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app.worker_thread import ErrorCatchingThread
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import fixture_runnable_four_board_mc_comm_process
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_null_subprotocol
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_four_board_mc_comm_process,
    fixture_runnable_four_board_mc_comm_process,
    fixture_patch_print,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_four_board_mc_comm_process_no_handshake,
]


@pytest.mark.parametrize(
    "test_comm,test_description",
    [
        (
            {"communication_type": "bad_type"},
            "raises error with invalid communication_type",
        ),
        (
            {
                "communication_type": "mantarray_naming",
                "command": "bad_command",
            },
            "raises error with invalid mantarray_naming command",
        ),
        (
            {
                "communication_type": "to_instrument",
                "command": "bad_command",
            },
            "raises error with invalid to_instrument command",
        ),
        (
            {
                "communication_type": "acquisition_manager",
                "command": "bad_command",
            },
            "raises error with invalid acquisition_manager command",
        ),
        (
            {
                "communication_type": "stimulation",
                "command": "bad_command",
            },
            "raises error with invalid stimulation command",
        ),
    ],
)
def test_McCommunicationProcess__raises_error_when_receiving_invalid_command_from_main(
    test_comm, test_description, four_board_mc_comm_process, mocker, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    input_queue = four_board_mc_comm_process["board_queues"][0][0]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_comm, input_queue)
    with pytest.raises(UnrecognizedCommandFromMainToMcCommError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert test_comm["communication_type"] in str(exc_info.value)
    if "command" in test_comm:
        assert test_comm["command"] in str(exc_info.value)


def test_McCommunicationProcess__processes_set_mantarray_nickname_command(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    expected_nickname = "Mantarray++"
    set_nickname_command = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(set_nickname_command), input_queue
    )
    # run mc_process one iteration to send the command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator one iteration to process the command
    invoke_process_run_and_check_errors(simulator)
    actual = simulator.get_metadata_dict()[MANTARRAY_NICKNAME_UUID.bytes]
    assert actual == convert_to_metadata_bytes(expected_nickname)
    # run mc_process one iteration to read response from simulator and send command completed response back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    command_response = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == set_nickname_command
    # confirm response is read by checking that no bytes are available to read from simulator
    assert simulator.in_waiting == 0


def test_McCommunicationProcess__processes_get_metadata_command(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    expected_response = {
        "communication_type": "metadata_comm",
        "command": "get_metadata",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), input_queue
    )
    # run mc_process one iteration to send the command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator one iteration to process the command
    invoke_process_run_and_check_errors(simulator)
    # run mc_process one iteration to get metadata from simulator and send back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    expected_response["metadata"] = MantarrayMcSimulator.default_metadata_values
    expected_response["board_index"] = 0
    command_response = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == expected_response


@pytest.mark.slow
@pytest.mark.timeout(20)
def test_McCommunicationProcess__processes_commands_from_main_when_process_is_fully_running(
    runnable_four_board_mc_comm_process,
):
    # Tanner (6/11/21): if this test times out, it means the get_metadata command response was never sent to main
    mc_process = runnable_four_board_mc_comm_process["mc_process"]
    board_queues = runnable_four_board_mc_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]

    expected_nickname = "Running McSimulator"
    set_nickname_command = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    test_command = {
        "communication_type": "metadata_comm",
        "command": "get_metadata",
    }
    handle_putting_multiple_objects_into_empty_queue(
        [set_nickname_command, copy.deepcopy(test_command)],
        input_queue,
        sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )
    mc_process.start()

    while True:
        try:
            item = output_queue.get_nowait()
            if item.get("command", None) == "get_metadata":
                assert item["metadata"][MANTARRAY_NICKNAME_UUID] == expected_nickname
                break
        except queue.Empty:
            pass
        time.sleep(0.5)
    mc_process.soft_stop()
    mc_process.join()


def test_McCommunicationProcess__processes_command_response_when_packet_received_in_between_sending_command_and_receiving_response(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    test_command = {
        "communication_type": "metadata_comm",
        "command": "get_metadata",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, input_queue)
    # send command to simulator and read status beacon sent before command response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # remove status beacon log message
    confirm_queue_is_eventually_of_size(output_queue, 1)
    output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    # confirm command response is received and data sent back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)


def test_McCommunicationProcess__processes_reboot_command(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]

    mocker.patch.object(  # Tanner (4/6/21): Need to prevent automatic beacons without interrupting the beacon sent after boot-up
        mc_simulator,
        "_get_secs_since_last_status_beacon",
        autospec=True,
        return_value=0,
    )
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        side_effect=[AVERAGE_MC_REBOOT_DURATION_SECONDS],
    )
    set_connection_and_register_simulator(four_board_mc_comm_process_no_handshake, mantarray_mc_simulator)

    expected_response = {
        "communication_type": "to_instrument",
        "command": "reboot",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), input_queue
    )
    # run mc_process one iteration to send reboot command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator to start reboot and mc_process to confirm reboot started
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    command_response = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_response["message"] = "Instrument beginning reboot"
    assert command_response == expected_response
    # run simulator to finish reboot and mc_process to send reboot complete message to main
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(
        output_queue, 2
    )  # first message should be reboot complete message, second message should be status code log message
    reboot_response = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_response["message"] = "Instrument completed reboot"
    assert reboot_response == expected_response


def test_McCommunicationProcess__processes_dump_eeprom_command(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    expected_response = {
        "communication_type": "to_instrument",
        "command": "dump_eeprom",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), input_queue
    )
    # run mc_process to send command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # run mc_process to process command response and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    # confirm correct message sent to main
    confirm_queue_is_eventually_of_size(output_queue, 1)
    message_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_response["eeprom_contents"] = simulator.get_eeprom_bytes()
    assert message_to_main == expected_response


def test_McCommunicationProcess__processes_change_magnetometer_config_command(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    test_num_wells = 24
    # set arbitrary configuration and sampling period
    expected_magnetometer_config = create_magnetometer_config_dict(test_num_wells)
    for key in expected_magnetometer_config[9].keys():
        expected_magnetometer_config[9][key] = True
    expected_sampling_period = 14000
    # send command to mc_process
    expected_response = {
        "communication_type": "acquisition_manager",
        "command": "change_magnetometer_config",
        "magnetometer_config": expected_magnetometer_config,
        "sampling_period": expected_sampling_period,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), input_queue
    )
    # run mc_process to send command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # assert that sampling period and configuration were updated
    assert simulator.get_sampling_period_us() == expected_sampling_period
    assert simulator.get_magnetometer_config() == expected_magnetometer_config
    # run mc_process to process command response and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    # confirm correct message sent to main
    confirm_queue_is_eventually_of_size(output_queue, 1)
    message_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert message_to_main == expected_response


def test_McCommunicationProcess__processes_set_protocols_command(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # confirm preconditions
    assert simulator.get_stim_info() == {}

    expected_protocol_ids = (None, "A", "B", "C")
    test_num_wells = 24
    expected_stim_info = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "stimulation_type": choice(["V", "C"]),
                "run_until_stopped": choice([False, True]),
                "subprotocols": [
                    choice([get_random_subprotocol(), get_null_subprotocol(500)]) for _ in range(2)
                ],
            }
            for protocol_id in expected_protocol_ids[1:]
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(expected_protocol_ids)
            for well_idx in range(test_num_wells)
        },
    }
    # send command to mc_process
    expected_response = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), input_queue
    )
    # run mc_process to send command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # assert that protocols were updated
    actual = simulator.get_stim_info()
    for protocol_idx in range(len(expected_protocol_ids) - 1):
        expected_protocol_copy = copy.deepcopy(expected_stim_info["protocols"][protocol_idx])
        del expected_protocol_copy["protocol_id"]  # the actual protocol ID letter is not included
        assert actual["protocols"][protocol_idx] == expected_protocol_copy, protocol_idx
    assert actual["protocol_assignments"] == {  # indices of the protocol are used instead
        well_name: (None if protocol_id is None else expected_protocol_ids.index(protocol_id) - 1)
        for well_name, protocol_id in expected_stim_info["protocol_assignments"].items()
    }
    # run mc_process to process command response and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    # confirm correct message sent to main
    confirm_queue_is_eventually_of_size(output_queue, 1)
    message_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert message_to_main == expected_response


def test_McCommunicationProcess__processes_get_latest_firmware_versions_command(
    four_board_mc_comm_process_no_handshake, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    input_queue = board_queues[0][0]

    spied_thread_init = mocker.spy(mc_comm.ErrorCatchingThread, "__init__")
    mocked_thread_start = mocker.patch.object(mc_comm.ErrorCatchingThread, "start", autospec=True)
    # mock so thread won't get deleted on same iteration it is created
    mocker.patch.object(mc_comm.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    test_latest_software_version = "1.0.0"
    test_main_firmware_version = "2.0.0"

    # send command to mc_process
    test_command = {
        "communication_type": "firmware_update",
        "command": "get_latest_firmware_versions",
        "latest_software_version": test_latest_software_version,
        "main_firmware_version": test_main_firmware_version,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(copy.deepcopy(test_command), input_queue)

    assert mc_process._fw_update_worker_thread is None
    invoke_process_run_and_check_errors(mc_process)
    assert isinstance(mc_process._fw_update_worker_thread, ErrorCatchingThread) is True
    assert mc_process._fw_update_thread_dict == {
        "communication_type": "firmware_update",
        "command": "get_latest_firmware_versions",
        "latest_firmware_versions": {},
    }
    spied_thread_init.assert_called_once_with(
        mocker.ANY,  # this is the actual thread instance
        target=get_latest_firmware_versions,
        args=(
            mc_process._fw_update_thread_dict,
            test_latest_software_version,
            test_main_firmware_version,
        ),
    )
    mocked_thread_start.assert_called_once()


@pytest.mark.parametrize(
    "main_fw_update,channel_fw_update",
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_McCommunicationProcess__handles_download_firmware_updates_command(
    main_fw_update, channel_fw_update, four_board_mc_comm_process_no_handshake, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    input_queue = board_queues[0][0]

    spied_thread_init = mocker.spy(mc_comm.ErrorCatchingThread, "__init__")
    mocked_thread_start = mocker.patch.object(mc_comm.ErrorCatchingThread, "start", autospec=True)
    # mock so thread won't get deleted on same iteration it is created
    mocker.patch.object(mc_comm.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    test_username = "user"
    test_password = "pw"

    test_command = {
        "communication_type": "firmware_update",
        "command": "download_firmware_updates",
        "main": main_fw_update,
        "channel": channel_fw_update,
        "username": test_username,
        "password": test_password,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(copy.deepcopy(test_command), input_queue)

    assert mc_process._fw_update_worker_thread is None
    if main_fw_update or channel_fw_update:
        invoke_process_run_and_check_errors(mc_process)
        assert isinstance(mc_process._fw_update_worker_thread, ErrorCatchingThread) is True
        assert mc_process._fw_update_thread_dict == {
            "communication_type": "firmware_update",
            "command": "download_firmware_updates",
            "main": None,
            "channel": None,
        }
        spied_thread_init.assert_called_once_with(
            mocker.ANY,  # this is the actual thread instance
            target=download_firmware_updates,
            args=(
                mc_process._fw_update_thread_dict,
                main_fw_update,
                channel_fw_update,
                test_username,
                test_password,
            ),
        )
        mocked_thread_start.assert_called_once()
    else:
        with pytest.raises(
            InvalidCommandFromMainError,
            match="Cannot download firmware files if neither firmware type needs an update",
        ):
            invoke_process_run_and_check_errors(mc_process)
