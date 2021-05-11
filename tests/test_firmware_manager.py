# -*- coding: utf-8 -*-
import os

from mantarray_desktop_app import firmware_manager
from mantarray_desktop_app import get_latest_firmware
from mantarray_desktop_app import get_latest_firmware_name
from mantarray_desktop_app import get_latest_firmware_version
from mantarray_desktop_app import sort_firmware_files
import pytest
from stdlib_utils import get_current_file_abs_directory


def test_sort_firmware_files__returns_sorted_list_of_all_firmware_files(mocker):
    expected_file_names = [
        "test_1_0_5.bit",
        "test_1_3_4.bit",
        "test_1_4_0.bit",
        "test_2_1_5.bit",
        "test_2_3_4.bit",
    ]
    mocked_path_str = os.path.join("tests", "test_firmware")
    mocked_path = mocker.patch.object(firmware_manager, "resource_path", return_value=mocked_path_str)

    actual = sort_firmware_files()
    expected_base_path = os.path.normcase(
        os.path.join(
            os.path.dirname(get_current_file_abs_directory()),
            "src",
            "mantarray_desktop_app",
            os.pardir,
            os.pardir,
        )
    )
    expected_relative_path = os.path.join("src", "firmware")
    os.path.join(expected_base_path, expected_relative_path)
    expected_file_list = expected_file_names

    mocked_path.assert_called_once_with(expected_relative_path, base_path=expected_base_path)
    assert actual == expected_file_list


def test_get_latest_firmware_name__returns_latest_firmware_file_name(mocker):
    expected_latest_name = "test_2_3_4.bit"
    mocked_path_str = os.path.join("tests", "test_firmware")
    mocker.patch.object(firmware_manager, "resource_path", return_value=mocked_path_str)

    actual = get_latest_firmware_name()
    assert actual == expected_latest_name


@pytest.mark.only_run_in_ci
def test_get_latest_firmware_name__returns_name_of_real_bit_file():
    actual = get_latest_firmware_name()
    assert "mantarray" in actual
    assert ".bit" in actual


def test_get_latest_firmware_version__returns_correct_version(mocker):
    expected_version = (2, 3, 4)
    mocked_path_str = os.path.join("tests", "test_firmware")
    mocker.patch.object(firmware_manager, "resource_path", return_value=mocked_path_str)

    actual = get_latest_firmware_version()
    assert actual == expected_version


def test_get_latest_firmware__returns_correct_path_to_latest_firmware_file(mocker):
    expected_base_path = os.path.normcase(
        os.path.join(
            os.path.dirname(get_current_file_abs_directory()),
            "src",
            "mantarray_desktop_app",
            os.pardir,
            os.pardir,
        )
    )

    mocked_path_str = os.path.join("tests", "test_firmware")
    mocked_path = mocker.patch.object(firmware_manager, "resource_path", return_value=mocked_path_str)

    expected_latest_file_path = os.path.join(mocked_path_str, "test_2_3_4.bit")
    actual = get_latest_firmware()
    assert actual == expected_latest_file_path

    expected_relative_path = os.path.join("src", "firmware")
    mocked_path.assert_called_with(expected_relative_path, base_path=expected_base_path)


def test_sort_firmware_files__returns_list_sorted_correctly_with_two_digit_numbers(
    mocker,
):
    expected = "mantarray_0_1_13.bit"
    mocker.patch.object(
        firmware_manager,
        "listdir",
        autospec=True,
        return_value=["mantarray_0_1_7.bit", expected],
    )
    actual = sort_firmware_files()
    assert actual[-1] == expected


def test_sort_firmware_files__returns_list_sorted_correctly_when_directory_contains_gitkeep_like_in_real_folder(
    mocker,
):
    expected = "mantarray_0_2_0.bit"
    mocker.patch.object(
        firmware_manager,
        "listdir",
        autospec=True,
        return_value=["mantarray_0_1_99.bit", expected, ".gitkeep"],
    )
    actual = sort_firmware_files()
    assert actual[-1] == expected


def test_get_latest_firmware__returns_correct_file_when_list_has_two_digit_numbers(
    mocker,
):
    expected = "mantarray_2_1_10.bit"
    mocker.patch.object(
        firmware_manager,
        "listdir",
        autospec=True,
        return_value=["mantarray_2_1_8.bit", expected],
    )
    actual = get_latest_firmware()
    assert actual.endswith(expected) is True
