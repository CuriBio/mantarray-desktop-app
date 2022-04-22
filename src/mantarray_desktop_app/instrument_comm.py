# -*- coding: utf-8 -*-
"""Shared functionality of different versions of Mantarray instruments."""
from __future__ import annotations

import abc
import logging
from multiprocessing import Queue
from multiprocessing import queues as mpqueues
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

import serial
from stdlib_utils import drain_queue
from stdlib_utils import InfiniteProcess
from stdlib_utils import put_log_message_into_queue
from xem_wrapper import FrontPanelBase
from xem_wrapper import okCFrontPanel

from .mc_simulator import MantarrayMcSimulator


def _drain_board_queues(
    board: Tuple[
        Queue[Any],  # pylint: disable=unsubscriptable-object
        Queue[Any],  # pylint: disable=unsubscriptable-object
        Queue[Any],  # pylint: disable=unsubscriptable-object
    ],
) -> Dict[str, List[Any]]:
    board_dict = dict()
    board_dict["main_to_instrument_comm"] = drain_queue(board[0])
    board_dict["instrument_comm_to_main"] = drain_queue(board[1])
    board_dict["instrument_comm_to_file_writer"] = drain_queue(board[2])
    return board_dict


class InstrumentCommProcess(InfiniteProcess, metaclass=abc.ABCMeta):
    """Process that controls communication with Mantarray instruments.

    Args:
        board_queues: A tuple (the max number of instrument board connections should be predefined, so not a mutable list) of tuples of 3 queues. The first queue is for input/communication from the main thread to this sub process, second queue is for communication from this process back to the main thread. Third queue is for streaming communication (largely of raw data) to the process that controls writing to disk.
        fatal_error_reporter: A queue that reports back any unhandled errors that have caused the process to stop.
        suppress_setup_communication_to_main: if set to true (often during unit testing), messages during the _setup_before_loop will not be put into the queue to communicate back to the main process
    """

    def __init__(
        self,
        board_queues: Tuple[
            Tuple[
                Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
                Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
                Queue[Any],  # pylint: disable=unsubscriptable-object
            ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ],
        fatal_error_reporter: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ],
        suppress_setup_communication_to_main: bool = False,
        # pylint: disable=duplicate-code
        logging_level: int = logging.INFO,
    ):
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._board_queues = board_queues
        self._board_connections: List[Union[None, okCFrontPanel, MantarrayMcSimulator]] = [None] * len(
            self._board_queues
        )
        self._suppress_setup_communication_to_main = suppress_setup_communication_to_main

    def start(self) -> None:
        for board_queue_tuple in self._board_queues:
            for ic_queue in board_queue_tuple:
                if not isinstance(ic_queue, mpqueues.Queue):
                    raise NotImplementedError(
                        "All queues must be standard multiprocessing queues to start this process"
                    )
        super().start()

    def hard_stop(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        return_value: Dict[str, Any] = super().hard_stop(timeout=timeout)
        board_connections = self.get_board_connections_list()
        for iter_board in board_connections:
            if iter_board is not None:
                iter_board.hard_stop(timeout=timeout)
        return return_value

    def determine_how_many_boards_are_connected(self) -> int:
        # currently a place holder just being mocked
        return 1

    @abc.abstractmethod
    def create_connections_to_all_available_boards(self) -> None:
        pass

    def set_board_connection(
        self,
        board_idx: int,
        board: Union[FrontPanelBase, MantarrayMcSimulator, serial.Serial],
    ) -> None:
        board_connections = self.get_board_connections_list()
        board_connections[board_idx] = board

    def get_board_connections_list(
        self,
    ) -> List[Union[None, okCFrontPanel, MantarrayMcSimulator]]:
        return self._board_connections

    def _send_performance_metrics(self, performance_metrics: Dict[str, Any]) -> None:
        tracker = self.reset_performance_tracker()
        performance_metrics["percent_use"] = tracker["percent_use"]
        performance_metrics["longest_iterations"] = sorted(tracker["longest_iterations"])
        if len(self._percent_use_values) > 1:
            performance_metrics["percent_use_metrics"] = self.get_percent_use_metrics()
        put_log_message_into_queue(
            logging.INFO,
            performance_metrics,
            self._board_queues[0][1],
            self.get_logging_level(),
        )

    def _drain_all_queues(self) -> Dict[str, Any]:
        queue_items = dict()
        for i, board in enumerate(self._board_queues):
            queue_items[f"board_{i}"] = _drain_board_queues(board)
        return queue_items
