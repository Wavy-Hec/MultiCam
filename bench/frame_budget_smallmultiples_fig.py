#!/usr/bin/env python
"""Small multiples: CVBench accuracy vs. frame budget, one panel per task type.

Presentation = 2x2 stitch, model = InternVL3-8B, 1000 CVBench questions x 4 passes.
This is the reproducible rebuild of analysis/figs_wednesday/fig1_frame_budget_by_category.png,
with a random-guessing (chance) reference added to every panel.

Everything is recomputed from the raw pooled run: for each frame budget and task
type we take the per-pass accuracy (correct / total within each of the 4 seeds),
then the mean and the population std across those 4 passes -- the same statistic
bench/report.py prints. Panels are ordered Overall first, then by accuracy gain
from 8 to 128 frames (descending).

The dashed line in each panel is that task type's chance level from
bench/chance_level.py: the accuracy of a guesser picking uniformly among the
options it is shown, = mean over that panel's questions of 1 / n_options. It is
not a flat 25% -- Cross-video Scene Recognition is mostly yes/no, so its chance
is 45.5%, and the pooled Overall panel sits at 28.5%.

    conda activate cvbench
    python -m bench.frame_budget_smallmultiples_fig

Outputs to figs/graphs/ (png 300 dpi + pdf + svg) and a png copy next to the
original in analysis/figs_wednesday/.
"""
import json
import os
import textwrap
import warnings
from collections import defaultdict
from statistics import mean as _mean, pstdev as _pstdev

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter  # noqa: E402

try:
    from bench.chance_level import chance_table
except ImportError:  # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from bench.chance_level import chance_table

# --------------------------------------------------------------------------- #
# Paths / constants
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
COMBINED = os.path.join(REPO, "bench", "results",
                        "bench_cvbench_STITCH_SWEEP_combined.jsonl")
OUT_DIR = os.path.join(REPO, "figs", "graphs")
OUT_STEM = os.path.join(OUT_DIR, "frame_budget_smallmultiples")
SIDECAR = os.path.join(REPO, "analysis", "figs_wednesday",
                       "fig1_frame_budget_by_category_chance.png")

METHOD_FRAMES = {
    "stitch08_f8": 8, "stitch16_f16": 16, "stitch32_f32": 32,
    "stitch64_f64": 64, "stitch128_f128": 128,
}
FRAMES = [8, 16, 32, 64, 128]
OVERALL = "Overall"          # pooled pseudo-category key

# --------------------------------------------------------------------------- #
# Style (matches the original wednesday figure's palette)
# --------------------------------------------------------------------------- #
INK = "#26251f"
MUTED = "#6e6a5e"
GRID = "#e8e6df"
SPINE = "#ced4da"
BLUE = "#1f5fbf"

RC = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Inter", "Source Sans Pro", "Source Sans 3", "Helvetica",
                        "Helvetica Neue", "Arial", "Liberation Sans",
                        "Nimbus Sans", "DejaVu Sans"],
    "font.size": 10,
    "text.color": INK,
    "axes.edgecolor": SPINE,
    "axes.linewidth": 0.8,
    "axes.labelcolor": MUTED,
    "axes.axisbelow": True,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": SPINE,
    "ytick.color": SPINE,
    "xtick.labelcolor": MUTED,
    "ytick.labelcolor": MUTED,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "xtick.major.size": 3,
    "ytick.major.size": 0,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    "figure.dpi": 150,
}

# Low enough to seat the ~25% chance lines with a clear strip underneath for the
# gain annotation, high enough for the Multi-video Attribute band (peaks ~83).
YLIM = (16, 92)
YTICKS = [40, 60, 80]


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_from_raw():
    """-> {task_type or 'Overall': {'mean': [...], 'std': [...], 'n': int}}."""
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0])))
    with open(COMBINED) as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            m = r.get("method")
            if m not in METHOD_FRAMES:
                continue
            correct = 1 if r.get("correct") else 0
            for key in (r.get("task_type"), OVERALL):
                cell = agg[m][key][r.get("pass_idx")]
                cell[1] += 1
                cell[0] += correct

    inv = {v: k for k, v in METHOD_FRAMES.items()}
    out = {}
    for key in agg[inv[8]]:
        means, stds = [], []
        for f in FRAMES:
            per_pass = [c / t for c, t in agg[inv[f]][key].values() if t]
            means.append(100 * _mean(per_pass))
            stds.append(100 * (_pstdev(per_pass) if len(per_pass) > 1 else 0.0))
        n_passes = len(agg[inv[8]][key]) or 1
        n_q = sum(t for _, t in agg[inv[8]][key].values()) // n_passes
        out[key] = {"mean": means, "std": stds, "n": n_q}
    return out


def get_data():
    if not os.path.exists(COMBINED):
        raise SystemExit(
            f"ERROR: {os.path.relpath(COMBINED, REPO)} not found. This figure is "
            "recomputed from the raw pooled sweep; re-pool it with "
            "bench/pool_stitch_sweep.sh first.")
    return load_from_raw()


def get_chance(series):
    per_task, overall, _, prov = chance_table()
    chance = {}
    for key in series:
        if key == OVERALL:
            chance[key] = overall
        elif key in per_task:
            chance[key] = per_task[key]
        else:
            warnings.warn(f"no chance level for {key!r}; falling back to 25%")
            chance[key] = 25.0
    return chance, prov


# --------------------------------------------------------------------------- #
# Figure
# --------------------------------------------------------------------------- #
def panel(ax, ys, ss, chance, color, is_overall, title, n_q, bottom_row, left_col):
    lo = [a - b for a, b in zip(ys, ss)]
    hi = [a + b for a, b in zip(ys, ss)]

    ax.set_xscale("log", base=2)
    ax.set_xlim(7.2, 142)
    ax.set_ylim(*YLIM)

    # chance reference, drawn under everything
    ax.plot([8, 128], [chance] * 2, color=color, lw=1.0, linestyle=(0, (4, 3)),
            alpha=0.5, zorder=1, solid_capstyle="butt")
    ax.text(8.3, chance + 1.2, f"chance {chance:.1f}%", color=color, alpha=0.85,
            fontsize=7.5, ha="left", va="bottom", zorder=4)

    ax.fill_between(FRAMES, lo, hi, color=color, alpha=0.13, linewidth=0, zorder=2)
    ax.plot(FRAMES, ys, color=color, lw=2.0, solid_capstyle="round",
            solid_joinstyle="round", zorder=3)

    # dot + value at the best budget
    best = max(range(len(ys)), key=lambda i: ys[i])
    ax.plot([FRAMES[best]], [ys[best]], marker="o", markersize=6, color=color,
            markeredgecolor="white", markeredgewidth=0.9, zorder=5)
    ha = "left" if best == 0 else ("right" if best == len(ys) - 1 else "center")
    dx = {"left": 1.06, "right": 0.94, "center": 1.0}[ha]
    ax.text(FRAMES[best] * dx, ys[best] + 3.0, f"{ys[best]:.0f}", color=color,
            fontsize=10, fontweight="bold", ha=ha, va="bottom", zorder=5)

    # gain annotation, bottom-right -- sits below the chance line, opposite its label
    gain = ys[-1] - ys[0]
    # white bbox so the chance line reads as interrupted, not struck through
    ax.text(0.975, 0.03, f"{gain:+.1f} pts @128 vs 8", transform=ax.transAxes,
            color=MUTED, fontsize=8.5, ha="right", va="bottom", zorder=6,
            bbox=dict(facecolor="white", edgecolor="none", pad=1.5))

    ax.xaxis.set_major_locator(FixedLocator(FRAMES))
    ax.xaxis.set_minor_locator(FixedLocator([]))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(round(v))}"))
    ax.set_yticks(YTICKS)
    if not bottom_row:
        ax.set_xticklabels([])
    if not left_col:
        ax.set_yticklabels([])

    label = f"{title} ({n_q} Q)" if is_overall else title
    ax.set_title("\n".join(textwrap.wrap(label, 26)), fontsize=10.5,
                 color=INK, fontweight="bold" if is_overall else "normal",
                 pad=8, linespacing=1.25)


def main():
    series = get_data()
    chance, chance_prov = get_chance(series)

    # Overall first, then by gain 8 -> 128, descending
    tasks = [k for k in series if k != OVERALL]
    tasks.sort(key=lambda k: -(series[k]["mean"][-1] - series[k]["mean"][0]))
    order = [OVERALL] + tasks

    # ---- print the exact arrays being plotted ------------------------------
    print(f"\nData source   : {os.path.relpath(COMBINED, REPO)} (recomputed)")
    print(f"Chance source : {chance_prov}")
    print(f"Frame budgets : {FRAMES}\n")
    print(f"{'panel':38s} {'n':>5s}  " + "".join(f"f{f:<6d}" for f in FRAMES)
          + f"{'gain':>7s} {'chance':>7s} {'best-chance':>12s}")
    print("-" * 108)
    for k in order:
        d = series[k]
        cells = "".join(f"{m:5.1f} " for m in d["mean"])
        gain = d["mean"][-1] - d["mean"][0]
        print(f"{k:38s} {d['n']:5d}  {cells}{gain:+7.1f} {chance[k]:7.1f} "
              f"{max(d['mean']) - chance[k]:+12.1f}")
    print()

    # ---- figure ------------------------------------------------------------
    plt.rcParams.update(RC)
    fig, axes = plt.subplots(4, 4, figsize=(13, 7.7))
    fig.subplots_adjust(left=0.055, right=0.988, top=0.825, bottom=0.10,
                        hspace=0.62, wspace=0.10)

    for i, key in enumerate(order):
        r, c = divmod(i, 4)
        ax = axes[r][c]
        d = series[key]
        panel(ax, d["mean"], d["std"], chance[key],
              INK if key == OVERALL else BLUE, key == OVERALL,
              key, d["n"], bottom_row=(r == 3), left_col=(c == 0))
    for j in range(len(order), 16):          # blank any unused cells
        axes[j // 4][j % 4].axis("off")

    fig.suptitle("More frames don't help: overall flat then falling — "
                 "temporal-ordering categories degrade most",
                 x=0.055, y=0.978, ha="left", fontsize=15, fontweight="bold",
                 color=INK)
    fig.text(0.055, 0.945,
             "2×2-stitch presentation · InternVL3-8B · 1000 CVBench questions × 4 "
             "passes · line = mean, band = ±1 std, dot = best budget · panels "
             "sorted by gain 8→128",
             ha="left", va="center", fontsize=10, color=MUTED)
    fig.text(0.055, 0.915,
             "Dashed = chance, the score of a uniform random guesser: mean over that "
             "panel's questions of 1∕(number of answer options). Not a flat 25% — "
             "Cross-video Scene Recognition is mostly yes/no.",
             ha="left", va="center", fontsize=9, color=MUTED)

    fig.text(0.012, 0.46, "accuracy (%)", rotation=90, ha="center", va="center",
             fontsize=10, color=MUTED)
    fig.text(0.52, 0.026,
             "frame budget (stitched 2×2 timesteps per question, log scale)",
             ha="center", va="center", fontsize=10, color=MUTED)

    # ---- export -------------------------------------------------------------
    os.makedirs(OUT_DIR, exist_ok=True)
    for ext, dpi in (("png", 300), ("pdf", None), ("svg", None)):
        fig.savefig(f"{OUT_STEM}.{ext}", **({"dpi": dpi} if dpi else {}))
    os.makedirs(os.path.dirname(SIDECAR), exist_ok=True)
    fig.savefig(SIDECAR, dpi=200)
    plt.close(fig)

    print("Wrote:")
    for ext in ("png", "pdf", "svg"):
        print(f"  {os.path.relpath(f'{OUT_STEM}.{ext}', REPO)}")
    print(f"  {os.path.relpath(SIDECAR, REPO)}")


if __name__ == "__main__":
    main()
