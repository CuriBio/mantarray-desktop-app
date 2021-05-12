# -*- coding: utf-8 -*-
import copy
from random import randint
import time

from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import handle_data_packets
from mantarray_desktop_app import InstrumentDataStreamingAlreadyStartedError
from mantarray_desktop_app import InstrumentDataStreamingAlreadyStoppedError
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SerialCommIncorrectChecksumFromInstrumentError
import numpy as np
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import get_full_packet_size_from_packet_body_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_patch_print,
    fixture_four_board_mc_comm_process,
    fixture_four_board_mc_comm_process_no_handshake,
]

TEST_NUM_WELLS = 24
FULL_DATA_PACKET_LEN = get_full_packet_size_from_packet_body_size(
    (SERIAL_COMM_NUM_DATA_CHANNELS * TEST_NUM_WELLS * 2) + 2
)

TEST_OTHER_TIMESTAMP = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
TEST_OTHER_PACKET = create_data_packet(
    TEST_OTHER_TIMESTAMP,
    SERIAL_COMM_MAIN_MODULE_ID,
    SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
    bytes(4),
)
TEST_OTHER_PACKET_INFO = (
    TEST_OTHER_TIMESTAMP,
    SERIAL_COMM_MAIN_MODULE_ID,
    SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
    bytes(4),
)


def test_handle_data_packets__handles_two_full_data_packets_correctly():
    test_num_data_packets = 2
    num_data_points_per_packet = SERIAL_COMM_NUM_DATA_CHANNELS * TEST_NUM_WELLS

    expected_packet_timestamps = np.array([5, 6], dtype=np.uint64)
    expected_timestamp_offsets = np.array([2, 1], dtype=np.uint64)
    expected_data_timestamps = expected_packet_timestamps - expected_timestamp_offsets

    expected_data_array = np.zeros((num_data_points_per_packet, test_num_data_packets), dtype=np.int16)
    test_data_packets = bytes(0)
    for packet_num in range(test_num_data_packets):
        test_data = [randint(-0x8000, 0x7FFF) for _ in range(SERIAL_COMM_NUM_DATA_CHANNELS * TEST_NUM_WELLS)]
        expected_data_array[:, packet_num] = test_data

        test_bytes = expected_timestamp_offsets[packet_num].item().to_bytes(2, byteorder="little")
        for value in test_data:
            test_bytes += value.to_bytes(2, byteorder="little", signed=True)
        test_data_packets += create_data_packet(
            expected_packet_timestamps[packet_num].item(),
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
            test_bytes,
        )

    (
        actual_timestamps,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_data_packets), FULL_DATA_PACKET_LEN)

    assert actual_timestamps.shape[0] == test_num_data_packets
    np.testing.assert_array_equal(actual_timestamps, expected_data_timestamps)
    assert actual_data.shape[1] == test_num_data_packets
    np.testing.assert_array_equal(actual_data, expected_data_array)
    assert num_data_packets_read == test_num_data_packets
    assert other_packet_info is None
    assert unread_bytes == bytes(0)


def test_handle_data_packets__handles_single_packet_with_incorrect_packet_type_correctly__when_all_channels_enabled():
    (
        actual_timestamps,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(TEST_OTHER_PACKET), FULL_DATA_PACKET_LEN)

    assert actual_timestamps.shape[0] == 0
    assert actual_data.shape[1] == 0
    assert num_data_packets_read == 0
    assert other_packet_info == TEST_OTHER_PACKET_INFO
    assert unread_bytes == bytes(0)


def test_handle_data_packets__handles_single_packet_with_incorrect_module_id_correctly__when_all_channels_enabled():
    test_body_length = randint(0, 10)
    expected_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_data_packet = create_data_packet(
        expected_timestamp,
        255,  # arbitrary module ID, preferably one that doesn't exist
        SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
        bytes(test_body_length),
    )

    (
        actual_timestamps,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_data_packet), FULL_DATA_PACKET_LEN)

    assert actual_timestamps.shape[0] == 0
    assert actual_data.shape[1] == 0
    assert num_data_packets_read == 0
    assert other_packet_info == (
        expected_timestamp,
        255,
        SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
        bytes(test_body_length),
    )
    assert unread_bytes == bytes(0)


def test_handle_data_packets__handles_interrupting_packet_followed_by_data_packet__when_all_channels_enabled():
    data_bytes = bytes(2)
    for _ in range(SERIAL_COMM_NUM_DATA_CHANNELS * TEST_NUM_WELLS):
        data_bytes += randint(-0x8000, 0x7FFF).to_bytes(2, byteorder="little", signed=True)
    expected_unread_bytes = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE),
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
        data_bytes,
    )
    test_bytes = TEST_OTHER_PACKET + expected_unread_bytes

    (
        actual_timestamps,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_bytes), FULL_DATA_PACKET_LEN)

    assert actual_timestamps.shape[0] == 1
    assert actual_data.shape[1] == 1
    assert num_data_packets_read == 0
    assert other_packet_info == TEST_OTHER_PACKET_INFO
    assert unread_bytes == expected_unread_bytes


def test_handle_data_packets__handles_single_data_packet_followed_by_interrupting_packet__when_all_channels_enabled():
    data_bytes = bytes(2)
    expected_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    for _ in range(SERIAL_COMM_NUM_DATA_CHANNELS * TEST_NUM_WELLS):
        data_bytes += randint(-0x8000, 0x7FFF).to_bytes(2, byteorder="little", signed=True)
    test_data_packet = create_data_packet(
        expected_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
        data_bytes,
    )
    test_bytes = test_data_packet + TEST_OTHER_PACKET

    (
        actual_timestamps,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_bytes), FULL_DATA_PACKET_LEN)

    assert actual_timestamps.shape[0] == 1
    assert actual_timestamps[0] == expected_timestamp
    assert actual_data.shape[1] == 1
    assert num_data_packets_read == 1
    assert other_packet_info == TEST_OTHER_PACKET_INFO
    assert unread_bytes == bytes(0)


def test_handle_data_packets__handles_single_data_packet_followed_by_incomplete_packet__when_all_channels_enabled():
    data_bytes = bytes(2)
    expected_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    for _ in range(SERIAL_COMM_NUM_DATA_CHANNELS * TEST_NUM_WELLS):
        data_bytes += randint(-0x8000, 0x7FFF).to_bytes(2, byteorder="little", signed=True)
    test_data_packet = create_data_packet(
        expected_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
        data_bytes,
    )
    test_incomplete_packet = bytes(SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES - 1)
    test_bytes = test_data_packet + test_incomplete_packet

    (
        actual_timestamps,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_bytes), FULL_DATA_PACKET_LEN)

    assert actual_timestamps.shape[0] == 1
    assert actual_timestamps[0] == expected_timestamp
    assert actual_data.shape[1] == 1
    assert num_data_packets_read == 1
    assert other_packet_info is None
    assert unread_bytes == test_incomplete_packet


def test_handle_data_packets__handles_interrupting_packet_in_between_two_data_packets__when_all_channels_enabled():
    test_num_data_packets = 2

    expected_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)

    test_data_packets = []
    for _ in range(test_num_data_packets):
        data_bytes = bytes(2)
        for _ in range(SERIAL_COMM_NUM_DATA_CHANNELS * TEST_NUM_WELLS):
            data_bytes += randint(-0x8000, 0x7FFF).to_bytes(2, byteorder="little", signed=True)
        test_data_packet = create_data_packet(
            expected_timestamp,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
            data_bytes,
        )
        test_data_packets.append(test_data_packet)
    test_bytes = test_data_packets[0] + TEST_OTHER_PACKET + test_data_packets[1]

    (
        actual_timestamps,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_bytes), FULL_DATA_PACKET_LEN)

    assert actual_timestamps.shape[0] == 2
    assert actual_timestamps[0] == expected_timestamp
    assert actual_data.shape[1] == 2
    assert num_data_packets_read == 1
    assert other_packet_info == TEST_OTHER_PACKET_INFO
    assert unread_bytes == test_data_packets[1]


def test_handle_data_packets__raises_error_when_packet_from_instrument_has_incorrect_crc32_checksum(
    patch_print,
):
    bad_checksum = 0
    bad_checksum_bytes = bad_checksum.to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")
    bad_packet = TEST_OTHER_PACKET[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES] + bad_checksum_bytes
    with pytest.raises(SerialCommIncorrectChecksumFromInstrumentError) as exc_info:
        handle_data_packets(bytearray(bad_packet), FULL_DATA_PACKET_LEN)

    expected_checksum = int.from_bytes(bad_packet[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:], byteorder="little")
    assert str(bad_checksum) in exc_info.value.args[0]
    assert str(expected_checksum) in exc_info.value.args[0]
    assert str(bytearray(bad_packet)) in exc_info.value.args[0]


def test_handle_data_packets__performance_test():
    # One second of data, max sampling rate, all data channels on
    # start:                            1391397

    test_num_data_packets = 1000  # one second of data at max sampling frequency
    num_data_points_per_packet = SERIAL_COMM_NUM_DATA_CHANNELS * TEST_NUM_WELLS

    expected_data_array = np.zeros((num_data_points_per_packet, test_num_data_packets), dtype=np.int16)
    test_data_packets = bytes(0)
    for packet_num in range(test_num_data_packets):
        test_data = [randint(-0x8000, 0x7FFF) for _ in range(SERIAL_COMM_NUM_DATA_CHANNELS * TEST_NUM_WELLS)]
        expected_data_array[:, packet_num] = test_data

        test_bytes = bytes(2)
        for value in test_data:
            test_bytes += value.to_bytes(2, byteorder="little", signed=True)
        test_data_packets += create_data_packet(
            packet_num,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
            test_bytes,
        )

    start = time.perf_counter_ns()
    (
        actual_timestamps,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_data_packets), FULL_DATA_PACKET_LEN)
    dur = time.perf_counter_ns() - start
    # print(f"Dur (ns): {dur}, (seconds): {dur / 10 ** 9}") # pylint:disable=wrong-spelling-in-comment # Tanner (5/11/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization

    assert dur < 1000000000
    # good to also assert the entire second of data was parsed correctly
    assert actual_timestamps.shape[0] == test_num_data_packets
    np.testing.assert_array_equal(actual_timestamps, list(range(test_num_data_packets)))
    assert actual_data.shape[1] == test_num_data_packets
    np.testing.assert_array_equal(actual_data, expected_data_array)
    assert num_data_packets_read == test_num_data_packets
    assert other_packet_info is None
    assert unread_bytes == bytes(0)


def test_McCommunicationProcess__processes_start_managed_acquisition_command__when_data_not_already_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # set arbitrary sampling period
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_sampling_period", "sampling_period": 60000}, testing_queue
    )

    spied_get_utc_now = mocker.spy(mc_comm, "_get_formatted_utc_now")

    expected_response = {
        "communication_type": "to_instrument",
        "command": "start_managed_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    # run mc_process one iteration to send start command
    invoke_process_run_and_check_errors(mc_process)
    # run mc_simulator once to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # run mc_process one more iteration to process command response and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_response["magnetometer_config"] = simulator.get_magnetometer_config()
    expected_response["timestamp"] = spied_get_utc_now.spy_return
    assert command_response == expected_response


def test_McCommunicationProcess__processes_start_managed_acquisition_command__and_raises_error_when_already_streaming(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    patch_print,
    mocker,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # put simulator in data streaming mode
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_data_streaming_status", "data_streaming_status": True},
        testing_queue,
    )

    expected_response = {
        "communication_type": "to_instrument",
        "command": "start_managed_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    # run mc_process one iteration to send start command
    invoke_process_run_and_check_errors(mc_process)
    # run mc_simulator once to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # run mc_process to check command response and raise error
    with pytest.raises(InstrumentDataStreamingAlreadyStartedError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__processes_stop_data_streaming_command__when_data_is_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # put simulator in data streaming mode
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_data_streaming_status", "data_streaming_status": True},
        testing_queue,
    )

    expected_response = {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    # run mc_process one iteration to send start command
    invoke_process_run_and_check_errors(mc_process)
    # run mc_simulator once to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # run mc_process one more iteration to process command response and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == expected_response


def test_McCommunicationProcess__processes_stpo_data_streaming_command__and_raises_error_when_not_streaming(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    patch_print,
    mocker,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    expected_response = {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    # run mc_process one iteration to send start command
    invoke_process_run_and_check_errors(mc_process)
    # run mc_simulator once to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # run mc_process to check command response and raise error
    with pytest.raises(InstrumentDataStreamingAlreadyStoppedError):
        invoke_process_run_and_check_errors(mc_process)
