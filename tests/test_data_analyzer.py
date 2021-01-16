# -*- coding: utf-8 -*-
import copy
import datetime
import json
import logging
import math
from multiprocessing import Queue
from statistics import stdev
import time

from freezegun import freeze_time
from mantarray_desktop_app import ADC_GAIN
from mantarray_desktop_app import CONSTRUCT_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import convert_24_bit_codes_to_voltage
from mantarray_desktop_app import DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS
from mantarray_desktop_app import DataAnalyzerProcess
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import MIDSCALE_CODE
from mantarray_desktop_app import MILLIVOLTS_PER_VOLT
from mantarray_desktop_app import RAW_TO_SIGNED_CONVERSION_VALUE
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import REFERENCE_SENSOR_SAMPLING_PERIOD
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app import UnrecognizedCommandToInstrumentError
from mantarray_desktop_app import UnrecognizedCommTypeFromMainToDataAnalyzerError
from mantarray_waveform_analysis import BUTTERWORTH_LOWPASS_30_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
from mantarray_waveform_analysis import Pipeline
from mantarray_waveform_analysis import pipelines
from mantarray_waveform_analysis import PipelineTemplate
import numpy as np
import pytest
from scipy import signal
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty

from .fixtures import get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION
from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .fixtures_data_analyzer import fixture_four_board_analyzer_process
from .helpers import confirm_queue_is_eventually_empty
from .helpers import confirm_queue_is_eventually_of_size


__fixtures__ = [
    fixture_four_board_analyzer_process,
]


def fill_da_input_data_queue(
    input_queue,
    num_seconds,
):
    # TODO Tanner (1/4/21): Consider using this function to remove protected-access of _data_buffer
    for seconds in range(num_seconds):
        for well in range(24):
            time_indices = np.arange(
                seconds * CENTIMILLISECONDS_PER_SECOND,
                (seconds + 1) * CENTIMILLISECONDS_PER_SECOND,
                CONSTRUCT_SENSOR_SAMPLING_PERIOD,
            )
            tissue_data = 1000 * signal.sawtooth(
                time_indices / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5
            )
            tissue_packet = {
                "well_index": well,
                "is_reference_sensor": False,
                "data": np.array([time_indices, tissue_data], dtype=np.int32),
            }
            input_queue.put(tissue_packet)
        for ref in range(6):
            time_indices = np.arange(
                seconds * CENTIMILLISECONDS_PER_SECOND,
                (seconds + 1) * CENTIMILLISECONDS_PER_SECOND,
                REFERENCE_SENSOR_SAMPLING_PERIOD,
            )
            ref_data = 1000 * signal.sawtooth(
                time_indices / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5
            )
            ref_packet = {
                "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[ref],
                "is_reference_sensor": True,
                "data": np.array([time_indices, ref_data], dtype=np.int32),
            }
            input_queue.put(ref_packet)
    confirm_queue_is_eventually_of_size(input_queue, num_seconds * (24 + 6))


def test_convert_24_bit_code_to_voltage_returns_correct_values_with_numpy_array():
    test_data = np.array(
        [-0x800000, MIDSCALE_CODE - RAW_TO_SIGNED_CONVERSION_VALUE, 0x7FFFFF]
    )
    actual_converted_data = convert_24_bit_codes_to_voltage(test_data)

    expected_data = [
        -(REFERENCE_VOLTAGE / ADC_GAIN) * MILLIVOLTS_PER_VOLT,
        0,
        (REFERENCE_VOLTAGE / ADC_GAIN) * MILLIVOLTS_PER_VOLT,
    ]
    np.testing.assert_almost_equal(actual_converted_data, expected_data, decimal=4)


@pytest.mark.slow
def test_DataAnalyzerProcess_performance(four_board_analyzer_process):
    # Data coming in from File Writer to going back to main (625 Hz)
    #
    # mantarray-waveform-analysis v0.3:     4148136512
    # mantarray-waveform-analysis v0.3.1:   3829136133
    # mantarray-waveform-analysis v0.4.0:   3323093677
    # remove concatenate:                   2966678695
    # 30 Hz Bessel filter:                  2930061808  # Tanner (9/3/20): not intended to speed anything up, just adding this to show it had it didn't have much affect on performance
    # 30 Hz Butterworth filter:             2935009033  # Tanner (9/10/20): not intended to speed anything up, just adding this to show it had it didn't have much affect on performance

    p, board_queues, comm_from_main_queue, _, _ = four_board_analyzer_process
    input_queue = board_queues[0][0]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION(),
        comm_from_main_queue,
    )
    invoke_process_run_and_check_errors(p)

    num_seconds = 8
    fill_da_input_data_queue(input_queue, num_seconds)
    start = time.perf_counter_ns()
    invoke_process_run_and_check_errors(p, num_iterations=num_seconds * (24 + 6))
    dur = time.perf_counter_ns() - start

    board_queues[0][1].get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # Tanner (8/31/20): prevent BrokenPipeError

    # print(f"Duration (ns): {dur}")
    assert dur < 7000000000


def test_DataAnalyzerProcess_super_is_called_during_init(mocker):
    error_queue = Queue()
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")
    DataAnalyzerProcess((), None, None, error_queue)
    mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


def test_DataAnalyzerProcess_commands_for_each_run_iteration__checks_for_calibration_update_from_main(
    four_board_analyzer_process,
):
    calibration_comm = {
        "communication_type": "calibration",
        "calibration_settings": 1,  # TODO Tanner (2/26/20): add real settings once fleshed out
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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_construct_dict, incoming_data
    )

    invoke_process_run_and_check_errors(p)

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    np.testing.assert_equal(
        data_buffer[test_well_index]["construct_data"], test_construct_data
    )


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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_construct_dict, incoming_data
    )
    data_buffer = p._data_buffer  # pylint:disable=protected-access

    expected_construct_data = [[0, 0], [0, 0]]
    data_buffer[test_well_index]["construct_data"] = copy.deepcopy(
        expected_construct_data
    )

    invoke_process_run_and_check_errors(p)

    expected_construct_data[0].extend(test_construct_data[0])
    expected_construct_data[1].extend(test_construct_data[1])
    np.testing.assert_equal(
        data_buffer[test_well_index]["construct_data"], expected_construct_data
    )


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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_ref_dict, incoming_data
    )

    invoke_process_run_and_check_errors(p)

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    expected_ref_data_0 = np.array([[125, 1125, 2125], [6, 54, 102]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[0]["ref_data"], expected_ref_data_0)
    expected_ref_data_1 = np.array([[375, 1375, 2375], [18, 66, 114]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[1]["ref_data"], expected_ref_data_1)
    expected_ref_data_4 = np.array([[625, 1625, 2625], [30, 78, 126]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[4]["ref_data"], expected_ref_data_4)
    expected_ref_data_5 = np.array([[875, 1875, 2875], [42, 90, 138]], dtype=np.int32)
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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_ref_dict, incoming_data
    )

    invoke_process_run_and_check_errors(p)

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    expected_ref_data_23 = np.array([[125, 1125, 2125], [11, 59, 107]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[23]["ref_data"], expected_ref_data_23)
    expected_ref_data_22 = np.array([[375, 1375, 2375], [23, 71, 119]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[22]["ref_data"], expected_ref_data_22)
    expected_ref_data_19 = np.array([[625, 1625, 2625], [35, 83, 131]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[19]["ref_data"], expected_ref_data_19)
    expected_ref_data_18 = np.array([[875, 1875, 2875], [47, 95, 143]], dtype=np.int32)
    np.testing.assert_equal(data_buffer[18]["ref_data"], expected_ref_data_18)


@pytest.mark.parametrize(
    "test_sample_indices,expected_status,test_description",
    [
        (None, False, "correctly sets falg when empty"),
        (
            np.array([0], dtype=np.int32),
            False,
            "correctly sets flag when containing one item",
        ),
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
    actual = p._is_buffer_full()  # pylint:disable=protected-access
    assert actual is expected_status


def test_DataAnalyzerProcess__dumps_all_data_when_buffer_is_full_and_clears_buffer(
    four_board_analyzer_process, mocker
):
    expected_x_vals = [0, DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS]
    expected_y_vals = [[0, i] for i in range(24)]

    # Tanner (6/16/20): The tiny amount of data used in this test doesn't work with mantarray_waveform_analysis functions, so we can mock them to prevent errors
    mocked_displacement_vals = [
        np.array([expected_x_vals, expected_y_vals[i]]) for i in range(24)
    ]
    mocked_compressed_displacement = mocker.patch.object(
        Pipeline,
        "get_compressed_displacement",
        autospec=True,
        side_effect=mocked_displacement_vals,
    )

    p, board_queues, _, _, _ = four_board_analyzer_process
    outgoing_data = board_queues[0][1]

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

    actual_json = outgoing_data.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    confirm_queue_is_eventually_empty(outgoing_data)

    actual = json.loads(actual_json)
    waveform_data_points = actual["waveform_data"]["basic_data"]["waveform_data_points"]
    expected_construct_data_0 = {
        "x_data_points": expected_x_vals,
        "y_data_points": np.array(expected_y_vals[0]) * MILLIVOLTS_PER_VOLT,
    }
    expected_construct_data_23 = {
        "x_data_points": expected_x_vals,
        "y_data_points": np.array(expected_y_vals[23]) * MILLIVOLTS_PER_VOLT,
    }
    np.testing.assert_equal(waveform_data_points["0"], expected_construct_data_0)
    np.testing.assert_equal(waveform_data_points["23"], expected_construct_data_23)

    assert actual["earliest_timepoint"] == 0
    assert actual["latest_timepoint"] == DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS

    assert data_buffer[0]["construct_data"] is None
    assert data_buffer[0]["ref_data"] is None
    assert data_buffer[23]["construct_data"] is None
    assert data_buffer[23]["ref_data"] is None

    assert mocked_compressed_displacement.call_count == 24


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

    expected_time = datetime.datetime(2020, 6, 1, 13, 45, 30, 123456).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    expected_message = {
        "communication_type": "data_available",
        "timestamp": expected_time,
        "num_data_points": len(dummy_data_dict["well0"]),
        "earliest_timepoint": dummy_data_dict["earliest_timepoint"],
        "latest_timepoint": dummy_data_dict["latest_timepoint"],
    }
    actual = comm_to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_message


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
    ) = four_board_analyzer_process
    for i, board in enumerate(board_queues):
        for j, queue in enumerate(board):
            queue_item = expected[i][j]
            put_object_into_queue_and_raise_error_if_eventually_still_empty(
                queue_item, queue
            )

    from_main_queue.put(expected_from_main)
    to_main_queue.put(expected_to_main)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_error, error_queue
    )
    confirm_queue_is_eventually_of_size(from_main_queue, 1)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    actual = (
        data_analyzer_process._drain_all_queues()  # pylint:disable=protected-access
    )

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


def test_DataAnalyzerProcess__create_outgoing_data__compresses_displacement_data(
    four_board_analyzer_process,
):
    p, _, _, _, _ = four_board_analyzer_process

    timepoint_end = math.ceil(
        DATA_ANALYZER_BUFFER_SIZE_CENTIMILLISECONDS / ROUND_ROBIN_PERIOD
    )
    timepoints = np.array(
        [
            (ROUND_ROBIN_PERIOD * (i + 1) // TIMESTEP_CONVERSION_FACTOR)
            for i in range(timepoint_end)
        ]
    )
    sawtooth_data = signal.sawtooth(
        timepoints / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5
    )
    test_data = np.array(
        (
            timepoints,
            (
                FIFO_READ_PRODUCER_DATA_OFFSET
                + FIFO_READ_PRODUCER_WELL_AMPLITUDE * sawtooth_data
            )
            - RAW_TO_SIGNED_CONVERSION_VALUE,
        ),
        dtype=np.int32,
    )

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    for well_idx in range(24):
        data_buffer[well_idx]["construct_data"] = copy.deepcopy(test_data)
        data_buffer[well_idx]["ref_data"] = np.zeros(test_data.shape)

    outgoing_data = p._create_outgoing_data()  # pylint:disable=protected-access
    actual = outgoing_data["waveform_data"]["basic_data"]["waveform_data_points"]

    pt = PipelineTemplate(
        noise_filter_uuid=BUTTERWORTH_LOWPASS_30_UUID,
        tissue_sampling_period=ROUND_ROBIN_PERIOD,
    )
    pipeline = pt.create_pipeline()
    pipeline.load_raw_gmr_data(test_data, np.zeros(test_data.shape))
    expected_compressed_data = pipeline.get_compressed_displacement()
    np.testing.assert_equal(actual[0]["x_data_points"], expected_compressed_data[0, :])
    np.testing.assert_equal(
        actual[0]["y_data_points"], expected_compressed_data[1, :] * MILLIVOLTS_PER_VOLT
    )
    np.testing.assert_equal(actual[23]["x_data_points"], expected_compressed_data[0, :])
    np.testing.assert_equal(
        actual[23]["y_data_points"],
        expected_compressed_data[1, :] * MILLIVOLTS_PER_VOLT,
    )


def test_DataAnalyzerProcess__raises_error_with_unrecognized_command_to_instrument(
    four_board_analyzer_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    p, _, comm_from_main_queue, _, _ = four_board_analyzer_process

    expected_command = "fake_command"
    start_command = {
        "communication_type": "to_instrument",
        "command": expected_command,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_command, comm_from_main_queue
    )

    with pytest.raises(UnrecognizedCommandToInstrumentError, match=expected_command):
        invoke_process_run_and_check_errors(p)


def test_DataAnalyzerProcess__processes_start_managed_acquisition_command__by_draining_outgoing_data_queue(
    four_board_analyzer_process,
):
    p, board_queues, comm_from_main_queue, _, _ = four_board_analyzer_process

    start_command = get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        start_command, comm_from_main_queue
    )

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        "item", board_queues[0][1]
    )
    invoke_process_run_and_check_errors(p)
    confirm_queue_is_eventually_empty(board_queues[0][1])


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
    assert p._is_managed_acquisition_running is False  # pylint:disable=protected-access
    assert data_buffer[0]["construct_data"] is None
    assert data_buffer[0]["ref_data"] is None
    assert data_buffer[23]["construct_data"] is None
    assert data_buffer[23]["ref_data"] is None


def test_DataAnalyzerProcess__raises_error_if_communication_type_is_invalid(
    four_board_analyzer_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    p, _, comm_from_main_queue, _, _ = four_board_analyzer_process

    invalid_command = {
        "communication_type": "fake_type",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        invalid_command,
        comm_from_main_queue,
    )

    with pytest.raises(
        UnrecognizedCommTypeFromMainToDataAnalyzerError, match="fake_type"
    ):
        invoke_process_run_and_check_errors(p)


def test_DataAnalyzerProcess__does_not_load_data_to_buffer_if_managed_acquisition_not_running(
    four_board_analyzer_process,
):
    p, board_queues, _, _, _ = four_board_analyzer_process
    incoming_data = board_queues[0][0]

    test_well_index = 0
    test_construct_dict = {
        "is_reference_sensor": False,
        "well_index": test_well_index,
        "data": np.array([[0, 250], [1, 3]]),
    }
    incoming_data.put(test_construct_dict)
    test_ref_dict = {
        "is_reference_sensor": True,
        "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[0],
        "data": np.array([[125, 375], [2, 4]]),
    }
    incoming_data.put(test_ref_dict)
    confirm_queue_is_eventually_of_size(incoming_data, 2)

    invoke_process_run_and_check_errors(p, num_iterations=2)

    data_buffer = p._data_buffer  # pylint:disable=protected-access
    assert data_buffer[test_well_index]["construct_data"] is None
    assert data_buffer[test_well_index]["ref_data"] is None


def test_DataAnalyzerProcess__logs_performance_metrics_after_dumping_data(
    four_board_analyzer_process, mocker
):
    da_process, _, _, to_main_queue, _ = four_board_analyzer_process

    mocker.patch.object(Pipeline, "get_compressed_voltage", autospec=True)
    mocker.patch.object(
        pipelines,
        "calculate_displacement_from_voltage",
        autospec=True,
        return_value=np.zeros((2, 2)),
    )

    expected_num_iterations = 10
    expected_iteration_dur = 0.001 * 10 ** 9
    expected_idle_time = expected_iteration_dur * expected_num_iterations
    expected_start_timepoint = 0
    expected_stop_timepoint = 2 * expected_iteration_dur * expected_num_iterations
    expected_latest_percent_use = 100 * (
        1 - expected_idle_time / (expected_stop_timepoint - expected_start_timepoint)
    )
    expected_percent_use_vals = [74.9, 31.7, expected_latest_percent_use]
    expected_data_creation_durs = [3.6, 11.0, 9.5]
    expected_longest_iterations = [
        expected_iteration_dur for _ in range(da_process.num_longest_iterations)
    ]

    da_process._idle_iteration_time_ns = (  # pylint: disable=protected-access
        expected_iteration_dur
    )
    da_process._minimum_iteration_duration_seconds = (  # pylint: disable=protected-access
        2 * expected_iteration_dur / (10 ** 9)
    )
    da_process._start_timepoint_of_last_performance_measurement = (  # pylint: disable=protected-access
        expected_start_timepoint
    )
    da_process._percent_use_values = (  # pylint: disable=protected-access
        expected_percent_use_vals[:-1]
    )
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
    mocker.patch.object(
        time, "perf_counter_ns", autospec=True, side_effect=perf_counter_ns_vals
    )
    perf_counter_vals = []
    waveform_analysis_durations = list(range(24))
    perf_counter_vals.append(0)
    for i in range(24):
        perf_counter_vals.append(0)
        perf_counter_vals.append(waveform_analysis_durations[i])
    perf_counter_vals.append(expected_data_creation_durs[-1])
    mocker.patch.object(
        time, "perf_counter", autospec=True, side_effect=perf_counter_vals
    )
    is_buffer_full_vals = [False for i in range(expected_num_iterations - 1)]
    is_buffer_full_vals.append(True)
    mocker.patch.object(
        da_process, "_is_buffer_full", autospec=True, side_effect=is_buffer_full_vals
    )

    invoke_process_run_and_check_errors(
        da_process, num_iterations=expected_num_iterations
    )
    confirm_queue_is_eventually_of_size(
        to_main_queue, 2
    )  # Tanner (1/4/21): log msg is put into queue after waveform data dump

    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual = actual["message"]
    assert actual["communication_type"] == "performance_metrics"
    assert actual["analysis_durations"] == {
        "max": max(waveform_analysis_durations),
        "min": min(waveform_analysis_durations),
        "stdev": round(stdev(waveform_analysis_durations), 6),
        "mean": round(
            sum(waveform_analysis_durations) / len(waveform_analysis_durations), 6
        ),
    }
    assert actual["data_creating_duration"] == expected_data_creation_durs[-1]
    assert actual["data_creating_duration_metrics"] == {
        "max": max(expected_data_creation_durs),
        "min": min(expected_data_creation_durs),
        "stdev": round(stdev(expected_data_creation_durs), 6),
        "mean": round(
            sum(expected_data_creation_durs) / len(expected_data_creation_durs), 6
        ),
    }
    assert "start_timepoint_of_measurements" not in actual
    assert "idle_iteration_time_ns" not in actual
    num_longest_iterations = da_process.num_longest_iterations
    assert (
        actual["longest_iterations"]
        == expected_longest_iterations[-num_longest_iterations:]
    )
    assert actual["percent_use"] == expected_latest_percent_use
    assert actual["percent_use_metrics"] == {
        "max": max(expected_percent_use_vals),
        "min": min(expected_percent_use_vals),
        "stdev": round(stdev(expected_percent_use_vals), 6),
        "mean": round(
            sum(expected_percent_use_vals) / len(expected_percent_use_vals), 6
        ),
    }


def test_DataAnalyzerProcess__does_not_include_metrics_in_first_logging_cycle(
    four_board_analyzer_process, mocker
):
    mocker.patch.object(Pipeline, "get_compressed_voltage", autospec=True)
    mocker.patch.object(
        pipelines,
        "calculate_displacement_from_voltage",
        autospec=True,
        return_value=np.zeros((2, 2)),
    )

    da_process, _, _, to_main_queue, _ = four_board_analyzer_process
    da_process._minimum_iteration_duration_seconds = (  # pylint: disable=protected-access
        0
    )
    data_buffer = da_process._data_buffer  # pylint: disable=protected-access
    for i in range(24):
        data_buffer[i]["construct_data"] = np.zeros((2, 2))
        data_buffer[i]["ref_data"] = np.zeros((2, 2))
    mocker.patch.object(da_process, "_is_buffer_full", return_value=True)

    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 2)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual = actual["message"]
    assert "percent_use_metrics" not in actual
    assert "outgoing_data_creation_metrics" not in actual
