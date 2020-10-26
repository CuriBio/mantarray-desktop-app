# -*- coding: utf-8 -*-
"""Could possibly be refactored as a plugin based on stdlib_utils.

https://docs.pytest.org/en/stable/writing_plugins.html
"""
from __future__ import annotations

import multiprocessing
import multiprocessing.queues
from queue import Queue
from typing import Any
from typing import Union

import stdlib_utils
from stdlib_utils import is_queue_eventually_empty as stdlib_is_queue_eventually_empty
from stdlib_utils import is_queue_eventually_not_empty as stdlib_is_queue_ena
from stdlib_utils import is_queue_eventually_of_size as stdlib_is_queue_eos

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS


def put_object_into_queue_and_raise_error_if_eventually_still_empty(
    obj: object,
    the_queue: Union[
        Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
        multiprocessing.queues.Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
    ],
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
) -> None:
    stdlib_utils.put_object_into_queue_and_raise_error_if_eventually_still_empty(
        obj, the_queue, timeout_seconds=timeout_seconds
    )


def is_queue_eventually_of_size(
    the_queue: Union[
        Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
        multiprocessing.queues.Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
    ],
    size: int,
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
) -> bool:
    output = stdlib_is_queue_eos(the_queue, size, timeout_seconds=timeout_seconds)
    if not isinstance(output, bool):
        raise NotImplementedError(
            "not sure why mypy is unable to follow the definition of stdlib_is_queue_eventually_of_size to know that it is typed as a bool return"
        )
    return output


def is_queue_eventually_empty(
    the_queue: Union[
        Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
        multiprocessing.queues.Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
    ],
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
    the_queue: Union[
        Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
        multiprocessing.queues.Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
    ],
    timeout_seconds: Union[float, int] = QUEUE_CHECK_TIMEOUT_SECONDS,
) -> bool:
    output = stdlib_is_queue_ena(the_queue, timeout_seconds=timeout_seconds)
    if not isinstance(output, bool):
        raise NotImplementedError(
            "not sure why mypy is unable to follow the definition of stdlib_is_queue_eventually_not_empty to know that it is typed as a bool return"
        )
    return output


def assert_queue_is_eventually_not_empty(
    the_queue: Union[
        Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
        multiprocessing.queues.Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
    ]
) -> None:
    assert (
        is_queue_eventually_not_empty(
            the_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )


def assert_queue_is_eventually_empty(
    the_queue: Union[
        Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
        multiprocessing.queues.Queue[  # pylint: disable=unsubscriptable-object # Eli (3/12/20) not sure why pylint doesn't recognize this type annotation
            Any
        ],
    ]
) -> None:
    assert (
        is_queue_eventually_empty(
            the_queue, timeout_seconds=QUEUE_CHECK_TIMEOUT_SECONDS
        )
        is True
    )
