# -*- coding: utf-8 -*-
"""Collection of worker threads."""
from threading import Thread
from typing import Any
from typing import Optional


class ErrorCatchingThread(Thread):
    """Catch errors to make available to caller thread."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.error: Optional[str] = None

    def run(self) -> None:
        try:
            super().run()
        except Exception as e:  # pylint: disable=broad-except  # Tanner (10/8/21): deliberately trying to catch all exceptions here
            self.error = repr(e)
