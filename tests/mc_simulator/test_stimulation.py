# -*- coding: utf-8 -*-
from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon


__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_MantarrayMcSimulator__processes_set_stimulation_protocol_command():
    pass
