# -*- coding: utf-8 -*-
import copy
import datetime, time
from random import choice, randint
from venv import create
from immutabledict import immutabledict
from freezegun import freeze_time
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import sort_serial_packets
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import STIM_COMPLETE_SUBPROTOCOL_IDX
from mantarray_desktop_app import STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
from mantarray_desktop_app import StimProtocolStatuses
from mantarray_desktop_app import StimulationProtocolUpdateFailedError
from mantarray_desktop_app import StimulationProtocolUpdateWhileStimulatingError
from mantarray_desktop_app import StimulationStatusUpdateFailedError
from mantarray_desktop_app.constants import (
    GENERIC_24_WELL_DEFINITION,
    SERIAL_COMM_CHECKSUM_LENGTH_BYTES,
    SERIAL_COMM_MAGIC_WORD_BYTES,
    SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE,
    SERIAL_COMM_NUM_CHANNELS_PER_SENSOR,
    SERIAL_COMM_NUM_DATA_CHANNELS,
    SERIAL_COMM_NUM_SENSORS_PER_WELL,
    SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES,
    SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
    SERIAL_COMM_STATUS_CODE_LENGTH_BYTES,
    SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE,
    SERIAL_COMM_TIME_INDEX_LENGTH_BYTES,
    SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES,
)
from mantarray_desktop_app.constants import STIM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app.exceptions import (
    SerialCommIncorrectChecksumFromInstrumentError,
    SerialCommIncorrectMagicWordFromMantarrayError,
)
from mantarray_desktop_app.serial_comm_utils import convert_impedance_to_circuit_status
import numpy as np
import pytest

from ..fixtures_mc_simulator import random_data_value, random_time_index, random_time_offset
from ..fixtures_mc_simulator import random_timestamp

TEST_OTHER_TIMESTAMP = random_timestamp()  # type: ignore
TEST_OTHER_PACKET_INFO = (
    TEST_OTHER_TIMESTAMP,
    SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
    bytes(SERIAL_COMM_STATUS_CODE_LENGTH_BYTES),
)
TEST_OTHER_PACKET = create_data_packet(*TEST_OTHER_PACKET_INFO)

UNPOPULATED_STREAM_DICT = immutabledict({"raw_bytes": bytearray(0), "num_packets": 0})

STREAM_PACKET_TYPES = [SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, SERIAL_COMM_STIM_STATUS_PACKET_TYPE]


def randint_excluding(stop, exclude):
    return choice(list(set(range(stop)) - set(exclude)))


def create_data_stream_body(time_index_us, num_wells_on_plate=24):
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


@pytest.mark.parametrize("test_packet_type", STREAM_PACKET_TYPES)
def test_sort_serial_packets__sorts_single_stream_packet_correctly(test_packet_type):
    # sort_serial_packets won't parse payloads, so can make it arbitrary bytes
    test_payload = bytes(range(10))
    test_packet = create_data_packet(random_timestamp(), test_packet_type, test_payload)

    if test_packet_type == SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE:
        test_populated_dict_key = "magnetometer_stream_info"
        test_unpopulated_dict_key = "stim_stream_info"
    else:
        test_populated_dict_key = "stim_stream_info"
        test_unpopulated_dict_key = "magnetometer_stream_info"

    sorted_packet_dict = sort_serial_packets(bytearray(test_packet))

    # convert this to a bytearray before assertion
    sorted_packet_dict[test_populated_dict_key]["raw_bytes"] = bytearray(
        sorted_packet_dict[test_populated_dict_key]["raw_bytes"][:]
    )

    assert sorted_packet_dict == {
        test_populated_dict_key: {"raw_bytes": bytearray(test_payload), "num_packets": 1},
        test_unpopulated_dict_key: dict(UNPOPULATED_STREAM_DICT),
        "other_packet_info": [],
        "unread_bytes": bytearray(0),
    }


def test_sort_serial_packets__sorts_single_non_stream_packet_correctly():
    sorted_packet_dict = sort_serial_packets(bytearray(TEST_OTHER_PACKET))
    assert sorted_packet_dict == {
        "magnetometer_stream_info": dict(UNPOPULATED_STREAM_DICT),
        "stim_stream_info": dict(UNPOPULATED_STREAM_DICT),
        "other_packet_info": [TEST_OTHER_PACKET_INFO],
        "unread_bytes": bytearray(0),
    }


def test_sort_serial_packets__sorts_incomplete_packet():
    incomplete_packet = TEST_OTHER_PACKET[:-1]
    sorted_packet_dict = sort_serial_packets(bytearray(incomplete_packet))
    assert sorted_packet_dict == {
        "magnetometer_stream_info": dict(UNPOPULATED_STREAM_DICT),
        "stim_stream_info": dict(UNPOPULATED_STREAM_DICT),
        "other_packet_info": [],
        "unread_bytes": bytearray(incomplete_packet),
    }


def test_sort_serial_packets__sorts_multiple_of_each_possible_packet_type_together():
    test_mag_1 = create_data_packet(random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, b"MAG1")
    test_mag_2 = create_data_packet(random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, b"MAG2")

    test_stim_1 = create_data_packet(random_timestamp(), SERIAL_COMM_STIM_STATUS_PACKET_TYPE, b"STIM1")
    test_stim_2 = create_data_packet(random_timestamp(), SERIAL_COMM_STIM_STATUS_PACKET_TYPE, b"STIM2")

    test_other_info_1 = (random_timestamp(), randint_excluding(0xFF, STREAM_PACKET_TYPES), b"OTHER1")
    test_other_info_2 = (random_timestamp(), randint_excluding(0xFF, STREAM_PACKET_TYPES), b"OTHER2")
    test_other_1 = create_data_packet(*test_other_info_1)
    test_other_2 = create_data_packet(*test_other_info_2)

    incomplete_packet = TEST_OTHER_PACKET[:-1]

    test_bytes = bytearray(
        test_mag_1 + test_stim_1 + test_other_1 + test_stim_2 + test_other_2 + test_mag_2 + incomplete_packet
    )
    sorted_packet_dict = sort_serial_packets(test_bytes)

    assert sorted_packet_dict == {
        "magnetometer_stream_info": {"raw_bytes": bytearray(b"MAG1MAG2"), "num_packets": 2},
        "stim_stream_info": {"raw_bytes": bytearray(b"STIM1STIM2"), "num_packets": 2},
        "other_packet_info": [test_other_info_1, test_other_info_2],
        "unread_bytes": bytearray(incomplete_packet),
    }


########################


# def test_sort_serial_packets__handles_two_full_mag_data_packets_correctly__and_assigns_correct_data_type_to_parsed_values__when_all_channels_enabled():
#     test_num_data_packets = 2
#     expected_time_indices = [0xFFFFFFFFFFFFFF00, 0xFFFFFFFFFFFFFF01]

#     base_global_time = randint(0, 100)

#     test_data_packet_bytes = bytes(0)
#     expected_data_points = []
#     expected_time_offsets = []
#     for packet_num in range(test_num_data_packets):
#         data_packet_payload, test_offsets, test_data = create_data_stream_body(
#             expected_time_indices[packet_num] + base_global_time
#         )
#         test_data_packet_bytes += create_data_packet(
#             random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
#         )
#         expected_data_points.extend(test_data)
#         expected_time_offsets.extend(test_offsets)
#     expected_time_offsets = np.array(expected_time_offsets).reshape(
#         (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
#     )
#     expected_data_points = np.array(expected_data_points).reshape(
#         (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
#     )

#     parsed_data_dict = sort_serial_packets(bytearray(test_data_packet_bytes), base_global_time)
#     actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
#         "magnetometer_data"
#     ].values()

#     assert actual_time_indices.dtype == np.uint64
#     assert actual_time_offsets.dtype == np.uint16
#     assert actual_data.dtype == np.uint16
#     np.testing.assert_array_equal(actual_time_indices, expected_time_indices)
#     np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
#     np.testing.assert_array_equal(actual_data, expected_data_points)
#     assert num_data_packets_read == test_num_data_packets
#     assert parsed_data_dict["other_packet_info"] == []
#     assert parsed_data_dict["unread_bytes"] == bytes(0)


# def test_sort_serial_packets__handles_single_packet_with_incorrect_packet_type_correctly__when_all_channels_enabled():
#     parsed_data_dict = sort_serial_packets(bytearray(TEST_OTHER_PACKET), 0)
#     actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
#         "magnetometer_data"
#     ].values()

#     assert actual_time_indices.shape[0] == 0
#     assert actual_time_offsets.shape[1] == 0
#     assert actual_data.shape[1] == 0
#     assert num_data_packets_read == 0
#     assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO]
#     assert parsed_data_dict["unread_bytes"] == bytes(0)


# def test_sort_serial_packets__handles_interrupting_packet_followed_by_data_packet__when_all_channels_enabled():
#     expected_time_index = random_time_index()
#     data_packet_payload, expected_time_offsets, expected_data_points = create_data_stream_body(
#         expected_time_index
#     )
#     test_bytes = TEST_OTHER_PACKET + create_data_packet(
#         random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
#     )

#     parsed_data_dict = sort_serial_packets(bytearray(test_bytes), 0)
#     actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
#         "magnetometer_data"
#     ].values()

#     np.testing.assert_array_equal(actual_time_indices, expected_time_index)
#     np.testing.assert_array_equal(actual_time_offsets.flatten(), expected_time_offsets)
#     np.testing.assert_array_equal(actual_data.flatten(), expected_data_points)
#     assert num_data_packets_read == 1
#     assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO]
#     assert parsed_data_dict["unread_bytes"] == bytes(0)


# def test_sort_serial_packets__handles_single_data_packet_followed_by_interrupting_packet__when_all_channels_enabled():
#     expected_time_index = random_time_index()
#     data_packet_payload, _, _ = create_data_stream_body(expected_time_index)
#     test_data_packet = create_data_packet(
#         random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
#     )
#     test_bytes = test_data_packet + TEST_OTHER_PACKET

#     parsed_data_dict = sort_serial_packets(bytearray(test_bytes), 0)
#     actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
#         "magnetometer_data"
#     ].values()

#     assert actual_time_indices.shape[0] == 1
#     assert actual_time_offsets.shape[1] == 1
#     assert actual_data.shape[1] == 1
#     assert actual_time_indices[0] == expected_time_index
#     assert num_data_packets_read == 1
#     assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO]
#     assert parsed_data_dict["unread_bytes"] == bytes(0)


# def test_sort_serial_packets__handles_single_data_packet_followed_by_incomplete_packet__when_all_channels_enabled():
#     expected_time_index = random_time_index()
#     data_packet_payload, _, _ = create_data_stream_body(expected_time_index)
#     test_data_packet = create_data_packet(
#         random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
#     )
#     test_incomplete_packet = bytes(SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES - 1)
#     test_bytes = test_data_packet + test_incomplete_packet

#     parsed_data_dict = sort_serial_packets(bytearray(test_bytes), 0)
#     actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
#         "magnetometer_data"
#     ].values()

#     assert actual_time_indices.shape[0] == 1
#     assert actual_time_offsets.shape[1] == 1
#     assert actual_data.shape[1] == 1
#     assert actual_time_indices[0] == expected_time_index
#     assert num_data_packets_read == 1
#     assert parsed_data_dict["other_packet_info"] == []
#     assert parsed_data_dict["unread_bytes"] == test_incomplete_packet


# def test_sort_serial_packets__handles_interrupting_packet_in_between_two_data_packets__when_all_channels_enabled():
#     test_num_data_packets = 2

#     expected_time_indices = []
#     expected_time_offsets = []
#     expected_data_points = []
#     test_data_packets = []
#     for _ in range(test_num_data_packets):
#         time_index = random_time_index()
#         expected_time_indices.append(time_index)

#         data_packet_payload, test_offsets, test_data = create_data_stream_body(time_index)
#         test_data_packet = create_data_packet(
#             random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
#         )
#         test_data_packets.append(test_data_packet)
#         expected_time_offsets.extend(test_offsets)
#         expected_data_points.extend(test_data)
#     test_bytes = test_data_packets[0] + TEST_OTHER_PACKET + test_data_packets[1]

#     parsed_data_dict = sort_serial_packets(bytearray(test_bytes), 0)
#     actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
#         "magnetometer_data"
#     ].values()

#     expected_time_offsets = np.array(expected_time_offsets).reshape(
#         (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
#     )
#     expected_data_points = np.array(expected_data_points).reshape(
#         (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
#     )

#     np.testing.assert_array_equal(actual_time_indices, expected_time_indices)
#     np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
#     np.testing.assert_array_equal(actual_data, expected_data_points)
#     assert num_data_packets_read == 2
#     assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO]
#     assert parsed_data_dict["unread_bytes"] == bytes(0)


# def test_sort_serial_packets__handles_two_interrupting_packets_in_between_two_data_packets__when_all_channels_enabled():
#     test_num_data_packets = 2

#     expected_time_indices = []
#     expected_time_offsets = []
#     expected_data_points = []
#     test_data_packets = []
#     for _ in range(test_num_data_packets):
#         time_index = random_time_index()
#         expected_time_indices.append(time_index)

#         data_packet_payload, test_offsets, test_data = create_data_stream_body(time_index)
#         test_data_packet = create_data_packet(
#             random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
#         )
#         test_data_packets.append(test_data_packet)
#         expected_time_offsets.extend(test_offsets)
#         expected_data_points.extend(test_data)
#     test_bytes = test_data_packets[0] + TEST_OTHER_PACKET + TEST_OTHER_PACKET + test_data_packets[1]

#     parsed_data_dict = sort_serial_packets(bytearray(test_bytes), 0)
#     actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
#         "magnetometer_data"
#     ].values()

#     expected_time_offsets = np.array(expected_time_offsets).reshape(
#         (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
#     )
#     expected_data_points = np.array(expected_data_points).reshape(
#         (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
#     )

#     np.testing.assert_array_equal(actual_time_indices, expected_time_indices)
#     np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
#     np.testing.assert_array_equal(actual_data, expected_data_points)
#     assert num_data_packets_read == 2
#     assert parsed_data_dict["other_packet_info"] == [TEST_OTHER_PACKET_INFO, TEST_OTHER_PACKET_INFO]
#     assert parsed_data_dict["unread_bytes"] == bytes(0)


# def test_sort_serial_packets__raises_error_when_packet_from_instrument_has_incorrect_magic_word(
#     patch_print,
# ):
#     bad_magic_word_bytes = b"NOT CURI"
#     bad_packet = bad_magic_word_bytes + TEST_OTHER_PACKET[len(SERIAL_COMM_MAGIC_WORD_BYTES) :]
#     with pytest.raises(SerialCommIncorrectMagicWordFromMantarrayError, match=str(bad_magic_word_bytes)):
#         sort_serial_packets(bytearray(bad_packet), 0)


# def test_sort_serial_packets__raises_error_when_packet_from_instrument_has_incorrect_crc32_checksum(
#     patch_print,
# ):
#     bad_checksum = 0
#     bad_checksum_bytes = bad_checksum.to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")
#     bad_packet = TEST_OTHER_PACKET[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES] + bad_checksum_bytes
#     with pytest.raises(SerialCommIncorrectChecksumFromInstrumentError) as exc_info:
#         sort_serial_packets(bytearray(bad_packet), 0)

#     expected_checksum = int.from_bytes(bad_packet[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:], byteorder="little")
#     assert str(bad_checksum) in exc_info.value.args[0]
#     assert str(expected_checksum) in exc_info.value.args[0]
#     assert str(bytearray(bad_packet)) in exc_info.value.args[0]


# def test_sort_serial_packets__does_not_parse_final_packet_if_it_is_not_complete():
#     test_num_data_packets = 1
#     expected_time_index = 10000

#     base_global_time = randint(0, 100)

#     data_packet_payload, expected_time_offsets, expected_data_points = create_data_stream_body(
#         expected_time_index + base_global_time
#     )
#     full_packet = create_data_packet(  # add one full packet
#         random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
#     )
#     incomplete_packet = create_data_packet(  # add one incomplete packet with arbitrary data
#         random_timestamp(), SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE, bytes(10)
#     )[:-1]
#     test_data_packet_bytes = full_packet + incomplete_packet

#     parsed_data_dict = sort_serial_packets(bytearray(test_data_packet_bytes), base_global_time)
#     actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
#         "magnetometer_data"
#     ].values()

#     expected_time_offsets = np.array(expected_time_offsets).reshape(
#         (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
#     )
#     expected_data_points = np.array(expected_data_points).reshape(
#         (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
#     )

#     np.testing.assert_array_equal(actual_time_indices, expected_time_index)
#     np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
#     np.testing.assert_array_equal(actual_data, expected_data_points)
#     assert num_data_packets_read == test_num_data_packets
#     assert parsed_data_dict["other_packet_info"] == []
#     assert parsed_data_dict["unread_bytes"] == incomplete_packet


# def test_sort_serial_packets__performance_test__magnetometer_data_only():
#     # One second of data, max sampling rate, all data channels on
#     # start:                                        1397497
#     # added time offsets + memory views:            2190868
#     # refactor before adding stim:                  3164056

#     num_us_of_data_to_send = MICRO_TO_BASE_CONVERSION
#     max_sampling_rate_us = 1000
#     test_num_data_packets = num_us_of_data_to_send // max_sampling_rate_us
#     expected_time_indices = list(range(0, num_us_of_data_to_send, max_sampling_rate_us))

#     test_data_packet_bytes = bytes(0)
#     expected_data_points = []
#     expected_time_offsets = []
#     for packet_num in range(test_num_data_packets):
#         data_packet_payload, test_offsets, test_data = create_data_stream_body(
#             expected_time_indices[packet_num]
#         )
#         test_data_packet_bytes += create_data_packet(
#             random_timestamp(), SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE, data_packet_payload
#         )
#         expected_data_points.extend(test_data)
#         expected_time_offsets.extend(test_offsets)
#     expected_time_offsets = np.array(expected_time_offsets).reshape(
#         (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
#     )
#     expected_data_points = np.array(expected_data_points).reshape(
#         (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
#     )

#     start = time.perf_counter_ns()
#     parsed_data_dict = sort_serial_packets(bytearray(test_data_packet_bytes), 0)
#     actual_time_indices, actual_time_offsets, actual_data, num_data_packets_read = parsed_data_dict[
#         "magnetometer_data"
#     ].values()
#     dur = time.perf_counter_ns() - start
#     # print(f"Dur (ns): {dur}, (seconds): {dur / 1e9}")  # pylint:disable=wrong-spelling-in-comment # Tanner (5/11/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization

#     assert dur < 1000000000
#     # good to also assert the entire second of data was parsed correctly
#     np.testing.assert_array_equal(
#         actual_time_indices, list(range(0, num_us_of_data_to_send, max_sampling_rate_us))
#     )
#     np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
#     np.testing.assert_array_equal(actual_data, expected_data_points)
#     assert num_data_packets_read == test_num_data_packets
#     assert parsed_data_dict["other_packet_info"] == []
#     assert parsed_data_dict["unread_bytes"] == bytes(0)


# def test_sort_serial_packets__parses_single_stim_data_packet_with_a_single_status_correctly():
#     base_global_time = randint(0, 100)
#     test_time_index = random_time_index()
#     test_well_idx = randint(0, 23)
#     test_subprotocol_idx = randint(0, 5)

#     stim_packet_payload = (
#         bytes([1])  # num status updates in packet
#         + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_idx]])
#         + bytes([StimProtocolStatuses.ACTIVE])
#         + test_time_index.to_bytes(8, byteorder="little")
#         + bytes([test_subprotocol_idx])
#     )
#     test_data_packet = create_data_packet(
#         random_timestamp(), SERIAL_COMM_STIM_STATUS_PACKET_TYPE, stim_packet_payload
#     )

#     parsed_data_dict = sort_serial_packets(bytearray(test_data_packet), base_global_time)
#     actual_stim_data = parsed_data_dict["stim_data"]
#     assert list(actual_stim_data.keys()) == [test_well_idx]
#     assert actual_stim_data[test_well_idx].dtype == np.int64
#     np.testing.assert_array_equal(
#         actual_stim_data[test_well_idx], [[test_time_index], [test_subprotocol_idx]]
#     )

#     # make sure no magnetometer data was returned
#     assert not any(parsed_data_dict["magnetometer_data"].values())


# def test_sort_serial_packets__parses_single_stim_data_packet_with_multiple_statuses_correctly():
#     base_global_time = randint(0, 100)
#     test_time_indices = [random_time_index(), random_time_index(), random_time_index()]
#     test_well_idx = randint(0, 23)
#     test_subprotocol_indices = [randint(0, 5), randint(0, 5), 0]
#     test_statuses = [StimProtocolStatuses.ACTIVE, StimProtocolStatuses.NULL, StimProtocolStatuses.RESTARTING]

#     stim_packet_payload = bytes([3])  # num status updates in packet
#     for packet_idx in range(3):
#         stim_packet_payload += (
#             bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_idx]])
#             + bytes([test_statuses[packet_idx]])
#             + test_time_indices[packet_idx].to_bytes(8, byteorder="little")
#             + bytes([test_subprotocol_indices[packet_idx]])
#         )
#     test_data_packet = create_data_packet(
#         random_timestamp(), SERIAL_COMM_STIM_STATUS_PACKET_TYPE, stim_packet_payload
#     )

#     parsed_data_dict = sort_serial_packets(bytearray(test_data_packet), base_global_time)
#     actual_stim_data = parsed_data_dict["stim_data"]
#     assert list(actual_stim_data.keys()) == [test_well_idx]
#     np.testing.assert_array_equal(
#         actual_stim_data[test_well_idx],
#         # removing last item in these lists since restarting status info is not needed
#         [np.array(test_time_indices[:-1]), test_subprotocol_indices[:-1]],
#     )


# def test_sort_serial_packets__parses_multiple_stim_data_packet_with_multiple_wells_and_statuses_correctly():
#     base_global_time = randint(0, 100)
#     test_well_indices = [randint(0, 11), randint(12, 23)]
#     test_time_indices = [
#         [random_time_index(), random_time_index()],
#         [random_time_index(), random_time_index(), random_time_index()],
#     ]
#     test_subprotocol_indices = [
#         [0, randint(1, 5)],
#         [randint(0, 5), randint(0, 5), STIM_COMPLETE_SUBPROTOCOL_IDX],
#     ]
#     test_statuses = [
#         [StimProtocolStatuses.RESTARTING, StimProtocolStatuses.NULL],
#         [StimProtocolStatuses.ACTIVE, StimProtocolStatuses.NULL, StimProtocolStatuses.FINISHED],
#     ]

#     stim_packet_payload_1 = (
#         bytes([2])  # num status updates in packet
#         + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[0]]])
#         + bytes([test_statuses[0][0]])
#         + test_time_indices[0][0].to_bytes(8, byteorder="little")
#         + bytes([test_subprotocol_indices[0][0]])
#         + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[1]]])
#         + bytes([test_statuses[1][0]])
#         + test_time_indices[1][0].to_bytes(8, byteorder="little")
#         + bytes([test_subprotocol_indices[1][0]])
#     )
#     stim_packet_payload_2 = (
#         bytes([3])  # num status updates in packet
#         + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[1]]])
#         + bytes([test_statuses[1][1]])
#         + test_time_indices[1][1].to_bytes(8, byteorder="little")
#         + bytes([test_subprotocol_indices[1][1]])
#         + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[0]]])
#         + bytes([test_statuses[0][1]])
#         + test_time_indices[0][1].to_bytes(8, byteorder="little")
#         + bytes([test_subprotocol_indices[0][1]])
#         + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[1]]])
#         + bytes([test_statuses[1][2]])
#         + test_time_indices[1][2].to_bytes(8, byteorder="little")
#         + bytes([test_subprotocol_indices[1][2]])
#     )
#     test_data_packet_1 = create_data_packet(
#         random_timestamp(), SERIAL_COMM_STIM_STATUS_PACKET_TYPE, stim_packet_payload_1
#     )
#     test_data_packet_2 = create_data_packet(
#         random_timestamp(), SERIAL_COMM_STIM_STATUS_PACKET_TYPE, stim_packet_payload_2
#     )

#     parsed_data_dict = sort_serial_packets(
#         bytearray(test_data_packet_1 + test_data_packet_2), base_global_time
#     )
#     actual_stim_data = parsed_data_dict["stim_data"]
#     assert sorted(list(actual_stim_data.keys())) == sorted(test_well_indices)
#     np.testing.assert_array_equal(
#         actual_stim_data[test_well_indices[0]],
#         # removing first item in these lists since restarting status info is not needed
#         [np.array(test_time_indices[0][1:]), test_subprotocol_indices[0][1:]],
#     )
#     np.testing.assert_array_equal(
#         actual_stim_data[test_well_indices[1]],
#         [np.array(test_time_indices[1]), test_subprotocol_indices[1]],
#     )
