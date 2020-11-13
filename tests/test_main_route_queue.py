# -*- coding: utf-8 -*-
import datetime

from freezegun import freeze_time
from mantarray_desktop_app import ADC_GAIN_SETTING_UUID
from mantarray_desktop_app import COMPILED_EXE_BUILD_TIMESTAMP
from mantarray_desktop_app import CURRENT_SOFTWARE_VERSION
from mantarray_desktop_app import CUSTOMER_ACCOUNT_ID_UUID
from mantarray_desktop_app import MAIN_FIRMWARE_VERSION_UUID
from mantarray_desktop_app import MANTARRAY_NICKNAME_UUID
from mantarray_desktop_app import MANTARRAY_SERIAL_NUMBER_UUID
from mantarray_desktop_app import PLATE_BARCODE_UUID
from mantarray_desktop_app import REFERENCE_VOLTAGE
from mantarray_desktop_app import REFERENCE_VOLTAGE_UUID
from mantarray_desktop_app import SLEEP_FIRMWARE_VERSION_UUID
from mantarray_desktop_app import SOFTWARE_RELEASE_VERSION_UUID
from mantarray_desktop_app import START_RECORDING_TIME_INDEX_UUID
from mantarray_desktop_app import USER_ACCOUNT_ID_UUID
from mantarray_desktop_app import UTC_BEGINNING_DATA_ACQUISTION_UUID
from mantarray_desktop_app import UTC_BEGINNING_RECORDING_UUID
from mantarray_desktop_app import XEM_SERIAL_NUMBER_UUID
from mantarray_file_manager import HARDWARE_TEST_RECORDING_UUID
from mantarray_file_manager import SOFTWARE_BUILD_NUMBER_UUID
from mantarray_waveform_analysis import CENTIMILLISECONDS_PER_SECOND

from .fixtures import fixture_fully_running_app_from_main_entrypoint
from .fixtures import fixture_patched_shared_values_dict
from .fixtures import fixture_patched_start_recording_shared_dict
from .fixtures import fixture_test_client
from .fixtures import fixture_test_process_manager
from .fixtures_file_writer import GENERIC_START_RECORDING_COMMAND
from .helpers import is_queue_eventually_not_empty


__fixtures__ = [
    fixture_test_process_manager,
    fixture_patched_shared_values_dict,
    fixture_patched_start_recording_shared_dict,
    fixture_fully_running_app_from_main_entrypoint,
    fixture_test_client,
]


@freeze_time(
    datetime.datetime(
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598
    )
    + datetime.timedelta(
        seconds=GENERIC_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
        / CENTIMILLISECONDS_PER_SECOND
    )
)
def test_start_recording_command__populates_queue__with_defaults__24_wells__utcnow_recording_start_time__and_metadata(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_acquisition_timestamp = datetime.datetime(  # pylint: disable=duplicate-code
        year=2020, month=2, day=11, hour=19, minute=3, second=22, microsecond=332598
    )
    expected_recording_timepoint = GENERIC_START_RECORDING_COMMAND[
        "timepoint_to_begin_recording_at"
    ]
    expected_recording_timestamp = expected_acquisition_timestamp + datetime.timedelta(
        seconds=(expected_recording_timepoint / CENTIMILLISECONDS_PER_SECOND)
    )

    patched_start_recording_shared_dict[
        "utc_timestamps_of_beginning_of_data_acquisition"
    ] = [expected_acquisition_timestamp]

    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["command"] == "start_recording"

    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_DATA_ACQUISTION_UUID
        ]
        == expected_acquisition_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            UTC_BEGINNING_RECORDING_UUID
        ]
        == expected_recording_timestamp
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            CUSTOMER_ACCOUNT_ID_UUID
        ]
        == patched_start_recording_shared_dict["config_settings"]["Customer Account ID"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            USER_ACCOUNT_ID_UUID
        ]
        == patched_start_recording_shared_dict["config_settings"]["User Account ID"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            START_RECORDING_TIME_INDEX_UUID
        ]
        == expected_recording_timepoint
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            SOFTWARE_BUILD_NUMBER_UUID
        ]
        == COMPILED_EXE_BUILD_TIMESTAMP
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            SOFTWARE_RELEASE_VERSION_UUID
        ]
        == CURRENT_SOFTWARE_VERSION
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            MAIN_FIRMWARE_VERSION_UUID
        ]
        == patched_start_recording_shared_dict["main_firmware_version"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            SLEEP_FIRMWARE_VERSION_UUID
        ]
        == patched_start_recording_shared_dict["sleep_firmware_version"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            XEM_SERIAL_NUMBER_UUID
        ]
        == patched_start_recording_shared_dict["xem_serial_number"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            MANTARRAY_SERIAL_NUMBER_UUID
        ]
        == patched_start_recording_shared_dict["mantarray_serial_number"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            MANTARRAY_NICKNAME_UUID
        ]
        == patched_start_recording_shared_dict["mantarray_nickname"][0]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            REFERENCE_VOLTAGE_UUID
        ]
        == REFERENCE_VOLTAGE
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            ADC_GAIN_SETTING_UUID
        ]
        == patched_start_recording_shared_dict["adc_gain"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"]
        == patched_start_recording_shared_dict["adc_offsets"]
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][PLATE_BARCODE_UUID]
        == expected_barcode
    )
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            HARDWARE_TEST_RECORDING_UUID
        ]
        is False
    )

    assert (
        communication["timepoint_to_begin_recording_at"]
        == GENERIC_START_RECORDING_COMMAND["timepoint_to_begin_recording_at"]
    )
    assert set(communication["active_well_indices"]) == set(range(24))
    response_json = response.get_json()
    assert response_json["command"] == "start_recording"


def test_start_recording_command__populates_queue__with_correctly_parsed_set_of_well_indices(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={expected_barcode}&active_well_indices=0,5,8&is_hardware_test_recording=False"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["command"] == "start_recording"
    assert set(communication["active_well_indices"]) == set([0, 8, 5])


def test_start_recording_command__populates_queue__with_given_time_index_parameter(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_time_index = 1000
    barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(
        f"/start_recording?barcode={barcode}&time_index={expected_time_index}&is_hardware_test_recording=false"
    )
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["command"] == "start_recording"
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"][
            START_RECORDING_TIME_INDEX_UUID
        ]
        == expected_time_index
    )
    assert communication["timepoint_to_begin_recording_at"] == expected_time_index


def test_start_recording_command__populates_queue__with_correct_adc_offset_values_if_is_hardware_test_recording_is_true(
    test_process_manager, test_client, mocker, patched_start_recording_shared_dict
):
    expected_adc_offsets = dict()
    for well_idx in range(24):
        expected_adc_offsets[well_idx] = {"construct": 0, "ref": 0}

    barcode = GENERIC_START_RECORDING_COMMAND[
        "metadata_to_copy_onto_main_file_attributes"
    ][PLATE_BARCODE_UUID]
    response = test_client.get(f"/start_recording?barcode={barcode}")
    assert response.status_code == 200

    comm_queue = test_process_manager.get_communication_queue_from_main_to_file_writer()
    assert is_queue_eventually_not_empty(comm_queue) is True
    communication = comm_queue.get_nowait()
    assert communication["command"] == "start_recording"
    assert (
        communication["metadata_to_copy_onto_main_file_attributes"]["adc_offsets"]
        == expected_adc_offsets
    )
