# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue

from mantarray_desktop_app import MantarrayMCSimulator
from stdlib_utils import InfiniteProcess

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator
from .helpers import confirm_queue_is_eventually_of_size
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_mantarray_mc_simulator,
]


def test_MantarrayMCSimulator__super_is_called_during_init__and_default_logging_value(
    mocker,
):
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")

    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    testing_queue = Queue()
    MantarrayMCSimulator(input_queue, output_queue, error_queue, testing_queue)

    mocked_init.assert_called_once_with(
        error_queue,
        logging_level=logging.INFO,
    )


def test_MantarrayMCSimulator_read__gets_next_item_from_output_queue(
    mantarray_mc_simulator,
):
    _, output_queue, _, _, mc_simulator = mantarray_mc_simulator
    expected_item = "expected_item"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_item, output_queue
    )
    actual_item = mc_simulator.read()
    assert actual_item == expected_item


def test_MantarrayMCSimulator_read__returns_empty_bytearray_if_output_queue_is_empty(
    mantarray_mc_simulator,
):
    _, _, _, _, mc_simulator = mantarray_mc_simulator
    actual_item = mc_simulator.read()
    expected_item = bytearray(0)
    assert actual_item == expected_item


def test_MantarrayMCSimulator_write__puts_object_into_input_queue(
    mantarray_mc_simulator,
):
    input_queue, _, _, _, mc_simulator = mantarray_mc_simulator
    test_item = "input_item"
    mc_simulator.write(test_item)
    confirm_queue_is_eventually_of_size(input_queue, 1)
    # Tanner (1/28/21): removing item from queue to avoid BrokenPipeError
    actual_item = input_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_item == test_item
