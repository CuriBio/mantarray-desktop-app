# -*- coding: utf-8 -*-
import copy
import datetime
from random import randint
import struct

from freezegun import freeze_time
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import STIM_COMPLETE_SUBPROTOCOL_IDX
from mantarray_desktop_app import StimulationProtocolUpdateFailedError
from mantarray_desktop_app import StimulationProtocolUpdateWhileStimulatingError
from mantarray_desktop_app import StimulationStatusUpdateFailedError
from mantarray_desktop_app.constants import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app.constants import GENERIC_24_WELL_DEFINITION
from mantarray_desktop_app.constants import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app.constants import NUM_INITIAL_SECONDS_TO_DROP
from mantarray_desktop_app.constants import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_PAYLOAD_INDEX
from mantarray_desktop_app.constants import STIM_MODULE_ID_TO_WELL_IDX
from mantarray_desktop_app.constants import StimulatorCircuitStatuses
from mantarray_desktop_app.simulators import mc_simulator
from mantarray_desktop_app.utils.serial_comm import convert_adc_readings_to_circuit_status
from mantarray_desktop_app.utils.stimulation import get_subprotocol_dur_us
import numpy as np
import pytest
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_comm import set_sampling_period
from ..fixtures_mc_comm import set_sampling_period_and_start_streaming
from ..fixtures_mc_comm import start_data_stream
from ..fixtures_mc_comm import stop_data_stream
from ..fixtures_mc_simulator import create_random_stim_info
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import get_random_stim_pulse
from ..fixtures_mc_simulator import get_random_subprotocol
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty
from ..helpers import random_bool


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

    config_command = {"communication_type": "stimulation", "command": "set_protocols", "stim_info": stim_info}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(config_command, from_main_queue)
    # send command, process command, process command response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    assert simulator.in_waiting == 0

    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)


def test_McCommunicationProcess__processes_start_stim_checks_command__and_sends_correct_stim_circuit_statuses_to_main(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    num_wells = 24
    test_well_indices = list(range(4))
    test_well_indices.extend([i for i in range(4, num_wells) if random_bool()])

    # set known adc readings in simulator. these first 4 values are hard coded, if this test fails might need to update them
    adc_readings = [(0, 0), (0, 2039), (0, 2049), (1113, 0)]
    adc_readings.extend([(i, i + 100) for i in range(num_wells - len(adc_readings))])
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_adc_readings", "adc_readings": adc_readings}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # send command
    start_stim_checks_command = {
        "communication_type": "stimulation",
        "command": "start_stim_checks",
        "well_indices": test_well_indices,
        "stim_barcode": MantarrayMcSimulator.default_stim_barcode,
        "plate_barcode": MantarrayMcSimulator.default_plate_barcode,
        "stim_barcode_is_from_scanner": True,
        "plate_barcode_is_from_scanner": True,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(start_stim_checks_command), input_queue
    )

    spied_write = mocker.spy(simulator, "write")

    invoke_process_run_and_check_errors(mc_process)

    # make sure each well's value is set based on if a protocol is assigned correctly
    bytes_sent = spied_write.call_args[0][0]
    well_val_bytes = bytes_sent[SERIAL_COMM_PAYLOAD_INDEX:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES]
    for module_id, well_val in enumerate(struct.unpack(f"<{num_wells}?", well_val_bytes)):
        well_idx = STIM_MODULE_ID_TO_WELL_IDX[module_id]
        assert well_val is (well_idx in test_well_indices), well_idx

    # process command and send response
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(output_queue, 1)
    msg_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    # make sure that the message sent back to main contains the correct values
    stimulator_circuit_statuses = {}
    for well_idx in test_well_indices:
        well_readings = adc_readings[well_idx]
        status_int = convert_adc_readings_to_circuit_status(*well_readings)
        status = list(StimulatorCircuitStatuses)[status_int + 1].name.lower()
        stimulator_circuit_statuses[well_idx] = status
    assert msg_to_main["stimulator_circuit_statuses"] == stimulator_circuit_statuses

    assert msg_to_main["adc_readings"] == {
        well_idx: adc_reading
        for well_idx, adc_reading in enumerate(adc_readings)
        if well_idx in test_well_indices
    }


@freeze_time(datetime.datetime(year=2021, month=10, day=24, hour=13, minute=7, second=23, microsecond=173814))
def test_McCommunicationProcess__processes_start_and_stop_stimulation_commands__when_commands_are_successful(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    expected_stim_info = create_random_stim_info()
    set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, expected_stim_info)

    spied_reset_stim_buffers = mocker.spy(mc_process, "_reset_stim_status_buffers")

    for command in ("start_stimulation", "stop_stimulation"):
        # send command to mc_process
        expected_response = {"communication_type": "stimulation", "command": command}
        put_object_into_queue_and_raise_error_if_eventually_still_empty(
            copy.deepcopy(expected_response), input_queue
        )
        # run mc_process to send command
        invoke_process_run_and_check_errors(mc_process)
        # run simulator to process command and send response
        invoke_process_run_and_check_errors(simulator)
        # run mc_process to process command response and send message back to main
        invoke_process_run_and_check_errors(mc_process)
        # confirm correct message sent to main
        expected_size = 1 if command == "start_stimulation" else 2
        confirm_queue_is_eventually_of_size(output_queue, expected_size)
        message_to_main = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        if command == "start_stimulation":
            spied_reset_stim_buffers.assert_not_called()
            expected_response["timestamp"] = datetime.datetime(
                year=2021, month=10, day=24, hour=13, minute=7, second=23, microsecond=173814
            )
        else:
            spied_reset_stim_buffers.assert_called_once()
            # also check that stim complete message was sent to main
            stim_status_update_msg = output_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
            assert stim_status_update_msg["communication_type"] == "stimulation"
            assert stim_status_update_msg["command"] == "status_update"
            assert set(stim_status_update_msg["wells_done_stimulating"]) == set(
                GENERIC_24_WELL_DEFINITION.get_well_index_from_well_name(well_name)
                for well_name, protocol_id in expected_stim_info["protocol_assignments"].items()
                if protocol_id
            )
        assert message_to_main == expected_response


def test_McCommunicationProcess__raises_error_if_set_protocols_command_received_while_stimulation_is_running(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, output_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
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
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # send command with too many protocols so it fails
    stim_info = create_random_stim_info()
    stim_info["protocols"] += [stim_info["protocols"][0]] * 25

    # send set_protocols command again now that stimulation is running and make sure errors is raised
    with pytest.raises(StimulationProtocolUpdateFailedError):
        set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, stim_info)


def test_McCommunicationProcess__raises_error_if_start_stim_command_fails(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # start stim before protocols are set and confirm error is raised from command failure response
    start_stim_command = {"communication_type": "stimulation", "command": "start_stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_stim_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    with pytest.raises(StimulationStatusUpdateFailedError, match="start_stimulation"):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__raises_error_if_stop_stim_command_fails(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # stop stim when it isn't running confirm error is raised from command failure response
    stop_stim_command = {"communication_type": "stimulation", "command": "stop_stimulation"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_stim_command, input_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    with pytest.raises(StimulationStatusUpdateFailedError, match="stop_stimulation"):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__handles_stimulation_status_comm_from_instrument__stim_completing_before_data_stream_starts(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, to_main_queue, to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    test_subprotocol = get_random_subprotocol()

    test_well_indices = [randint(0, 11), randint(12, 23)]
    expected_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "C",
                "run_until_stopped": False,
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_iterations": 1,
                        "subprotocols": [test_subprotocol],
                    }
                ],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
                "A" if well_idx in test_well_indices else None
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

    test_duration_us = get_subprotocol_dur_us(test_subprotocol)
    # mock so protocol will complete in first iteration
    mocker.patch.object(
        mc_simulator, "_get_us_since_subprotocol_start", autospec=True, return_value=test_duration_us
    )
    invoke_process_run_and_check_errors(simulator)

    # send start stimulation command
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # process command, send back response and initial stimulator status packet
    invoke_process_run_and_check_errors(simulator)
    # process command response and stim packet and make sure stim packet was not sent to file writer
    invoke_process_run_and_check_errors(mc_process)
    assert simulator.in_waiting == 0
    confirm_queue_is_eventually_empty(to_fw_queue)

    # confirm stimulation complete message sent to main
    msg_to_main = drain_queue(to_main_queue)[-1]
    assert msg_to_main["communication_type"] == "stimulation"
    assert msg_to_main["command"] == "status_update"
    assert set(msg_to_main["wells_done_stimulating"]) == set(test_well_indices)

    # mock so no mag data is produced
    mocker.patch.object(mc_simulator, "_get_us_since_last_data_packet", autospec=True, return_value=0)
    # start data streaming
    set_sampling_period_and_start_streaming(four_board_mc_comm_process_no_handshake, simulator)
    # check no status packets sent to file writer
    confirm_queue_is_eventually_empty(to_fw_queue)


def test_McCommunicationProcess__handles_stimulation_status_comm_from_instrument__data_stream_begins_in_middle_of_protocol(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, to_main_queue, to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period(four_board_mc_comm_process_no_handshake, simulator)

    test_subprotocol = get_random_subprotocol()

    test_well_indices = [randint(0, 11), randint(12, 23)]
    expected_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "V",
                "run_until_stopped": False,
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_iterations": 1,
                        "subprotocols": [test_subprotocol] * 2,
                    }
                ],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
                "A" if well_idx in test_well_indices else None
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

    # mock so just enough mag data is produced to get through initial buffering
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[MICRO_TO_BASE_CONVERSION * NUM_INITIAL_SECONDS_TO_DROP + DEFAULT_SAMPLING_PERIOD, 0],
    )
    # mock so no mag data is actually sent to file_writer
    mocker.patch.object(mc_process, "_dump_mag_data_packet", autospec=True)

    test_duration_us = get_subprotocol_dur_us(test_subprotocol)
    # mock so one status update is produced
    mocked_get_us_subprotocol = mocker.patch.object(
        mc_simulator, "_get_us_since_subprotocol_start", autospec=True, return_value=test_duration_us
    )
    spied_global_timer = mocker.spy(simulator, "_get_global_timer")

    # send start stimulation command
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # process command, send back response and initial stimulator status packet
    invoke_process_run_and_check_errors(simulator)
    # process command response and initial stim packet and make sure stim packet was not sent to file writer
    invoke_process_run_and_check_errors(mc_process)
    assert simulator.in_waiting == 0
    confirm_queue_is_eventually_empty(to_fw_queue)

    expected_global_time_stim_start = spied_global_timer.spy_return

    # start data streaming
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        dict(START_MANAGED_ACQUISITION_COMMUNICATION), input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # send stimulator status packet after initial subprotocol completes
    mocked_get_us_subprotocol.return_value = test_duration_us
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # process stim statuses and start data streaming command response
    invoke_process_run_and_check_errors(mc_process)

    expected_global_time_data_start = spied_global_timer.spy_return

    # check status packet sent to file writer
    confirm_queue_is_eventually_of_size(to_fw_queue, 2)
    expected_well_statuses = (
        [
            [
                expected_global_time_stim_start
                - (NUM_INITIAL_SECONDS_TO_DROP * MICRO_TO_BASE_CONVERSION)
                + test_duration_us
                - expected_global_time_data_start
            ],
            [1],
        ],
        [
            [
                expected_global_time_stim_start
                - (NUM_INITIAL_SECONDS_TO_DROP * MICRO_TO_BASE_CONVERSION)
                + (test_duration_us * 2)
                - expected_global_time_data_start
            ],
            [STIM_COMPLETE_SUBPROTOCOL_IDX],
        ],
    )
    for i, expected_well_status in enumerate(expected_well_statuses):
        msg_to_fw = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert msg_to_fw["data_type"] == "stimulation", i
        assert msg_to_fw["is_first_packet_of_stream"] is (i == 0), i
        assert set(msg_to_fw["well_statuses"].keys()) == set(test_well_indices), i
        np.testing.assert_array_equal(
            msg_to_fw["well_statuses"][test_well_indices[0]], expected_well_status, err_msg=f"Packet {i}"
        )
        np.testing.assert_array_equal(
            msg_to_fw["well_statuses"][test_well_indices[1]], expected_well_status, err_msg=f"Packet {i}"
        )


def test_McCommunicationProcess__handles_stimulation_status_comm_from_instrument__stim_starting_while_data_is_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, to_main_queue, to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    test_subprotocol = get_random_stim_pulse()

    test_well_indices = [randint(0, 11), randint(12, 23)]
    expected_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "C",
                "run_until_stopped": False,
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_iterations": 1,
                        "subprotocols": [test_subprotocol],
                    }
                ],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
                "A" if well_idx in test_well_indices else None
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

    spied_global_timer = mocker.spy(simulator, "_get_global_timer")
    # mock so just enough mag data is produced to get through initial buffering
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        return_value=MICRO_TO_BASE_CONVERSION * NUM_INITIAL_SECONDS_TO_DROP + DEFAULT_SAMPLING_PERIOD,
    )
    # mock so no mag data is actually sent to file_writer
    mocker.patch.object(mc_process, "_dump_mag_data_packet", autospec=True)

    # start data streaming
    set_sampling_period_and_start_streaming(four_board_mc_comm_process_no_handshake, simulator)
    # check no status packets sent to file writer
    confirm_queue_is_eventually_empty(to_fw_queue)

    expected_global_time_data_start = spied_global_timer.spy_return

    test_duration_us = get_subprotocol_dur_us(test_subprotocol)
    # mock so protocol will complete in first iteration
    mocker.patch.object(
        mc_simulator, "_get_us_since_subprotocol_start", autospec=True, return_value=test_duration_us
    )

    # send start stimulation command
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # process command, send back response and both stim status packet
    invoke_process_run_and_check_errors(simulator)
    # process command response and both stim packets
    invoke_process_run_and_check_errors(mc_process)
    assert simulator.in_waiting == 0
    # remove message to main
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    expected_global_time_stim_start = spied_global_timer.spy_return

    # confirm stimulation complete message sent to main
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_main["communication_type"] == "stimulation"
    assert msg_to_main["command"] == "status_update"
    assert set(msg_to_main["wells_done_stimulating"]) == set(test_well_indices)

    # check status packet sent to file writer
    stim_status_msg = drain_queue(to_fw_queue)[-1]
    assert stim_status_msg["data_type"] == "stimulation"
    assert stim_status_msg["is_first_packet_of_stream"] is True
    assert set(stim_status_msg["well_statuses"].keys()) == set(test_well_indices)
    expected_well_statuses = [
        [
            expected_global_time_stim_start
            - (NUM_INITIAL_SECONDS_TO_DROP * MICRO_TO_BASE_CONVERSION)
            - expected_global_time_data_start,
            expected_global_time_stim_start
            - (NUM_INITIAL_SECONDS_TO_DROP * MICRO_TO_BASE_CONVERSION)
            + test_duration_us
            - expected_global_time_data_start,
        ],
        [0, STIM_COMPLETE_SUBPROTOCOL_IDX],
    ]
    for test_well_idx in test_well_indices:
        np.testing.assert_array_equal(
            stim_status_msg["well_statuses"][test_well_idx],
            expected_well_statuses,
            err_msg=f"Well {test_well_idx}",
        )


def test_McCommunicationProcess__protocols_can_be_updated_and_stimulation_can_be_restarted_after_initial_run_completes(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, to_main_queue, _ = four_board_mc_comm_process_no_handshake["board_queues"][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    test_first_subprotocol = get_random_stim_pulse()

    test_well_indices = [randint(0, 11), randint(12, 23)]
    test_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "C",
                "run_until_stopped": False,
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_iterations": 1,
                        "subprotocols": [test_first_subprotocol],
                    }
                ],
            }
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
                "A" if well_idx in test_well_indices else None
            )
            for well_idx in range(24)
        },
    }
    set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, test_stim_info)

    test_duration_us = get_subprotocol_dur_us(test_first_subprotocol)
    # mock so protocol will complete in first iteration
    mocked_get_us_sss = mocker.patch.object(mc_simulator, "_get_us_since_subprotocol_start", autospec=True)
    mocked_get_us_sss.return_value = test_duration_us

    # send start stimulation command
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # process command, send back response and both stim status packet
    invoke_process_run_and_check_errors(simulator)
    # process command response and both stim packets
    invoke_process_run_and_check_errors(mc_process, num_iterations=2)
    assert simulator.in_waiting == 0
    # remove message to main
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    # confirm stimulation complete message sent to main
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert set(msg_to_main["wells_done_stimulating"]) == set(test_well_indices)

    # mock so no more stim packets are sent
    mocked_get_us_sss.return_value = 0

    # update protocols
    set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, create_random_stim_info())
    # restart stimulation
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # process command, send back response
    invoke_process_run_and_check_errors(simulator)
    # process command response
    invoke_process_run_and_check_errors(mc_process)
    # confirm start stim response sent to main

    start_stim_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert start_stim_response["communication_type"] == "stimulation"
    assert start_stim_response["command"] == "start_stimulation"


def test_McCommunicationProcess__stim_packets_sent_to_file_writer_after_restarting_data_stream(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    input_queue, to_main_queue, to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    test_subprotocol = get_random_subprotocol()

    test_well_idx = randint(0, 23)
    test_stim_info = {
        "protocols": [
            {
                "protocol_id": "A",
                "stimulation_type": "C",
                "run_until_stopped": True,
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_iterations": 1,
                        "subprotocols": [test_subprotocol],
                    }
                ],
            },
            {
                "protocol_id": "B",
                "stimulation_type": "C",
                "run_until_stopped": True,
                "subprotocols": [
                    {
                        "type": "loop",
                        "num_iterations": 1,
                        "subprotocols": [get_random_stim_pulse()],
                    }
                ],
            },
        ],
        "protocol_assignments": {
            GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx): (
                # assign B to other protocols to make sure McComm can handle multiple protocols
                "A"
                if well_idx == test_well_idx
                else "B"
            )
            for well_idx in range(24)
        },
    }
    set_stimulation_protocols(four_board_mc_comm_process_no_handshake, simulator, test_stim_info)

    test_duration_us = get_subprotocol_dur_us(test_subprotocol)
    # mock so status update will be sent each iteration
    mocked_us_since_subprotocol_start = mocker.patch.object(
        mc_simulator, "_get_us_since_subprotocol_start", autospec=True, return_value=test_duration_us
    )
    # mock so no barcode sent
    mocker.patch.object(simulator, "_handle_barcode", autospec=True)

    # send start stimulation command
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "stimulation", "command": "start_stimulation"}, input_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    # process command, send back response and both stim status packet
    invoke_process_run_and_check_errors(simulator)
    # process command response and both stim packets
    invoke_process_run_and_check_errors(mc_process, num_iterations=2)
    # remove message to main
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    # mock so just enough mag data is produced to get through initial buffering
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        return_value=MICRO_TO_BASE_CONVERSION * NUM_INITIAL_SECONDS_TO_DROP + DEFAULT_SAMPLING_PERIOD,
    )
    # mock so no mag data is actually sent to file_writer
    mocker.patch.object(mc_process, "_dump_mag_data_packet", autospec=True)
    # update this value so no stim statuses sent while starting data stream
    mocked_us_since_subprotocol_start.return_value = 0

    # start data streaming
    set_sampling_period_and_start_streaming(four_board_mc_comm_process_no_handshake, simulator)
    # confirm most recent packet sent to file writer
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    # stop data streaming
    stop_data_stream(four_board_mc_comm_process_no_handshake, simulator)

    # run simulator and make sure no packets are sent to file writer
    mocked_us_since_subprotocol_start.return_value = test_duration_us
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    assert simulator.in_waiting == 0
    confirm_queue_is_eventually_empty(to_fw_queue)

    # update this value so no stim statuses sent while starting data stream
    mocked_us_since_subprotocol_start.return_value = 0
    # restart data stream
    start_data_stream(four_board_mc_comm_process_no_handshake, simulator)
    # confirm most recent packet sent to file writer and marked as first stim packet of the stream
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    actual = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual["is_first_packet_of_stream"] is True
