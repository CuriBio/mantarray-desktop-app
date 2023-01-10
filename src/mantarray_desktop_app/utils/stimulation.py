# -*- coding: utf-8 -*-
"""Utility functions for stimulation."""

import copy
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from ..constants import STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS
from ..constants import STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS

SUBPROTOCOL_DUTY_CYCLE_DUR_COMPONENTS = frozenset(
    ["phase_one_duration", "interphase_interval", "phase_two_duration"]
)


def get_pulse_duty_cycle_dur_us(subprotocol: Dict[str, Union[str, int]]) -> int:
    return sum(subprotocol.get(comp, 0) for comp in SUBPROTOCOL_DUTY_CYCLE_DUR_COMPONENTS)  # type: ignore


def get_pulse_dur_us(subprotocol: Dict[str, Union[str, int]]) -> int:
    return get_pulse_duty_cycle_dur_us(subprotocol) + subprotocol["postphase_interval"]  # type: ignore


def get_subprotocol_dur_us(subprotocol: Dict[str, Union[str, int]]) -> int:
    duration = (
        subprotocol["duration"]
        if subprotocol["type"] == "delay"
        else get_pulse_dur_us(subprotocol) * subprotocol["num_cycles"]
    )
    return duration  # type: ignore


def chunk_subprotocol(original_subprotocol: Dict[str, Any]) -> List[Dict[str, Any]]:
    # copy so the original subprotocol dict isn't modified
    subprotocol = copy.deepcopy(original_subprotocol)
    original_subprotocol_dur_us = get_subprotocol_dur_us(subprotocol)

    if (
        subprotocol["type"] == "delay"
        or original_subprotocol_dur_us <= STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS
    ):
        return [original_subprotocol]

    original_num_cycles = subprotocol["num_cycles"]

    pulse_dur_us = get_pulse_dur_us(subprotocol)
    max_num_cycles_in_loop = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // pulse_dur_us
    looped_subprotocol = {**subprotocol, "num_cycles": max_num_cycles_in_loop}
    num_loop_repeats = original_subprotocol_dur_us // get_subprotocol_dur_us(looped_subprotocol)  # type: ignore
    loop_chunk = {"type": "loop", "num_repeats": num_loop_repeats, "subprotocols": [looped_subprotocol]}

    subprotocol_chunks = [loop_chunk]

    if num_leftover_cycles := original_num_cycles - (looped_subprotocol["num_cycles"] * num_loop_repeats):
        leftover_chunk = {**subprotocol, "num_cycles": num_leftover_cycles}

        if get_subprotocol_dur_us(leftover_chunk) < STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS:
            # if there is only 1 loop repeat, then just return the original subprotocol
            if loop_chunk["num_repeats"] == 1:
                return [original_subprotocol]

            # otherwise, combine leftover chunk with the final loop repeat
            leftover_chunk["num_cycles"] += looped_subprotocol["num_cycles"]
            loop_chunk["num_repeats"] -= 1  # type: ignore

        subprotocol_chunks.append(leftover_chunk)

    return subprotocol_chunks


def chunk_protocols_in_stim_info(
    stim_info: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Dict[int, int]]]:
    # copying so the original dict passed in does not get modified
    chunked_stim_info = copy.deepcopy(stim_info)

    subprotocol_idx_mappings = {}

    for protocol in chunked_stim_info["protocols"]:
        chunked_idx_to_original_idx = {}
        curr_idx = 0

        new_subprotocols = []

        for original_idx, subprotocol in enumerate(protocol["subprotocols"]):
            subprotocol_chunks = chunk_subprotocol(subprotocol)

            for chunk in subprotocol_chunks:
                chunked_idx_to_original_idx[curr_idx] = original_idx
                new_subprotocols.append(chunk)
                curr_idx += 1

        protocol["subprotocols"] = new_subprotocols
        subprotocol_idx_mappings[protocol["protocol_id"]] = chunked_idx_to_original_idx

    return chunked_stim_info, subprotocol_idx_mappings


class StimulationSubrotocolManager:
    def __init__(
        self, subprotocols: List[Dict[str, Any]], num_repeats: Optional[int] = None, start_idx: int = 0
    ) -> None:
        if num_repeats is not None and num_repeats < 1:
            raise ValueError("num_repeats must be >= 1")

        self._subprotocols = copy.deepcopy(subprotocols)
        self._num_repeats = num_repeats
        self._start_idx = start_idx

        self._subprotocol_idx: int
        self._node_idx: int
        self._num_repeats_remaining: Optional[int]
        self._loop: Optional[StimulationSubrotocolManager]
        self._reset(hard_reset=True)

    def _reset(self, hard_reset: bool) -> None:
        self._reset_idxs(hard_reset)
        if self._num_repeats:
            self._num_repeats_remaining = self._num_repeats - 1
        else:
            self._num_repeats_remaining = None
        self._loop = None

    def restart(self) -> None:
        self._reset(hard_reset=False)

    def current(self) -> Dict[str, Any]:
        # if there is a loop, the current subprotocol must be retrieved from it the current node at this level is a loop
        if self._loop:
            return self._loop.current()
        # otherwise, return the current node stored at this level since it is not a loop
        return self._subprotocols[self._node_idx]

    def idx(self) -> int:
        # if there is a loop, the current idx must be retrieved from it as it is invalid at this level
        if self._loop:
            return self._loop.idx()
        # otherwise, return the current idx stored at this level
        return self._subprotocol_idx

    def advance(self) -> Dict[str, Any]:
        # if there is a loop, advance to the next subprotocol node within the loop first
        if self._loop:
            try:
                return self._loop.advance()
            except StopIteration:
                # the loop completed, so update the subprotocol idx at this level and then clear the loop
                self._subprotocol_idx = self._loop.idx()
                self._loop = None

        # advance to the next subprotocol node at this level
        self._increment_idxs(1)
        if self._node_idx >= len(self._subprotocols):
            if self._num_repeats_remaining is not None:
                if self._num_repeats_remaining <= 0:
                    self._increment_idxs(-1)
                    raise StopIteration
                self._num_repeats_remaining -= 1
            self._reset_idxs(hard_reset=False)

        subprotocol = self.current()

        # if the next subprotocol node is a loop, setup the loop and advance through it
        if subprotocol["type"] == "loop":
            self._loop = StimulationSubrotocolManager(
                subprotocol["subprotocols"], subprotocol["num_repeats"], self.idx()
            )
            return self._loop.advance()
        # otherwise, return this subprotocol
        return subprotocol

    def _increment_idxs(self, amount: int) -> None:
        self._node_idx += amount
        self._subprotocol_idx += amount

    def _reset_idxs(self, hard_reset: bool) -> None:
        self._subprotocol_idx = self._start_idx - int(hard_reset)
        self._node_idx = 0 - int(hard_reset)
