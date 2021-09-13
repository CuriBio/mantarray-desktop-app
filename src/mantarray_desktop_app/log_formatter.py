# -*- coding: utf-8 -*-
"""Custom Log Formatter."""
import logging
import re

from .utils import get_redacted_string


class SensitiveFormatter(logging.Formatter):
    """Formatter that removes sensitive information in URLs.

    Based on https://stackoverflow.com/questions/48380452/mask-out-sensitive-information-in-python-log
    """

    @staticmethod
    def _filter(log_msg: str) -> str:
        return re.sub(
            r"(.*set_mantarray_nickname\?nickname=)(.*)( HTTP.*)",
            lambda match_obj: match_obj[1] + get_redacted_string(len(match_obj[2])) + match_obj[3],
            log_msg,
        )

    def format(self, record: logging.LogRecord) -> str:
        original = logging.Formatter.format(self, record)
        return self._filter(original)
