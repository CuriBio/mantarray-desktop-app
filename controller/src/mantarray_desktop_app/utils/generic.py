# -*- coding: utf-8 -*-
"""Misc utility functions."""
from __future__ import annotations

from collections import defaultdict
from collections import deque
import copy
import datetime
import glob
import json
import logging
import os
import re
import tempfile
from typing import Any
from typing import Deque
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from uuid import UUID

import psutil
from pulse3D.constants import ADC_GAIN_SETTING_UUID
from pulse3D.constants import BACKEND_LOG_UUID
from pulse3D.constants import BOOT_FLAGS_UUID
from pulse3D.constants import CHANNEL_FIRMWARE_VERSION_UUID
from pulse3D.constants import COMPUTER_NAME_HASH_UUID
from pulse3D.constants import CUSTOMER_ACCOUNT_ID_UUID
from pulse3D.constants import HARDWARE_TEST_RECORDING_UUID
from pulse3D.constants import INITIAL_MAGNET_FINDING_PARAMS_UUID
from pulse3D.constants import MAIN_FIRMWARE_VERSION_UUID
from pulse3D.constants import MANTARRAY_NICKNAME_UUID
from pulse3D.constants import MANTARRAY_SERIAL_NUMBER_UUID
from pulse3D.constants import MAX_MINI_SKM_EXPERIMENT_ID
from pulse3D.constants import NOT_APPLICABLE_H5_METADATA
from pulse3D.constants import NUM_INITIAL_MICROSECONDS_TO_REMOVE_UUID
from pulse3D.constants import PLATE_BARCODE_IS_FROM_SCANNER_UUID
from pulse3D.constants import PLATE_BARCODE_UUID
from pulse3D.constants import REFERENCE_VOLTAGE_UUID
from pulse3D.constants import SLEEP_FIRMWARE_VERSION_UUID
from pulse3D.constants import SOFTWARE_BUILD_NUMBER_UUID
from pulse3D.constants import SOFTWARE_RELEASE_VERSION_UUID
from pulse3D.constants import START_RECORDING_TIME_INDEX_UUID
from pulse3D.constants import STIM_BARCODE_IS_FROM_SCANNER_UUID
from pulse3D.constants import STIM_BARCODE_UUID
from pulse3D.constants import TISSUE_SAMPLING_PERIOD_UUID
from pulse3D.constants import USER_ACCOUNT_ID_UUID
from pulse3D.constants import USER_DEFINED_METADATA_UUID
from pulse3D.constants import UTC_BEGINNING_DATA_ACQUISTION_UUID
from pulse3D.constants import UTC_BEGINNING_RECORDING_UUID
from pulse3D.constants import XEM_SERIAL_NUMBER_UUID
from semver import VersionInfo
from stdlib_utils import get_current_file_abs_directory
from stdlib_utils import is_frozen_as_exe

from .web_api import AuthTokens
from .web_api import get_cloud_api_tokens
from ..constants import ALL_VALID_BARCODE_HEADERS
from ..constants import BARCODE_HEADERS
from ..constants import BARCODE_LEN
from ..constants import CENTIMILLISECONDS_PER_SECOND
from ..constants import COMPILED_EXE_BUILD_TIMESTAMP
from ..constants import CURRENT_SOFTWARE_VERSION
from ..constants import DEFAULT_SAMPLING_PERIOD
from ..constants import GENERIC_24_WELL_DEFINITION
from ..constants import MICRO_TO_BASE_CONVERSION
from ..constants import MICROSECONDS_PER_CENTIMILLISECOND
from ..constants import NUM_INITIAL_MICROSECONDS_TO_PAD
from ..constants import PLATE_BARCODE_ENTRY_TIME
from ..constants import REFERENCE_VOLTAGE
from ..constants import STIM_BARCODE_ENTRY_TIME
from ..exceptions import RecordingFolderDoesNotExistError
from ..workers.file_uploader import FileUploader

logger = logging.getLogger(__name__)


class CommandTracker:
    def __init__(self) -> None:
        self._command_order: Deque[int] = deque()
        self._command_mapping: Dict[int, Deque[Dict[str, Any]]] = defaultdict(deque)

    def add(self, packet_type: int, command_dict: Dict[str, Any]) -> None:
        self._command_order.append(packet_type)
        self._command_mapping[packet_type].append(command_dict)

    def oldest(self) -> Dict[str, Any]:
        try:
            packet_type_of_oldest = self._command_order[0]
        except IndexError as e:
            raise IndexError("Tracker is empty") from e

        return self._command_mapping[packet_type_of_oldest][0]

    def pop(self, packet_type: int) -> Dict[str, Any]:
        try:
            self._command_order.remove(packet_type)
        except ValueError as e:
            raise ValueError(f"No commands of packet type: {packet_type}") from e

        command = self._command_mapping[packet_type].popleft()

        if not self._command_mapping[packet_type]:
            del self._command_mapping[packet_type]

        return command

    def __bool__(self) -> bool:
        return bool(self._command_order)


def validate_settings(settings_dict: Dict[str, Any]) -> None:
    """Check if potential new user configuration settings are valid.

    Args:
        settings_dict: dictionary containing the new user configuration settings.
    """
    if recording_directory := settings_dict.get("recording_directory"):
        if not os.path.isdir(recording_directory):
            raise RecordingFolderDoesNotExistError(recording_directory)


def validate_user_credentials(request_args: Dict[str, Any]) -> Optional[Tuple[AuthTokens, Dict[str, Any]]]:
    """Validate users creds using cloud login.

    Args:
        request_args: dictionary containing the new user configuration settings.
        shared_values_dict: dictionary containing stored customer settings.
    """
    cloud_response = None
    if customer_id := request_args.get("customer_id"):
        user_name = request_args["user_name"]
        user_password = request_args["user_password"]
        cloud_response = get_cloud_api_tokens(customer_id, user_name, user_password)

    return cloud_response


def convert_request_args_to_config_dict(request_args: Dict[str, Any]) -> Dict[str, Any]:
    """Convert request inputs to correctly formatted dict.

    Also filters out args that are not given

    Args should be validated before being passed to this function.
    """
    config_dict: Dict[str, Any] = dict()

    for arg in ("customer_id", "user_password", "user_name", "recording_directory", "pulse3d_version"):
        if arg_val := request_args.get(arg):
            config_dict[arg] = arg_val

    for arg, new_arg_name in (
        ("auto_upload", "auto_upload_on_completion"),
        ("auto_delete", "auto_delete_local_files"),
    ):
        if arg_bool_str := request_args.get(arg):
            config_dict[new_arg_name] = arg_bool_str.lower() == "true"

    return config_dict


def redact_sensitive_info(communication: Dict[str, Any]) -> Dict[str, Any]:
    communication_type = communication.get("communication_type")
    command = communication.get("command")

    if "mantarray_nickname" in communication:
        # Tanner (1/20/21): items in communication dict are used after this log message is generated, so need to create a copy of the dict when redacting info
        comm_copy = copy.deepcopy(communication)
        comm_copy["mantarray_nickname"] = get_redacted_string(len(comm_copy["mantarray_nickname"]))
    elif communication_type == "update_user_settings":
        comm_copy = copy.deepcopy(communication)
        _redact_user_creds(comm_copy["content"])
    elif command == "update_user_settings":
        comm_copy = copy.deepcopy(communication)
        _redact_user_creds(comm_copy["config_settings"])
    elif communication_type == "mag_finding_analysis":
        comm_copy = copy.deepcopy(communication)
        comm_copy["recordings"] = [
            redact_sensitive_info_from_path(recording_path) for recording_path in comm_copy["recordings"]
        ]
    elif communication_type == "mag_analysis_complete":
        data_type = communication["content"]["data_type"]
        comm_copy = {
            "communication_type": "mag_analysis_complete",
            # make a shallow copy so all the data isn't copied
            "content": copy.copy(communication["content"]),
        }
        if data_type == "recording_snapshot_data":
            comm_copy["content"].pop("data_json")
    elif communication_type == "metadata_comm":
        comm_copy = copy.deepcopy(communication)
        comm_copy["metadata"][MANTARRAY_NICKNAME_UUID] = get_redacted_string(
            len(comm_copy["metadata"][MANTARRAY_NICKNAME_UUID])
        )
    elif communication_type == "stimulation" and command == "start_stim_checks":
        comm_copy = copy.deepcopy(communication)
        for sub_dict_name in ("stimulator_circuit_statuses", "adc_readings"):
            if sub_dict := comm_copy.get(sub_dict_name):
                for well_idx in sorted(sub_dict):
                    well_name = GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx)
                    sub_dict[well_name] = sub_dict.pop(well_idx)
    else:
        comm_copy = copy.copy(communication)

    return comm_copy


def _redact_user_creds(comm: Dict[str, Any]) -> None:
    for setting_name in comm:
        if setting_name in ("user_password", "user_name"):
            comm[setting_name] = get_redacted_string(4)


def redact_sensitive_info_from_path(file_path: Optional[str]) -> Optional[str]:
    """Scrubs username from file path to protect sensitive info."""
    if file_path is None:
        return None
    split_path = re.split(r"(Users\\)(.*)(\\AppData)", file_path)
    if len(split_path) != 5:
        return get_redacted_string(len(file_path))
    scrubbed_path = split_path[0] + split_path[1]
    scrubbed_path += get_redacted_string(len(split_path[2]))
    scrubbed_path += split_path[3] + split_path[4]
    return scrubbed_path


def get_redacted_string(length: int) -> str:
    return "*" * length


def get_current_software_version() -> str:
    """Return the current software version.

    Returns the constant if running in a bundle. Otherwise reads it from
    package.json
    """
    if is_frozen_as_exe():
        return CURRENT_SOFTWARE_VERSION
    path_to_package_json = os.path.join(
        get_current_file_abs_directory(), *([os.pardir] * 4), "electron", "package.json"
    )
    with open(path_to_package_json) as in_file:
        parsed_json = json.load(in_file)
        version = parsed_json["version"]
        if not isinstance(version, str):
            raise NotImplementedError(
                f"The version in package.json should always be a string. It was: {version}"
            )
        return version


def check_barcode_for_errors(barcode: str, beta_2_mode: bool, barcode_type: Optional[str] = None) -> str:
    """Return error message if barcode contains an error.

    barcode_type kwarg should always be given unless checking a scanned
    barcode value.
    """
    if len(barcode) != BARCODE_LEN:
        return "barcode is incorrect length"
    header = barcode[:2]
    if header not in BARCODE_HEADERS.get(barcode_type, ALL_VALID_BARCODE_HEADERS):
        return f"barcode contains invalid header: '{header}'"
    if "-" in barcode:
        barcode_check_err = _check_new_barcode(barcode, beta_2_mode)
    else:
        barcode_check_err = _check_old_barcode(barcode)
    return barcode_check_err


def _check_new_barcode(barcode: str, beta_2_mode: bool) -> str:
    for char in barcode[2:10] + barcode[-1]:
        if not char.isnumeric():
            return f"barcode contains invalid character: '{char}'"
    if int(barcode[2:4]) < 22:
        return f"barcode contains invalid year: '{barcode[2:4]}'"
    if not 0 < int(barcode[4:7]) < 366:
        return f"barcode contains invalid Julian date: '{barcode[4:7]}'"
    if not 0 <= int(barcode[7:10]) <= MAX_MINI_SKM_EXPERIMENT_ID:
        return f"barcode contains invalid experiment id: '{barcode[7:10]}'"
    # final digit must equal beta version (1/2)
    last_digit = int(barcode[-1])
    if last_digit != 1 + int(beta_2_mode):
        return f"barcode contains invalid last digit: '{last_digit}'"
    return ""


def _check_old_barcode(barcode: str) -> str:
    for char in barcode[2:]:
        if not char.isnumeric():
            return f"barcode contains invalid character: '{char}'"
    if int(barcode[2:6]) < 2021:
        return f"barcode contains invalid year: '{barcode[2:6]}'"
    if not 0 < int(barcode[6:9]) < 366:
        return f"barcode contains invalid Julian date: '{barcode[6:9]}'"
    return ""


def check_barcode_is_valid(barcode: str, mode: bool) -> bool:
    error_msg = check_barcode_for_errors(barcode, mode)
    return error_msg == ""


def _trim_barcode(barcode: str) -> str:
    """Trim the trailing 1 or 2 ASCII NULL (0x00) characters off barcode."""
    if barcode[11] != chr(0):
        return barcode
    if barcode[10] != chr(0):
        return barcode[:11]
    return barcode[:10]


def _create_start_recording_command(
    shared_values_dict: Dict[str, Any],
    *,
    recording_name: Optional[str] = None,
    time_index: Optional[Union[str, int]] = 0,
    active_well_indices: Optional[List[int]] = None,
    barcodes: Optional[Dict[str, Union[str, UUID]]] = None,
    platemap_info: Optional[Dict[str, Any]] = None,
    is_calibration_recording: bool = False,
    is_hardware_test_recording: bool = False,
    plate_barcode_entry_time: str | None = None,
    stim_barcode_entry_time: str | None = None,
) -> Dict[str, Any]:
    board_idx = 0  # board index 0 hardcoded for now

    timestamp_of_sample_idx_zero = _get_timestamp_of_acquisition_sample_index_zero(shared_values_dict)

    begin_time_index: Union[int, float]
    timestamp_of_begin_recording = datetime.datetime.utcnow()
    if time_index is not None:
        begin_time_index = int(time_index)
        if not shared_values_dict["beta_2_mode"]:
            begin_time_index /= MICROSECONDS_PER_CENTIMILLISECOND
    else:
        time_since_index_0 = timestamp_of_begin_recording - timestamp_of_sample_idx_zero
        begin_time_index = time_since_index_0.total_seconds() * (
            MICRO_TO_BASE_CONVERSION if shared_values_dict["beta_2_mode"] else CENTIMILLISECONDS_PER_SECOND
        )

    if shared_values_dict["beta_2_mode"]:
        begin_time_index = max(0, begin_time_index - NUM_INITIAL_MICROSECONDS_TO_PAD)

    if not active_well_indices:
        active_well_indices = list(range(24))

    if not barcodes:
        barcodes = {"plate_barcode": NOT_APPLICABLE_H5_METADATA, "stim_barcode": NOT_APPLICABLE_H5_METADATA}

    plate_barcode_entry_time = _process_barcode_entry_time(plate_barcode_entry_time)  # type: ignore
    stim_barcode_entry_time = _process_barcode_entry_time(stim_barcode_entry_time)  # type: ignore

    barcode_match_dict: Dict[str, Union[bool, UUID]] = {}
    for barcode_type, barcode in barcodes.items():
        if isinstance(barcode, str):
            barcode_match_dict[barcode_type] = _check_scanned_barcode_vs_user_value(
                barcode, barcode_type, shared_values_dict
            )
        else:
            barcode_match_dict[barcode_type] = NOT_APPLICABLE_H5_METADATA
            if barcode_type == "plate_barcode":  # pragma: no cover:
                plate_barcode_entry_time = NOT_APPLICABLE_H5_METADATA
            else:  # pragma: no cover
                stim_barcode_entry_time = NOT_APPLICABLE_H5_METADATA

    customer_id = shared_values_dict["config_settings"].get("customer_id", NOT_APPLICABLE_H5_METADATA)
    user_name = shared_values_dict["config_settings"].get("user_name", NOT_APPLICABLE_H5_METADATA)

    formatted_platemap_info = {
        "name": str(NOT_APPLICABLE_H5_METADATA),
        "labels": [str(NOT_APPLICABLE_H5_METADATA)] * 24,
    }
    if platemap_info:
        formatted_platemap_info["name"] = platemap_info["map_name"]
        for label_info in platemap_info["labels"]:
            for well_idx in label_info["wells"]:
                formatted_platemap_info["labels"][well_idx] = label_info["name"]  # type: ignore

    comm_dict: Dict[str, Any] = {
        "communication_type": "recording",
        "command": "start_recording",
        "timepoint_to_begin_recording_at": begin_time_index,
        "active_well_indices": active_well_indices,
        "platemap": formatted_platemap_info,
        "is_calibration_recording": is_calibration_recording,
        "is_hardware_test_recording": is_hardware_test_recording,
        "metadata_to_copy_onto_main_file_attributes": {
            BACKEND_LOG_UUID: shared_values_dict["log_file_id"],
            COMPUTER_NAME_HASH_UUID: shared_values_dict["computer_name_hash"],
            HARDWARE_TEST_RECORDING_UUID: is_hardware_test_recording,
            UTC_BEGINNING_DATA_ACQUISTION_UUID: timestamp_of_sample_idx_zero,
            START_RECORDING_TIME_INDEX_UUID: begin_time_index,
            UTC_BEGINNING_RECORDING_UUID: timestamp_of_begin_recording,
            CUSTOMER_ACCOUNT_ID_UUID: customer_id,
            USER_ACCOUNT_ID_UUID: user_name,
            SOFTWARE_BUILD_NUMBER_UUID: COMPILED_EXE_BUILD_TIMESTAMP,
            SOFTWARE_RELEASE_VERSION_UUID: CURRENT_SOFTWARE_VERSION,
            MAIN_FIRMWARE_VERSION_UUID: shared_values_dict["main_firmware_version"][board_idx],
            MANTARRAY_SERIAL_NUMBER_UUID: shared_values_dict["mantarray_serial_number"][board_idx],
            MANTARRAY_NICKNAME_UUID: shared_values_dict["mantarray_nickname"][board_idx],
            PLATE_BARCODE_UUID: barcodes["plate_barcode"],
            PLATE_BARCODE_IS_FROM_SCANNER_UUID: barcode_match_dict["plate_barcode"],
            PLATE_BARCODE_ENTRY_TIME: plate_barcode_entry_time,
            STIM_BARCODE_UUID: barcodes["stim_barcode"],
            STIM_BARCODE_IS_FROM_SCANNER_UUID: barcode_match_dict["stim_barcode"],
            STIM_BARCODE_ENTRY_TIME: stim_barcode_entry_time,
        },
    }
    if shared_values_dict["beta_2_mode"]:
        instrument_metadata = shared_values_dict["instrument_metadata"][board_idx]
        comm_dict["metadata_to_copy_onto_main_file_attributes"].update(
            {
                BOOT_FLAGS_UUID: instrument_metadata[BOOT_FLAGS_UUID],
                CHANNEL_FIRMWARE_VERSION_UUID: instrument_metadata[CHANNEL_FIRMWARE_VERSION_UUID],
                TISSUE_SAMPLING_PERIOD_UUID: DEFAULT_SAMPLING_PERIOD,
                INITIAL_MAGNET_FINDING_PARAMS_UUID: json.dumps(
                    dict(instrument_metadata[INITIAL_MAGNET_FINDING_PARAMS_UUID])
                ),
                NUM_INITIAL_MICROSECONDS_TO_REMOVE_UUID: NUM_INITIAL_MICROSECONDS_TO_PAD,
                USER_DEFINED_METADATA_UUID: json.dumps({}),
            }
        )
    else:
        adc_offsets: Dict[int, Dict[str, int]]
        if is_hardware_test_recording:
            adc_offsets = dict()
            for well_idx in range(24):
                adc_offsets[well_idx] = {"construct": 0, "ref": 0}
        else:
            adc_offsets = shared_values_dict["adc_offsets"]
        comm_dict["metadata_to_copy_onto_main_file_attributes"].update(
            {
                SLEEP_FIRMWARE_VERSION_UUID: shared_values_dict["sleep_firmware_version"][board_idx],
                XEM_SERIAL_NUMBER_UUID: shared_values_dict["xem_serial_number"][board_idx],
                REFERENCE_VOLTAGE_UUID: REFERENCE_VOLTAGE,
                ADC_GAIN_SETTING_UUID: shared_values_dict["adc_gain"],
                "adc_offsets": adc_offsets,
            }
        )

    if recording_name:
        comm_dict["recording_name"] = recording_name

    return comm_dict


def _process_barcode_entry_time(datetime_str: str | None) -> datetime.datetime | UUID:  # pragma: no cover
    if datetime_str is None:
        return NOT_APPLICABLE_H5_METADATA  # type: ignore
    try:
        return datetime.datetime.fromisoformat(datetime_str[:-1] + "+00:00")
    except Exception:
        return NOT_APPLICABLE_H5_METADATA  # type: ignore


def _check_scanned_barcode_vs_user_value(
    barcode: str, barcode_type: str, shared_values_dict: Dict[str, Any]
) -> bool:
    board_idx = 0  # board index 0 hardcoded for now
    if "barcodes" not in shared_values_dict:
        # Tanner (1/11/21): Guard against edge case where start_recording route is called before a scanned barcode is stored since this can take up to 15 seconds
        return False
    result: bool = shared_values_dict["barcodes"][board_idx].get(barcode_type) == barcode
    return result


def _get_timestamp_of_acquisition_sample_index_zero(  # yeah, it's kind of long, but Eli (2/27/20) doesn't know a good way to shorten it
    shared_values_dict: Dict[str, Any]
) -> datetime.datetime:
    board_idx = 0  # board index 0 hardcoded for now
    timestamp_of_sample_idx_zero: datetime.datetime = shared_values_dict[
        "utc_timestamps_of_beginning_of_data_acquisition"
    ][board_idx]
    return timestamp_of_sample_idx_zero


def set_this_process_high_priority() -> None:  # pragma: no cover
    p = psutil.Process(os.getpid())
    try:
        nice_value = psutil.REALTIME_PRIORITY_CLASS
    except AttributeError:
        nice_value = -10
    p.nice(nice_value)


def upload_log_files_to_s3(config_settings: Dict[str, str]) -> None:
    if not config_settings.get("auto_upload_on_completion", False):
        logger.info("Auto-upload is not turned on, skipping upload of log files.")
        return

    log_file_dir = config_settings["log_directory"]
    if not log_file_dir:
        logger.info("Skipping upload of log files to s3 because no log files were created")
        return

    logger.info("Attempting upload of log files to s3")

    file_directory = os.path.dirname(log_file_dir)
    sub_dir_name = os.path.basename(log_file_dir)

    customer_id = config_settings["customer_id"]
    user_name = config_settings["user_name"]
    user_password = config_settings["user_password"]

    with tempfile.TemporaryDirectory() as zipped_dir:
        try:
            file_uploader = FileUploader(
                file_directory, sub_dir_name, zipped_dir, customer_id, user_name, user_password
            )
            file_uploader()
        except Exception as e:
            logger.error(f"Failed to upload log files to s3: {repr(e)}")
        else:
            logger.info("Successfully uploaded session logs to s3")


def _semver_gt(version_a: str, version_b: str) -> bool:
    """Determine if Version A is greater than Version B."""
    return VersionInfo.parse(version_a) > VersionInfo.parse(version_b)  # type: ignore


def get_info_of_recordings(recording_dir: str) -> List[Dict[str, str]]:
    return [
        {
            "name": dir,
            "creation_time": datetime.datetime.fromtimestamp(
                os.stat(os.path.join(recording_dir, dir)).st_mtime
            ).strftime("%m-%d-%Y %H:%M.%S"),
        }
        for dir in os.listdir(recording_dir)
        if glob.glob(os.path.join(recording_dir, dir, "*.h5"), recursive=True)
    ]
