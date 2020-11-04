# -*- coding: utf-8 -*-
import pytest

from ..fixtures import fixture_generic_queue_container
from ..fixtures import fixture_test_process_manager
from ..fixtures_server import fixture_client_and_server_thread_and_shared_values
from ..fixtures_server import fixture_server_thread
from ..fixtures_server import fixture_test_client
from ..helpers import is_queue_eventually_not_empty

__fixtures__ = [
    fixture_client_and_server_thread_and_shared_values,
    fixture_server_thread,
    fixture_generic_queue_container,
    fixture_test_process_manager,
    fixture_test_client,
]


@pytest.mark.slow
def test_send_single_set_mantarray_nickname_command__gets_processed_and_stores_nickname_in_shared_values_dict(
    test_process_manager, test_client
):
    shared_values_dict = test_process_manager.get_values_to_share_to_server()
    shared_values_dict["mantarray_nickname"] = dict()
    expected_nickname = "Surnom Français"

    test_process_manager.start_processes()
    response = test_client.get(f"/set_mantarray_nickname?nickname={expected_nickname}")
    assert response.status_code == 200
    assert shared_values_dict["mantarray_nickname"][0] == expected_nickname

    test_process_manager.soft_stop_and_join_processes()
    comm_queue = test_process_manager.queue_container().get_communication_to_ok_comm_queue(
        0
    )
    assert is_queue_eventually_empty(comm_queue) is True

    comm_from_ok_queue = test_process_manager.queue_container().get_communication_queue_from_ok_comm_to_main(
        0
    )
    comm_from_ok_queue.get_nowait()  # pull out the initial boot-up message
    comm_from_ok_queue.get_nowait()  # pull ok_comm connect to board message

    assert is_queue_eventually_not_empty(comm_from_ok_queue) is True
    communication = comm_from_ok_queue.get_nowait()
    assert communication["communication_type"] == "mantarray_naming"
    assert communication["command"] == "set_mantarray_nickname"
    assert communication["mantarray_nickname"] == expected_nickname
