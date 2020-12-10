# -*- coding: utf-8 -*-
from mantarray_desktop_app import FIRMWARE_VERSION_WIRE_OUT_ADDRESS
from mantarray_desktop_app import MantarrayFrontPanel
from mantarray_desktop_app import MantarrayFrontPanelMixIn
import pytest
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import okCFrontPanel
from xem_wrapper import OpalKellyBoardNotInitializedError


def test_MantarrayFrontPanelMixIn__get_firmware_version_calls_read_wire_out(mocker):
    mantarray_mixin = MantarrayFrontPanelMixIn()

    expected_value = "3.2.1"
    mocked_read_wire = mocker.patch.object(
        mantarray_mixin,
        "read_wire_out",
        autospec=True,
        return_value=0x04030201,
    )

    actual = mantarray_mixin.get_firmware_version()
    assert actual == expected_value

    mocked_read_wire.assert_called_once_with(FIRMWARE_VERSION_WIRE_OUT_ADDRESS)


def test_MantarrayFrontPanelMixIn__read_wire_out_returns_0(mocker):
    expected_value = 0
    mantarray_mixin = MantarrayFrontPanelMixIn()
    actual = mantarray_mixin.read_wire_out(0x00)
    assert actual == expected_value
    actual = mantarray_mixin.read_wire_out(0x0F)
    assert actual == expected_value
    actual = mantarray_mixin.read_wire_out(0xFF)
    assert actual == expected_value


def test_MantarrayFrontPanel__get_firmware_version_raises_error_if_board_not_initialized(
    mocker,
):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)
    with pytest.raises(OpalKellyBoardNotInitializedError):
        mantarray_fp.get_firmware_version()


def test_MantarrayFrontPanel__read_wire_out_raises_correct_error_if_board_not_initialized(
    mocker,
):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)
    with pytest.raises(OpalKellyBoardNotInitializedError):
        mantarray_fp.read_wire_out(0x00)


def test_MantarrayFrontPanel__get_firmware_version_returns_expected_value_from_correct_xem_GetWireOutValue_address(
    mocker,
):
    dummy_xem = okCFrontPanel()

    expected_value = "0.1.2"
    mocked_get_wire = mocker.patch.object(
        dummy_xem,
        "GetWireOutValue",
        autospec=True,
        return_value=0x00000102,
    )
    mocker.patch.object(
        dummy_xem, "IsFrontPanelEnabled", autospec=True, return_value=True
    )
    mocker.patch.object(dummy_xem, "UpdateWireOuts", autospec=True, return_value=True)

    mantarray_fp = MantarrayFrontPanel(dummy_xem)
    mantarray_fp.initialize_board()
    actual = mantarray_fp.get_firmware_version()
    assert actual == expected_value

    mocked_get_wire.assert_called_once_with(FIRMWARE_VERSION_WIRE_OUT_ADDRESS)


class BadFrontPanel(MantarrayFrontPanelMixIn, FrontPanelSimulator):
    pass


def test_MantarrayFrontPanelMixIn__read_wire_out_raises_error_when_called_by_FrontPanelBase_subclass():
    fp = BadFrontPanel({})
    with pytest.raises(
        NotImplementedError,
        match="This implementation of read_wire_out should never be called by a FrontPanelBase object. Use a FrontPanelBase implementation instead",
    ):
        fp.read_wire_out(0x00)
