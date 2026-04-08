from __future__ import annotations
import csv
import io
from typing import Optional, Set, Tuple
from metrics.utils import parse_s3_uri, s3_path_join

class PairwiseCSVWriter:
    def __init__(self, out_s3_prefix: str, s3):
        self.out_s3_prefix = out_s3_prefix
        self.s3 = s3

    def write( 
        self, 
        rows_sorted,
        dropped_pairs: Optional[Set[Tuple[int, int]]] = None,
    ) -> str:
        base_header = [
            "TileA",
            "TileB",
            "ShiftX",
            "ShiftY",
            "ShiftZ",
            "Correlation",
            "OverlapX",
            "OverlapY",
            "OverlapZ",
            "Alignment",
        ]
        header = (
            base_header + ["DroppedBySolver"]
            if dropped_pairs is not None
            else base_header
        )

        csv_s3_uri = s3_path_join(self.out_s3_prefix, "pairwise_links.csv")
        bucket, key = parse_s3_uri(csv_s3_uri)

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)

        for r in rows_sorted:
            if dropped_pairs is None:
                w.writerow(r)
            else:
                a = int(r[0])
                b = int(r[1])
                pair_key = (min(a, b), max(a, b))
                is_dropped = pair_key in dropped_pairs
                w.writerow(list(r) + ["yes" if is_dropped else "no"])

        data = buf.getvalue().encode("utf-8")
        self.s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType="text/csv",
        )

        return csv_s3_uri