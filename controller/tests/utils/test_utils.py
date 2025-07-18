# -*- coding: utf-8 -*-
import copy
import json
import os

from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import get_current_software_version
from mantarray_desktop_app import get_redacted_string
from mantarray_desktop_app import redact_sensitive_info_from_path
from mantarray_desktop_app.utils import generic
from mantarray_desktop_app.utils.generic import redact_sensitive_info
from mantarray_desktop_app.utils.generic import validate_user_credentials
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
import pytest
from stdlib_utils import get_current_file_abs_directory


def test_validate_user_credentials__pings_cloud_api_to_validate_user_creds(mocker):
    mocked_get_tokens = mocker.patch.object(generic, "get_cloud_api_tokens", autospec=True)

    test_user_creds = {"customer_id": "cid", "user_name": "user", "user_password": "pw"}
    validate_user_credentials(test_user_creds)

    mocked_get_tokens.assert_called_once_with(*test_user_creds.values())


def test_validate_user_credentials__does_not_ping_cloud_api_if_customer_id_not_given(mocker):
    mocked_get_tokens = mocker.patch.object(generic, "get_cloud_api_tokens", autospec=True)
    validate_user_credentials({})
    mocked_get_tokens.assert_not_called()


def test_get_current_software_version__Given_code_is_not_bundled__When_the_function_is_called__Then_it_returns_version_from_package_json():
    path_to_package_json = os.path.join(
        get_current_file_abs_directory(), *([os.pardir] * 3), "electron", "package.json"
    )
    with open(path_to_package_json) as in_file:
        parsed_json = json.load(in_file)
        expected = parsed_json["version"]
        actual = get_current_software_version()
        assert actual == expected


def test_get_current_software_version__Given_code_is_mocked_as_being_bundled__When_the_function_is_called__Then_it_returns_version_from_constants_py(
    mocker,
):
    mocker.patch.object(generic, "is_frozen_as_exe", autospec=True, return_value=True)

    actual = get_current_software_version()
    assert actual == CURRENT_SOFTWARE_VERSION


def test_get_redacted_string__returns_correct_string():
    assert get_redacted_string(10) == "*" * 10


@pytest.mark.parametrize(
    "test_path,expected_path,test_description",
    [
        (
            r"C:\Users\Tanner\AppData\Local\Programs\MantarrayController",
            r"C:\Users\******\AppData\Local\Programs\MantarrayController",
            "returns correct value when username is 'Tanner'",
        ),
        (
            r"C:\Users\Anna\Craig\AppData\Local\Programs\MantarrayController",
            r"C:\Users\**********\AppData\Local\Programs\MantarrayController",
            r"returns correct value when username is 'Anna\Craig'",
        ),
        (
            r"C:\Users\t\AppData\Local\Programs\MantarrayController",
            r"C:\Users\*\AppData\Local\Programs\MantarrayController",
            "returns correct value when username is 't'",
        ),
        (
            r"Users\username\AppData\Local\Programs\MantarrayController",
            r"Users\********\AppData\Local\Programs\MantarrayController",
            "returns correct value when nothing before Users",
        ),
        (
            r"C:\Users\username\AppData",
            r"C:\Users\********\AppData",
            "returns correct value when nothing after AppData",
        ),
        (
            r"C:\Users\username\AppData",
            r"C:\Users\********\AppData",
            "returns correct value when nothing after AppData",
        ),
        (
            r"Users\username\AppData",
            r"Users\********\AppData",
            "returns correct value when nothing before Users or after AppData",
        ),
    ],
)
def test_redact_sensitive_info_from_path__scrubs_chars_in_between_Users_and_AppData(
    test_path, expected_path, test_description
):
    actual = redact_sensitive_info_from_path(test_path)
    assert actual == expected_path


@pytest.mark.parametrize(
    "test_path,test_description",
    [
        (
            r"C:\Tanner\AppData\Local\Programs\MantarrayController",
            "returns scrubbed string when missing 'Users'",
        ),
        (
            r"C:\Users\Tanner\Local\Programs\MantarrayController",
            "returns scrubbed string when missing 'AppData'",
        ),
        (
            r"C:\Local\Programs\MantarrayController",
            "returns scrubbed string when missing 'Users' and 'AppData'",
        ),
        (
            r"C:AppData\Local\Users\Programs\MantarrayController",
            "returns scrubbed string when 'Users' and 'AppData' are out of order",
        ),
    ],
)
def test_redact_sensitive_info_from_path__scrubs_everything_if_does_not_match_pattern(
    test_path, test_description
):
    actual = redact_sensitive_info_from_path(test_path)
    assert actual == get_redacted_string(len(test_path))


@pytest.mark.parametrize(
    "test_dict,use_orignal_len",
    [
        ({"mantarray_nickname": "some nickname"}, True),
        (
            {
                "communication_type": "update_user_settings",
                "content": {"user_name": "some name", "user_password": "pw"},
            },
            False,
        ),
        (
            {
                "command": "update_user_settings",
                "config_settings": {"user_name": "name", "user_password": "pw"},
            },
            False,
        ),
        (
            {"communication_type": "metadata_comm", "metadata": {MANTARRAY_NICKNAME_UUID: "some nickname"}},
            True,
        ),
        (
            {"communication_type": "mag_finding_analysis", "recordings": ["some path", "some other path"]},
            None,
        ),
    ],
)
def test_redact_sensitive_info__scrubs_sensitive_info_from_dicts(test_dict, use_orignal_len):
    def redact(d):
        for k, v in d.items():
            if k in ("command", "communication_type"):
                continue
            if isinstance(v, str):
                d[k] = get_redacted_string(len(v) if use_orignal_len else 4)
            elif isinstance(v, list):
                d[k] = [redact_sensitive_info_from_path(recording_path) for recording_path in v]
            elif isinstance(v, dict):
                redact(v)

    expected_dict = copy.deepcopy(test_dict)
    redact(expected_dict)

    assert redact_sensitive_info(test_dict) == expected_dict


def test_upload_log_files_to_s3__auto_upload_is_not_enabled(mocker):
    spied_info = mocker.spy(generic.logger, "info")
    spied_error = mocker.spy(generic.logger, "error")
    mocked_uploader = mocker.patch.object(generic, "FileUploader", autospec=True)
    mocked_tempdir = mocker.patch.object(generic.tempfile, "TemporaryDirectory", autospec=True)

    generic.upload_log_files_to_s3({})

    mocked_uploader.assert_not_called()
    mocked_tempdir.assert_not_called()

    spied_info.assert_called_once_with("Auto-upload is not turned on, skipping upload of log files.")
    spied_error.assert_not_called()


def test_upload_log_files_to_s3__log_file_is_None(mocker):
    spied_info = mocker.spy(generic.logger, "info")
    spied_error = mocker.spy(generic.logger, "error")
    mocked_uploader = mocker.patch.object(generic, "FileUploader", autospec=True)
    mocked_tempdir = mocker.patch.object(generic.tempfile, "TemporaryDirectory", autospec=True)

    generic.upload_log_files_to_s3(
        {
            "customer_id": "cid",
            "user_name": "un",
            "user_password": "pw",
            "log_directory": None,
            "auto_upload_on_completion": True,
        }
    )

    mocked_uploader.assert_not_called()
    mocked_tempdir.assert_not_called()

    spied_info.assert_called_once_with("Skipping upload of log files to s3 because no log files were created")
    spied_error.assert_not_called()


def test_upload_log_files_to_s3__successful_upload(mocker):
    spied_info = mocker.spy(generic.logger, "info")
    spied_error = mocker.spy(generic.logger, "error")
    mocked_uploader = mocker.patch.object(generic, "FileUploader", autospec=True)
    mocked_tempdir = mocker.patch.object(
        generic.tempfile, "TemporaryDirectory", autospec=True, return_value=mocker.MagicMock()
    )

    config_settings = {
        "log_directory": os.path.join("log", "file", "dir"),
        "customer_id": "cid",
        "user_name": "un",
        "user_password": "pw",
        "auto_upload_on_completion": True,
    }
    generic.upload_log_files_to_s3(config_settings)

    mocked_uploader.assert_called_once_with(
        "logs",
        os.path.dirname(config_settings["log_directory"]),
        os.path.basename(config_settings["log_directory"]),
        mocked_tempdir.return_value.__enter__(),
        config_settings["customer_id"],
        config_settings["user_name"],
        config_settings["user_password"],
    )
    mocked_uploader.return_value.assert_called_once_with()

    assert spied_info.call_args_list == [
        mocker.call("Attempting upload of log files to s3"),
        mocker.call("Successfully uploaded session logs to s3"),
    ]
    spied_error.assert_not_called()


def test_upload_log_files_to_s3__error_during_upload(mocker):
    spied_info = mocker.spy(generic.logger, "info")
    spied_error = mocker.spy(generic.logger, "error")
    mocked_uploader = mocker.patch.object(generic, "FileUploader", autospec=True)
    mocked_tempdir = mocker.patch.object(
        generic.tempfile, "TemporaryDirectory", autospec=True, return_value=mocker.MagicMock()
    )

    test_err = Exception("err_msg")
    mocked_uploader.return_value.side_effect = test_err

    config_settings = {
        "log_directory": os.path.join("log", "file", "dir"),
        "customer_id": "cid",
        "user_name": "un",
        "user_password": "pw",
        "auto_upload_on_completion": True,
    }
    generic.upload_log_files_to_s3(config_settings)

    mocked_uploader.assert_called_once_with(
        "logs",
        os.path.dirname(config_settings["log_directory"]),
        os.path.basename(config_settings["log_directory"]),
        mocked_tempdir.return_value.__enter__(),
        config_settings["customer_id"],
        config_settings["user_name"],
        config_settings["user_password"],
    )
    mocked_uploader.return_value.assert_called_once_with()

    spied_info.assert_called_once_with("Attempting upload of log files to s3"),
    spied_error.assert_called_once_with(f"Failed to upload log files to s3: {repr(test_err)}")
