#!/usr/bin/env python3
"""Generate AIND processing metadata for BigStitcher alignment."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3

from aind_data_schema.base import _GenericModel
from aind_data_schema.components.identifiers import Code
from aind_data_schema.core.processing import DataProcess, Processing, ProcessStage
from aind_data_schema_models.process_names import ProcessName


# --------------------------------------------------
# Metadata
# --------------------------------------------------

REPO_URL = "https://github.com/JaneliaSciComp/BigStitcher-Spark"
GIT_URL = f"{REPO_URL}.git"

CODE_NAME = "big-stitcher"
RUN_SCRIPT = "/code/run"
LANGUAGE = "Python"
EXPERIMENTERS = ["Tim Wang"]

LOCAL_PROCESSING_JSON = Path("/results/processing.json")


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def fetch_main_commit_sha() -> str:
    result = subprocess.run(
        ["git", "ls-remote", GIT_URL, "refs/heads/main"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    return result.stdout.split()[0]


def upload_file_to_s3(local_path: Path, s3_uri: str) -> None:
    parsed = urlparse(s3_uri)

    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    s3 = boto3.client("s3")
    s3.upload_file(str(local_path), bucket, key)

    print(f"[processing-metadata] Uploaded {local_path} -> {s3_uri}")


def build_parameters(
    *,
    xml_path: str,
    zarr_location: str,
    parameters: dict,
) -> _GenericModel:
    metadata_parameters = {
        "s3_xml_path": xml_path,
        "zarr_location": zarr_location,
        **parameters,
    }

    return _GenericModel(**metadata_parameters)


def build_processing_metadata(
    *,
    xml_path: str,
    zarr_location: str,
    parameters: dict,
) -> Processing:
    timestamp = datetime.now(timezone.utc)

    return Processing(
        data_processes=[
            DataProcess(
                process_type=ProcessName.IMAGE_TILE_ALIGNMENT,
                stage=ProcessStage.PROCESSING,
                code=Code(
                    url=REPO_URL,
                    name=CODE_NAME,
                    version=fetch_main_commit_sha(),
                    run_script=RUN_SCRIPT,
                    language=LANGUAGE,
                    parameters=build_parameters(
                        xml_path=xml_path,
                        zarr_location=zarr_location,
                        parameters=parameters,
                    ),
                ),
                experimenters=EXPERIMENTERS,
                start_date_time=timestamp,
                end_date_time=timestamp,
            )
        ]
    )


def main(
    *,
    xml_path: str,
    zarr_location: str,
    processing_json_s3: str,
    parameters: dict,
) -> int:
    processing = build_processing_metadata(
        xml_path=xml_path,
        zarr_location=zarr_location,
        parameters=parameters,
    )

    LOCAL_PROCESSING_JSON.parent.mkdir(parents=True, exist_ok=True)

    LOCAL_PROCESSING_JSON.write_text(
        processing.model_dump_json(indent=3),
        encoding="utf-8",
    )

    print(f"[processing-metadata] Wrote local file: {LOCAL_PROCESSING_JSON}")

    upload_file_to_s3(LOCAL_PROCESSING_JSON, processing_json_s3)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main(
            xml_path="",
            zarr_location="",
            processing_json_s3="",
            parameters={},
        )
    )