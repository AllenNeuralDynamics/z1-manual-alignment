import os
from pathlib import Path
import sys
import math
import boto3
from urllib.parse import urlparse
from typing import List, Optional, Tuple 

from metrics.run_metrics import RunMetrics
import alignment.bigstitcher as bigstitcher
from alignment import alignment_utils

"""
Manual BigStitcher alignment capsule, replacing existing alignment output
"""

def list_results_tree(results_dir: Path) -> None:
    """
    Recursively list everything under /results so we can see what QC produced.
    """
    print(f"\n📂 Contents of {results_dir}:")
    if not results_dir.exists():
        print("   (directory does not exist)")
        return

    count = 0
    for p in sorted(results_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(results_dir)
            size = p.stat().st_size
            print(f"   - {rel} ({size} bytes)")
            count += 1

    if count == 0:
        print("   (no files found)")
    else:
        print(f"   → Total files: {count}")

def mirror_s3_prefix_to_results(s3_prefix: str, results_dir: Path) -> None:
    """
    Mirror all S3 objects under `s3_prefix` into the local `/results` directory,
    preserving relative paths, and print what we downloaded.
    """
    parsed = urlparse(s3_prefix)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")

    print(f"🔍 Mirroring S3 prefix: s3://{bucket}/{prefix} -> {results_dir}")

    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    total_files = 0

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        contents = page.get("Contents", [])
        if not contents:
            continue

        for obj in contents:
            key = obj["Key"]
            if key.endswith("/"):
                continue

            rel = key[len(prefix):].lstrip("/")
            local_path = results_dir / rel
            local_path.parent.mkdir(parents=True, exist_ok=True)

            print(f"📥 Downloading: s3://{bucket}/{key} -> {local_path}")
            s3.download_file(bucket, key, str(local_path))
            total_files += 1

    print(f"✅ Finished mirroring {total_files} file(s) from {s3_prefix} into {results_dir}")

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

def run():
    """
    Function that runs image stitching with BigStitcher
    """
    results_folder = Path(os.path.abspath("../results"))
    data_folder = Path(os.path.abspath("../data"))
    
    input_prefix = sys.argv[1]

    aligned_xml_path = sys.argv[7]
    
    parsed = urlparse(str(input_prefix))
    bucket = parsed.netloc
    if bucket != "aind-open-data":
        raise SystemExit(
            f"Refusing to run: input_prefix bucket must be 'aind-open-data' "
            f"(got '{bucket}'). input_prefix={input_prefix}"
        )

    if not aligned_xml_path:    
        max_error = sys.argv[2]
        if not max_error:
            max_error = 3.0

        relative_threshold = sys.argv[3]
        if not relative_threshold:
            relative_threshold = 2.5
        
        absolute_threshold = sys.argv[4]
        if not absolute_threshold:
            absolute_threshold = 3.5
        
        voxel_resolution = alignment_utils.fetch_voxel_resolution(input_prefix)
        res_for_transforms = (0.76, 0.76, 3.4)

        downsampled_scale = 2
        max_shift = sys.argv[5]
        if not max_shift:
            max_shift = 160 // (downsampled_scale + 1)
        
        min_r = sys.argv[6]
        if not min_r:
            min_r = 0.6
        
        # Optional param to align on other channel
        align_on_ch = sys.argv[8]
        
        # Grab unaligned xml from s3 and put into results folder 
        xml_prefix = input_prefix + "image_tile_alignment/"
        source_xml_s3 = alignment_utils.pick_latest_bigstitcher_xml_s3(xml_prefix)
        local_xml_path = results_folder / "bigstitcher.xml"
        alignment_utils.download_s3_to_local(source_xml_s3, local_xml_path, align_on_ch)

        # Gather inputs from s3
        stitching_channel, other_channels = alignment_utils.fetch_channels(input_prefix, align_on_ch)
        dataset_name = alignment_utils.fetch_dataset_name(input_prefix)

        # Create local output paths
        path_to_data = f"{input_prefix}image_radial_correction"
        output_json_file = results_folder.joinpath(f"{dataset_name}_tile_metadata.json")
        stitching_channel_path = data_folder.joinpath(f"processed")

        processing_params = {
            "path_to_data": path_to_data,
            "input_prefix": input_prefix,
            "local_xml_path": str(local_xml_path),
            "acquisition_path": input_prefix + "acquisition.json",
            "channel_wavelength": stitching_channel,
            "stitching_channel_path": str(stitching_channel_path),
            "voxel_resolution": voxel_resolution,
            "output_json_file": str(output_json_file),
            "results_folder": str(results_folder),
            "dataset_name": dataset_name,
            "max_error": max_error,
            "relative_threshold": relative_threshold,
            "absolute_threshold": absolute_threshold,
            "max_shift": max_shift,
            "min_r": min_r,
            "res_for_transforms": list(res_for_transforms),
            "scale_for_transforms": downsampled_scale,
        }

        # Computing image transformations with bigtstitcher
        bigstitcher.main(processing_params)

        # Save dropped links locally for metrics eval (always none for non-prot)
        alignment_utils.write_solver_removed_links_csv(results_folder)

        dropped_csv_path = results_folder / "solver_removed_links.csv"
        xml_path = results_folder / "bigstitcher.xml"
        metrics_output_path = f"{input_prefix.rstrip('/')}/image_tile_alignment/alignment_metrics"

        run_metrics = RunMetrics(
            dropped_csv_path=dropped_csv_path,
            xml_path=xml_path,
            output_path=metrics_output_path,
        )
        run_metrics.run_alignment_metrics()

        mirror_s3_prefix_to_results(metrics_output_path, results_folder)
        list_results_tree(results_folder)
    
    else:
        local_xml_path = results_folder / "bigstitcher.xml"
        alignment_utils.download_s3_to_local(aligned_xml_path, local_xml_path)
        stitching_channel, other_channels = alignment_utils.fetch_channels(input_prefix)
        dataset_name = alignment_utils.fetch_dataset_name(input_prefix)

    # Update new alignment output xmls to s3
    alignment_utils.publish_bigstitcher_xmls(
        input_prefix_s3=input_prefix,
        local_xml_path=local_xml_path,
        results_folder=results_folder,
        stitching_channel=stitching_channel,
        other_channels=other_channels,
    )

if __name__ == "__main__":
    run()
