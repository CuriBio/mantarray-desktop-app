# -*- coding: utf-8 -*-
"""Classes used for controlling a Mantarray device."""
import struct

from xem_wrapper import FrontPanel
from xem_wrapper import FrontPanelBase

from .constants import FIRMWARE_VERSION_WIRE_OUT_ADDRESS


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


class MantarrayFrontPanel(FrontPanel, MantarrayFrontPanelMixIn):
    pass
