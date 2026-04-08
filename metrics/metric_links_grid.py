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
        max_gy = max(all_gy) if all_gy else 0

        fig, ax = plt.subplots(figsize=(8, 6))

        # tile nodes
        for setup, (gx, gy, gz) in setup_to_grid.items():
            y_plot = max_gy - gy
            ax.scatter(gx, y_plot, s=70, color="black")
            ax.text(gx + 0.03, y_plot + 0.03, str(setup), fontsize=7, color="black")

        def edge_color(corr: float) -> str:
            if corr >= 0.90:
                return "tab:green"
            elif corr >= 0.80:
                return "gold"
            elif corr >= 0.70:
                return "tab:orange"
            return "red"

        band_counts = {"90-100": 0, "80-90": 0, "70-80": 0, "<70": 0}

        def increment_band(c: float):
            if c >= 0.90:
                band_counts["90-100"] += 1
            elif c >= 0.80:
                band_counts["80-90"] += 1
            elif c >= 0.70:
                band_counts["70-80"] += 1
            else:
                band_counts["<70"] += 1

        has_dropped = bool(dropped_pairs)

        for r in rows:
            a, b, corr = int(r[0]), int(r[1]), float(r[5])
            if a not in setup_to_grid or b not in setup_to_grid:
                continue

            increment_band(corr)

            gx_a, gy_a, _ = setup_to_grid[a]
            gx_b, gy_b, _ = setup_to_grid[b]
            ay = max_gy - gy_a
            by = max_gy - gy_b

            key = (min(a, b), max(a, b))
            is_dropped = has_dropped and (key in dropped_pairs)

            linestyle = ":" if is_dropped else "-"
            linewidth = 2 if is_dropped else 1

            ax.plot(
                [gx_a, gx_b],
                [ay, by],
                linewidth=linewidth,
                linestyle=linestyle,
                color=edge_color(corr),
            )

        legend_handles = [
            Line2D([0], [0], color="tab:green",  lw=2, label="90–100"),
            Line2D([0], [0], color="gold",       lw=2, label="80–90"),
            Line2D([0], [0], color="tab:orange", lw=2, label="70–80"),
            Line2D([0], [0], color="red",        lw=2, label="< 70"),
        ]
        if has_dropped:
            legend_handles.append(
                Line2D(
                    [0], [0],
                    color="black",
                    lw=2,
                    linestyle=":",
                    label="Dropped by solver",
                )
            )

        fig.subplots_adjust(top=0.80)
        fig.legend(
            handles=legend_handles,
            title="Correlation bands (percent)",
            loc="upper center",
            ncol=2,
            bbox_to_anchor=(0.5, 0.96),
            borderaxespad=0.3,
            columnspacing=1.5,
        )

        ax.set_title("All pairwise links on grid (colored by corr band)")
        ax.set_xlabel("Grid X index")
        ax.set_ylabel("Grid Y index")
        ax.set_aspect("equal", adjustable="box")

        fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.78])

        grid_png_s3 = s3_path_join(self.out_s3_prefix, "links_grid_all.png")
        save_figure_to_s3(fig, grid_png_s3, self.s3)

        print("Correlation band counts:")
        for k, v in band_counts.items():
            print(f"  {k}: {v}")

        return grid_png_s3

        