# -*- coding: utf-8 -*-
from typing import List
from typing import Union

from mantarray_desktop_app import MantarrayFrontPanelMixIn
from mantarray_desktop_app.utils.mantarray_front_panel import FrontPanelBase
import pytest


class TestBarcodeSimulator(FrontPanelBase, MantarrayFrontPanelMixIn):
    pass


@pytest.fixture(scope="function", name="test_barcode_simulator")
def fixture_test_barcode_simulator(mocker):

    simulator = TestBarcodeSimulator()
    simulator.initialize_board()

    def _foo(barcode_values: Union[None, List[str], str] = None):
        mocked_get = None
        if isinstance(barcode_values, list):
            mocked_get = mocker.patch.object(
                simulator, "get_barcode", autospec=True, side_effect=barcode_values
            )
        elif isinstance(barcode_values, str):
            mocked_get = mocker.patch.object(
                simulator, "get_barcode", autospec=True, return_value=barcode_values
            )

        return simulator, mocked_get

    yield _foo
