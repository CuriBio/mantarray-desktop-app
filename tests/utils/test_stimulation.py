# -*- coding: utf-8 -*-
import copy
import itertools
from random import choice
from random import randint

from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS
from mantarray_desktop_app.utils import stimulation
from mantarray_desktop_app.utils.stimulation import chunk_protocols_in_stim_info
from mantarray_desktop_app.utils.stimulation import chunk_subprotocol

from ..fixtures_mc_simulator import get_random_stim_delay
from ..fixtures_mc_simulator import get_random_stim_pulse
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_mc_simulator import random_stim_type
from ..helpers import random_bool


def test_chunk_subprotocol__returns_delay_unmodified():
    test_delay = get_random_stim_delay()
    assert chunk_subprotocol(test_delay) == [test_delay]


def test_chunk_subprotocol__returns_pulse_unmodified_if_no_chunking_needed():
    test_dur_us = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS
    test_subprotocol = get_random_stim_pulse(total_subprotocol_dur_us=test_dur_us)
    assert chunk_subprotocol(test_subprotocol) == [test_subprotocol]


def test_chunk_subprotocol__returns_single_loop_with_shortened_subprotocol__when_subprotocol_can_be_divided_into_an_integer_num_of_full_size_chunks():
    expected_num_loop_repeats = randint(2, 5)
    test_dur_us = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS * expected_num_loop_repeats

    # the original number of cycles must be a multiple of the expected number of loop repeats and a factor of
    # the total duration of the original subprotocol in order for there to be an integer number of cycles in
    # the chunked subprotocol
    def filt(n):
        return test_dur_us % n == 0 and n % expected_num_loop_repeats == 0

    test_original_num_cycles = choice([n for n in range(1, int(test_dur_us**0.5) + 1) if filt(n)])

    test_subprotocol = get_random_stim_pulse(
        total_subprotocol_dur_us=test_dur_us, num_cycles=test_original_num_cycles
    )

    chunked_subprotocol_list = chunk_subprotocol(test_subprotocol)
    assert len(chunked_subprotocol_list) == 1

    chunked_subprotocol = chunked_subprotocol_list[0]

    # pop this to make assertion on loop
    loop_subprotocols = chunked_subprotocol.pop("subprotocols")
    assert len(loop_subprotocols) == 1
    assert chunked_subprotocol == {"type": "loop", "num_repeats": expected_num_loop_repeats}

    # pop this to make assertion on the rest of the subprotocol_dict
    chunked_num_cycles = loop_subprotocols[0].pop("num_cycles")
    test_subprotocol.pop("num_cycles")
    assert loop_subprotocols[0] == test_subprotocol
    assert chunked_num_cycles * expected_num_loop_repeats == test_original_num_cycles


def test_chunk_subprotocol__returns_loop_with_shortened_subprotocol_and_leftover_subprotocol_with_less_cycles__when_subprotocol_cannot_be_divided_into_an_integer_num_of_full_size_chunks():
    expected_num_loop_repeats = randint(2, 5)
    test_dur_us = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS * expected_num_loop_repeats

    # the following conditions must be satisfied in order for there to be a loop and leftover chunk required:
    def filt(n):
        return (
            # the original number of cycles must not be a multiple of the expected number of loop repeats
            test_dur_us % n == 0
            # the original number of cycles must not be a factor of the total duration of the original subprotocol in order
            and n % expected_num_loop_repeats != 0
            # the number of cycles in the loop chunk and leftover chunk must not be the same
            and n // expected_num_loop_repeats != n % expected_num_loop_repeats
        )

    # the number of cycles in the loop chunk must be > 1 which is achieved by making sure the min number of
    # cycles in the original subprotocol is at least double the number of expected loop repeats
    min_original_num_cycles = expected_num_loop_repeats * 2

    test_original_num_cycles = choice(
        [n for n in range(min_original_num_cycles, int(test_dur_us**0.5) + 1) if filt(n)]
    )
    expected_num_cycles_in_loop = test_original_num_cycles // expected_num_loop_repeats
    expected_num_cycles_in_leftover = test_original_num_cycles % expected_num_loop_repeats

    test_subprotocol = get_random_stim_pulse(
        total_subprotocol_dur_us=test_dur_us, num_cycles=test_original_num_cycles
    )

    chunked_subprotocol_list = chunk_subprotocol(test_subprotocol)
    assert len(chunked_subprotocol_list) == 2

    loop_chunk, leftover_chunk = chunked_subprotocol_list

    # pop this to make assertion on loop
    loop_subprotocols = loop_chunk.pop("subprotocols")
    assert len(loop_subprotocols) == 1
    assert loop_chunk == {"type": "loop", "num_repeats": expected_num_loop_repeats}

    # pop these to make assertion on the rest of the subprotocol_dict
    test_subprotocol.pop("num_cycles")

    num_cycles_in_loop_chunk = loop_subprotocols[0].pop("num_cycles")
    assert loop_subprotocols[0] == test_subprotocol
    assert num_cycles_in_loop_chunk == expected_num_cycles_in_loop

    num_cycles_in_leftover_chunk = leftover_chunk.pop("num_cycles")
    assert leftover_chunk == test_subprotocol
    assert num_cycles_in_leftover_chunk == expected_num_cycles_in_leftover

    assert (
        num_cycles_in_loop_chunk * expected_num_loop_repeats + num_cycles_in_leftover_chunk
        == test_original_num_cycles
    )


def test_chunk_subprotocol__returns_loop_with_shortened_subprotocol_and_leftover_subprotocol_with_less_cycles__when_subprotocol_can_be_divided_into_an_integer_num_of_partial_chunks():
    assert not "TODO"


def test_chunk_subprotocol__returns_loop_with_shortened_subprotocol_and_leftover_subprotocol_with_less_cycles__when_subprotocol_cannot_be_divided_into_a_integer_num_of_partial_chunks():
    assert not "TODO"  # randomize this test correctly
    expected_num_loop_repeats = 2

    test_original_num_cycles = 191

    expected_num_cycles_in_loop = test_original_num_cycles // expected_num_loop_repeats
    expected_num_cycles_in_leftover = test_original_num_cycles % expected_num_loop_repeats

    test_subprotocol = {
        "type": "biphasic",
        "num_cycles": test_original_num_cycles,
        "postphase_interval": 75263,
        "phase_one_duration": 10000,
        "phase_one_charge": 4000,
        "interphase_interval": 10000,
        "phase_two_charge": -4000,
        "phase_two_duration": 10000,
    }

    chunked_subprotocol_list = chunk_subprotocol(test_subprotocol)
    assert len(chunked_subprotocol_list) == 2

    loop_chunk, leftover_chunk = chunked_subprotocol_list

    # pop this to make assertion on loop
    loop_subprotocols = loop_chunk.pop("subprotocols")
    assert len(loop_subprotocols) == 1
    assert loop_chunk == {"type": "loop", "num_repeats": expected_num_loop_repeats}

    # pop these to make assertion on the rest of the subprotocol_dict
    test_subprotocol.pop("num_cycles")

    num_cycles_in_loop_chunk = loop_subprotocols[0].pop("num_cycles")
    assert loop_subprotocols[0] == test_subprotocol
    assert num_cycles_in_loop_chunk == expected_num_cycles_in_loop

    num_cycles_in_leftover_chunk = leftover_chunk.pop("num_cycles")
    assert leftover_chunk == test_subprotocol
    assert num_cycles_in_leftover_chunk == expected_num_cycles_in_leftover

    assert (
        num_cycles_in_loop_chunk * expected_num_loop_repeats + num_cycles_in_leftover_chunk
        == test_original_num_cycles
    )


def test_chunk_protocols_in_stim_info__returns_correct_values(mocker):
    mocked_chunk_subprotocol_returns = [
        # protocol A
        [mocker.MagicMock(), mocker.MagicMock()],
        [mocker.MagicMock()],
        # protocol B
        [mocker.MagicMock()],
        [mocker.MagicMock()],
        [mocker.MagicMock(), mocker.MagicMock()],
    ]

    mocked_chunk_subprotocol = mocker.patch.object(
        stimulation, "chunk_subprotocol", autospec=True, side_effect=mocked_chunk_subprotocol_returns
    )

    test_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": random_stim_type(),
                "run_until_stopped": random_bool(),
                "subprotocols": [get_random_subprotocol() for _ in range(2)],
            },
            {
                "protocol_id": "B",
                "stimulation_type": random_stim_type(),
                "run_until_stopped": random_bool(),
                "subprotocols": [get_random_subprotocol() for _ in range(3)],
            },
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): choice(["A", "B"])
            for well_idx in range(24)
        },
    }

    expected_chunked_stim_info = copy.deepcopy(test_stim_info)
    expected_chunked_stim_info["protocols"][0]["subprotocols"] = [
        mocked_chunk_subprotocol_returns[0][0],
        mocked_chunk_subprotocol_returns[0][1],
        mocked_chunk_subprotocol_returns[1][0],
    ]
    expected_chunked_stim_info["protocols"][1]["subprotocols"] = [
        mocked_chunk_subprotocol_returns[2][0],
        mocked_chunk_subprotocol_returns[3][0],
        mocked_chunk_subprotocol_returns[4][0],
        mocked_chunk_subprotocol_returns[4][1],
    ]

    actual_stim_info, subprotocol_idx_mappings = chunk_protocols_in_stim_info(test_stim_info)

    # test chunked protocol
    for protocol_idx, (actual_protocol, expected_protocol) in enumerate(
        itertools.zip_longest(actual_stim_info.pop("protocols"), expected_chunked_stim_info.pop("protocols"))
    ):
        for subprotocol_idx, (actual_subprotocol, expected_subprotocol) in enumerate(
            itertools.zip_longest(actual_protocol.pop("subprotocols"), expected_protocol.pop("subprotocols"))
        ):
            assert (
                actual_subprotocol == expected_subprotocol
            ), f"Protocol {protocol_idx}, Subprotocol {subprotocol_idx}"

        # make sure the rest of the protocol wasn't changed
        assert actual_protocol == expected_protocol, f"Protocol {protocol_idx}"

    # make sure other stim info wasn't changed
    assert actual_stim_info == expected_chunked_stim_info

    # test mapping
    assert subprotocol_idx_mappings == {"A": {0: 0, 1: 0, 2: 1}, "B": {0: 0, 1: 1, 2: 2, 3: 2}}

    # make sure chunk_subprotocol was called correctly
    assert mocked_chunk_subprotocol.call_args_list == [
        mocker.call(subprotocol)
        for protocol in test_stim_info["protocols"]
        for subprotocol in protocol["subprotocols"]
    ]
