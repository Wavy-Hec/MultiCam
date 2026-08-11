"""Accuracy vs frame budget, small multiples across the three datasets.

Nothing in the repo plotted across datasets on a frame axis: bench/plots.py
groups rows by (method, backend) with no dataset dimension, and its
intersect_cells keys on (id, pass_idx) where `id` is a bare integer that is NOT
namespaced by dataset -- MVU-Eval and CrossView both start at id=0, so pooling
their rows silently collides cells. Hence a separate script.

All-Angles cannot sit on the frame axis: it is 100% still images and
--total-frames is inert on stills in all three arms (cvbench_native.py:31-37,
centralized.py:88-89, per_stream.py:72-74). Its panel states the cell_px /
max_tiles budget that actually governs its visual input instead of faking a
frame curve.

Reads the *_rescored.jsonl written by analysis/rescore_answers.py, falling back
to the raw files with a warning -- the raw ones under-report InternVL3 by up to
8 points because of the old answer-parser gate.

    python3 analysis/make_frame_sweep_fig.py
    python3 analysis/make_frame_sweep_fig.py --out analysis/figs_deck/fig_frame_sweep.png
"""
import argparse
import collections
import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from bench import metrics  # noqa: E402
from clip_scorer_gate import modal_letter_floor  # noqa: E402

RES = os.path.join(REPO, "bench", "results")
BUDGETS = [32, 64, 96]
METHOD, BACKEND_SUB = "cvbench_native", "InternVL3"

# The frame axis carries the two video pools; All-Angles gets a budget panel.
FRAME_PANELS = [
    {"title": "MVU-Eval", "dataset": "mvueval_qa", "subset": "mvueval_qa.json",
     "tag": "internvl_fs{b}"},
    {"title": "CrossView-MEVA", "dataset": "crossview_meva_cap13",
     "subset": "crossview_meva_cap13.json", "tag": "internvl_fs{b}"},
]
STILL_PANEL = {"title": "All-Angles-Bench", "dataset": "allangles_qa",
               "subset": "allangles_qa.json", "tag": "internvl_t1iv"}

# dataviz: emphasis form -- one series in the accent hue, reference rule in the
# de-emphasis gray. Slot 1 of the validated categorical palette; contrast on the
# light surface 4.30:1, on the dark surface 4.79:1 (both >= 3:1).
SERIES = "#2a78d6"
INK, INK2, RULE, GRID = "#0b0b0b", "#52514e", "#8a8985", "#e6e5e2"
SURFACE = "#fcfcfb"


def load_leg(dataset, tag):
    """Concatenated rows for one leg, preferring the rescored copy of a shard.

    Shards are strided (data[offset::chunk]) so they are disjoint by question;
    a per-shard _summary.json covers only its own quarter and must never be read
    as the leg's accuracy. Concatenate first, aggregate second.

    Merged per SHARD, not per leg: preferring rescored/ wholesale would drop
    any raw shard that landed after the last rescore pass, and the resulting
    partial-pool point renders identically to a complete one (a missing shard
    removes the same questions from all passes, so the balance check passes).
    """
    base = f"bench_{dataset}_{tag}_shard*.jsonl"
    raw = {os.path.basename(p): p for p in glob.glob(os.path.join(RES, base))}
    resc = {os.path.basename(p): p
            for p in glob.glob(os.path.join(RES, "rescored", base))}
    files = [resc.get(n) or raw[n] for n in sorted(set(raw) | set(resc))]
    rescored = bool(resc) and set(raw) <= set(resc)
    rows = []
    for p in files:
        with open(p) as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    rows = [r for r in rows
            if r.get("method") == METHOD and BACKEND_SUB in str(r.get("backend"))]
    return rows, rescored, len(files)


def point(rows):
    """(mean, std, n_passes, balanced) for one budget point.

    metrics averages passes UNWEIGHTED, so a leg whose passes cover different
    question sets is silently mis-averaged. Report balance rather than hide it.
    """
    if not rows:
        return None
    summ = metrics.summarize_passes(rows)
    ov = summ.get("overall_passes") or {}
    by_pass = collections.Counter(r.get("pass_idx") for r in rows)
    balanced = len(by_pass) == 4 and len(set(by_pass.values())) == 1
    return (100.0 * ov.get("mean", 0.0), 100.0 * (ov.get("std") or 0.0),
            ov.get("n_passes", 0), balanced, len({r["id"] for r in rows}))


def floor_pct(subset):
    """Task-conditioned leave-one-out modal-letter floor for a pool, in %."""
    path = os.path.join(HERE, subset)
    if not os.path.exists(path):
        return None
    recs = json.load(open(path))
    hits = modal_letter_floor(recs)
    return 100.0 * sum(hits.values()) / len(hits) if hits else None


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "figs_deck",
                                                  "fig_frame_sweep.png"))
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    series, notes = {}, []
    for p in FRAME_PANELS:
        pts = {}
        for b in BUDGETS:
            rows, rescored, nf = load_leg(p["dataset"], p["tag"].format(b=b))
            got = point(rows)
            if got is None:
                notes.append(f"{p['title']} @ {b} frames: NO DATA (leg not finished)")
                continue
            mean, std, npass, balanced, nq = got
            if not balanced:
                notes.append(f"{p['title']} @ {b}: passes unbalanced "
                             f"({npass} passes, {nq} questions) - point flagged")
            if not rescored:
                notes.append(f"{p['title']} @ {b}: RAW rows (run rescore_answers.py)")
            pts[b] = (mean, std, balanced, nq)
        series[p["title"]] = pts

    rows, still_rescored, _ = load_leg(STILL_PANEL["dataset"], STILL_PANEL["tag"])
    still = point(rows)
    if still and not still[3]:
        notes.append(f"{STILL_PANEL['title']}: passes unbalanced "
                     f"({still[2]} passes, {still[4]} questions) - tile flagged")
    if rows and not still_rescored:
        notes.append(f"{STILL_PANEL['title']}: RAW rows (run rescore_answers.py)")
    cell_px = max_tiles = None
    for r in rows:
        fa = r.get("frame_alloc") or {}
        cell_px = fa.get("cell_px", cell_px)
        max_tiles = fa.get("max_tiles", max_tiles)

    fig, axes = plt.subplots(1, 3, figsize=(12.6, 4.0), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    floors = []

    for ax, p in zip(axes[:2], FRAME_PANELS):
        style(ax)
        pts = series[p["title"]]
        xs = [b for b in BUDGETS if b in pts]
        if xs:
            ys = [pts[b][0] for b in xs]
            es = [pts[b][1] for b in xs]
            ax.errorbar(xs, ys, yerr=es, color=SERIES, linewidth=2,
                        marker="o", markersize=8, markeredgecolor=SURFACE,
                        markeredgewidth=2, capsize=3, ecolor=SERIES, elinewidth=1.2,
                        zorder=3)
            # direct labels, not a number on every point: ends only
            for b in (xs[0], xs[-1]):
                ax.annotate(f"{pts[b][0]:.1f}%", (b, pts[b][0]),
                            textcoords="offset points", xytext=(0, 12),
                            ha="center", fontsize=9, color=INK, fontweight="bold")
            for b in xs:
                if not pts[b][2]:
                    ax.annotate("unbalanced", (b, pts[b][0]),
                                textcoords="offset points", xytext=(0, -16),
                                ha="center", fontsize=7, color="#e34948")
        else:
            ax.text(0.5, 0.5, "leg not finished", transform=ax.transAxes,
                    ha="center", va="center", color=INK2, fontsize=11)
        fl = floor_pct(p["subset"])
        if fl:
            ax.axhline(fl, color=RULE, linewidth=1.4, linestyle=(0, (5, 4)), zorder=2)
            # left-anchored: the right end carries the series' own value label
            ax.annotate(f"modal-letter floor {fl:.1f}%", (BUDGETS[0], fl),
                        textcoords="offset points", xytext=(2, 5), ha="left",
                        fontsize=8, color=INK2)
        floors.append(fl)
        ax.set_xticks(BUDGETS)
        ax.set_xlabel("total frames per question", fontsize=9, color=INK2)
        ax.set_title(p["title"], fontsize=11, color=INK, loc="left", pad=10)

    # All-Angles: a budget statement, not a fake curve. A single value is a stat
    # tile, not a one-point line.
    ax = axes[2]
    style(ax)
    ax.set_xticks([])
    for s in ("left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.grid(False)
    ax.set_title(STILL_PANEL["title"], fontsize=11, color=INK, loc="left", pad=10)
    if still:
        ax.text(0.5, 0.60, f"{still[0]:.1f}%", transform=ax.transAxes, ha="center",
                fontsize=34, color=SERIES, fontweight="bold")
        ax.text(0.5, 0.50, f"±{still[1]:.1f} over {still[2]} passes",
                transform=ax.transAxes, ha="center", fontsize=9, color=INK2)
        # same flag the frame panels stamp on their points; the tile must not
        # render a mid-drain unbalanced average as if it were final
        if not still[3]:
            ax.text(0.5, 0.42, "unbalanced passes", transform=ax.transAxes,
                    ha="center", fontsize=8, color="#e34948")
    else:
        ax.text(0.5, 0.58, "leg not finished", transform=ax.transAxes,
                ha="center", fontsize=11, color=INK2)
    budget_txt = "still images — frame budget does not apply"
    if cell_px:
        budget_txt += f"\nvisual budget: cell_px={cell_px}"
        if max_tiles:
            budget_txt += f", max_tiles={max_tiles}"
    ax.text(0.5, 0.30, budget_txt, transform=ax.transAxes, ha="center",
            fontsize=8.5, color=INK2, linespacing=1.5)
    fl = floor_pct(STILL_PANEL["subset"])
    if fl:
        ax.text(0.5, 0.16, f"modal-letter floor {fl:.1f}%", transform=ax.transAxes,
                ha="center", fontsize=8, color=INK2)

    # headroom so the floor rule and the end-point labels never touch the spine
    vals = [v[0] for p in series.values() for v in p.values()]
    vals += [f for f in floors if f] + ([still[0]] if still else [])
    if vals:
        lo, hi = min(vals), max(vals)
        pad = max(4.0, 0.18 * (hi - lo))
        axes[0].set_ylim(lo - pad, hi + pad)
    axes[0].set_ylabel("accuracy (%)", fontsize=9, color=INK2)
    fig.suptitle(f"Accuracy vs frame budget — {METHOD} / InternVL3, "
                 "reasoning off, temp 0.1, 4 passes",
                 fontsize=12.5, color=INK, x=0.012, ha="left", y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(args.out, dpi=200, facecolor=SURFACE)
    print(f"wrote {args.out}")

    # persist the exact series beside the PNG (bench/plots.py:46-54 convention),
    # so restyling never needs the results re-read
    side = args.out.replace(".png", ".json")
    with open(side, "w") as f:
        json.dump({"method": METHOD, "backend": BACKEND_SUB, "budgets": BUDGETS,
                   "frame_panels": {k: {str(b): v for b, v in p.items()}
                                    for k, p in series.items()},
                   "still_panel": {"title": STILL_PANEL["title"], "point": still,
                                   "cell_px": cell_px, "max_tiles": max_tiles},
                   "floors": {p["title"]: floor_pct(p["subset"])
                              for p in FRAME_PANELS + [STILL_PANEL]},
                   "notes": notes}, f, indent=1)
    print(f"wrote {side}")
    for n in notes:
        print("  NOTE:", n)


if __name__ == "__main__":
    main()
