# -*- coding: utf-8 -*-
from random import choice
from random import randint

from mantarray_desktop_app import convert_stim_dict_to_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import set_simulator_idle_ready


__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator_no_beacon,
]


def get_null_subprotocol(duration):
    return {
        "phase_one_duration": duration,
        "phase_one_charge": 0,
        "interpulse_interval": 0,
        "phase_two_duration": 0,
        # pylint: disable=duplicate-code
        "phase_two_charge": 0,
        "repeat_delay_interval": 0,
        "total_active_duration": duration,
    }


def get_random_pulse_subprotocol():
    return {
        "phase_one_duration": randint(1, 500),
        "phase_one_charge": randint(1, 1000),
        "interpulse_interval": randint(0, 500),
        "phase_two_duration": randint(1, 1000),
        "phase_two_charge": randint(1, 1000),
        "repeat_delay_interval": randint(0, 500),
        "total_active_duration": randint(1500, 3000),
    }


def test_MantarrayMcSimulator__processes_set_stimulation_protocol_command(mantarray_mc_simulator_no_beacon):
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

    set_protocol_command = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SET_STIM_PROTOCOL_PACKET_TYPE,
        convert_stim_dict_to_bytes(stim_info_dict),
    )
    simulator.write(set_protocol_command)

    invoke_process_run_and_check_errors(simulator)
    actual = simulator.get_stim_info()
    for protocol_idx in range(len(test_protocol_ids) - 1):
        assert actual["protocols"][protocol_idx] == stim_info_dict["protocols"][protocol_idx], protocol_idx
    assert actual["well_name_to_protocol_id"] == stim_info_dict["well_name_to_protocol_id"]


# SERIAL_COMM_START_STIM_PACKET_TYPE, SERIAL_COMM_STOP_STIM_PACKET_TYPE
