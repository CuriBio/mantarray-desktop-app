# -*- coding: utf-8 -*-
import copy
import math
from random import choice
from random import randint
from zlib import crc32

from mantarray_desktop_app import CLOUD_API_ENDPOINT
from mantarray_desktop_app import firmware_downloader
from mantarray_desktop_app import FirmwareDownloadError
from mantarray_desktop_app import FirmwareUpdateCommandFailedError
from mantarray_desktop_app import FirmwareUpdateTimeoutError
from mantarray_desktop_app import MAX_CHANNEL_FIRMWARE_UPDATE_DURATION_SECONDS
from mantarray_desktop_app import MAX_MAIN_FIRMWARE_UPDATE_DURATION_SECONDS
from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app.firmware_downloader import call_firmware_route
from mantarray_desktop_app.mc_comm import download_firmware_updates
from mantarray_desktop_app.mc_comm import get_latest_firmware_versions
from mantarray_desktop_app.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
import pytest
import requests
from requests.exceptions import ConnectionError
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_patch_print,
    fixture_four_board_mc_comm_process,
    fixture_four_board_mc_comm_process_no_handshake,
    fixture_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_call_firmware_route__calls_requests_get_correctly(mocker):
    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.status_code = 200

    test_url = "url"
    test_headers = {"Authorization": "Bearer token"}
    call_firmware_route("url", headers=test_headers, error_message="err msg")

    mocked_get.assert_called_once_with(test_url, headers=test_headers)


def test_call_firmware_route__handles_connection_error_correctly(mocker):
    mocker.patch.object(requests, "get", autospec=True, side_effect=ConnectionError)

    test_error_message = "err msg"
    with pytest.raises(FirmwareDownloadError, match=test_error_message):
        call_firmware_route("url", error_message=test_error_message)


def test_call_firmware_route__handles_response_error_code_correctly(mocker):
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
        call_firmware_route("url", error_message=test_error_message)


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
    test_hw_version = "0.0.1"
    get_latest_firmware_versions(test_result_dict, test_hw_version)
    mocked_get.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/firmware_latest?hardware_version={test_hw_version}"
    )

    assert test_result_dict == expected_response_dict


@pytest.mark.parametrize(
    "main_fw_update,channel_fw_update",
    [(False, True), (True, False), (True, True)],
)
def test_download_firmware_updates__gets_auth_then_downloads_specified_firmware_files_and_returns_values_correctly(
    main_fw_update, channel_fw_update, mocker
):
    test_username = "user"
    test_password = "pw"
    test_access_token = "access_token"

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

    mocked_post = mocker.patch.object(requests, "post", autospec=True)
    mocked_post.return_value.json.return_value = {"access_token": test_access_token}

    def call_se(url, *args, **kwargs):
        mocked_call_return = mocker.MagicMock()

        if "firmware_download" in url:
            mocked_call_return.json = lambda: {
                "presigned_url": test_main_presigned_url if "main" in url else test_channel_presigned_url
            }
        else:
            mocked_call_return.content = (
                expected_main_fw_bytes if "main" in url else expected_channel_fw_bytes
            )

        return mocked_call_return

    mocked_call = mocker.patch.object(
        firmware_downloader, "call_firmware_route", autospec=True, side_effect=call_se
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
        test_username,
        test_password,
    )

    mocked_post.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/get_auth", json={"username": test_username, "password": test_password}
    )

    assert mocked_call.call_count == 2 * (int(main_fw_update) + int(channel_fw_update))
    call_idx = 0
    call_idx_offset = 1 + int(main_fw_update and channel_fw_update)
    for update_needed, fw_type, presigned_url in (
        (main_fw_update, "main", test_main_presigned_url),
        (channel_fw_update, "channel", test_channel_presigned_url),
    ):
        if update_needed:
            assert mocked_call.call_args_list[call_idx] == mocker.call(
                f"https://{CLOUD_API_ENDPOINT}/firmware_download?firmware_version={test_new_version}&firmware_type={fw_type}",
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
        download_firmware_updates(
            {},
            None,
            None,
            "any user",
            "any pw",
        )


def test_McCommunicationProcess__handles_error_in_firmware_update_worker_thread(
    four_board_mc_comm_process_no_handshake, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue, to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]

    expected_error_msg = "error in thread"
    mocker.patch.object(
        mc_comm.ErrorCatchingThread, "get_error", autospec=True, return_value=expected_error_msg
    )

    mocker.patch.object(mc_comm.ErrorCatchingThread, "start", autospec=True)
    mocker.patch.object(mc_comm.ErrorCatchingThread, "errors", autospec=True, return_value=True)
    # mock so thread will appear complete on the second iteration of mc_process
    mocker.patch.object(mc_comm.ErrorCatchingThread, "is_alive", autospec=True, side_effect=[True, False])

    # send command to mc_process. Using get_latest_firmware_versions here arbitrarily, but functionality should be the same for any worker thread
    test_command = {
        "communication_type": "firmware_update",
        "command": "get_latest_firmware_versions",
        "hardware_version": "1.0.0",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(test_command), from_main_queue
    )

    # run first iteration and make sure command response not sent to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_empty(to_main_queue)
    # run second iteration and make sure correct command response sent to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == {
        "communication_type": "firmware_update",
        "command": "get_latest_firmware_versions",
        "error": expected_error_msg,
    }


def test_McCommunicationProcess__handles_successful_completion_of_get_latest_firmware_versions_worker_thread(
    four_board_mc_comm_process_no_handshake, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue, to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]

    expected_main_fw_version = "1.1.1"
    expected_channel_fw_version = "2.2.2"
    expected_sw_version = "3.3.3"
    expected_latest_versions = {
        "main-fw": expected_main_fw_version,
        "channel-fw": expected_channel_fw_version,
        "sw": expected_sw_version,
    }

    def init_se(obj, target, args):
        args[0].update({"latest_versions": expected_latest_versions})

    # mock init so it populates output dict immediately
    mocker.patch.object(mc_comm.ErrorCatchingThread, "__init__", autospec=True, side_effect=init_se)
    mocker.patch.object(mc_comm.ErrorCatchingThread, "start", autospec=True)
    mocker.patch.object(mc_comm.ErrorCatchingThread, "errors", autospec=True, return_value=False)
    # mock so thread will appear complete on the second iteration of mc_process
    mocker.patch.object(mc_comm.ErrorCatchingThread, "is_alive", autospec=True, side_effect=[True, False])

    # send command to mc_process
    test_command = {
        "communication_type": "firmware_update",
        "command": "get_latest_firmware_versions",
        "hardware_version": "1.0.0",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(test_command), from_main_queue
    )

    # run first iteration and make sure command response not sent to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_empty(to_main_queue)
    # run second iteration and make sure correct command response sent to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == {
        "communication_type": "firmware_update",
        "command": "get_latest_firmware_versions",
        "latest_versions": expected_latest_versions,
    }


def test_McCommunicationProcess__handles_successful_completion_of_download_firmware_updates_worker_thread(
    four_board_mc_comm_process_no_handshake, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue, to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]

    expected_main_fw_bytes = bytes("main", encoding="ascii")
    expected_channel_fw_bytes = bytes("channel", encoding="ascii")

    def init_se(obj, target, args):
        args[0].update({"main": expected_main_fw_bytes, "channel": expected_channel_fw_bytes})

    # mock init so it populates output dict immediately
    mocker.patch.object(mc_comm.ErrorCatchingThread, "__init__", autospec=True, side_effect=init_se)
    mocker.patch.object(mc_comm.ErrorCatchingThread, "start", autospec=True)
    mocker.patch.object(mc_comm.ErrorCatchingThread, "errors", autospec=True, return_value=False)
    # mock so thread will appear complete on the second iteration of mc_process
    mocker.patch.object(mc_comm.ErrorCatchingThread, "is_alive", autospec=True, side_effect=[True, False])

    # send command to mc_process
    test_command = {
        "communication_type": "firmware_update",
        "command": "download_firmware_updates",
        "main": "1.0.0",
        "channel": "1.0.1",
        "username": "user",
        "password": "pw",
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(test_command), from_main_queue
    )

    # run first iteration and make sure command response not sent to main
    invoke_process_run_and_check_errors(mc_process)
    assert mc_process._main_firmware_update_bytes is None
    assert mc_process._channel_firmware_update_bytes is None
    confirm_queue_is_eventually_empty(to_main_queue)
    # run second iteration and make sure correct command response sent to main
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    command_response = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert command_response == {
        "communication_type": "firmware_update",
        "command": "download_firmware_updates",
        "message": "Updates downloaded, ready to install",
    }
    assert mc_process._main_firmware_update_bytes == expected_main_fw_bytes
    assert mc_process._channel_firmware_update_bytes == expected_channel_fw_bytes


@pytest.mark.parametrize("firmware_type", ["channel", "main"])
def test_McCommunicationProcess__handles_successful_firmware_update(
    four_board_mc_comm_process, mantarray_mc_simulator, firmware_type, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    from_main_queue, to_main_queue = four_board_mc_comm_process["board_queues"][0][:2]
    simulator = mantarray_mc_simulator["simulator"]

    spied_send_handshake = mocker.spy(mc_process, "_send_handshake")
    # mock so no handshakes are sent
    mocked_get_secs_since_handshake = mocker.patch.object(
        mc_comm, "_get_secs_since_last_handshake", autospec=True, return_value=0
    )
    # set this value to anything other than None so mc_process thinks the first handshake has already been sent
    mc_process._time_of_last_handshake_secs = 0
    # mock so no beacons are sent
    mocked_get_secs_since_beacon = mocker.patch.object(
        mc_simulator, "_get_secs_since_last_status_beacon", autospec=True, return_value=0
    )

    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator)
    set_simulator_idle_ready(mantarray_mc_simulator)

    test_firmware_len = randint(1000, SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES * 3)
    test_firmware_bytes = bytes([randint(0, 255) for _ in range(test_firmware_len)])
    if firmware_type == "main":
        mc_process._main_firmware_update_bytes = test_firmware_bytes
    else:
        mc_process._channel_firmware_update_bytes = test_firmware_bytes
    mc_process._latest_versions = {"main-fw": "2.0.0", "channel-fw": "2.0.0", "sw": "1.0.0"}

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": firmware_type,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        copy.deepcopy(update_firmware_command), from_main_queue
    )
    # process begin firmware update command
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # make sure only begin firmware update response sent to main
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_main == update_firmware_command

    # send another command and make sure it is ignored until firmware update process is complete
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "metadata_comm",
            "command": "get_metadata",
        },
        from_main_queue,
    )
    # confirm that only a single item is in queue
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    spied_send_handshake.assert_not_called()
    # mock so that handshake is ready to be sent
    mocked_get_secs_since_handshake.return_value = SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS

    spied_send_packet = mocker.spy(mc_process, "_send_data_packet")

    # send firmware bytes to instrument
    num_iterations_to_send_firmware = math.ceil(
        test_firmware_len / (SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES - 1)
    )
    for packet_idx in range(num_iterations_to_send_firmware):
        # send packet and process response
        invoke_process_run_and_check_errors(mc_process)
        invoke_process_run_and_check_errors(simulator)
        invoke_process_run_and_check_errors(mc_process)
        assert spied_send_packet.call_count == packet_idx + 1
        # confirm message sent to main
        confirm_queue_is_eventually_of_size(to_main_queue, 1)
        msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        assert msg_to_main == {
            "communication_type": "firmware_update",
            "command": "send_firmware_data",
            "firmware_type": firmware_type,
            "packet_index": packet_idx,
        }
    spied_send_handshake.assert_not_called()

    # send and process end of firmware update packet
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_main == {
        "communication_type": "firmware_update",
        "command": "end_of_firmware_update",
        "firmware_type": firmware_type,
    }
    # make sure reboot has begun
    assert simulator.is_rebooting() is True

    # make sure handshake still hasn't been sent
    invoke_process_run_and_check_errors(mc_process)
    spied_send_handshake.assert_not_called()
    # make sure status beacon timeout is ignored
    mocked_get_secs_since_beacon = mocker.patch.object(
        mc_comm,
        "_get_secs_since_last_beacon",
        autospec=True,
        return_value=SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS,
    )
    invoke_process_run_and_check_errors(mc_process)

    # make sure command from main was ignored
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    # complete reboot and send firmware update complete packet
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        autospec=True,
        return_value=AVERAGE_MC_REBOOT_DURATION_SECONDS,
    )
    invoke_process_run_and_check_errors(simulator)

    mocked_get_secs_since_beacon.return_value = 0

    # process firmware update complete packet
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_main == {
        "communication_type": "firmware_update",
        "command": "update_completed",
        "firmware_type": firmware_type,
    }

    # make sure handshake still hasn't been sent
    invoke_process_run_and_check_errors(mc_process)
    spied_send_handshake.assert_not_called()

    # save current status beacon timepoint for assertion later
    prev_time_of_last_beacon = mc_process._time_of_last_beacon_secs

    # complete reboot and and acknowledge reboot completion
    mocked_get_secs_since_beacon.return_value = SERIAL_COMM_STATUS_BEACON_PERIOD_SECONDS
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    # make sure status beacon tracking timepoint was updated
    assert mc_process._time_of_last_beacon_secs > prev_time_of_last_beacon
    # make sure handshakes are now sent
    invoke_process_run_and_check_errors(mc_process)
    spied_send_handshake.assert_called_once()
    # make sure command from main was processed
    confirm_queue_is_eventually_empty(from_main_queue)


def test_McCommunicationProcess__raises_error_if_begin_firmware_update_command_fails(
    patch_print, four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    test_firmware_type = choice(["main", "channel"])
    test_firmware_bytes = bytes(1000)
    if test_firmware_type == "main":
        mc_process._main_firmware_update_bytes = test_firmware_bytes
    else:
        mc_process._channel_firmware_update_bytes = test_firmware_bytes
    mc_process._latest_versions = {"main-fw": "2.0.0", "channel-fw": "2.0.0", "sw": "1.0.0"}

    # set simulator firmware update status
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_firmware_update_type", "firmware_type": test_firmware_type}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": test_firmware_type,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(update_firmware_command, from_main_queue)
    # send begin firmware update command and make sure error is raised
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    with pytest.raises(FirmwareUpdateCommandFailedError, match="start_firmware_update"):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__raises_error_if_firmware_update_packet_fails(
    patch_print, four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    test_firmware_type = choice(["main", "channel"])
    test_firmware_bytes = bytes(1000)
    if test_firmware_type == "main":
        mc_process._main_firmware_update_bytes = test_firmware_bytes
    else:
        mc_process._channel_firmware_update_bytes = test_firmware_bytes
    mc_process._latest_versions = {"main-fw": "2.0.0", "channel-fw": "2.0.0", "sw": "1.0.0"}

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": test_firmware_type,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(update_firmware_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    # send first firmware update packet
    invoke_process_run_and_check_errors(mc_process)
    # flip succeeded byte to failed byte
    invoke_process_run_and_check_errors(simulator)
    response = simulator.read_all()
    response = bytearray(response)
    response[SERIAL_COMM_ADDITIONAL_BYTES_INDEX + SERIAL_COMM_TIMESTAMP_LENGTH_BYTES] = 1
    response[-SERIAL_COMM_CHECKSUM_LENGTH_BYTES:] = crc32(
        response[:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES]
    ).to_bytes(4, byteorder="little")
    # add modified response to read
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "add_read_bytes", "read_bytes": bytes(response)}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    with pytest.raises(FirmwareUpdateCommandFailedError, match="send_firmware_data, packet index: 0"):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__raises_error_if_end_firmware_update_command_fails(
    patch_print, four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    test_firmware_type = choice(["main", "channel"])
    test_firmware_bytes = bytes(1000)
    if test_firmware_type == "main":
        mc_process._main_firmware_update_bytes = test_firmware_bytes
    else:
        mc_process._channel_firmware_update_bytes = test_firmware_bytes
    mc_process._latest_versions = {"main-fw": "2.0.0", "channel-fw": "2.0.0", "sw": "1.0.0"}

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": test_firmware_type,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(update_firmware_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # send firmware update packet
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    # mock so checksum is incorrect and failure response is produced
    mocker.patch.object(
        mc_simulator, "crc32", autospec=True, return_value=1.5  # arbitrary value not equal to any integers
    )

    # send end of firmware packet and make sure error is raised
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    with pytest.raises(FirmwareUpdateCommandFailedError, match="end_of_firmware_update"):
        invoke_process_run_and_check_errors(mc_process)


@pytest.mark.parametrize(
    "firmware_type,timeout_value",
    [
        ("channel", MAX_CHANNEL_FIRMWARE_UPDATE_DURATION_SECONDS),
        ("main", MAX_MAIN_FIRMWARE_UPDATE_DURATION_SECONDS),
    ],
)
def test_McCommunicationProcess__raises_error_if_firmware_update_timeout_occurs(
    patch_print,
    four_board_mc_comm_process_no_handshake,
    mantarray_mc_simulator_no_beacon,
    firmware_type,
    timeout_value,
    mocker,
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]

    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    test_firmware_bytes = bytes(1000)
    if firmware_type == "main":
        mc_process._main_firmware_update_bytes = test_firmware_bytes
    else:
        mc_process._channel_firmware_update_bytes = test_firmware_bytes
    mc_process._latest_versions = {"main-fw": "2.0.0", "channel-fw": "2.0.0", "sw": "1.0.0"}

    # mock so timeout occurs after end of firmware response received
    mocker.patch.object(mc_comm, "_get_firmware_update_dur_secs", autospec=True, return_value=timeout_value)

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": firmware_type,
    }
    put_object_into_queue_and_raise_error_if_eventually_still_empty(update_firmware_command, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # firmware update packet
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)
    # end of firmware packet
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    # Tanner (11/17/21): currently the error will be raised on the same iteration that the end of firmware update response is received
    with pytest.raises(FirmwareUpdateTimeoutError, match=firmware_type):
        invoke_process_run_and_check_errors(mc_process)
