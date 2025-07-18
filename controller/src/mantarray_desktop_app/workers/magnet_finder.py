# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from mantarray_magnet_finding.exceptions import UnableToConvergeError
from pulse3D.plate_recording import PlateRecording

from ..constants import GENERIC_24_WELL_DEFINITION
from ..constants import MICRO_TO_BASE_CONVERSION


ALL_VALID_WELL_NAMES = {
    GENERIC_24_WELL_DEFINITION.get_well_name_from_well_index(well_idx) for well_idx in range(24)
}


def run_magnet_finding_alg(
    result_dict: Dict[str, Any],
    recordings: List[str],
    output_dir: Optional[str] = None,
    end_time: Optional[Union[float, int]] = None,
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

        is_recording_snapshot = output_dir == tmpdir

        for rec_path in recordings:
            try:
                # copy existing h5 directories to temp directory
                recording_name = os.path.basename(rec_path)
                recording_copy_path = os.path.join(tmpdir, recording_name)
                shutil.copytree(rec_path, recording_copy_path)

                pr = PlateRecording(recording_copy_path, end_time=end_time)
                # TODO remove this once pulse3d fixes this bug
                df = pr.to_dataframe(include_stim_data=False)

                # remove unnecessary columns from df
                columns_to_drop = [c for c in df.columns if c not in ("Time (s)", *ALL_VALID_WELL_NAMES)]
                df.drop(columns_to_drop, inplace=True, axis=1)

                # Tanner (3/22/23): dropping NaN values just to be safe, although to_dataframe should handle this
                df.dropna(inplace=True)

                # to_dataframe sends µs, convert to seconds
                df["Time (s)"] /= MICRO_TO_BASE_CONVERSION

                if is_recording_snapshot:
                    analysis_dfs.append(df)
                else:
                    output_path = os.path.join(output_dir, f"{recording_name}.csv")
                    df.to_csv(output_path)

            except UnableToConvergeError:
                failed_recordings.append(
                    {
                        "name": recording_name,
                        "error": "Unable to process recording due to low quality calibration and/or noise",
                    }
                )
            except Exception as e:
                # Leaving in plain text because this error message is used directly in pop up modal to user when rec snapshot fails
                # It is never displayed to user in local analysis
                failed_recordings.append(
                    {"name": recording_name, "error": "Something went wrong", "expanded_err": repr(e)}
                )

    if failed_recordings:
        result_dict["failed_recordings"] = failed_recordings

    return analysis_dfs
