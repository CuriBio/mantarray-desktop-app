# -*- coding: utf-8 -*-
import copy
import datetime

from mantarray_desktop_app import get_stimulation_dataset_from_file
from mantarray_desktop_app import get_time_index_dataset_from_file
from mantarray_desktop_app import get_time_offset_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
import numpy as np
from pulse3D.constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from pulse3D.constants import UTC_FIRST_TISSUE_DATA_POINT_UUID
import pytest
from stdlib_utils import confirm_parallelism_is_stopped
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import fixture_runnable_four_board_file_writer_process
from ..fixtures_file_writer import fixture_running_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_NUM_CHANNELS_ENABLED
from ..fixtures_file_writer import GENERIC_NUM_SENSORS_ENABLED
from ..fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND
from ..fixtures_file_writer import open_the_generic_h5_file
from ..fixtures_file_writer import populate_calibration_folder
from ..helpers import assert_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..parsed_channel_data_packets import SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS
from ..parsed_channel_data_packets import SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS


__fixtures__ = [
    fixture_four_board_file_writer_process,
    fixture_running_four_board_file_writer_process,
    fixture_runnable_four_board_file_writer_process,
]


def create_simple_1d_array(start_timepoint, num_data_points, dtype):
    return np.arange(start_timepoint, start_timepoint + num_data_points, dtype=dtype)


def create_simple_2d_array(start_timepoint, num_data_points, dtype, step=1):
    return np.array(
        [
            np.arange(start_timepoint, start_timepoint + (num_data_points * step), step, dtype=dtype),
            np.arange(start_timepoint, start_timepoint + (num_data_points * step), step, dtype=dtype),
        ]
    )


def create_simple_magnetometer_well_dict(start_timepoint, num_data_points):
    test_value_arr = create_simple_1d_array(start_timepoint, num_data_points, np.uint16)
    return {
        "time_offsets": create_simple_2d_array(start_timepoint, num_data_points, np.uint16) * 2,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: test_value_arr * 3,
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: test_value_arr * 4,
    }


def create_simple_data_packet(
    time_index_start, data_start, well_idxs, num_data_points, is_first_packet_of_stream=False
):
    if isinstance(well_idxs, int):
        well_idxs = [well_idxs]
    data_packet = {
        "data_type": "magnetometer",
        "time_indices": create_simple_1d_array(time_index_start, num_data_points, np.uint64),
        "is_first_packet_of_stream": is_first_packet_of_stream,
    }
    for idx in well_idxs:
        data_packet[idx] = create_simple_magnetometer_well_dict(data_start, num_data_points)
    return data_packet


def create_simple_stim_packet(time_index_start, num_data_points, is_first_packet_of_stream=False, step=1):
    stim_packet = {
        "data_type": "stimulation",
        "well_statuses": {
            well_idx: create_simple_2d_array(time_index_start, num_data_points, np.int64, step=step)
            for well_idx in range(24)
        },
        "is_first_packet_of_stream": is_first_packet_of_stream,
    }
    return stim_packet


@pytest.mark.timeout(15)
@pytest.mark.slow
def test_FileWriterProcess__passes_magnetometer_data_packet_through_to_output_queue_correctly(
    runnable_four_board_file_writer_process,
):
    fw_process = runnable_four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    incoming_data_queue = runnable_four_board_file_writer_process["board_queues"][0][0]
    outgoing_data_queue = runnable_four_board_file_writer_process["board_queues"][0][1]
    error_queue = runnable_four_board_file_writer_process["error_queue"]

    test_data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)

    fw_process.start()  # start it after the queue has been populated so that the process will certainly see the object in the queue
    fw_process.soft_stop()
    confirm_parallelism_is_stopped(fw_process, timeout_seconds=15)
    assert_queue_is_eventually_empty(error_queue)

    out_packet = outgoing_data_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    np.testing.assert_array_equal(out_packet["time_indices"], test_data_packet["time_indices"])
    for well_idx in range(24):
        for channel_id, expected_data in test_data_packet[well_idx].items():
            np.testing.assert_array_equal(
                out_packet[well_idx][channel_id],
                expected_data,
                err_msg=f"Incorrect data for well {well_idx}, channel id {channel_id}",
            )

    # clean up
    fw_process.hard_stop()
    fw_process.join()


def test_FileWriterProcess__does_not_pass_magnetometer_data_packet_through_to_output_queue_after_stop_managed_acquisition_command_received(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # stop data stream
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(STOP_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)
    # send stim packet and make sure it is not passed through
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS), board_queues[0]
    )
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(board_queues[1])


@pytest.mark.timeout(4)
def test_FileWriterProcess__does_not_pass_magnetometer_data_packet_through_to_output_queue_when_making_calibration_recording(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # start calibration
    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["is_calibration_recording"] = True
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    # send magnetometer data packet
    test_data_packet = create_simple_data_packet(
        start_recording_command["timepoint_to_begin_recording_at"],
        0,
        start_recording_command["active_well_indices"],
        10,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0][0])
    # make sure packet was not passed through
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(board_queues[0][1])


def test_FileWriterProcess_process_magnetometer_data_packet__writes_data_if_the_whole_data_chunk_is_at_the_timestamp_idx__and_sets_timestamp_metadata_for_tissue_since_this_is_first_piece_of_data(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [3]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 50
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_data_packet(
        start_timepoint,
        0,
        start_recording_command["active_well_indices"],
        num_data_points,
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)
    this_file = open_the_generic_h5_file(file_dir, well_name="D1", beta_version=2)

    expected_timestamp = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ] + datetime.timedelta(seconds=start_timepoint / MICRO_TO_BASE_CONVERSION)
    assert this_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == expected_timestamp.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    actual_time_index_data = get_time_index_dataset_from_file(this_file)
    assert actual_time_index_data.shape == (num_data_points,)
    assert actual_time_index_data[0] == start_timepoint
    actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
    assert actual_time_offset_data.shape == (GENERIC_NUM_SENSORS_ENABLED, num_data_points)
    assert actual_time_offset_data[0, 8] == 8 * 2
    assert actual_time_offset_data[1, 5] == 5 * 2
    actual_tissue_data = get_tissue_dataset_from_file(this_file)
    assert actual_tissue_data.shape == (GENERIC_NUM_CHANNELS_ENABLED, num_data_points)
    assert actual_tissue_data[0, 8] == 8 * 3
    assert actual_tissue_data[1, 5] == 5 * 4
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_magnetometer_data_packet__writes_data_if_the_timestamp_idx_starts_part_way_through_the_chunk__and_sets_timestamp_metadata_for_tissue_since_this_is_first_piece_of_data(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    total_num_data_points = 75
    num_recorded_data_points = 50
    time_index_offset = total_num_data_points - num_recorded_data_points
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"] - time_index_offset
    test_data_packet = create_simple_data_packet(
        start_timepoint,
        0,
        start_recording_command["active_well_indices"],
        total_num_data_points,
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    expected_timestamp = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ] + datetime.timedelta(
        seconds=(start_recording_command["timepoint_to_begin_recording_at"]) / MICRO_TO_BASE_CONVERSION
    )

    this_file = open_the_generic_h5_file(file_dir, beta_version=2)
    assert this_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == expected_timestamp.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    actual_time_index_data = get_time_index_dataset_from_file(this_file)
    assert actual_time_index_data.shape == (num_recorded_data_points,)
    assert actual_time_index_data[0] == start_timepoint + time_index_offset
    actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
    assert actual_time_offset_data.shape == (GENERIC_NUM_SENSORS_ENABLED, num_recorded_data_points)
    assert actual_time_offset_data[0, 9] == (9 + time_index_offset) * 2
    assert actual_time_offset_data[1, 6] == (6 + time_index_offset) * 2
    actual_tissue_data = get_tissue_dataset_from_file(this_file)
    assert actual_tissue_data.shape == (GENERIC_NUM_CHANNELS_ENABLED, num_recorded_data_points)
    assert actual_tissue_data[0, 9] == (9 + time_index_offset) * 3
    assert actual_tissue_data[1, 6] == (6 + time_index_offset) * 4
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_magnetometer_data_packet__does_not_write_data_if_data_chunk_is_all_before_the_timestamp_idx(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    num_data_points = 30
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"] - num_data_points
    test_data_packet = create_simple_data_packet(
        start_timepoint,
        0,
        start_recording_command["active_well_indices"],
        num_data_points,
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    this_file = open_the_generic_h5_file(file_dir, beta_version=2)
    assert str(UTC_FIRST_TISSUE_DATA_POINT_UUID) not in this_file.attrs
    actual_time_index_data = get_time_index_dataset_from_file(this_file)
    assert actual_time_index_data.shape == (0,)
    actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
    assert actual_time_offset_data.shape == (GENERIC_NUM_SENSORS_ENABLED, 0)
    actual_tissue_data = get_tissue_dataset_from_file(this_file)
    assert actual_tissue_data.shape == (GENERIC_NUM_CHANNELS_ENABLED, 0)
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_magnetometer_data_packet__writes_data_for_two_packets_when_the_timestamp_idx_starts_part_way_through_the_first_packet__and_sets_timestamp_metadata_for_tissue_since_this_is_first_piece_of_data(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    total_num_data_points_1 = 40
    num_recorded_data_points_1 = 31
    time_index_offset = total_num_data_points_1 - num_recorded_data_points_1
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"] - time_index_offset
    first_data_packet = create_simple_data_packet(
        start_timepoint,
        0,
        start_recording_command["active_well_indices"],
        total_num_data_points_1,
    )
    num_data_points_2 = 15
    second_data_packet = create_simple_data_packet(
        start_timepoint + total_num_data_points_1,
        total_num_data_points_1,
        start_recording_command["active_well_indices"],
        num_data_points_2,
    )
    handle_putting_multiple_objects_into_empty_queue(
        [first_data_packet, second_data_packet], board_queues[0][0]
    )
    invoke_process_run_and_check_errors(fw_process, num_iterations=2)

    num_recorded_data_points = num_recorded_data_points_1 + num_data_points_2

    this_file = open_the_generic_h5_file(file_dir, beta_version=2)
    expected_timestamp = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ] + datetime.timedelta(
        seconds=(start_recording_command["timepoint_to_begin_recording_at"]) / MICRO_TO_BASE_CONVERSION
    )
    assert this_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == expected_timestamp.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    actual_time_index_data = get_time_index_dataset_from_file(this_file)
    assert actual_time_index_data.shape == (num_recorded_data_points,)
    assert actual_time_index_data[0] == start_timepoint + time_index_offset
    assert actual_time_index_data[-1] == start_timepoint + time_index_offset + num_recorded_data_points - 1
    actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
    assert actual_time_offset_data.shape == (GENERIC_NUM_SENSORS_ENABLED, num_recorded_data_points)
    assert actual_time_offset_data[0, -1] == (num_recorded_data_points - 1 + time_index_offset) * 2
    assert actual_time_offset_data[1, 0] == time_index_offset * 2
    actual_tissue_data = get_tissue_dataset_from_file(this_file)
    assert actual_tissue_data.shape == (GENERIC_NUM_CHANNELS_ENABLED, num_recorded_data_points)
    assert actual_tissue_data[0, -1] == (num_recorded_data_points - 1 + time_index_offset) * 3
    assert actual_tissue_data[1, 0] == time_index_offset * 4
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_magnetometer_data_packet__does_not_add_a_data_packet_completely_after_the_stop_recording_timepoint__and_sets_data_finalization_status_to_true(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    num_recorded_data_points = 10
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    recorded_data_packet = create_simple_data_packet(
        start_timepoint,
        0,
        start_recording_command["active_well_indices"],
        num_recorded_data_points,
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(recorded_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    this_file = open_the_generic_h5_file(file_dir, beta_version=2)
    # confirm some data already recorded to file
    actual_time_index_data = get_time_index_dataset_from_file(this_file)
    assert actual_time_index_data.shape == (num_recorded_data_points,)
    assert actual_time_index_data[-1] == start_timepoint + num_recorded_data_points - 1
    actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
    assert actual_time_offset_data.shape == (GENERIC_NUM_SENSORS_ENABLED, num_recorded_data_points)
    assert actual_time_offset_data[0, 0] == 0
    assert actual_time_offset_data[1, -1] == (num_recorded_data_points - 1) * 2
    actual_tissue_data = get_tissue_dataset_from_file(this_file)
    assert actual_tissue_data.shape == (GENERIC_NUM_CHANNELS_ENABLED, num_recorded_data_points)
    assert actual_tissue_data[0, 0] == 0
    assert actual_tissue_data[1, -1] == (num_recorded_data_points - 1) * 4

    stop_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)

    ignored_data_packet = create_simple_data_packet(
        stop_command["timepoint_to_stop_recording_at"],
        num_recorded_data_points,
        start_recording_command["active_well_indices"],
        15,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(ignored_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    # confirm no additional data added to file
    actual_time_index_data = get_time_index_dataset_from_file(this_file)
    assert actual_time_index_data.shape == (num_recorded_data_points,)
    actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
    assert actual_time_offset_data.shape == (GENERIC_NUM_SENSORS_ENABLED, num_recorded_data_points)
    actual_tissue_data = get_tissue_dataset_from_file(this_file)
    assert actual_tissue_data.shape == (GENERIC_NUM_CHANNELS_ENABLED, num_recorded_data_points)
    # TODO Tanner (5/19/21): add assertion about reference data once it is added to Beta 2 files

    tissue_status, _ = fw_process.get_recording_finalization_statuses()
    assert tissue_status[0][4] is True
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_magnetometer_data_packet__adds_a_data_packet_completely_before_the_stop_recording_timepoint__and_does_not_set_data_finalization_status_to_true(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    stop_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)

    num_data_points_1 = 26
    start_timepoint_1 = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet_1 = create_simple_data_packet(
        start_timepoint_1,
        0,
        start_recording_command["active_well_indices"],
        num_data_points_1,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet_1, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    this_file = open_the_generic_h5_file(file_dir, beta_version=2)
    # confirm some data already recorded to file
    actual_time_index_data = get_time_index_dataset_from_file(this_file)
    assert actual_time_index_data.shape == (num_data_points_1,)
    assert actual_time_index_data[7] == start_timepoint_1 + 7
    actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
    assert actual_time_offset_data.shape == (GENERIC_NUM_SENSORS_ENABLED, num_data_points_1)
    assert actual_time_offset_data[0, 15] == 15 * 2
    assert actual_time_offset_data[1, 5] == 5 * 2
    actual_tissue_data = get_tissue_dataset_from_file(this_file)
    assert actual_tissue_data.shape == (GENERIC_NUM_CHANNELS_ENABLED, num_data_points_1)
    assert actual_tissue_data[0, 15] == 15 * 3
    assert actual_tissue_data[1, 5] == 5 * 4

    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)

    num_data_points_2 = 24
    start_timepoint_2 = stop_command["timepoint_to_stop_recording_at"] - num_data_points_2
    test_data_packet_2 = create_simple_data_packet(
        start_timepoint_2,
        num_data_points_1,
        start_recording_command["active_well_indices"],
        num_data_points_2,
    )
    assert test_data_packet_2["time_indices"][-1] == stop_command["timepoint_to_stop_recording_at"] - 1
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet_2, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    total_num_data_points = num_data_points_1 + num_data_points_2
    # confirm additional data added to file
    actual_time_index_data = get_time_index_dataset_from_file(this_file)
    assert actual_time_index_data.shape == (total_num_data_points,)
    assert actual_time_index_data[-1] == stop_command["timepoint_to_stop_recording_at"] - 1
    actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
    assert actual_time_offset_data.shape == (GENERIC_NUM_SENSORS_ENABLED, total_num_data_points)
    assert actual_time_offset_data[0, 11] == 11 * 2
    assert actual_time_offset_data[1, 14] == 14 * 2
    actual_tissue_data = get_tissue_dataset_from_file(this_file)
    assert actual_tissue_data.shape == (GENERIC_NUM_CHANNELS_ENABLED, total_num_data_points)
    assert actual_tissue_data[0, 11] == 11 * 3
    assert actual_tissue_data[1, 14] == 14 * 4
    # TODO Tanner (5/19/21): add assertion about reference data once it is added to Beta 2 files

    tissue_status, _ = fw_process.get_recording_finalization_statuses()
    assert tissue_status[0][4] is False
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_magnetometer_data_packet__updates_dict_of_time_index_of_latest_recorded_data__when_new_data_is_added(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    expected_latest_timepoint = 100
    test_data_packet = create_simple_data_packet(
        expected_latest_timepoint,
        0,
        start_recording_command["active_well_indices"],
        1,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    for well_idx in range(24):
        actual_latest_timepoint = fw_process.get_file_latest_timepoint(well_idx)
        assert (
            actual_latest_timepoint == expected_latest_timepoint
        ), f"Incorrect latest timepoint for well {well_idx}"


def test_FileWriterProcess__passes_stim_data_packet_through_to_output_queue_correctly(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # send stim packet and make sure it is passed through
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS), board_queues[0]
    )
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_of_size(board_queues[1], 1)
    assert board_queues[1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)["data_type"] == "stimulation"

    # stop data stream
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(STOP_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)
    # send stim packet and make sure it is not passed through
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS), board_queues[0]
    )
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(board_queues[1])


def test_FileWriterProcess_process_stim_data_packet__writes_data_if_the_whole_data_chunk_is_at_the_timestamp_idx(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [14]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_stim_packet(start_timepoint, num_data_points)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)
    this_file = open_the_generic_h5_file(file_dir, well_name="C4", beta_version=2)

    actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
    assert actual_stimulation_data.shape == (2, num_data_points)
    assert actual_stimulation_data[0, 0] == start_timepoint
    assert actual_stimulation_data[1, 0] == start_timepoint
    assert actual_stimulation_data[0, num_data_points - 1] == start_timepoint + num_data_points - 1
    assert actual_stimulation_data[1, num_data_points - 1] == start_timepoint + num_data_points - 1
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_stim_data_packet__writes_data_if_the_timestamp_idx_starts_part_way_through_the_chunk(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [14]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_stim_packet(start_timepoint - 3, num_data_points, step=2)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)
    this_file = open_the_generic_h5_file(file_dir, well_name="C4", beta_version=2)

    actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
    assert actual_stimulation_data.shape == (2, num_data_points - 1)
    assert actual_stimulation_data[0, 0] == start_timepoint - 1
    assert actual_stimulation_data[1, 0] == start_timepoint - 1
    assert actual_stimulation_data[0, 1] == start_timepoint + 1
    assert actual_stimulation_data[1, 1] == start_timepoint + 1
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_stim_data_packet__writes_only_final_data_point_if_chunk_is_all_before_the_timestamp_idx(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [14]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_stim_packet(start_timepoint - 5, num_data_points)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)
    this_file = open_the_generic_h5_file(file_dir, well_name="C4", beta_version=2)

    actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
    assert actual_stimulation_data.shape == (2, 1)
    assert actual_stimulation_data[0, 0] == start_timepoint - 1
    assert actual_stimulation_data[1, 0] == start_timepoint - 1
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_stim_data_packet__writes_data_for_two_packets_when_the_timestamp_idx_starts_part_way_through_the_first_packet(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [14]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet_1 = create_simple_stim_packet(start_timepoint - 2, num_data_points)
    test_data_packet_2 = create_simple_stim_packet(start_timepoint + 3, num_data_points)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet_1, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet_2, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)
    this_file = open_the_generic_h5_file(file_dir, well_name="C4", beta_version=2)

    actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
    assert actual_stimulation_data.shape == (2, num_data_points * 2 - 2)
    assert actual_stimulation_data[0, 0] == start_timepoint
    assert actual_stimulation_data[1, 0] == start_timepoint
    assert actual_stimulation_data[0, num_data_points * 2 - 3] == start_timepoint + 3 + (num_data_points - 1)
    assert actual_stimulation_data[1, num_data_points * 2 - 3] == start_timepoint + 3 + (num_data_points - 1)
    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_stim_data_packet__does_not_add_a_data_packet_completely_after_the_stop_recording_timepoint(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [14]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_stim_packet(start_timepoint, num_data_points)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)
    this_file = open_the_generic_h5_file(file_dir, well_name="C4", beta_version=2)

    actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
    assert actual_stimulation_data.shape == (2, num_data_points)
    assert actual_stimulation_data[0, 0] == start_timepoint
    assert actual_stimulation_data[1, 0] == start_timepoint

    # add some magnetometer data to avoid errors when stopping the recording
    data_packet = create_simple_data_packet(
        start_timepoint,
        0,
        start_recording_command["active_well_indices"],
        3,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    stop_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)

    stop_timepoint = stop_command["timepoint_to_stop_recording_at"]
    ignored_data_packet = create_simple_stim_packet(stop_timepoint, num_data_points)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(ignored_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    # confirm no additional data added to file
    actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
    assert actual_stimulation_data.shape == (2, num_data_points)

    # close file to avoid issues on Windows
    this_file.close()


def test_FileWriterProcess_process_stim_data_packet__adds_a_data_packet_ending_on_the_stop_recording_timepoint(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)
    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = copy.deepcopy(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [14]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_stim_packet(start_timepoint, num_data_points)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)
    this_file = open_the_generic_h5_file(file_dir, well_name="C4", beta_version=2)

    actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
    assert actual_stimulation_data.shape == (2, num_data_points)
    assert actual_stimulation_data[0, 0] == start_timepoint
    assert actual_stimulation_data[1, 0] == start_timepoint

    # add some magnetometer data to avoid errors when stopping the recording
    data_packet = create_simple_data_packet(
        start_timepoint,
        0,
        start_recording_command["active_well_indices"],
        3,
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    stop_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)

    stop_timepoint = stop_command["timepoint_to_stop_recording_at"]
    test_data_packet = create_simple_stim_packet(stop_timepoint - (num_data_points - 1), num_data_points)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    # confirm no additional data added to file
    actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
    assert actual_stimulation_data.shape == (2, num_data_points * 2)
    assert actual_stimulation_data[0, 0] == start_timepoint
    assert actual_stimulation_data[1, 0] == start_timepoint
    assert actual_stimulation_data[0, -1] == stop_timepoint
    assert actual_stimulation_data[1, -1] == stop_timepoint

    # close file to avoid issues on Windows
    this_file.close()
