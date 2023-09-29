# -*- coding: utf-8 -*-
from mantarray_desktop_app.constants import CLOUD_API_ENDPOINT
from mantarray_desktop_app.constants import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app.exceptions import LoginFailedError
from mantarray_desktop_app.exceptions import RefreshFailedError
from mantarray_desktop_app.utils import web_api
from mantarray_desktop_app.utils.web_api import AuthTokens
from mantarray_desktop_app.utils.web_api import get_cloud_api_tokens
from mantarray_desktop_app.utils.web_api import refresh_cloud_api_tokens
from mantarray_desktop_app.utils.web_api import WebWorker
import pytest


class TestWebWorker(WebWorker):
    """Simple subclass that implements abstract methods and nothing else."""

    def job(self):
        pass


def test_get_cloud_api_tokens__return_tokens_if_login_successful(mocker):
    mocked_post = mocker.patch.object(web_api.requests, "post", autospec=True)
    mocked_post.return_value.status_code = 200

    expected_tokens = AuthTokens(access="access", refresh="refresh")
    mocked_post.return_value.json.return_value = {
        "tokens": {
            "access": {"token": expected_tokens.access},
            "refresh": {"token": expected_tokens.refresh},
        },
        "usage_quota": {"jobs_reached": False},
    }

    test_creds = {"customer_id": "cid", "username": "user", "password": "pw"}

    tokens, _ = get_cloud_api_tokens(*test_creds.values())
    assert tokens == expected_tokens

    mocked_post.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/users/login",
        json={**test_creds, "client_type": f"mantarray:{CURRENT_SOFTWARE_VERSION}"},
    )


def test_get_cloud_api_tokens__raises_error_if_login_fails(mocker):
    mocked_post = mocker.patch.object(web_api.requests, "post", autospec=True)
    mocked_post.return_value.status_code = error_status_code = 401

    test_creds = {"customer_id": "cid", "username": "user", "password": "pw"}

    with pytest.raises(LoginFailedError, match=str(error_status_code)):
        get_cloud_api_tokens(*test_creds.values())


def test_refresh_cloud_api_tokens__return_tokens_if_refresh_successful(mocker):
    mocked_post = mocker.patch.object(web_api.requests, "post", autospec=True)
    mocked_post.return_value.status_code = 201

    expected_tokens = AuthTokens(access="new_access", refresh="new_refresh")
    mocked_post.return_value.json.return_value = {
        "access": {"token": expected_tokens.access},
        "refresh": {"token": expected_tokens.refresh},
    }

    test_refresh_token = "old_refresh"

    new_tokens = refresh_cloud_api_tokens(test_refresh_token)
    assert new_tokens == expected_tokens

    mocked_post.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/users/refresh",
        headers={"Authorization": f"Bearer {test_refresh_token}"},
    )


def test_refresh_cloud_api_tokens__raises_error_if_refresh_fails(mocker):
    mocked_post = mocker.patch.object(web_api.requests, "post", autospec=True)
    mocked_post.return_value.status_code = error_status_code = 401

    with pytest.raises(RefreshFailedError, match=str(error_status_code)):
        refresh_cloud_api_tokens("refresh")


def test_WebWorker__cannot_instantiate_if_abstract_methods_not_implemented():
    class BadWebWorker(WebWorker):
        pass

    with pytest.raises(TypeError, match="abstract"):
        BadWebWorker(None, None, None)


def test_WebWorker__does_not_run_when_created(mocker):
    spied_get_tokens = mocker.spy(web_api, "get_cloud_api_tokens")
    spied_job = mocker.spy(TestWebWorker, "job")

    TestWebWorker(None, None, None)

    spied_get_tokens.assert_not_called()
    spied_job.assert_not_called()


def test_WebWorker__runs_correctly_when_called(mocker):
    mocked_get_tokens = mocker.patch.object(web_api, "get_cloud_api_tokens", autospec=True)
    mocked_get_tokens.return_value = (AuthTokens(access="", refresh=""), {"jobs_reached": False})
    spied_job = mocker.spy(TestWebWorker, "job")

    test_creds = {"customer_id": "cid", "user_name": "user", "password": "pw"}

    test_ww = TestWebWorker(*test_creds.values())
    test_ww()

    mocked_get_tokens.assert_called_once_with(*test_creds.values())
    spied_job.assert_called_once_with(test_ww)


def test_WebWorker_request_with_refresh__immediately_returns_response_if_no_auth_errors(mocker):
    mocked_request_func = mocker.Mock()
    mocked_request_func.return_value.status_code = 200

    spied_refresh_tokens = mocker.spy(web_api, "refresh_cloud_api_tokens")

    test_ww = TestWebWorker(None, None, None)

    response = test_ww.request_with_refresh(mocked_request_func)
    assert response == mocked_request_func.return_value

    mocked_request_func.assert_called_once_with()
    spied_refresh_tokens.assert_not_called()


def test_WebWorker_request_with_refresh__gets_new_auth_tokens_and_tries_request_again_if_first_request_encounters_auth_error(
    mocker,
):
    mocked_request_func = mocker.Mock()
    mocked_request_func.return_value.status_code = 401

    mocked_refresh_tokens = mocker.patch.object(web_api, "refresh_cloud_api_tokens", autospec=True)
    mocked_refresh_tokens.return_value = new_tokens = AuthTokens(access="access2", refresh="refresh2")

    test_ww = TestWebWorker(None, None, None)
    test_ww.tokens = initial_tokens = AuthTokens(access="access1", refresh="refresh1")

    response = test_ww.request_with_refresh(mocked_request_func)
    assert response == mocked_request_func.return_value
    assert test_ww.tokens == new_tokens

    assert mocked_request_func.call_args_list == [mocker.call()] * 2
    mocked_refresh_tokens.assert_called_once_with(initial_tokens.refresh)
