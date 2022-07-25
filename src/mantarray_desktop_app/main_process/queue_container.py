# -*- coding: utf-8 -*-
"""Container for all multiprocessing/threading queues."""
from __future__ import annotations

from multiprocessing import Queue
import queue
from typing import Any
from typing import Dict
from typing import Tuple

from eventlet.queue import LightQueue


# TODO Tanner (6/15/21): refactor this into something nicer
class MantarrayQueueContainer:
    """Getter for all the queues."""

    # pylint:disable=too-many-instance-attributes # Eli (12/8/20): there are a lot of queues, this class manages them
    def __init__(self) -> None:
        # Tanner (6/15/21): black does not treat all these type definitions and comments kindly, so turning off formatting
        # fmt: off
        self._instrument_communication_error_queue: Queue[Tuple[Exception, str]] = Queue()  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        self._instrument_comm_board_queues: Tuple[
            Tuple[Queue[Dict[str, Any]], Queue[Dict[str, Any]], Queue[Any]], ...,  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        ] = tuple((Queue(), Queue(), Queue()) for _ in range(1))

        self._from_main_to_file_writer_queue: Queue[Dict[str, Any]] = Queue()  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        self._from_file_writer_to_main_queue: Queue[Dict[str, Any]] = Queue()  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        self._file_writer_error_queue: Queue[Tuple[Exception, str]] = Queue()  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        self._file_writer_board_queues: Tuple[
            Tuple[Queue[Any], Queue[Any]], ...  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        ] = tuple((self._instrument_comm_board_queues[i][2], Queue()) for i in range(1))

        self._data_analyzer_board_queues: Tuple[
            Tuple[Queue[Any], Queue[Any]], ...  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ] = tuple((self._file_writer_board_queues[i][1], Queue()) for i in range(1))
        self._from_main_to_data_analyzer_queue: Queue[Dict[str, Any]] = Queue()  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        self._from_data_analyzer_to_main_queue: Queue[Dict[str, Any]] = Queue()  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        self._data_analyzer_error_queue: Queue[Tuple[Exception, str]] = Queue()  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498

        self._from_server_to_main_queue: queue.Queue[Dict[str, Any]] = queue.Queue()  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        self._data_to_server_queue: LightQueue = LightQueue()
        # fmt: on

    def get_communication_queue_from_main_to_file_writer(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._from_main_to_file_writer_queue

    def get_communication_to_instrument_comm_queue(
        self, board_idx: int
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._instrument_comm_board_queues[board_idx][0]

    def get_instrument_comm_board_queues(
        self,
    ) -> Tuple[  # pylint-disable: duplicate-code
        Tuple[
            Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Dict[str, Any]
            ],
            Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Dict[str, Any]
            ],
            Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Any
            ],
        ],
        ...,
    ]:
        """Return all board queues for Instrument subprocess."""
        return self._instrument_comm_board_queues

    def get_file_writer_board_queues(  # pylint: disable=duplicate-code # Eli (12/8/20): I can't figure out how to use mypy type aliases correctly...but the type definitions are triggering duplicate code warnings
        self,
    ) -> Tuple[  # pylint: disable=duplicate-code
        Tuple[
            Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Any  # pylint: disable=duplicate-code
            ],
            Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Any
            ],  # pylint: disable=duplicate-code
        ],
        ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
    ]:
        """Return all board queues for File Writer subprocess."""
        return self._file_writer_board_queues

    # pylint: disable=duplicate-code # Eli (12/8/20): I can't figure out how to use mypy type aliases correctly...but the type definitions are triggering duplicate code warnings
    def get_data_analyzer_board_queues(  # pylint: disable=duplicate-code # Eli (12/8/20): I can't figure out how to use mypy type aliases correctly...but the type definitions are triggering duplicate code warnings
        self,
    ) -> Tuple[  # pylint:disable=duplicate-code
        Tuple[
            Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Any
            ],
            Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                Any
            ],
        ],
        ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
    ]:
        """Return all board queues for Data Analyzer subprocess."""
        return self._data_analyzer_board_queues

    def get_communication_queue_from_instrument_comm_to_main(
        self, board_idx: int
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._instrument_comm_board_queues[board_idx][1]

    def get_communication_queue_from_server_to_main(
        self,
    ) -> queue.Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._from_server_to_main_queue

    def get_data_queue_to_server(self) -> LightQueue:
        return self._data_to_server_queue

    def get_communication_queue_from_file_writer_to_main(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._from_file_writer_to_main_queue

    def get_file_writer_error_queue(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Tuple[Exception, str]
    ]:
        return self._file_writer_error_queue

    def get_instrument_communication_error_queue(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Tuple[Exception, str]
    ]:
        return self._instrument_communication_error_queue

    def get_communication_queue_from_data_analyzer_to_main(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._from_data_analyzer_to_main_queue

    def get_communication_queue_from_main_to_data_analyzer(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._from_main_to_data_analyzer_queue

    def get_data_analyzer_data_out_queue(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._data_analyzer_board_queues[0][1]

    def get_data_analyzer_error_queue(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Tuple[Exception, str]
    ]:
        return self._data_analyzer_error_queue
