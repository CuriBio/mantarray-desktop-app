# -*- coding: utf-8 -*-
import base64
import hashlib
import os
import tempfile
import threading
import zipfile

from mantarray_desktop_app import file_uploader
from mantarray_desktop_app.file_uploader import create_zip_file
from mantarray_desktop_app.file_uploader import ErrorCatchingThread
from mantarray_desktop_app.file_uploader import get_access_token
from mantarray_desktop_app.file_uploader import get_file_md5
from mantarray_desktop_app.file_uploader import get_sdk_status
from mantarray_desktop_app.file_uploader import get_upload_details
from mantarray_desktop_app.file_uploader import upload_file_to_s3
from mantarray_desktop_app.file_uploader import uploader
import pytest
import requests


def test_get_file_md5__creates_and_returns_file_md5_value_correctly(mocker):
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_md5 = mocker.patch.object(hashlib, "md5", autospec=True)
    mocked_b64encode = mocker.patch.object(base64, "b64encode", autospec=True)

    expected_md5 = mocked_b64encode.return_value.decode()
    test_file_name = "test_file_name"

    actual = get_file_md5(test_file_name)
    mocked_open.assert_called_once_with(test_file_name, "rb")
    mocked_md5.assert_called_once_with(mocked_open.return_value.__enter__().read())
    mocked_b64encode.assert_called_once_with(mocked_md5.return_value.digest())
    assert actual == expected_md5


def test_get_access_token__requests_and_returns_access_token_correctly(mocker):
    mocked_post = mocker.patch.object(requests, "post", autospec=True)

    expected_access_token = mocked_post.return_value.json()["access_token"]
    test_customer_id = "cid"
    test_password = "pw"

    actual = get_access_token(test_customer_id, test_password)
    mocked_post.assert_called_once_with(
        "https://<TODO>.execute-api.us-east-1.amazonaws.com/prod-lambda-gw-stage/get_auth",
        json={"username": test_customer_id, "password": test_password},
    )
    assert actual == expected_access_token


def test_get_upload_details__requests_and_returns_upload_details_correctly(mocker):
    mocked_post = mocker.patch.object(requests, "post", autospec=True)

    expected_upload_details = mocked_post.return_value.json()
    test_access_token = "token"
    test_file_name = "fname"
    test_file_md5 = "hash"

    actual = get_upload_details(test_access_token, test_file_name, test_file_md5)
    mocked_post.assert_called_once_with(
        "https://<TODO>.execute-api.us-east-1.amazonaws.com/prod-lambda-gw-stage/sdk_upload",
        json={"file_name": test_file_name},
        headers={"Authorization": f"Bearer {test_access_token}", "Content-MD5": test_file_md5},
    )
    assert actual == expected_upload_details


def test_upload_file_to_s3__uploads_file_correctly(mocker):
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_post = mocker.patch.object(requests, "post", autospec=True)

    expected_open_file = mocked_open.return_value.__enter__()
    test_file_name = "fname"
    test_file_path = "/tmp/fname"
    test_url = "website.com"
    test_data = {"key": "val"}
    test_upload_details = {"presigned_params": {"url": test_url, "fields": test_data}}

    upload_file_to_s3(test_file_path, test_file_name, test_upload_details)

    mocked_open.assert_called_once_with(test_file_path, "rb")
    mocked_post.assert_called_once_with(
        test_url, data=test_data, files={"file": (test_file_name, expected_open_file)}
    )


def test_get_sdk_status__requests_and_returns_sdk_status_correctly(mocker):
    mocked_post = mocker.patch.object(requests, "get", autospec=True)

    expected_sdk_status = mocked_post.return_value.json()["status"]
    test_access_token = "token"
    test_upload_details = {"upload_id": "test_id"}

    actual = get_sdk_status(test_access_token, test_upload_details)
    mocked_post.assert_called_once_with(
        "https://<TODO>.execute-api.us-east-1.amazonaws.com/prod-lambda-gw-stage/get_sdk_status?upload_id=test_id",
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

    test_dir_path = "/tmp"
    test_file_name = "test_h5_files"
    test_zipped_path = f"{test_dir_path}/zipped_recordings/cid"

    zipped_file_path = create_zip_file(test_dir_path, test_file_name, test_zipped_path)
    mocked_zip_function.assert_called_once_with(f"{os.path.join(test_zipped_path, test_file_name)}.zip", "w")
    assert len(spied_os_join.call_args_list) == 5
    assert zipped_file_path == f"{os.path.join(test_zipped_path, test_file_name)}.zip"


def test_create_zip_file__create_zip_file_should_not_be_called_with_previously_failed_zip_file(mocker):
    mocked_create_zip_file = mocker.patch.object(file_uploader, "create_zip_file", autospec=True)
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocker.patch.object(file_uploader, "get_sdk_status", autospec=True, return_value="analysis complete")

    test_file_name = "zip_file"
    test_file_path = "/test"
    test_zip_dir = "/test/zipped_recordings"
    test_customer_account_id = "cid"
    test_password = "pw"

    uploader(test_file_path, test_file_name, test_zip_dir, test_customer_account_id, test_password)
    mocked_create_zip_file.assert_not_called()


def test_uploader__runs_upload_procedure_correctly(mocker):
    mocked_create_zip_file = mocker.patch.object(file_uploader, "create_zip_file", autospec=True)
    mocked_get_file_md5 = mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocked_get_access_token = mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocked_get_upload_details = mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocked_upload_file = mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocked_get_sdk_status = mocker.patch.object(
        file_uploader, "get_sdk_status", autospec=True, return_value="analysis complete"
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        expected_upload_details = mocked_get_upload_details.return_value
        expected_access_token = mocked_get_access_token.return_value
        expected_md5 = mocked_get_file_md5.return_value

        test_dir = tmp_dir
        test_file_path = "/test"
        test_zip_dir = "/test/zipped_recordings"
        test_customer_account_id = "cid"
        test_password = "pw"
        zipped_file_name = f"{test_dir}.zip"
        zipped_file_path = mocked_create_zip_file.return_value

        uploader(test_file_path, test_dir, test_zip_dir, test_customer_account_id, test_password)

        mocked_create_zip_file.assert_called_once_with(
            test_file_path, test_dir, f"{os.path.join(test_zip_dir, test_customer_account_id)}"
        )
        mocked_get_access_token.assert_called_once_with(test_customer_account_id, test_password)
        mocked_get_file_md5.assert_called_once_with(zipped_file_path)
        mocked_get_upload_details.assert_called_once_with(
            expected_access_token, zipped_file_name, expected_md5
        )
        mocked_upload_file.assert_called_once_with(
            zipped_file_path, zipped_file_name, expected_upload_details
        )
        mocked_get_sdk_status.assert_called_once_with(expected_access_token, expected_upload_details)


def test_uploader__uploader_raises_error_if_get_sdk_status_returns_error_message_from_aws(mocker):
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocker.patch.object(file_uploader, "get_sdk_status", autospec=True, return_value="error in upload")

    with tempfile.TemporaryDirectory() as tmp_dir:

        test_dir = tmp_dir
        test_file_path = "/test"
        test_zip_dir = "/test/zipped_recordings"
        test_customer_account_id = "cid"
        test_password = "pw"

        with pytest.raises(Exception) as e:
            thread = ErrorCatchingThread(
                target=uploader,
                args=(test_file_path, test_dir, test_zip_dir, test_customer_account_id, test_password),
            )
            thread.start()
            thread.join()

            assert thread.error == e
            assert thread.errors() is True


def test_uploader__uploader_sleeps_same_number_of_max_loops(mocker):
    mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)
    mocked_get_sdk_status = mocker.patch.object(
        file_uploader, "get_sdk_status", autospec=True, return_value="status"
    )

    mocked_sleep = mocker.patch.object(file_uploader, "sleep", autospec=True)

    test_file = "test_name"
    test_file_path = "/test"
    test_zip_dir = "/test/zipped_recordings"
    test_customer_account_id = "cid"
    test_password = "pw"

    uploader(
        test_file_path, test_file, test_zip_dir, test_customer_account_id, test_password, max_num_loops=3
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

    mocked_sleep = mocker.patch.object(file_uploader, "sleep", autospec=True)

    test_file = "test_name"
    test_file_path = "/test"
    test_zip_dir = "/test/zipped_recordings"
    test_customer_account_id = "cid"
    test_password = "pw"

    uploader(
        test_file_path, test_file, test_zip_dir, test_customer_account_id, test_password, max_num_loops=2
    )
    mocked_sleep.assert_called_once_with(5)
    assert len(mocked_get_sdk_status.call_args_list) == 2


def test_ErrorCatchingThread__correctly_returns_target_function(mocker):
    mocked_uploader_function = mocker.patch.object(file_uploader, "uploader", return_value="mocked_return")

    mocked_thread = ErrorCatchingThread(target=mocked_uploader_function)
    mocked_thread.start()
    mocked_thread.join()

    assert mocked_thread.result == mocked_uploader_function.return_value


def test_ErrorCatchingThread__correctly_returns_error_to_caller_thread(mocker):
    mocked_uploader_function = mocker.patch.object(file_uploader, "uploader", autospec=True)
    mocked_uploader_function.side_effect = Exception("mocked error")

    test_file_path = "/test"
    test_sub_dir = "/sub_dir"
    test_zip_dir = "/test/zipped_recordings"
    test_customer_id = "username"
    test_password = "password"

    mocked_thread = ErrorCatchingThread(
        target=mocked_uploader_function,
        args=(test_file_path, test_sub_dir, test_zip_dir, test_customer_id, test_password),
    )
    mocked_thread.start()
    mocked_thread.join()

    assert mocked_thread.error == mocked_uploader_function.side_effect
    assert mocked_thread.errors() is True


def test_ErrorCatchingThread__run__calls_init(mocker):
    mocked_uploader_function = mocker.patch.object(
        file_uploader, "uploader", autospec=True, return_value="analysis pending"
    )

    test_file_path = "/test"
    test_sub_dir = "/sub_dir"
    test_zip_dir = "/test/zipped_recordings"
    test_customer_id = "username"
    test_password = "password"

    mocked_super_init = mocker.spy(threading.Thread, "run")
    mocked_thread = ErrorCatchingThread(
        target=mocked_uploader_function,
        args=(test_file_path, test_sub_dir, test_zip_dir, test_customer_id, test_password),
    )
    mocked_thread.start()
    mocked_thread.join()

    assert mocked_super_init.call_count == 1
    assert mocked_thread.result == mocked_uploader_function.return_value
    assert mocked_thread.get_upload_status() == mocked_uploader_function.return_value


def test_MantarrayProcessesMonitor__returns_if_no_target(mocker):
    mocked_super_init = mocker.spy(threading.Thread, "run")
    mocked_thread = ErrorCatchingThread(
        target=None,
    )
    mocked_thread.start()

    assert mocked_super_init.call_count == 0
