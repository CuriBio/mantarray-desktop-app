# -*- coding: utf-8 -*-
import copy
from random import randint

from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
from mantarray_desktop_app import StimulationProtocolUpdateFailedError
from mantarray_desktop_app import StimulationProtocolUpdateWhileStimulatingError
from mantarray_desktop_app import StimulationStatusUpdateFailedError
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
import numpy as np
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import create_random_stim_info
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_null_subprotocol
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_patch_print,
    fixture_four_board_mc_comm_process_no_handshake,
    fixture_mantarray_mc_simulator_no_beacon,
]


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
            well_name: bool(protocol_id)
            for well_name, protocol_id in expected_stim_info["protocol_assignments"].items()
        },
        {well_name: False for well_name in expected_stim_info["protocol_assignments"].keys()},
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
        [get_null_subprotocol(19000)] * STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
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


def test_McCommunicationProcess__handles_stimulation_status_comm_from_instrument__one_status_per_packet(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    total_active_duration = 76000
    test_well_idx = randint(0, 23)
    expected_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "C",
                "run_until_stopped": False,
                "subprotocols": [get_random_subprotocol(total_active_duration=total_active_duration)],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
                "A" if well_idx == test_well_idx else None
            )
            for well_idx in range(24)
        },
    }
    # send command to mc_process
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, input_queue)
    # set protocols and process response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[0, total_active_duration],
    )
    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    # send start stimulation command
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)

    # process command, send back response and initial stimulator status packet
    invoke_process_run_and_check_errors(simulator)
    # process command response only
    invoke_process_run_and_check_errors(mc_process)
    # send stimulator status packet after initial subprotocol completes
    invoke_process_run_and_check_errors(simulator)
    # process both stimulator status packets
    invoke_process_run_and_check_errors(mc_process, num_iterations=2)
    assert simulator.in_waiting == 0

    # check status packets sent to file writer
    confirm_queue_is_eventually_of_size(to_fw_queue, 2)
    first_msg_to_fw = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert first_msg_to_fw["data_type"] == "stimulation"
    assert list(first_msg_to_fw["well_statuses"].keys()) == [test_well_idx]
    expected_well_statuses_1 = [[spied_global_timer.spy_return], [0]]  # subprotocol idx
    np.testing.assert_array_equal(first_msg_to_fw["well_statuses"][test_well_idx], expected_well_statuses_1)
    second_msg_to_fw = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert second_msg_to_fw["data_type"] == "stimulation"
    assert list(second_msg_to_fw["well_statuses"].keys()) == [test_well_idx]
    expected_well_statuses_2 = [
        [spied_global_timer.spy_return + total_active_duration],
        [255],  # subprotocol idx
    ]
    np.testing.assert_array_equal(second_msg_to_fw["well_statuses"][test_well_idx], expected_well_statuses_2)


def test_McCommunicationProcess__handles_stimulation_status_comm_from_instrument__multiple_statuses_for_a_single_well_in_a_single_packet(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    total_active_duration = 76000
    test_well_idx = randint(0, 23)
    expected_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "C",
                "run_until_stopped": True,
                "subprotocols": [get_random_subprotocol(total_active_duration=total_active_duration)],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
                "A" if well_idx == test_well_idx else None
            )
            for well_idx in range(24)
        },
    }
    # send command to mc_process
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, input_queue)
    # set protocols and process response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[total_active_duration],
    )
    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    # send start stimulation command
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # process command, send back and process response plus both stim statuses
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # process stimulator status packets
    invoke_process_run_and_check_errors(mc_process, num_iterations=1)
    assert simulator.in_waiting == 0

    # check status packets sent to file writer
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    msg_to_fw = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_fw["data_type"] == "stimulation"
    assert list(msg_to_fw["well_statuses"].keys()) == [test_well_idx]
    expected_well_statuses = [
        [spied_global_timer.spy_return, spied_global_timer.spy_return + total_active_duration],
        [0, 0],  # subprotocol idxs
    ]
    np.testing.assert_array_equal(msg_to_fw["well_statuses"][test_well_idx], expected_well_statuses)


def test_McCommunicationProcess__handles_stimulation_status_comm_from_instrument__multiple_statuses_for_a_multiple_wells_in_a_single_packet(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    # TODO
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    total_active_durations = [58000, 85000]
    test_well_indices = [10, 20]
    test_protocol_ids = ["A", "E"]
    test_num_wells_active = 2

    test_protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): None for well_idx in range(24)
    }
    for i, test_well_idx in enumerate(test_well_indices):
        test_protocol_assignments[
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(test_well_idx)
        ] = test_protocol_ids[i]

    expected_stim_info = {
        "protocols": [
            {
                "protocol_id": test_protocol_ids[i],
                "stimulation_type": "C",
                "run_until_stopped": True,
                "subprotocols": [
                    get_random_subprotocol(total_active_duration=total_active_durations[i]),
                    get_null_subprotocol(total_active_durations[i]),
                ],
            }
            for i in range(test_num_wells_active)
        ],
        "protocol_assignments": test_protocol_assignments,
    }
    # send command to mc_process
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, input_queue)
    # set protocols and process response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=total_active_durations,
    )
    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    # send start stimulation command
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # process command, send back and process response plus both stim statuses
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # process stimulator status packets
    invoke_process_run_and_check_errors(mc_process, num_iterations=1)
    assert simulator.in_waiting == 0

    # check status packets sent to file writer
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    msg_to_fw = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_fw["data_type"] == "stimulation"
    assert list(msg_to_fw["well_statuses"].keys()) == test_well_indices
    expected_well_statuses = (
        [
            [spied_global_timer.spy_return, spied_global_timer.spy_return + total_active_durations[0]],
            [0, 0],  # subprotocol idxs
        ],
        [
            [spied_global_timer.spy_return, spied_global_timer.spy_return + total_active_durations[1]],
            [0, 0],  # subprotocol idxs
        ],
    )
    np.testing.assert_array_equal(msg_to_fw["well_statuses"][test_well_indices[0]], expected_well_statuses[0])
    np.testing.assert_array_equal(msg_to_fw["well_statuses"][test_well_indices[1]], expected_well_statuses[1])
