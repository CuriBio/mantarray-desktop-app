# -*- coding: utf-8 -*-
import logging

from mantarray_desktop_app import clear_the_server_manager
from mantarray_desktop_app import DataAnalyzerProcess
from mantarray_desktop_app import FileWriterProcess
from mantarray_desktop_app import INSTRUMENT_INITIALIZING_STATE
from mantarray_desktop_app import MantarrayProcessesManager
from mantarray_desktop_app import McCommunicationProcess
from mantarray_desktop_app import OkCommunicationProcess
from mantarray_desktop_app import process_manager
from mantarray_desktop_app import ServerManager
from mantarray_desktop_app import SUBPROCESS_JOIN_SECONDS
from mantarray_desktop_app import SUBPROCESS_POLL_DELAY_SECONDS
from mantarray_desktop_app import SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS
import pytest
from stdlib_utils import InfiniteProcess

from .fixtures import fixture_patch_subprocess_is_stopped_to_false
from .fixtures import fixture_patched_firmware_folder
from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .helpers import is_queue_eventually_of_size
from .helpers import put_object_into_queue_and_raise_error_if_eventually_still_empty

__fixtures__ = [
    fixture_patched_firmware_folder,
    fixture_patch_subprocess_is_stopped_to_false,
]


@pytest.fixture(scope="function", name="generic_manager")
def fixture_generic_manager():
    manager = MantarrayProcessesManager()
    yield manager

    if manager.are_subprocess_start_ups_complete() and not manager.are_processes_stopped():
        manager.hard_stop_processes()

    # aspects of processes are often mocked just to assert they are called, so make sure to explicitly clean up the ServerManager module singleton
    clear_the_server_manager()


def test_MantarrayProcessesManager__stop_processes__calls_stop_on_all_processes_and_shuts_down_server(
    mocker, generic_manager
):
    generic_manager.create_processes()
    mocked_ok_comm_stop = mocker.patch.object(OkCommunicationProcess, "stop")
    mocked_file_writer_stop = mocker.patch.object(FileWriterProcess, "stop")
    mocked_data_analyzer_stop = mocker.patch.object(DataAnalyzerProcess, "stop")
    mocked_shutdown_server = mocker.patch.object(ServerManager, "shutdown_server")

    generic_manager.stop_processes()

    mocked_ok_comm_stop.assert_called_once()
    mocked_file_writer_stop.assert_called_once()
    mocked_data_analyzer_stop.assert_called_once()
    mocked_shutdown_server.assert_called_once()


def test_MantarrayProcessesManager__soft_stop_processes__calls_soft_stop_on_all_processes_and_shuts_down_server(
    generic_manager,
    mocker,
):
    generic_manager.create_processes()
    mocked_ok_comm_soft_stop = mocker.patch.object(OkCommunicationProcess, "soft_stop")
    mocked_file_writer_soft_stop = mocker.patch.object(FileWriterProcess, "soft_stop")
    mocked_data_analyzer_soft_stop = mocker.patch.object(DataAnalyzerProcess, "soft_stop")
    mocked_shutdown_server = mocker.patch.object(ServerManager, "shutdown_server")

    generic_manager.soft_stop_processes()

    mocked_ok_comm_soft_stop.assert_called_once()
    mocked_file_writer_soft_stop.assert_called_once()
    mocked_data_analyzer_soft_stop.assert_called_once()
    mocked_shutdown_server.assert_called_once()


def test_MantarrayProcessesManager__hard_stop_processes__logs_info(mocker, generic_manager):
    mocked_info = mocker.patch.object(process_manager.logger, "info", autospec=True)

    generic_manager.create_processes()
    mocker.patch.object(generic_manager, "shutdown_server", autospec=True, return_value={})
    mocker.patch.object(OkCommunicationProcess, "hard_stop", autospec=True)
    mocker.patch.object(FileWriterProcess, "hard_stop", autospec=True)
    mocker.patch.object(DataAnalyzerProcess, "hard_stop", autospec=True)

    generic_manager.hard_stop_processes()
    assert mocked_info.call_args_list == [
        mocker.call("Hard stopping Instrument Comm Process"),
        mocker.call("Hard stopping File Writer Process"),
        mocker.call("Hard stopping Data Analyzer Process"),
        mocker.call("All subprocesses hard stopped"),
    ]


@pytest.mark.parametrize("shutdown_server", [True, False])
def test_MantarrayProcessesManager__hard_stop_processes__calls_hard_stop_on_all_processes_and_conditionally_shuts_down_server__and_returns_process_queue_items(
    shutdown_server, mocker, generic_manager
):
    expected_ok_comm_items = {"instrument_comm_queue": ["instrument_item"]}
    expected_file_writer_items = {"file_writer_queue": ["fw_item"]}
    expected_da_items = {"data_analyzer_queue": ["da_item"]}
    expected_server_items = {"to_main": ["server_item"]}

    generic_manager.create_processes()
    mocked_ok_comm_hard_stop = mocker.patch.object(
        OkCommunicationProcess, "hard_stop", autospec=True, return_value=expected_ok_comm_items
    )
    mocked_file_writer_hard_stop = mocker.patch.object(
        FileWriterProcess, "hard_stop", autospec=True, return_value=expected_file_writer_items
    )
    mocked_data_analyzer_hard_stop = mocker.patch.object(
        DataAnalyzerProcess, "hard_stop", autospec=True, return_value=expected_da_items
    )
    mocked_server_drain_queues = mocker.patch.object(
        ServerManager, "drain_all_queues", autospec=True, return_value=expected_server_items
    )

    actual = generic_manager.hard_stop_processes(shutdown_server=shutdown_server)

    mocked_ok_comm_hard_stop.assert_called_once()
    mocked_file_writer_hard_stop.assert_called_once()
    mocked_data_analyzer_hard_stop.assert_called_once()
    assert mocked_server_drain_queues.call_count == int(shutdown_server)

    assert actual["instrument_comm_items"] == expected_ok_comm_items
    assert actual["file_writer_items"] == expected_file_writer_items
    assert actual["data_analyzer_items"] == expected_da_items
    if shutdown_server:
        assert actual["server_items"] == expected_server_items
    else:
        assert "server_items" not in actual


@pytest.mark.slow
@pytest.mark.timeout(20)
def test_MantarrayProcessesManager__join_processes__calls_join_on_all_processes(mocker, generic_manager):
    generic_manager.spawn_processes()

    spied_ok_comm_join = mocker.spy(OkCommunicationProcess, "join")
    spied_file_writer_join = mocker.spy(FileWriterProcess, "join")
    spied_data_analyzer_join = mocker.spy(DataAnalyzerProcess, "join")

    generic_manager.soft_stop_processes()
    generic_manager.join_processes()

    spied_ok_comm_join.assert_called_once_with(mocker.ANY, SUBPROCESS_JOIN_SECONDS)
    spied_file_writer_join.assert_called_once_with(mocker.ANY, SUBPROCESS_JOIN_SECONDS)
    spied_data_analyzer_join.assert_called_once_with(mocker.ANY, SUBPROCESS_JOIN_SECONDS)


def test_MantarrayProcessesManager__join_processes__logs_info(mocker, generic_manager):
    generic_manager.create_processes()

    mocker.patch.object(process_manager, "_process_can_be_joined", autospec=True, return_value=True)
    mocker.patch.object(process_manager, "_process_failed_to_join", autospec=True, return_value=False)
    mocker.patch.object(InfiniteProcess, "join", autospec=True)

    mocked_info = mocker.patch.object(process_manager.logger, "info", autospec=True)
    generic_manager.join_processes()
    assert mocked_info.call_args_list == [
        mocker.call("Joining Instrument Comm Process"),
        mocker.call("Joining File Writer Process"),
        mocker.call("Joining Data Analyzer Process"),
        mocker.call("All subprocesses joined"),
    ]


def test_MantarrayProcessesManager__join_processes__terminates_process_if_not_successfully_joined__and_logs_error(
    mocker, generic_manager
):
    generic_manager.create_processes()

    mocker.patch.object(process_manager, "_process_can_be_joined", autospec=True, return_value=True)
    mocker.patch.object(InfiniteProcess, "join", autospec=True)

    mocked_ok_comm_terminate = mocker.patch.object(OkCommunicationProcess, "terminate", autospec=True)
    mocked_file_writer_terminate = mocker.patch.object(FileWriterProcess, "terminate", autospec=True)
    mocked_data_analyzer_terminate = mocker.patch.object(DataAnalyzerProcess, "terminate", autospec=True)

    mocked_error = mocker.patch.object(process_manager.logger, "error", autospec=True)
    generic_manager.join_processes()

    mocked_ok_comm_terminate.assert_called_once()
    mocked_file_writer_terminate.assert_called_once()
    mocked_data_analyzer_terminate.assert_called_once()

    assert mocked_error.call_args_list == [
        mocker.call("Terminating Instrument Comm Process after unsuccessful join"),
        mocker.call("Terminating File Writer Process after unsuccessful join"),
        mocker.call("Terminating Data Analyzer Process after unsuccessful join"),
    ]


@pytest.mark.slow
@pytest.mark.timeout(20)
def test_MantarrayProcessesManager__spawn_processes__stop_and_join_processes__starts_and_stops_all_processes_and_shuts_down_server(
    mocker, generic_manager
):
    spied_ok_comm_start = mocker.spy(OkCommunicationProcess, "start")
    spied_ok_comm_stop = mocker.spy(OkCommunicationProcess, "stop")
    spied_ok_comm_join = mocker.spy(OkCommunicationProcess, "join")
    spied_file_writer_start = mocker.spy(FileWriterProcess, "start")
    spied_file_writer_stop = mocker.spy(FileWriterProcess, "stop")
    spied_file_writer_join = mocker.spy(FileWriterProcess, "join")
    spied_data_analyzer_start = mocker.spy(DataAnalyzerProcess, "start")
    spied_data_analyzer_stop = mocker.spy(DataAnalyzerProcess, "stop")
    spied_data_analyzer_join = mocker.spy(DataAnalyzerProcess, "join")
    mocked_shutdown_server = mocker.patch.object(ServerManager, "shutdown_server")

    generic_manager.spawn_processes()

    # drain all queues of start-up messages before attempting to join
    generic_manager.get_instrument_process()._drain_all_queues()  # pylint:disable=protected-access
    generic_manager.get_file_writer_process()._drain_all_queues()  # pylint:disable=protected-access
    generic_manager.get_data_analyzer_process()._drain_all_queues()  # pylint:disable=protected-access

    generic_manager.stop_and_join_processes()

    spied_ok_comm_start.assert_called_once()
    spied_ok_comm_stop.assert_called_once()
    spied_ok_comm_join.assert_called_once()

    spied_file_writer_start.assert_called_once()
    spied_file_writer_stop.assert_called_once()
    spied_file_writer_join.assert_called_once()

    spied_data_analyzer_start.assert_called_once()
    spied_data_analyzer_stop.assert_called_once()
    spied_data_analyzer_join.assert_called_once()

    mocked_shutdown_server.assert_called_once()


@pytest.mark.slow
@pytest.mark.timeout(20)
def test_MantarrayProcessesManager__soft_stop_and_join_processes__soft_stops_and_joins_processes_and_shuts_down_server(
    mocker, generic_manager
):
    spied_ok_comm_start = mocker.spy(OkCommunicationProcess, "start")
    spied_ok_comm_soft_stop = mocker.spy(OkCommunicationProcess, "soft_stop")
    spied_ok_comm_join = mocker.patch.object(OkCommunicationProcess, "join")

    spied_file_writer_start = mocker.spy(FileWriterProcess, "start")
    spied_file_writer_soft_stop = mocker.spy(FileWriterProcess, "soft_stop")
    spied_file_writer_join = mocker.patch.object(FileWriterProcess, "join")

    spied_data_analyzer_start = mocker.spy(DataAnalyzerProcess, "start")
    spied_data_analyzer_soft_stop = mocker.spy(DataAnalyzerProcess, "soft_stop")
    spied_data_analyzer_join = mocker.patch.object(DataAnalyzerProcess, "join")

    mocked_shutdown_server = mocker.patch.object(ServerManager, "shutdown_server")

    generic_manager.spawn_processes()
    generic_manager.soft_stop_and_join_processes()

    spied_ok_comm_start.assert_called_once()
    spied_ok_comm_soft_stop.assert_called_once()
    spied_ok_comm_join.assert_called_once()

    spied_file_writer_start.assert_called_once()
    spied_file_writer_soft_stop.assert_called_once()
    spied_file_writer_join.assert_called_once()

    spied_data_analyzer_start.assert_called_once()
    spied_data_analyzer_soft_stop.assert_called_once()
    spied_data_analyzer_join.assert_called_once()

    mocked_shutdown_server.assert_called_once()


@pytest.mark.slow
@pytest.mark.timeout(20)
@pytest.mark.parametrize("shutdown_server", [True, False])
def test_MantarrayProcessesManager__hard_stop_and_join_processes__hard_stops_processes_and_shuts_down_server__and_returns_queue_items(
    shutdown_server, mocker, generic_manager
):
    expected_ok_comm_item = "ok_comm_item"
    expected_file_writer_item = "file_writer_item"
    expected_da_item = "data_analyzer_item"
    expected_server_item = "server_item"

    spied_hard_stop_processes = mocker.spy(generic_manager, "hard_stop_processes")

    def se(*args):
        spied_hard_stop_processes.assert_called_once()

    mocked_join_processes = mocker.patch.object(
        generic_manager, "join_processes", autospec=True, side_effect=se
    )

    mocked_shutdown_server = mocker.patch.object(ServerManager, "shutdown_server")
    spied_server_drain_queues = mocker.spy(ServerManager, "drain_all_queues")

    mocker.patch.object(OkCommunicationProcess, "start", autospec=True)
    mocker.patch.object(FileWriterProcess, "start", autospec=True)
    mocker.patch.object(DataAnalyzerProcess, "start", autospec=True)

    generic_manager.spawn_processes()

    container = generic_manager.queue_container()
    instrument_comm_to_main = container.get_communication_queue_from_instrument_comm_to_main(0)
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_ok_comm_item, instrument_comm_to_main
    )
    file_writer_to_main = container.get_communication_queue_from_file_writer_to_main()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(
        expected_file_writer_item, file_writer_to_main
    )
    data_analyzer_to_main = container.get_communication_queue_from_data_analyzer_to_main()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_da_item, data_analyzer_to_main)

    server_to_main = container.get_communication_queue_from_server_to_main()
    put_object_into_queue_and_raise_error_if_eventually_still_empty(expected_server_item, server_to_main)

    actual = generic_manager.hard_stop_and_join_processes(shutdown_server=shutdown_server)

    spied_hard_stop_processes.assert_called_once_with(shutdown_server=False)
    mocked_join_processes.assert_called_once()
    assert mocked_shutdown_server.call_count == int(shutdown_server)
    assert spied_server_drain_queues.call_count == int(shutdown_server)

    assert expected_ok_comm_item in actual["instrument_comm_items"]["board_0"]["instrument_comm_to_main"]
    assert expected_file_writer_item in actual["file_writer_items"]["from_file_writer_to_main"]
    assert expected_da_item in actual["data_analyzer_items"]["from_data_analyzer_to_main"]
    if shutdown_server:
        assert expected_server_item in actual["server_items"]["to_main"]
    else:
        assert "server_items" not in actual


def test_MantarrayProcessesManager__passes_file_directory_to_FileWriter():
    manager = MantarrayProcessesManager(file_directory="blahdir")
    manager.create_processes()
    assert manager.get_file_writer_process().get_file_directory() == "blahdir"

    # clean up the ServerManager singleton
    clear_the_server_manager()


def test_MantarrayProcessesManager__passes_shared_values_dict_to_server():
    expected_dict = {"beta_2_mode": False}
    manager = MantarrayProcessesManager(values_to_share_to_server=expected_dict)
    manager.create_processes()
    assert manager.get_server_manager().get_values_from_process_monitor() == expected_dict

    # clean up the ServerManager singleton
    clear_the_server_manager()


def test_MantarrayProcessesManager__passes_logging_level_to_subprocesses():
    expected_level = logging.WARNING
    manager = MantarrayProcessesManager(logging_level=expected_level)
    manager.create_processes()
    assert manager.get_file_writer_process().get_logging_level() == expected_level
    assert manager.get_instrument_process().get_logging_level() == expected_level
    assert manager.get_data_analyzer_process().get_logging_level() == expected_level
    assert manager.get_server_manager().get_logging_level() == expected_level

    # clean up the ServerManager singleton
    clear_the_server_manager()


@pytest.mark.parametrize(
    "load_firmware_file,test_description",
    [
        (True, "sends correct command dict to ok_comm when loading firmware file"),
        (False, "sends correct command dict to ok_comm when not loading firmware file"),
    ],
)
def test_MantarrayProcessesManager__boot_up_instrument__populates_ok_comm_queue_correctly__and_sets_system_status(
    load_firmware_file, test_description, generic_manager, patched_firmware_folder
):
    generic_manager.create_processes()
    generic_manager.boot_up_instrument(load_firmware_file=load_firmware_file)
    main_to_instrument_comm_queue = (
        generic_manager.queue_container().get_communication_to_instrument_comm_queue(0)
    )
    assert is_queue_eventually_of_size(main_to_instrument_comm_queue, 2) is True
    assert generic_manager.get_values_to_share_to_server()["system_status"] == INSTRUMENT_INITIALIZING_STATE

    actual_communication_1 = main_to_instrument_comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_communication_1 == {
        "communication_type": "boot_up_instrument",
        "command": "initialize_board",
        "bit_file_name": patched_firmware_folder if load_firmware_file else None,
        "suppress_error": False,
        "allow_board_reinitialization": False,
    }

    actual_communication_2 = main_to_instrument_comm_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
    assert actual_communication_2 == {
        "communication_type": "xem_scripts",
        "script_type": "start_up",
    }


def test_MantarrayProcessesManager__are_processes_stopped__waits_correct_amount_of_time_with_default_timeout_before_returning_false(
    generic_manager, mocker
):
    generic_manager.create_processes()
    okc_process = generic_manager.get_instrument_process()
    fw_process = generic_manager.get_file_writer_process()
    da_process = generic_manager.get_data_analyzer_process()
    mocked_okc_is_stopped = mocker.patch.object(
        okc_process, "is_stopped", autospec=True, side_effect=[False, True, True]
    )
    mocked_fw_is_stopped = mocker.patch.object(
        fw_process, "is_stopped", autospec=True, side_effect=[False, True]
    )
    mocked_da_is_stopped = mocker.patch.object(da_process, "is_stopped", autospec=True, side_effect=[False])

    mocked_counter = mocker.patch.object(
        process_manager,
        "perf_counter",
        side_effect=[0, 0, 0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS],
        autospec=True,
    )

    assert generic_manager.are_processes_stopped() is False

    assert mocked_counter.call_count == 4
    assert mocked_okc_is_stopped.call_count == 3
    assert mocked_fw_is_stopped.call_count == 2
    assert mocked_da_is_stopped.call_count == 1


def test_MantarrayProcessesManager__are_processes_stopped__waits_correct_amount_of_time_with_timeout_kwarg_passed_before_returning_false(
    generic_manager, mocker
):
    expected_timeout = SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS + 0.5

    generic_manager.create_processes()
    okc_process = generic_manager.get_instrument_process()
    fw_process = generic_manager.get_file_writer_process()
    da_process = generic_manager.get_data_analyzer_process()
    mocked_okc_is_stopped = mocker.patch.object(
        okc_process, "is_stopped", autospec=True, side_effect=[False, True, True]
    )
    mocked_fw_is_stopped = mocker.patch.object(
        fw_process, "is_stopped", autospec=True, side_effect=[False, True]
    )
    mocked_da_is_stopped = mocker.patch.object(da_process, "is_stopped", autospec=True, side_effect=[False])

    mocked_counter = mocker.patch.object(
        process_manager,
        "perf_counter",
        side_effect=[0, 0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS, expected_timeout],
        autospec=True,
    )

    assert generic_manager.are_processes_stopped(timeout_seconds=expected_timeout) is False

    assert mocked_counter.call_count == 4
    assert mocked_okc_is_stopped.call_count == 3
    assert mocked_fw_is_stopped.call_count == 2
    assert mocked_da_is_stopped.call_count == 1


def test_MantarrayProcessesManager__create_processes__passes_port_value_from_dictionary_to_server_manager(
    mocker,
):
    expected_port = 5432
    manager = MantarrayProcessesManager(
        values_to_share_to_server={
            "server_port_number": expected_port,
            "beta_2_mode": False,
        }
    )
    spied_create_server_manager = mocker.spy(ServerManager, "__init__")

    manager.create_processes()

    spied_create_server_manager.assert_called_once()
    assert spied_create_server_manager.call_args.kwargs["port"] == expected_port

    # clean up the ServerManager singleton
    clear_the_server_manager()


def test_MantarrayProcessesManager__are_processes_stopped__returns_true_if_stop_occurs_during_polling(
    generic_manager, mocker
):
    generic_manager.create_processes()
    instrument_process = generic_manager.get_instrument_process()
    da_process = generic_manager.get_data_analyzer_process()
    fw_process = generic_manager.get_file_writer_process()
    mocker.patch.object(instrument_process, "is_stopped", autospec=True, return_value=True)
    mocker.patch.object(fw_process, "is_stopped", autospec=True, return_value=True)
    mocker.patch.object(da_process, "is_stopped", autospec=True, side_effect=[False, True])

    mocked_counter = mocker.patch.object(process_manager, "perf_counter", autospec=True, return_value=0)
    mocker.patch.object(process_manager, "sleep", autospec=True)

    assert generic_manager.are_processes_stopped() is True

    assert mocked_counter.call_count == 2  # ensure it was activated once inside the loop


def test_MantarrayProcessesManager__are_processes_stopped__returns_true_if_stop_occurs_before_polling(
    generic_manager, mocker
):
    generic_manager.create_processes()
    instrument_process = generic_manager.get_instrument_process()
    da_process = generic_manager.get_data_analyzer_process()
    fw_process = generic_manager.get_file_writer_process()
    mocked_instrument_is_stopped = mocker.patch.object(
        instrument_process, "is_stopped", autospec=True, return_value=True
    )
    mocked_fw_is_stopped = mocker.patch.object(fw_process, "is_stopped", autospec=True, return_value=True)
    mocked_da_is_stopped = mocker.patch.object(da_process, "is_stopped", autospec=True, return_value=True)
    assert generic_manager.are_processes_stopped() is True

    assert mocked_instrument_is_stopped.call_count == 1
    assert mocked_fw_is_stopped.call_count == 1
    assert mocked_da_is_stopped.call_count == 1


def test_MantarrayProcessesManager__are_processes_stopped__sleeps_for_correct_amount_of_time_each_cycle_of_checking_subprocess_status(
    generic_manager, mocker, patch_subprocess_is_stopped_to_false
):
    generic_manager.create_processes()
    mocker.patch.object(
        process_manager,
        "perf_counter",
        side_effect=[0, SUBPROCESS_SHUTDOWN_TIMEOUT_SECONDS],
        autospec=True,
    )
    mocked_sleep = mocker.patch.object(process_manager, "sleep", autospec=True)

    generic_manager.are_processes_stopped()

    mocked_sleep.assert_called_once_with(SUBPROCESS_POLL_DELAY_SECONDS)


def test_MantarrayProcessesManager__are_subprocess_start_ups_complete__returns_false_if_none_are_started(
    generic_manager,
):
    generic_manager.create_processes()
    assert generic_manager.are_subprocess_start_ups_complete() is False


def test_MantarrayProcessesManager__are_subprocess_start_ups_complete__returns_false_if_none_are_created():
    test_manager = MantarrayProcessesManager()
    assert test_manager.are_subprocess_start_ups_complete() is False


def test_MantarrayProcessesManager__are_subprocess_start_ups_complete__returns_true_if_all_except_server_are_started(
    generic_manager, mocker
):
    generic_manager.create_processes()
    for iter_process in (
        generic_manager.get_instrument_process(),
        generic_manager.get_data_analyzer_process(),
        generic_manager.get_file_writer_process(),
    ):
        mocker.patch.object(iter_process, "is_start_up_complete", autospec=True, return_value=True)
    assert generic_manager.are_subprocess_start_ups_complete() is True


def test_MantarrayProcessesManager__are_subprocess_start_ups_complete__returns_false_if_all_except_file_writer_are_started(
    generic_manager, mocker
):
    generic_manager.create_processes()
    for iter_process in (
        generic_manager.get_instrument_process(),
        generic_manager.get_data_analyzer_process(),
    ):
        mocker.patch.object(iter_process, "is_start_up_complete", autospec=True, return_value=True)
    assert generic_manager.are_subprocess_start_ups_complete() is False


def test_MantarrayProcessesManager__passes_beta_2_flag_to_subprocesses_other_than_instrument_comm(
    mocker,
):
    expected_beta_2_flag = True
    shared_values_dict = {"beta_2_mode": expected_beta_2_flag}
    manager = MantarrayProcessesManager(values_to_share_to_server=shared_values_dict)

    spied_fw_init = mocker.spy(FileWriterProcess, "__init__")
    spied_da_init = mocker.spy(DataAnalyzerProcess, "__init__")

    manager.create_processes()

    assert spied_fw_init.call_args.kwargs["beta_2_mode"] is expected_beta_2_flag
    assert spied_da_init.call_args.kwargs["beta_2_mode"] is expected_beta_2_flag

    # clean up the ServerManager singleton
    clear_the_server_manager()


def test_MantarrayProcessesManager__creates_mc_comm_instead_of_ok_comm_when_beta_2_flag_is_set_true(
    mocker,
):
    shared_values_dict = {"beta_2_mode": True}
    manager = MantarrayProcessesManager(values_to_share_to_server=shared_values_dict)
    manager.create_processes()

    mc_comm_process = manager.get_instrument_process()
    assert isinstance(mc_comm_process, McCommunicationProcess) is True

    # clean up the ServerManager singleton
    clear_the_server_manager()


def test_MantarrayProcessesManager_shutdown_server__shutsdown_server_and_returns_remaining_items_in_queue_to_server(
    generic_manager, mocker
):
    generic_manager.create_processes()
    server_manager = generic_manager.get_server_manager()
    mocked_shutdown = mocker.patch.object(server_manager, "shutdown_server", autospec=True)
    mocked_drain = mocker.patch.object(
        server_manager, "drain_all_queues", autospec=True, return_value=["item"]
    )

    server_items = generic_manager.shutdown_server()
    assert server_items == {"server_items": ["item"]}
    mocked_shutdown.assert_called_once()
    mocked_drain.assert_called_once()


def test_MantarrayProcessesManager_shutdown_server__logs_info(generic_manager, mocker):
    mocked_info = mocker.patch.object(process_manager.logger, "info", autospec=True)
    generic_manager.create_processes()

    generic_manager.shutdown_server()
    mocked_info.assert_called_once_with("Shutting down server")


def test_MantarrayProcessesManager_get_subprocesses_running_status__returns_correct_values(
    generic_manager, mocker
):
    spied_are_processes_stopped = mocker.spy(generic_manager, "are_processes_stopped")

    assert generic_manager.get_subprocesses_running_status() is False
    spied_are_processes_stopped.assert_not_called()

    generic_manager.create_processes()
    assert generic_manager.get_subprocesses_running_status() is False
    spied_are_processes_stopped.assert_not_called()

    # mock so subprocesses don't actually start
    mocker.patch.object(generic_manager.get_instrument_process(), "start", autospec=True)
    mocker.patch.object(generic_manager.get_file_writer_process(), "start", autospec=True)
    mocker.patch.object(generic_manager.get_data_analyzer_process(), "start", autospec=True)

    generic_manager.start_processes()
    assert generic_manager.get_subprocesses_running_status() is not spied_are_processes_stopped.spy_return
    spied_are_processes_stopped.assert_called_once_with(timeout_seconds=0, sleep_between_checks=False)


def test_MantarrayProcessesManager_start_processes__returns_pids_for_each_subprocess(generic_manager, mocker):
    generic_manager.create_processes()

    ic_process = generic_manager.get_instrument_process()
    fw_process = generic_manager.get_file_writer_process()
    da_process = generic_manager.get_data_analyzer_process()

    # mock so subprocesses don't actually start
    mocker.patch.object(ic_process, "start", autospec=True)
    mocker.patch.object(fw_process, "start", autospec=True)
    mocker.patch.object(da_process, "start", autospec=True)

    pid_dict = generic_manager.start_processes()
    assert pid_dict == {
        "Instrument Comm": ic_process.pid,
        "File Writer": fw_process.pid,
        "Data Analyzer": da_process.pid,
    }
