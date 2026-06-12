from __future__ import annotations

from typing import Optional, Set, Tuple, Dict

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from metrics.utils import s3_path_join, save_figure_to_s3


class LinksGridPlot:
    def __init__(self, out_s3_prefix: str, s3):
        self.out_s3_prefix = out_s3_prefix
        self.s3 = s3

    def make_plot(
        self,
        rows,
        setup_to_grid: Dict[int, Tuple[int, int, int]],
        dropped_pairs: Optional[Set[Tuple[int, int]]] = None,
    ) -> Optional[str]:
        if not setup_to_grid:
            return None

        all_gx = [g[0] for g in setup_to_grid.values()]
        all_gy = [g[1] for g in setup_to_grid.values()]

        min_gx = min(all_gx)
        max_gx = max(all_gx)
        min_gy = min(all_gy)
        max_gy = max(all_gy)

        grid_w = max_gx - min_gx + 1
        grid_h = max_gy - min_gy + 1

        print("[grid-debug] x index min/max:", min_gx, max_gx, "unique:", sorted(set(all_gx)))
        print("[grid-debug] y index min/max:", min_gy, max_gy, "unique:", sorted(set(all_gy)))
        print("[grid-debug] grid_w/grid_h:", grid_w, grid_h)

        if grid_w <= 3 and grid_h >= 8:
            x_stretch = 2.75
        elif grid_w <= 5 and grid_h >= 12:
            x_stretch = 2.0
        else:
            x_stretch = 1.0

        print("[grid-debug] display x_stretch:", x_stretch)

        def x_plot(gx: int) -> float:
            return (gx - min_gx) * x_stretch + min_gx

        def edge_color(corr: float) -> str:
            if corr >= 0.90:
                return "tab:blue"
            elif corr >= 0.80:
                return "tab:green"
            elif corr >= 0.70:
                return "gold"
            else:
                return "red"

        band_counts = {
            "corr >= 0.90": 0,
            "0.80 <= corr < 0.90": 0,
            "0.70 <= corr < 0.80": 0,
            "corr < 0.70": 0,
        }

        def increment_band(corr: float) -> None:
            if corr >= 0.90:
                band_counts["corr >= 0.90"] += 1
            elif corr >= 0.80:
                band_counts["0.80 <= corr < 0.90"] += 1
            elif corr >= 0.70:
                band_counts["0.70 <= corr < 0.80"] += 1
            else:
                band_counts["corr < 0.70"] += 1

        best_row_by_pair: Dict[Tuple[int, int], list] = {}

        for r in rows:
            a = int(r[0])
            b = int(r[1])
            corr = float(r[5])
            key = (min(a, b), max(a, b))

            if key not in best_row_by_pair or corr > float(best_row_by_pair[key][5]):
                best_row_by_pair[key] = r

        dropped_rows = []
        dropped_missing_from_xml = []
        dropped_missing_from_grid = []

        if dropped_pairs:
            for key in sorted(dropped_pairs):
                normalized_key = (min(int(key[0]), int(key[1])), max(int(key[0]), int(key[1])))

                r = best_row_by_pair.get(normalized_key)
                if r is None:
                    dropped_missing_from_xml.append(normalized_key)
                    continue

                a = int(r[0])
                b = int(r[1])

                if a not in setup_to_grid or b not in setup_to_grid:
                    dropped_missing_from_grid.append(normalized_key)
                    continue

                dropped_rows.append(r)

        display_w = (grid_w - 1) * x_stretch + 1
        fig_w = max(7.0, min(14.0, display_w * 1.6))
        fig_h = max(14.0, min(38.0, grid_h * 0.50))

        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        tile_fontsize = 8 if grid_h <= 30 else 6 if grid_h <= 60 else 5
        tile_marker_size = 180 if grid_h <= 30 else 120 if grid_h <= 60 else 80

        def draw_nodes() -> None:
            for setup, (gx, gy, gz) in setup_to_grid.items():
                y = max_gy - gy
                x = x_plot(gx)

                ax.scatter(
                    x,
                    y,
                    s=tile_marker_size,
                    color="white",
                    edgecolors="black",
                    marker="s",
                    linewidths=1.0,
                    zorder=5,
                )

                ax.text(
                    x,
                    y,
                    str(setup),
                    fontsize=tile_fontsize,
                    color="black",
                    ha="center",
                    va="center",
                    zorder=6,
                )

        def draw_edge(
            a: int,
            b: int,
            corr: float,
            *,
            linestyle: str,
            linewidth: float,
            zorder: int,
            color_override=None,
            alpha: float = 0.9,
        ) -> bool:
            if a not in setup_to_grid or b not in setup_to_grid:
                return False

            gx_a, gy_a, _ = setup_to_grid[a]
            gx_b, gy_b, _ = setup_to_grid[b]

            ay = max_gy - gy_a
            by = max_gy - gy_b

            ax.plot(
                [x_plot(gx_a), x_plot(gx_b)],
                [ay, by],
                linewidth=linewidth,
                linestyle=linestyle,
                color=edge_color(corr) if color_override is None else color_override,
                alpha=alpha,
                zorder=zorder,
            )

            return True

        drawn_all = 0
        skipped_all = 0

        for r in rows:
            a = int(r[0])
            b = int(r[1])
            corr = float(r[5])

            increment_band(corr)

            ok = draw_edge(
                a,
                b,
                corr,
                linestyle="-",
                linewidth=1.2,
                zorder=2,
            )

            if ok:
                drawn_all += 1
            else:
                skipped_all += 1

        drawn_dropped = 0

        if dropped_rows:
            for r in dropped_rows:
                a = int(r[0])
                b = int(r[1])
                corr = float(r[5])

                ok = draw_edge(
                    a,
                    b,
                    corr,
                    linestyle=":",
                    linewidth=2.5,
                    zorder=4,
                    color_override="black",
                    alpha=1.0,
                )

                if ok:
                    drawn_dropped += 1

        draw_nodes()

        legend_handles = [
            Line2D([0], [0], color="tab:blue", lw=2, label="corr ≥ 0.90"),
            Line2D([0], [0], color="tab:green", lw=2, label="0.80 ≤ corr < 0.90"),
            Line2D([0], [0], color="gold", lw=2, label="0.70 ≤ corr < 0.80"),
            Line2D([0], [0], color="red", lw=2, label="corr < 0.70"),
        ]

        if dropped_pairs:
            legend_handles.append(
                Line2D(
                    [0],
                    [0],
                    color="black",
                    lw=2,
                    linestyle=":",
                    label="Dropped by solver",
                )
            )

        fig.legend(
            handles=legend_handles,
            title="Link bands",
            loc="upper center",
            ncol=1,
            bbox_to_anchor=(0.5, 0.945),
            borderaxespad=0.1,
            frameon=True,
        )

        ax.set_title(
            "All pairwise links on grid (colored by corr band)",
            fontsize=12,
            pad=4,
        )
        ax.set_xlabel("Grid X index")
        ax.set_ylabel("Grid Y index")
        ax.set_aspect("equal", adjustable="box")

        pad = 0.75
        ax.set_xlim(x_plot(min_gx) - pad, x_plot(max_gx) + pad)
        ax.set_ylim(-pad, max_gy + pad)

        x_ticks = [x_plot(gx) for gx in range(min_gx, max_gx + 1)]
        x_labels = [str(gx) for gx in range(min_gx, max_gx + 1)]

        ax.set_xticks(x_ticks)
        ax.set_xticklabels(x_labels)
        ax.set_yticks(range(0, max_gy + 1))

        ax.tick_params(axis="x", labelsize=9, rotation=0)
        ax.tick_params(axis="y", labelsize=8)

        ax.grid(True, alpha=0.25)

        fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.905])

        grid_png_s3 = s3_path_join(self.out_s3_prefix, "links_grid_all.png")
        save_figure_to_s3(fig, grid_png_s3, self.s3)
        plt.close(fig)

        print("[grid-debug] total pairwise rows:", len(rows))
        print("[grid-debug] drawn all links:", drawn_all)
        print("[grid-debug] skipped all links:", skipped_all)

        print("Correlation band counts:")
        for k, v in band_counts.items():
            print(f"  {k}: {v}")

        if dropped_pairs:
            print("[grid-debug] dropped pairs from CSV:", len(dropped_pairs))
            print("[grid-debug] drawn dropped links:", drawn_dropped)
            print("[grid-debug] dropped missing from XML pairwise rows:", len(dropped_missing_from_xml))
            print("[grid-debug] dropped missing grid coords:", len(dropped_missing_from_grid))

            if dropped_missing_from_xml:
                print("[grid-debug] first dropped missing from XML:", dropped_missing_from_xml[:25])

            if dropped_missing_from_grid:
                print("[grid-debug] first dropped missing grid coords:", dropped_missing_from_grid[:25])

        print("[grid-debug] wrote grid map:", grid_png_s3)

        return grid_png_s3