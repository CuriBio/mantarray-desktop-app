# -*- coding: utf-8 -*-
import copy
import json

from freezegun import freeze_time
from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app import SERIAL_COMM_DEFAULT_DATA_CHANNEL
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
import numpy as np
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process_beta_2_mode
from ..fixtures_data_analyzer import set_magnetometer_config
from ..fixtures_file_writer import GENERIC_BOARD_MAGNETOMETER_CONFIGURATION
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..parsed_channel_data_packets import SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS


__fixtures__ = [
    fixture_four_board_analyzer_process_beta_2_mode,
]


@freeze_time("2021-06-15 16:39:10.120589")
def test_DataAnalyzerProcess__sends_outgoing_data_dict_to_main_as_soon_as_it_retrieves_a_data_packet_from_file_writer__and_sends_data_available_message_to_main(
    four_board_analyzer_process_beta_2_mode, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    to_main_queue = four_board_analyzer_process_beta_2_mode["to_main_queue"]
    incoming_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][0]
    outgoing_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][1]

    # mock so that well metrics don't populate outgoing data queue
    mocker.patch.object(da_process, "_dump_outgoing_well_metrics", autospec=True)
    # mock so performance log messages don't populate queue to main
    mocker.patch.object(da_process, "_handle_performance_logging", autospec=True)

    da_process.init_streams()
    # set config arbitrary sampling period
    test_sampling_period = 1000
    set_magnetometer_config(
        four_board_analyzer_process_beta_2_mode,
        {
            "magnetometer_config": GENERIC_BOARD_MAGNETOMETER_CONFIGURATION,
            "sampling_period": test_sampling_period,
        },
    )

    # start managed_acquisition
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(START_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    # remove message to main
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_empty(outgoing_data_queue)
    confirm_queue_is_eventually_empty(to_main_queue)

    test_data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(outgoing_data_queue, 1)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    # test data dump
    waveform_data_points = dict()
    for well_idx in range(24):
        default_channel_data = test_data_packet[well_idx][SERIAL_COMM_DEFAULT_DATA_CHANNEL]
        pipeline = da_process.get_pipeline_template().create_pipeline()
        pipeline.load_raw_gmr_data(
            np.array([test_data_packet["time_indices"], default_channel_data], np.int64),
            np.zeros((2, len(default_channel_data))),
        )
        compressed_data = pipeline.get_compressed_force()
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


def test_DataAnalyzerProcess__does_not_process_data_packets_after_receiving_stop_managed_acquisition_command_until_receiving_first_packet_of_new_stream(
    four_board_analyzer_process_beta_2_mode, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    to_main_queue = four_board_analyzer_process_beta_2_mode["to_main_queue"]
    incoming_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][0]

    # mock so these since not using real data
    mocked_process_data = mocker.patch.object(
        da_process, "_process_beta_2_data", autospec=True, return_value={}
    )

    invoke_process_run_and_check_errors(da_process, perform_setup_before_loop=True)
    # set config arbitrary sampling period
    test_sampling_period = 10000
    set_magnetometer_config(
        four_board_analyzer_process_beta_2_mode,
        {
            "magnetometer_config": GENERIC_BOARD_MAGNETOMETER_CONFIGURATION,
            "sampling_period": test_sampling_period,
        },
    )

    # start managed_acquisition
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(START_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)
    # send first packet of first stream and make sure it is processed
    test_data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_data_packet["is_first_packet_of_stream"] = True
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 1
    # send another packet of first stream and make sure it is processed
    test_data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_data_packet["is_first_packet_of_stream"] = False
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 2

    # stop managed acquisition and make sure next data packet in the first stream is not processed
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(STOP_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)
    test_data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_data_packet["is_first_packet_of_stream"] = False
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 2

    # start managed acquisition again and make sure next data packet in the first stream is not processed
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(START_MANAGED_ACQUISITION_COMMUNICATION), from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)
    test_data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_data_packet["is_first_packet_of_stream"] = False
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 2

    # send first data packet from second stream and make sure it is processed
    test_data_packet = copy.deepcopy(SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS)
    test_data_packet["is_first_packet_of_stream"] = True
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_data_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    assert mocked_process_data.call_count == 3

    # prevent BrokenPipeErrors
    drain_queue(to_main_queue)


def test_DataAnalyzerProcess__processes_incoming_stim_packet(four_board_analyzer_process_beta_2_mode, mocker):
    # TODO Tanner (10/20/21): add to this test when ready to add stim handling
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    incoming_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][0]

    # can probably remove this spy and assertion once actual handling is implemented
    spied_process_stim_packet = mocker.spy(da_process, "_process_stim_packet")

    test_stim_packet = {"data_type": "stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_stim_packet, incoming_data_queue)
    invoke_process_run_and_check_errors(da_process)
    spied_process_stim_packet.assert_called_once_with(test_stim_packet)
