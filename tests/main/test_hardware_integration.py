# -*- coding: utf-8 -*-
import queue
import time

from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID,MantarrayMcSimulator
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import get_formatted_stack_trace

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_hardware_integration import fixture_four_board_mc_comm_process_hardware_test_mode
from ..helpers import random_bool

__fixtures__ = [
    fixture_four_board_mc_comm_process_hardware_test_mode,
]


def create_random_config():
    random_config_dict = create_magnetometer_config_dict(24)
    num_channels = 0
    for module_dict in random_config_dict.values():
        for cid in module_dict.keys():
            if num_channels == 15:
                break
            enabled = random_bool()
            num_channels += int(enabled)
            module_dict[cid] = enabled  # type: ignore
    # make sure at least one channel is on
    if num_channels == 0:
        random_config_dict[1][0] = True
    return random_config_dict


random_config_dict = create_random_config()

COMMAND_RESPONSE_SEQUENCE = [
    ("get_metadata", "get_metadata"),
    ("change_magnetometer_config_1", "magnetometer_config_1"),
    ("start_managed_acquisition", "start_1"),
    ("start_managed_acquisition", "start_2"),
    ("stop_managed_acquisition", "stop_1"),
    ("stop_managed_acquisition", "stop_2"),
    ("change_magnetometer_config_2", "magnetometer_config_2"),
]

COMMANDS_FROM_MAIN = {
    "change_magnetometer_config_1": {
        "communication_type": "to_instrument",
        "command": "change_magnetometer_config",
        "magnetometer_config": random_config_dict,
        "sampling_period": 10,
    },
    "start_managed_acquisition": {
        "communication_type": "to_instrument",
        "command": "start_managed_acquisition",
    },
    "stop_managed_acquisition": {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
    },
    "change_magnetometer_config_2": {
        "communication_type": "to_instrument",
        "command": "change_magnetometer_config",
        "magnetometer_config": create_magnetometer_config_dict(24),
        "sampling_period": 21000,
    },
}

RESPONSES = {
    "get_metadata": {
        "communication_type": "metadata_comm",
        "board_index": 0,
        "metadata": MantarrayMcSimulator.default_metadata_values, # TODO: remove this once get_metadata command is implemented
    },
    "magnetometer_config_1": {
        "communication_type": "to_instrument",
        "command": "change_magnetometer_config",
        "magnetometer_config": random_config_dict,
        "sampling_period": 10,
    },
    "start_1": {
        "communication_type": "to_instrument",
        "command": "start_managed_acquisition",
        "magnetometer_config": random_config_dict,
    },
    "start_2": {
        "communication_type": "to_instrument",
        "command": "start_managed_acquisition",
        "hardware_test_message": "Data stream already started",
    },
    "stop_1": {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
    },
    "stop_2": {
        "communication_type": "to_instrument",
        "command": "stop_managed_acquisition",
        "hardware_test_message": "Data stream already stopped",
    },
    "magnetometer_config_2": {
        "communication_type": "to_instrument",
        "command": "change_magnetometer_config",
        "magnetometer_config": create_magnetometer_config_dict(24),
        "sampling_period": 21000,
    },
}


@pytest.mark.live_test
def test_communication_with_live_board(four_board_mc_comm_process_hardware_test_mode):
    # pylint: disable=too-many-locals  # Tanner (6/4/21): a lot of local variables needed for this test
    mc_process, board_queues, error_queue = four_board_mc_comm_process_hardware_test_mode.values()
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    data_queue = board_queues[0][2]

    print("\n*** BEGIN TEST ***")  # allow-print

    mc_process.start()

    for command, response_key in COMMAND_RESPONSE_SEQUENCE:
        if command != "get_metadata":
            # get_metadata command is automatically sent by McComm
            command_dict = COMMANDS_FROM_MAIN[command]
            print(f"Sending command: {command}")
            input_queue.put_nowait(command_dict)

        expected_response = RESPONSES[response_key]
        response_found = False
        while not response_found:
            # check for error
            try:
                error = error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
                assert False, get_formatted_stack_trace(error[0])
            except queue.Empty:
                pass
            # check for message to main
            try:
                msg_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
            except queue.Empty:
                continue

            # if message is found then handle it
            comm_type = msg_to_main["communication_type"]
            if comm_type == "log":
                # if message is from a status beacon or handshake, just print it
                print("### Log msg:", msg_to_main["message"])  # allow-print
            elif comm_type == "board_connection_status_change":
                # if message is some other form of expected message, just print it
                print("###", msg_to_main)  # allow-print
            elif comm_type == expected_response["communication_type"]:
                # if message is the response, make sure it is as expected
                print("$$$", msg_to_main)  # allow-print
                for key, value in expected_response.items():
                    assert (
                        msg_to_main[key] == value
                    ), f"\nActual: {msg_to_main}\nExpected: {expected_response}"
                if response_key == "start_1":
                    # sleep after data stream starts so data can be parsed and sent to file writer
                    print("Sleeping so data can be produced and parsed...")  # allow-print
                    time.sleep(2)
                    print("End sleep...")  # allow-print
                response_found = True
            # elif comm_type == "barcode_comm" or msg_to_main["command"] == "set_time":
            #     pass  # TODO remove this elif branch when testing with real board
            else:
                # o/w stop test
                assert False, msg_to_main

    # stop and join McComm
    mc_process.soft_stop()
    data_sent_to_fw = drain_queue(data_queue)
    mc_process.join()
    # do one last check of error_queue
    try:
        error = error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert False, get_formatted_stack_trace(error[0])
    except queue.Empty:
        print("No errors after Instrument Communication Process stopped and joined")  # allow-print

    # test keys of dict going to file writer. tests on the actual data will be done in the full integration test
    test_num_wells = 24
    expected_fw_item = {"time_indices": None}
    for well_idx in range(test_num_wells):
        module_config_values = list(random_config_dict[SERIAL_COMM_WELL_IDX_TO_MODULE_ID[well_idx]].values())
        if not any(module_config_values):
            continue

        num_channels_for_well = 0
        for sensor_start_idx in range(0, SERIAL_COMM_NUM_DATA_CHANNELS, SERIAL_COMM_NUM_CHANNELS_PER_SENSOR):
            num_channels_for_sensor = sum(
                module_config_values[
                    sensor_start_idx : sensor_start_idx + SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
                ]
            )
            num_channels_for_well += int(num_channels_for_sensor > 0)

        channel_dict = {"time_offsets": None}
        for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
            if not module_config_values[channel_id]:
                continue
            channel_dict[channel_id] = None
        expected_fw_item[well_idx] = channel_dict
    expected_fw_item["is_first_packet_of_stream"] = None

    for actual_item in data_sent_to_fw:
        assert actual_item.keys() == expected_fw_item.keys()
        for key, expected_item in expected_fw_item.items():
            if key in ("is_first_packet_of_stream", "time_indices"):
                continue
            item = actual_item[key]
            assert item.keys() == expected_item.keys()  # pylint: disable=no-member

    print("*** TEST COMPLETE ***")  # allow-print
