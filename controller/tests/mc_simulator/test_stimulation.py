# -*- coding: utf-8 -*-
import copy
from random import choice
from random import randint
import struct

from mantarray_desktop_app import convert_stim_dict_to_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import SERIAL_COMM_COMMAND_FAILURE_BYTE
from mantarray_desktop_app import SERIAL_COMM_COMMAND_SUCCESS_BYTE
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_START_STIM_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STOP_STIM_PACKET_TYPE
from mantarray_desktop_app import STIM_COMPLETE_SUBPROTOCOL_IDX
from mantarray_desktop_app import StimProtocolStatuses
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import MICROS_PER_MILLI
from mantarray_desktop_app.constants import SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE
from mantarray_desktop_app.simulators import mc_simulator
from mantarray_desktop_app.utils.serial_comm import convert_adc_readings_to_circuit_status
from mantarray_desktop_app.utils.serial_comm import is_null_subprotocol
from mantarray_desktop_app.utils.stimulation import get_subprotocol_dur_us
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures_mc_simulator import create_converted_stim_info
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_random_stim_delay
from ..fixtures_mc_simulator import get_random_stim_pulse
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_mc_simulator import random_stim_type
from ..fixtures_mc_simulator import set_stim_info_and_start_stimulating
from ..helpers import assert_serial_packet_is_expected
from ..helpers import get_full_packet_size_from_payload_len
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..helpers import random_bool


__fixtures__ = [fixture_mantarray_mc_simulator, fixture_mantarray_mc_simulator_no_beacon]


def test_MantarrayMcSimulator__processes_start_stimulator_checks_command(mantarray_mc_simulator_no_beacon):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    num_wells = 24

    test_module_ids = [i for i in range(num_wells) if random_bool()]
    if not test_module_ids:
        # guard against unlikely case where no module IDs were selected
        test_module_ids = [1]

    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    start_checks_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE,
        struct.pack("<24?", *[module_id in test_module_ids for module_id in range(num_wells)]),
    )
    simulator.write(start_checks_command)

    invoke_process_run_and_check_errors(simulator)

    test_adc_reading = MantarrayMcSimulator.default_adc_reading

    # make sure results immediately sent back
    payload_bytes = (
        test_adc_reading.to_bytes(2, byteorder="little") * 2
        + bytes([convert_adc_readings_to_circuit_status(test_adc_reading, test_adc_reading)])
    ) * num_wells
    stim_check_results = simulator.read(size=get_full_packet_size_from_payload_len(len(payload_bytes)))
    assert_serial_packet_is_expected(
        stim_check_results, SERIAL_COMM_STIM_IMPEDANCE_CHECK_PACKET_TYPE, additional_bytes=payload_bytes
    )


def test_MantarrayMcSimulator__processes_set_stimulation_protocol_command__when_stimulation_not_running_on_any_wells(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_protocol_ids = ("A", "B", "E", None)
    stim_info_dict = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "stimulation_type": random_stim_type(),
                "run_until_stopped": choice([True, False]),
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_iterations": 1,
                        "subprotocols": [
                            choice([get_random_stim_pulse(num_cycles=10), get_random_stim_delay()])
                            for _ in range(randint(1, 3))
                        ],
                    }
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
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        convert_stim_dict_to_bytes(stim_info_dict),
    )
    simulator.write(set_protocols_command)

    invoke_process_run_and_check_errors(simulator)
    # assert that stim info was stored
    actual = simulator._stim_info
    # don't loop over last test protocol ID because it's just a placeholder for no protocol
    for protocol_idx in range(len(test_protocol_ids) - 1):
        # the actual protocol ID letter is not included
        del stim_info_dict["protocols"][protocol_idx]["protocol_id"]
        assert actual["protocols"][protocol_idx] == stim_info_dict["protocols"][protocol_idx], protocol_idx

    assert actual["protocol_assignments"] == {  # indices of the protocol are used instead
        well_name: (None if not protocol_id else test_protocol_ids.index(protocol_id))
        for well_name, protocol_id in stim_info_dict["protocol_assignments"].items()
    }
    # assert command response is correct
    stim_command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
    assert_serial_packet_is_expected(
        stim_command_response,
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        additional_bytes=bytes([SERIAL_COMM_COMMAND_SUCCESS_BYTE]),
    )


def test_MantarrayMcSimulator__processes_set_stimulation_protocol_command__when_too_many_protocols_are_given(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_protocol_ids = [chr(ord("A") + i) for i in range(25)]
    stim_info_dict = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "stimulation_type": random_stim_type(),
                "run_until_stopped": choice([True, False]),
                "subprotocols": [get_random_stim_pulse(num_cycles=10)],
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
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        convert_stim_dict_to_bytes(stim_info_dict),
    )
    simulator.write(set_protocols_command)

    invoke_process_run_and_check_errors(simulator)
    # assert stim info was not updated
    assert simulator._stim_info == {}
    # assert command response is correct
    stim_command_response = simulator.read(size=get_full_packet_size_from_payload_len(1))
    assert_serial_packet_is_expected(
        stim_command_response,
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        additional_bytes=bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


def test_MantarrayMcSimulator__processes_start_stimulation_command__before_protocols_have_been_set(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # send start stim command
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    start_stimulation_command = create_data_packet(expected_pc_timestamp, SERIAL_COMM_START_STIM_PACKET_TYPE)
    simulator.write(start_stimulation_command)

    invoke_process_run_and_check_errors(simulator)
    # assert that stimulation was not started on any wells
    assert not any(simulator._stim_running_statuses)
    # assert command response is correct
    expected_size = get_full_packet_size_from_payload_len(1)
    stim_command_response = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_command_response,
        SERIAL_COMM_START_STIM_PACKET_TYPE,
        additional_bytes=bytes([SERIAL_COMM_COMMAND_FAILURE_BYTE]),
    )


# TODO Tanner (10/5/21): consider setting one protocol to run longer than all others and try sending this command when only that one is left running and assert that the stim statuses didn't change
def test_MantarrayMcSimulator__processes_start_stimulation_command__after_protocols_have_been_set(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # mock so no protocol status packets are sent
    mocker.patch.object(simulator, "_handle_stimulation_packets", autospec=True, return_value=0)

    # set single arbitrary protocol applied to wells randomly
    stim_info = simulator._stim_info
    stim_info["protocols"] = [
        {
            "protocol_id": "A",
            "stimulation_type": "C",
            "run_until_stopped": True,
            "subprotocols": [get_random_stim_pulse(num_cycles=10)],
        }
    ]
    stim_info["protocol_assignments"] = {
        # make sure that this protocol is assigned to at least 1 well
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
            "A" if well_idx == 0 else choice(["A", None])
        )
        for well_idx in range(24)
    }
    expected_stim_running_statuses = [True] * len(stim_info["protocols"])

    for response_byte_value in (SERIAL_COMM_COMMAND_SUCCESS_BYTE, SERIAL_COMM_COMMAND_FAILURE_BYTE):
        # send start stim command
        expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
        start_stimulation_command = create_data_packet(
            expected_pc_timestamp, SERIAL_COMM_START_STIM_PACKET_TYPE
        )
        simulator.write(start_stimulation_command)

        invoke_process_run_and_check_errors(simulator)
        # assert that stimulation was started on wells that were assigned a protocol
        assert simulator._stim_running_statuses == expected_stim_running_statuses
        # assert command response is correct
        additional_bytes = bytes([response_byte_value])
        expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
        stim_command_response = simulator.read(size=expected_size)
        assert_serial_packet_is_expected(
            stim_command_response, SERIAL_COMM_START_STIM_PACKET_TYPE, additional_bytes=additional_bytes
        )


def test_MantarrayMcSimulator__processes_stop_stimulation_command(mantarray_mc_simulator_no_beacon, mocker):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    # set single arbitrary protocol applied to wells randomly
    stim_info = simulator._stim_info
    stim_info["protocols"] = [
        {
            "protocol_id": "B",
            "stimulation_type": "V",
            "run_until_stopped": True,
            "subprotocols": [get_random_stim_pulse(num_cycles=10)],
        }
    ]
    stim_info["protocol_assignments"] = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
            "B" if well_idx == 0 else choice(["B", None])
        )
        for well_idx in range(24)
    }
    simulator._stim_running_statuses = [True]

    for response_byte_value in (SERIAL_COMM_COMMAND_SUCCESS_BYTE, SERIAL_COMM_COMMAND_FAILURE_BYTE):
        # send stop stim command
        expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
        stop_stimulation_command = create_data_packet(
            expected_pc_timestamp, SERIAL_COMM_STOP_STIM_PACKET_TYPE
        )
        simulator.write(stop_stimulation_command)
        invoke_process_run_and_check_errors(simulator)

        # make sure finished status updates are sent if command succeeded
        if response_byte_value == SERIAL_COMM_COMMAND_SUCCESS_BYTE:
            status_update_bytes = (
                bytes([1])  # num status updates
                + bytes([0])  # protocol idx
                + (spied_global_timer.spy_return).to_bytes(8, byteorder="little")
                + bytes([StimProtocolStatuses.FINISHED])
                + bytes([STIM_COMPLETE_SUBPROTOCOL_IDX])
            )
            expected_size = get_full_packet_size_from_payload_len(len(status_update_bytes))
            stim_command_response = simulator.read(size=expected_size)
            assert_serial_packet_is_expected(
                stim_command_response,
                SERIAL_COMM_STIM_STATUS_PACKET_TYPE,
                additional_bytes=status_update_bytes,
            )
        # assert that stimulation was stopped on all wells
        assert simulator._stim_running_statuses == [False]
        # assert command response is correct
        additional_bytes = bytes([response_byte_value])
        expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
        stim_command_response = simulator.read(size=expected_size)
        assert_serial_packet_is_expected(
            stim_command_response, SERIAL_COMM_STOP_STIM_PACKET_TYPE, additional_bytes=additional_bytes
        )


def test_MantarrayMcSimulator__sends_protocol_status_packet_for_initial_subprotocol_of_each_protocol_when_stim_starts(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[0, 1, 0],
    )

    test_protocol_ids = ("A", "B", "C")
    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": protocol_id,
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": [
                        get_random_stim_pulse(num_cycles=1),
                        get_random_stim_pulse(num_cycles=2),
                    ],
                }
                for protocol_id in test_protocol_ids
            ],
            "protocol_assignments": {
                GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(
                    [*test_protocol_ids, None]
                )
                for well_idx in range(24)
            },
        }
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_stim_info", "stim_info": test_stim_info}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_stim_status", "status": True}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    num_status_updates = len(test_protocol_ids)
    additional_bytes = bytes([num_status_updates])
    for protocol_idx in range(num_status_updates):
        additional_bytes += (
            bytes([protocol_idx])
            + (spied_global_timer.spy_return).to_bytes(8, byteorder="little")
            + bytes([StimProtocolStatuses.ACTIVE, 0])  # subprotocol idx
        )
    expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet, SERIAL_COMM_STIM_STATUS_PACKET_TYPE, additional_bytes=additional_bytes
    )


def test_MantarrayMcSimulator__sends_protocol_status_packet_when_a_new_subprotocol_starts_for_a_single_protocol(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    test_protocol_ids = ("A", "B", "C")
    test_subprotocols = [
        [
            get_random_stim_pulse(total_subprotocol_dur_us=int(1e6)),
            get_random_stim_pulse(total_subprotocol_dur_us=int(2e6)),
        ],
        [get_random_stim_pulse(total_subprotocol_dur_us=int(2e6))] * 2,
        [get_random_stim_pulse(total_subprotocol_dur_us=int(2e6))] * 2,
    ]

    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": protocol_id,
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": [
                        {
                            "type": "loop",
                            "num_iterations": 1,
                            "subprotocols": subprotocols,
                        }
                    ],
                }
                for protocol_id, subprotocols in zip(test_protocol_ids, test_subprotocols)
            ],
            "protocol_assignments": {
                GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(
                    [*test_protocol_ids, None]
                )
                for well_idx in range(24)
            },
        }
    )
    set_stim_info_and_start_stimulating(mantarray_mc_simulator_no_beacon, test_stim_info)

    test_duration_us = get_subprotocol_dur_us(test_subprotocols[0][0])
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[test_duration_us - 1, 0, 0, test_duration_us, 0, 0],
    )

    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    additional_bytes = (
        bytes([1, 0])  # number of status updates in this packet, protocol_idx
        + (spied_global_timer.spy_return + test_duration_us).to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.ACTIVE, 1])  # subprotocol idx
    )
    expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet, SERIAL_COMM_STIM_STATUS_PACKET_TYPE, additional_bytes=additional_bytes
    )


def test_MantarrayMcSimulator__sends_multiple_protocol_status_packets_if_multiple_subprotocol_updates_have_occured_for_a_single_protocol(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    test_first_subprotocol = get_random_stim_pulse(num_cycles=1)
    test_second_subprotocol = get_random_stim_pulse(num_cycles=2)

    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": "A",
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": [
                        {
                            "type": "loop",
                            "num_iterations": 1,
                            "subprotocols": [
                                test_first_subprotocol,
                                test_second_subprotocol,
                                get_random_stim_pulse(num_cycles=3),
                            ],
                        }
                    ],
                }
            ],
            "protocol_assignments": {
                GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", None])
                for well_idx in range(24)
            },
        }
    )
    set_stim_info_and_start_stimulating(mantarray_mc_simulator_no_beacon, test_stim_info)

    test_duration_us_1 = get_subprotocol_dur_us(test_first_subprotocol)
    test_duration_us_2 = get_subprotocol_dur_us(test_second_subprotocol)
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[test_duration_us_1 - 1, test_duration_us_1 + test_duration_us_2, 0],
    )

    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    status_bytes_1 = (
        (spied_global_timer.spy_return + test_duration_us_1).to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.ACTIVE])
        + bytes([1])  # subprotocol idx
    )
    status_bytes_2 = (
        (spied_global_timer.spy_return + test_duration_us_1 + test_duration_us_2).to_bytes(
            8, byteorder="little"
        )
        + bytes([StimProtocolStatuses.ACTIVE])
        + bytes([2])  # subprotocol idx
    )
    additional_bytes = (
        bytes([2])  # number of status updates in this packet
        + bytes([0])  # protocol idx
        + status_bytes_1
        + bytes([0])  # protocol idx
        + status_bytes_2
    )
    expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet, SERIAL_COMM_STIM_STATUS_PACKET_TYPE, additional_bytes=additional_bytes
    )


def test_MantarrayMcSimulator__sends_multiple_protocol_status_packets_if_subprotocol_updates_occur_for_two_different_protocols(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    test_first_subprotocol = get_random_stim_pulse(num_cycles=1)
    test_second_subprotocol = get_random_stim_pulse(num_cycles=2)

    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": "A",
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": [test_first_subprotocol, get_random_stim_pulse(num_cycles=3)],
                },
                {
                    "protocol_id": "B",
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": [test_second_subprotocol, get_random_stim_pulse(num_cycles=3)],
                },
            ],
            "protocol_assignments": {
                GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", "B", None])
                for well_idx in range(24)
            },
        }
    )
    set_stim_info_and_start_stimulating(mantarray_mc_simulator_no_beacon, test_stim_info)

    test_duration_us_1 = get_subprotocol_dur_us(test_first_subprotocol)
    test_duration_us_2 = get_subprotocol_dur_us(test_second_subprotocol)
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[
            test_duration_us_1 - 1,
            test_duration_us_2 - 1,
            test_duration_us_1,
            test_duration_us_2,
            0,
        ],
    )

    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    status_bytes_1 = (
        (spied_global_timer.spy_return + test_duration_us_1).to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.ACTIVE])
        + bytes([1])  # subprotocol idx
    )
    status_bytes_2 = (
        (spied_global_timer.spy_return + test_duration_us_2).to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.ACTIVE])
        + bytes([1])  # subprotocol idx
    )
    additional_bytes = (
        bytes([2])  # number of status updates in this packet
        + bytes([0])  # protocol idx
        + status_bytes_1
        + bytes([1])  # protocol idx
        + status_bytes_2
    )
    expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet, SERIAL_COMM_STIM_STATUS_PACKET_TYPE, additional_bytes=additional_bytes
    )


def test_MantarrayMcSimulator__sends_protocol_status_with_null_status_correctly(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    test_first_subprotocol = get_random_stim_pulse(num_cycles=1)

    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": "A",
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": [test_first_subprotocol, get_random_stim_delay()],
                }
            ],
            "protocol_assignments": {
                GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", None])
                for well_idx in range(24)
            },
        }
    )
    set_stim_info_and_start_stimulating(mantarray_mc_simulator_no_beacon, test_stim_info)

    test_duration_us = get_subprotocol_dur_us(test_first_subprotocol)
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[test_duration_us - 1, test_duration_us, 0],
    )

    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    additional_bytes = (
        bytes([1])  # number of status updates in this packet
        + bytes([0])  # protocol idx
        + (spied_global_timer.spy_return + test_duration_us).to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.NULL])
        + bytes([1])  # subprotocol idx
    )
    expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet, SERIAL_COMM_STIM_STATUS_PACKET_TYPE, additional_bytes=additional_bytes
    )


# TODO
def test_MantarrayMcSimulator__sends_protocol_status_correctly_after_protocol_restarts(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    test_first_subprotocol = get_random_stim_pulse(num_cycles=10)

    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": "A",
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": [test_first_subprotocol],
                }
            ],
            "protocol_assignments": {
                GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", None])
                for well_idx in range(24)
            },
        }
    )
    set_stim_info_and_start_stimulating(mantarray_mc_simulator_no_beacon, test_stim_info)

    test_duration_us = get_subprotocol_dur_us(test_first_subprotocol)
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[test_duration_us - 1, test_duration_us, 0],
    )

    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    additional_bytes = (
        bytes([1])  # number of status updates in this packet
        + bytes([0])  # protocol idx
        + (spied_global_timer.spy_return + test_duration_us).to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.ACTIVE])
        + bytes([0])  # subprotocol idx
    )
    expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet, SERIAL_COMM_STIM_STATUS_PACKET_TYPE, additional_bytes=additional_bytes
    )


# TODO
def test_MantarrayMcSimulator__sends_protocol_status_with_finished_status_correctly__and_stops_stim_for_the_finished_protocol(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    test_first_subprotocol = get_random_stim_pulse(num_cycles=10)
    test_second_subprotocol = copy.deepcopy(test_first_subprotocol)
    test_second_subprotocol["num_cycles"] *= 2

    test_well_idx_to_stop = randint(0, 11)
    test_well_name_to_stop = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(test_well_idx_to_stop)
    test_well_idx_to_continue = randint(12, 23)
    test_well_name_to_continue = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(
        test_well_idx_to_continue
    )

    test_protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): None for well_idx in range(24)
    }
    test_protocol_assignments[test_well_name_to_stop] = "A"
    test_protocol_assignments[test_well_name_to_continue] = "B"

    mocked_get_us = mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        return_value=0,
    )

    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": "A",
                    "stimulation_type": "C",
                    "run_until_stopped": False,
                    "subprotocols": [test_first_subprotocol],
                },
                {
                    "protocol_id": "B",
                    "stimulation_type": "C",
                    "run_until_stopped": False,
                    "subprotocols": [test_second_subprotocol],
                },
            ],
            "protocol_assignments": test_protocol_assignments,
        }
    )
    set_stim_info_and_start_stimulating(mantarray_mc_simulator_no_beacon, test_stim_info)

    test_duration_us = get_subprotocol_dur_us(test_first_subprotocol)
    mocked_get_us.side_effect = ([test_duration_us - 1] * 2) + ([test_duration_us] * 4)

    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    additional_bytes = (
        bytes([1])  # number of status updates in this packet
        + bytes([0])  # protocol idx
        + (spied_global_timer.spy_return + test_duration_us).to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.FINISHED])
        + bytes([STIM_COMPLETE_SUBPROTOCOL_IDX])
    )
    expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet, SERIAL_COMM_STIM_STATUS_PACKET_TYPE, additional_bytes=additional_bytes
    )

    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 0


# TODO
def test_MantarrayMcSimulator__sends_protocol_status_with_finished_status_correctly__when_receiving_command_to_stop_stimulation(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    test_subprotocol = get_random_stim_pulse(num_cycles=10)

    test_well_idx_to_stop_automatically = randint(0, 11)
    test_well_name_to_stop_automatically = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(
        test_well_idx_to_stop_automatically
    )
    test_well_idx_to_stop_manually = randint(12, 23)
    test_well_name_to_stop_manually = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(
        test_well_idx_to_stop_manually
    )

    test_protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): None for well_idx in range(24)
    }
    test_protocol_assignments[test_well_name_to_stop_automatically] = "A"
    test_protocol_assignments[test_well_name_to_stop_manually] = "B"

    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": "A",
                    "stimulation_type": "C",
                    "run_until_stopped": False,
                    "subprotocols": [test_subprotocol],
                },
                {
                    "protocol_id": "B",
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": [test_subprotocol],
                },
            ],
            "protocol_assignments": test_protocol_assignments,
        }
    )
    set_stim_info_and_start_stimulating(mantarray_mc_simulator_no_beacon, test_stim_info)

    test_duration_us = get_subprotocol_dur_us(test_subprotocol)
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=[test_duration_us] * 2,
    )

    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    additional_bytes = (
        bytes([2])  # number of status updates in this packet
        + bytes([0])  # protocol idx
        + (spied_global_timer.spy_return + test_duration_us).to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.FINISHED])
        + bytes([STIM_COMPLETE_SUBPROTOCOL_IDX])
        + bytes([1])  # protocol idx
        + (spied_global_timer.spy_return + test_duration_us).to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.ACTIVE])
        + bytes([0])  # subprotocol idx
    )
    expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet, SERIAL_COMM_STIM_STATUS_PACKET_TYPE, additional_bytes=additional_bytes
    )

    # send stop stim command
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    stop_stimulation_command = create_data_packet(expected_pc_timestamp, SERIAL_COMM_STOP_STIM_PACKET_TYPE)
    simulator.write(stop_stimulation_command)
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting > 0

    additional_bytes = (
        bytes([1])  # number of status updates in this packet
        + bytes([1])  # protocol idx
        + spied_global_timer.spy_return.to_bytes(8, byteorder="little")
        + bytes([StimProtocolStatuses.FINISHED])
        + bytes([STIM_COMPLETE_SUBPROTOCOL_IDX])
    )
    expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
    stim_status_packet = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        stim_status_packet, SERIAL_COMM_STIM_STATUS_PACKET_TYPE, additional_bytes=additional_bytes
    )


@pytest.mark.parametrize("is_loop_top_level", [True, False])
def test_MantarrayMcSimulator__handles_looping_correctly(
    is_loop_top_level, mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    test_well_index = randint(0, 23)
    test_protocol_assignments = {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
            "A" if well_idx == test_well_index else None
        )
        for well_idx in range(24)
    }

    test_num_iterations = [2, 3, 2]
    test_subprotocols = [
        get_random_subprotocol(total_subprotocol_dur_us=randint(1000, 10000) * MICROS_PER_MILLI)
        for _ in range(7)
    ]

    test_num_iterations_iter = iter(test_num_iterations)
    test_subprotocols_iter = iter(test_subprotocols)

    test_subprotocol_nodes = [
        next(test_subprotocols_iter),
        {
            "type": "loop",
            "num_iterations": next(test_num_iterations_iter),
            "subprotocols": [
                {
                    "type": "loop",
                    "num_iterations": next(test_num_iterations_iter),
                    "subprotocols": [next(test_subprotocols_iter)],
                },
                next(test_subprotocols_iter),
                {
                    "type": "loop",
                    "num_iterations": next(test_num_iterations_iter),
                    "subprotocols": [next(test_subprotocols_iter) for _ in range(3)],
                },
            ],
        },
        next(test_subprotocols_iter),
    ]

    if is_loop_top_level:
        test_subprotocols = test_subprotocols[1:-1]
        test_subprotocol_nodes = test_subprotocol_nodes[1:-1]

    test_stim_info = create_converted_stim_info(
        {
            "protocols": [
                {
                    "protocol_id": "A",
                    "stimulation_type": "C",
                    "run_until_stopped": True,
                    "subprotocols": test_subprotocol_nodes,
                },
            ],
            "protocol_assignments": test_protocol_assignments,
        }
    )
    set_stim_info_and_start_stimulating(mantarray_mc_simulator_no_beacon, test_stim_info)

    test_num_runs_through_protocol = randint(3, 5)

    expected_subprotocol_idx_order = (
        [0]
        + (([1] * test_num_iterations[1]) + [2] + ([3, 4, 5] * test_num_iterations[2]))
        * test_num_iterations[0]
        + [6]
    )
    if is_loop_top_level:
        expected_subprotocol_idx_order = [i - 1 for i in expected_subprotocol_idx_order[1:-1]]
    # run through entire protocol twice
    expected_subprotocol_idx_order *= test_num_runs_through_protocol

    expected_subprotocol_dur_order = [
        get_subprotocol_dur_us(test_subprotocols[i]) for i in expected_subprotocol_idx_order
    ]
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        side_effect=expected_subprotocol_dur_order,
    )

    # the first subprotocol status up packet is read inside set_stim_info_and_start_stimulating
    for update_num, subprotocol_idx in enumerate(expected_subprotocol_idx_order[1:], 1):
        error_msg = f"Update {update_num}, Subprotocol {subprotocol_idx}"

        invoke_process_run_and_check_errors(simulator)
        assert simulator.in_waiting > 0, error_msg

        stim_status = (
            StimProtocolStatuses.NULL
            if is_null_subprotocol(test_subprotocols[subprotocol_idx])
            else StimProtocolStatuses.ACTIVE
        )

        current_time_idx = spied_global_timer.spy_return + sum(expected_subprotocol_dur_order[:update_num])

        additional_bytes = (
            bytes([1])  # number of status updates in this packet
            + bytes([0])  # protocol idx
            + current_time_idx.to_bytes(8, byteorder="little")
            + bytes([stim_status])
            + bytes([subprotocol_idx])
        )

        expected_size = get_full_packet_size_from_payload_len(len(additional_bytes))
        stim_status_packet = simulator.read(size=expected_size)
        assert_serial_packet_is_expected(
            stim_status_packet,
            SERIAL_COMM_STIM_STATUS_PACKET_TYPE,
            additional_bytes=additional_bytes,
            err_msg=error_msg,
        )
