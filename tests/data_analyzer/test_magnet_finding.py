# -*- coding: utf-8 -*-
import json

from mantarray_desktop_app import MICRO_TO_BASE_CONVERSION
from mantarray_desktop_app.constants import RECORDING_SNAPSHOT_DUR_SECS
from mantarray_desktop_app.exceptions import UnrecognizedCommandFromMainToDataAnalyzerError
from mantarray_desktop_app.sub_processes import data_analyzer
from mantarray_desktop_app.workers import magnet_finder
from mantarray_desktop_app.workers.magnet_finder import run_magnet_finding_alg
from mantarray_magnet_finding.exceptions import UnableToConvergeError
import numpy as np
import pandas as pd
import pytest
from stdlib_utils import confirm_queue_is_eventually_empty
from stdlib_utils import confirm_queue_is_eventually_of_size
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import put_object_into_queue_and_raise_error_if_eventually_still_empty

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_data_analyzer import fixture_four_board_analyzer_process_beta_2_mode
from ..fixtures_data_analyzer import TEST_START_MAG_ANALYSIS_COMMAND
from ..fixtures_data_analyzer import TEST_START_RECORDING_SNAPSHOT_COMMAND


__fixtures__ = [fixture_patch_print, fixture_four_board_analyzer_process_beta_2_mode]


def test_DataAnalyzerProcess__processes_start_mag_analysis_command_correctly(
    four_board_analyzer_process_beta_2_mode, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]

    spied_thread_init = mocker.spy(data_analyzer.ErrorCatchingThread, "__init__")
    mocked_thread_start = mocker.patch.object(data_analyzer.ErrorCatchingThread, "start", autospec=True)
    # mock so thread will not appear complete
    mocker.patch.object(data_analyzer.ErrorCatchingThread, "is_alive", autospec=True, return_value=True)

    # send command to da_process
    test_command = dict(TEST_START_MAG_ANALYSIS_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, from_main_queue)

    # run first iteration and make sure command response not sent to main
    invoke_process_run_and_check_errors(da_process)
    spied_thread_init.assert_called_once_with(
        mocker.ANY,  # this is the actual thread instance
        target=run_magnet_finding_alg,
        args=(
            da_process._mag_finder_thread_dict,
            test_command["recordings"],
            da_process._mag_finder_output_dir,
        ),
    )
    mocked_thread_start.assert_called_once()


@pytest.mark.parametrize("failed_recordings", [None, ["test/recording/1", "test/recording/2"]])
def test_DataAnalyzerProcess__handles_successful_completion_of_magnet_finder_worker_thread(
    four_board_analyzer_process_beta_2_mode, failed_recordings, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    to_main_queue = four_board_analyzer_process_beta_2_mode["to_main_queue"]

    def init_se(obj, target, args):
        if failed_recordings:
            args[0].update({"failed_recordings": failed_recordings})
        obj.error = None

    # mock init so it populates output dict immediately
    mocker.patch.object(data_analyzer.ErrorCatchingThread, "__init__", autospec=True, side_effect=init_se)
    mocked_start = mocker.patch.object(data_analyzer.ErrorCatchingThread, "start", autospec=True)
    # mock so thread will appear complete on the second iteration of da_process
    mocker.patch.object(
        data_analyzer.ErrorCatchingThread, "is_alive", autospec=True, side_effect=[True, False]
    )
    mocked_join = mocker.patch.object(
        data_analyzer.ErrorCatchingThread, "join", autospec=True, side_effect=[True, False]
    )

    # send command to da_process
    test_command = dict(TEST_START_MAG_ANALYSIS_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, from_main_queue)

    # run first iteration and make sure command response not sent to main
    invoke_process_run_and_check_errors(da_process)
    mocked_start.assert_called_once()
    mocked_join.assert_not_called()
    confirm_queue_is_eventually_empty(to_main_queue)
    # run second iteration and make sure correct command response sent to main
    invoke_process_run_and_check_errors(da_process)
    mocked_start.assert_called_once()
    mocked_join.assert_called_once()
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)

    expected_result_dict = {
        "recordings": test_command["recordings"],
        "output_dir": da_process._mag_finder_output_dir,
    }
    if failed_recordings:
        expected_result_dict.update({"failed_recordings": failed_recordings})

    assert command_response == {
        "communication_type": "mag_analysis_complete",
        "content": {"data_type": "local_analysis", "data_json": json.dumps(expected_result_dict)},
    }


def test_DataAnalyzerProcess__correctly_handles_recording_snapshot_command(
    four_board_analyzer_process_beta_2_mode, mocker
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    to_main_queue = four_board_analyzer_process_beta_2_mode["to_main_queue"]

    test_timepoints = np.arange(10000, 2 * MICRO_TO_BASE_CONVERSION, 10000)
    test_timepoints[-1] = 2
    mocked_df = dict({"Time (s)": pd.Series(test_timepoints)})
    for well in range(24):
        mocked_df[str(well)] = pd.Series(test_timepoints)
    time_force_df = pd.DataFrame(mocked_df)

    mocked_run_alg = mocker.patch.object(
        data_analyzer, "run_magnet_finding_alg", autospec=True, return_value=[time_force_df]
    )

    test_command = dict(TEST_START_RECORDING_SNAPSHOT_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, from_main_queue)
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg["communication_type"] == "mag_analysis_complete"
    assert msg["content"]["data_type"] == "recording_snapshot_data"
    parsed_data = json.loads(msg["content"]["data_json"])
    for force_data in parsed_data["force"]:
        assert len(parsed_data["time"]) == len(force_data)

    mocked_run_alg.assert_called_once_with(
        {}, [test_command["recording_path"]], end_time=RECORDING_SNAPSHOT_DUR_SECS
    )


@pytest.mark.parametrize(
    "exception,err_message",
    [
        [Exception, "Something went wrong"],
        [UnableToConvergeError, "Unable to process recording due to low quality calibration and/or noise"],
    ],
)
def test_DataAnalyzerProcess__correctly_handles_recording_snapshot_errors(
    four_board_analyzer_process_beta_2_mode, mocker, exception, err_message
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]
    to_main_queue = four_board_analyzer_process_beta_2_mode["to_main_queue"]

    mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    mocker.patch.object(magnet_finder, "PlateRecording", side_effect=exception())

    test_command = dict(TEST_START_RECORDING_SNAPSHOT_COMMAND)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_command, from_main_queue)
    invoke_process_run_and_check_errors(da_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    msg = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg["communication_type"] == "mag_analysis_complete"
    assert msg["content"]["data_type"] == "recording_snapshot_data"
    parsed_data = json.loads(msg["content"]["data_json"])

    assert parsed_data["error"] == err_message


def test_DataAnalyzerProcess__raises_error_when_receiving_unrecognized_mag_finding_analysis_command(
    four_board_analyzer_process_beta_2_mode, patch_print
):
    da_process = four_board_analyzer_process_beta_2_mode["da_process"]
    from_main_queue = four_board_analyzer_process_beta_2_mode["from_main_queue"]

    expected_command = "fake_command"
    test_comm = {"communication_type": "mag_finding_analysis", "command": expected_command}

    put_object_into_queue_and_raise_error_if_eventually_still_empty(test_comm, from_main_queue)
    with pytest.raises(UnrecognizedCommandFromMainToDataAnalyzerError, match=expected_command):
        invoke_process_run_and_check_errors(da_process)
