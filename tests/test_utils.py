# -*- coding: utf-8 -*-
from mantarray_desktop_app import redact_sensitive_info_from_path
import pytest


@pytest.mark.parametrize(
    "test_path,expected_path,test_description",
    [
        (
            r"C:\Users\Tanner\AppData\Local\Programs\MantarrayController",
            r"C:\Users\******\AppData\Local\Programs\MantarrayController",
            "returns correct value when username is 'Tanner'",
        ),
        (
            r"C:\Users\Anna\Craig\AppData\Local\Programs\MantarrayController",
            r"C:\Users\**********\AppData\Local\Programs\MantarrayController",
            r"returns correct value when username is 'Anna\Craig'",
        ),
        (
            r"C:\Users\t\AppData\Local\Programs\MantarrayController",
            r"C:\Users\*\AppData\Local\Programs\MantarrayController",
            "returns correct value when username is 't'",
        ),
        (
            r"Users\username\AppData\Local\Programs\MantarrayController",
            r"Users\********\AppData\Local\Programs\MantarrayController",
            "returns correct value when nothing before Users",
        ),
        (
            r"C:\Users\username\AppData",
            r"C:\Users\********\AppData",
            "returns correct value when nothing after AppData",
        ),
        (
            r"C:\Users\username\AppData",
            r"C:\Users\********\AppData",
            "returns correct value when nothing after AppData",
        ),
        (
            r"Users\username\AppData",
            r"Users\********\AppData",
            "returns correct value when nothing before Users or after AppData",
        ),
    ],
)
def test_redact_sensitive_info_from_path__scrubs_chars_in_between_Users_and_AppData(
    test_path, expected_path, test_description
):
    actual = redact_sensitive_info_from_path(test_path)
    assert actual == expected_path


@pytest.mark.parametrize(
    "test_path,test_description",
    [
        (
            r"C:\Tanner\AppData\Local\Programs\MantarrayController",
            "returns scrubbed string when missing 'Users'",
        ),
        (
            r"C:\Users\Tanner\Local\Programs\MantarrayController",
            "returns scrubbed string when missing 'AppData'",
        ),
        (
            r"C:\Local\Programs\MantarrayController",
            "returns scrubbed string when missing 'Users' and 'AppData'",
        ),
        (
            r"C:AppData\Local\Users\Programs\MantarrayController",
            "returns scrubbed string when 'Users' and 'AppData' are out of order",
        ),
    ],
)
def test_redact_sensitive_info_from_path__scrubs_everything_if_does_not_match_pattern(
    test_path, test_description
):
    actual = redact_sensitive_info_from_path(test_path)
    assert actual == "*" * len(test_path)
