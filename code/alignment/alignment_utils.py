import os
from pathlib import Path
from typing import List, Optional, Union, Tuple, Iterable
import re
import csv
import json
from urllib.parse import urlparse
import boto3
from botocore.exceptions import ClientError
from packaging import version
import xml.etree.ElementTree as ET 

"""
Utility functions
"""

PathLike = Union[str, Path]
S3 = boto3.client("s3")

def pick_latest_bigstitcher_xml_s3(xml_prefix: str) -> str:
    """
    Return the S3 URI for the bigstitcher.xml~n
    """
    s3 = S3
    u = urlparse(xml_prefix)
    bucket = u.netloc
    prefix = u.path.lstrip("/")

    # List and find bigstitcher.xml~N
    pat = re.compile(r"bigstitcher\.xml~(\d+)$")
    best_n = -1
    best_key = None

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            m = pat.search(key)
            if m:
                n = int(m.group(1))
                if n > best_n:
                    best_n = n
                    best_key = key

    if best_key is None:
        raise ValueError(f"No bigstitcher.xml~N found under: {xml_prefix}")
        
    return f"s3://{bucket}/{best_key}"

def publish_bigstitcher_xmls(
    *,
    input_prefix_s3: str,
    local_xml_path: Path,
    results_folder: Path,
    stitching_channel: str,
    other_channels: Iterable[str],
) -> None:
    """
    Upload all local bigstitcher.xml* files back to s3
    Then write per-channel single-channel XMLs to s3
    """
    # Copy all local bigstitcher.xml* files and replace what is in S3
    dst_prefix_s3 = input_prefix_s3.rstrip("/") + "/image_tile_alignment/"
    local_dir = local_xml_path.parent

    xml_files = sorted(local_dir.glob("bigstitcher.xml*"))
    if not xml_files:
        raise FileNotFoundError(f"No bigstitcher.xml* files found under: {local_dir}")

    for p in xml_files:
        dst_s3 = dst_prefix_s3 + p.name
        upload_local_to_s3(p, dst_s3)
        print(f"[XML] Uploaded: {p} -> {dst_s3}")

    # Write per-channel single_channel_xmls/channel_<ch>.xml
    single_xml_prefix_s3 = input_prefix_s3.rstrip("/") + "/image_tile_alignment/single_channel_xmls/"
    src_xml = local_xml_path

    # Stitching channel gets the unmodified xml
    dst_s3 = single_xml_prefix_s3 + f"channel_{stitching_channel}.xml"
    upload_local_to_s3(src_xml, dst_s3)
    print(f"[XML] Uploaded stitch channel xml: {src_xml} -> {dst_s3}")

    # Other channels: rewrite then upload
    for ch in other_channels:
        tmp_xml = results_folder / "image_tile_alignment" / f"bigstitcher_channel_{ch}.xml"
        write_xml_for_channel(src_xml, tmp_xml, str(ch))

        dst_s3 = single_xml_prefix_s3 + f"channel_{ch}.xml"
        upload_local_to_s3(tmp_xml, dst_s3)
        print(f"[XML] Uploaded rewritten channel xml: {tmp_xml} -> {dst_s3}")

def write_solver_removed_links_csv(results_folder: Path) -> None:
    """
    Extract ONLY iterative-solver dropped links from /results/logs.txt:
    """
    log_path = results_folder / "logs.txt"
    if not log_path.exists():
        print("[POST] logs.txt not found; cannot parse removed links.")
        return

    txt = log_path.read_text(errors="replace")

    re_removed = re.compile(
        r"Removed link from\s+(\d+)-(\d+)\s+to\s+(\d+)-(\d+)\s+\(error=([0-9.eE+-]+)\)"
    )

    rows = []
    seen = set()  # (tp, u, v) de-dupe in case line appears twice

    for m in re_removed.finditer(txt):
        tp_a, a, tp_b, b, err = m.groups()
        tp_a = int(tp_a); a = int(a)
        tp_b = int(tp_b); b = int(b)
        err_f = float(err)

        u, v = (a, b) if a <= b else (b, a)
        key = (tp_a, u, v)
        if key in seen:
            continue
        seen.add(key)

        rows.append([tp_a, a, tp_b, b, u, v, err_f])

    # Sort biggest error first (helpful for quick inspection)
    rows.sort(key=lambda r: r[6], reverse=True)

    out_csv = results_folder / "solver_removed_links.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tp_a", "a", "tp_b", "b", "u", "v", "error"])
        w.writerows(rows)

    print(f"[POST] wrote: {out_csv} ({len(rows)} rows)")

def fetch_json_from_s3(dataset_prefix_s3: str, filename: str) -> dict:
    """
    Reusable JSON fetcher:
      s3://bucket/prefix/ + filename  -> dict
    """
    prefix = dataset_prefix_s3.rstrip("/") + "/"
    s3_uri = prefix + filename

    u = urlparse(s3_uri)
    if u.scheme != "s3" or not u.netloc:
        raise ValueError(f"Not a valid s3:// URI: {s3_uri}")

    bucket = u.netloc
    key = u.path.lstrip("/")

    s3 = S3
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        raise FileNotFoundError(f"Failed to read {s3_uri}: {e}") from e

    try:
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to parse JSON from {s3_uri}: {e}") from e

def fetch_channels(dataset_prefix_s3: str, align_on_ch: str = "") -> Tuple[str, list[str]]:
    manifest = fetch_json_from_s3(dataset_prefix_s3, "processing_manifest.json")
    pp = manifest["pipeline_processing"]

    original_stitch_ch = str(pp["stitching"]["channel"])
    align_on_ch = str(align_on_ch).strip() if align_on_ch else ""

    raw_channels = pp.get("radial_correction", {}).get("channels", [])
    if not raw_channels:
        raise ValueError(
            "processing_manifest.json missing pipeline_processing.radial_correction.channels; "
            "cannot determine full channel list for single-channel XML generation."
        )

    all_ch = [str(ch) for ch in raw_channels]

    if original_stitch_ch not in all_ch:
        all_ch.insert(0, original_stitch_ch)

    stitch_ch = align_on_ch if align_on_ch else original_stitch_ch

    if stitch_ch not in all_ch:
        all_ch.insert(0, stitch_ch)

    # Stable de-dupe
    seen = set()
    all_ch = [ch for ch in all_ch if not (ch in seen or seen.add(ch))]

    # Important: exclude the active stitching channel
    other_ch = [ch for ch in all_ch if ch != stitch_ch]

    # print(f"[XML] original stitching channel: {original_stitch_ch}")
    # print(f"[XML] active stitching channel: {stitch_ch}")
    # print(f"[XML] all channels: {all_ch}")
    # print(f"[XML] other channels: {other_ch}")

    return stitch_ch, other_ch

def get_resolution_schema_2(acquisition_config: dict) -> Tuple[float]:
    """
    Get the image resolution from the acquisition.json metadata
    in the version 2.0

    Parameters
    ----------
    acquisition_config: dict
        Acquisition metadata

    Returns
    -------
    Tuple[float]
        Tuple with the floats for image resolution
    """

    # Grabbing a tile with metadata from acquisition - we assume all
    # dataset was acquired with the same resolution
    try:
        data_stream = acquisition_config.get("data_streams", [])[0]
        configuration = data_stream.get("configurations", [])[0]
        image = configuration.get("images", [])[0]
        image_to_acquisition_transform = image["image_to_acquisition_transform"]
    except (IndexError, AttributeError, KeyError) as e:
        raise ValueError(
            "acquisition_config structure is invalid or missing " "required fields"
        ) from e

    scale_transform = [
        x["scale"]
        for x in image_to_acquisition_transform
        if x["object_type"] == "Scale"
    ][0]

    x = float(scale_transform[0])
    y = float(scale_transform[1])
    z = float(scale_transform[2])

    return z, y, x

def fetch_voxel_resolution(dataset_prefix_s3: str) -> Tuple[float, float, float]:
    """
    Fetch acquisition.json from the dataset root prefix in S3 and return voxel resolution (x, y, z).
    """
    acquisition_config = fetch_json_from_s3(dataset_prefix_s3, "acquisition.json")

    x = y = z = None
    schema_version = acquisition_config.get("schema_version")

    if schema_version and version.parse(schema_version) >= version.parse("2.0.0"):
        x, y, z = get_resolution_schema_2(acquisition_config=acquisition_config)
    else:
        x, y, z = get_resolution_schema_2(acquisition_config=acquisition_config)

    assert not any(val is None for val in (x, y, z)), (
        f"Resolution contains None!: X: {x}, y: {y}, z: {z}"
    )

    return x, y, z

def fetch_dataset_name(dataset_prefix_s3: str) -> str:
    """
    Fetch data_description.json from the dataset root prefix in S3 and return project_name.
    """
    desc = fetch_json_from_s3(dataset_prefix_s3, "data_description.json")
    return desc["project_name"]

def rewrite_xml_channel(local_path: Path, align_on_ch: str) -> None:
    align_on_ch = str(align_on_ch).strip()
    if not align_on_ch:
        return

    text = local_path.read_text(encoding="utf-8")

    # Replace filename/path/name occurrences like:
    text = re.sub(r"_ch_\d+", f"_ch_{align_on_ch}", text)

    # Replace XML channel values:
    text = re.sub(r"(<channel>)\d+(</channel>)", rf"\g<1>{align_on_ch}\g<2>", text)

    # More targeted replacement for the channel Attributes block.
    text = re.sub(
        r'(<Attributes name="channel">\s*<Channel>\s*<id>)\d+(</id>\s*<name>)\d+(</name>)',
        rf"\g<1>{align_on_ch}\g<2>{align_on_ch}\g<3>",
        text,
        flags=re.DOTALL,
    )

    local_path.write_text(text, encoding="utf-8")

def download_s3_to_local(s3_uri: str, local_path: Path, align_on_ch: str) -> None:
    u = urlparse(s3_uri)
    if u.scheme != "s3" or not u.netloc:
        raise ValueError(f"Not a valid s3:// URI: {s3_uri}")

    bucket = u.netloc
    key = u.path.lstrip("/")

    local_path.parent.mkdir(parents=True, exist_ok=True)

    s3 = S3
    try:
        s3.download_file(bucket, key, str(local_path))
    except ClientError as e:
        raise FileNotFoundError(f"Failed to download {s3_uri}: {e}") from e
    
    rewrite_xml_channel(local_path, align_on_ch)

def upload_local_to_s3(local_path: Path, s3_uri: str) -> None:
    u = urlparse(s3_uri)
    if u.scheme != "s3" or not u.netloc:
        raise ValueError(f"Not a valid s3:// URI: {s3_uri}")

    bucket = u.netloc
    key = u.path.lstrip("/")

    s3 = S3
    try:
        s3.upload_file(str(local_path), bucket, key)
    except ClientError as e:
        raise RuntimeError(f"Failed to upload {local_path} -> {s3_uri}: {e}") from e

def write_xml_for_channel(src_xml: Path, dst_xml: Path, new_channel: str) -> None:
    """
    Read BigStitcher XML (single-channel) and rewrite all channel markers to `new_channel`,
    then write to dst_xml.
    """
    if not src_xml.exists():
        raise FileNotFoundError(f"Missing source XML: {src_xml}")

    tree = ET.parse(str(src_xml))
    root = tree.getroot()

    # zgroup paths
    for zg in root.findall(".//zgroup"):
        p = zg.get("path")
        if p and "_ch_" in p:
            left = p.split("_ch_")[0]
            suffix = p.split("_ch_")[1]
            # keep extension (e.g. ".ome.zarr") and anything after digits
            # replace just the digits chunk at start of suffix
            i = 0
            while i < len(suffix) and suffix[i].isdigit():
                i += 1
            zg.set("path", f"{left}_ch_{new_channel}{suffix[i:]}")

    # ViewSetup <name> tags often include the same filename
    for name_el in root.findall(".//ViewSetup/name"):
        if name_el.text and "_ch_" in name_el.text:
            t = name_el.text
            left = t.split("_ch_")[0]
            suffix = t.split("_ch_")[1]
            i = 0
            while i < len(suffix) and suffix[i].isdigit():
                i += 1
            name_el.text = f"{left}_ch_{new_channel}{suffix[i:]}"

    # ViewSetup attributes
    for ch_el in root.findall(".//ViewSetup/attributes/channel"):
        ch_el.text = str(new_channel)

    # Global channel attribute block
    for attrs in root.findall(".//Attributes[@name='channel']"):
        for ch in attrs.findall(".//Channel"):
            id_el = ch.find("id")
            nm_el = ch.find("name")
            if id_el is not None:
                id_el.text = str(new_channel)
            if nm_el is not None:
                nm_el.text = str(new_channel)

    dst_xml.parent.mkdir(parents=True, exist_ok=True)

    # preserve XML declaration
    tree.write(str(dst_xml), encoding="UTF-8", xml_declaration=True)

def create_folder(dest_dir: PathLike, verbose: Optional[bool] = False) -> None:
    """
    Create new folders
    """

    if not (os.path.exists(dest_dir)):
        try:
            if verbose:
                print(f"Creating new directory: {dest_dir}")
            os.makedirs(dest_dir)
        except OSError as e:
            if e.errno != os.errno.EEXIST:
                raise

