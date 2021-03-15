# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue

from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import McCommunicationProcess
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import SerialCommPacketRegistrationReadEmptyError
from mantarray_desktop_app import SerialCommPacketRegistrationSearchExhaustedError
from mantarray_desktop_app import SerialCommPacketRegistrationTimoutError
import pytest
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from .fixtures_mc_comm import fixture_four_board_mc_comm_process
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from .helpers import confirm_queue_is_eventually_empty
from .helpers import confirm_queue_is_eventually_of_size
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_four_board_mc_comm_process,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
]

DEFAULT_SIMULATOR_STATUS_CODE = bytes(4)


def test_McCommunicationProcess_super_is_called_during_init(mocker):
    error_queue = Queue()
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")
    McCommunicationProcess((), error_queue)
    mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


def test_McCommunicationProcess_hard_stop__clears_all_queues_and_returns_lists_of_values(
    four_board_mc_comm_process,
):
    mc_process, board_queues, error_queue = four_board_mc_comm_process.values()

    expected = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]]
    expected_error = "error"

    for i, board in enumerate(board_queues):
        for j, queue in enumerate(board):
            item = expected[i][j]
            queue.put(item)
    confirm_queue_is_eventually_of_size(board_queues[3][2], 1)
    error_queue.put(expected_error)
    confirm_queue_is_eventually_of_size(error_queue, 1)

    actual = mc_process.hard_stop()
    assert actual["fatal_error_reporter"] == [expected_error]

    # Assert arbitrarily that most queues are empty
    confirm_queue_is_eventually_empty(board_queues[1][0])
    confirm_queue_is_eventually_empty(board_queues[2][0])
    confirm_queue_is_eventually_empty(board_queues[3][0])
    confirm_queue_is_eventually_empty(board_queues[0][0])
    confirm_queue_is_eventually_empty(board_queues[0][2])

    # Assert arbitrarily that most queue items are correct
    assert actual["board_1"]["main_to_instrument_comm"] == [expected[1][0]]
    assert actual["board_2"]["main_to_instrument_comm"] == [expected[2][0]]
    assert actual["board_3"]["main_to_instrument_comm"] == [expected[3][0]]
    assert actual["board_0"]["main_to_instrument_comm"] == [expected[0][0]]
    assert expected[0][1] in actual["board_0"]["instrument_comm_to_main"]
    assert actual["board_0"]["instrument_comm_to_file_writer"] == [expected[0][2]]


def test_McCommunicationProcess_set_board_connection__sets_connect_to_mc_simulator_correctly(
    four_board_mc_comm_process, mantarray_mc_simulator
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator["simulator"]

    mc_process.set_board_connection(1, simulator)
    actual = mc_process.get_board_connections_list()

    assert actual[0] is None
    assert actual[1] is simulator
    assert actual[2] is None
    assert actual[3] is None


def test_McCommunicationProcess_register_magic_word__registers_magic_word_in_serial_comm_from_board__when_first_packet_is_truncated_to_more_than_8_bytes(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    board_idx = 0
    dummy_timestamp = 0
    mc_process.set_board_connection(board_idx, simulator)
    assert mc_process.is_registered_with_serial_comm(board_idx) is False
    test_bytes = SERIAL_COMM_MAGIC_WORD_BYTES[3:] + bytes(8)
    test_bytes += create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    test_item = {"command": "add_read_bytes", "read_bytes": test_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_registered_with_serial_comm(board_idx) is True
    # make sure no errors in next iteration
    invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess_register_magic_word__registers_magic_word_in_serial_comm_from_board__when_first_packet_is_not_truncated(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    board_idx = 0
    dummy_timestamp = 0
    mc_process.set_board_connection(board_idx, simulator)
    assert mc_process.is_registered_with_serial_comm(board_idx) is False
    test_bytes = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    test_item = {"command": "add_read_bytes", "read_bytes": test_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_registered_with_serial_comm(board_idx) is True
    # make sure no errors in next iteration
    invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess_register_magic_word__registers_with_magic_word_in_serial_comm_from_board__when_first_packet_is_truncated_to_less_than_8_bytes__and_calls_read_with_correct_size__and_calls_sleep_correctly(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    # mock sleep to speed up the test
    mocked_sleep = mocker.patch.object(mc_comm, "sleep", autospec=True)

    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # Arbitrarily slice the magic word across multiple reads and add empty reads to simulate no bytes being available to read
    test_read_values = [SERIAL_COMM_MAGIC_WORD_BYTES[:4]]
    test_read_values.extend(
        [bytes(0) for _ in range(SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS - 1)]
    )
    test_read_values.append(SERIAL_COMM_MAGIC_WORD_BYTES[4:])
    # need to mock read here to have better control over the reads going into McComm
    mocked_read = mocker.patch.object(
        simulator, "read", autospec=True, side_effect=test_read_values
    )

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    assert mc_process.is_registered_with_serial_comm(board_idx) is False
    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_registered_with_serial_comm(board_idx) is True

    # Assert it reads once initially then once per second until status beacon period is reached (a new packet should be available by then)
    assert (
        len(mocked_read.call_args_list) == SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS + 1
    )
    assert mocked_read.call_args_list[0] == mocker.call(size=8)
    assert mocked_read.call_args_list[1] == mocker.call(size=4)
    assert mocked_read.call_args_list[2] == mocker.call(size=4)
    assert mocked_read.call_args_list[3] == mocker.call(size=4)
    assert mocked_read.call_args_list[4] == mocker.call(size=4)

    # Assert sleep is called with correct value and correct number of times
    expected_sleep_secs = 1
    for sleep_call_num in range(SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS - 1):
        sleep_iter_call = mocked_sleep.call_args_list[sleep_call_num][0][0]
        assert (sleep_call_num, sleep_iter_call) == (
            sleep_call_num,
            expected_sleep_secs,
        )


def test_McCommunicationProcess_register_magic_word__raises_error_if_less_than_8_bytes_available_after_status_beacon_period_has_elapsed(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    # mock sleep to speed up the test
    mocker.patch.object(mc_comm, "sleep", autospec=True)

    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # Arbitrarily slice the magic word in first read and add empty reads to simulate no bytes being available to read
    test_read_values = [SERIAL_COMM_MAGIC_WORD_BYTES[:-1]]
    test_read_values.extend(
        [bytes(0) for _ in range(SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS)]
    )
    # need to mock read here to have better control over the reads going into McComm
    mocker.patch.object(simulator, "read", autospec=True, side_effect=test_read_values)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommPacketRegistrationTimoutError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess_register_magic_word__raises_error_if_reading_next_byte_results_in_empty_read(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    # mock sleep to speed up the test
    mocker.patch.object(mc_comm, "sleep", autospec=True)

    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # Add arbitrary first 8 bytes and then empty read to raise error
    test_read_values = [bytes(8), bytes(0)]
    # need to mock read here to have better control over the reads going into McComm
    mocker.patch.object(simulator, "read", autospec=True, side_effect=test_read_values)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommPacketRegistrationReadEmptyError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess_register_magic_word__raises_error_if_search_exceeds_max_packet_length(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    # mock sleep to speed up the test
    mocker.patch.object(mc_comm, "sleep", autospec=True)

    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # Add arbitrary first 8 bytes and then enough arbitrary bytes to reach a max size data packet length to raise error
    test_read_values = [bytes(8)]
    test_read_values.extend(
        [bytes(1) for _ in range(SERIAL_COMM_MAX_PACKET_LENGTH_BYTES + 1)]
    )
    # need to mock read here to have better control over the reads going into McComm
    mocker.patch.object(simulator, "read", autospec=True, side_effect=test_read_values)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommPacketRegistrationSearchExhaustedError):
        invoke_process_run_and_check_errors(mc_process)
