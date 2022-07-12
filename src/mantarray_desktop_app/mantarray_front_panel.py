# -*- coding: utf-8 -*-
"""Classes used for controlling a Mantarray device."""
import struct

from .arch_utils import is_cpu_arm
from .constants import BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS
from .constants import BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS
from .constants import BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS
from .constants import BARCODE_SCANNER_TRIGGER_IN_ADDRESS
from .constants import CLEAR_BARCODE_TRIG_BIT
from .constants import FIRMWARE_VERSION_WIRE_OUT_ADDRESS
from .constants import START_BARCODE_SCAN_TRIG_BIT

try:
    from xem_wrapper import FrontPanel
    from xem_wrapper import FrontPanelBase
except ImportError:  # no sec  # pragma: no cover
    if not is_cpu_arm():
        raise

    class FrontPanelBase:  # type: ignore
        pass

    class FrontPanel(FrontPanelBase):  # type: ignore
        pass


class MantarrayFrontPanelMixIn:
    """Mix-in for Mantarray instruments using FrontPanel devices.

    Provides Mantarray specific functionality to a FrontPanelBase object.

    Classes that inherit from this should always also inherit from a FrontPanelBase subclass
    """

    def get_firmware_version(self) -> str:
        version_int = self.read_wire_out(FIRMWARE_VERSION_WIRE_OUT_ADDRESS)
        version_tuple = struct.unpack(">3B", struct.pack(">I", version_int)[1:])
        version_string = f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"
        return version_string

    def read_wire_out(self, ep_addr: int) -> int:
        # pylint: disable=no-self-use,unused-argument # Tanner (7/14/20): this method should never actually be used by child classes. They should use this method provided by the other parent class due to MRO.
        if isinstance(self, FrontPanelBase):
            raise NotImplementedError(
                "This implementation of read_wire_out should never be called by a FrontPanelBase object. Use a FrontPanelBase implementation instead"
            )
        return 0

    def activate_trigger_in(self, ep_addr: int, bit: int) -> None:
        # pylint: disable=no-self-use,unused-argument # Tanner (7/14/20): this method should never actually be used by child classes. They should use this method provided by the other parent class due to MRO.
        if isinstance(self, FrontPanelBase):
            raise NotImplementedError(
                "This implementation of activate_trigger_in should never be called by a FrontPanelBase object. Use a FrontPanelBase implementation instead"
            )

    def clear_barcode_scanner(self) -> None:
        self.activate_trigger_in(BARCODE_SCANNER_TRIGGER_IN_ADDRESS, CLEAR_BARCODE_TRIG_BIT)

    def start_barcode_scan(self) -> None:
        self.activate_trigger_in(BARCODE_SCANNER_TRIGGER_IN_ADDRESS, START_BARCODE_SCAN_TRIG_BIT)

    def get_barcode(self) -> str:
        """Convert 3 32-bit wire out values to a barcode string."""
        barcode_str = ""
        barcode_words = [
            self.read_wire_out(BARCODE_SCANNER_TOP_WIRE_OUT_ADDRESS),
            self.read_wire_out(BARCODE_SCANNER_MID_WIRE_OUT_ADDRESS),
            self.read_wire_out(BARCODE_SCANNER_BOTTOM_WIRE_OUT_ADDRESS),
        ]
        for word in barcode_words:
            barcode_str += struct.unpack("<4s", struct.pack(">I", word))[0].decode("utf-8")
        return barcode_str


class MantarrayFrontPanel(FrontPanel, MantarrayFrontPanelMixIn):
    pass
