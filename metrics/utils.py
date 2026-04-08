from __future__ import annotations
import csv
import io
import json
from pathlib import Path
from typing import Optional, Set, Dict, Tuple, List
from urllib.parse import urlparse
import boto3
import matplotlib.pyplot as plt
import numpy as np
import xml.etree.ElementTree as ET 

# ----------------------------
# S3 + plotting helpers
# ----------------------------

def create_s3_client(): 
    return boto3.client("s3")


def parse_s3_uri(uri: str) -> Tuple[str, str]:
    uri = str(uri)
    if not uri.startswith("s3://"):
        raise ValueError(f"Expected S3 URI starting with s3://, got {uri!r}")
    without = uri[5:]
    bucket, sep, key = without.partition("/")
    if not bucket or not sep or not key:
        raise ValueError(f"Invalid S3 URI {uri!r}; expected s3://bucket/key")
    return bucket, key


def s3_path_join(prefix: str, filename: str) -> str:
    return prefix.rstrip("/") + "/" + filename


def save_figure_to_s3(figure, s3_uri: str, s3, dpi: int = 200) -> None:
    bucket, key = parse_s3_uri(s3_uri)
    buf = io.BytesIO()
    figure.savefig(buf, dpi=dpi, format="png", bbox_inches="tight")
    plt.close(figure)
    buf.seek(0)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="image/png",
    )


# ----------------------------
# XML + grid helpers
# ----------------------------

def load_xml_root(xml_path: str | Path, s3) -> ET.Element:
    path_str = str(xml_path)
    if path_str.startswith("s3://"):
        bucket, key = parse_s3_uri(path_str)
        resp = s3.get_object(Bucket=bucket, Key=key)
        data = resp["Body"].read()
        return ET.fromstring(data)
    return ET.parse(path_str).getroot()


def parse_affine_3x4(text: str) -> np.ndarray:
    vals = np.array(text.split(), dtype=float)
    if vals.size != 12:
        raise ValueError(f"Expected 12 values in 3x4 affine, got {vals.size}")
    return vals.reshape(3, 4)


def is_pure_translation(aff: np.ndarray, atol: float = 1e-9) -> bool:
    return np.allclose(aff[:, :3], np.eye(3), atol=atol)


def get_nominal_grid(root: ET.Element) -> Dict[int, Tuple[int, int, int]]:
    vr_root = root.find("ViewRegistrations")
    if vr_root is None:
        raise RuntimeError("No <ViewRegistrations> in XML")

    setup_to_xyz: Dict[int, np.ndarray] = {}

    for vr in vr_root.findall("ViewRegistration"):
        setup = int(vr.get("setup"))
        nominal = None

        for vt in vr.findall("ViewTransform"):
            name = (vt.findtext("Name") or "").strip()
            if name != "Translation to Nominal Grid":
                continue

            aff_text = vt.findtext("affine")
            if not aff_text:
                continue

            aff = parse_affine_3x4(aff_text)
            if not is_pure_translation(aff):
                continue

            nominal = aff[:, 3].astype(float)
            break

        if nominal is not None:
            setup_to_xyz[setup] = nominal

    if not setup_to_xyz:
        raise RuntimeError("No 'Translation to Nominal Grid' transforms found")

    xs = sorted({float(v[0]) for v in setup_to_xyz.values()})
    ys = sorted({float(v[1]) for v in setup_to_xyz.values()})
    zs = sorted({float(v[2]) for v in setup_to_xyz.values()})

    x_to_ix = {x: i for i, x in enumerate(xs)}
    y_to_iy = {y: i for i, y in enumerate(ys)}
    z_to_iz = {z: i for i, z in enumerate(zs)}

    setup_to_grid: Dict[int, Tuple[int, int, int]] = {}
    for setup, xyz in setup_to_xyz.items():
        gx = x_to_ix[float(xyz[0])]
        gy = y_to_iy[float(xyz[1])]
        gz = z_to_iz[float(xyz[2])]
        setup_to_grid[setup] = (gx, gy, gz)

    return setup_to_grid


def extract_pairwise_rows(root: ET.Element, xy_thresh_log2: float) -> List[list]:
    sr = root.find("StitchingResults")
    if sr is None:
        raise RuntimeError("No <StitchingResults> in XML")

    rows: List[list] = []
    seen = set()

    for pr in sr.findall("PairwiseResult"):
        a = int(pr.get("view_setup_a"))
        b = int(pr.get("view_setup_b"))

        shift_aff = parse_affine_3x4(pr.find("shift").text)
        if not is_pure_translation(shift_aff):
            raise SystemExit(f"Non-translation detected between {a} and {b}")

        shifts = shift_aff[:, 3].astype(float)
        corr = float(pr.find("correlation").text)

        bb = np.array(
            pr.find("overlap_boundingbox").text.split(),
            dtype=float,
        ).reshape(2, 3)
        ext = bb[1] - bb[0]
        overlap_x, overlap_y, overlap_z = ext.tolist()

        eps = 1e-9
        x = max(abs(overlap_x), eps)
        y = max(abs(overlap_y), eps)

        if np.log2(x / y) > xy_thresh_log2:
            align = "top_bottom"
        elif np.log2(y / x) > xy_thresh_log2:
            align = "left_right"
        else:
            align = "corner"

        sx_round = round(float(shifts[0]), 3)
        sy_round = round(float(shifts[1]), 3)
        sz_round = round(float(shifts[2]), 3)
        corr_round = round(corr, 6)

        key = (min(a, b), max(a, b), sx_round, sy_round, sz_round, corr_round)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            [
                a,
                b,
                sx_round,
                sy_round,
                sz_round,
                corr_round,
                float(overlap_x),
                float(overlap_y),
                float(overlap_z),
                align,
            ]
        )

    return rows


def load_dropped_pairs(
    csv_path: str | Path,
) -> Tuple[Set[Tuple[int, int]], Dict[Tuple[int, int], float]]:
    dropped: Set[Tuple[int, int]] = set()
    pair_errors: Dict[Tuple[int, int], float] = {}

    try:
        with open(csv_path, "r", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
                reader = csv.DictReader(f, dialect=dialect)
            except csv.Error:
                reader = csv.DictReader(f)

            fieldnames = reader.fieldnames or []
            has_type = "type" in fieldnames

            for row in reader:
                if not any(row.values()):
                    continue

                if has_type and row.get("type") != "solver_removed_link":
                    continue

                try:
                    a = int(row["a"])
                    b = int(row["b"])
                except (KeyError, ValueError, TypeError):
                    continue

                key = (min(a, b), max(a, b))
                dropped.add(key)

                err_val: Optional[float] = None
                err_str = row.get("error")
                if err_str:
                    try:
                        err_val = float(err_str)
                    except ValueError:
                        err_val = None

                if err_val is not None:
                    if key in pair_errors:
                        pair_errors[key] = max(pair_errors[key], err_val)
                    else:
                        pair_errors[key] = err_val

        print(
            f"Loaded {len(dropped)} dropped pairs from {csv_path}: "
            f"{sorted(dropped)}"
        )
    except FileNotFoundError:
        print(
            f"[WARN] dropped_links file not found at {csv_path}; "
            "continuing without dropped-link labels."
        )
    except Exception as e:
        print(f"[WARN] Error reading dropped_links CSV at {csv_path}: {e!r}")

    return dropped, pair_errors


# ----------------------------
# Run-script helpers
# ----------------------------

def mirror_s3_prefix_to_results(s3_prefix: str, results_dir: Path) -> None:
    """
    Mirror all S3 objects under `s3_prefix` into the local `/results` directory,
    preserving relative paths, and print what we downloaded.
    """
    parsed = urlparse(s3_prefix)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")

    print(f"🔍 Mirroring S3 prefix: s3://{bucket}/{prefix} -> {results_dir}")

    s3 = create_s3_client()
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


def _safe_read_json(path: Path) -> dict:
    try:
        with path.open("r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️  JSON file not found: {path}")
    except Exception as e:
        print(f"⚠️  Error reading JSON {path}: {e!r}")
    return {}
