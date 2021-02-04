# -*- coding: utf-8 -*-
from multiprocessing import Queue

from mantarray_desktop_app import MantarrayMCSimulator
from mantarray_desktop_app import SECONDS_TO_WAIT_WHEN_POLLING_QUEUES
import pytest


@pytest.fixture(scope="function", name="mantarray_mc_simulator")
def fixture_mantarray_mc_simulator():
    input_queue = Queue()
    testing_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    simulator = MantarrayMCSimulator(
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        read_timeout_seconds=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES,
    )

    yield input_queue, output_queue, error_queue, testing_queue, simulator


class MantarrayMCSimulatorNoBeacons(MantarrayMCSimulator):
    def _handle_status_beacon(self) -> None:
        return


@pytest.fixture(scope="function", name="mantarray_mc_simulator_no_beacon")
def fixture_mantarray_mc_simulator_no_beacon(mocker):
    testing_queue = Queue()
    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    simulator = MantarrayMCSimulatorNoBeacons(
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        read_timeout_seconds=SECONDS_TO_WAIT_WHEN_POLLING_QUEUES,
    )

    yield input_queue, output_queue, error_queue, testing_queue, simulator
