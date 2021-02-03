# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue
import random

from mantarray_desktop_app import MantarrayMCSimulator
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import UnrecognizedSimulatorTestCommandError
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import pytest
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


def test_MantarrayMCSimulator__correctly_stores_time_since_initialized(
    mocker,
):
    mocker.patch.object(
        InfiniteProcess, "__init__"
    )  # Tanner (2/1/21): mocking super classes __init__ so there are no conflicting calls to perf_counter_ns

    expected_init_time = 15796649135715
    expected_poll_time = 15880317595302
    mocker.patch.object(  # Tanner (2/1/21): mocking perf_counter is generally a bad idea but can't think of any other way to test this
        mc_simulator.time,
        "perf_counter_ns",
        autospec=True,
        side_effect=[expected_init_time, expected_poll_time],
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


def test_MantarrayMCSimulator_read__gets_next_item_from_output_queue(
    mantarray_mc_simulator,
):
    _, output_queue, _, _, simulator = mantarray_mc_simulator
    simulator.read()  # clear initial status beacon
    confirm_queue_is_eventually_empty(output_queue)

    expected_item = "expected_item"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_item, output_queue
    )
    actual_item = simulator.read(len(expected_item))
    assert actual_item == expected_item


def test_MantarrayMCSimulator_read__returns_empty_bytes_if_output_queue_is_empty(
    mantarray_mc_simulator,
):
    _, _, _, _, simulator = mantarray_mc_simulator
    simulator.read()  # clear initial status beacon
    actual_item = simulator.read(10)
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


def test_MantarrayMCSimulator__puts_status_beacon_into_output_queue_on_first_iteration__with_random_truncation(
    mantarray_mc_simulator, mocker
):
    spied_randint = mocker.spy(random, "randint")

    _, output_queue, _, _, simulator = mantarray_mc_simulator
    mocker.patch.object(simulator, "get_dur_since_init", autospec=True, return_value=0)

    invoke_process_run_and_check_errors(simulator)
    spied_randint.assert_called_once_with(0, 10)

    confirm_queue_is_eventually_of_size(output_queue, 1)
    actual = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_initial_beacon = (
        SERIAL_COMM_MAGIC_WORD_BYTES + bytes(8) + b"\x00\x00\x04" + bytes(4)
    )
    assert actual == expected_initial_beacon[spied_randint.spy_return :]


def test_MantarrayMCSimulator__puts_status_beacon_into_output_queue_every_5_seconds__and_includes_correct_timestamp(
    mantarray_mc_simulator, mocker
):
    _, output_queue, _, _, simulator = mantarray_mc_simulator

    expected_durs = [
        0,
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
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    # 1 second since prev beacon
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_empty(output_queue)
    # 5 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    expected_beacon_1 = (
        SERIAL_COMM_MAGIC_WORD_BYTES
        + expected_durs[1].to_bytes(8, "little")
        + b"\x00\x00\x04"
        + bytes(4)
    )
    assert output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_beacon_1
    # 4 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_empty(output_queue)
    # 6 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    expected_beacon_2 = (
        SERIAL_COMM_MAGIC_WORD_BYTES
        + expected_durs[2].to_bytes(8, "little")
        + b"\x00\x00\x04"
        + bytes(4)
    )
    assert output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_beacon_2


def test_MantarrayMCSimulator__allows_reads_to_be_set_through_test_queue(
    mantarray_mc_simulator,
):
    _, output_queue, _, testing_queue, simulator = mantarray_mc_simulator

    # remove boot up beacon
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    expected_bytes = b"test_item"
    test_item = {"command": "add_read_bytes", "read_bytes": expected_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    actual = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert expected_bytes == actual


def test_MantarrayMCSimulator__raises_error_if_unrecognized_test_command_is_received(
    mantarray_mc_simulator,
):
    _, _, _, testing_queue, simulator = mantarray_mc_simulator

    expected_command = "bad_command"
    test_item = {"command": expected_command}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    with pytest.raises(UnrecognizedSimulatorTestCommandError, match=expected_command):
        invoke_process_run_and_check_errors(simulator)


def test_MantarrayMCSimulator__handles_reads_of_size_less_than_next_packet_in_queue__when_queue_is_not_empty(
    mantarray_mc_simulator,
):
    _, output_queue, _, _, simulator = mantarray_mc_simulator

    test_size_diff = 2
    item_1 = b"item_one"
    item_2 = b"second_item"
    output_queue.put(item_1)
    output_queue.put(item_2)
    confirm_queue_is_eventually_of_size(output_queue, 2)

    expected_1 = item_1[:-test_size_diff]
    actual_1 = simulator.read(len(item_1) - test_size_diff)
    assert actual_1 == expected_1

    expected_2 = item_1[-test_size_diff:] + item_2[:-test_size_diff]
    actual_2 = simulator.read(len(item_2))
    assert actual_2 == expected_2

    expected_3 = item_2[-test_size_diff:]
    actual_3 = simulator.read(
        len(expected_3)
    )  # specifically want to read exactly the remaining number of bytes
    assert actual_3 == expected_3


def test_MantarrayMCSimulator__handles_reads_of_size_less_than_next_packet_in_queue__when_queue_is_empty(
    mantarray_mc_simulator,
):
    _, output_queue, _, _, simulator = mantarray_mc_simulator

    test_size_diff_1 = 3
    test_size_diff_2 = 1
    test_item = b"first_item"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, output_queue
    )

    expected_1 = test_item[:-test_size_diff_1]
    actual_1 = simulator.read(len(test_item) - test_size_diff_1)
    assert actual_1 == expected_1

    expected_2 = test_item[-test_size_diff_1:-test_size_diff_2]
    actual_2 = simulator.read(test_size_diff_1 - test_size_diff_2)
    assert actual_2 == expected_2

    expected_3 = test_item[-1:]
    actual_3 = simulator.read(1)
    assert actual_3 == expected_3


@pytest.mark.slow
def test_MantarrayMCSimulator__handles_reads_of_size_less_than_next_packet_in_queue__when_simulator_is_running(
    mantarray_mc_simulator,
):
    _, output_queue, _, testing_queue, simulator = mantarray_mc_simulator

    test_item_1 = b"12345"
    test_item_2 = b"67890"
    testing_queue.put({"command": "add_read_bytes", "read_bytes": test_item_1})
    testing_queue.put({"command": "add_read_bytes", "read_bytes": test_item_2})
    confirm_queue_is_eventually_of_size(testing_queue, 2)

    # Tanner (2/2/20): this try/finally block ensures that the simulator is stopped even if the test fails. Problems can arise from processes not being stopped after tests complete
    try:
        simulator.start()
        confirm_queue_is_eventually_empty(  # Tanner (2/2/21): Adding a large timeout here to avoid sporadic failures in CI (windows did not like a 5 second timeout)
            testing_queue, timeout_seconds=10
        )
        # remove boot up beacon
        output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

        read_len_1 = 3
        read_1 = simulator.read(read_len_1)
        assert read_1 == test_item_1[:read_len_1]
        # read remaining bytes
        read_len_2 = len(test_item_1) + len(test_item_2) - read_len_1
        read_2 = simulator.read(read_len_2)
        assert read_2 == test_item_1[read_len_1:] + test_item_2
    finally:
        simulator.stop()
        simulator.join()
