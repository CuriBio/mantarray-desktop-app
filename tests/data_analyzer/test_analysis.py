# -*- coding: utf-8 -*-
from mantarray_desktop_app import DATA_ANALYZER_BETA_1_BUFFER_SIZE
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app.data_analyzer import append_data
from mantarray_desktop_app.data_analyzer import get_pipeline_analysis
from mantarray_desktop_app.data_analyzer import PIPELINE_TEMPLATE
from mantarray_waveform_analysis import IRREGULARITY_INTERVAL_UUID
import numpy as np

from ..fixtures_data_analyzer import fixture_four_board_analyzer_process
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator


__fixtures__ = [fixture_four_board_analyzer_process, fixture_mantarray_mc_simulator]


def test_append_data__correctly_appends_x_and_y_data_from_numpy_array_to_list():
    init_list = [list(), list()]
    expected_list = [[0], [1]]
    new_list, downstream_new_list = append_data(init_list, expected_list)
    assert new_list[0] == expected_list[0]
    assert new_list[1] == expected_list[1]
    assert downstream_new_list[0] == expected_list[0]
    assert downstream_new_list[1] == expected_list[1]


def test_append_data__removes_oldest_data_points_when_buffer_exceeds_max_size():
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
    new_list, _ = append_data(init_list, new_data)
    assert new_list[0] == list(range(3, DATA_ANALYZER_BETA_1_BUFFER_SIZE + 3))
    assert new_list[1] == list(range(3, DATA_ANALYZER_BETA_1_BUFFER_SIZE + 3))


# TODO add test for 7 second data filter


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
    expected_metrics = pipeline.get_displacement_data_metrics()[0]

    actual = get_pipeline_analysis(test_data_arr.tolist())
    assert actual.keys() == expected_metrics.keys()
    for i, k in enumerate(expected_metrics.keys()):
        if i in (0, len(expected_metrics.keys()) - 1):
            # Tanner (7/12/21): These values are NaN which are not equal
            del actual[k][IRREGULARITY_INTERVAL_UUID]
            del expected_metrics[k][IRREGULARITY_INTERVAL_UUID]
        assert actual[k] == expected_metrics[k], f"Incorrect twitch dict at idx {k}"


# def test_DataAnalyzerProcess_init_stream__?
