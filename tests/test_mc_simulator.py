# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue

from mantarray_desktop_app import MantarrayMCSimulator
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator
from .helpers import confirm_queue_is_eventually_empty
from .helpers import confirm_queue_is_eventually_of_size
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_mantarray_mc_simulator,
]


def test_MantarrayMCSimulator__super_is_called_during_init__with_default_logging_value(
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

    # TODO Tanner (2/2/21): figure out how to remove BrokenPipeErrors in this and the following test
    # drain_queue(output_queue)  # prevent BrokenPipeErrors


def test_MantarrayMCSimulator__correctly_stores_time_since_initialized(
    mocker,
):
    mocker.patch.object(
        InfiniteProcess, "__init__"
    )  # Tanner (2/1/21): mocking super classes __init__ so there are no conflicting calls to perf_counter_ns

    expected_init_time = 15796649135715
    dummy_val = 99999999999999
    expected_poll_time = 15880317595302
    mocker.patch.object(  # Tanner (2/1/21): mocking perf_counter is generally a bad idea but can't think of any other way to test this
        mc_simulator.time,
        "perf_counter_ns",
        autospec=True,
        side_effect=[expected_init_time, dummy_val, expected_poll_time],
    )

    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    testing_queue = Queue()
    simulator = MantarrayMCSimulator(
        input_queue, output_queue, error_queue, testing_queue
    )

    expected_dur_since_init = expected_poll_time - expected_init_time
    assert simulator.get_dur_since_init() == expected_dur_since_init

    # drain_queue(output_queue)  # prevent BrokenPipeErrors


def test_MantarrayMCSimulator_read__gets_next_item_from_output_queue(
    mantarray_mc_simulator,
):
    _, output_queue, _, _, simulator = mantarray_mc_simulator
    simulator.read()  # clear initial handshake message
    confirm_queue_is_eventually_empty(output_queue)

    expected_item = "expected_item"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_item, output_queue
    )
    actual_item = simulator.read()
    assert actual_item == expected_item


def test_MantarrayMCSimulator_read__returns_empty_bytes_if_output_queue_is_empty(
    mantarray_mc_simulator,
):
    _, _, _, _, simulator = mantarray_mc_simulator
    simulator.read()  # clear initial status beacon
    actual_item = simulator.read()
    expected_item = bytes(0)
    assert actual_item == expected_item


def test_MantarrayMCSimulator_write__puts_object_into_input_queue(
    mantarray_mc_simulator,
):
    input_queue, _, _, _, simulator = mantarray_mc_simulator
    test_item = b"input_item"
    simulator.write(test_item)
    confirm_queue_is_eventually_of_size(input_queue, 1)
    # Tanner (1/28/21): removing item from queue to avoid BrokenPipeError
    actual_item = input_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_item == test_item


def test_MantarrayMCSimulator__puts_status_beacon_into_output_queue_on_initialization__with_random_truncation(
    mantarray_mc_simulator,
):
    _, output_queue, _, _, _ = mantarray_mc_simulator
    confirm_queue_is_eventually_of_size(output_queue, 1)
    init_status_beacon = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert SERIAL_COMM_MAGIC_WORD_BYTES in init_status_beacon


def test_MantarrayMCSimulator__puts_status_beacon_into_output_queue_every_5_seconds__and_includes_correct_timestamp(
    mantarray_mc_simulator, mocker
):
    _, output_queue, _, _, simulator = mantarray_mc_simulator

    expected_durs = [
        CENTIMILLISECONDS_PER_SECOND * SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS,
        CENTIMILLISECONDS_PER_SECOND * SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS * 2 + 1,
    ]
    mocker.patch.object(
        simulator, "get_dur_since_init", autospec=True, side_effect=expected_durs
    )
    mocker.patch.object(
        mc_simulator,
        "_get_dur_since_last_status_beacon",
        autospec=True,
        side_effect=[
            1,
            SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS,
            SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS - 1,
            SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS + 1,
        ],
    )

    # remove boot up beacon
    confirm_queue_is_eventually_of_size(output_queue, 1)
    output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    # 1 second since prev beacon
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_empty(output_queue)
    # 5 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    expected_handshake_1 = (
        SERIAL_COMM_MAGIC_WORD_BYTES
        + expected_durs[0].to_bytes(8, "little")
        + b"\x00\x00\x04"
        + bytes(4)
    )
    assert output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_handshake_1
    # 4 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_empty(output_queue)
    # 6 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    expected_handshake_2 = (
        SERIAL_COMM_MAGIC_WORD_BYTES
        + expected_durs[1].to_bytes(8, "little")
        + b"\x00\x00\x04"
        + bytes(4)
    )
    assert output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_handshake_2
