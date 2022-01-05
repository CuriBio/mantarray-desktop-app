# -*- coding: utf-8 -*-
import copy
import math
from random import choice
from random import randint
from zlib import crc32

from mantarray_desktop_app import CLOUD_API_ENDPOINT
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
from mantarray_desktop_app import SERIAL_COMM_STATUS_BEACON_TIMEOUT_SECONDS
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app.mc_comm import get_latest_firmware_versions
from mantarray_desktop_app.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
import pytest
from pytest import approx
import requests
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_patch_print,
    fixture_four_board_mc_comm_process,
    fixture_four_board_mc_comm_process_no_handshake,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_get_latest_firmware_versions__polls_api_endpoint_correctly_and_returns_values_correctly(mocker):
    expected_latest_main_fw_version = "1.0.0"
    expected_latest_channel_fw_version = "1.0.1"
    expected_response_dict = {
        "latest_firmware_versions": {
            "main": expected_latest_main_fw_version,
            "channel": expected_latest_channel_fw_version,
        }
    }

    mocked_get = mocker.patch.object(requests, "get", autospec=True)
    mocked_get.return_value.json.return_value = copy.deepcopy(expected_response_dict)

    test_result_dict = {"latest_firmware_versions": {}}
    test_latest_software_version = "0.0.1"
    test_main_firmware_version = "0.0.2"
    get_latest_firmware_versions(test_result_dict, test_latest_software_version, test_main_firmware_version)
    mocked_get.assert_called_once_with(
        f"https://{CLOUD_API_ENDPOINT}/firmware_latest?software_version={test_latest_software_version}&main_firmware_version={test_main_firmware_version}"
    )

    assert test_result_dict == expected_response_dict


def test_McCommunicationProcess__handles_successful_completion_of_firmware_update_worker_thread(
    four_board_mc_comm_process_no_handshake, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue, to_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][:2]

    expected_main_fw_version = "1.1.1"
    expected_channel_fw_version = "2.2.2"
    expected_latest_firmware_versions = {
        "main": expected_main_fw_version,
        "channel": expected_channel_fw_version,
    }

    def init_se(obj, target, args):
        args[0].update({"latest_firmware_versions": expected_latest_firmware_versions})

    # mock init so it populates output dict immediately
    mocker.patch.object(mc_comm.ErrorCatchingThread, "__init__", autospec=True, side_effect=init_se)
    mocker.patch.object(mc_comm.ErrorCatchingThread, "start", autospec=True)
    mocker.patch.object(mc_comm.ErrorCatchingThread, "errors", autospec=True, return_value=False)
    # mock so thread will appear complete on the second iteration of mc_process
    mocker.patch.object(mc_comm.ErrorCatchingThread, "is_alive", autospec=True, side_effect=[True, False])

    # send command to mc_process. Using get_latest_firmware_versions here arbitrarily, but functionality should be the same for any worker thread
    test_command = {
        "communication_type": "firmware_update",
        "command": "get_latest_firmware_versions",
        "latest_software_version": "1.0.0",
        "main_firmware_version": "2.0.0",
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
        "latest_firmware_versions": expected_latest_firmware_versions,
    }


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
        "latest_software_version": "1.0.0",
        "main_firmware_version": "2.0.0",
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


@pytest.mark.parametrize("firmware_type", ["channel", "main"])
def test_McCommunicationProcess__handles_successful_firmware_update(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, firmware_type, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    from_main_queue, to_main_queue = four_board_mc_comm_process["board_queues"][0][:2]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]

    spied_send_handshake = mocker.spy(mc_process, "_send_handshake")
    # mock so no handshakes are sent
    mocked_get_secs_since_handshake = mocker.patch.object(
        mc_comm, "_get_secs_since_last_handshake", autospec=True, return_value=0
    )
    mc_process._time_of_last_handshake_secs = 0  # pylint: disable=protected-access

    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)
    set_simulator_idle_ready(mantarray_mc_simulator_no_beacon)

    test_firmware_len = randint(1000, SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES * 3)
    test_firmware_bytes = bytes([randint(0, 255) for _ in range(test_firmware_len)])

    test_file_path = "test/file/path"
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_read = mocked_open.return_value.__enter__().read
    mocked_read.return_value = test_firmware_bytes

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": firmware_type,
        "file_path": test_file_path,
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
    # make sure firmware contents were loaded from file
    mocked_open.assert_called_once_with(test_file_path, "rb")
    mocked_read.assert_called_once_with()

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

    # make sure command from main is ignored
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {
            "communication_type": "metadata_comm",
            "command": "get_metadata",
        },
        from_main_queue,
    )
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)

    # complete reboot and send firmware update complete packet
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        return_value=AVERAGE_MC_REBOOT_DURATION_SECONDS,
        autospec=True,
    )
    invoke_process_run_and_check_errors(simulator)

    mocked_get_secs_since_beacon.return_value = 0
    spied_perf_counter = mocker.spy(mc_comm, "perf_counter")

    # process firmware update complete packet
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_main == {
        "communication_type": "firmware_update",
        "command": "update_completed",
        "firmware_type": firmware_type,
    }
    # make sure status beacon tracking timepoint was updated  # Tanner (11/16/21): using large abs here in case perf_counter is called again in this same iteration
    assert mc_process._time_of_last_beacon_secs == approx(  # pylint: disable=protected-access
        spied_perf_counter.spy_return, abs=1
    )
    # make sure handshakes are now sent
    invoke_process_run_and_check_errors(mc_process)
    spied_send_handshake.assert_called_once()
    # make sure command from main get processed
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

    test_file_path = "test/file/path"
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_read = mocked_open.return_value.__enter__().read
    mocked_read.return_value = bytes(1000)

    # set simulator firmware update status
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_firmware_update_type", "firmware_type": choice(["main", "channel"])}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": choice(["main", "channel"]),
        "file_path": test_file_path,
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

    test_file_path = "test/file/path"
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_read = mocked_open.return_value.__enter__().read
    mocked_read.return_value = bytes(1000)

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": choice(["main", "channel"]),
        "file_path": test_file_path,
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

    test_file_path = "test/file/path"
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_read = mocked_open.return_value.__enter__().read
    mocked_read.return_value = bytes(1000)

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": choice(["main", "channel"]),
        "file_path": test_file_path,
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

    test_file_path = "test/file/path"
    mocked_open = mocker.patch("builtins.open", autospec=True)
    mocked_read = mocked_open.return_value.__enter__().read
    mocked_read.return_value = bytes(1000)

    # mock so timeout occurs after end of firmware response received
    mocker.patch.object(mc_comm, "_get_firmware_update_dur_secs", autospec=True, return_value=timeout_value)

    # start firmware update
    update_firmware_command = {
        "communication_type": "firmware_update",
        "command": "start_firmware_update",
        "firmware_type": firmware_type,
        "file_path": test_file_path,
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
