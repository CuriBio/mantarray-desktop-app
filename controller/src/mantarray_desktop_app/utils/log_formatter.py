# -*- coding: utf-8 -*-
"""Custom Log Formatter."""
import logging
import re
from typing import Any

from .generic import get_redacted_string


class SensitiveFormatter(logging.Formatter):
    """Formatter that removes sensitive information in URLs.

    Based on https://stackoverflow.com/questions/48380452/mask-out-sensitive-information-in-python-log
    """

    @staticmethod
    def _filter(log_msg: str) -> Any:
        try:
            if "/set_mantarray_nickname" in log_msg:
                return re.sub(
                    r"(.*set_mantarray_nickname\?nickname=)(.*)( HTTP.*)",
                    lambda match_obj: match_obj[1] + get_redacted_string(len(match_obj[2])) + match_obj[3],
                    log_msg,
                )
            else:
                for route in ("/login", "/update_settings"):
                    if route in log_msg:
                        return re.sub(
                            rf"(.*{route}\?)(.*)( HTTP.*)",
                            lambda match_obj: match_obj[1] + get_redacted_string(4) + match_obj[3],
                            log_msg,
                        )
            return log_msg
        except Exception:
            return f"ERROR LOGGING MSG: {log_msg}"

    def format(self, record: logging.LogRecord) -> Any:
        original = logging.Formatter.format(self, record)
        return self._filter(original)
