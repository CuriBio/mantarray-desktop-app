# -*- coding: utf-8 -*-
import copy
import json

from freezegun import freeze_time
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process_beta_2_mode
from ..fixtures_data_analyzer import set_sampling_period
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..parsed_channel_data_packets import SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS


__fixtures__ = [
    fixture_four_board_analyzer_process_beta_2_mode,
]


@freeze_time("2021-06-15 16:39:10.120589")
def test_DataAnalyzerProcess__sends_outgoing_data_dict_to_main_as_soon_as_it_retrieves_a_data_packet_from_file_writer__and_sends_data_available_message_to_main(
    four_board_analyzer_process_beta_2_mode,
):
    # set arbitrary sampling period
    set_sampling_period(four_board_analyzer_process_beta_2_mode, 1000)

    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    to_main_queue = four_board_analyzer_process_beta_2_mode["to_main_queue"]
    incoming_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][0]
    outgoing_data_queue = four_board_analyzer_process_beta_2_mode["board_queues"][0][1]

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
    outgoing_data_dict = outgoing_data_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    waveform_data_points = dict()
    for well_idx in range(24):
        waveform_data_points[well_idx] = dict()
        for key in test_data_packet[well_idx].keys():
            if key == "time_offsets":
                continue
            waveform_data_points[well_idx][key] = test_data_packet[well_idx][key].tolist()
    expected_outgoing_dict = {
        "waveform_data": {"basic_data": {"waveform_data_points": waveform_data_points}},
        "earliest_timepoint": test_data_packet["time_indices"][0].item(),
        "latest_timepoint": test_data_packet["time_indices"][-1].item(),
        "num_data_points": len(test_data_packet["time_indices"]),
    }
    assert outgoing_data_dict == json.dumps(expected_outgoing_dict)
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
