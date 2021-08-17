# -*- coding: utf-8 -*-
import copy

from mantarray_desktop_app import convert_pulse_dict_to_bytes
from mantarray_desktop_app import convert_stim_status_list_to_bitmask
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import IncorrectPulseFromInstrumentError
from mantarray_desktop_app import IncorrectStimStatusesFromInstrumentError
from mantarray_desktop_app import IncorrectStimTypeFromInstrumentError
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import ProtocolUpdateWhileStimulationIsRunningError
from mantarray_desktop_app import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
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


GENERIC_PULSE_INFO_1 = {
    "phase_one_duration": 100,
    "phase_one_charge": 100,
    "interpulse_interval": 0,
    "phase_two_duration": 0,
    "phase_two_charge": 0,
    "repeat_delay_interval": 0,
}
GENERIC_PULSE_INFO_2 = {
    "phase_one_duration": 200,
    "phase_one_charge": 200,
    "interpulse_interval": 0,
    "phase_two_duration": 0,
    "phase_two_charge": 0,
    "repeat_delay_interval": 0,
}


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
def test_McCommunicationProcess__raises_error_if_set_protocol_command_received_when_stimulation_is_running(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
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


def test_McCommunicationProcess__raises_error_if_set_stim_status_command_received_before_any_protocols_are_set(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
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


@pytest.mark.slow
@pytest.mark.parametrize(
    "test_status,test_decsription",
    [
        (True, "raises error when incorrect stim statuses received after enabling wells"),
        (False, "raises error when incorrect stim statuses received after disabling wells"),
    ],
)
def test_McCommunicationProcess__raises_error_if_instrument_responds_with_different_stim_statuses_than_expected(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
    test_status,
    test_decsription,
    patch_print,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    test_well_idx = 0
    test_module_id = SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_idx]

    # set protocol on a single well
    test_stim_config = random_module_stim_config()
    test_stim_config["pulse"]["total_active_duration"] = STIM_MAX_PULSE_DURATION_MICROSECONDS
    set_protocol_command = {
        "communication_type": "stimulation",
        "command": "set_protocol",
        "protocols": [
            {
                "stimulation_type": test_stim_config["stimulation_type"],
                "well_number": GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(test_well_idx),
                "total_protocol_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                "pulses": [test_stim_config["pulse"]],
            }
        ],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocol_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    # if stopping stimulation, need to start it first
    if not test_status:
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            {
                "communication_type": "stimulation",
                "command": "set_stim_status",
                "status": True,
            },
            from_main_queue,
        )
        invoke_process_run_and_check_errors(mc_process)
        invoke_process_run_and_check_errors(simulator)
        invoke_process_run_and_check_errors(mc_process)

    # add a data packet to simulator with invalid bitmask to create bad response
    bad_stim_statuses = [
        module_id == 20 for module_id in range(1, 25)
    ]  # arbitrary status list, just needs to be incorrect
    data_to_send = bytes(8) + convert_stim_status_list_to_bitmask(bad_stim_statuses)
    bad_response = create_data_packet(
        0,  # dummy timestamp
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        data_to_send,
    )
    test_command = {"command": "add_read_bytes", "read_bytes": bad_response}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)

    # send command and run simulator to send bad response
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "stimulation",
            "command": "set_stim_status",
            "status": test_status,
        },
        from_main_queue,
    )
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # make sure error is raised
    with pytest.raises(IncorrectStimStatusesFromInstrumentError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    # make sure correct message is included in error
    expected_statuses = [test_status if i == test_module_id else False for i in range(1, 25)]
    expected_msg = f"Expected Module Statuses: {expected_statuses}, Actual: {bad_stim_statuses}"
    assert expected_msg in str(exc_info.value)


@pytest.mark.slow
def test_McCommunicationProcess__raises_error_if_instrument_responds_to_start_stimulators_command_with_unexpected_stim_type_for_a_single_module(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # patching so errors aren't raised
    mocker.patch.object(mc_comm, "_get_secs_since_command_sent", autospec=True, return_value=0)

    test_well_idx = 1
    test_module_id = SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_idx]

    # set protocol on a single well
    test_pulse = copy.deepcopy(GENERIC_PULSE_INFO_1)
    test_pulse["total_active_duration"] = STIM_MAX_PULSE_DURATION_MICROSECONDS
    set_protocol_command = {
        "communication_type": "stimulation",
        "command": "set_protocol",
        "protocols": [
            {
                "stimulation_type": "V",
                "well_number": GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx),
                "total_protocol_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                "pulses": [test_pulse],
            }
            for well_idx in range(2)
        ],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocol_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator, num_iterations=2)
    invoke_process_run_and_check_errors(mc_process, num_iterations=2)

    # add a data packet to simulator with invalid pulse
    stim_statuses = [
        SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id] in (0, 1) for module_id in range(1, 25)
    ]  # arbitrary status list, just needs to be incorrect
    data_to_send = (
        bytes(8)  # dummy timestamp bytes
        + convert_stim_status_list_to_bitmask(stim_statuses)
        + bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[0], 1])  # module ID, correct stim type
        + convert_pulse_dict_to_bytes(test_pulse)
        + bytes([test_module_id, 0])  # module ID, incorrect stim type
        + convert_pulse_dict_to_bytes(test_pulse)
    )
    bad_response = create_data_packet(
        0,  # dummy timestamp
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        data_to_send,
    )
    test_command = {"command": "add_read_bytes", "read_bytes": bad_response}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)

    # send command and run simulator to send bad response
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "stimulation",
            "command": "set_stim_status",
            "status": True,
        },
        from_main_queue,
    )
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # make sure error is raised
    with pytest.raises(IncorrectStimTypeFromInstrumentError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    # make sure correct message is included in error
    expected_msg = f"Incorrect stim type (C) for module {test_module_id}"
    assert expected_msg in str(exc_info.value)


@pytest.mark.slow
def test_McCommunicationProcess__raises_error_if_instrument_responds_to_start_stimulators_command_with_unexpected_pulse_for_a_single_module(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # patching so errors aren't raised
    mocker.patch.object(mc_comm, "_get_secs_since_command_sent", autospec=True, return_value=0)

    test_well_idx = 1
    test_module_id = SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_idx]

    # set protocol on a single well
    test_pulse = copy.deepcopy(GENERIC_PULSE_INFO_1)
    test_pulse["total_active_duration"] = STIM_MAX_PULSE_DURATION_MICROSECONDS
    set_protocol_command = {
        "communication_type": "stimulation",
        "command": "set_protocol",
        "protocols": [
            {
                "stimulation_type": "C",
                "well_number": GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx),
                "total_protocol_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS,
                "pulses": [copy.deepcopy(test_pulse)],
            }
            for well_idx in range(2)
        ],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocol_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator, num_iterations=2)
    invoke_process_run_and_check_errors(mc_process, num_iterations=2)

    bad_pulse = copy.deepcopy(GENERIC_PULSE_INFO_2)
    # add a data packet to simulator with invalid pulse
    stim_statuses = [
        SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id] in (0, 1) for module_id in range(1, 25)
    ]  # arbitrary status list, just needs to be incorrect
    data_to_send = (
        bytes(8)  # dummy timestamp bytes
        + convert_stim_status_list_to_bitmask(stim_statuses)
        + bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[0], 0])  # module ID, stim type
        + convert_pulse_dict_to_bytes(test_pulse)
        + bytes([test_module_id, 0])  # module ID, stim type
        + convert_pulse_dict_to_bytes(bad_pulse)
    )
    bad_response = create_data_packet(
        0,  # dummy timestamp
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        data_to_send,
    )
    test_command = {"command": "add_read_bytes", "read_bytes": bad_response}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)

    # send command and run simulator to send bad response
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "stimulation",
            "command": "set_stim_status",
            "status": True,
        },
        from_main_queue,
    )
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # make sure error is raised
    with pytest.raises(IncorrectPulseFromInstrumentError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    # make sure correct message is included in error
    del test_pulse["total_active_duration"]
    expected_msg = (
        f"Incorrect pulse for module ID {test_module_id}. Expected: {test_pulse}, Actual: {bad_pulse}"
    )
    assert expected_msg in str(exc_info.value)


@pytest.mark.slow
def test_McCommunicationProcess__handles_switching_between_pulses_according_protocol_for_each_well_that_needs_an_update(
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

    # patch so no pulses are updated yet
    mocked_get_secs = mocker.patch.object(
        mc_comm, "_get_secs_since_pulse_started", autospec=True, return_value=0
    )

    test_wells = [0, 1, 2]
    test_num_wells = len(test_wells)
    wells_to_update = [0, 2]

    # set up different duration for first pulse in each protocol
    test_pulse_dict_a1 = copy.deepcopy(GENERIC_PULSE_INFO_1)
    test_pulse_dict_a1["total_active_duration"] = STIM_MAX_PULSE_DURATION_MICROSECONDS
    test_pulse_dict_b1 = copy.deepcopy(GENERIC_PULSE_INFO_1)
    test_pulse_dict_b1["total_active_duration"] = STIM_MAX_PULSE_DURATION_MICROSECONDS + 1
    # use same second pulse dict for both protocols
    test_pulse_dict_2 = copy.deepcopy(GENERIC_PULSE_INFO_2)
    test_pulse_dict_2["total_active_duration"] = STIM_MAX_PULSE_DURATION_MICROSECONDS

    test_pulse_list_a = [test_pulse_dict_a1, test_pulse_dict_2]
    test_pulse_list_b = [test_pulse_dict_b1, test_pulse_dict_2]
    # set protocols and first pulse
    set_protocol_command = {
        "communication_type": "stimulation",
        "command": "set_protocol",
        "protocols": [
            {
                "stimulation_type": "V",
                "well_number": GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx),
                "total_protocol_duration": STIM_MAX_PULSE_DURATION_MICROSECONDS * 10,
                "pulses": test_pulse_list_a if well_idx in wells_to_update else test_pulse_list_b,
            }
            for well_idx in range(test_num_wells)
        ],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocol_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator, num_iterations=test_num_wells)
    invoke_process_run_and_check_errors(mc_process, num_iterations=test_num_wells)
    # start stimulation
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "stimulation",
            "command": "set_stim_status",
            "status": True,
        },
        from_main_queue,
    )
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    # remove messages to main to make testing log message easier
    drain_queue(to_main_queue)

    # update return value to simulate the duration of the first pulse being reached
    for update_num in range(2):
        mocked_get_secs.return_value = STIM_MAX_PULSE_DURATION_MICROSECONDS
        # run mc_process to send all the necessary commands (1 to stop stim for the two necessary modules, 2 to update each of their pulses, 1 to restart stim on those two modules)
        invoke_process_run_and_check_errors(mc_process)
        # update return value so no more pulses are updated
        mocked_get_secs.return_value = 0
        # process commands + command responses
        invoke_process_run_and_check_errors(simulator, num_iterations=4)
        invoke_process_run_and_check_errors(mc_process, num_iterations=4)

        # check that pulses are correctly updated on simulator
        current_pulses = simulator.get_stim_config()
        for well_idx in test_wells:
            module_id = SERIAL_COMM_WELL_IDX_TO_MODULE_ID[well_idx]
            if update_num == 0:
                expected_pulse = GENERIC_PULSE_INFO_2 if well_idx in wells_to_update else GENERIC_PULSE_INFO_1
            else:
                expected_pulse = GENERIC_PULSE_INFO_1
            assert current_pulses[module_id]["pulse"] == expected_pulse, (update_num, well_idx)
            assert current_pulses[module_id]["stimulation_type"] == "V", (update_num, well_idx)
        # check that correct log message was send to main after update
        confirm_queue_is_eventually_of_size(to_main_queue, 1)
        log_msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert log_msg_to_main == {
            "command": "restart_stim_for_pulse_update",
            "communication_type": "stimulation",
            "wells_updated": wells_to_update,
        }, update_num
