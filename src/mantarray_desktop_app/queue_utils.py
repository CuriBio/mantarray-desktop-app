# -*- coding: utf-8 -*-
"""Utility functions for interacting with the fully running app."""
from __future__ import annotations

from queue import Queue
from typing import Any
from typing import List

from stdlib_utils import safe_get


def _drain_queue(
    data_out_queue: Queue[Any],  # pylint: disable=unsubscriptable-object
) -> List[Any]:
    # TODO (Eli 10/27/20): figure out how to move this to stdlib_utils
    queue_items = list()
    item = safe_get(data_out_queue)
    while item is not None:
        queue_items.append(item)
        item = safe_get(data_out_queue)
    return queue_items
