import json
import math
import os
import subprocess
from pathlib import Path
from time import time
from typing import List, Optional, Tuple 

from alignment import alignment_utils
from util import utils
from aind_data_schema.core.processing import DataProcess, ProcessName

"""
Computes stitching transformations using
bigstitcher for SmartSPIM data structure
"""

def main(processing_params):
    path_to_data = processing_params["path_to_data"]
    input_prefix = processing_params["input_prefix"]
    local_xml_path = Path(processing_params["local_xml_path"])
    acquisition_path = processing_params["acquisition_path"]
    channel_wavelength = processing_params["channel_wavelength"]
    stitching_channel_path = Path(processing_params["stitching_channel_path"])
    voxel_resolution = processing_params["voxel_resolution"]
    output_json_file = Path(processing_params["output_json_file"])
    results_folder = Path(processing_params["results_folder"])
    dataset_name = processing_params["dataset_name"]
    max_error = processing_params["max_error"]
    relative_threshold = processing_params["relative_threshold"]
    absolute_threshold = processing_params["absolute_threshold"]
    max_shift = processing_params["max_shift"]
    min_r = processing_params["min_r"]
    res_for_transforms = tuple(
        processing_params.get("res_for_transforms", (0.19, 0.19, 0.85))
    )
    scale_for_transforms = processing_params.get("scale_for_transforms")
    downsampled_scale = int(scale_for_transforms)

    """
    Computes image stitching with BigStitcher using Phase Correlation
    """

    BIGSTITCHER_PATH = os.getenv("BIGSTITCHER_HOME")

    if BIGSTITCHER_PATH is None:
        raise ValueError("Please, set the BIGSTITCHER_HOME env value.")

    BIGSTITCHER_PATH = Path(BIGSTITCHER_PATH)
    env = os.environ.copy()

    if not BIGSTITCHER_PATH.exists():
        raise ValueError("Please, set the BIGSTITCHER_PATH env value.")

    start_time = time()
    metadata_folder = results_folder.joinpath("metadata")
    alignment_utils.create_folder(str(metadata_folder))

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
            "--minR",
            str(0.0)
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
            input_location=str(input_prefix),
            output_location=str(output_big_stitcher_json),
            outputs={"output_file": str(output_big_stitcher_json)},
            code_url="",
            code_version="1.2.7",
            parameters={"stitching": stitching_command, "global_optimization": global_opt_command},
            notes="Running stitching and global optimization separately",
        )
    )

    utils.generate_processing(
        data_processes=data_processes,
        dest_processing=metadata_folder,
        processor_full_name="Sean Fite",
        pipeline_version="3.0.0",
    )

if __name__ == "__main__":
    main()
