# -*- coding: utf-8 -*-
"""Could possibly be refactored as a plugin based on stdlib_utils.

https://docs.pytest.org/en/stable/writing_plugins.html
"""
from __future__ import annotations

import json
import time
from time import perf_counter
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from mantarray_desktop_app import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from mantarray_desktop_app import SERIAL_COMM_CHECKSUM_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_MAGIC_WORD_BYTES
from mantarray_desktop_app import SERIAL_COMM_MIN_PACKET_SIZE_BYTES
from mantarray_desktop_app import SERIAL_COMM_MODULE_ID_INDEX
from mantarray_desktop_app import SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
from mantarray_desktop_app import SERIAL_COMM_PACKET_TYPE_INDEX
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
    stdlib_c_q_is_e_of_s(the_queue, size, timeout_seconds=timeout_seconds)
    if sleep_after_confirm_seconds is not None:
        time.sleep(sleep_after_confirm_seconds)


def handle_putting_multiple_objects_into_empty_queue(
    objs: List[object],
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
) -> None:
    for next_obj in objs:
        the_queue.put(next_obj)
    confirm_queue_is_eventually_of_size(the_queue, len(objs))
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
    output = stdlib_is_queue_eventually_empty(
        the_queue, timeout_seconds=timeout_seconds
    )
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
    assert (
        is_queue_eventually_not_empty(
            the_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )


def assert_queue_is_eventually_empty(
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
) -> None:
    assert (
        is_queue_eventually_empty(
            the_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )


def convert_after_request_log_msg_to_json(log_msg: str) -> Dict[Any, Any]:
    trimmed_log_msg = log_msg[log_msg.index("{") :].replace("'", '"')
    logged_json: Dict[Any, Any] = json.loads(trimmed_log_msg)
    return logged_json


def assert_serial_packet_is_expected(
    full_packet: bytes,
    module_id: int,
    packet_type: int,
    additional_bytes: bytes = bytes(0),
) -> None:
    assert full_packet[SERIAL_COMM_MODULE_ID_INDEX] == module_id
    assert full_packet[SERIAL_COMM_PACKET_TYPE_INDEX] == packet_type
    assert (
        full_packet[
            SERIAL_COMM_ADDITIONAL_BYTES_INDEX:-SERIAL_COMM_CHECKSUM_LENGTH_BYTES
        ]
        == additional_bytes
    )


def get_full_packet_size_from_packet_body_size(packet_body_size: int) -> int:
    return (
        len(SERIAL_COMM_MAGIC_WORD_BYTES)
        + SERIAL_COMM_PACKET_INFO_LENGTH_BYTES
        + SERIAL_COMM_MIN_PACKET_SIZE_BYTES
        + packet_body_size
    )
