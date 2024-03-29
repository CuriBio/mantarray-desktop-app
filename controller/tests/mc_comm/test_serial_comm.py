# -*- coding: utf-8 -*-
import copy
import logging
from random import randint

from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import FirmwareGoingDormantError
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_GET_METADATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PLATE_EVENT_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SerialCommCommandResponseTimeoutError
from mantarray_desktop_app import SerialCommIncorrectChecksumFromInstrumentError
from mantarray_desktop_app import SerialCommIncorrectChecksumFromPCError
from mantarray_desktop_app import SerialCommIncorrectMagicWordFromMantarrayError
from mantarray_desktop_app import SerialCommStatusBeaconTimeoutError
from mantarray_desktop_app import SerialCommUntrackedCommandResponseError
from mantarray_desktop_app import UnrecognizedSerialCommPacketTypeError
from mantarray_desktop_app.constants import SERIAL_COMM_GOING_DORMANT_PACKET_TYPE
from mantarray_desktop_app.exceptions import SerialCommCommandProcessingError
from mantarray_desktop_app.sub_processes import mc_comm
import pytest
from src.mantarray_desktop_app.constants import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import DEFAULT_SIMULATOR_STATUS_CODES
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_patch_print,
    fixture_four_board_mc_comm_process,
    fixture_four_board_mc_comm_process_no_handshake,
]


def test_McCommunicationProcess__does_not_read_bytes_from_instrument_if_not_enough_are_in_waiting(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    spied_read = mocker.spy(simulator, "read")

    # make bytes available to read, 1 short of required amount
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": bytes(SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES - 1)},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    # make sure mc_comm does not try to read these bytes
    invoke_process_run_and_check_errors(mc_process)
    spied_read.assert_not_called()


def test_McCommunicationProcess__raises_error_if_magic_word_is_incorrect_in_packet_after_previous_magic_word_has_been_registered(
    four_board_mc_comm_process,
    mantarray_mc_simulator_no_beacon,
    patch_print,
):
    mc_process = four_board_mc_comm_process["mc_process"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    board_idx = 0
    dummy_timestamp = 0
    mc_process.set_board_connection(board_idx, simulator)
    assert mc_process.is_registered_with_serial_comm(board_idx) is False
    test_bytes_1 = create_data_packet(
        dummy_timestamp, SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, DEFAULT_SIMULATOR_STATUS_CODES
    )
    # Add arbitrary incorrect value into magic word slot
    bad_magic_word = b"NANOSURF"
    test_bytes_2 = bad_magic_word + test_bytes_1[len(SERIAL_COMM_MAGIC_WORD_BYTES) :]
    test_item = {"command": "add_read_bytes", "read_bytes": [test_bytes_1, test_bytes_2]}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_item, testing_queue)
    invoke_process_run_and_check_errors(simulator)

    with pytest.raises(SerialCommIncorrectMagicWordFromMantarrayError, match=str(bad_magic_word)):
        # First iteration registers magic word, next iteration receive incorrect magic word
        invoke_process_run_and_check_errors(mc_process, num_iterations=2)


def test_McCommunicationProcess__raises_error_if_checksum_in_data_packet_sent_from_mantarray_is_invalid(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    patch_print,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # add packet with bad checksum to be sent from simulator
    dummy_timestamp = 0
    test_bytes = create_data_packet(
        dummy_timestamp, SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, DEFAULT_SIMULATOR_STATUS_CODES
    )
    # set checksum bytes to an arbitrary incorrect value
    bad_checksum = 1234
    bad_checksum_bytes = bad_checksum.to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")
    test_bytes = test_bytes[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES] + bad_checksum_bytes
    expected_checksum = int.from_bytes(test_bytes[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:], byteorder="little")

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": test_bytes}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    with pytest.raises(SerialCommIncorrectChecksumFromInstrumentError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)

    assert str(bad_checksum) in exc_info.value.args[0]
    assert str(expected_checksum) in exc_info.value.args[0]
    assert str(list(test_bytes)) in exc_info.value.args[0]


def test_McCommunicationProcess__raises_error_if_unrecognized_packet_type_sent_from_instrument(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    dummy_timestamp = 0
    test_packet_type = 123  # arbitrary packet type, this test can fail if this packet type ever gets added
    test_packet = create_data_packet(dummy_timestamp, test_packet_type, DEFAULT_SIMULATOR_STATUS_CODES)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": test_packet}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    board_idx = 0
    mc_process.set_board_connection(board_idx, simulator)
    with pytest.raises(SerialCommCommandProcessingError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert type(exc_info.value.__cause__) == UnrecognizedSerialCommPacketTypeError
    assert str(test_packet_type) in str(exc_info.value.__cause__)


def test_McCommunicationProcess__raises_error_if_mantarray_returns_data_packet_that_it_determined_has_an_incorrect_checksum(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, patch_print
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    dummy_timestamp_bytes = bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    dummy_checksum_bytes = bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES)
    handshake_packet_length = 14
    test_handshake = SERIAL_COMM_MAGIC_WORD_BYTES
    test_handshake += handshake_packet_length.to_bytes(
        SERIAL_COMM_PACKET_REMAINDER_SIZE_LENGTH_BYTES, byteorder="little"
    )
    test_handshake += dummy_timestamp_bytes
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
    mocker.patch.object(mc_comm, "get_serial_comm_timestamp", autospec=True, return_value=expected_timestamp)

    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    spied_write = mocker.spy(simulator, "write")

    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)
    test_command = {"communication_type": "metadata_comm", "command": "get_metadata"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(copy.deepcopy(test_command), input_queue)
    # run mc_process one iteration to send the command
    invoke_process_run_and_check_errors(mc_process)

    expected_data_packet = create_data_packet(expected_timestamp, SERIAL_COMM_GET_METADATA_PACKET_TYPE)
    spied_write.assert_called_with(expected_data_packet)


def test_McCommunicationProcess__logs_message_if_write_fails(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    board_queues = four_board_mc_comm_process["board_queues"]
    input_queue, output_queue = board_queues[0][:2]

    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)
    test_command = {"communication_type": "metadata_comm", "command": "get_metadata"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(copy.deepcopy(test_command), input_queue)

    mocker.patch.object(simulator, "write", autospec=True, return_value=0)

    # run mc_process one iteration to send the command
    invoke_process_run_and_check_errors(mc_process)

    confirm_queue_is_eventually_of_size(output_queue, 1)
    assert (
        output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)["message"]
        == "Serial data write reporting no bytes written"
    )


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
        MICRO_TO_BASE_CONVERSION * SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS,
    ]
    mocker.patch.object(mc_comm, "get_serial_comm_timestamp", autospec=True, side_effect=expected_durs)
    mocker.patch.object(
        mc_comm,
        "_get_secs_since_last_handshake",
        autospec=True,
        side_effect=[0, SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS, SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS - 1, 1],
    )

    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)
    # send handshake
    invoke_process_run_and_check_errors(mc_process)
    expected_handshake_1 = create_data_packet(expected_durs[0], SERIAL_COMM_HANDSHAKE_PACKET_TYPE, bytes(0))
    assert spied_write.call_args[0][0] == expected_handshake_1
    # process handshake on simulator
    invoke_process_run_and_check_errors(simulator)
    # process handshake response
    invoke_process_run_and_check_errors(mc_process)
    # assert handshake response was read
    assert simulator.in_waiting == 0
    # repeat, 5 seconds since previous beacon
    invoke_process_run_and_check_errors(mc_process)
    expected_handshake_2 = create_data_packet(expected_durs[1], SERIAL_COMM_HANDSHAKE_PACKET_TYPE, bytes(0))
    assert spied_write.call_args[0][0] == expected_handshake_2
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    assert simulator.in_waiting == 0


def test_McCommunicationProcess__raises_error_when_receiving_going_dormant_packet_from_instrument(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    patch_print,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # have simulator send going dormant packet
    test_reason = randint(0, 255)
    test_command_response = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_GOING_DORMANT_PACKET_TYPE,
        bytes([test_reason]),
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": test_command_response},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    # make sure error is raised
    with pytest.raises(FirmwareGoingDormantError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert str(exc_info.value) == str(test_reason)


def test_McCommunicationProcess__raises_error_when_receiving_untracked_command_response_from_instrument(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    patch_print,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_timestamp_bytes = bytes(8)  # 8 arbitrary bytes in place of timestamp of command sent from PC
    # using arbitrary command packet type here
    test_command_response = create_data_packet(
        test_timestamp, SERIAL_COMM_GET_METADATA_PACKET_TYPE, test_timestamp_bytes
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": test_command_response},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    mc_process.set_board_connection(0, simulator)
    with pytest.raises(SerialCommUntrackedCommandResponseError) as exc_info:
        invoke_process_run_and_check_errors(mc_process)
    assert str(SERIAL_COMM_GET_METADATA_PACKET_TYPE) in str(exc_info.value)
    assert str(test_timestamp_bytes) in str(exc_info.value)


def test_McCommunicationProcess__raises_error_if_command_response_not_received_within_command_response_wait_period(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
    patch_print,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    board_queues = four_board_mc_comm_process_no_handshake["board_queues"]
    input_queue = board_queues[0][0]

    # patch so second iteration of mc_process will hit response timeout
    mocker.patch.object(
        mc_comm,
        "_get_secs_since_command_sent",
        autospec=True,
        side_effect=[SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS - 1, SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    expected_command = "get_metadata"
    test_command_dict = {
        "communication_type": "metadata_comm",
        "command": expected_command,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command_dict, input_queue)

    # send command but do not run simulator so command response is not sent
    invoke_process_run_and_check_errors(mc_process)
    # confirm error is raised after wait period elapses
    with pytest.raises(SerialCommCommandResponseTimeoutError, match=expected_command):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__handles_missed_beacons_correctly(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
    patch_print,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    mocker.patch.object(
        mc_comm,
        "_get_secs_since_last_beacon",
        autospec=True,
        side_effect=[SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS + 1, SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS],
    )

    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    assert to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == {
        "communication_type": "log",
        "log_level": logging.INFO,
        "message": "Status Beacon overdue. Sending handshake now to prompt a response.",
    }

    with pytest.raises(SerialCommStatusBeaconTimeoutError):
        invoke_process_run_and_check_errors(mc_process)


@pytest.mark.parametrize(
    "test_barcode,expected_valid_flag,test_description",
    [
        ("", None, "sends correct message to main when plate is removed"),
        (
            MantarrayMcSimulator.default_plate_barcode,
            True,
            "sends correct message to main when plate with valid plate barcode is placed",
        ),
        (
            MantarrayMcSimulator.default_stim_barcode,
            True,
            "sends correct message to main when plate with valid stim barcode is placed",
        ),
        (
            "M$190190001",
            False,
            "sends correct message to main when plate with invalid barcode is placed",
        ),
        (
            "M$22123199-2",
            False,
            "sends correct message to main when plate with invalid barcode is placed",
        ),
    ],
)
def test_McCommunicationProcess__handles_plate_event(
    test_barcode,
    expected_valid_flag,
    test_description,
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]

    # send plate event packet from simulator
    was_plate_placed_byte = expected_valid_flag is not None
    plate_event_packet = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_PLATE_EVENT_PACKET_TYPE,
        bytes([was_plate_placed_byte]) + bytes(test_barcode, encoding="ascii"),
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": plate_event_packet},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    # process plate event packet and send barcode comm to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    # check that comm was sent correctly
    expected_barcode_comm = {"communication_type": "barcode_comm", "board_idx": 0, "barcode": test_barcode}
    if expected_valid_flag is not None:
        expected_barcode_comm["valid"] = expected_valid_flag
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm


@pytest.mark.parametrize(
    "test_barcode,expected_valid_flag",
    [
        (MantarrayMcSimulator.default_plate_barcode, True),
        (MantarrayMcSimulator.default_stim_barcode, True),
        ("M$190190001", False),
    ],
)
def test_McCommunicationProcess__handles_barcode_found(
    test_barcode,
    expected_valid_flag,
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]

    # send plate event packet from simulator
    plate_event_packet = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE,
        bytes(test_barcode, encoding="ascii"),
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": plate_event_packet},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    # process plate event packet and send barcode comm to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    # check that comm was sent correctly
    expected_barcode_comm = {
        "communication_type": "barcode_comm",
        "board_idx": 0,
        "barcode": test_barcode,
        "valid": expected_valid_flag,
    }
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm
