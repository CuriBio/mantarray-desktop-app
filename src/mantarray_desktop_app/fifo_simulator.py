# -*- coding: utf-8 -*-
"""FIFO Simulator."""
from __future__ import annotations

import queue
from queue import Queue
import threading
from typing import Any
from typing import Dict
from typing import Optional

from xem_wrapper import DATA_FRAME_SIZE_WORDS
from xem_wrapper import DATA_FRAMES_PER_ROUND_ROBIN
from xem_wrapper import FrontPanelBase
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import OpalKellyBoardNotInitializedError

from .constants import FIFO_READ_PRODUCER_CYCLES_PER_ITERATION
from .constants import FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
from .constants import FIRMWARE_VERSION_WIRE_OUT_ADDRESS
from .exceptions import AttemptToAddCyclesWhileSPIRunningError
from .exceptions import AttemptToInitializeFIFOReadsError
from .fifo_read_producer import FIFOReadProducer
from .fifo_read_producer import produce_data
from .mantarray_front_panel import MantarrayFrontPanelMixIn


class RunningFIFOSimulator(FrontPanelSimulator, MantarrayFrontPanelMixIn):
    """Simulate a running Mantarray machine.

    Args:
        simulated_response_queues: dictionary where the ultimate leaves should be multiprocessing_utils.SimpleMultiprocessingQueue objects. These values are popped off the end of the queue and returned as if coming from the XEM. The 'wire_outs' key should contain a sub-dict with keys of integer values representing the ep addresses.
    """

    default_device_id = "M02001900Mantarray Simulator"
    default_mantarray_serial_number = "M02001900"
    default_mantarray_nickname = "Mantarray Simulator"
    default_firmware_version = "0.0.0"

    def __init__(
        self, simulated_response_queues: Optional[Dict[str, Any]] = None
    ) -> None:
        if simulated_response_queues is None:
            simulated_response_queues = {}
        if "pipe_outs" in simulated_response_queues:
            raise AttemptToInitializeFIFOReadsError()
        super().__init__(simulated_response_queues)
        self._device_id = self.default_device_id
        self._fifo_read_producer: Optional[FIFOReadProducer] = None
        self._producer_error_queue: Optional[
            Queue[str]  # pylint: disable=unsubscriptable-object
        ] = None
        self._producer_data_queue: Optional[
            Queue[bytearray]  # pylint: disable=unsubscriptable-object
        ] = None
        self._lock: Optional[threading.Lock] = None

    def initialize_board(
        self,
        bit_file_name: Optional[str] = None,
        allow_board_reinitialization: bool = False,
    ) -> None:
        board_already_initialized = self.is_board_initialized()

        super().initialize_board(
            bit_file_name=bit_file_name,
            allow_board_reinitialization=allow_board_reinitialization,
        )
        if not board_already_initialized:
            self._producer_error_queue = queue.Queue()
            self._producer_data_queue = queue.Queue()
            self._lock = threading.Lock()

    def start_acquisition(self) -> None:
        super().start_acquisition()
        if self._producer_data_queue is None:
            raise NotImplementedError("_producer_data_queue should never be None here")
        if self._producer_error_queue is None:
            raise NotImplementedError("_producer_error_queue should never be None here")
        if self._lock is None:
            raise NotImplementedError("_lock should never be None here")
        self._fifo_read_producer = FIFOReadProducer(
            self._producer_data_queue, self._producer_error_queue, self._lock
        )
        self._fifo_read_producer.start()

    def stop_acquisition(self) -> None:
        super().stop_acquisition()
        if self._fifo_read_producer is None:
            raise NotImplementedError("_fifo_read_producer should never be None here")
        if self._producer_data_queue is None:
            raise NotImplementedError("_producer_data_queue should never be None here")
        if self._lock is None:
            raise NotImplementedError("_lock should never be None here")
        self._fifo_read_producer.soft_stop()
        is_producer_stopped = False
        while not is_producer_stopped:
            is_producer_stopped = self._fifo_read_producer.is_stopped()

        with self._lock:
            while not self._producer_data_queue.empty():
                self._producer_data_queue.get_nowait()
        self._fifo_read_producer.join()
        self._fifo_read_producer = None

    def read_wire_out(self, ep_addr: int) -> int:
        FrontPanelBase.read_wire_out(self, ep_addr)
        wire_outs = self._simulated_response_queues.get("wire_outs", None)
        if wire_outs is None:
            return FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
        wire_out_queue = wire_outs.get(ep_addr, None)
        if wire_out_queue is None:
            return FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
        if wire_out_queue.empty():
            return FIFO_SIMULATOR_DEFAULT_WIRE_OUT_VALUE
        wire_out_val: int = wire_out_queue.get_nowait()
        return wire_out_val

    def read_from_fifo(self) -> bytearray:
        if self._producer_data_queue is None:
            raise NotImplementedError("_producer_data_queue should never be None here")
        if self._lock is None:
            raise NotImplementedError("_lock should never be None here")
        # Tanner (3/12/20) is not sure how to test that we are using a lock here. The purpose of this lock is to ensure that data is not pulled from the queue at the same time it is being added.
        with self._lock:
            data_read = bytearray(0)
            while not self._producer_data_queue.empty():
                data_read.extend(self._producer_data_queue.get_nowait())
            return data_read

    def get_num_words_fifo(self) -> int:
        FrontPanelBase.get_num_words_fifo(self)
        if self._producer_data_queue is None:
            raise NotImplementedError("_producer_data_queue should never be None here")
        if self._lock is None:
            raise NotImplementedError("_lock should never be None here")
        num_words = 0
        temp_queue: Queue[  # pylint: disable=unsubscriptable-object
            bytearray
        ] = queue.Queue()
        # Tanner (3/12/20) is not sure how to test that we are using a lock here. The purpose of this lock is to ensure that data is not pulled from the queue at the same time it is being added.
        with self._lock:
            while not self._producer_data_queue.empty():
                num_words += (
                    DATA_FRAME_SIZE_WORDS
                    * DATA_FRAMES_PER_ROUND_ROBIN
                    * FIFO_READ_PRODUCER_CYCLES_PER_ITERATION
                )
                temp_queue.put(self._producer_data_queue.get_nowait())
            while not temp_queue.empty():
                self._producer_data_queue.put(temp_queue.get_nowait())
        return num_words

    def add_data_cycles(self, num_cycles: int) -> None:
        if not self._is_board_initialized:
            raise OpalKellyBoardNotInitializedError()
        if self.is_spi_running():
            raise AttemptToAddCyclesWhileSPIRunningError()
        if self._producer_data_queue is None:
            raise NotImplementedError("_producer_data_queue should never be None here")

        data = produce_data(num_cycles, 0)
        self._producer_data_queue.put(data)

    def get_firmware_version(self) -> str:
        FrontPanelBase.read_wire_out(self, FIRMWARE_VERSION_WIRE_OUT_ADDRESS)
        return self.default_firmware_version
