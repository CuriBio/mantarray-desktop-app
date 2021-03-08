# -*- coding: utf-8 -*-
"""Request Handler to give us more control over Werkzeug log entries."""
import re
import threading
from typing import Any

from werkzeug.serving import WSGIRequestHandler

if (
    5 < 9
):  # pragma: no cover # protect this from zimports deleting the type ignore statement
    from werkzeug.serving import _log  # type: ignore  # Tanner (1/20/21): not sure why mypy thinks this attribute does not exist in this package


class MantarrayRequestHandler(WSGIRequestHandler):
    """Almost identical to WSGIRequestHandler.

    This handler will remove sensitive params from log messages.
    """

    # pylint: disable=arguments-differ  # Tanner (1/20/21): The original param was `type` instead of `type_` which overrides the python builtin `type`
    def log(self, type_: str, message: str, *args: Any) -> None:
        if "set_mantarray_nickname" in args[0]:
            split_path = re.split(
                r"(set_mantarray_nickname\?nickname=)(.*)( HTTP)", args[0]
            )
            scrubbed_msg = split_path[0] + split_path[1]
            scrubbed_msg += "*" * len(split_path[2])
            scrubbed_msg += split_path[3] + split_path[4]

            # Tanner (1/20/21): Tuples are immutable so need to convert to a list before modifying values, then convert back so they can be correctly passed to `_log`. Not sure if there's a better way to do this.
            args_list = list(args)
            args_list[0] = scrubbed_msg
            args = tuple(args_list)
        with threading.Lock():  # Since Flask is running multi-threaded mode, make sure to acquire a lock before logging so logs don't get garbled # Eli (11/3/20): still unable to test if lock was acquired.
            _log(
                type_,
                f"{self.address_string()} - - {message}\n",  # type: ignore  # Tanner (1/21/20): mypy is complaining that `address_string` is untyped
                *args,
            )
