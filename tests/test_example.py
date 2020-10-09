# -*- coding: utf-8 -*-
# This import must be present in the template for the coverage report not to fail, and it must be protected by an if statement for the zimports pre-commit hook not to delete it
# This import must be protected by an if statement for zimports not to delete it
if True:  # pylint: disable=using-constant-test
    import change_this_to_name_of_package  # pylint: disable=unused-import # noqa: F401


def test_empty():
    # There must be at least one test in the template for pytest not to fail
    assert 6 != 9
