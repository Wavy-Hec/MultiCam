#!/usr/bin/env python3
"""Figures for the CVBench text-only (no video) legs on Qwen3.8-27B, next to
everything else run on CVBench.

Inputs:
  --bm / --nt   the analysis JSONs analysis/cvbench_text_answerability.py writes
                for the thinking leg (_q38bm) and the no-thinking control (_q38nt),
                each run with --blind-o2 so both option orders are present
  --results     bench/results (the legs' raw rows: answer letters, trace lengths)
  --archive     the Era-1 rows extracted from ~/cvbench_archive_2026-07-27.tgz
                (its bench/results/ directory): InternVL3-8B with video, 1000 q x 4

Writes fig_cvbench_*.png and fig_cvbench_data.json (every plotted number - the
table view of each chart) into --out. Nothing else.

Colour by job (reference palette of the dataviz method, validated): categorical
blue = Qwen3.8 thinking, orange = Qwen3.8 no thinking, aqua = InternVL3-8B with
video; references (chance, key floors, bias null) in muted gray; the
both/one/neither stacks on one ordinal blue ramp; the reasoning delta on the
blue/red diverging pair.

Run (no GPU):
  python3 analysis/make_cvbench_text_figs.py \\
      --bm analysis/records/cvbench_text_answerability_q38bm.json \\
      --nt analysis/records/cvbench_text_answerability_q38nt.json \\
      --archive <extracted archive>/bench/results --out analysis/figs_deck
"""
import argparse
import glob
import json
import math
import os
from collections import Counter, defaultdict
from statistics import mean, pstdev, stdev

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                          # noqa: E402
from matplotlib.path import Path                          # noqa: E402
from matplotlib.patches import PathPatch                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

SURF, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASE = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"
BLUE_FADED, RED_FADED = "#a9c9f0", "#f2b3b2"            # the same hues at ~40% on SURF
ORD = ["#184f95", "#3987e5", "#86b6ef"]                  # both / one order / neither
SEQ = ["#fcfcfb", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DPI_LAYOUT, DPI_SAVE = 100, 200                          # design in px at 100 dpi, save 2x
PT = 72 / DPI_LAYOUT                                     # points per layout px

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
    "axes.facecolor": SURF, "figure.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": BASE, "axes.labelcolor": INK2, "axes.linewidth": 1 * PT,
    "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 9, "ytick.labelsize": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False, "legend.fontsize": 9,
})

ARMS = [  # (archive tag, label) - Era 1, InternVL3-8B, 1000 q x 4 passes, T 0.7
    ("fulldur", "sequential, duration-weighted (64 frames)"),
    ("fulleven", "sequential, even split (64 frames)"),
    ("fullstitch8", "grid stitch, 8 montages"),
    ("fullstitch", "grid stitch, 16 montages"),
    ("fullstitch32", "grid stitch, 32 montages"),
    ("fullstitch64", "grid stitch, 64 montages"),
    ("fullstitch128", "grid stitch, 128 montages"),
    ("fullperstream", "per-stream describe + text aggregator"),
]
SHORT = {"Cross-video Anomaly Detection": "Anomaly Detection",
         "Cross-video Counterfactual Reasoning": "Counterfactual Reasoning",
         "Cross-video Entity Matching": "Entity Matching",
         "Cross-video Event Retrieval": "Event Retrieval",
         "Cross-video Object Recognition": "Object Recognition",
         "Cross-video Procedural Transfer": "Procedural Transfer",
         "Cross-video Scene Recognition": "Scene Recognition",
         "Joint-video Counting": "Counting",
         "Joint-video Spatial Navigating": "Spatial Navigating",
         "Joint-video Summarization": "Summarization",
         "Multi-video Attribute Recognition": "Attribute Recognition",
         "Multi-video Key-Action Recognition": "Key-Action Recognition",
         "Multi-video Temporal Reasoning": "Temporal Reasoning",
         "Multi-view Scene Understanding": "Multi-view Scene Underst.",
         "Video Difference Caption": "Video Difference Caption"}


# ------------------------------------------------------------------ data ---

def rows_of(pattern):
    out = []
    for f in sorted(glob.glob(pattern)):
        if f.endswith("_summary.json"):
            continue
        with open(f) as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def per_pass(rows):
    by = defaultdict(list)
    for r in rows:
        by[r.get("pass_idx")].append(1.0 if r.get("correct") is True else 0.0)
    accs = [100 * mean(v) for _, v in sorted(by.items()) if v]
    return mean(accs), (pstdev(accs) if len(accs) > 1 else 0.0)


def per_question(rows):
    q = defaultdict(list)
    for r in rows:
        q[r["id"]].append(r.get("correct") is True)
    return q


def two_order_mean(j, getter):
    vals = [getter(j[o]) for o in ("O1", "O2") if o in j]
    return mean(vals), vals


def exact_acc(s):
    """Accuracy from the summary's row counts (unrounded); the 2-dp mean if they are absent."""
    return 100 * s["n_correct"] / s["n_rows"] if s.get("n_correct") is not None else s["accuracy"]["mean"]


# --------------------------------------------------------------- drawing ---

def px_scale(ax):
    """Data units per layout pixel along x and y (after limits are final)."""
    (x0, y0), (x1, y1) = ax.transData.transform([(0, 0), (1, 1)]) / (DPI_SAVE / DPI_LAYOUT)
    return 1 / abs(x1 - x0), 1 / abs(y1 - y0)


def hbar(ax, y, x0, x1, h, color, round_end=True, gap_px=0):
    """Horizontal bar from x0 to x1 (x1 may be < x0), height h, square at x0
    and a 4px rounded data end at x1; gap_px trims the data end (surface gap
    between stacked segments)."""
    ux, uy = px_scale(ax)
    sgn = 1 if x1 >= x0 else -1
    x1 = x1 - sgn * gap_px * ux
    if (x1 - x0) * sgn <= 0:
        return
    rx = min(4 * ux, abs(x1 - x0) / 2) if round_end else 0
    ry = min(4 * uy, h / 2) if round_end else 0
    yb, yt = y - h / 2, y + h / 2
    if rx == 0:
        verts = [(x0, yb), (x1, yb), (x1, yt), (x0, yt), (x0, yb)]
        codes = [Path.MOVETO] + [Path.LINETO] * 3 + [Path.CLOSEPOLY]
    else:
        e = x1 - sgn * rx
        verts = [(x0, yb), (e, yb), (x1, yb), (x1, yb + ry), (x1, yt - ry), (x1, yt), (e, yt),
                 (x0, yt), (x0, yb)]
        codes = [Path.MOVETO, Path.LINETO, Path.CURVE3, Path.CURVE3, Path.LINETO,
                 Path.CURVE3, Path.CURVE3, Path.LINETO, Path.CLOSEPOLY]
    ax.add_patch(PathPatch(Path(verts, codes), facecolor=color, edgecolor="none", zorder=3))


def vbar(ax, x, y1, w, color):
    """Vertical bar from 0 to y1, width w (data units), 4px rounded data end."""
    ux, uy = px_scale(ax)
    if y1 <= 0:
        return
    rx, ry = min(4 * ux, w / 2), min(4 * uy, y1 / 2)
    xl, xr = x - w / 2, x + w / 2
    verts = [(xl, 0), (xr, 0), (xr, y1 - ry), (xr, y1), (xr - rx, y1), (xl + rx, y1), (xl, y1),
             (xl, y1 - ry), (xl, 0)]
    codes = [Path.MOVETO, Path.LINETO, Path.LINETO, Path.CURVE3, Path.CURVE3, Path.LINETO,
             Path.CURVE3, Path.CURVE3, Path.CLOSEPOLY]
    ax.add_patch(PathPatch(Path(verts, codes), facecolor=color, edgecolor="none", zorder=3))


def bar_h(ax):
    """Bar height in data units: at most 24 layout px, at most 0.62 of a slot."""
    _, uy = px_scale(ax)
    return min(0.62, 22 * uy)


def dot(ax, x, y, color, size_px=10, marker="o", z=5, label=None):
    ax.scatter(x, y, s=(size_px * PT) ** 2, c=color, marker=marker, edgecolors=SURF,
               linewidths=2 * PT, zorder=z, label=label)


def xgrid(ax):
    ax.xaxis.grid(True, color=GRID, linewidth=1 * PT, linestyle="-", zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)


def title(fig, ax, head, sub):
    ax.set_title(head, pad=26)
    ax.text(0, 1.015, sub, transform=ax.transAxes, color=INK2, fontsize=9, va="bottom")


def save(fig, out, name):
    path = os.path.join(out, name)
    fig.savefig(path, dpi=DPI_SAVE, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- figures ---

def fig_overall(D, out):
    rows = [(f"InternVL3-8B WITH video (Era 1 best arm, 1000 q x 4)", D["sighted"]["fulldur"]["acc"], AQUA),
            ("Qwen3.8-27B, NO video, thinking (medium)", D["bm"]["acc"], BLUE),
            ("Qwen3.8-27B, NO video, no thinking", D["nt"]["acc"], ORANGE),
            ("Best answer-key guesser (modal answer per task x answer space, in-sample, O1)",
             D["key_insample"], MUTED),
            ("Pick the longest option (863 lettered questions only)", D["longest"], MUTED),
            ("No-thinking answers shuffled within task x answer space (bias null)", D["nt"]["bias_null_acc"], MUTED),
            ("Thinking answers shuffled within task x answer space (bias null)", D["bm"]["bias_null_acc"], MUTED),
            ("Random guessing (chance)", D["chance"], MUTED)]
    fig, ax = plt.subplots(figsize=(9.2, 4.3), dpi=DPI_LAYOUT)
    ax.set_xlim(0, 75)
    ax.set_ylim(len(rows) - 0.5, -0.6)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    xgrid(ax)
    h = bar_h(ax)
    for i, (_, v, c) in enumerate(rows):
        hbar(ax, i, 0, v, h, c)
        ax.text(v + 1, i, f"{v:.1f}%", va="center", fontsize=9, color=INK)
    ax.set_xlabel("accuracy on the 1000 CVBench questions (%)\n"
                  "Qwen rows and bias nulls = mean of both option orders x 4 seeds")
    title(fig, ax, "CVBench with no video: accuracy vs. answer-key baselines",
          "Qwen3.8-27B given only the question and options, next to the best with-video result (Era 1)")
    return save(fig, out, "fig_cvbench_1_overall.png")


def fig_per_task(D, out):
    tasks = sorted(D["tasks"], key=lambda t: D["tasks"][t]["bm"])
    fig, ax = plt.subplots(figsize=(9.2, 6.6), dpi=DPI_LAYOUT)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.7, len(tasks) - 0.3)
    ax.set_yticks(range(len(tasks)), [f"{SHORT[t]}  (n={D['tasks'][t]['n']})" for t in tasks])
    xgrid(ax)
    off = 0.17                                           # thinking above, no thinking below the row line
    for i, t in enumerate(tasks):
        d = D["tasks"][t]
        ax.plot([d["nt"], d["bm"]], [i - off, i + off], color=BASE, linewidth=2 * PT, zorder=2)
        ax.scatter(d["chance"], i, marker="|", s=(14 * PT) ** 2, c=INK2, linewidths=2 * PT, zorder=4)
        dot(ax, d["sighted"], i, AQUA)
        dot(ax, d["nt"], i - off, ORANGE)
        dot(ax, d["bm"], i + off, BLUE)
        ax.scatter(d["key_insample"], i, marker="D", s=(7 * PT) ** 2, facecolors=SURF,
                   edgecolors=INK2, linewidths=1.5 * PT, zorder=6)
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, markeredgecolor=SURF, markersize=8, label=l)
               for c, l in ((BLUE, "Qwen3.8-27B no video, thinking"), (ORANGE, "Qwen3.8-27B no video, no thinking"),
                            (AQUA, "InternVL3-8B with video (Era 1)"))]
    handles += [plt.Line2D([], [], marker="|", ls="", color=INK2, markersize=10, label="chance"),
                plt.Line2D([], [], marker="D", ls="", markerfacecolor=SURF, markeredgecolor=INK2,
                           markersize=6, label="best answer-key guesser (in-sample, O1)")]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.45, 1.01), ncol=3, columnspacing=1.2)
    ax.set_xlabel("accuracy (%; Qwen = mean of both option orders x 4 seeds; InternVL3 = 4 passes)")
    ax.set_title("Accuracy per task, with and without the video", pad=46)
    return save(fig, out, "fig_cvbench_2_per_task_accuracy.png")


def fig_answerable(D, out):
    tasks = sorted(D["tasks"], key=lambda t: D["tasks"][t]["both_share"], reverse=True)
    labels = ["All 1000 questions"] + [SHORT[t] + (" †" if D["tasks"][t]["p_both_paired"] >= 0.05 else "")
                                       for t in tasks]
    data = [D["both_overall"]] + [D["tasks"][t]["both_split"] for t in tasks]
    fig, ax = plt.subplots(figsize=(9.2, 6.6), dpi=DPI_LAYOUT)
    ax.set_xlim(0, 100)
    ax.set_ylim(len(labels) - 0.4, -0.7)
    ax.set_yticks(range(len(labels)), labels)
    xgrid(ax)
    h = bar_h(ax)
    for i, (both, one, neither, n) in enumerate(data):
        segs = [100 * both / n, 100 * one / n, 100 * neither / n]
        x = 0
        for k, (w, c) in enumerate(zip(segs, ORD)):
            last = k == 2
            hbar(ax, i, x, x + w, h, c, round_end=last, gap_px=0 if last else 2)
            if k == 0 and w >= 8:
                ax.text(x + 1.2, i, f"{w:.0f}%", va="center", fontsize=8.5, color="#ffffff", zorder=6)
            x += w
    ax.get_yticklabels()[0].set_fontweight("bold")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c, label=l) for c, l in
               zip(ORD, ("right in >= 3/4 seeds in BOTH option orders", "in one order only", "in neither order"))]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.42, 1.04), ncol=3, columnspacing=1.2)
    nb = D["both_null_paired"]
    ax.set_xlabel(f"share of the task's questions (%); Qwen3.8-27B thinking, no video\n"
                  f"Its answers shuffled within task x answer space would give {nb['mean']:.0f} of 1000 in both "
                  f"orders (95%: {nb['lo']}-{nb['hi']}; figure 4)\n"
                  f"† = not above that shuffled-answers null for the task (p >= 0.05)")
    ax.set_title("Right in >= 3 of 4 seeds in both option orders, by task", pad=40)
    return save(fig, out, "fig_cvbench_3_text_answerable_by_task.png")


def fig_vs_null(D, out):
    tasks = sorted(D["tasks"], key=lambda t: D["tasks"][t]["both_share"])
    fig, ax = plt.subplots(figsize=(9.2, 6.2), dpi=DPI_LAYOUT)
    ax.set_xlim(-1.5, 100)
    ax.set_ylim(-0.7, len(tasks) - 0.3)
    ax.set_yticks(range(len(tasks)), [SHORT[t] for t in tasks])
    xgrid(ax)
    for i, t in enumerate(tasks):
        d = D["tasks"][t]
        lo, hi = (100 * v / d["n"] for v in d["null_95_both_paired"])
        ax.plot([lo, hi], [i, i], color=BASE, linewidth=6 * PT, solid_capstyle="round", zorder=2)
        ax.scatter(100 * d["null_mean_both_paired"] / d["n"], i, marker="|", s=(12 * PT) ** 2, c=SURF,
                   linewidths=2 * PT, zorder=3)
        ax.scatter(100 * d["chance_both"] / d["n"], i, marker="|", s=(12 * PT) ** 2, c=INK2,
                   linewidths=2 * PT, zorder=3)
        dot(ax, 100 * d["both_split"][0] / d["n"], i, BLUE)
    handles = [plt.Line2D([], [], marker="o", ls="", color=BLUE, markeredgecolor=SURF, markersize=8,
                          label="observed (thinking leg)"),
               plt.Line2D([], [], color=BASE, linewidth=4,
                          label="its answers shuffled within task x answer space: 95% range (white notch = mean)"),
               plt.Line2D([], [], marker="|", ls="", color=INK2, markersize=10, label="pure guessing")]
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.01), ncol=1)
    ax.set_xlabel("questions right in >= 3/4 seeds in both option orders (% of task). The shuffle moves a "
                  "question's O1 and O2\nanswers together, so habits that hold across orders (such as a "
                  "Yes/No preference) stay in the null")
    ax.set_title("Text-answerable share vs. what luck or answer habits alone give", pad=72)
    return save(fig, out, "fig_cvbench_4_observed_vs_null.png")


def fig_hist(D, out):
    series = [("Qwen3.8-27B no video, thinking (O1)", D["hist"]["bm"], BLUE),
              ("Qwen3.8-27B no video, no thinking (O1)", D["hist"]["nt"], ORANGE),
              ("InternVL3-8B with video (Era 1)", D["hist"]["sighted"], AQUA)]
    fig, ax = plt.subplots(figsize=(8.4, 4.0), dpi=DPI_LAYOUT)
    width = 0.24
    ax.set_xlim(-0.6, 4.6)
    ymax = max(max(s[1]) for s in series) * 1.15
    ax.set_ylim(0, ymax)
    ax.yaxis.grid(True, color=GRID, linewidth=1 * PT, zorder=0)
    ax.set_axisbelow(True)
    for k, (lab, h, c) in enumerate(series):
        for x, v in zip(range(5), h):
            vbar(ax, x + (k - 1) * (width + 0.03), v, width, c)
    ax.set_xticks(range(5), [f"{k} of 4" for k in range(5)])
    ax.set_xlabel("passes (seeds) right per question")
    ax.set_ylabel("questions (of 1000)")
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c, label=l) for l, _, c in series],
              loc="upper center", bbox_to_anchor=(0.5, 1.2), ncol=1)
    ax.set_title("Passes right per question (consistency across 4 seeds; option order O1)", pad=58)
    return save(fig, out, "fig_cvbench_5_passes_histogram.png")


def fig_sighted_by_label(D, out):
    cats = [("text-answerable\nin both orders", "both"), ("in one order\nonly", "one"),
            ("in neither\norder", "neither")]
    vals = [D["sighted_by_label"][k] for _, k in cats]
    fig, ax = plt.subplots(figsize=(7.4, 3.9), dpi=DPI_LAYOUT)
    ax.set_ylim(0, 100)
    ax.set_xlim(-0.6, 2.6)
    ax.yaxis.grid(True, color=GRID, linewidth=1 * PT, zorder=0)
    ax.set_axisbelow(True)
    for i, v in enumerate(vals):
        vbar(ax, i, v["acc"], 0.42, AQUA)
        ax.text(i, v["acc"] + 2, f"{v['acc']:.1f}%\n(n={v['n']})", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(range(3), [c for c, _ in cats])
    ax.set_ylabel("InternVL3-8B accuracy WITH video (%)")
    ax.set_title("With-video accuracy, split by the text-only (both-orders) label", pad=30)
    ax.text(0, 1.03, "Era-1 best arm (sequential, duration-weighted, 4 passes), split by the Qwen3.8 thinking label",
            transform=ax.transAxes, color=INK2, fontsize=9)
    return save(fig, out, "fig_cvbench_6_sighted_by_text_label.png")


def fig_delta(D, out):
    tasks = sorted(D["tasks"], key=lambda t: D["tasks"][t]["delta"])
    labels = [SHORT[t] for t in tasks] + ["All 1000 questions"]
    deltas = [D["tasks"][t]["delta"] for t in tasks] + [D["delta_all"]]
    halfw = [1.96 * D["tasks"][t]["delta_se"] for t in tasks] + [1.96 * D["delta_all_se"]]
    lim = max(10, max(abs(d) + w for d, w in zip(deltas, halfw)) + 3.5)   # room for the value labels
    fig, ax = plt.subplots(figsize=(8.6, 6.4), dpi=DPI_LAYOUT)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-0.7, len(labels) - 0.3)
    ax.set_yticks(range(len(labels)), labels)
    ax.get_yticklabels()[-1].set_fontweight("bold")
    xgrid(ax)
    ax.axvline(0, color=BASE, linewidth=1 * PT, zorder=2)
    h = bar_h(ax)
    for i, (d, w) in enumerate(zip(deltas, halfw)):
        clear = abs(d) > w                               # 95% interval excludes 0
        c = BLUE if d >= 0 else RED
        hbar(ax, i, 0, d, h, c if clear else (BLUE_FADED if d >= 0 else RED_FADED))
        ax.plot([d - w, d + w], [i, i], color=INK2, linewidth=1 * PT, zorder=5)
        end = d + w if d >= 0 else d - w
        ax.text(end + (0.5 if d >= 0 else -0.5), i, f"{d:+.1f}", va="center",
                ha="left" if d >= 0 else "right", fontsize=8.5, color=INK2)
    ax.set_xlabel("accuracy change from thinking (percentage points; no video, mean of both orders).\n"
                  "Whisker = 95% interval over questions (paired); pale bar = interval includes 0")
    ax.set_title("Thinking minus no thinking, per task (no video)", pad=12)
    return save(fig, out, "fig_cvbench_7_thinking_minus_nothinking.png")


def fig_letters(D, out):
    fig, axes = plt.subplots(1, 3, figsize=(11.6, 3.9), dpi=DPI_LAYOUT, sharey=True,
                             gridspec_kw={"width_ratios": [4, 4, 2.2]})
    width = 0.24
    for ax, order in zip(axes, ("O1", "O2")):
        L = D["letters"][order]
        series = [("gold answer key", L["gold"], MUTED), ("thinking", L["bm"], BLUE),
                  ("no thinking", L["nt"], ORANGE)]
        ax.yaxis.grid(True, color=GRID, linewidth=1 * PT, zorder=0)
        ax.set_axisbelow(True)
        ax.set_xlim(-0.6, 3.6)
        ax.set_ylim(0, 80)
        for k, (lab, v, c) in enumerate(series):
            for x, l in enumerate("ABCD"):
                vbar(ax, x + (k - 1) * (width + 0.03), v[l], width, c)
        ax.axhline(25, color=INK2, linewidth=1 * PT, zorder=2)
        ax.text(3.55, 25.8, "25%", fontsize=8, color=INK2, ha="right")
        ax.set_xticks(range(4), list("ABCD"))
        ax.set_title({"O1": "O1 - options as released", "O2": "O2 - options reversed"}[order],
                     fontsize=10, pad=6)
    ax = axes[2]                                         # Yes/No questions: the answer is a word
    ax.yaxis.grid(True, color=GRID, linewidth=1 * PT, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlim(-0.6, 1.6)
    for x, order in enumerate(("O1", "O2")):
        Y = D["yesno"][order]
        for k, (key, c) in enumerate((("gold", MUTED), ("bm", BLUE), ("nt", ORANGE))):
            vbar(ax, x + (k - 1) * (width + 0.03), Y[key], width, c)
    ax.axhline(50, color=INK2, linewidth=1 * PT, zorder=2)
    ax.text(0.5, 50.8, "50%", fontsize=8, color=INK2, ha="center")
    ax.set_xticks(range(2), ["O1", "O2"])
    ax.set_title(f"Yes/No ({D['yesno']['n']} q): share 'Yes'", fontsize=10, pad=6)
    axes[0].set_ylabel(f"share of answers on the {D['letters']['n']} lettered questions (%)")
    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c, label=l) for l, c in
                        (("gold answer key", MUTED), ("Qwen3.8 thinking", BLUE), ("Qwen3.8 no thinking", ORANGE))],
               loc="lower center", bbox_to_anchor=(0.5, -0.06), ncol=3)
    fig.suptitle("Answer habits vs. the answer key (no video)", x=0.07, y=1.02, ha="left",
                 fontsize=12, fontweight="bold")
    return save(fig, out, "fig_cvbench_8_answer_letters.png")


def fig_history(D, out):
    sec = [("WITH video - InternVL3-8B, Era 1 (Jun-Jul 2026), 1000 q x 4 passes", None)]
    sec += [(lab, ("arm", tag)) for tag, lab in ARMS]
    sec += [("NO video - Qwen3.8-27B, this run, 1000 q x 4 seeds x 2 orders", None),
            ("thinking (medium)", ("bm", None)), ("no thinking", ("nt", None)),
            ("Baselines", None),
            ("best answer-key guesser (in-sample, O1)", ("ref", D["key_insample"])),
            ("random guessing", ("ref", D["chance"]))]
    fig, ax = plt.subplots(figsize=(9.6, 6.2), dpi=DPI_LAYOUT)
    ax.set_xlim(0, 75)
    ax.set_ylim(len(sec) - 0.4, -0.6)
    ax.set_yticks(range(len(sec)), [lab for lab, _ in sec])
    for tl, (_, what) in zip(ax.get_yticklabels(), sec):
        if what is None:
            tl.set_fontweight("bold")
            tl.set_color(INK)
    xgrid(ax)
    h = bar_h(ax)
    for i, (lab, what) in enumerate(sec):
        if what is None:
            continue
        kind, key = what
        if kind == "arm":
            a = D["sighted"][key]
            hbar(ax, i, 0, a["acc"], h, AQUA)
            ax.errorbar(a["acc"], i, xerr=a["std"], color=INK2, capsize=0, elinewidth=1 * PT, zorder=4)
            v = a["acc"]
            ax.text(v + a["std"] + 1.4, i, f"{v:.1f}%", va="center", fontsize=8.5, color=INK)
            continue
        elif kind in ("bm", "nt"):
            v = D[kind]["acc"]
            hbar(ax, i, 0, v, h, BLUE if kind == "bm" else ORANGE)
        else:
            v = key
            hbar(ax, i, 0, v, h, MUTED)
        ax.text(v + 1.4, i, f"{v:.1f}%", va="center", fontsize=8.5, color=INK)
    ax.set_xlabel("accuracy on the same 1000 CVBench questions (%); whisker (with-video arms) = sd over 4 passes;"
                  "\nQwen rows = mean of both option orders")
    ax.set_title("Everything run on the full CVBench pool", pad=12)
    return save(fig, out, "fig_cvbench_9_history_full1000.png")


def fig_sweep(D, out):
    tags = ["fullstitch8", "fullstitch", "fullstitch32", "fullstitch64", "fullstitch128"]
    xs = [8, 16, 32, 64, 128]
    ys = [D["sighted"][t]["acc"] for t in tags]
    es = [D["sighted"][t]["std"] for t in tags]
    fig, ax = plt.subplots(figsize=(8.0, 4.0), dpi=DPI_LAYOUT)
    ax.set_xscale("log", base=2)
    ax.set_xticks(xs, [str(x) for x in xs])
    ax.set_xlim(6.5, 260)
    ax.set_ylim(20, 70)
    ax.yaxis.grid(True, color=GRID, linewidth=1 * PT, zorder=0)
    ax.set_axisbelow(True)
    refs = [(D["sighted"]["fulldur"]["acc"], f"sequential video, 64 frames (best arm)  "
             f"{D['sighted']['fulldur']['acc']:.1f}", AQUA),
            (D["bm"]["acc"], f"Qwen3.8-27B, no video: thinking {D['bm']['acc']:.1f} (blue) / "
             f"no thinking {D['nt']['acc']:.1f} (orange)", BLUE),
            (D["nt"]["acc"], None, ORANGE),
            (D["chance"], f"chance  {D['chance']:.1f}", INK2)]
    for y, lab, c in refs:
        ax.axhline(y, color=c, linewidth=1 * PT, zorder=2, alpha=0.9)
        if lab:
            left = c == BLUE                             # keep the 128-montage leader line clear of it
            ax.text(7 if left else 255, y + 0.6, lab, ha="left" if left else "right", va="bottom",
                    fontsize=8, color=INK2)
    for x, y in zip(xs, ys):
        dot(ax, x, y, AQUA)
    ax.errorbar(xs, ys, yerr=es, color=AQUA, ecolor=INK2, linewidth=2 * PT, elinewidth=1 * PT, capsize=3,
                zorder=6)
    lo, hi = D["stitch_input_tokens"]["fullstitch128"]
    ax.annotate(f"128 montages: {lo:,}-{hi:,} input tokens,\npast InternVL3-8B's 32,768\n"
                "max_position_embeddings", xy=(128, ys[-1]), xytext=(100, 34), fontsize=8, color=INK2,
                ha="center", arrowprops=dict(arrowstyle="-", color=INK2, linewidth=1 * PT))
    ax.set_xlabel("montages per question (grid stitch, up to 2x2; InternVL3-8B, Era 1); whisker = sd over 4 passes")
    ax.set_ylabel("accuracy (%)")
    ax.set_title("Stitch frame-budget sweep (Era 1, InternVL3-8B with video)", pad=12)
    return save(fig, out, "fig_cvbench_10_stitch_sweep.png")


def fig_tokens(D, out):
    toks = D["tokens"]["bm"]
    cut = 2500
    fig, ax = plt.subplots(figsize=(8.0, 3.6), dpi=DPI_LAYOUT)
    bins = list(range(0, cut + 1, 100))
    ax.hist([t for t in toks if t <= cut], bins=bins, color=BLUE, rwidth=0.88, zorder=3)
    ax.set_xlim(0, cut)
    ax.yaxis.grid(True, color=GRID, linewidth=1 * PT, zorder=0)
    ax.set_axisbelow(True)
    med = sorted(toks)[len(toks) // 2]
    ax.axvline(med, color=INK2, linewidth=1 * PT, zorder=4)
    tail = sum(1 for t in toks if t > cut)
    ax.text(0.98, 0.62, f"line = median {med:,}; mean {mean(toks):,.0f}; max {max(toks):,}\n"
            f"{tail} of {len(toks):,} answers above {cut:,} tokens (not drawn)\n"
            f"both option orders", transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color=INK2)
    ax.set_xlabel("output tokens per answer (thinking + reply), Qwen3.8-27B effort medium")
    ax.set_ylabel("answers")
    ax.set_title("Output length per answer, thinking leg (no video)", pad=12)
    return save(fig, out, "fig_cvbench_11_reasoning_length.png")


def fig_order_heat(D, out):
    M = D["order_matrix"]                                # M[k1][k2] counts, thinking leg
    fig, ax = plt.subplots(figsize=(5.4, 4.8), dpi=DPI_LAYOUT)
    vmax = max(max(r) for r in M)
    for i in range(5):
        for j in range(5):
            v = M[i][j]                                  # log ramp: the corners dwarf every other cell
            step = 0 if v == 0 else min(len(SEQ) - 1, 1 + round((len(SEQ) - 2) * math.log(v) / math.log(vmax)))
            ax.add_patch(plt.Rectangle((j - 0.47, i - 0.47), 0.94, 0.94, color=SEQ[step], zorder=2))
            ax.text(j, i, str(v), ha="center", va="center", fontsize=9,
                    color="#ffffff" if step >= 5 else INK, zorder=3)
    ax.set_xlim(-0.6, 4.6)
    ax.set_ylim(4.6, -0.6)
    ax.set_xticks(range(5), [str(k) for k in range(5)])
    ax.set_yticks(range(5), [str(k) for k in range(5)])
    ax.tick_params(length=0)
    for s in ("left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.set_xlabel("seeds right with options REVERSED (O2)")
    ax.set_ylabel("seeds right as RELEASED (O1)")
    ax.set_title("Same question, two option orders (thinking leg)", pad=26)
    ax.text(0, 1.015, "cell = number of questions; darker = more (log scale)", transform=ax.transAxes,
            color=INK2, fontsize=9, va="bottom")
    return save(fig, out, "fig_cvbench_12_order_consistency.png")


# ------------------------------------------------------------------ main ---

def assemble(bm, nt, results, archive):
    D = {}
    for key, j in (("bm", bm), ("nt", nt)):
        acc, accs = two_order_mean(j, lambda o: exact_acc(o["overall"]))
        bn = mean(100 * j[o]["overall"]["bias_null"]["null_mean_correct"] / j[o]["overall"]["n_rows"]
                  for o in ("O1", "O2"))
        D[key] = {"acc": acc, "acc_O1_O2": accs, "bias_null_acc": bn,
                  "both": j["both_orders"]["labels"], "rows": [j[o]["overall"]["n_rows"] for o in ("O1", "O2")]}
    bp = bm["both_orders"]["bias_null_paired"]
    D["both_null_paired"] = {"mean": bp["null_mean_text_answerable"], "lo": bp["null_95_text_answerable"][0],
                             "hi": bp["null_95_text_answerable"][1], "p": bp["p_text_answerable"]}

    # thinking minus no thinking per question: mean over 4 seeds x 2 orders, paired over questions
    def q_acc(j, q):
        k = sum(j[o]["questions"][q]["k"] for o in ("O1", "O2"))
        n = sum(j[o]["questions"][q]["n"] for o in ("O1", "O2"))
        return k / n if n else None
    diffs = defaultdict(list)
    for q, m in bm["O1"]["questions"].items():
        a, b = q_acc(bm, q), q_acc(nt, q)
        if a is not None and b is not None:
            diffs[m["task"]].append(100 * (a - b))
    se = lambda xs: stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0
    all_d = [x for xs in diffs.values() for x in xs]
    D["delta_all"], D["delta_all_se"] = mean(all_d), se(all_d)
    o1 = bm["O1"]["overall"]
    D["chance"] = o1["chance"]
    D["key_insample"] = o1["key_floor_insample"]
    D["key_loo"] = o1["key_floor_loo"]
    D["longest"] = o1["longest_option"]["acc"]

    sighted = {}
    sq = {}
    D["stitch_input_tokens"] = {}
    for tag, _ in ARMS:
        rows = rows_of(os.path.join(archive, f"bench_cvbench_full_runnable_subset_internvl_{tag}_shard*.jsonl"))
        a, s = per_pass(rows)
        sighted[tag] = {"acc": a, "std": s, "rows": len(rows)}
        if "stitch" in tag:
            toks = [r["input_tokens"] for r in rows if r.get("input_tokens")]
            D["stitch_input_tokens"][tag] = [min(toks), max(toks)] if toks else [0, 0]
        if tag == "fulldur":
            sq = per_question(rows)
            task_rows = defaultdict(list)
            for r in rows:
                task_rows[r["task_type"]].append(r)
    D["sighted"] = sighted

    D["tasks"] = {}
    for t in bm["O1"]["per_task"]:
        bt = bm["both_orders"]["per_task"][t]
        d = {"n": bm["O1"]["per_task"][t]["n_questions"],
             "bm": mean(exact_acc(bm[o]["per_task"][t]) for o in ("O1", "O2")),
             "nt": mean(exact_acc(nt[o]["per_task"][t]) for o in ("O1", "O2")),
             "delta": mean(diffs[t]), "delta_se": se(diffs[t]),
             "chance": bm["O1"]["per_task"][t]["chance"],
             "key_insample": bm["O1"]["per_task"][t]["key_floor_insample"],
             "sighted": per_pass(task_rows[t])[0],
             "both_split": (bt["both"], bt["one"], bt["neither"], bt["n"]),
             "both_share": bt["both"] / bt["n"],
             "chance_both": bt["expected_both_at_chance"],
             "null_mean_both": bt["null_mean_both"], "null_95_both": bt["null_95_both"],
             "p_both": bt["p_both"],
             "null_mean_both_paired": bt["null_mean_both_paired"],
             "null_95_both_paired": bt["null_95_both_paired"], "p_both_paired": bt["p_both_paired"]}
        D["tasks"][t] = d
    lab = bm["both_orders"]["labels"]
    n_all = sum(lab.values())
    D["both_overall"] = (lab.get("text-answerable in both orders", 0),
                         lab.get("text-answerable in one order", 0),
                         lab.get("not in either order", 0), n_all)

    D["hist"] = {}
    for key, j in (("bm", bm), ("nt", nt)):
        h = Counter(q["k"] for q in j["O1"]["questions"].values() if q["n"] == 4)
        D["hist"][key] = [h.get(k, 0) for k in range(5)]
    h = Counter(sum(v) for v in sq.values() if len(v) == 4)
    D["hist"]["sighted"] = [h.get(k, 0) for k in range(5)]

    lab1, lab2 = bm["O1"]["questions"], bm["O2"]["questions"]
    groups = {"both": [], "one": [], "neither": []}
    for q in lab1:
        if q not in lab2 or q not in sq:
            continue
        a, b = lab1[q]["label"] == "text-answerable", lab2[q]["label"] == "text-answerable"
        groups["both" if a and b else "one" if a or b else "neither"].append(q)
    D["sighted_by_label"] = {g: {"n": len(qs), "acc": 100 * mean(mean(sq[q]) for q in qs) if qs else 0.0,
                                 "video_ge3_of_4": sum(1 for q in qs if sum(sq[q]) >= 3)}
                             for g, qs in groups.items()}

    D["letters"] = {}
    for order, stem in (("O1", "bench_cvbench_full_runnable_subset"), ("O2", "bench_cvbench_full_runnable_subset_o2")):
        L = {}
        for key, tag in (("bm", "q38bm"), ("nt", "q38nt")):
            rows = rows_of(os.path.join(results, f"{stem}_cvbench_{tag}_shard*.jsonl"))
            c = Counter(r["prediction"] for r in rows if r.get("gold") in tuple("ABCD") and not r.get("error"))
            tot = sum(c[l] for l in "ABCD") or 1
            L[key] = {l: 100 * c[l] / tot for l in "ABCD"}
            if key == "bm":
                g = Counter(r["gold"] for r in rows if r.get("pass_idx") == 1 and r.get("gold") in tuple("ABCD"))
                gt = sum(g.values()) or 1
                L["gold"] = {l: 100 * g[l] / gt for l in "ABCD"}
                D["letters"]["n"] = gt
        D["letters"][order] = L

    D["yesno"] = {}                                      # Yes/No answers are words: the same in both orders
    for order in ("O1", "O2"):
        qs = {q: m for q, m in bm[order]["questions"].items() if m["fmt"] == "YN"}
        share = lambda j: 100 * mean(p == "Yes" for q in qs for p in j[order]["questions"][q]["preds"])
        D["yesno"][order] = {"gold": 100 * mean(m["gold"] == "Yes" for m in qs.values()),
                             "bm": share(bm), "nt": share(nt)}
        D["yesno"]["n"] = len(qs)

    rows = rows_of(os.path.join(results, "bench_cvbench_full_runnable_subset*_cvbench_q38bm_shard*.jsonl"))
    D["tokens"] = {"bm": [r["output_tokens"] for r in rows if not r.get("error") and r.get("output_tokens")]}

    M = [[0] * 5 for _ in range(5)]
    for q in lab1:
        if q in lab2 and lab1[q]["n"] == 4 and lab2[q]["n"] == 4:
            M[lab1[q]["k"]][lab2[q]["k"]] += 1
    D["order_matrix"] = M
    return D


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bm", default=os.path.join(HERE, "records", "cvbench_text_answerability_q38bm.json"))
    ap.add_argument("--nt", default=os.path.join(HERE, "records", "cvbench_text_answerability_q38nt.json"))
    ap.add_argument("--results", default=os.path.join(REPO, "bench", "results"))
    ap.add_argument("--archive", required=True, help="Era-1 bench/results extracted from the archive tgz")
    ap.add_argument("--out", default=os.path.join(HERE, "figs_deck"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    bm, nt = json.load(open(args.bm)), json.load(open(args.nt))
    for name, j in (("--bm", bm), ("--nt", nt)):
        if "O2" not in j or "both_orders" not in j:
            raise SystemExit(f"{name} was written without --blind-o2; both option orders are needed")
    D = assemble(bm, nt, args.results, args.archive)
    paths = [f(D, args.out) for f in (fig_overall, fig_per_task, fig_answerable, fig_vs_null, fig_hist,
                                      fig_sighted_by_label, fig_delta, fig_letters, fig_history, fig_sweep,
                                      fig_tokens, fig_order_heat)]
    D_out = dict(D)
    D_out["tokens"] = {"bm_n": len(D["tokens"]["bm"]), "bm_mean": mean(D["tokens"]["bm"]) if D["tokens"]["bm"] else None,
                       "bm_median": sorted(D["tokens"]["bm"])[len(D["tokens"]["bm"]) // 2] if D["tokens"]["bm"] else None,
                       "bm_max": max(D["tokens"]["bm"]) if D["tokens"]["bm"] else None}
    json.dump(D_out, open(os.path.join(args.out, "fig_cvbench_data.json"), "w"), indent=1)
    for p in paths:
        print("wrote", p)
    print("wrote", os.path.join(args.out, "fig_cvbench_data.json"))


if __name__ == "__main__":
    main()
