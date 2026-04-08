# Z1 Manual Alignment (BigStitcher) — Code Ocean Capsule
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Code%20Style](https://img.shields.io/badge/code%20style-black-000000.svg)

Manual alignment capsule for Z1 datasets using BigStitcher (phase correlation + solver).
The only required input is the **S3 prefix to a processed dataset**.

> **Guardrail:** `input_prefix` is restricted to the `aind-open-data` bucket.  
> If you pass any other bucket, the capsule exits immediately.

## What this capsule does

Given `input_prefix` (processed dataset root prefix), the capsule:

1. Validates the bucket is `aind-open-data`.
2. Finds the original BigStitcher XML under:
   - `s3://aind-open-data/processed_prefix/image_tile_alignment/`
   and downloads it locally to `/results/bigstitcher.xml`.
3. Fetches dataset metadata from S3:
   - voxel resolution, stitching channel + other channels, dataset name.
4. Runs BigStitcher alignment (`alignment.bigstitcher.main(...)`).
5. Publishes updated alignment XMLs back to S3 (including per-channel variants).
6. Generates alignment QC metrics (pairwise CSV + plots + optional dropped-link report) and writes them to S3 under:
   - `s3://aind-open-data/processed_prefix/image_tile_alignment/alignment_metrics/`
   Then mirrors them into `/results/metrics/`.

⚠️ **Overwrites:** This capsule is intended to **replace existing alignment outputs** at the prefix you provide (alignment XMLs and associated outputs). Use with care.

## App Builder Inputs (Parameters)

### Required
- **Input Prefix**
  - Format: `s3://aind-open-data/<processed_prefix>/`
  - Example:
    - `s3://aind-open-data/HCR_823476-s1-ls2_2025-11-18_00-00-00_processed_2025-11-19_22-11-11/`

### Optional (defaults shown in the App Panel)

**Proteomics Solver**
- Max Error (default `3.0`)
- Relative Threshold (default `2.5`)
- Absolute Threshold (default `3.5`)

**HCR Phase Correlation**
- Max Shift (default ~`32`, varies per dataset)
- Min R (default `0.6`)

> Note: The capsule accepts both “Proteomics Solver” and “HCR” knobs as CLI args and passes them through to BigStitcher.

## Outputs

### S3 Outputs
- Updated BigStitcher XMLs written back under:
  - `s3://aind-open-data/processed_prefix/image_tile_alignment/` (and additional channel-specific XMLs as applicable)
- Alignment QC metrics written under:
  - `s3://aind-open-data/processed_prefix/image_tile_alignment/alignment_metrics/`

### Code Ocean `/results` outputs
- `/results/bigstitcher.xml`
- `/results/metrics/` mirrored QC artifacts (CSV, plots, etc.)
- Additional run artifacts produced by BigStitcher / the capsule.

## Running (CLI)

Inside the capsule container, the entrypoint expects arguments in this order:

```bash
python -u run \
  "<input_prefix>" \
  "<max_error>" "<relative_threshold>" "<absolute_threshold>" \
  "<max_shift>" "<min_r>"
