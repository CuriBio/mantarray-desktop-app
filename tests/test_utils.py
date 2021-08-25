# -*- coding: utf-8 -*-
import copy
import json
import os

from mantarray_desktop_app import create_magnetometer_config_dict
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import get_active_wells_from_config
from mantarray_desktop_app import get_current_software_version
from mantarray_desktop_app import get_redacted_string
from mantarray_desktop_app import redact_sensitive_info_from_path
from mantarray_desktop_app import SERIAL_COMM_WELL_IDX_TO_MODULE_ID
from mantarray_desktop_app import sort_nested_dict
from mantarray_desktop_app import utils
import pytest
from stdlib_utils import get_current_file_abs_directory


def test_get_current_software_version__Given_code_is_not_bundled__When_the_function_is_called__Then_it_returns_version_from_package_json():
    path_to_package_json = os.path.join(get_current_file_abs_directory(), os.pardir, "package.json")
    with open(path_to_package_json) as in_file:
        parsed_json = json.load(in_file)
        expected = parsed_json["version"]
        actual = get_current_software_version()
        assert actual == expected


def test_get_current_software_version__Given_code_is_mocked_as_being_bundled__When_the_function_is_called__Then_it_returns_version_from_constants_py(
    mocker,
):
    mocker.patch.object(utils, "is_frozen_as_exe", autospec=True, return_value=True)

    actual = get_current_software_version()
    assert actual == CURRENT_SOFTWARE_VERSION


def test_get_redacted_string__returns_correct_string():
    assert get_redacted_string(10) == "*" * 10


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
    assert actual == get_redacted_string(len(test_path))


def test_get_active_wells_from_config__returns_correct_values():
    test_num_wells = 24
    default_config_dict = create_magnetometer_config_dict(test_num_wells)
    assert get_active_wells_from_config(default_config_dict) == []

    expected_wells = [0, 8, 9, 17]
    test_config_dict = copy.deepcopy(default_config_dict)
    for well_idx in expected_wells:
        module_id = SERIAL_COMM_WELL_IDX_TO_MODULE_ID[well_idx]
        test_config_dict[module_id][0] = True

    assert get_active_wells_from_config(test_config_dict) == expected_wells


def test_sort_nested_dict__returns_correct_dict():
    test_dict = {
        2: {"A": 7, "Z": 0, "V": None},
        3: True,
        1: bytes(2),
    }
    actual = sort_nested_dict(test_dict)

    expected_outer_keys = [1, 2, 3]
    for i, outer_key in enumerate(list(actual.keys())):
        assert outer_key == expected_outer_keys[i]
    expected_inner_keys = ["A", "V", "Z"]
    for i, inner_key in enumerate(list(actual[2].keys())):
        assert inner_key == expected_inner_keys[i]
