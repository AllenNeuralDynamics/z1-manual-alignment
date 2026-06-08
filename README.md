# Big Stitcher Alignment capsule for z1

This capsule is used to re-run Big Stitcher Phase Correlation on an aligned processed prefixf

<br>

**Note**

This capsule makes the assumption that the input prefix is pointing to output from the z1 prod pipeline V2.0 or higher

<br>

**How to Run**

This capsule can be ran using the AppBuilder param tab

<br>

**Params**  

- **Input Prefix:** prefix of where your data is hosted (required)

  **Example** - s3://aind-open-data/HCR_823476-s1-ls2_2025-11-18_00-00-00_processed_2025-11-19_22-11-11/

<br>

**Optional Params**

- Aligned XML Path - Use this if you have an aligned XML you want to upload for the fusion capsule. This updates existing xmls (all channels) and metrics (without dropped links). This path can be from anywhere in s3 but the **Input Prefix** param still needs to be from the correct processed prefix
- Align on New Channel - Use this if you want to run alignment again on a new channel (561)

**Proteomics Solver**
- Max Error (default `3.0`)
- Relative Threshold (default `2.5`)
- Absolute Threshold (default `3.5`)

**HCR Phase Correlation**
- Max Shift (default ~32, varies per dataset)
- Min R (default `0.6`)

<br>
<br>


