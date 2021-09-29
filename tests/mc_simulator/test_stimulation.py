# -*- coding: utf-8 -*-
from mantarray_desktop_app import convert_stim_dict_to_bytes

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import set_simulator_idle_ready


__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_MantarrayMcSimulator__processes_set_stimulation_protocol_command(mantarray_mc_simulator_no_beacon):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    set_protocol_command = convert_stim_dict_to_bytes
    simulator.write(set_protocol_command)
