# -*- coding: utf-8 -*-
from random import randint

from mantarray_desktop_app import mc_comm
from mantarray_desktop_app import SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS
from mantarray_desktop_app import SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
from mantarray_desktop_app.constants import MAX_MC_REBOOT_DURATION_SECONDS
from mantarray_desktop_app.constants import SERIAL_COMM_ERROR_PING_PONG_PACKET_TYPE
from mantarray_desktop_app.exceptions import InstrumentFirmwareError
from mantarray_desktop_app.serial_comm_utils import convert_status_code_bytes_to_dict
from mantarray_desktop_app.serial_comm_utils import convert_to_status_code_bytes
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import fixture_patch_print
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process
from ..fixtures_mc_comm import fixture_four_board_mc_comm_process_no_handshake
from ..fixtures_mc_comm import set_connection_and_register_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..helpers import assert_serial_packet_is_expected
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_mantarray_mc_simulator_no_beacon,
    fixture_patch_print,
    fixture_four_board_mc_comm_process,
    fixture_four_board_mc_comm_process_no_handshake,
]


def test_McCommunicationProcess__handles_error_ping__before_reboot(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    spied_write = mocker.spy(simulator, "write")

    # set random non-zero status code before sending error ping
    test_main_status_code = randint(1, 255)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": test_main_status_code}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # have simulator send an error ping
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_error_ping", "error_before_reboot": True}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # process error ping packet and make sure error pong packet is sent right away
    invoke_process_run_and_check_errors(mc_process)
    # make sure error pong message was sent
    spied_write.assert_called_once()
    assert_serial_packet_is_expected(spied_write.call_args[0][0], SERIAL_COMM_ERROR_PING_PONG_PACKET_TYPE)
    # make sure no error is until simulator sends next status beacon which will signal the completion of the post-error reboot
    invoke_process_run_and_check_errors(mc_process)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_single_beacon"}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    expected_status_code_dict = convert_status_code_bytes_to_dict(
        convert_to_status_code_bytes(test_main_status_code)
    )
    with pytest.raises(
        InstrumentFirmwareError,
        match=f"Instrument reported firmware error. Status codes: {expected_status_code_dict}",
    ):
        invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__handles_error_ping__after_reboot(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    spied_write = mocker.spy(simulator, "write")

    # set random non-zero status code before sending error ping
    test_main_status_code = randint(1, 255)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": test_main_status_code}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # have simulator send an error ping
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_error_ping", "error_before_reboot": False}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # process error ping packet. Make sure error pong packet is sent right away and mc_comm raises error
    expected_status_code_dict = convert_status_code_bytes_to_dict(
        convert_to_status_code_bytes(test_main_status_code)
    )
    with pytest.raises(
        InstrumentFirmwareError,
        match=f"Instrument reported firmware error. Status codes: {expected_status_code_dict}",
    ):
        invoke_process_run_and_check_errors(mc_process)
    # make sure error pong message was sent
    spied_write.assert_called_once()
    assert_serial_packet_is_expected(spied_write.call_args[0][0], SERIAL_COMM_ERROR_PING_PONG_PACKET_TYPE)


def test_McCommunicationProcess__ignores_commands_from_main_after_receiving_error_ping(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    # set random non-zero status code before sending error ping
    test_main_status_code = randint(1, 255)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": test_main_status_code}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # have simulator send an error ping. Need to set error_before_reboot to True so error is not immediately raised
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_error_ping", "error_before_reboot": True}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # process error ping packet
    invoke_process_run_and_check_errors(mc_process)

    # add item to queue from main and make sure it is ignored
    put_object_into_queue_and_raise_error_if_eventually_still_empty({"command": "any"}, from_main_queue)
    invoke_process_run_and_check_errors(mc_process)
    confirm_queue_is_eventually_of_size(from_main_queue, 1)


def test_McCommunicationProcess__does_not_send_handshakes_while_instrument_is_rebooting(
    four_board_mc_comm_process, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(four_board_mc_comm_process, mantarray_mc_simulator_no_beacon)

    # process initial handshake and response
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    invoke_process_run_and_check_errors(mc_process)

    mocker.patch.object(
        mc_comm,
        "_get_secs_since_last_handshake",
        autospec=True,
        side_effect=[0, SERIAL_COMM_HANDSHAKE_PERIOD_SECONDS],
    )

    # set random non-zero status code before sending error ping
    test_main_status_code = randint(1, 255)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": test_main_status_code}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # have simulator send an error ping. Need to set error_before_reboot to True so error is not immediately raised
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_error_ping", "error_before_reboot": True}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # process error ping packet
    invoke_process_run_and_check_errors(mc_process)
    # run one more iteration to make sure that handshake packet is not sent (by checking that write call count does not change)
    spied_write = mocker.spy(simulator, "write")
    invoke_process_run_and_check_errors(mc_process)
    spied_write.assert_not_called()


def test_McCommunicationProcess__does_not_send_reboot_command_in_teardown_if_error_ping_received(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    spied_write = mocker.spy(simulator, "write")

    # mock so that mc_comm will use teardown procedure for a real instrument
    mocker.patch.object(mc_comm, "_is_simulator", autospec=True, return_value=False)

    # set random non-zero status code before sending error ping
    test_main_status_code = randint(1, 255)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": test_main_status_code}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # have simulator send an error ping
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_error_ping", "error_before_reboot": True}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # process error ping packet and send error pong packet
    invoke_process_run_and_check_errors(mc_process)
    spied_write.assert_called_once()
    assert_serial_packet_is_expected(spied_write.call_args[0][0], SERIAL_COMM_ERROR_PING_PONG_PACKET_TYPE)
    # run one more iteration to raise error and run teardown
    mocker.patch.object(
        mc_process, "_commands_for_each_run_iteration", autospec=True, side_effect=Exception()
    )
    with pytest.raises(Exception):
        invoke_process_run_and_check_errors(mc_process, perform_teardown_after_loop=True)
    # make sure error pong packet is sent but not reboot command
    spied_write.assert_called_once()


def test_McCommunicationProcess__does_not_track_command_response_timeouts_after_error_ping_is_received(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    from_main_queue = four_board_mc_comm_process_no_handshake["board_queues"][0][0]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    mocked_secs_since_command_sent = mocker.patch.object(
        mc_comm, "_get_secs_since_command_sent", autospec=True, return_value=0
    )

    # have mc_comm send an arbitrary command and manually remove the response
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"communication_type": "metadata_comm", "command": "get_metadata"}, from_main_queue
    )
    invoke_process_run_and_check_errors(mc_process)
    invoke_process_run_and_check_errors(simulator)
    simulator.read_all()

    # set random non-zero status code before sending error ping
    test_main_status_code = randint(1, 255)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": test_main_status_code}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # have simulator send an error ping. Need to set error_before_reboot to True so error is not immediately raised
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_error_ping", "error_before_reboot": True}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # process error ping packet
    invoke_process_run_and_check_errors(mc_process)
    # run one more iteration to make sure that command response timeout error is not raised
    mocked_secs_since_command_sent.return_value = SERIAL_COMM_RESPONSE_TIMEOUT_SECONDS
    invoke_process_run_and_check_errors(mc_process)


def test_McCommunicationProcess__raises_error_correctly_if_error_ping_received_before_reboot_and_reboot_timeout_occurs(
    four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon, mocker, patch_print
):
    mc_process = four_board_mc_comm_process_no_handshake["mc_process"]
    simulator = mantarray_mc_simulator_no_beacon["simulator"]
    testing_queue = mantarray_mc_simulator_no_beacon["testing_queue"]
    set_connection_and_register_simulator(
        four_board_mc_comm_process_no_handshake, mantarray_mc_simulator_no_beacon
    )

    mocker.patch.object(
        mc_comm,
        "_get_secs_since_reboot_start",
        side_effect=[0, MAX_MC_REBOOT_DURATION_SECONDS],
        autospec=True,
    )

    # set random non-zero status code before sending error ping
    test_main_status_code = randint(1, 255)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "set_status_code", "status_code": test_main_status_code}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # have simulator send an error ping. Need to set error_before_reboot to True so error is not immediately raised
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        {"command": "send_error_ping", "error_before_reboot": True}, testing_queue
    )
    invoke_process_run_and_check_errors(simulator)
    # process error ping packet
    invoke_process_run_and_check_errors(mc_process)

    # run one more iteration to trigger reboot timeout
    expected_status_code_dict = convert_status_code_bytes_to_dict(
        convert_to_status_code_bytes(test_main_status_code)
    )
    with pytest.raises(
        InstrumentFirmwareError,
        match=f"Instrument reported firmware error, and failed to complete reboot before timeout. Status codes: {expected_status_code_dict}",
    ):
        invoke_process_run_and_check_errors(mc_process)
