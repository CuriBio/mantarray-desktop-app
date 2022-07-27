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
from .shared_values import SharedValues
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
        values_to_share_to_server: SharedValues,
        logging_level: int = logging.INFO,
    ) -> None:
        self._logging_level = logging_level
        self._all_processes: Optional[Dict[str, InfiniteProcess]] = None
        self._subprocesses_started: bool = False

        self.values_to_share_to_server = values_to_share_to_server

        self.queue_container: MantarrayQueueContainer
        self.server_manager: ServerManager
        self.instrument_comm_process: InstrumentCommProcess
        self.file_writer_process: FileWriterProcess
        self.data_analyzer_process: DataAnalyzerProcess

    def get_logging_level(self) -> int:
        return self._logging_level

    def create_processes(self) -> None:
        """Create/init the processes."""
        self.queue_container = MantarrayQueueContainer()
        beta_2_mode = self.values_to_share_to_server["beta_2_mode"]

        self.server_manager = ServerManager(
            self.queue_container.from_server,
            self.queue_container,
            logging_level=self._logging_level,
            values_from_process_monitor=self.values_to_share_to_server,
            port=self.values_to_share_to_server.get("server_port_number", DEFAULT_SERVER_PORT_NUMBER),
        )

        instrument_comm_process = OkCommunicationProcess if not beta_2_mode else McCommunicationProcess
        self.instrument_comm_process = instrument_comm_process(
            self.queue_container.instrument_comm_boards,
            self.queue_container.instrument_comm_error,
            logging_level=self._logging_level,
        )

        self.file_writer_process = FileWriterProcess(
            self.queue_container.file_writer_boards,
            self.queue_container.to_file_writer,
            self.queue_container.from_file_writer,
            self.queue_container.file_writer_error,
            file_directory=self.values_to_share_to_server["config_settings"]["recording_directory"],
            logging_level=self._logging_level,
            beta_2_mode=beta_2_mode,
        )

        self.data_analyzer_process = DataAnalyzerProcess(
            self.queue_container.data_analyzer_boards,
            self.queue_container.to_data_analyzer,
            self.queue_container.from_data_analyzer,
            self.queue_container.data_analyzer_error,
            mag_analysis_output_dir=self.values_to_share_to_server["config_settings"][
                "mag_analysis_output_dir"
            ],
            logging_level=self._logging_level,
            beta_2_mode=beta_2_mode,
        )

        self._all_processes = {
            "Instrument Comm": self.instrument_comm_process,
            "File Writer": self.file_writer_process,
            "Data Analyzer": self.data_analyzer_process,
        }

    def start_processes(self) -> Dict[str, int]:
        if self._all_processes is None:
            raise NotImplementedError("Processes must be created first.")
        for iter_process in self._all_processes.values():
            iter_process.start()
        self._subprocesses_started = True
        return {
            "Instrument Comm": self.instrument_comm_process.pid,
            "File Writer": self.file_writer_process.pid,
            "Data Analyzer": self.data_analyzer_process.pid,
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
        to_instrument_comm_queue = self.queue_container.to_instrument_comm(0)

        self.values_to_share_to_server["system_status"] = INSTRUMENT_INITIALIZING_STATE
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

        self.server_manager.shutdown_server()

    def soft_stop_processes(self) -> None:
        if self._all_processes is None:
            raise NotImplementedError("Processes must be created first.")
        for iter_process in self._all_processes.values():
            iter_process.soft_stop()
        self.server_manager.shutdown_server()

    def hard_stop_processes(self, shutdown_server: bool = True) -> Dict[str, Any]:
        """Immediately stop subprocesses."""
        logger.info("Hard stopping Instrument Comm Process")
        instrument_comm_items = self.instrument_comm_process.hard_stop()
        logger.info("Hard stopping File Writer Process")
        file_writer_items = self.file_writer_process.hard_stop()
        logger.info("Hard stopping Data Analyzer Process")
        data_analyzer_items = self.data_analyzer_process.hard_stop()
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
        server_manager = self.server_manager
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
