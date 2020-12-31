# -*- coding: utf-8 -*-
"""Docstring."""
from __future__ import annotations

import copy
import logging
import os
from time import perf_counter
from time import sleep
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Optional
from typing import Tuple
from typing import Union

from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import resource_path

from .constants import DEFAULT_SERVER_PORT_NUMBER
from .constants import INSTRUMENT_INITIALIZING_STATE
from .constants import SUBPROCESS_POLL_DELAY_SECONDS
from .constants import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from .data_analyzer import DataAnalyzerProcess
from .file_writer import FileWriterProcess
from .firmware_manager import get_latest_firmware
from .ok_comm import OkCommunicationProcess
from .queue_container import MantarrayQueueContainer
from .server import ServerThread


class MantarrayProcessesManager:  # pylint: disable=too-many-public-methods
    """Controls access to all the subprocesses."""

    def __init__(
        self,
        file_directory: str = "",
        logging_level: int = logging.INFO,
        values_to_share_to_server: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._queue_container: MantarrayQueueContainer

        self._ok_communication_process: OkCommunicationProcess
        self._logging_level: int
        if values_to_share_to_server is None:
            values_to_share_to_server = dict()

        self._values_to_share_to_server = values_to_share_to_server
        self._server_thread: ServerThread
        self._file_writer_process: FileWriterProcess
        self._file_directory: str = file_directory
        self._data_analyzer_process: DataAnalyzerProcess

        self._all_processes = Tuple[
            ServerThread, OkCommunicationProcess, FileWriterProcess, DataAnalyzerProcess
        ]  # server takes longest to start, so have that first

        self.set_logging_level(logging_level)

    def set_logging_level(self, logging_level: int) -> None:
        self._logging_level = logging_level

    def get_values_to_share_to_server(self) -> Dict[str, Any]:
        return self._values_to_share_to_server

    def queue_container(self) -> MantarrayQueueContainer:
        return self._queue_container

    def get_file_directory(self) -> str:
        return self._file_directory

    def set_file_directory(self, file_dir: str) -> None:
        self._file_directory = file_dir

    def get_logging_level(self) -> int:
        return self._logging_level

    def get_instrument_process(self) -> OkCommunicationProcess:
        return self._ok_communication_process

    def get_file_writer_process(self) -> FileWriterProcess:
        return self._file_writer_process

    def get_server_thread(self) -> ServerThread:
        return self._server_thread

    def get_data_analyzer_process(self) -> DataAnalyzerProcess:
        return self._data_analyzer_process

    def create_processes(self) -> None:
        """Create/init the processes."""
        queue_container = MantarrayQueueContainer()
        self._queue_container = queue_container

        self._server_thread = ServerThread(
            queue_container.get_communication_queue_from_server_to_main(),
            queue_container.get_server_error_queue(),
            queue_container,
            logging_level=self._logging_level,
            values_from_process_monitor=self._values_to_share_to_server,
            port=self._values_to_share_to_server.get(
                "server_port_number", DEFAULT_SERVER_PORT_NUMBER
            ),
        )

        self._ok_communication_process = OkCommunicationProcess(
            queue_container.get_ok_comm_board_queues(),
            queue_container.get_ok_communication_error_queue(),
            logging_level=self._logging_level,
        )

        self._file_writer_process = FileWriterProcess(
            queue_container.get_file_writer_board_queues(),
            queue_container.get_communication_queue_from_main_to_file_writer(),
            queue_container.get_communication_queue_from_file_writer_to_main(),
            queue_container.get_file_writer_error_queue(),
            file_directory=self._file_directory,
            logging_level=self._logging_level,
        )

        self._data_analyzer_process = DataAnalyzerProcess(
            queue_container.get_data_analyzer_board_queues(),
            queue_container.get_communication_queue_from_main_to_data_analyzer(),
            queue_container.get_communication_queue_from_data_analyzer_to_main(),
            queue_container.get_data_analyzer_error_queue(),
            logging_level=self._logging_level,
        )

        self._all_processes = (
            self._server_thread,
            self._ok_communication_process,
            self._file_writer_process,
            self._data_analyzer_process,
        )

    def start_processes(self) -> None:
        if not isinstance(  # pylint:disable=isinstance-second-argument-not-valid-type # Eli (12/8/20): pylint issue https://github.com/PyCQA/pylint/issues/3507
            self._all_processes, Iterable
        ):
            raise NotImplementedError("Processes must be created first.")
        for iter_process in self._all_processes:
            iter_process.start()

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
        to_ok_comm_queue = self.queue_container().get_communication_to_ok_comm_queue(0)

        self.get_values_to_share_to_server()[
            "system_status"
        ] = INSTRUMENT_INITIALIZING_STATE
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
        if not isinstance(  # pylint:disable=isinstance-second-argument-not-valid-type # Eli (12/8/20): pylint issue https://github.com/PyCQA/pylint/issues/3507
            self._all_processes, Iterable
        ):
            raise NotImplementedError("Processes must be created first.")
        for iter_process in self._all_processes:
            iter_process.stop()

    def soft_stop_processes(self) -> None:
        self.soft_stop_processes_except_server()
        self.get_server_thread().soft_stop()

    def soft_stop_processes_except_server(self) -> None:
        if not isinstance(  # pylint:disable=isinstance-second-argument-not-valid-type # Eli (12/8/20): pylint issue https://github.com/PyCQA/pylint/issues/3507
            self._all_processes, Iterable
        ):
            raise NotImplementedError("Processes must be created first.")
        for iter_process in self._all_processes:
            if isinstance(iter_process, ServerThread):
                continue
            iter_process.soft_stop()

    def hard_stop_processes(self) -> Dict[str, Any]:
        """Immediately stop subprocesses."""
        ok_comm_items = self._ok_communication_process.hard_stop()
        file_writer_items = self._file_writer_process.hard_stop()
        data_analyzer_items = self._data_analyzer_process.hard_stop()
        server_items = self._server_thread.hard_stop()
        process_items = {
            "ok_comm_items": ok_comm_items,
            "file_writer_items": file_writer_items,
            "data_analyzer_items": data_analyzer_items,
            "server_items": server_items,
        }
        return process_items

    def join_processes(self) -> None:
        if not isinstance(  # pylint:disable=isinstance-second-argument-not-valid-type # Eli (12/8/20): pylint issue https://github.com/PyCQA/pylint/issues/3507
            self._all_processes, Iterable
        ):
            raise NotImplementedError("Processes must be created first.")
        for iter_process in self._all_processes:
            iter_process.join()

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
        server_items = self._server_thread.hard_stop()
        self._server_thread.join()
        process_items = {
            "ok_comm_items": ok_comm_items,
            "file_writer_items": file_writer_items,
            "data_analyzer_items": data_analyzer_items,
            "server_items": server_items,
        }
        return process_items

    def are_processes_stopped(
        self, timeout_secs: Union[float, int] = SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
    ) -> bool:
        """Check if processes are stopped."""
        start = perf_counter()
        processes = self._all_processes
        if not isinstance(  # pylint:disable=isinstance-second-argument-not-valid-type # Eli (12/8/20): pylint issue https://github.com/PyCQA/pylint/issues/3507
            processes, Iterable
        ):
            raise NotImplementedError("Processes must be created first.")

        are_stopped = all(p.is_stopped() for p in processes)
        while not are_stopped:
            sleep(SUBPROCESS_POLL_DELAY_SECONDS)
            elapsed_time = perf_counter() - start
            if elapsed_time >= timeout_secs:
                break
            are_stopped = all(p.is_stopped() for p in processes)
        return are_stopped

    def are_subprocess_start_ups_complete(self) -> bool:
        """Check if all subprocesses' start-up events have been set.

        Often useful in unit-testing or other places where the processes
        should be fully running before attempting the next command.
        """
        if not isinstance(  # pylint:disable=isinstance-second-argument-not-valid-type # Eli (12/8/20): pylint issue https://github.com/PyCQA/pylint/issues/3507
            self._all_processes, Iterable
        ):
            return False
        for iter_process in self._all_processes:
            if isinstance(iter_process, ServerThread):
                # Eli (12/17/20): skip the ServerThread because there is no clear way to mark the start up complete after launching flask.run()
                continue
            if not iter_process.is_start_up_complete():
                return False

        return True


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
