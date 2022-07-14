# -*- coding: utf-8 -*-
import platform


def is_cpu_arm() -> bool:  # pragma: no cover
    return "arm" in platform.platform().lower()
