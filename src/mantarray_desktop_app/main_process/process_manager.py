# -*- coding: utf-8 -*-
"""Managing subprocesses."""
from __future__ import annotations

import copy
import logging
from time import perf_counter
from time import sleep
from typing import Any
from typing import Dict
from typing import Optional
from typing import Union

from stdlib_utils import InfiniteProcess

from .queue_container import MantarrayQueueContainer
from .server import ServerManager
from ..constants import DEFAULT_SERVER_PORT_NUMBER
from ..constants import INSTRUMENT_INITIALIZING_STATE
from ..constants import SUBPROCESS_JOIN_TIMEOUT_SECONDS
from ..constants import SUBPROCESS_POLL_DELAY_SECONDS
from ..constants import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
from ..sub_processes.data_analyzer import DataAnalyzerProcess
from ..sub_processes.file_writer import FileWriterProcess
from ..sub_processes.instrument_comm import InstrumentCommProcess
from ..sub_processes.mc_comm import McCommunicationProcess
from ..sub_processes.ok_comm import OkCommunicationProcess
from ..utils.firmware_manager import get_latest_firmware

logger = logging.getLogger(__name__)


def _process_can_be_joined(process: InfiniteProcess) -> bool:
    return process.ident is not None


def _process_failed_to_join(process: InfiniteProcess) -> bool:
    return process.exitcode is None


class MantarrayProcessesManager:  # pylint: disable=too-many-public-methods
    """Controls access to all the subprocesses."""

    def __init__(
        self,
        values_to_share_to_server: Dict[str, Any],
        logging_level: int = logging.INFO,
    ) -> None:
        self._queue_container: MantarrayQueueContainer

        self._logging_level = logging_level

        self._values_to_share_to_server = values_to_share_to_server
        self._server_manager: ServerManager

        self._instrument_communication_process: InstrumentCommProcess
        self._file_writer_process: FileWriterProcess
        self._data_analyzer_process: DataAnalyzerProcess

        self._all_processes: Optional[Dict[str, InfiniteProcess]] = None
        self._subprocesses_started: bool = False

    def get_values_to_share_to_server(self) -> Dict[str, Any]:
        return self._values_to_share_to_server

    def queue_container(self) -> MantarrayQueueContainer:
        return self._queue_container

    def get_logging_level(self) -> int:
        return self._logging_level

    def get_instrument_process(self) -> InstrumentCommProcess:
        return self._instrument_communication_process

    def get_file_writer_process(self) -> FileWriterProcess:
        return self._file_writer_process

    def get_server_manager(self) -> ServerManager:
        return self._server_manager

    def get_data_analyzer_process(self) -> DataAnalyzerProcess:
        return self._data_analyzer_process

    def create_processes(self) -> None:
        """Create/init the processes."""
        queue_container = MantarrayQueueContainer()
        self._queue_container = queue_container
        beta_2_mode = self._values_to_share_to_server["beta_2_mode"]

        self._server_manager = ServerManager(
            queue_container.get_communication_queue_from_server_to_main(),
            queue_container,
            logging_level=self._logging_level,
            values_from_process_monitor=self._values_to_share_to_server,
            port=self._values_to_share_to_server.get("server_port_number", DEFAULT_SERVER_PORT_NUMBER),
        )

        instrument_comm_process = OkCommunicationProcess if not beta_2_mode else McCommunicationProcess
        self._instrument_communication_process = instrument_comm_process(
            queue_container.get_instrument_comm_board_queues(),
            queue_container.get_instrument_communication_error_queue(),
            logging_level=self._logging_level,
        )

        self._file_writer_process = FileWriterProcess(
            queue_container.get_file_writer_board_queues(),
            queue_container.get_communication_queue_from_main_to_file_writer(),
            queue_container.get_communication_queue_from_file_writer_to_main(),
            queue_container.get_file_writer_error_queue(),
            file_directory=self._values_to_share_to_server["config_settings"]["recording_directory"],
            logging_level=self._logging_level,
            beta_2_mode=beta_2_mode,
        )

        self._data_analyzer_process = DataAnalyzerProcess(
            queue_container.get_data_analyzer_board_queues(),
            queue_container.get_communication_queue_from_main_to_data_analyzer(),
            queue_container.get_communication_queue_from_data_analyzer_to_main(),
            queue_container.get_data_analyzer_error_queue(),
            mag_analysis_output_dir=self._values_to_share_to_server["config_settings"][
                "mag_analysis_output_dir"
            ],
            logging_level=self._logging_level,
            beta_2_mode=beta_2_mode,
        )

        self._all_processes = {
            "Instrument Comm": self._instrument_communication_process,
            "File Writer": self._file_writer_process,
            "Data Analyzer": self._data_analyzer_process,
        }

    def start_processes(self) -> Dict[str, int]:
        if self._all_processes is None:
            raise NotImplementedError("Processes must be created first.")
        for iter_process in self._all_processes.values():
            iter_process.start()
        self._subprocesses_started = True
        return {
            "Instrument Comm": self._instrument_communication_process.pid,
            "File Writer": self._file_writer_process.pid,
            "Data Analyzer": self._data_analyzer_process.pid,
        }

    def spawn_processes(self) -> None:
        """Create and start processes, no extra args."""
        self.create_processes()
        self.start_processes()

    def boot_up_instrument(self, load_firmware_file: bool = True) -> Dict[str, Any]:
        """Boot up a Mantarray Beta 1 instrument.

        It is assumed that 'bit_file_name' will be a path to a real .bit
        firmware file whose name follows the format:
        'mantarray_#_#_#.bit'
        """
        bit_file_name = None
        if load_firmware_file:
            bit_file_name = get_latest_firmware()
        to_instrument_comm_queue = self.queue_container().get_communication_to_instrument_comm_queue(0)

        self._values_to_share_to_server["system_status"] = INSTRUMENT_INITIALIZING_STATE
        boot_up_dict = {
            "communication_type": "boot_up_instrument",
            "command": "initialize_board",
            "bit_file_name": bit_file_name,
            "suppress_error": False,
            "allow_board_reinitialization": False,
        }
        to_instrument_comm_queue.put_nowait(boot_up_dict)

        start_up_dict = {"communication_type": "xem_scripts", "script_type": "start_up"}
        to_instrument_comm_queue.put_nowait(start_up_dict)

        response_dict = {
            "boot_up_instrument": copy.deepcopy(boot_up_dict),
            "start_up": copy.deepcopy(start_up_dict),
        }
        return response_dict

    def stop_processes(self) -> None:
        if self._all_processes is None:
            raise NotImplementedError("Processes must be created first.")
        for iter_process in self._all_processes.values():
            iter_process.stop()

        self.get_server_manager().shutdown_server()

    def soft_stop_processes(self) -> None:
        if self._all_processes is None:
            raise NotImplementedError("Processes must be created first.")
        for iter_process in self._all_processes.values():
            iter_process.soft_stop()
        self.get_server_manager().shutdown_server()

    def hard_stop_processes(self, shutdown_server: bool = True) -> Dict[str, Any]:
        """Immediately stop subprocesses."""
        logger.info("Hard stopping Instrument Comm Process")
        instrument_comm_items = self._instrument_communication_process.hard_stop()
        logger.info("Hard stopping File Writer Process")
        file_writer_items = self._file_writer_process.hard_stop()
        logger.info("Hard stopping Data Analyzer Process")
        data_analyzer_items = self._data_analyzer_process.hard_stop()
        logger.info("All subprocesses hard stopped")
        process_items = {
            "instrument_comm_items": instrument_comm_items,
            "file_writer_items": file_writer_items,
            "data_analyzer_items": data_analyzer_items,
        }

        if shutdown_server:
            process_items.update(self.shutdown_server())

        return process_items

    def join_processes(self) -> None:
        if self._all_processes is None:
            raise NotImplementedError("Processes must be created first.")
        for process_name, iter_process in self._all_processes.items():
            if _process_can_be_joined(iter_process):
                logger.info(f"Joining {process_name} Process")
                iter_process.join(SUBPROCESS_JOIN_TIMEOUT_SECONDS)
                if _process_failed_to_join(iter_process):
                    logger.error(f"Terminating {process_name} Process after unsuccessful join")
                    iter_process.terminate()
        logger.info("All subprocesses joined")

    def soft_stop_and_join_processes(self) -> None:
        self.soft_stop_processes()
        self.join_processes()

    def stop_and_join_processes(self) -> None:
        self.stop_processes()
        self.join_processes()

    def hard_stop_and_join_processes(self, shutdown_server: bool = True) -> Dict[str, Any]:
        """Hard stop all processes and return contents of their queues."""
        process_items = self.hard_stop_processes(shutdown_server=False)
        self.join_processes()

        if shutdown_server:
            process_items.update(self.shutdown_server())

        return process_items

    def shutdown_server(self) -> Dict[str, Any]:
        logger.info("Shutting down server")
        server_manager = self.get_server_manager()
        server_manager.shutdown_server()
        return {"server_items": server_manager.drain_all_queues()}

    def are_processes_stopped(
        self,
        timeout_seconds: Union[float, int] = SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS,
        sleep_between_checks: bool = True,
    ) -> bool:
        """Check if processes are stopped."""
        start = perf_counter()
        if self._all_processes is None:
            raise NotImplementedError("Processes must be created first.")

        processes = self._all_processes.values()
        while not (are_stopped := all(p.is_stopped() for p in processes)):
            if sleep_between_checks:
                sleep(SUBPROCESS_POLL_DELAY_SECONDS)
            elapsed_time = perf_counter() - start
            if elapsed_time >= timeout_seconds:
                break
        return are_stopped

    def are_subprocess_start_ups_complete(self) -> bool:
        """Check if all subprocesses' start-up events have been set.

        Often useful in unit-testing or other places where the processes
        should be fully running before attempting the next command.
        """
        if self._all_processes is None:
            return False
        for iter_process in self._all_processes.values():
            if not iter_process.is_start_up_complete():
                return False

        return True

    def get_subprocesses_running_status(self) -> bool:
        if not self._subprocesses_started:
            return False

        return not self.are_processes_stopped(timeout_seconds=0, sleep_between_checks=False)
