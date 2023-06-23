# -*- coding: utf-8 -*-
import csv
import os

from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_DATA_SAMPLE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from mantarray_desktop_app import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from mantarray_desktop_app import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app import SERIAL_COMM_PACKET_TYPE_INDEX
from mantarray_desktop_app import SERIAL_COMM_PAYLOAD_INDEX
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from mantarray_desktop_app.simulators import mc_simulator
import numpy as np
from scipy import interpolate
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import resource_path

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import fixture_runnable_mantarray_mc_simulator
from ..helpers import get_full_packet_size_from_payload_len
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_runnable_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator_no_beacon,
]


ORDERED_AXES = list(list(SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE.values())[0].keys())


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
        np.array(simulated_data_timepoints, dtype=np.uint64),
        simulated_data_values,
    )
    expected_data = interpolator(
        np.arange(0, MICRO_TO_BASE_CONVERSION, test_sampling_period, dtype=np.uint64)
    ).astype(np.uint16)

    actual_data = simulator.get_interpolated_data(test_sampling_period)
    assert actual_data.dtype == np.uint16
    np.testing.assert_array_equal(actual_data, expected_data)


def test_MantarrayMcSimulator__sends_correct_time_index_and_data_points_in_first_three_data_packets__when_all_wells_and_channels_enabled(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    num_wells = simulator._num_wells
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

    spied_get_global_timer = mocker.spy(simulator, "_get_global_timer")

    # set up data stream (no packets created yet)
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

    magnetometer_data_len = SERIAL_COMM_TIME_INDEX_LENGTH_BYTES + (
        (
            SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
            + (SERIAL_COMM_DATA_SAMPLE_LENGTH_BYTES * SERIAL_COMM_NUM_CHANNELS_PER_SENSOR)
        )
        * num_wells
        * SERIAL_COMM_NUM_SENSORS_PER_WELL
    )
    data_packet_size = get_full_packet_size_from_payload_len(magnetometer_data_len)
    data_packets = [simulator.read(size=data_packet_size) for _ in range(3)]
    assert simulator.in_waiting == 0

    expected_waveform = simulator.get_interpolated_data(test_sampling_period)
    for packet_num, data_packet in enumerate(data_packets):
        assert (
            data_packet[SERIAL_COMM_PACKET_TYPE_INDEX] == SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
        ), f"Incorrect packet type in packet {packet_num + 1}"

        idx = SERIAL_COMM_PAYLOAD_INDEX
        time_index = int.from_bytes(
            data_packet[idx : idx + SERIAL_COMM_TIME_INDEX_LENGTH_BYTES], byteorder="little"
        )
        expected_time_index = spied_get_global_timer.spy_return + packet_num * test_sampling_period
        assert time_index == expected_time_index, f"Incorrect time index in packet {packet_num + 1}"

        idx += SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
        for module_id in range(num_wells):
            well_idx = SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id]
            expected_sensor_value = expected_waveform[packet_num] * (well_idx + 1)
            for sensor_num in range(1, SERIAL_COMM_NUM_CHANNELS_PER_SENSOR + 1):
                # test offset value (always 0 for simulator)
                offset_value = int.from_bytes(
                    data_packet[idx : idx + SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES], byteorder="little"
                )
                assert (
                    offset_value == 0
                ), f"Incorrect offset value for sensor {sensor_num} of module ID {module_id} in packet {packet_num + 1}"
                idx += SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
                for axis in ORDERED_AXES:
                    # test sensor value
                    sensor_value = int.from_bytes(data_packet[idx : idx + 2], byteorder="little", signed=True)
                    assert (
                        sensor_value == expected_sensor_value
                    ), f"Incorrect sensor value for {axis}-axis of sensor {sensor_num} of module ID {module_id} in packet {packet_num + 1}"
                    idx += SERIAL_COMM_DATA_SAMPLE_LENGTH_BYTES
        # make the whole data body was tested
        assert (
            idx == data_packet_size - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
        ), f"missing assertions for packet body of packet {packet_num + 1}"
