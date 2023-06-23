# -*- coding: utf-8 -*-
"""Thread safe, dict-like object."""

import copy
import threading
from typing import Any
from typing import Dict


class SharedValues:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Dict[str, Any] = dict()

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._values[key]

    def __setitem__(self, key: str, val: Any) -> None:
        with self._lock:
            self._values[key] = val

    def __contains__(self, key: str) -> bool:
        return key in self._values

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def deepcopy(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._values)
