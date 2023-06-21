# -*- coding: utf-8 -*-
"""Container for all multiprocessing/threading queues."""
from __future__ import annotations

from multiprocessing import Queue
import queue
from typing import Any
from typing import Dict
from typing import Tuple

from eventlet.queue import LightQueue


# TODO Tanner (7/27/22): refactor queue structure so there is a single queue per data direction, not one per board connection
class MantarrayQueueContainer:
    """Container for all the queues."""

    def __init__(self) -> None:
        max_num_boards = 1
        self.instrument_comm_error: Queue[Tuple[Exception, str]] = Queue()
        self.instrument_comm_boards: Tuple[
            Tuple[Queue[Dict[str, Any]], Queue[Dict[str, Any]], Queue[Any]],
            ...,
        ] = tuple((Queue(), Queue(), Queue()) for _ in range(max_num_boards))

        self.to_file_writer: Queue[Dict[str, Any]] = Queue()
        self.from_file_writer: Queue[Dict[str, Any]] = Queue()
        self.file_writer_error: Queue[Tuple[Exception, str]] = Queue()
        self.file_writer_boards: Tuple[Tuple[Queue[Any], Queue[Any]], ...] = tuple(
            (self.instrument_comm_boards[i][2], Queue()) for i in range(max_num_boards)
        )

        self.data_analyzer_boards: Tuple[
            Tuple[Queue[Any], Queue[Any]],
            ...,
        ] = tuple((self.file_writer_boards[i][1], Queue()) for i in range(max_num_boards))
        self.to_data_analyzer: Queue[Dict[str, Any]] = Queue()
        self.from_data_analyzer: Queue[Dict[str, Any]] = Queue()
        self.data_analyzer_error: Queue[Tuple[Exception, str]] = Queue()

        self.from_flask: queue.Queue[Dict[str, Any]] = queue.Queue()
        self.to_websocket: LightQueue = LightQueue()
        self.from_websocket: queue.Queue[Dict[str, Any]] = queue.Queue()

    # TODO (7/27/22): remove these methods once the refactor in the to do note above is complete
    def to_instrument_comm(self, board_idx: int) -> Queue[Dict[str, Any]]:
        return self.instrument_comm_boards[board_idx][0]

    def from_instrument_comm(self, board_idx: int) -> Queue[Dict[str, Any]]:
        return self.instrument_comm_boards[board_idx][1]

    def get_data_analyzer_data_out_queue(self) -> Queue[Dict[str, Any]]:
        return self.data_analyzer_boards[0][1]
