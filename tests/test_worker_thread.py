# -*- coding: utf-8 -*-
import threading

from mantarray_desktop_app.worker_thread import ErrorCatchingThread


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


def test_ErrorCatchingThread__handles_error_in_target_func_correctly(mocker):
    expected_error = Exception("mocked error")

    def raise_err():
        raise expected_error

    mocked_thread = ErrorCatchingThread(target=raise_err)
    mocked_thread.start()
    mocked_thread.join()

    assert mocked_thread.error == repr(expected_error)
