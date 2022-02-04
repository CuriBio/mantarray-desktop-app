# -*- coding: utf-8 -*-
"""Collection of worker threads."""
from threading import Thread
from typing import Any
from typing import Optional


class ErrorCatchingThread(Thread):
    """Catch errors to make available to caller thread."""

    def __init__(self, target: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.error: Optional[Exception] = None
        self._target: Any = target
        self._args: Optional[Any]
        self._kwargs: Optional[Any]

    def run(self) -> None:
        if self._target is not None:
            try:
                super().run()
            except Exception as e:  # pylint: disable=broad-except  # Tanner (10/8/21): deliberately trying to catch all exceptions here
                self.error = e

    # for testing
    def errors(self) -> bool:
        return self.error is not None

    def get_error(self) -> Any:
        if self.error is not None:  # for testing
            # Lucy (11/8/21) prevents error when sending status to main queue by making exception a string
            return getattr(self.error, "message", str(self.error))
        return self.error
