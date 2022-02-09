# -*- coding: utf-8 -*-
import copy
import json

from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import DATA_ANALYZER_BETA_1_BUFFER_SIZE
from mantarray_desktop_app import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.data_analyzer import check_for_new_twitches
import numpy as np
from pulse3D.constants import AMPLITUDE_UUID
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from pulse3D.constants import TWITCH_FREQUENCY_UUID
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process_beta_2_mode
from ..fixtures_data_analyzer import set_magnetometer_config
from ..fixtures_file_writer import GENERIC_BOARD_MAGNETOMETER_CONFIGURATION
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..parsed_channel_data_packets import SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0
from ..parsed_channel_data_packets import SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS


__fixtures__ = [
    fixture_four_board_analyzer_process,
    fixture_four_board_analyzer_process_beta_2_mode,
    fixture_mantarray_mc_simulator,
]


def test_append_data__beta_1__correctly_appends_x_and_y_data_from_numpy_array_to_list(
    four_board_analyzer_process,
):
    da_process, *_ = four_board_analyzer_process

    init_list = [list(), list()]
    expected_list = [[0], [1]]
    new_list, downstream_new_list = da_process.append_data(init_list, expected_list)
    assert new_list[0] == expected_list[0]
    assert new_list[1] == expected_list[1]
    assert downstream_new_list[0] == expected_list[0]
    assert downstream_new_list[1] == expected_list[1]


def test_append_data__beta_1__removes_oldest_data_points_when_buffer_exceeds_required_size(
    four_board_analyzer_process,
):
    da_process, *_ = four_board_analyzer_process

    init_list = init_list = [
        list(range(DATA_ANALYZER_BETA_1_BUFFER_SIZE)),
        list(range(DATA_ANALYZER_BETA_1_BUFFER_SIZE)),
    ]
    new_data = np.array(
        [
            np.arange(DATA_ANALYZER_BETA_1_BUFFER_SIZE, DATA_ANALYZER_BETA_1_BUFFER_SIZE + 3),
            np.arange(DATA_ANALYZER_BETA_1_BUFFER_SIZE, DATA_ANALYZER_BETA_1_BUFFER_SIZE + 3),
        ]
    )
    new_list, _ = da_process.append_data(init_list, new_data)
    assert new_list[0] == list(range(3, DATA_ANALYZER_BETA_1_BUFFER_SIZE + 3))
    assert new_list[1] == list(range(3, DATA_ANALYZER_BETA_1_BUFFER_SIZE + 3))


def test_append_data__beta_2__correctly_appends_x_and_y_data_from_numpy_array_to_list(
    four_board_analyzer_process_beta_2_mode,
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]

    expected_sampling_period_us = 13000
    set_magnetometer_config(
        four_board_analyzer_process_beta_2_mode,
        {
            "magnetometer_config": GENERIC_BOARD_MAGNETOMETER_CONFIGURATION,
            "sampling_period": expected_sampling_period_us,
        },
    )

    init_list = [list(), list()]
    expected_list = [[0], [1]]
    new_list, downstream_new_list = da_process.append_data(init_list, expected_list)
    assert new_list[0] == expected_list[0]
    assert new_list[1] == expected_list[1]
    assert downstream_new_list[0] == expected_list[0]
    assert downstream_new_list[1] == expected_list[1]


def test_append_data__beta_2__removes_oldest_data_points_when_buffer_exceeds_required_size(
    four_board_analyzer_process_beta_2_mode,
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]

    expected_sampling_period_us = 15000
    set_magnetometer_config(
        four_board_analyzer_process_beta_2_mode,
        {
            "magnetometer_config": GENERIC_BOARD_MAGNETOMETER_CONFIGURATION,
            "sampling_period": expected_sampling_period_us,
        },
    )

    expected_buffer_size = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS * int(1e6 / expected_sampling_period_us)

    init_list = init_list = [
        list(range(expected_buffer_size)),
        list(range(expected_buffer_size)),
    ]
    new_data = np.array(
        [
            np.arange(expected_buffer_size, expected_buffer_size + 3),
            np.arange(expected_buffer_size, expected_buffer_size + 3),
        ]
    )
    new_list, _ = da_process.append_data(init_list, new_data)
    assert new_list[0] == list(range(3, expected_buffer_size + 3))
    assert new_list[1] == list(range(3, expected_buffer_size + 3))


def test_get_twitch_analysis__returns_error_dict_when_peak_detection_error_occurs_during_analysis(
    four_board_analyzer_process,
):
    da_process, *_ = four_board_analyzer_process

    # Tanner (7/14/21): using Beta 1 data here, but error catching should work for Beta 2 data as well
    data_len = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS * int(CENTIMILLISECONDS_PER_SECOND / ROUND_ROBIN_PERIOD)

    # use a flat line here to raise an error due to no peaks being detected
    test_y_data = np.zeros(data_len)
    test_x_data = np.arange(0, ROUND_ROBIN_PERIOD * len(test_y_data), ROUND_ROBIN_PERIOD)
    test_data_arr = np.array([test_x_data, test_y_data], dtype=np.int32)

    actual = da_process.get_twitch_analysis(test_data_arr.tolist())
    assert actual == {-1: None}


def test_get_twitch_analysis__returns_force_metrics_from_given_beta_1_data(
    four_board_analyzer_process, mantarray_mc_simulator
):
    da_process, *_ = four_board_analyzer_process
    # Tanner (7/12/21): This test is "True by definition", but can't think of a better way to test waveform analysis
    test_y_data = (
        mantarray_mc_simulator["simulator"]
        .get_interpolated_data(ROUND_ROBIN_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND)
        .tolist()
        * MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
    )
    test_x_data = (
        np.arange(0, ROUND_ROBIN_PERIOD * len(test_y_data), ROUND_ROBIN_PERIOD)
        * MICROSECONDS_PER_CENTIMILLISECOND
    )
    test_data_arr = np.array([test_x_data, test_y_data], dtype=np.int32)

    pipeline = da_process.get_pipeline_template().create_pipeline()
    pipeline.load_raw_magnetic_data(test_data_arr, np.zeros(test_data_arr.shape))
    expected_metrics = pipeline.get_force_data_metrics(
        metrics_to_create=[AMPLITUDE_UUID, TWITCH_FREQUENCY_UUID]
    )[0]

    actual = da_process.get_twitch_analysis(test_data_arr.tolist())

    assert actual.keys() == expected_metrics.keys()
    for k in expected_metrics.keys():
        assert actual[k] == expected_metrics[k], f"Incorrect twitch dict at idx {k}"


def test_get_twitch_analysis__returns_force_metrics_from_given_beta_2_data(
    four_board_analyzer_process, mantarray_mc_simulator
):
    da_process, *_ = four_board_analyzer_process
    # Tanner (7/12/21): This test is "True by definition", but can't think of a better way to test waveform analysis
    test_y_data = (
        mantarray_mc_simulator["simulator"].get_interpolated_data(DEFAULT_SAMPLING_PERIOD).tolist()
        * MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
    )
    test_x_data = np.arange(0, DEFAULT_SAMPLING_PERIOD * len(test_y_data), DEFAULT_SAMPLING_PERIOD)
    test_data_arr = np.array([test_x_data, test_y_data], dtype=np.int64)

    pipeline = da_process.get_pipeline_template().create_pipeline()
    pipeline.load_raw_magnetic_data(test_data_arr, np.zeros(test_data_arr.shape))
    expected_metrics = pipeline.get_force_data_metrics(
        metrics_to_create=[AMPLITUDE_UUID, TWITCH_FREQUENCY_UUID]
    )[0]

    actual = da_process.get_twitch_analysis(test_data_arr.tolist())

    assert actual.keys() == expected_metrics.keys()
    for k in expected_metrics.keys():
        assert actual[k] == expected_metrics[k], f"Incorrect twitch dict at idx {k}"


def test_check_for_new_twitches__returns_empty_dict_when_receiving_peak_detection_error_dict():
    latest_time_index = 0

    error_dict = {-1: None}
    updated_time_index, actual_dict = check_for_new_twitches(latest_time_index, error_dict)

    assert updated_time_index == latest_time_index
    assert actual_dict == {}


def test_check_for_new_twitches__returns_latest_twitch_index_and_empty_metric_dict__when_no_new_twitch_metrics_present():
    latest_time_index = 10
    # Tanner (7/12/21): function should only check keys of the top-level dict, so values can be None
    test_dict = {0: None, 9: None, latest_time_index: None}
    updated_time_index, actual_dict = check_for_new_twitches(latest_time_index, test_dict)

    assert updated_time_index == latest_time_index
    assert actual_dict == {}


def test_check_for_new_twitches__returns_latest_twitch_index_and_populated_metric_dict__when_two_new_twitch_metrics_present():
    latest_time_index = 5
    # Tanner (7/12/21): function should only check keys of the top-level dict, so values can be None
    test_dict = {0: None, latest_time_index: None, (latest_time_index + 1): None, 10: None}
    updated_time_index, actual_dict = check_for_new_twitches(latest_time_index, test_dict)

    assert updated_time_index == 10
    assert actual_dict == {(latest_time_index + 1): None, 10: None}


def test_DataAnalyzerProcess__sends_beta_1_metrics_of_all_wells_to_main_when_ready(
    four_board_analyzer_process, mantarray_mc_simulator, mocker
):
    da_process, board_queues, from_main_queue, _, _ = four_board_analyzer_process
    da_process.init_streams()

    # mock so waveform data doesn't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_data_into_queue", autospec=True)

    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )

    # twitch waveform to send for wells 0-10
    test_y_data = (
        mantarray_mc_simulator["simulator"]
        .get_interpolated_data(ROUND_ROBIN_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND)
        .tolist()
        * MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
    )
    test_x_data = np.arange(0, ROUND_ROBIN_PERIOD * len(test_y_data), ROUND_ROBIN_PERIOD)
    test_data_arr = np.array([test_x_data, test_y_data], dtype=np.int32)
    # flat line to send for wells 11-23
    dummy_data_arr = np.array([test_x_data, np.zeros(len(test_y_data))], dtype=np.int32)

    # send less data than required for analysis first
    for well_idx in range(24):
        test_packet_1 = copy.deepcopy(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)
        test_packet_1["well_index"] = well_idx
        test_packet_1["data"] = test_data_arr[:, :-100] if well_idx <= 10 else dummy_data_arr[:, :-100]
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            copy.deepcopy(test_packet_1), board_queues[0][0]
        )
        invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_empty(board_queues[0][1])

    # send remaining data
    for well_idx in range(24):
        test_packet_2 = copy.deepcopy(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)
        test_packet_2["well_index"] = well_idx
        test_packet_2["data"] = test_data_arr[:, -100:] if well_idx <= 10 else dummy_data_arr[:, -100:]
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            copy.deepcopy(test_packet_2), board_queues[0][0]
        )
        invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)

    outgoing_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert outgoing_msg["data_type"] == "twitch_metrics"
    outgoing_metrics = json.loads(outgoing_msg["data_json"])
    for well_idx in range(24):
        if well_idx > 10:
            assert str(well_idx) not in outgoing_metrics, well_idx
            continue

        actual_well_metric_dict = outgoing_metrics[str(well_idx)]
        assert list(actual_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
        for metric_id, metric_list in actual_well_metric_dict.items():
            # Tanner (7/13/21): to guard against future changes to mantarray-waveform-analysis breaking this test, only asserting that the correct number of data points are present
            assert (
                len(metric_list) == MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 2
            ), f"Well: {well_idx}, Metric ID: {metric_id}"


def test_DataAnalyzerProcess__sends_beta_2_metrics_of_all_wells_to_main_when_ready(
    four_board_analyzer_process_beta_2_mode, mantarray_mc_simulator, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    da_process.init_streams()

    # mock so waveform data doesn't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_data_into_queue", autospec=True)
    mocker.patch.object(da_process, "_create_outgoing_beta_2_data", autospec=True)
    mocker.patch.object(da_process, "_handle_performance_logging", autospec=True)

    expected_sampling_period_us = 11000
    set_magnetometer_config(
        four_board_analyzer_process_beta_2_mode,
        {
            "magnetometer_config": GENERIC_BOARD_MAGNETOMETER_CONFIGURATION,
            "sampling_period": expected_sampling_period_us,
        },
    )

    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    board_queues = four_board_analyzer_process_beta_2_mode["board_queues"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )

    # twitch waveform to send for wells 0-10
    test_y_data = (
        mantarray_mc_simulator["simulator"].get_interpolated_data(expected_sampling_period_us).tolist()
        * MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
    )
    test_x_data = np.arange(
        0, expected_sampling_period_us * len(test_y_data), expected_sampling_period_us, dtype=np.uint64
    )
    # flat line to send for wells 11-23
    dummy_y_data = np.zeros(len(test_y_data))

    # send less data than required for analysis first
    test_packet_1 = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_packet_1["time_indices"] = test_x_data[:-50]
    for well_idx in range(24):
        # Tanner (7/14/21): time offsets are currently unused in data analyzer so not modifying them here
        first_channel = list(test_packet_1[well_idx].keys())[1]
        y_data = test_y_data if well_idx <= 10 else dummy_y_data
        test_packet_1[well_idx][first_channel] = np.array(y_data[:-50], dtype=np.uint16)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_packet_1, board_queues[0][0])
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_empty(board_queues[0][1])

    # send remaining data
    test_packet_2 = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_packet_2["time_indices"] = test_x_data[-50:]
    for well_idx in range(24):
        # Tanner (7/14/21): time offsets are currently unused in data analyzer so not modifying them here
        first_channel = list(test_packet_2[well_idx].keys())[1]
        y_data = test_y_data if well_idx <= 10 else dummy_y_data
        test_packet_2[well_idx][first_channel] = np.array(y_data[-50:], dtype=np.uint16)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_packet_2, board_queues[0][0])
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)

    outgoing_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert outgoing_msg["data_type"] == "twitch_metrics"
    outgoing_metrics = json.loads(outgoing_msg["data_json"])
    for well_idx in range(24):
        if well_idx > 10:
            assert str(well_idx) not in outgoing_metrics, well_idx
            continue

        actual_well_metric_dict = outgoing_metrics[str(well_idx)]
        assert list(actual_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
        for metric_id, metric_list in actual_well_metric_dict.items():
            # Tanner (7/13/21): to guard against future changes to mantarray-waveform-analysis breaking this test, only asserting that the correct number of data points are present
            assert (
                len(metric_list) == MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 2
            ), f"Well: {well_idx}, Metric ID: {metric_id}"


def test_DataAnalyzerProcess__only_dumps_new_twitch_metrics__with_beta_1_data(
    four_board_analyzer_process, mantarray_mc_simulator, mocker
):
    da_process, board_queues, from_main_queue, _, _ = four_board_analyzer_process
    da_process.init_streams()

    # mock so waveform data doesn't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_data_into_queue", autospec=True)

    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )

    single_second_of_data = mantarray_mc_simulator["simulator"].get_interpolated_data(
        ROUND_ROBIN_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
    )
    num_data_points_per_second = len(single_second_of_data)

    test_y_data = single_second_of_data.tolist() * (MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS + 1)
    test_x_data = np.arange(0, ROUND_ROBIN_PERIOD * len(test_y_data), ROUND_ROBIN_PERIOD)
    test_data_arr = np.array([test_x_data, test_y_data], dtype=np.int32)

    # send first round of data through for analysis
    for well_idx in range(24):
        test_packet_1 = copy.deepcopy(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)
        test_packet_1["data"] = test_data_arr[:, :-num_data_points_per_second]
        test_packet_1["well_index"] = well_idx
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            copy.deepcopy(test_packet_1), board_queues[0][0]
        )
        invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    # check all analyzable twitches are reported for each well
    outgoing_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    outgoing_metrics = json.loads(outgoing_msg["data_json"])
    for well_idx in range(24):
        actual_well_metric_dict = outgoing_metrics[str(well_idx)]
        assert list(actual_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
        for metric_id, metric_list in actual_well_metric_dict.items():
            # Tanner (7/13/21): to guard against future changes to mantarray-waveform-analysis breaking this test, only asserting that the correct number of data points are present
            assert (
                len(metric_list) == MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 2
            ), f"Well: {well_idx}, Metric ID: {metric_id}"

    # send remaining data (1 second / 1 new twitch)
    for well_idx in range(24):
        test_packet_2 = copy.deepcopy(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)
        test_packet_2["data"] = test_data_arr[:, -num_data_points_per_second:]
        test_packet_2["well_index"] = well_idx
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            copy.deepcopy(test_packet_2), board_queues[0][0]
        )
        invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    # check that only the newly analyzable twitch is reported for each well
    outgoing_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    outgoing_metrics = json.loads(outgoing_msg["data_json"])
    for well_idx in range(24):
        actual_well_metric_dict = outgoing_metrics[str(well_idx)]
        assert list(actual_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
        for metric_id, metric_list in actual_well_metric_dict.items():
            # Tanner (7/13/21): to guard against future changes to mantarray-waveform-analysis breaking this test, only asserting that the correct number of data points are present
            assert len(metric_list) == 1, f"Well: {well_idx}, Metric ID: {metric_id}"


def test_DataAnalyzerProcess__only_dumps_new_twitch_metrics__with_beta_2_data(
    four_board_analyzer_process_beta_2_mode, mantarray_mc_simulator, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    da_process.init_streams()

    # mock so waveform data doesn't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_data_into_queue", autospec=True)
    mocker.patch.object(da_process, "_create_outgoing_beta_2_data", autospec=True)
    mocker.patch.object(da_process, "_handle_performance_logging", autospec=True)

    expected_sampling_period_us = 13000
    set_magnetometer_config(
        four_board_analyzer_process_beta_2_mode,
        {
            "magnetometer_config": GENERIC_BOARD_MAGNETOMETER_CONFIGURATION,
            "sampling_period": expected_sampling_period_us,
        },
    )

    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    board_queues = four_board_analyzer_process_beta_2_mode["board_queues"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )

    single_second_of_data = mantarray_mc_simulator["simulator"].get_interpolated_data(
        expected_sampling_period_us
    )
    num_data_points_per_second = len(single_second_of_data)

    test_y_data = single_second_of_data.tolist() * (MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS + 1)
    test_x_data = np.arange(
        0, expected_sampling_period_us * len(test_y_data), expected_sampling_period_us, dtype=np.uint64
    )

    # send first round of data through for analysis
    test_packet_1 = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_packet_1["time_indices"] = test_x_data[:-num_data_points_per_second]
    for well_idx in range(24):
        # Tanner (7/14/21): time offsets are currently unused in data analyzer so not modifying them here
        first_channel = list(test_packet_1[well_idx].keys())[1]
        test_packet_1[well_idx][first_channel] = np.array(
            test_y_data[:-num_data_points_per_second], dtype=np.uint16
        )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_packet_1, board_queues[0][0])
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    # check all analyzable twitches are reported for each well
    outgoing_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    outgoing_metrics = json.loads(outgoing_msg["data_json"])
    for well_idx in range(24):
        actual_well_metric_dict = outgoing_metrics[str(well_idx)]
        assert list(actual_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
        for metric_id, metric_list in actual_well_metric_dict.items():
            # Tanner (7/13/21): to guard against future changes to mantarray-waveform-analysis breaking this test, only asserting that the correct number of data points are present
            assert (
                len(metric_list) == MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 2
            ), f"Well: {well_idx}, Metric ID: {metric_id}"

    # send remaining data (1 second / 1 new twitch)
    test_packet_2 = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_packet_2["time_indices"] = test_x_data[-num_data_points_per_second:]
    for well_idx in range(24):
        # Tanner (7/14/21): time offsets are currently unused in data analyzer so not modifying them here
        first_channel = list(test_packet_2[well_idx].keys())[1]
        test_packet_2[well_idx][first_channel] = np.array(
            test_y_data[-num_data_points_per_second:], dtype=np.uint16
        )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_packet_2, board_queues[0][0])
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    # check that only the newly analyzable twitch is reported for each well
    outgoing_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    outgoing_metrics = json.loads(outgoing_msg["data_json"])
    for well_idx in range(24):
        actual_well_metric_dict = outgoing_metrics[str(well_idx)]
        assert list(actual_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
        for metric_id, metric_list in actual_well_metric_dict.items():
            # Tanner (7/13/21): to guard against future changes to mantarray-waveform-analysis breaking this test, only asserting that the correct number of data points are present
            assert len(metric_list) == 1, f"Well: {well_idx}, Metric ID: {metric_id}"


def test_DataAnalyzerProcess__data_analysis_stream_is_reconfigured_in_beta_2_mode_upon_receiving_change_magnetometer_config_command(
    four_board_analyzer_process_beta_2_mode, mantarray_mc_simulator, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    da_process.init_streams()

    # mock so waveform data doesn't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_data_into_queue", autospec=True)
    mocker.patch.object(da_process, "_create_outgoing_beta_2_data", autospec=True)
    mocker.patch.object(da_process, "_handle_performance_logging", autospec=True)

    expected_sampling_period_us = 12000
    set_magnetometer_config(
        four_board_analyzer_process_beta_2_mode,
        {
            "magnetometer_config": GENERIC_BOARD_MAGNETOMETER_CONFIGURATION,
            "sampling_period": expected_sampling_period_us,
        },
    )

    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    board_queues = four_board_analyzer_process_beta_2_mode["board_queues"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )

    single_second_of_data = mantarray_mc_simulator["simulator"].get_interpolated_data(
        expected_sampling_period_us
    )

    test_y_data = single_second_of_data.tolist() * MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
    test_x_data = np.arange(
        0, expected_sampling_period_us * len(test_y_data), expected_sampling_period_us, dtype=np.uint64
    )

    # send first round of data through will all wells enabled
    test_packet_1 = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_packet_1["time_indices"] = test_x_data
    for well_idx in range(24):
        # Tanner (7/14/21): time offsets are currently unused in data analyzer so not modifying them here
        first_channel = list(test_packet_1[well_idx].keys())[1]
        test_packet_1[well_idx][first_channel] = np.array(test_y_data, dtype=np.uint16)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_packet_1, board_queues[0][0])
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    # check all analyzable twitches are reported for each well
    outgoing_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    outgoing_metrics = json.loads(outgoing_msg["data_json"])
    for well_idx in range(24):
        actual_well_metric_dict = outgoing_metrics[str(well_idx)]
        assert list(actual_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
        for metric_id, metric_list in actual_well_metric_dict.items():
            assert (
                len(metric_list) == MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 2
            ), f"Well: {well_idx}, Metric ID: {metric_id}"

    # change magnetometer config so that only wells 20-23 are enabled
    test_config = create_magnetometer_config_dict(24)
    for well_idx in range(20, 24):
        module_id = SERIAL_COMM_WELL_IDX_TO_MODULE_ID[well_idx]
        # enable arbitrary channel
        test_config[module_id][2] = True
    set_magnetometer_config(
        four_board_analyzer_process_beta_2_mode,
        {"magnetometer_config": test_config, "sampling_period": expected_sampling_period_us},
    )

    # send second round of data through will only some wells enabled
    test_packet_2 = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_packet_2["time_indices"] = test_x_data
    for well_idx in range(24):
        # Tanner (7/14/21): time offsets are currently unused in data analyzer so not modifying them here
        first_channel = list(test_packet_2[well_idx].keys())[1]
        test_packet_2[well_idx][first_channel] = np.array(test_y_data, dtype=np.uint16)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_packet_2, board_queues[0][0])
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)
    # check all analyzable twitches are reported only for enabled wells
    outgoing_msg = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    outgoing_metrics = json.loads(outgoing_msg["data_json"])
    for well_idx in range(24):
        if well_idx < 20:
            assert str(well_idx) not in outgoing_metrics, well_idx
            continue

        actual_well_metric_dict = outgoing_metrics[str(well_idx)]
        assert list(actual_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
        for metric_id, metric_list in actual_well_metric_dict.items():
            assert (
                len(metric_list) == MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 2
            ), f"Well: {well_idx}, Metric ID: {metric_id}"
