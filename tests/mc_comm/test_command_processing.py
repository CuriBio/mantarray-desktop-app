# -*- coding: utf-8 -*-
import copy
import queue
from random import choice
import time

from mantarray_desktop_app import InvalidCommandFromMainError
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import UnrecognizedCommandFromMainToMcCommError
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.simulators import mc_simulator
from mantarray_desktop_app.simulators.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app.sub_processes import mc_comm
from mantarray_desktop_app.utils.data_parsing_cy import sort_serial_packets
from mantarray_desktop_app.utils.serial_comm import convert_status_code_bytes_to_dict
from mantarray_desktop_app.utils.serial_comm import create_data_packet
from mantarray_desktop_app.workers.firmware_downloader import check_versions
from mantarray_desktop_app.workers.firmware_downloader import download_firmware_updates
from mantarray_desktop_app.workers.worker_thread import ErrorCatchingThread
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import fixture_runnable_four_board_mc_comm_process
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import DEFAULT_SIMULATOR_STATUS_CODES
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_random_stim_delay
from ..fixtures_mc_simulator import get_random_stim_pulse
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
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
            {"communication_type": "mantarray_naming", "command": "bad_command"},
            "raises error with invalid mantarray_naming command",
        ),
        (
            {"communication_type": "to_instrument", "command": "bad_command"},
            "raises error with invalid to_instrument command",
        ),
        (
            {"communication_type": "acquisition_manager", "command": "bad_command"},
            "raises error with invalid acquisition_manager command",
        ),
        (
            {"communication_type": "stimulation", "command": "bad_command"},
            "raises error with invalid stimulation command",
        ),
        (
            {"communication_type": "firmware_update", "command": "bad_command"},
            "raises error with invalid firmware_update command",
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
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator["simulator"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    set_connection_and_register_simulator(four_board_mc_comm_process_no_handshake, mantarray_mc_simulator)

    # mock so reboots complete on the next iteration
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        return_value=AVERAGE_MC_REBOOT_DURATION_SECONDS,
    )
    # mock to have control over when beacons are sent
    mocked_get_secs_since_beacon = mocker.patch.object(
        mc_simulator, "_get_secs_since_last_status_beacon", autospec=True, return_value=0
    )

    # send set nickname command
    expected_nickname = "Mantarray++  "
    set_nickname_command = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(set_nickname_command), input_queue
    )
    # send another command to make sure it is ignored during nickname update process
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "metadata_comm", "command": "get_metadata"}, input_queue
    )

    # send the command
    invoke_process_run_and_check_errors(mc_process)
    # process the command
    invoke_process_run_and_check_errors(simulator)
    # complete reboot and make sure nickname was updated
    invoke_process_run_and_check_errors(simulator)
    actual = simulator._metadata_dict[MANTARRAY_NICKNAME_UUID]
    assert actual == expected_nickname
    # run mc_process one iteration to read response from simulator and send command completed response back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    command_response = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == set_nickname_command
    # make sure second command not processed yet
    confirm_queue_is_eventually_of_size(input_queue, 1)
    # run simulator one more iteration to complete 2nd reboot
    mocked_get_secs_since_beacon.return_value = SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # make sure second command gets processed now
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_empty(input_queue)


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

    expected_response = {"communication_type": "metadata_comm", "command": "get_metadata"}
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
    expected_response["metadata"] = dict(MantarrayMcSimulator.default_metadata_values)
    expected_response["metadata"]["status_codes_prior_to_reboot"] = convert_status_code_bytes_to_dict(
        DEFAULT_SIMULATOR_STATUS_CODES
    )
    expected_response["board_index"] = 0
    command_response = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == expected_response


@pytest.mark.slow
@pytest.mark.timeout(20)
def test_McCommunicationProcess__processes_commands_from_main_when_process_is_fully_running(
    runnable_four_board_mc_comm_process, mocker
):
    # Tanner (6/11/21): if this test times out, it means the get_metadata command response was never sent to main
    mc_process = runnable_four_board_mc_comm_process["mc_process"]
    board_queues = runnable_four_board_mc_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]

    test_command = {"communication_type": "metadata_comm", "command": "get_metadata"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(copy.deepcopy(test_command), input_queue)
    mc_process.start()

    while True:
        try:
            item = output_queue.get_nowait()
            if item.get("command", None) == "get_metadata":
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
    input_queue, output_queue = board_queues[0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    test_command = {"communication_type": "metadata_comm", "command": "get_metadata"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, input_queue)
    # send command to simulator and read status beacon sent before command response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # confirm command response is received and data sent back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)


def test_McCommunicationProcess__processes_command_responses_from_two_different_packet_types_out_of_order(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    input_queue, output_queue = board_queues[0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    # mock so no data packets are sent
    mocker.patch.object(mc_simulator, "_get_us_since_last_data_packet", autospec=True, return_value=0)

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # send two commands
    test_command = {"communication_type": "metadata_comm", "command": "get_metadata"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)
    test_command = dict(START_MANAGED_ACQUISITION_COMMUNICATION)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)

    # process both commands
    invoke_process_run_and_check_errors(simulator, num_iterations=2)
    # reorder command responses and add them back to simulator's available data
    sorted_packet_dict = sort_serial_packets(bytearray(simulator.read_all()))
    reordered_response_packet_bytes = create_data_packet(
        *sorted_packet_dict["other_packet_info"][1]
    ) + create_data_packet(*sorted_packet_dict["other_packet_info"][0])
    test_command = {"command": "add_read_bytes", "read_bytes": reordered_response_packet_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    invoke_process_run_and_check_errors(simulator)

    # confirm command responses are processed without issue and msgs are sent back to main
    invoke_process_run_and_check_errors(mc_process)

    confirm_queue_is_eventually_of_size(output_queue, 2)
    assert output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)["command"] == "start_managed_acquisition"
    assert output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)["command"] == "get_metadata"


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
    confirm_queue_is_eventually_of_size(output_queue, 1)
    reboot_response = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_response["message"] = "Instrument completed reboot"
    assert reboot_response == expected_response


def test_McCommunicationProcess__processes_set_sampling_period_command(
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

    # set arbitrary sampling period
    expected_sampling_period = 14000
    # send command to mc_process
    expected_response = {
        "communication_type": "acquisition_manager",
        "command": "set_sampling_period",
        "sampling_period": expected_sampling_period,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), input_queue
    )
    # run mc_process to send command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # assert that sampling period was updated
    assert simulator._sampling_period_us == expected_sampling_period
    # run mc_process to process command response and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    # confirm correct message sent to main
    confirm_queue_is_eventually_of_size(output_queue, 1)
    message_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert message_to_main == expected_response


def test_McCommunicationProcess__processes_set_protocols_command__and_breaks_up_long_subprotocol_into_appropriately_sized_chunks(
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

    # confirm preconditions
    assert simulator._stim_info == {}

    expected_protocol_ids = (None, "A", "B", "C")
    test_num_wells = 24

    expected_stim_info = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "stimulation_type": choice(["V", "C"]),
                "run_until_stopped": choice([False, True]),
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_iterations": 1,
                        "subprotocols": [
                            choice([get_random_stim_pulse(), get_random_stim_delay()]) for _ in range(2)
                        ],
                    }
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
    expected_response = {"communication_type": "stimulation", "command": "set_protocols"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {**expected_response, "stim_info": expected_stim_info}, input_queue
    )
    # run mc_process to send command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # assert that protocols were updated
    actual = simulator._stim_info
    # don't loop over last test protocol ID because it's just a placeholder for no protocol
    for protocol_idx in range(len(expected_protocol_ids) - 1):
        expected_protocol_copy = copy.deepcopy(expected_stim_info["protocols"][protocol_idx])
        # the actual protocol ID letter is not included
        del expected_protocol_copy["protocol_id"]

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


def test_McCommunicationProcess__processes_check_versions_command(
    four_board_mc_comm_process_no_handshake, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    input_queue = board_queues[0][0]

    spied_thread_init = mocker.spy(mc_comm.ErrorCatchingThread, "__init__")
    mocked_thread_start = mocker.patch.object(mc_comm.ErrorCatchingThread, "start", autospec=True)
    # mock so thread won't get deleted on same iteration it is created
    mocker.patch.object(mc_comm.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    test_serial_number = MantarrayMcSimulator.default_mantarray_serial_number
    test_main_fw_version = MantarrayMcSimulator.default_mantarray_serial_number

    test_fw_update_dir_path = "fw/dir"

    # send command to mc_process
    test_command = {
        "communication_type": "firmware_update",
        "command": "check_versions",
        "serial_number": test_serial_number,
        "main_fw_version": test_main_fw_version,
        "fw_update_dir_path": test_fw_update_dir_path,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(copy.deepcopy(test_command), input_queue)

    assert mc_process._fw_update_worker_thread is None
    invoke_process_run_and_check_errors(mc_process)
    assert isinstance(mc_process._fw_update_worker_thread, ErrorCatchingThread) is True
    assert mc_process._fw_update_thread_dict == {
        "communication_type": "firmware_update",
        "command": "check_versions",
    }
    spied_thread_init.assert_called_once_with(
        mocker.ANY,  # this is the actual thread instance
        target=check_versions,
        args=(
            mc_process._fw_update_thread_dict,
            test_serial_number,
            test_main_fw_version,
            test_fw_update_dir_path,
        ),
        use_error_repr=False,
    )
    mocked_thread_start.assert_called_once()


@pytest.mark.parametrize(
    "main_fw_update,channel_fw_update",
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_McCommunicationProcess__handles_download_firmware_updates_command(
    main_fw_update, channel_fw_update, four_board_mc_comm_process_no_handshake, mocker, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    input_queue = board_queues[0][0]

    spied_thread_init = mocker.spy(mc_comm.ErrorCatchingThread, "__init__")
    mocked_thread_start = mocker.patch.object(mc_comm.ErrorCatchingThread, "start", autospec=True)
    # mock so thread won't get deleted on same iteration it is created
    mocker.patch.object(mc_comm.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    test_customer_id = "id"
    test_username = "user"
    test_password = "pw"

    test_fw_update_dir_path = "fw/dir"

    test_command = {
        "communication_type": "firmware_update",
        "command": "download_firmware_updates",
        "main": main_fw_update,
        "channel": channel_fw_update,
        "customer_id": test_customer_id,
        "username": test_username,
        "password": test_password,
        "fw_update_dir_path": test_fw_update_dir_path,
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
                test_customer_id,
                test_username,
                test_password,
                test_fw_update_dir_path,
            ),
        )
        mocked_thread_start.assert_called_once()
    else:
        with pytest.raises(
            InvalidCommandFromMainError,
            match="Cannot download firmware files if neither firmware type needs an update",
        ):
            invoke_process_run_and_check_errors(mc_process)
