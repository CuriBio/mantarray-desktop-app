# -*- coding: utf-8 -*-
import base64
import hashlib

from mantarray_desktop_app import file_uploader
from mantarray_desktop_app.file_uploader import get_access_token
from mantarray_desktop_app.file_uploader import get_file_md5
from mantarray_desktop_app.file_uploader import get_upload_details
from mantarray_desktop_app.file_uploader import upload_file_to_s3
from mantarray_desktop_app.file_uploader import uploader
import requests


def test_get_file_md5__creates_and_returns_file_md5_value_correctly(mocker):
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_md5 = mocker.patch.object(hashlib, "md5", autospec=True)
    mocked_b64encode = mocker.patch.object(base64, "b64encode", autospec=True)

    expected_md5 = mocked_b64encode.return_value.decode()
    test_file_name = "test_file_name"

    actual = get_file_md5(test_file_name)
    mocked_open.assert_called_once_with(test_file_name, "r")
    mocked_md5.assert_called_once_with(mocked_open.return_value.__enter__().read().encode())
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
    test_url = "website.com"
    test_data = {"key": "val"}
    test_upload_details = {"presigned_params": {"url": test_url, "fields": test_data}}

    upload_file_to_s3(test_file_name, test_upload_details)
    mocked_open.assert_called_once_with(test_file_name, "rb")
    mocked_post.assert_called_once_with(
        test_url, data=test_data, files={"file": (test_file_name, expected_open_file)}
    )


def test_uploader__runs_upload_procedure_correctly(mocker):
    mocked_get_file_md5 = mocker.patch.object(file_uploader, "get_file_md5", autospec=True)
    mocked_get_access_token = mocker.patch.object(file_uploader, "get_access_token", autospec=True)
    mocked_get_upload_details = mocker.patch.object(file_uploader, "get_upload_details", autospec=True)
    mocked_upload_file = mocker.patch.object(file_uploader, "upload_file_to_s3", autospec=True)

    expected_upload_details = mocked_get_upload_details.return_value
    expected_access_token = mocked_get_access_token.return_value
    expected_md5 = mocked_get_file_md5.return_value
    test_file_name = "fname"
    test_customer_account_id = "cid"
    test_password = "pw"

    uploader(test_file_name, test_customer_account_id, test_password)
    mocked_get_access_token.assert_called_once_with(test_customer_account_id, test_password)
    mocked_get_file_md5.assert_called_once_with(test_file_name)
    mocked_get_upload_details.assert_called_once_with(expected_access_token, test_file_name, expected_md5)
    mocked_upload_file.assert_called_once_with(test_file_name, expected_upload_details)
