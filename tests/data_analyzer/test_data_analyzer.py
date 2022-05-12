# -*- coding: utf-8 -*-
import copy
import logging
from multiprocessing import Queue
import random
from statistics import stdev
import tempfile
import time

from mantarray_desktop_app import data_analyzer
from mantarray_desktop_app import DataAnalyzerProcess
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import UnrecognizedCommandFromMainToDataAnalyzerError
from mantarray_desktop_app.constants import DEFAULT_SAMPLING_PERIOD
import numpy as np
from pulse3D.exceptions import PeakDetectionError
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty

from ..fixtures import fixture_patch_print
from ..fixtures import get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process_beta_2_mode
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..parsed_channel_data_packets import SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS


__fixtures__ = [
    fixture_four_board_analyzer_process,
    fixture_four_board_analyzer_process_beta_2_mode,
    fixture_patch_print,
]


def test_DataAnalyzerProcess_super_is_called_during_init(mocker):
    error_queue = Queue()
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")

    with tempfile.TemporaryDirectory() as tmp_output_dir:
        DataAnalyzerProcess((), None, None, error_queue, mag_analysis_output_dir=tmp_output_dir)
        mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


def test_DataAnalyzerProcess_setup_before_loop__calls_super(four_board_analyzer_process, mocker):
    spied_setup = mocker.spy(InfiniteProcess, "_setup_before_loop")

    da_process, *_ = four_board_analyzer_process
    invoke_process_run_and_check_errors(da_process, perform_setup_before_loop=True)
    spied_setup.assert_called_once()


@pytest.mark.parametrize("beta_2_mode", [True, False])
def test_DataAnalyzerProcess_setup_before_loop__inits_streams_correctly(
    beta_2_mode, four_board_analyzer_process, mocker
):
    da_process, *_ = four_board_analyzer_process
    da_process._beta_2_mode = beta_2_mode
    spied_check_dirs = mocker.spy(da_process, "_check_dirs")
    spied_init_streams = mocker.spy(da_process, "init_streams")
    spied_set_sampling_period = mocker.spy(da_process, "set_sampling_period")

    invoke_process_run_and_check_errors(da_process, perform_setup_before_loop=True)
    spied_init_streams.assert_called_once()
    if beta_2_mode:
        spied_set_sampling_period.assert_called_once_with(DEFAULT_SAMPLING_PERIOD)
        spied_check_dirs.assert_called_once_with()
    else:
        spied_set_sampling_period.assert_not_called()


def test_DataAnalyzerProcess__drain_all_queues__drains_all_queues_except_error_queue_and_returns__all_items(
    four_board_analyzer_process,
):
    expected = [[10, 11], [12, 13], [14, 15], [16, 17]]
    expected_error = "error"
    expected_from_main = "from_main"
    expected_to_main = "to_main"

    (
        data_analyzer_process,
        board_queues,
        from_main_queue,
        to_main_queue,
        error_queue,
        _,
    ) = four_board_analyzer_process
    for i, board in enumerate(board_queues):
        for j, queue in enumerate(board):
            queue_item = expected[i][j]
            put_object_into_queue_and_raise_error_if_eventually_still_empty(queue_item, queue)

    from_main_queue.put_nowait(expected_from_main)
    to_main_queue.put_nowait(expected_to_main)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_error, error_queue)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    actual = data_analyzer_process._drain_all_queues()  # pylint:disable=protected-access

    confirm_queue_is_eventually_of_size(error_queue, 1)
    actual_error = error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_error == expected_error

    confirm_queue_is_eventually_empty(from_main_queue)
    confirm_queue_is_eventually_empty(to_main_queue)
    confirm_queue_is_eventually_empty(board_queues[3][0])
    confirm_queue_is_eventually_empty(board_queues[2][0])
    confirm_queue_is_eventually_empty(board_queues[1][0])
    confirm_queue_is_eventually_empty(board_queues[0][1])
    confirm_queue_is_eventually_empty(board_queues[0][0])

    assert actual["board_0"]["outgoing_data"] == [expected[0][1]]
    assert actual["board_3"]["file_writer_to_data_analyzer"] == [expected[3][0]]
    assert actual["board_2"]["file_writer_to_data_analyzer"] == [expected[2][0]]
    assert actual["board_1"]["file_writer_to_data_analyzer"] == [expected[1][0]]
    assert actual["board_0"]["file_writer_to_data_analyzer"] == [expected[0][0]]
    assert actual["from_main_to_data_analyzer"] == [expected_from_main]
    assert actual["from_data_analyzer_to_main"] == [expected_to_main]


def test_DataAnalyzerProcess__raises_error_with_unrecognized_acquisition_manager_command(
    four_board_analyzer_process, mocker, patch_print
):
    p, _, comm_from_main_queue, _, _, _ = four_board_analyzer_process

    expected_command = "fake_command"
    start_command = {
        "communication_type": "acquisition_manager",
        "command": expected_command,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, comm_from_main_queue)

    with pytest.raises(UnrecognizedCommandFromMainToDataAnalyzerError, match=expected_command):
        invoke_process_run_and_check_errors(p)


def test_DataAnalyzerProcess__processes_start_managed_acquisition_command__by_draining_outgoing_data_queue(
    four_board_analyzer_process,
):
    p, board_queues, comm_from_main_queue, _, _, _ = four_board_analyzer_process

    start_command = get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, comm_from_main_queue)

    put_object_into_queue_and_raise_error_if_eventually_still_empty("item", board_queues[0][1])
    invoke_process_run_and_check_errors(p)
    confirm_queue_is_eventually_empty(board_queues[0][1])


def test_DataAnalyzerProcess__raises_error_if_communication_type_is_invalid(
    four_board_analyzer_process, mocker, patch_print
):
    p, _, comm_from_main_queue, _, _, _ = four_board_analyzer_process

    invalid_command = {
        "communication_type": "fake_type",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        invalid_command,
        comm_from_main_queue,
    )

    with pytest.raises(UnrecognizedCommandFromMainToDataAnalyzerError, match="fake_type"):
        invoke_process_run_and_check_errors(p)


def test_DataAnalyzerProcess__logs_performance_metrics_after_creating_beta_1_data(
    four_board_analyzer_process, mocker
):
    da_process, _, _, to_main_queue, _, _ = four_board_analyzer_process

    mocker.patch.object(data_analyzer, "get_force_signal", autospec=True, return_value=np.zeros((2, 2)))

    expected_num_iterations = 10
    expected_iteration_dur = 0.001 * 10**9
    expected_idle_time = expected_iteration_dur * expected_num_iterations
    expected_start_timepoint = 0
    expected_stop_timepoint = 2 * expected_iteration_dur * expected_num_iterations
    expected_latest_percent_use = 100 * (
        1 - expected_idle_time / (expected_stop_timepoint - expected_start_timepoint)
    )
    expected_percent_use_vals = [74.9, 31.7, expected_latest_percent_use]
    expected_data_creation_durs = [3.6, 11.0, 9.5]
    expected_longest_iterations = [expected_iteration_dur for _ in range(da_process.num_longest_iterations)]

    da_process._idle_iteration_time_ns = expected_iteration_dur  # pylint: disable=protected-access
    da_process._minimum_iteration_duration_seconds = (  # pylint: disable=protected-access
        2 * expected_iteration_dur / (10**9)
    )
    da_process._start_timepoint_of_last_performance_measurement = (  # pylint: disable=protected-access
        expected_start_timepoint
    )
    da_process._percent_use_values = expected_percent_use_vals[:-1]  # pylint: disable=protected-access
    da_process._outgoing_data_creation_durations = (  # pylint: disable=protected-access
        expected_data_creation_durs[:-1]
    )
    data_buffer = da_process._data_buffer  # pylint: disable=protected-access
    for i in range(24):
        data_buffer[i]["construct_data"] = np.zeros((2, 2))
        data_buffer[i]["ref_data"] = np.zeros((2, 2))

    perf_counter_ns_vals = []
    for _ in range(expected_num_iterations - 1):
        perf_counter_ns_vals.append(0)
        perf_counter_ns_vals.append(expected_iteration_dur)
    perf_counter_ns_vals.append(0)
    perf_counter_ns_vals.append(expected_stop_timepoint)
    perf_counter_ns_vals.append(0)
    mocker.patch.object(time, "perf_counter_ns", autospec=True, side_effect=perf_counter_ns_vals)

    perf_counter_vals = [0, expected_data_creation_durs[-1]]
    mocker.patch.object(data_analyzer, "perf_counter", autospec=True, side_effect=perf_counter_vals)

    is_data_present_vals = [False for i in range(expected_num_iterations - 1)]
    is_data_present_vals.append(True)
    mocker.patch.object(
        da_process, "_is_data_from_each_well_present", autospec=True, side_effect=is_data_present_vals
    )

    invoke_process_run_and_check_errors(da_process, num_iterations=expected_num_iterations)
    confirm_queue_is_eventually_of_size(
        to_main_queue, 2
    )  # Tanner (1/4/21): log message is also put into queue after waveform data dump

    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual = actual["message"]
    assert actual["communication_type"] == "performance_metrics"
    assert actual["data_creation_duration"] == expected_data_creation_durs[-1]
    assert actual["data_creation_duration_metrics"] == {
        "max": max(expected_data_creation_durs),
        "min": min(expected_data_creation_durs),
        "stdev": round(stdev(expected_data_creation_durs), 6),
        "mean": round(sum(expected_data_creation_durs) / len(expected_data_creation_durs), 6),
    }
    assert "start_timepoint_of_measurements" not in actual
    assert "idle_iteration_time_ns" not in actual
    num_longest_iterations = da_process.num_longest_iterations
    assert actual["longest_iterations"] == expected_longest_iterations[-num_longest_iterations:]
    assert actual["percent_use"] == expected_latest_percent_use
    assert actual["percent_use_metrics"] == {
        "max": max(expected_percent_use_vals),
        "min": min(expected_percent_use_vals),
        "stdev": round(stdev(expected_percent_use_vals), 6),
        "mean": round(sum(expected_percent_use_vals) / len(expected_percent_use_vals), 6),
    }


def test_DataAnalyzerProcess__logs_performance_metrics_after_creating_beta_2_data(
    four_board_analyzer_process_beta_2_mode, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    to_main_queue = four_board_analyzer_process_beta_2_mode["to_main_queue"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    board_queues = four_board_analyzer_process_beta_2_mode["board_queues"]

    # perform setup so performance logging values are initialized
    invoke_process_run_and_check_errors(da_process, perform_setup_before_loop=True)

    # set this to a lower value to speed up the test
    da_process._minimum_iteration_duration_seconds /= 10

    # mock functions to speed up test
    mocker.patch.object(data_analyzer, "get_force_signal", autospec=True, return_value=np.zeros((2, 2)))
    mocker.patch.object(data_analyzer, "peak_detector", autospec=True, side_effect=PeakDetectionError())

    # start managed acquisition
    start_command = get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)
    invoke_process_run_and_check_errors(da_process)
    # remove command receipt
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    # create expected durations for metric creation
    expected_num_data_packets = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
    expected_data_creation_durs = [random.uniform(30, 70) for _ in range(expected_num_data_packets)]
    mocker.patch.object(
        data_analyzer,
        "_get_secs_since_data_creation_start",
        autospec=True,
        side_effect=expected_data_creation_durs,
    )
    expected_data_analysis_durs = [random.uniform(20, 80) for _ in range(24)]
    mocker.patch.object(
        data_analyzer,
        "_get_secs_since_data_analysis_start",
        autospec=True,
        side_effect=expected_data_analysis_durs,
    )

    # create test data packets
    num_data_points_per_second = int(1e6) // DEFAULT_SAMPLING_PERIOD
    for packet_num in range(expected_num_data_packets):
        test_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
        test_packet["time_indices"] = (
            np.arange(
                num_data_points_per_second * packet_num,
                num_data_points_per_second * (packet_num + 1),
                dtype=np.int64,
            )
            * DEFAULT_SAMPLING_PERIOD
        )
        put_object_into_queue_and_raise_error_if_eventually_still_empty(test_packet, board_queues[0][0])
        invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(
        to_main_queue, expected_num_data_packets * 2
    )  # Tanner (1/4/21): a log message is also put into queue after each waveform data dump

    actual = drain_queue(to_main_queue)[-1]["message"]
    assert actual["communication_type"] == "performance_metrics"
    assert actual["data_creation_duration"] == expected_data_creation_durs[-1]
    assert actual["data_creation_duration_metrics"] == {
        "max": max(expected_data_creation_durs),
        "min": min(expected_data_creation_durs),
        "stdev": round(stdev(expected_data_creation_durs), 6),
        "mean": round(sum(expected_data_creation_durs) / len(expected_data_creation_durs), 6),
    }
    assert actual["data_analysis_duration_metrics"] == {
        "max": max(expected_data_analysis_durs),
        "min": min(expected_data_analysis_durs),
        "stdev": round(stdev(expected_data_analysis_durs), 6),
        "mean": round(sum(expected_data_analysis_durs) / len(expected_data_analysis_durs), 6),
    }
    # values created in parent class
    assert "start_timepoint_of_measurements" not in actual
    assert "idle_iteration_time_ns" not in actual
    assert "longest_iterations" in actual
    assert "percent_use" in actual
    assert "percent_use_metrics" in actual

    # prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])


def test_DataAnalyzerProcess__does_not_include_performance_metrics_in_first_logging_cycle__with_beta_1_data(
    four_board_analyzer_process, mocker
):
    # TODO Tanner (8/30/21): change this test to work with Beta 2 data once beta 1 is phased out
    mocker.patch.object(data_analyzer, "get_force_signal", autospec=True, return_value=np.zeros((2, 2)))

    da_process, _, _, to_main_queue, _, _ = four_board_analyzer_process
    da_process._minimum_iteration_duration_seconds = 0  # pylint: disable=protected-access
    data_buffer = da_process._data_buffer  # pylint: disable=protected-access
    for i in range(24):
        data_buffer[i]["construct_data"] = np.zeros((2, 2))
        data_buffer[i]["ref_data"] = np.zeros((2, 2))

    invoke_process_run_and_check_errors(da_process, perform_setup_before_loop=True)
    confirm_queue_is_eventually_of_size(to_main_queue, 2)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual = actual["message"]
    assert "percent_use_metrics" not in actual
    assert "data_creation_duration_metrics" not in actual


def test_DataAnalyzerProcess__processes_set_sampling_period_command(
    four_board_analyzer_process_beta_2_mode,
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]

    expected_sampling_period = 15000
    set_sampling_period_command = {
        "communication_type": "acquisition_manager",
        "command": "set_sampling_period",
        "sampling_period": expected_sampling_period,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        set_sampling_period_command, from_main_queue
    )

    invoke_process_run_and_check_errors(da_process)
    expected_buffer_size = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS * int(1e6 / expected_sampling_period)
    assert da_process.get_buffer_size() == expected_buffer_size


def test_DataAnalyzerProcess__reinits_streams_upon_receiving_stop_managed_acquisition_command(
    four_board_analyzer_process, mocker
):
    p, _, from_main_queue, _, _, _ = four_board_analyzer_process

    spied_init_streams = mocker.spy(p, "init_streams")

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        STOP_MANAGED_ACQUISITION_COMMUNICATION,
        from_main_queue,
    )
    invoke_process_run_and_check_errors(p)

    spied_init_streams.assert_called_once_with()
