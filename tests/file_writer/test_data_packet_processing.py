# -*- coding: utf-8 -*-
import copy
import datetime

from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import get_reference_dataset_from_file
from mantarray_desktop_app import get_tissue_dataset_from_file
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_file_manager import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_file_manager import UTC_FIRST_REF_DATA_POINT_UUID
from mantarray_file_manager import UTC_FIRST_TISSUE_DATA_POINT_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import numpy as np
import pytest
from stdlib_utils import confirm_parallelism_is_stopped
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_file_writer import fixture_four_board_file_writer_process
from ..fixtures_file_writer import fixture_running_four_board_file_writer_process
from ..fixtures_file_writer import GENERIC_REFERENCE_SENSOR_DATA_PACKET
from ..fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_STOP_RECORDING_COMMAND
from ..fixtures_file_writer import GENERIC_TISSUE_DATA_PACKET
from ..fixtures_file_writer import open_the_generic_h5_file
from ..fixtures_file_writer import open_the_generic_h5_file_as_WellFile
from ..helpers import assert_queue_is_eventually_empty
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..parsed_channel_data_packets import SIMPLE_CONSTRUCT_DATA_FROM_WELL_0


__fixtures__ = [
    fixture_four_board_file_writer_process,
    fixture_running_four_board_file_writer_process,
]


@pytest.mark.timeout(15)
def test_FileWriterProcess__passes_data_packet_through_to_output_queue(
    four_board_file_writer_process,
):
    fw_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    error_queue = four_board_file_writer_process["error_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        SIMPLE_CONSTRUCT_DATA_FROM_WELL_0,
        board_queues[0][0],
    )

    fw_process.start()  # start it after the queue has been populated so that the process will certainly see the object in the queue

    fw_process.soft_stop()
    confirm_parallelism_is_stopped(fw_process, timeout_seconds=15)

    assert_queue_is_eventually_empty(error_queue)

    out_data = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    np.testing.assert_array_equal(out_data["data"], SIMPLE_CONSTRUCT_DATA_FROM_WELL_0["data"])
    assert out_data["well_index"] == SIMPLE_CONSTRUCT_DATA_FROM_WELL_0["well_index"]

    # clean up
    fw_process.hard_stop()
    fw_process.join()


def test_FileWriterProcess__process_next_data_packet__writes_tissue_data_if_the_whole_data_chunk_is_at_the_timestamp_idx__and_sets_timestamp_metadata_for_tissue_since_this_is_first_piece_of_data(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [3]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command,
        from_main_queue,
    )
    num_data_points = 50
    data = np.zeros((2, num_data_points), dtype=np.int32)
    for this_index in range(num_data_points):
        data[0, this_index] = (
            this_command["timepoint_to_begin_recording_at"] + this_index * CONSTRUCT_SENSOR_SAMPLING_PERIOD
        )
        data[1, this_index] = this_index * 2
    this_data_packet = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    this_data_packet["well_index"] = 3
    this_data_packet["data"] = data

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)
    actual_file = open_the_generic_h5_file(file_dir, well_name="D1")

    expected_timestamp = this_command["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ] + datetime.timedelta(
        seconds=this_command["timepoint_to_begin_recording_at"] / CENTIMILLISECONDS_PER_SECOND
    )
    assert actual_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == expected_timestamp.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    actual_tissue_data = get_tissue_dataset_from_file(actual_file)
    assert actual_tissue_data.shape == (50,)
    assert actual_tissue_data[3] == 6
    assert actual_tissue_data[9] == 18


def test_FileWriterProcess__process_next_data_packet__writes_tissue_data_if_the_timestamp_idx_starts_part_way_through_the_chunk__and_sets_timestamp_metadata_for_tissue_since_this_is_first_piece_of_data(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command,
        from_main_queue,
    )
    num_data_points = 75
    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_index in range(num_data_points):
        data[0, this_index] = (
            this_command["timepoint_to_begin_recording_at"]
            + (this_index - 25) * CONSTRUCT_SENSOR_SAMPLING_PERIOD
            + DATA_FRAME_PERIOD
        )
        data[1, this_index] = this_index * 2

    this_data_packet = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    this_data_packet["data"] = data

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    actual_file = open_the_generic_h5_file(file_dir)

    expected_timestamp = this_command["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ] + datetime.timedelta(
        seconds=(this_command["timepoint_to_begin_recording_at"] + DATA_FRAME_PERIOD)
        / CENTIMILLISECONDS_PER_SECOND
    )
    assert actual_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == expected_timestamp.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    actual_tissue_data = get_tissue_dataset_from_file(actual_file)
    assert actual_tissue_data.shape == (50,)
    assert actual_tissue_data[0] == 50
    assert actual_tissue_data[2] == 54


def test_FileWriterProcess__process_next_data_packet__does_not_write_tissue_data_if_data_chunk_is_all_before_the_timestamp_idx(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command,
        from_main_queue,
    )
    num_data_points = 5
    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_index in range(num_data_points):
        data[0, this_index] = (
            this_command["timepoint_to_begin_recording_at"]
            + (this_index - 25) * CONSTRUCT_SENSOR_SAMPLING_PERIOD
        )
        data[1, this_index] = this_index * 2

    this_data_packet = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    this_data_packet["data"] = data

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    actual_file = open_the_generic_h5_file(file_dir)
    assert str(UTC_FIRST_TISSUE_DATA_POINT_UUID) not in actual_file.attrs
    actual_tissue_data = get_tissue_dataset_from_file(actual_file)
    assert actual_tissue_data.shape == (0,)


def test_FileWriterProcess__process_next_data_packet__writes_tissue_data_for_two_packets_when_the_timestamp_idx_starts_part_way_through_the_first_packet__and_sets_timestamp_metadata_for_tissue_since_this_is_first_piece_of_data(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command,
        from_main_queue,
    )
    num_data_points = 75
    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_index in range(num_data_points):
        data[0, this_index] = (
            this_command["timepoint_to_begin_recording_at"]
            + (this_index - 30) * CONSTRUCT_SENSOR_SAMPLING_PERIOD
            + DATA_FRAME_PERIOD
        )
        data[1, this_index] = this_index * 2

    this_data_packet = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    this_data_packet["data"] = data

    num_data_points = 15
    next_data = np.zeros((2, num_data_points), dtype=np.int32)
    for this_index in range(num_data_points):
        next_data[0, this_index] = data[0, -1] + (this_index + 1) * CONSTRUCT_SENSOR_SAMPLING_PERIOD
        next_data[1, this_index] = this_index * 2 + 1000

    next_data_packet = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    next_data_packet["data"] = next_data

    board_queues[0][0].put_nowait(this_data_packet)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        next_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process, num_iterations=2)

    actual_file = open_the_generic_h5_file(file_dir)
    expected_timestamp = this_command["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ] + datetime.timedelta(
        seconds=(this_command["timepoint_to_begin_recording_at"] + DATA_FRAME_PERIOD)
        / CENTIMILLISECONDS_PER_SECOND
    )
    assert actual_file.attrs[str(UTC_FIRST_TISSUE_DATA_POINT_UUID)] == expected_timestamp.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    actual_tissue_data = get_tissue_dataset_from_file(actual_file)
    assert actual_tissue_data.shape == (60,)
    assert actual_tissue_data[0] == 60
    assert actual_tissue_data[-1] == 1028


def test_FileWriterProcess__process_next_data_packet__writes_reference_data_to_active_subset_of_wells_if_the_timestamp_idx_starts_part_way_through_the_chunk__and_sets_timestamp_metadata_for_reference_sensor_since_this_is_first_piece_of_data(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    this_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    this_command["active_well_indices"] = [4, 0]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_command,
        from_main_queue,
    )
    num_data_points = 70
    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_index in range(num_data_points):
        data[0, this_index] = (
            this_command["timepoint_to_begin_recording_at"]
            + (this_index - 30) * REFERENCE_SENSOR_SAMPLING_PERIOD
            + DATA_FRAME_PERIOD
        )
        data[1, this_index] = this_index * 3

    this_data_packet = copy.deepcopy(GENERIC_REFERENCE_SENSOR_DATA_PACKET)
    this_data_packet["data"] = data
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    actual_file_4 = open_the_generic_h5_file_as_WellFile(file_dir)

    actual_file_0 = open_the_generic_h5_file_as_WellFile(file_dir, well_name="A1")

    expected_timestamp = this_command["metadata_to_copy_onto_main_file_attributes"][
        UTC_BEGINNING_DATA_ACQUISTION_UUID
    ] + datetime.timedelta(
        seconds=(this_command["timepoint_to_begin_recording_at"] + DATA_FRAME_PERIOD)
        / CENTIMILLISECONDS_PER_SECOND
    )
    assert actual_file_0.get_h5_attribute(str(UTC_FIRST_REF_DATA_POINT_UUID)) == expected_timestamp.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    assert actual_file_4.get_h5_attribute(str(UTC_FIRST_REF_DATA_POINT_UUID)) == expected_timestamp.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    actual_reference_data_0 = actual_file_0.get_raw_reference_reading()[1, :]
    assert actual_reference_data_0.shape == (40,)
    assert actual_reference_data_0[0] == 90
    assert actual_reference_data_0[2] == 96

    actual_reference_data_4 = actual_file_4.get_raw_reference_reading()[1, :]
    assert actual_reference_data_4.shape == (40,)
    assert actual_reference_data_4[0] == 90
    assert actual_reference_data_0[39] == 207


def test_FileWriterProcess__process_next_data_packet__does_not_add_a_data_packet_after_the_stop_recording_timepoint__and_sets_tissue_finalization_status_to_true__if_data_packet_is_completely_after_timepoint(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    start_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_command,
        from_main_queue,
    )
    num_data_points = 10
    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_index in range(num_data_points):
        data[0, this_index] = (
            start_command["timepoint_to_begin_recording_at"]
            + this_index * CONSTRUCT_SENSOR_SAMPLING_PERIOD
            + DATA_FRAME_PERIOD
        )
        data[1, this_index] = this_index * 2

    this_data_packet = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    this_data_packet["data"] = data

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    actual_tissue_data_file = open_the_generic_h5_file(file_dir)

    # confirm some data already recorded to file
    actual_tissue_data = get_tissue_dataset_from_file(actual_tissue_data_file)
    assert actual_tissue_data.shape == (10,)
    assert actual_tissue_data[9] == 18
    assert actual_tissue_data[3] == 6

    stop_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_command,
        from_main_queue,
    )

    data_after_stop = np.zeros((2, num_data_points), dtype=np.int32)
    for this_index in range(num_data_points):
        data_after_stop[0, this_index] = (
            stop_command["timepoint_to_stop_recording_at"] + this_index * CONSTRUCT_SENSOR_SAMPLING_PERIOD
        )
    this_data_packet["data"] = data_after_stop

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    # confirm no additional data added to file
    actual_tissue_data = get_tissue_dataset_from_file(actual_tissue_data_file)
    assert actual_tissue_data.shape == (10,)

    tissue_status, _ = file_writer_process.get_recording_finalization_statuses()
    assert tissue_status[0][4] is True


def test_FileWriterProcess__process_next_data_packet__adds_part_of_a_data_packet_if_includes_the_stop_recording_timepoint__and_sets_reference_finalization_status_to_true(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    start_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_command,
        from_main_queue,
    )

    num_data_points = 10
    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_index in range(num_data_points):
        data[0, this_index] = (
            start_command["timepoint_to_begin_recording_at"] + this_index * REFERENCE_SENSOR_SAMPLING_PERIOD
        )
        data[1, this_index] = this_index * 2

    this_data_packet = copy.deepcopy(GENERIC_REFERENCE_SENSOR_DATA_PACKET)
    this_data_packet["data"] = data

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )

    invoke_process_run_and_check_errors(file_writer_process)

    actual_file = open_the_generic_h5_file(file_dir)

    # confirm some data already recorded to file
    actual_data_in_file = get_reference_dataset_from_file(actual_file)
    assert actual_data_in_file.shape == (10,)
    assert actual_data_in_file[4] == 8
    assert actual_data_in_file[8] == 16

    stop_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_command,
        from_main_queue,
    )

    data_after_stop = np.zeros((2, num_data_points), dtype=np.int32)
    for this_index in range(num_data_points):
        data_after_stop[0, this_index] = (
            stop_command["timepoint_to_stop_recording_at"]
            + (this_index - 4) * REFERENCE_SENSOR_SAMPLING_PERIOD
        )
        data_after_stop[1, this_index] = this_index * 5
    this_data_packet["data"] = data_after_stop

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    # confirm no additional data added to file
    actual_data = get_reference_dataset_from_file(actual_file)
    assert actual_data.shape == (15,)
    assert actual_data[11] == 5
    assert actual_data[14] == 20

    _, reference_status = file_writer_process.get_recording_finalization_statuses()
    assert reference_status[0][4] is True


def test_FileWriterProcess__process_next_data_packet__adds_a_data_packet_before_the_stop_recording_timepoint__and_does_not_set_tissue_finalization_status_to_true__if_data_packet_is_completely_before_timepoint(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]
    file_dir = four_board_file_writer_process["file_dir"]

    start_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    start_command["active_well_indices"] = [4]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_command,
        from_main_queue,
    )

    num_data_points = 10
    data = np.zeros((2, num_data_points), dtype=np.int32)

    for this_index in range(num_data_points):
        data[0, this_index] = (
            start_command["timepoint_to_begin_recording_at"]
            + this_index * CONSTRUCT_SENSOR_SAMPLING_PERIOD
            + DATA_FRAME_PERIOD
        )
        data[1, this_index] = this_index * 2

    this_data_packet = copy.deepcopy(GENERIC_TISSUE_DATA_PACKET)
    this_data_packet["data"] = data

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    actual_file = open_the_generic_h5_file(file_dir)

    # confirm some data already recorded to file
    actual_tissue_data = get_tissue_dataset_from_file(actual_file)
    assert actual_tissue_data.shape == (10,)
    assert actual_tissue_data[9] == 18
    assert actual_tissue_data[3] == 6

    stop_command = copy.deepcopy(GENERIC_STOP_RECORDING_COMMAND)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        stop_command,
        from_main_queue,
    )
    data_before_stop = np.zeros((2, num_data_points), dtype=np.int32)
    for this_index in range(num_data_points):
        data_before_stop[0, this_index] = (
            stop_command["timepoint_to_stop_recording_at"]
            + (this_index - 10) * CONSTRUCT_SENSOR_SAMPLING_PERIOD
        )
        data_before_stop[1, this_index] = this_index * 5
    this_data_packet["data"] = data_before_stop

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        this_data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    # confirm no additional data added to file
    actual_data = get_tissue_dataset_from_file(actual_file)
    assert actual_data.shape == (20,)
    assert actual_data[11] == 5
    assert actual_data[14] == 20

    tissue_status, _ = file_writer_process.get_recording_finalization_statuses()
    assert tissue_status[0][4] is False


def test_FileWriterProcess__process_next_data_packet__updates_dict_of_time_index_of_latest_recorded_data__when_new_data_is_added(
    four_board_file_writer_process,
):
    file_writer_process = four_board_file_writer_process["fw_process"]
    board_queues = four_board_file_writer_process["board_queues"]
    from_main_queue = four_board_file_writer_process["from_main_queue"]

    start_recording_command = copy.deepcopy(GENERIC_START_RECORDING_COMMAND)
    start_recording_command["timepoint_to_begin_recording_at"] = 0
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_recording_command,
        from_main_queue,
    )
    invoke_process_run_and_check_errors(file_writer_process)

    expected_latest_timepoint = 100
    expected_well_idx = 0
    data_packet = {
        "is_reference_sensor": False,
        "well_index": expected_well_idx,
        "data": np.array([[expected_latest_timepoint], [0]], dtype=np.int32),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        data_packet,
        board_queues[0][0],
    )
    invoke_process_run_and_check_errors(file_writer_process)

    actual_latest_timepoint = file_writer_process.get_file_latest_timepoint(expected_well_idx)
    assert actual_latest_timepoint == expected_latest_timepoint
