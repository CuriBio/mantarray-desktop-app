# -*- coding: utf-8 -*-
import os

from mantarray_desktop_app.workers import magnet_finder
from mantarray_desktop_app.workers.magnet_finder import run_magnet_finding_alg
from mantarray_magnet_finding.exceptions import UnableToConvergeError
import pandas as pd
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
    assert mocked_pr.call_args_list == [
        mocker.call(os.path.join(tmpdir, rec_name), end_time=end_time) for rec_name in test_recordings
    ]


@pytest.mark.parametrize("output_dir", [None, "test/dir"])
def test_run_magnet_finding_alg__only_returns_dataframes_if_no_output_dir_is_given(output_dir, mocker):
    mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    mocked_pr = mocker.patch.object(magnet_finder, "PlateRecording", autospec=True)

    test_recording_paths = [f"path/to/rec{i}" for i in range(3)]
    mocked_df = mocker.MagicMock()

    def to_dataframe_se(*args, **kwargs):
        return mocked_df

    mocked_pr.return_value.to_dataframe.side_effect = to_dataframe_se

    actual_dfs = run_magnet_finding_alg({}, test_recording_paths, output_dir)

    # first make sure the list is populated or not correctly since the next assertion will always pass if the list doesn't get populated correctly and stays empty
    expected_num_dfs = 0 if output_dir else len(test_recording_paths)
    assert len(actual_dfs) == expected_num_dfs
    # not that size has been confirmed, make sure the contents are correct
    expected_dfs = [] if output_dir else [mocked_df] * len(test_recording_paths)
    assert actual_dfs == expected_dfs

    assert mocked_pr.return_value.to_dataframe.call_args_list == [mocker.call(include_stim_data=False)] * len(
        test_recording_paths
    )


def test_run_magnet_finding_alg__removes_unnecessary_columns_from_returned_dataframe(mocker):
    mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    mocked_pr = mocker.patch.object(magnet_finder, "PlateRecording", autospec=True)

    test_recording_paths = [f"path/to/rec{i}" for i in range(3)]
    mocked_df = pd.DataFrame({"Time (s)": [1], "Stim Time": [2], "A1": [3], "A1__raw": [4], "A1__stim": [5]})

    def to_dataframe_se(*args, **kwargs):
        return mocked_df

    mocked_pr.return_value.to_dataframe.side_effect = to_dataframe_se

    actual_dfs = run_magnet_finding_alg({}, test_recording_paths)
    # confirm precondition
    assert len(actual_dfs) == len(test_recording_paths)

    for i, df in enumerate(actual_dfs):
        assert list(df.columns) == ["Time (s)", "A1"], i


def test_run_magnet_finding_alg__removes_NaN_values_from_returned_dataframe(mocker):
    mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    mocked_pr = mocker.patch.object(magnet_finder, "PlateRecording", autospec=True)

    mocked_df = mocker.MagicMock()

    # dropna must be called after drop
    def dropna_se(*args, **kwargs):
        mocked_df.drop.assert_called()

    mocked_df.dropna.side_effect = dropna_se

    def to_dataframe_se(*args, **kwargs):
        return mocked_df

    mocked_pr.return_value.to_dataframe.side_effect = to_dataframe_se

    result_dict = {}
    run_magnet_finding_alg(result_dict, ["path/to/rec"])

    if failed_recordings := result_dict.get("failed_recordings"):
        assert False, failed_recordings[0]["error"]

    mocked_df.dropna.assert_called_once_with(inplace=True)


@pytest.mark.parametrize("failure", [True, False])
def test_run_magnet_finding_alg__handles_failed_recordings_correctly(failure, mocker):
    mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    mocked_pr = mocker.patch.object(magnet_finder, "PlateRecording", autospec=True)

    test_recordings = [f"rec{i}" for i in range(3)]
    test_recording_paths = [f"path/to/{rec}" for rec in test_recordings]
    test_error = Exception("err")

    recording_iter = iter(test_recordings)

    def to_dataframe_se(*args, **kwargs):
        # make the second recording error
        if "1" in next(recording_iter) and failure:
            raise test_error
        return mocker.MagicMock()

    mocked_pr.return_value.to_dataframe.side_effect = to_dataframe_se

    result_dict = {}
    run_magnet_finding_alg(result_dict, test_recording_paths, "")

    if failure:
        assert result_dict["failed_recordings"] == [
            {"name": test_recordings[1], "error": "Something went wrong", "expanded_err": repr(test_error)}
        ]
    else:
        assert "failed_recordings" not in result_dict


def test_run_magnet_finding_alg__correctly_raises_exception_if_pr_raises_convergence_error(mocker):
    mocker.patch.object(magnet_finder.shutil, "copytree", autospec=True)
    mocker.patch.object(magnet_finder, "PlateRecording", side_effect=UnableToConvergeError())
    failed_dict = dict()

    run_magnet_finding_alg(failed_dict, ["path/to/rec_snapshot"], "")

    assert failed_dict["failed_recordings"] == [
        {
            "name": "rec_snapshot",
            "error": "Unable to process recording due to low quality calibration and/or noise",
        }
    ]
