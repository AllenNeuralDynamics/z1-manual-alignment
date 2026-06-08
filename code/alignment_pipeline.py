import os
from pathlib import Path
import sys
import math
from urllib.parse import urlparse
from typing import List, Optional, Tuple 

import alignment.bigstitcher as bigstitcher
from alignment import alignment_utils
from metrics.metric_pairwise_csv import PairwiseCSVWriter
from metrics.metric_corr_shift import CorrAndShiftPlots
from metrics.metric_links_grid import LinksGridPlot
from metrics.metric_dropped_links_report import DroppedLinksReport
from metrics.utils import (
    mirror_s3_prefix_to_results,
    list_results_tree,
    _safe_read_json,
    create_s3_client, 
    load_xml_root,
    get_nominal_grid,
    extract_pairwise_rows,
    load_dropped_pairs,
) 

"""
Manual BigStitcher alignment capsule, replacing existing alignment output
"""

def run_alignment_metrics(*, input_prefix: str, dataset_name: str, local_xml_path: Path,
    results_folder: Path, xy_thres: float = 2.0) -> None:

    # optional dropped-links csv produced earlier in this capsule
    dropped_csv_path = results_folder / "solver_removed_links.csv"
    dropped_csv_arg = str(dropped_csv_path) if dropped_csv_path.exists() else None
    output_path = input_prefix.rstrip("/") + "/image_tile_alignment/alignment_metrics"

    s3 = create_s3_client()
    root = load_xml_root(str(local_xml_path), s3)
    setup_to_grid = get_nominal_grid(root)
    rows = extract_pairwise_rows(root, xy_thres)
    rows_sorted = sorted(rows, key=lambda r: r[5], reverse=True)

    dropped_pairs = None
    pair_errors = {}

    if dropped_csv_arg:
        dropped_pairs_loaded, pair_errors_loaded = load_dropped_pairs(dropped_csv_arg)
        if dropped_pairs_loaded:
            dropped_pairs = dropped_pairs_loaded
            pair_errors = pair_errors_loaded
            print(f"✅ Using {len(dropped_pairs)} dropped pair(s) for QC annotations.")
        else:
            print("⚠️ No valid dropped pairs found; continuing without annotations.")
    else:
        print("ℹ️ No solver_removed_links.csv found; continuing without annotations.")

    csv_writer = PairwiseCSVWriter(output_path, s3)
    corr_shift = CorrAndShiftPlots(output_path, s3)
    links_grid = LinksGridPlot(output_path, s3)
    dropped_report = DroppedLinksReport(output_path, s3)

    csv_uri = csv_writer.write(rows_sorted, dropped_pairs)
    corr_png_uri, shifts_all_png_uri, shifts_kept_png_uri = corr_shift.make_plots(
        rows_sorted, dropped_pairs
    )
    links_grid_png_uri = links_grid.make_plot(rows, setup_to_grid, dropped_pairs)

    dropped_txt_uri = None
    if dropped_pairs:
        dropped_txt_uri = dropped_report.write(rows_sorted, dropped_pairs, pair_errors)

    print("QC done.")
    print("  CSV  :", csv_uri)
    print("  Plots:")
    print("    corr vs rank   :", corr_png_uri)
    print("    shifts (all)   :", shifts_all_png_uri)
    print("    shifts (kept)  :", shifts_kept_png_uri)
    print("    links (grid)   :", links_grid_png_uri)
    if dropped_txt_uri:
        print("    dropped link metrics:", dropped_txt_uri)

    # pull QC outputs into /results
    metrics_dir = results_folder / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    mirror_s3_prefix_to_results(output_path, metrics_dir)
    list_results_tree(metrics_dir)

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

    # Generate alignment metrics and save to s3
    run_alignment_metrics(
        input_prefix=input_prefix,
        dataset_name=dataset_name,
        local_xml_path=local_xml_path,
        results_folder=results_folder,
        xy_thres=2.0,
    )

if __name__ == "__main__":
    run()
