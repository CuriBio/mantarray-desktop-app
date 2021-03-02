# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue
import random
from zlib import crc32

from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import NANOSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_REBOOT_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import UnrecognizedSerialCommModuleIdError
from mantarray_desktop_app import UnrecognizedSerialCommPacketTypeError
from mantarray_desktop_app import UnrecognizedSimulatorTestCommandError
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import pytest
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator
from .fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from .fixtures_mc_simulator import fixture_runnable_mantarray_mc_simulator
from .helpers import confirm_queue_is_eventually_empty
from .helpers import confirm_queue_is_eventually_of_size
from .helpers import handle_putting_multiple_objects_into_empty_queue
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_runnable_mantarray_mc_simulator,
]

STATUS_BEACON_SIZE_BYTES = 28
HANDSHAKE_RESPONSE_SIZE_BYTES = 28
DEFAULT_SIMULATOR_STATUS_CODE = bytes(4)


def test_create_data_packet__creates_data_packet_bytes_correctly():
    test_timestamp = 100
    test_module_id = 0
    test_packet_type = 1
    test_data = bytes([1, 5, 3])

    expected_data_packet_bytes = SERIAL_COMM_MAGIC_WORD_BYTES
    expected_data_packet_bytes += (17).to_bytes(2, byteorder="little")
    expected_data_packet_bytes += test_timestamp.to_bytes(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
    )
    expected_data_packet_bytes += bytes([test_module_id, test_packet_type])
    expected_data_packet_bytes += test_data
    expected_data_packet_bytes += crc32(expected_data_packet_bytes).to_bytes(
        SERIAL_COMM_CHECKSUM_LENGTH_BYTES, byteorder="little"
    )

    actual = create_data_packet(
        test_timestamp,
        test_module_id,
        test_packet_type,
        test_data,
    )
    assert actual == expected_data_packet_bytes


def test_MantarrayMcSimulator__super_is_called_during_init__with_default_logging_value(
    mocker,
):
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")

    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    testing_queue = Queue()
    MantarrayMcSimulator(input_queue, output_queue, error_queue, testing_queue)

    mocked_init.assert_called_once_with(
        error_queue,
        logging_level=logging.INFO,
    )


def test_MantarrayMcSimulator_hard_stop__clears_all_queues_and_returns_lists_of_values(
    mantarray_mc_simulator_no_beacon,
):
    (
        input_queue,
        output_queue,
        error_queue,
        testing_queue,
        simulator,
    ) = mantarray_mc_simulator_no_beacon.values()

    test_testing_queue_item_1 = {
        "command": "add_read_bytes",
        "read_bytes": b"first test bytes",
    }
    testing_queue.put_nowait(test_testing_queue_item_1)
    test_testing_queue_item_2 = {
        "command": "add_read_bytes",
        "read_bytes": b"second test bytes",
    }
    testing_queue.put_nowait(test_testing_queue_item_2)
    confirm_queue_is_eventually_of_size(testing_queue, 2)

    test_input_item = b"some more bytes"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_input_item, input_queue
    )

    test_output_item = b"some more bytes"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_output_item, output_queue
    )

    test_error_item = {"test_error": "an error"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_error_item, error_queue
    )

    actual = simulator.hard_stop()
    assert actual["fatal_error_reporter"] == [test_error_item]
    assert actual["input_queue"] == [test_input_item]
    assert actual["output_queue"] == [test_output_item]
    assert actual["testing_queue"] == [
        test_testing_queue_item_1,
        test_testing_queue_item_2,
    ]

    confirm_queue_is_eventually_empty(input_queue)
    confirm_queue_is_eventually_empty(output_queue)
    confirm_queue_is_eventually_empty(error_queue)
    confirm_queue_is_eventually_empty(testing_queue)


def test_MantarrayMcSimulator__correctly_stores_time_since_initialized__in_setup_before_loop(
    mocker,
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_init_time = 15796649135715
    expected_poll_time = 15880317595302
    mocker.patch.object(
        mc_simulator,
        "perf_counter_ns",
        autospec=True,
        side_effect=[expected_init_time, expected_poll_time],
    )

    # before setup
    assert simulator.get_cms_since_init() == 0

    invoke_process_run_and_check_errors(simulator, perform_setup_before_loop=True)
    # after setup
    expected_dur_since_init = (
        expected_poll_time - expected_init_time
    ) // NANOSECONDS_PER_CENTIMILLISECOND
    assert simulator.get_cms_since_init() == expected_dur_since_init


def test_MantarrayMcSimulator_read__gets_next_available_bytes(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    expected_bytes = b"expected_item"
    test_item = {"command": "add_read_bytes", "read_bytes": expected_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    actual_item = simulator.read(size=len(expected_bytes))
    assert actual_item == expected_bytes


def test_MantarrayMcSimulator_read__returns_empty_bytes_if_no_bytes_to_read(
    mantarray_mc_simulator,
):
    simulator = mantarray_mc_simulator["simulator"]
    actual_item = simulator.read(size=1)
    expected_item = bytes(0)
    assert actual_item == expected_item


def test_MantarrayMcSimulator_write__puts_object_into_input_queue__with_no_sleep_after_write(
    mocker,
):
    spied_sleep = mocker.spy(mc_simulator.time, "sleep")

    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    testing_queue = Queue()
    simulator = MantarrayMcSimulator(
        input_queue, output_queue, error_queue, testing_queue
    )

    test_item = b"input_item"
    simulator.write(test_item)
    confirm_queue_is_eventually_of_size(input_queue, 1)
    # Tanner (1/28/21): removing item from queue to avoid BrokenPipeError
    actual_item = input_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_item == test_item

    spied_sleep.assert_not_called()


def test_MantarrayMcSimulator__makes_status_beacon_available_to_read_on_first_iteration__with_random_truncation(
    mantarray_mc_simulator, mocker
):
    spied_randint = mocker.spy(random, "randint")

    simulator = mantarray_mc_simulator["simulator"]

    expected_cms_since_init = 0
    mocker.patch.object(
        simulator,
        "get_cms_since_init",
        autospec=True,
        return_value=expected_cms_since_init,
    )

    expected_initial_beacon = create_data_packet(
        expected_cms_since_init,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    expected_randint_upper_bound = len(expected_initial_beacon) - 1

    invoke_process_run_and_check_errors(simulator)
    spied_randint.assert_called_once_with(0, expected_randint_upper_bound)

    actual = simulator.read(
        size=len(expected_initial_beacon[spied_randint.spy_return :])
    )
    assert actual == expected_initial_beacon[spied_randint.spy_return :]


def test_MantarrayMcSimulator__makes_status_beacon_available_to_read_every_5_seconds__and_includes_correct_timestamp(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]

    expected_durs = [
        0,
        CENTIMILLISECONDS_PER_SECOND * SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS,
        CENTIMILLISECONDS_PER_SECOND * SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS * 2 + 1,
    ]
    mocker.patch.object(
        simulator, "get_cms_since_init", autospec=True, side_effect=expected_durs
    )
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_status_beacon",
        autospec=True,
        side_effect=[
            1,
            SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS,
            SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS - 1,
            SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS + 1,
        ],
    )

    # remove boot up beacon
    invoke_process_run_and_check_errors(simulator)
    simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    # 1 second since prev beacon
    invoke_process_run_and_check_errors(simulator)
    # 5 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    expected_beacon_1 = create_data_packet(
        expected_durs[1],
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    assert simulator.read(size=len(expected_beacon_1)) == expected_beacon_1
    # 4 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    # 6 seconds since prev beacon
    invoke_process_run_and_check_errors(simulator)
    expected_beacon_2 = create_data_packet(
        expected_durs[2],
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    assert simulator.read(size=len(expected_beacon_2)) == expected_beacon_2


def test_MantarrayMcSimulator__raises_error_if_unrecognized_test_command_is_received(
    mantarray_mc_simulator, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print the error message to console

    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]

    expected_command = "bad_command"
    test_item = {"command": expected_command}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
    with pytest.raises(UnrecognizedSimulatorTestCommandError, match=expected_command):
        invoke_process_run_and_check_errors(simulator)


def test_MantarrayMcSimulator__handles_reads_of_size_less_than_next_packet_in_queue__when_queue_is_not_empty(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_size_diff = 2
    item_1 = b"item_one"
    item_2 = b"second_item"

    test_items = [
        {"command": "add_read_bytes", "read_bytes": item_1},
        {"command": "add_read_bytes", "read_bytes": item_2},
    ]
    handle_putting_multiple_objects_into_empty_queue(test_items, testing_queue)
    invoke_process_run_and_check_errors(simulator, 2)
    confirm_queue_is_eventually_empty(testing_queue)

    expected_1 = item_1[:-test_size_diff]
    actual_1 = simulator.read(size=len(item_1) - test_size_diff)
    assert actual_1 == expected_1

    expected_2 = item_1[-test_size_diff:] + item_2[:-test_size_diff]
    actual_2 = simulator.read(size=len(item_2))
    assert actual_2 == expected_2

    expected_3 = item_2[-test_size_diff:]
    actual_3 = simulator.read(
        size=len(expected_3)
    )  # specifically want to read exactly the remaining number of bytes
    assert actual_3 == expected_3


def test_MantarrayMcSimulator__handles_reads_of_size_less_than_next_packet_in_queue__when_queue_is_empty(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_size_diff_1 = 3
    test_size_diff_2 = 1
    test_item = b"first_item"
    test_dict = {"command": "add_read_bytes", "read_bytes": test_item}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_dict, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    expected_1 = test_item[:-test_size_diff_1]
    actual_1 = simulator.read(size=len(test_item) - test_size_diff_1)
    assert actual_1 == expected_1

    expected_2 = test_item[-test_size_diff_1:-test_size_diff_2]
    actual_2 = simulator.read(size=test_size_diff_1 - test_size_diff_2)
    assert actual_2 == expected_2

    expected_3 = test_item[-1:]
    actual_3 = simulator.read()
    assert actual_3 == expected_3


@pytest.mark.slow
def test_MantarrayMcSimulator__handles_reads_of_size_less_than_next_packet_in_queue__when_simulator_is_running(
    runnable_mantarray_mc_simulator,
):
    simulator = runnable_mantarray_mc_simulator["simulator"]
    testing_queue = runnable_mantarray_mc_simulator["testing_queue"]

    # remove boot up beacon
    invoke_process_run_and_check_errors(simulator)
    simulator.read(size=STATUS_BEACON_SIZE_BYTES)

    test_item_1 = b"12345"
    test_item_2 = b"67890"
    test_items = [
        {"command": "add_read_bytes", "read_bytes": test_item_1},
        {"command": "add_read_bytes", "read_bytes": test_item_2},
    ]

    handle_putting_multiple_objects_into_empty_queue(test_items, testing_queue)
    simulator.start()
    confirm_queue_is_eventually_empty(  # Tanner (2/7/21): Using 5 second timeout here to give sufficient time to make sure testing_queue is emptied
        testing_queue, timeout_seconds=5
    )

    read_len_1 = 3
    read_1 = simulator.read(size=read_len_1)
    assert read_1 == test_item_1[:read_len_1]
    # read remaining bytes
    read_len_2 = len(test_item_1) + len(test_item_2) - read_len_1
    read_2 = simulator.read(size=read_len_2)
    assert read_2 == test_item_1[read_len_1:] + test_item_2


def test_MantarrayMcSimulator__handles_reads_of_size_greater_than_next_packet_in_queue__when_queue_is_not_empty(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_size_diff = 2
    item_1 = b"item_one"
    item_2 = b"second_item"

    test_items = [
        {"command": "add_read_bytes", "read_bytes": item_1},
        {"command": "add_read_bytes", "read_bytes": item_2},
    ]
    handle_putting_multiple_objects_into_empty_queue(test_items, testing_queue)
    invoke_process_run_and_check_errors(simulator, 2)
    confirm_queue_is_eventually_empty(testing_queue)

    expected_1 = item_1 + item_2[:test_size_diff]
    actual_1 = simulator.read(size=len(item_1) + test_size_diff)
    assert actual_1 == expected_1

    expected_2 = item_2[test_size_diff:]
    actual_2 = simulator.read(size=len(expected_2) + 1)
    assert actual_2 == expected_2

    expected_3 = bytes(0)
    actual_3 = simulator.read(size=1)
    assert actual_3 == expected_3


def test_MantarrayMcSimulator__handles_reads_of_size_greater_than_next_packet_in_queue__when_queue_is_empty(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_item = b"the_item"
    test_dict = {"command": "add_read_bytes", "read_bytes": test_item}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_dict, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    expected_1 = test_item
    actual_1 = simulator.read(size=len(test_item) + 1)
    assert actual_1 == expected_1

    actual_2 = simulator.read(size=1)
    assert actual_2 == bytes(0)


def test_MantarrayMcSimulator__raises_error_if_unrecognized_module_id_sent_from_pc(
    mantarray_mc_simulator_no_beacon, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    dummy_timestamp = 0
    dummy_packet_type = 1
    test_module_id = 254
    test_handshake = create_data_packet(
        dummy_timestamp,
        test_module_id,
        dummy_packet_type,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )

    simulator.write(test_handshake)

    with pytest.raises(UnrecognizedSerialCommModuleIdError, match=str(test_module_id)):
        invoke_process_run_and_check_errors(simulator)


def test_MantarrayMcSimulator__raises_error_if_unrecognized_packet_type_sent_from_pc(
    mantarray_mc_simulator_no_beacon, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    dummy_timestamp = 0
    test_packet_type = 254
    test_handshake = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        test_packet_type,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )

    simulator.write(test_handshake)

    with pytest.raises(UnrecognizedSerialCommPacketTypeError) as exc_info:
        invoke_process_run_and_check_errors(simulator)
    assert str(SERIAL_COMM_MAIN_MODULE_ID) in str(exc_info.value)
    assert str(test_packet_type) in str(exc_info.value)


def test_MantarrayMcSimulator__responds_to_handshake__when_checksum_is_correct(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_get_cms_since_init = mocker.spy(simulator, "get_cms_since_init")

    dummy_timestamp = 0
    test_handshake = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
        bytes(0),
    )

    simulator.write(test_handshake)

    invoke_process_run_and_check_errors(simulator)
    actual = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)

    expected_handshake_response = create_data_packet(
        spied_get_cms_since_init.spy_return,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )
    assert actual == expected_handshake_response


def test_MantarrayMcSimulator__responds_to_handshake__when_checksum_is_incorrect(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_get_cms_since_init = mocker.spy(simulator, "get_cms_since_init")

    dummy_timestamp_bytes = bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    dummy_checksum_bytes = bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES)
    handshake_packet_length = 14
    test_handshake = (
        SERIAL_COMM_MAGIC_WORD_BYTES
        + handshake_packet_length.to_bytes(2, byteorder="little")
        + dummy_timestamp_bytes
        + bytes([SERIAL_COMM_MAIN_MODULE_ID])
        + bytes([SERIAL_COMM_HANDSHAKE_PACKET_TYPE])
        + dummy_checksum_bytes
    )
    simulator.write(test_handshake)

    invoke_process_run_and_check_errors(simulator)

    expected_handshake_response = create_data_packet(
        spied_get_cms_since_init.spy_return,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE,
        test_handshake[len(SERIAL_COMM_MAGIC_WORD_BYTES) :],
    )
    actual = simulator.read(size=len(expected_handshake_response))
    assert actual == expected_handshake_response


def test_MantarrayMcSimulator__allows_status_bits_to_be_set_through_testing_queue_commands(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    expected_status_code_bits = bytes([4, 13, 7, 0])
    test_command = {
        "command": "set_status_code_bits",
        "status_code_bits": expected_status_code_bits,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    dummy_timestamp = 0
    test_handshake = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
        bytes(0),
    )

    simulator.write(test_handshake)

    invoke_process_run_and_check_errors(simulator)
    handshake_response = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)

    status_code_end = len(handshake_response) - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
    status_code_start = status_code_end - len(expected_status_code_bits)
    actual_status_code_bits = handshake_response[status_code_start:status_code_end]
    assert actual_status_code_bits == expected_status_code_bits


def test_MantarrayMcSimulator__discards_commands_from_pc_during_reboot_period__and_sends_reboot_response_packet_when_finished(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_get_cms_since_init = mocker.spy(simulator, "get_cms_since_init")

    reboot_duration = 5
    reboot_times = [4, reboot_duration]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        side_effect=reboot_times,
    )

    spied_reset = mocker.spy(simulator, "_reset_start_time")

    dummy_timestamp = 0
    test_reboot_command = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_REBOOT_PACKET_TYPE,
        bytes(0),
    )
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)

    # TODO Tanner (3/2/21): figure out if real mantarray would ever process this comm

    # test that handshake is ignored
    test_handshake = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
        bytes(0),
    )
    simulator.write(test_handshake)
    invoke_process_run_and_check_errors(simulator)
    response_during_reboot = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)
    assert len(response_during_reboot) == 0

    # test that reboot response packet is sent
    invoke_process_run_and_check_errors(simulator)
    expected_reboot_response = create_data_packet(
        spied_get_cms_since_init.spy_return,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_REBOOT_PACKET_TYPE,
        bytes(0),
    )
    response_after_reboot = simulator.read(size=len(expected_reboot_response))
    assert response_after_reboot == expected_reboot_response

    # test that start time was reset
    spied_reset.assert_called_once()


def test_MantarrayMcSimulator__reset_status_code_after_rebooting(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    reboot_duration = 5
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        return_value=reboot_duration,
    )

    # set status code to known value
    expected_status_code_bits = bytes([1, 7, 3, 8])
    test_command = {
        "command": "set_status_code_bits",
        "status_code_bits": expected_status_code_bits,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # send reboot command
    dummy_timestamp = 0
    test_reboot_command = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_REBOOT_PACKET_TYPE,
        bytes(0),
    )
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)

    # remove reboot response packet
    invoke_process_run_and_check_errors(simulator)
    expected_reboot_response = create_data_packet(
        0,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_REBOOT_PACKET_TYPE,
        bytes(0),
    )
    simulator.read(size=len(expected_reboot_response))

    test_handshake = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
        bytes(0),
    )
    simulator.write(test_handshake)
    invoke_process_run_and_check_errors(simulator)
    handshake_response = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)
    assert len(handshake_response) == HANDSHAKE_RESPONSE_SIZE_BYTES
    assert handshake_response[-8:-4] == DEFAULT_SIMULATOR_STATUS_CODE
