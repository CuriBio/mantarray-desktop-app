# -*- coding: utf-8 -*-
import copy
import datetime
import logging
from random import randint

from freezegun import freeze_time
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import DEFAULT_SAMPLING_PERIOD
from mantarray_desktop_app import InstrumentDataStreamingAlreadyStartedError
from mantarray_desktop_app import InstrumentDataStreamingAlreadyStoppedError
from mantarray_desktop_app import SamplingPeriodUpdateWhileDataStreamingError
from mantarray_desktop_app import SERIAL_COMM_MODULE_ID_TO_WELL_IDX
from mantarray_desktop_app import SERIAL_COMM_NUM_DATA_CHANNELS
from mantarray_desktop_app import SERIAL_COMM_NUM_SENSORS_PER_WELL
from mantarray_desktop_app import SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app.constants import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app.constants import NUM_INITIAL_SECONDS_TO_DROP
from mantarray_desktop_app.constants import PERFOMANCE_LOGGING_PERIOD_SECS
from mantarray_desktop_app.constants import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app.constants import SERIAL_COMM_NUM_CHANNELS_PER_SENSOR
from mantarray_desktop_app.constants import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app.constants import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.simulators import mc_simulator
from mantarray_desktop_app.sub_processes import mc_comm
from mantarray_desktop_app.sub_processes.mc_comm import MetadataStatuses
import numpy as np
import pytest
import serial
from stdlib_utils import create_metrics_stats
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_comm import set_sampling_period_and_start_streaming
from ..fixtures_mc_comm import start_data_stream
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import random_timestamp
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_patch_print,
    fixture_four_board_mc_comm_process_no_handshake,
]

TEST_OTHER_TIMESTAMP = random_timestamp()  # type: ignore
TEST_OTHER_PACKET_INFO = (
    TEST_OTHER_TIMESTAMP,
    SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
    bytes(SERIAL_COMM_STATUS_CODE_LENGTH_BYTES),
)
TEST_OTHER_PACKET = create_data_packet(*TEST_OTHER_PACKET_INFO)


@freeze_time(datetime.datetime(year=2021, month=10, day=24, hour=13, minute=5, second=23, microsecond=173814))
def test_McCommunicationProcess__processes_start_managed_acquisition_command__when_data_not_already_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # set arbitrary sampling period
    expected_sampling_period = 60000
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_sampling_period", "sampling_period": expected_sampling_period}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    expected_response = dict(START_MANAGED_ACQUISITION_COMMUNICATION)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_response, from_main_queue)
    # run mc_process one iteration to send start command
    invoke_process_run_and_check_errors(mc_process)
    # run mc_simulator once to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # run mc_process one more iteration to process command response and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    expected_response["timestamp"] = datetime.datetime(
        year=2021, month=10, day=24, hour=13, minute=5, second=23, microsecond=173814
    )
    assert command_response == expected_response


def test_McCommunicationProcess__raises_error_when_set_sampling_period_command_received_while_data_is_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_sampling_period", "sampling_period": 5000}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # start data streaming
    start_command = dict(START_MANAGED_ACQUISITION_COMMUNICATION)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(start_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # attempt to change magnetometer configuration and assert error is raised
    change_config_command = {
        "communication_type": "acquisition_manager",
        "command": "set_sampling_period",
        "sampling_period": 65000,  # arbitrary value
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(change_config_command, from_main_queue)
    with pytest.raises(SamplingPeriodUpdateWhileDataStreamingError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__processes_start_managed_acquisition_command__and_raises_error_when_already_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # put simulator in data streaming mode
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_data_streaming_status", "data_streaming_status": True}, testing_queue
    )

    expected_response = dict(START_MANAGED_ACQUISITION_COMMUNICATION)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_response, from_main_queue)
    # run mc_process one iteration to send start command
    invoke_process_run_and_check_errors(mc_process)
    # run mc_simulator once to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # run mc_process to check command response and raise error
    with pytest.raises(InstrumentDataStreamingAlreadyStartedError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__processes_stop_data_streaming_command__when_data_is_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue, to_main_queue, _ = four_board_mc_comm_process_no_handshake["board_queues"][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # mocking so no barcode messages are sent from mc_comm to main
    mocker.patch.object(simulator, "_handle_barcode", autospec=True)

    # put simulator in data streaming mode
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_data_streaming_status", "data_streaming_status": True}, testing_queue
    )

    expected_response = {"communication_type": "acquisition_manager", "command": "stop_managed_acquisition"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_response), from_main_queue
    )
    # run mc_process one iteration to send start command
    invoke_process_run_and_check_errors(mc_process)
    # run mc_simulator once to process command and send response
    invoke_process_run_and_check_errors(simulator)
    # run mc_process one more iteration to process command response and send message back to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == expected_response


def test_McCommunicationProcess__processes_stop_data_streaming_command__and_raises_error_when_not_streaming(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    stop_command = {"communication_type": "acquisition_manager", "command": "stop_managed_acquisition"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(stop_command, from_main_queue)
    # run mc_process one iteration to send start command
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # run mc_process to check command response and raise error
    with pytest.raises(InstrumentDataStreamingAlreadyStoppedError):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__reads_all_bytes_from_instrument__and_does_not_sort_packets_if_not_at_least_one_full_packet_is_present(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_sampling_period_us = 25000  # arbitrary value
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )

    # mocking in order to produce incomplete data packet
    mocker.patch.object(
        mc_simulator,
        "create_data_packet",
        autospec=True,
        return_value=bytes(SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES - 1),
    )

    spied_sort = mocker.spy(mc_comm, "sort_serial_packets")
    spied_read_all = mocker.spy(simulator, "read_all")

    # send data
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES - 1
    # read data
    invoke_process_run_and_check_errors(mc_process)

    spied_read_all.assert_called_once()
    spied_sort.assert_not_called()
    confirm_queue_is_eventually_empty(to_fw_queue)


def test_McCommunicationProcess__tries_to_read_one_more_time_if_first_read_fails(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_sampling_period_us = 25000  # arbitrary value
    # mocking to ensure only one data packet is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )

    expected_error = serial.SerialException("test msg")

    mocked_read_all = mocker.patch.object(
        simulator, "read_all", autospec=True, side_effect=[expected_error, bytes()]
    )

    # send and read data
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    assert mocked_read_all.call_count == 2

    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    assert (
        to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)["message"]
        == f"Serial data read failed: {expected_error}. Trying one more time"
    )


def test_McCommunicationProcess__processes_non_stream_packet_immediately(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_sampling_period_us = 25000  # arbitrary value

    # mocking to ensure no mag data packets are sent
    mocker.patch.object(mc_simulator, "_get_us_since_last_data_packet", autospec=True, return_value=0)

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )

    spied_sort = mocker.spy(mc_comm, "sort_serial_packets")
    spied_read_all = mocker.spy(simulator, "read_all")

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )

    # send beacon
    invoke_process_run_and_check_errors(simulator)
    # read and process beacon. Set logging level to debug so that the beacon msg is sent to main
    mc_process._logging_level = logging.DEBUG
    invoke_process_run_and_check_errors(mc_process)

    spied_read_all.assert_called_once()
    spied_sort.assert_called_once()

    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    beacon_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert "status beacon" in beacon_msg["message"].lower()


def test_McCommunicationProcess__correctly_indicates_which_packet_is_the_first_of_the_stream(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_sampling_period_us = DEFAULT_SAMPLING_PERIOD
    test_num_packets_per_second = MICRO_TO_BASE_CONVERSION // test_sampling_period_us
    # mocking to ensure one second of data is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[
            0,
            test_sampling_period_us * test_num_packets_per_second * (NUM_INITIAL_SECONDS_TO_DROP + 1),
            test_sampling_period_us * test_num_packets_per_second,
        ],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )
    mc_process._discarding_beginning_of_data_stream = False

    for read_num in range(2):
        invoke_process_run_and_check_errors(simulator)
        invoke_process_run_and_check_errors(mc_process)
        confirm_queue_is_eventually_of_size(to_fw_queue, 1)
        actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert actual_fw_item["is_first_packet_of_stream"] is not bool(read_num)


def test_McCommunicationProcess__does_not_parse_data_packets_before_one_second_of_data_is_present__all_channels_enabled(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_parse = mocker.spy(mc_comm, "parse_magnetometer_data")

    test_num_packets = 99
    test_sampling_period_us = DEFAULT_SAMPLING_PERIOD
    # mocking to ensure one packet short of one second of data is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us * test_num_packets],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    start_data_stream(four_board_mc_comm_process_no_handshake, simulator)

    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    spied_parse.assert_not_called()
    confirm_queue_is_eventually_empty(to_fw_queue)


def test_McCommunicationProcess__handles_read_of_only_data_packets__and_sends_data_to_file_writer_correctly__when_at_least_one_second_of_data_with_all_channels_enabled_is_present(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_sampling_period_us = DEFAULT_SAMPLING_PERIOD
    test_num_packets = (
        int((NUM_INITIAL_SECONDS_TO_DROP + 1) * MICRO_TO_BASE_CONVERSION) // test_sampling_period_us
    ) + 1
    expected_num_packets = MICRO_TO_BASE_CONVERSION // DEFAULT_SAMPLING_PERIOD
    # mocking to ensure one second of data is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[
            0,
            test_sampling_period_us * (test_num_packets - expected_num_packets),
            test_sampling_period_us * expected_num_packets,
        ],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    start_data_stream(four_board_mc_comm_process_no_handshake, simulator)

    min_time_idx_us = test_sampling_period_us
    max_time_idx_us = test_sampling_period_us * (expected_num_packets + 1)
    expected_time_indices = np.arange(
        min_time_idx_us, max_time_idx_us, test_sampling_period_us, dtype=np.uint64
    )

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)
    expected_data = np.hstack([simulated_data[1:], simulated_data[:1]])
    expected_fw_item = {"data_type": "mangetometer", "time_indices": expected_time_indices}
    for well_idx in range(mc_process._num_wells):
        channel_dict = {
            "time_offsets": np.zeros(
                (SERIAL_COMM_NUM_SENSORS_PER_WELL, expected_num_packets), dtype=np.uint16
            )
        }
        for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
            channel_dict[channel_id] = expected_data * np.uint16(well_idx + 1)
        expected_fw_item[well_idx] = channel_dict
    # not actually using the value here in any assertions, just need the key present
    expected_fw_item["is_first_packet_of_stream"] = None

    # process discared packets
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_empty(to_fw_queue)
    # process retained packets
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_fw_item.keys() == expected_fw_item.keys()
    np.testing.assert_array_equal(actual_fw_item["time_indices"], expected_fw_item["time_indices"])
    for key, expected_item in expected_fw_item.items():
        if key in ("data_type", "is_first_packet_of_stream", "time_indices"):
            continue
        actual_item = actual_fw_item[key]
        assert actual_item.keys() == expected_item.keys()
        for sub_key, expected_data in expected_item.items():
            actual_data = actual_item[sub_key]
            assert actual_data.dtype == np.uint16
            np.testing.assert_array_equal(
                actual_data, expected_data, err_msg=f"Failure at key '{key}', sub key '{sub_key}'"
            )


def test_McCommunicationProcess__handles_read_of_only_data_packets__and_sends_data_to_file_writer_correctly__when_one_second_of_data_is_present(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    test_sampling_period_us = 10000  # specifically chosen so that there are 100 data packets in one second
    test_num_packets_to_drop = (
        NUM_INITIAL_SECONDS_TO_DROP * MICRO_TO_BASE_CONVERSION
    ) // test_sampling_period_us + 1
    expected_num_packets = int(MICRO_TO_BASE_CONVERSION // test_sampling_period_us)
    # mocking to ensure one second of data is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[
            0,
            test_sampling_period_us * test_num_packets_to_drop // 2,
            test_sampling_period_us * (test_num_packets_to_drop // 2 + 1),
            test_sampling_period_us * expected_num_packets,
        ],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )

    min_time_idx_us = test_sampling_period_us
    max_time_idx_us = test_sampling_period_us * (expected_num_packets + 1)
    expected_time_indices = np.arange(
        min_time_idx_us, max_time_idx_us, test_sampling_period_us, dtype=np.uint64
    )

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)
    expected_data = np.hstack([simulated_data[1:], simulated_data[:1]])
    expected_fw_item = {
        "data_type": "mangetometer",
        "time_indices": np.array(expected_time_indices, np.uint64),
    }
    for well_idx in range(24):
        channel_dict = {
            "time_offsets": np.zeros(
                (SERIAL_COMM_NUM_SENSORS_PER_WELL, expected_num_packets), dtype=np.uint16
            )
        }
        for channel_id in range(SERIAL_COMM_NUM_DATA_CHANNELS):
            channel_dict[channel_id] = expected_data * np.uint16(well_idx + 1)
        expected_fw_item[well_idx] = channel_dict
    # not actually using the value here in any assertions, just need the key present
    expected_fw_item["is_first_packet_of_stream"] = None

    # process discared packets
    for _ in range(2):
        invoke_process_run_and_check_errors(simulator)
        invoke_process_run_and_check_errors(mc_process)
        confirm_queue_is_eventually_empty(to_fw_queue)
    # process retained packets
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_fw_item.keys() == expected_fw_item.keys()
    np.testing.assert_array_equal(actual_fw_item["time_indices"], expected_fw_item["time_indices"])
    for key, expected_item in expected_fw_item.items():
        if key in ("data_type", "is_first_packet_of_stream", "time_indices"):
            continue
        actual_item = actual_fw_item[key]
        assert actual_item.keys() == expected_item.keys()
        for sub_key, expected_data in expected_item.items():
            actual_data = actual_item[sub_key]
            np.testing.assert_array_equal(
                actual_data, expected_data, err_msg=f"Failure at '{key}' key, sub key '{sub_key}'"
            )


def test_McCommunicationProcess__handles_one_second_read_with_two_interrupting_packets_correctly(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    _, to_main_queue, to_fw_queue = four_board_mc_comm_process_no_handshake["board_queues"][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_sampling_period_us = 10000  # specifically chosen so that there are 100 data packets in one second
    expected_num_packets = int(MICRO_TO_BASE_CONVERSION * 1.5 // test_sampling_period_us)
    # mocking to ensure one second of data is sent
    mocker.patch.object(
        mc_simulator,
        "_get_us_since_last_data_packet",
        autospec=True,
        side_effect=[0, test_sampling_period_us * expected_num_packets, 0],
    )

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(
        four_board_mc_comm_process_no_handshake, simulator, sampling_period=test_sampling_period_us
    )
    mc_process._discarding_beginning_of_data_stream = False

    min_time_idx_us = 0
    max_time_idx_us = test_sampling_period_us * expected_num_packets
    expected_time_indices = list(range(min_time_idx_us, max_time_idx_us, test_sampling_period_us))

    simulated_data = simulator.get_interpolated_data(test_sampling_period_us)
    expected_sensor_axis_id = 0
    expected_fw_item = {
        "data_type": "mangetometer",
        "time_indices": np.array(expected_time_indices, np.uint64),
    }
    for module_id in range(24):
        well_idx = SERIAL_COMM_MODULE_ID_TO_WELL_IDX[module_id]
        channel_data = np.concatenate((simulated_data, simulated_data[: expected_num_packets // 3]))
        channel_dict = {
            "time_offsets": np.zeros(
                (SERIAL_COMM_NUM_SENSORS_PER_WELL, expected_num_packets), dtype=np.uint16
            ),
            expected_sensor_axis_id: channel_data * np.uint16(well_idx + 1),
        }
        expected_fw_item[well_idx] = channel_dict
    # not actually using the value here in any assertions, just need the key present
    expected_fw_item["is_first_packet_of_stream"] = None

    # insert one status beacon at beginning of data and on after 1/3 of data
    invoke_process_run_and_check_errors(simulator)
    read_bytes = simulator.read_all()
    read_bytes = (
        TEST_OTHER_PACKET
        + read_bytes[: len(read_bytes) // 3]
        + TEST_OTHER_PACKET
        + read_bytes[len(read_bytes) // 3 :]
    )
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": read_bytes}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # set logging level to debug so that beacon log message is sent to main
    mc_process._logging_level = logging.DEBUG

    # parse all data and make sure outgoing queues are populated
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 2)
    confirm_queue_is_eventually_of_size(to_fw_queue, 1)
    # test message to main from interrupting packets
    for beacon_num in range(2):
        actual_beacon_log_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        expected_status_code = int.from_bytes(TEST_OTHER_PACKET_INFO[-1], byteorder="little")
        assert str(expected_status_code) in actual_beacon_log_msg["message"], beacon_num
    # test data packets going to file_writer
    actual_fw_item = to_fw_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_fw_item.keys() == expected_fw_item.keys()

    np.testing.assert_array_equal(actual_fw_item["time_indices"], expected_fw_item["time_indices"])

    for key, expected_item in expected_fw_item.items():
        if key in ("data_type", "is_first_packet_of_stream", "time_indices"):
            continue
        actual_time_offsets = actual_fw_item[key]["time_offsets"]
        actual_data = actual_fw_item[key][expected_sensor_axis_id]
        np.testing.assert_array_equal(
            actual_time_offsets, expected_item["time_offsets"], err_msg=f"Failure at '{key}' key"
        )
        np.testing.assert_array_equal(
            actual_data, expected_item[expected_sensor_axis_id], err_msg=f"Failure at at '{key}' key"
        )


def test_McCommunicationProcess__handles_incomplete_read_of_packet_immediately_following_end_of_data_stream(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue, to_main_queue, _ = four_board_mc_comm_process_no_handshake["board_queues"][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    # mocking so no barcode messages are sent from mc_comm to main
    mocker.patch.object(simulator, "_handle_barcode", autospec=True)
    # mocking to ensure no data packets are sent
    mocker.patch.object(mc_simulator, "_get_us_since_last_data_packet", autospec=True, return_value=0)

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_sampling_period_and_start_streaming(four_board_mc_comm_process_no_handshake, simulator)

    # immediately stop data stream
    stop_command = {"communication_type": "acquisition_manager", "command": "stop_managed_acquisition"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(stop_command), from_main_queue
    )
    invoke_process_run_and_check_errors(mc_process)

    # arbitrarily choosing to slice the next packet at the end of the magic word
    slice_idx = len(SERIAL_COMM_MAGIC_WORD_BYTES)

    # have next read contain full stop data stream command response and part of another packet
    invoke_process_run_and_check_errors(simulator)
    read_bytes = simulator.read_all()
    read_bytes = read_bytes + TEST_OTHER_PACKET[:slice_idx]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": read_bytes}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # handle stop data stream command response
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    assert to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS) == stop_command

    # add remainder of the partially read packet
    read_bytes = TEST_OTHER_PACKET[slice_idx:]
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": read_bytes}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # set logging level to debug so that beacon log message is sent to main
    mc_process._logging_level = logging.DEBUG

    # make next packet is handled correctly
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    assert "status codes" in to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)["message"].lower()


def test_McCommunicationProcess__updates_performance_metrics_after_parsing_data(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # set logging level to debug so performance metrics and created and sent to main
    mc_process._logging_level = logging.DEBUG

    # confirm precondition
    assert mc_process._iterations_per_logging_cycle == int(
        PERFOMANCE_LOGGING_PERIOD_SECS / mc_process._minimum_iteration_duration_seconds
    )

    test_num_iterations = PERFOMANCE_LOGGING_PERIOD_SECS

    # set this value to a smaller number to make testing easier
    mc_process._iterations_per_logging_cycle = test_num_iterations

    # mock since connection to simulator will be made by this test
    mocker.patch.object(mc_process, "create_connections_to_all_available_boards", autospec=True)
    # perform setup so performance logging values are initialized
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    # don't automatically get metadata
    mc_process._metadata_status = MetadataStatuses.SKIP

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    start_data_stream(four_board_mc_comm_process_no_handshake, simulator)

    # call this method so there are percent use metrics to report
    mc_process.reset_performance_tracker()
    # set this to 0 to speed up the test
    mc_process._minimum_iteration_duration_seconds = 0
    # mock to speed up test and not send any data to file writer
    mocker.patch.object(mc_process, "_dump_mag_data_packet", autospec=True)
    # mock so mag packet is parsed each iteration
    mocker.patch.object(
        mc_comm.McCommunicationProcess,
        "_num_mag_packets_per_second",
        new_callable=mocker.PropertyMock,
        return_value=0,
    )
    mocker.patch.object(mc_comm, "SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES", 0)

    # create expected values for metric creation
    expected_secs_between_reading = [randint(1, 50) for _ in range(test_num_iterations - 1)]
    expected_secs_between_reading = list(range(test_num_iterations - 1))
    mocked_since_last_read = mocker.patch.object(
        mc_comm, "_get_secs_since_last_data_read", autospec=True, side_effect=expected_secs_between_reading
    )
    expected_read_durs = [randint(1, 50) for _ in range(test_num_iterations)]
    mocked_data_read_dur = mocker.patch.object(
        mc_comm, "_get_dur_of_data_read_secs", autospec=True, side_effect=expected_read_durs
    )
    expected_read_lengths = [randint(1, 50) for _ in range(test_num_iterations)]
    mocker.patch.object(
        simulator,
        "read_all",
        autospec=True,
        side_effect=[bytes(read_len) for read_len in expected_read_lengths],
    )

    expected_secs_between_sorting = [randint(1, 50) for _ in range(test_num_iterations - 1)]
    mocked_since_last_sort = mocker.patch.object(
        mc_comm, "_get_secs_since_last_data_sort", autospec=True, side_effect=expected_secs_between_sorting
    )
    expected_sort_durs = [randint(1, 50) for _ in range(test_num_iterations)]
    mocked_packet_sort_dur = mocker.patch.object(
        mc_comm, "_get_dur_of_data_sort_secs", autospec=True, side_effect=expected_sort_durs
    )
    expected_num_packets_sorted = [randint(1, 50) for _ in range(test_num_iterations)]
    mocker.patch.object(
        mc_comm,
        "sort_serial_packets",
        autospec=True,
        side_effect=[
            {
                "num_packets_sorted": num_packets,
                "magnetometer_stream_info": {"raw_bytes": bytearray(0), "num_packets": num_packets},
                "stim_stream_info": {"raw_bytes": bytearray(0), "num_packets": 0},
                "other_packet_info": [],
                "unread_bytes": bytearray(0),
            }
            for num_packets in expected_num_packets_sorted
        ],
    )

    expected_secs_between_parsing = [randint(1, 50) for _ in range(test_num_iterations - 1)]
    mocked_since_last_parse = mocker.patch.object(
        mc_comm,
        "_get_secs_since_last_mag_data_parse",
        autospec=True,
        side_effect=expected_secs_between_parsing,
    )
    expected_parse_durs = [randint(1, 50) for _ in range(test_num_iterations)]
    mocked_parse_dur = mocker.patch.object(
        mc_comm, "_get_dur_of_mag_data_parse_secs", autospec=True, side_effect=expected_parse_durs
    )
    expected_num_packets_parsed = [randint(1, 50) for _ in range(test_num_iterations)]
    mocker.patch.object(
        mc_comm,
        "parse_magnetometer_data",
        autospec=True,
        side_effect=[
            {
                "time_indices": np.empty((num_packets,)),
                "time_offsets": np.empty((SERIAL_COMM_NUM_CHANNELS_PER_SENSOR, num_packets)),
                "data": np.empty((mc_process._num_wells * SERIAL_COMM_NUM_DATA_CHANNELS, num_packets)),
            }
            for num_packets in expected_num_packets_parsed
        ],
    )

    # reset before creating metrics
    mc_process._reset_timepoints_of_prev_actions()
    mc_process._reset_performance_tracking_values()

    # run mc_process to create metrics
    invoke_process_run_and_check_errors(mc_process, num_iterations=PERFOMANCE_LOGGING_PERIOD_SECS)
    # check that related metrics use same timepoints
    assert mocked_since_last_read.call_args_list == mocked_data_read_dur.call_args_list[:-1]
    assert mocked_since_last_sort.call_args_list == mocked_packet_sort_dur.call_args_list[:-1]
    assert mocked_since_last_parse.call_args_list == mocked_parse_dur.call_args_list[:-1]
    # check actual metric values
    actual = drain_queue(to_main_queue)[-1]["message"]
    assert actual["communication_type"] == "performance_metrics"
    for name, mc_measurements in (
        ("period_between_reading", expected_secs_between_reading),
        ("data_read_duration", expected_read_durs),
        ("num_bytes_read", expected_read_lengths),
        ("period_between_sorting", expected_secs_between_sorting),
        ("sorting_duration", expected_sort_durs),
        ("num_packets_sorted", expected_num_packets_sorted),
        ("period_between_mag_data_parsing", expected_secs_between_parsing),
        ("mag_data_parsing_duration", expected_parse_durs),
        ("num_mag_packets_parsed", expected_num_packets_parsed),
    ):
        assert actual[name] == {"n": len(mc_measurements)} | create_metrics_stats(mc_measurements), name

    # values created in parent class
    assert "idle_iteration_time_ns" not in actual
    assert "start_timepoint_of_measurements" not in actual

    assert "percent_use" in actual
    assert "percent_use_metrics" in actual
    assert "longest_iterations" in actual
    assert "sleep_durations" in actual
    assert "periods_between_iterations" in actual


def test_McCommunicationProcess__does_not_include_data_streaming_performance_metrics_in_first_logging_cycle(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][1]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # set logging level to debug so performance metrics and created and sent to main
    mc_process._logging_level = logging.DEBUG

    # mock since connection to simulator will be made by this test
    mocker.patch.object(mc_process, "create_connections_to_all_available_boards", autospec=True)
    # perform setup so performance logging values are initialized
    invoke_process_run_and_check_errors(mc_process, perform_setup_before_loop=True)
    # don't automatically get metadata
    mc_process._metadata_status = MetadataStatuses.SKIP

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    start_data_stream(four_board_mc_comm_process_no_handshake, simulator)

    # mock these to speed up test
    mc_process._minimum_iteration_duration_seconds = 0
    # mock so no data is parsed
    mocker.patch.object(simulator, "read_all", autospec=True, return_value=bytes(0))

    # run mc_process to create metrics
    invoke_process_run_and_check_errors(mc_process, num_iterations=mc_process._iterations_per_logging_cycle)

    actual = drain_queue(to_main_queue)[-1]["message"]
    assert actual["communication_type"] == "performance_metrics"
    assert "percent_use_metrics" not in actual
