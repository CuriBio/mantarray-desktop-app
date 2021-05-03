# -*- coding: utf-8 -*-
import csv
import os

from mantarray_desktop_app import MICROSECONDS_PER_CENTIMILLISECOND
from mantarray_file_manager import CENTIMILLISECONDS_PER_SECOND
import numpy as np
from scipy import interpolate
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import resource_path

from ..fixtures import fixture_patch_print
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator
from ..fixtures_mc_simulator import fixture_mantarray_mc_simulator_no_beacon
from ..fixtures_mc_simulator import fixture_runnable_mantarray_mc_simulator


__fixtures__ = [
    fixture_runnable_mantarray_mc_simulator,
    fixture_mantarray_mc_simulator,
    fixture_patch_print,
    fixture_mantarray_mc_simulator_no_beacon,
]


def test_MantarrayMcSimulator__get_interpolated_data_returns_correct_value(
    mantarray_mc_simulator,
):
    simulator = mantarray_mc_simulator["simulator"]

    test_sampling_period = 1000
    actual_data = simulator.get_interpolated_data(test_sampling_period)

    relative_path = os.path.join("src", "simulated_data", "simulated_twitch.csv")
    absolute_path = os.path.normcase(
        os.path.join(get_current_file_abs_directory(), os.pardir, os.pardir)
    )
    file_path = resource_path(relative_path, base_path=absolute_path)
    with open(file_path, newline="") as csvfile:
        simulated_data_timepoints = next(csv.reader(csvfile, delimiter=","))
        simulated_data_values = next(csv.reader(csvfile, delimiter=","))
    expected_data = interpolate.interp1d(
        np.array(simulated_data_timepoints, dtype=np.int64)
        // MICROSECONDS_PER_CENTIMILLISECOND,
        simulated_data_values,
    )(
        np.arange(
            0,
            CENTIMILLISECONDS_PER_SECOND,
            test_sampling_period // MICROSECONDS_PER_CENTIMILLISECOND,
            dtype=np.int64,
        )
    )

    np.testing.assert_array_equal(actual_data, expected_data)
