# -*- coding: utf-8 -*-
import _thread
from multiprocessing import Queue
import queue
import time

from mantarray_desktop_app import AttemptToAddCyclesWhileSPIRunningError
from mantarray_desktop_app import AttemptToInitializeFIFOReadsError
from mantarray_desktop_app import FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
from mantarray_desktop_app import FIFOReadProducer
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import RunningFIFOSimulator
import pytest
from stdlib_utils import TestingQueue
from xem_wrapper import FrontPanelBase
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import OpalKellyBoardNotInitializedError
from xem_wrapper import OpalKellyFileNotFoundError
from xem_wrapper import PIPE_OUT_FIFO

from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import is_queue_eventually_not_empty


@pytest.fixture(scope="function", name="fifo_simulator")
def fixture_fifo_simulator():
    simulator = RunningFIFOSimulator()
    yield simulator


def test_RunningFIFOSimulator__class_attributes():
    assert RunningFIFOSimulator.default_xem_serial_number == "1917000Q70"
    assert RunningFIFOSimulator.default_device_id == "M02001900Mantarray Simulator"
    assert RunningFIFOSimulator.default_mantarray_serial_number == "M02001900"
    assert RunningFIFOSimulator.default_mantarray_nickname == "Mantarray Simulator"
    assert RunningFIFOSimulator.default_firmware_version == "0.0.0"
    assert RunningFIFOSimulator.default_barcode == "ML2021001000"


def test_RunningFIFOSimulator__super_is_called_during_init(mocker):
    init_dict = {"wire_outs": {0: Queue()}}
    mocked_super_init = mocker.patch.object(FrontPanelSimulator, "__init__")
    RunningFIFOSimulator(init_dict)
    mocked_super_init.assert_called_once_with(init_dict)


def test_RunningFIFOSimulator__init__raises_error_if_fifo_dict_is_passed():
    init_dict = {"pipe_outs": {PIPE_OUT_FIFO: Queue()}}
    with pytest.raises(AttemptToInitializeFIFOReadsError):
        RunningFIFOSimulator(init_dict)


def test_RunningFIFOSimulator__super_is_called_with_empty_dict_if_no_simulated_response_queues_dict_given(
    mocker,
):
    expected_dict = {}
    mocked_super_init = mocker.patch.object(FrontPanelSimulator, "__init__")
    RunningFIFOSimulator()
    mocked_super_init.assert_called_once_with(expected_dict)


def test_RunningFIFOSimulator__init__sets_default_simulated_device_id(fifo_simulator):
    expected_id = RunningFIFOSimulator.default_device_id

    actual = fifo_simulator.get_device_id()
    assert actual == expected_id


def test_RunningFIFOSimulator__super_called_during_initialize_board_with_correct_args(mocker, fifo_simulator):
    mocked_super_init_board = mocker.spy(FrontPanelSimulator, "initialize_board")

    assert mocked_super_init_board.call_count == 0

    fifo_simulator.initialize_board()
    mocked_super_init_board.assert_called_once_with(
        fifo_simulator,
        bit_file_name=None,
        allow_board_reinitialization=False,
    )


def test_RunningFIFOSimulator__raises_error_if_bit_file_is_given_that_cannot_be_found(
    fifo_simulator,
):
    with pytest.raises(OpalKellyFileNotFoundError):
        fifo_simulator.initialize_board(bit_file_name="fake.bit")


def test_RunningFIFOSimulator__allows_board_reinitialization_with_kwarg(mocker, fifo_simulator):
    mocked_super_init_board = mocker.spy(FrontPanelSimulator, "initialize_board")

    fifo_simulator.initialize_board()
    assert mocked_super_init_board.call_count == 1

    fifo_simulator.initialize_board(allow_board_reinitialization=True)
    mocked_super_init_board.assert_called_with(
        fifo_simulator, bit_file_name=None, allow_board_reinitialization=True
    )


def test_RunningFIFOSimulator__initialize_board__creates_threading_utils(
    fifo_simulator,
):
    fifo_simulator.initialize_board()

    producer_error_queue = fifo_simulator._producer_error_queue
    producer_data_queue = fifo_simulator._producer_data_queue
    lock = fifo_simulator._lock

    assert isinstance(producer_error_queue, queue.Queue)
    assert isinstance(producer_data_queue, queue.Queue)
    assert isinstance(lock, _thread.LockType)


def test_RunningFIFOSimulator__initialize_board__does_not_recreate_threading_utils_when_reinitializing(
    fifo_simulator,
):
    fifo_simulator.initialize_board()

    producer_error_queue_1 = fifo_simulator._producer_error_queue
    producer_data_queue_1 = fifo_simulator._producer_data_queue
    lock_1 = fifo_simulator._lock

    fifo_simulator.initialize_board(allow_board_reinitialization=True)

    producer_error_queue_2 = fifo_simulator._producer_error_queue
    producer_data_queue_2 = fifo_simulator._producer_data_queue
    lock_2 = fifo_simulator._lock

    assert producer_error_queue_1 is producer_error_queue_2
    assert producer_data_queue_1 is producer_data_queue_2
    assert lock_1 is lock_2


def test_RunningFIFOSimulator__super_called_during_start_spi_acquisition(mocker):
    # patch to speed up test
    mocker.patch.object(FIFOReadProducer, "start", autospec=True)

    spied_super_start = mocker.spy(FrontPanelSimulator, "start_acquisition")
    fifo_simulator = RunningFIFOSimulator()
    fifo_simulator.initialize_board()
    assert spied_super_start.call_count == 0

    fifo_simulator.start_acquisition()
    assert spied_super_start.call_count == 1


def test_RunningFIFOSimulator__start_spi_acquisition_creates_and_starts_fifo_read_thread(
    fifo_simulator,
):
    fifo_simulator.initialize_board()
    fifo_simulator.start_acquisition()
    producer_thread = fifo_simulator._fifo_read_producer
    assert producer_thread.is_alive() is True

    producer_thread.soft_stop()
    producer_thread.join()


def test_RunningFIFOSimulator__queue_from_read_producer_gets_populated_after_starting_spi(
    fifo_simulator,
):
    fifo_simulator.initialize_board()
    queue_from_read_producer = fifo_simulator._producer_data_queue

    confirm_queue_is_eventually_empty(queue_from_read_producer)
    fifo_simulator.start_acquisition()
    assert is_queue_eventually_not_empty(queue_from_read_producer) is True

    fifo_simulator.stop_acquisition()


def test_RunningFIFOSimulator__super_called_during_stop_spi_acquisition(mocker, fifo_simulator):
    mocked_super_stop = mocker.spy(FrontPanelSimulator, "stop_acquisition")
    fifo_simulator.initialize_board()
    fifo_simulator.start_acquisition()
    assert mocked_super_stop.call_count == 0

    fifo_simulator.stop_acquisition()
    assert mocked_super_stop.call_count == 1


def test_RunningFIFOSimulator__stop_spi_acquisition__stops_and_joins_fifo_read_thread__then_sets_to_None(
    mocker, fifo_simulator
):
    fifo_simulator.initialize_board()
    fifo_simulator.start_acquisition()
    running_producer_thread = fifo_simulator._fifo_read_producer
    producer_queue = fifo_simulator._producer_data_queue
    spied_is_stopped = mocker.spy(running_producer_thread, "is_stopped")

    fifo_simulator.stop_acquisition()
    stopped_producer_thread = fifo_simulator._fifo_read_producer

    assert spied_is_stopped.call_count > 0
    assert producer_queue.empty() is True
    assert stopped_producer_thread is None


def test_RunningFIFOSimulator__read_from_fifo__reads_all_data_from_input_data_queue(
    fifo_simulator,
):
    fifo_simulator.initialize_board()
    fifo_simulator.start_acquisition()
    fifo_simulator.stop_acquisition()
    fifo_simulator.read_from_fifo()

    queue_from_read_producer = fifo_simulator._producer_data_queue
    confirm_queue_is_eventually_empty(queue_from_read_producer)


@pytest.mark.parametrize(
    """test_sleep_time,test_description""",
    [
        (0.1, "returns correct num words after sleeping 100 ms"),
        (0.2, "returns correct num words after sleeping 200 ms"),
        (0.3, "returns correct num words after sleeping 300 ms"),
    ],
)
def test_RunningFIFOSimulator__read_from_fifo__returns_all_data_from_producer_as_single_bytearray(
    test_sleep_time, test_description, fifo_simulator
):
    fifo_simulator.initialize_board()
    fifo_simulator.start_acquisition()
    time.sleep(test_sleep_time)
    fifo_simulator.stop_acquisition()

    expected_num_bytes = fifo_simulator.get_num_words_fifo() * 4

    data_read = fifo_simulator.read_from_fifo()
    assert len(data_read) == expected_num_bytes


def test_RunningFIFOSimulator__FPBase_get_called_during_get_num_words_fifo(mocker, fifo_simulator):
    mocked_base_get = mocker.spy(FrontPanelBase, "get_num_words_fifo")
    fifo_simulator.initialize_board()
    assert mocked_base_get.call_count == 0

    fifo_simulator.get_num_words_fifo()
    assert mocked_base_get.call_count == 1


def test_RunningFIFOSimulator__get_num_words_fifo_returns_correct_values(
    fifo_simulator,
):
    fifo_simulator.initialize_board()
    fifo_simulator.start_acquisition()
    time.sleep(0.5)
    fifo_simulator.stop_acquisition()

    actual = fifo_simulator.get_num_words_fifo()
    expected_num_words = len(fifo_simulator.read_from_fifo()) // 4
    assert actual == expected_num_words


def test_RunningFIFOSimulator__add_data_cycles__raises_error_if_not_initialized(
    fifo_simulator,
):
    with pytest.raises(OpalKellyBoardNotInitializedError):
        fifo_simulator.add_data_cycles(1)


def test_RunningFIFOSimulator__add_data_cycles__raises_error_if_spi_running(
    fifo_simulator,
):
    fifo_simulator.initialize_board()
    fifo_simulator.start_acquisition()
    with pytest.raises(AttemptToAddCyclesWhileSPIRunningError):
        fifo_simulator.add_data_cycles(1)

    producer_thread = fifo_simulator._fifo_read_producer
    producer_thread.soft_stop()
    producer_thread.join()


@pytest.mark.parametrize(
    """test_num_cycles,test_description""",
    [
        (0, "adds correct bytearray given 0 cycles"),
        (1, "adds correct bytearray given 1 cycle"),
        (10, "adds correct bytearray given 10 cycles"),
    ],
)
def test_RunningFIFOSimulator__add_data_cycles__adds_correct_bytearray_to_fifo(
    test_num_cycles, test_description, fifo_simulator
):
    fifo_simulator.initialize_board()
    fifo_simulator.add_data_cycles(test_num_cycles)

    expected_bytearray = produce_data(test_num_cycles, 0)

    actual = fifo_simulator.read_from_fifo()
    assert actual == expected_bytearray


def test_RunningFIFOSimulator__read_wire_out__raises_error_error_if_not_initialized(
    fifo_simulator,
):
    with pytest.raises(OpalKellyBoardNotInitializedError):
        fifo_simulator.read_wire_out(0x00)


def test_RunningFIFOSimulator__read_wire_out__returns_default_value_if_no_wire_out_queues_given(
    fifo_simulator,
):
    fifo_simulator.initialize_board()

    actual = fifo_simulator.read_wire_out(0x00)
    assert actual == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE


def test_RunningFIFOSimulator__read_wire_out__returns_default_value_if_no_wire_out_queue_for_ep_addr_given():
    wire_outs = {0: TestingQueue()}
    fifo_simulator = RunningFIFOSimulator({"wire_outs": wire_outs})
    fifo_simulator.initialize_board()

    actual = fifo_simulator.read_wire_out(0x01)
    assert actual == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE


def test_RunningFIFOSimulator__read_wire_out__returns_default_value_if_wire_out_queue_of_ep_addr_is_empty():
    wire_outs = {0: TestingQueue()}
    fifo_simulator = RunningFIFOSimulator({"wire_outs": wire_outs})
    fifo_simulator.initialize_board()

    actual = fifo_simulator.read_wire_out(0x00)
    assert actual == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE


def test_RunningFIFOSimulator__read_wire_out__returns_expected_values_from_populated_wire_out():
    expected_first_read = 1
    wire_out_queue = TestingQueue()
    wire_out_queue.put_nowait(expected_first_read)
    confirm_queue_is_eventually_of_size(wire_out_queue, 1)
    wire_outs = {0: wire_out_queue}
    fifo_simulator = RunningFIFOSimulator({"wire_outs": wire_outs})
    fifo_simulator.initialize_board()

    actual_1 = fifo_simulator.read_wire_out(0x00)
    assert actual_1 == expected_first_read
    confirm_queue_is_eventually_empty(wire_out_queue)
    actual_2 = fifo_simulator.read_wire_out(0x00)
    assert actual_2 == FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE


def test_RunningFIFOSimulator__get_firmware_version__raises_error_if_board_not_initialized(
    fifo_simulator,
):
    with pytest.raises(OpalKellyBoardNotInitializedError):
        fifo_simulator.get_firmware_version()


def test_RunningFIFOSimulator__get_firmware_version__returns_correct_value(
    fifo_simulator,
):
    fifo_simulator.initialize_board()
    assert fifo_simulator.get_firmware_version() == RunningFIFOSimulator.default_firmware_version


def test_RunningFIFOSimulator__can_be_started_and_restarted(fifo_simulator):
    fifo_simulator.initialize_board()

    fifo_simulator.start_acquisition()
    assert fifo_simulator.is_spi_running() is True
    time.sleep(1)
    fifo_simulator.stop_acquisition()
    assert fifo_simulator.is_spi_running() is False

    fifo_simulator.start_acquisition()
    assert fifo_simulator.is_spi_running() is True
    time.sleep(1)
    fifo_simulator.stop_acquisition()
    assert fifo_simulator.is_spi_running() is False

    # clean up
    fifo_simulator.hard_stop()


def test_RunningFIFOSimulator_hard_stop__hard_stops_the_read_producer_during_managed_acquisition(
    mocker, fifo_simulator
):
    # patch to speed up test
    mocker.patch.object(FIFOReadProducer, "start", autospec=True)

    fifo_simulator.initialize_board()
    fifo_simulator.start_acquisition()

    spied_producer_hard_stop = mocker.patch.object(
        fifo_simulator._fifo_read_producer,  # Eli (10/27/20): it is important to confirm this is stopped, but it seems odd to provide public access to this
        "hard_stop",
        autospec=True,
    )
    fifo_simulator.hard_stop()

    assert spied_producer_hard_stop.call_count == 1


def test_RunningFIFOSimulator_hard_stop__passes_timeout_kwarg_to_read_producer(mocker, fifo_simulator):
    # patch to speed up test
    mocker.patch.object(FIFOReadProducer, "start", autospec=True)

    fifo_simulator.initialize_board()
    fifo_simulator.start_acquisition()

    spied_producer_hard_stop = mocker.patch.object(
        fifo_simulator._fifo_read_producer,  # Eli (10/27/20): it is important to confirm this is stopped, but it seems odd to provide public access to this
        "hard_stop",
        autospec=True,
    )
    expected_timeout = 1.21
    fifo_simulator.hard_stop(timeout=expected_timeout)

    spied_producer_hard_stop.assert_called_once_with(timeout=expected_timeout)


def test_RunningFIFOSimulator_hard_stop__drains_wire_out_queues(mocker):

    wire_out_queue = TestingQueue()
    wire_out_queue.put_nowait(1)
    confirm_queue_is_eventually_of_size(wire_out_queue, 1)
    wire_out_queue_2 = TestingQueue()
    wire_out_queue_2.put_nowait(2)
    confirm_queue_is_eventually_of_size(wire_out_queue_2, 1)
    wire_outs = {0: wire_out_queue, 7: wire_out_queue_2}
    fifo_simulator = RunningFIFOSimulator({"wire_outs": wire_outs})

    fifo_simulator.hard_stop()

    confirm_queue_is_eventually_empty(wire_out_queue)
    confirm_queue_is_eventually_empty(wire_out_queue_2)


def test_RunningFIFOSimulator__get_barcode__raises_error_if_board_not_initialized():
    simulator = RunningFIFOSimulator()
    with pytest.raises(OpalKellyBoardNotInitializedError):
        simulator.get_barcode()


def test_RunningFIFOSimulator__get_barcode__returns_correct_value():
    simulator = RunningFIFOSimulator()
    simulator.initialize_board()
    assert simulator.get_barcode() == RunningFIFOSimulator.default_barcode
