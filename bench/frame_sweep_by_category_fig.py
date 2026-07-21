#!/usr/bin/env python
"""Editorial line chart: CVBench accuracy vs. frame budget, by task category.

Presentation = 2x2 stitch, model = InternVL3-8B, 1000 CVBench questions x 4 passes.

The numbers are recomputed from the raw pooled run so the figure is reproducible
end-to-end: for each frame budget and task category we take the per-pass accuracy
(correct / total within each of the 4 seeds), then report the mean and the
population std across those 4 passes -- the same statistic bench/report.py prints
(statistics.pstdev). If the raw jsonl is missing we fall back to the frozen
verified arrays and print a warning.

    conda activate cvbench
    python -m bench.frame_sweep_by_category_fig      # or: python bench/frame_sweep_by_category_fig.py

Outputs (300-dpi raster + vector) to figs/graphs/:
    frame_sweep_by_category.png / .pdf / .svg
"""
import json
import os
import warnings
from collections import defaultdict
from statistics import mean as _mean, pstdev as _pstdev

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter  # noqa: E402

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
COMBINED = os.path.join(REPO, "bench", "results",
                        "bench_cvbench_STITCH_SWEEP_combined.jsonl")
OUT_DIR = os.path.join(REPO, "figs", "graphs")
OUT_STEM = os.path.join(OUT_DIR, "frame_sweep_by_category")

# method tag (in the combined jsonl) -> frame budget
METHOD_FRAMES = {
    "stitch08_f8": 8, "stitch16_f16": 16, "stitch32_f32": 32,
    "stitch64_f64": 64, "stitch128_f128": 128,
}
FRAMES = [8, 16, 32, 64, 128]
CLIP_SECONDS = 300.0  # effective fps = frames / clip length; ~5-min clips
FPS = {f: round(f / CLIP_SECONDS, 2) for f in FRAMES}  # 0.03,0.05,0.11,0.21,0.43

# category display name -> task_type string in the data (None = pooled overall)
CATS = {
    "Overall":            None,
    "Temporal Reasoning": "Multi-video Temporal Reasoning",
    "Event Retrieval":    "Cross-video Event Retrieval",
    "Spatial Navigating": "Joint-video Spatial Navigating",
}

# Frozen fallback (verified 2026-07-20 pooled report) -- means and per-pass pstd,
# both in accuracy %. Used only if the raw jsonl cannot be found.
FALLBACK_MEAN = {
    "Overall":            [57.75, 57.42, 57.55, 55.75, 54.88],
    "Temporal Reasoning": [50.33, 45.00, 43.33, 35.00, 36.67],
    "Event Retrieval":    [56.12, 52.55, 52.04, 50.00, 44.39],
    "Spatial Navigating": [38.10, 41.07, 42.26, 44.64, 46.43],
}
FALLBACK_STD = {
    "Overall":            [0.62, 1.41, 0.73, 0.49, 0.75],
    "Temporal Reasoning": [3.82, 4.46, 4.47, 3.32, 7.21],
    "Event Retrieval":    [6.85, 0.88, 1.77, 6.04, 4.65],
    "Spatial Navigating": [5.05, 7.41, 1.97, 7.96, 7.62],
}


def load_from_raw():
    """Return (mean%, std%) dicts keyed by category, each a list over FRAMES."""
    # method -> cat -> pass_idx -> [correct, total]
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0])))
    with open(COMBINED) as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            m = r.get("method")
            if m not in METHOD_FRAMES:
                continue
            tt, pi, correct = r.get("task_type"), r.get("pass_idx"), bool(r.get("correct"))
            for cat, filt in CATS.items():
                if filt is None or tt == filt:
                    cell = agg[m][cat][pi]
                    cell[1] += 1
                    cell[0] += 1 if correct else 0

    means, stds = {}, {}
    inv = {v: k for k, v in METHOD_FRAMES.items()}
    for cat in CATS:
        m_row, s_row = [], []
        for f in FRAMES:
            method = inv[f]
            per_pass = []
            for pi in sorted(agg[method][cat]):
                cor, tot = agg[method][cat][pi]
                if tot:
                    per_pass.append(cor / tot)
            m_row.append(100 * _mean(per_pass))
            s_row.append(100 * (_pstdev(per_pass) if len(per_pass) > 1 else 0.0))
        means[cat], stds[cat] = m_row, s_row
    return means, stds


def get_data():
    if os.path.exists(COMBINED):
        try:
            return load_from_raw(), "raw pooled jsonl (recomputed)"
        except Exception as e:  # pragma: no cover
            warnings.warn(f"failed to recompute from raw ({e}); using frozen fallback")
    else:
        warnings.warn(
            f"WARNING: {COMBINED} not found -- plotting FROZEN FALLBACK numbers, "
            "not a live recompute.")
    return (FALLBACK_MEAN, FALLBACK_STD), "frozen fallback arrays"


# --------------------------------------------------------------------------- #
# Reusable editorial style -- an rcParams block, drop into any figure script.
# --------------------------------------------------------------------------- #
INK = "#1a1a1a"      # primary text / near-black
INK_SOFT = "#4d4d4d"  # secondary text
MUTED = "#8a8a8a"    # tertiary (fps row, footnote)
GRID = "#ededed"
SPINE = "#3d3d3d"

EDITORIAL_RC = {
    # type: a clean sans; resolves to Liberation Sans (Helvetica-metric) here,
    # honouring the Inter/Source Sans/Helvetica preference where installed.
    "font.family": "sans-serif",
    "font.sans-serif": ["Inter", "Source Sans Pro", "Source Sans 3", "Helvetica",
                        "Helvetica Neue", "Arial", "Liberation Sans",
                        "Nimbus Sans", "DejaVu Sans"],
    "font.size": 11,
    "text.color": INK,
    "axes.edgecolor": SPINE,
    "axes.linewidth": 0.8,
    "axes.labelcolor": INK,
    "axes.labelsize": 11,
    "axes.titlesize": 15,
    "axes.titlecolor": INK,
    "axes.titlelocation": "left",
    "axes.titlepad": 12,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.axisbelow": True,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": SPINE,
    "ytick.color": SPINE,
    "xtick.labelcolor": INK_SOFT,
    "ytick.labelcolor": INK_SOFT,
    "xtick.labelsize": 10.5,
    "ytick.labelsize": 10.5,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "xtick.major.size": 4,
    "ytick.major.size": 0,      # y ticks read off the gridlines; no stubs
    "xtick.major.width": 0.8,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "svg.fonttype": "none",     # keep SVG text as editable text
    "pdf.fonttype": 42,         # embed TrueType in PDF (text stays text)
    "figure.dpi": 150,
}

# entity -> hue (validated: all six data-viz checks pass, light surface)
COLOR = {
    "Overall":            "#1F1B18",  # near-black reference
    "Temporal Reasoning": "#A63D2C",  # muted rust  (faller, warm)
    "Event Retrieval":    "#BC8A1E",  # muted ochre (faller, warm)
    "Spatial Navigating": "#068A72",  # muted teal-green (riser, cool)
}
LW = {"Overall": 2.4, "Temporal Reasoning": 1.7,
      "Event Retrieval": 1.7, "Spatial Navigating": 1.7}
ZORD = {"Temporal Reasoning": 3, "Event Retrieval": 3,
        "Spatial Navigating": 3, "Overall": 5}
ORDER = ["Overall", "Temporal Reasoning", "Event Retrieval", "Spatial Navigating"]


def decollide(targets, min_gap, lo, hi):
    """Nudge label y-positions apart by >= min_gap, keeping within [lo, hi].

    targets: dict name -> desired y. Returns dict name -> adjusted y.
    """
    names = sorted(targets, key=lambda k: targets[k])
    ys = [targets[n] for n in names]
    # forward pass: push up
    for i in range(1, len(ys)):
        if ys[i] - ys[i - 1] < min_gap:
            ys[i] = ys[i - 1] + min_gap
    # if we overran the top, slide the whole stack down
    overflow = ys[-1] - hi
    if overflow > 0:
        ys = [y - overflow for y in ys]
    # backward pass in case sliding down collided at the bottom
    for i in range(len(ys) - 2, -1, -1):
        if ys[i + 1] - ys[i] < min_gap:
            ys[i] = ys[i + 1] - min_gap
    ys = [max(lo, y) for y in ys]
    return dict(zip(names, ys))


def main():
    (means, stds), provenance = get_data()

    # ---- print the exact arrays being plotted -----------------------------
    print(f"\nData source: {provenance}")
    print(f"Frame budgets : {FRAMES}")
    print(f"Effective fps : {[FPS[f] for f in FRAMES]}  (= frames / {CLIP_SECONDS:.0f}s clip)\n")
    print(f"{'category':20s} | " + " | ".join(f"f{f:<3d}" for f in FRAMES))
    print("-" * 66)
    for cat in ORDER:
        cells = " | ".join(f"{m:4.1f}" for m in means[cat])
        print(f"{cat:20s} | {cells}   (accuracy %)")
        scells = " | ".join(f"{s:4.1f}" for s in stds[cat])
        print(f"{'  +/- pass std':20s} | {scells}")
    print()

    # ---- figure ------------------------------------------------------------
    plt.rcParams.update(EDITORIAL_RC)
    fig, ax = plt.subplots(figsize=(9, 5))
    fig.subplots_adjust(left=0.115, right=0.815, top=0.84, bottom=0.215)

    ax.set_xscale("log", base=2)

    # faint +/-1 std bands (drawn first, under the lines)
    for cat in ORDER:
        m, s = means[cat], stds[cat]
        ax.fill_between(FRAMES, [a - b for a, b in zip(m, s)],
                        [a + b for a, b in zip(m, s)],
                        color=COLOR[cat], alpha=0.09, linewidth=0, zorder=1)

    # lines + markers
    for cat in ORDER:
        ax.plot(FRAMES, means[cat], color=COLOR[cat], lw=LW[cat],
                solid_capstyle="round", solid_joinstyle="round",
                marker="o", markersize=5.5, markerfacecolor=COLOR[cat],
                markeredgecolor="white", markeredgewidth=0.9, zorder=ZORD[cat])

    # ---- axes limits & ticks ----------------------------------------------
    ax.set_xlim(7.1, 205)          # right room for the direct labels
    ax.set_ylim(29, 72)
    ax.set_yticks([30, 40, 50, 60, 70])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}"))

    ax.xaxis.set_major_locator(FixedLocator(FRAMES))
    ax.xaxis.set_minor_locator(FixedLocator([]))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(round(v))}"))

    # Tufte-ish: trim spines to the data range so they don't run into margins
    ax.spines["left"].set_bounds(30, 70)
    ax.spines["bottom"].set_bounds(8, 128)

    ax.set_ylabel("accuracy (%)")

    # ---- second tick row: effective fps under each frame tick -------------
    trans = ax.get_xaxis_transform()  # x in data, y in axes fraction
    for f in FRAMES:
        ax.text(f, -0.075, f"{FPS[f]:.2f}", transform=trans, ha="center",
                va="top", fontsize=8.5, color=MUTED)
    # row labels at the far left, aligned to each row
    ax.text(-0.028, -0.038, "frames", transform=ax.transAxes, ha="right",
            va="top", fontsize=9, color=INK_SOFT)
    ax.text(-0.028, -0.075, "eff. fps", transform=ax.transAxes, ha="right",
            va="top", fontsize=8.5, color=MUTED, style="italic")

    # ---- direct labels at the right end, de-collided ----------------------
    ends = {cat: means[cat][-1] for cat in ORDER}
    label_y = decollide(dict(ends), min_gap=2.8, lo=30.5, hi=71.0)
    x_text = 128 * 2 ** 0.07       # just right of the f128 marker
    for cat in ORDER:
        ye, yl = ends[cat], label_y[cat]
        if abs(yl - ye) > 0.35:    # thin leader when the label was nudged
            ax.plot([128, x_text], [ye, yl], color=COLOR[cat], lw=0.6,
                    alpha=0.55, zorder=2, clip_on=False)
        ax.text(x_text * 1.04, yl, cat, color=COLOR[cat], fontsize=10,
                va="center", ha="left", clip_on=False)

    # ---- title (neutral, descriptive) & finding caption (below axes) ------
    ax.set_title("CVBench accuracy vs. frame budget, by task category\n"
                 "(2×2-stitch, InternVL3-8B)", loc="left", linespacing=1.35)

    fig.text(0.115, 0.055,
             "Overall flat then falling; temporal-ordering tasks degrade with "
             "more frames, spatial navigation improves.",
             ha="left", va="center", fontsize=9.5, color=INK_SOFT)
    fig.text(0.115, 0.018,
             f"1000 CVBench questions × 4 passes; bands = ±1 std across "
             f"passes.  Effective fps = frames ÷ {CLIP_SECONDS:.0f}s clip.",
             ha="left", va="center", fontsize=8, color=MUTED)

    # ---- export -----------------------------------------------------------
    os.makedirs(OUT_DIR, exist_ok=True)
    for ext, dpi in (("png", 300), ("pdf", None), ("svg", None)):
        kw = {"dpi": dpi} if dpi else {}
        fig.savefig(f"{OUT_STEM}.{ext}", **kw)
    plt.close(fig)
    print("Wrote:")
    for ext in ("png", "pdf", "svg"):
        print(f"  {os.path.relpath(f'{OUT_STEM}.{ext}', REPO)}")


if __name__ == "__main__":
    main()
