# -*- coding: utf-8 -*-
from multiprocessing import Queue as MPQueue
import os
import tempfile

from immutabledict import immutabledict
from mantarray_desktop_app import DataAnalyzerProcess
from mantarray_desktop_app import START_MANAGED_ACQUISITION_COMMUNICATION
from mantarray_desktop_app.simulators.mc_simulator import MantarrayMcSimulator
import pytest
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import TestingQueue

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

TEST_REC_DIR_PATH = os.path.join("recordings", "ML2021172153__2022_01_21_023323")

TEST_START_MAG_ANALYSIS_COMMAND = immutabledict(
    {
        "communication_type": "mag_finding_analysis",
        "command": "start_mag_analysis",
        "recordings": [TEST_REC_DIR_PATH, TEST_REC_DIR_PATH],
    }
)
TEST_START_RECORDING_SNAPSHOT_COMMAND = immutabledict(
    {
        "communication_type": "mag_finding_analysis",
        "command": "start_recording_snapshot",
        "recording_path": TEST_REC_DIR_PATH,
    }
)

TEST_START_MANAGED_ACQUISITION_COMMUNICATION = immutabledict(
    {**START_MANAGED_ACQUISITION_COMMUNICATION, "barcode": MantarrayMcSimulator.default_plate_barcode}
)


def set_sampling_period(da_fixture, sampling_period):
    da_process = da_fixture["da_process"]
    from_main_queue = da_fixture["from_main_queue"]
    to_main_queue = da_fixture["to_main_queue"]

    set_sampling_period_command = {
        "communication_type": "acquisition_manager",
        "command": "set_sampling_period",
        "sampling_period": sampling_period,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        set_sampling_period_command, from_main_queue
    )
    invoke_process_run_and_check_errors(da_process)
    # remove message to main
    to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)


@pytest.fixture(scope="function", name="four_board_analyzer_process")
def fixture_four_board_analyzer_process():
    num_boards = 4
    comm_from_main_queue = TestingQueue()
    comm_to_main_queue = TestingQueue()
    error_queue = TestingQueue()
    board_queues = tuple(
        (
            (
                TestingQueue(),
                TestingQueue(),
            )
            # pylint: disable=duplicate-code
            for _ in range(num_boards)
        )
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = DataAnalyzerProcess(
            board_queues,
            comm_from_main_queue,
            comm_to_main_queue,
            error_queue,
            mag_analysis_output_dir=tmp_dir,
        )
        yield p, board_queues, comm_from_main_queue, comm_to_main_queue, error_queue, tmp_dir


@pytest.fixture(scope="function", name="four_board_analyzer_process_beta_2_mode")
def fixture_four_board_analyzer_process_beta_2_mode():
    num_boards = 4
    comm_from_main_queue = TestingQueue()
    comm_to_main_queue = TestingQueue()
    error_queue = TestingQueue()
    board_queues = tuple((TestingQueue(), TestingQueue()) for _ in range(num_boards))

    with tempfile.TemporaryDirectory() as tmp_dir:
        da_process = DataAnalyzerProcess(
            board_queues,
            comm_from_main_queue,
            comm_to_main_queue,
            error_queue,
            mag_analysis_output_dir=os.path.join(tmp_dir, "time_force_data"),
            beta_2_mode=True,
        )
        da_items_dict = {
            "da_process": da_process,
            "board_queues": board_queues,
            "from_main_queue": comm_from_main_queue,
            "to_main_queue": comm_to_main_queue,
            "mag_analysis_output_dir": os.path.join(tmp_dir, "time_force_data"),
            "error_queue": error_queue,
        }
        yield da_items_dict


@pytest.fixture(scope="function", name="runnable_four_board_analyzer_process")
def fixture_runnable_four_board_analyzer_process():
    num_boards = 4
    comm_from_main_queue = MPQueue()
    comm_to_main_queue = MPQueue()
    error_queue = MPQueue()
    board_queues = tuple(
        (
            (
                MPQueue(),
                MPQueue(),
            )
            # pylint: disable=duplicate-code
            for _ in range(num_boards)
        )
    )
    with tempfile.TemporaryDirectory() as tmp_dir:

        p = DataAnalyzerProcess(
            board_queues,
            comm_from_main_queue,
            comm_to_main_queue,
            error_queue,
            mag_analysis_output_dir=tmp_dir,
        )
        yield p, board_queues, comm_from_main_queue, comm_to_main_queue, error_queue, tmp_dir
