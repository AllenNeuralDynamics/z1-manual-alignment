import alignment.utils as utils
import json
import math
import os
import subprocess
from pathlib import Path
from time import time
from typing import List, Optional, Tuple 
from aind_data_schema.core.processing import DataProcess, ProcessName

"""
Computes stitching transformations using
bigstitcher for SmartSPIM data structure
"""

def get_estimated_downsample(
    voxel_resolution: List[float], phase_corr_res: Tuple[float] = (8.0, 8.0, 4.0)
) -> int:
    """
    Estimate the multiscale level (power-of-two downsampling) such that
    the resolution at that level is at least the phase_corr_res in all axes.

    Parameters
    ----------
    voxel_resolution : List[float]
        Resolution of the original image at level 0 (in XYZ order).
    phase_corr_res : Tuple[float]
        Target resolution for phase correlation (in XYZ order).

    Returns
    -------
    int
        Estimated downsample level (0 or higher).
    """

    levels = []
    for vres, cres in zip(voxel_resolution, phase_corr_res):
        if cres < vres:
            raise ValueError(
                "phase_corr_res must be greater than or equal to voxel_resolution."
            )
        ratio = cres / vres
        levels.append(math.floor(math.log2(ratio)))

    return max(levels)

def main(
    path_to_data,
    input_prefix,
    local_xml_path,
    acquisition_path,
    channel_wavelength,
    stitching_channel_path,
    voxel_resolution,
    output_json_file,
    results_folder,
    dataset_name,
    max_error,
    relative_threshold,
    absolute_threshold,
    max_shift,
    min_r,
    res_for_transforms=(0.19, 0.19, 0.85),
    scale_for_transforms=None,
):
    """
    Computes image stitching with BigStitcher using Phase Correlation
    """
    if not max_error:
        max_error = 3.0

    if not relative_threshold:
        relative_threshold = 2.5
    
    if not absolute_threshold:
        absolute_threshold = 3.5

    if not scale_for_transforms:
        scale_for_transforms = get_estimated_downsample(
            voxel_resolution=voxel_resolution, phase_corr_res=res_for_transforms
        )
    
    downsampled_scale = int(scale_for_transforms)
    if not max_shift:
        max_shift = 160 // (downsampled_scale + 1)
    
    if not min_r:
        min_r = 0.6

    BIGSTITCHER_PATH = os.getenv("BIGSTITCHER_HOME")

    if BIGSTITCHER_PATH is None:
        raise ValueError("Please, set the BIGSTITCHER_HOME env value.")

    BIGSTITCHER_PATH = Path(BIGSTITCHER_PATH)
    env = os.environ.copy()

    if not BIGSTITCHER_PATH.exists():
        raise ValueError("Please, set the BIGSTITCHER_PATH env value.")

    start_time = time()
    metadata_folder = results_folder.joinpath("metadata")
    utils.create_folder(str(metadata_folder))

    is_proteomics = False
    if dataset_name == "PLACE": 
        is_proteomics = True
        print("PROTEOMICS DATASET")

    curr_folder = Path(os.path.realpath(__file__)).parent
    print(f"Current file path: {curr_folder}")

    run_classes_script = curr_folder / "run_classes.sh"

    # Assuming machine with 128G and 16 cores
    env.update(
        {
            "JAVA_HEAP_SIZE": "128g",
            "SPARK_THREADS": "16",
            "MAIN_CLASS": "net.preibisch.bigstitcher.spark.SparkPairwiseStitching",
        }
    )

    if is_proteomics:
        stitching_command = [
            "bash",
            str(run_classes_script),
            "--xml",
            str(local_xml_path),
            "--downsampling",
            f"{downsampled_scale},{downsampled_scale},{downsampled_scale}",
        ]
    else:
        stitching_command = [
            "bash",
            str(run_classes_script),
            "--xml",
            str(local_xml_path),
            "--downsampling",
            f"{downsampled_scale},{downsampled_scale},{downsampled_scale}",
            "--maxShiftZ",
            str(max_shift),
            "--maxShiftY",
            str(max_shift),
            "--maxShiftX",
            str(max_shift),
            "--minR",
            str(min_r)
        ]

    _ = subprocess.run(
        stitching_command,
        check=True,
        cwd=curr_folder,
        env=env,
    )

    # Updating java class to solver for global optimization
    env.update({"MAIN_CLASS": "net.preibisch.bigstitcher.spark.Solver"})

    if is_proteomics:
        global_opt_command = [
            "bash",
            str(run_classes_script),
            "--xml",
            str(local_xml_path),
            "-s",
            "STITCHING",
            "--method",
            "TWO_ROUND_ITERATIVE",
            "--maxError",
            str(max_error),
            "--maxIterations",
            "10000",
            "--maxPlateauwidth",
            "200",
            "--relativeThreshold",
            str(relative_threshold),
            "--absoluteThreshold",
            str(absolute_threshold),
        ]
    else:
        global_opt_command = [
            "bash",
            str(run_classes_script),
            "--xml",
            str(local_xml_path),
            "--sourcePoints",
            "STITCHING",
        ]

    _ = subprocess.run(
        global_opt_command,
        check=True,
        cwd=curr_folder,
        env=env,
    )
   
    end_time = time()

    output_big_stitcher_json = (
        f"{results_folder}/{dataset_name}_stitch_channel_{channel_wavelength}_params.json"
    )

    data_processes = []
    data_processes.append(
        DataProcess(
            name=ProcessName.IMAGE_TILE_ALIGNMENT,
            software_version="e112363",
            start_date_time=start_time,
            end_date_time=end_time,
            input_location=str(dataset_name),
            output_location=str(output_big_stitcher_json),
            outputs={"output_file": str(output_big_stitcher_json)},
            code_url="",
            code_version="2.0.0",
            parameters={"stitching": stitching_command, "global_optimization": global_opt_command},
            notes="Running stitching and global optimization separately",
        )
    )

    utils.generate_processing(
        data_processes=data_processes,
        dest_processing=metadata_folder,
        input_prefix=input_prefix,
        processor_full_name="Sean Fite",
        pipeline_version="2.0.0",
    )

if __name__ == "__main__":
    main()
