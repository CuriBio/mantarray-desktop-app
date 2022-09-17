# -*- coding: utf-8 -*-
import os

from mantarray_desktop_app.workers import magnet_finder
from mantarray_desktop_app.workers.magnet_finder import run_magnet_finding_alg
import numpy as np
import pytest


@pytest.mark.parametrize("output_dir", [None, "test/dir"])
def test_run_magnet_finding_alg__copies_each_recording_to_a_temporary_directory(output_dir, mocker):
    mocked_copy = mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    spied_temp_dir = mocker.spy(magnet_finder.tempfile, "TemporaryDirectory")
    mocker.patch.object(magnet_finder, "PlateRecording", autospec=True)

    test_recordings = [f"rec{i}" for i in range(3)]
    test_recording_paths = [f"path/to/{rec}" for rec in test_recordings]

    run_magnet_finding_alg({}, test_recording_paths, output_dir)

    tmpdir = spied_temp_dir.spy_return.name
    assert mocked_copy.call_args_list == [
        mocker.call(rec_path, os.path.join(tmpdir, rec_name))
        for rec_name, rec_path in zip(test_recordings, test_recording_paths)
    ]


@pytest.mark.parametrize("output_dir", [None, "test/dir"])
@pytest.mark.parametrize("end_time", [None, 5])
def test_run_magnet_finding_alg__creates_force_output_correctly(output_dir, end_time, mocker):
    mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    spied_temp_dir = mocker.spy(magnet_finder.tempfile, "TemporaryDirectory")
    mocked_pr = mocker.patch.object(magnet_finder, "PlateRecording", autospec=True)

    test_recordings = [f"rec{i}" for i in range(3)]
    test_recording_paths = [f"path/to/{rec}" for rec in test_recordings]

    args = [{}, test_recording_paths, output_dir]
    if end_time:
        args.append(end_time)

    run_magnet_finding_alg(*args)

    tmpdir = spied_temp_dir.spy_return.name
    expected_end_time = end_time if end_time else np.inf
    assert mocked_pr.call_args_list == [
        mocker.call(os.path.join(tmpdir, rec_name), end_time=expected_end_time)
        for rec_name in test_recordings
    ]


@pytest.mark.parametrize("output_dir", [None, "test/dir"])
def test_run_magnet_finding_alg__only_returns_dataframes_if_no_output_dir_is_given(output_dir, mocker):
    mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    mocked_pr = mocker.patch.object(magnet_finder, "PlateRecording", autospec=True)

    test_recording_paths = [f"path/to/rec{i}" for i in range(3)]

    expected_dfs = []

    def write_time_force_csv_se(*args):
        df = mocker.MagicMock()
        if not output_dir:
            expected_dfs.append(df)
        return df, None

    mocked_pr.return_value.write_time_force_csv.side_effect = write_time_force_csv_se

    actual_dfs = run_magnet_finding_alg({}, test_recording_paths, output_dir)

    # first make sure the list is populated or not correctly since the next assertion will always pass if the list doesn't get populated correctly and stays empty
    expected_num_dfs = 0 if output_dir else len(test_recording_paths)
    assert len(actual_dfs) == expected_num_dfs
    # not that size has been confirmed, make sure the contents are correct
    assert actual_dfs == expected_dfs


@pytest.mark.parametrize("failure", [True, False])
def test_run_magnet_finding_alg__handles_failed_recordings_correctly(failure, mocker):
    mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    mocked_pr = mocker.patch.object(magnet_finder, "PlateRecording", autospec=True)

    test_recordings = [f"rec{i}" for i in range(3)]
    test_recording_paths = [f"path/to/{rec}" for rec in test_recordings]
    test_error = Exception("err")

    recording_iter = iter(test_recordings)

    def write_time_force_csv_se(*args):
        # make the second recording error
        if "1" in next(recording_iter) and failure:
            raise test_error
        return mocker.MagicMock(), None

    mocked_pr.return_value.write_time_force_csv.side_effect = write_time_force_csv_se

    result_dict = {}
    run_magnet_finding_alg(result_dict, test_recording_paths, "")

    if failure:
        assert result_dict["failed_recordings"] == [{"name": test_recordings[1], "error": repr(test_error)}]
    else:
        assert "failed_recordings" not in result_dict
