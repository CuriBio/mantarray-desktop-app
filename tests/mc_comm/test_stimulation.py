# -*- coding: utf-8 -*-
import copy

from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import ProtocolUpdateWhileStimulationIsRunningError
from mantarray_desktop_app import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app import STIM_MAX_PULSE_DURATION_MICROSECONDS
from mantarray_desktop_app import StimStatusUpdateBeforeProtocolsSetError
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
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
from ..fixtures_mc_simulator import random_module_stim_config
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_four_board_mc_comm_process,
    fixture_patch_print,
    fixture_four_board_mc_comm_process_no_handshake,
]


@pytest.mark.slow
def test_McCommunicationProcess__handles_set_protocol_command__when_no_stimulators_are_running(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # patching so errors aren't raised
    mocker.patch.object(mc_comm, "_get_secs_since_command_sent", autospec=True, return_value=0)

    expected_stim_configs = [random_module_stim_config() for _ in range(24)]
    test_pulse_dicts = list()
    for stim_config in expected_stim_configs:
        test_dict = copy.deepcopy(stim_config["pulse"])
        test_dict["total_active_duration"] = STIM_MAX_PULSE_DURATION_MICROSECONDS
        test_pulse_dicts.append(test_dict)

    expected_response = {
        "communication_type": "stimulation",
        "command": "set_protocol",
        "protocols": [
            {
                "stimulation_type": expected_stim_configs[well_idx]["stimulation_type"],
                "well_number": GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx),
                "total_protocol_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                "pulses": [test_pulse_dicts[well_idx]],
            }
            for well_idx in range(24)
        ],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )

    # send all commands to simulator at once
    invoke_process_run_and_check_errors(mc_process)
    # process command for each module ID and return responses
    invoke_process_run_and_check_errors(simulator, num_iterations=24)
    # process response and send messages to main
    invoke_process_run_and_check_errors(mc_process, num_iterations=24)

    # test that stimulator config was set correctly
    simulator_stim_config = simulator.get_stim_config()
    for well_idx in range(24):
        module_id = SERIAL_COMM_WELL_IDX_TO_MODULE_ID[well_idx]
        assert (
            simulator_stim_config[module_id] == expected_stim_configs[well_idx]
        ), f"Well: {well_idx}, Module {module_id}"
    # confirm all command responses were sent back to main
    confirm_queue_is_eventually_of_size(to_main_queue, 24)


@pytest.mark.slow
def test_McCommunicationProcess__handles_set_stim_status_command__when_at_least_one_protocol_has_been_set(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # patching so errors aren't raised
    mocker.patch.object(mc_comm, "_get_secs_since_command_sent", autospec=True, return_value=0)

    test_wells = [1, 5, 10]  # arbitrary wells
    num_wells = len(test_wells)

    expected_stim_configs = [random_module_stim_config() for _ in range(num_wells)]
    test_pulse_dicts = list()
    for stim_config in expected_stim_configs:
        test_dict = copy.deepcopy(stim_config["pulse"])
        test_dict["total_active_duration"] = STIM_MAX_PULSE_DURATION_MICROSECONDS
        test_pulse_dicts.append(test_dict)

    set_protocol_command = {
        "communication_type": "stimulation",
        "command": "set_protocol",
        "protocols": [
            {
                "stimulation_type": expected_stim_configs[i]["stimulation_type"],
                "well_number": GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx),
                "total_protocol_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                "pulses": [test_pulse_dicts[i]],
            }
            for i, well_idx in enumerate(test_wells)
        ],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocol_command, from_main_queue)

    # send all commands to simulator at once
    invoke_process_run_and_check_errors(mc_process)
    # process command for each module ID and return responses
    invoke_process_run_and_check_errors(simulator, num_iterations=num_wells)
    # process response and send messages to main
    invoke_process_run_and_check_errors(mc_process, num_iterations=num_wells)
    drain_queue(to_main_queue)

    # start stimulation
    expected_response = {
        "communication_type": "stimulation",
        "command": "set_stim_status",
        "status": True,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    # send start stim command to simulator, process command, process response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    # make sure stim statuses are correct
    assert simulator.get_stimulation_statuses() == [
        SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id] in test_wells for module_id in range(1, 25)
    ]
    # confirm command response is sent back to main
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_main == {
        "command": "set_stim_status",
        "communication_type": "stimulation",
        "status": True,
        "wells_currently_stimulating": test_wells,
    }

    # stop stimulation
    expected_response = {
        "communication_type": "stimulation",
        "command": "set_stim_status",
        "status": False,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    # send stop stim command to simulator, process command, process response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    # make sure all modules have stopped stimulating
    assert simulator.get_stimulation_statuses() == [False] * 24
    # confirm command response is sent back to main
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_main == {
        "command": "set_stim_status",
        "communication_type": "stimulation",
        "status": False,
    }


@pytest.mark.slow
def test_McCommunicationProcess__handles_set_protocol_command__when_stimulation_is_running(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # patching so errors aren't raised
    mocker.patch.object(mc_comm, "_get_secs_since_command_sent", autospec=True, return_value=0)

    expected_stim_configs = [random_module_stim_config() for _ in range(24)]
    test_pulse_dicts = list()
    for stim_config in expected_stim_configs:
        test_dict = copy.deepcopy(stim_config["pulse"])
        test_dict["total_active_duration"] = STIM_MAX_PULSE_DURATION_MICROSECONDS
        test_pulse_dicts.append(test_dict)

    expected_response = {
        "communication_type": "stimulation",
        "command": "set_protocol",
        "protocols": [
            {
                "stimulation_type": expected_stim_configs[well_idx]["stimulation_type"],
                "well_number": GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx),
                "total_protocol_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                "pulses": [test_pulse_dicts[well_idx]],
            }
            for well_idx in range(24)
        ],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )

    # send all commands to simulator at once
    invoke_process_run_and_check_errors(mc_process)
    # process command for each module ID and return responses
    invoke_process_run_and_check_errors(simulator, num_iterations=24)
    # process response and send messages to main
    invoke_process_run_and_check_errors(mc_process, num_iterations=24)

    # send start stimulation to simulator
    expected_response = {
        "communication_type": "stimulation",
        "command": "set_stim_status",
        "status": True,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    invoke_process_run_and_check_errors(mc_process)

    # attempt to set protocol and make sure error is raised
    expected_response = {
        "communication_type": "stimulation",
        "command": "set_protocol",
        "protocols": [
            {
                "stimulation_type": "V",
                "well_number": "A1",
                "total_protocol_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                "pulses": [test_pulse_dicts[0]],
            }
        ],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    with pytest.raises(ProtocolUpdateWhileStimulationIsRunningError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__handles_set_stim_status_command__before_any_protocols_are_set(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    # patching so errors aren't raised
    mocker.patch.object(mc_comm, "_get_secs_since_command_sent", autospec=True, return_value=0)

    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # send set_stim_status and make sure error is raised (status value currently doesn't matter from this test)
    expected_response = {
        "communication_type": "stimulation",
        "command": "set_stim_status",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    with pytest.raises(StimStatusUpdateBeforeProtocolsSetError):
        invoke_process_run_and_check_errors(mc_process)
