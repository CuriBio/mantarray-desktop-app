# -*- coding: utf-8 -*-
"""Collection of worker threads."""
from threading import Thread
from typing import Any
from typing import Optional
from typing import Union


class ErrorCatchingThread(Thread):
    """Catch errors to make available to caller thread."""

    def __init__(self, *args: Any, use_error_repr: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._use_error_repr = use_error_repr
        self.error: Optional[Union[str, Exception]] = None

    def run(self) -> None:
        try:
            super().run()
        except Exception as e:
            self.error = repr(e) if self._use_error_repr else e
