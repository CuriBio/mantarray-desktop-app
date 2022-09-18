# -*- coding: utf-8 -*-
import copy

from mantarray_desktop_app import CLOUD_API_ENDPOINT
from mantarray_desktop_app import FirmwareDownloadError
from mantarray_desktop_app.simulators.mc_simulator import MantarrayMcSimulator
from mantarray_desktop_app.sub_processes.mc_comm import download_firmware_updates
from mantarray_desktop_app.sub_processes.mc_comm import get_latest_firmware_versions
from mantarray_desktop_app.workers import firmware_downloader
from mantarray_desktop_app.workers.firmware_downloader import call_firmware_download_route
import pytest
import requests
from requests.exceptions import ConnectionError


def test_call_firmware_download_route__calls_requests_get_correctly(mocker):
    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.status_code = 200

    test_url = "url"
    test_headers = {"Authorization": "Bearer token"}
    call_firmware_download_route("url", headers=test_headers, error_message="err msg")

    mocked_get.assert_called_once_with(test_url, headers=test_headers)


def test_call_firmware_download_route__handles_connection_error_correctly(mocker):
    mocker.patch.object(requests, "get", autospec=True, side_effect=ConnectionError)

    test_error_message = "err msg"
    with pytest.raises(FirmwareDownloadError, match=test_error_message):
        call_firmware_download_route("url", error_message=test_error_message)


def test_call_firmware_download_route__handles_response_error_code_correctly(mocker):
    expected_error_code = 400
    expected_reason = "bad request"

    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.status_code = expected_error_code
    mocked_get.return_value.reason = expected_reason

    test_error_message = "err msg"
    with pytest.raises(
        FirmwareDownloadError,
        match=f"{test_error_message} Status code: {expected_error_code}, Reason: {expected_reason}",
    ):
        call_firmware_download_route("url", error_message=test_error_message)


def test_get_latest_firmware_versions__calls_api_endpoint_correctly_and_returns_values_correctly(mocker):
    expected_latest_main_fw_version = "1.0.0"
    expected_latest_channel_fw_version = "1.0.1"
    expected_latest_sw_version = "1.0.2"
    expected_response_dict = {
        "latest_versions": {
            "main-fw": expected_latest_main_fw_version,
            "channel-fw": expected_latest_channel_fw_version,
            "sw": expected_latest_sw_version,
        }
    }

    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.json.return_value = copy.deepcopy(expected_response_dict)

    test_result_dict = {"latest_versions": {}}
    test_serial_number = MantarrayMcSimulator.default_mantarray_serial_number
    get_latest_firmware_versions(test_result_dict, test_serial_number)
    mocked_get.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/mantarray/firmware_latest",
        params={"serial_number": test_serial_number},
    )

    assert test_result_dict == expected_response_dict


@pytest.mark.parametrize(
    "main_fw_update,channel_fw_update",
    [(False, True), (True, False), (True, True)],
)
def test_download_firmware_updates__get_access_token_then_downloads_specified_firmware_files_and_returns_values_correctly(
    main_fw_update, channel_fw_update, mocker
):
    test_customer_id = "id"
    test_username = "user"
    test_password = "pw"
    test_access_token = "at"

    test_main_presigned_url = "main_url"
    test_channel_presigned_url = "channel_url"

    test_new_version = "1.0.0"

    test_main_fw_to_download = test_new_version if main_fw_update else None
    test_channel_fw_to_download = test_new_version if channel_fw_update else None

    expected_main_fw_bytes = bytes("main", encoding="ascii") if main_fw_update else None
    expected_channel_fw_bytes = bytes("channel", encoding="ascii") if channel_fw_update else None
    expected_response_dict = {
        "communication_type": "firmware_update",
        "command": "download_firmware_updates",
        "main": expected_main_fw_bytes,
        "channel": expected_channel_fw_bytes,
    }

    mocked_get_token = mocker.patch.object(firmware_downloader, "get_cloud_api_tokens", autospec=True)
    mocked_get_token.return_value.access = test_access_token

    def call_se(url, *args, params=None, **kwargs):
        if params is None:
            params = {}

        mocked_call_return = mocker.MagicMock()

        is_main = params.get("firmware_type") == "main" or "main" in url
        if "firmware_download" in url:
            presigned_url = test_main_presigned_url if is_main else test_channel_presigned_url
            mocked_call_return.json = lambda: {"presigned_url": presigned_url}
        else:
            content = expected_main_fw_bytes if is_main else expected_channel_fw_bytes
            mocked_call_return.content = content

        return mocked_call_return

    mocked_call = mocker.patch.object(
        firmware_downloader, "call_firmware_download_route", autospec=True, side_effect=call_se
    )

    test_result_dict = {
        "communication_type": "firmware_update",
        "command": "download_firmware_updates",
        "main": None,
        "channel": None,
    }
    download_firmware_updates(
        test_result_dict,
        test_main_fw_to_download,
        test_channel_fw_to_download,
        test_customer_id,
        test_username,
        test_password,
    )

    mocked_get_token.assert_called_once_with(test_customer_id, test_username, test_password)

    assert mocked_call.call_count == 2 * (int(main_fw_update) + int(channel_fw_update))
    call_idx = 0
    call_idx_offset = 1 + int(main_fw_update and channel_fw_update)
    for update_needed, fw_type, presigned_url in (
        (main_fw_update, "main", test_main_presigned_url),
        (channel_fw_update, "channel", test_channel_presigned_url),
    ):
        if update_needed:
            assert mocked_call.call_args_list[call_idx] == mocker.call(
                f"https://{CLOUD_API_ENDPOINT}/mantarray/firmware_download",
                params={"firmware_version": test_new_version, "firmware_type": fw_type},
                headers={"Authorization": f"Bearer {test_access_token}"},
                error_message=f"Error getting presigned URL for {fw_type} firmware",
            ), fw_type
            assert mocked_call.call_args_list[call_idx + call_idx_offset] == mocker.call(
                presigned_url, error_message=f"Error during download of {fw_type} firmware"
            ), fw_type
            call_idx += 1

    assert test_result_dict == expected_response_dict


def test_download_firmware_updates__raises_error_if_no_updates_needed():
    with pytest.raises(FirmwareDownloadError, match="No firmware types specified"):
        download_firmware_updates({}, None, None, "any customer id", "any user", "any pw")