# -*- coding: utf-8 -*-
import logging

from mantarray_desktop_app import BARCODE_CONFIRM_CLEAR_WAIT_SECONDS
from mantarray_desktop_app import BARCODE_GET_SCAN_WAIT_SECONDS
from mantarray_desktop_app import BarcodeNotClearedError
from mantarray_desktop_app import BarcodeScannerNotRespondingError
from mantarray_desktop_app import CLEARED_BARCODE_VALUE
from mantarray_desktop_app import NO_PLATE_DETECTED_BARCODE_VALUE
from mantarray_desktop_app import ok_comm
from mantarray_desktop_app import RunningFIFOSimulator
import pytest
from stdlib_utils import invoke_process_run_and_check_errors

from ..fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from ..fixtures_barcode import fixture_test_barcode_simulator
from ..fixtures_ok_comm import fixture_four_board_comm_process
from ..helpers import confirm_queue_is_eventually_empty
from ..helpers import confirm_queue_is_eventually_of_size
from ..helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [fixture_four_board_comm_process, fixture_test_barcode_simulator]

RUN_BARCODE_SCAN_COMMUNICATION = {
    "communication_type": "barcode_comm",
    "command": "start_scan",
}


INVALID_BARCODE = RunningFIFOSimulator.default_barcode[:-1] + "$"


def test_OkCommunicationProcess__always_returns_default_barcode_when_connected_to_simulator(
    four_board_comm_process,
    mocker,
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    simulator = RunningFIFOSimulator()
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    expected_barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": RunningFIFOSimulator.default_barcode,
        "board_idx": 0,
        "valid": True,
    }

    confirm_queue_is_eventually_empty(to_main_queue)
    input_queue.put_nowait(RUN_BARCODE_SCAN_COMMUNICATION)
    confirm_queue_is_eventually_of_size(
        input_queue, 1, sleep_after_confirm_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
    )

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION,
        input_queue,
        sleep_after_put_seconds=QUEUE_CHECK_TIMEOUT_SECONDS,
    )

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm


def test_OkCommunicationProcess__clears_barcode_scanner_after_receiving_start_scan_comm(
    four_board_comm_process, mocker, test_barcode_simulator
):
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]

    simulator, _ = test_barcode_simulator()
    spied_clear = mocker.spy(simulator, "clear_barcode_scanner")

    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    spied_clear.assert_not_called()
    invoke_process_run_and_check_errors(ok_process)
    spied_clear.assert_called_once()


def test_OkCommunicationProcess__waits_appropriate_amount_of_time_after_clearing_barcode_to_check_value__and_triggers_scan_after_confirming_barcode_is_cleared(
    four_board_comm_process, mocker, test_barcode_simulator
):
    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS - 0.25,
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
        ],
    )

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]

    simulator, mocked_get = test_barcode_simulator(CLEARED_BARCODE_VALUE)
    spied_start_scan = mocker.spy(simulator, "start_barcode_scan")
    ok_process.set_board_connection(0, simulator)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process)
    mocked_get.assert_not_called()
    spied_start_scan.assert_not_called()
    invoke_process_run_and_check_errors(ok_process)
    mocked_get.assert_called_once()
    spied_start_scan.assert_called_once()


def test_OkCommunicationProcess__raises_error_if_barcode_buffer_not_cleared_after_sending_clear_command__and_doesnt_start_scan(
    four_board_comm_process, mocker, test_barcode_simulator
):
    mocker.patch("builtins.print", autospec=True)  # don't print all the error messages to console

    expected_barcode = "not clear"

    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        return_value=BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
    )

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]

    simulator, _ = test_barcode_simulator(expected_barcode)
    spied_start_scan = mocker.spy(simulator, "start_barcode_scan")
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    with pytest.raises(BarcodeNotClearedError, match=expected_barcode):
        invoke_process_run_and_check_errors(ok_process)
    spied_start_scan.assert_not_called()


def test_OkCommunicationProcess__checks_barcode_value_after_appropriate_amount_of_time(
    four_board_comm_process, mocker, test_barcode_simulator
):
    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[BARCODE_GET_SCAN_WAIT_SECONDS - 1, BARCODE_GET_SCAN_WAIT_SECONDS],
    )

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]

    simulator, mocked_get = test_barcode_simulator(
        [CLEARED_BARCODE_VALUE, RunningFIFOSimulator.default_barcode]
    )
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process)
    mocked_get.assert_called_once()
    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 2


@pytest.mark.parametrize(
    "test_barcode,expected_barcode,test_description",
    [
        (
            RunningFIFOSimulator.default_barcode,
            RunningFIFOSimulator.default_barcode,
            "sends valid 11 char barcode",
        )
    ],
)
def test_OkCommunicationProcess__sends_message_to_main_if_valid_barcode_received_after_first_attempt__and_stops_scan_process(
    test_barcode,
    expected_barcode,
    test_description,
    four_board_comm_process,
    mocker,
    test_barcode_simulator,
):
    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        return_value=BARCODE_GET_SCAN_WAIT_SECONDS,
    )

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    simulator, mocked_get = test_barcode_simulator(test_barcode)
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process)
    mocked_get.assert_called_once()
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    expected_barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_barcode,
        "board_idx": 0,
        "valid": True,
    }
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm

    invoke_process_run_and_check_errors(ok_process)
    mocked_get.assert_called_once()


def test_OkCommunicationProcess__raises_error_if_barcode_scanner_does_not_respond(
    four_board_comm_process, mocker, test_barcode_simulator
):
    mocker.patch("builtins.print", autospec=True)  # don't print all the error messages to console

    expected_barcode = CLEARED_BARCODE_VALUE

    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        return_value=BARCODE_GET_SCAN_WAIT_SECONDS,
    )

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]

    simulator, _ = test_barcode_simulator(expected_barcode)
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    with pytest.raises(BarcodeScannerNotRespondingError):
        invoke_process_run_and_check_errors(ok_process)


def test_OkCommunicationProcess__logs_that_no_plate_was_detected_if_barcode_scanner_returns_no_plate_value__and_clears_barcode_value(
    four_board_comm_process, mocker, test_barcode_simulator
):
    expected_barcode = NO_PLATE_DETECTED_BARCODE_VALUE

    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[0, BARCODE_GET_SCAN_WAIT_SECONDS],
    )
    mocked_put = mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    simulator, _ = test_barcode_simulator(expected_barcode)
    spied_clear = mocker.spy(simulator, "clear_barcode_scanner")
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process)
    spied_clear.assert_called_once()

    invoke_process_run_and_check_errors(ok_process)
    assert spied_clear.call_count == 2
    mocked_put.assert_any_call(
        logging.INFO,
        "No plate detected, retrying scan",
        to_main_queue,
        logging.INFO,
    )


def test_OkCommunicationProcess__logs_that_invalid_barcode_received_if_barcode_scanner_returns_invalid_barcode__and_clears_barcode_value(
    four_board_comm_process, mocker, test_barcode_simulator
):
    expected_barcode = INVALID_BARCODE

    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[0, BARCODE_GET_SCAN_WAIT_SECONDS],
    )
    mocked_put = mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    simulator, _ = test_barcode_simulator(expected_barcode)
    spied_clear = mocker.spy(simulator, "clear_barcode_scanner")
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process)
    spied_clear.assert_called_once()

    invoke_process_run_and_check_errors(ok_process)
    assert spied_clear.call_count == 2
    mocked_put.assert_any_call(
        logging.INFO,
        f"Invalid barcode detected: {expected_barcode}, retrying scan",
        to_main_queue,
        logging.INFO,
    )


def test_OkCommunicationProcess__restarts_scan_process_if_valid_barcode_not_detected_on_first_scan(
    four_board_comm_process, mocker, test_barcode_simulator
):
    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
        ],
    )

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]

    simulator, mocked_get = test_barcode_simulator(
        [CLEARED_BARCODE_VALUE, INVALID_BARCODE, CLEARED_BARCODE_VALUE]
    )
    spied_start_scan = mocker.spy(simulator, "start_barcode_scan")
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process)
    mocked_get.assert_called_once()
    spied_start_scan.assert_called_once()
    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 2
    spied_start_scan.assert_called_once()
    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 3
    assert spied_start_scan.call_count == 2


def test_OkCommunicationProcess__sends_correct_values_to_main_for_valid_second_barcode_read__and_scan_process_ends(
    four_board_comm_process, mocker, test_barcode_simulator
):
    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
        ],
    )
    # Tanner (12/7/20): mock this so we can make assertions on what's in the queue more easily
    mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    simulator, mocked_get = test_barcode_simulator(
        [
            CLEARED_BARCODE_VALUE,
            INVALID_BARCODE,
            CLEARED_BARCODE_VALUE,
            RunningFIFOSimulator.default_barcode,
        ]
    )
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process, num_iterations=3)
    confirm_queue_is_eventually_empty(to_main_queue)

    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 4
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    expected_barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": RunningFIFOSimulator.default_barcode,
        "board_idx": 0,
        "valid": True,
    }
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm

    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 4


def test_OkCommunicationProcess__sends_correct_values_to_main_for_invalid_second_barcode_read__and_scan_process_ends(
    four_board_comm_process, mocker, test_barcode_simulator
):
    expected_barcode = "M$2001900001"

    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
        ],
    )
    # Tanner (12/7/20): mock this so we can make assertions on what's in the queue more easily
    mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    simulator, mocked_get = test_barcode_simulator(
        [
            CLEARED_BARCODE_VALUE,
            INVALID_BARCODE,
            CLEARED_BARCODE_VALUE,
            expected_barcode,
        ],
    )
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process, num_iterations=3)
    confirm_queue_is_eventually_empty(to_main_queue)

    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 4
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    expected_barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_barcode,
        "board_idx": 0,
        "valid": False,
    }
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm

    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 4


def test_OkCommunicationProcess__sends_correct_values_to_main_for_invalid_second_barcode_new_scheme_read__and_scan_process_ends(
    four_board_comm_process, mocker, test_barcode_simulator
):
    expected_barcode = "M*22123199-2"

    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
        ],
    )
    # Tanner (12/7/20): mock this so we can make assertions on what's in the queue more easily
    mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    simulator, mocked_get = test_barcode_simulator(
        [
            CLEARED_BARCODE_VALUE,
            INVALID_BARCODE,
            CLEARED_BARCODE_VALUE,
            expected_barcode,
        ],
    )
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process, num_iterations=3)
    confirm_queue_is_eventually_empty(to_main_queue)

    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 4
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    expected_barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": expected_barcode,
        "board_idx": 0,
        "valid": False,
    }
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm

    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 4


def test_OkCommunicationProcess__sends_correct_values_to_main_when_no_valid_barcode_detected__and_scan_process_ends(
    four_board_comm_process, mocker, test_barcode_simulator
):
    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
        ],
    )
    # Tanner (12/7/20): mock this so we can make assertions on what's in the queue more easily
    mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    simulator, mocked_get = test_barcode_simulator(
        [
            CLEARED_BARCODE_VALUE,
            INVALID_BARCODE,
            CLEARED_BARCODE_VALUE,
            NO_PLATE_DETECTED_BARCODE_VALUE,
        ],
    )
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process, num_iterations=3)
    confirm_queue_is_eventually_empty(to_main_queue)
    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 4
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    expected_barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": "",
        "board_idx": 0,
    }
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm

    invoke_process_run_and_check_errors(ok_process)
    assert mocked_get.call_count == 4


def test_OkCommunicationProcess__correctly_handles_two_consecutive_full_process_barcode_scans(
    four_board_comm_process, mocker, test_barcode_simulator
):
    expected_invalid_barcode = RunningFIFOSimulator.default_barcode + chr(1)

    mocker.patch.object(
        ok_comm,
        "_get_dur_since_barcode_clear",
        autospec=True,
        side_effect=[
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
            BARCODE_CONFIRM_CLEAR_WAIT_SECONDS,
            BARCODE_GET_SCAN_WAIT_SECONDS,
        ],
    )
    # Tanner (12/7/20): mock this so we can make assertions on what's in the queue more easily
    mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)

    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    simulator, _ = test_barcode_simulator(
        [
            CLEARED_BARCODE_VALUE,
            INVALID_BARCODE,
            CLEARED_BARCODE_VALUE,
            expected_invalid_barcode,
            CLEARED_BARCODE_VALUE,
            INVALID_BARCODE,
            CLEARED_BARCODE_VALUE,
            RunningFIFOSimulator.default_barcode,
        ],
    )
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process, num_iterations=4)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    expected_barcode_comm_1 = {
        "communication_type": "barcode_comm",
        "barcode": expected_invalid_barcode,
        "board_idx": 0,
        "valid": False,
    }
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm_1

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )
    invoke_process_run_and_check_errors(ok_process, num_iterations=4)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)

    expected_barcode_comm_2 = {
        "communication_type": "barcode_comm",
        "barcode": RunningFIFOSimulator.default_barcode,
        "board_idx": 0,
        "valid": True,
    }
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm_2


def test_OkCommunicationProcess__does_not_try_to_scan_barcode_before_board_is_initialized(
    four_board_comm_process, mocker, test_barcode_simulator
):
    # Tanner (12/10/20): This test is to make sure the barcode feature is compatible with --skip-mantarray-boot-up command line argument
    ok_process = four_board_comm_process["ok_process"]
    board_queues = four_board_comm_process["board_queues"]
    input_queue = board_queues[0][0]
    to_main_queue = board_queues[0][1]

    mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)
    simulator = RunningFIFOSimulator()
    ok_process.set_board_connection(0, simulator)

    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        RUN_BARCODE_SCAN_COMMUNICATION, input_queue
    )

    invoke_process_run_and_check_errors(ok_process)
    confirm_queue_is_eventually_of_size(to_main_queue, 1)
    expected_barcode_comm = {
        "communication_type": "barcode_comm",
        "barcode": "",
        "board_idx": 0,
    }
    actual = to_main_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual == expected_barcode_comm
