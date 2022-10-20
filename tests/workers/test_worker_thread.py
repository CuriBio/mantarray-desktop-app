# -*- coding: utf-8 -*-
import threading

from mantarray_desktop_app.workers.worker_thread import ErrorCatchingThread
import pytest


def test_ErrorCatchingThread__run__calls_thread_init_correctly(mocker):
    mocked_super_init = mocker.spy(threading.Thread, "__init__")

    test_target = lambda: None  # noqa: E731  # this is fine for a test
    test_target_args = ("arg1", "arg2")
    test_target_kwargs = {"kwarg1": "kwarg1", "kwarg2": "kwarg2"}

    ect = ErrorCatchingThread(target=test_target, args=test_target_args, kwargs=test_target_kwargs)
    mocked_super_init.assert_called_once_with(
        ect, target=test_target, args=test_target_args, kwargs=test_target_kwargs
    )


def test_ErrorCatchingThread__correctly_returns_no_error_when_target_func_does_not_raise_one():
    mocked_thread = ErrorCatchingThread(target=lambda: None)
    mocked_thread.start()
    mocked_thread.join()

    assert mocked_thread.error is None


@pytest.mark.parametrize("use_error_repr", [None, False, True])
def test_ErrorCatchingThread__handles_error_in_target_func_correctly(use_error_repr, mocker):
    expected_error = Exception("mocked error")

    def raise_err():
        raise expected_error

    kwargs = {}
    if use_error_repr is not None:
        kwargs["use_error_repr"] = use_error_repr

    mocked_thread = ErrorCatchingThread(target=raise_err, **kwargs)
    mocked_thread.start()
    mocked_thread.join()

    assert mocked_thread.error == (expected_error if use_error_repr is False else repr(expected_error))
