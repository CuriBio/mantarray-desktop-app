# -*- coding: utf-8 -*-
import copy
from random import choice
from random import randint
import time

from mantarray_desktop_app import convert_bitmask_to_config_dict
from mantarray_desktop_app import create_active_channel_per_sensor_list
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import handle_data_packets
from mantarray_desktop_app import InstrumentDataStreamingAlreadyStartedError
from mantarray_desktop_app import InstrumentDataStreamingAlreadyStoppedError
from mantarray_desktop_app import MagnetometerConfigUpdateWhileDataStreamingError
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from mantarray_desktop_app import SerialCommIncorrectChecksumFromInstrumentError
from mantarray_desktop_app import SerialCommIncorrectMagicWordFromMantarrayError
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
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_patch_print,
    fixture_four_board_mc_comm_process,
    fixture_four_board_mc_comm_process_no_handshake,
]


def random_time_index():
    return randint(0, 0xFFFFFFFFFF)


def random_time_offset():
    return randint(0, 0xFFFF)


def random_data_value():
    return randint(-0x8000, 0x7FFF)


def random_timestamp():
    return randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)


def random_bool():
    return choice([True, False])


TEST_NUM_WELLS = 24

WELL_CONFIG_ALL_CHANNELS_ENABLED = {channel_id: True for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS)}
FULL_CONFIG_ALL_CHANNELS_ENABLED = {
    module_id: copy.deepcopy(WELL_CONFIG_ALL_CHANNELS_ENABLED) for module_id in range(1, TEST_NUM_WELLS + 1)
}

FULL_DATA_PACKET_CHANNEL_LIST = [
    SERIAL_COMM_NUM_CHANNELS_PER_SENSOR for _ in range(SERIAL_COMM_NUM_SENSORS_PER_WELL * TEST_NUM_WELLS)
]

TEST_OTHER_TIMESTAMP = random_timestamp()  # type: ignore
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


def create_data_stream_body(
    time_index_us,
    magnetometer_config=FULL_CONFIG_ALL_CHANNELS_ENABLED,
    num_wells_on_plate=24,
):
    data_packet_body = time_index_us.to_bytes(SERIAL_COMM_TIME_INDEX_LENGTH_BYTES, byteorder="little")
    data_values = []
    offset_values = []
    for well_idx in range(num_wells_on_plate):
        config_values = list(magnetometer_config[well_idx + 1].values())
        for sensor_base_idx in range(0, SERIAL_COMM_NUM_DATA_CHANNELS, SERIAL_COMM_NUM_SENSORS_PER_WELL):
            if not any(config_values[sensor_base_idx : sensor_base_idx + SERIAL_COMM_NUM_SENSORS_PER_WELL]):
                continue
            # create offset value
            offset = random_time_offset()
            offset_values.append(offset)
            data_packet_body += offset.to_bytes(SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES, byteorder="little")
            # create data point
            data_value = random_data_value()
            data_value_bytes = data_value.to_bytes(2, byteorder="little", signed=True)
            for axis_idx in range(SERIAL_COMM_NUM_CHANNELS_PER_SENSOR):
                # add data points
                channel_id = sensor_base_idx + axis_idx
                if magnetometer_config[well_idx + 1][channel_id]:
                    data_values.append(data_value)
                    data_packet_body += data_value_bytes
    return data_packet_body, offset_values, data_values


def set_magnetometer_config_and_start_streaming(
    mc_fixture,
    simulator,
    magnetometer_config,
    sampling_period,
):
    mc_process = mc_fixture["mc_process"]
    from_main_queue = mc_fixture["board_queues"][0][0]
    to_main_queue = mc_fixture["board_queues"][0][1]
    config_command = {
        "communication_type": "to_instrument",
        "command": "change_magnetometer_config",
        "magnetometer_config": magnetometer_config,
        "sampling_period": sampling_period,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(config_command, from_main_queue)
    # send command, process command, process command response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    start_command = {
        "communication_type": "to_instrument",
        "command": "start_managed_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)
    # send command, process command, process command response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)


def test_handle_data_packets__handles_two_full_data_packets_correctly__and_assigns_correct_data_type_to_parsed_values__when_all_channels_enabled():
    test_num_data_packets = 2
    expected_time_indices = [5000, 10000]

    test_data_packet_bytes = bytes(0)
    expected_data_points = []
    expected_time_offsets = []
    for packet_num in range(test_num_data_packets):
        data_packet_body, test_offsets, test_data = create_data_stream_body(expected_time_indices[packet_num])
        test_data_packet_bytes += create_data_packet(
            random_timestamp(),
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
            data_packet_body,
        )
        expected_data_points.extend(test_data)
        expected_time_offsets.extend(test_offsets)
    expected_time_offsets = np.array(expected_time_offsets).reshape(
        (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
    )
    expected_data_points = np.array(expected_data_points).reshape(
        (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
    )

    (
        actual_time_indices,
        actual_time_offsets,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_data_packet_bytes), FULL_DATA_PACKET_CHANNEL_LIST)

    assert actual_time_indices.dtype == np.uint64
    assert actual_time_offsets.dtype == np.uint16
    assert actual_data.dtype == np.int16
    np.testing.assert_array_equal(actual_time_indices, expected_time_indices)
    np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
    np.testing.assert_array_equal(actual_data, expected_data_points)
    assert num_data_packets_read == test_num_data_packets
    assert other_packet_info is None
    assert unread_bytes == bytes(0)


def test_handle_data_packets__handles_two_full_data_packets_correctly__when_active_sensors_have_different_configs():
    test_num_data_packets = 2
    expected_time_indices = [1000, 2000]

    # set up config dict so that starting at well 5 with one channel enabled, each well has one more channel enabled than the last until a well has all channels enabled
    test_num_wells = 24
    test_config_dict = create_magnetometer_config_dict(test_num_wells)
    first_well_enabled = 5
    for well_idx in range(first_well_enabled, first_well_enabled + SERIAL_COMM_NUM_DATA_CHANNELS):
        num_channels_to_enable = well_idx - first_well_enabled + 1
        for channel_id in range(num_channels_to_enable):
            test_config_dict[well_idx + 1][channel_id] = True
    # also set up random config on one more arbitrarily chosen key
    for channel_id in test_config_dict[test_num_wells].keys():
        test_config_dict[test_num_wells][channel_id] = random_bool()

    test_data_packet_bytes = bytes(0)
    expected_data_points = []
    expected_time_offsets = []
    for packet_num in range(test_num_data_packets):
        data_packet_body, test_offsets, test_data = create_data_stream_body(
            expected_time_indices[packet_num],
            test_config_dict,
        )
        test_data_packet_bytes += create_data_packet(
            random_timestamp(),
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
            data_packet_body,
        )
        expected_data_points.extend(test_data)
        expected_time_offsets.extend(test_offsets)
    expected_time_offsets = np.array(expected_time_offsets).reshape(
        (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
    )
    expected_data_points = np.array(expected_data_points).reshape(
        (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
    )

    active_channels_list = create_active_channel_per_sensor_list(test_config_dict)
    (
        actual_time_indices,
        actual_time_offsets,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_data_packet_bytes), active_channels_list)

    np.testing.assert_array_equal(actual_time_indices, expected_time_indices)
    np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
    np.testing.assert_array_equal(actual_data, expected_data_points)
    assert num_data_packets_read == test_num_data_packets
    assert other_packet_info is None
    assert unread_bytes == bytes(0)


def test_handle_data_packets__handles_single_packet_with_incorrect_packet_type_correctly__when_all_channels_enabled():
    (
        actual_time_indices,
        actual_time_offsets,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(TEST_OTHER_PACKET), FULL_DATA_PACKET_CHANNEL_LIST)

    assert actual_time_indices.shape[0] == 0
    assert actual_time_offsets.shape[1] == 0
    assert actual_data.shape[1] == 0
    assert num_data_packets_read == 0
    assert other_packet_info == TEST_OTHER_PACKET_INFO
    assert unread_bytes == bytes(0)


def test_handle_data_packets__handles_single_packet_with_incorrect_module_id_correctly__when_all_channels_enabled():
    test_body_length = randint(0, 10)
    expected_timestamp = random_timestamp()
    test_data_packet = create_data_packet(
        expected_timestamp,
        255,  # using module ID that hasn't been implemented, but could probably use arbitrary module ID other than the main module ID that data packets will have
        SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
        bytes(test_body_length),
    )

    (
        actual_time_indices,
        actual_time_offsets,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_data_packet), FULL_DATA_PACKET_CHANNEL_LIST)

    assert actual_time_indices.shape[0] == 0
    assert actual_time_offsets.shape[1] == 0
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
    data_packet_body, _, _ = create_data_stream_body(random_time_index())
    expected_unread_bytes = create_data_packet(
        random_timestamp(),
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
        data_packet_body,
    )
    test_bytes = TEST_OTHER_PACKET + expected_unread_bytes

    (
        actual_time_indices,
        actual_time_offsets,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_bytes), FULL_DATA_PACKET_CHANNEL_LIST)

    assert actual_time_indices.shape[0] == 1
    assert actual_time_offsets.shape[1] == 1
    assert actual_data.shape[1] == 1
    assert num_data_packets_read == 0
    assert other_packet_info == TEST_OTHER_PACKET_INFO
    assert unread_bytes == expected_unread_bytes


def test_handle_data_packets__handles_single_data_packet_followed_by_interrupting_packet__when_all_channels_enabled():
    expected_time_index = random_time_index()
    data_packet_body, _, _ = create_data_stream_body(expected_time_index)
    test_data_packet = create_data_packet(
        random_timestamp(),
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
        data_packet_body,
    )
    test_bytes = test_data_packet + TEST_OTHER_PACKET

    (
        actual_time_indices,
        actual_time_offsets,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_bytes), FULL_DATA_PACKET_CHANNEL_LIST)

    assert actual_time_indices.shape[0] == 1
    assert actual_time_offsets.shape[1] == 1
    assert actual_data.shape[1] == 1
    assert actual_time_indices[0] == expected_time_index
    assert num_data_packets_read == 1
    assert other_packet_info == TEST_OTHER_PACKET_INFO
    assert unread_bytes == bytes(0)


def test_handle_data_packets__handles_single_data_packet_followed_by_incomplete_packet__when_all_channels_enabled():
    expected_time_index = random_time_index()
    data_packet_body, _, _ = create_data_stream_body(expected_time_index)
    test_data_packet = create_data_packet(
        random_timestamp(),
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
        data_packet_body,
    )
    test_incomplete_packet = bytes(SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES - 1)
    test_bytes = test_data_packet + test_incomplete_packet

    (
        actual_time_indices,
        actual_data,
        actual_time_offsets,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_bytes), FULL_DATA_PACKET_CHANNEL_LIST)

    assert actual_time_indices.shape[0] == 1
    assert actual_time_offsets.shape[1] == 1
    assert actual_data.shape[1] == 1
    assert actual_time_indices[0] == expected_time_index
    assert num_data_packets_read == 1
    assert other_packet_info is None
    assert unread_bytes == test_incomplete_packet


def test_handle_data_packets__handles_interrupting_packet_in_between_two_data_packets__when_all_channels_enabled():
    test_num_data_packets = 2

    expected_time_indices = []
    test_data_packets = []
    for _ in range(test_num_data_packets):
        time_index = random_time_index()
        expected_time_indices.append(time_index)

        data_packet_body, _, _ = create_data_stream_body(time_index)
        test_data_packet = create_data_packet(
            random_timestamp(),
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
            data_packet_body,
        )
        test_data_packets.append(test_data_packet)
    test_bytes = test_data_packets[0] + TEST_OTHER_PACKET + test_data_packets[1]

    (
        actual_time_indices,
        actual_time_offsets,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_bytes), FULL_DATA_PACKET_CHANNEL_LIST)

    assert actual_time_indices.shape[0] == 2
    assert actual_time_offsets.shape[1] == 2
    assert actual_data.shape[1] == 2
    assert actual_time_indices[0] == expected_time_indices[0]
    assert num_data_packets_read == 1
    assert other_packet_info == TEST_OTHER_PACKET_INFO
    assert unread_bytes == test_data_packets[1]


def test_handle_data_packets__raises_error_when_packet_from_instrument_has_incorrect_magic_word(
    patch_print,
):
    bad_magic_word_bytes = b"NOT CURI"
    bad_packet = bad_magic_word_bytes + TEST_OTHER_PACKET[len(SERIAL_COMM_MAGIC_WORD_BYTES) :]
    with pytest.raises(SerialCommIncorrectMagicWordFromMantarrayError, match=str(bad_magic_word_bytes)):
        handle_data_packets(bytearray(bad_packet), FULL_DATA_PACKET_CHANNEL_LIST)


def test_handle_data_packets__raises_error_when_packet_from_instrument_has_incorrect_crc32_checksum(
    patch_print,
):
    bad_checksum = 0
    bad_checksum_bytes = bad_checksum.to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")
    bad_packet = TEST_OTHER_PACKET[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES] + bad_checksum_bytes
    with pytest.raises(SerialCommIncorrectChecksumFromInstrumentError) as exc_info:
        handle_data_packets(bytearray(bad_packet), FULL_DATA_PACKET_CHANNEL_LIST)

    expected_checksum = int.from_bytes(bad_packet[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:], byteorder="little")
    assert str(bad_checksum) in exc_info.value.args[0]
    assert str(expected_checksum) in exc_info.value.args[0]
    assert str(bytearray(bad_packet)) in exc_info.value.args[0]


def test_handle_data_packets__performance_test():
    # One second of data, max sampling rate, all data channels on
    # start:                                        1397497
    # added time offsets + memory views:            2297374  # TODO

    num_us_of_data_to_send = int(1e6)
    max_sampling_rate_us = 1000
    test_num_data_packets = num_us_of_data_to_send // max_sampling_rate_us
    expected_time_indices = list(range(0, num_us_of_data_to_send, max_sampling_rate_us))

    test_data_packet_bytes = bytes(0)
    expected_data_points = []
    expected_time_offsets = []
    for packet_num in range(test_num_data_packets):
        data_packet_body, test_offsets, test_data = create_data_stream_body(expected_time_indices[packet_num])
        test_data_packet_bytes += create_data_packet(
            random_timestamp(),
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
            data_packet_body,
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
    (
        actual_time_indices,
        actual_time_offsets,
        actual_data,
        num_data_packets_read,
        other_packet_info,
        unread_bytes,
    ) = handle_data_packets(bytearray(test_data_packet_bytes), FULL_DATA_PACKET_CHANNEL_LIST)
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


def test_McCommunicationProcess__raises_error_when_change_magnetometer_config_command_received_while_data_is_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
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
    start_command = {
        "communication_type": "to_instrument",
        "command": "start_managed_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # attempt to change magnetometer configuration and assert error is raised
    change_config_command = {
        "communication_type": "to_instrument",
        "command": "change_magnetometer_config",
        "sampling_period": 65000,  # arbitrary value
        "magnetometer_config": dict(),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(change_config_command, from_main_queue)
    with pytest.raises(MagnetometerConfigUpdateWhileDataStreamingError):
        invoke_process_run_and_check_errors(mc_process)


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

    expected_response = {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
    }
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
    set_magnetometer_config_and_start_streaming(
        four_board_mc_comm_process_no_handshake,
        simulator,
        {},
        test_sampling_period_us,  # arbitrary value
    )

    # mocking in order to produce incomplete data packet
    mocker.patch.object(
        mc_simulator,
        "create_data_packet",
        autospec=True,
        return_value=bytes(SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES - 1),
    )
    spied_handle = mocker.spy(mc_comm, "handle_data_packets")
    spied_read_all = mocker.spy(simulator, "read_all")

    # send data
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES - 1
    # read data
    invoke_process_run_and_check_errors(mc_process)
    spied_read_all.assert_called_once()
    spied_handle.assert_not_called()
    confirm_queue_is_eventually_empty(to_fw_queue)


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
    test_sampling_period_us = int(1e6 // test_num_packets)
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

    set_magnetometer_config_and_start_streaming(
        four_board_mc_comm_process_no_handshake,
        simulator,
        FULL_CONFIG_ALL_CHANNELS_ENABLED,
        test_sampling_period_us,
    )

    max_time_idx_us = test_sampling_period_us * test_num_packets
    expected_time_indices = list(range(0, max_time_idx_us, test_sampling_period_us))

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)
    expected_fw_item = {"time_indices": np.array(expected_time_indices, np.uint64)}
    for well_idx in range(test_num_wells):
        channel_dict = {
            "time_offsets": np.zeros((SERIAL_COMM_NUM_SENSORS_PER_WELL, test_num_packets), dtype=np.uint16),
        }
        for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
            channel_dict[channel_id] = simulated_data * np.int16(well_idx + 1)
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
        if key in ("is_first_packet_of_stream", "time_indices"):
            continue
        actual_item = actual_fw_item[key]
        assert actual_item.keys() == expected_item.keys()  # pylint: disable=no-member
        for sub_key, expected_data in expected_item.items():  # pylint: disable=no-member
            actual_data = actual_item[sub_key]
            expected_dtype = np.uint16 if sub_key == "time_offsets" else np.int16
            assert actual_data.dtype == expected_dtype
            np.testing.assert_array_equal(
                actual_data, expected_data, err_msg=f"Failure at '{key}' key, sub key '{sub_key}'"
            )


def test_McCommunicationProcess__handles_read_of_only_data_packets__and_sends_data_to_file_writer_correctly__when_one_second_of_data_with_random_magnetometer_config_is_present(
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

    test_num_wells = 24
    test_config_dict = create_magnetometer_config_dict(test_num_wells)
    for well_dict in test_config_dict.values():
        for channel_id in well_dict.keys():
            well_dict[channel_id] = random_bool()
    test_config_dict[1][0] = True  # need at least one channel enabled
    set_magnetometer_config_and_start_streaming(
        four_board_mc_comm_process_no_handshake,
        simulator,
        test_config_dict,
        test_sampling_period_us,
    )

    max_time_idx_us = test_sampling_period_us * test_num_packets
    expected_time_indices = list(range(0, max_time_idx_us, test_sampling_period_us))

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)
    expected_fw_item = {"time_indices": np.array(expected_time_indices, np.uint64)}
    for well_idx in range(test_num_wells):
        config_values = list(test_config_dict[well_idx + 1].values())
        num_channels_for_well = 0
        for sensor_base_idx in range(0, SERIAL_COMM_NUM_DATA_CHANNELS, SERIAL_COMM_NUM_CHANNELS_PER_SENSOR):
            num_channels_for_sensor = sum(
                config_values[sensor_base_idx : sensor_base_idx + SERIAL_COMM_NUM_CHANNELS_PER_SENSOR]
            )
            num_channels_for_well += int(num_channels_for_sensor > 0)

        channel_dict = {"time_offsets": np.zeros((num_channels_for_well, test_num_packets), dtype=np.uint16)}
        for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
            if not config_values[channel_id]:
                continue
            channel_dict[channel_id] = simulated_data * np.int16(well_idx + 1)
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
        if key in ("is_first_packet_of_stream", "time_indices"):
            continue
        actual_item = actual_fw_item[key]
        assert actual_item.keys() == expected_item.keys()  # pylint: disable=no-member
        for sub_key, expected_data in expected_item.items():  # pylint: disable=no-member
            actual_data = actual_item[sub_key]
            np.testing.assert_array_equal(
                actual_data, expected_data, err_msg=f"Failure at '{key}' key, sub key '{sub_key}'"
            )


def test_McCommunicationProcess__handles_one_second_read_with_interrupting_packet_correctly__and_indicates_the_first_packet_is_the_very_first_packet_of_the_stream(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    mocker,
):
    # pylint: disable=too-many-locals  # Tanner (5/13/21): a lot of locals variables needed for this test
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_sampling_period_us = 10000  # specifically chosen so that there are 100 data packets in one second
    test_num_packets = int(1.5e6 // test_sampling_period_us)
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us * test_num_packets, 0],
    )

    expected_sensor_axis_id = SERIAL_COMM_NUM_DATA_CHANNELS - 1

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    test_num_channels_per_sensor = 1
    test_config_dict = dict()
    for well_idx in range(0, 24):
        bitmask_int = int(10 <= well_idx <= 15)  # turn on one channel of wells 10-15
        test_config_dict[well_idx + 1] = convert_bitmask_to_config_dict(bitmask_int)
    set_magnetometer_config_and_start_streaming(
        four_board_mc_comm_process_no_handshake,
        simulator,
        test_config_dict,
        test_sampling_period_us,
    )

    max_time_idx_us = test_sampling_period_us * test_num_packets
    expected_time_indices = list(range(0, max_time_idx_us, test_sampling_period_us))

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)
    expected_fw_item = {"time_indices": np.array(expected_time_indices, np.uint64)}
    for well_idx in range(10, 16):
        channel_data = np.concatenate((simulated_data, simulated_data[: test_num_packets // 3]))
        channel_dict = {
            "time_offsets": np.zeros((test_num_channels_per_sensor, test_num_packets), dtype=np.uint16),
            expected_sensor_axis_id: channel_data * np.int16(well_idx + 1),
        }
        expected_fw_item[well_idx] = channel_dict
    # not actually using the value here in any assertions, just need the key present
    expected_fw_item["is_first_packet_of_stream"] = None

    # insert status beacon after 1/3 of data
    invoke_process_run_and_check_errors(simulator)
    read_bytes = simulator.read_all()
    read_bytes = read_bytes[: len(read_bytes) // 3] + TEST_OTHER_PACKET + read_bytes[len(read_bytes) // 3 :]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": read_bytes}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # populate mc_comm output queues
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_fw_queue, 2)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    # test message to main from interrupting packet
    actual_beacon_log_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_status_code = int.from_bytes(TEST_OTHER_PACKET_INFO[3], byteorder="little")
    assert str(expected_status_code) in actual_beacon_log_msg["message"]
    # test data packets going to file_writer
    for item_idx in range(2):
        actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert actual_fw_item.keys() == expected_fw_item.keys()
        assert actual_fw_item["is_first_packet_of_stream"] is (item_idx == 0)

        start_idx = 0 if item_idx == 0 else test_num_packets // 3
        stop_idx = test_num_packets // 3 if item_idx == 0 else test_num_packets
        np.testing.assert_array_equal(
            actual_fw_item["time_indices"],
            expected_fw_item["time_indices"][start_idx:stop_idx],
            err_msg=f"Failure at item idx {item_idx}",
        )

        for key, expected_item in expected_fw_item.items():
            if key in ("is_first_packet_of_stream", "time_indices"):
                continue
            actual_time_offsets = actual_fw_item[key]["time_offsets"]
            actual_data = actual_fw_item[key][expected_sensor_axis_id]
            np.testing.assert_array_equal(
                actual_time_offsets,
                expected_item["time_offsets"][:, start_idx:stop_idx],
                err_msg=f"Failure at item idx {item_idx} at '{key}' key",
            )
            np.testing.assert_array_equal(
                actual_data,
                expected_item[expected_sensor_axis_id][start_idx:stop_idx],
                err_msg=f"Failure at item idx {item_idx} at '{key}' key",
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
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us * test_num_packets],
    )

    expected_sensor_axis_id = SERIAL_COMM_NUM_DATA_CHANNELS - 1

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    test_num_channels_per_sensor = 1
    test_config_dict = dict()
    for well_idx in range(0, 24):
        bitmask_int = int(10 <= well_idx <= 15)  # turn on one channel of wells 10-15
        test_config_dict[well_idx + 1] = convert_bitmask_to_config_dict(bitmask_int)
    set_magnetometer_config_and_start_streaming(
        four_board_mc_comm_process_no_handshake,
        simulator,
        test_config_dict,
        test_sampling_period_us,
    )
    invoke_process_run_and_check_errors(simulator)

    max_time_idx_us = test_sampling_period_us * test_num_packets
    expected_time_indices = list(range(0, max_time_idx_us, test_sampling_period_us))

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)
    expected_fw_item = {"time_indices": np.array(expected_time_indices, np.uint64)}
    for well_idx in range(10, 16):
        channel_dict = {
            "time_offsets": np.zeros((test_num_channels_per_sensor, test_num_packets), dtype=np.uint16),
            expected_sensor_axis_id: simulated_data[:test_num_packets] * np.int16(well_idx + 1),
        }
        expected_fw_item[well_idx] = channel_dict
    # not actually using the value here in any assertions, just need the key present
    expected_fw_item["is_first_packet_of_stream"] = None

    # tell mc_comm to stop data stream before 1 second of data is present
    expected_response = {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
    }
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
        if key in ("is_first_packet_of_stream", "time_indices"):
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
