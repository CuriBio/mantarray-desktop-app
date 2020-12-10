# -*- coding: utf-8 -*-
import copy
import logging
import math
from multiprocessing import Queue
from queue import Empty
import struct
import time

from freezegun import freeze_time
from mantarray_desktop_app import ADC_CH_TO_24_WELL_INDEX
from mantarray_desktop_app import build_file_writer_objects
from mantarray_desktop_app import check_mantarray_serial_number
from mantarray_desktop_app import DATA_FRAME_PERIOD
from mantarray_desktop_app import FirmwareFileNameDoesNotMatchWireOutVersionError
from mantarray_desktop_app import InvalidDataFramePeriodError
from mantarray_desktop_app import MantarrayFrontPanel
from mantarray_desktop_app import ok_comm
from mantarray_desktop_app import OkCommunicationProcess
from mantarray_desktop_app import parse_adc_metadata_byte
from mantarray_desktop_app import parse_data_frame
from mantarray_desktop_app import parse_gain
from mantarray_desktop_app import parse_little_endian_int24
from mantarray_desktop_app import parse_sensor_bytes
from mantarray_desktop_app import produce_data
from mantarray_desktop_app import RAW_TO_SIGNED_CONVERSION_VALUE
from mantarray_desktop_app import REF_INDEX_TO_24_WELL_INDEX
from mantarray_desktop_app import ROUND_ROBIN_PERIOD
from mantarray_desktop_app import RunningFIFOSimulator
from mantarray_desktop_app import TIMESTEP_CONVERSION_FACTOR
from mantarray_desktop_app import UnrecognizedCommTypeFromMainToOKCommError
from mantarray_desktop_app import UnrecognizedDataFrameFormatNameError
from mantarray_desktop_app import UnrecognizedMantarrayNamingCommandError
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND
import numpy as np
import pytest
from stdlib_utils import InfiniteProcess
from stdlib_utils import invoke_process_run_and_check_errors
from xem_wrapper import build_header_magic_number_bytes
from xem_wrapper import DATA_FRAME_SIZE_WORDS
from xem_wrapper import FrontPanel
from xem_wrapper import FrontPanelSimulator
from xem_wrapper import HEADER_MAGIC_NUMBER
from xem_wrapper import okCFrontPanel
from xem_wrapper import OpalKellyIncorrectHeaderError

from .fixtures import fixture_patched_firmware_folder
from .fixtures import get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION
from .fixtures import QUEUE_CHECK_TIMEOUT_SECONDS
from .fixtures_ok_comm import fixture_four_board_comm_process
from .fixtures_ok_comm import fixture_patch_connection_to_board
from .fixtures_ok_comm import fixture_running_process_with_simulated_board
from .helpers import is_queue_eventually_empty
from .helpers import is_queue_eventually_not_empty
from .helpers import is_queue_eventually_of_size

__fixtures__ = [
    fixture_four_board_comm_process,
    fixture_running_process_with_simulated_board,
    fixture_patch_connection_to_board,
    fixture_patched_firmware_folder,
]


@pytest.fixture(scope="function", name="patch_check_header")
def fixture_patch_check_header(mocker):
    mocker.patch.object(ok_comm, "check_header", autospec=True, return_value=True)


def test_parse_data_frame__raises_error_if_magic_number_incorrect():
    with pytest.raises(OpalKellyIncorrectHeaderError):
        parse_data_frame(bytearray([0, 0, 0, 0, 0, 0, 0, 0]), "any")


def test_parse_data_frame__raises_error_if_format_name_not_recognized(
    patch_check_header,
):
    with pytest.raises(UnrecognizedDataFrameFormatNameError, match="fakeformat"):
        parse_data_frame(bytearray([0, 0, 0, 0, 0, 0, 0, 0]), "fakeformat")


def test_parse_data_frame__two_channels_32_bit__single_sample_index__with_reference(
    patch_check_header,
):
    data_bytes = bytearray([0, 0, 0, 0, 0, 0, 0, 0])  # magic header
    data_bytes.extend([2, 3, 4, 5])  # sample index
    data_bytes.extend([6, 7, 8, 9])  # channel 0 reference
    data_bytes.extend([10, 11, 12, 13])  # channel 0 reading
    data_bytes.extend([14, 15, 16, 17])  # channel 1 reference
    data_bytes.extend([18, 19, 20, 21])  # channel 1 reading
    actual = parse_data_frame(
        data_bytes, "two_channels_32_bit__single_sample_index__with_reference"
    )

    channel_0 = np.zeros((1, 3), dtype=np.int32)
    channel_0[0] = [84148994, 218893066, 151521030]
    channel_1 = np.zeros((1, 3), dtype=np.int32)
    channel_1[0] = [84148994, 353637138, 286265102]

    expected = {0: channel_0, 1: channel_1}
    assert actual.keys() == expected.keys()
    np.testing.assert_equal(actual[0], expected[0])
    np.testing.assert_equal(actual[1], expected[1])


def test_parse_data_frame__six_channels_32_bit__single_sample_index(
    patch_check_header,
):
    data_bytes = bytearray(
        [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    )  # magic header
    data_bytes.extend([0x01, 0x02, 0x03, 0x04])  # sample index
    data_bytes.extend([0x05, 0x06, 0x07, 0x08])  # channel 0 reading
    data_bytes.extend([0x09, 0x0A, 0x0B, 0x0C])  # channel 1 reading
    data_bytes.extend([0x0D, 0x0E, 0x0F, 0x10])  # channel 2 reading
    data_bytes.extend([0x11, 0x12, 0x13, 0x14])  # channel 3 reading
    data_bytes.extend([0x15, 0x16, 0x17, 0x18])  # channel 4 reading
    data_bytes.extend([0x19, 0x1A, 0x1B, 0x1C])  # chxannel 5 reading
    actual = parse_data_frame(data_bytes, "six_channels_32_bit__single_sample_index")

    sample_index = 0x04030201 * TIMESTEP_CONVERSION_FACTOR
    expected = {
        0: (sample_index, bytearray([0x05, 0x06, 0x07, 0x08])),
        1: (sample_index, bytearray([0x09, 0x0A, 0x0B, 0x0C])),
        2: (sample_index, bytearray([0x0D, 0x0E, 0x0F, 0x10])),
        3: (sample_index, bytearray([0x11, 0x12, 0x13, 0x14])),
        4: (sample_index, bytearray([0x15, 0x16, 0x17, 0x18])),
        5: (sample_index, bytearray([0x19, 0x1A, 0x1B, 0x1C])),
    }
    assert actual.keys() == expected.keys()
    for i in range(6):
        np.testing.assert_equal(actual[i], expected[i])


@pytest.mark.parametrize(
    """test_metadata_byte,expected_adc_num,expected_adc_ch_num,
    expected_error_status,test_description""",
    [
        (0x00, 0, 0, False, "returns adc 0, adc ch 0, no error"),
        (0x11, 1, 1, False, "returns adc 1, adc ch 1, no error"),
        (0x27, 2, 7, False, "returns adc 2, adc ch 7, no error"),
        (0x54, 5, 4, False, "returns adc 5, adc ch 4, no error"),
        (0x08, 0, 0, True, "returns adc 0, adc ch 0, error"),
        (0x3C, 3, 4, True, "returns adc 3, adc ch 4, error"),
    ],
)
def test_parse_adc_metadata_byte(
    test_metadata_byte,
    expected_adc_num,
    expected_adc_ch_num,
    expected_error_status,
    test_description,
):
    actual_adc_num, actual_adc_ch_num, actual_error_status = parse_adc_metadata_byte(
        test_metadata_byte
    )
    assert actual_adc_num == expected_adc_num
    assert actual_adc_ch_num == expected_adc_ch_num
    assert actual_error_status is expected_error_status


@pytest.mark.parametrize(
    """test_bytearray,expected_value,test_description""",
    [
        (
            bytearray([0x00, 0x00, 0x00]),
            0x000000,
            "zero",
        ),
        (
            bytearray([0x00, 0x00, 0x80]),
            0x800000,
            "mid value",
        ),
        (
            bytearray([0xFF, 0xFF, 0xFF]),
            0xFFFFFF,
            "max reading",
        ),
    ],
)
def test_parse_little_endian_int24(test_bytearray, expected_value, test_description):
    actual = parse_little_endian_int24(test_bytearray)
    assert actual == expected_value


@pytest.mark.parametrize(
    """test_bytearray,expected_is_reference,expected_idx,expected_value,test_description""",
    [
        (
            bytearray([0x02, 0x02, 0x05, 0x03]),
            False,
            None,
            None,
            "returns_reference_false_when_false",
        ),
        (
            bytearray([0x01, 0x02, 0x05, 0x03]),
            True,
            None,
            None,
            "returns_reference_true_when_true",
        ),
        (
            bytearray([0x35, 0x02, 0x05, 0x03]),
            None,
            3,
            None,
            "returns_correct_reference_index_when_reference",
        ),
        (
            bytearray([0x12, 0x02, 0x05, 0x03]),
            None,
            ADC_CH_TO_24_WELL_INDEX[1][2],
            None,
            "returns_correct_plate_well_index_when_not_reference",
        ),
        (
            bytearray([0x02, 0x02, 0x05, 0x03]),
            None,
            None,
            0x030502 - RAW_TO_SIGNED_CONVERSION_VALUE,
            "correct value parsing 0x030502",
        ),
        (
            bytearray([0x02, 0x00, 0x00, 0x80]),
            None,
            None,
            0x800000 - RAW_TO_SIGNED_CONVERSION_VALUE,
            "correct value parsing 0x800000",
        ),
        (
            bytearray([0x02, 0xFF, 0xFF, 0xFF]),
            None,
            None,
            0xFFFFFF - RAW_TO_SIGNED_CONVERSION_VALUE,
            "correct value parsing 0xFFFFFF",
        ),
    ],
)
def test_parse_sensor_bytes(
    test_bytearray,
    expected_is_reference,
    expected_idx,
    expected_value,
    test_description,
):
    actual_is_reference, actual_index, actual_value = parse_sensor_bytes(test_bytearray)
    if expected_is_reference is not None:
        assert actual_is_reference is expected_is_reference
    if expected_idx is not None:
        assert actual_index == expected_idx
    if expected_value is not None:
        assert actual_value == expected_value


def test_parse_sensor_bytes_performance():
    # 5000 iterations
    # parsing sensor bytes, adc metadata, and little endian int24
    #
    # started at:                       30867322
    # 1. converting to cython:           4758391
    # 2. cpdef functions:                2846122
    # 3. line_trace=False:               2672362
    # 4. better function arg typing:     1477277
    # 5. more cdef variables:             808056

    test_bytearray = bytearray([0x02, 0xF6, 0x85, 0x77])
    start = time.perf_counter_ns()
    for _ in range(5000):
        parse_sensor_bytes(test_bytearray)
    dur = time.perf_counter_ns() - start
    # print(f"Duration (ns): {dur}")
    assert dur < 10000000


@pytest.mark.slow
def test_build_file_writer_objects_performance():
    # 10 iterations with 625 Hz data rate
    #
    # 1. cython parse_sensor_bytes:         266523479.8
    # 2. parse_sensor_bytes (4):            253645684.3
    # 3. parse_sensor_bytes (5):            246193920.3

    num_cycles = math.ceil(CENTIMILLISECONDS_PER_SECOND / ROUND_ROBIN_PERIOD)
    test_bytearray = produce_data(num_cycles, 0)
    q = Queue()

    start = time.perf_counter_ns()
    num_iterations = 10
    for _ in range(num_iterations):
        build_file_writer_objects(
            test_bytearray,
            "six_channels_32_bit__single_sample_index",
            q,
            logging.DEBUG,
        )
    dur = time.perf_counter_ns() - start

    ns_per_iter = dur / num_iterations
    # print(f"ns per iterations: {ns_per_iter}")
    assert (
        ns_per_iter < 400000000
    )  # Eli (10/20/20): bumped up from 300000000 to 400000000 because it was running a bit slow on windows in Github CI


def test_build_file_writer_objects__raises_error_if_format_name_not_recognized(
    patch_check_header, mocker
):
    # Tanner (5/21/20) When the error is raised, the queue is closed before it finishes writing to Pipe, so mock to avoid error in test
    mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)
    q = Queue()
    with pytest.raises(UnrecognizedDataFrameFormatNameError, match="fakeformat"):
        build_file_writer_objects(
            bytearray([0, 0, 0, 0, 0, 0, 0, 0]),
            "fakeformat",
            q,
            logging.DEBUG,
        )


@pytest.mark.parametrize(
    "test_data_frame_period,test_logging_level,test_description",
    [
        (
            DATA_FRAME_PERIOD // TIMESTEP_CONVERSION_FACTOR + 1,
            logging.INFO,
            "raises error when first period is longer than expected and log level info",
        ),
        (
            DATA_FRAME_PERIOD // TIMESTEP_CONVERSION_FACTOR - 1,
            logging.WARNING,
            "raises error when first period is shorter than expected and log level warning",
        ),
    ],
)
def test_build_file_writer_objects__raises_error__when_first_data_frame_period_of_read_is_not_expected_value_and_logging_level_is_info_or_higher(
    test_data_frame_period, test_logging_level, test_description, mocker
):
    # Tanner (7/10/20) When the error is raised, the queue is closed before it finishes writing to Pipe, so mock to avoid error in test
    mocker.patch.object(ok_comm, "put_log_message_into_queue", autospec=True)
    q = Queue()
    first_data_frame_size = DATA_FRAME_SIZE_WORDS * 4  # num bytes in a word
    test_bytearray = produce_data(1, 0)[:first_data_frame_size]
    test_bytearray.extend(produce_data(1, test_data_frame_period))
    expected_error_string = f"Detected period between first two data frames of FIFO read: {test_data_frame_period * TIMESTEP_CONVERSION_FACTOR} does not matched expected value: {DATA_FRAME_PERIOD}. Actual time indices: 0x0, {hex(test_data_frame_period * TIMESTEP_CONVERSION_FACTOR)}"
    with pytest.raises(InvalidDataFramePeriodError, match=expected_error_string):
        build_file_writer_objects(
            test_bytearray,
            "six_channels_32_bit__single_sample_index",
            q,
            test_logging_level,
        )


@pytest.mark.parametrize(
    "test_data_frame_period,test_description",
    [
        (
            DATA_FRAME_PERIOD // TIMESTEP_CONVERSION_FACTOR + 1,
            "logs warning when first period is longer than expected",
        ),
        (
            DATA_FRAME_PERIOD // TIMESTEP_CONVERSION_FACTOR - 1,
            "logs warning when first period is shorter than expected",
        ),
    ],
)
def test_build_file_writer_objects__logs_warning__when_first_data_frame_period_of_read_is_not_expected_value_and_logging_level_is_debug(
    test_data_frame_period, test_description, mocker
):
    mocked_put = mocker.patch.object(
        ok_comm, "put_log_message_into_queue", autospec=True
    )
    expected_queue = Queue()
    first_data_frame_size = DATA_FRAME_SIZE_WORDS * 4  # num bytes in a word
    test_bytearray = produce_data(1, 0)[:first_data_frame_size]
    test_bytearray.extend(produce_data(1, test_data_frame_period))

    expected_logging_threshold = logging.DEBUG
    build_file_writer_objects(
        test_bytearray,
        "six_channels_32_bit__single_sample_index",
        expected_queue,
        expected_logging_threshold,
    )

    expected_message = f"Detected period between first two data frames of FIFO read: {test_data_frame_period * TIMESTEP_CONVERSION_FACTOR} does not matched expected value: {DATA_FRAME_PERIOD}. Actual time indices: 0x0, {hex(test_data_frame_period * TIMESTEP_CONVERSION_FACTOR)}"
    mocked_put.assert_any_call(
        logging.DEBUG,
        expected_message,
        expected_queue,
        expected_logging_threshold,
    )


@pytest.mark.timeout(
    2
)  # Eli (3/16/20) - there were issues at one point where the test hung because it was putting things into the log queue. So adding the timeout
def test_build_file_writer_objects__returns_correct_values__with_six_channel_format__three_cycles():
    expected = dict()
    for i in range(6):
        expected[f"ref{i}"] = {
            "is_reference_sensor": True,
            "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[i],
            "data": None,
        }
    for i in range(24):
        expected[i] = {"is_reference_sensor": False, "well_index": i, "data": None}
    # build test and expected data
    test_bytearray = bytearray(0)
    for cycle in range(3):
        for frame in range(8):
            # add header
            test_bytearray.extend(build_header_magic_number_bytes(HEADER_MAGIC_NUMBER))
            sample_index = (
                cycle * ROUND_ROBIN_PERIOD // TIMESTEP_CONVERSION_FACTOR
                + frame * DATA_FRAME_PERIOD
            )
            # add sample index
            test_bytearray.extend(struct.pack("<L", sample_index))
            # add channel data
            for adc_num in range(6):
                # add metadata byte
                adc_ch_num = frame
                metadata_byte = (adc_num << 4) + adc_ch_num
                test_bytearray.extend([metadata_byte])
                # add value equal to position in data frame format
                test_data_byte = (48 * cycle) + (6 * frame) + adc_num
                test_bytearray.extend([test_data_byte, 0, 0])

                # update expected dictionary
                data = np.array(
                    [
                        [sample_index * TIMESTEP_CONVERSION_FACTOR],
                        [test_data_byte - RAW_TO_SIGNED_CONVERSION_VALUE],
                    ],
                    dtype=np.int32,
                )
                # determine if reference or construct
                if adc_ch_num % 2 == 1:
                    key = f"ref{adc_num}"
                else:
                    key = ADC_CH_TO_24_WELL_INDEX[adc_num][adc_ch_num]
                # add data appropriately
                if expected[key]["data"] is not None:
                    expected[key]["data"] = np.concatenate(
                        (expected[key]["data"], data), axis=1
                    )
                else:
                    expected[key]["data"] = data
    actual_queue = Queue()
    actual = build_file_writer_objects(
        test_bytearray,
        "six_channels_32_bit__single_sample_index",
        actual_queue,
        logging.DEBUG,
    )

    for key in expected:
        assert (
            actual[key]["is_reference_sensor"] is expected[key]["is_reference_sensor"]
        )

        if isinstance(key, str):
            assert (
                actual[key]["reference_for_wells"]
                == expected[key]["reference_for_wells"]
            )
        else:
            assert actual[key]["well_index"] == expected[key]["well_index"]

        np.testing.assert_equal(actual[key]["data"], expected[key]["data"])

    # drain the queue to avoid broken pipe errors
    while True:
        try:
            actual_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        except Empty:
            break


DATA_FROM_JASON = [
    "0xc6911999",
    "0x27021942",
    "0x41c2",
    "0x7ff19c00",
    "0x805d0710",
    "0x802bb020",
    "0x7fff1530",
    "0x80378440",
    "0x80027250",
    "0xc6911999",
    "0x27021942",
    "0x423c",
    "0x7fef5901",
    "0x803dee11",
    "0x7ffe6921",
    "0x7fbb0e31",
    "0x8058e041",
    "0x802e8251",
    "0xc6911999",
    "0x27021942",
    "0x42b7",
    "0x7fabf002",
    "0x8007bd12",
    "0x801f2a22",
    "0x7fb91532",
    "0x7fd88d42",
    "0x800c6d52",
    "0xc6911999",
    "0x27021942",
    "0x4332",
    "0x7fef3703",
    "0x803dd513",
    "0x7ffe7423",
    "0x7fbb0833",
    "0x8058d843",
    "0x802e8e53",
    "0xc6911999",
    "0x27021942",
    "0x43ad",
    "0x80101204",
    "0x7fc75714",
    "0x80111924",
    "0x80072e34",
    "0x7ff2de44",
    "0x804d1154",
    "0xc6911999",
    "0x27021942",
    "0x4427",
    "0x7fef6905",
    "0x803dbd15",
    "0x7ffe8725",
    "0x7fbaff35",
    "0x8058ef45",
    "0x802e5955",
    "0xc6911999",
    "0x27021942",
    "0x44a2",
    "0x7fd53b06",
    "0x800d9616",
    "0x7ff74326",
    "0x7fe99e36",
    "0x80319346",
    "0x800c8b56",
    "0xc6911999",
    "0x27021942",
    "0x451d",
    "0x80106107",
    "0x7fc27517",
    "0x80014727",
    "0x80446637",
    "0x7fa6c647",
    "0x7fd05a57",
]


def build_jasons_data_cycle() -> bytearray:

    test_bytearray = bytearray(0)
    for this_jason_word in DATA_FROM_JASON:
        word_as_int = int(this_jason_word, 0)
        converted_bytes = struct.pack("<L", word_as_int)

        test_bytearray.extend(converted_bytes)
    return test_bytearray


@pytest.mark.timeout(
    2
)  # Eli (3/16/20) - there were issues at one point where the test hung because it was putting things into the log queue. So adding the timeout
def test_build_file_writer_objects__correctly_parses_a_real_data_cycle_from_jason():
    test_bytearray = build_jasons_data_cycle()

    expected_dict = {}
    for ch_num in range(24):
        expected_dict[ch_num] = {
            "is_reference_sensor": False,
            "well_index": ch_num,
            "data": None,
        }
    for ref_num in range(6):
        expected_dict[f"ref{ref_num}"] = {
            "is_reference_sensor": True,
            "reference_for_wells": REF_INDEX_TO_24_WELL_INDEX[ref_num],
            "data": None,
        }
    for frame in range(8):
        sample_idx = int(DATA_FROM_JASON[(frame * 9) + 2], 16)
        for adc in range(6):
            data_word = bytearray(
                struct.pack("<L", int(DATA_FROM_JASON[(frame * 9) + 3 + adc], 16))
            )
            is_reference_sensor, index, sensor_value = parse_sensor_bytes(data_word)
            data = np.array(
                [[sample_idx * TIMESTEP_CONVERSION_FACTOR], [sensor_value]],
                dtype=np.int32,
            )
            key = f"ref{index}" if is_reference_sensor else index
            if expected_dict[key]["data"] is not None:
                expected_dict[key]["data"] = np.concatenate(
                    (expected_dict[key]["data"], data), axis=1
                )
            else:
                expected_dict[key]["data"] = data
    logging_queue = (
        Queue()
    )  # Eli (3/16/20): if there isn't a reference to the queue that still exists, it gives a 'broken pipe' error
    actual = build_file_writer_objects(
        test_bytearray,
        "six_channels_32_bit__single_sample_index",
        logging_queue,
        logging.DEBUG,
    )
    for key in expected_dict:
        assert (
            actual[key]["is_reference_sensor"]
            is expected_dict[key]["is_reference_sensor"]
        )

        if isinstance(key, str):
            assert (
                actual[key]["reference_for_wells"]
                == expected_dict[key]["reference_for_wells"]
            )
        else:
            assert actual[key]["well_index"] == expected_dict[key]["well_index"]

        np.testing.assert_equal(actual[key]["data"], expected_dict[key]["data"])

    # drain the queue to avoid broken pipe errors
    while True:
        try:
            logging_queue.get(timeout=QUEUE_CHECK_TIMEOUT_SECONDS)
        except Empty:
            break


def test_OkCommunicationProcess_super_is_called_during_init(mocker):
    error_queue = Queue()
    mocked_init = mocker.patch.object(InfiniteProcess, "__init__")
    OkCommunicationProcess((), error_queue)
    mocked_init.assert_called_once_with(error_queue, logging_level=logging.INFO)


def test_OkCommunicationProcess_get_board_connections_list__returns_sequence_same_length_as_queues_in_init(
    four_board_comm_process,
):
    ok_process, board_queues, _ = four_board_comm_process

    actual_connections = ok_process.get_board_connections_list()

    assert actual_connections == [None] * len(board_queues)


def test_OkCommunicationProcess_create_connections_to_all_available_boards__populates_connections_list_with_a_FrontPanel(
    patch_connection_to_board, mocker, four_board_comm_process
):
    ok_process, board_queues, _ = four_board_comm_process
    dummy_xem, mocked_open_board = patch_connection_to_board
    mocker.patch.object(
        ok_process,
        "determine_how_many_boards_are_connected",
        autospec=True,
        return_value=1,
    )

    ok_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(board_queues[0][1]) is True
    assert mocked_open_board.call_count == 1
    actual_connections = ok_process.get_board_connections_list()
    assert actual_connections[1:] == [None, None, None]
    actual_fp = actual_connections[0]
    assert isinstance(actual_fp, FrontPanel)
    assert actual_fp.get_xem() == dummy_xem


def test_OkCommunicationProcess_soft_stop_not_allowed_if_communication_from_main_still_in_queue(
    four_board_comm_process, patched_firmware_folder
):
    ok_process, board_queues, _ = four_board_comm_process
    dummy_communication = {
        "communication_type": "debug_console",
        "command": "initialize_board",
        "bit_file_name": patched_firmware_folder,
    }
    # The first communication will be processed, but if there is a second one in the queue then the soft stop should be disabled
    board_queues[0][0].put(dummy_communication)
    board_queues[0][0].put(dummy_communication)
    assert is_queue_eventually_of_size(board_queues[0][0], 2) is True
    simulator = FrontPanelSimulator({})
    ok_process.set_board_connection(0, simulator)
    ok_process.soft_stop()
    invoke_process_run_and_check_errors(ok_process)
    assert ok_process.is_stopped() is False


def test_OkCommunicationProcess_run__raises_error_if_communication_type_is_invalid(
    four_board_comm_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    ok_process, board_queues, _ = four_board_comm_process

    simulator = FrontPanelSimulator({})
    simulator.initialize_board()
    ok_process.set_board_connection(0, simulator)

    input_queue = board_queues[0][0]
    expected_returned_communication = {
        "communication_type": "fake_comm_type",
    }
    input_queue.put(copy.deepcopy(expected_returned_communication))
    assert is_queue_eventually_not_empty(input_queue) is True
    with pytest.raises(
        UnrecognizedCommTypeFromMainToOKCommError, match="fake_comm_type"
    ):
        invoke_process_run_and_check_errors(ok_process)


@freeze_time("2020-02-12 14:10:11.123456")
def test_OkCommunicationProcess_run_sends_initial_communication_to_main_during_setup(
    four_board_comm_process,
):
    ok_process, board_queues, _ = four_board_comm_process

    invoke_process_run_and_check_errors(ok_process, perform_setup_before_loop=True)
    comm_to_main = board_queues[0][1]
    assert is_queue_eventually_not_empty(comm_to_main) is True
    actual_msg = comm_to_main.get_nowait()
    assert actual_msg["communication_type"] == "log"
    assert (
        actual_msg["message"]
        == "OpalKelly Communication Process initiated at 2020-02-12 14:10:11.123456"
    )


def test_OkCommunicationProcess__sets_up_board_connection_when_run(
    patch_connection_to_board,
):
    error_queue = Queue()

    board_queues = tuple(
        [
            (
                Queue(),
                Queue(),
                Queue(),
            )
        ]
        * 4
    )
    p = OkCommunicationProcess(board_queues, error_queue)
    dummy_xem, _ = patch_connection_to_board
    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)
    xem_for_board_0 = p.get_board_connections_list()[0].get_xem()
    assert xem_for_board_0 == dummy_xem


@freeze_time("2020-02-13 11:43:11.123456")
def test_OkCommunicationProcess__puts_message_into_queue_for_successful_board_connection_when_run(
    patch_connection_to_board,
):
    error_queue = Queue()

    board_queues = tuple(
        [
            (
                Queue(),
                Queue(),
                Queue(),
            )
        ]
        * 4
    )
    p = OkCommunicationProcess(board_queues, error_queue)
    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)
    ok_comm_to_main = board_queues[0][1]
    ok_comm_to_main.get_nowait()  # pop out initial boot-up message

    assert is_queue_eventually_not_empty(ok_comm_to_main) is True
    msg = ok_comm_to_main.get_nowait()
    assert msg["communication_type"] == "board_connection_status_change"
    assert msg["is_connected"] is True
    assert msg["board_index"] == 0
    assert msg["timestamp"] == "2020-02-13 11:43:11.123456"
    assert (
        msg["mantarray_serial_number"]
        == RunningFIFOSimulator.default_mantarray_serial_number
    )
    assert msg["mantarray_nickname"] == RunningFIFOSimulator.default_mantarray_nickname
    assert msg["xem_serial_number"] == RunningFIFOSimulator.default_xem_serial_number
    board_0 = p.get_board_connections_list()[0]
    assert isinstance(board_0, FrontPanel)


def test_OkCommunicationProcess__puts_message_into_queue_for_unsuccessful_board_connection_when_run():
    error_queue = Queue()

    board_queues = tuple(
        [
            (
                Queue(),
                Queue(),
                Queue(),
            )
        ]
        * 4
    )
    p = OkCommunicationProcess(board_queues, error_queue)

    invoke_process_run_and_check_errors(p, perform_setup_before_loop=True)
    ok_comm_to_main = board_queues[0][1]
    ok_comm_to_main.get_nowait()  # pop out initial boot-up message

    assert is_queue_eventually_not_empty(ok_comm_to_main) is True
    msg = ok_comm_to_main.get_nowait()
    assert msg["communication_type"] == "board_connection_status_change"
    assert msg["is_connected"] is False
    assert msg["message"] == "No board detected. Creating simulator."
    assert (
        msg["mantarray_serial_number"]
        == RunningFIFOSimulator.default_mantarray_serial_number
    )
    assert msg["mantarray_nickname"] == RunningFIFOSimulator.default_mantarray_nickname
    assert msg["xem_serial_number"] == RunningFIFOSimulator.default_xem_serial_number

    board_0 = p.get_board_connections_list()[0]
    assert isinstance(board_0, FrontPanelSimulator)

    # cleanup process/queues to avoid broken pipe errors
    p.hard_stop()


def test_OkCommunicationProcess__hard_stop__hard_stops_the_RunningFIFOSimulator__for_board_0(
    four_board_comm_process, mocker
):
    ok_process, _, _ = four_board_comm_process
    simulator = FrontPanelSimulator({})
    # simulator.set_device_id('bob')
    ok_process.set_board_connection(0, simulator)

    spied_simulator_hard_stop = mocker.spy(simulator, "hard_stop")

    ok_process.hard_stop()
    assert spied_simulator_hard_stop.call_count == 1


def test_OkCommunicationProcess__hard_stop__does_not_raise_error_if_board_connections_not_yet_made(
    four_board_comm_process, mocker
):
    ok_process, _, _ = four_board_comm_process

    # would raise error if attempting to hard stop a non-existent board connection
    ok_process.hard_stop()


def test_OkCommunicationProcess__hard_stop__passes_timeout_arg_to_super_hard_stop__and_front_panel_hard_stop__and_returns_value_from_super(
    four_board_comm_process, mocker
):
    ok_process, _, _ = four_board_comm_process
    simulator = FrontPanelSimulator({})
    ok_process.set_board_connection(0, simulator)
    expected_return = {"someinfo": ["list"]}
    mocked_parent_hard_stop = mocker.patch.object(
        InfiniteProcess, "hard_stop", autospec=True, return_value=expected_return
    )
    mocked_front_panel_hard_stop = mocker.patch.object(
        simulator, "hard_stop", autospec=True
    )

    expected_timeout = 1.1
    actual_return = ok_process.hard_stop(timeout=expected_timeout)
    assert actual_return == expected_return
    mocked_parent_hard_stop.assert_called_once_with(
        ok_process, timeout=expected_timeout
    )
    mocked_front_panel_hard_stop.assert_called_once_with(timeout=expected_timeout)


def test_OkCommunicationProcess__hard_stop__drains_all_queues_and_returns__all_items(
    four_board_comm_process,
):
    expected = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]]
    expected_error = "error"

    ok_process, board_queues, error_queue = four_board_comm_process
    for i, board in enumerate(board_queues):
        for j, queue in enumerate(board):
            item = expected[i][j]
            queue.put(item)
    assert is_queue_eventually_not_empty(board_queues[3][2]) is True
    error_queue.put(expected_error)
    assert is_queue_eventually_of_size(error_queue, 1) is True

    actual = ok_process.hard_stop()
    assert actual["fatal_error_reporter"] == [expected_error]

    assert is_queue_eventually_empty(board_queues[0][0]) is True
    assert is_queue_eventually_empty(board_queues[0][2]) is True
    assert is_queue_eventually_empty(board_queues[1][0]) is True
    assert is_queue_eventually_empty(board_queues[2][0]) is True
    assert is_queue_eventually_empty(board_queues[3][0]) is True

    assert actual["board_0"]["main_to_ok_comm"] == [expected[0][0]]
    assert expected[0][1] in actual["board_0"]["ok_comm_to_main"]
    assert actual["board_0"]["ok_comm_to_file_writer"] == [expected[0][2]]
    assert actual["board_1"]["main_to_ok_comm"] == [expected[1][0]]
    assert actual["board_2"]["main_to_ok_comm"] == [expected[2][0]]
    assert actual["board_3"]["main_to_ok_comm"] == [expected[3][0]]


@pytest.mark.parametrize(
    "test_value,expected_gain,test_description",
    [
        (0xFFFFFFF8, 1, "returns gain of 1"),
        (0x00000005, 32, "returns gain of 32"),
        (0x1234567F, 128, "returns gain of 128"),
    ],
)
def test_parse_gain__returns_correct_value(test_value, expected_gain, test_description):
    actual = parse_gain(test_value)
    assert actual == expected_gain


def test_OkCommunicationProcess_run__raises_error_if_mantarray_naming_command_is_invalid(
    four_board_comm_process, mocker
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    ok_process, board_queues, _ = four_board_comm_process

    simulator = FrontPanelSimulator({})
    ok_process.set_board_connection(0, simulator)

    input_queue = board_queues[0][0]
    expected_returned_communication = {
        "communication_type": "mantarray_naming",
        "command": "fake_command",
    }
    input_queue.put(copy.deepcopy(expected_returned_communication))
    assert is_queue_eventually_not_empty(input_queue) is True
    with pytest.raises(UnrecognizedMantarrayNamingCommandError, match="fake_command"):
        invoke_process_run_and_check_errors(ok_process)


def test_OkCommunicationProcess_run__correctly_sets_mantarray_serial_number(
    four_board_comm_process,
):
    ok_process, board_queues, _ = four_board_comm_process
    expected_serial_number = RunningFIFOSimulator.default_mantarray_serial_number

    simulator = FrontPanelSimulator({})
    simulator.set_device_id("Existing Device ID")
    ok_process.set_board_connection(0, simulator)

    input_queue = board_queues[0][0]
    expected_returned_communication = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_serial_number",
        "mantarray_serial_number": expected_serial_number,
    }
    input_queue.put(copy.deepcopy(expected_returned_communication))
    assert is_queue_eventually_not_empty(input_queue) is True

    invoke_process_run_and_check_errors(ok_process)
    actual = simulator.get_device_id()
    assert actual == expected_serial_number


@pytest.mark.parametrize(
    "test_id,expected_value,test_description",
    [
        (
            RunningFIFOSimulator.default_mantarray_serial_number,
            "",
            "returns empty string with Simulator serial number",
        ),
        (
            "M02-36700",
            "Serial Number contains invalid character: '-'",
            "returns error message with invalid character",
        ),
        (
            "M1200190",
            "Serial Number does not reach min length",
            "returns error message when too short",
        ),
        (
            "M120019000",
            "Serial Number exceeds max length",
            "returns error message when too long",
        ),
        (
            "M12001900",
            "Serial Number contains invalid header: 'M1'",
            "returns error message with invalid header",
        ),
        (
            "M01901900",
            "Serial Number contains invalid year: '19'",
            "returns error message with year 19",
        ),
        (
            "M02101900",
            "Serial Number contains invalid year: '21'",
            "returns error message with year 21",
        ),
        (
            "M02000000",
            "Serial Number contains invalid Julian date: '000'",
            "returns error message with invalid Julian date 000",
        ),
        (
            "M02036700",
            "Serial Number contains invalid Julian date: '367'",
            "returns error message with invalid Julian date 367",
        ),
    ],
)
def test_check_mantarray_serial_number__returns_correct_values(
    test_id, expected_value, test_description
):
    actual = check_mantarray_serial_number(test_id)
    assert actual == expected_value


@pytest.mark.parametrize(
    "test_device_id,test_description",
    [
        ("Not a serial number", "correctly sets nickname with normal device ID"),
        ("", "correctly sets nickname with short device ID"),
    ],
)
def test_OkCommunicationProcess_run__correctly_sets_mantarray_nickname_without_serial_number_present(
    test_device_id, test_description, four_board_comm_process
):
    ok_process, board_queues, _ = four_board_comm_process
    expected_nickname = "New Nickname"

    simulator = FrontPanelSimulator({})
    simulator.set_device_id("Not a serial number")
    ok_process.set_board_connection(0, simulator)

    input_queue = board_queues[0][0]
    expected_returned_communication = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    input_queue.put(copy.deepcopy(expected_returned_communication))
    assert is_queue_eventually_not_empty(input_queue) is True

    invoke_process_run_and_check_errors(ok_process)
    actual = simulator.get_device_id()
    assert actual == expected_nickname


def test_OkCommunicationProcess_run__correctly_sets_mantarray_nickname_with_valid_serial_number_present(
    four_board_comm_process,
):
    ok_process, board_queues, _ = four_board_comm_process
    expected_serial_number = RunningFIFOSimulator.default_mantarray_serial_number
    expected_nickname = "New Nickname"

    simulator = FrontPanelSimulator({})
    simulator.set_device_id(expected_serial_number)
    ok_process.set_board_connection(0, simulator)

    input_queue = board_queues[0][0]
    expected_returned_communication = {
        "communication_type": "mantarray_naming",
        "command": "set_mantarray_nickname",
        "mantarray_nickname": expected_nickname,
    }
    input_queue.put(copy.deepcopy(expected_returned_communication))
    assert is_queue_eventually_not_empty(input_queue) is True

    invoke_process_run_and_check_errors(ok_process)
    actual = simulator.get_device_id()
    assert actual == f"{expected_serial_number}{expected_nickname}"


@pytest.mark.parametrize(
    "expected_serial_number,expected_nickname,test_description",
    [
        (
            "M02001900",
            "My Nickname",
            "handles correctly with serial number and nickname present",
        ),
        ("", "Solo Nickname", "handles correctly without serial number present"),
        ("M02001900", "", "handles correctly without nickname present"),
        ("", "", "handles correctly with empty device ID"),
    ],
)
def test_OkCommunicationProcess_create_connections_to_all_available_boards__handles_extracting_mantarray_serial_number_and_nickname(
    expected_serial_number,
    expected_nickname,
    test_description,
    four_board_comm_process,
    mocker,
):
    ok_process, board_queues, _ = four_board_comm_process
    comm_to_main_queue = board_queues[0][1]

    device_id = f"{expected_serial_number}{expected_nickname}"
    mocker.patch.object(RunningFIFOSimulator, "get_device_id", return_value=device_id)

    ok_process.create_connections_to_all_available_boards()
    assert is_queue_eventually_not_empty(comm_to_main_queue) is True

    actual = comm_to_main_queue.get_nowait()
    assert actual["mantarray_serial_number"] == expected_serial_number
    assert actual["mantarray_nickname"] == expected_nickname


def test_OkCommunicationProcess_teardown_after_loop__sets_teardown_complete_event(
    four_board_comm_process,
    mocker,
):
    ok_process, _, _ = four_board_comm_process

    ok_process.soft_stop()
    ok_process.run(perform_setup_before_loop=False, num_iterations=1)

    assert ok_process.is_teardown_complete() is True


@freeze_time("2020-07-20 11:57:11.123456")
def test_OkCommunicationProcess_teardown_after_loop__puts_teardown_log_message_into_queue(
    four_board_comm_process,
    mocker,
):
    ok_process, board_queues, _ = four_board_comm_process
    comm_to_main_queue = board_queues[0][1]

    ok_process.soft_stop()
    ok_process.run(perform_setup_before_loop=False, num_iterations=1)
    assert is_queue_eventually_not_empty(comm_to_main_queue)

    actual = comm_to_main_queue.get_nowait()
    assert (
        actual["message"]
        == "OpalKelly Communication Process beginning teardown at 2020-07-20 11:57:11.123456"
    )


@pytest.mark.slow
@pytest.mark.timeout(6)
def test_OkCommunicationProcess_teardown_after_loop__can_teardown_while_managed_acquisition_is_running_with_simulator__and_log_stop_acquistion_message(
    running_process_with_simulated_board,
    mocker,
):
    simulator = RunningFIFOSimulator()
    ok_process, board_queues, _ = running_process_with_simulated_board(simulator)
    input_queue = board_queues[0][0]
    comm_to_main_queue = board_queues[0][1]

    input_queue.put(
        {
            "communication_type": "debug_console",
            "command": "initialize_board",
            "bit_file_name": None,
        }
    )
    input_queue.put(get_mutable_copy_of_START_MANAGED_ACQUISITION_COMMUNICATION())
    ok_process.soft_stop()
    ok_process.join()

    # TODO Tanner (8/31/20): add drain queue to other tests where applicable
    # drain the queue to avoid broken pipe errors
    actual_last_queue_item = dict()
    while True:
        try:
            actual_last_queue_item = comm_to_main_queue.get(
                timeout=QUEUE_CHECK_TIMEOUT_SECONDS
            )
        except Empty:
            break

    assert (
        actual_last_queue_item["message"]
        == "Board acquisition still running. Stopping acquisition to complete teardown"
    )


def test_OkCommunicationProcess_boot_up_instrument__with_real_board__raises_error_if_firmware_version_does_not_match_file_name(
    four_board_comm_process,
    patched_firmware_folder,
    mocker,
):
    mocker.patch(
        "builtins.print", autospec=True
    )  # don't print all the error messages to console
    ok_process, board_queues, _ = four_board_comm_process

    dummy_xem = okCFrontPanel()
    mocker.patch.object(dummy_xem, "ConfigureFPGA", autospec=True, return_value=0)
    mocker.patch.object(
        dummy_xem, "IsFrontPanelEnabled", autospec=True, return_value=True
    )
    fp_board = MantarrayFrontPanel(dummy_xem)

    expected_wire_out_version = "-1"
    mocker.patch.object(
        fp_board,
        "get_firmware_version",
        autospec=True,
        return_value=expected_wire_out_version,
    )
    ok_process.set_board_connection(0, fp_board)

    boot_up_comm = {
        "communication_type": "boot_up_instrument",
        "command": "initialize_board",
        "bit_file_name": patched_firmware_folder,
        "suppress_error": False,
        "allow_board_reinitialization": False,
    }
    board_queues[0][0].put(boot_up_comm)
    assert is_queue_eventually_not_empty(board_queues[0][0]) is True

    expected_error_msg = f"File name: {patched_firmware_folder}, Version from wire_out value: {expected_wire_out_version}"
    with pytest.raises(FirmwareFileNameDoesNotMatchWireOutVersionError) as exc_info:
        invoke_process_run_and_check_errors(ok_process)
    # Tanner (7/26/20): using match=expected_error_msg as a kwarg in pytest.raises wasn't working in windows because it always treats "\" as a regex escape character, even in an r-string. Not sure if there is a better way around this than making the following assertion
    assert exc_info.value.args[0] == expected_error_msg


def test_OkCommunicationProcess_boot_up_instrument__with_real_board__does_not_raise_error_if_firmware_version_matches_file_name(
    four_board_comm_process,
    patched_firmware_folder,
    mocker,
):
    ok_process, board_queues, _ = four_board_comm_process

    dummy_xem = okCFrontPanel()
    mocker.patch.object(dummy_xem, "ConfigureFPGA", autospec=True, return_value=0)
    mocker.patch.object(
        dummy_xem, "IsFrontPanelEnabled", autospec=True, return_value=True
    )
    fp_board = MantarrayFrontPanel(dummy_xem)

    expected_wire_out_version = "2.3.4"
    mocker.patch.object(
        fp_board,
        "get_firmware_version",
        autospec=True,
        return_value=expected_wire_out_version,
    )
    ok_process.set_board_connection(0, fp_board)

    boot_up_comm = {
        "communication_type": "boot_up_instrument",
        "command": "initialize_board",
        "bit_file_name": patched_firmware_folder,
        "suppress_error": False,
        "allow_board_reinitialization": False,
    }
    board_queues[0][0].put(boot_up_comm)
    assert is_queue_eventually_not_empty(board_queues[0][0]) is True
    invoke_process_run_and_check_errors(ok_process)

    assert is_queue_eventually_not_empty(board_queues[0][1]) is True
    response_comm = board_queues[0][1].get_nowait()
    assert response_comm["main_firmware_version"] == expected_wire_out_version
