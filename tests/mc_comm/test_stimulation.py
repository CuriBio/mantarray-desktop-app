# -*- coding: utf-8 -*-
import copy
from random import randint

from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import handle_data_packets
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_STIM_STATUS_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app import STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
from mantarray_desktop_app import StimStatuses
from mantarray_desktop_app import StimulationProtocolUpdateFailedError
from mantarray_desktop_app import StimulationProtocolUpdateWhileStimulatingError
from mantarray_desktop_app import StimulationStatusUpdateFailedError
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
import numpy as np
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_comm import set_magnetometer_config_and_start_streaming
from ..fixtures_mc_simulator import create_random_stim_info
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_null_subprotocol
from ..fixtures_mc_simulator import get_random_subprotocol
from ..fixtures_mc_simulator import random_time_index
from ..fixtures_mc_simulator import random_timestamp
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_patch_print,
    fixture_four_board_mc_comm_process_no_handshake,
    fixture_mantarray_mc_simulator_no_beacon,
]


def set_stimulation_protocols(
    mc_fixture,
    simulator,
    stim_info,
):
    mc_process = mc_fixture["mc_process"]
    from_main_queue = mc_fixture["board_queues"][0][0]
    to_main_queue = mc_fixture["board_queues"][0][1]

    config_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": stim_info,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(config_command, from_main_queue)
    # send command, process command, process command response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)


def test_handle_data_packets__parses_single_stim_data_packet_with_a_single_status_correctly():
    base_global_time = randint(0, 100)
    test_time_index = random_time_index()
    test_well_idx = randint(0, 23)
    test_subprotocol_idx = randint(0, 5)

    stim_packet_body = (
        bytes([1])  # num status updates in packet
        + bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_idx]])
        + bytes([StimStatuses.ACTIVE])
        + test_time_index.to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_idx])
    )
    test_data_packet = create_data_packet(
        random_timestamp(),
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STIM_STATUS_PACKET_TYPE,
        stim_packet_body,
    )

    parsed_data_dict = handle_data_packets(bytearray(test_data_packet), [], base_global_time)
    actual_stim_data = parsed_data_dict["stim_data"]
    assert list(actual_stim_data.keys()) == [test_well_idx]
    assert actual_stim_data[test_well_idx].dtype == np.int64
    np.testing.assert_array_equal(
        actual_stim_data[test_well_idx], [[test_time_index - base_global_time], [test_subprotocol_idx]]
    )

    # make sure no magnetometer data was returned
    assert not any(parsed_data_dict["magnetometer_data"].values())


def test_handle_data_packets__parses_single_stim_data_packet_with_multiple_statuses_correctly():
    base_global_time = randint(0, 100)
    test_time_indices = [random_time_index(), random_time_index(), random_time_index()]
    test_well_idx = randint(0, 23)
    test_subprotocol_indices = [randint(0, 5), randint(0, 5), 0]
    test_statuses = [StimStatuses.ACTIVE, StimStatuses.NULL, StimStatuses.RESTARTING]

    stim_packet_body = bytes([3])  # num status updates in packet
    for packet_idx in range(3):
        stim_packet_body += (
            bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_idx]])
            + bytes([test_statuses[packet_idx]])
            + test_time_indices[packet_idx].to_bytes(8, byteorder="little")
            + bytes([test_subprotocol_indices[packet_idx]])
        )
    test_data_packet = create_data_packet(
        random_timestamp(),
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STIM_STATUS_PACKET_TYPE,
        stim_packet_body,
    )

    parsed_data_dict = handle_data_packets(
        bytearray(test_data_packet), [1, 2, 3, 4], base_global_time  # arbitrary channel list,
    )
    actual_stim_data = parsed_data_dict["stim_data"]
    assert list(actual_stim_data.keys()) == [test_well_idx]
    np.testing.assert_array_equal(
        actual_stim_data[test_well_idx],
        # removing last item in these lists since restarting status info is not needed
        [np.array(test_time_indices[:-1]) - base_global_time, test_subprotocol_indices[:-1]],
    )


def test_handle_data_packets__parses_multiple_stim_data_packet_with_multiple_wells_and_statuses_correctly():
    base_global_time = randint(0, 100)
    test_well_indices = [randint(0, 11), randint(12, 23)]
    test_time_indices = [
        [random_time_index(), random_time_index()],
        [random_time_index(), random_time_index(), random_time_index()],
    ]
    test_subprotocol_indices = [
        [0, randint(1, 5)],
        [randint(0, 5), randint(0, 5), 255],
    ]
    test_statuses = [
        [StimStatuses.RESTARTING, StimStatuses.NULL],
        [StimStatuses.ACTIVE, StimStatuses.NULL, StimStatuses.FINISHED],
    ]

    stim_packet_body_1 = (
        bytes([2])  # num status updates in packet
        + bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_indices[0]]])
        + bytes([test_statuses[0][0]])
        + test_time_indices[0][0].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[0][0]])
        + bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_indices[1]]])
        + bytes([test_statuses[1][0]])
        + test_time_indices[1][0].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[1][0]])
    )
    stim_packet_body_2 = (
        bytes([3])  # num status updates in packet
        + bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_indices[1]]])
        + bytes([test_statuses[1][1]])
        + test_time_indices[1][1].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[1][1]])
        + bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_indices[0]]])
        + bytes([test_statuses[0][1]])
        + test_time_indices[0][1].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[0][1]])
        + bytes([SERIAL_COMM_WELL_IDX_TO_MODULE_ID[test_well_indices[1]]])
        + bytes([test_statuses[1][2]])
        + test_time_indices[1][2].to_bytes(8, byteorder="little")
        + bytes([test_subprotocol_indices[1][2]])
    )
    test_data_packet_1 = create_data_packet(
        random_timestamp(),
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STIM_STATUS_PACKET_TYPE,
        stim_packet_body_1,
    )
    test_data_packet_2 = create_data_packet(
        random_timestamp(),
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STIM_STATUS_PACKET_TYPE,
        stim_packet_body_2,
    )

    parsed_data_dict = handle_data_packets(
        bytearray(test_data_packet_1 + test_data_packet_2), [], base_global_time
    )
    actual_stim_data = parsed_data_dict["stim_data"]
    assert sorted(list(actual_stim_data.keys())) == sorted(test_well_indices)
    np.testing.assert_array_equal(
        actual_stim_data[test_well_indices[0]],
        # removing first item in these lists since restarting status info is not needed
        [np.array(test_time_indices[0][1:]) - base_global_time, test_subprotocol_indices[0][1:]],
    )
    np.testing.assert_array_equal(
        actual_stim_data[test_well_indices[1]],
        [np.array(test_time_indices[1]) - base_global_time, test_subprotocol_indices[1]],
    )


def test_McCommunicationProcess__processes_start_and_stop_stimulation_commands__when_commands_are_successful(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    expected_stim_info = create_random_stim_info()
    set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, expected_stim_info)
    expected_stim_running_statuses = (
        {
            well_name: bool(protocol_id)
            for well_name, protocol_id in expected_stim_info["protocol_assignments"].items()
        },
        {well_name: False for well_name in expected_stim_info["protocol_assignments"].keys()},
    )

    spied_get_utc_now = mocker.spy(mc_comm, "_get_formatted_utc_now")

    for command, stim_running_statuses in (
        ("start_stimulation", expected_stim_running_statuses[0]),
        ("stop_stimulation", expected_stim_running_statuses[1]),
    ):
        # send command to mc_process
        expected_response = {"communication_type": "stimulation", "command": command}
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            copy.deepcopy(expected_response), input_queue
        )
        # run mc_process to send command
        invoke_process_run_and_check_errors(mc_process)
        # run simulator to process command and send response
        invoke_process_run_and_check_errors(simulator)
        # assert that stim statuses were updated correctly
        assert simulator.get_stim_running_statuses() == stim_running_statuses
        # run mc_process to process command response and send message back to main
        invoke_process_run_and_check_errors(mc_process)
        # confirm correct message sent to main
        confirm_queue_is_eventually_of_size(output_queue, 1)
        message_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        if command == "start_stimulation":
            expected_response["timestamp"] = spied_get_utc_now.spy_return
        assert message_to_main == expected_response


def test_McCommunicationProcess__raises_error_if_set_protocols_command_received_while_stimulation_is_running(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, create_random_stim_info())

    # start stimulation
    start_stim_command = {"communication_type": "stimulation", "command": "start_stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_stim_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # confirm correct message sent to main
    confirm_queue_is_eventually_of_size(output_queue, 1)
    output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    # send set protocols command and confirm error is raised
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": create_random_stim_info(),
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, input_queue)
    with pytest.raises(StimulationProtocolUpdateWhileStimulatingError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__raises_error_if_set_protocols_command_fails(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # send set protocols command with too many subprotocols in a protocol and confirm error is raised
    bad_stim_info = create_random_stim_info()
    bad_stim_info["protocols"][0]["subprotocols"].extend(
        [get_null_subprotocol(19000)] * STIM_MAX_NUM_SUBPROTOCOLS_PER_PROTOCOL
    )
    with pytest.raises(StimulationProtocolUpdateFailedError):
        set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, bad_stim_info)


def test_McCommunicationProcess__raises_error_if_start_stim_command_fails(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # start stim before protocols are set and confirm error is raised from command failure response
    start_stim_command = {"communication_type": "stimulation", "command": "start_stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_stim_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    with pytest.raises(StimulationStatusUpdateFailedError, match="start_stimulation"):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__raises_error_if_stop_stim_command_fails(
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    # stop stim when it isn't running confirm error is raised from command failure response
    stop_stim_command = {"communication_type": "stimulation", "command": "stop_stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_stim_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    with pytest.raises(StimulationStatusUpdateFailedError, match="stop_stimulation"):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__handles_stimulation_status_comm_from_instrument(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, to_main_queue, to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    total_active_duration = 76000
    test_well_idx = randint(0, 23)
    expected_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "C",
                "run_until_stopped": False,
                "subprotocols": [get_random_subprotocol(total_active_duration=total_active_duration)],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
                "A" if well_idx == test_well_idx else None
            )
            for well_idx in range(24)
        },
    }
    # send command to mc_process
    set_protocols_command = {
        "communication_type": "stimulation",
        "command": "set_protocols",
        "stim_info": expected_stim_info,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(set_protocols_command, input_queue)
    # set protocols and process response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # remove message to main
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    # mock so no data packets are sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        return_value=0,
    )
    # mock so not status updates are sent yet
    mocked_get_us_subprotocol = mocker.patch.object(
        mc_simulator,
        "_get_us_since_subprotocol_start",
        autospec=True,
        return_value=0,
    )
    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    # send start stimulation command
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # process command, send back response and initial stimulator status packet
    invoke_process_run_and_check_errors(simulator)
    # process command response only
    invoke_process_run_and_check_errors(mc_process)
    assert simulator.in_waiting > 0
    # remove message to main
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    # process initial stim packet and make sure it was not sent to file writer
    invoke_process_run_and_check_errors(mc_process)
    assert simulator.in_waiting == 0

    expected_global_time_stim_start = spied_global_timer.spy_return

    # start data streaming
    set_magnetometer_config_and_start_streaming(four_board_mc_comm_process_no_handshake, simulator)
    # send stimulator status packet after initial subprotocol completes
    mocked_get_us_subprotocol.return_value = total_active_duration
    invoke_process_run_and_check_errors(simulator)
    # process stimulator status packet
    invoke_process_run_and_check_errors(mc_process)

    expected_global_time_data_start = spied_global_timer.spy_return

    # check status packets sent to file writer
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    msg_to_fw = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_fw["data_type"] == "stimulation"
    assert list(msg_to_fw["well_statuses"].keys()) == [test_well_idx]
    expected_well_statuses = [
        [expected_global_time_stim_start + total_active_duration - expected_global_time_data_start],
        [255],  # subprotocol idx
    ]
    np.testing.assert_array_equal(msg_to_fw["well_statuses"][test_well_idx], expected_well_statuses)
