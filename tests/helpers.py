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

from stdlib_utils import is_queue_eventually_not_empty

from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS


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
