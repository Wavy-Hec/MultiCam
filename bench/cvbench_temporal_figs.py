"""Comparison figures for the CVBench duration-weighted temporal run.

Reads a results JSONL (one or more arms in it) and renders grouped-bar charts of
accuracy (mean +/- std over the 4 passes) for the three equal-budget arms:
  temporal_weighted (duration) | temporal_even (control) | centralized (2x2 stitch)

  Fig 1: accuracy by method (overall)
  Fig 2: accuracy by #clips (2/3/4) x method  <- the key stratified view
  Fig 3: accuracy by task_type x method (top task types by support)

Run from repo root:
  python bench/cvbench_temporal_figs.py --jsonl bench/results/bench_cvbench_temporal_internvl_ALL.jsonl
"""
import argparse
import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bench import metrics  # noqa: E402

# label in the JSONL -> (display name, bar color), in the order we want them plotted
METHOD_ORDER = [
    ("temporal_weighted", "Duration-weighted", "#2c7fb8"),
    ("temporal_even", "Even split (control)", "#7fcdbb"),
    ("centralized", "2x2 spatial stitch", "#f03b20"),
]


def load_rows(paths):
    rows = []
    for p in paths:
        for g in glob.glob(p):
            with open(g) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            pass
    return rows


def _present(rows):
    """[(label, name, color, summary_passes_dict), ...] for arms actually in the data."""
    out = []
    for label, name, color in METHOD_ORDER:
        mrows = [r for r in rows if r.get("method") == label]
        if mrows:
            out.append((label, name, color, metrics.summarize_passes(mrows), len(mrows)))
    return out


def _bar(ax, x, mean, std, color, width, label):
    ax.bar(x, [m if m is not None else 0 for m in mean], width,
           yerr=[s if s is not None else 0 for s in std], capsize=3,
           color=color, label=label, edgecolor="black", linewidth=0.4)


def fig_overall(arms, out):
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for i, (label, name, color, s, n) in enumerate(arms):
        mp = s["overall_passes"]
        m = (mp["mean"] or 0) * 100
        sd = (mp["std"] or 0) * 100
        ax.bar(i, m, 0.62, yerr=sd, capsize=4, color=color, edgecolor="black", linewidth=0.5)
        ax.text(i, m + (sd or 0) + 1.0, f"{m:.1f}%", ha="center", va="bottom", fontsize=10)
    ax.set_xticks(range(len(arms)))
    ax.set_xticklabels([f"{name}\n(n={n//max(1,arms[0][3]['overall_passes']['n_passes'] or 1)})"
                        for (_, name, _, s, n) in arms], fontsize=9)
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("CVBench temporal — accuracy by presentation (64-frame budget, InternVL3, 4-pass)")
    ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def fig_by_cams(arms, out):
    cams = ["2", "3", "4"]
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    width = 0.8 / max(1, len(arms))
    for j, (label, name, color, s, n) in enumerate(arms):
        bc = s["by_orig_num_cameras_passes"]
        mean = [(bc.get(c, {}).get("mean") or 0) * 100 for c in cams]
        std = [(bc.get(c, {}).get("std") or 0) * 100 for c in cams]
        xs = [i + (j - (len(arms) - 1) / 2) * width for i in range(len(cams))]
        _bar(ax, xs, mean, std, color, width, name)
    ax.set_xticks(range(len(cams)))
    ax.set_xticklabels([f"{c} clips" for c in cams])
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("CVBench temporal — accuracy by #clips x presentation (64-frame budget)")
    ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def fig_by_task(arms, out, top=8):
    # rank task types by support in the first arm
    base = arms[0][3]["by_task_type_passes"]
    counts = {tt: (v.get("n_passes") or 0) for tt, v in base.items()}
    # use the overall by_task_type totals for ranking instead (support)
    tts = sorted(base.keys(), key=lambda t: -(arms[0][3]["by_task_type"].get(t, {}).get("total", 0)))[:top]
    fig, ax = plt.subplots(figsize=(max(8, len(tts) * 1.3), 4.8))
    width = 0.8 / max(1, len(arms))
    for j, (label, name, color, s, n) in enumerate(arms):
        bt = s["by_task_type_passes"]
        mean = [(bt.get(t, {}).get("mean") or 0) * 100 for t in tts]
        std = [(bt.get(t, {}).get("std") or 0) * 100 for t in tts]
        xs = [i + (j - (len(arms) - 1) / 2) * width for i in range(len(tts))]
        _bar(ax, xs, mean, std, color, width, name)
    ax.set_xticks(range(len(tts)))
    ax.set_xticklabels([t.replace(" ", "\n") for t in tts], fontsize=7)
    ax.set_ylabel("Accuracy (%)")
    ax.set_title(f"CVBench temporal — accuracy by task type x presentation (top {len(tts)})")
    ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", nargs="+", required=True,
                    help="results JSONL path(s); globs allowed (e.g. bench/results/..._shard*.jsonl)")
    ap.add_argument("--out-dir", default="bench/results/figs_temporal")
    args = ap.parse_args()

    rows = load_rows(args.jsonl)
    arms = _present(rows)
    if not arms:
        raise SystemExit(f"no known arms (temporal_weighted/temporal_even/centralized) in {args.jsonl}")
    os.makedirs(args.out_dir, exist_ok=True)
    print(f"loaded {len(rows)} rows; arms present:")
    for label, name, _, s, n in arms:
        mp = s["overall_passes"]
        print(f"  {label:18s} n={n:4d}  acc={ (mp['mean'] or 0)*100:.1f}% +/- {(mp['std'] or 0)*100:.1f}  passes={mp['n_passes']}")
    outs = [
        fig_overall(arms, os.path.join(args.out_dir, "acc_by_method.png")),
        fig_by_cams(arms, os.path.join(args.out_dir, "acc_by_numclips.png")),
        fig_by_task(arms, os.path.join(args.out_dir, "acc_by_task.png")),
    ]
    print("wrote:", *outs, sep="\n  ")


if __name__ == "__main__":
    main()
