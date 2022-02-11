# -*- coding: utf-8 -*-
import copy
import datetime
import json
import math
import time

from freezegun import freeze_time
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import data_analyzer
from mantarray_desktop_app import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS
from mantarray_desktop_app import RAW_TO_SIGNED_CONVERSION_VALUE
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app.data_analyzer import get_force_signal
import numpy as np
from pulse3D.constants import BUTTERWORTH_LOWPASS_30_UUID
from pulse3D.constants import CENTIMILLISECONDS_PER_SECOND
from pulse3D.transforms import create_filter
import pytest
from scipy import signal
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty

from ..fixtures import get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process
from ..fixtures_data_analyzer import fixture_runnable_four_board_analyzer_process
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size


__fixtures__ = [fixture_four_board_analyzer_process, fixture_runnable_four_board_analyzer_process]


def fill_da_input_data_queue(input_queue, num_seconds):
    for seconds in range(num_seconds):
        for well in range(24):
            time_indices = np.arange(
                seconds * CENTIMILLISECONDS_PER_SECOND,
                (seconds + 1) * CENTIMILLISECONDS_PER_SECOND,
                CONSTRUCT_SENSOR_SAMPLING_PERIOD,
            )
            tissue_data = 1000 * signal.sawtooth(time_indices / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5)
            tissue_packet = {
                "well_index": well,
                "is_reference_sensor": False,
                "data": np.array([time_indices, tissue_data], dtype=np.int32),
            }
            input_queue.put_nowait(tissue_packet)
        for ref in range(6):
            time_indices = np.arange(
                seconds * CENTIMILLISECONDS_PER_SECOND,
                (seconds + 1) * CENTIMILLISECONDS_PER_SECOND,
                REFERENCE_SENSOR_SAMPLING_PERIOD,
            )
            ref_data = 1000 * signal.sawtooth(time_indices / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5)
            ref_packet = {
                "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[ref],
                "is_reference_sensor": True,
                "data": np.array([time_indices, ref_data], dtype=np.int32),
            }
            input_queue.put_nowait(ref_packet)


@pytest.mark.slow
def test_DataAnalyzerProcess_beta_1_performance__fill_data_analysis_buffer(
    runnable_four_board_analyzer_process,
):
    # 11 seconds of data (625 Hz) coming in from File Writer to going through to Main
    #
    # mantarray-waveform-analysis v0.3:     4.148136512
    # mantarray-waveform-analysis v0.3.1:   3.829136133
    # mantarray-waveform-analysis v0.4.0:   3.323093677
    # remove concatenate:                   2.966678695
    # 30 Hz Bessel filter:                  2.930061808  # Tanner (9/3/20): not intended to speed anything up, just adding this to show it had it didn't have much affect on performance
    # 30 Hz Butterworth filter:             2.935009033  # Tanner (9/10/20): not intended to speed anything up, just adding this to show it had it didn't have much affect on performance
    #
    # added twitch metric analysis:         3.013469479
    # initial pulse3D import:               3.855403546

    p, board_queues, comm_from_main_queue, comm_to_main_queue, _ = runnable_four_board_analyzer_process
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)

    num_seconds = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS + 1
    fill_da_input_data_queue(board_queues[0][0], num_seconds)
    start = time.perf_counter_ns()
    invoke_process_run_and_check_errors(p, num_iterations=num_seconds * (24 + 6))
    dur_seconds = (time.perf_counter_ns() - start) / 10 ** 9

    # prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])
    drain_queue(comm_to_main_queue)

    # print(f"Duration (seconds): {dur_seconds}")  # Eli (4/8/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization
    assert dur_seconds < 10


@pytest.mark.slow
def test_DataAnalyzerProcess_beta_1_performance__first_second_of_data_with_analysis(
    runnable_four_board_analyzer_process,
):
    # Fill data analysis buffer with 10 seconds of data to start metric analysis,
    # Then record duration of sending 1 additional second of data
    #
    # start:                                 0.547285524
    # initial pulse3D import:                0.535316489

    p, board_queues, comm_from_main_queue, comm_to_main_queue, _ = runnable_four_board_analyzer_process
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)

    # load data
    num_seconds = MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS + 1
    fill_da_input_data_queue(board_queues[0][0], num_seconds)
    invoke_process_run_and_check_errors(p, num_iterations=MIN_NUM_SECONDS_NEEDED_FOR_ANALYSIS * (24 + 6))

    # send additional data and time analysis
    start = time.perf_counter_ns()
    invoke_process_run_and_check_errors(p, num_iterations=(24 + 6))
    dur_seconds = (time.perf_counter_ns() - start) / 10 ** 9

    # prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])
    drain_queue(comm_to_main_queue)

    # print(f"Duration (seconds): {dur_seconds}")  # Eli (4/8/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization
    assert dur_seconds < 2


@pytest.mark.slow
def test_DataAnalyzerProcess_beta_1_performance__single_data_packet_per_well_without_analysis(
    runnable_four_board_analyzer_process,
):
    # 1 second of data (625 Hz) coming in from File Writer to going through to Main
    #
    # start:                                 0.530731389
    # added twitch metric analysis:          0.578328276
    # initial pulse3D import:                0.533860423

    p, board_queues, comm_from_main_queue, comm_to_main_queue, _ = runnable_four_board_analyzer_process
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)

    num_seconds = 1
    fill_da_input_data_queue(board_queues[0][0], num_seconds)
    start = time.perf_counter_ns()
    invoke_process_run_and_check_errors(p, num_iterations=num_seconds * (24 + 6))
    dur_seconds = (time.perf_counter_ns() - start) / 10 ** 9

    # prevent BrokenPipeErrors
    drain_queue(board_queues[0][1])
    drain_queue(comm_to_main_queue)

    # print(f"Duration (seconds): {dur_seconds}")  # Eli (4/8/21): this is commented code that is deliberately kept in the codebase since it is often toggled on/off during optimization
    assert dur_seconds < 2


def test_DataAnalyzerProcess_commands_for_each_run_iteration__checks_for_calibration_update_from_main(
    four_board_analyzer_process,
):
    calibration_comm = {
        "communication_type": "calibration",
        "calibration_settings": 1,
    }

    p, _, comm_from_main_queue, _, _ = four_board_analyzer_process
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        calibration_comm,
        comm_from_main_queue,
        timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )
    invoke_process_run_and_check_errors(p)

    actual = p.get_calibration_settings()
    assert actual == calibration_comm["calibration_settings"]


@pytest.mark.parametrize(
    "test_well_index,test_construct_data,test_description",
    [
        (
            0,
            np.array([[0, 1000, 2000], [0, 48, 96]], dtype=np.int32),
            "correctly loads well 0 data",
        ),
        (
            9,
            np.array([[250, 1250, 2250], [13, 61, 109]], dtype=np.int32),
            "correctly loads well 9 data",
        ),
        (
            18,
            np.array([[750, 1750, 2750], [41, 89, 137]], dtype=np.int32),
            "correctly loads well 18 data",
        ),
    ],
)
def test_DataAnalyzerProcess__correctly_loads_construct_sensor_data_to_buffer_when_empty(
    test_well_index, test_construct_data, test_description, four_board_analyzer_process
):
    p, board_queues, comm_from_main_queue, _, _ = four_board_analyzer_process
    p.init_streams()
    incoming_data = board_queues[0][0]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(p)

    test_construct_dict = {
        "is_reference_sensor": False,
        "well_index": test_well_index,
        "data": test_construct_data,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_construct_dict, incoming_data)

    invoke_process_run_and_check_errors(p)

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    np.testing.assert_equal(data_buffer[test_well_index]["construct_data"], test_construct_data)


@pytest.mark.parametrize(
    "test_well_index,test_construct_data,test_description",
    [
        (
            0,
            [[0, 1000, 2000], [0, 48, 96]],
            "correctly loads well 0 data",
        ),
        (
            9,
            [[250, 1250, 2250], [13, 61, 109]],
            "correctly loads well 9 data",
        ),
        (
            18,
            [[750, 1750, 2750], [41, 89, 137]],
            "correctly loads well 18 data",
        ),
    ],
)
def test_DataAnalyzerProcess__correctly_loads_construct_sensor_data_to_buffer_when_not_empty(
    test_well_index, test_construct_data, test_description, four_board_analyzer_process
):
    p, board_queues, comm_from_main_queue, _, _ = four_board_analyzer_process
    p.init_streams()
    incoming_data = board_queues[0][0]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(p)

    test_construct_dict = {
        "is_reference_sensor": False,
        "well_index": test_well_index,
        "data": test_construct_data,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_construct_dict, incoming_data)
    data_buffer = p._data_buffer  # pylint:disable=protected-access

    expected_construct_data = [[0, 0], [0, 0]]
    data_buffer[test_well_index]["construct_data"] = copy.deepcopy(expected_construct_data)

    invoke_process_run_and_check_errors(p)

    expected_construct_data[0].extend(test_construct_data[0])
    expected_construct_data[1].extend(test_construct_data[1])
    np.testing.assert_equal(data_buffer[test_well_index]["construct_data"], expected_construct_data)


def test_DataAnalyzerProcess__correctly_pairs_ascending_order_ref_sensor_data_in_buffer(
    four_board_analyzer_process,
):
    p, board_queues, comm_from_main_queue, _, _ = four_board_analyzer_process
    incoming_data = board_queues[0][0]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(p)

    test_ref_data = np.array(
        [
            [125, 375, 625, 875, 1125, 1375, 1625, 1875, 2125, 2375, 2625, 2875],
            [6, 18, 30, 42, 54, 66, 78, 90, 102, 114, 126, 138],
        ],
        dtype=np.int32,
    )
    test_ref_dict = {
        "is_reference_sensor": True,
        "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[0],
        "data": test_ref_data,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_ref_dict, incoming_data)

    invoke_process_run_and_check_errors(p)

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    expected_ref_data_0 = np.array([[1250, 11250, 21250], [6, 54, 102]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[0]["ref_data"], expected_ref_data_0)
    expected_ref_data_1 = np.array([[3750, 13750, 23750], [18, 66, 114]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[1]["ref_data"], expected_ref_data_1)
    expected_ref_data_4 = np.array([[6250, 16250, 26250], [30, 78, 126]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[4]["ref_data"], expected_ref_data_4)
    expected_ref_data_5 = np.array([[8750, 18750, 28750], [42, 90, 138]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[5]["ref_data"], expected_ref_data_5)


def test_DataAnalyzerProcess__correctly_pairs_descending_order_ref_sensor_data_in_buffer(
    four_board_analyzer_process,
):
    p, board_queues, comm_from_main_queue, _, _ = four_board_analyzer_process
    incoming_data = board_queues[0][0]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(p)

    test_ref_data = np.array(
        [
            [125, 375, 625, 875, 1125, 1375, 1625, 1875, 2125, 2375, 2625, 2875],
            [11, 23, 35, 47, 59, 71, 83, 95, 107, 119, 131, 143],
        ],
        dtype=np.int32,
    )
    test_ref_dict = {
        "is_reference_sensor": True,
        "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[5],
        "data": test_ref_data,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_ref_dict, incoming_data)

    invoke_process_run_and_check_errors(p)

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    expected_ref_data_23 = np.array([[1250, 11250, 21250], [11, 59, 107]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[23]["ref_data"], expected_ref_data_23)
    expected_ref_data_22 = np.array([[3750, 13750, 23750], [23, 71, 119]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[22]["ref_data"], expected_ref_data_22)
    expected_ref_data_19 = np.array([[6250, 16250, 26250], [35, 83, 131]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[19]["ref_data"], expected_ref_data_19)
    expected_ref_data_18 = np.array([[8750, 18750, 28750], [47, 95, 143]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[18]["ref_data"], expected_ref_data_18)


@pytest.mark.parametrize(
    "test_sample_indices,expected_status,test_description",
    [
        (None, False, "correctly sets falg when empty"),
        (np.array([0], dtype=np.int32), False, "correctly sets flag when containing one item"),
        (
            np.array(
                [0, DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS - 1],
                dtype=np.int32,
            ),
            False,
            "correctly sets flag when not full",
        ),
        (
            np.array(
                [0, DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS],
                dtype=np.int32,
            ),
            True,
            "correctly sets flag when full",
        ),
    ],
)
def test_DataAnalyzerProcess__is_buffer_full_returns_correct_value(
    test_sample_indices, expected_status, test_description, four_board_analyzer_process
):
    p, _, _, _, _ = four_board_analyzer_process

    test_data = None
    if test_sample_indices is not None:
        test_data = np.zeros((2, test_sample_indices.shape[0]))
        test_data[0] = test_sample_indices

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    for well_idx in range(24):
        data_buffer[well_idx]["construct_data"] = test_data
        data_buffer[well_idx]["ref_data"] = test_data
    actual = p.is_buffer_full()
    assert actual is expected_status


def test_DataAnalyzerProcess__dumps_all_data_when_buffer_is_full_and_clears_buffer(
    four_board_analyzer_process, mocker
):
    expected_x_vals = [0, DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS]
    expected_y_vals = [[0, i] for i in range(24)]

    # Tanner (6/16/20): The tiny amount of data used in this test doesn't work with mantarray_waveform_analysis functions, so we can mock them to prevent errors
    mocked_force_vals = [np.array([expected_x_vals, expected_y_vals[i]]) for i in range(24)]
    mocked_get_force = mocker.patch.object(
        data_analyzer,
        "get_force_signal",
        autospec=True,
        side_effect=mocked_force_vals,
    )

    p, board_queues, _, _, _ = four_board_analyzer_process
    outgoing_data = board_queues[0][1]

    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)
    data_buffer = p._data_buffer  # pylint:disable=protected-access
    for well_index in range(24):
        data_buffer[well_index]["construct_data"] = np.array(
            [expected_x_vals, expected_y_vals[well_index]],
            dtype=np.int32,
        )
        data_buffer[well_index]["ref_data"] = np.array(
            [expected_x_vals, [0, 0]],
            dtype=np.int32,
        )

    invoke_process_run_and_check_errors(p)

    actual_msg = outgoing_data.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    confirm_queue_is_eventually_empty(outgoing_data)

    assert actual_msg["data_type"] == "waveform_data"
    actual = json.loads(actual_msg["data_json"])
    waveform_data_points = actual["waveform_data"]["basic_data"]["waveform_data_points"]
    expected_construct_data_0 = {
        "x_data_points": expected_x_vals,
        "y_data_points": np.array(expected_y_vals[0]) * MICRO_TO_BASE_CONVERSION,
    }
    expected_construct_data_23 = {
        "x_data_points": expected_x_vals,
        "y_data_points": np.array(expected_y_vals[23]) * MICRO_TO_BASE_CONVERSION,
    }
    np.testing.assert_equal(waveform_data_points["0"], expected_construct_data_0)
    np.testing.assert_equal(waveform_data_points["23"], expected_construct_data_23)

    assert actual["earliest_timepoint"] == 0
    assert actual["latest_timepoint"] == DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS

    assert data_buffer[0]["construct_data"] is None
    assert data_buffer[0]["ref_data"] is None
    assert data_buffer[23]["construct_data"] is None
    assert data_buffer[23]["ref_data"] is None

    assert mocked_get_force.call_count == 24


@freeze_time("2020-06-1 13:45:30.123456")
def test_DataAnalyzerProcess__dump_data_into_queue__sends_message_to_main_indicating_data_is_available__with_info_about_data(
    four_board_analyzer_process,
):
    p, _, _, comm_to_main_queue, _ = four_board_analyzer_process

    dummy_well_data = [
        [CONSTRUCT_SENSOR_SAMPLING_PERIOD * i for i in range(3)],
        [0, 0, 0],
    ]
    dummy_data_dict = {
        "well0": dummy_well_data,
        "earliest_timepoint": dummy_well_data[0][0],
        "latest_timepoint": dummy_well_data[0][-1],
    }
    p._dump_data_into_queue(dummy_data_dict)  # pylint:disable=protected-access
    confirm_queue_is_eventually_of_size(comm_to_main_queue, 1)

    expected_time = datetime.datetime(2020, 6, 1, 13, 45, 30, 123456).strftime("%Y-%m-%d %H:%M:%S.%f")
    expected_message = {
        "communication_type": "data_available",
        "timestamp": expected_time,
        "num_data_points": len(dummy_data_dict["well0"]),
        "earliest_timepoint": dummy_data_dict["earliest_timepoint"],
        "latest_timepoint": dummy_data_dict["latest_timepoint"],
    }
    actual = comm_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_message


def test_DataAnalyzerProcess__create_outgoing_data__normalizes_and_flips_raw_data_then_compresses_force_data(
    four_board_analyzer_process,
):
    p, _, _, _, _ = four_board_analyzer_process
    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)

    timepoint_end = math.ceil(DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS / ROUND_ROBIN_PERIOD)
    timepoints = np.array(
        [(ROUND_ROBIN_PERIOD * (i + 1) // TIMESTEP_CONVERSION_FACTOR) for i in range(timepoint_end)]
    )
    sawtooth_data = signal.sawtooth(timepoints / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5) * -1
    test_data = np.array(
        (
            timepoints * MICROSECONDS_PER_CENTIMILLISECOND,
            (FIFO_READ_PRODUCER_DATA_OFFSET + FIFO_READ_PRODUCER_WELL_AMPLITUDE * sawtooth_data)
            - RAW_TO_SIGNED_CONVERSION_VALUE,
        ),
        dtype=np.int32,
    )

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    for well_idx in range(24):
        data_buffer[well_idx]["construct_data"] = copy.deepcopy(test_data)
        data_buffer[well_idx]["ref_data"] = np.zeros(test_data.shape)

    outgoing_data = p._create_outgoing_beta_1_data()  # pylint:disable=protected-access
    actual = outgoing_data["waveform_data"]["basic_data"]["waveform_data_points"]

    normalized_data = np.array(
        [test_data[0], (test_data[1] - max(test_data[1])) * -1],
        dtype=np.int32,
    )
    filter_coefficients = create_filter(
        BUTTERWORTH_LOWPASS_30_UUID,
        ROUND_ROBIN_PERIOD * MICROSECONDS_PER_CENTIMILLISECOND,
    )
    expected_compressed_data = get_force_signal(normalized_data, filter_coefficients, is_beta_2_data=False)
    np.testing.assert_equal(actual[0]["x_data_points"], expected_compressed_data[0, :])
    np.testing.assert_equal(
        actual[0]["y_data_points"], expected_compressed_data[1, :] * MICRO_TO_BASE_CONVERSION
    )
    np.testing.assert_equal(actual[23]["x_data_points"], expected_compressed_data[0, :])
    np.testing.assert_equal(
        actual[23]["y_data_points"],
        expected_compressed_data[1, :] * MICRO_TO_BASE_CONVERSION,
    )


def test_DataAnalyzerProcess__does_not_load_data_to_buffer_if_managed_acquisition_not_running(
    four_board_analyzer_process,
):
    p, board_queues, _, _, _ = four_board_analyzer_process
    incoming_data = board_queues[0][0]

    p._end_of_data_stream_reached[0] = True  # pylint:disable=protected-access

    test_well_index = 0
    test_construct_dict = {
        "is_reference_sensor": False,
        "well_index": test_well_index,
        "data": np.array([[0, 250], [1, 3]]),
    }
    incoming_data.put_nowait(test_construct_dict)
    test_ref_dict = {
        "is_reference_sensor": True,
        "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[0],
        "data": np.array([[125, 375], [2, 4]]),
    }
    incoming_data.put_nowait(test_ref_dict)
    confirm_queue_is_eventually_of_size(incoming_data, 2)

    invoke_process_run_and_check_errors(p, num_iterations=2)

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    assert data_buffer[test_well_index]["construct_data"] is None
    assert data_buffer[test_well_index]["ref_data"] is None


def test_DataAnalyzerProcess__processes_stop_managed_acquisition_command(
    four_board_analyzer_process,
):
    p, _, comm_from_main_queue, _, _ = four_board_analyzer_process

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(p)

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    for well_idx in range(24):
        data_buffer[well_idx]["construct_data"] = [[0, 0, 0], [1, 2, 3]]
        data_buffer[well_idx]["ref_data"] = [[0, 0, 0], [4, 5, 6]]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        STOP_MANAGED_ACQUISITION_COMMUNICATION,
        comm_from_main_queue,
    )

    invoke_process_run_and_check_errors(p)
    assert p._end_of_data_stream_reached[0] is True  # pylint:disable=protected-access
    assert data_buffer[0]["construct_data"] is None
    assert data_buffer[0]["ref_data"] is None
    assert data_buffer[23]["construct_data"] is None
    assert data_buffer[23]["ref_data"] is None
