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


def chunk_subprotocol(
    original_subprotocol: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    # copy so the original subprotocol dict isn't modified
    original_subprotocol = copy.deepcopy(original_subprotocol)
    original_subprotocol_dur_us = get_subprotocol_dur_us(original_subprotocol)

    if (
        original_subprotocol["type"] == "delay"
        or original_subprotocol_dur_us <= STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS
    ):
        return None, original_subprotocol

    original_num_cycles = original_subprotocol["num_cycles"]

    pulse_dur_us = get_pulse_dur_us(original_subprotocol)
    max_num_cycles_in_loop = STIM_MAX_CHUNKED_SUBPROTOCOL_DUR_MICROSECONDS // pulse_dur_us
    looped_subprotocol = {**original_subprotocol, "num_cycles": max_num_cycles_in_loop}
    num_loop_iterations = original_subprotocol_dur_us // get_subprotocol_dur_us(looped_subprotocol)  # type: ignore

    loop_chunk = {"type": "loop", "num_iterations": num_loop_iterations, "subprotocols": [looped_subprotocol]}

    leftover_chunk = None

    if num_leftover_cycles := original_num_cycles - (looped_subprotocol["num_cycles"] * num_loop_iterations):
        leftover_chunk = {**original_subprotocol, "num_cycles": num_leftover_cycles}

        if get_subprotocol_dur_us(leftover_chunk) < STIM_MIN_SUBPROTOCOL_DURATION_MICROSECONDS:
            # if there is only 1 loop iteration, then just return the original subprotocol
            if loop_chunk["num_iterations"] == 1:
                return None, original_subprotocol
            # otherwise, combine leftover chunk with the final loop iteration
            leftover_chunk["num_cycles"] += looped_subprotocol["num_cycles"]
            loop_chunk["num_iterations"] -= 1  # type: ignore

    return loop_chunk, leftover_chunk


def chunk_protocols_in_stim_info(
    stim_info: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Dict[int, int]], Dict[str, Tuple[int, ...]]]:
    # copying so the original dict passed in does not get modified
    chunked_stim_info = copy.deepcopy(stim_info)

    subprotocol_idx_mappings = {}
    max_subprotocol_idx_counts = {}

    for protocol in chunked_stim_info["protocols"]:
        curr_chunked_idx = 0

        chunked_idx_to_original_idx = {}
        original_idx_counts = []
        new_subprotocols = []

        for original_idx, subprotocol in enumerate(protocol["subprotocols"]):
            original_idx_count = 0

            for chunk in chunk_subprotocol(subprotocol):
                if not chunk:
                    continue

                chunked_idx_to_original_idx[curr_chunked_idx] = original_idx
                # for loop chunk need to count the num iterations, leftover chunk is always 1
                original_idx_count += chunk.get("num_iterations", 1)
                new_subprotocols.append(chunk)

                curr_chunked_idx += 1

            original_idx_counts.append(original_idx_count)

        protocol["subprotocols"] = new_subprotocols

        protocol_id = protocol["protocol_id"]
        subprotocol_idx_mappings[protocol_id] = chunked_idx_to_original_idx
        max_subprotocol_idx_counts[protocol_id] = tuple(original_idx_counts)

    return chunked_stim_info, subprotocol_idx_mappings, max_subprotocol_idx_counts


class StimulationProtocolManager:
    def __init__(
        self, subprotocols: List[Dict[str, Any]], num_iterations: Optional[int] = None, start_idx: int = 0
    ) -> None:
        if num_iterations is not None and num_iterations < 1:
            raise ValueError("num_iterations must be >= 1")

        self._subprotocols = copy.deepcopy(subprotocols)
        self._num_iterations = num_iterations
        self._start_idx = start_idx

        self._subprotocol_idx: int
        self._node_idx: int
        self._num_iterations_remaining: Optional[int]
        self._loop: Optional[StimulationProtocolManager]
        self._reset()

    def _reset(self) -> None:
        self._reset_idxs(hard_reset=True)
        # reset the number of iteratioms remaining if a limit was given
        if self._num_iterations:
            self._num_iterations_remaining = self._num_iterations - 1
        else:
            self._num_iterations_remaining = None
        self._loop = None

    def complete(self) -> bool:
        # if not on the final node or still have more iterations, then not complete
        if self._node_idx < len(self._subprotocols) - 1 or self._num_iterations_remaining:
            return False
        # if on the final node but a loop is present, need to check if the loop is complete
        if self._loop:
            return self._loop.complete()
        # if on the final node and no loop is present, then the protocol is complete
        return True

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
            if self._num_iterations_remaining is not None:
                if self._num_iterations_remaining <= 0:
                    self._increment_idxs(-1)
                    raise StopIteration
                self._num_iterations_remaining -= 1
            self._reset_idxs(hard_reset=False)

        subprotocol = self.current()

        # if the next subprotocol node is a loop, setup the loop and advance through it
        if subprotocol["type"] == "loop":
            self._loop = StimulationProtocolManager(
                subprotocol["subprotocols"], subprotocol["num_iterations"], self.idx()
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
