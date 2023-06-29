# -*- coding: utf-8 -*-
import copy

from freezegun import freeze_time
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import InstrumentRebootTimeoutError
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MAX_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app import SERIAL_COMM_BAUD_RATE
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_FULL_PACKET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from mantarray_desktop_app import SerialCommPacketRegistrationReadEmptyError
from mantarray_desktop_app import SerialCommPacketRegistrationSearchExhaustedError
from mantarray_desktop_app import SerialCommPacketRegistrationTimeoutError
from mantarray_desktop_app.constants import SERIAL_COMM_GET_METADATA_PACKET_TYPE
from mantarray_desktop_app.simulators import mc_simulator
from mantarray_desktop_app.simulators.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app.sub_processes import mc_comm
from mantarray_desktop_app.utils.serial_comm import convert_status_code_bytes_to_dict
import pytest
import serial
from serial import Serial
from serial.tools.list_ports_common import ListPortInfo
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import fixture_patch_comports
from ..fixtures_mc_comm import fixture_patch_serial_connection
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import DEFAULT_SIMULATOR_STATUS_CODES
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..helpers import assert_serial_packet_is_expected
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_four_board_mc_comm_process_no_handshake,
    fixture_patch_print,
    fixture_four_board_mc_comm_process,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_patch_comports,
    fixture_patch_serial_connection,
]


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
    comport, comport_description, mocked_comports = patch_comports
    _, mocked_serial = patch_serial_connection
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    mocker.patch.object(mc_process, "determine_how_many_boards_are_connected", autospec=True, return_value=1)
    board_idx = 0
    actual_connections = mc_process.get_board_connections_list()

    assert actual_connections == [None] * 4
    mc_process.create_connections_to_all_available_boards()
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    assert mocked_comports.call_count == 1
    assert mocked_serial.call_count == 1
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
    assert comport_description in actual_message["message"]
    assert actual_message["is_connected"] is True
    assert actual_message["timestamp"] == "2021-03-15 13:05:10.121212"


@freeze_time("2021-03-15 13:27:31.005000")
def test_McCommunicationProcess_create_connections_to_all_available_boards__populates_connections_list_with_a_simulator_when_com_port_is_unavailable__and_sends_correct_message_to_main(
    four_board_mc_comm_process, mocker, patch_comports, patch_serial_connection
):
    *_, mocked_comports = patch_comports
    mocked_comports.return_value = [ListPortInfo("")]
    _, mocked_serial = patch_serial_connection
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    mocker.patch.object(mc_process, "determine_how_many_boards_are_connected", autospec=True, return_value=1)
    board_idx = 0
    actual_connections = mc_process.get_board_connections_list()

    assert actual_connections == [None] * 4
    mc_process.create_connections_to_all_available_boards()
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    assert mocked_comports.call_count == 1
    assert mocked_serial.call_count == 0
    actual_connections = mc_process.get_board_connections_list()
    assert actual_connections[1:] == [None] * 3
    actual_serial_obj = actual_connections[board_idx]
    assert isinstance(actual_serial_obj, MantarrayMcSimulator)
    # Tanner (8/25/21): it's important that the simulator is created with no read timeout because the connection to a real instrument will not have one either
    assert actual_serial_obj._read_timeout_seconds == 0

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
    mc_process.set_board_connection(board_idx, simulator)
    assert mc_process.is_registered_with_serial_comm(board_idx) is False
    test_bytes = SERIAL_COMM_MAGIC_WORD_BYTES[3:] + bytes(8)
    dummy_timestamp = 0
    test_bytes += create_data_packet(
        dummy_timestamp, SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, DEFAULT_SIMULATOR_STATUS_CODES
    )
    test_item = {"command": "add_read_bytes", "read_bytes": test_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_item, testing_queue)
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
    timestamp = 0
    mc_process.set_board_connection(board_idx, simulator)
    assert mc_process.is_registered_with_serial_comm(board_idx) is False
    test_bytes = create_data_packet(
        timestamp, SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, DEFAULT_SIMULATOR_STATUS_CODES
    )
    test_item = {"command": "add_read_bytes", "read_bytes": [test_bytes, test_bytes]}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_item, testing_queue)
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
    test_read_values.extend([bytes(0) for _ in range(SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS - 1)])
    test_read_values.append(SERIAL_COMM_MAGIC_WORD_BYTES[4:])
    # add a real data packet after but remove magic word
    dummy_timestamp = 0
    test_packet = create_data_packet(
        dummy_timestamp, SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, DEFAULT_SIMULATOR_STATUS_CODES
    )
    packet_length_bytes = test_packet[
        len(SERIAL_COMM_MAGIC_WORD_BYTES) : len(SERIAL_COMM_MAGIC_WORD_BYTES)
        + SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
    ]
    test_read_values.append(packet_length_bytes)
    test_read_values.append(
        test_packet[len(SERIAL_COMM_MAGIC_WORD_BYTES) + SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES :]
    )
    mocked_read = mocker.patch.object(simulator, "read", autospec=True, side_effect=test_read_values)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    assert mc_process.is_registered_with_serial_comm(board_idx) is False
    invoke_process_run_and_check_errors(mc_process)
    assert mc_process.is_registered_with_serial_comm(board_idx) is True

    # Assert it reads once initially then once per second until status beacon period is reached (a new packet should be available by then). Tanner (3/16/21): changed == to >= in the next line because others parts of mc_comm may call read after the magic word is registered
    assert len(mocked_read.call_args_list) >= SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS + 1
    assert mocked_read.call_args_list[0] == mocker.call(size=8)
    assert mocked_read.call_args_list[1] == mocker.call(size=4)
    assert mocked_read.call_args_list[2] == mocker.call(size=4)
    assert mocked_read.call_args_list[3] == mocker.call(size=4)
    assert mocked_read.call_args_list[4] == mocker.call(size=4)

    # Assert sleep is called with correct value and correct number of times
    expected_sleep_secs = 1
    for sleep_call_num in range(SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS - 1):
        sleep_iter_call = mocked_sleep.call_args_list[sleep_call_num][0][0]
        assert sleep_iter_call == expected_sleep_secs, sleep_call_num


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
    test_read_values.extend([bytes(0) for _ in range(SERIAL_COMM_REGISTRATION_TIMEOUT_SECONDS + 4)])
    # need to mock read here to have better control over the reads going into McComm
    mocker.patch.object(simulator, "read", autospec=True, side_effect=test_read_values)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommPacketRegistrationTimeoutError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert str(list(expected_partial_bytes)) in str(exc_info.value)


def test_McCommunicationProcess_register_magic_word__raises_error_if_reading_next_byte_results_in_empty_read_for_longer_than_registration_timeout_period(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    # mock with only two return values to speed up the test
    mocker.patch.object(
        mc_comm,
        "_get_secs_since_read_start",
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
    test_read_values.extend([bytes(1) for _ in range(SERIAL_COMM_MAX_FULL_PACKET_LENGTH_BYTES + 1)])
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


def test_McCommunicationProcess__waits_until_instrument_is_done_rebooting_to_send_commands(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator["simulator"]
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]

    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        side_effect=[AVERAGE_MC_REBOOT_DURATION_SECONDS],
    )

    set_connection_and_register_simulator(four_board_mc_comm_process_no_handshake, mantarray_mc_simulator)
    reboot_command = {"communication_type": "to_instrument", "command": "reboot"}
    test_command = {"communication_type": "metadata_comm", "command": "get_metadata"}
    handle_putting_multiple_objects_into_empty_queue(
        [copy.deepcopy(reboot_command), copy.deepcopy(test_command)], input_queue
    )
    # run mc_process to sent reboot command and simulator to start reboot
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # run mc_process once and confirm the command is still in queue
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(input_queue, 1)
    # run simulator to finish reboot
    invoke_process_run_and_check_errors(simulator)
    # run mc_process twice to confirm reboot completion and then to send command to simulator
    invoke_process_run_and_check_errors(mc_process, num_iterations=2)
    # run simulator once to process the command
    invoke_process_run_and_check_errors(simulator)
    # run mc_process to process response from instrument and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    # confirm message was sent back to main
    to_main_items = drain_queue(output_queue)
    assert to_main_items[-1]["command"] == "get_metadata"


def test_McCommunicationProcess__does_not_check_for_overdue_status_beacons_after_reboot_command_is_sent(
    four_board_mc_comm_process, mantarray_mc_simulator, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    simulator = mantarray_mc_simulator["simulator"]
    input_queue = board_queues[0][0]
    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator)

    mocked_get_secs = mocker.patch.object(
        mc_comm,
        "_get_secs_since_last_beacon",
        autospec=True,
        side_effect=[SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS],
    )
    reboot_command = {"communication_type": "to_instrument", "command": "reboot"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(reboot_command), input_queue
    )
    # run mc_process to sent reboot command and simulator to start reboot
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # run mc_process again to make sure status beacon time is not checked
    assert mocked_get_secs.call_count == 0


def test_McCommunicationProcess__raises_error_if_reboot_takes_longer_than_maximum_reboot_period(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator,
    mocker,
    patch_print,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    simulator = mantarray_mc_simulator["simulator"]
    input_queue = board_queues[0][0]
    set_connection_and_register_simulator(four_board_mc_comm_process_no_handshake, mantarray_mc_simulator)

    mocker.patch.object(
        mc_comm,
        "_get_secs_since_reboot_start",
        autospec=True,
        side_effect=[MAX_MC_REBOOT_DURATION_SECONDS],
    )

    reboot_command = {"communication_type": "to_instrument", "command": "reboot"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(reboot_command), input_queue
    )
    # run mc_process to sent reboot command and simulator to start reboot
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # run mc_process to raise error after reboot period has elapsed and confirm error is raised
    with pytest.raises(InstrumentRebootTimeoutError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__requests_metadata_if_setup_before_loop_was_performed(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]
    set_connection_and_register_simulator(four_board_mc_comm_process_no_handshake, mantarray_mc_simulator)

    spied_write = mocker.spy(simulator, "write")
    mocker.patch.object(  # Tanner (4/6/21): Need to prevent automatic beacons without interrupting the beacons sent after status code updates
        mc_simulator, "_get_secs_since_last_status_beacon", return_value=0, autospec=True
    )
    # Tanner (5/22/21): performing set up before loop means that mc_comm will try to start the simulator process which will slow this test down
    mocker.patch.object(simulator, "start", autospec=True)

    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)

    # have simulator send a status beacon to trigger automatic collection of metadata
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # send get metadata command
    invoke_process_run_and_check_errors(mc_process)
    # process get metadata command
    invoke_process_run_and_check_errors(simulator)
    # send metadata to main
    invoke_process_run_and_check_errors(mc_process)
    assert_serial_packet_is_expected(spied_write.call_args[0][0], SERIAL_COMM_GET_METADATA_PACKET_TYPE)
    # check that metadata was sent to main
    to_main_items = drain_queue(output_queue)
    metadata_comm = to_main_items[-1]
    assert metadata_comm["communication_type"] == "metadata_comm"
    expected_dict = dict(MantarrayMcSimulator.default_metadata_values)
    expected_dict.pop("is_stingray")
    expected_dict["status_codes_prior_to_reboot"] = convert_status_code_bytes_to_dict(
        DEFAULT_SIMULATOR_STATUS_CODES
    )
    assert metadata_comm["metadata"] == expected_dict
