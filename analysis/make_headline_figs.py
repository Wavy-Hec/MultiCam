"""Two slide-headline figures assembled from already-dumped series JSONs.

  fig_table1_overview.png     Table 1 as a chart: accuracy by pool x harness x
                              backend with 4-pass std error bars and each pool's
                              task-conditioned floor drawn over its group.
  fig_counting_signed_err.png Item 5a as a chart: mean signed count error
                              (prediction - gold) per arm at temp 0.1, diverging
                              around zero — right of zero = over-counting (the
                              dedup direction), left = under-counting (perception).

Reads figs_task1_<pool>/table1.json and analysis/counting_failures.json only —
never the raw shards. Same visual language as restyle_task1_figs.py.

    python3 analysis/make_headline_figs.py
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from restyle_task1_figs import (  # noqa: E402
    HUES, HARNESS_ORDER, INK, INK2, GRID, SURFACE, DPI, split_method, style_axis,
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RES = os.path.join(REPO, "bench", "results")
OUT = os.path.join(RES, "figs_task1_overview")

POOLS = [
    ("crossview_meva_cap13", "CrossView-MEVA", 54.7),
    ("crossview_egoexo500", "CrossView-EgoExo", None),
    ("allangles_qa", "All-Angles", 30.4),
    ("mvueval_qa", "MVU-Eval", 26.0),
]


def fig_table1_overview():
    fig, ax = plt.subplots(figsize=(12.6, 5.8))
    group_w, bw = 0.78, 0.78 / 6
    for i, (pool, title, floor) in enumerate(POOLS):
        rows = json.load(open(os.path.join(RES, f"figs_task1_{pool}", "table1.json")))["rows"]
        rows.sort(key=lambda r: (
            HARNESS_ORDER.index(split_method(r["method"])[1]),
            0 if split_method(r["method"])[0] == "InternVL3" else 1))
        for j, r in enumerate(rows):
            b, h = split_method(r["method"])
            x = i - group_w / 2 + j * bw + bw / 2
            kw = dict(color=HUES[h], width=bw - 0.012, zorder=3)
            if b == "Qwen2.5":
                kw.update(alpha=0.42, edgecolor=HUES[h], linewidth=1.2)
            ax.bar(x, r["acc_mean_pct"], yerr=r["acc_std_pct"],
                   error_kw=dict(ecolor=INK2, elinewidth=1.0, capsize=0, zorder=4), **kw)
        if floor:
            ax.plot([i - group_w / 2 - 0.03, i + group_w / 2 + 0.03], [floor, floor],
                    color=INK, linewidth=1.6, linestyle=(0, (5, 3)), zorder=5)
            ax.annotate(f"floor {floor:g}", (i - group_w / 2 - 0.02, floor),
                        xytext=(0, 5), textcoords="offset points", ha="left",
                        va="bottom", fontsize=10, color=INK, zorder=6,
                        bbox=dict(boxstyle="square,pad=0.15", facecolor=SURFACE,
                                  edgecolor="none"))
    ax.set_xticks(range(len(POOLS)))
    ax.set_xticklabels([t for _, t, _ in POOLS], fontsize=12.5)
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 68)
    style_axis(ax)
    handles = [Patch(facecolor=HUES[h], label=h) for h in HARNESS_ORDER]
    handles += [Patch(facecolor=INK2, label="InternVL3-8B (solid)"),
                Patch(facecolor=INK2, alpha=0.4, edgecolor=INK2, linewidth=1.2,
                      label="Qwen2.5-VL-7B (tinted)"),
                Line2D([], [], color=INK, linewidth=1.6, linestyle=(0, (5, 3)),
                       label="modal-letter floor (leave-one-out)")]
    ax.legend(handles=handles, ncol=3, frameon=False, loc="upper left",
              bbox_to_anchor=(0, 1.02), columnspacing=1.3, handlelength=1.5)
    fig.suptitle("Overall accuracy — 4 pools × 3 harnesses × 2 backends",
                 x=0.06, y=0.975, ha="left", fontsize=15.5, fontweight="bold", color=INK)
    fig.text(0.06, 0.905, "8 frames/view · reasoning off · temp 0.1 · 4 passes · error bars = ±std",
             ha="left", fontsize=11.5, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.85))
    out = os.path.join(OUT, "fig_table1_overview.png")
    fig.savefig(out, dpi=DPI)
    plt.close(fig)
    print("wrote", out)


def fig_counting_signed_err():
    arms = json.load(open(os.path.join(HERE, "counting_failures.json")))["arms"]
    rows = []
    for be in ["InternVL3-8B", "Qwen2.5-VL-7B-Instruct"]:
        for m, h in [("centralized", "Centralized"), ("cvbench_native", "Sequential"),
                     ("per_stream", "Decentralized")]:
            a = arms.get(f"{be}/{m}/temp=0.1")
            if a:
                rows.append((be, h, a["mean_signed_err"], a["n_questions"]))
    rows.sort(key=lambda r: (HARNESS_ORDER.index(r[1]), 0 if "Intern" in r[0] else 1))
    fig, ax = plt.subplots(figsize=(11.5, 4.6))
    y, ticks, labels = 0, [], []
    for i, (be, h, err, nq) in enumerate(rows):
        if i and i % 2 == 0:
            y -= 0.55
        b = "InternVL3" if "Intern" in be else "Qwen2.5"
        kw = dict(color=HUES[h], height=0.62, zorder=3)
        if b == "Qwen2.5":
            kw.update(alpha=0.42, edgecolor=HUES[h], linewidth=1.2)
        ax.barh(y, err, **kw)
        ax.annotate(f"{err:+.2f}", (err, y), xytext=(8 if err >= 0 else -8, 0),
                    textcoords="offset points", va="center",
                    ha="left" if err >= 0 else "right", fontsize=11, color=INK)
        ticks.append(y)
        labels.append(f"{h} — {b}")
        y -= 1
    ax.axvline(0, color=INK, linewidth=1.2, zorder=4)
    ax.axvline(0.46, color=INK2, linewidth=1.4, linestyle=(0, (5, 3)), zorder=2)
    ax.text(0.445, (min(ticks) + max(ticks)) / 2, "blind prior +0.46 (temp-0.7 pilot)",
            ha="right", va="center", fontsize=10.5, color=INK2, rotation=90)
    ax.set_ylim(min(ticks) - 0.8, max(ticks) + 0.9)
    ax.set_yticks(ticks)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Mean signed count error (prediction − gold) — ← under-counts (perception) · over-counts (dedup direction) →")
    ax.set_xlim(-0.55, 0.62)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(left=False)
    fig.suptitle("Counting: every arm under-counts except decentralized InternVL3",
                 x=0.06, y=0.975, ha="left", fontsize=15.5, fontweight="bold", color=INK)
    fig.text(0.06, 0.885, "All-Angles numeric counting, 251 questions · reasoning off · temp 0.1 · 4 passes",
             ha="left", fontsize=11.5, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    out = os.path.join(OUT, "fig_counting_signed_err.png")
    fig.savefig(out, dpi=DPI)
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fig_table1_overview()
    fig_counting_signed_err()
