# -*- coding: utf-8 -*-
import base64
import hashlib
import os
import tempfile
import zipfile

from mantarray_desktop_app.constants import CLOUD_PULSE3D_ENDPOINT
from mantarray_desktop_app.exceptions import CloudAnalysisJobFailedError
from mantarray_desktop_app.exceptions import PresignedUploadFailedError
from mantarray_desktop_app.exceptions import RecordingUploadMissingPulse3dVersionError
from mantarray_desktop_app.utils import web_api
from mantarray_desktop_app.utils.web_api import AuthTokens
from mantarray_desktop_app.workers import file_uploader
from mantarray_desktop_app.workers.file_uploader import create_zip_file
from mantarray_desktop_app.workers.file_uploader import download_analysis_from_s3
from mantarray_desktop_app.workers.file_uploader import FileUploader
from mantarray_desktop_app.workers.file_uploader import get_file_md5
from mantarray_desktop_app.workers.file_uploader import get_upload_details
from mantarray_desktop_app.workers.file_uploader import start_analysis
from mantarray_desktop_app.workers.file_uploader import upload_file_to_s3
import pytest
import requests

from ..fixtures_file_writer import TEST_CUSTOMER_ID
from ..fixtures_file_writer import TEST_USER_NAME

TEST_FILEPATH = os.path.join("test", "recordings")
TEST_LOGPATH = os.path.join("log", "directory")
TEST_FILENAME = "test_filename"
TEST_ZIPDIR = os.path.join("test", "zipped_recordings")
TEST_PASSWORD = "pw"
TEST_PULSE3D_VERSION = "6.7.9"

RECORDING_UPLOAD_TYPE = "recording"
LOG_UPLOAD_TYPE = "logs"


@pytest.fixture(scope="function", name="create_file_uploader")
def fixture_create_file_uploader():
    def _foo(
        file_directory=TEST_FILEPATH,
        file_name=TEST_FILENAME,
        zipped_recordings_dir=TEST_ZIPDIR,
        customer_id=TEST_CUSTOMER_ID,
        user_name=TEST_USER_NAME,
        password=TEST_PASSWORD,
        pulse3d_version=TEST_PULSE3D_VERSION,
        create_tokens=False,
    ):
        test_file_uploader = FileUploader(
            "recording" if "recording" in file_directory else "logs",
            file_directory,
            file_name,
            zipped_recordings_dir,
            customer_id,
            user_name,
            password,
            pulse3d_version,
        )
        if create_tokens:
            test_file_uploader.tokens = AuthTokens(access="test_access_token", refresh="test_refresh_token")
        return test_file_uploader

    yield _foo


def test_get_file_md5__creates_and_returns_file_md5_value_correctly(mocker):
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_md5 = mocker.patch.object(hashlib, "md5", autospec=True)
    mocked_b64encode = mocker.patch.object(base64, "b64encode", autospec=True)

    expected_md5 = mocked_b64encode.return_value.decode()

    actual = get_file_md5(TEST_FILENAME)
    mocked_open.assert_called_once_with(TEST_FILENAME, "rb")
    mocked_md5.assert_called_once_with(mocked_open.return_value.__enter__().read())
    mocked_b64encode.assert_called_once_with(mocked_md5.return_value.digest())
    assert actual == expected_md5


@pytest.mark.parametrize("upload_type,expected_route", [("recording", "uploads"), ("logs", "logs")])
def test_get_upload_details__requests_and_returns_upload_details_correctly(
    upload_type, expected_route, mocker
):
    mocked_post = mocker.patch.object(requests, "post", autospec=True)
    expected_upload_details = mocked_post.return_value.json()

    test_access_token = "token"
    test_file_md5 = "hash"

    actual = get_upload_details(test_access_token, TEST_FILENAME, test_file_md5, upload_type)
    mocked_post.assert_called_once_with(
        f"https://{CLOUD_PULSE3D_ENDPOINT}/{expected_route}",
        json={"filename": TEST_FILENAME, "md5s": test_file_md5, "upload_type": "mantarray"},
        headers={"Authorization": f"Bearer {test_access_token}"},
    )
    assert actual == expected_upload_details


def test_upload_file_to_s3__uploads_file_correctly(mocker):
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_post = mocker.patch.object(requests, "post", autospec=True)

    mocked_post.return_value.status_code = 204

    expected_open_file = mocked_open.return_value.__enter__()
    test_url = "website.com"
    test_data = {"key": "val"}
    test_upload_details = {"params": {"url": test_url, "fields": test_data}}

    upload_file_to_s3(TEST_FILEPATH, TEST_FILENAME, test_upload_details)

    mocked_open.assert_called_once_with(TEST_FILEPATH, "rb")
    mocked_post.assert_called_once_with(
        test_url, data=test_data, files={"file": (TEST_FILENAME, expected_open_file)}
    )


def test_upload_file_to_s3__raises_error_if_upload_fails(mocker):
    mocker.patch("builtins.open", autospec=True)
    mocked_post = mocker.patch.object(requests, "post", autospec=True)

    mocked_post.return_value.status_code = error_code = 400
    mocked_post.return_value.reason = error_reason = "BAD REQUEST"

    test_upload_details = mocker.MagicMock()

    with pytest.raises(PresignedUploadFailedError, match=f"{error_code} {error_reason}"):
        upload_file_to_s3(TEST_FILEPATH, TEST_FILENAME, test_upload_details)


def test_start_analysis__starts_analysis_job_correctly__and_returns_job_id_and_usage(mocker):
    mocked_post = mocker.patch.object(requests, "post", autospec=True)
    mocked_post.return_value.json.return_value = {"id": "test_id", "usage_quota": {"jobs_reached": False}}

    test_access_token = "token"
    test_id = "id"
    test_version = "1.2.3"

    job_details = start_analysis(test_access_token, test_id, test_version)

    assert job_details["id"] == mocked_post.return_value.json()["id"]
    assert job_details["usage_quota"] == mocked_post.return_value.json()["usage_quota"]
    mocked_post.assert_called_once_with(
        f"https://{CLOUD_PULSE3D_ENDPOINT}/jobs",
        json={"upload_id": test_id, "version": test_version},
        headers={"Authorization": f"Bearer {test_access_token}"},
    )


def test_create_zip_file__correctly_writes_h5_files_to_zipfile_at_designated_path(mocker):
    mocked_zipfile = mocker.patch.object(zipfile, "ZipFile", autospec=True)
    mocked_zipfile_write = mocked_zipfile.return_value.__enter__.return_value.write

    test_folder_path = os.path.join("some", "path", "to", "test_h5_files")
    test_file_names = ("test_1.h5", "test_2.h5")

    mocked_os_walk = mocker.patch.object(os, "walk", autospec=True)
    mocked_os_walk.return_value = [(test_folder_path, ("",), test_file_names)]

    test_zipped_path = f"{TEST_FILEPATH}/zipped_recordings/cid"

    zipped_file_path = create_zip_file(TEST_FILEPATH, TEST_FILENAME, test_zipped_path)
    assert zipped_file_path == f"{os.path.join(test_zipped_path, TEST_FILENAME)}.zip"

    mocked_zipfile.assert_called_once_with(f"{os.path.join(test_zipped_path, TEST_FILENAME)}.zip", "w")
    assert mocked_zipfile_write.call_args_list == [
        mocker.call(os.path.join(test_folder_path, file_name), file_name) for file_name in test_file_names
    ]


def test_download_analysis_from_s3__downloads_content_and_writes_to_file_in_downloads_dir(mocker):
    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_file_handle = mocked_open.return_value.__enter__()

    test_presigned_url = "presigned_url"
    test_file_path = "path/to/file"

    expected_download_file_path = os.path.join(os.path.expanduser("~"), "downloads", f"{test_file_path}.xlsx")

    download_analysis_from_s3(test_presigned_url, test_file_path)

    mocked_get.assert_called_once_with(test_presigned_url)
    mocked_open.assert_called_once_with(expected_download_file_path, "wb")
    mocked_file_handle.write.assert_called_once_with(mocked_get.return_value.content)


def test_FileUploader_init__raises_error_if_uploading_a_recording_and_pulse3d_version_not_given(
    create_file_uploader,
):
    with pytest.raises(RecordingUploadMissingPulse3dVersionError, match=TEST_FILENAME):
        # this will do a recording upload by default
        create_file_uploader(pulse3d_version=None)


def test_FileUploader_get_analysis_status__requests_with_refresh__and_returns_analysis_status_correctly(
    create_file_uploader, mocker
):
    expected_status_dict = {"status": "pending"}

    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.json.return_value = {"jobs": [expected_status_dict]}

    test_file_uploader = create_file_uploader(create_tokens=True)

    test_id = "id"

    actual = test_file_uploader.get_analysis_status(test_id)
    assert actual == expected_status_dict

    mocked_get.assert_called_once_with(
        f"https://{CLOUD_PULSE3D_ENDPOINT}/jobs",
        params={"job_ids": test_id},
        headers={"Authorization": f"Bearer {test_file_uploader.tokens.access}"},
    )


def test_FileUploader_get_analysis_status__makes_request_with_refresh(create_file_uploader, mocker):
    mocked_get = mocker.patch.object(requests, "get", autospec=True)

    test_file_uploader = create_file_uploader(create_tokens=True)

    mocked_rwr = mocker.patch.object(test_file_uploader, "request_with_refresh", autospec=True)
    mocked_rwr.return_value.json.return_value = {"jobs": [{}]}

    test_file_uploader.get_analysis_status("job_id")
    request_func = mocked_rwr.call_args[0][0]

    mocked_get.assert_not_called()
    request_func()
    mocked_get.assert_called_once()


def test_FileUploader_get_analysis_status__raises_error_if_job_route_errored(mocker, create_file_uploader):
    expected_error_msg = "err_msg"

    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.json.return_value = {"error": expected_error_msg}

    test_file_uploader = create_file_uploader(create_tokens=True)

    with pytest.raises(CloudAnalysisJobFailedError, match=expected_error_msg):
        test_file_uploader.get_analysis_status("job_id")


def test_FileUploader__raises_error_if_start_analysis_returns_error_from_post(mocker, create_file_uploader):
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocker.patch.object(file_uploader, "download_analysis_from_s3", autospec=True)

    mocked_get_tokens = mocker.patch.object(web_api, "get_cloud_api_tokens", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})

    mocked_start_analysis = mocker.patch.object(file_uploader, "start_analysis", autospec=True)
    mocked_start_analysis.return_value = {"error": "UsageError"}

    test_file_uploader = create_file_uploader(create_tokens=True)

    with pytest.raises(CloudAnalysisJobFailedError, match="UsageError"):
        test_file_uploader = create_file_uploader()
        test_file_uploader()


def test_FileUploader_get_analysis_status__raises_error_if_analysis_job_errored(mocker, create_file_uploader):
    expected_error_msg = "err_msg"
    expected_status_dict = {"error_info": expected_error_msg}

    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.json.return_value = {"jobs": [expected_status_dict]}

    test_file_uploader = create_file_uploader(create_tokens=True)

    with pytest.raises(CloudAnalysisJobFailedError, match=expected_error_msg):
        test_file_uploader.get_analysis_status("job_id")


def test_FileUploader_job__does_not_create_new_zip_file_if_file_to_upload_is_a_zip_file(
    create_file_uploader, mocker
):
    mocked_get_tokens = mocker.patch.object(web_api, "get_cloud_api_tokens", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocker.patch.object(file_uploader, "download_analysis_from_s3", autospec=True)
    mocker.patch.object(file_uploader.FileUploader, "get_analysis_status", autospec=True)
    mocked_create_zip_file = mocker.patch.object(file_uploader, "create_zip_file", autospec=True)

    mocked_start_analysis = mocker.patch.object(file_uploader, "start_analysis", autospec=True)
    mocked_start_analysis.return_value = {"id": "test_id"}

    test_file_uploader = create_file_uploader()
    test_file_uploader()

    mocked_create_zip_file.assert_not_called()


@pytest.mark.parametrize("job_status", ["pending", "running"])
def test_FileUploader__sleeps_in_between_polling_analysis_status_until_analysis_completes(
    create_file_uploader, mocker, job_status
):
    mocked_get_tokens = mocker.patch.object(web_api, "get_cloud_api_tokens", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocker.patch.object(file_uploader, "download_analysis_from_s3", autospec=True)

    mocked_start_analysis = mocker.patch.object(file_uploader, "start_analysis", autospec=True)
    mocked_start_analysis.return_value = {"id": "test_id"}

    # set up so analysis status is only polled twice
    test_status_dicts = [{"status": job_status}, {"status": "finished", "url": None}]

    mocked_get_analysis_status = mocker.patch.object(
        file_uploader.FileUploader, "get_analysis_status", autospec=True, side_effect=test_status_dicts
    )
    mocked_sleep = mocker.patch.object(file_uploader, "sleep", autospec=True)

    test_file_uploader = create_file_uploader()
    test_file_uploader()

    mocked_sleep.assert_called_once_with(5)
    assert mocked_get_analysis_status.call_count == 2


@pytest.mark.parametrize("user_dir_exists", [True, False])
def test_FileUploader__runs_upload_procedure_correctly_for_recording(
    user_dir_exists, create_file_uploader, mocker
):
    mocker.patch.object(os.path, "exists", autospec=True, return_value=user_dir_exists)
    mocked_makedirs = mocker.patch.object(os, "makedirs", autospec=True)

    mocked_get_tokens = mocker.patch.object(web_api, "get_cloud_api_tokens", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})
    mocked_create_zip_file = mocker.patch.object(file_uploader, "create_zip_file", autospec=True)
    mocked_get_file_md5 = mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocked_get_upload_details = mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocked_upload_file = mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocked_start_analysis = mocker.patch.object(file_uploader, "start_analysis", autospec=True)
    mocked_download_analaysis = mocker.patch.object(file_uploader, "download_analysis_from_s3", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})

    expected_upload_details = mocked_get_upload_details.return_value
    expected_access_token = mocked_get_tokens.return_value[0].access
    expected_md5 = mocked_get_file_md5.return_value
    expected_zipped_file_path = mocked_create_zip_file.return_value
    mocked_start_analysis.return_value = {"id": "test_id"}

    with tempfile.TemporaryDirectory(prefix=RECORDING_UPLOAD_TYPE) as tmp_dir:
        expected_zipped_file_name = f"{tmp_dir}.zip"

        test_file_uploader = create_file_uploader(file_name=tmp_dir)

        mocked_get_analysis_status = mocker.patch.object(
            test_file_uploader, "get_analysis_status", autospec=True
        )

        test_file_uploader()

    if user_dir_exists:
        mocked_makedirs.assert_not_called()
    else:
        mocked_makedirs.assert_called_once_with(os.path.join(TEST_ZIPDIR, TEST_USER_NAME))

    mocked_create_zip_file.assert_called_once_with(
        TEST_FILEPATH, tmp_dir, os.path.join(TEST_ZIPDIR, TEST_USER_NAME)
    )

    mocked_get_tokens.assert_called_once_with(TEST_CUSTOMER_ID, TEST_USER_NAME, TEST_PASSWORD)
    mocked_get_file_md5.assert_called_once_with(expected_zipped_file_path)
    mocked_get_upload_details.assert_called_once_with(
        expected_access_token, expected_zipped_file_name, expected_md5, RECORDING_UPLOAD_TYPE
    )
    mocked_upload_file.assert_called_once_with(
        expected_zipped_file_path, expected_zipped_file_name, expected_upload_details
    )
    mocked_start_analysis.assert_called_once_with(
        expected_access_token, expected_upload_details["id"], TEST_PULSE3D_VERSION
    )
    mocked_get_analysis_status.assert_called_once_with(mocked_start_analysis.return_value["id"])
    mocked_download_analaysis.assert_called_once_with(
        mocked_get_analysis_status.return_value["url"], expected_zipped_file_name
    )


def test_FileUploader__runs_upload_procedure_correctly_for_log_files(mocker, create_file_uploader):
    mocked_get_tokens = mocker.patch.object(web_api, "get_cloud_api_tokens", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})
    mocked_create_zip_file = mocker.patch.object(file_uploader, "create_zip_file", autospec=True)
    mocked_get_file_md5 = mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocked_get_upload_details = mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocked_upload_file = mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    spied_start_analysis = mocker.spy(file_uploader, "start_analysis")
    spied_download_analaysis = mocker.spy(file_uploader, "download_analysis_from_s3")
    mocker.patch.object(os.path, "exists", autospec=True, return_value=True)

    spied_start_analysis.return_value = {"id": "test_id"}
    expected_upload_details = mocked_get_upload_details.return_value
    expected_access_token = mocked_get_tokens.return_value[0].access
    expected_md5 = mocked_get_file_md5.return_value
    expected_zipped_file_path = mocked_create_zip_file.return_value

    with tempfile.TemporaryDirectory(prefix=LOG_UPLOAD_TYPE) as tmp_dir:
        expected_zipped_file_name = f"{tmp_dir}.zip"

        test_file_uploader = create_file_uploader(file_directory=TEST_LOGPATH, file_name=tmp_dir)

        spied_get_analysis_status = mocker.spy(test_file_uploader, "get_analysis_status")

        test_file_uploader()

    mocked_create_zip_file.assert_called_once_with(TEST_LOGPATH, tmp_dir, TEST_ZIPDIR)
    mocked_get_tokens.assert_called_once_with(TEST_CUSTOMER_ID, TEST_USER_NAME, TEST_PASSWORD)
    mocked_get_file_md5.assert_called_once_with(expected_zipped_file_path)
    mocked_get_upload_details.assert_called_once_with(
        expected_access_token, expected_zipped_file_name, expected_md5, LOG_UPLOAD_TYPE
    )
    mocked_upload_file.assert_called_once_with(
        expected_zipped_file_path, expected_zipped_file_name, expected_upload_details
    )

    spied_start_analysis.assert_not_called()
    spied_get_analysis_status.assert_not_called()
    spied_download_analaysis.assert_not_called()
