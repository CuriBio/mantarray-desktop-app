# -*- coding: utf-8 -*-
import copy

from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app import STIM_MAX_PULSE_DURATION_MICROSECONDS
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
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
def test_McCommunicationProcess__handles_set_protocol_command(
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

    expected_stim_configs = [random_module_stim_config() for i in range(24)]
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
