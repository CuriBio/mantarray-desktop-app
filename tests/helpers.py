# -*- coding: utf-8 -*-
"""Could possibly be refactored as a plugin based on stdlib_utils.

https://docs.pytest.org/en/stable/writing_plugins.html
"""
from __future__ import annotations

import json
from random import choice
import time
from time import perf_counter
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from mantarray_desktop_app import convert_subprotocol_pulse_bytes_to_dict
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_TYPE_INDEX
from mantarray_desktop_app import SERIAL_COMM_PAYLOAD_INDEX
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_BYTES_INDEX
from mantarray_desktop_app import SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
from mantarray_desktop_app.constants import STIM_PULSE_BYTES_LEN
import stdlib_utils
from stdlib_utils import confirm_queue_is_eventually_empty as stdlib_c_q_is_e_e
from stdlib_utils import confirm_queue_is_eventually_of_size as stdlib_c_q_is_e_of_s
from stdlib_utils import is_queue_eventually_empty as stdlib_is_queue_eventually_empty
from stdlib_utils import is_queue_eventually_not_empty as stdlib_is_queue_ene
from stdlib_utils import is_queue_eventually_of_size as stdlib_is_queue_eos
from stdlib_utils import QueueStillEmptyError
from stdlib_utils import SECONDS_TO_SLEEP_BETWEEN_CHECKING_QUEUE_SIZE
from stdlib_utils import UnionOfThreadingAndMultiprocessingQueue

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS

QUEUE_EMPTY_CHECK_TIMEOUT_SECONDS = 0.2


def random_bool() -> bool:
    return choice([True, False])


def put_object_into_queue_and_raise_error_if_eventually_still_empty(
    obj: object,
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
    sleep_after_put_seconds: Optional[Union[float, int]] = None,
) -> None:
    stdlib_utils.put_object_into_queue_and_raise_error_if_eventually_still_empty(
        obj, the_queue, timeout_seconds=timeout_seconds
    )
    if sleep_after_put_seconds is not None:
        time.sleep(sleep_after_put_seconds)


def is_queue_eventually_of_size(
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
    size: int,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
) -> bool:
    output = stdlib_is_queue_eos(the_queue, size, timeout_seconds=timeout_seconds)
    if not isinstance(output, bool):
        raise NotImplementedError(
            "not sure why mypy is unable to follow the definition of stdlib_is_queue_eventually_of_size to know that it is typed as a bool return"
        )
    return output


def confirm_queue_is_eventually_of_size(
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
    size: int,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
    sleep_after_confirm_seconds: Optional[Union[float, int]] = None,
) -> None:
    if size == 0:
        raise ValueError(
            "If trying to confirm that a queue is empty, use confirm_queue_is_eventually_empty instead"
        )
    stdlib_c_q_is_e_of_s(the_queue, size, timeout_seconds=timeout_seconds)
    if sleep_after_confirm_seconds is not None:
        time.sleep(sleep_after_confirm_seconds)


def handle_putting_multiple_objects_into_empty_queue(
    objs: List[object],
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
    sleep_after_confirm_seconds: int = 0,
) -> None:
    for next_obj in objs:
        the_queue.put_nowait(next_obj)
    confirm_queue_is_eventually_of_size(
        the_queue,
        len(objs),
        timeout_seconds=timeout_seconds,
        sleep_after_confirm_seconds=sleep_after_confirm_seconds,
    )
    start = perf_counter()
    while perf_counter() - start < QUEUE_EMPTY_CHECK_TIMEOUT_SECONDS:
        if not the_queue.empty():
            return
        time.sleep(SECONDS_TO_SLEEP_BETWEEN_CHECKING_QUEUE_SIZE)

    raise QueueStillEmptyError()


def confirm_queue_is_eventually_empty(
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
) -> None:
    stdlib_c_q_is_e_e(the_queue, timeout_seconds=timeout_seconds)


def is_queue_eventually_empty(
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
) -> bool:
    output = stdlib_is_queue_eventually_empty(the_queue, timeout_seconds=timeout_seconds)
    if not isinstance(output, bool):
        raise NotImplementedError(
            "not sure why mypy is unable to follow the definition of stdlib_is_queue_eventually_empty to know that it is typed as a bool return"
        )
    return output


def is_queue_eventually_not_empty(
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
) -> bool:
    output = stdlib_is_queue_ene(the_queue, timeout_seconds=timeout_seconds)
    if not isinstance(output, bool):
        raise NotImplementedError(
            "not sure why mypy is unable to follow the definition of stdlib_is_queue_eventually_not_empty to know that it is typed as a bool return"
        )
    return output


def assert_queue_is_eventually_not_empty(
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
) -> None:
    assert is_queue_eventually_not_empty(the_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS) is True


def assert_queue_is_eventually_empty(
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
) -> None:
    assert is_queue_eventually_empty(the_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS) is True


def convert_after_request_log_msg_to_json(log_msg: str) -> Dict[Any, Any]:
    trimmed_log_msg = log_msg[log_msg.index("{") :].replace("'", '"')
    logged_json: Dict[Any, Any] = json.loads(trimmed_log_msg)
    return logged_json


def assert_serial_packet_is_expected(
    full_packet: bytes,
    packet_type: int,
    additional_bytes: bytes = bytes(0),
    timestamp: Optional[int] = None,
    error_msg: Optional[str] = None,
) -> None:
    try:
        assert full_packet[SERIAL_COMM_PACKET_TYPE_INDEX] == packet_type
        packet_payload = full_packet[SERIAL_COMM_PAYLOAD_INDEX:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES]
        if packet_payload != additional_bytes:
            expected_len = len(additional_bytes)
            actual_len = len(packet_payload)
            if expected_len != actual_len:
                error_info = f"Expected len: {expected_len}, Actual len: {actual_len}"
                assert packet_payload == additional_bytes, error_info
            else:
                assert packet_payload == additional_bytes
        if timestamp is not None:
            actual_timestamp_bytes = full_packet[
                SERIAL_COMM_TIMESTAMP_BYTES_INDEX : SERIAL_COMM_TIMESTAMP_BYTES_INDEX
                + SERIAL_COMM_TIMESTAMP_LENGTH_BYTES
            ]
            actual_timestamp = int.from_bytes(actual_timestamp_bytes, byteorder="little")
            assert actual_timestamp == timestamp
    except AssertionError as e:
        if error_msg is not None:
            formatted_error_msg = f"\n  Error Message: {error_msg}"
            if "\n" in e.args[0]:
                error_lines = e.args[0].split("\n")
                error_lines[-2] += formatted_error_msg
                error_str = "\n".join(error_lines)
            else:
                error_str = e.args[0] + formatted_error_msg
            e.args = (error_str,)
        raise e


def get_full_packet_size_from_payload_len(payload_len: int) -> int:
    packet_size: int = SERIAL_COMM_PACKET_METADATA_LENGTH_BYTES + payload_len
    return packet_size


def assert_subprotocol_bytes_are_expected(actual, expected, err_msg=None):
    if len(expected) != STIM_PULSE_BYTES_LEN:
        raise ValueError(f"'expected' has incorrect len: {len(expected)}, should be: {STIM_PULSE_BYTES_LEN}")

    assert len(actual) == STIM_PULSE_BYTES_LEN, "Incorrect number of bytes"

    actual_dict = convert_subprotocol_pulse_bytes_to_dict(actual)
    expected_dict = convert_subprotocol_pulse_bytes_to_dict(expected)

    if err_msg:
        assert actual_dict == expected_dict, err_msg
    else:
        assert actual_dict == expected_dict


def assert_subprotocol_node_bytes_are_expected(actual, expected):
    assert len(actual) == len(expected), "Incorrect number of bytes"

    assert actual[0] == expected[0], "Incorrect stim node type"

    is_loop = bool(expected[0])

    if is_loop:
        assert actual[1] == expected[1], "Incorrect num stim nodes"

        actual_num_repeats = int.from_bytes(actual[2:6], byteorder="little")
        expected_num_repeats = int.from_bytes(expected[2:6], byteorder="little")
        assert actual_num_repeats == expected_num_repeats, "Incorrect number of repeats"

        # TODO this will only work with single level loops right now
        num_subprotocols = len(expected[6:]) // STIM_PULSE_BYTES_LEN
        for subprotocol_idx in range(num_subprotocols):
            start_idx = 6 + (subprotocol_idx * STIM_PULSE_BYTES_LEN)
            stop_idx = start_idx + STIM_PULSE_BYTES_LEN
            assert_subprotocol_bytes_are_expected(
                actual[start_idx:stop_idx],
                expected[start_idx:stop_idx],
                err_msg=f"subprotocol_idx: {subprotocol_idx}",
            )
    else:
        assert_subprotocol_bytes_are_expected(actual[1:], expected[1:])
