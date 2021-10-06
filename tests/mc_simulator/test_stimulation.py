# -*- coding: utf-8 -*-
from random import choice
from random import randint

from mantarray_desktop_app import convert_module_id_to_well_name
from mantarray_desktop_app import convert_stim_dict_to_bytes
from mantarray_desktop_app import convert_to_timestamp_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import SERIAL_COMM_COMMAND_FAILURE_BYTE
from mantarray_desktop_app import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_COMMAND_SUCCESS_BYTE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_START_STIM_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STOP_STIM_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app import STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
from mantarray_desktop_app import StimStatuses
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_null_subprotocol
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import assert_serial_packet_is_expected
from ..helpers import get_full_packet_size_from_packet_body_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
]


def set_stim_info_and_start_stimulating(simulator_fixture, stim_info):
    simulator = simulator_fixture["simulator"]
    testing_queue = simulator_fixture["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_stim_info", "stim_info": stim_info}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_stim_status", "status": True}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)


def create_converted_stim_info(stim_info):
    protocol_ids = set()
    for protocol in stim_info["protocols"]:
        if protocol["protocol_id"] not in protocol_ids:
            protocol_ids.add(protocol["protocol_id"])
        del protocol["protocol_id"]

    protocol_ids = list(protocol_ids)
    converted_protocol_assignments = {
        well_name: None if protocol_id is None else protocol_ids.index(protocol_id)
        for well_name, protocol_id in stim_info["protocol_assignments"].items()
    }
    stim_info["protocol_assignments"] = converted_protocol_assignments
    return stim_info


def test_MantarrayMcSimulator__processes_set_stimulation_protocol_command__when_stimulation_not_running_on_any_wells(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    test_protocol_ids = ("A", "B", "E", None)
    stim_info_dict = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "stimulation_type": choice(["C", "V"]),
                "run_until_stopped": choice([True, False]),
                "subprotocols": [
                    choice([get_random_subprotocol(), get_null_subprotocol(600)])
                    for _ in range(randint(1, 3))
                ],
            }
            for protocol_id in test_protocol_ids[:-1]
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(test_protocol_ids)
            for well_idx in range(24)
        },
    }

    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    set_protocols_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        convert_stim_dict_to_bytes(stim_info_dict),
    )
    simulator.write(set_protocols_command)

    invoke_process_run_and_check_errors(simulator)
    # assert that stim info was stored
    actual = simulator.get_stim_info()
    for protocol_idx in range(len(test_protocol_ids) - 1):
        del stim_info_dict["protocols"][protocol_idx][
            "protocol_id"
        ]  # the actual protocol ID letter is not included
        assert actual["protocols"][protocol_idx] == stim_info_dict["protocols"][protocol_idx], protocol_idx
    assert actual["protocol_assignments"] == {  # indices of the protocol are used instead
        well_name: (None if protocol_id is None else test_protocol_ids.index(protocol_id))
        for well_name, protocol_id in stim_info_dict["protocol_assignments"].items()
    }
    # assert command response is correct
    stim_command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        stim_command_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
        + bytes([SERIAL_COMM_COMMAND_SUCCESS_BYTE]),
    )


def test_MantarrayMcSimulator__processes_set_stimulation_protocol_command__when_too_many_protocols_are_given(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    test_protocol_ids = [chr(ord("A") + i) for i in range(25)]
    stim_info_dict = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "stimulation_type": choice(["C", "V"]),
                "run_until_stopped": choice([True, False]),
                "subprotocols": [get_random_subprotocol()],
            }
            for protocol_id in test_protocol_ids
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(test_protocol_ids)
            for well_idx in range(24)
        },
    }

    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    set_protocols_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        convert_stim_dict_to_bytes(stim_info_dict),
    )
    simulator.write(set_protocols_command)

    invoke_process_run_and_check_errors(simulator)
    # assert stim info was not updated
    assert simulator.get_stim_info() == {}
    # assert command response is correct
    stim_command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        stim_command_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
        + bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


@pytest.mark.parametrize(
    "test_num_module_assignments,test_description",
    [
        (23, "returns command failure response when 23 module assignments given"),
        (25, "returns command failure response when 25 module assignments given"),
    ],
)
def test_MantarrayMcSimulator__processes_set_stimulation_protocol_command__when_an_incorrect_amount_of_module_assignments_are_given(
    mantarray_mc_simulator_no_beacon, test_num_module_assignments, test_description
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    stim_info_dict = {
        "protocols": [
            {
                "protocol_id": "V",
                "stimulation_type": choice(["C", "V"]),
                "run_until_stopped": choice([True, False]),
                "subprotocols": [get_random_subprotocol()],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "V" for well_idx in range(24)
        },
    }
    stim_info_bytes = convert_stim_dict_to_bytes(stim_info_dict)
    # add or remove an assignment
    if test_num_module_assignments > 24:
        stim_info_bytes += bytes([0])
    else:
        stim_info_bytes = stim_info_bytes[:-1]

    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    set_protocols_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        stim_info_bytes,
    )
    simulator.write(set_protocols_command)

    invoke_process_run_and_check_errors(simulator)
    # assert stim info was not updated
    assert simulator.get_stim_info() == {}
    # assert command response is correct
    stim_command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        stim_command_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
        + bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


def test_MantarrayMcSimulator__processes_set_stimulation_protocol_command__when_too_many_subprotocols_given_in_a_single_protocol(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    stim_info_dict = {
        "protocols": [
            {
                "protocol_id": "O",
                "stimulation_type": choice(["C", "V"]),
                "run_until_stopped": choice([True, False]),
                "subprotocols": [
                    choice([get_random_subprotocol(), get_null_subprotocol(130)])
                    for _ in range(STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL + 1)
                ],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "O" for well_idx in range(24)
        },
    }

    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    set_protocols_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        convert_stim_dict_to_bytes(stim_info_dict),
    )
    simulator.write(set_protocols_command)

    invoke_process_run_and_check_errors(simulator)
    # assert stim info was not updated
    assert simulator.get_stim_info() == {}
    # assert command response is correct
    stim_command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        stim_command_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
        + bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


def test_MantarrayMcSimulator__processes_start_stimulation_command__before_protocols_have_been_set(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    expected_stim_running_statuses = {
        convert_module_id_to_well_name(module_id): False for module_id in range(1, 25)
    }

    # send start stim command
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    start_stimulation_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_START_STIM_PACKET_TYPE,
    )
    simulator.write(start_stimulation_command)

    invoke_process_run_and_check_errors(simulator)
    # assert that stimulation was not started on any wells
    assert simulator.get_stim_running_statuses() == expected_stim_running_statuses
    # assert command response is correct
    expected_size = get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    stim_command_response = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_command_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp)
        + bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


# TODO Tanner (10/5/21): consider setting one protocol to run longer than all others and try sending this command when only that one is left running and assert that the stim statuses didn't change
def test_MantarrayMcSimulator__processes_start_stimulation_command__after_protocols_have_been_set(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")
    # mock so no protocol status packets are sent
    mocker.patch.object(mc_simulator, "_get_us_since_subprotocol_start", autospec=True, return_value=0)

    # set single arbitrary protocol applied to wells randomly
    stim_info = simulator.get_stim_info()
    stim_info["protocols"] = [
        {
            "protocol_id": "A",
            "stimulation_type": "C",
            "run_until_stopped": True,
            "subprotocols": [get_random_subprotocol()],
        }
    ]
    stim_info["protocol_assignments"] = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", None])
        if well_idx
        else "A"
        for well_idx in range(24)
    }
    expected_stim_running_statuses = {
        well_name: bool(protocol_id) for well_name, protocol_id in stim_info["protocol_assignments"].items()
    }

    for response_byte_value in (
        SERIAL_COMM_COMMAND_SUCCESS_BYTE,
        SERIAL_COMM_COMMAND_FAILURE_BYTE,
    ):
        # send start stim command
        expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
        start_stimulation_command = create_data_packet(
            expected_pc_timestamp,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_START_STIM_PACKET_TYPE,
        )
        simulator.write(start_stimulation_command)

        invoke_process_run_and_check_errors(simulator)
        # assert that stimulation was started on wells that were assigned a protocol
        assert simulator.get_stim_running_statuses() == expected_stim_running_statuses
        # assert command response is correct
        additional_bytes = convert_to_timestamp_bytes(expected_pc_timestamp) + bytes([response_byte_value])
        if not response_byte_value:
            additional_bytes += spied_global_timer.spy_return.to_bytes(8, byteorder="little")
        expected_size = get_full_packet_size_from_packet_body_size(len(additional_bytes))
        stim_command_response = simulator.read(size=expected_size)
        assert_serial_packet_is_expected(
            stim_command_response,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
            additional_bytes=additional_bytes,
        )


def test_MantarrayMcSimulator__processes_stop_stimulation_command(mantarray_mc_simulator_no_beacon):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # set single arbitrary protocol applied to wells randomly
    stim_info = simulator.get_stim_info()
    stim_info["protocols"] = [
        {
            "protocol_id": "B",
            "stimulation_type": "V",
            "run_until_stopped": True,
            "subprotocols": [get_random_subprotocol()],
        }
    ]
    stim_info["protocol_assignments"] = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["B", None])
        if well_idx
        else "B"
        for well_idx in range(24)
    }
    initial_stim_running_statuses = {
        well_name: bool(protocol_id) for well_name, protocol_id in stim_info["protocol_assignments"].items()
    }
    simulator.get_stim_running_statuses().update(initial_stim_running_statuses)

    for response_byte_value in (
        SERIAL_COMM_COMMAND_SUCCESS_BYTE,
        SERIAL_COMM_COMMAND_FAILURE_BYTE,
    ):
        # send start stim command
        expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
        stop_stimulation_command = create_data_packet(
            expected_pc_timestamp,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_STOP_STIM_PACKET_TYPE,
        )
        simulator.write(stop_stimulation_command)

        invoke_process_run_and_check_errors(simulator)
        # assert that stimulation was started on wells that were assigned a protocol
        assert simulator.get_stim_running_statuses() == {
            convert_module_id_to_well_name(module_id): False for module_id in range(1, 25)
        }
        # assert command response is correct
        additional_bytes = convert_to_timestamp_bytes(expected_pc_timestamp) + bytes([response_byte_value])
        expected_size = get_full_packet_size_from_packet_body_size(len(additional_bytes))
        stim_command_response = simulator.read(size=expected_size)
        assert_serial_packet_is_expected(
            stim_command_response,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
            additional_bytes=additional_bytes,
        )


def test_MantarrayMcSimulator__sends_protocol_status_packet_when_a_new_subprotocol_starts_on_a_single_well(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    test_duration_us = 5000
    test_well_idx = randint(0, 24)

    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": "A",
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": [
                        get_random_subprotocol(total_active_duration=test_duration_us),
                        get_random_subprotocol(),
                    ],
                }
            ],
            "protocol_assignments": {
                GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): "A"
                if well_idx == test_well_idx
                else None
                for well_idx in range(24)
            },
        }
    )
    set_stim_info_and_start_stimulating(mantarray_mc_simulator_no_beacon, test_stim_info)

    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[test_duration_us - 1, test_duration_us],
    )

    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    additional_bytes = (
        bytes([1])  # number of status updates in this packet
        + bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_idx]])
        + (spied_global_timer.spy_return + test_duration_us).to_bytes(8, byteorder="little")
        + bytes([1])  # subprotocol idx
        + bytes([StimStatuses.ACTIVE])
    )
    expected_size = get_full_packet_size_from_packet_body_size(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STIM_STATUS_PACKET_TYPE,
        additional_bytes=additional_bytes,
    )


def test_MantarrayMcSimulator__sends_protocol_status_packets_when_multiple_wells_running_the_same_protocol_reach_a_new_subprotocol():
    pass


def test_MantarrayMcSimulator__sends_mutiple_protocol_status_packets_if_multiple_subprotocol_updates_have_occured_on_a_single_well():
    pass


def test_MantarrayMcSimulator__sends_protocol_status_with_null_status_correctly():
    pass


def test_MantarrayMcSimulator__sends_protocol_status_with_restarting_status_correctly():
    pass


def test_MantarrayMcSimulator__sends_protocol_status_with_finished_status_correctly():
    pass
