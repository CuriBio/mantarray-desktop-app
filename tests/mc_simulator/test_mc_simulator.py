# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue
import random
from random import randint

from mantarray_desktop_app import BOOTUP_COUNTER_UUID
from mantarray_desktop_app import convert_to_metadata_bytes
from mantarray_desktop_app import convert_to_status_code_bytes
from mantarray_desktop_app import convert_to_timestamp_bytes
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_desktop_app import PCB_SERIAL_NUMBER_UUID
from mantarray_desktop_app import SERIAL_COMM_BOOT_UP_CODE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_GET_METADATA_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_IDLE_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAIN_MODULE_ID
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
from mantarray_desktop_app import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_REBOOT_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SET_TIME_COMMAND_BYTE
from mantarray_desktop_app import SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_TIME_SYNC_READY_CODE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SerialCommTooManyMissedHandshakesError
from mantarray_desktop_app import TAMPER_FLAG_UUID
from mantarray_desktop_app import TOTAL_WORKING_HOURS_UUID
from mantarray_desktop_app import UnrecognizedSerialCommModuleIdError
from mantarray_desktop_app import UnrecognizedSerialCommPacketTypeError
from mantarray_desktop_app import UnrecognizedSimulatorTestCommandError
from mantarray_desktop_app.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app.mc_simulator import MC_SIMULATOR_BOOT_UP_DURATION_SECONDS
from mantarray_file_manager import MAIN_FIRMWARE_VERSION_UUID
from mantarray_file_manager import MANTARRAY_NICKNAME_UUID
from mantarray_file_manager import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import pytest
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import fixture_runnable_mantarray_mc_simulator
from ..helpers import assert_serial_packet_is_expected
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import get_full_packet_size_from_packet_body_size
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_patch_print,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_runnable_mantarray_mc_simulator,
]

STATUS_BEACON_SIZE_BYTES = 28
HANDSHAKE_RESPONSE_SIZE_BYTES = 36

TEST_HANDSHAKE_TIMESTAMP = 12345
TEST_HANDSHAKE = create_data_packet(
    TEST_HANDSHAKE_TIMESTAMP,
    SERIAL_COMM_MAIN_MODULE_ID,
    SERIAL_COMM_HANDSHAKE_PACKET_TYPE,
    bytes(0),
)

DEFAULT_SIMULATOR_STATUS_CODE = convert_to_status_code_bytes(SERIAL_COMM_BOOT_UP_CODE)


def test_MantarrayMcSimulator__class_attributes():
    assert (
        MantarrayMcSimulator.default_mantarray_nickname == "Mantarray Simulator (MCU)"
    )
    assert MantarrayMcSimulator.default_mantarray_serial_number == "M02001901"
    assert MantarrayMcSimulator.default_pcb_serial_number == "TBD"
    assert MantarrayMcSimulator.default_firmware_version == "0.0.0"
    assert MantarrayMcSimulator.default_metadata_values == {
        BOOTUP_COUNTER_UUID: 0,
        TOTAL_WORKING_HOURS_UUID: 0,
        TAMPER_FLAG_UUID: 0,
        MANTARRAY_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_mantarray_serial_number,
        MANTARRAY_NICKNAME_UUID: MantarrayMcSimulator.default_mantarray_nickname,
        PCB_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_pcb_serial_number,
        MAIN_FIRMWARE_VERSION_UUID: MantarrayMcSimulator.default_firmware_version,
    }


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
    assert metadata_dict[
        MANTARRAY_SERIAL_NUMBER_UUID.bytes
    ] == convert_to_metadata_bytes(MantarrayMcSimulator.default_mantarray_serial_number)
    assert metadata_dict[MAIN_FIRMWARE_VERSION_UUID.bytes] == convert_to_metadata_bytes(
        MantarrayMcSimulator.default_firmware_version
    )
    assert metadata_dict[PCB_SERIAL_NUMBER_UUID.bytes] == convert_to_metadata_bytes(
        MantarrayMcSimulator.default_pcb_serial_number
    )


def test_MantarrayMcSimulator_setup_before_loop__calls_super(
    mantarray_mc_simulator, mocker
):
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


def test_MantarrayMcSimulator_in_waiting__getter_returns_number_of_bytes_available_for_read__and_does_not_affect_read_sizes(
    mantarray_mc_simulator_no_beacon,
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    assert simulator.in_waiting == 0

    test_bytes = b"1234567890"
    test_item = {"command": "add_read_bytes", "read_bytes": test_bytes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_item, testing_queue
    )
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


def test_MantarrayMcSimulator__makes_status_beacon_available_to_read_every_5_seconds__and_includes_correct_timestamp_before_time_is_synced(
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
    mantarray_mc_simulator, mocker, patch_print
):
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

    test_comm = {"command": "add_read_bytes", "read_bytes": [item_1, item_2]}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_comm, testing_queue
    )
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
    mantarray_mc_simulator_no_beacon, mocker, patch_print
):
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
    mantarray_mc_simulator_no_beacon, mocker, patch_print
):
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

    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    actual = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)

    assert_serial_packet_is_expected(
        actual,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        TEST_HANDSHAKE_TIMESTAMP.to_bytes(
            SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
        )
        + DEFAULT_SIMULATOR_STATUS_CODE,
    )


def test_MantarrayMcSimulator__responds_to_comm_from_pc__when_checksum_is_incorrect(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    dummy_timestamp_bytes = bytes(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    dummy_checksum_bytes = bytes(SERIAL_COMM_CHECKSUM_LENGTH_BYTES)
    handshake_packet_length = 14
    test_handshake = (
        SERIAL_COMM_MAGIC_WORD_BYTES
        + handshake_packet_length.to_bytes(
            SERIAL_COMM_PACKET_INFO_LENGTH_BYTES, byteorder="little"
        )
        + dummy_timestamp_bytes
        + bytes([SERIAL_COMM_MAIN_MODULE_ID])
        + bytes([SERIAL_COMM_HANDSHAKE_PACKET_TYPE])
        + dummy_checksum_bytes
    )
    simulator.write(test_handshake)
    invoke_process_run_and_check_errors(simulator)

    expected_packet_body = test_handshake[len(SERIAL_COMM_MAGIC_WORD_BYTES) :]
    expected_size = get_full_packet_size_from_packet_body_size(
        len(expected_packet_body)
    )
    actual = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        actual,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_CHECKSUM_FAILURE_PACKET_TYPE,
        expected_packet_body,
    )


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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    handshake_response = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)

    status_code_end = len(handshake_response) - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
    status_code_start = status_code_end - SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
    actual_status_code_bytes = handshake_response[status_code_start:status_code_end]
    assert actual_status_code_bytes == convert_to_status_code_bytes(
        expected_status_code
    )


def test_MantarrayMcSimulator__discards_commands_from_pc_during_reboot_period__and_sends_reboot_response_packet_before_reboot__and_sends_status_beacon_after_reboot(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]

    spied_randint = mocker.spy(random, "randint")

    reboot_times = [
        AVERAGE_MC_REBOOT_DURATION_SECONDS - 1,
        AVERAGE_MC_REBOOT_DURATION_SECONDS,
    ]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        side_effect=reboot_times,
    )

    spied_reset = mocker.spy(simulator, "_reset_start_time")

    # remove initial status beacon
    invoke_process_run_and_check_errors(simulator)
    initial_status_beacon_length = STATUS_BEACON_SIZE_BYTES - spied_randint.spy_return
    initial_status_beacon = simulator.read(size=initial_status_beacon_length)
    assert len(initial_status_beacon) == initial_status_beacon_length

    # send reboot command
    expected_timestamp = 0
    test_reboot_command = create_data_packet(
        expected_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_REBOOT_COMMAND_BYTE]),
    )
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)

    # test that reboot response packet is sent
    reboot_response_size = get_full_packet_size_from_packet_body_size(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
    )
    reboot_response = simulator.read(size=reboot_response_size)
    assert_serial_packet_is_expected(
        reboot_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        expected_timestamp.to_bytes(
            SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
        ),
    )

    # test that handshake is ignored
    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    response_during_reboot = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)
    assert len(response_during_reboot) == 0

    # test that status beacon is sent after reboot
    invoke_process_run_and_check_errors(simulator)
    status_beacon = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert_serial_packet_is_expected(
        status_beacon,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        DEFAULT_SIMULATOR_STATUS_CODE,
    )

    # test that start time was reset
    spied_reset.assert_called_once()


def test_MantarrayMcSimulator__reset_status_code_after_rebooting(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    reboot_dur = AVERAGE_MC_REBOOT_DURATION_SECONDS
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        return_value=reboot_dur,
    )

    # set status code to known value
    test_status_code = 1738
    test_command = {
        "command": "set_status_code",
        "status_code": test_status_code,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # send reboot command
    expected_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_reboot_command = create_data_packet(
        expected_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_REBOOT_COMMAND_BYTE]),
    )
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)

    # remove reboot response packet
    invoke_process_run_and_check_errors(simulator)
    expected_reboot_response = create_data_packet(
        0,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        expected_timestamp.to_bytes(
            SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
        ),
    )
    reboot_response = simulator.read(size=len(expected_reboot_response))
    assert reboot_response == expected_reboot_response

    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    handshake_response = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)
    assert len(handshake_response) == HANDSHAKE_RESPONSE_SIZE_BYTES
    assert handshake_response[-8:-4] == DEFAULT_SIMULATOR_STATUS_CODE


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

    # send reboot command
    expected_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_reboot_command = create_data_packet(
        expected_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_REBOOT_COMMAND_BYTE]),
    )
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)

    # remove reboot response packet
    invoke_process_run_and_check_errors(simulator)
    expected_reboot_response = create_data_packet(
        0,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        expected_timestamp.to_bytes(
            SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
        ),
    )
    reboot_response = simulator.read(size=len(expected_reboot_response))
    assert reboot_response == expected_reboot_response

    # add read bytes as test command
    expected_item = b"the_item"
    test_dict = {"command": "add_read_bytes", "read_bytes": expected_item}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_dict, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    actual = simulator.read(size=len(expected_item))
    assert actual == expected_item


def test_MantarrayMcSimulator__does_not_send_status_beacon_while_rebooting(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]

    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_status_beacon",
        autospec=True,
        side_effect=[0, SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS],
    )

    # remove boot up beacon
    invoke_process_run_and_check_errors(simulator)
    simulator.read(size=STATUS_BEACON_SIZE_BYTES)

    # send reboot command
    expected_timestamp = 1
    test_reboot_command = create_data_packet(
        expected_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_REBOOT_COMMAND_BYTE]),
    )
    simulator.write(test_reboot_command)
    invoke_process_run_and_check_errors(simulator)

    # remove reboot response packet
    invoke_process_run_and_check_errors(simulator)
    reboot_response_size = get_full_packet_size_from_packet_body_size(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
    )
    reboot_response = simulator.read(size=reboot_response_size)
    assert_serial_packet_is_expected(
        reboot_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        expected_timestamp.to_bytes(
            SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
        ),
    )

    # check status beacon was not sent
    invoke_process_run_and_check_errors(simulator)
    actual_beacon_packet = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert actual_beacon_packet == bytes(0)


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
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, testing_queue
    )
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
    assert actual_metadata[
        MANTARRAY_SERIAL_NUMBER_UUID.bytes
    ] == convert_to_metadata_bytes(MantarrayMcSimulator.default_mantarray_serial_number)


def test_MantarrayMcSimulator__allows_mantarray_nickname_to_be_set_by_command_received_from_pc__and_sends_correct_response(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_nickname = "Newer Nickname"
    expected_timestamp = SERIAL_COMM_MAX_TIMESTAMP_VALUE
    set_nickname_command = create_data_packet(
        expected_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_SET_NICKNAME_COMMAND_BYTE])
        + convert_to_metadata_bytes(expected_nickname),
    )
    simulator.write(set_nickname_command)
    invoke_process_run_and_check_errors(simulator)

    # Check that nickname is updated
    actual_metadata = simulator.get_metadata_dict()
    assert actual_metadata[MANTARRAY_NICKNAME_UUID.bytes] == convert_to_metadata_bytes(
        expected_nickname
    )
    # Check that correct response is sent
    expected_response_size = get_full_packet_size_from_packet_body_size(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
    )
    actual = simulator.read(size=expected_response_size)
    assert_serial_packet_is_expected(
        actual,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        expected_timestamp.to_bytes(
            SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
        ),
    )


def test_MantarrayMcSimulator__processes_get_metadata_command(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    expected_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    get_metadata_command = create_data_packet(
        expected_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_GET_METADATA_COMMAND_BYTE]),
    )
    simulator.write(get_metadata_command)
    invoke_process_run_and_check_errors(simulator)

    expected_metadata_bytes = bytes(0)
    for key, value in simulator.get_metadata_dict().items():
        expected_metadata_bytes += key
        expected_metadata_bytes += value
    expected_size = get_full_packet_size_from_packet_body_size(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES + len(expected_metadata_bytes)
    )
    actual = simulator.read(size=expected_size)
    assert_serial_packet_is_expected(
        actual,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        expected_timestamp.to_bytes(
            SERIAL_COMM_TIMESTAMP_LENGTH_BYTES, byteorder="little"
        )
        + expected_metadata_bytes,
    )


def test_MantarrayMcSimulator__raises_error_if_too_many_consecutive_handshake_periods_missed_from_pc__after_first_handshake_received(
    mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": SERIAL_COMM_IDLE_READY_CODE},
        testing_queue,
    )
    invoke_process_run_and_check_errors(simulator)

    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_handshake",
        autospec=True,
        side_effect=[
            0,
            SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
            * SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES
            - 1,
            SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
            * SERIAL_COMM_NUM_ALLOWED_MISSED_HANDSHAKES,
        ],
    )

    # make sure error isn't raised before initial handshake received
    invoke_process_run_and_check_errors(simulator)
    # send and process first handshake
    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    # make sure error isn't raised 1 second before final handshake missed
    invoke_process_run_and_check_errors(simulator)
    # make sure error is raised when final handshake missed
    with pytest.raises(SerialCommTooManyMissedHandshakesError):
        invoke_process_run_and_check_errors(simulator)


def test_MantarrayMcSimulator__switches_to_time_sync_status_code_after_boot_up_period__and_automatically_sends_beacon_after_status_code_update(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_boot_up",
        autospec=True,
        side_effect=[0, MC_SIMULATOR_BOOT_UP_DURATION_SECONDS],
    )

    # remove initial beacon
    invoke_process_run_and_check_errors(simulator)
    simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    # run simulator to complete boot up
    invoke_process_run_and_check_errors(simulator)
    # check that status beacon is automatically sent with updated status code
    actual = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert_serial_packet_is_expected(
        actual,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        convert_to_status_code_bytes(SERIAL_COMM_TIME_SYNC_READY_CODE),
    )


def test_MantarrayMcSimulator__switches_from_idle_ready_status_to_magic_word_timeout_status_if_magic_word_not_detected_within_timeout_period(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_comm_from_pc",
        autospec=True,
        side_effect=[
            SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS - 1,
            SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS,
        ],
    )

    test_command = {
        "command": "set_status_code",
        "status_code": SERIAL_COMM_IDLE_READY_CODE,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, testing_queue
    )
    simulator.write(TEST_HANDSHAKE)
    # confirm idle ready and process handshake
    invoke_process_run_and_check_errors(simulator, num_iterations=2)
    assert simulator.get_status_code() == SERIAL_COMM_IDLE_READY_CODE
    # confirm magic word timeout
    invoke_process_run_and_check_errors(simulator)
    assert simulator.get_status_code() == SERIAL_COMM_HANDSHAKE_TIMEOUT_CODE


@pytest.mark.parametrize(
    "test_code,test_description",
    [
        (SERIAL_COMM_BOOT_UP_CODE, "does not switch status code when booting up"),
        (
            SERIAL_COMM_TIME_SYNC_READY_CODE,
            "does not switch status code when waiting for time sync",
        ),
    ],
)
def test_MantarrayMcSimulator__does_not_switch_to_magic_word_timeout_status_before_time_is_synced(
    test_code, test_description, mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_last_comm_from_pc",
        autospec=True,
        side_effect=[SERIAL_COMM_HANDSHAKE_TIMEOUT_SECONDS],
    )

    test_command = {
        "command": "set_status_code",
        "status_code": test_code,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, testing_queue
    )
    simulator.write(TEST_HANDSHAKE)
    # confirm test status code
    invoke_process_run_and_check_errors(simulator)
    assert simulator.get_status_code() == test_code
    # confirm status code did not change
    invoke_process_run_and_check_errors(simulator)
    assert simulator.get_status_code() == test_code


def test_MantarrayMcSimulator__processes_set_time_command(
    mantarray_mc_simulator, mocker
):
    simulator = mantarray_mc_simulator["simulator"]
    testing_queue = mantarray_mc_simulator["testing_queue"]

    # put simulator in time sync ready state before syncing time
    test_command = {
        "command": "set_status_code",
        "status_code": SERIAL_COMM_TIME_SYNC_READY_CODE,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # remove initial beacon
    simulator.read(size=STATUS_BEACON_SIZE_BYTES)

    # mock here to avoid interference from previous iteration calling method
    expected_command_response_time_us = 111111
    expected_status_beacon_time_us = 222222
    mocker.patch.object(
        mc_simulator,
        "_perf_counter_us",
        autospec=True,
        side_effect=[expected_command_response_time_us, expected_status_beacon_time_us],
    )

    # send set time command
    expected_pc_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    test_set_time_command = create_data_packet(
        expected_pc_timestamp,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_SIMPLE_COMMAND_PACKET_TYPE,
        bytes([SERIAL_COMM_SET_TIME_COMMAND_BYTE])
        + convert_to_timestamp_bytes(expected_pc_timestamp),
    )
    simulator.write(test_set_time_command)
    invoke_process_run_and_check_errors(simulator)

    # test that command response uses updated timestamp
    command_response_size = get_full_packet_size_from_packet_body_size(
        SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
    )
    command_response = simulator.read(size=command_response_size)
    assert_serial_packet_is_expected(
        command_response,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_COMMAND_RESPONSE_PACKET_TYPE,
        additional_bytes=convert_to_timestamp_bytes(expected_pc_timestamp),
        timestamp=(expected_pc_timestamp + expected_command_response_time_us)
        // MICROSECONDS_PER_CENTIMILLISECOND,
    )
    # test that status beacon is automatically sent after command response with status code updated to idle ready and correct timestamp
    status_beacon = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert_serial_packet_is_expected(
        status_beacon,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        additional_bytes=convert_to_status_code_bytes(SERIAL_COMM_IDLE_READY_CODE),
        timestamp=(expected_pc_timestamp + expected_status_beacon_time_us)
        // MICROSECONDS_PER_CENTIMILLISECOND,
    )


def test_MantarrayMcSimulator__accepts_time_sync_along_with_status_code_update__if_status_code_is_set_to_state_following_time_sync(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    spied_perf_counter_us = mocker.spy(
        mc_simulator,
        "_perf_counter_us",
    )

    expected_time_usecs = 83924409
    test_command = {
        "command": "set_status_code",
        "status_code": SERIAL_COMM_IDLE_READY_CODE,
        "baseline_time": expected_time_usecs,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        test_command, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # send status beacon to verify timestamp is set
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    status_beacon = simulator.read(size=STATUS_BEACON_SIZE_BYTES)
    assert_serial_packet_is_expected(
        status_beacon,
        SERIAL_COMM_MAIN_MODULE_ID,
        SERIAL_COMM_STATUS_BEACON_PACKET_TYPE,
        additional_bytes=convert_to_status_code_bytes(SERIAL_COMM_IDLE_READY_CODE),
        timestamp=(expected_time_usecs + spied_perf_counter_us.spy_return)
        // MICROSECONDS_PER_CENTIMILLISECOND,
    )
