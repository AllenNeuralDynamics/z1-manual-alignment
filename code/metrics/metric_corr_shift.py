from __future__ import annotations

from typing import Optional, Set, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from metrics.utils import s3_path_join, save_figure_to_s3


class CorrAndShiftPlots:
    def __init__(self, out_s3_prefix: str, s3):
        self.out_s3_prefix = out_s3_prefix
        self.s3 = s3

    @staticmethod
    def _axis_min_max(arr: np.ndarray):
        if arr.size == 0:
            return (-1.0, 1.0)

        vmin = float(arr.min())
        vmax = float(arr.max())

        if vmin == vmax:
            eps = 1.0 if vmin == 0 else abs(vmin) * 0.1
            return (vmin - eps, vmax + eps)

        pad = 0.05 * (vmax - vmin)
        return (vmin - pad, vmax + pad)

    def make_plots(
        self,
        rows_sorted,
        dropped_pairs: Optional[Set[Tuple[int, int]]] = None,
    ):
        if not rows_sorted:
            return None, None, None

        corr = np.array([r[5] for r in rows_sorted], dtype=float)
        sx = np.array([r[2] for r in rows_sorted], dtype=float)
        sy = np.array([r[3] for r in rows_sorted], dtype=float)
        sz = np.array([r[4] for r in rows_sorted], dtype=float)
        rank = np.arange(1, len(rows_sorted) + 1)
        aligns = [r[9] for r in rows_sorted]

        dropped_flags = None
        if dropped_pairs is not None:
            dropped_flags = np.array(
                [
                    (min(int(r[0]), int(r[1])), max(int(r[0]), int(r[1])))
                    in dropped_pairs
                    for r in rows_sorted
                ],
                dtype=bool,
            )

        cat_order = ["top_bottom", "left_right", "corner"]
        cat_labels = {
            "top_bottom": "Top / Bottom",
            "left_right": "Left / Right",
            "corner": "Corner",
        }
        cat_colors = {
            "top_bottom": "tab:blue",
            "left_right": "tab:orange",
            "corner": "tab:green",
        }

        # -------- Corr vs rank, split by category --------
        corr_png_s3 = s3_path_join(self.out_s3_prefix, "corr_rank.png")

        fig, axes = plt.subplots(
            1,
            len(cat_order),
            figsize=(15, 4.5),
            sharey=True,
        )

        if len(cat_order) == 1:
            axes = [axes]

        for ax, cat in zip(axes, cat_order):
            idxs_cat = np.array(
                [i for i, a in enumerate(aligns) if a == cat],
                dtype=int,
            )

            ax.set_title(cat_labels[cat])
            ax.set_xlabel("Pair rank (corr desc)")
            ax.grid(True, alpha=0.25)

            if idxs_cat.size == 0:
                ax.text(
                    0.5,
                    0.5,
                    "No pairs",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )
                continue

            if dropped_flags is None:
                ax.scatter(
                    rank[idxs_cat],
                    corr[idxs_cat],
                    s=10,
                    color=cat_colors[cat],
                    label=cat_labels[cat],
                )
            else:
                local_dropped = dropped_flags[idxs_cat]
                kept_idx = idxs_cat[~local_dropped]
                drop_idx = idxs_cat[local_dropped]

                if kept_idx.size > 0:
                    ax.scatter(
                        rank[kept_idx],
                        corr[kept_idx],
                        s=10,
                        color=cat_colors[cat],
                        label=cat_labels[cat],
                    )

                if drop_idx.size > 0:
                    ax.scatter(
                        rank[drop_idx],
                        corr[drop_idx],
                        s=40,
                        marker="x",
                        color=cat_colors[cat],
                    )

            ax.text(
                0.02,
                0.96,
                f"n={idxs_cat.size}",
                ha="left",
                va="top",
                transform=ax.transAxes,
                fontsize=9,
                bbox={
                    "facecolor": "white",
                    "edgecolor": "black",
                    "boxstyle": "round,pad=0.25",
                    "alpha": 0.8,
                },
            )

        axes[0].set_ylabel("Correlation")

        legend_handles = [
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                color=cat_colors["top_bottom"],
                label=cat_labels["top_bottom"],
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                color=cat_colors["left_right"],
                label=cat_labels["left_right"],
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                color=cat_colors["corner"],
                label=cat_labels["corner"],
            ),
        ]

        if dropped_flags is not None and dropped_flags.any():
            legend_handles.append(
                Line2D(
                    [0],
                    [0],
                    marker="x",
                    linestyle="None",
                    color="black",
                    label="Dropped by solver",
                )
            )

        fig.legend(
            handles=legend_handles,
            loc="upper center",
            ncol=4,
            bbox_to_anchor=(0.5, 1.03),
        )

        fig.suptitle("Pairwise correlation ranked by orientation group", y=1.08)
        fig.tight_layout()
        save_figure_to_s3(fig, corr_png_s3, self.s3)
        plt.close(fig)

        # -------- Shifts plots, original grouped layout with all links --------
        shift_arrays = [sx, sy, sz]
        axis_labels = ["X", "Y", "Z"]

        x_base = {cat: i for i, cat in enumerate(cat_order)}

        shifts_all_png_s3 = s3_path_join(self.out_s3_prefix, "shifts_all.png")
        fig, axes = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

        for ax, shifts, axis_label in zip(axes, shift_arrays, axis_labels):
            for cat in cat_order:
                idxs_cat = [i for i, a in enumerate(aligns) if a == cat]
                if not idxs_cat:
                    continue

                idxs_cat = np.array(idxs_cat, dtype=int)
                y_vals = shifts[idxs_cat]

                n_cat = len(idxs_cat)
                if n_cat == 1:
                    offsets = np.array([0.0])
                else:
                    offsets = np.linspace(-0.4, 0.4, n_cat)

                x_vals = x_base[cat] + offsets

                if dropped_flags is None:
                    ax.scatter(
                        x_vals,
                        y_vals,
                        s=10,
                        color=cat_colors[cat],
                        label=cat_labels[cat],
                    )
                else:
                    local_dropped = dropped_flags[idxs_cat]
                    keep_idx = np.where(~local_dropped)[0]
                    drop_idx = np.where(local_dropped)[0]

                    if keep_idx.size > 0:
                        ax.scatter(
                            x_vals[keep_idx],
                            y_vals[keep_idx],
                            s=10,
                            color=cat_colors[cat],
                            label=cat_labels[cat],
                        )

                    if drop_idx.size > 0:
                        ax.scatter(
                            x_vals[drop_idx],
                            y_vals[drop_idx],
                            s=30,
                            color="red",
                            marker="x",
                        )

            ymin, ymax = self._axis_min_max(shifts)
            ax.set_ylim(ymin, ymax)
            ax.set_ylabel(f"Shift{axis_label} (pixels)")
            ax.set_title(f"Shift{axis_label} by orientation group")

        axes[-1].set_xticks(list(x_base.values()))
        axes[-1].set_xticklabels(
            [cat_labels[c] for c in cat_order],
            rotation=15,
        )
        axes[-1].set_xlabel("Link orientation group")

        fig.tight_layout()
        save_figure_to_s3(fig, shifts_all_png_s3, self.s3)
        plt.close(fig)

        # -------- Shifts kept only, one chart per orientation category --------
        if dropped_flags is not None and dropped_flags.any():
            kept_flags = ~dropped_flags

            if kept_flags.any():
                shifts_kept_png_s3 = None

                for cat in cat_order:
                    kept_cat_idxs = [
                        i
                        for i in range(len(aligns))
                        if kept_flags[i] and aligns[i] == cat
                    ]

                    if not kept_cat_idxs:
                        print(f"No kept pairs for {cat_labels[cat]}")
                        continue

                    kept_cat_idxs = np.array(kept_cat_idxs, dtype=int)

                    out_name = f"shifts_kept_{cat}.png"
                    kept_cat_png_s3 = s3_path_join(self.out_s3_prefix, out_name)

                    fig, axes = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

                    for ax, shifts, axis_label in zip(axes, shift_arrays, axis_labels):
                        y_vals = shifts[kept_cat_idxs]

                        n_cat = len(kept_cat_idxs)
                        if n_cat == 1:
                            x_vals = np.array([0.0])
                        else:
                            x_vals = np.linspace(-0.4, 0.4, n_cat)

                        ax.scatter(
                            x_vals,
                            y_vals,
                            s=10,
                            color=cat_colors[cat],
                            label=cat_labels[cat],
                        )

                        ymin, ymax = self._axis_min_max(y_vals)
                        ax.set_ylim(ymin, ymax)
                        ax.set_ylabel(f"Shift{axis_label} (pixels)")
                        ax.set_title(
                            f"Shift{axis_label} for {cat_labels[cat]} kept only"
                        )
                        ax.grid(True, alpha=0.25)

                    axes[-1].set_xticks([0.0])
                    axes[-1].set_xticklabels([cat_labels[cat]], rotation=15)
                    axes[-1].set_xlabel("Link orientation group")

                    fig.suptitle(
                        f"Pairwise shifts for {cat_labels[cat]} kept only",
                        y=1.02,
                    )

                    fig.tight_layout()
                    save_figure_to_s3(fig, kept_cat_png_s3, self.s3)
                    plt.close(fig)

                    print(f"Kept shift plot for {cat_labels[cat]}:", kept_cat_png_s3)

                    # Keep return signature compatible by returning the first kept category plot.
                    if shifts_kept_png_s3 is None:
                        shifts_kept_png_s3 = kept_cat_png_s3

                if shifts_kept_png_s3 is None:
                    shifts_kept_png_s3 = shifts_all_png_s3
            else:
                shifts_kept_png_s3 = shifts_all_png_s3
        else:
            shifts_kept_png_s3 = shifts_all_png_s3

        print("Pair counts by orientation:")
        for cat in cat_order:
            n_cat = sum(1 for a in aligns if a == cat)
            print(f"  {cat_labels[cat]}: {n_cat}")

        if dropped_flags is not None:
            print("Dropped pair count:", int(dropped_flags.sum()))

        print("ShiftX min/max:", float(sx.min()), float(sx.max()))
        print("ShiftY min/max:", float(sy.min()), float(sy.max()))
        print("ShiftZ min/max:", float(sz.min()), float(sz.max()))

        return corr_png_s3, shifts_all_png_s3, shifts_kept_png_s3