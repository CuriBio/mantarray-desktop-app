# -*- coding: utf-8 -*-
import base64
import hashlib
import os
import tempfile
import threading
import zipfile

from mantarray_desktop_app import CLOUD_API_ENDPOINT
from mantarray_desktop_app import file_uploader
from mantarray_desktop_app.file_uploader import create_zip_file
from mantarray_desktop_app.file_uploader import get_access_token
from mantarray_desktop_app.file_uploader import get_file_md5
from mantarray_desktop_app.file_uploader import get_sdk_status
from mantarray_desktop_app.file_uploader import get_upload_details
from mantarray_desktop_app.file_uploader import upload_file_to_s3
from mantarray_desktop_app.file_uploader import uploader
from mantarray_desktop_app.worker_thread import ErrorCatchingThread
import pytest
import requests

TEST_FILENAME = "test_filename"
TEST_FILEPATH = "/test/recordings"
TEST_ZIPDIR = os.path.join("test", "zipped_recordings")
TEST_CUSTOMER_ACCOUNT_ID = "cid"
TEST_PASSWORD = "pw"
TEST_USER_ACCOUNT_ID = "test_user"
SDK_UPLOAD_TYPE = "sdk"
LOG_UPLOAD_TYPE = "logs"
TEST_LOGPATH = "/log/directory"


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


def test_get_access_token__requests_and_returns_access_token_correctly(mocker):
    mocked_post = mocker.patch.object(requests, "post", autospec=True)

    expected_access_token = mocked_post.return_value.json()["access_token"]

    actual = get_access_token(TEST_CUSTOMER_ACCOUNT_ID, TEST_PASSWORD)
    mocked_post.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/users/login",
        json={"username": TEST_CUSTOMER_ACCOUNT_ID, "password": TEST_PASSWORD},
    )
    assert actual == expected_access_token


def test_get_upload_details__requests_and_returns_upload_details_correctly(mocker):
    mocked_post = mocker.patch.object(requests, "post", autospec=True)
    expected_upload_details = mocked_post.return_value.json()
    test_access_token = "token"
    test_file_md5 = "hash"
    no_user_object_key = f"{TEST_CUSTOMER_ACCOUNT_ID}/{TEST_FILENAME}"
    user_object_key = f"{TEST_CUSTOMER_ACCOUNT_ID}/{TEST_USER_ACCOUNT_ID}/{TEST_FILENAME}"

    actual = get_upload_details(
        test_access_token, TEST_FILENAME, TEST_CUSTOMER_ACCOUNT_ID, test_file_md5, None, SDK_UPLOAD_TYPE
    )
    mocked_post.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/sdk_upload",
        json={"file_name": no_user_object_key, "upload_type": SDK_UPLOAD_TYPE},
        headers={"Authorization": f"Bearer {test_access_token}", "Content-MD5": test_file_md5},
    )
    assert actual == expected_upload_details

    actual = get_upload_details(
        test_access_token,
        TEST_FILENAME,
        TEST_CUSTOMER_ACCOUNT_ID,
        test_file_md5,
        TEST_USER_ACCOUNT_ID,
        SDK_UPLOAD_TYPE,
    )
    mocked_post.assert_any_call(
        f"https://{CLOUD_API_ENDPOINT}/sdk_upload",
        json={"file_name": user_object_key, "upload_type": SDK_UPLOAD_TYPE},
        headers={"Authorization": f"Bearer {test_access_token}", "Content-MD5": test_file_md5},
    )
    assert actual == expected_upload_details


def test_upload_file_to_s3__uploads_file_correctly(mocker):
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_post = mocker.patch.object(requests, "post", autospec=True)

    expected_open_file = mocked_open.return_value.__enter__()
    test_url = "website.com"
    test_data = {"key": "val"}
    test_upload_details = {"presigned_params": {"url": test_url, "fields": test_data}}

    upload_file_to_s3(TEST_FILEPATH, TEST_FILENAME, test_upload_details)

    mocked_open.assert_called_once_with(TEST_FILEPATH, "rb")
    mocked_post.assert_called_once_with(
        test_url, data=test_data, files={"file": (TEST_FILENAME, expected_open_file)}
    )


def test_get_sdk_status__requests_and_returns_sdk_status_correctly(mocker):
    mocked_post = mocker.patch.object(requests, "get", autospec=True)

    expected_sdk_status = mocked_post.return_value.json()["status"]
    test_access_token = "token"
    test_upload_details = {"upload_id": "test_id"}

    actual = get_sdk_status(test_access_token, test_upload_details)
    mocked_post.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/get_sdk_status?upload_id=test_id",
        headers={"Authorization": f"Bearer {test_access_token}"},
    )
    assert actual == expected_sdk_status


def test_create_zip_file__correctly_writes_h5_files_to_zipfile_at_designated_path(mocker):
    mocked_zip_function = mocker.patch.object(zipfile, "ZipFile", autospec=True)
    mocked_os_walk = mocker.patch.object(os, "walk", autospec=True)
    spied_os_join = mocker.spy(os.path, "join")
    mocked_os_walk.return_value = [
        (
            "/tmp/test_h5_files",
            ("",),
            (
                "test_1.h5",
                "test_2.h5",
            ),
        ),
    ]

    test_zipped_path = f"{TEST_FILEPATH}/zipped_recordings/cid"

    zipped_file_path = create_zip_file(TEST_FILEPATH, TEST_FILENAME, test_zipped_path)
    mocked_zip_function.assert_called_once_with(f"{os.path.join(test_zipped_path, TEST_FILENAME)}.zip", "w")
    assert len(spied_os_join.call_args_list) == 5
    assert zipped_file_path == f"{os.path.join(test_zipped_path, TEST_FILENAME)}.zip"


def test_create_zip_file__create_zip_file_should_not_be_called_with_previously_failed_zip_file(mocker):
    mocked_create_zip_file = mocker.patch.object(file_uploader, "create_zip_file", autospec=True)
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocker.patch.object(file_uploader, "download_analysis_from_s3", autospec=True)
    mocker.patch.object(
        file_uploader,
        "get_sdk_status",
        autospec=True,
        return_value="https",
    )

    uploader(
        TEST_FILEPATH,
        TEST_FILENAME,
        TEST_ZIPDIR,
        TEST_CUSTOMER_ACCOUNT_ID,
        TEST_PASSWORD,
        TEST_USER_ACCOUNT_ID,
    )
    mocked_create_zip_file.assert_not_called()


def test_uploader__runs_upload_procedure_correctly_for_uploading_a_recording(mocker):
    mocked_create_zip_file = mocker.patch.object(file_uploader, "create_zip_file", autospec=True)
    mocked_get_file_md5 = mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocked_get_access_token = mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocked_get_upload_details = mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocked_upload_file = mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocked_download_analaysis = mocker.patch.object(file_uploader, "download_analysis_from_s3", autospec=True)
    mocked_get_sdk_status = mocker.patch.object(
        file_uploader,
        "get_sdk_status",
        autospec=True,
        return_value="https",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        expected_upload_details = mocked_get_upload_details.return_value
        expected_access_token = mocked_get_access_token.return_value
        expected_md5 = mocked_get_file_md5.return_value
        mocker.patch.object(os.path, "exists", autospec=True, return_value=True)

        test_dir = tmp_dir
        zipped_file_name = f"{test_dir}.zip"
        zipped_file_path = mocked_create_zip_file.return_value

        uploader(
            TEST_FILEPATH,
            test_dir,
            TEST_ZIPDIR,
            TEST_CUSTOMER_ACCOUNT_ID,
            TEST_PASSWORD,
            TEST_USER_ACCOUNT_ID,
        )

        mocked_create_zip_file.assert_called_once_with(
            TEST_FILEPATH,
            test_dir,
            f"{os.path.join(TEST_ZIPDIR, TEST_CUSTOMER_ACCOUNT_ID, TEST_USER_ACCOUNT_ID)}",
        )
        mocked_get_access_token.assert_called_once_with(TEST_CUSTOMER_ACCOUNT_ID, TEST_PASSWORD)
        mocked_get_file_md5.assert_called_once_with(zipped_file_path)
        mocked_get_upload_details.assert_called_once_with(
            expected_access_token,
            zipped_file_name,
            TEST_CUSTOMER_ACCOUNT_ID,
            expected_md5,
            TEST_USER_ACCOUNT_ID,
            SDK_UPLOAD_TYPE,
        )
        mocked_upload_file.assert_called_once_with(
            zipped_file_path, zipped_file_name, expected_upload_details
        )
        mocked_get_sdk_status.assert_called_once_with(expected_access_token, expected_upload_details)
        mocked_download_analaysis.assert_called_once_with(
            mocked_get_sdk_status.return_value, zipped_file_name
        )


def test_uploader__runs_upload_procedure_correctly_for_log_files(mocker):
    mocked_create_zip_file = mocker.patch.object(file_uploader, "create_zip_file", autospec=True)
    mocked_get_file_md5 = mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocked_get_access_token = mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocked_get_upload_details = mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocked_upload_file = mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    spied_download_analaysis = mocker.spy(file_uploader, "download_analysis_from_s3")
    spied_get_sdk_status = mocker.spy(
        file_uploader,
        "get_sdk_status",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        expected_upload_details = mocked_get_upload_details.return_value
        expected_access_token = mocked_get_access_token.return_value
        expected_md5 = mocked_get_file_md5.return_value
        mocker.patch.object(os.path, "exists", autospec=True, return_value=True)

        test_dir = tmp_dir
        zipped_file_name = f"{test_dir}.zip"
        zipped_file_path = mocked_create_zip_file.return_value

        uploader(
            TEST_LOGPATH,
            test_dir,
            TEST_ZIPDIR,
            TEST_CUSTOMER_ACCOUNT_ID,
            TEST_PASSWORD,
        )

        mocked_create_zip_file.assert_called_once_with(
            TEST_LOGPATH,
            test_dir,
            f"{os.path.join(TEST_ZIPDIR, TEST_CUSTOMER_ACCOUNT_ID)}",
        )
        mocked_get_access_token.assert_called_once_with(TEST_CUSTOMER_ACCOUNT_ID, TEST_PASSWORD)
        mocked_get_file_md5.assert_called_once_with(zipped_file_path)
        mocked_get_upload_details.assert_called_once_with(
            expected_access_token,
            zipped_file_name,
            TEST_CUSTOMER_ACCOUNT_ID,
            expected_md5,
            None,
            LOG_UPLOAD_TYPE,
        )
        mocked_upload_file.assert_called_once_with(
            zipped_file_path, zipped_file_name, expected_upload_details
        )
        spied_get_sdk_status.assert_not_called()
        spied_download_analaysis.assert_not_called()


def test_uploader__uploader_raises_error_if_get_sdk_status_returns_error_message_from_aws(mocker):
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocked_sdk_status = mocker.patch.object(
        file_uploader, "get_sdk_status", autospec=True, return_value="error in upload"
    )
    mocker.patch.object(file_uploader, "download_analysis_from_s3", autospec=True)
    mocker.patch.object(os.path, "exists", autospec=True, return_Value=True)
    with tempfile.TemporaryDirectory() as tmp_dir:

        test_dir = tmp_dir

        with pytest.raises(Exception) as e:
            thread = ErrorCatchingThread(
                target=uploader,
                args=(
                    TEST_FILEPATH,
                    test_dir,
                    TEST_ZIPDIR,
                    TEST_CUSTOMER_ACCOUNT_ID,
                    TEST_PASSWORD,
                    TEST_USER_ACCOUNT_ID,
                ),
            )
            thread.start()
            thread.join()

            assert thread.error == e
            assert thread.errors() is True
            assert thread.get_error() == mocked_sdk_status.return_value


def test_uploader__uploader_sleeps_same_number_of_max_loops(mocker):
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocked_get_sdk_status = mocker.patch.object(
        file_uploader, "get_sdk_status", autospec=True, return_value="status"
    )
    mocker.patch.object(file_uploader, "download_analysis_from_s3", autospec=True)
    mocked_sleep = mocker.patch.object(file_uploader, "sleep", autospec=True)

    uploader(
        TEST_FILEPATH,
        TEST_FILENAME,
        TEST_ZIPDIR,
        TEST_CUSTOMER_ACCOUNT_ID,
        TEST_PASSWORD,
        TEST_USER_ACCOUNT_ID,
        max_num_loops=3,
    )
    mocked_sleep.assert_called_with(5)
    assert len(mocked_sleep.call_args_list) == 2
    assert len(mocked_get_sdk_status.call_args_list) == 3


def test_uploader__uploader_sleeps_after_loop_getting_sdk_status(mocker):
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocked_get_sdk_status = mocker.patch.object(
        file_uploader, "get_sdk_status", autospec=True, return_value="status"
    )
    mocker.patch.object(file_uploader, "download_analysis_from_s3", autospec=True)
    mocked_sleep = mocker.patch.object(file_uploader, "sleep", autospec=True)

    uploader(
        TEST_FILEPATH,
        TEST_FILENAME,
        TEST_ZIPDIR,
        TEST_CUSTOMER_ACCOUNT_ID,
        TEST_PASSWORD,
        TEST_USER_ACCOUNT_ID,
        max_num_loops=2,
    )
    mocked_sleep.assert_called_once_with(5)
    assert len(mocked_get_sdk_status.call_args_list) == 2


def test_ErrorCatchingThread__correctly_returns_no_error_when_upload_is_successful(mocker):
    mocked_uploader_function = mocker.patch.object(file_uploader, "uploader")

    mocked_thread = ErrorCatchingThread(target=mocked_uploader_function)
    mocked_thread.start()
    mocked_thread.join()

    assert mocked_thread.errors() is False
    assert mocked_thread.get_error() is None


def test_ErrorCatchingThread__correctly_returns_error_to_caller_thread(mocker):
    mocked_uploader_function = mocker.patch.object(file_uploader, "uploader", autospec=True)
    mocked_uploader_function.side_effect = Exception("mocked error")

    test_sub_dir = "/sub_dir"

    mocked_thread = ErrorCatchingThread(
        target=mocked_uploader_function,
        args=(
            TEST_FILEPATH,
            test_sub_dir,
            TEST_ZIPDIR,
            TEST_CUSTOMER_ACCOUNT_ID,
            TEST_PASSWORD,
            TEST_USER_ACCOUNT_ID,
        ),
    )
    mocked_thread.start()
    mocked_thread.join()

    assert mocked_thread.error == mocked_uploader_function.side_effect
    assert mocked_thread.errors() is True
    assert mocked_thread.get_error() == "mocked error"


def test_ErrorCatchingThread__run__calls_init(mocker):
    mocked_uploader_function = mocker.patch.object(file_uploader, "uploader", autospec=True)

    test_sub_dir = "/sub_dir"

    mocked_super_init = mocker.spy(threading.Thread, "run")
    mocked_thread = ErrorCatchingThread(
        target=mocked_uploader_function,
        args=(
            TEST_FILEPATH,
            test_sub_dir,
            TEST_ZIPDIR,
            TEST_CUSTOMER_ACCOUNT_ID,
            TEST_PASSWORD,
            TEST_USER_ACCOUNT_ID,
        ),
    )
    mocked_thread.start()
    mocked_thread.join()

    assert mocked_super_init.call_count == 1
    assert mocked_thread.get_error() == mocked_thread.error
    assert mocked_thread.errors() is False


def test_MantarrayProcessesMonitor__returns_if_no_target(mocker):
    mocked_super_init = mocker.spy(threading.Thread, "run")
    mocked_thread = ErrorCatchingThread(target=None)
    mocked_thread.start()

    assert mocked_super_init.call_count == 0


def test_download_analysis_from_s3__writes_to_downloads_directory_after_successful_upload(mocker):
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocker.patch.object(file_uploader, "get_sdk_status", autospec=True, return_value="https")

    with tempfile.TemporaryFile() as tmp_file:
        tmp_file.content = "test"
        mocked_post = mocker.patch.object(requests, "get", autospec=True, return_value=tmp_file)
        mocked_open = mocker.patch("builtins.open", autospec=True)
        mocker.patch.object(os.path, "exists", autospec=True, return_value=False)
        mocker.patch.object(os, "makedirs", autospec=True)

        with tempfile.TemporaryDirectory() as temp_dir:
            test_sub_dir = temp_dir

            uploader(
                TEST_FILEPATH,
                test_sub_dir,
                TEST_ZIPDIR,
                TEST_CUSTOMER_ACCOUNT_ID,
                TEST_PASSWORD,
                TEST_USER_ACCOUNT_ID,
            )

            mocked_open.assert_called_once_with(f"{test_sub_dir}.xlsx", "wb")
            mocked_open.return_value.__enter__().write.assert_called_once_with(
                mocked_post.return_value.content
            )
