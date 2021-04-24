# -*- coding: utf-8 -*-
import copy

from mantarray_desktop_app import convert_to_metadata_bytes
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_BYTE_LOOKUP_TABLE
from mantarray_desktop_app import UnrecognizedCommandFromMainToMcCommError
from mantarray_desktop_app.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_four_board_mc_comm_process,
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
    ],
)
def test_McCommunicationProcess__raises_error_when_receiving_invalid_command_from_main(
    test_comm, test_description, four_board_mc_comm_process, mocker, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    input_queue = four_board_mc_comm_process["board_queues"][0][0]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_comm, input_queue
    )
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
    four_board_mc_comm_process,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
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
        [set_nickname_command, copy.deepcopy(test_command)], input_queue
    )
    mc_process.start()
    confirm_queue_is_eventually_empty(  # Tanner (3/3/21): Using timeout longer than registration period here to give sufficient time to make sure queue is emptied
        input_queue, timeout_seconds=SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS + 8
    )
    mc_process.soft_stop()
    mc_process.join()

    to_main_items = drain_queue(output_queue)
    for item in to_main_items:
        if item.get("command", None) == "get_metadata":
            assert item["metadata"][MANTARRAY_NICKNAME_UUID] == expected_nickname
            break
    else:
        assert False, "expected response to main not found"


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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, input_queue
    )
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
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator
    )

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


def test_McCommunicationProcess__processes_change_sensors_axes_sampling_period_command(
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

    expected_sampling_period = 14000
    expected_well_idx = 23
    test_sensor_axis_id = SERIAL_COMM_SENSOR_AXIS_BYTE_LOOKUP_TABLE["A"]["Z"]
    expected_response = {
        "communication_type": "to_instrument",
        "command": "change_sensor_axis_sampling_period",
        "well_index": expected_well_idx,
        "sensor_axis_id": test_sensor_axis_id,
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
    actual = simulator.get_well_recording_id_sampling_period(
        expected_well_idx, test_sensor_axis_id
    )
    assert actual == expected_sampling_period
    # run mc_process to process command response and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    # confirm correct message sent to main
    confirm_queue_is_eventually_of_size(output_queue, 1)
    message_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert message_to_main == expected_response
