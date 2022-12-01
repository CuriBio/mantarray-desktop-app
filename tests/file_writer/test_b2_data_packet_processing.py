# -*- coding: utf-8 -*-
import copy
import datetime

from mantarray_desktop_app import get_stimulation_dataset_from_file
from mantarray_desktop_app import get_time_index_dataset_from_file
from mantarray_desktop_app import get_time_offset_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.constants import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app.utils.serial_comm import chunk_protocols_in_stim_info
import numpy as np
from pulse3D.constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from pulse3D.constants import UTC_FIRST_TISSUE_DATA_POINT_UUID
import pytest
from stdlib_utils import confirm_parallelism_is_stopped
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import create_simple_beta_2_data_packet
from ..fixtures_file_writer import create_simple_stim_packet
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import fixture_runnable_four_board_file_writer_process
from ..fixtures_file_writer import fixture_running_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_BETA_2_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_STIM_INFO
from ..fixtures_file_writer import GENERIC_STIM_PROTOCOL_ASSIGNMENTS
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
    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["is_calibration_recording"] = True
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)
    # send magnetometer data packet
    test_data_packet = create_simple_beta_2_data_packet(
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

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [3]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 50
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_beta_2_data_packet(
        start_timepoint, 0, start_recording_command["active_well_indices"], num_data_points
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, well_name="D1", beta_version=2) as this_file:
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
        assert actual_time_offset_data.shape == (SERIAL_COMM_NUM_SENSORS_PER_WELL, num_data_points)
        assert actual_time_offset_data[0, 8] == 8 * 2
        assert actual_time_offset_data[1, 5] == 5 * 2
        actual_tissue_data = get_tissue_dataset_from_file(this_file)
        assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, num_data_points)
        assert actual_tissue_data[0, 8] == 8 * 1
        assert actual_tissue_data[1, 5] == 5 * 2


def test_FileWriterProcess_process_magnetometer_data_packet__writes_data_if_the_timestamp_idx_starts_part_way_through_the_chunk__and_sets_timestamp_metadata_for_tissue_since_this_is_first_piece_of_data(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)

    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    total_num_data_points = 75
    num_recorded_data_points = 50
    time_index_offset = total_num_data_points - num_recorded_data_points
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"] - time_index_offset
    test_data_packet = create_simple_beta_2_data_packet(
        start_timepoint, 0, start_recording_command["active_well_indices"], total_num_data_points
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    expected_timestamp = start_recording_command["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ] + datetime.timedelta(
        seconds=(start_recording_command["timepoint_to_begin_recording_at"]) / MICRO_TO_BASE_CONVERSION
    )

    with open_the_generic_h5_file(file_dir, beta_version=2) as this_file:
        assert this_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == expected_timestamp.strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )
        actual_time_index_data = get_time_index_dataset_from_file(this_file)
        assert actual_time_index_data.shape == (num_recorded_data_points,)
        assert actual_time_index_data[0] == start_timepoint + time_index_offset
        actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
        assert actual_time_offset_data.shape == (SERIAL_COMM_NUM_SENSORS_PER_WELL, num_recorded_data_points)
        assert actual_time_offset_data[0, 9] == (9 + time_index_offset) * 2
        assert actual_time_offset_data[1, 6] == (6 + time_index_offset) * 2
        actual_tissue_data = get_tissue_dataset_from_file(this_file)
        assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, num_recorded_data_points)
        assert actual_tissue_data[0, 9] == (9 + time_index_offset) * 1
        assert actual_tissue_data[1, 6] == (6 + time_index_offset) * 2


def test_FileWriterProcess_process_magnetometer_data_packet__does_not_write_data_if_data_chunk_is_all_before_the_timestamp_idx(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)

    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    num_data_points = 30
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"] - num_data_points
    test_data_packet = create_simple_beta_2_data_packet(
        start_timepoint, 0, start_recording_command["active_well_indices"], num_data_points
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, beta_version=2) as this_file:
        assert str(UTC_FIRST_TISSUE_DATA_POINT_UUID) not in this_file.attrs
        actual_time_index_data = get_time_index_dataset_from_file(this_file)
        assert actual_time_index_data.shape == (0,)
        actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
        assert actual_time_offset_data.shape == (SERIAL_COMM_NUM_SENSORS_PER_WELL, 0)
        actual_tissue_data = get_tissue_dataset_from_file(this_file)
        assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, 0)


def test_FileWriterProcess_process_magnetometer_data_packet__writes_data_for_two_packets_when_the_timestamp_idx_starts_part_way_through_the_first_packet__and_sets_timestamp_metadata_for_tissue_since_this_is_first_piece_of_data(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)

    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    total_num_data_points_1 = 40
    num_recorded_data_points_1 = 31
    time_index_offset = total_num_data_points_1 - num_recorded_data_points_1
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"] - time_index_offset
    first_data_packet = create_simple_beta_2_data_packet(
        start_timepoint, 0, start_recording_command["active_well_indices"], total_num_data_points_1
    )
    num_data_points_2 = 15
    second_data_packet = create_simple_beta_2_data_packet(
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

    with open_the_generic_h5_file(file_dir, beta_version=2) as this_file:
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
        assert (
            actual_time_index_data[-1] == start_timepoint + time_index_offset + num_recorded_data_points - 1
        )
        actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
        assert actual_time_offset_data.shape == (SERIAL_COMM_NUM_SENSORS_PER_WELL, num_recorded_data_points)
        assert actual_time_offset_data[0, -1] == (num_recorded_data_points - 1 + time_index_offset) * 2
        assert actual_time_offset_data[1, 0] == time_index_offset * 2
        actual_tissue_data = get_tissue_dataset_from_file(this_file)
        assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, num_recorded_data_points)
        assert actual_tissue_data[0, -1] == (num_recorded_data_points - 1 + time_index_offset) * 1
        assert actual_tissue_data[8, 0] == time_index_offset * 9


def test_FileWriterProcess_process_magnetometer_data_packet__does_not_add_a_data_packet_starting_on_the_stop_recording_timepoint__and_sets_data_finalization_status_to_true(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)

    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    num_recorded_data_points = 10
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    recorded_data_packet = create_simple_beta_2_data_packet(
        start_timepoint, 0, start_recording_command["active_well_indices"], num_recorded_data_points
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(recorded_data_packet, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, beta_version=2) as this_file:
        # confirm some data already recorded to file
        actual_time_index_data = get_time_index_dataset_from_file(this_file)
        assert actual_time_index_data.shape == (num_recorded_data_points,)
        assert actual_time_index_data[-1] == start_timepoint + num_recorded_data_points - 1
        actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
        assert actual_time_offset_data.shape == (SERIAL_COMM_NUM_SENSORS_PER_WELL, num_recorded_data_points)
        assert actual_time_offset_data[0, 0] == 0
        assert actual_time_offset_data[1, -1] == (num_recorded_data_points - 1) * 2
        actual_tissue_data = get_tissue_dataset_from_file(this_file)
        assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, num_recorded_data_points)
        assert actual_tissue_data[0, 0] == 0
        assert actual_tissue_data[1, -1] == (num_recorded_data_points - 1) * 2

        stop_command = dict(GENERIC_STOP_RECORDING_COMMAND)
        put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)

        ignored_data_packet = create_simple_beta_2_data_packet(
            stop_command["timepoint_to_stop_recording_at"],
            num_recorded_data_points,
            start_recording_command["active_well_indices"],
            15,
        )
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            ignored_data_packet, board_queues[0][0]
        )
        invoke_process_run_and_check_errors(fw_process)

        # confirm no additional data added to file
        actual_time_index_data = get_time_index_dataset_from_file(this_file)
        assert actual_time_index_data.shape == (num_recorded_data_points,)
        actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
        assert actual_time_offset_data.shape == (SERIAL_COMM_NUM_SENSORS_PER_WELL, num_recorded_data_points)
        actual_tissue_data = get_tissue_dataset_from_file(this_file)
        assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, num_recorded_data_points)
        # TODO Tanner (5/19/21): add assertion about reference data once it is added to Beta 2 files

        tissue_status, _ = fw_process.get_recording_finalization_statuses()
        assert tissue_status[0][4] is True


def test_FileWriterProcess_process_magnetometer_data_packet__adds_a_data_packet_completely_before_the_stop_recording_timepoint__and_does_not_set_data_finalization_status_to_true(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)

    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    stop_command = dict(GENERIC_STOP_RECORDING_COMMAND)

    num_data_points_1 = 26
    start_timepoint_1 = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet_1 = create_simple_beta_2_data_packet(
        start_timepoint_1, 0, start_recording_command["active_well_indices"], num_data_points_1
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet_1, board_queues[0][0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, beta_version=2) as this_file:
        # confirm some data already recorded to file
        actual_time_index_data = get_time_index_dataset_from_file(this_file)
        assert actual_time_index_data.shape == (num_data_points_1,)
        assert actual_time_index_data[7] == start_timepoint_1 + 7
        actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
        assert actual_time_offset_data.shape == (SERIAL_COMM_NUM_SENSORS_PER_WELL, num_data_points_1)
        assert actual_time_offset_data[0, 15] == 15 * 2
        assert actual_time_offset_data[1, 5] == 5 * 2
        actual_tissue_data = get_tissue_dataset_from_file(this_file)
        assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, num_data_points_1)
        assert actual_tissue_data[0, 15] == 15 * 1
        assert actual_tissue_data[1, 5] == 5 * 2

        put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)

        num_data_points_2 = 24
        start_timepoint_2 = stop_command["timepoint_to_stop_recording_at"] - num_data_points_2
        test_data_packet_2 = create_simple_beta_2_data_packet(
            start_timepoint_2,
            num_data_points_1,
            start_recording_command["active_well_indices"],
            num_data_points_2,
        )
        assert test_data_packet_2["time_indices"][-1] == stop_command["timepoint_to_stop_recording_at"] - 1
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            test_data_packet_2, board_queues[0][0]
        )
        invoke_process_run_and_check_errors(fw_process)

        total_num_data_points = num_data_points_1 + num_data_points_2
        # confirm additional data added to file
        actual_time_index_data = get_time_index_dataset_from_file(this_file)
        assert actual_time_index_data.shape == (total_num_data_points,)
        assert actual_time_index_data[-1] == stop_command["timepoint_to_stop_recording_at"] - 1
        actual_time_offset_data = get_time_offset_dataset_from_file(this_file)
        assert actual_time_offset_data.shape == (SERIAL_COMM_NUM_SENSORS_PER_WELL, total_num_data_points)
        assert actual_time_offset_data[0, 11] == 11 * 2
        assert actual_time_offset_data[1, 14] == 14 * 2
        actual_tissue_data = get_tissue_dataset_from_file(this_file)
        assert actual_tissue_data.shape == (SERIAL_COMM_NUM_DATA_CHANNELS, total_num_data_points)
        assert actual_tissue_data[3, 11] == 11 * 4
        assert actual_tissue_data[5, 14] == 14 * 6
        # TODO Tanner (5/19/21): add assertion about reference data once it is added to Beta 2 files

        tissue_status, _ = fw_process.get_recording_finalization_statuses()
        assert tissue_status[0][4] is False


def test_FileWriterProcess_process_magnetometer_data_packet__updates_dict_of_time_index_of_latest_recorded_data__when_new_data_is_added(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)

    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    expected_latest_timepoint = 100
    test_data_packet = create_simple_beta_2_data_packet(
        expected_latest_timepoint, 0, start_recording_command["active_well_indices"], 1
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
    data_input_queue, data_output_queue = board_queues
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    # set subprotocol_idx_mappings
    test_protocol_assignments = GENERIC_STIM_PROTOCOL_ASSIGNMENTS
    test_stim_info = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "stimulation_type": "C",
                "run_until_stopped": True,
                # Tanner (11/27/22): actual subprotocols currently not needed for this test to pass
                "subprotocols": [],
            }
            for protocol_id in ("A", "B")
        ],
        "protocol_assignments": test_protocol_assignments,
    }
    subprotocol_idx_mappings = {"A": {i: i for i in range(4)}, "B": {i: i // 2 for i in range(4)}}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "stimulation",
            "command": "set_protocols",
            "stim_info": test_stim_info,
            "subprotocol_idx_mappings": subprotocol_idx_mappings,
        },
        from_main_queue,
    )
    invoke_process_run_and_check_errors(fw_process)

    test_well_statuses = [
        {0: np.array([[10], [0]])},
        {1: np.array([[20], [0]])},
        {0: np.array([[11], [1]])},
        {1: np.array([[21], [1]])},  # this will not produce a packet sent through to the output queue
        {0: np.array([[11], [1]]), 1: np.array([[21], [1]])},
        {0: np.array([[10, 11], [0, 1]])},
        {1: np.array([[20, 21], [0, 1]])},
        {0: np.array([[10, 11, 12, 13, 14], [0, 1, 2, 3, 0]])},
        {1: np.array([[20, 21, 22, 23, 24], [0, 1, 2, 3, 0]])},
        {
            0: np.array([[10, 11, 12, 13, 14], [0, 1, 2, 3, 0]]),
            1: np.array([[20, 21, 22, 23, 24], [0, 1, 2, 3, 0]]),
        },
    ]
    expected_well_statuses = [
        # Protocol A is assigned to well 0, Protocol B is assigned to well 1
        {0: np.array([[10], [0]])},
        {1: np.array([[20], [0]])},
        {0: np.array([[11], [1]])},
        None,
        {0: np.array([[11], [1]])},
        {0: np.array([[10, 11], [0, 1]])},
        {1: np.array([[20], [0]])},
        {0: np.array([[10, 11, 12, 13, 14], [0, 1, 2, 3, 0]])},
        {1: np.array([[20, 22, 24], [0, 1, 0]])},
        {
            0: np.array([[10, 11, 12, 13, 14], [0, 1, 2, 3, 0]]),
            1: np.array([[20, 22, 24], [0, 1, 0]]),
        },
    ]

    for packet_num, (input_statuses, expected_output_statuses) in enumerate(
        zip(test_well_statuses, expected_well_statuses)
    ):
        # send stim packets and make sure they pass through correctly
        test_input_packet = copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
        test_input_packet["well_statuses"] = input_statuses
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            # copy this packet before sending it into the queue so it can be modified later
            copy.deepcopy(test_input_packet),
            data_input_queue,
        )
        invoke_process_run_and_check_errors(fw_process)

        if expected_output_statuses is None:
            confirm_queue_is_eventually_empty(data_output_queue)
            continue

        confirm_queue_is_eventually_of_size(data_output_queue, 1)
        actual_output_packet = data_output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

        actual_output_statuses = actual_output_packet.pop("well_statuses")
        assert actual_output_statuses.keys() == expected_output_statuses.keys()
        for well_idx, expected_status_arr in expected_output_statuses.items():
            actual_status_arr = actual_output_statuses[well_idx]
            np.testing.assert_array_equal(
                actual_status_arr, expected_status_arr, err_msg=f"Packet {packet_num}, Well {well_idx}"
            )

        # don't copy well_statuses value since an assertion was already made on it
        expected_output_packet = {k: v for k, v in test_input_packet.items() if k != "well_statuses"}
        assert actual_output_packet == expected_output_packet, packet_num

    # stop data stream
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(STOP_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(fw_process)
    # send stim packet and make sure it is not passed through
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS), data_input_queue
    )
    invoke_process_run_and_check_errors(fw_process)
    confirm_queue_is_eventually_empty(data_output_queue)


def test_FileWriterProcess_process_stim_data_packet__writes_correct_subprotocol_indices_using_chunked_to_original_mapping(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)

    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    # set subprotocol_idx_mappings
    test_protocol_assignments = GENERIC_STIM_PROTOCOL_ASSIGNMENTS
    test_stim_info = {
        "protocols": [
            {
                "protocol_id": protocol_id,
                "stimulation_type": "C",
                "run_until_stopped": True,
                # Tanner (11/27/22): actual subprotocols currently not needed for this test to pass
                "subprotocols": [],
            }
            for protocol_id in ("A", "B")
        ],
        "protocol_assignments": test_protocol_assignments,
    }
    subprotocol_idx_mappings = {"A": {i: i for i in range(4)}, "B": {i: i // 2 for i in range(4)}}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "stimulation",
            "command": "set_protocols",
            "stim_info": test_stim_info,
            "subprotocol_idx_mappings": subprotocol_idx_mappings,
        },
        from_main_queue,
    )
    invoke_process_run_and_check_errors(fw_process)

    test_well_statuses = [
        {0: np.array([[10], [0]])},
        {1: np.array([[20], [0]])},
        {0: np.array([[11], [1]])},
        {1: np.array([[21], [1]])},
        {0: np.array([[11], [1]]), 1: np.array([[21], [1]])},
        {0: np.array([[10, 11], [0, 1]])},
        {1: np.array([[20, 21], [0, 1]])},
        {0: np.array([[10, 11, 12, 13, 14], [0, 1, 2, 3, 0]])},
        {1: np.array([[20, 21, 22, 23, 24], [0, 1, 2, 3, 0]])},
        {
            0: np.array([[10, 11, 12, 13, 14], [0, 1, 2, 3, 0]]),
            1: np.array([[20, 21, 22, 23, 24], [0, 1, 2, 3, 0]]),
        },
    ]
    expected_well_statuses = [0, 1, 1, 0, 1, 0, 1, 2, 3, 0, 0, 1, 2, 3, 0]

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [0, 1]
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    for input_status in test_well_statuses:
        test_input_packet = copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
        test_input_packet["well_statuses"] = input_status
        put_object_into_queue_and_raise_error_if_eventually_still_empty(test_input_packet, board_queues[0])
        invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(
        file_dir, well_name="A1", beta_version=2, timestamp_str="2020_02_09_190322"
    ) as this_file:
        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
        np.testing.assert_array_equal(actual_stimulation_data[1], expected_well_statuses)
    with open_the_generic_h5_file(
        file_dir, well_name="B1", beta_version=2, timestamp_str="2020_02_09_190322"
    ) as this_file:
        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
        np.testing.assert_array_equal(
            actual_stimulation_data[1], [subprotocol_idx_mappings["B"][n] for n in expected_well_statuses]
        )


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

    expected_stim_info, expected_subprotocol_idx_mappings = chunk_protocols_in_stim_info(GENERIC_STIM_INFO)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": expected_subprotocol_idx_mappings,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [1]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_stim_packet(start_timepoint, num_data_points, well_idxs=(0, 1))

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, well_name="B1", beta_version=2) as this_file:
        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
        assert actual_stimulation_data.shape == (2, num_data_points)
        assert actual_stimulation_data[0, 0] == start_timepoint
        assert actual_stimulation_data[1, 0] == 0
        assert actual_stimulation_data[0, num_data_points - 1] == start_timepoint + num_data_points - 1
        assert actual_stimulation_data[1, num_data_points - 1] == 0


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

    expected_stim_info, expected_subprotocol_idx_mappings = chunk_protocols_in_stim_info(GENERIC_STIM_INFO)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": expected_subprotocol_idx_mappings,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [0]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    first_recorded_idx = 1

    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_stim_packet(
        start_timepoint - first_recorded_idx, num_data_points, step=2, well_idxs=(0, 1)
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, well_name="A1", beta_version=2) as this_file:
        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
        assert actual_stimulation_data.shape == (2, num_data_points - 1)
        assert actual_stimulation_data[0, 0] == start_timepoint - 1
        assert actual_stimulation_data[1, 0] == 0
        assert actual_stimulation_data[0, 1] == start_timepoint + 1
        assert actual_stimulation_data[1, 1] == 0


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

    expected_stim_info, expected_subprotocol_idx_mappings = chunk_protocols_in_stim_info(GENERIC_STIM_INFO)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": expected_subprotocol_idx_mappings,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [0]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]

    test_data_packet = create_simple_stim_packet(
        start_timepoint - num_data_points, num_data_points, well_idxs=(0, 1)
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, well_name="A1", beta_version=2) as this_file:
        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
        assert actual_stimulation_data.shape == (2, 1)
        assert actual_stimulation_data[0, 0] == start_timepoint - 1
        assert actual_stimulation_data[1, 0] == 0


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

    expected_stim_info, expected_subprotocol_idx_mappings = chunk_protocols_in_stim_info(GENERIC_STIM_INFO)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": expected_subprotocol_idx_mappings,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [0]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = 5
    first_recorded_idx = 2

    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet_1 = create_simple_stim_packet(
        start_timepoint - first_recorded_idx, num_data_points, well_idxs=(0, 1)
    )
    test_data_packet_2 = create_simple_stim_packet(start_timepoint + 3, num_data_points, well_idxs=(0, 1))

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet_1, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet_2, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, well_name="A1", beta_version=2) as this_file:
        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
        assert actual_stimulation_data.shape == (2, num_data_points * 2 - first_recorded_idx)
        assert actual_stimulation_data[0, 0] == start_timepoint
        assert actual_stimulation_data[1, 0] == 0
        assert actual_stimulation_data[0, num_data_points * 2 - 3] == start_timepoint + 3 + (
            num_data_points - 1
        )
        assert actual_stimulation_data[1, num_data_points * 2 - 3] == 0


def test_FileWriterProcess_process_stim_data_packet__does_not_add_a_data_packet_starting_on_the_stop_recording_timepoint(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    fw_process.set_beta_2_mode()
    populate_calibration_folder(fw_process)

    board_idx = 0
    board_queues = four_board_file_writer_process["board_queues"][board_idx]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    expected_stim_info, expected_subprotocol_idx_mappings = chunk_protocols_in_stim_info(GENERIC_STIM_INFO)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": expected_subprotocol_idx_mappings,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [1]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points = len(expected_subprotocol_idx_mappings["B"])
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_stim_packet(start_timepoint, num_data_points, well_idxs=(0, 1))

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, well_name="B1", beta_version=2) as this_file:
        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
        assert actual_stimulation_data.shape == (2, num_data_points)
        assert actual_stimulation_data[0, 0] == start_timepoint
        assert actual_stimulation_data[1, 0] == 0

        # add some magnetometer data to avoid errors when stopping the recording
        data_packet = create_simple_beta_2_data_packet(
            start_timepoint, 0, start_recording_command["active_well_indices"], 3
        )
        put_object_into_queue_and_raise_error_if_eventually_still_empty(data_packet, board_queues[0])
        invoke_process_run_and_check_errors(fw_process)

        stop_command = dict(GENERIC_STOP_RECORDING_COMMAND)
        put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)

        stop_timepoint = stop_command["timepoint_to_stop_recording_at"]
        ignored_data_packet = create_simple_stim_packet(stop_timepoint, num_data_points, well_idxs=(0, 1))
        put_object_into_queue_and_raise_error_if_eventually_still_empty(ignored_data_packet, board_queues[0])
        invoke_process_run_and_check_errors(fw_process)

        # confirm no additional data added to file
        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
        assert actual_stimulation_data.shape == (2, num_data_points)


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

    expected_stim_info, expected_subprotocol_idx_mappings = chunk_protocols_in_stim_info(GENERIC_STIM_INFO)
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
        "subprotocol_idx_mappings": expected_subprotocol_idx_mappings,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, from_main_queue)
    invoke_process_run_and_check_errors(fw_process)

    start_recording_command = dict(GENERIC_BETA_2_START_RECORDING_COMMAND)
    start_recording_command["active_well_indices"] = [0]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_recording_command, from_main_queue)

    num_data_points_packet_1 = len(expected_subprotocol_idx_mappings["A"])
    start_timepoint = start_recording_command["timepoint_to_begin_recording_at"]
    test_data_packet = create_simple_stim_packet(start_timepoint, num_data_points_packet_1, well_idxs=(0, 1))

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
    invoke_process_run_and_check_errors(fw_process)

    with open_the_generic_h5_file(file_dir, well_name="A1", beta_version=2) as this_file:
        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)
        assert actual_stimulation_data.shape == (2, num_data_points_packet_1)
        assert actual_stimulation_data[0, 0] == start_timepoint
        assert actual_stimulation_data[1, 0] == 0
        assert actual_stimulation_data[0, -1] == start_timepoint + num_data_points_packet_1 - 1
        assert actual_stimulation_data[1, -1] == "TODO"

        # add some magnetometer data to avoid errors when stopping the recording
        data_packet = create_simple_beta_2_data_packet(
            start_timepoint, 0, start_recording_command["active_well_indices"], 3
        )
        put_object_into_queue_and_raise_error_if_eventually_still_empty(data_packet, board_queues[0])
        invoke_process_run_and_check_errors(fw_process)

        stop_command = dict(GENERIC_STOP_RECORDING_COMMAND)
        put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)

        num_data_points_packet_2 = 4
        stop_timepoint = stop_command["timepoint_to_stop_recording_at"]
        test_data_packet = create_simple_stim_packet(
            stop_timepoint - (num_data_points_packet_2 - 1), num_data_points_packet_2, well_idxs=(0, 1)
        )
        put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, board_queues[0])
        invoke_process_run_and_check_errors(fw_process)

        actual_stimulation_data = get_stimulation_dataset_from_file(this_file)

        # TODO fix below if necessary

        # confirm data from first packet unchanged
        assert actual_stimulation_data.shape == (2, num_data_points_packet_1 + num_data_points_packet_2)
        assert actual_stimulation_data[0, 0] == start_timepoint
        assert actual_stimulation_data[1, 0] == 0
        assert (
            actual_stimulation_data[0, num_data_points_packet_1 - 1]
            == start_timepoint + num_data_points_packet_1 - 1
        )
        assert actual_stimulation_data[1, num_data_points_packet_1 - 1] == num_data_points_packet_1 - 1

        # confirm data from new packet added to file correctly
        assert actual_stimulation_data[0, num_data_points_packet_1] == stop_timepoint - (
            num_data_points_packet_2 - 1
        )
        assert actual_stimulation_data[1, num_data_points_packet_1] == 0
        assert actual_stimulation_data[0, -1] == stop_timepoint
        assert actual_stimulation_data[1, -2] == num_data_points_packet_2 - 2
        assert actual_stimulation_data[1, -1] == num_data_points_packet_2 - 1
