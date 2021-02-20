# -*- coding: utf-8 -*-
import os
from queue import Queue

from mantarray_desktop_app import ADC_CH_TO_24_WELL_INDEX
from mantarray_desktop_app import ADC_GAIN_DESCRIPTION_TAG
from mantarray_desktop_app import ADC_OFFSET_DESCRIPTION_TAG
from mantarray_desktop_app import InvalidScriptCommandError
from mantarray_desktop_app import MismatchedScriptTypeError
from mantarray_desktop_app import ok_comm
from mantarray_desktop_app import parse_scripting_log
from mantarray_desktop_app import parse_scripting_log_line
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import ScriptDoesNotContainEndCommandError
import pytest
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import invoke_process_run_and_check_errors
from stdlib_utils import resource_path
from xem_wrapper import convert_wire_value
from xem_wrapper import OkHardwareUnsupportedFeatureError

from ..fixtures import fixture_test_process_manager
from ..fixtures_ok_comm import fixture_four_board_comm_process
from ..fixtures_process_monitor import fixture_test_monitor
from ..helpers import is_queue_eventually_not_empty

__fixtures__ = [
    fixture_test_monitor,
    fixture_test_process_manager,
    fixture_four_board_comm_process,
]


@pytest.mark.parametrize(
    """test_log_line,expected_dict,test_description""",
    [
        (
            '[2020-03-31 23:50:17,068 UTC] werkzeug-{_internal.py:113} INFO - 127.0.0.1 - - [31/Mar/2020 16:50:17] " [33mGET /insert_xem_command_into_queue/development/begin_hardware_script?script_type=start_up&version=0 HTTP/1.1 [0m" 404 -',
            {
                "command": "begin_hardware_script",
                "script_type": "start_up",
                "version": 0,
            },
            "correctly parses begin_hardware_script command",
        ),
        (
            '[2020-03-31 23:50:17,363 UTC] werkzeug-{_internal.py:113} INFO - 127.0.0.1 - - [31/Mar/2020 16:50:17] " [37mGET /insert_xem_command_into_queue/set_wire_in?ep_addr=0&value=0x00000004&mask=0x00000004 HTTP/1.1 [0m" 200 -',
            {"command": "set_wire_in", "ep_addr": 0, "value": 4, "mask": 4},
            "correctly parses set_wire_in command",
        ),
        (
            '[2020-03-31 23:50:27,183 UTC] werkzeug-{_internal.py:113} INFO - 127.0.0.1 - - [31/Mar/2020 16:50:27] " [37mGET /insert_xem_command_into_queue/read_wire_out?ep_addr=38 HTTP/1.1 [0m" 200 -',
            {"command": "read_wire_out", "ep_addr": 38},
            "correctly parses read_wire_out command",
        ),
        (
            '[2020-03-31 23:50:32,641 UTC] werkzeug-{_internal.py:113} INFO - 127.0.0.1 - - [31/Mar/2020 16:50:32] " [37mGET /insert_xem_command_into_queue/activate_trigger_in?ep_addr=0x41&bit=0x00000002 HTTP/1.1 [0m" 200 -',
            {"command": "activate_trigger_in", "ep_addr": 0x41, "bit": 2},
            "correctly parses activate_trigger_in command",
        ),
        (
            '[2020-03-31 23:50:32,641 UTC] werkzeug-{_internal.py:113} INFO - 127.0.0.1 - - [31/Mar/2020 16:50:32] " [37mGET /insert_xem_command_into_queue/comm_delay?num_milliseconds=15 HTTP/1.1 [0m" 200 -',
            {"command": "comm_delay", "num_milliseconds": 15},
            "correctly parses comm_delay command",
        ),
    ],
)
def test_parse_scripting_log_line__correctly_parses_log_line(
    test_log_line, expected_dict, test_description
):
    actual = parse_scripting_log_line(test_log_line)
    assert actual == expected_dict


def test_parse_scripting_log_line__raises_error_if_line_contains_invalid_command():
    test_log_line = '[2020-03-31 23:50:32,641 UTC] werkzeug-{_internal.py:113} INFO - 127.0.0.1 - - [31/Mar/2020 16:50:32] " [37mGET /insert_xem_command_into_queue/fake_command?ep_addr=0x41 HTTP/1.1 [0m" 200 -'
    with pytest.raises(
        InvalidScriptCommandError, match="Invalid scripting command: 'fake_command'"
    ):
        parse_scripting_log_line(test_log_line)


def test_parse_scripting_log__calls_resource_path_correctly(mocker):
    test_script = "test_script"
    mocked_path_str = os.path.join(
        "tests", "test_xem_scripts", f"xem_{test_script}.txt"
    )

    def side_effect(*args, **kwargs):
        # Tanner (4/14/20): we want to call resource_path unmocked, but need to patch it to get the return value needed for testing
        resource_path(*args, **kwargs)
        return mocked_path_str

    mocked_path = mocker.patch.object(
        ok_comm, "resource_path", autospec=True, side_effect=side_effect
    )

    parse_scripting_log(test_script)

    expected_base_path = os.path.normcase(
        os.path.join(
            os.path.dirname(os.path.dirname(get_current_file_abs_directory())),
            "src",
            "mantarray_desktop_app",
            os.pardir,
            os.pardir,
        )
    )
    expected_relative_path = os.path.join(
        "src", "xem_scripts", f"xem_{test_script}.txt"
    )
    mocked_path.assert_called_once_with(
        expected_relative_path, base_path=expected_base_path
    )


def test_parse_scripting_log__raises_error_if_script_types_dont_match(mocker):
    test_script = "test_error"
    mocked_path_str = os.path.join(
        "tests", "test_xem_scripts", f"xem_{test_script}.txt"
    )
    mocker.patch.object(
        ok_comm, "resource_path", autospec=True, return_value=mocked_path_str
    )
    with pytest.raises(
        MismatchedScriptTypeError,
        match=f"Script type in log: 'test_script' does not match file name: '{test_script}'",
    ):
        parse_scripting_log(test_script)


def test_parse_scripting_log__raises_error_if_script_does_not_contain_end_hardware_script_command(
    mocker,
):
    test_script = "test_no_end_hardware"
    mocked_path_str = os.path.join(
        "tests", "test_xem_scripts", f"xem_{test_script}.txt"
    )
    mocker.patch.object(
        ok_comm, "resource_path", autospec=True, return_value=mocked_path_str
    )
    with pytest.raises(ScriptDoesNotContainEndCommandError):
        parse_scripting_log(test_script)


def test_parse_scripting_log__correctly_parses_and_returns_commands_from_xem_test_script(
    mocker,
):
    test_script = "test_script"

    mocked_path_str = os.path.join(
        "tests", "test_xem_scripts", f"xem_{test_script}.txt"
    )
    mocker.patch.object(
        ok_comm, "resource_path", autospec=True, return_value=mocked_path_str
    )

    expected_return_dict = dict()
    expected_return_dict["script_type"] = test_script
    expected_return_dict["version"] = 0

    expected_command_list = list()
    expected_return_dict["command_list"] = expected_command_list
    expected_command_list.append(
        {"command": "set_wire_in", "ep_addr": 0, "value": 4, "mask": 4}
    )
    expected_command_list.append({"command": "comm_delay", "num_milliseconds": 10})
    expected_command_list.append(
        {"command": "read_wire_out", "ep_addr": 35, "description": "test_description"}
    )
    expected_command_list.append({"command": "read_wire_out", "ep_addr": 36})
    expected_command_list.append(
        {"command": "activate_trigger_in", "ep_addr": 65, "bit": 2}
    )

    actual = parse_scripting_log(test_script)
    assert actual == expected_return_dict


def test_all_xem_scripts_are_present_and_parse_without_error():
    script_dir = os.path.join(
        get_current_file_abs_directory(), os.pardir, os.pardir, "src", "xem_scripts"
    )
    script_list = list()
    for file in os.listdir(script_dir):
        if file.endswith(".txt"):
            script_list.append(file)
    script_types = frozenset(script_list)

    # Tanner (4/14/20): this loop is only to test that each script parses without error
    for script_file in script_list:
        script_type = script_file.strip("xem_").strip(".txt")
        parse_scripting_log(script_type)

    assert script_types == frozenset(["xem_start_up.txt", "xem_start_calibration.txt"])


def test_real_start_up_script__contains_gain_value_description_tag():
    script_dict = parse_scripting_log("start_up")
    command_list = script_dict["command_list"]

    description_list = []
    for command in command_list:
        if command["command"] == "set_wire_in":
            description = command.get("description", "")
            if ADC_GAIN_DESCRIPTION_TAG in description:
                description_list.append(description)

    for adc_idx in range(6):
        for ch_idx in range(8):
            assert (
                f"{ADC_GAIN_DESCRIPTION_TAG}__adc_index_{adc_idx}__channel_index_{ch_idx}"
                in description_list
            )


def test_gain_value_is_parsed_and_saved_when_running_start_up_script(
    test_monitor, test_process_manager, mocker
):
    test_script = "test_start_up"
    simulator = RunningFIFOSimulator()
    simulator.initialize_board()

    mocked_path_str = os.path.join(
        "tests", "test_xem_scripts", f"xem_{test_script}.txt"
    )
    mocker.patch.object(
        ok_comm, "resource_path", autospec=True, return_value=mocked_path_str
    )

    monitor_thread, shared_values_dict, _, _ = test_monitor

    ok_comm_process = test_process_manager.get_instrument_process()
    from_ok_comm_queue = test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(
        0
    )
    to_ok_comm_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(
        0
    )
    ok_comm_process.set_board_connection(0, simulator)

    to_ok_comm_queue.put(
        {"communication_type": "xem_scripts", "script_type": "start_up"}
    )
    assert is_queue_eventually_not_empty(to_ok_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_ok_comm_queue) is True
    # Tanner (6/12/20): num iterations should be 3 here because xem_scripts sends 3 messages to main, and the third one will contain the gain value
    invoke_process_run_and_check_errors(monitor_thread, num_iterations=3)

    assert shared_values_dict["adc_gain"] == 16


def test_real_calibration_script__contains_offset_value_description_tag():
    script_dict = parse_scripting_log("start_calibration")
    command_list = script_dict["command_list"]

    description_list = []
    for command in command_list:
        if command["command"] == "read_wire_out":
            description = command.get("description", "")
            if ADC_OFFSET_DESCRIPTION_TAG in description:
                description_list.append(description)

    assert len(description_list) == 48
    for adc_idx in range(6):
        for ch_idx in range(8):
            assert (
                f"{ADC_OFFSET_DESCRIPTION_TAG}__adc_index_{adc_idx}__channel_index_{ch_idx}"
                in description_list
            )


def test_offset_values_are_parsed_and_saved_when_running_start_calibration_script(
    test_monitor, test_process_manager, mocker
):
    test_script = "test_start_calibration"

    # pair construct and ref offset so that ref offset = construct offset + 1 for any given well index
    wire_outs = dict()
    for ch_idx in range(0, 8, 2):
        for adc_idx in range(6):
            well_idx = ADC_CH_TO_24_WELL_INDEX[adc_idx][ch_idx]
            ep_addr_val = ch_idx * 6 + adc_idx
            wire_outs[ep_addr_val] = Queue()
            val = convert_wire_value(well_idx * 2)
            wire_outs[ep_addr_val].put(val)
            wire_outs[ep_addr_val + 6] = Queue()
            val = convert_wire_value(well_idx * 2 + 1)
            wire_outs[ep_addr_val + 6].put(val)

    simulator = RunningFIFOSimulator({"wire_outs": wire_outs})
    simulator.initialize_board()

    mocked_path_str = os.path.join(
        "tests", "test_xem_scripts", f"xem_{test_script}.txt"
    )
    mocker.patch.object(
        ok_comm, "resource_path", autospec=True, return_value=mocked_path_str
    )

    monitor_thread, shared_values_dict, _, _ = test_monitor

    ok_comm_process = test_process_manager.get_instrument_process()
    from_ok_comm_queue = test_process_manager.queue_container().get_communication_queue_from_instrument_comm_to_main(
        0
    )
    to_ok_comm_queue = test_process_manager.queue_container().get_communication_to_instrument_comm_queue(
        0
    )
    ok_comm_process.set_board_connection(0, simulator)

    to_ok_comm_queue.put(
        {"communication_type": "xem_scripts", "script_type": "start_calibration"}
    )
    assert is_queue_eventually_not_empty(to_ok_comm_queue) is True
    invoke_process_run_and_check_errors(ok_comm_process)

    assert is_queue_eventually_not_empty(from_ok_comm_queue) is True
    # Tanner (6/26/20): num iterations should be 49 here because xem_scripts sends one scripting message followed by 48 offset values to main
    invoke_process_run_and_check_errors(monitor_thread, num_iterations=49)

    assert shared_values_dict["adc_offsets"][0]["construct"] == 0
    assert shared_values_dict["adc_offsets"][0]["ref"] == 1
    assert shared_values_dict["adc_offsets"][8]["construct"] == 16
    assert shared_values_dict["adc_offsets"][8]["ref"] == 17
    assert shared_values_dict["adc_offsets"][18]["construct"] == 36
    assert shared_values_dict["adc_offsets"][18]["ref"] == 37
    assert shared_values_dict["adc_offsets"][23]["construct"] == 46
    assert shared_values_dict["adc_offsets"][23]["ref"] == 47


def test_OkCommunicationProcess_xem_scripts__allows_errors_to_propagate(
    mocker, four_board_comm_process
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console

    test_script = "test_script"
    mocked_path_str = os.path.join(
        "tests", "test_xem_scripts", f"xem_{test_script}.txt"
    )
    mocker.patch.object(
        ok_comm, "resource_path", autospec=True, return_value=mocked_path_str
    )

    ok_process, board_queues, _ = four_board_comm_process

    mocked_simulator = RunningFIFOSimulator()
    mocked_activate = mocker.patch.object(
        mocked_simulator,
        "activate_trigger_in",
        autospec=True,
        side_effect=OkHardwareUnsupportedFeatureError(),
    )

    mocked_simulator.initialize_board()
    ok_process.set_board_connection(0, mocked_simulator)

    board_queues[0][0].put(
        {"communication_type": "xem_scripts", "script_type": test_script}
    )
    assert is_queue_eventually_not_empty(board_queues[0][0])

    with pytest.raises(OkHardwareUnsupportedFeatureError):
        invoke_process_run_and_check_errors(ok_process, perform_setup_before_loop=True)
    assert mocked_activate.call_count == 1
