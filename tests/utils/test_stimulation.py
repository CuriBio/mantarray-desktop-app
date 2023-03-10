# -*- coding: utf-8 -*-
import copy
import itertools
import math
from random import choice
from random import randint

from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app.constants import STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS
from mantarray_desktop_app.constants import STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
from mantarray_desktop_app.utils import stimulation
from mantarray_desktop_app.utils.stimulation import chunk_protocols_in_stim_info
from mantarray_desktop_app.utils.stimulation import chunk_subprotocol
import pytest

from ..fixtures_mc_simulator import get_random_stim_delay
from ..fixtures_mc_simulator import get_random_stim_pulse
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_mc_simulator import random_stim_type
from ..helpers import random_bool

TEST_MIN_PULSE_FREQ = 0.1
TEST_MAX_PULSE_FREQ = 100


TEST_MIN_PULSE_DUR_US = int(MICRO_TO_BASE_CONVERSION / TEST_MAX_PULSE_FREQ)
TEST_MAX_PULSE_DUR_US = int(MICRO_TO_BASE_CONVERSION / TEST_MIN_PULSE_FREQ)


def pulse_dur_generator(filt):
    pulse_dur_candidate_gen = range(
        TEST_MIN_PULSE_DUR_US, TEST_MAX_PULSE_DUR_US + TEST_MIN_PULSE_DUR_US, TEST_MIN_PULSE_DUR_US
    )
    possible_pulse_durs = [dur for dur in pulse_dur_candidate_gen if filt(dur)]
    return choice(possible_pulse_durs)


def test_chunk_subprotocol__returns_delay_unmodified():
    test_delay = get_random_stim_delay()
    assert chunk_subprotocol(test_delay) == (None, test_delay)


def test_chunk_subprotocol__returns_pulse_unmodified_if_no_chunking_needed():
    test_dur_us = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS
    test_subprotocol = get_random_stim_pulse(total_subprotocol_dur_us=test_dur_us)
    assert chunk_subprotocol(test_subprotocol) == (None, test_subprotocol)


@pytest.mark.parametrize("is_loop_full_size", [True, False])
def test_chunk_subprotocol__divides_into_loop_without_leftover_cycles(is_loop_full_size):
    test_pulse_dur_us = pulse_dur_generator(
        lambda dur_us: (STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS % dur_us == 0) is is_loop_full_size
    )
    test_num_loop_cycles = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // test_pulse_dur_us
    expected_num_loop_iterations = randint(2, 5)

    test_original_num_cycles = test_num_loop_cycles * expected_num_loop_iterations
    test_original_dur_us = test_pulse_dur_us * test_original_num_cycles
    test_subprotocol = get_random_stim_pulse(
        total_subprotocol_dur_us=test_original_dur_us, num_cycles=test_original_num_cycles
    )

    actual_loop_chunk, actual_leftover_chunk = chunk_subprotocol(test_subprotocol)

    # check loop chunk
    assert actual_loop_chunk is not None
    # pop this to make assertion on loop
    loop_subprotocols = actual_loop_chunk.pop("subprotocols")
    assert len(loop_subprotocols) == 1
    assert actual_loop_chunk == {"type": "loop", "num_iterations": expected_num_loop_iterations}
    # pop this to make assertion on the rest of the subprotocol_dict
    chunked_num_cycles = loop_subprotocols[0].pop("num_cycles")
    test_subprotocol.pop("num_cycles")
    assert loop_subprotocols[0] == test_subprotocol
    assert chunked_num_cycles * expected_num_loop_iterations == test_original_num_cycles

    # check leftover chunk
    assert actual_leftover_chunk is None


@pytest.mark.parametrize("is_loop_full_size", [True, False])
def test_chunk_subprotocol__divides_into_loop_with_leftover_cycles__leftover_chunk_meets_min_subprotocol_dur_requirement(
    is_loop_full_size,
):
    test_pulse_dur_us = pulse_dur_generator(
        lambda dur_us: (STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS % dur_us == 0) is is_loop_full_size
    )
    expected_num_loop_cycles = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // test_pulse_dur_us
    expected_num_loop_iterations = randint(1, 5)
    expected_num_leftover_cycles = math.ceil(STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS / test_pulse_dur_us)

    test_original_num_cycles = (
        expected_num_loop_cycles * expected_num_loop_iterations + expected_num_leftover_cycles
    )
    test_original_dur_us = test_pulse_dur_us * test_original_num_cycles
    test_subprotocol = get_random_stim_pulse(
        total_subprotocol_dur_us=test_original_dur_us, num_cycles=test_original_num_cycles
    )

    actual_loop_chunk, actual_leftover_chunk = chunk_subprotocol(test_subprotocol)
    # make sure both chunks are present
    assert actual_loop_chunk is not None
    assert actual_leftover_chunk is not None

    # pop this to make assertion on loop
    loop_subprotocols = actual_loop_chunk.pop("subprotocols")
    assert len(loop_subprotocols) == 1
    assert actual_loop_chunk == {"type": "loop", "num_iterations": expected_num_loop_iterations}

    # pop this to make assertion on the rest of the subprotocol_dict
    test_subprotocol.pop("num_cycles")

    num_cycles_in_loop_chunk = loop_subprotocols[0].pop("num_cycles")
    assert loop_subprotocols[0] == test_subprotocol
    assert num_cycles_in_loop_chunk == expected_num_loop_cycles

    num_cycles_in_leftover_chunk = actual_leftover_chunk.pop("num_cycles")
    assert actual_leftover_chunk == test_subprotocol
    assert num_cycles_in_leftover_chunk == expected_num_leftover_cycles

    assert (
        num_cycles_in_loop_chunk * expected_num_loop_iterations + num_cycles_in_leftover_chunk
        == test_original_num_cycles
    )


@pytest.mark.parametrize("is_loop_full_size", [True, False])
def test_chunk_subprotocol__divides_into_loop_with_leftover_cycles__leftover_chunk_does_not_meet_min_subprotocol_dur_requirement__can_borrow_from_loop(
    is_loop_full_size,
):
    test_pulse_dur_us = pulse_dur_generator(
        lambda dur_us: (
            (STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS % dur_us == 0) is is_loop_full_size
            and dur_us < STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
        )
    )
    test_initial_num_loop_iterations = randint(2, 5)
    test_initial_num_leftover_cycles = STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS // test_pulse_dur_us
    if STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS % test_pulse_dur_us == 0:
        # when this happens the leftover chunk will be exactly the min subprotocol duration, so need to remove one cycle to shorten it
        test_initial_num_leftover_cycles -= 1
    expected_num_loop_cycles = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // test_pulse_dur_us
    expected_num_loop_iterations = test_initial_num_loop_iterations - 1
    expected_num_leftover_cycles = test_initial_num_leftover_cycles + expected_num_loop_cycles

    test_original_num_cycles = (
        expected_num_loop_cycles * test_initial_num_loop_iterations + test_initial_num_leftover_cycles
    )
    test_original_dur_us = test_pulse_dur_us * test_original_num_cycles
    test_subprotocol = get_random_stim_pulse(
        total_subprotocol_dur_us=test_original_dur_us, num_cycles=test_original_num_cycles
    )

    actual_loop_chunk, actual_leftover_chunk = chunk_subprotocol(test_subprotocol)
    # make sure both chunks are present
    assert actual_loop_chunk is not None
    assert actual_leftover_chunk is not None

    # pop this to make assertion on loop
    loop_subprotocols = actual_loop_chunk.pop("subprotocols")
    assert len(loop_subprotocols) == 1
    assert actual_loop_chunk == {"type": "loop", "num_iterations": expected_num_loop_iterations}

    # pop these to make assertion on the rest of the subprotocol_dict
    test_subprotocol.pop("num_cycles")

    num_cycles_in_loop_chunk = loop_subprotocols[0].pop("num_cycles")
    assert loop_subprotocols[0] == test_subprotocol
    assert num_cycles_in_loop_chunk == expected_num_loop_cycles

    num_cycles_in_leftover_chunk = actual_leftover_chunk.pop("num_cycles")
    assert actual_leftover_chunk == test_subprotocol
    assert num_cycles_in_leftover_chunk == expected_num_leftover_cycles

    assert (
        num_cycles_in_loop_chunk * expected_num_loop_iterations + num_cycles_in_leftover_chunk
        == test_original_num_cycles
    )


@pytest.mark.parametrize("is_loop_full_size", [True, False])
def test_chunk_subprotocol__divides_into_loop_with_leftover_cycles__leftover_chunk_does_not_meet_min_subprotocol_dur_requirement__cannot_borrow_from_loop(
    is_loop_full_size,
):
    test_pulse_dur_us = pulse_dur_generator(
        lambda dur_us: (
            (STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS % dur_us == 0) is is_loop_full_size
            and dur_us < STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS
        )
    )
    test_initial_num_loop_iterations = 1
    test_initial_num_loop_cycles = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // test_pulse_dur_us
    test_initial_num_leftover_cycles = STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS // test_pulse_dur_us
    if STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS % test_pulse_dur_us == 0:
        # when this happens the leftover chunk will be exactly the min subprotocol duration, so need to remove one cycle to shorten it
        test_initial_num_leftover_cycles -= 1

    test_original_num_cycles = (
        test_initial_num_loop_cycles * test_initial_num_loop_iterations + test_initial_num_leftover_cycles
    )
    test_original_dur_us = test_pulse_dur_us * test_original_num_cycles
    test_subprotocol = get_random_stim_pulse(
        total_subprotocol_dur_us=test_original_dur_us, num_cycles=test_original_num_cycles
    )

    assert chunk_subprotocol(test_subprotocol) == (None, test_subprotocol)


def test_chunk_protocols_in_stim_info__returns_correct_values(mocker):
    mocked_chunk_subprotocol_returns = [
        # protocol A
        ({"num_iterations": randint(1, 10)}, {"dummy": 0}),
        (None, {"dummy": 1}),
        # protocol B
        (None, {"dummy": 2}),
        (None, {"dummy": 3}),
        ({"num_iterations": randint(11, 20)}, {"dummy": 4}),
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
        {
            "type": "loop",
            "num_iterations": 1,
            "subprotocols": [
                mocked_chunk_subprotocol_returns[0][0],
                mocked_chunk_subprotocol_returns[0][1],
                mocked_chunk_subprotocol_returns[1][1],
            ],
        }
    ]
    expected_chunked_stim_info["protocols"][1]["subprotocols"] = [
        {
            "type": "loop",
            "num_iterations": 1,
            "subprotocols": [
                mocked_chunk_subprotocol_returns[2][1],
                mocked_chunk_subprotocol_returns[3][1],
                mocked_chunk_subprotocol_returns[4][0],
                mocked_chunk_subprotocol_returns[4][1],
            ],
        }
    ]

    actual_stim_info, subprotocol_idx_mappings, max_subprotocol_idx_counts = chunk_protocols_in_stim_info(
        test_stim_info
    )

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

    # test counters
    assert max_subprotocol_idx_counts == {
        "A": (mocked_chunk_subprotocol_returns[0][0]["num_iterations"] + 1, 1),
        "B": (1, 1, mocked_chunk_subprotocol_returns[4][0]["num_iterations"] + 1),
    }

    # make sure chunk_subprotocol was called correctly
    assert mocked_chunk_subprotocol.call_args_list == [
        mocker.call(subprotocol)
        for protocol in test_stim_info["protocols"]
        for subprotocol in protocol["subprotocols"]
    ]
