# -*- coding: utf-8 -*-
import os
from typing import Any
from typing import Dict

import pandas as pd
from pulse3D.plate_recording import PlateRecording


def run_mag_finding_analysis(file_path: str, recording_name: str, output_dir: str) -> Any:
    # generate time force data
    prs = PlateRecording.from_directory(file_path)

    # write csv files to output directory
    time_force_dict: Dict[str, pd.DataFrame] = dict()
    for pr in prs:
        output_path = os.path.join(output_dir, f"{recording_name}.csv")
        # set first column to time points
        force_data = dict({"Time (microseconds)": pd.Series(pr.wells[0].force[0])})
        for idx, well in enumerate(pr):
            force_data[str(idx)] = pd.Series(well.force[1])

        time_force_df = pd.DataFrame(force_data)
        time_force_df.to_csv(output_path, index=False)
        time_force_dict[recording_name] = time_force_df

    return time_force_df, output_path
