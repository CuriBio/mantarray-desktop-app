# -*- coding: utf-8 -*-
from abc import ABC
from abc import abstractmethod
from collections import namedtuple
from typing import Any
from typing import Callable
from typing import Dict
from typing import Tuple

from mantarray_desktop_app.constants import CLOUD_API_ENDPOINT
from mantarray_desktop_app.constants import CURRENT_SOFTWARE_VERSION
import requests
from requests import Response

from ..exceptions import LoginFailedError
from ..exceptions import RefreshFailedError


AuthTokens = namedtuple("AuthTokens", ["access", "refresh"])


def _get_tokens(response_json: Dict[str, Any]) -> AuthTokens:
    return AuthTokens(access=response_json["access"]["token"], refresh=response_json["refresh"]["token"])


def get_cloud_api_tokens(
    customer_id: str, user_name: str, password: str
) -> Tuple[AuthTokens, Dict[str, Any]]:
    """Login and get tokens.

    Args:
        customer_id: current user's customer account id.
        user_name: current user.
        password: current user's password.
    """
    response = requests.post(
        f"https://{CLOUD_API_ENDPOINT}/users/login",
        json={
            "customer_id": customer_id,
            "username": user_name,
            "password": password,
            "client_type": f"mantarray:{CURRENT_SOFTWARE_VERSION}",
        },
    )
    response_json = response.json()
    if response.status_code != 200:
        raise LoginFailedError(response.status_code, response_json["detail"])

    return _get_tokens(response_json["tokens"]), response_json["usage_quota"]


def refresh_cloud_api_tokens(refresh_token: str) -> AuthTokens:
    """Use refresh token to get new set of auth tokens."""
    response = requests.post(
        f"https://{CLOUD_API_ENDPOINT}/users/refresh", headers={"Authorization": f"Bearer {refresh_token}"}
    )
    if response.status_code != 201:
        raise RefreshFailedError(response.status_code)

    response_json = response.json()
    return _get_tokens(response_json)


class WebWorker(ABC):
    """Generic base class that provides basic utilities.

    Main purpose of this class is to store the auth tokens provide `request_with_refresh`
    which allows a request that fails due to an expired access token to be tried again
    after getting new tokens.

    Also implements `__call__` and `job` which provide a simple interface for subclasses
    to interact with the cloud API after logging in.

    Args:
        customer_id: current customer's account id.
        user_name: current user's account id.
        password: current user's account password.
    """

    def __init__(self, customer_id: str, user_name: str, password: str) -> None:
        self.customer_id = customer_id
        self.user_name = user_name
        self.password = password

        self.tokens: AuthTokens

    def __call__(self) -> None:
        """Login and then do the job."""
        tokens, _ = get_cloud_api_tokens(self.customer_id, self.user_name, self.password)
        self.tokens = tokens
        self.job()

    @abstractmethod
    def job(self) -> None:
        """Interact with the Cloud API."""
        pass

    def request_with_refresh(self, request_func: Callable[..., Response]) -> Response:
        """Make request, refresh once if needed, and try request once more."""
        response = request_func()
        # if auth token expired then request will return 401 code
        if response.status_code == 401:
            # get new tokens and try request once more
            self.tokens = refresh_cloud_api_tokens(self.tokens.refresh)
            response = request_func()
            # Tanner (5/26/22): could add error handling if request fails again or if refresh fails

        return response
