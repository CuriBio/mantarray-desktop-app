# -*- coding: utf-8 -*-
"""Docstring."""
from __future__ import annotations

import copy
import logging
from multiprocessing import Queue
import os
from typing import Any
from typing import Dict
from typing import Tuple

from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import resource_path

from .data_analyzer import DataAnalyzerProcess
from .file_writer import FileWriterProcess
from .firmware_manager import get_latest_firmware
from .ok_comm import OkCommunicationProcess


class MantarrayProcessesManager:  # pylint: disable=too-many-instance-attributes, too-many-public-methods
    """Controls access to all the subprocesses."""

    def __init__(
        self, file_directory: str = "", logging_level: int = logging.INFO
    ) -> None:
        # pylint-disable: duplicate-code # needed for the type definition of the board_queues
        self._ok_communication_error_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ]
        self._ok_communication_process: OkCommunicationProcess
        self._ok_comm_board_queues: Tuple[  # pylint-disable: duplicate-code
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
        ]
        self._logging_level: int
        self.set_logging_level(logging_level)
        self._file_writer_process: FileWriterProcess
        self._from_main_to_file_writer_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Dict[str, Any]
        ]
        self._from_file_writer_to_main_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Dict[str, Any]
        ]
        self._file_writer_error_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ]
        self._file_writer_board_queues: Tuple[  # pylint-disable: duplicate-code
            Tuple[
                Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                    Any
                ],
                Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                    Any
                ],
            ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ]
        self._file_directory: str = file_directory
        self._data_analyzer_process: DataAnalyzerProcess
        self._data_analyzer_board_queues: Tuple[  # pylint-disable: duplicate-code
            Tuple[
                Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                    Any
                ],
                Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
                    Any
                ],
            ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ]
        self._from_main_to_data_analyzer_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Dict[str, Any]
        ]
        self._from_data_analyzer_to_main_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Dict[str, Any]
        ]
        self._data_analyzer_error_queue: Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
            Tuple[Exception, str]
        ]

    def set_logging_level(self, logging_level: int) -> None:
        self._logging_level = logging_level

    def get_file_directory(self) -> str:
        return self._file_directory

    def set_file_directory(self, file_dir: str) -> None:
        self._file_directory = file_dir

    def get_logging_level(self) -> int:
        return self._logging_level

    def get_communication_queue_from_main_to_file_writer(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._from_main_to_file_writer_queue

    def get_communication_to_ok_comm_queue(
        self, board_idx: int
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._ok_comm_board_queues[board_idx][0]

    def get_communication_queue_from_ok_comm_to_main(
        self, board_idx: int
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Dict[str, Any]
    ]:
        return self._ok_comm_board_queues[board_idx][1]

    def get_ok_comm_process(self) -> OkCommunicationProcess:
        return self._ok_communication_process

    def get_file_writer_process(self) -> FileWriterProcess:
        return self._file_writer_process

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

    def get_ok_communication_error_queue(
        self,
    ) -> Queue[  # pylint: disable=unsubscriptable-object # https://github.com/PyCQA/pylint/issues/1498
        Tuple[Exception, str]
    ]:
        return self._ok_communication_error_queue

    def get_data_analyzer_process(self) -> DataAnalyzerProcess:
        return self._data_analyzer_process

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

    def _create_queues(self) -> None:
        """Create all the queues and assign to the instance variables."""
        self._ok_communication_error_queue = Queue()
        ok_board_queues: Tuple[  # pylint-disable: duplicate-code
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
            ],  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
            ...,  # noqa: E231 # flake8 doesn't understand the 3 dots for type definition
        ] = tuple([(Queue(), Queue(), Queue(),)] * 1)
        self._ok_comm_board_queues = ok_board_queues

        self._from_file_writer_to_main_queue = Queue()
        self._file_writer_error_queue = Queue()
        self._from_main_to_file_writer_queue = Queue()
        self._file_writer_board_queues = tuple([(ok_board_queues[0][2], Queue(),)] * 1)

        self._from_data_analyzer_to_main_queue = Queue()
        self._data_analyzer_error_queue = Queue()
        self._from_main_to_data_analyzer_queue = Queue()
        self._data_analyzer_board_queues = tuple(
            [(self._file_writer_board_queues[0][1], Queue(),)] * 1
        )

    def create_processes(self) -> None:
        """Create/init the processes."""
        self._create_queues()

        self._ok_communication_process = OkCommunicationProcess(
            self._ok_comm_board_queues,
            self._ok_communication_error_queue,
            logging_level=self._logging_level,
        )

        self._file_writer_process = FileWriterProcess(
            self._file_writer_board_queues,
            self._from_main_to_file_writer_queue,
            self._from_file_writer_to_main_queue,
            self._file_writer_error_queue,
            file_directory=self._file_directory,
            logging_level=self._logging_level,
        )

        self._data_analyzer_process = DataAnalyzerProcess(
            self._data_analyzer_board_queues,
            self._from_main_to_data_analyzer_queue,
            self._from_data_analyzer_to_main_queue,
            self._data_analyzer_error_queue,
            logging_level=self._logging_level,
        )

    def start_processes(self) -> None:
        self._ok_communication_process.start()
        self._file_writer_process.start()
        self._data_analyzer_process.start()

    def spawn_processes(self) -> None:
        """Create and start processes, no extra args."""
        self.create_processes()
        self.start_processes()

    def boot_up_instrument(self) -> Dict[str, Any]:
        """Boot up the Mantarray instrument.

        It is assumed that 'bit_file_name' will be a path to a real .bit
        firmware file whose name follows the format:
        'mantarray_#_#_#.bit'
        """
        bit_file_name = get_latest_firmware()
        to_ok_comm_queue = self.get_communication_to_ok_comm_queue(0)

        boot_up_dict = {
            "communication_type": "boot_up_instrument",
            "command": "initialize_board",
            "bit_file_name": bit_file_name,
            "suppress_error": False,
            "allow_board_reinitialization": False,
        }
        to_ok_comm_queue.put(boot_up_dict)

        start_up_dict = {
            "communication_type": "xem_scripts",
            "script_type": "start_up",
        }
        to_ok_comm_queue.put(start_up_dict)

        response_dict = {
            "boot_up_instrument": copy.deepcopy(boot_up_dict),
            "start_up": copy.deepcopy(start_up_dict),
        }
        return response_dict

    def stop_processes(self) -> None:
        self._ok_communication_process.stop()
        self._file_writer_process.stop()
        self._data_analyzer_process.stop()

    def soft_stop_processes(self) -> None:
        self._ok_communication_process.soft_stop()
        self._file_writer_process.soft_stop()
        self._data_analyzer_process.soft_stop()

    def hard_stop_processes(self) -> Dict[str, Any]:
        ok_comm_items = self._ok_communication_process.hard_stop()
        file_writer_items = self._file_writer_process.hard_stop()
        data_analyzer_items = self._data_analyzer_process.hard_stop()
        process_items = {
            "ok_comm_items": ok_comm_items,
            "file_writer_items": file_writer_items,
            "data_analyzer_items": data_analyzer_items,
        }
        return process_items

    def join_processes(self) -> None:
        self._ok_communication_process.join()
        self._file_writer_process.join()
        self._data_analyzer_process.join()

    def soft_stop_and_join_processes(self) -> None:
        self.soft_stop_processes()
        self.join_processes()

    def stop_and_join_processes(self) -> None:
        self.stop_processes()
        self.join_processes()

    def hard_stop_and_join_processes(self) -> Dict[str, Any]:
        """Hard stop all processes and return contents of their queues."""
        ok_comm_items = self._ok_communication_process.hard_stop()
        self._ok_communication_process.join()
        file_writer_items = self._file_writer_process.hard_stop()
        self._file_writer_process.join()
        data_analyzer_items = self._data_analyzer_process.hard_stop()
        self._data_analyzer_process.join()
        process_items = {
            "ok_comm_items": ok_comm_items,
            "file_writer_items": file_writer_items,
            "data_analyzer_items": data_analyzer_items,
        }
        return process_items


def _create_process_manager() -> MantarrayProcessesManager:
    base_path = os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir)
    relative_path = "recordings"
    file_dir = resource_path(relative_path, base_path=base_path)
    return MantarrayProcessesManager(file_directory=file_dir)


the_manager = (  # pylint: disable=invalid-name # this is a singleton
    _create_process_manager()
)


def get_mantarray_process_manager() -> MantarrayProcessesManager:
    return the_manager
