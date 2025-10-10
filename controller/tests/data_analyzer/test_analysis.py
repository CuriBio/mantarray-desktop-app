# -*- coding: utf-8 -*-
import copy
import json
from random import randint

from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import DATA_ANALYZER_BETA_1_BUFFER_SIZE
from mantarray_desktop_app import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app.simulators.mc_simulator import MantarrayMcSimulator
from mantarray_desktop_app.sub_processes import data_analyzer
from mantarray_desktop_app.sub_processes.data_analyzer import check_for_new_twitches
from mantarray_desktop_app.sub_processes.data_analyzer import get_force_signal
from mantarray_desktop_app.sub_processes.data_analyzer import live_data_metrics
from mantarray_desktop_app.sub_processes.data_analyzer import METRIC_CALCULATORS
import numpy as np
from pulse3D.constants import AMPLITUDE_UUID
from pulse3D.constants import BUTTERWORTH_LOWPASS_30_UUID
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from pulse3D.constants import TWITCH_FREQUENCY_UUID
from pulse3D.exceptions import PeakDetectionError
from pulse3D.peak_detection import peak_detector
from pulse3D.transforms import create_filter
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures import TEST_BARCODE_CONFIG
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process_beta_2_mode
from ..fixtures_data_analyzer import set_sampling_period
from ..fixtures_data_analyzer import TEST_START_MANAGED_ACQUISITION_COMMUNICATION
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


@pytest.mark.parametrize(
    "test_magnet_type,expected_conversion_factor", list(TEST_BARCODE_CONFIG["S"].items())
)
def test_calculate_magnetic_flux_density_from_memsic__returns_correct_value(
    test_magnet_type, expected_conversion_factor
):
    test_mfd = np.array([list(range(15)), [randint(0, 100) for _ in range(15)]], dtype=np.float64)
    actual = data_analyzer.calculate_displacement_from_magnetic_flux_density(
        test_mfd.copy(),
        test_magnet_type,
        magnet_type_to_mt_per_mm={test_magnet_type: expected_conversion_factor},
    )

    test_mfd[1] *= expected_conversion_factor
    np.testing.assert_array_almost_equal(actual, test_mfd)


@pytest.mark.parametrize("is_beta_2_data", [True, False])
@pytest.mark.parametrize("compress", [True, False])
def test_get_force_signal__converts_to_force_correctly(is_beta_2_data, compress, mocker):
    # beta 2
    mocked_mfd_from_memsic = mocker.patch.object(
        data_analyzer, "calculate_magnetic_flux_density_from_memsic", autospec=True
    )
    mocked_displacement_from_mfd = mocker.patch.object(
        data_analyzer, "calculate_displacement_from_magnetic_flux_density", autospec=True
    )
    mocked_array = mocker.patch.object(data_analyzer.np, "array", autospec=True)
    # beta 1
    mocked_voltage_from_gmr = mocker.patch.object(data_analyzer, "calculate_voltage_from_gmr", autospec=True)
    mocked_displacement_from_voltage = mocker.patch.object(
        data_analyzer, "calculate_displacement_from_voltage", autospec=True
    )
    # both
    mocked_filt = mocker.patch.object(data_analyzer, "apply_noise_filtering", autospec=True)
    mocked_compress = mocker.patch.object(data_analyzer, "compress_filtered_magnetic_data", autospec=True)
    mocked_force_from_displacement = mocker.patch.object(
        data_analyzer, "calculate_force_from_displacement", autospec=True
    )
    mocked_get_experiment_id = mocker.patch.object(data_analyzer, "get_experiment_id", autospec=True)
    mocked_get_stiffness_factor = mocker.patch.object(data_analyzer, "get_stiffness_factor", autospec=True)

    # using dummy values here since all funcs are mocked
    test_raw_signal = "raw_signal"
    test_filter_coefficients = "filter_coefficients"
    test_barcode = MantarrayMcSimulator.default_plate_barcode
    test_well_idx = randint(0, 23)

    get_force_signal(
        test_raw_signal,
        test_filter_coefficients,
        test_barcode,
        test_well_idx,
        compress=compress,
        is_beta_2_data=is_beta_2_data,
        magnet_type_to_mt_per_mm=TEST_BARCODE_CONFIG["S"],
    )

    mocked_get_stiffness_factor.assert_called_once_with(
        mocked_get_experiment_id.return_value,
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(test_well_idx),
    )

    mocked_filt.assert_called_once_with(test_raw_signal, test_filter_coefficients)
    if compress:
        mocked_compress.assert_called_once_with(mocked_filt.return_value)
        filter_and_compress_res = mocked_compress.return_value
    else:
        mocked_compress.assert_not_called()
        filter_and_compress_res = mocked_filt.return_value
    if is_beta_2_data:
        mocked_mfd_from_memsic.assert_called_once_with(filter_and_compress_res[1])
        mocked_array.assert_called_once_with(
            [filter_and_compress_res[0], mocked_mfd_from_memsic.return_value], dtype=np.float64
        )
        mocked_displacement_from_mfd.assert_called_once_with(
            mocked_array.return_value, test_barcode[-1:], magnet_type_to_mt_per_mm=TEST_BARCODE_CONFIG["S"]
        )
        mocked_voltage_from_gmr.assert_not_called()
        mocked_displacement_from_voltage.assert_not_called()
        displacement_res = mocked_displacement_from_mfd.return_value
    else:
        mocked_mfd_from_memsic.assert_not_called()
        mocked_array.assert_not_called()
        mocked_displacement_from_mfd.assert_not_called()
        mocked_voltage_from_gmr.assert_called_once_with(filter_and_compress_res)
        mocked_displacement_from_voltage.assert_called_once_with(mocked_voltage_from_gmr.return_value)
        displacement_res = mocked_displacement_from_voltage.return_value
    mocked_get_experiment_id.assert_called_once_with(test_barcode)
    mocked_force_from_displacement.assert_called_once_with(
        displacement_res, mocked_get_stiffness_factor.return_value, in_mm=is_beta_2_data
    )


def test_live_data_metrics__returns_desired_metrics(mantarray_mc_simulator):
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

    peak_detection_results = peak_detector(test_data_arr)
    metrics_dict = live_data_metrics(peak_detection_results, test_data_arr)

    # first and last twitch will not be included in metric calculations
    assert len(metrics_dict.keys()) == MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 2
    for twitch_time_index, twitch_dict in metrics_dict.items():
        # just assert that keys are present
        assert sorted(twitch_dict.keys()) == sorted(
            [TWITCH_FREQUENCY_UUID, AMPLITUDE_UUID]
        ), twitch_time_index


def test_live_data_metrics__raises_error_if_no_twitch_indices(mocker):
    mocker.patch.object(data_analyzer, "find_twitch_indices", autospec=True, return_value=dict())

    with pytest.raises(PeakDetectionError):
        # currently does not need real values passed in to raise this error
        live_data_metrics(tuple(), np.empty((0, 0)))


def test_live_data_metrics__raises_error_if_all_metric_calculations_fail(mantarray_mc_simulator, mocker):
    for metric_calculator in METRIC_CALCULATORS.values():
        mocker.patch.object(metric_calculator, "fit", autospec=True, side_effect=Exception())

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

    peak_detection_results = peak_detector(test_data_arr)

    with pytest.raises(PeakDetectionError):
        live_data_metrics(peak_detection_results, test_data_arr)


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
    set_sampling_period(four_board_analyzer_process_beta_2_mode, expected_sampling_period_us)

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
    set_sampling_period(four_board_analyzer_process_beta_2_mode, expected_sampling_period_us)

    expected_buffer_size = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS * int(1e6 / expected_sampling_period_us)

    init_list = init_list = [list(range(expected_buffer_size)), list(range(expected_buffer_size))]
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

    da_process._barcode = MantarrayMcSimulator.default_plate_barcode

    actual = da_process.get_twitch_analysis(test_data_arr.tolist(), well_idx=randint(0, 23))
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

    test_barcode = MantarrayMcSimulator.default_plate_barcode
    test_well_idx = randint(0, 23)

    filter_coefficients = create_filter(
        BUTTERWORTH_LOWPASS_30_UUID, CONSTRUCT_SENSOR_SAMPLING_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND
    )
    force = get_force_signal(
        test_data_arr,
        filter_coefficients,
        test_barcode,
        test_well_idx,
        compress=False,
        is_beta_2_data=False,
        magnet_type_to_mt_per_mm=TEST_BARCODE_CONFIG["S"],
    )
    force[1] *= MICRO_TO_BASE_CONVERSION
    peak_detection_results = peak_detector(force)
    expected_metrics = live_data_metrics(peak_detection_results, force)

    da_process._barcode = MantarrayMcSimulator.default_plate_barcode

    actual = da_process.get_twitch_analysis(test_data_arr.tolist(), well_idx=randint(0, 23))
    assert actual.keys() == expected_metrics.keys()
    for k in expected_metrics.keys():
        assert actual[k] == expected_metrics[k], f"Incorrect twitch dict at idx {k}"


def test_get_twitch_analysis__returns_force_metrics_from_given_beta_2_data(
    four_board_analyzer_process_beta_2_mode, mantarray_mc_simulator
):
    # Tanner (7/12/21): This test is "True by definition", but can't think of a better way to test waveform analysis
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]

    # run setup before loop to set sampling period and init streams
    invoke_process_run_and_check_errors(da_process, perform_setup_before_loop=True)

    test_y_data = (
        mantarray_mc_simulator["simulator"].get_interpolated_data(DEFAULT_SAMPLING_PERIOD).tolist()
        * MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
    )
    test_x_data = np.arange(0, DEFAULT_SAMPLING_PERIOD * len(test_y_data), DEFAULT_SAMPLING_PERIOD)
    test_data_arr = np.array([test_x_data, test_y_data], dtype=np.int64)

    test_barcode = MantarrayMcSimulator.default_plate_barcode
    test_well_idx = randint(0, 23)

    filter_coefficients = create_filter(BUTTERWORTH_LOWPASS_30_UUID, DEFAULT_SAMPLING_PERIOD)
    force = get_force_signal(
        test_data_arr,
        filter_coefficients,
        test_barcode,
        test_well_idx,
        compress=False,
        magnet_type_to_mt_per_mm=TEST_BARCODE_CONFIG["S"],
    )
    force[1] *= MICRO_TO_BASE_CONVERSION

    peak_detection_results = peak_detector(force)
    expected_metrics = live_data_metrics(peak_detection_results, force)

    da_process._barcode = MantarrayMcSimulator.default_plate_barcode

    actual = da_process.get_twitch_analysis(test_data_arr.tolist(), well_idx=randint(0, 23))
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


def test_DataAnalyzerProcess__handles_problematic_data(
    four_board_analyzer_process_beta_2_mode, mantarray_mc_simulator, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    da_process.init_streams()

    # mock so waveform data doesn't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_data_into_queue", autospec=True)
    mocker.patch.object(da_process, "_create_outgoing_beta_2_data", autospec=True)
    mocker.patch.object(da_process, "_handle_performance_logging", autospec=True)

    expected_sampling_period_us = 11000
    set_sampling_period(four_board_analyzer_process_beta_2_mode, expected_sampling_period_us)

    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    board_queues = four_board_analyzer_process_beta_2_mode["board_queues"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        TEST_START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
    )

    test_twitch = mantarray_mc_simulator["simulator"].get_interpolated_data(expected_sampling_period_us)

    # twitch waveform to send for wells 0-10
    test_y_data = test_twitch.tolist() * 2 + np.zeros(len(test_twitch)).tolist() * (
        MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 2
    )
    test_x_data = np.arange(
        0, expected_sampling_period_us * len(test_y_data), expected_sampling_period_us, dtype=np.uint64
    )
    # flat line to send for wells 11-23
    dummy_y_data = np.zeros(len(test_y_data))

    # send less data than required for analysis first
    test_packet_1 = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_packet_1["time_indices"] = test_x_data
    for well_idx in range(24):
        # Tanner (7/14/21): time offsets are currently unused in data analyzer so not modifying them here
        first_channel = list(test_packet_1[well_idx].keys())[1]
        y_data = test_y_data if well_idx <= 10 else dummy_y_data
        test_packet_1[well_idx][first_channel] = np.array(y_data, dtype=np.uint16)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_packet_1, board_queues[0][0])
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_empty(board_queues[0][1])


def test_DataAnalyzerProcess__sends_beta_1_metrics_of_all_wells_to_main_when_ready(
    four_board_analyzer_process, mantarray_mc_simulator, mocker
):
    da_process, board_queues, from_main_queue, *_ = four_board_analyzer_process
    da_process.init_streams()

    # mock so waveform data doesn't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_data_into_queue", autospec=True)

    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        TEST_START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
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
    set_sampling_period(four_board_analyzer_process_beta_2_mode, expected_sampling_period_us)

    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    board_queues = four_board_analyzer_process_beta_2_mode["board_queues"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        TEST_START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
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
    da_process, board_queues, from_main_queue, *_ = four_board_analyzer_process
    da_process.init_streams()

    # mock so waveform data doesn't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_data_into_queue", autospec=True)

    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        TEST_START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
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
    set_sampling_period(four_board_analyzer_process_beta_2_mode, expected_sampling_period_us)

    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    board_queues = four_board_analyzer_process_beta_2_mode["board_queues"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        TEST_START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
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


def test_DataAnalyzerProcess__data_analysis_stream_is_reconfigured_in_beta_2_mode_upon_receiving_set_sampling_period_command(
    four_board_analyzer_process_beta_2_mode, mantarray_mc_simulator, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    da_process.init_streams()

    # mock so waveform data doesn't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_data_into_queue", autospec=True)
    mocker.patch.object(da_process, "_create_outgoing_beta_2_data", autospec=True)
    mocker.patch.object(da_process, "_handle_performance_logging", autospec=True)

    expected_sampling_period_us = 12000
    set_sampling_period(four_board_analyzer_process_beta_2_mode, expected_sampling_period_us)

    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    board_queues = four_board_analyzer_process_beta_2_mode["board_queues"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    # make sure data analyzer knows that managed acquisition is running
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        TEST_START_MANAGED_ACQUISITION_COMMUNICATION, from_main_queue
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

    set_sampling_period(four_board_analyzer_process_beta_2_mode, expected_sampling_period_us)

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
        actual_well_metric_dict = outgoing_metrics[str(well_idx)]
        assert list(actual_well_metric_dict.keys()) == [str(AMPLITUDE_UUID), str(TWITCH_FREQUENCY_UUID)]
        for metric_id, metric_list in actual_well_metric_dict.items():
            assert (
                len(metric_list) == MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS - 2
            ), f"Well: {well_idx}, Metric ID: {metric_id}"
