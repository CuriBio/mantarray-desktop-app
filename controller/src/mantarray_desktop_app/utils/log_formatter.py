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
        if "/system_status" in log_msg and re.search(r"HTTP\S* 200 ", log_msg):
            return None
        elif "/set_mantarray_nickname" in log_msg:
            return re.sub(
                r"(.*set_mantarray_nickname\?nickname=)(.*)( HTTP.*)",
                lambda match_obj: match_obj[1] + get_redacted_string(len(match_obj[2])) + match_obj[3],
                log_msg,
            )
        elif "/login" in log_msg:
            return re.sub(
                r"(.*login\?)(.*)( HTTP.*)",
                lambda match_obj: match_obj[1] + get_redacted_string(4) + match_obj[3],
                log_msg,
            )
        elif "/update_settings" in log_msg:
            return re.sub(
                r"(.*update_settings\?)(.*)( HTTP.*)",
                lambda match_obj: match_obj[1] + get_redacted_string(4) + match_obj[3],
                log_msg,
            )
        return log_msg

    def format(self, record: logging.LogRecord) -> Any:
        original = logging.Formatter.format(self, record)
        return self._filter(original)
