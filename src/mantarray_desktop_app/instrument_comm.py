# -*- coding: utf-8 -*-
"""Shared functionality of different versions of Mantarray instruments."""
from __future__ import annotations

import abc
import logging
from multiprocessing import Queue
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from stdlib_utils import InfiniteProcess
from xem_wrapper import okCFrontPanel


class InstrumentCommProcess(InfiniteProcess, metaclass=abc.ABCMeta):
    """Process that controls communication with the Mantarrays Instruments.

    Args:
        board_queues: A tuple (the max number of instrument board connections should be pre-defined, so not a mutable list) of tuples of 3 queues. The first queue is for input/communication from the main thread to this sub process, second queue is for communication from this process back to the main thread. Third queue is for streaming communication (largely fo raw data) to the process that controls writing to disk.
        fatal_error_reporter: A queue that reports back any unhandled errors that have caused the process to stop.
        suppress_setup_communication_to_main: if set to true (often during unit testing), messages during the _setup_before_loop will not be put into the queue to communicate back to the main process
    """

    def __init__(
        # pylint: disable=duplicate-code
        self,
        board_queues: Tuple[
            Tuple[
                Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
                Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
                # pylint: disable=duplicate-code
                Queue[Any],  # pylint: disable=unsubscriptable-object
            ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ],
        # pylint: disable=duplicate-code
        fatal_error_reporter: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ],
        # pylint: disable=duplicate-code
        suppress_setup_communication_to_main: bool = False,
        logging_level: int = logging.INFO,
    ):
        super().__init__(fatal_error_reporter, logging_level=logging_level)
        self._board_queues = board_queues
        self._board_connections: List[Union[None, okCFrontPanel]] = [None] * len(
            self._board_queues
        )
        self._suppress_setup_communication_to_main = (
            suppress_setup_communication_to_main
        )

    def hard_stop(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        return_value: Dict[str, Any] = super().hard_stop(timeout=timeout)
        board_connections = self.get_board_connections_list()
        for iter_board in board_connections:
            if iter_board is not None:
                iter_board.hard_stop(timeout=timeout)
        return return_value

    def determine_how_many_boards_are_connected(self) -> int:
        # pylint: disable=no-self-use # currently a place holder just being mocked
        return 1  # place holder for linting

    @abc.abstractmethod
    def create_connections_to_all_available_boards(self) -> None:
        pass

    def get_board_connections_list(self) -> List[Union[None, okCFrontPanel]]:
        return self._board_connections
