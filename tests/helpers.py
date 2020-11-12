# -*- coding: utf-8 -*-
"""Could possibly be refactored as a plugin based on stdlib_utils.

https://docs.pytest.org/en/stable/writing_plugins.html
"""
from __future__ import annotations

from typing import Union

import stdlib_utils
from stdlib_utils import (
    confirm_queue_is_eventually_of_size as stdlib_confirm_queue_is_eventually_of_size,
)
from stdlib_utils import is_queue_eventually_empty as stdlib_is_queue_eventually_empty
from stdlib_utils import is_queue_eventually_not_empty as stdlib_is_queue_ena
from stdlib_utils import is_queue_eventually_of_size as stdlib_is_queue_eos
from stdlib_utils import UnionOfThreadingAndMultiprocessingQueue

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS


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
    stdlib_confirm_queue_is_eventually_of_size(
        the_queue, size, timeout_seconds=timeout_seconds
    )


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
