from __future__ import annotations
from typing import Optional, Set, Tuple, Dict
from metrics.utils import s3_path_join, parse_s3_uri
import io

class DroppedLinksReport:
    def __init__(self, out_s3_prefix: str, s3):
        self.out_s3_prefix = out_s3_prefix
        self.s3 = s3

    def write( 
        self,
        rows_sorted,
        dropped_pairs: Optional[Set[Tuple[int, int]]],
        pair_errors: Dict[Tuple[int, int], float],
    ) -> Optional[str]:
        if not dropped_pairs:
            return None

        corr_by_pair: Dict[Tuple[int, int], list] = {}
        for r in rows_sorted:
            a = int(r[0])
            b = int(r[1])
            corr = float(r[5])
            key = (min(a, b), max(a, b))
            if key in dropped_pairs:
                corr_by_pair.setdefault(key, []).append(corr)

        buf = io.StringIO()
        buf.write("Dropped links summary\n")
        buf.write("=====================\n\n")
        buf.write(f"Total dropped pairs (from CSV): {len(dropped_pairs)}\n")
        buf.write(
            "Dropped pairs found in XML pairwise results: "
            f"{len(corr_by_pair)}\n\n"
        )

        missing_pairs = sorted(dropped_pairs - set(corr_by_pair.keys()))
        if missing_pairs:
            buf.write("Dropped pairs NOT found in StitchingResults (by TileA/TileB):\n")
            for (a, b) in missing_pairs:
                err = pair_errors.get((a, b))
                if err is not None:
                    buf.write(f"  - ({a}, {b})  Error={err}\n")
                else:
                    buf.write(f"  - ({a}, {b})  Error=N/A\n")
            buf.write("\n")

        if not corr_by_pair:
            buf.write(
                "No dropped pairs had corresponding pairwise correlations in the XML.\n"
            )
        else:
            buf.write("Dropped pairs with error + corr:\n")
            for key in sorted(corr_by_pair.keys()):
                a, b = key
                best_corr = max(corr_by_pair[key])
                err = pair_errors.get(key)
                err_str = "N/A" if err is None else f"{err}"
                buf.write(
                    f"Pair (TileA={a}, TileB={b}):  "
                    f"Error={err_str},  Corr={best_corr}\n"
                )

        txt_s3_uri = s3_path_join(
            self.out_s3_prefix, "dropped_links_metrics.txt"
        )
        bucket, key = parse_s3_uri(txt_s3_uri)
        data = buf.getvalue().encode("utf-8")

        self.s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType="text/plain",
        )

        return txt_s3_uri

