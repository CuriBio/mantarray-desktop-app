# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import numpy as np
from pulse3D.plate_recording import PlateRecording


def run_magnet_finding_alg(
    result_dict: Dict[str, Any],
    recordings: List[str],
    output_dir: Optional[str] = None,
    end_time: Union[float, int] = np.inf,
) -> List[Any]:
    """Run magnet finding analysis on the given recordings.

    Args:
        result_dict: dict to store results. Necessary if running this function in a worker thread
        recordings: a list of paths to recording directories of h5 files
        output_dir: path to the time_force_data directory
        end_time: time point to stop analysis
    """
    analysis_dfs = list()
    failed_recordings = list()

    with tempfile.TemporaryDirectory() as tmpdir:
        # if no output dir is given, assume the output files can be discarded after processing and store them in the temp dir
        if not output_dir:
            output_dir = tmpdir

        for rec_path in recordings:
            try:
                # copy existing h5 directories to temp directory
                recording_name = os.path.basename(rec_path)
                recording_copy_path = os.path.join(tmpdir, recording_name)
                shutil.copytree(rec_path, recording_copy_path)

                pr = PlateRecording(recording_copy_path, end_time=end_time)
                df, _ = pr.write_time_force_csv(output_dir)

                # only store dataframes if writing csv to tmpdir. Assume they are not needed here if writing csv to a permanent file
                if output_dir == tmpdir:
                    analysis_dfs.append(df)

            except Exception as e:
                failed_recordings.append({"name": recording_name, "error": repr(e)})

    if failed_recordings:
        result_dict["failed_recordings"] = failed_recordings

    return analysis_dfs
