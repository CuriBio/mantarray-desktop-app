# -*- coding: utf-8 -*-
"""Thread safe, dict-like object."""

import re
from typing import Dict, Any
import threading, copy

class SharedValues():
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values = dict()

    def __getitem__(self, key) -> Any:
        with self._lock:
            return self._values[key]

    def __setitem__(self, key, val) -> None:
        with self._lock:
            self._values[key] = val

    def __contains__(self, key) -> bool:
        return key in self._values
    
    def get(self, key, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def deepcopy(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._values)
