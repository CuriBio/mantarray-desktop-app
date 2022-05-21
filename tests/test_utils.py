# -*- coding: utf-8 -*-
import json
import os

from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import get_current_software_version
from mantarray_desktop_app import get_redacted_string
from mantarray_desktop_app import redact_sensitive_info_from_path
from mantarray_desktop_app import utils
from mantarray_desktop_app.constants import CLOUD_API_ENDPOINT
from mantarray_desktop_app.exceptions import InvalidUserCredsError
from mantarray_desktop_app.utils import validate_user_credentials
import pytest
from stdlib_utils import get_current_file_abs_directory


def test_validate_user_credentials__pings_cloud_api_to_validate_user_creds(mocker):
    mocked_post = mocker.patch.object(utils.requests, "post", autospec=True)
    mocked_post.return_value.status_code = 200

    test_user_creds = {"customer_id": "cid", "user_name": "user", "user_password": "pw"}
    validate_user_credentials(test_user_creds)

    # rename keys before assertion
    test_user_creds["username"] = test_user_creds.pop("user_name")
    test_user_creds["password"] = test_user_creds.pop("user_password")

    mocked_post.assert_called_with(f"https://{CLOUD_API_ENDPOINT}/users/login", json=test_user_creds)


def test_validate_user_credentials__does_not_ping_cloud_api_if_customer_id_not_given(mocker):
    mocked_post = mocker.patch.object(utils.requests, "post", autospec=True)
    validate_user_credentials({})
    mocked_post.assert_not_called()


def test_validate_user_credentials__raises_error_if_creds_are_invalid(mocker):
    mocked_post = mocker.patch.object(utils.requests, "post", autospec=True)
    mocked_post.return_value.status_code = 401

    with pytest.raises(InvalidUserCredsError):
        validate_user_credentials({"customer_id": "cid", "user_name": "user", "user_password": "pw"})


def test_get_current_software_version__Given_code_is_not_bundled__When_the_function_is_called__Then_it_returns_version_from_package_json():
    path_to_package_json = os.path.join(get_current_file_abs_directory(), os.pardir, "package.json")
    with open(path_to_package_json) as in_file:
        parsed_json = json.load(in_file)
        expected = parsed_json["version"]
        actual = get_current_software_version()
        assert actual == expected


def test_get_current_software_version__Given_code_is_mocked_as_being_bundled__When_the_function_is_called__Then_it_returns_version_from_constants_py(
    mocker,
):
    mocker.patch.object(utils, "is_frozen_as_exe", autospec=True, return_value=True)

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


def test_upload_log_files_to_s3__no_user_creds_found(mocker):
    spied_info = mocker.spy(utils.logger, "info")
    spied_error = mocker.spy(utils.logger, "error")
    mocked_uploader = mocker.patch.object(utils, "uploader", autospec=True)
    mocked_tempdir = mocker.patch.object(utils.tempfile, "TemporaryDirectory", autospec=True)

    utils.upload_log_files_to_s3({})

    mocked_uploader.assert_not_called()
    mocked_tempdir.assert_not_called()

    spied_info.assert_called_once_with("Skipping upload of log files to s3 because no user creds were found")
    spied_error.assert_not_called()


def test_upload_log_files_to_s3__log_file_is_None(mocker):
    spied_info = mocker.spy(utils.logger, "info")
    spied_error = mocker.spy(utils.logger, "error")
    mocked_uploader = mocker.patch.object(utils, "uploader", autospec=True)
    mocked_tempdir = mocker.patch.object(utils.tempfile, "TemporaryDirectory", autospec=True)

    utils.upload_log_files_to_s3(
        {"customer_id": "cid", "user_name": "un", "user_password": "pw", "log_directory": None}
    )

    mocked_uploader.assert_not_called()
    mocked_tempdir.assert_not_called()

    spied_info.assert_called_once_with("Skipping upload of log files to s3 because no log files were created")
    spied_error.assert_not_called()


def test_upload_log_files_to_s3__successful_upload(mocker):
    spied_info = mocker.spy(utils.logger, "info")
    spied_error = mocker.spy(utils.logger, "error")
    mocked_uploader = mocker.patch.object(utils, "uploader", autospec=True)
    mocked_tempdir = mocker.patch.object(
        utils.tempfile, "TemporaryDirectory", autospec=True, return_value=mocker.MagicMock()
    )

    config_settings = {
        "log_directory": os.path.join("log", "file", "dir"),
        "customer_id": "cid",
        "user_name": "un",
        "user_password": "pw",
    }
    utils.upload_log_files_to_s3(config_settings)

    mocked_uploader.assert_called_once_with(
        os.path.dirname(config_settings["log_directory"]),
        os.path.basename(config_settings["log_directory"]),
        mocked_tempdir.return_value.__enter__(),
        config_settings["customer_id"],
        config_settings["user_name"],
        config_settings["user_password"],
    )

    assert spied_info.call_args_list == [
        mocker.call("Attempting upload of log files to s3"),
        mocker.call("Successfully uploaded session logs to s3"),
    ]
    spied_error.assert_not_called()


def test_upload_log_files_to_s3__error_during_upload(mocker):
    spied_info = mocker.spy(utils.logger, "info")
    spied_error = mocker.spy(utils.logger, "error")
    mocked_uploader = mocker.patch.object(utils, "uploader", autospec=True)
    mocked_tempdir = mocker.patch.object(
        utils.tempfile, "TemporaryDirectory", autospec=True, return_value=mocker.MagicMock()
    )

    test_err = Exception("err_msg")
    mocked_uploader.side_effect = test_err

    config_settings = {
        "log_directory": os.path.join("log", "file", "dir"),
        "customer_id": "cid",
        "user_name": "un",
        "user_password": "pw",
    }
    utils.upload_log_files_to_s3(config_settings)

    mocked_uploader.assert_called_once_with(
        os.path.dirname(config_settings["log_directory"]),
        os.path.basename(config_settings["log_directory"]),
        mocked_tempdir.return_value.__enter__(),
        config_settings["customer_id"],
        config_settings["user_name"],
        config_settings["user_password"],
    )

    spied_info.assert_called_once_with("Attempting upload of log files to s3"),
    spied_error.assert_called_once_with(f"Failed to upload log files to s3: {repr(test_err)}")
