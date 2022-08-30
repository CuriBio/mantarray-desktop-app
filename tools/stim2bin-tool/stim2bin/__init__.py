# -*- coding: utf-8 -*-
import argparse
import json
import os

from mantarray_desktop_app.utils.serial_comm import convert_stim_dict_to_bytes


"""
convert_stim_dict_to_bytes() input:
{
    'protocols': [
        {
            'protocol_id': 'A',
            'stimulation_type': 'C',
            'run_until_stopped': True,
            'subprotocols': [
                {
                    'phase_one_duration': 10000,
                    'phase_one_charge': 100000,
                    'interphase_interval': 0,
                    'phase_two_charge': 0,
                    'phase_two_duration': 0,
                    'repeat_delay_interval': 90000,
                    'total_active_duration': 1000
                }, {
                    'phase_one_duration': 5000000,
                    'phase_one_charge': 0,
                    'interphase_interval': 0,
                    'phase_two_charge': 0,
                    'phase_two_duration': 0,
                    'repeat_delay_interval': 0,
                    'total_active_duration': 5000
                }
            ]
        }
    ],
    'protocol_assignments': {
        'A1': 'A',
        'B1': 'A',
        'C1': None,
        'D1': None,
        'A2': None,
        'B2': None,
        'C2': None,
        'D2': None,
        'A3': None,
        'B3': None,
        'C3': None,
        'D3': None,
        'A4': None,
        'B4': None,
        'C4': None,
        'D4': None,
        'A5': None,
        'B5': None,
        'C5': None,
        'D5': None,
        'A6': None,
        'B6': None,
        'C6': None,
        'D6': None
    }
}
"""
UNIT_CONVERSION = {"C": 1000, "V": 1}


def main() -> None:
    parser = argparse.ArgumentParser(description="Process some integers.")
    parser.add_argument("--file", type=str, default=None)
    parser.add_argument("--output_dir", type=str, default=None)
    args = parser.parse_args()

    try:
        # user can send desired path, otherwise will just write to desktop
        output_dir = os.path.expanduser("~/Desktop") if not args.output_dir else args.output_dir
        # make directories if none exists
        os.makedirs(output_dir, exist_ok=True)
        file_name = os.path.basename(os.path.splitext(args.file)[0])
        complete_output_path = os.path.join(output_dir, f"{file_name}.bin")
        # load json file
        print(f"Opening file: {args.file}")
        with open(args.file, "rb") as f:
            print("Loading json and processing stim data")
            parsed_stim = json.load(f)

        stim_dict = {"protocols": [], "protocol_assignments": parsed_stim["protocol_assignments"]}
        for protocol in parsed_stim["protocols"]:
            protocol_details = protocol["protocol"]
            stim_type = protocol_details["stimulation_type"]
            converted_pulses = [
                {
                    "phase_one_duration": p["phase_one_duration"] * 1000,
                    "phase_one_charge": p["phase_one_charge"] * UNIT_CONVERSION[stim_type],
                    "interphase_interval": p["interphase_interval"] * 1000,
                    "phase_two_charge": p["phase_two_charge"] * UNIT_CONVERSION[stim_type],
                    "phase_two_duration": p["phase_two_duration"] * 1000,
                    "repeat_delay_interval": round(p["repeat_delay_interval"] * 1000, 1),
                    "total_active_duration": p["total_active_duration"],
                }
                for p in protocol_details["pulses"]
            ]

            stim_dict["protocols"].append(
                {
                    "protocol_id": protocol["letter"],
                    "stimulation_type": stim_type,
                    "run_until_stopped": protocol_details["stop_setting"] == "Stimulate Until Stopped",
                    "subprotocols": converted_pulses,
                }
            )

        print("Converting stim data to bytes")
        bytes_to_write = convert_stim_dict_to_bytes(stim_dict)

        print(f"Writing bytes to {complete_output_path}")
        with open(complete_output_path, "w+b") as f:
            f.write(bytes_to_write)

        print("Done")
    except Exception as e:
        print(f"Job failed with error: {e}")
