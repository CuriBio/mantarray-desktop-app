# -*- coding: utf-8 -*-
from ..fixtures import fixture_patch_print
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon

__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_four_board_mc_comm_process,
    fixture_patch_print,
    fixture_four_board_mc_comm_process_no_handshake,
]
