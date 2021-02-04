# -*- coding: utf-8 -*-
from multiprocessing import Queue

from mantarray_desktop_app import MantarrayMCSimulator
import pytest


@pytest.fixture(scope="function", name="mantarray_mc_simulator")
def fixture_mantarray_mc_simulator():
    input_queue = Queue()
    testing_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    simulator = MantarrayMCSimulator(
        input_queue, output_queue, error_queue, testing_queue
    )

    yield input_queue, output_queue, error_queue, testing_queue, simulator


@pytest.fixture(scope="function", name="mantarray_mc_simulator_no_beacon")
def fixture_mantarray_mc_simulator_no_beacon(mocker):
    testing_queue = Queue()
    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    simulator = MantarrayMCSimulator(
        input_queue, output_queue, error_queue, testing_queue
    )

    mocker.patch.object(simulator, "_handle_status_beacon", autospec=True)

    yield input_queue, output_queue, error_queue, testing_queue, simulator
