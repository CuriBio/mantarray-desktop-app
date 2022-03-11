# -*- coding: utf-8 -*-
import queue
import time
from typing import Dict

from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import DEFAULT_MAGNETOMETER_CONFIG
from mantarray_desktop_app import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app import SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import get_formatted_stack_trace

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_hardware_integration import fixture_four_board_mc_comm_process_hardware_test_mode
from ..fixtures_mc_simulator import create_random_stim_info
from ..helpers import random_bool

__fixtures__ = [
    fixture_four_board_mc_comm_process_hardware_test_mode,
]


def create_random_config() -> Dict[int, Dict[int, bool]]:
    random_config_dict: Dict[int, Dict[int, bool]] = create_magnetometer_config_dict(24)
    num_channels = 0
    for module_dict in random_config_dict.values():
        for cid in module_dict.keys():
            enabled = random_bool()
            num_channels += int(enabled)
            module_dict[cid] = enabled
    # make sure at least one channel is on
    if num_channels == 0:
        random_config_dict[1][0] = True
    return random_config_dict


RANDOM_CONFIG_DICT = create_random_config()

# RANDOM_STIM_INFO_1 = create_random_stim_info()  # type: ignore
RANDOM_STIM_INFO_1 = {
    "protocols": [
        {
            "protocol_id": "A",
            "run_until_stopped": True,
            "stimulation_type": "C",
            "subprotocols": [
                {
                    "phase_one_duration": 10000,
                    "phase_one_charge": 50000,
                    "interphase_interval": 10000,
                    "phase_two_duration": 10000,
                    "phase_two_charge": -50000,
                    "repeat_delay_interval": 50000,
                    "total_active_duration": 5000,
                },
                # get_null_subprotocol(1000),  # type: ignore
            ],
        }
    ],
    "protocol_assignments": {
        GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
            "A" if well_idx in (0, 3, 20, 23) else None
        )
        for well_idx in range(24)
    },
}
RANDOM_STIM_INFO_2 = create_random_stim_info()  # type: ignore

COMMAND_RESPONSE_SEQUENCE = [
    ("get_metadata", "get_metadata"),
    # MAGNETOMETERS
    ("start_managed_acquisition", "start_md_1"),
    ("start_managed_acquisition", "start_md_2"),
    ("stop_managed_acquisition", "stop_md_1"),
    ("stop_managed_acquisition", "stop_md_2"),
    ("change_magnetometer_config", "magnetometer_config"),
    # STIMULATORS
    ("start_stimulation", "start_stim_1"),
    ("stop_stimulation", "stop_stim_1"),
    ("set_protocols_1", "set_protocols_1_1"),
    ("start_stimulation", "start_stim_2_1"),
    ("start_stimulation", "start_stim_2_2"),
    ("set_protocols_1", "set_protocols_1_2"),
    ("stop_stimulation", "stop_stim_2_1"),
    ("stop_stimulation", "stop_stim_2_2"),
    ("set_protocols_2", "set_protocols_2"),
    # FIRMWARE
    # (["start_firmware_update_1", "start_firmware_update_2"], ["start_fw_update_1", "start_fw_update_2"]),
]

COMMANDS_FROM_MAIN = {
    "start_managed_acquisition": {
        "communication_type": "acquisition_manager",
        "command": "start_managed_acquisition",
    },
    "stop_managed_acquisition": {
        "communication_type": "acquisition_manager",
        "command": "stop_managed_acquisition",
    },
    "change_magnetometer_config": {
        "communication_type": "acquisition_manager",
        "command": "change_magnetometer_config",
        "sampling_period": DEFAULT_SAMPLING_PERIOD,
    },
    "set_protocols_1": {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": RANDOM_STIM_INFO_1,
    },
    "set_protocols_2": {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": RANDOM_STIM_INFO_2,
    },
    "start_stimulation": {
        "communication_type": "stimulation",
        "command": "start_stimulation",
    },
    "stop_stimulation": {
        "communication_type": "stimulation",
        "command": "stop_stimulation",
    },
    "start_firmware_update_1": {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": "channel",
    },
    "start_firmware_update_2": {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": "main",
    },
}

RESPONSES = {
    "get_metadata": {
        "communication_type": "metadata_comm",
        "command": "get_metadata",
        "board_index": 0,
        "metadata": {
            BOOT_FLAGS_UUID: 0,
            MANTARRAY_NICKNAME_UUID: bytes([0] * 13).decode("utf-8"),
            MANTARRAY_SERIAL_NUMBER_UUID: bytes([0] * 12).decode("ascii"),
            MAIN_FIRMWARE_VERSION_UUID: "0.0.0",
            CHANNEL_FIRMWARE_VERSION_UUID: "0.0.0",
        },
        # "metadata": MantarrayMcSimulator.default_metadata_values,
    },
    "magnetometer_config": {
        "communication_type": "acquisition_manager",
        "command": "change_magnetometer_config",
        "sampling_period": DEFAULT_SAMPLING_PERIOD,
    },
    "start_md_1": {
        "communication_type": "acquisition_manager",
        "command": "start_managed_acquisition",
    },
    "start_md_2": {
        "communication_type": "acquisition_manager",
        "command": "start_managed_acquisition",
        "hardware_test_message": "Data stream already started",
    },
    "stop_md_1": {
        "communication_type": "acquisition_manager",
        "command": "stop_managed_acquisition",
    },
    "stop_md_2": {
        "communication_type": "acquisition_manager",
        "command": "stop_managed_acquisition",
        "hardware_test_message": "Data stream already stopped",
    },
    "set_protocols_1_1": {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": RANDOM_STIM_INFO_1,
    },
    "set_protocols_1_2": {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "hardware_test_message": "Command failed",
        "stim_info": RANDOM_STIM_INFO_1,
    },
    "set_protocols_2": {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": RANDOM_STIM_INFO_2,
    },
    "start_stim_1": {
        "communication_type": "stimulation",
        "command": "start_stimulation",
        "hardware_test_message": "Command failed",
    },
    "start_stim_2_1": {
        "communication_type": "stimulation",
        "command": "start_stimulation",
    },
    "start_stim_2_2": {
        "communication_type": "stimulation",
        "command": "start_stimulation",
        "hardware_test_message": "Command failed",
    },
    "stop_stim_1": {
        "communication_type": "stimulation",
        "command": "stop_stimulation",
        "hardware_test_message": "Command failed",
    },
    "stop_stim_2_1": {
        "communication_type": "stimulation",
        "command": "stop_stimulation",
    },
    "stop_stim_2_2": {
        "communication_type": "stimulation",
        "command": "stop_stimulation",
        "hardware_test_message": "Command failed",
    },
    "start_fw_update_1": {
        "communication_type": "firmware_update",
        "command": "update_completed",
        "firmware_type": "channel",
    },
    "start_fw_update_2": {
        "communication_type": "firmware_update",
        "command": "update_completed",
        "firmware_type": "main",
    },
}


@pytest.mark.live_test
def test_communication_with_live_board(four_board_mc_comm_process_hardware_test_mode):
    # pylint: disable=too-many-locals,too-many-branches  # Tanner (6/4/21): a lot of local variables and branches needed for this test
    mc_process, board_queues, error_queue = four_board_mc_comm_process_hardware_test_mode.values()
    input_queue = board_queues[0][0]
    output_queue = board_queues[0][1]
    data_queue = board_queues[0][2]

    mc_process._main_firmware_update_bytes = bytes(int(SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES * 1.5))
    mc_process._channel_firmware_update_bytes = bytes(int(SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES * 1.5))

    print("\n*** BEGIN TEST ***")  # allow-print

    mc_process.start()

    for command, response_key in COMMAND_RESPONSE_SEQUENCE:
        if not isinstance(command, str):
            for idx, sub_command in enumerate(command):
                command_dict = COMMANDS_FROM_MAIN[sub_command]
                print(  # allow-print
                    f"Sending command: {sub_command}, expecting response: {response_key[idx]}"
                )
                input_queue.put_nowait(command_dict)
            expected_response = RESPONSES[response_key[-1]]
        elif command != "get_metadata":
            # get_metadata command is automatically sent by McComm
            command_dict = COMMANDS_FROM_MAIN[command]
            print(f"Sending command: {command}, expecting response: {response_key}")  # allow-print
            input_queue.put_nowait(command_dict)
            expected_response = RESPONSES[response_key]
        else:
            expected_response = RESPONSES[response_key]

        response_found = False
        error = None
        try:
            while not response_found:
                # check for error
                if not error_queue.empty():
                    try:
                        error = error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
                        print(get_formatted_stack_trace(error[0]))  # allow-print
                        assert False
                    except queue.Empty:
                        assert False, "Error queue reported not empty but no error found in queue"
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
                elif comm_type == "firmware_update":
                    print("&&&", msg_to_main)  # allow-print
                    response_found = (
                        msg_to_main["command"] == "update_completed"
                        and msg_to_main["firmware_type"] == "main"
                    )
                elif comm_type == expected_response["communication_type"]:
                    if msg_to_main.get("command", "") == "status_update":
                        print("###", msg_to_main)  # allow-print
                        continue
                    if "timestamp" in msg_to_main:
                        del msg_to_main["timestamp"]
                    # if message is the response, make sure it is as expected
                    print("$$$", msg_to_main)  # allow-print
                    if msg_to_main.get("command", "") == "get_metadata":
                        actual_metadata = msg_to_main.pop("metadata")
                        expected_metadata = expected_response.pop("metadata")
                        assert (
                            actual_metadata == expected_metadata
                        ), f"Incorrect metadata\nActual: {actual_metadata}\nExpected: {expected_metadata}"
                    assert (
                        msg_to_main == expected_response
                    ), f"{response_key}\nActual: {msg_to_main}\nExpected: {expected_response}"
                    if response_key == "start_md_1":
                        # sleep after data stream starts so data can be parsed and sent to file writer
                        print("Sleeping so data can be produced and parsed...")  # allow-print
                        time.sleep(2)
                        print("End sleep...")  # allow-print
                    # elif response_key == "start_stim_2_1":
                    #     print("Sleeping to let stim complete")  # allow-print
                    #     time.sleep(20)
                    response_found = True
                elif msg_to_main.get("command", None) == "set_time" or comm_type == "barcode_comm":
                    # this branch not needed for real board
                    print("@@@", msg_to_main)  # allow-print
                    continue
                else:
                    # o/w stop test
                    print("!!!", msg_to_main)  # allow-print
                    print("!!!", expected_response)  # allow-print
                    assert False, "unexpected msg sent to main"
        except AssertionError as e:
            error = e
            break

    # stop and join McComm
    if error:
        mc_process.hard_stop()
    else:
        mc_process.soft_stop()
    data_sent_to_fw = drain_queue(data_queue)
    mc_process.join()

    if error:
        raise error

    # do one last check of error_queue
    try:
        error = error_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert False, get_formatted_stack_trace(error[0])
    except queue.Empty:
        print("No errors after Instrument Communication Process stopped and joined")  # allow-print

    if len(data_sent_to_fw) == 0:
        assert False, "No data packets sent to File Writer"

    # test keys of dict going to file writer. tests on the actual data will be done in the full integration test
    test_num_wells = 24
    expected_fw_item = {"time_indices": None, "data_type": "magnetometer"}
    for well_idx in range(test_num_wells):
        module_config_values = list(
            DEFAULT_MAGNETOMETER_CONFIG[SERIAL_COMM_WELL_IDX_TO_MODULE_ID[well_idx]].values()
        )
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
        if actual_item["data_type"] == "stimulation":
            print("### Ignoring stim packet:", actual_item)  # allow-print
            continue
        assert actual_item.keys() == expected_fw_item.keys()
        for key, expected_item in expected_fw_item.items():
            if key in ("is_first_packet_of_stream", "time_indices", "data_type"):
                continue
            item = actual_item[key]
            assert item.keys() == expected_item.keys()  # pylint: disable=no-member

    print("*** TEST COMPLETE ***")  # allow-print
