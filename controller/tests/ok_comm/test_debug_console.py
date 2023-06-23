# -*- coding: utf-8 -*-
import copy
import struct

from mantarray_desktop_app import execute_debug_console_command
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import UnrecognizedDebugConsoleCommandError
import pytest
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import TestingQueue
from xem_wrapper import DATA_FRAME_SIZE_WORDS
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import PIPE_OUT_FIFO

from ..fixtures import fixture_patched_firmware_folder
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_ok_comm import fixture_four_board_comm_process
from ..fixtures_ok_comm import fixture_running_process_with_simulated_board
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_running_process_with_simulated_board,
    fixture_four_board_comm_process,
    fixture_patched_firmware_folder,
]


def test_execute_debug_console_command__raises_error_for_unrecognized_command():
    with pytest.raises(UnrecognizedDebugConsoleCommandError, match="fakecommand"):
        execute_debug_console_command(None, {"command": "fakecommand"})


def test_execute_debug_console_command__returns_stack_trace_of_error_raised_when_attempting_to_run_command_with_suppress_error_key_True(
    mocker,
):
    dummy_panel = FrontPanelSimulator({})
    mocker.patch.object(dummy_panel, "initialize_board", side_effect=KeyError("side_effect_error"))
    return_value = execute_debug_console_command(
        dummy_panel,
        {
            "command": "initialize_board",
            "bit_file_name": "main.bit",
            "suppress_error": True,
        },
    )
    assert ", in execute_debug_console_command" in return_value
    assert "side_effect_error" in str(return_value)


def test_execute_debug_console_command__lets_error_propagate_up_with_default_suppress_error_value(
    mocker,
):
    dummy_panel = FrontPanelSimulator({})
    mocker.patch.object(dummy_panel, "initialize_board", side_effect=KeyError("side_effect_error"))
    with pytest.raises(KeyError, match="side_effect_error"):
        execute_debug_console_command(
            dummy_panel,
            {"command": "initialize_board", "bit_file_name": "main.bit"},
        )


def test_execute_debug_console_command__initializes_board(patched_firmware_folder):
    dummy_panel = FrontPanelSimulator({})

    execute_debug_console_command(
        dummy_panel,
        {"command": "initialize_board", "bit_file_name": patched_firmware_folder},
    )
    assert dummy_panel.is_board_initialized() is True


@pytest.mark.slow
def test_OkCommunicationProcess_run__processes_init_board_debug_console_command(
    running_process_with_simulated_board, patched_firmware_folder
):
    # Tanner (8/20/21): leave running_process_with_simulated_board in this test so there is at least one test where a command from main is processed in a running instance of OkComm
    test_bit_file_name = patched_firmware_folder
    simulator = FrontPanelSimulator({})
    ok_process, board_queues, error_queue = running_process_with_simulated_board(simulator).values()
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]
    init_command = {
        "communication_type": "debug_console",
        "command": "initialize_board",
        "bit_file_name": test_bit_file_name,
    }
    input_queue.put_nowait(copy.deepcopy(init_command))
    ok_process.soft_stop()
    ok_process.join()
    assert error_queue.empty() is True

    init_response = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert init_response["command"] == "initialize_board"
    assert init_response["bit_file_name"] == test_bit_file_name


def test_OkCommunicationProcess_run__processes_init_board_debug_console_command_when_reinitializing(
    four_board_comm_process, patched_firmware_folder
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    test_bit_file_name = patched_firmware_folder
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    init_command = {
        "communication_type": "debug_console",
        "command": "initialize_board",
        "bit_file_name": test_bit_file_name,
        "allow_board_reinitialization": True,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(copy.deepcopy(init_command), input_queue)
    invoke_process_run_and_check_errors(ok_process)

    init_response = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert init_response["command"] == "initialize_board"
    assert init_response["bit_file_name"] == test_bit_file_name
    # Tanner (5/26/20): Asserting response is None is the simplest way to assert no error was returned
    assert init_response["response"] is None


@pytest.mark.parametrize(
    """test_address,test_response,test_description""",
    [(7, 5, "response of 5 from wire 7"), (4, 8, "response of 8 from wire 4")],
)
def test_OkCommunicationProcess_run__processes_read_wire_out_debug_console_command(
    test_address,
    test_response,
    test_description,
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    wire_queue = TestingQueue()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_response, wire_queue)
    simulator = FrontPanelSimulator({"wire_outs": {test_address: wire_queue}})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "read_wire_out",
        "ep_addr": test_address,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    expected_returned_communication["response"] = test_response
    expected_returned_communication["hex_converted_response"] = hex(test_response)
    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_returned_communication


@pytest.mark.parametrize(
    """test_num_words_to_log,test_num_cycles_to_read,test_description""",
    [
        (1, 1, "logs 1 word with one cycle read"),
        (72, 1, "logs 72 words with one cycle read"),
        (73, 1, "logs 72 words given 73 num words to log and one cycle read"),
        (144, 2, "logs 144 words given 144 num words to log and two cycles read"),
    ],
)
def test_OkCommunicationProcess_run__processes_read_from_fifo_debug_console_command(
    test_num_words_to_log,
    test_num_cycles_to_read,
    test_description,
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    test_bytearray = produce_data(test_num_cycles_to_read, 0)
    fifo = TestingQueue()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_bytearray, fifo)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    simulator.start_acquisition()

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "read_from_fifo",
        "num_words_to_log": test_num_words_to_log,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    total_num_words = len(test_bytearray) // 4
    test_words = struct.unpack(f"<{total_num_words}L", test_bytearray)
    formatted_test_words = list()
    num_words_to_log = min(total_num_words, test_num_words_to_log)
    for i in range(num_words_to_log):
        formatted_test_words.append(hex(test_words[i]))
    expected_returned_communication["response"] = formatted_test_words
    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_returned_communication


def test_OkCommunicationProcess_run__processes_get_device_id_debug_console_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    expected_id = "Mantarray XEM"
    simulator.set_device_id(expected_id)

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "get_device_id",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    expected_returned_communication["response"] = expected_id
    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_returned_communication


def test_OkCommunicationProcess_run__processes_get_serial_number_debug_console_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "get_serial_number",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    expected_returned_communication["response"] = "1917000Q70"
    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_returned_communication


def test_OkCommunicationProcess_run__processes_is_spi_running_debug_console_command_when_false(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    assert simulator.is_spi_running() is False

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "is_spi_running",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    expected_returned_communication["response"] = False
    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_returned_communication


def test_OkCommunicationProcess_run__processes_start_acquisition_debug_console_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    assert simulator.is_spi_running() is False

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "start_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)
    expected_spi_communication = {
        "communication_type": "debug_console",
        "command": "is_spi_running",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_spi_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    actual_returned_communication = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert (
        actual_returned_communication["communication_type"]
        == expected_returned_communication["communication_type"]
    )
    assert actual_returned_communication["command"] == expected_returned_communication["command"]
    expected_spi_communication["response"] = True
    actual_spi_communication = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_spi_communication == expected_spi_communication


def test_OkCommunicationProcess_run__processes_stop_acquisition_debug_console_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    simulator.start_acquisition()

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "stop_acquisition",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)
    expected_spi_communication = {
        "communication_type": "debug_console",
        "command": "is_spi_running",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_spi_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual["communication_type"] == expected_returned_communication["communication_type"]
    assert actual["command"] == expected_returned_communication["command"]
    expected_spi_communication["response"] = False
    actual_spi_response = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_spi_response == expected_spi_communication


def test_OkCommunicationProcess_run__processes_set_device_id_debug_console_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    expected_id = "Mantarray XEM"
    simulator = FrontPanelSimulator({})
    ok_process.set_board_connection(0, simulator)

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "set_device_id",
        "new_id": expected_id,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)
    expected_get_communication = {
        "communication_type": "debug_console",
        "command": "get_device_id",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_get_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual["command"] == expected_returned_communication["command"]
    assert actual["new_id"] == expected_returned_communication["new_id"]

    get_response = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    actual_id = get_response["response"]
    assert actual_id == expected_id


def test_OkCommunicationProcess_run__processes_set_wire_in_debug_console_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "set_wire_in",
        "ep_addr": 6,
        "value": 0x00000001,
        "mask": 0x00000001,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual["command"] == expected_returned_communication["command"]
    assert actual["ep_addr"] == expected_returned_communication["ep_addr"]
    assert actual["value"] == expected_returned_communication["value"]
    assert actual["mask"] == expected_returned_communication["mask"]


def test_OkCommunicationProcess_run__processes_activate_trigger_in_debug_console_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "activate_trigger_in",
        "ep_addr": 32,
        "bit": 0x01,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual["command"] == expected_returned_communication["command"]
    assert actual["ep_addr"] == expected_returned_communication["ep_addr"]
    assert actual["bit"] == expected_returned_communication["bit"]


def test_OkCommunicationProcess_run__processes_get_num_words_fifo_debug_console_command_with_one_data_frame(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    expected_num_words = DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    test_bytearray = bytearray(expected_num_words * 4)
    fifo = TestingQueue()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_bytearray, fifo)
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "get_num_words_fifo",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    expected_returned_communication["response"] = expected_num_words
    expected_returned_communication["hex_converted_response"] = hex(expected_num_words)
    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_returned_communication


def test_OkCommunicationProcess_run__processes_get_status_debug_console_command_with_default_values(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    simulator = FrontPanelSimulator({})
    ok_process.set_board_connection(0, simulator)

    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "get_status",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    expected_response = {}
    expected_response["is_spi_running"] = False
    expected_response["is_board_initialized"] = False
    expected_response["bit_file_name"] = None
    expected_returned_communication["response"] = expected_response
    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_returned_communication


def test_OkCommunicationProcess_run__processes_comm_delay_debug_console_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    response_queue = board_queues[0][1]

    simulator = FrontPanelSimulator({})
    ok_process.set_board_connection(0, simulator)

    expected_num_millis = 20
    expected_returned_communication = {
        "communication_type": "debug_console",
        "command": "comm_delay",
        "num_milliseconds": expected_num_millis,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(expected_returned_communication), input_queue
    )
    invoke_process_run_and_check_errors(ok_process)

    actual = response_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual["command"] == expected_returned_communication["command"]
    assert actual["num_milliseconds"] == expected_returned_communication["num_milliseconds"]
    assert actual["response"] == f"Delayed for {expected_num_millis} milliseconds"
