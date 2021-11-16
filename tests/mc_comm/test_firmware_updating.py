# -*- coding: utf-8 -*-
import copy
import math
from random import randint

from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import mc_simulator
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES
from mantarray_desktop_app.mc_simulator import AVERAGE_MC_REBOOT_DURATION_SECONDS
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import set_simulator_idle_ready
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty


__fixtures__ = [
    fixture_patch_print,
    fixture_four_board_mc_comm_process,
    fixture_four_board_mc_comm_process_no_handshake,
    fixture_mantarray_mc_simulator_no_beacon,
]


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

    # send firmware bytes to instrument
    num_iterations_to_send_firmware = math.ceil(
        test_firmware_len / (SERIAL_COMM_MAX_PACKET_BODY_LENGTH_BYTES - 1)
    )
    for packet_idx in range(num_iterations_to_send_firmware):
        # send packet and process response
        invoke_process_run_and_check_errors(mc_process)
        invoke_process_run_and_check_errors(simulator)
        invoke_process_run_and_check_errors(mc_process)
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

    # complete reboot and send firmware update complete packet
    mocker.patch.object(
        mc_simulator,
        "_get_secs_since_reboot_command",
        return_value=AVERAGE_MC_REBOOT_DURATION_SECONDS,
        autospec=True,
    )
    invoke_process_run_and_check_errors(simulator)
    # process firmware update complete packet
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    msg_to_main = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert msg_to_main == {
        "communication_type": "firmware_update",
        "command": "update_completed",
        "firmware_type": firmware_type,
    }

    # make sure handshakes are now sent
    invoke_process_run_and_check_errors(mc_process)
    spied_send_handshake.assert_called_once()
