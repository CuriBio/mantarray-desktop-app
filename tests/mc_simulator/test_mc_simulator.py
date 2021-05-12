# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue
from random import randint

from mantarray_desktop_app import convert_to_metadata_bytes
from mantarray_desktop_app import convert_to_status_code_bytes
from mantarray_desktop_app import convert_to_timestamp_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import create_magnetometer_config_bytes
from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_IDLE_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_PLATE_EVENT_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_REBOOT_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SET_TIME_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_TIME_SYNC_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SerialCommInvalidSamplingPeriodError
from mantarray_desktop_app import UnrecognizedSimulatorTestCommandError
from mantarray_desktop_app.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
from mantarray_file_manager import BOOTUP_COUNTER_UUID
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_file_manager import PCB_SERIAL_NUMBER_UUID
from mantarray_file_manager import TAMPER_FLAG_UUID
from mantarray_file_manager import TOTAL_WORKING_HOURS_UUID
import pytest
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_simulator import DEFAULT_SIMULATOR_STATUS_CODE
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import fixture_runnable_mantarray_mc_simulator
from ..fixtures_mc_simulator import HANDSHAKE_RESPONSE_SIZE_BYTES
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..fixtures_mc_simulator import STATUS_BEACON_SIZE_BYTES
from ..fixtures_mc_simulator import TEST_HANDSHAKE
from ..helpers import assert_serial_packet_is_expected
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import get_full_packet_size_from_packet_body_size
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_runnable_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_MantarrayMcSimulator__class_attributes():
    assert MantarrayMcSimulator.default_mantarray_nickname == "Mantarray Simulator (MCU)"
    assert MantarrayMcSimulator.default_mantarray_serial_number == "M02001901"
    assert MantarrayMcSimulator.default_pcb_serial_number == "TBD"
    assert MantarrayMcSimulator.default_firmware_version == "0.0.0"
    assert MantarrayMcSimulator.default_barcode == "MA190190001"
    assert MantarrayMcSimulator.default_metadata_values == {
        BOOTUP_COUNTER_UUID: 0,
        TOTAL_WORKING_HOURS_UUID: 0,
        TAMPER_FLAG_UUID: 0,
        MANTARRAY_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_mantarray_serial_number,
        MANTARRAY_NICKNAME_UUID: MantarrayMcSimulator.default_mantarray_nickname,
        PCB_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_pcb_serial_number,
        MAIN_FIRMWARE_VERSION_UUID: MantarrayMcSimulator.default_firmware_version,
    }
    assert MantarrayMcSimulator.default_24_well_magnetometer_config == create_magnetometer_config_dict(24)


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


def test_MantarrayMcSimulator__init__sets_default_metadata_values(
    mantarray_mc_simulator,
):
    simulator = mantarray_mc_simulator["simulator"]
    metadata_dict = simulator.get_metadata_dict()
    assert metadata_dict[BOOTUP_COUNTER_UUID.bytes] == convert_to_metadata_bytes(0)
    assert metadata_dict[TOTAL_WORKING_HOURS_UUID.bytes] == convert_to_metadata_bytes(0)
    assert metadata_dict[TAMPER_FLAG_UUID.bytes] == convert_to_metadata_bytes(0)
    assert metadata_dict[MANTARRAY_NICKNAME_UUID.bytes] == convert_to_metadata_bytes(
        MantarrayMcSimulator.default_mantarray_nickname
    )
    assert metadata_dict[MANTARRAY_SERIAL_NUMBER_UUID.bytes] == convert_to_metadata_bytes(
        MantarrayMcSimulator.default_mantarray_serial_number
    )
    assert metadata_dict[MAIN_FIRMWARE_VERSION_UUID.bytes] == convert_to_metadata_bytes(
        MantarrayMcSimulator.default_firmware_version
    )
    assert metadata_dict[PCB_SERIAL_NUMBER_UUID.bytes] == convert_to_metadata_bytes(
        MantarrayMcSimulator.default_pcb_serial_number
    )


def test_MantarrayMcSimulator_setup_before_loop__calls_super(mantarray_mc_simulator, mocker):
    spied_setup = mocker.spy(InfiniteProcess, "_setup_before_loop")

    simulator = mantarray_mc_simulator["simulator"]
    invoke_process_run_and_check_errors(simulator, perform_setup_before_loop=True)
    spied_setup.assert_called_once()


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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_input_item, input_queue)

    test_output_item = b"some more bytes"
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_output_item, output_queue)

    test_error_item = {"test_error": "an error"}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_error_item, error_queue)

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


def test_MantarrayMcSimulator_read__gets_next_available_bytes(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    expected_bytes = b"expected_item"
    test_item = {"command": "add_read_bytes", "read_bytes": expected_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_item, testing_queue)
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


def test_MantarrayMcSimulator_read_all__gets_all_available_bytes(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_reads = [b"11111", b"222"]
    expected_bytes = test_reads[0] + test_reads[1]
    test_item = {"command": "add_read_bytes", "read_bytes": expected_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_item, testing_queue)
    invoke_process_run_and_check_errors(simulator)
    actual_item = simulator.read_all()
    assert actual_item == expected_bytes


def test_MantarrayMcSimulator_read_all__gets_all_available_bytes__after_partial_read(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_reads = [b"11111", b"222"]
    expected_bytes = test_reads[0] + test_reads[1]
    test_item = {"command": "add_read_bytes", "read_bytes": expected_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_item, testing_queue)
    invoke_process_run_and_check_errors(simulator)

    test_read_size = 3
    actual_item = simulator.read_all()
    assert actual_item == expected_bytes[test_read_size:]


def test_MantarrayMcSimulator_read_all__returns_empty_bytes_if_no_bytes_to_read(
    mantarray_mc_simulator,
):
    simulator = mantarray_mc_simulator["simulator"]
    actual_item = simulator.read_all()
    expected_item = bytes(0)
    assert actual_item == expected_item


def test_MantarrayMcSimulator_in_waiting__getter_returns_number_of_bytes_available_for_read__and_does_not_affect_read_sizes(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    assert simulator.in_waiting == 0

    test_bytes = b"1234567890"
    test_item = {"command": "add_read_bytes", "read_bytes": test_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_item, testing_queue)
    invoke_process_run_and_check_errors(simulator)
    assert simulator.in_waiting == 10

    test_read_size_1 = 4
    test_read_1 = simulator.read(size=test_read_size_1)
    assert len(test_read_1) == test_read_size_1
    assert simulator.in_waiting == len(test_bytes) - test_read_size_1

    test_read_size_2 = len(test_bytes) - test_read_size_1
    test_read_2 = simulator.read(size=test_read_size_2)
    assert len(test_read_2) == test_read_size_2
    assert simulator.in_waiting == 0


def test_MantarrayMcSimulator_in_waiting__setter_raises_error(
    mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    with pytest.raises(AttributeError):
        simulator.in_waiting = 0


def test_MantarrayMcSimulator_write__puts_object_into_input_queue(
    mocker,
):
    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    testing_queue = Queue()
    simulator = MantarrayMcSimulator(input_queue, output_queue, error_queue, testing_queue)

    test_item = b"input_item"
    simulator.write(test_item)
    confirm_queue_is_eventually_of_size(input_queue, 1)
    # Tanner (1/28/21): removing item from queue to avoid BrokenPipeError
    actual_item = input_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_item == test_item


def test_MantarrayMcSimulator__handles_reads_of_size_less_than_next_packet_in_queue__when_queue_is_not_empty(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    test_size_diff = 2
    item_1 = b"item_one"
    item_2 = b"second_item"

    test_comm = {"command": "add_read_bytes", "read_bytes": [item_1, item_2]}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_comm, testing_queue)
    invoke_process_run_and_check_errors(simulator, 1)
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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_dict, testing_queue)
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

    # add test bytes as initial bytes to be read
    test_item_1 = b"12345"
    test_item_2 = b"67890"
    test_items = [
        {"command": "add_read_bytes", "read_bytes": [test_item_1, test_item_2]},
    ]
    handle_putting_multiple_objects_into_empty_queue(test_items, testing_queue)
    invoke_process_run_and_check_errors(simulator)

    simulator.start()

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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_dict, testing_queue)
    invoke_process_run_and_check_errors(simulator)

    expected_1 = test_item
    actual_1 = simulator.read(size=len(test_item) + 1)
    assert actual_1 == expected_1

    actual_2 = simulator.read(size=1)
    assert actual_2 == bytes(0)


def test_MantarrayMcSimulator__raises_error_if_unrecognized_test_command_is_received(
    mantarray_mc_simulator, mocker, patch_print
):
    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]

    expected_command = "bad_command"
    test_item = {"command": expected_command}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_item, testing_queue)
    with pytest.raises(UnrecognizedSimulatorTestCommandError, match=expected_command):
        invoke_process_run_and_check_errors(simulator)


def test_MantarrayMcSimulator__allows_status_code_to_be_set_through_testing_queue_commands(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    expected_status_code = SERIAL_COMM_IDLE_READY_CODE
    test_command = {
        "command": "set_status_code",
        "status_code": expected_status_code,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    invoke_process_run_and_check_errors(simulator)

    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    handshake_response = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)

    status_code_end = len(handshake_response) - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
    status_code_start = status_code_end - SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
    actual_status_code_bytes = handshake_response[status_code_start:status_code_end]
    assert actual_status_code_bytes == convert_to_status_code_bytes(expected_status_code)


def test_MantarrayMcSimulator__processes_testing_commands_during_reboot(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        return_value=AVERAGE_MC_REBOOT_DURATION_SECONDS - 1,
    )
    spied_get_cms_since_init = mocker.spy(simulator, "get_cms_since_init")

    # send reboot command
    test_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    simulator.write(
        create_data_packet(
            test_timestamp,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
            bytes([SERIAL_COMM_REBOOT_COMMAND_BYTE]),
        )
    )
    invoke_process_run_and_check_errors(simulator)

    # remove reboot response packet
    invoke_process_run_and_check_errors(simulator)
    reboot_response_size = get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    reboot_response = simulator.read(size=reboot_response_size)
    assert_serial_packet_is_expected(
        reboot_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(test_timestamp),
        timestamp=spied_get_cms_since_init.spy_return,
    )

    # add read bytes as test command
    expected_item = b"the_item"
    test_dict = {"command": "add_read_bytes", "read_bytes": expected_item}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_dict, testing_queue)
    invoke_process_run_and_check_errors(simulator)
    actual = simulator.read(size=len(expected_item))
    assert actual == expected_item


def test_MantarrayMcSimulator__resets_status_code_after_rebooting(mantarray_mc_simulator_no_beacon, mocker):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    reboot_dur = AVERAGE_MC_REBOOT_DURATION_SECONDS
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        return_value=reboot_dur,
    )
    spied_get_cms_since_init = mocker.spy(simulator, "get_cms_since_init")

    # set status code to known value
    test_status_code = 1738
    test_command = {
        "command": "set_status_code",
        "status_code": test_status_code,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    invoke_process_run_and_check_errors(simulator)
    # send reboot command
    test_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    simulator.write(
        create_data_packet(
            test_timestamp,
            SERIAL_COMM_MAIN_MODULE_ID,
            SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
            bytes([SERIAL_COMM_REBOOT_COMMAND_BYTE]),
        )
    )
    invoke_process_run_and_check_errors(simulator)
    # remove reboot response packet
    invoke_process_run_and_check_errors(simulator)
    reboot_response_size = get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    reboot_response = simulator.read(size=reboot_response_size)
    assert_serial_packet_is_expected(
        reboot_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(test_timestamp),
        timestamp=spied_get_cms_since_init.spy_return,
    )
    # send handshake to test status code reset
    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    handshake_response = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)
    assert len(handshake_response) == HANDSHAKE_RESPONSE_SIZE_BYTES
    assert handshake_response[-8:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES] == DEFAULT_SIMULATOR_STATUS_CODE


def test_MantarrayMcSimulator__allows_metadata_to_be_set_through_testing_queue(
    mantarray_mc_simulator,
):
    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]

    expected_metadata = {
        TOTAL_WORKING_HOURS_UUID: 0,
        MANTARRAY_NICKNAME_UUID: "New Nickname",
    }
    test_command = {"command": "set_metadata", "metadata_values": expected_metadata}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    invoke_process_run_and_check_errors(simulator)

    actual_metadata = simulator.get_metadata_dict()
    # Check that expected values are updated
    assert actual_metadata[TOTAL_WORKING_HOURS_UUID.bytes] == convert_to_metadata_bytes(
        expected_metadata[TOTAL_WORKING_HOURS_UUID]
    )
    assert actual_metadata[MANTARRAY_NICKNAME_UUID.bytes] == convert_to_metadata_bytes(
        expected_metadata[MANTARRAY_NICKNAME_UUID]
    )
    # Check that at least one other value is not changed
    assert actual_metadata[MANTARRAY_SERIAL_NUMBER_UUID.bytes] == convert_to_metadata_bytes(
        MantarrayMcSimulator.default_mantarray_serial_number
    )


def test_MantarrayMcSimulator__accepts_time_sync_along_with_status_code_update__if_status_code_is_set_to_state_following_time_sync(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    spied_get_us = mocker.spy(
        simulator,
        "_get_us_since_time_sync",
    )

    expected_time_usecs = 83924409
    test_command = {
        "command": "set_status_code",
        "status_code": SERIAL_COMM_IDLE_READY_CODE,
        "baseline_time": expected_time_usecs,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    invoke_process_run_and_check_errors(simulator)
    # send status beacon to verify timestamp is set
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    updated_status_beacon = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert_serial_packet_is_expected(
        updated_status_beacon,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        additional_bytes=convert_to_status_code_bytes(SERIAL_COMM_IDLE_READY_CODE),
        timestamp=(expected_time_usecs + spied_get_us.spy_return) // MICROSECONDS_PER_CENTIMILLISECOND,
    )


def test_MantarrayMcSimulator__raises_error_when_magnetometer_config_command_received_with_invalid_sampling_period(
    mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    bad_sampling_period = 1001
    magnetometer_config_bytes = create_magnetometer_config_bytes(
        MantarrayMcSimulator.default_24_well_magnetometer_config
    )
    # send command with invalid sampling period
    dummy_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    change_config_command = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_MAGNETOMETER_CONFIG_COMMAND_BYTE])
        + bad_sampling_period.to_bytes(2, byteorder="little")
        + magnetometer_config_bytes,
    )
    simulator.write(change_config_command)
    # process command and raise error with given sampling period
    with pytest.raises(SerialCommInvalidSamplingPeriodError, match=str(bad_sampling_period)):
        invoke_process_run_and_check_errors(simulator)


def test_MantarrayMcSimulator__automatically_sends_plate_barcode_after_time_is_synced(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    # put simulator in time sync ready status
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": SERIAL_COMM_TIME_SYNC_READY_CODE},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)
    # send set time command
    test_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_set_time_command = create_data_packet(
        test_pc_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_SET_TIME_COMMAND_BYTE]) + convert_to_timestamp_bytes(test_pc_timestamp),
    )
    simulator.write(test_set_time_command)
    # process set time command and remove response
    invoke_process_run_and_check_errors(simulator)
    simulator.read(size=get_full_packet_size_from_packet_body_size(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES))
    plate_event_packet_size = get_full_packet_size_from_packet_body_size(
        1 + len(MantarrayMcSimulator.default_barcode)  # 1 byte for placed/removed flag
    )
    # assert plate event packet sent correctly
    plate_event_packet = simulator.read(size=plate_event_packet_size)
    assert_serial_packet_is_expected(
        plate_event_packet,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_PLATE_EVENT_PACKET_TYPE,
        additional_bytes=bytes([1]) + bytes(MantarrayMcSimulator.default_barcode, encoding="ascii"),
    )
