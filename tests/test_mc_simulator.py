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
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from .helpers import confirm_queue_is_eventually_empty
from .helpers import confirm_queue_is_eventually_of_size
from .helpers import handle_putting_multiple_objects_into_queue
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
]

STATUS_BEACON_SIZE_BYTES = 1  # TODO


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


def test_MantarrayMCSimulator_hard_stop__clears_all_queues_and_returns_lists_of_values(
    mantarray_mc_simulator_no_beacon,
):
    (
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        simulator,
    ) = mantarray_mc_simulator_no_beacon

    test_testing_queue_item_1 = {
        "command": "add_read_bytes",
        "read_bytes": b"first test bytes",
    }
    testing_queue.put(test_testing_queue_item_1)
    test_testing_queue_item_2 = {
        "command": "add_read_bytes",
        "read_bytes": b"second test bytes",
    }
    testing_queue.put(test_testing_queue_item_2)
    confirm_queue_is_eventually_of_size(testing_queue, 2)

    test_input_item = b"some more bytes"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_input_item, input_queue
    )

    test_output_item = b"some more bytes"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_output_item, output_queue
    )

    test_error_item = {"test_error": "an error"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_error_item, error_queue
    )

    actual = simulator.hard_stop()
    assert actual["fatal_error_reporter"] == [test_error_item]
    assert actual["input_queue"] == [test_input_item]
    assert actual["output_queue"] == [test_output_item]
    assert actual["testing_queue"] == [
        test_testing_queue_item_1,
        test_testing_queue_item_2,
    ]

    confirm_queue_is_eventually_empty(input_queue)
    confirm_queue_is_eventually_empty(output_queue)
    confirm_queue_is_eventually_empty(error_queue)
    confirm_queue_is_eventually_empty(testing_queue)


def test_MantarrayMCSimulator__correctly_stores_time_since_initialized(
    mocker,
):
    expected_init_time = 15796649135715
    expected_poll_time = 15880317595302
    mocker.patch.object(  # Tanner (2/1/21): mocking perf_counter is generally a bad idea but can't think of any other way to test this
        mc_simulator,
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


def test_MantarrayMCSimulator_read__gets_next_available_bytes(
    mantarray_mc_simulator_no_beacon,
):
    _, _, _, testing_queue, simulator = mantarray_mc_simulator_no_beacon

    expected_bytes = b"expected_item"
    test_item = {"command": "add_read_bytes", "read_bytes": expected_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    actual_item = simulator.read(size=len(expected_bytes))
    assert actual_item == expected_bytes


def test_MantarrayMCSimulator_read__returns_empty_bytes_if_no_bytes_to_read(
    mantarray_mc_simulator,
):
    _, _, _, _, simulator = mantarray_mc_simulator
    actual_item = simulator.read(size=10)
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


def test_MantarrayMCSimulator__makes_status_beacon_available_to_read_on_first_iteration__with_random_truncation(
    mantarray_mc_simulator, mocker
):
    spied_randint = mocker.spy(random, "randint")

    _, _, _, _, simulator = mantarray_mc_simulator
    mocker.patch.object(simulator, "get_dur_since_init", autospec=True, return_value=0)

    invoke_process_run_and_check_errors(simulator)
    spied_randint.assert_called_once_with(0, 10)

    expected_initial_beacon = (
        SERIAL_COMM_MAGIC_WORD_BYTES + bytes(8) + b"\x00\x00\x04" + bytes(4)
    )
    # TODO
    actual = simulator.read(size=len(expected_initial_beacon))
    assert actual == expected_initial_beacon[spied_randint.spy_return :]


def test_MantarrayMCSimulator__makes_status_beacon_available_to_read_every_5_seconds__and_includes_correct_timestamp(
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

    # TODO
    # remove boot up beacon
    invoke_process_run_and_check_errors(simulator)
    output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    # 1 second since prev beacon
    invoke_process_run_and_check_errors(simulator)
    # 5 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    expected_beacon_1 = (
        SERIAL_COMM_MAGIC_WORD_BYTES
        + expected_durs[1].to_bytes(8, "little")
        + b"\x00\x00\x04"
        + bytes(4)
    )
    # TODO
    assert simulator.read(size=len(expected_beacon_1)) == expected_beacon_1
    # 4 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    # 6 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    expected_beacon_2 = (
        SERIAL_COMM_MAGIC_WORD_BYTES
        + expected_durs[2].to_bytes(8, "little")
        + b"\x00\x00\x04"
        + bytes(4)
    )
    # TODO
    assert simulator.read(size=len(expected_beacon_2)) == expected_beacon_2


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
    mantarray_mc_simulator_no_beacon,
):
    _, _, _, testing_queue, simulator = mantarray_mc_simulator_no_beacon

    test_size_diff = 2
    item_1 = b"item_one"
    item_2 = b"second_item"

    test_items = [
        {"command": "add_read_bytes", "read_bytes": item_1},
        {"command": "add_read_bytes", "read_bytes": item_2},
    ]
    handle_putting_multiple_objects_into_queue(test_items, testing_queue)
    invoke_process_run_and_check_errors(simulator, 2)
    confirm_queue_is_eventually_empty(testing_queue)

    expected_1 = item_1[:-test_size_diff]
    actual_1 = simulator.read(size=len(item_1) - test_size_diff)
    assert actual_1 == expected_1

    expected_2 = item_1[-test_size_diff:] + item_2[:-test_size_diff]
    actual_2 = simulator.read(size=len(item_2))
    assert actual_2 == expected_2

    expected_3 = item_2[-test_size_diff:]
    actual_3 = simulator.read(
        size=len(expected_3)
    )  # specifically want to read exactly the remaining number of bytes
    assert actual_3 == expected_3


def test_MantarrayMCSimulator__handles_reads_of_size_less_than_next_packet_in_queue__when_queue_is_empty(
    mantarray_mc_simulator_no_beacon,
):
    _, _, _, testing_queue, simulator = mantarray_mc_simulator_no_beacon

    test_size_diff_1 = 3
    test_size_diff_2 = 1
    test_item = b"first_item"
    test_dict = {"command": "add_read_bytes", "read_bytes": test_item}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_dict, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    expected_1 = test_item[:-test_size_diff_1]
    actual_1 = simulator.read(size=len(test_item) - test_size_diff_1)
    assert actual_1 == expected_1

    expected_2 = test_item[-test_size_diff_1:-test_size_diff_2]
    actual_2 = simulator.read(size=test_size_diff_1 - test_size_diff_2)
    assert actual_2 == expected_2

    expected_3 = test_item[-1:]
    actual_3 = simulator.read()
    assert actual_3 == expected_3


@pytest.mark.slow
def test_MantarrayMCSimulator__handles_reads_of_size_less_than_next_packet_in_queue__when_simulator_is_running(
    mantarray_mc_simulator,
):
    _, output_queue, _, testing_queue, simulator = mantarray_mc_simulator

    test_item_1 = b"12345"
    test_item_2 = b"67890"
    test_items = [
        {"command": "add_read_bytes", "read_bytes": test_item_1},
        {"command": "add_read_bytes", "read_bytes": test_item_2},
    ]
    handle_putting_multiple_objects_into_queue(test_items, testing_queue)

    # Tanner (2/2/20): this try/finally block ensures that the simulator is stopped even if the test fails. Problems can arise from processes not being stopped after tests complete
    try:
        simulator.start()
        confirm_queue_is_eventually_empty(testing_queue, timeout_seconds=5)
        # remove boot up beacon
        # TODO
        output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

        read_len_1 = 3
        read_1 = simulator.read(size=read_len_1)
        assert read_1 == test_item_1[:read_len_1]
        # read remaining bytes
        read_len_2 = len(test_item_1) + len(test_item_2) - read_len_1
        read_2 = simulator.read(size=read_len_2)
        assert read_2 == test_item_1[read_len_1:] + test_item_2
    finally:
        simulator.hard_stop()
        simulator.join()
