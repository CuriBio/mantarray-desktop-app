# -*- coding: utf-8 -*-
import copy
import datetime
from random import randint
from statistics import stdev
import time

from freezegun import freeze_time
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app import handle_data_packets
from mantarray_desktop_app import INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
from mantarray_desktop_app import InstrumentDataStreamingAlreadyStartedError
from mantarray_desktop_app import InstrumentDataStreamingAlreadyStoppedError
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import NUM_INITIAL_PACKETS_TO_DROP
from mantarray_desktop_app import SamplingPeriodUpdateWhileDataStreamingError
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from mantarray_desktop_app import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app import SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from mantarray_desktop_app import SerialCommIncorrectChecksumFromInstrumentError
from mantarray_desktop_app import SerialCommIncorrectMagicWordFromMantarrayError
from mantarray_desktop_app.constants import STOP_MANAGED_ACQUISITION_COMMUNICATION
import numpy as np
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_comm import set_sampling_period_and_start_streaming
from ..fixtures_mc_comm import start_data_stream
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import random_data_value
from ..fixtures_mc_simulator import random_time_index
from ..fixtures_mc_simulator import random_time_offset
from ..fixtures_mc_simulator import random_timestamp
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_patch_print,
    fixture_four_board_mc_comm_process_no_handshake,
]


TEST_NUM_WELLS = 24

TEST_OTHER_TIMESTAMP = random_timestamp()  # type: ignore
TEST_OTHER_PACKET = create_data_packet(TEST_OTHER_TIMESTAMP, SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, bytes(4))
TEST_OTHER_PACKET_INFO = (TEST_OTHER_TIMESTAMP, SERIAL_COMM_STATUS_BEACON_PACKET_TYPE, bytes(4))


def create_data_stream_body(
    time_index_us,
    num_wells_on_plate=24,
):
    data_packet_payload = time_index_us.to_bytes(SERIAL_COMM_TIME_INDEX_LENGTH_BYTES, byteorder="little")
    data_values = []
    offset_values = []
    for _ in range(1, num_wells_on_plate + 1):
        for _ in range(0, SERIAL_COMM_NUM_DATA_CHANNELS, SERIAL_COMM_NUM_SENSORS_PER_WELL):
            # create and add offset value
            offset = random_time_offset()
            offset_values.append(offset)
            data_packet_payload += offset.to_bytes(SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES, byteorder="little")
            # create data point
            data_value = random_data_value()
            data_value_bytes = data_value.to_bytes(2, byteorder="little")
            for _ in range(SERIAL_COMM_NUM_CHANNELS_PER_SENSOR):
                # add data points
                data_values.append(data_value)
                data_packet_payload += data_value_bytes
    return data_packet_payload, offset_values, data_values


def test_handle_data_packets__handles_two_full_data_packets_correctly__and_assigns_correct_data_type_to_parsed_values__when_all_channels_enabled():
    test_num_data_packets = 2
    expected_time_indices = [0xFFFFFFFFFFFFFF00, 0xFFFFFFFFFFFFFF01]

    base_global_time = randint(0, 100)

    test_data_packet_bytes = bytes(0)
    expected_data_points = []
    expected_time_offsets = []
    for packet_num in range(test_num_data_packets):
        data_packet_payload, test_offsets, test_data = create_data_stream_body(
            expected_time_indices[packet_num] + base_global_time
        )
        test_data_packet_bytes += create_data_packet(
            random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
        )
        expected_data_points.extend(test_data)
        expected_time_offsets.extend(test_offsets)
    expected_time_offsets = np.array(expected_time_offsets).reshape(
        (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
    )
    expected_data_points = np.array(expected_data_points).reshape(
        (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
    )

    parsed_data_dict = handle_data_packets(bytearray(test_data_packet_bytes), base_global_time)
    actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
        "magnetometer_data"
    ].values()

    assert actual_time_indices.dtype == np.uint64
    assert actual_time_offsets.dtype == np.uint16
    assert actual_data.dtype == np.uint16
    np.testing.assert_array_equal(actual_time_indices, expected_time_indices)
    np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
    np.testing.assert_array_equal(actual_data, expected_data_points)
    assert num_data_packets_read == test_num_data_packets
    assert parsed_data_dict["other_packet_info"] == []
    assert parsed_data_dict["unread_bytes"] == bytes(0)


def test_handle_data_packets__handles_single_packet_with_incorrect_packet_type_correctly__when_all_channels_enabled():
    parsed_data_dict = handle_data_packets(bytearray(TEST_OTHER_PACKET), 0)
    actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
        "magnetometer_data"
    ].values()

    assert actual_time_indices.shape[0] == 0
    assert actual_time_offsets.shape[1] == 0
    assert actual_data.shape[1] == 0
    assert num_data_packets_read == 0
    assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO]
    assert parsed_data_dict["unread_bytes"] == bytes(0)


def test_handle_data_packets__handles_interrupting_packet_followed_by_data_packet__when_all_channels_enabled():
    expected_time_index = random_time_index()
    data_packet_payload, expected_time_offsets, expected_data_points = create_data_stream_body(
        expected_time_index
    )
    test_bytes = TEST_OTHER_PACKET + create_data_packet(
        random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
    )

    parsed_data_dict = handle_data_packets(bytearray(test_bytes), 0)
    actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
        "magnetometer_data"
    ].values()

    np.testing.assert_array_equal(actual_time_indices, expected_time_index)
    np.testing.assert_array_equal(actual_time_offsets.flatten(), expected_time_offsets)
    np.testing.assert_array_equal(actual_data.flatten(), expected_data_points)
    assert num_data_packets_read == 1
    assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO]
    assert parsed_data_dict["unread_bytes"] == bytes(0)


def test_handle_data_packets__handles_single_data_packet_followed_by_interrupting_packet__when_all_channels_enabled():
    expected_time_index = random_time_index()
    data_packet_payload, _, _ = create_data_stream_body(expected_time_index)
    test_data_packet = create_data_packet(
        random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
    )
    test_bytes = test_data_packet + TEST_OTHER_PACKET

    parsed_data_dict = handle_data_packets(bytearray(test_bytes), 0)
    actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
        "magnetometer_data"
    ].values()

    assert actual_time_indices.shape[0] == 1
    assert actual_time_offsets.shape[1] == 1
    assert actual_data.shape[1] == 1
    assert actual_time_indices[0] == expected_time_index
    assert num_data_packets_read == 1
    assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO]
    assert parsed_data_dict["unread_bytes"] == bytes(0)


def test_handle_data_packets__handles_single_data_packet_followed_by_incomplete_packet__when_all_channels_enabled():
    expected_time_index = random_time_index()
    data_packet_payload, _, _ = create_data_stream_body(expected_time_index)
    test_data_packet = create_data_packet(
        random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
    )
    test_incomplete_packet = bytes(SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES - 1)
    test_bytes = test_data_packet + test_incomplete_packet

    parsed_data_dict = handle_data_packets(bytearray(test_bytes), 0)
    actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
        "magnetometer_data"
    ].values()

    assert actual_time_indices.shape[0] == 1
    assert actual_time_offsets.shape[1] == 1
    assert actual_data.shape[1] == 1
    assert actual_time_indices[0] == expected_time_index
    assert num_data_packets_read == 1
    assert parsed_data_dict["other_packet_info"] == []
    assert parsed_data_dict["unread_bytes"] == test_incomplete_packet


def test_handle_data_packets__handles_interrupting_packet_in_between_two_data_packets__when_all_channels_enabled():
    test_num_data_packets = 2

    expected_time_indices = []
    expected_time_offsets = []
    expected_data_points = []
    test_data_packets = []
    for _ in range(test_num_data_packets):
        time_index = random_time_index()
        expected_time_indices.append(time_index)

        data_packet_payload, test_offsets, test_data = create_data_stream_body(time_index)
        test_data_packet = create_data_packet(
            random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
        )
        test_data_packets.append(test_data_packet)
        expected_time_offsets.extend(test_offsets)
        expected_data_points.extend(test_data)
    test_bytes = test_data_packets[0] + TEST_OTHER_PACKET + test_data_packets[1]

    parsed_data_dict = handle_data_packets(bytearray(test_bytes), 0)
    actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
        "magnetometer_data"
    ].values()

    expected_time_offsets = np.array(expected_time_offsets).reshape(
        (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
    )
    expected_data_points = np.array(expected_data_points).reshape(
        (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
    )

    np.testing.assert_array_equal(actual_time_indices, expected_time_indices)
    np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
    np.testing.assert_array_equal(actual_data, expected_data_points)
    assert num_data_packets_read == 2
    assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO]
    assert parsed_data_dict["unread_bytes"] == bytes(0)


def test_handle_data_packets__handles_two_interrupting_packets_in_between_two_data_packets__when_all_channels_enabled():
    test_num_data_packets = 2

    expected_time_indices = []
    expected_time_offsets = []
    expected_data_points = []
    test_data_packets = []
    for _ in range(test_num_data_packets):
        time_index = random_time_index()
        expected_time_indices.append(time_index)

        data_packet_payload, test_offsets, test_data = create_data_stream_body(time_index)
        test_data_packet = create_data_packet(
            random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
        )
        test_data_packets.append(test_data_packet)
        expected_time_offsets.extend(test_offsets)
        expected_data_points.extend(test_data)
    test_bytes = test_data_packets[0] + TEST_OTHER_PACKET + TEST_OTHER_PACKET + test_data_packets[1]

    parsed_data_dict = handle_data_packets(bytearray(test_bytes), 0)
    actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
        "magnetometer_data"
    ].values()

    expected_time_offsets = np.array(expected_time_offsets).reshape(
        (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
    )
    expected_data_points = np.array(expected_data_points).reshape(
        (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
    )

    np.testing.assert_array_equal(actual_time_indices, expected_time_indices)
    np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
    np.testing.assert_array_equal(actual_data, expected_data_points)
    assert num_data_packets_read == 2
    assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO, TEST_OTHER_PACKET_INFO]
    assert parsed_data_dict["unread_bytes"] == bytes(0)


def test_handle_data_packets__raises_error_when_packet_from_instrument_has_incorrect_magic_word(
    patch_print,
):
    bad_magic_word_bytes = b"NOT CURI"
    bad_packet = bad_magic_word_bytes + TEST_OTHER_PACKET[len(SERIAL_COMM_MAGIC_WORD_BYTES) :]
    with pytest.raises(SerialCommIncorrectMagicWordFromMantarrayError, match=str(bad_magic_word_bytes)):
        handle_data_packets(bytearray(bad_packet), 0)


def test_handle_data_packets__raises_error_when_packet_from_instrument_has_incorrect_crc32_checksum(
    patch_print,
):
    bad_checksum = 0
    bad_checksum_bytes = bad_checksum.to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")
    bad_packet = TEST_OTHER_PACKET[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES] + bad_checksum_bytes
    with pytest.raises(SerialCommIncorrectChecksumFromInstrumentError) as exc_info:
        handle_data_packets(bytearray(bad_packet), 0)

    expected_checksum = int.from_bytes(bad_packet[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:], byteorder="little")
    assert str(bad_checksum) in exc_info.value.args[0]
    assert str(expected_checksum) in exc_info.value.args[0]
    assert str(bytearray(bad_packet)) in exc_info.value.args[0]


def test_handle_data_packets__does_not_parse_final_packet_if_it_is_not_complete():
    test_num_data_packets = 1
    expected_time_index = 10000

    base_global_time = randint(0, 100)

    data_packet_payload, expected_time_offsets, expected_data_points = create_data_stream_body(
        expected_time_index + base_global_time
    )
    full_packet = create_data_packet(  # add one full packet
        random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
    )
    incomplete_packet = create_data_packet(  # add one incomplete packet with arbitrary data
        random_timestamp(), SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE, bytes(10)
    )[:-1]
    test_data_packet_bytes = full_packet + incomplete_packet

    parsed_data_dict = handle_data_packets(bytearray(test_data_packet_bytes), base_global_time)
    actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
        "magnetometer_data"
    ].values()

    expected_time_offsets = np.array(expected_time_offsets).reshape(
        (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
    )
    expected_data_points = np.array(expected_data_points).reshape(
        (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
    )

    np.testing.assert_array_equal(actual_time_indices, expected_time_index)
    np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
    np.testing.assert_array_equal(actual_data, expected_data_points)
    assert num_data_packets_read == test_num_data_packets
    assert parsed_data_dict["other_packet_info"] == []
    assert parsed_data_dict["unread_bytes"] == incomplete_packet


def test_handle_data_packets__performance_test__magnetometer_data_only():
    # One second of data, max sampling rate, all data channels on
    # start:                                        1397497
    # added time offsets + memory views:            2190868
    # refactor before adding stim:                  3164056

    num_us_of_data_to_send = MICRO_TO_BASE_CONVERSION
    max_sampling_rate_us = 1000
    test_num_data_packets = num_us_of_data_to_send // max_sampling_rate_us
    expected_time_indices = list(range(0, num_us_of_data_to_send, max_sampling_rate_us))

    test_data_packet_bytes = bytes(0)
    expected_data_points = []
    expected_time_offsets = []
    for packet_num in range(test_num_data_packets):
        data_packet_payload, test_offsets, test_data = create_data_stream_body(
            expected_time_indices[packet_num]
        )
        test_data_packet_bytes += create_data_packet(
            random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
        )
        expected_data_points.extend(test_data)
        expected_time_offsets.extend(test_offsets)
    expected_time_offsets = np.array(expected_time_offsets).reshape(
        (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
    )
    expected_data_points = np.array(expected_data_points).reshape(
        (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
    )

    start = time.perf_counter_ns()
    parsed_data_dict = handle_data_packets(bytearray(test_data_packet_bytes), 0)
    actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
        "magnetometer_data"
    ].values()
    dur = time.perf_counter_ns() - start
    # print(f"Dur (ns): {dur}, (seconds): {dur / 1e9}")  # pylint:disable=wrong-spelling-in-comment # Tanner (5/11/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization

    assert dur < 1000000000
    # good to also assert the entire second of data was parsed correctly
    np.testing.assert_array_equal(
        actual_time_indices, list(range(0, num_us_of_data_to_send, max_sampling_rate_us))
    )
    np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
    np.testing.assert_array_equal(actual_data, expected_data_points)
    assert num_data_packets_read == test_num_data_packets
    assert parsed_data_dict["other_packet_info"] == []
    assert parsed_data_dict["unread_bytes"] == bytes(0)


@freeze_time(datetime.datetime(year=2021, month=10, day=24, hour=13, minute=5, second=23, microsecond=173814))
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

    # set arbitrary sampling period
    expected_sampling_period = 60000
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_sampling_period", "sampling_period": expected_sampling_period}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    expected_response = {"communication_type": "acquisition_manager", "command": "start_managed_acquisition"}
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
    expected_response["timestamp"] = datetime.datetime(
        year=2021, month=10, day=24, hour=13, minute=5, second=23, microsecond=173814
    )
    assert command_response == expected_response


def test_McCommunicationProcess__raises_error_when_set_sampling_period_command_received_while_data_is_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_sampling_period", "sampling_period": 5000}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # start data streaming
    start_command = {"communication_type": "acquisition_manager", "command": "start_managed_acquisition"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # attempt to change magnetometer configuration and assert error is raised
    change_config_command = {
        "communication_type": "acquisition_manager",
        "command": "set_sampling_period",
        "sampling_period": 65000,  # arbitrary value
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(change_config_command, from_main_queue)
    with pytest.raises(SamplingPeriodUpdateWhileDataStreamingError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__processes_start_managed_acquisition_command__and_raises_error_when_already_streaming(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    patch_print,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # put simulator in data streaming mode
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_data_streaming_status", "data_streaming_status": True},
        testing_queue,
    )

    expected_response = {"communication_type": "acquisition_manager", "command": "start_managed_acquisition"}
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

    # put simulator in data streaming mode
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_data_streaming_status", "data_streaming_status": True},
        testing_queue,
    )

    expected_response = {"communication_type": "acquisition_manager", "command": "stop_managed_acquisition"}
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


def test_McCommunicationProcess__processes_stop_data_streaming_command__and_raises_error_when_not_streaming(
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

    expected_response = {"communication_type": "acquisition_manager", "command": "stop_managed_acquisition"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    # run mc_process one iteration to send start command
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # run mc_process to check command response and raise error
    with pytest.raises(InstrumentDataStreamingAlreadyStoppedError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__reads_all_bytes_from_instrument__and_does_not_parse_bytes_if_not_enough_are_present(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_sampling_period_us = 25000  # arbitrary value
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )

    # mocking in order to produce incomplete data packet
    mocker.patch.object(
        mc_simulator,
        "create_data_packet",
        autospec=True,
        return_value=bytes(SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES - 1),
    )
    spied_handle = mocker.spy(mc_comm, "handle_data_packets")
    spied_read_all = mocker.spy(simulator, "read_all")

    # send data
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES - 1
    # read data
    invoke_process_run_and_check_errors(mc_process)
    spied_read_all.assert_called_once()
    spied_handle.assert_not_called()
    confirm_queue_is_eventually_empty(to_fw_queue)


def test_McCommunicationProcess__correctly_indicates_which_packet_is_the_first_of_the_stream(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_num_packets = 100
    test_sampling_period_us = int(1e6 // test_num_packets)
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[
            0,
            test_sampling_period_us * test_num_packets,
            test_sampling_period_us * test_num_packets,
        ],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )

    for read_num in range(2):
        invoke_process_run_and_check_errors(simulator)
        invoke_process_run_and_check_errors(mc_process)
        confirm_queue_is_eventually_of_size(to_fw_queue, 1)
        actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert actual_fw_item["is_first_packet_of_stream"] is not bool(read_num)


def test_McCommunicationProcess__handles_read_of_only_data_packets__and_sends_data_to_file_writer_correctly__when_one_second_of_data_with_all_channels_enabled_is_present(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_num_wells = 24
    test_num_packets = 100
    expected_num_packets = test_num_packets - NUM_INITIAL_PACKETS_TO_DROP
    test_sampling_period_us = DEFAULT_SAMPLING_PERIOD
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us * test_num_packets],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    start_data_stream(four_board_mc_comm_process_no_handshake, simulator)

    min_time_idx_us = test_sampling_period_us * NUM_INITIAL_PACKETS_TO_DROP
    max_time_idx_us = test_sampling_period_us * test_num_packets
    expected_time_indices = list(range(min_time_idx_us, max_time_idx_us, test_sampling_period_us))

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)[NUM_INITIAL_PACKETS_TO_DROP:]
    expected_fw_item = {
        "data_type": "mangetometer",
        "time_indices": np.array(expected_time_indices, np.uint64),
    }
    for well_idx in range(test_num_wells):
        channel_dict = {
            "time_offsets": np.zeros(
                (SERIAL_COMM_NUM_SENSORS_PER_WELL, expected_num_packets), dtype=np.uint16
            ),
        }
        for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
            channel_dict[channel_id] = simulated_data * np.uint16(well_idx + 1)
        expected_fw_item[well_idx] = channel_dict
    # not actually using the value here in any assertions, just need the key present
    expected_fw_item["is_first_packet_of_stream"] = None

    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_fw_item.keys() == expected_fw_item.keys()
    np.testing.assert_array_equal(actual_fw_item["time_indices"], expected_fw_item["time_indices"])
    for key, expected_item in expected_fw_item.items():
        if key in ("data_type", "is_first_packet_of_stream", "time_indices"):
            continue
        actual_item = actual_fw_item[key]
        assert actual_item.keys() == expected_item.keys()  # pylint: disable=no-member
        for sub_key, expected_data in expected_item.items():  # pylint: disable=no-member
            actual_data = actual_item[sub_key]
            expected_dtype = np.uint16
            assert actual_data.dtype == expected_dtype
            np.testing.assert_array_equal(
                actual_data, expected_data, err_msg=f"Failure at key '{key}', sub key '{sub_key}'"
            )


def test_McCommunicationProcess__handles_read_of_only_data_packets__and_sends_data_to_file_writer_correctly__when_one_second_of_data_is_present(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    # pylint: disable=too-many-locals  # Tanner (5/27/21): a lot of locals variables needed for this test
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_sampling_period_us = 10000  # specifically chosen so that there are 100 data packets in one second
    test_num_packets = int(1e6 // test_sampling_period_us)
    expected_num_packets = test_num_packets - NUM_INITIAL_PACKETS_TO_DROP
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us * test_num_packets],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )

    min_time_idx_us = test_sampling_period_us * NUM_INITIAL_PACKETS_TO_DROP
    max_time_idx_us = test_sampling_period_us * test_num_packets
    expected_time_indices = list(range(min_time_idx_us, max_time_idx_us, test_sampling_period_us))

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)[NUM_INITIAL_PACKETS_TO_DROP:]
    expected_fw_item = {
        "data_type": "mangetometer",
        "time_indices": np.array(expected_time_indices, np.uint64),
    }
    for well_idx in range(24):
        channel_dict = {
            "time_offsets": np.zeros(
                (SERIAL_COMM_NUM_SENSORS_PER_WELL, expected_num_packets), dtype=np.uint16
            )
        }
        for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
            channel_dict[channel_id] = simulated_data * np.uint16(well_idx + 1)
        expected_fw_item[well_idx] = channel_dict
    # not actually using the value here in any assertions, just need the key present
    expected_fw_item["is_first_packet_of_stream"] = None

    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_fw_item.keys() == expected_fw_item.keys()
    np.testing.assert_array_equal(actual_fw_item["time_indices"], expected_fw_item["time_indices"])
    for key, expected_item in expected_fw_item.items():
        if key in ("data_type", "is_first_packet_of_stream", "time_indices"):
            continue
        actual_item = actual_fw_item[key]
        assert actual_item.keys() == expected_item.keys()  # pylint: disable=no-member
        for sub_key, expected_data in expected_item.items():  # pylint: disable=no-member
            actual_data = actual_item[sub_key]
            np.testing.assert_array_equal(
                actual_data, expected_data, err_msg=f"Failure at '{key}' key, sub key '{sub_key}'"
            )


def test_McCommunicationProcess__handles_one_second_read_with_two_interrupting_packets_correctly(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    # pylint: disable=too-many-locals  # Tanner (5/13/21): a lot of local variables needed for this test
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_sampling_period_us = 10000  # specifically chosen so that there are 100 data packets in one second
    test_num_packets = int(1.5e6 // test_sampling_period_us)
    expected_num_packets = test_num_packets - NUM_INITIAL_PACKETS_TO_DROP
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us * test_num_packets, 0],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )

    min_time_idx_us = test_sampling_period_us * NUM_INITIAL_PACKETS_TO_DROP
    max_time_idx_us = test_sampling_period_us * test_num_packets
    expected_time_indices = list(range(min_time_idx_us, max_time_idx_us, test_sampling_period_us))

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)
    expected_sensor_axis_id = 0
    expected_fw_item = {
        "data_type": "mangetometer",
        "time_indices": np.array(expected_time_indices, np.uint64),
    }
    for module_id in range(1, 25):
        well_idx = SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id]
        channel_data = np.concatenate(
            (simulated_data[NUM_INITIAL_PACKETS_TO_DROP:], simulated_data[: test_num_packets // 3])
        )
        channel_dict = {
            "time_offsets": np.zeros(
                (SERIAL_COMM_NUM_SENSORS_PER_WELL, expected_num_packets), dtype=np.uint16
            ),
            expected_sensor_axis_id: channel_data * np.uint16(well_idx + 1),
        }
        expected_fw_item[well_idx] = channel_dict
    # not actually using the value here in any assertions, just need the key present
    expected_fw_item["is_first_packet_of_stream"] = None

    # insert one status beacon at beginning of data and on after 1/3 of data
    invoke_process_run_and_check_errors(simulator)
    read_bytes = simulator.read_all()
    read_bytes = (
        TEST_OTHER_PACKET
        + read_bytes[: len(read_bytes) // 3]
        + TEST_OTHER_PACKET
        + read_bytes[len(read_bytes) // 3 :]
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": read_bytes}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # parse all data and make sure outgoing queues are populated
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 2)
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    # test message to main from interrupting packets
    for beacon_num in range(2):
        actual_beacon_log_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        expected_status_code = int.from_bytes(TEST_OTHER_PACKET_INFO[-1], byteorder="little")
        assert str(expected_status_code) in actual_beacon_log_msg["message"], beacon_num
    # test data packets going to file_writer
    actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_fw_item.keys() == expected_fw_item.keys()

    np.testing.assert_array_equal(actual_fw_item["time_indices"], expected_fw_item["time_indices"])

    for key, expected_item in expected_fw_item.items():
        if key in ("data_type", "is_first_packet_of_stream", "time_indices"):
            continue
        actual_time_offsets = actual_fw_item[key]["time_offsets"]
        actual_data = actual_fw_item[key][expected_sensor_axis_id]
        np.testing.assert_array_equal(
            actual_time_offsets,
            expected_item["time_offsets"],
            err_msg=f"Failure at '{key}' key",
        )
        np.testing.assert_array_equal(
            actual_data,
            expected_item[expected_sensor_axis_id],
            err_msg=f"Failure at at '{key}' key",
        )


def test_McCommunicationProcess__handles_less_than_one_second_read_when_stopping_data_stream(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    # pylint: disable=too-many-locals  # Tanner (5/27/21): a lot of locals variables needed for this test
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_sampling_period_us = 10000  # specifically chosen so that there are 100 data packets in one second
    test_num_packets = int(0.5e6 // test_sampling_period_us)  # only send half a second of data
    expected_num_packets = test_num_packets - 2
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us * test_num_packets],
    )
    # mock so barcode isn't sent after streaming stops
    mocker.patch.object(simulator, "_handle_barcode", autospec=True)

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )
    invoke_process_run_and_check_errors(simulator)

    min_time_idx_us = test_sampling_period_us * NUM_INITIAL_PACKETS_TO_DROP
    max_time_idx_us = test_sampling_period_us * test_num_packets
    expected_time_indices = list(range(min_time_idx_us, max_time_idx_us, test_sampling_period_us))

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)[NUM_INITIAL_PACKETS_TO_DROP:]
    expected_sensor_axis_id = 0
    expected_fw_item = {
        "data_type": "mangetometer",
        "time_indices": np.array(expected_time_indices, np.uint64),
    }
    for module_id in range(1, 25):
        well_idx = SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id]
        channel_dict = {
            "time_offsets": np.zeros(
                (SERIAL_COMM_NUM_CHANNELS_PER_SENSOR, expected_num_packets), dtype=np.uint16
            ),
            expected_sensor_axis_id: simulated_data[:expected_num_packets] * np.uint16(well_idx + 1),
        }
        expected_fw_item[well_idx] = channel_dict
    # not actually using the value here in any assertions, just need the key present
    expected_fw_item["is_first_packet_of_stream"] = None

    # tell mc_comm to stop data stream before 1 second of data is present
    expected_response = {"communication_type": "acquisition_manager", "command": "stop_managed_acquisition"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # make sure any data read is sent to file writer
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_fw_item.keys() == expected_fw_item.keys()
    np.testing.assert_array_equal(actual_fw_item["time_indices"], expected_fw_item["time_indices"])
    for key, expected_item in expected_fw_item.items():
        if key in ("data_type", "is_first_packet_of_stream", "time_indices"):
            continue
        actual_time_offsets = actual_fw_item[key]["time_offsets"]
        actual_data = actual_fw_item[key][expected_sensor_axis_id]
        np.testing.assert_array_equal(
            actual_time_offsets, expected_item["time_offsets"], err_msg=f"Failure at '{key}' key"
        )
        np.testing.assert_array_equal(
            actual_data, expected_item[expected_sensor_axis_id], err_msg=f"Failure at '{key}' key"
        )

    # process stop data streaming command and send response to mc_comm
    invoke_process_run_and_check_errors(simulator)
    # process response and send message to main. Also make sure empty data wasn't sent to file writer
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    assert to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == expected_response
    confirm_queue_is_eventually_empty(to_fw_queue)


def test_McCommunicationProcess__does_not_attempt_to_parse_when_stopping_data_stream_if_no_bytes_are_present(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_sampling_period_us = 10000
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )

    # tell mc_comm to stop data stream before 1 second of data is present
    expected_response = {"communication_type": "acquisition_manager", "command": "stop_managed_acquisition"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__logs_performance_metrics_after_parsing_data(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # mock since connection to simulator will be made by this test
    mocker.patch.object(mc_process, "create_connections_to_all_available_boards", autospec=True)
    # perform setup so performance logging values are initialized
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    # don't automatically get metadata
    mc_process._auto_get_metadata = False

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    start_data_stream(four_board_mc_comm_process_no_handshake, simulator)

    mc_process.reset_performance_tracker()  # call this method so there are percent use metrics to report
    mc_process._minimum_iteration_duration_seconds /= (  # pylint: disable=protected-access
        10  # set this to a lower value to speed up the test
    )
    # mock to speed up test
    mocker.patch.object(mc_process, "_dump_data_packets", autospec=True)

    # create expected values for metric creation
    expected_secs_between_parsing = list(range(15, 15 + INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES - 1))
    mocked_since_last_parse = mocker.patch.object(
        mc_comm, "_get_secs_since_last_data_parse", autospec=True, side_effect=expected_secs_between_parsing
    )
    expected_secs_between_reading = list(range(25, 25 + INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES - 1))
    mocked_since_last_read = mocker.patch.object(
        mc_comm, "_get_secs_since_last_data_read", autospec=True, side_effect=expected_secs_between_reading
    )
    expected_read_durs = list(range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES))
    mocked_data_read_dur = mocker.patch.object(
        mc_comm, "_get_dur_of_data_read_secs", autospec=True, side_effect=expected_read_durs
    )
    # Tanner (8/30/21): using arbitrary large number here. If data packet size changes this test may fail
    expected_read_lengths = list(range(1000000, 1000000 + INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES))
    mocker.patch.object(
        simulator,
        "read_all",
        autospec=True,
        side_effect=[bytes(read_len) for read_len in expected_read_lengths],
    )
    expected_parse_durs = list(range(0, INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES * 2, 2))
    mocked_data_parse_dur = mocker.patch.object(
        mc_comm, "_get_dur_of_data_parse_secs", autospec=True, side_effect=expected_parse_durs
    )
    expected_num_packets_read = list(range(20, 20 + INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES))
    mocker.patch.object(
        mc_comm,
        "handle_data_packets",
        autospec=True,
        side_effect=[
            {
                "magnetometer_data": {
                    "time_indices": [],
                    "time_offsets": [],
                    "data": [],
                    "num_data_packets": num_packets,
                },
                "stim_data": {},
                "other_packet_info": [],
                "unread_bytes": bytes(0),
            }
            for num_packets in expected_num_packets_read
        ],
    )

    # run mc_process to create metrics
    invoke_process_run_and_check_errors(
        mc_process, num_iterations=INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
    )
    # check that related metrics use same timepoints
    assert mocked_since_last_read.call_args_list == mocked_data_read_dur.call_args_list[:-1]
    assert mocked_since_last_parse.call_args_list == mocked_data_parse_dur.call_args_list[:-1]
    # check actual metric values
    actual = drain_queue(to_main_queue)[-1]["message"]
    assert actual["communication_type"] == "performance_metrics"
    for name, mc_measurements in (
        ("data_read_num_bytes", expected_read_lengths),
        ("data_read_duration", expected_read_durs),
        ("data_parsing_duration", expected_parse_durs),
        ("data_parsing_num_packets_produced", expected_num_packets_read),
        ("duration_between_reading", expected_secs_between_reading),
        ("duration_between_parsing", expected_secs_between_parsing),
    ):
        assert actual[name] == {
            "max": max(mc_measurements),
            "min": min(mc_measurements),
            "stdev": round(stdev(mc_measurements), 6),
            "mean": round(sum(mc_measurements) / len(mc_measurements), 6),
        }, name
    # values created in parent class
    assert "idle_iteration_time_ns" not in actual
    assert "start_timepoint_of_measurements" not in actual
    assert "percent_use" in actual
    assert "percent_use_metrics" in actual
    assert "longest_iterations" in actual


def test_McCommunicationProcess__does_not_update_or_log_performance_metrics_when_stopping_data_stream(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # mock since connection to simulator will be made by this test
    mocker.patch.object(mc_process, "create_connections_to_all_available_boards", autospec=True)
    # perform setup so performance logging values are initialized
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    # don't automatically get metadata
    mc_process._auto_get_metadata = False

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    start_data_stream(four_board_mc_comm_process_no_handshake, simulator)

    mc_process.reset_performance_tracker()  # call this method so there are percent use metrics to report
    mc_process._minimum_iteration_duration_seconds /= (  # pylint: disable=protected-access
        10  # set this to a lower value to speed up the test
    )
    # mock to speed up test
    mocker.patch.object(mc_process, "_dump_data_packets", autospec=True)

    # create expected values for metric creation
    mocker.patch.object(mc_comm, "_get_secs_since_last_data_parse", autospec=True, return_value=-1)
    mocker.patch.object(mc_comm, "_get_secs_since_last_data_read", autospec=True, return_value=-1)
    mocker.patch.object(mc_comm, "_get_dur_of_data_read_secs", autospec=True, return_value=-1)
    # Tanner (8/30/21): using arbitrary large number here. If data packet size changes this test may fail
    mocker.patch.object(
        simulator, "read_all", autospec=True, side_effect=lambda *args: bytes(1000000)  # arbitrary len
    )
    mocker.patch.object(mc_comm, "_get_dur_of_data_parse_secs", autospec=True, return_value=-1)
    mocker.patch.object(
        mc_comm,
        "handle_data_packets",
        autospec=True,
        side_effect=lambda *args: {
            "magnetometer_data": {
                "time_indices": [],
                "time_offsets": [],
                "data": [],
                "num_data_packets": 0,
            },
            "stim_data": {},
            "other_packet_info": [],
            "unread_bytes": bytes(0),
        },
    )

    # run mc_process to create metrics
    invoke_process_run_and_check_errors(
        mc_process, num_iterations=INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
    )
    # check metric values were sent to main
    actual = drain_queue(to_main_queue)[-1]["message"]
    assert actual["communication_type"] == "performance_metrics"
    # store current lengths of metric lists
    initial_metric_list_lens = {
        "data_read_durations": len(mc_process._data_read_durations),
        "data_read_lengths": len(mc_process._data_read_lengths),
        "data_parsing_num_packets_produced": len(mc_process._data_parsing_num_packets_produced),
        "data_parsing_durations": len(mc_process._data_parsing_durations),
        "durations_between_reading": len(mc_process._durations_between_reading),
        "durations_between_parsing": len(mc_process._durations_between_parsing),
    }

    # send command to stop managed acquisition
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(STOP_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    # run mc_process to create metrics
    invoke_process_run_and_check_errors(
        mc_process, num_iterations=INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
    )
    # check that not performance logging message sent to main
    confirm_queue_is_eventually_empty(to_main_queue)
    # make sure metric lists were not updated
    new_metric_list_lens = {
        "data_read_durations": len(mc_process._data_read_durations),
        "data_read_lengths": len(mc_process._data_read_lengths),
        "data_parsing_num_packets_produced": len(mc_process._data_parsing_num_packets_produced),
        "data_parsing_durations": len(mc_process._data_parsing_durations),
        "durations_between_reading": len(mc_process._durations_between_reading),
        "durations_between_parsing": len(mc_process._durations_between_parsing),
    }
    assert initial_metric_list_lens == new_metric_list_lens


def test_McCommunicationProcess__does_not_include_data_streaming_performance_metrics_in_first_logging_cycle(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # mock since connection to simulator will be made by this test
    mocker.patch.object(mc_process, "create_connections_to_all_available_boards", autospec=True)
    # perform setup so performance logging values are initialized
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    # don't automatically get metadata
    mc_process._auto_get_metadata = False

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    start_data_stream(four_board_mc_comm_process_no_handshake, simulator)

    # mock these to speed up test
    mc_process._minimum_iteration_duration_seconds = 0  # pylint: disable=protected-access
    # Tanner (8/30/21): using arbitrary large number here. If data packet size changes this test may fail
    test_read_lengths = list(range(1000000, 1000000 + INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES))
    mocker.patch.object(
        simulator, "read_all", autospec=True, side_effect=[bytes(read_len) for read_len in test_read_lengths]
    )
    mocker.patch.object(
        mc_comm,
        "handle_data_packets",
        autospec=True,
        side_effect=[
            {
                "magnetometer_data": {
                    "time_indices": [],
                    "time_offsets": [],
                    "data": [],
                    "num_data_packets": 0,
                },
                "stim_data": {},
                "other_packet_info": [],
                "unread_bytes": bytes(0),
            }
            for _ in range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES)
        ],
    )

    # run mc_process to create metrics
    invoke_process_run_and_check_errors(
        mc_process, num_iterations=INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
    )

    actual = drain_queue(to_main_queue)[-1]["message"]
    assert actual["communication_type"] == "performance_metrics"
    assert "percent_use_metrics" not in actual
