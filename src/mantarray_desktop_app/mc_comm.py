# -*- coding: utf-8 -*-
"""Mantarray Microcontroller Simulator."""
from __future__ import annotations

import logging
from multiprocessing import Queue
from typing import Any
from typing import Dict
from typing import Tuple

from .instrument_comm import InstrumentCommProcess


class McCommunicationProcess(InstrumentCommProcess):
    """Process that controls communication with the Mantarray Beta 2 Board(s).

    Args:
        board_queues: A tuple (the max number of MC board connections should be pre-defined, so not a mutable list) of tuples of 3 queues. The first queue is for input/communication from the main thread to this sub process, second queue is for communication from this process back to the main thread. Third queue is for streaming communication (largely fo raw data) to the process that controls writing to disk.
        fatal_error_reporter: A queue that reports back any unhandled errors that have caused the process to stop.
        suppress_setup_communication_to_main: if set to true (often during unit tests), messages during the _setup_before_loop will not be put into the queue to communicate back to the main process
    """

    def __init__(
        self,
        # pylint: disable=duplicate-code
        board_queues: Tuple[  # pylint-disable: duplicate-code
            Tuple[
                Queue[Dict[str, Any]],  # pylint: disable=unsubscriptable-object
                Queue[  # pylint: disable=unsubscriptable-object
                    Dict[str, Any]
                ],  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Queue[Any],  # pylint: disable=unsubscriptable-object
            ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            # pylint: disable=duplicate-code
        ],
        fatal_error_reporter: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ],
        # pylint: disable=duplicate-code
        suppress_setup_communication_to_main: bool = False,
        logging_level: int = logging.INFO,
    ):
        # pylint: disable=duplicate-code
        super().__init__(
            board_queues,
            fatal_error_reporter,  # pylint: disable=duplicate-code
            suppress_setup_communication_to_main,
            logging_level,
        )
        self._new_var = None

    def create_connections_to_all_available_boards(self) -> None:
        pass  # Tanner (12/18/21): adding this as a placeholder for now to override abstract method
