# -*- coding: utf-8 -*-
import copy
import logging
from multiprocessing import Queue
from random import randint
from zlib import crc32

from freezegun import freeze_time
from mantarray_desktop_app import convert_to_metadata_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import McCommunicationProcess
from mantarray_desktop_app import SERIAL_COMM_BAUD_RATE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_PACKET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_MIN_PACKET_SIZE_BYTES
from mantarray_desktop_app import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SerialCommIncorrectChecksumFromInstrumentError
from mantarray_desktop_app import SerialCommIncorrectChecksumFromPCError
from mantarray_desktop_app import SerialCommIncorrectMagicWordFromMantarrayError
from mantarray_desktop_app import SerialCommPacketFromMantarrayTooSmallError
from mantarray_desktop_app import SerialCommPacketRegistrationReadEmptyError
from mantarray_desktop_app import SerialCommPacketRegistrationSearchExhaustedError
from mantarray_desktop_app import SerialCommPacketRegistrationTimoutError
from mantarray_desktop_app import SerialCommUntrackedCommandResponseError
from mantarray_desktop_app import UnrecognizedCommandFromMainToMcCommError
from mantarray_desktop_app import UnrecognizedSerialCommModuleIdError
from mantarray_desktop_app import UnrecognizedSerialCommPacketTypeError
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import pytest
import serial
from serial import Serial
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import generate_board_and_error_queues
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import fixture_patch_comports
from ..fixtures_mc_comm import fixture_patch_serial_connection
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..helpers import assert_queue_is_eventually_not_empty
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_patch_print,
    fixture_four_board_mc_comm_process,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_patch_comports,
    fixture_patch_serial_connection,
    fixture_four_board_mc_comm_process_no_handshake,
]

DEFAULT_SIMULATOR_STATUS_CODE = bytes(4)
HANDSHAKE_RESPONSE_SIZE_BYTES = 24


def set_connection_and_register_simulator(
    mc_process,
    simulator_fixture,
) -> None:
    """Send a single status beacon in order to register magic word.

    Sets connection on board index 0.
    """
    simulator = simulator_fixture["simulator"]
    testing_queue = simulator_fixture["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    mc_process.set_board_connection(0, simulator)
    invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess_super_is_called_during_init(mocker):
    error_queue = Queue()
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")
    McCommunicationProcess((), error_queue)
    mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


@pytest.mark.slow
@freeze_time("2021-03-16 13:05:55.654321")
@pytest.mark.timeout(15)
def test_McCommunicationProcess_setup_before_loop__connects_to_boards__and_sends_message_to_main(
    four_board_mc_comm_process,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    assert mc_process.get_board_connections_list() == [None] * 4
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    populated_connections_list = mc_process.get_board_connections_list()
    assert isinstance(populated_connections_list[0], MantarrayMcSimulator)
    assert populated_connections_list[1:] == [None] * 3

    assert_queue_is_eventually_not_empty(board_queues[0][1])
    process_initiated_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert process_initiated_msg["communication_type"] == "log"
    assert (
        process_initiated_msg["message"]
        == "Microcontroller Communication Process initiated at 2021-03-16 13:05:55.654321"
    )
    # simulator is automatically started by mc_comm during setup_before_loop. Need to hard stop here since there is no access to the simulator's queues which must be drained before joining
    populated_connections_list[0].hard_stop()
    populated_connections_list[0].join()


@pytest.mark.slow
@pytest.mark.timeout(15)
def test_McCommunicationProcess_setup_before_loop__does_not_send_message_to_main_when_setup_comm_is_suppressed():
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    mc_process = McCommunicationProcess(
        board_queues, error_queue, suppress_setup_communication_to_main=True
    )
    assert mc_process.get_board_connections_list() == [None] * 4
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    populated_connections_list = mc_process.get_board_connections_list()
    assert isinstance(populated_connections_list[0], MantarrayMcSimulator)
    assert populated_connections_list[1:] == [None] * 3

    # Other parts of the process after setup may or may not send messages to main, so drain queue and make sure none of the items (if present) have a setup message
    to_main_queue_items = drain_queue(board_queues[0][1])
    for item in to_main_queue_items:
        if "message" in item:
            assert (
                "Microcontroller Communication Process initiated" not in item["message"]
            )

    # simulator is automatically started by mc_comm during setup_before_loop. Need to hard stop here since there is no access to the simulator's queues which must be drained before joining
    populated_connections_list[0].hard_stop()
    populated_connections_list[0].join()


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


def test_OkCommunicationProcess_soft_stop_not_allowed_if_communication_from_main_still_in_queue(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    dummy_communication = {
        "communication_type": "to_instrument",
        "command": "get_metadata",
    }
    items_to_put_in_queue = [copy.deepcopy(dummy_communication)] * 3
    # The first two commands will be processed, but if there is a third one in the queue then the soft stop should be disabled
    handle_putting_multiple_objects_into_empty_queue(
        items_to_put_in_queue, board_queues[0][0]
    )
    set_connection_and_register_simulator(mc_process, mantarray_mc_simulator_no_beacon)
    mc_process.soft_stop()
    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_stopped() is False


def test_McCommunicationProcess_teardown_after_loop__sets_teardown_complete_event(
    four_board_mc_comm_process,
):
    mc_process = four_board_mc_comm_process["mc_process"]

    mc_process.soft_stop()
    invoke_process_run_and_check_errors(
        mc_process, num_iterations=1, perform_teardown_after_loop=True
    )

    assert mc_process.is_teardown_complete() is True


@freeze_time("2021-03-19 12:53:30.654321")
def test_OkCommunicationProcess_teardown_after_loop__puts_teardown_log_message_into_queue(
    four_board_mc_comm_process,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    comm_to_main_queue = board_queues[0][1]

    mc_process.soft_stop()
    invoke_process_run_and_check_errors(
        mc_process, num_iterations=1, perform_teardown_after_loop=True
    )
    confirm_queue_is_eventually_of_size(comm_to_main_queue, 1)

    actual = comm_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert (
        actual["message"]
        == "Microcontroller Communication Process beginning teardown at 2021-03-19 12:53:30.654321"
    )


@pytest.mark.slow
@pytest.mark.timeout(15)
def test_OkCommunicationProcess_teardown_after_loop__stops_running_simulator(
    four_board_mc_comm_process,
):
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    mc_process = McCommunicationProcess(
        board_queues, error_queue, suppress_setup_communication_to_main=True
    )
    invoke_process_run_and_check_errors(
        mc_process,
        num_iterations=1,
        perform_teardown_after_loop=True,
        perform_setup_before_loop=True,
    )
    mc_process.soft_stop()
    simulator = mc_process.get_board_connections_list()[0]
    assert simulator.is_stopped() is True
    assert simulator.is_alive() is False


def test_McCommunicationProcess_set_board_connection__sets_connection_to_mc_simulator_correctly(
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


@freeze_time("2021-03-15 13:05:10.121212")
def test_McCommunicationProcess_create_connections_to_all_available_boards__populates_connections_list_with_a_serial_object_when_com_port_is_available__and_sends_correct_message_to_main(
    four_board_mc_comm_process, mocker, patch_comports, patch_serial_connection
):
    comport, comport_name, mocked_comports = patch_comports
    dummy_serial_obj, mocked_serial = patch_serial_connection
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    mocker.patch.object(
        mc_process,
        "determine_how_many_boards_are_connected",
        autospec=True,
        return_value=1,
    )
    board_idx = 0

    mc_process.create_connections_to_all_available_boards()
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    assert mocked_comports.call_count == 1
    assert mocked_serial.call_count == 1
    actual_connections = mc_process.get_board_connections_list()
    assert actual_connections[1:] == [None] * 3
    actual_serial_obj = actual_connections[board_idx]
    assert isinstance(actual_serial_obj, Serial)
    assert mocked_serial.call_args_list[0][1] == {
        "port": comport,
        "baudrate": SERIAL_COMM_BAUD_RATE,
        "bytesize": 8,
        "timeout": 0,
        "stopbits": serial.STOPBITS_ONE,
    }

    actual_message = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_message["communication_type"] == "board_connection_status_change"
    assert actual_message["board_index"] == board_idx
    assert comport_name in actual_message["message"]
    assert actual_message["is_connected"] is True
    assert actual_message["timestamp"] == "2021-03-15 13:05:10.121212"


@freeze_time("2021-03-15 13:27:31.005000")
def test_McCommunicationProcess_create_connections_to_all_available_boards__populates_connections_list_with_a_simulator_when_com_port_is_unavailable__and_sends_correct_message_to_main(
    four_board_mc_comm_process, mocker, patch_comports, patch_serial_connection
):
    _, _, mocked_comports = patch_comports
    mocked_comports.return_value = ["bad COM port"]
    _, mocked_serial = patch_serial_connection
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    mocker.patch.object(
        mc_process,
        "determine_how_many_boards_are_connected",
        autospec=True,
        return_value=1,
    )
    board_idx = 0

    mc_process.create_connections_to_all_available_boards()
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    assert mocked_comports.call_count == 1
    assert mocked_serial.call_count == 0
    actual_connections = mc_process.get_board_connections_list()
    assert actual_connections[1:] == [None] * 3
    actual_serial_obj = actual_connections[board_idx]
    assert isinstance(actual_serial_obj, MantarrayMcSimulator)

    actual_message = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_message["communication_type"] == "board_connection_status_change"
    assert actual_message["board_index"] == board_idx
    assert actual_message["message"] == "No board detected. Creating simulator."
    assert actual_message["is_connected"] is False
    assert actual_message["timestamp"] == "2021-03-15 13:27:31.005000"


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


def test_McCommunicationProcess_register_magic_word__registers_magic_word_in_serial_comm_from_board__when_first_packet_is_not_truncated__and_handles_reads_correctly_afterward(
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
    test_item = {"command": "add_read_bytes", "read_bytes": [test_bytes, test_bytes]}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_registered_with_serial_comm(board_idx) is True
    # make sure no errors reading next packet
    invoke_process_run_and_check_errors(mc_process)
    # make sure no errors when no more bytes available
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
        [bytes(0) for _ in range(SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS - 1)]
    )
    test_read_values.append(SERIAL_COMM_MAGIC_WORD_BYTES[4:])
    # add a real data packet after but remove magic word
    dummy_timestamp = 0
    test_packet = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    packet_length_bytes = test_packet[
        len(SERIAL_COMM_MAGIC_WORD_BYTES) : len(SERIAL_COMM_MAGIC_WORD_BYTES) + 2
    ]
    test_read_values.append(packet_length_bytes)
    test_read_values.append(test_packet[len(SERIAL_COMM_MAGIC_WORD_BYTES) + 2 :])
    mocked_read = mocker.patch.object(
        simulator, "read", autospec=True, side_effect=test_read_values
    )

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    assert mc_process.is_registered_with_serial_comm(board_idx) is False
    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_registered_with_serial_comm(board_idx) is True

    # Assert it reads once initially then once per second until status beacon period is reached (a new packet should be available by then). Tanner (3/16/21): changed == to >= in the next line because others parts of mc_comm may call read after the magic word is registered
    assert (
        len(mocked_read.call_args_list) >= SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS + 1
    )
    assert mocked_read.call_args_list[0] == mocker.call(size=8)
    assert mocked_read.call_args_list[1] == mocker.call(size=4)
    assert mocked_read.call_args_list[2] == mocker.call(size=4)
    assert mocked_read.call_args_list[3] == mocker.call(size=4)
    assert mocked_read.call_args_list[4] == mocker.call(size=4)

    # Assert sleep is called with correct value and correct number of times
    expected_sleep_secs = 1
    for sleep_call_num in range(SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS - 1):
        sleep_iter_call = mocked_sleep.call_args_list[sleep_call_num][0][0]
        assert (sleep_call_num, sleep_iter_call) == (
            sleep_call_num,
            expected_sleep_secs,
        )


def test_McCommunicationProcess_register_magic_word__raises_error_if_less_than_8_bytes_available_after_registration_timeout_period_has_elapsed(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    # mock sleep to speed up the test
    mocker.patch.object(mc_comm, "sleep", autospec=True)

    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # Arbitrarily slice the magic word in first read and add empty reads to simulate no bytes being available to read
    expected_partial_bytes = SERIAL_COMM_MAGIC_WORD_BYTES[:-1]
    test_read_values = [expected_partial_bytes]
    test_read_values.extend(
        [bytes(0) for _ in range(SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS + 4)]
    )
    # need to mock read here to have better control over the reads going into McComm
    mocker.patch.object(simulator, "read", autospec=True, side_effect=test_read_values)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommPacketRegistrationTimoutError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert str(expected_partial_bytes) in str(exc_info.value)


def test_McCommunicationProcess_register_magic_word__raises_error_if_reading_next_byte_results_in_empty_read_for_longer_than_registration_timeout_period(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    # mock with only two return values to speed up the test
    mocker.patch.object(
        mc_comm,
        "_get_seconds_since_read_start",
        autospec=True,
        side_effect=[0, SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS],
    )

    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # Add arbitrary first "magic word" bytes and then empty reads to raise error
    test_read_values = [bytes(len(SERIAL_COMM_MAGIC_WORD_BYTES)), bytes(0), bytes(0)]
    # need to mock read here to have better control over the reads going into McComm
    mocker.patch.object(simulator, "read", autospec=True, side_effect=test_read_values)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommPacketRegistrationReadEmptyError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess_register_magic_word__raises_error_if_search_exceeds_max_packet_length(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
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


def test_McCommunicationProcess_register_magic_word__does_not_try_to_register_when_not_connected_to_anything(
    four_board_mc_comm_process,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    invoke_process_run_and_check_errors(mc_process)

    assert mc_process.is_registered_with_serial_comm(0) is False
    assert mc_process.is_registered_with_serial_comm(1) is False
    assert mc_process.is_registered_with_serial_comm(2) is False
    assert mc_process.is_registered_with_serial_comm(3) is False


def test_McCommunicationProcess__raises_error_if_magic_word_is_incorrect_in_packet_after_previous_magic_word_has_been_registered(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    board_idx = 0
    dummy_timestamp = 0
    mc_process.set_board_connection(board_idx, simulator)
    assert mc_process.is_registered_with_serial_comm(board_idx) is False
    test_bytes_1 = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    # Add arbitrary incorrect value into magic word slot
    bad_magic_word = b"NANOSURF"
    test_bytes_2 = bad_magic_word + test_bytes_1[: len(SERIAL_COMM_MAGIC_WORD_BYTES)]
    test_item = {
        "command": "add_read_bytes",
        "read_bytes": [test_bytes_1, test_bytes_2],
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    with pytest.raises(
        SerialCommIncorrectMagicWordFromMantarrayError, match=str(bad_magic_word)
    ):
        # First iteration registers magic word, next iteration receive incorrect magic word
        invoke_process_run_and_check_errors(mc_process, num_iterations=2)


def test_McCommunicationProcess__raises_error_if_checksum_in_data_packet_sent_from_mantarray_is_invalid(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    # add packet with bad checksum to be sent from simulator
    dummy_timestamp = 0
    test_bytes = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    # set checksum bytes to an arbitrary incorrect value
    bad_checksum = 1234
    bad_checksum_bytes = bad_checksum.to_bytes(4, byteorder="little")
    test_bytes = test_bytes[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES] + bad_checksum_bytes
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "add_read_bytes",
            "read_bytes": test_bytes,
        },
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommIncorrectChecksumFromInstrumentError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)

    expected_checksum = int.from_bytes(
        test_bytes[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:], byteorder="little"
    )
    assert str(bad_checksum) in exc_info.value.args[0]
    assert str(expected_checksum) in exc_info.value.args[0]
    assert str(test_bytes) in exc_info.value.args[0]


def test_McCommunicationProcess__raises_error_if_not_enough_bytes_in_packet_sent_from_instrument(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    dummy_timestamp_bytes = bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    bad_packet_length = SERIAL_COMM_MIN_PACKET_SIZE_BYTES - 1
    test_packet = SERIAL_COMM_MAGIC_WORD_BYTES
    test_packet += bad_packet_length.to_bytes(2, byteorder="little")
    test_packet += dummy_timestamp_bytes
    test_packet += bytes([SERIAL_COMM_MAIN_MODULE_ID])
    test_packet += crc32(test_packet).to_bytes(
        SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little"
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "add_read_bytes",
            "read_bytes": test_packet,
        },
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommPacketFromMantarrayTooSmallError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert str(bad_packet_length) in exc_info.value.args[0]
    assert str(test_packet) in exc_info.value.args[0]


def test_McCommunicationProcess__raises_error_if_unrecognized_module_id_sent_from_instrument(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    dummy_timestamp = 0
    dummy_packet_type = 1
    test_module_id = 254
    test_packet = create_data_packet(
        dummy_timestamp,
        test_module_id,
        dummy_packet_type,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "add_read_bytes",
            "read_bytes": test_packet,
        },
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(UnrecognizedSerialCommModuleIdError, match=str(test_module_id)):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__raises_error_if_unrecognized_packet_type_sent_from_instrument(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    dummy_timestamp = 0
    test_packet_type = 254
    test_packet = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        test_packet_type,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "add_read_bytes",
            "read_bytes": test_packet,
        },
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(UnrecognizedSerialCommPacketTypeError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert str(SERIAL_COMM_MAIN_MODULE_ID) in str(exc_info.value)
    assert str(test_packet_type) in str(exc_info.value)


def test_McCommunicationProcess__raises_error_if_mantarray_returns_data_packet_that_it_determined_has_an_incorrect_checksum(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    dummy_timestamp_bytes = bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    dummy_checksum_bytes = bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES)
    handshake_packet_length = 14
    test_handshake = SERIAL_COMM_MAGIC_WORD_BYTES
    test_handshake += handshake_packet_length.to_bytes(2, byteorder="little")
    test_handshake += dummy_timestamp_bytes
    test_handshake += bytes([SERIAL_COMM_MAIN_MODULE_ID])
    test_handshake += bytes([SERIAL_COMM_HANDSHAKE_PACKET_TYPE])
    test_handshake += dummy_checksum_bytes
    # send bad packet to simulator to get checksum failure response
    simulator.write(test_handshake)
    invoke_process_run_and_check_errors(simulator)
    # assert that mc_comm receives the checksum failure response and handles it correctly
    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommIncorrectChecksumFromPCError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert str(test_handshake) in str(exc_info.value)


def test_McCommunicationProcess__includes_correct_timestamp_in_packets_sent_to_instrument(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    input_queue = board_queues[0][0]

    expected_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    mocker.patch.object(
        mc_process, "get_cms_since_init", autospec=True, return_value=expected_timestamp
    )

    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    spied_write = mocker.spy(simulator, "write")

    set_connection_and_register_simulator(mc_process, mantarray_mc_simulator_no_beacon)
    test_nickname = "anything"
    set_nickname_command = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": test_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(set_nickname_command), input_queue
    )
    # run mc_process one iteration to send the command
    invoke_process_run_and_check_errors(mc_process)

    expected_data_packet = create_data_packet(
        expected_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE])
        + convert_to_metadata_bytes(test_nickname),
    )
    spied_write.assert_called_with(expected_data_packet)


@pytest.mark.parametrize(
    "test_comm,test_description",
    [
        (
            {"communication_type": "bad_type"},
            "raises error with invalid communication_type",
        ),
        (
            {
                "communication_type": "mantarray_naming",
                "command": "bad_command",
            },
            "raises error with invalid mantarray_naming command",
        ),
        (
            {
                "communication_type": "to_instrument",
                "command": "bad_command",
            },
            "raises error with invalid to_instrument command",
        ),
    ],
)
def test_McCommunicationProcess__raises_error_when_receiving_invalid_command_from_main(
    test_comm, test_description, four_board_mc_comm_process, mocker, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    input_queue = four_board_mc_comm_process["board_queues"][0][0]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_comm, input_queue
    )
    with pytest.raises(UnrecognizedCommandFromMainToMcCommError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert test_comm["communication_type"] in str(exc_info.value)
    if "command" in test_comm:
        assert test_comm["command"] in str(exc_info.value)


def test_McCommunicationProcess__processes_set_mantarray_nickname_command(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    set_connection_and_register_simulator(mc_process, mantarray_mc_simulator_no_beacon)

    expected_nickname = "Mantarray++"
    set_nickname_command = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(set_nickname_command), input_queue
    )
    # run mc_process one iteration to send the command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator one iteration to process the command
    invoke_process_run_and_check_errors(simulator)
    actual = simulator.get_metadata_dict()[MANTARRAY_NICKNAME_UUID.bytes]
    assert actual == convert_to_metadata_bytes(expected_nickname)
    # run mc_process one iteration to read response from simulator and send command completed response back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    command_response = output_queue.get_nowait()
    assert command_response == set_nickname_command
    # confirm response is read by checking that no bytes are available to read from simulator
    assert simulator.in_waiting == 0


def test_McCommunicationProcess__processes_get_metadata_command(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    set_connection_and_register_simulator(mc_process, mantarray_mc_simulator_no_beacon)

    expected_response = {
        "communication_type": "to_instrument",
        "command": "get_metadata",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), input_queue
    )
    # run mc_process one iteration to send the command
    invoke_process_run_and_check_errors(mc_process)
    # run simulator one iteration to process the command
    invoke_process_run_and_check_errors(simulator)
    # run mc_process one iteration to get metadata from simulator and send back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    expected_response["metadata"] = MantarrayMcSimulator.default_metadata_values
    command_response = output_queue.get_nowait()
    assert command_response == expected_response


@pytest.mark.slow
@pytest.mark.timeout(20)
def test_McCommunicationProcess__processes_commands_from_main_when_process_is_fully_running(
    four_board_mc_comm_process,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]

    expected_nickname = "Running McSimulator"
    set_nickname_command = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    expected_response = {
        "communication_type": "to_instrument",
        "command": "get_metadata",
    }
    handle_putting_multiple_objects_into_empty_queue(
        [set_nickname_command, copy.deepcopy(expected_response)], input_queue
    )
    mc_process.start()
    confirm_queue_is_eventually_empty(  # Tanner (3/3/21): Using timeout longer than registration period here to give sufficient time to make sure queue is emptied
        input_queue, timeout_seconds=SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS + 6
    )
    mc_process.soft_stop()
    mc_process.join()

    to_main_items = drain_queue(output_queue)
    for item in to_main_items:
        if item.get("command", None) == "get_metadata":
            assert item["metadata"][MANTARRAY_NICKNAME_UUID] == expected_nickname
            break
    else:
        assert False, "expected response to main not found"


def test_McCommunicationProcess__sends_handshake_every_5_seconds__and_includes_correct_timestamp__and_processes_response(
    four_board_mc_comm_process,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_write = mocker.spy(simulator, "write")

    expected_durs = [
        0,
        CENTIMILLISECONDS_PER_SECOND * SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS,
    ]
    mocker.patch.object(
        mc_process, "get_cms_since_init", autospec=True, side_effect=expected_durs
    )
    mocker.patch.object(
        mc_comm,
        "_get_secs_since_last_handshake",
        autospec=True,
        side_effect=[
            0,
            SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS,
            SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS - 1,
            1,
        ],
    )

    set_connection_and_register_simulator(mc_process, mantarray_mc_simulator_no_beacon)
    # send handshake
    invoke_process_run_and_check_errors(mc_process)
    expected_handshake_1 = create_data_packet(
        expected_durs[0],
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
        bytes(0),
    )
    assert spied_write.call_args[0][0] == expected_handshake_1
    # process handshake on simulator
    invoke_process_run_and_check_errors(simulator)
    # process handshake response
    invoke_process_run_and_check_errors(mc_process)
    # assert handshake response was read
    assert simulator.in_waiting == 0
    # repeat, 5 seconds since prev beacon
    invoke_process_run_and_check_errors(mc_process)
    expected_handshake_2 = create_data_packet(
        expected_durs[1],
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
        bytes(0),
    )
    assert spied_write.call_args[0][0] == expected_handshake_2
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    assert simulator.in_waiting == 0


def test_McCommunicationProcess__raises_error_when_receiving_untracked_command_response_from_instrument(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
    patch_print,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_command_response = create_data_packet(
        test_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        bytes(8),  # 8 arbitrary bytes in place of timestamp of command sent from pc
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": test_command_response},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    mc_process.set_board_connection(0, simulator)
    with pytest.raises(SerialCommUntrackedCommandResponseError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert str(test_command_response) in str(exc_info.value)
