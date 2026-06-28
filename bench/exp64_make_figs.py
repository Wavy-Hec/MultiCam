"""Render the figures for the 64-frame native-vs-stitching report (exp64).

Reads the per-question results (`bench/results/exp64_internvl.jsonl`) + its summary
and writes three PNGs into `bench/results/figs_exp64/`:

  exp64_accuracy.png   overall + per-task-type accuracy (the two conditions)
  exp64_cameras.png    accuracy vs original camera count (line)
  exp64_budget.png     the equal-frame / NOT-equal-token budget (grouped bars)

Run from the repo root:  python -m bench.exp64_make_figs
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
FIGS = os.path.join(RES, "figs_exp64")
os.makedirs(FIGS, exist_ok=True)

SUMMARY = json.load(open(os.path.join(RES, "exp64_internvl_summary.json")))
ROWS = [json.loads(l) for l in open(os.path.join(RES, "exp64_internvl.jsonl")) if l.strip()]

NATIVE = "cvbench_native/InternVL3-8B"
STITCH = "centralized/InternVL3-8B"
C_NATIVE, C_STITCH = "#7f7f7f", "#1f77b4"
L_NATIVE = "1. CVBench-native (sequential clips)"
L_STITCH = "2. Our stitching (grid montage)"
TASK_SHORT = {"CrossView-MEVA-Event-Ordering": "Event-Ordering",
              "CrossView-MEVA-Spatial": "Spatial", "CrossView-MEVA-Temporal": "Temporal"}


def pct(x):
    return None if x is None else 100.0 * x


# --- Figure 1: overall + per-task accuracy -----------------------------------
def fig_accuracy():
    tasks = ["CrossView-MEVA-Event-Ordering", "CrossView-MEVA-Spatial",
             "CrossView-MEVA-Temporal"]
    groups = ["Overall"] + [TASK_SHORT[t] for t in tasks]
    nat = [pct(SUMMARY[NATIVE]["overall"]["acc"])] + \
          [pct(SUMMARY[NATIVE]["by_task_type"][t]["acc"]) for t in tasks]
    sti = [pct(SUMMARY[STITCH]["overall"]["acc"])] + \
          [pct(SUMMARY[STITCH]["by_task_type"][t]["acc"]) for t in tasks]
    x = range(len(groups))
    w = 0.38
    fig, ax = plt.subplots(figsize=(9, 5.2))
    b1 = ax.bar([i - w / 2 for i in x], nat, w, label=L_NATIVE, color=C_NATIVE)
    b2 = ax.bar([i + w / 2 for i in x], sti, w, label=L_STITCH, color=C_STITCH)
    ax.axhline(25, ls="--", color="red", alpha=0.6)
    ax.text(len(groups) - 1.4, 26, "chance 25%", color="red", fontsize=9)
    for bars in (b1, b2):
        for r in bars:
            ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 0.6,
                    f"{r.get_height():.0f}%", ha="center", fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(groups)
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 70)
    ax.set_title("InternVL3-8B · equal 64-frame budget · 150 four-camera MEVA questions\n"
                 "CVBench-native vs. our spatial stitching")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "exp64_accuracy.png"), dpi=150)
    plt.close(fig)


# --- Figure 2: accuracy vs camera count --------------------------------------
def fig_cameras():
    def series(key):
        d = SUMMARY[key]["by_orig_num_cameras"]
        cams = sorted(int(c) for c in d)
        return cams, [pct(d[str(c)]["acc"]) for c in cams]
    cn, yn = series(NATIVE)
    cs, ys = series(STITCH)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(cn, yn, marker="o", color=C_NATIVE, label=L_NATIVE)
    ax.plot(cs, ys, marker="o", color=C_STITCH, label=L_STITCH)
    ax.axhline(25, ls="--", color="red", alpha=0.5)
    ax.set_xlabel("Original scene camera count (orig_num_cameras)")
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("Plot 3 — Accuracy vs camera count (input capped at 4 streams)")
    ax.set_xticks(sorted(set(cn) | set(cs)))
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "exp64_cameras.png"), dpi=150)
    plt.close(fig)


# --- Figure 3: the budget (equal frames, NOT equal tokens) -------------------
def fig_budget():
    frames = {NATIVE: 64, STITCH: 64}
    vtok = {}
    for r in ROWS:
        k = f'{r["method"]}/{r["backend"]}'
        vtok.setdefault(k, r.get("video_tokens"))
    lat = {NATIVE: SUMMARY[NATIVE]["latency_s"]["mean"],
           STITCH: SUMMARY[STITCH]["latency_s"]["mean"]}
    metrics = [
        ("Camera frames\n(visual budget)", frames[NATIVE], frames[STITCH], ""),
        ("Video tokens\n(InternVL)", vtok[NATIVE], vtok[STITCH], ""),
        ("Mean latency (s)", lat[NATIVE], lat[STITCH], "s"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.4))
    for ax, (title, nv, sv, unit) in zip(axes, metrics):
        bars = ax.bar([0, 1], [nv, sv], color=[C_NATIVE, C_STITCH], width=0.6)
        for r, v in zip(bars, [nv, sv]):
            txt = f"{v:.0f}{unit}" if title.startswith("Mean") else f"{v:,.0f}"
            ax.text(r.get_x() + r.get_width() / 2, r.get_height(), txt,
                    ha="center", va="bottom", fontsize=10)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["native", "stitch"])
        ax.set_title(title, fontsize=11)
        ax.margins(y=0.18)
        ax.grid(axis="y", alpha=0.3)
    fig.suptitle("Budget parity: frames are EQUAL (64=64); tokens are NOT "
                 "(stitch +25% from InternVL's per-montage thumbnail tile)", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(FIGS, "exp64_budget.png"), dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    fig_accuracy()
    fig_cameras()
    fig_budget()
    print("wrote exp64_accuracy.png, exp64_cameras.png, exp64_budget.png ->", FIGS)
