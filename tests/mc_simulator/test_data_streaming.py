# -*- coding: utf-8 -*-
import csv
import os

from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from mantarray_desktop_app import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MODULE_ID_INDEX
from mantarray_desktop_app import SERIAL_COMM_PACKET_TYPE_INDEX
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
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
    absolute_path = os.path.normcase(
        os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir)
    )
    file_path = resource_path(relative_path, base_path=absolute_path)
    with open(file_path, newline="") as csvfile:
        simulated_data_timepoints = next(csv.reader(csvfile, delimiter=","))
        simulated_data_values = next(csv.reader(csvfile, delimiter=","))

    test_sampling_period = 1000
    expected_data = interpolate.interp1d(
        np.array(simulated_data_timepoints, dtype=np.uint64)
        // MICROSECONDS_PER_CENTIMILLISECOND,
        simulated_data_values,
    )(
        np.arange(
            0,
            CENTIMILLISECONDS_PER_SECOND,
            test_sampling_period // MICROSECONDS_PER_CENTIMILLISECOND,
            dtype=np.uint64,
        )
    ).astype(
        np.int16
    )

    actual_data = simulator.get_interpolated_data(test_sampling_period)
    np.testing.assert_array_equal(actual_data, expected_data)


def test_MantarrayMcSimulator__sends_correct_timestamp_offset_and_data_points_in_first_two_data_packets(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_sampling_period = 1000
    test_us_since_last_data_packet = int(test_sampling_period * 2.5)
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        return_value=test_us_since_last_data_packet,
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

    # set up data stream and create first data packet
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "command": "set_data_streaming_status",
            "data_streaming_status": True,
            "sampling_period": test_sampling_period,
        },
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    data_packet_size = get_full_packet_size_from_packet_body_size(
        2 + (2 * num_wells * len(test_channels))  # 2 for timestamp offset
    )
    first_data_packet = simulator.read(size=data_packet_size)
    second_data_packet = simulator.read(size=data_packet_size)

    expected_waveform = simulator.get_interpolated_data(test_sampling_period)
    for packet_num, data_packet in enumerate((first_data_packet, second_data_packet)):
        assert (
            data_packet[SERIAL_COMM_MODULE_ID_INDEX] == SERIAL_COMM_MAIN_MODULE_ID
        ), f"Incorrect module ID in packet {packet_num + 1}"
        assert (
            data_packet[SERIAL_COMM_PACKET_TYPE_INDEX]
            == SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
        ), f"Incorrect packet type in packet {packet_num + 1}"

        idx = SERIAL_COMM_ADDITIONAL_BYTES_INDEX

        expected_offset = (
            test_us_since_last_data_packet - (packet_num + 1) * test_sampling_period
        ) // MICROSECONDS_PER_CENTIMILLISECOND
        timestamp_offset = int.from_bytes(
            data_packet[idx : idx + 2], byteorder="little"
        )
        assert (
            timestamp_offset == expected_offset
        ), f"Incorrect timestamp offset in packet {packet_num + 1}"
        for well_idx in range(num_wells):
            expected_sensor_value = expected_waveform[packet_num] * (well_idx + 1)
            for channel_id in test_channels:
                idx += 2
                sensor_value = int.from_bytes(
                    data_packet[idx : idx + 2], byteorder="little", signed=True
                )
                assert (
                    sensor_value == expected_sensor_value
                ), f"Incorrect sensor value for channel ID {channel_id} well {well_idx} in packet {packet_num + 1}"
