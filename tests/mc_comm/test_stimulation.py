# -*- coding: utf-8 -*-
import copy
from random import choice
from random import randint

from mantarray_desktop_app import convert_well_name_to_module_id
from mantarray_desktop_app import STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
from mantarray_desktop_app import StimulationProtocolUpdateFailedError
from mantarray_desktop_app import StimulationProtocolUpdateWhileStimulatingError
from mantarray_desktop_app import StimulationStatusUpdateFailedError
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_null_subprotocol
from ..fixtures_mc_simulator import get_random_pulse_subprotocol
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_patch_print,
    fixture_four_board_mc_comm_process_no_handshake,
    fixture_mantarray_mc_simulator_no_beacon,
]


def create_random_stim_info():
    protocol_ids = (None, "A", "B", "C", "D")
    return {
        "protocols": [
            {
                "protocol_id": pid,
                "stimulation_type": choice(["C", "V"]),
                "run_until_stopped": choice([True, False]),
                "subprotocols": [
                    choice([get_random_pulse_subprotocol(), get_null_subprotocol(450)])
                    for _ in range(randint(1, 2))
                ],
            }
            for pid in protocol_ids[1:]
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(protocol_ids)
            for well_idx in range(24)
        },
    }


def set_stimulation_protocols(
    mc_fixture,
    simulator,
    stim_info,
):
    mc_process = mc_fixture["mc_process"]
    from_main_queue = mc_fixture["board_queues"][0][0]
    to_main_queue = mc_fixture["board_queues"][0][1]

    config_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": stim_info,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(config_command, from_main_queue)
    # send command, process command, process command response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)


def test_McCommunicationProcess__processes_start_and_stop_stimulation_commands__when_commands_are_successful(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    expected_stim_info = create_random_stim_info()
    set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, expected_stim_info)
    expected_stim_running_statuses = (
        {
            convert_well_name_to_module_id(well_name): bool(protocol_id)
            for well_name, protocol_id in expected_stim_info["protocol_assignments"].items()
        },
        {module_id: False for module_id in range(1, 25)},
    )

    for command, stim_running_statuses in (
        ("start_stimulation", expected_stim_running_statuses[0]),
        ("stop_stimulation", expected_stim_running_statuses[1]),
    ):
        # send command to mc_process
        expected_response = {"communication_type": "stimulation", "command": command}
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            copy.deepcopy(expected_response), input_queue
        )
        # run mc_process to send command
        invoke_process_run_and_check_errors(mc_process)
        # run simulator to process command and send response
        invoke_process_run_and_check_errors(simulator)
        # assert that stim statuses were updated correctly
        assert simulator.get_stim_running_statuses() == stim_running_statuses
        # run mc_process to process command response and send message back to main
        invoke_process_run_and_check_errors(mc_process)
        # confirm correct message sent to main
        confirm_queue_is_eventually_of_size(output_queue, 1)
        message_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert message_to_main == expected_response


def test_McCommunicationProcess__raises_error_if_set_protocols_command_received_while_stimulation_is_running(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, create_random_stim_info())

    # start stimulation
    start_stim_command = {"communication_type": "stimulation", "command": "start_stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_stim_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # confirm correct message sent to main
    confirm_queue_is_eventually_of_size(output_queue, 1)
    output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    # send set protocols command and confirm error is raised
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": create_random_stim_info(),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, input_queue)
    with pytest.raises(StimulationProtocolUpdateWhileStimulatingError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__raises_error_if_set_protocols_command_fails(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # send set protocols command with too many subprotocols in a protocol and confirm error is raised
    bad_stim_info = create_random_stim_info()
    bad_stim_info["protocols"][0]["subprotocols"].extend(
        [get_null_subprotocol(190)] * STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
    )
    with pytest.raises(StimulationProtocolUpdateFailedError):
        set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, bad_stim_info)


def test_McCommunicationProcess__raises_error_if_start_stim_command_fails(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # start stim before protocols are set and confirm error is raised from command failure response
    start_stim_command = {"communication_type": "stimulation", "command": "start_stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_stim_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    with pytest.raises(StimulationStatusUpdateFailedError, match="start_stimulation"):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__raises_error_if_stop_stim_command_fails(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # stop stim when it isn't running confirm error is raised from command failure response
    stop_stim_command = {"communication_type": "stimulation", "command": "stop_stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_stim_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    with pytest.raises(StimulationStatusUpdateFailedError, match="stop_stimulation"):
        invoke_process_run_and_check_errors(mc_process)
