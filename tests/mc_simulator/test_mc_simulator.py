# -*- coding: utf-8 -*-
import logging
from multiprocessing import Queue
from random import randint

from immutabledict import immutabledict
from mantarray_desktop_app import create_data_packet
from mantarray_desktop_app import MantarrayMcSimulator
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAX_TIMESTAMP_VALUE
from mantarray_desktop_app import SERIAL_COMM_REBOOT_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app import SerialCommInvalidSamplingPeriodError
from mantarray_desktop_app import UnrecognizedSimulatorTestCommandError
from mantarray_desktop_app.constants import BARCODE_LEN
from mantarray_desktop_app.constants import SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE
from mantarray_desktop_app.simulators import mc_simulator
from mantarray_desktop_app.simulators.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import INITIAL_MAGNET_FINDING_PARAMS_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
import pytest
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import fixture_runnable_mantarray_mc_simulator
from ..fixtures_mc_simulator import HANDSHAKE_RESPONSE_SIZE_BYTES
from ..fixtures_mc_simulator import TEST_HANDSHAKE
from ..helpers import assert_serial_packet_is_expected
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import get_full_packet_size_from_payload_len
from ..helpers import handle_putting_multiple_objects_into_empty_queue
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_runnable_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_MantarrayMcSimulator__class_attributes():
    assert MantarrayMcSimulator.initial_magnet_finding_params == {"X": 0, "Y": 2, "Z": -5, "REMN": 1200}
    assert MantarrayMcSimulator.default_mantarray_nickname == "Mantarray Sim"
    assert MantarrayMcSimulator.default_mantarray_serial_number == "MA2022001000"
    assert MantarrayMcSimulator.default_main_firmware_version == "0.0.0"
    assert MantarrayMcSimulator.default_channel_firmware_version == "0.0.0"
    assert MantarrayMcSimulator.default_plate_barcode == "ML22001000-2"
    assert MantarrayMcSimulator.default_stim_barcode == "MS22001000-2"
    assert MantarrayMcSimulator.default_metadata_values == {
        BOOT_FLAGS_UUID: 0b00000000,
        MANTARRAY_SERIAL_NUMBER_UUID: MantarrayMcSimulator.default_mantarray_serial_number,
        MANTARRAY_NICKNAME_UUID: MantarrayMcSimulator.default_mantarray_nickname,
        MAIN_FIRMWARE_VERSION_UUID: MantarrayMcSimulator.default_main_firmware_version,
        CHANNEL_FIRMWARE_VERSION_UUID: MantarrayMcSimulator.default_channel_firmware_version,
        INITIAL_MAGNET_FINDING_PARAMS_UUID: MantarrayMcSimulator.initial_magnet_finding_params,
    }
    assert MantarrayMcSimulator.global_timer_offset_secs == 2.5


def test_MantarrayMcSimulator__super_is_called_during_init__with_default_logging_value(
    mocker,
):
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")

    input_queue = Queue()
    output_queue = Queue()
    error_queue = Queue()
    testing_queue = Queue()
    MantarrayMcSimulator(input_queue, output_queue, error_queue, testing_queue)

    mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


def test_MantarrayMcSimulator__init__sets_default_metadata_values(
    mantarray_mc_simulator,
):
    simulator = mantarray_mc_simulator["simulator"]
    metadata_dict = simulator.get_metadata_dict()
    assert isinstance(metadata_dict, dict)
    assert not isinstance(metadata_dict, immutabledict)


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
    test_item = {"command": "add_read_bytes", "read_bytes": test_reads}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_item, testing_queue)
    invoke_process_run_and_check_errors(simulator)

    test_read_size = 3
    simulator.read(size=test_read_size)
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

    expected_status_codes = list(range(2 + simulator._num_wells))
    test_command = {"command": "set_status_code", "status_codes": expected_status_codes}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, testing_queue)
    invoke_process_run_and_check_errors(simulator)

    simulator.write(TEST_HANDSHAKE)
    invoke_process_run_and_check_errors(simulator)
    handshake_response = simulator.read(size=HANDSHAKE_RESPONSE_SIZE_BYTES)

    status_code_end = len(handshake_response) - SERIAL_COMM_CHECKSUM_LENGTH_BYTES
    status_code_start = status_code_end - SERIAL_COMM_STATUS_CODE_LENGTH_BYTES
    actual_status_code_bytes = handshake_response[status_code_start:status_code_end]
    assert actual_status_code_bytes == bytes(expected_status_codes)


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
    spied_get_absolute_timer = mocker.spy(simulator, "_get_absolute_timer")

    # send reboot command
    test_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    simulator.write(create_data_packet(test_timestamp, SERIAL_COMM_REBOOT_PACKET_TYPE))
    invoke_process_run_and_check_errors(simulator)

    # remove reboot response packet
    invoke_process_run_and_check_errors(simulator)
    reboot_response_size = get_full_packet_size_from_payload_len(SERIAL_COMM_TIMESTAMP_LENGTH_BYTES)
    reboot_response = simulator.read(size=reboot_response_size)
    assert_serial_packet_is_expected(
        reboot_response, SERIAL_COMM_REBOOT_PACKET_TYPE, timestamp=spied_get_absolute_timer.spy_return
    )

    # add read bytes as test command
    expected_item = b"the_item"
    test_dict = {"command": "add_read_bytes", "read_bytes": expected_item}
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_dict, testing_queue)
    invoke_process_run_and_check_errors(simulator)
    actual = simulator.read(size=len(expected_item))
    assert actual == expected_item


def test_MantarrayMcSimulator__raises_error_when_set_sampling_period_command_received_with_invalid_sampling_period(
    mantarray_mc_simulator_no_beacon, patch_print
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    bad_sampling_period = 1001
    # send command with invalid sampling period
    dummy_timestamp = randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE)
    set_sampling_period_command = create_data_packet(
        dummy_timestamp,
        SERIAL_COMM_SET_SAMPLING_PERIOD_PACKET_TYPE,
        bad_sampling_period.to_bytes(2, byteorder="little"),
    )
    simulator.write(set_sampling_period_command)
    # process command and raise error with given sampling period
    with pytest.raises(SerialCommInvalidSamplingPeriodError, match=str(bad_sampling_period)):
        invoke_process_run_and_check_errors(simulator)


def test_MantarrayMcSimulator__automatically_sends_plate_then_stim_barcode_after_first_data_stream_completes(
    mantarray_mc_simulator_no_beacon, mocker
):
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    # mock so no data is created
    mocker.patch.object(simulator, "_handle_magnetometer_data_packet", autospec=True)

    # start data streaming
    start_data_streaming_command = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE), SERIAL_COMM_START_DATA_STREAMING_PACKET_TYPE
    )
    simulator.write(start_data_streaming_command)
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()  # clear command response
    # stop data streaming
    stop_data_streaming_command = create_data_packet(
        randint(0, SERIAL_COMM_MAX_TIMESTAMP_VALUE), SERIAL_COMM_STOP_DATA_STREAMING_PACKET_TYPE
    )
    simulator.write(stop_data_streaming_command)
    invoke_process_run_and_check_errors(simulator)
    # clear command response
    expected_response_size = get_full_packet_size_from_payload_len(1)
    assert len(simulator.read(size=expected_response_size)) == expected_response_size

    # test barcode packets
    expected_barcode_packet_size = get_full_packet_size_from_payload_len(BARCODE_LEN)
    plate_barcode_packet = simulator.read(size=expected_barcode_packet_size)
    assert_serial_packet_is_expected(
        plate_barcode_packet,
        SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE,
        additional_bytes=bytes(MantarrayMcSimulator.default_plate_barcode, encoding="ascii"),
    )
    stim_barcode_packet = simulator.read(size=expected_barcode_packet_size)
    assert_serial_packet_is_expected(
        stim_barcode_packet,
        SERIAL_COMM_BARCODE_FOUND_PACKET_TYPE,
        additional_bytes=bytes(MantarrayMcSimulator.default_stim_barcode, encoding="ascii"),
    )
