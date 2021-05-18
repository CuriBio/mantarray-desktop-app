# -*- coding: utf-8 -*-
from typing import Any
from typing import Dict

from mantarray_desktop_app import SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE
import numpy as np

SIMPLE_BETA_1_CONSTRUCT_DATA_FROM_WELL_0 = {
    "is_reference_sensor": False,
    "well_index": 0,
    "data": np.zeros((2, 100), dtype=np.int32),
}

# X Axis of Sensor A from 24 wells
SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS: Dict[Any, Any] = {"timestamps": np.zeros((2, 100), np.uint64)}
for well_idx in range(24):
    channel_dict = {SERIAL_COMM_SENSOR_AXIS_LOOKUP_TABLE["A"]["X"]: np.zeros((2, 100), np.uint64)}
    SIMPLE_BETA_2_CONSTRUCT_DATA_FROM_ALL_WELLS[well_idx] = channel_dict
