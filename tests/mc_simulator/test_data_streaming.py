# -*- coding: utf-8 -*-
import csv
import os

from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MODULE_ID_INDEX
from mantarray_desktop_app import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app import SERIAL_COMM_PACKET_TYPE_INDEX
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from mantarray_file_manager import CENTIMILLISECONDS_PER_SECOND
import numpy as np
from scipy import interpolate
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import resource_path

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import fixture_runnable_mantarray_mc_simulator
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import get_full_packet_size_from_packet_body_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_runnable_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_MantarrayMcSimulator__get_interpolated_data_returns_correct_value(
    mantarray_mc_simulator,
):
    simulator = mantarray_mc_simulator["simulator"]

    relative_path = os.path.join("src", "simulated_data", "simulated_twitch.csv")
    absolute_path = os.path.normcase(os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir))
    file_path = resource_path(relative_path, base_path=absolute_path)
    with open(file_path, newline="") as csvfile:
        simulated_data_timepoints = next(csv.reader(csvfile, delimiter=","))
        simulated_data_values = next(csv.reader(csvfile, delimiter=","))

    test_sampling_period = 1000
    interpolator = interpolate.interp1d(
        np.array(simulated_data_timepoints, dtype=np.uint64) // MICROSECONDS_PER_CENTIMILLISECOND,
        simulated_data_values,
    )
    expected_data = interpolator(
        np.arange(
            0,
            CENTIMILLISECONDS_PER_SECOND,
            test_sampling_period // MICROSECONDS_PER_CENTIMILLISECOND,
            dtype=np.uint64,
        )
    ).astype(np.int16)

    actual_data = simulator.get_interpolated_data(test_sampling_period)
    np.testing.assert_array_equal(actual_data, expected_data)


def test_MantarrayMcSimulator__sends_correct_time_index_and_data_points_in_first_three_data_packets__when_all_wells_have_same_config(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_sampling_period = 1000
    test_counter_us = [
        0,  # 0 first so that no packets are created on the iteration that starts the data stream
        int(test_sampling_period * 1.5),
        test_sampling_period * 3,
    ]
    mocker.patch.object(
        mc_simulator,
        "_perf_counter_us",
        autospec=True,
        side_effect=test_counter_us,
    )

    # set up arbitrary magnetometer configuration
    num_wells = simulator.get_num_wells()
    test_channels = [
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"],
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Y"],
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"],
    ]
    magnetometer_config_dict = simulator.get_magnetometer_config()
    for module_id in range(1, num_wells + 1):
        magnetometer_config_dict[module_id] = {
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: True,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Y"]: False,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Z"]: False,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["X"]: False,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Y"]: True,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Z"]: False,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["X"]: False,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Y"]: False,
            SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: True,
        }

    # set up data stream (no packets created yet)
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "set_data_streaming_status",
            "sampling_period": test_sampling_period,
            "data_streaming_status": True,
        },
        testing_queue,
    )
    # create packets
    invoke_process_run_and_check_errors(simulator, num_iterations=2)

    data_packet_size = get_full_packet_size_from_packet_body_size(
        SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
        + ((2 + SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES) * num_wells * len(test_channels))
    )
    data_packets = [
        simulator.read(size=data_packet_size),
        simulator.read(size=data_packet_size),
        simulator.read(size=data_packet_size),
    ]
    assert simulator.in_waiting == 0

    expected_waveform = simulator.get_interpolated_data(test_sampling_period)
    for packet_num, data_packet in enumerate(data_packets):
        assert (
            data_packet[SERIAL_COMM_MODULE_ID_INDEX] == SERIAL_COMM_MAIN_MODULE_ID
        ), f"Incorrect module ID in packet {packet_num + 1}"
        assert (
            data_packet[SERIAL_COMM_PACKET_TYPE_INDEX] == SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
        ), f"Incorrect packet type in packet {packet_num + 1}"

        idx = SERIAL_COMM_ADDITIONAL_BYTES_INDEX
        time_index = int.from_bytes(
            data_packet[idx : idx + SERIAL_COMM_TIME_INDEX_LENGTH_BYTES], byteorder="little"
        )
        expected_time_index = (packet_num * test_sampling_period) // MICROSECONDS_PER_CENTIMILLISECOND
        assert time_index == expected_time_index, f"Incorrect time index in packet {packet_num + 1}"

        idx += SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
        for well_idx in range(num_wells):
            expected_sensor_value = expected_waveform[packet_num] * (well_idx + 1)
            for channel_id in test_channels:
                # test offset value (always 0 for simulator)
                offset_value = int.from_bytes(
                    data_packet[idx : idx + SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES], byteorder="little"
                )
                assert (
                    offset_value == 0
                ), f"Incorrect offset value for channel ID {channel_id} well {well_idx} in packet {packet_num + 1}"
                idx += SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
                # test sensor value
                sensor_value = int.from_bytes(data_packet[idx : idx + 2], byteorder="little", signed=True)
                assert (
                    sensor_value == expected_sensor_value
                ), f"Incorrect sensor value for channel ID {channel_id} well {well_idx} in packet {packet_num + 1}"
                idx += 2
        # make the whole data body was tested
        assert (
            idx == data_packet_size - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
        ), f"missing assertions for packet body of packet {packet_num + 1}"


def test_MantarrayMcSimulator__returns_correctly_formatted_data_packet_with_wells_that_have_different_configs(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_sampling_period = 1000
    test_counter_us = [
        0,  # 0 first so that no packets are created on the iteration that starts the data stream
        test_sampling_period,
    ]
    mocker.patch.object(
        mc_simulator,
        "_perf_counter_us",
        autospec=True,
        side_effect=test_counter_us,
    )
    # set up arbitrary magnetometer configuration
    magnetometer_config_dict = simulator.get_magnetometer_config()
    magnetometer_config_dict[1] = {
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Y"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Z"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["X"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Y"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Z"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["X"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Y"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: False,
    }
    magnetometer_config_dict[2] = {
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Y"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["Z"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["X"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Y"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["B"]["Z"]: False,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["X"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Y"]: True,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: False,
    }
    num_wells_enabled = 2
    num_sensors_enabled = 5  # three on module 1, two on module 2
    num_channels_enabled = sum(magnetometer_config_dict[1].values()) + sum(
        magnetometer_config_dict[2].values()
    )

    # set up data stream (no packets created yet)
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    expected_data_idx = 10  # picking this value to test a different sample point from the simulated data where the amplitude is larger
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "set_data_streaming_status",
            "sampling_period": test_sampling_period,
            "data_streaming_status": True,
            "simulated_data_index": expected_data_idx,
        },
        testing_queue,
    )
    # create packet
    invoke_process_run_and_check_errors(simulator)

    data_packet_size = get_full_packet_size_from_packet_body_size(
        SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
        + (SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES * num_sensors_enabled)
        + (num_channels_enabled * 2)
    )
    data_packet = simulator.read(size=data_packet_size)
    assert simulator.in_waiting == 0, simulator.read(size=simulator.in_waiting)

    # test data packet IDs
    assert data_packet[SERIAL_COMM_MODULE_ID_INDEX] == SERIAL_COMM_MAIN_MODULE_ID
    assert data_packet[SERIAL_COMM_PACKET_TYPE_INDEX] == SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
    # test time index
    idx = SERIAL_COMM_ADDITIONAL_BYTES_INDEX
    time_index = int.from_bytes(
        data_packet[idx : idx + SERIAL_COMM_TIME_INDEX_LENGTH_BYTES], byteorder="little"
    )
    assert time_index == 0
    idx += SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
    # test offsets and data points
    expected_waveform = simulator.get_interpolated_data(test_sampling_period)
    for well_idx in range(num_wells_enabled):
        config_values = list(magnetometer_config_dict[well_idx + 1].values())
        expected_sensor_value = expected_waveform[expected_data_idx] * (well_idx + 1)
        for sensor_base_idx in range(0, SERIAL_COMM_NUM_DATA_CHANNELS, SERIAL_COMM_NUM_SENSORS_PER_WELL):
            if not any(config_values[sensor_base_idx : sensor_base_idx + SERIAL_COMM_NUM_SENSORS_PER_WELL]):
                continue
            # test offset value (always 0 for simulator)
            offset_value = int.from_bytes(
                data_packet[idx : idx + SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES], byteorder="little"
            )
            assert (
                offset_value == 0
            ), f"Incorrect offset value for sensor {sensor_base_idx // SERIAL_COMM_NUM_SENSORS_PER_WELL} well {well_idx}"
            idx += SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
            for axis_idx in range(SERIAL_COMM_NUM_CHANNELS_PER_SENSOR):
                channel_id = sensor_base_idx + axis_idx
                if not config_values[channel_id]:
                    continue
                sensor_value = int.from_bytes(data_packet[idx : idx + 2], byteorder="little", signed=True)
                assert (
                    sensor_value == expected_sensor_value
                ), f"Incorrect sensor value for channel ID {channel_id} well {well_idx}"
                idx += 2
    # make the whole data body was tested
    assert idx == data_packet_size - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
