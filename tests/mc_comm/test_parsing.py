# -*- coding: utf-8 -*-
from random import choice
from random import randint
import time

from immutabledict import immutabledict
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import parse_magnetometer_data
from mantarray_desktop_app import parse_stim_data
from mantarray_desktop_app import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from mantarray_desktop_app import sort_serial_packets
from mantarray_desktop_app import STIM_COMPLETE_SUBPROTOCOL_IDX
from mantarray_desktop_app import StimProtocolStatuses
from mantarray_desktop_app.constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from mantarray_desktop_app.constants import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from mantarray_desktop_app.constants import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app.constants import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app.constants import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app.constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app.constants import STIM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app.exceptions import SerialCommIncorrectChecksumFromInstrumentError
from mantarray_desktop_app.exceptions import SerialCommIncorrectMagicWordFromMantarrayError
import numpy as np
import pytest

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import random_data_value
from ..fixtures_mc_simulator import random_time_index
from ..fixtures_mc_simulator import random_time_offset
from ..fixtures_mc_simulator import random_timestamp

__fixtures__ = [fixture_patch_print]


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
    # sort_serial_packets won't parse payload, so can make it arbitrary bytes
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
        "num_packets_sorted": 1,
    }


def test_sort_serial_packets__sorts_single_non_stream_packet_correctly():
    sorted_packet_dict = sort_serial_packets(bytearray(TEST_OTHER_PACKET))
    assert sorted_packet_dict == {
        "magnetometer_stream_info": dict(UNPOPULATED_STREAM_DICT),
        "stim_stream_info": dict(UNPOPULATED_STREAM_DICT),
        "other_packet_info": [TEST_OTHER_PACKET_INFO],
        "unread_bytes": bytearray(0),
        "num_packets_sorted": 1,
    }


def test_sort_serial_packets__sorts_incomplete_packet():
    incomplete_packet = TEST_OTHER_PACKET[:-1]
    sorted_packet_dict = sort_serial_packets(bytearray(incomplete_packet))
    assert sorted_packet_dict == {
        "magnetometer_stream_info": dict(UNPOPULATED_STREAM_DICT),
        "stim_stream_info": dict(UNPOPULATED_STREAM_DICT),
        "other_packet_info": [],
        "unread_bytes": bytearray(incomplete_packet),
        "num_packets_sorted": 0,
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
        "num_packets_sorted": 6,
    }


def test_sort_serial_packets__raises_error_when_packet_from_instrument_has_incorrect_magic_word(
    patch_print,
):
    bad_magic_word_bytes = b"NOT CURI"
    bad_packet = bad_magic_word_bytes + TEST_OTHER_PACKET[len(SERIAL_COMM_MAGIC_WORD_BYTES) :]
    with pytest.raises(SerialCommIncorrectMagicWordFromMantarrayError, match=str(bad_magic_word_bytes)):
        sort_serial_packets(bytearray(bad_packet))


def test_sort_serial_packets__raises_error_when_packet_from_instrument_has_incorrect_crc32_checksum(
    patch_print,
):
    bad_checksum = 0
    bad_checksum_bytes = bad_checksum.to_bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little")
    bad_packet = TEST_OTHER_PACKET[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES] + bad_checksum_bytes
    with pytest.raises(SerialCommIncorrectChecksumFromInstrumentError) as exc_info:
        sort_serial_packets(bytearray(bad_packet))

    expected_checksum = int.from_bytes(bad_packet[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:], byteorder="little")
    assert str(bad_checksum) in exc_info.value.args[0]
    assert str(expected_checksum) in exc_info.value.args[0]
    assert str(bytearray(bad_packet)) in exc_info.value.args[0]


def test_parse_magnetometer_data__handles_two_mag_data_packets_correctly__and_assigns_correct_data_type_to_parsed_values__when_all_channels_enabled():
    expected_time_indices = [0xFFFFFFFFFFFFFF00, 0xFFFFFFFFFFFFFF01]
    test_num_data_packets = len(expected_time_indices)

    base_global_time = randint(0, 100)

    test_mag_data_bytes = bytearray(0)
    expected_data_points = []
    expected_time_offsets = []
    for time_idx in expected_time_indices:
        data_packet_payload, test_offsets, test_data = create_data_stream_body(time_idx + base_global_time)
        test_mag_data_bytes += data_packet_payload
        expected_data_points.extend(test_data)
        expected_time_offsets.extend(test_offsets)
    expected_time_offsets = np.array(expected_time_offsets).reshape(
        (len(expected_time_offsets) // test_num_data_packets, test_num_data_packets), order="F"
    )
    expected_data_points = np.array(expected_data_points).reshape(
        (len(expected_data_points) // test_num_data_packets, test_num_data_packets), order="F"
    )

    parsed_mag_data_dict = parse_magnetometer_data(
        test_mag_data_bytes, test_num_data_packets, base_global_time
    )
    actual_time_indices, actual_time_offsets, actual_data = parsed_mag_data_dict.values()

    assert actual_time_indices.dtype == np.uint64
    assert actual_time_offsets.dtype == np.uint16
    assert actual_data.dtype == np.uint16
    np.testing.assert_array_equal(actual_time_indices, expected_time_indices)
    np.testing.assert_array_equal(actual_time_offsets, expected_time_offsets)
    np.testing.assert_array_equal(actual_data, expected_data_points)


def test_parse_stim_data__parses_single_stim_data_packet_with_a_single_status_correctly():
    test_num_stim_packets = 1

    test_time_index = random_time_index()
    test_well_idx = randint(0, 23)
    test_subprotocol_idx = randint(0, 5)

    stim_packet_payload = bytearray(
        bytes([1])  # num status updates in packet
        + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_idx]])
        + bytes([StimProtocolStatuses.ACTIVE])
        + test_time_index.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little")
        + bytes([test_subprotocol_idx])
    )

    actual_stim_data = parse_stim_data(stim_packet_payload, test_num_stim_packets)
    assert list(actual_stim_data.keys()) == [test_well_idx]
    assert actual_stim_data[test_well_idx].dtype == np.int64
    np.testing.assert_array_equal(
        actual_stim_data[test_well_idx], [[test_time_index], [test_subprotocol_idx]]
    )


def test_parse_stim_data__parses_single_stim_data_packet_with_multiple_statuses_correctly():
    test_num_stim_packets = 1

    test_well_idx = randint(0, 23)

    test_statuses = [StimProtocolStatuses.ACTIVE, StimProtocolStatuses.NULL, StimProtocolStatuses.RESTARTING]
    test_time_indices = [random_time_index() for _ in range(len(test_statuses))]
    test_subprotocol_indices = [randint(0, 5), randint(0, 5), 0]

    stim_packet_payload = bytearray([len(test_statuses)])  # num status updates in packet
    for status, time_idx, subprotocol_idx in zip(test_statuses, test_time_indices, test_subprotocol_indices):
        stim_packet_payload += (
            bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_idx]])
            + bytes([status])
            + time_idx.to_bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little")
            + bytes([subprotocol_idx])
        )

    actual_stim_data = parse_stim_data(stim_packet_payload, test_num_stim_packets)
    assert list(actual_stim_data.keys()) == [test_well_idx]
    np.testing.assert_array_equal(
        actual_stim_data[test_well_idx],
        # removing last item in these lists since restarting status info is not included
        [np.array(test_time_indices[:-1]), test_subprotocol_indices[:-1]],
    )


def test_parse_stim_data__parses_multiple_stim_data_packet_with_multiple_wells_and_statuses_correctly():
    test_num_stim_packets = 2

    test_well_indices = [randint(0, 11), randint(12, 23)]
    test_subprotocol_indices = [
        [0, randint(1, 5)],
        [randint(0, 5), randint(0, 5), STIM_COMPLETE_SUBPROTOCOL_IDX],
    ]
    test_statuses = [
        [StimProtocolStatuses.RESTARTING, StimProtocolStatuses.NULL],
        [StimProtocolStatuses.ACTIVE, StimProtocolStatuses.NULL, StimProtocolStatuses.FINISHED],
    ]
    test_time_indices = [[random_time_index() for _ in range(len(statuses))] for statuses in test_statuses]

    stim_packet_payload_1 = bytearray(
        bytes([2])  # num status updates in packet
        + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[0]]])
        + bytes([test_statuses[0][0]])
        + test_time_indices[0][0].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[0][0]])
        + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[1]]])
        + bytes([test_statuses[1][0]])
        + test_time_indices[1][0].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[1][0]])
    )
    stim_packet_payload_2 = bytearray(
        bytes([3])  # num status updates in packet
        + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[1]]])
        + bytes([test_statuses[1][1]])
        + test_time_indices[1][1].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[1][1]])
        + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[0]]])
        + bytes([test_statuses[0][1]])
        + test_time_indices[0][1].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[0][1]])
        + bytes([STIM_WELL_IDX_TO_MODULE_ID[test_well_indices[1]]])
        + bytes([test_statuses[1][2]])
        + test_time_indices[1][2].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[1][2]])
    )

    actual_stim_data = parse_stim_data(stim_packet_payload_1 + stim_packet_payload_2, test_num_stim_packets)
    assert set(actual_stim_data.keys()) == set(test_well_indices)
    np.testing.assert_array_equal(
        actual_stim_data[test_well_indices[0]],
        # removing first item in these lists since restarting status info is not needed
        [np.array(test_time_indices[0][1:]), test_subprotocol_indices[0][1:]],
    )
    np.testing.assert_array_equal(
        actual_stim_data[test_well_indices[1]],
        [np.array(test_time_indices[1]), test_subprotocol_indices[1]],
    )


def test_performance__magnetometer_data_sorting_and_parsing():
    # One second of data, max sampling rate, all data channels on.
    # Results in ns
    #
    # start:                                        1397497
    # added time offsets + memory views:            2190868
    # refactor before adding stim:                  3164056
    #
    # This was previously testing a single function, but it has since been split into
    # two separate functions. Testing should now be done on the new functions, but
    # keeping this here to show the split did not degrade performance
    #
    # refactor into sort and parse:                 2317237

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
    sorted_packet_dict = sort_serial_packets(bytearray(test_data_packet_bytes))
    parsed_mag_data_dict = parse_magnetometer_data(
        *sorted_packet_dict["magnetometer_stream_info"].values(), 0
    )
    actual_time_indices, actual_time_offsets, actual_data = parsed_mag_data_dict.values()
    dur = time.perf_counter_ns() - start
    # print(f"Dur (ns): {dur}, (seconds): {dur / 1e9}")  # Tanner (5/11/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization

    assert dur < 1000000000


def test_sort_serial_packets__performance_test__magnetometer_data_only():
    # One second of data, max sampling rate, all data channels on.
    # Results in ns
    #
    # start:                                        1231030

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
    sort_serial_packets(bytearray(test_data_packet_bytes))
    dur = time.perf_counter_ns() - start
    # print(f"Dur (ns): {dur}, (seconds): {dur / 1e9}")  # Tanner (5/11/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization

    assert dur < 1000000000


def test_parse_magnetometer_data__performance_test():
    # One second of data, max sampling rate, all data channels on.
    # Results in ns
    #
    # start:                                        1517561

    num_us_of_data_to_send = MICRO_TO_BASE_CONVERSION
    max_sampling_rate_us = 1000
    test_num_data_packets = num_us_of_data_to_send // max_sampling_rate_us
    expected_time_indices = list(range(0, num_us_of_data_to_send, max_sampling_rate_us))

    mag_data_bytes = bytearray(0)
    for packet_num in range(test_num_data_packets):
        data_packet_payload, *_ = create_data_stream_body(expected_time_indices[packet_num])
        mag_data_bytes += data_packet_payload

    start = time.perf_counter_ns()
    parse_magnetometer_data(mag_data_bytes, test_num_data_packets, 0)
    dur = time.perf_counter_ns() - start
    # print(f"Dur (ns): {dur}, (seconds): {dur / 1e9}")  # Tanner (5/11/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization

    assert dur < 1000000000
