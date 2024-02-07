# -*- coding: utf-8 -*-
import copy
import os

from mantarray_desktop_app import CLOUD_API_ENDPOINT
from mantarray_desktop_app.constants import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app.constants import SOFTWARE_RELEASE_CHANNEL
from mantarray_desktop_app.exceptions import FirmwareAndSoftwareNotCompatibleError
from mantarray_desktop_app.exceptions import FirmwareDownloadError
from mantarray_desktop_app.simulators.mc_simulator import MantarrayMcSimulator
from mantarray_desktop_app.sub_processes.mc_comm import download_firmware_updates
from mantarray_desktop_app.utils.web_api import AuthTokens
from mantarray_desktop_app.workers import firmware_downloader
from mantarray_desktop_app.workers.firmware_downloader import call_firmware_download_route
from mantarray_desktop_app.workers.firmware_downloader import check_for_local_firmware_versions
from mantarray_desktop_app.workers.firmware_downloader import check_versions
from mantarray_desktop_app.workers.firmware_downloader import get_latest_firmware_versions
from mantarray_desktop_app.workers.firmware_downloader import verify_software_firmware_compatibility
import pytest
import requests
from requests.exceptions import ConnectionError

from ..fixtures import random_semver


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


def test_call_firmware_download_route__handles_response_error_code_correctly__without_json(mocker):
    expected_error_code = 400
    expected_reason = "bad request"

    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.status_code = expected_error_code
    mocked_get.return_value.json.side_effect = Exception()
    mocked_get.return_value.reason = expected_reason

    test_error_message = "err msg"
    with pytest.raises(
        FirmwareDownloadError,
        match=f"{test_error_message}. Status code: {expected_error_code}, Reason: {expected_reason}",
    ):
        call_firmware_download_route("url", error_message=test_error_message)


def test_call_firmware_download_route__handles_response_error_code_correctly__without_message_in_json(mocker):
    expected_error_code = 400
    expected_reason = "bad request"

    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.status_code = expected_error_code
    mocked_get.return_value.json.return_value = {}
    mocked_get.return_value.reason = expected_reason

    test_error_message = "err msg"
    with pytest.raises(
        FirmwareDownloadError,
        match=f"{test_error_message}. Status code: {expected_error_code}, Reason: {expected_reason}",
    ):
        call_firmware_download_route("url", error_message=test_error_message)


def test_call_firmware_download_route__handles_response_error_code_correctly__with_message_in_json(mocker):
    expected_error_code = 400
    expected_message = "bad request"

    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.status_code = expected_error_code
    mocked_get.return_value.json.return_value = {"message": expected_message}
    mocked_get.return_value.reason = "reason"

    test_error_message = "err msg"
    with pytest.raises(
        FirmwareDownloadError,
        match=f"{test_error_message}. Status code: {expected_error_code}, Reason: {expected_message}",
    ):
        call_firmware_download_route("url", error_message=test_error_message)


def test_check_for_local_firmware_versions__return_correctly_if_fw_update_path_is_not_a_directory(mocker):
    mocked_is_dir = mocker.patch.object(
        firmware_downloader.os.path, "isdir", autospec=True, return_value=False
    )
    mocked_listdir = mocker.patch.object(firmware_downloader.os, "listdir", autospec=True, return_value=[])

    test_fw_update_dir_path = "some/dir"
    assert check_for_local_firmware_versions(test_fw_update_dir_path) is None

    mocked_is_dir.assert_called_once_with(test_fw_update_dir_path)
    mocked_listdir.assert_not_called()


def test_check_for_local_firmware_versions__return_correctly_if_fw_update_directory_is_empty(mocker):
    mocked_is_dir = mocker.patch.object(
        firmware_downloader.os.path, "isdir", autospec=True, return_value=True
    )
    mocked_listdir = mocker.patch.object(firmware_downloader.os, "listdir", autospec=True, return_value=[])

    test_fw_update_dir_path = "some/dir"
    assert check_for_local_firmware_versions(test_fw_update_dir_path) is None

    mocked_is_dir.assert_called_once_with(test_fw_update_dir_path)
    mocked_listdir.assert_called_once_with(test_fw_update_dir_path)


@pytest.mark.parametrize("main_fw_update,channel_fw_update", [(False, True), (True, False), (True, True)])
def test_check_for_local_firmware_versions__return_correctly_if_fw_update_directory_contains_files(
    main_fw_update, channel_fw_update, mocker
):
    mocked_is_dir = mocker.patch.object(
        firmware_downloader.os.path, "isdir", autospec=True, return_value=True
    )
    mocked_listdir = mocker.patch.object(firmware_downloader.os, "listdir", autospec=True)

    expected_fw_versions = {
        "main_fw": "1.1.1" if main_fw_update else "0.0.0",
        "channel_fw": "2.2.2" if channel_fw_update else "0.0.0",
    }

    mocked_listdir.return_value = [
        f"{fw_type.split('_')[0]}-{version}.bin"
        for fw_type, version in expected_fw_versions.items()
        if version != "0.0.0"
    ] + [".DS_Store"]

    test_fw_update_dir_path = "some/dir"
    assert check_for_local_firmware_versions(test_fw_update_dir_path) == {
        "latest_versions": {"ma_sw": CURRENT_SOFTWARE_VERSION, **expected_fw_versions},
        "download": False,
    }

    mocked_is_dir.assert_called_once_with(test_fw_update_dir_path)
    mocked_listdir.assert_called_once_with(test_fw_update_dir_path)


def test_get_latest_firmware_versions__calls_api_endpoint_correctly_and_returns_values_correctly(mocker):
    expected_latest_main_fw_version = "1.0.0"
    expected_latest_channel_fw_version = "1.0.1"
    expected_latest_sw_version = "1.0.2"
    expected_response_dict = {
        "latest_versions": {
            "main_fw": expected_latest_main_fw_version,
            "channel_fw": expected_latest_channel_fw_version,
            "ma_sw": expected_latest_sw_version,
        },
        "download": True,
    }

    mocked_call = mocker.patch.object(firmware_downloader, "call_firmware_download_route", autospec=True)
    mocked_call.return_value.json.return_value = copy.deepcopy(expected_response_dict["latest_versions"])

    test_result_dict = {"latest_versions": {}}
    test_serial_number = MantarrayMcSimulator.default_mantarray_serial_number
    get_latest_firmware_versions(test_result_dict, test_serial_number)

    is_prod = SOFTWARE_RELEASE_CHANNEL == "prod"
    mocked_call.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/mantarray/versions/{test_serial_number}/{is_prod}",
        error_message="Error getting latest firmware versions",
    )

    assert test_result_dict == expected_response_dict


@pytest.mark.parametrize(
    "min_sw,max_sw,current_sw",
    [("2.0.0", "2.0.0", "2.0.0"), ("2.0.0", "11.0.0", "2.0.0"), ("2.0.0", "11.0.0", "11.0.0")],
)
def test_verify_software_firmware_compatibility__does_not_raise_error_if_current_sw_version_is_compatible_with_current_fw_version(
    min_sw, max_sw, current_sw, mocker
):
    mocked_call = mocker.patch.object(firmware_downloader, "call_firmware_download_route", autospec=True)
    mocked_call.return_value.json.return_value = {"min_sw": min_sw, "max_sw": max_sw}

    mocker.patch.object(firmware_downloader, "CURRENT_SOFTWARE_VERSION", current_sw)

    test_main_fw = random_semver()
    verify_software_firmware_compatibility(test_main_fw)

    is_prod = SOFTWARE_RELEASE_CHANNEL == "prod"
    mocked_call.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/mantarray/software-range/{test_main_fw}/{is_prod}",
        error_message="Error checking software/firmware compatibility",
    )


@pytest.mark.parametrize(
    "min_sw,max_sw,current_sw",
    [
        ("2.0.0", "2.0.0", "1.0.0"),
        ("2.0.0", "2.0.0", "3.0.0"),
        ("1.0.0", "2.0.0", "11.0.0"),
        ("11.0.0", "22.0.0", "2.0.0"),
    ],
)
def test_verify_software_firmware_compatibility__raises_error_if_current_sw_version_is_not_compatible_with_current_fw_version(
    min_sw, max_sw, current_sw, mocker
):
    mocked_call = mocker.patch.object(firmware_downloader, "call_firmware_download_route", autospec=True)
    mocked_call.return_value.json.return_value = {"min_sw": min_sw, "max_sw": max_sw}

    mocker.patch.object(firmware_downloader, "CURRENT_SOFTWARE_VERSION", current_sw)

    test_main_fw = random_semver()
    with pytest.raises(FirmwareAndSoftwareNotCompatibleError, match=max_sw):
        verify_software_firmware_compatibility(test_main_fw)


def test_check_versions__does_not_ping_cloud_at_all_if_local_firmware_files_found(mocker):
    test_result_dict = {}
    test_serial_number = MantarrayMcSimulator.default_mantarray_serial_number
    test_main_fw_version = MantarrayMcSimulator.default_main_firmware_version
    test_fw_update_dir_path = "some/path"

    local_latest_versions = {"latest_versions": "Anything"}
    mocked_check_local = mocker.patch.object(
        firmware_downloader,
        "check_for_local_firmware_versions",
        autospec=True,
        return_value=local_latest_versions,
    )

    mocked_verify = mocker.patch.object(
        firmware_downloader, "verify_software_firmware_compatibility", autospec=True
    )
    mocked_get_latest = mocker.patch.object(
        firmware_downloader, "get_latest_firmware_versions", autospec=True
    )

    check_versions(test_result_dict, test_serial_number, test_main_fw_version, test_fw_update_dir_path)
    assert test_result_dict == local_latest_versions

    mocked_check_local.assert_called_once_with(test_fw_update_dir_path)
    mocked_verify.assert_not_called()
    mocked_get_latest.assert_not_called()


@pytest.mark.parametrize("local_check_result", [None, Exception()])
def test_check_versions__verifies_current_versions_before_checking_for_new_versions(
    local_check_result, mocker
):
    test_result_dict = {}
    test_serial_number = MantarrayMcSimulator.default_mantarray_serial_number
    test_main_fw_version = MantarrayMcSimulator.default_main_firmware_version
    test_fw_update_dir_path = "some/path"

    mocker.patch.object(
        firmware_downloader,
        "check_for_local_firmware_versions",
        autospec=True,
        side_effect=[local_check_result],
    )

    mocked_verify = mocker.patch.object(
        firmware_downloader, "verify_software_firmware_compatibility", autospec=True
    )

    mocked_get_latest = mocker.patch.object(
        firmware_downloader, "get_latest_firmware_versions", autospec=True
    )
    mocked_get_latest.side_effect = lambda *args: mocked_verify.assert_called_once()

    check_versions(test_result_dict, test_serial_number, test_main_fw_version, test_fw_update_dir_path)

    mocked_verify.assert_called_once_with(test_main_fw_version)
    mocked_get_latest.assert_called_once_with(test_result_dict, test_serial_number)


@pytest.mark.parametrize("main_fw_update,channel_fw_update", [(False, True), (True, False), (True, True)])
def test_download_firmware_updates__loads_local_files_correctly__when_download_is_not_required(
    main_fw_update, channel_fw_update, mocker
):
    test_customer_id = None
    test_username = None
    test_password = None
    test_fw_update_dir_path = "fw/dir"

    test_update_versions = {
        "main": "1.1.1" if main_fw_update else None,
        "channel": "2.2.2" if channel_fw_update else None,
    }
    expected_file_contents = {
        fw_type: f"{fw_type}-{version}-data" for fw_type, version in test_update_versions.items() if version
    }

    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_file_obj = mocked_open.return_value.__enter__.return_value
    mocked_file_obj.read.side_effect = list(expected_file_contents.values())

    test_result_dict = {
        "communication_type": "firmware_update",
        "command": "download_firmware_updates",
        "main": None,
        "channel": None,
    }

    download_firmware_updates(
        test_result_dict,
        test_update_versions["main"],
        test_update_versions["channel"],
        test_customer_id,
        test_username,
        test_password,
        test_fw_update_dir_path,
    )

    assert mocked_open.call_args_list == [
        mocker.call(os.path.join(test_fw_update_dir_path, f"{fw_type}-{version}.bin"), "rb")
        for fw_type, version in test_update_versions.items()
        if version
    ]
    assert test_result_dict == {**test_result_dict, **expected_file_contents}


@pytest.mark.parametrize("main_fw_update,channel_fw_update", [(False, True), (True, False), (True, True)])
def test_download_firmware_updates__get_access_token_then_downloads_specified_firmware_files_and_returns_values_correctly__when_download_is_required(
    main_fw_update, channel_fw_update, mocker
):
    test_customer_id = "id"
    test_username = "user"
    test_password = "pw"
    test_fw_update_dir_path = None

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
    mocked_get_token.return_value = (
        AuthTokens(access=test_access_token, refresh=""),
        {"jobs_reached": False},
    )

    def call_se(url, *args, params=None, **kwargs):
        if params is None:
            params = {}

        mocked_call_return = mocker.MagicMock()

        is_main = "main" in url
        if "firmware" in url:
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
        test_fw_update_dir_path,
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
                f"https://{CLOUD_API_ENDPOINT}/mantarray/firmware/{fw_type}/{test_new_version}",
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
        download_firmware_updates({}, None, None, "any customer id", "any user", "any pw", "any/dir")
