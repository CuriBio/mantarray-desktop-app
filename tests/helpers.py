# -*- coding: utf-8 -*-
"""Could possibly be refactored as a plugin based on stdlib_utils.

https://docs.pytest.org/en/stable/writing_plugins.html
"""
from __future__ import annotations

import json
from time import perf_counter
from typing import Any
from typing import Dict
from typing import List
from typing import Union

import stdlib_utils
from stdlib_utils import confirm_queue_is_eventually_empty as stdlib_c_q_is_e_e
from stdlib_utils import confirm_queue_is_eventually_of_size as stdlib_c_q_is_e_of_s
from stdlib_utils import is_queue_eventually_empty as stdlib_is_queue_eventually_empty
from stdlib_utils import is_queue_eventually_not_empty as stdlib_is_queue_ena
from stdlib_utils import is_queue_eventually_of_size as stdlib_is_queue_eos
from stdlib_utils import QueueStillEmptyError
from stdlib_utils import UnionOfThreadingAndMultiprocessingQueue

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS

QUEUE_EMPTY_CHECK_TIMEOUT_SECONDS = 0.2


def put_object_into_queue_and_raise_error_if_eventually_still_empty(
    obj: object,
    the_queue: UnionOfThreadingAndMultiprocessingQueue,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
) -> None:
    stdlib_utils.put_object_into_queue_and_raise_error_if_eventually_still_empty(
        obj, the_queue, timeout_seconds=timeout_seconds
    )


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
) -> None:
    stdlib_c_q_is_e_of_s(the_queue, size, timeout_seconds=timeout_seconds)


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
    output = stdlib_is_queue_ena(the_queue, timeout_seconds=timeout_seconds)
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
