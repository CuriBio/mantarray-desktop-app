# -*- coding: utf-8 -*-
from random import choice
from random import randint

from mantarray_desktop_app import convert_stim_dict_to_bytes
from mantarray_desktop_app import convert_to_timestamp_bytes
from mantarray_desktop_app import convert_well_name_to_module_id
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import SERIAL_COMM_COMMAND_FAILURE_BYTE
from mantarray_desktop_app import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_COMMAND_SUCCESS_BYTE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_START_STIM_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_null_subprotocol
from ..fixtures_mc_simulator import get_random_pulse_subprotocol
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import assert_serial_packet_is_expected
from ..helpers import get_full_packet_size_from_packet_body_size


__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator_no_beacon,
]


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
                    choice([get_random_pulse_subprotocol(), get_null_subprotocol(600)])
                    for _ in range(randint(1, 3))
                ],
            }
            for protocol_id in test_protocol_ids[:-1]
        ],
        "well_name_to_protocol_id": {
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
        assert actual["protocols"][protocol_idx] == stim_info_dict["protocols"][protocol_idx], protocol_idx
    assert actual["well_name_to_protocol_id"] == stim_info_dict["well_name_to_protocol_id"]
    # assert command response is correct
    stim_command_response = simulator.read(
        size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + 1)
    )
    assert_serial_packet_is_expected(
        stim_command_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp) + bytes([0]),
    )


def test_MantarrayMcSimulator__processes_start_stimulation_command__before_protocols_have_been_set(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    expected_stim_running_statuses = {module_id: False for module_id in range(1, 25)}

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


# TODO consider setting one protocol to run longer than all others and try sending this command when only that one is left running and assert that the stim statuses didn't change
def test_MantarrayMcSimulator__processes_start_stimulation_command__after_protocols_have_been_set(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    # set single arbitrary protocol applied to wells randomly
    stim_info = simulator.get_stim_info()
    stim_info["protocols"] = [
        {
            "protocol_id": "A",
            "stimulation_type": "C",
            "run_until_stopped": True,
            "subprotocols": [get_random_pulse_subprotocol()],
        }
    ]
    stim_info["well_name_to_protocol_id"] = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", None])
        for well_idx in range(24)
    }
    expected_stim_running_statuses = {
        convert_well_name_to_module_id(well_name): bool(protocol_id)
        for well_name, protocol_id in stim_info["well_name_to_protocol_id"].items()
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


# SERIAL_COMM_STOP_STIM_PACKET_TYPE
