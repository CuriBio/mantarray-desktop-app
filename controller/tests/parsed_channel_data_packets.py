# -*- coding: utf-8 -*-
from typing import Any
from typing import Dict

from mantarray_desktop_app import SERIAL_COMM_DEFAULT_DATA_CHANNEL
from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
import numpy as np

# TODO make these all immutable
SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0 = {
    "is_reference_sensor": False,
    "well_index": 0,
    "data": np.zeros((2, 100), dtype=np.int32),
}

# Default channel (currently Z-axis of sensor 0) and Z Axis of Sensor 2 from 24 wells.
SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS: Dict[Any, Any] = {
    "data_type": "magnetometer",
    "time_indices": np.zeros(100, dtype=np.uint64),
    "is_first_packet_of_stream": False,
}
for well_idx in range(24):
    channel_dict = {
        "time_offsets": np.zeros((2, 100), dtype=np.uint16),
        SERIAL_COMM_DEFAULT_DATA_CHANNEL: np.zeros(100, dtype=np.uint16),
        SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["C"]["Z"]: np.zeros(100, dtype=np.uint16),
    }
    SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS[well_idx] = channel_dict

SIMPLE_STIM_DATA_PACKET_FROM_ALL_WELLS: Dict[Any, Any] = {
    "data_type": "stimulation",
    "well_statuses": {well_idx: np.zeros((2, 5), dtype=np.uint64) for well_idx in range(24)},
    "is_first_packet_of_stream": False,
}
