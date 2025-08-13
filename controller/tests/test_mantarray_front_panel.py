# -*- coding: utf-8 -*-
from mantarray_desktop_app import BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS
from mantarray_desktop_app import BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS
from mantarray_desktop_app import BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS
from mantarray_desktop_app import BARCODE_SCANNER_TRIGGER_IN_ADDRESS
from mantarray_desktop_app import CLEAR_BARCODE_TRIG_BIT
from mantarray_desktop_app import CLEARED_BARCODE_VALUE
from mantarray_desktop_app import FIRMWARE_VERSION_WIRE_OUT_ADDRESS
from mantarray_desktop_app import MantarrayFrontPanel
from mantarray_desktop_app import MantarrayFrontPanelMixIn
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import START_BARCODE_SCAN_TRIG_BIT
import pytest
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import okCFrontPanel
from xem_wrapper import OpalKellyBoardNotInitializedError


def test_MantarrayFrontPanelMixIn__get_firmware_version_calls_read_wire_out_correctly__and_formats_value_correctly(
    mocker,
):
    mantarray_mixin = MantarrayFrontPanelMixIn()

    expected_value = "3.2.1"
    mocked_read_wire = mocker.patch.object(
        mantarray_mixin, "read_wire_out", autospec=True, return_value=0x04030201
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


def test_MantarrayFrontPanel__get_firmware_version_raises_error_if_board_not_initialized(mocker):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)
    with pytest.raises(OpalKellyBoardNotInitializedError):
        mantarray_fp.get_firmware_version()


def test_MantarrayFrontPanel__read_wire_out_raises_correct_error_if_board_not_initialized(mocker):
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
        dummy_xem, "GetWireOutValue", autospec=True, return_value=0x00000102
    )
    mocker.patch.object(dummy_xem, "IsFrontPanelEnabled", autospec=True, return_value=True)
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


def test_MantarrayFrontPanelMixIn__activate_trigger_in_raises_error_when_called_by_FrontPanelBase_subclass():
    fp = BadFrontPanel({})
    with pytest.raises(
        NotImplementedError,
        match="This implementation of activate_trigger_in should never be called by a FrontPanelBase object. Use a FrontPanelBase implementation instead",
    ):
        fp.activate_trigger_in(0x00, 0)


def test_MantarrayFrontPanel__clear_barcode_scanner__raises_error_if_board_not_initialized(mocker):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)
    with pytest.raises(OpalKellyBoardNotInitializedError):
        mantarray_fp.clear_barcode_scanner()


def test_MantarrayFrontPanel__clear_barcode_scanner__calls_activate_trigger_in_correctly(mocker):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)
    mocked_ati = mocker.patch.object(dummy_xem, "ActivateTriggerIn", autospec=True, return_value=0)
    mocker.patch.object(dummy_xem, "IsFrontPanelEnabled", autospec=True, return_value=True)

    mantarray_fp.initialize_board()
    mantarray_fp.clear_barcode_scanner()

    mocked_ati.assert_called_once_with(BARCODE_SCANNER_TRIGGER_IN_ADDRESS, CLEAR_BARCODE_TRIG_BIT)


def test_MantarrayFrontPanel__get_barcode__raises_error_if_board_not_initialized(mocker):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)
    with pytest.raises(OpalKellyBoardNotInitializedError):
        mantarray_fp.get_barcode()


def test_MantarrayFrontPanel__get_barcode__calls_read_wire_out_correctly__and_returns_correct_value(mocker):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)

    expected_barcode = RunningFIFOSimulator.default_barcode

    def get_wire_out_se(ep_addr):
        if ep_addr == BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS:
            return 0x4D4C3232
        if ep_addr == BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS:
            return 0x30303130
        if ep_addr == BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS:
            return 0x30302D31
        return 0

    mocked_get_wire = mocker.patch.object(
        dummy_xem, "GetWireOutValue", autospec=True, side_effect=get_wire_out_se
    )
    mocker.patch.object(dummy_xem, "IsFrontPanelEnabled", autospec=True, return_value=True)
    mocker.patch.object(dummy_xem, "UpdateWireOuts", autospec=True, return_value=True)

    mantarray_fp.initialize_board()
    actual = mantarray_fp.get_barcode()
    assert actual == expected_barcode

    mocked_get_wire.assert_any_call(BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS)
    mocked_get_wire.assert_any_call(BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS)
    mocked_get_wire.assert_any_call(BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS)


def test_MantarrayFrontPanel__get_barcode_returns_cleared_value_correctly(mocker):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)

    expected_barcode = CLEARED_BARCODE_VALUE

    def get_wire_out_se(ep_addr):
        return 0

    mocker.patch.object(dummy_xem, "GetWireOutValue", autospec=True, side_effect=get_wire_out_se)
    mocker.patch.object(dummy_xem, "IsFrontPanelEnabled", autospec=True, return_value=True)
    mocker.patch.object(dummy_xem, "UpdateWireOuts", autospec=True, return_value=True)

    mantarray_fp.initialize_board()
    actual = mantarray_fp.get_barcode()
    assert actual == expected_barcode


def test_MantarrayFrontPanel__start_barcode_scan__raises_error_if_board_not_initialized(mocker):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)
    with pytest.raises(OpalKellyBoardNotInitializedError):
        mantarray_fp.start_barcode_scan()


def test_MantarrayFrontPanel__start_barcode_scan__calls_activate_trigger_in_correctly(mocker):
    dummy_xem = okCFrontPanel()
    mantarray_fp = MantarrayFrontPanel(dummy_xem)
    mocked_ati = mocker.patch.object(dummy_xem, "ActivateTriggerIn", autospec=True, return_value=0)
    mocker.patch.object(dummy_xem, "IsFrontPanelEnabled", autospec=True, return_value=True)

    mantarray_fp.initialize_board()
    mantarray_fp.start_barcode_scan()

    mocked_ati.assert_called_once_with(BARCODE_SCANNER_TRIGGER_IN_ADDRESS, START_BARCODE_SCAN_TRIG_BIT)
