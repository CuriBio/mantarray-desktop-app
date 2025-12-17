# -*- coding: utf-8 -*-
import copy
import json
import time

from freezegun import freeze_time
from mantarray_desktop_app import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import SERIAL_COMM_DEFAULT_DATA_CHANNEL
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.constants import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app.simulators.mc_simulator import MantarrayMcSimulator
from mantarray_desktop_app.sub_processes import data_analyzer
from mantarray_desktop_app.sub_processes.data_analyzer import get_force_signal
import numpy as np
from pulse3D.constants import BUTTERWORTH_LOWPASS_30_UUID
from pulse3D.constants import MEMSIC_CENTER_OFFSET
from pulse3D.magnet_finding import fix_dropped_samples
from pulse3D.transforms import create_filter
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty
from stdlib_utils import TestingQueue

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures import TEST_BARCODE_CONFIG
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process_beta_2_mode
from ..fixtures_data_analyzer import fixture_runnable_four_board_analyzer_process
from ..fixtures_data_analyzer import set_sampling_period
from ..fixtures_data_analyzer import TEST_START_MANAGED_ACQUISITION_COMMUNICATION
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..parsed_channel_data_packets import SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS
from ..parsed_channel_data_packets import SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS


__fixtures__ = [fixture_four_board_analyzer_process_beta_2_mode, fixture_runnable_four_board_analyzer_process]


def fill_da_input_data_queue(input_queue, num_seconds):
    simulator = MantarrayMcSimulator(*[TestingQueue() for _ in range(4)])
    test_y_data = np.tile(simulator.get_interpolated_data(DEFAULT_SAMPLING_PERIOD), num_seconds)
    single_packet_duration = DEFAULT_SAMPLING_PERIOD * len(test_y_data)
    for seconds in range(num_seconds):
        data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
        data_packet["time_indices"] = np.arange(
            seconds * single_packet_duration, (seconds + 1) * single_packet_duration, DEFAULT_SAMPLING_PERIOD
        )
        for well_idx in range(24):
            data_packet[well_idx] = {"time_offsets": np.zeros((2, 100), dtype=np.uint16)}
            data_packet[well_idx].update(
                {channel_num: test_y_data.copy() for channel_num in range(SERIAL_COMM_NUM_DATA_CHANNELS)}
            )
        input_queue.put_nowait(data_packet)
    confirm_queue_is_eventually_of_size(
        input_queue, num_seconds, timeout_seconds=3, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )


@pytest.mark.slow
def test_DataAnalyzerProcess_beta_2_performance__fill_data_analysis_buffer(
    runnable_four_board_analyzer_process,
):
    # 11 seconds of data (100 Hz) coming in from File Writer to going through to Main
    #
    # initial pulse3D import:                             1.662150824
    # pulse3D 0.23.3:                                     1.680566285

    p, board_queues, comm_from_main_queue, comm_to_main_queue, *_ = runnable_four_board_analyzer_process
    p._beta_2_mode = True
    p.set_sampling_period(DEFAULT_SAMPLING_PERIOD)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(TEST_START_MANAGED_ACQUISITION_COMMUNICATION), comm_from_main_queue
    )
    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)

    num_seconds = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS + 1
    fill_da_input_data_queue(board_queues[0][0], num_seconds)
    start = time.perf_counter_ns()
    invoke_process_run_and_check_errors(p, num_iterations=num_seconds)
    dur_seconds = (time.perf_counter_ns() - start) / 10**9

    # prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])
    drain_queue(comm_to_main_queue)

    # print(f"Duration (seconds): {dur_seconds}")  # Eli (4/8/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization
    assert dur_seconds < 10


@pytest.mark.slow
def test_DataAnalyzerProcess_beta_2_performance__first_second_of_data_with_analysis(
    runnable_four_board_analyzer_process,
):
    # Fill data analysis buffer with 10 seconds of data to start metric analysis,
    # Then record duration of sending 1 additional second of data
    #
    # initial pulse3D import:                             0.334087008
    # pulse3D 0.23.3:                                     0.337370183

    p, board_queues, comm_from_main_queue, comm_to_main_queue, *_ = runnable_four_board_analyzer_process
    p._beta_2_mode = True
    p.set_sampling_period(DEFAULT_SAMPLING_PERIOD)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(TEST_START_MANAGED_ACQUISITION_COMMUNICATION), comm_from_main_queue
    )
    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)

    # load data
    num_seconds = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS + 1
    fill_da_input_data_queue(board_queues[0][0], num_seconds)
    invoke_process_run_and_check_errors(p, num_iterations=num_seconds - 1)

    # send additional data and time analysis
    start = time.perf_counter_ns()
    invoke_process_run_and_check_errors(p)
    dur_seconds = (time.perf_counter_ns() - start) / 10**9

    # prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])
    drain_queue(comm_to_main_queue)

    # print(f"Duration (seconds): {dur_seconds}")  # Eli (4/8/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization
    assert dur_seconds < 2


@pytest.mark.slow
def test_DataAnalyzerProcess_beta_2_performance__single_data_packet_per_well_without_analysis(
    runnable_four_board_analyzer_process,
):
    # 1 second of data (100 Hz) coming in from File Writer to going through to Main
    #
    # initial pulse3D import:                             0.224968242
    # pulse3D 0.23.3:                                     0.225489661

    p, board_queues, comm_from_main_queue, comm_to_main_queue, *_ = runnable_four_board_analyzer_process
    p._beta_2_mode = True
    p.set_sampling_period(DEFAULT_SAMPLING_PERIOD)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(TEST_START_MANAGED_ACQUISITION_COMMUNICATION), comm_from_main_queue
    )
    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)

    num_seconds = 1
    fill_da_input_data_queue(board_queues[0][0], num_seconds)
    start = time.perf_counter_ns()
    invoke_process_run_and_check_errors(p, num_iterations=num_seconds)
    dur_seconds = (time.perf_counter_ns() - start) / 10**9

    # prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])
    drain_queue(comm_to_main_queue)

    # print(f"Duration (seconds): {dur_seconds}")  # Eli (4/8/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization
    assert dur_seconds < 2


@freeze_time("2021-06-15 16:39:10.120589")
@pytest.mark.parametrize("final_plate_barcode_char", ["2", "5"])
def test_DataAnalyzerProcess__sends_outgoing_data_dict_to_main_as_soon_as_it_retrieves_a_data_packet_from_file_writer__and_sends_data_available_message_to_main(
    final_plate_barcode_char, four_board_analyzer_process_beta_2_mode, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    to_main_queue = four_board_analyzer_process_beta_2_mode["to_main_queue"]
    incoming_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][0]
    outgoing_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][1]

    spied_fix = mocker.spy(data_analyzer, "fix_dropped_samples")
    # mock so that well metrics don't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_outgoing_well_metrics", autospec=True)
    # mock so performance log messages don't populate queue to main
    mocker.patch.object(da_process, "_handle_performance_logging", autospec=True)

    da_process.init_streams()
    # set arbitrary sampling period
    test_sampling_period = 1000
    set_sampling_period(four_board_analyzer_process_beta_2_mode, test_sampling_period)
    test_barcode = TEST_START_MANAGED_ACQUISITION_COMMUNICATION["barcode"][:-1] + final_plate_barcode_char

    # start managed_acquisition
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {**TEST_START_MANAGED_ACQUISITION_COMMUNICATION, "barcode": test_barcode}, from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    # remove message to main
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_empty(outgoing_data_queue)
    confirm_queue_is_eventually_empty(to_main_queue)

    test_data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    # fix time indices so it doesn't create "ZeroDivisionError: float division"
    test_data_packet["time_indices"] = np.arange(test_data_packet["time_indices"].shape[0])
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(test_data_packet), incoming_data_queue
    )

    invoke_process_run_and_check_errors(da_process)
    assert spied_fix.call_count == 24
    confirm_queue_is_eventually_of_size(outgoing_data_queue, 1)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    # test data dump
    waveform_data_points = dict()
    filter_coefficients = create_filter(BUTTERWORTH_LOWPASS_30_UUID, test_sampling_period)
    for well_idx in range(24):
        default_channel_data = test_data_packet[well_idx][SERIAL_COMM_DEFAULT_DATA_CHANNEL]
        fixed_default_channel_data = fix_dropped_samples(default_channel_data)
        flipped_default_channel_data = (
            (fixed_default_channel_data.astype(np.int32) - max(fixed_default_channel_data)) * -1
            + MEMSIC_CENTER_OFFSET
        ).astype(np.uint16)
        compressed_data = get_force_signal(
            np.array([test_data_packet["time_indices"], flipped_default_channel_data], np.int64),
            filter_coefficients,
            test_barcode,
            well_idx,
            magnet_type_to_mt_per_mm=TEST_BARCODE_CONFIG["plate"]["S"],
        )
        waveform_data_points[well_idx] = {
            "x_data_points": compressed_data[0].tolist(),
            "y_data_points": (compressed_data[1] * MICRO_TO_BASE_CONVERSION).tolist(),
        }
    expected_outgoing_dict = {
        "waveform_data": {"basic_data": {"waveform_data_points": waveform_data_points}},
        "earliest_timepoint": test_data_packet["time_indices"][0].item(),
        "latest_timepoint": test_data_packet["time_indices"][-1].item(),
        "num_data_points": len(test_data_packet["time_indices"]),
    }

    outgoing_msg = outgoing_data_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert outgoing_msg["data_type"] == "waveform_data"
    assert outgoing_msg["data_json"] == json.dumps(expected_outgoing_dict)
    # test message sent to main
    outgoing_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_msg = {
        "communication_type": "data_available",
        "timestamp": "2021-06-15 16:39:10.120589",
        "num_data_points": len(test_data_packet["time_indices"]),
        "earliest_timepoint": test_data_packet["time_indices"][0],
        "latest_timepoint": test_data_packet["time_indices"][-1],
    }
    assert outgoing_msg == expected_msg


@pytest.mark.parametrize("data_type", ["mag", "stim"])
def test_DataAnalyzerProcess__does_not_process_any_packets_after_receiving_stop_managed_acquisition_command_until_receiving_first_packet_of_new_stream(
    data_type, four_board_analyzer_process_beta_2_mode, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    to_main_queue = four_board_analyzer_process_beta_2_mode["to_main_queue"]
    incoming_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][0]

    test_packet = copy.deepcopy(
        SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS
        if data_type == "mag"
        else SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS
    )

    # mock since not using real data
    fn_name = "_process_beta_2_data" if data_type == "mag" else "_process_stim_packet"
    mocked_process_data = mocker.patch.object(da_process, fn_name, autospec=True)

    invoke_process_run_and_check_errors(da_process, perform_setup_before_loop=True)

    # start managed_acquisition
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(TEST_START_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)
    # send first packet of first stream and make sure it is processed
    test_data_packet = copy.deepcopy(test_packet)
    test_data_packet["is_first_packet_of_stream"] = True
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 1
    # send another packet of first stream and make sure it is processed
    test_data_packet = copy.deepcopy(test_packet)
    test_data_packet["is_first_packet_of_stream"] = False
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 2

    # stop managed acquisition and make sure next data packet in the first stream is not processed
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(STOP_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)
    test_data_packet = copy.deepcopy(test_packet)
    test_data_packet["is_first_packet_of_stream"] = False
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 2

    # start managed acquisition again and make sure next data packet in the first stream is not processed
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(TEST_START_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)
    test_data_packet = copy.deepcopy(test_packet)
    test_data_packet["is_first_packet_of_stream"] = False
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 2

    # send first data packet from second stream and make sure it is processed
    test_data_packet = copy.deepcopy(test_packet)
    test_data_packet["is_first_packet_of_stream"] = True
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 3

    # prevent BrokenPipeErrors
    drain_queue(to_main_queue)


def test_DataAnalyzerProcess__formats_and_passes_incoming_stim_packet_through_to_main(
    four_board_analyzer_process_beta_2_mode,
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    incoming_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][0]
    outgoing_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][1]

    test_stim_packet = copy.deepcopy(SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(test_stim_packet), incoming_data_queue
    )
    invoke_process_run_and_check_errors(da_process)

    confirm_queue_is_eventually_of_size(outgoing_data_queue, 1)
    outgoing_msg = outgoing_data_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    expected_stim_data = {
        well_idx: stim_status_arr.tolist()
        for well_idx, stim_status_arr in test_stim_packet["well_statuses"].items()
    }

    assert outgoing_msg["data_type"] == "stimulation_data"
    assert outgoing_msg["data_json"] == json.dumps(expected_stim_data)
