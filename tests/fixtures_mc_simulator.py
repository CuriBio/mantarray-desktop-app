# -*- coding: utf-8 -*-
from multiprocessing import Queue

from mantarray_desktop_app import MantarrayMCSimulator
import pytest
from stdlib_utils import drain_queue


@pytest.fixture(scope="function", name="mantarray_mc_simulator")
def fixture_mantarray_mc_simulator():
    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    testing_queue = Queue()
    mc_simulator = MantarrayMCSimulator(
        input_queue, output_queue, error_queue, testing_queue
    )

    yield input_queue, output_queue, error_queue, testing_queue, mc_simulator

    drain_queue(input_queue)
    drain_queue(output_queue)
    drain_queue(error_queue)
    drain_queue(testing_queue)
