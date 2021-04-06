# -*- coding: utf-8 -*-
import copy
import datetime
import logging
from multiprocessing import Queue
from statistics import stdev
import struct
import time
from typing import Any
from typing import Dict

from freezegun import freeze_time
from mantarray_desktop_app import FIFO_READ_PRODUCER_DATA_OFFSET
from mantarray_desktop_app import FIFO_READ_PRODUCER_SAWTOOTH_PERIOD
from mantarray_desktop_app import FIFO_READ_PRODUCER_WELL_AMPLITUDE
from mantarray_desktop_app import FirstManagedReadLessThanOneRoundRobinError
from mantarray_desktop_app import INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
from mantarray_desktop_app import InstrumentCommIncorrectHeaderError
from mantarray_desktop_app import OkCommunicationProcess
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import RAW_TO_SIGNED_CONVERSION_VALUE
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import STOP_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app import UnrecognizedCommandToInstrumentError
from mantarray_desktop_app import UnrecognizedDataFrameFormatNameError
import numpy as np
import pytest
from scipy import signal
from stdlib_utils import drain_queue
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import parallelism_framework
from xem_wrapper import build_header_magic_number_bytes
from xem_wrapper import DATA_FRAME_SIZE_WORDS
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import HEADER_MAGIC_NUMBER
from xem_wrapper import PIPE_OUT_FIFO

from ..fixtures import get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_ok_comm import fixture_four_board_comm_process
from ..fixtures_ok_comm import generate_board_and_error_queues
from ..helpers import assert_queue_is_eventually_not_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_empty
from ..helpers import is_queue_eventually_not_empty
from ..helpers import is_queue_eventually_of_size

__fixtures__ = [
    fixture_four_board_comm_process,
]


@freeze_time("2020-02-12 14:10:11.123456")
def test_OkCommunicationProcess_run__processes_start_managed_acquisition_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    input_queue = board_queues[0][0]
    ok_comm_to_main = board_queues[0][1]
    expected_returned_communication: Dict[
        str, Any
    ] = get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    input_queue.put_nowait(copy.deepcopy(expected_returned_communication))
    confirm_queue_is_eventually_of_size(
        input_queue, 1, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    invoke_process_run_and_check_errors(ok_process)

    expected_returned_communication["timestamp"] = datetime.datetime.utcnow()
    actual = ok_comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_returned_communication

    assert (
        ok_process._is_managed_acquisition_running[0]  # pylint:disable=protected-access
        is True
    )
    board_connections = ok_process.get_board_connections_list()
    assert board_connections[0].is_spi_running() is True
    assert (
        ok_process._is_first_managed_read[0] is True  # pylint:disable=protected-access
    )


def test_OkCommunicationProcess_run__processes_stop_managed_acquisition_command(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    simulator.start_acquisition()
    ok_process.set_board_connection(0, simulator)
    ok_process._is_managed_acquisition_running[  # pylint:disable=protected-access
        0
    ] = True

    input_queue = board_queues[0][0]
    ok_comm_to_main = board_queues[0][1]
    expected_returned_communication = STOP_MANAGED_ACQUISITION_COMMUNICATION
    input_queue.put_nowait(copy.deepcopy(expected_returned_communication))
    confirm_queue_is_eventually_of_size(
        input_queue, 1, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    invoke_process_run_and_check_errors(ok_process)

    actual = ok_comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_returned_communication

    assert (
        ok_process._is_managed_acquisition_running[0]  # pylint:disable=protected-access
        is False
    )
    board_connections = ok_process.get_board_connections_list()
    assert board_connections[0].is_spi_running() is False


def test_OkCommunicationProcess_run__raises_error_if_command_to_instrument_is_invalid(
    four_board_comm_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    input_queue = board_queues[0][0]
    expected_returned_communication = {
        "communication_type": "to_instrument",
        "command": "fake_command",
    }
    input_queue.put_nowait(copy.deepcopy(expected_returned_communication))
    confirm_queue_is_eventually_of_size(
        input_queue, 1, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )
    with pytest.raises(UnrecognizedCommandToInstrumentError, match="fake_command"):
        invoke_process_run_and_check_errors(ok_process)


@freeze_time("2020-02-13 11:43:11.123456")
def test_OkCommunicationProcess_commands_for_each_run_iteration__sets_default_time_since_last_fifo_read_if_none_while_spi_running(
    mocker,
):
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)

    p = OkCommunicationProcess(board_queues, error_queue)

    expected_timepoint = 9876
    mocker.patch.object(time, "perf_counter", return_value=expected_timepoint)

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    simulator.start_acquisition()
    p.set_board_connection(0, simulator)
    p._is_managed_acquisition_running[0] = True  # pylint:disable=protected-access
    invoke_process_run_and_check_errors(p)

    assert (
        p._time_of_last_fifo_read[0]  # pylint:disable=protected-access
        == datetime.datetime.utcnow()
    )
    assert (
        p._timepoint_of_last_fifo_read[0]  # pylint:disable=protected-access
        == expected_timepoint
    )


@freeze_time("2020-02-13 11:43:11.123456")
def test_OkCommunicationProcess_commands_for_each_run_iteration__removes_default_time_since_last_fifo_read_while_spi_not_running():
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)

    p = OkCommunicationProcess(board_queues, error_queue)
    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    p.set_board_connection(0, simulator)
    p._time_of_last_fifo_read[  # pylint:disable=protected-access
        0
    ] = datetime.datetime.utcnow()
    p._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    invoke_process_run_and_check_errors(p)

    assert p._time_of_last_fifo_read[0] is None  # pylint:disable=protected-access
    assert p._timepoint_of_last_fifo_read[0] is None  # pylint: disable=protected-access


@freeze_time("2020-02-13 11:43:11.123456")
def test_OkCommunicationProcess_commands_for_each_run_iteration__sends_fifo_read_to_file_writer_if_ready_to_read():
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    p = OkCommunicationProcess(board_queues, error_queue)
    test_bytearray = produce_data(1, 0)
    fifo = Queue()
    fifo.put_nowait(test_bytearray)
    assert is_queue_eventually_of_size(fifo, 1) is True
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    simulator.start_acquisition()
    p.set_board_connection(0, simulator)
    p._is_managed_acquisition_running[0] = True  # pylint:disable=protected-access
    p._time_of_last_fifo_read[0] = datetime.datetime(  # pylint:disable=protected-access
        2020, 2, 13, 11, 43, 10, 123455
    )
    p._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    invoke_process_run_and_check_errors(p)

    expected_well_idx = 0
    test_value_1 = (
        FIFO_READ_PRODUCER_DATA_OFFSET
        + FIFO_READ_PRODUCER_WELL_AMPLITUDE
        * (expected_well_idx + 1)
        / 24
        * 6
        * signal.sawtooth(0 / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD, width=0.5)
    )
    expected_first_dict_sent = {
        "is_reference_sensor": False,
        "well_index": expected_well_idx,
        "data": np.array(
            [[0], [int(test_value_1) - RAW_TO_SIGNED_CONVERSION_VALUE]], dtype=np.int32
        ),
    }
    actual = board_queues[0][2].get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert (
        actual["is_reference_sensor"] == expected_first_dict_sent["is_reference_sensor"]
    )
    assert actual["well_index"] == expected_first_dict_sent["well_index"]
    np.testing.assert_equal(actual["data"], expected_first_dict_sent["data"])


@freeze_time("2020-02-13 11:43:11.123456")
def test_OkCommunicationProcess_commands_for_each_run_iteration__does_not_send_fifo_read_to_file_writer_if_not_ready_to_read():
    board_queues, error_queue = generate_board_and_error_queues(num_boards=4)
    test_bytearray = bytearray(DATA_FRAME_SIZE_WORDS * 4 * DATA_FRAMES_PER_ROUND_ROBIN)
    test_bytearray[:8] = build_header_magic_number_bytes(HEADER_MAGIC_NUMBER)
    fifo = Queue()
    fifo.put_nowait(test_bytearray)
    assert (
        is_queue_eventually_of_size(
            fifo, 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    simulator.start_acquisition()
    p = OkCommunicationProcess(board_queues, error_queue)
    p.set_board_connection(0, simulator)
    p._is_managed_acquisition_running[0] = True  # pylint:disable=protected-access
    p._time_of_last_fifo_read[0] = datetime.datetime(  # pylint:disable=protected-access
        2020, 2, 13, 11, 43, 10, 123456
    )
    p._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    invoke_process_run_and_check_errors(p)

    assert (
        is_queue_eventually_not_empty(
            board_queues[0][2], timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is False
    )


def test_OkCommunicationProcess_managed_acquisition__reads_at_least_one_prepopulated_simulated_fifo_read(
    four_board_comm_process,  # mocker
):
    # mocker.patch('builtins.print') # don't print all the debug messages to console
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    ok_process._logging_level = logging.DEBUG  # pylint:disable=protected-access

    board_queues[0][0].put_nowait(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    )
    fifo = Queue()
    fifo.put_nowait(produce_data(2, 0))
    assert (
        is_queue_eventually_of_size(
            fifo, 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}

    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    to_main_queue = board_queues[0][1]
    invoke_process_run_and_check_errors(ok_process)

    to_main_queue.get(
        timeout=QUEUE_CHECK_TIMEOUT_SECONDS
    )  # pop out the receipt of the command
    assert to_main_queue.empty()

    ok_process._time_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = datetime.datetime(year=2000, month=12, day=2)
    ok_process._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    invoke_process_run_and_check_errors(ok_process)

    words_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert "words in the FIFO" in words_msg["message"]
    about_to_read_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert "About to read from FIFO" in about_to_read_msg["message"]
    after_read_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert "After reading from FIFO" in after_read_msg["message"]
    size_msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert "576 bytes" in size_msg["message"]


def test_OkCommunicationProcess_managed_acquisition__handles_ignoring_first_data_cycle(
    four_board_comm_process,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    ok_process._logging_level = logging.DEBUG  # pylint:disable=protected-access

    board_queues[0][0].put_nowait(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    )
    fifo = Queue()
    fifo.put_nowait(produce_data(2, 0))
    assert (
        is_queue_eventually_of_size(
            fifo, 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}

    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    to_file_writer_queue = board_queues[0][2]
    invoke_process_run_and_check_errors(ok_process)

    ok_process._time_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = datetime.datetime(year=2000, month=12, day=2)
    ok_process._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    invoke_process_run_and_check_errors(ok_process)
    assert (
        ok_process._is_first_managed_read[0]  # pylint: disable=protected-access
        is False
    )

    expected_well_idx = 0
    test_value_1 = (
        FIFO_READ_PRODUCER_DATA_OFFSET
        + FIFO_READ_PRODUCER_WELL_AMPLITUDE
        * (expected_well_idx + 1)
        / 24
        * 6
        * signal.sawtooth(
            (ROUND_ROBIN_PERIOD // TIMESTEP_CONVERSION_FACTOR)
            / FIFO_READ_PRODUCER_SAWTOOTH_PERIOD,
            width=0.5,
        )
    )
    expected_first_dict_sent = {
        "is_reference_sensor": False,
        "well_index": expected_well_idx,
        "data": np.array(
            [
                [ROUND_ROBIN_PERIOD],
                [int(test_value_1) - RAW_TO_SIGNED_CONVERSION_VALUE],
            ],
            dtype=np.int32,
        ),
    }
    actual = to_file_writer_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert (
        actual["is_reference_sensor"] == expected_first_dict_sent["is_reference_sensor"]
    )
    assert actual["well_index"] == expected_first_dict_sent["well_index"]
    np.testing.assert_equal(actual["data"], expected_first_dict_sent["data"])


@pytest.mark.parametrize(
    """test_read,expected_error,is_read_convertable,test_description""",
    [
        (
            bytearray(
                [1] * DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN * 4 * 3
            ),
            InstrumentCommIncorrectHeaderError,
            True,
            "handles error correctly when no errors parsing into words",
        ),
        (
            bytearray(
                [1] * (DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN * 4 * 3 + 1)
            ),
            struct.error,
            False,
            "handles error correctly when error raised parsing into words",
        ),
        (
            bytearray(
                [1] * (DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN * 4 * 3 - 1)
            ),
            struct.error,
            False,
            "handles error correctly when error raised parsing into words",
        ),
    ],
)
def test_OkCommunicationProcess_managed_acquisition__logs_fifo_parsing_errors_and_attempts_word_conversion(
    test_read,
    expected_error,
    is_read_convertable,
    test_description,
    four_board_comm_process,
    mocker,
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    ok_process._logging_level = logging.DEBUG  # pylint:disable=protected-access

    board_queues[0][0].put_nowait(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    )
    assert (
        is_queue_eventually_of_size(
            board_queues[0][0], 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    fifo = Queue()
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}

    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    comm_to_main = board_queues[0][1]

    fifo.put_nowait(test_read)
    assert (
        is_queue_eventually_of_size(
            fifo, 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    invoke_process_run_and_check_errors(ok_process)
    comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # pop out init message
    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )

    ok_process._time_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = datetime.datetime(year=2000, month=12, day=2)
    ok_process._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    with pytest.raises(expected_error):
        invoke_process_run_and_check_errors(ok_process)
    assert (
        is_queue_eventually_not_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )

    for _ in range(10):
        comm_to_main.get(
            timeout=QUEUE_CHECK_TIMEOUT_SECONDS
        )  # pop expected log messages
        assert (
            is_queue_eventually_not_empty(
                comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
            )
            is True
        )

    assert (
        is_queue_eventually_not_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    fifo_read_msg = comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    first_managed_read_length = len(test_read) - (
        DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN * 4
    )
    assert f"{first_managed_read_length} bytes" in fifo_read_msg["message"]
    assert r"b'\x01\x01\x01\x01" in fifo_read_msg["message"]

    assert (
        is_queue_eventually_not_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    error_msg = comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert "InstrumentCommIncorrectHeaderError" in error_msg["message"]

    if is_read_convertable:
        assert (
            is_queue_eventually_not_empty(
                comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
            )
            is True
        )
        hex_words_msg = comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert "['0x1010101', '0x1010101'" in hex_words_msg["message"]

    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )


def test_OkCommunicationProcess_managed_acquisition__does_not_log_when_non_parsing_error_raised_after_first_managed_read(
    four_board_comm_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    ok_process._logging_level = logging.DEBUG  # pylint:disable=protected-access
    ok_process._data_frame_format = "fake_format"  # pylint:disable=protected-access

    board_queues[0][0].put_nowait(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    )
    fifo = Queue()
    fifo.put_nowait(produce_data(1, 0))
    assert (
        is_queue_eventually_of_size(
            fifo, 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}

    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    comm_to_main = board_queues[0][1]

    invoke_process_run_and_check_errors(ok_process)
    comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # pop out init message
    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )

    ok_process._time_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = datetime.datetime(year=2000, month=12, day=2)
    ok_process._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    ok_process._is_first_managed_read[0] = False  # pylint:disable=protected-access
    with pytest.raises(UnrecognizedDataFrameFormatNameError):
        invoke_process_run_and_check_errors(ok_process)

    for _ in range(6):
        assert (
            is_queue_eventually_not_empty(
                comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
            )
            is True
        )
        comm_to_main.get(
            timeout=QUEUE_CHECK_TIMEOUT_SECONDS
        )  # pop out expected log messages

    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )


def test_OkCommunicationProcess__raises_and_logs_error_if_first_managed_read_does_not_contain_at_least_one_round_robin(
    four_board_comm_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    test_bytearray = bytearray(0)
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    ok_process._logging_level = logging.DEBUG  # pylint:disable=protected-access

    board_queues[0][0].put_nowait(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    )
    fifo = Queue()
    fifo.put_nowait(test_bytearray)
    assert (
        is_queue_eventually_of_size(
            fifo, 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}

    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    comm_to_main = board_queues[0][1]

    invoke_process_run_and_check_errors(ok_process)
    comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # pop out init log message
    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )

    ok_process._time_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = datetime.datetime(year=2000, month=12, day=2)
    ok_process._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    with pytest.raises(FirstManagedReadLessThanOneRoundRobinError):
        invoke_process_run_and_check_errors(ok_process)
    assert (
        is_queue_eventually_not_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )

    for _ in range(4):
        comm_to_main.get(
            timeout=QUEUE_CHECK_TIMEOUT_SECONDS
        )  # pop out expected log messages
        assert (
            is_queue_eventually_not_empty(
                comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
            )
            is True
        )

    fifo_read_msg = comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert f"{len(test_bytearray)} bytes" in fifo_read_msg["message"]
    assert r"b''" in fifo_read_msg["message"]

    assert (
        is_queue_eventually_not_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    error_msg = comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert "FirstManagedReadLessThanOneRoundRobinError" in error_msg["message"]

    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )


def test_OkCommunicationProcess_managed_acquisition__logs_fifo_parsing_errors_and_attempts_word_conversion_of_first_round_robin(
    four_board_comm_process,
):
    test_read = bytearray([1] * DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN * 4)
    test_read.extend(produce_data(1, 12345))
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    ok_process._logging_level = logging.DEBUG  # pylint:disable=protected-access

    board_queues[0][0].put_nowait(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    )
    fifo = Queue()
    fifo.put_nowait(test_read)
    assert (
        is_queue_eventually_of_size(
            fifo, 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}

    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    comm_to_main = board_queues[0][1]

    invoke_process_run_and_check_errors(ok_process)

    comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # pop out init message
    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )

    ok_process._time_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = datetime.datetime(year=2000, month=12, day=2)
    ok_process._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    invoke_process_run_and_check_errors(ok_process)
    assert (
        is_queue_eventually_not_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )

    for _ in range(6):
        comm_to_main.get(
            timeout=QUEUE_CHECK_TIMEOUT_SECONDS
        )  # pop out expected log messages
        assert (
            is_queue_eventually_not_empty(
                comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
            )
            is True
        )

    fifo_read_msg = comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    first_round_robin_len = DATA_FRAME_SIZE_WORDS * DATA_FRAMES_PER_ROUND_ROBIN * 4
    assert f"{first_round_robin_len} bytes" in fifo_read_msg["message"]
    assert r"b'\x01\x01\x01\x01" in fifo_read_msg["message"]

    assert (
        is_queue_eventually_not_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    error_msg = comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert "InstrumentCommIncorrectHeaderError" in error_msg["message"]

    for _ in range(2):
        assert (
            is_queue_eventually_not_empty(
                comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
            )
            is True
        )
        comm_to_main.get(
            timeout=QUEUE_CHECK_TIMEOUT_SECONDS
        )  # pop out expected log messages

    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )


def test_OkCommunicationProcess_managed_acquisition__does_not_log_when_non_parsing_error_raised_with_first_round_robin(
    four_board_comm_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]

    ok_process._logging_level = logging.DEBUG  # pylint:disable=protected-access
    ok_process._data_frame_format = "fake_format"  # pylint:disable=protected-access

    board_queues[0][0].put_nowait(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    )
    assert (
        is_queue_eventually_of_size(
            board_queues[0][0], 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    fifo = Queue()
    fifo.put_nowait(produce_data(1, 0))
    assert (
        is_queue_eventually_of_size(
            fifo, 1, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}

    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    comm_to_main = board_queues[0][1]

    invoke_process_run_and_check_errors(ok_process)
    comm_to_main.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)  # pop out init message
    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )

    ok_process._time_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = datetime.datetime(year=2000, month=12, day=2)
    ok_process._timepoint_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = time.perf_counter()
    with pytest.raises(UnrecognizedDataFrameFormatNameError):
        invoke_process_run_and_check_errors(ok_process)

    for _ in range(6):
        assert (
            is_queue_eventually_not_empty(
                comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
            )
            is True
        )
        comm_to_main.get(
            timeout=QUEUE_CHECK_TIMEOUT_SECONDS
        )  # pop out expected log messages

    assert (
        is_queue_eventually_empty(
            comm_to_main, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )


# pylint: disable=too-many-locals
@pytest.mark.slow
def test_OkCommunicationProcess_managed_acquisition__logs_performance_metrics_after_appropriate_number_of_read_cycles(
    four_board_comm_process, mocker
):
    expected_idle_time = 1
    expected_start_timepoint = 7
    expected_stop_timepoint = 11
    expected_latest_percent_use = 100 * (
        1 - expected_idle_time / (expected_stop_timepoint - expected_start_timepoint)
    )
    expected_percent_use_values = [40.1, 67.8, expected_latest_percent_use]
    expected_longest_iterations = list(
        range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES - 1)
    )

    test_data_parse_dur_values = [
        0 for _ in range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES * 2)
    ]
    test_read_dur_values = [
        0 for _ in range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES * 2)
    ]
    for i in range(1, INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES * 2, 2):
        test_data_parse_dur_values[i] = i
        test_read_dur_values[i] = i // 2 + 1
    test_acquisition_values = [
        20 for _ in range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES)
    ]
    for i in range(1, INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES):
        test_acquisition_values[i] = test_acquisition_values[i - 1] + 10 * (i + 1)

    perf_counter_vals = list()
    for i in range(0, INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES * 2, 2):
        perf_counter_vals.append(test_read_dur_values[i])
        perf_counter_vals.append(test_read_dur_values[i + 1])
        perf_counter_vals.append(test_data_parse_dur_values[i])
        perf_counter_vals.append(test_data_parse_dur_values[i + 1])
        perf_counter_vals.append(test_acquisition_values[i // 2])
    mocker.patch.object(time, "perf_counter", side_effect=perf_counter_vals)
    mocker.patch.object(time, "perf_counter_ns", return_value=expected_stop_timepoint)
    mocker.patch.object(
        OkCommunicationProcess, "_is_ready_to_read_from_fifo", return_value=True
    )
    mocker.patch.object(
        parallelism_framework,
        "calculate_iteration_time_ns",
        autospec=True,
        side_effect=expected_longest_iterations,
    )

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    ok_process._time_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = datetime.datetime(2020, 5, 28, 12, 58, 0, 0)
    ok_process._timepoint_of_last_fifo_read[0] = 10  # pylint: disable=protected-access
    ok_process._idle_iteration_time_ns = (  # pylint: disable=protected-access
        expected_idle_time
    )
    ok_process._minimum_iteration_duration_seconds = (  # pylint: disable=protected-access
        0
    )
    ok_process._start_timepoint_of_last_performance_measurement = (  # pylint: disable=protected-access
        expected_start_timepoint
    )
    ok_process._percent_use_values = (  # pylint: disable=protected-access
        expected_percent_use_values[:-1]
    )

    test_fifo_reads = [
        produce_data(i + 2, 0)
        for i in range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES)
    ]
    fifo = Queue()
    for read in test_fifo_reads:
        fifo.put_nowait(read)
    confirm_queue_is_eventually_of_size(
        fifo,
        INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES,
        sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    board_queues[0][0].put_nowait(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    )
    confirm_queue_is_eventually_of_size(
        board_queues[0][0], 1, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )

    invoke_process_run_and_check_errors(
        ok_process, num_iterations=INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES
    )

    assert_queue_is_eventually_not_empty(board_queues[0][1])
    queue_items = drain_queue(board_queues[0][1])
    actual = queue_items[-1]
    assert "message" in actual
    actual = actual["message"]

    expected_num_bytes = [len(read) for read in test_fifo_reads]
    expected_parsing_dur_values = [
        i * 2 + 1 for i in range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES)
    ]
    expected_read_dur_values = [
        i + 1 for i in range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES)
    ]
    expected_acquisition_values = [
        10 * (i + 1) for i in range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES)
    ]
    assert actual["communication_type"] == "performance_metrics"
    assert "idle_iteration_time_ns" not in actual
    assert "start_timepoint_of_measurements" not in actual
    assert actual["fifo_read_num_bytes"] == {
        "max": max(expected_num_bytes),
        "min": min(expected_num_bytes),
        "stdev": round(stdev(expected_num_bytes), 6),
        "mean": round(sum(expected_num_bytes) / len(expected_num_bytes), 6),
    }
    assert actual["fifo_read_duration"] == {
        "max": max(expected_read_dur_values),
        "min": min(expected_read_dur_values),
        "stdev": round(stdev(expected_read_dur_values), 6),
        "mean": round(sum(expected_read_dur_values) / len(expected_read_dur_values), 6),
    }
    assert actual["duration_between_acquisition"] == {
        "max": max(expected_acquisition_values),
        "min": min(expected_acquisition_values),
        "stdev": round(stdev(expected_acquisition_values), 6),
        "mean": round(
            sum(expected_acquisition_values) / len(expected_acquisition_values), 6
        ),
    }
    assert actual["data_parsing_duration"] == {
        "max": max(expected_parsing_dur_values),
        "min": min(expected_parsing_dur_values),
        "stdev": round(stdev(expected_parsing_dur_values), 6),
        "mean": round(
            sum(expected_parsing_dur_values) / len(expected_parsing_dur_values), 6
        ),
    }
    assert actual["percent_use"] == expected_latest_percent_use
    assert actual["percent_use_metrics"] == {
        "max": max(expected_percent_use_values),
        "min": min(expected_percent_use_values),
        "stdev": round(stdev(expected_percent_use_values), 6),
        "mean": round(
            sum(expected_percent_use_values) / len(expected_percent_use_values), 6
        ),
    }
    num_longest_iterations = ok_process.num_longest_iterations
    assert (
        actual["longest_iterations"]
        == expected_longest_iterations[-num_longest_iterations:]
    )

    # Tanner (5/29/20): Closing a queue while it is not empty (especially when very full) causes BrokePipeErrors, so flushing it before the test ends prevents this
    drain_queue(board_queues[0][2])


@pytest.mark.slow
def test_OkCommunicationProcess_managed_acquisition__does_not_log_percent_use_metrics_in_first_logging_cycle(
    four_board_comm_process, mocker
):
    mocker.patch.object(
        OkCommunicationProcess, "_is_ready_to_read_from_fifo", return_value=True
    )

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    ok_process._time_of_last_fifo_read[  # pylint: disable=protected-access
        0
    ] = datetime.datetime(2020, 7, 3, 9, 25, 0, 0)
    ok_process._timepoint_of_last_fifo_read[0] = 10  # pylint: disable=protected-access
    ok_process._minimum_iteration_duration_seconds = (  # pylint: disable=protected-access
        0
    )

    fifo = Queue()
    for _ in range(INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES):
        fifo.put_nowait(produce_data(2, 0))
    confirm_queue_is_eventually_of_size(
        fifo,
        INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES,
        sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )
    queues = {"pipe_outs": {PIPE_OUT_FIFO: fifo}}
    simulator = FrontPanelSimulator(queues)
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)
    board_queues[0][0].put_nowait(
        get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION()
    )
    confirm_queue_is_eventually_of_size(
        board_queues[0][0], 1, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )

    invoke_process_run_and_check_errors(
        ok_process,
        num_iterations=INSTRUMENT_COMM_PERFOMANCE_LOGGING_NUM_CYCLES,
        perform_setup_before_loop=True,
    )

    assert_queue_is_eventually_not_empty(board_queues[0][1])
    queue_items = drain_queue(board_queues[0][1])
    actual = queue_items[-1]
    assert "message" in actual
    assert "percent_use_metrics" not in actual["message"]

    # Tanner (5/29/20): Closing a queue while it is not empty (especially when very full) causes BrokePipeErrors, so flushing it before the test ends prevents this
    drain_queue(board_queues[0][2])


# @pytest.mark.slow
# def test_OkCommunicationProcess_managed_acquisition__cpu_usage_is_less_than_80_percent(
#     mocker,
# ):
#     board_queues, error_queue = generate_board_and_error_queues()
#     input_queue = board_queues[0][0]

#     ok_process = OkCommunicationProcess(
#         board_queues, error_queue, suppress_setup_communication_to_main=True
#     )
#     simulator = RunningFIFOSimulator()
#     ok_process.set_board_connection(0, simulator)

#     # lowering this value so the test runs quicker
#     ok_process._performance_logging_cycles = 3  # pylint: disable=protected-access

#     input_queue.put_nowait(
#         {
#             "communication_type": "debug_console",
#             "command": "initialize_board",
#             "bit_file_name": None,
#         }
#     )
#     input_queue.put_nowait(get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION())
#     confirm_queue_is_eventually_of_size(input_queue, 2)
#     ok_process.start()
#     time.sleep(10)  # let ok_comm create performance logging message

#     input_queue.put_nowait(STOP_MANAGED_ACQUISITION_COMMUNICATION)
#     queue_items = ok_process.hard_stop()

#     items_to_main = queue_items["board_0"]["instrument_comm_to_main"]
#     for item in items_to_main:
#         if "message" not in item:
#             continue
#         if "communication_type" not in item["message"]:
#             continue
#         if item["message"]["communication_type"] == "performance_metrics":
#             assert item["message"]["percent_use"] < 80
#             break
#     else:
#         assert False, "No performance logging message was found"
