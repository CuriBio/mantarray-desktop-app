# -*- coding: utf-8 -*-
import copy
import json

from mantarray_desktop_app import DATA_ANALYZER_BETA_1_BUFFER_SIZE
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.data_analyzer import append_beta_1_data
from mantarray_desktop_app.data_analyzer import check_for_new_twitches
from mantarray_desktop_app.data_analyzer import get_pipeline_analysis
from mantarray_desktop_app.data_analyzer import PIPELINE_TEMPLATE
from mantarray_waveform_analysis import AMPLITUDE_UUID
from mantarray_waveform_analysis import TWITCH_FREQUENCY_UUID
import numpy as np
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..parsed_channel_data_packets import SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0


__fixtures__ = [fixture_four_board_analyzer_process, fixture_mantarray_mc_simulator]


def test_append_beta_1_data__correctly_appends_x_and_y_data_from_numpy_array_to_list():
    init_list = [list(), list()]
    expected_list = [[0], [1]]
    new_list, downstream_new_list = append_beta_1_data(init_list, expected_list)
    assert new_list[0] == expected_list[0]
    assert new_list[1] == expected_list[1]
    assert downstream_new_list[0] == expected_list[0]
    assert downstream_new_list[1] == expected_list[1]


def test_append_beta_1_data__removes_oldest_data_points_when_buffer_exceeds_max_size():
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
    new_list, _ = append_beta_1_data(init_list, new_data)
    assert new_list[0] == list(range(3, DATA_ANALYZER_BETA_1_BUFFER_SIZE + 3))
    assert new_list[1] == list(range(3, DATA_ANALYZER_BETA_1_BUFFER_SIZE + 3))


def test_get_pipeline_analysis__returns_displacement_metrics_from_given_data(mantarray_mc_simulator):
    # Tanner (7/12/21): This test is "True by definition", but can't think of a better way to test waveform analysis
    test_y_data = (
        mantarray_mc_simulator["simulator"]
        .get_interpolated_data(ROUND_ROBIN_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND)
        .tolist()
        * MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
    )
    test_x_data = np.arange(0, ROUND_ROBIN_PERIOD * len(test_y_data), ROUND_ROBIN_PERIOD)
    test_data_arr = np.array([test_x_data, test_y_data], dtype=np.int32)

    pipeline = PIPELINE_TEMPLATE.create_pipeline()
    pipeline.load_raw_gmr_data(test_data_arr, np.zeros(test_data_arr.shape))
    expected_metrics = pipeline.get_displacement_data_metrics(
        metrics_to_create=[AMPLITUDE_UUID, TWITCH_FREQUENCY_UUID]
    )[0]

    actual = get_pipeline_analysis(test_data_arr.tolist())

    assert actual.keys() == expected_metrics.keys()
    for k in expected_metrics.keys():
        assert actual[k] == expected_metrics[k], f"Incorrect twitch dict at idx {k}"


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


def test_DataAnalyzerProcess__sends_single_beta_1_well_metrics_to_main_when_ready(
    four_board_analyzer_process, mantarray_mc_simulator
):
    # Tanner (7/13/21): this test assumes no waveform data will be put into the data queue to main
    da_process, board_queues, comm_from_main_queue, _, _ = four_board_analyzer_process
    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        START_MANAGED_ACQUISITION_COMMUNICATION, comm_from_main_queue
    )

    expected_well_idx = 0

    test_y_data = (
        mantarray_mc_simulator["simulator"]
        .get_interpolated_data(ROUND_ROBIN_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND)
        .tolist()
        * MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
    )
    test_x_data = np.arange(0, ROUND_ROBIN_PERIOD * len(test_y_data), ROUND_ROBIN_PERIOD)
    test_data_arr = np.array([test_x_data, test_y_data], dtype=np.int32)

    test_packet = copy.deepcopy(SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0)
    test_packet["data"] = test_data_arr
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_packet, board_queues[0][0])

    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(board_queues[0][1], 1)

    outgoing_metrics = board_queues[0][1].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert outgoing_metrics["data_type"] == "twitch_metrics"
    expected_well_metric_dict = json.loads(outgoing_metrics["data_json"])[str(expected_well_idx)]
    assert list(expected_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
    for metric_id, metric_list in expected_well_metric_dict.items():
        # Tanner (7/13/21): to guard against future changes to mantarray-waveform-analysis breaking this test, only asserting that the correct number of data points are present
        assert len(metric_list) == 5, metric_id
