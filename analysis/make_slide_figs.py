#!/usr/bin/env python3
"""Render the July-30 results deck figures (the InternVL3-8B remake of the
mentor's "Multi-camera Video Understanding" slides) from analysis/slide_stats.json
ONLY — no number is computed here. Output: analysis/figs_deck/fig*.png, sized for
16:9 slides. Figures whose runs are still queued (blind, single-view, budget-32)
render as placeholders until slide_stats.json contains their sections, then pick
up the real data on rerun.

Style: mentor-deck semantics (sequential=near-black, centralized=blue,
decentralized=gray) on a white surface; palette CVD-validated (see
scratchpad validate_palette port of the dataviz skill checks).

Run (no GPU): python3 analysis/make_slide_figs.py
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "figs_deck")
os.makedirs(OUT, exist_ok=True)
S = json.load(open(os.path.join(HERE, "slide_stats.json")))

INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, BASE = "#e1e0d9", "#c3c2b7"
SEQ, CEN, DEC = "#0b0b0b", "#2a78d6", "#898781"   # arrangement arms
POS, NEG = "#2a78d6", "#e34948"                   # diverging delta poles
CLIP3 = ["#eb6834", "#1baf7a", "#4a3aa7"]         # frame_sel / temporal / clip_top1
GREEN = "#008300"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "figure.facecolor": "white",
    "axes.facecolor": "white", "axes.edgecolor": BASE,
    "text.color": INK, "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "font.size": 11,
})
FIG_KW = dict(figsize=(10, 5.6), dpi=150)


def style(ax, ymax=None, ygrid=True):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left",):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    if ygrid:
        ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    if ymax:
        ax.set_ylim(0, ymax)


def header(fig, title, subtitle):
    fig.text(0.05, 0.955, title, fontsize=19, fontweight="bold", ha="left", va="top")
    fig.text(0.05, 0.885, subtitle, fontsize=10.5, color=INK2, ha="left", va="top")


def footer(fig, text):
    fig.text(0.05, 0.015, text, fontsize=10, color=INK2, ha="left", va="bottom")


def bar_labels(ax, bars, fmt="{:.1f}", dy=0.6):
    for b in bars:
        v = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2, v + dy, fmt.format(v),
                ha="center", va="bottom", fontsize=10, color=INK)


def wrap(text, width):
    """Greedy wrap — matplotlib does not wrap fig.text, and an overflowing note
    silently runs off the right edge of the PNG."""
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def placeholder(name, title, note):
    fig = plt.figure(**FIG_KW)
    header(fig, title, "")
    fig.text(0.5, 0.5, note, ha="center", va="center", fontsize=13, color=MUTED)
    fig.savefig(os.path.join(OUT, name), bbox_inches=None)
    plt.close(fig)


ARMS = [("cvbench_native", "sequential", SEQ),
        ("centralized", "centralized (stitching)", CEN),
        ("per_stream", "decentralized", DEC)]


# Datasets this deck reports. The mentor's ask is the two video benchmarks
# re-run end to end; All-Angles is computed by the stats layer but not rendered,
# so putting "aab170" back here (and in DECK_DATASETS) is all it takes to return
# it to every figure.
DECK_POOLS = ["mvu_full", "meva1033"]
DECK_DATASETS = ["MVU-Eval", "CrossView-MEVA"]

# Display order for the n-way (dataset, backend) legs. Any leg present in
# slide_stats but missing here still renders, appended at the end — adding a
# backend needs no edit to the figure code.
LEG_ORDER = ["mvu_full|InternVL3-8B", "mvu_full|Qwen2.5-VL-7B-Instruct",
             "meva1033|InternVL3-8B", "meva1033|Qwen2.5-VL-7B-Instruct"]
SHORT_BACKEND = {"InternVL3-8B": "InternVL3-8B", "Qwen2.5-VL-7B-Instruct": "Qwen2.5-VL-7B"}


def ordered_legs():
    legs = {k: v for k, v in S["arrangement"].get("legs", {}).items()
            if v["pool"] in DECK_POOLS}
    keys = [k for k in LEG_ORDER if k in legs] + \
           [k for k in sorted(legs) if k not in LEG_ORDER]
    return [(k, legs[k]) for k in keys]


# ── fig 1: Does the arrangement matter? ─────────────────────────────────────────
def fig_arrangement():
    legs = ordered_legs()
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.07, 0.24, 0.88, 0.47])
    W, gap = 0.235, 0.03
    import matplotlib.lines as mlines
    for gi, (_, leg) in enumerate(legs):
        for ai, (key, label, color) in enumerate(ARMS):
            arm = leg["arms"].get(key)
            if not arm:
                continue
            x = gi + (ai - 1) * (W + gap)
            b = ax.bar([x], [arm["acc"]], width=W, color=color,
                       label=label if gi == 0 else None)
            bar_labels(ax, b, dy=0.5)
        ax.hlines(leg["chance"], gi - 0.44, gi + 0.44, color=MUTED,
                  linestyle=(0, (4, 3)), linewidth=1.2)
        mf = leg["majority_floor"]["acc"]
        ax.hlines(mf, gi - 0.44, gi + 0.44, color=NEG, linestyle=(0, (1, 2)),
                  linewidth=1.6)
    # three short lines: five groups do not leave room for one long label
    ax.set_xticks(range(len(legs)))
    ax.set_xticklabels([f"{leg['label']}\n"
                        f"{SHORT_BACKEND.get(leg['backend'], leg['backend'])}\n"
                        f"{leg['modality']} · n={leg['n_pool']:,}"
                        for _, leg in legs], fontsize=9.5, color=INK2)
    style(ax, ymax=62)
    ax.set_ylabel("accuracy, percent")
    h, l = ax.get_legend_handles_labels()
    h += [mlines.Line2D([], [], color=MUTED, linestyle=(0, (4, 3)), linewidth=1.2),
          mlines.Line2D([], [], color=NEG, linestyle=(0, (1, 2)), linewidth=1.6)]
    l += ["random guessing", "always-answer-the-most-common-letter floor"]
    ax.legend(h, l, loc="upper left", bbox_to_anchor=(-0.01, 1.28), ncol=3,
              frameon=False, fontsize=9.5, handlelength=1.4)
    header(fig, "Does the arrangement matter? It depends on the dataset.",
           "The 3 conditions on the same questions, 4 passes each, every (dataset, model) leg that has run.\n"
           "8 frames per video, so the frame count floats with view count — see the unmatched-budget slide.")
    p = S["arrangement"]["perm"]
    cvp = ((S.get("crossview") or {}).get("legs", {})
           .get("InternVL3-8B", {}).get("perm", {}).get("cvbench_native-centralized"))
    cv_bit = (f"On CrossView-MEVA the ordering FLIPS — stitching wins by {abs(cvp['delta']):.1f} "
              f"(p={cvp['p']:.3f}) — but only InternVL3-stitching clears\nthat dotted always-A floor, "
              "by 1.5 points: those bars compare harnesses, not task competence."
              if cvp else "")
    footer(fig, f"On MVU-Eval centralized is within {abs(p['cvbench_native-centralized']['delta']):.1f} points of "
                f"sequential (p={p['cvbench_native-centralized']['p']:.2f}); decentralized is "
                f"{abs(p['cvbench_native-per_stream']['delta']):.1f} below it (p<0.001).\n" + cv_bit)
    fig.savefig(os.path.join(OUT, "fig1_arrangement.png"))
    plt.close(fig)


# ── fig 2: synchronized vs unrelated ────────────────────────────────────────────
def fig_sync():
    sy = S["sync"]
    rows = [("Synchronized\n6-camera rigs\n128 questions", sy["sync128"]["stitch_delta"]),
            ("Unrelated clips\n1,696 questions", sy["unrelated"]["stitch_delta"])]
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.22, 0.24, 0.72, 0.50])
    ys = [1, 0]
    for y, (label, d) in zip(ys, rows):
        v = d["delta"]
        ax.barh([y], [v], height=0.42, color=(POS if v >= 0 else NEG))
        ax.text(v + (0.12 if v >= 0 else -0.12), y, f"{v:+.2f}\np={d['p']:.2f}",
                va="center", ha=("left" if v >= 0 else "right"), fontsize=10.5, color=INK)
    ax.axvline(0, color=INK, linewidth=1)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], fontsize=10.5, color=INK2)
    ax.set_xlim(-4.5, 4.5)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xlabel("change in accuracy from stitching, percentage points")
    header(fig, "Does it matter if the cameras are synchronized?",
           "Stitching delta (centralized − sequential), InternVL3-8B, inside one benchmark with the same code, model,\n"
           "prompt and scoring. Sync slice = the 128 nuScenes 6-camera rigs.")
    footer(fig, "On synchronized cameras stitching changes accuracy by +1.56 points; on unrelated clips by −1.12. Neither is\n"
                "statistically significant (question-level permutation). Same shape as the reference deck: whatever stitching\n"
                "buys, it buys only on genuinely synchronized cameras.")
    fig.savefig(os.path.join(OUT, "fig2_sync.png"))
    plt.close(fig)


# ── fig 3: per-task stitching delta ─────────────────────────────────────────────
def fig_pertask():
    PRETTY = {"MVU-Counting": "Counting", "MVU-OR": "Object recognition",
              "MVU-SU": "Spatial understanding", "MVU-ICL": "In-context learning",
              "MVU-RAG": "Retrieval", "MVU-KIR": "Knowledge reasoning",
              "MVU-Comparison": "Comparison", "MVU-TR": "Temporal reasoning"}
    items = sorted(S["per_task"].items(), key=lambda kv: kv[1]["delta"], reverse=True)
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.24, 0.23, 0.70, 0.55])
    ys = range(len(items) - 1, -1, -1)
    for y, (t, d) in zip(ys, items):
        v = d["delta"]
        ax.barh([y], [v], height=0.55, color=(POS if v >= 0 else NEG))
        ax.text(v + (0.15 if v >= 0 else -0.15), y,
                f"{v:+.2f}  (p={d['p']:.2f}, n={d['n']})",
                va="center", ha=("left" if v >= 0 else "right"), fontsize=9.5, color=INK2)
    ax.axvline(0, color=INK, linewidth=1)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([PRETTY[t] for t, _ in items], fontsize=10.5, color=INK2)
    ax.set_xlim(-7.5, 7.5)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xlabel("change in accuracy from stitching, percentage points")
    header(fig, "Is there one arrangement that works? Not in my run.",
           "centralized − sequential per MVU-Eval question type, full 1,824 questions, InternVL3-8B.")
    footer(fig, "NONE of the 8 differences survives Holm correction — or even reaches p<0.05 alone. The reference deck's one\n"
                "surviving result (Counting +6.83 with InternVL) REVERSES here (−2.86, p=0.33): at my 8-frames-per-video\n"
                "budget, stitching does not help counting.")
    fig.savefig(os.path.join(OUT, "fig3_pertask.png"))
    plt.close(fig)


# ── fig 4: clip experiment on the full pool ─────────────────────────────────────
def fig_clip():
    order = [("frame_select", "frame_select\n(CLIP top-64 frames)"),
             ("temporal_weighted", "temporal_weighted\n(64 frames, all clips)"),
             ("clip_select_top1", "clip_select_top1\n(all 64 on ONE clip)")]
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.08, 0.20, 0.86, 0.55])
    for i, ((key, label), color) in enumerate(zip(order, CLIP3)):
        v = S["clip"][key]["acc"]
        b = ax.bar([i], [v], width=0.5, color=color)
        bar_labels(ax, b)
    seq = S["arrangement"]["mvu_full"]["cvbench_native"]["acc"]
    ax.axhline(seq, color=MUTED, linestyle=(0, (4, 3)), linewidth=1.2)
    ax.text(2.35, seq + 0.5, f"sequential, all frames: {seq:.1f}", fontsize=9.5,
            color=INK2, ha="right")
    ax.set_xticks(range(3))
    ax.set_xticklabels([l for _, l in order], fontsize=10, color=INK2)
    style(ax, ymax=60)
    ax.set_ylabel("accuracy, percent")
    header(fig, "Spending the budget on fewer clips does not help",
           "The clip experiment on the FULL 1,824 questions (matched 64-frame total budget), InternVL3-8B.")
    footer(fig, "Selecting frames (52.4) ties uniform sampling (51.8) and both sit at the sequential baseline. Betting everything\n"
                "on one clip collapses (43.8) — partly structural: 70% of MVU-Eval questions name specific videos in text or\n"
                "options, and a view-discarding method cannot answer those.")
    fig.savefig(os.path.join(OUT, "fig4_clip.png"))
    plt.close(fig)


# ── fig 5: the budget was not matched (what is wrong) ───────────────────────────
def fig_budget():
    f = S["forensics"]
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.08, 0.20, 0.38, 0.50])
    vals = [f["native_video_tokens_median"], f["centralized_video_tokens_median"]]
    b = ax.bar([0, 1], vals, width=0.5, color=[SEQ, CEN])
    for x, v in zip((0, 1), vals):
        ax.text(x, v + 150, f"{v:,}", ha="center", fontsize=10.5, color=INK)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["sequential", "centralized\n(stitching)"], fontsize=10.5, color=INK2)
    style(ax, ymax=12000)
    ax.set_ylabel("median visual tokens per question")
    ax.set_title("the montage carries 0.63× the tokens", fontsize=11, color=INK2, pad=8)

    ax2 = fig.add_axes([0.58, 0.20, 0.36, 0.50])
    ks = list(range(2, 14))
    ax2.plot(ks, [8 * k for k in ks], color=SEQ, linewidth=2, label="my run: 8 × K frames")
    ax2.axhline(32, color=NEG, linestyle=(0, (4, 3)), linewidth=1.6,
                label="reference protocol: 32 total")
    ax2.set_xlabel("videos per question (K)")
    ax2.set_ylabel("frames fed per question")
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    ax2.grid(axis="y", color=GRID, linewidth=0.8)
    ax2.set_axisbelow(True)
    ax2.tick_params(length=0)
    ax2.legend(frameon=False, fontsize=9.5, loc="upper left")
    ax2.set_title("the frame budget floats with K", fontsize=11, color=INK2, pad=8)
    header(fig, "What is wrong: the budgets were not matched",
           "Two protocol gaps found while rebuilding the reference slides from my run (measured from the real result\n"
           "rows, not the configs).")
    b32 = S.get("budget32") or {}
    if b32.get("cvbench_native"):
        tail = (f"The fixed-32 rerun answers it: seq {b32['cvbench_native']['acc']:.1f} / "
                f"stitch {b32['centralized']['acc']:.1f} / decentral {b32['per_stream']['acc']:.1f} —\n"
                "same story at the matched budget (centralized still rounds to 26–36 frames on its montage grid).")
    else:
        tail = "The corrected fixed-32 rerun of all\nthree arms is queued (job 72241)."
    footer(fig, "“Same images at the same budget” does not hold in my run: stitching squeezes into 0.63× the tokens, and every\n"
                f"question's frame count floats with its view count instead of a fixed 32. {tail}")
    fig.savefig(os.path.join(OUT, "fig5_budget.png"))
    plt.close(fig)


# ── fig 6/7: blind + single-view (real when jobs land, placeholder until) ──────
def fig_blind():
    bl = S.get("blind") or {}
    if not bl.get("mvu_full"):
        placeholder("fig6_blind.png", "Do the images even help?",
                    "blind (no images) arm launched — jobs 72235 (MVU-Eval) & 72236 (All-Angles)\n"
                    "rerun analysis/mvueval_slide_stats.py + this script when they finish")
        return
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.07, 0.14, 0.88, 0.60])
    groups = [("InternVL3-8B\nMVU-Eval (n=1,824)", bl["mvu_full"]["acc"],
               S["arrangement"]["mvu_full"]["cvbench_native"]["acc"],
               S["arrangement"]["chance"]["mvu_full"], bl["images_add"]["delta"])]
    if bl.get("aab170") and "aab170" in DECK_POOLS:
        groups.append(("InternVL3-8B\nAll-Angles EgoHumans (n=170)", bl["aab170"]["acc"],
                       S["arrangement"]["aab170"]["cvbench_native"]["acc"],
                       S["arrangement"]["chance"]["aab170"], bl["aab170_images_add"]["delta"]))
    W = 0.28
    for gi, (gname, b_acc, s_acc, ch, d) in enumerate(groups):
        bb = ax.bar([gi - W / 2 - 0.02], [b_acc], width=W, color=DEC,
                    label="blind, no images" if gi == 0 else None)
        sb = ax.bar([gi + W / 2 + 0.02], [s_acc], width=W, color=SEQ,
                    label="sequential, all views" if gi == 0 else None)
        bar_labels(ax, bb); bar_labels(ax, sb)
        ax.hlines(ch, gi - 0.45, gi + 0.45, color=MUTED, linestyle=(0, (4, 3)), linewidth=1.2)
        ax.text(gi, max(b_acc, s_acc) + 5.5, f"images add {d:+.1f}",
                ha="center", fontsize=11, fontweight="bold", color=INK)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([g[0] for g in groups], fontsize=10.5, color=INK2)
    style(ax, ymax=68)
    ax.set_ylabel("accuracy, percent")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.18), ncol=3, frameon=False, fontsize=9.5)
    header(fig, "Do the images even help?",
           "blind = the identical prompt with zero visual input, 4 passes, vs sequential with all views. "
           "Dashed line: random guessing.")
    ia = bl["images_add"]
    footer(fig, f"On MVU-Eval the images add {ia['delta']:+.1f} points (p={ia['p']:.3g}). "
                "Whatever blind scores above random guessing is text-prior exploitation in the benchmark itself.")
    fig.savefig(os.path.join(OUT, "fig6_blind.png"))
    plt.close(fig)


def fig_singleview():
    sv = S.get("single_view") or {}
    if not sv.get("n_q_complete"):
        placeholder("fig7_singleview.png", "Does picking the right view matter?",
                    "single_view1–13 sweep launched on the 545 questions that don't name a video\n"
                    "job 72240 — rerun analysis/mvueval_slide_stats.py + this script when it finishes")
        return
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.08, 0.14, 0.86, 0.58])
    bars = [("best single view", sv["best"], GREEN),
            ("all views (sequential)", sv["sequential_all_views"], SEQ),
            ("a randomly chosen view", sv["random"], DEC),
            ("worst single view", sv["worst"], NEG)]
    for i, (label, v, c) in enumerate(bars):
        b = ax.bar([i], [v], width=0.5, color=c)
        bar_labels(ax, b)
    luck = sv["luck_best_of_k"]
    ax.axhline(luck, color=MUTED, linestyle=(0, (4, 3)), linewidth=1.2)
    ax.text(3.4, luck + 0.6, f"what lucky guessing alone gives: {luck:.1f}",
            ha="right", fontsize=9.5, color=INK2)
    ax.set_xticks(range(4))
    ax.set_xticklabels([b[0] for b in bars], fontsize=10, color=INK2)
    style(ax, ymax=max(v for _, v, _ in bars) + 12)
    ax.set_ylabel("accuracy, percent")
    header(fig, "Does picking the right view matter?",
           f"Single-view runs on the {sv['n_q_complete']} MVU-Eval questions whose text does not name a "
           "video (naming a view already does the picking), InternVL3-8B, 4 passes per view.")
    footer(fig, f"The best single view scores {sv['best'] - sv['sequential_all_views']:+.1f} over feeding all views; "
                f"subtracting the lucky-guessing inflation leaves {sv['best'] - luck:+.1f}. A random view costs "
                f"{sv['random'] - sv['sequential_all_views']:+.1f}. Choosing one view only helps when the choice is right.")
    fig.savefig(os.path.join(OUT, "fig7_singleview.png"))
    plt.close(fig)


# ── fig 9: selector headroom (blind x vision joint contingency) ─────────────────
def fig_headroom():
    con = (S.get("blind") or {}).get("contingency")
    if not con or not con.get("overall"):
        placeholder("fig9_headroom.png", "How many points can a selector still add?",
                    "needs the blind x vision contingency — rerun analysis/mvueval_slide_stats.py\n"
                    "once the blind and mvufull rows are on disk")
        return
    PRETTY = {"MVU-Counting": "Counting", "MVU-OR": "Object recognition",
              "MVU-SU": "Spatial understanding", "MVU-ICL": "In-context learning",
              "MVU-RAG": "Retrieval", "MVU-KIR": "Knowledge reasoning",
              "MVU-Comparison": "Comparison", "MVU-TR": "Temporal reasoning"}
    fig = plt.figure(**FIG_KW)

    def stack(ax, y, c, height=0.5, labels=True):
        right = c["right_both"] + c["vision_helped"]
        segs = [(right, SEQ), (c["vision_hurt"], NEG), (c["wrong_both"], BASE)]
        x = 0.0
        for v, color in segs:
            ax.barh([y], [v], left=x, height=height, color=color)
            if labels and v > 4:
                ax.text(x + v / 2, y, f"{v:.1f}", va="center", ha="center",
                        fontsize=9.5, color=("white" if color == SEQ else INK))
            x += v

    # top: overall, one wide bar
    ax = fig.add_axes([0.26, 0.615, 0.68, 0.095])
    stack(ax, 0, con["overall"], height=0.9)
    ax.set_xlim(0, 100); ax.set_ylim(-0.6, 0.6)
    ax.set_yticks([0]); ax.set_yticklabels(["all 1,824\nquestions"], fontsize=10, color=INK2)
    ax.set_xticks([]); [s.set_visible(False) for s in ax.spines.values()]
    ax.tick_params(length=0)

    # bottom: per task, sorted by recoverable share
    items = sorted(((t, c) for t, c in con["by_task"].items() if c),
                   key=lambda kv: kv[1]["vision_hurt"], reverse=True)
    ax2 = fig.add_axes([0.26, 0.135, 0.68, 0.42])
    for i, (t, c) in enumerate(items):
        stack(ax2, len(items) - 1 - i, c, height=0.62)
    ax2.set_xlim(0, 100); ax2.set_ylim(-0.6, len(items) - 0.4)
    ax2.set_yticks(range(len(items) - 1, -1, -1))
    ax2.set_yticklabels([f"{PRETTY.get(t, t)}  (n={c['n_q']})" for t, c in items],
                        fontsize=9.5, color=INK2)
    ax2.set_xticks(range(0, 101, 25))
    ax2.set_xticklabels(["0", "25", "50", "75", "100%\nof questions"], fontsize=9, color=MUTED)
    ax2.grid(axis="x", color=GRID, linewidth=0.8)
    ax2.set_axisbelow(True); ax2.tick_params(length=0)
    for s in ax2.spines.values():
        s.set_visible(False)

    import matplotlib.patches as mpatches
    fig.legend(handles=[mpatches.Patch(color=SEQ, label="right with images"),
                        mpatches.Patch(color=NEG, label="recoverable (blind right, images wrong)"),
                        mpatches.Patch(color=BASE, label="wrong either way")],
               loc="upper left", bbox_to_anchor=(0.24, 0.815), ncol=3, frameon=False,
               fontsize=9.5, handlelength=1.2, columnspacing=1.4)
    o = con["overall"]
    header(fig, "How many points can a selector still add?",
           "blind and sequential compared question by question (probabilistic over the 4 passes:\n"
           "per-question pass-mean correctness with and without images, quadrant mass = their products).")
    footer(fig, f"Only {o['vision_hurt']:.1f} points sit where the images made the answer worse than showing nothing — that is the frame-\n"
                f"selection headroom. {o['wrong_both']:.1f} points are wrong with AND without images; no selector reaches those.")
    fig.savefig(os.path.join(OUT, "fig9_headroom.png"))
    plt.close(fig)


# ── fig 10: single-view per task + per-view-index sanity ────────────────────────
def fig_singleview_tasks():
    sv = S.get("single_view") or {}
    if not sv.get("by_task"):
        placeholder("fig10_singleview_tasks.png", "Where does picking the view pay off?",
                    "needs single_view.by_task — rerun analysis/mvueval_slide_stats.py")
        return
    PRETTY = {"MVU-Counting": "Counting", "MVU-OR": "Object recognition",
              "MVU-SU": "Spatial understanding", "MVU-ICL": "In-context learning",
              "MVU-RAG": "Retrieval", "MVU-KIR": "Knowledge reasoning",
              "MVU-Comparison": "Comparison", "MVU-TR": "Temporal reasoning"}
    SMALL_N = 30
    items = sorted(sv["by_task"].items(),
                   key=lambda kv: kv[1]["best"] - (kv[1]["sequential_all_views"] or 0),
                   reverse=True)
    fig = plt.figure(**FIG_KW)

    # left: per-task dumbbell, all-views -> best view
    ax = fig.add_axes([0.24, 0.14, 0.38, 0.62])
    for i, (t, d) in enumerate(items):
        y = len(items) - 1 - i
        tiny = d["n_q"] < SMALL_N
        c_best, c_seq = (MUTED, MUTED) if tiny else (GREEN, SEQ)
        s = d["sequential_all_views"]
        ax.plot([s, d["best"]], [y, y], color=(GRID if tiny else BASE),
                linewidth=2, zorder=1)
        ax.scatter([s], [y], color=c_seq, s=42, zorder=2)
        ax.scatter([d["best"]], [y], color=c_best, s=42, zorder=2)
        if not tiny:
            ax.text(d["best"] + 2, y, f"+{d['best'] - s:.0f}", va="center",
                    fontsize=9.5, color=INK)
    ax.set_yticks(range(len(items) - 1, -1, -1))
    ax.set_yticklabels([f"{PRETTY.get(t, t)}  (n={d['n_q']})" for t, d in items],
                       fontsize=9.5, color=INK2)
    for i, (t, d) in enumerate(items):     # gray out the tiny-n tick labels
        if d["n_q"] < SMALL_N:
            ax.get_yticklabels()[i].set_color(MUTED)
    ax.set_xlim(0, 100)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True); ax.tick_params(length=0)
    for s_ in ax.spines.values():
        s_.set_visible(False)
    ax.set_xlabel("accuracy, percent")
    ax.set_title("all views (black) → best single view (green)", fontsize=10.5,
                 color=INK2, pad=8)

    # right: accuracy by view index (positional-artifact check)
    pv = sv.get("per_view_index") or {}
    ax2 = fig.add_axes([0.70, 0.14, 0.26, 0.62])
    idx = sorted(int(v) for v in pv)
    ax2.plot(idx, [pv[str(v)]["acc"] for v in idx], color=SEQ, linewidth=2,
             marker="o", markersize=4)
    for v in idx:
        if v in (1, 7) or v == idx[-1]:
            ax2.annotate(f"n={pv[str(v)]['n_q']}", (v, pv[str(v)]["acc"]),
                         textcoords="offset points", xytext=(0, 8),
                         fontsize=8.5, color=MUTED, ha="center")
    ax2.axvspan(6.5, max(idx) + 0.5, color=GRID, alpha=0.5, zorder=0)
    ax2.text(6.7, 20, "only high-K questions\nhave views 7+", fontsize=8.5,
             color=MUTED, va="bottom")
    ax2.set_xlabel("view index"); ax2.set_ylim(0, 75)
    ax2.grid(axis="y", color=GRID, linewidth=0.8)
    ax2.set_axisbelow(True); ax2.tick_params(length=0)
    for s_ in ("top", "right"):
        ax2.spines[s_].set_visible(False)
    ax2.set_title("accuracy by view slot", fontsize=10.5, color=INK2, pad=8)

    big = [(t, d) for t, d in items if d["n_q"] >= SMALL_N]
    lead = ", ".join(f"{PRETTY.get(t, t)} +{d['best'] - d['sequential_all_views']:.0f}"
                     for t, d in big[:2])
    header(fig, "Where does picking the view pay off?",
           f"The {sv['n_q_complete']}-question single-view sweep split by task. Gray rows have too few "
           f"questions to read (n<{SMALL_N});\nthey are shown, not hidden.")
    footer(fig, f"The view-selection headroom concentrates in {lead}.\n"
                "Right panel: flat across slots 1–6 → no positional artifact; the swings at 7+ are "
                "question composition at tiny n, not position.")
    fig.savefig(os.path.join(OUT, "fig10_singleview_tasks.png"))
    plt.close(fig)


# ── fig 11: the frame-budget story vs the paper's protocol ──────────────────────
def fig_frame_budget():
    fb = S.get("frame_budget")
    if not fb or not any(p["arms"] for p in fb["points"]):
        placeholder("fig11_framebudget.png", "Does the frame budget explain anything?",
                    "needs the frame_budget section — rerun analysis/mvueval_slide_stats.py")
        return
    paper = S["paper"]
    pts = fb["points"]
    xt = [f"{p['label']}\n(≈{p['frames_per_q_mean']:.0f} frames/question)" for p in pts]
    fig = plt.figure(**FIG_KW)

    # left: overall accuracy per budget point, native + per_stream
    ax = fig.add_axes([0.08, 0.16, 0.50, 0.56])
    for m, label, color in (("cvbench_native", "sequential (native)", SEQ),
                            ("per_stream", "decentralized (per-stream)", DEC)):
        xs, ys, es = [], [], []
        for i, p in enumerate(pts):
            a = p["arms"].get(m)
            if a:
                xs.append(i); ys.append(a["acc"]); es.append(a["pass_std"] or 0)
        if xs:
            ax.errorbar(xs, ys, yerr=es, color=color, linewidth=2, marker="o",
                        markersize=5, capsize=3, label=label)
            for x, y in zip(xs, ys):
                ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points",
                            xytext=(0, 9), fontsize=9.5, color=INK, ha="center")
    queued = [i for i, p in enumerate(pts) if p.get("status") == "queued"]
    prelim = [i for i, p in enumerate(pts) if p.get("status") == "preliminary"]
    for i in queued:
        ax.text(i, 54, "parity run\nqueued", ha="center", fontsize=9.5,
                color=MUTED, style="italic")
    for i in prelim:
        rows = pts[i].get("rows_in") or {}
        exp = pts[i].get("rows_expected_per_arm") or 0
        pct = (100 * min(rows.values()) / exp) if rows and exp else 0
        ax.text(i, 22.5, f"preliminary — runs in flight\n({pct:.0f}% of rows in)",
                ha="center", fontsize=9, color=MUTED, style="italic")
    pi = paper["internvl3_8b"]["overall"]
    ax.axhline(pi, color=NEG, linestyle=(0, (4, 3)), linewidth=1.6)
    ax.text(len(pts) - 0.55, pi + 0.5, f"paper's InternVL3-8B: {pi:.1f}\n(their 32/video protocol)",
            fontsize=9, color=NEG, ha="right")
    ax.axhline(paper["random"], color=MUTED, linestyle=(0, (4, 3)), linewidth=1.2)
    ax.text(len(pts) - 0.55, paper["random"] + 0.5, f"random: {paper['random']:.1f}",
            fontsize=9, color=MUTED, ha="right")
    ax.set_xticks(range(len(pts)))
    ax.set_xticklabels(xt, fontsize=9.5, color=INK2)
    ax.set_xlim(-0.35, len(pts) - 0.65)
    style(ax, ymax=62)
    ax.set_ylim(20, 62)
    ax.set_ylabel("accuracy, percent")
    ax.legend(loc="lower left", frameon=False, fontsize=9.5)

    # right: the long-context facet (native, K<=4 vs K>=5). At 32/video the
    # K=4 prompts already total ~34k tokens (visual alone = 32,768 = the full
    # pre-trained window); K>=5 runs 1.3-3.4x past it on dynamic-NTK rope.
    ax2 = fig.add_axes([0.67, 0.16, 0.29, 0.56])
    W = 0.34
    ks = fb["k_split"]
    for j, (kk, label, color) in enumerate(
            (("k_le_4", f"K≤4 (n={ks['n_le_4']}) — ≤34k tokens, at the window", CEN),
             ("k_ge_5", f"K≥5 (n={ks['n_ge_5']}) — 42k–112k, deep past it", NEG))):
        xs, ys = [], []
        for i, p in enumerate(pts):
            a = p["arms"].get("cvbench_native")
            if a and a["by_k"][kk]["acc"] is not None:
                xs.append(i + (j - 0.5) * W); ys.append(a["by_k"][kk]["acc"])
        b = ax2.bar(xs, ys, width=W, color=color, label=label)
        for x, y in zip(xs, ys):
            ax2.text(x, y + 0.7, f"{y:.1f}", ha="center", fontsize=8.5, color=INK)
    ax2.set_xticks(range(len(pts)))
    ax2.set_xticklabels(["32 total", "8/video", "32/video"], fontsize=9.5, color=INK2)
    style(ax2, ymax=78)
    ax2.set_title("sequential, split by view count", fontsize=10.5, color=INK2, pad=8)
    ax2.legend(loc="upper left", frameon=False, fontsize=8.5, handlelength=1.2)

    have_parity = not queued
    header(fig, "Does the frame budget explain anything?",
           "The same questions at three per-question frame budgets, InternVL3-8B, 4 passes. The paper's own\n"
           f"protocol is 32 frames per video (mean K={fb['mean_k']:.1f} → ≈{pts[2]['frames_per_q_mean']:.0f} frames); "
           "even K=4 fills the 32k window, K≥5 runs far past it.")
    if have_parity:
        nat = pts[2]["arms"].get("cvbench_native", {})
        tag = " (PRELIMINARY — the arrays are still draining)" if prelim else ""
        footer(fig, f"At the paper's own budget our sequential arm scores {nat.get('acc', 0):.1f}{tag} vs their published "
                    f"{pi:.1f}. The right panel shows whether any change\nconcentrates in K≥5, which runs deepest past "
                    "the pre-trained window — long-context degradation, not frame count.")
    else:
        footer(fig, f"Our runs beat the paper's published {pi:.1f} at BOTH tested budgets while feeding fewer frames. "
                    "The 32/video paper-parity arm is queued;\nif accuracy drops there — concentrated in K≥5 — the "
                    "paper's low InternVL number is a long-context artifact of its own protocol.")
    fig.savefig(os.path.join(OUT, "fig11_framebudget.png"))
    plt.close(fig)


# ── fig 12: which tasks can measure a vision harness? ───────────────────────────
def fig_task_relevance():
    tr = S.get("task_relevance")
    if not tr:
        placeholder("fig12_task_relevance.png", "Which tasks can measure the harness?",
                    "needs the task_relevance section — rerun analysis/mvueval_slide_stats.py")
        return
    PRETTY = {"MVU-Counting": "Counting", "MVU-OR": "Object recognition",
              "MVU-SU": "Spatial understanding", "MVU-ICL": "In-context learning",
              "MVU-RAG": "Retrieval", "MVU-KIR": "Knowledge reasoning",
              "MVU-Comparison": "Comparison", "MVU-TR": "Temporal reasoning"}
    items = sorted(tr.items(), key=lambda kv: kv[1]["images_add"]["delta"],
                   reverse=True)
    n = len(items)
    ys = range(n - 1, -1, -1)

    fig = plt.figure(**FIG_KW)
    # panel A: images_add per task (vision-dependence)
    ax = fig.add_axes([0.24, 0.14, 0.30, 0.60])
    for y, (t, d) in zip(ys, items):
        ia = d["images_add"]
        sig = ia["p"] is not None and ia["p"] < 0.05
        color = (POS if ia["delta"] >= 0 else NEG) if sig else BASE
        ax.barh([y], [ia["delta"]], height=0.6, color=color)
        ax.text(ia["delta"] + (0.9 if ia["delta"] >= 0 else -0.9), y,
                f"{ia['delta']:+.1f}" + ("" if sig else f"  p={ia['p']:.2f}"),
                va="center", ha=("left" if ia["delta"] >= 0 else "right"),
                fontsize=9, color=INK)
    ax.axvline(0, color=INK, linewidth=1)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([f"{PRETTY.get(t, t)}  (n={d['n_q']})" for t, d in items],
                       fontsize=9.5, color=INK2)
    ax.set_xlim(-6, 46)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True); ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("what the images add, points", fontsize=10.5, color=INK2, pad=8)

    # panel B: blind margin over chance (text-solvability)
    ax2 = fig.add_axes([0.60, 0.14, 0.20, 0.60])
    for y, (t, d) in zip(ys, items):
        v = d["blind_acc"] - d["chance"]
        ax2.barh([y], [v], height=0.6, color=DEC)
        ax2.text(v + (0.4 if v >= 0 else -0.4), y, f"{v:+.1f}", va="center",
                 ha=("left" if v >= 0 else "right"), fontsize=9, color=INK)
    ax2.axvline(0, color=INK, linewidth=1)
    ax2.set_yticks(list(ys)); ax2.set_yticklabels([])
    ax2.set_xlim(-6, 26)
    ax2.grid(axis="x", color=GRID, linewidth=0.8)
    ax2.set_axisbelow(True); ax2.tick_params(length=0)
    for s in ax2.spines.values():
        s.set_visible(False)
    ax2.set_title("blind margin over chance", fontsize=10.5, color=INK2, pad=8)

    # panel C: view-selection headroom (text column, only where n allows)
    ax3 = fig.add_axes([0.84, 0.14, 0.12, 0.60])
    ax3.set_xlim(0, 1); ax3.set_ylim(-0.6, n - 0.4)
    for y, (t, d) in zip(ys, items):
        sv = d.get("sv")
        if sv and sv["n_q"] >= 30:
            txt = f"+{sv['best'] - sv['sequential_all_views']:.0f}  (n={sv['n_q']})"
            c = INK
        else:
            txt, c = "—", MUTED
        ax3.text(0.05, y, txt, va="center", fontsize=9.5, color=c)
    ax3.axis("off")
    ax3.set_title("view-selection\nheadroom", fontsize=10.5, color=INK2, pad=8)

    icl = tr["MVU-ICL"]["images_add"]
    header(fig, "Which tasks can measure the harness?",
           "All 8 MVU-Eval tasks, no cherry-picking — three kinds of evidence per task: does vision help at all,\n"
           "how much is solvable from text alone, and how much does choosing the right view add.")
    footer(fig, f"In-context learning is the one task where images do not measurably help "
                f"({icl['delta']:+.1f}, p={icl['p']:.2f}) — it cannot score a vision harness.\n"
                "Every other task is vision-dependent; where the sweep has the n to measure it, "
                "comparison and retrieval carry the largest view-selection headroom.")
    fig.savefig(os.path.join(OUT, "fig12_task_relevance.png"))
    plt.close(fig)


# ── fig 8: defects/census table ─────────────────────────────────────────────────
def fig_defects():
    d = S["defects"]
    nv = d["mvu_names_video"]
    letters = d["mvu_gold_letter_dist"]
    abcd = ", ".join(f"{k} {v}" for k, v in list(letters.items())[:4])
    sync_n = S["meta"]["sync_n"]
    rows = [
        ("Most questions name their videos",
         f"{nv['names_a_video']:,} of {nv['total']:,} questions ({100 * nv['names_a_video'] / nv['total']:.0f}%) "
         "name a specific video in the text or options (“A. Video 1”). Any view-discarding\n"
         "method is structurally penalized on them — they are excluded from the single-view slides."),
        ("Only 7% of the benchmark is truly multi-camera",
         f"Exactly {sync_n} of {nv['total']:,} questions use synchronized cameras — all nuScenes 6-camera "
         "rigs — and they span 6 task types\n(SU 78, Comparison 31, KIR 10, TR 5, OR 3, Counting 1). "
         "Filtering by the SU task does NOT recover this slice."),
        ("The answer key is close to balanced",
         f"Gold letters: {abcd} over 1,824 — no exploitable skew like All-Angles' camera-pose key.\n"
         "A constant-letter guesser gets 25.5%, right at the 25.9% chance floor."),
    ]
    fig = plt.figure(**FIG_KW)
    header(fig, "What the benchmark itself is made of",
           "Dataset-level census of MVU-Eval computed from the raw question files (no model involved) —\n"
           "the analogue of the reference deck's “defects” slide.")
    y = 0.72
    for title, body in rows:
        fig.text(0.05, y, title, fontsize=12.5, fontweight="bold", color=INK)
        fig.text(0.05, y - 0.06, body, fontsize=10.5, color=INK2, va="top")
        y -= 0.22
    fig.savefig(os.path.join(OUT, "fig8_census.png"))
    plt.close(fig)


# ══ CrossView-MEVA panels (figs 13-17) ═════════════════════════════════════════
# The deck's questions re-asked on the second video dataset. Every one of these
# renders only when analysis/slide_stats.json carries a `crossview` section, so
# the deck degrades to the MVU-only story rather than lying if the arrays move.
CV_TASK_PRETTY = {
    "CrossView-MEVA-Event-Ordering": "Event ordering\n(put 4 events in order)",
    "CrossView-MEVA-Spatial": "Spatial\n(which camera / where)",
    "CrossView-MEVA-Temporal": "Temporal\n(when did it happen)",
}
CV_BACKEND_ORDER = ["InternVL3-8B", "Qwen2.5-VL-7B-Instruct"]


def cv_legs():
    legs = ((S.get("crossview") or {}).get("legs") or {})
    return [(b, legs[b]) for b in CV_BACKEND_ORDER if b in legs] + \
           [(b, l) for b, l in sorted(legs.items()) if b not in CV_BACKEND_ORDER]


def cv_floor_lines(ax, x0, x1, chance, majority, task_floor=None):
    """Three reference levels, and the third is the one that matters: a guesser
    that sees only the task type and answers that task's modal letter."""
    ax.hlines(chance, x0, x1, color=MUTED, linestyle=(0, (4, 3)), linewidth=1.2)
    ax.hlines(majority, x0, x1, color=NEG, linestyle=(0, (1, 2)), linewidth=1.6)
    if task_floor is not None:
        ax.hlines(task_floor, x0, x1, color=NEG, linewidth=2.2)


# ── fig 13: CrossView arrangement + what each arrangement costs ────────────────
def fig_crossview_arms():
    cv = S.get("crossview") or {}
    legs = cv_legs()
    if not legs:
        return placeholder("fig13_crossview_arms.png", "CrossView-MEVA arrangement",
                           "no CrossView rows on disk")
    pool = cv["pool"]
    mf, ch = pool["majority"]["acc"], pool["chance"]
    tf = pool["task_floor"]
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.07, 0.235, 0.53, 0.46])
    W = 0.26
    for gi, (backend, leg) in enumerate(legs):
        for ai, (key, label, color) in enumerate(ARMS):
            arm = leg["arms"].get(key)
            if not arm:
                continue
            x = gi + (ai - 1) * (W + 0.03)
            b = ax.bar([x], [arm["acc"]], width=W, color=color,
                       label=label if gi == 0 else None,
                       yerr=[arm["pass_std"] or 0], ecolor=INK2, capsize=3)
            ax.text(x, arm["acc"] + (arm["pass_std"] or 0) + 0.7, f"{arm['acc']:.1f}",
                    ha="center", va="bottom", fontsize=10, color=INK)
        cv_floor_lines(ax, gi - 0.45, gi + 0.45, ch, mf)
    # pool-level constant: one unbroken line, labelled once
    ax.axhline(tf["acc"], color=NEG, linewidth=2.2)
    ax.set_xticks(range(len(legs)))
    ax.set_xticklabels([SHORT_BACKEND.get(b, b) for b, _ in legs],
                       fontsize=10.5, color=INK2)
    style(ax, ymax=64)
    ax.set_ylabel("accuracy, percent")
    ax.text(-0.48, tf["acc"] + 1.5,
            f"text-only floor ({tf['rule']}): {tf['acc']:.1f}", fontsize=9.5,
            color=NEG, ha="left", fontweight="bold")
    # under the line, on the right, where the collapsed Qwen bar leaves room
    ax.text(len(legs) - 0.52, mf - 3.4, f"always answer A: {mf:.1f}", fontsize=9,
            color=NEG, ha="right")
    ax.set_title("accuracy (4 passes; whiskers = per-pass spread, NOT a confidence interval)",
                 fontsize=10, color=INK2, pad=26)

    # right panel: the cost of each arrangement (the other half of Task 1)
    ax2 = fig.add_axes([0.70, 0.235, 0.25, 0.46])
    ivl = dict(legs).get("InternVL3-8B") or legs[0][1]
    cost = ivl.get("cost", {})
    vals = [(cost.get(k) or {}).get("latency_median_s") for k, _, _ in ARMS]
    for i, ((key, label, color), v) in enumerate(zip(ARMS, vals)):
        if v is None:
            continue
        ax2.bar([i], [v], width=0.55, color=color)
        calls = (cost.get(key) or {}).get("model_calls_mean")
        ax2.text(i, v + max(v * 0.02, 1), f"{v:.0f}s\n{calls:.1f} calls",
                 ha="center", va="bottom", fontsize=9.5, color=INK)
    ax2.set_xticks(range(len(ARMS)))
    ax2.set_xticklabels(["seq", "central", "decentral"], fontsize=10, color=INK2)
    style(ax2)
    ax2.set_ylim(0, max(v for v in vals if v is not None) * 1.35)
    ax2.set_ylabel("median seconds per question")
    ax2.set_title(f"cost, {SHORT_BACKEND.get(legs[0][0], legs[0][0])}",
                  fontsize=10.5, color=INK2, pad=26)
    h, l = ax.get_legend_handles_labels()
    ax.legend(h, l, loc="upper left", bbox_to_anchor=(-0.01, 1.30), ncol=3,
              frameon=False, fontsize=9.5, handlelength=1.4)

    header(fig, "Stitching wins — but no arm clears the text-only floor",
           f"The same three conditions on {pool['n']:,} synchronized-rig questions, 4 passes, both backends.\n"
           "CrossView-MEVA is where the MVU-Eval ordering reverses — and where the answer key does the work.")
    p_iv = (dict(legs).get("InternVL3-8B") or {}).get("perm", {})
    p_q = (dict(legs).get("Qwen2.5-VL-7B-Instruct") or {}).get("perm", {})
    bits = []
    if p_iv.get("cvbench_native-centralized"):
        d = p_iv["cvbench_native-centralized"]
        bits.append(f"stitching beats sequential by {abs(d['delta']):.2f} on InternVL3 "
                    f"(p={d['p']:.3f})")
    if p_q.get("cvbench_native-centralized"):
        d = p_q["cvbench_native-centralized"]
        bits.append(f"and by {abs(d['delta']):.2f} on Qwen (p<0.001)")
    worst = min((leg["vs_floor"][m]["task_conditioned"]["delta"]
                 for _, leg in legs for m in leg["vs_floor"]), default=None)
    best = max((leg["vs_floor"][m]["task_conditioned"]["delta"]
                for _, leg in legs for m in leg["vs_floor"]), default=None)
    inc = [(b, m, leg["completeness"][m])
           for b, leg in legs for m in leg.get("incomplete_arms", [])]
    inc_bit = ""
    if inc:
        b, m, c = inc[0]
        inc_bit = (f"\n{SHORT_BACKEND.get(b, b)} {m} covers {c['n_q']:,} of "
                   f"{cv['pool']['n']:,} questions (two shards hit the wall); "
                   "the others move <0.1 on it.")
    footer(fig, "The arrangement comparison is real: " + bits[0] + ",\n" + bits[1]
                + " — and decentralized never wins, collapsing to 18.7 on Qwen.\n"
                f"But EVERY arm on BOTH backends lands {abs(best):.0f}–{abs(worst):.0f} points BELOW the solid "
                "red line: a guesser that reads\nonly the task type and answers that task's modal letter "
                "(all p<0.001). These bars compare harnesses." + inc_bit)
    fig.savefig(os.path.join(OUT, "fig13_crossview_arms.png"))
    plt.close(fig)


# ── fig 14: per-task stitching effect on CrossView ─────────────────────────────
def fig_crossview_pertask():
    legs = [(b, l) for b, l in cv_legs() if l.get("per_task")]
    if not legs:
        return placeholder("fig14_crossview_pertask.png",
                           "CrossView per-task stitching effect", "no CrossView rows on disk")
    tasks = sorted(legs[0][1]["per_task"], key=lambda t: legs[0][1]["per_task"][t]["delta"],
                   reverse=True)
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.26, 0.34, 0.68, 0.40])
    H = 0.34
    for ti, t in enumerate(tasks):
        y0 = len(tasks) - 1 - ti
        for bi, (backend, leg) in enumerate(legs):
            d = leg["per_task"][t]
            y = y0 + (0.5 - bi) * H
            v = d["delta"]
            ax.barh([y], [v], height=H * 0.86, color=(POS if v >= 0 else NEG),
                    alpha=1.0 if bi == 0 else 0.55)
            star = " ★" if d.get("holm_significant") else ""
            ptxt = "p<0.001" if d["p"] < 0.001 else f"p={d['p']:.3f}"
            # every label sits to the RIGHT of its bar end (negative bars label
            # just past zero) so nothing collides with the task names
            ax.text(max(v, 0) + 0.4, y,
                    f"{SHORT_BACKEND.get(backend, backend)}  {v:+.2f}  ({ptxt}, n={d['n']}){star}",
                    va="center", ha="left", fontsize=9, color=INK2)
    ax.axvline(0, color=INK, linewidth=1)
    ax.set_yticks(range(len(tasks)))
    ax.set_yticklabels([CV_TASK_PRETTY.get(t, t) for t in tasks[::-1]],
                       fontsize=10, color=INK2)
    ax.set_xlim(-6, 35)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xlabel("change in accuracy from stitching (centralized − sequential), percentage points")
    import matplotlib.patches as mpatches
    ax.legend([mpatches.Patch(color=POS), mpatches.Patch(color=NEG)],
              ["stitching helps", "stitching hurts"], loc="upper right",
              frameon=False, fontsize=9.5, handlelength=1.2)
    # what a text-only guesser gets on each task, printed next to the task name —
    # both starred deltas move between two points that are below their own floor
    cvp = (S.get("crossview") or {}).get("pool", {}).get("task_floor", {}).get("by_task", {})
    if cvp:
        ax.set_yticklabels(
            [f"{CV_TASK_PRETTY.get(t, t)}\ntext-only floor {cvp[t]['acc']:.0f}%"
             for t in tasks[::-1]], fontsize=9.5, color=INK2)

    # the Qwen temporal jump is mostly the montage suppressing "Cannot be
    # determined" (option D on Temporal, a fixed string that is NEVER gold)
    qt = ((S.get("crossview") or {}).get("legs", {})
          .get("Qwen2.5-VL-7B-Instruct", {}).get("per_task", {})
          .get("CrossView-MEVA-Temporal", {}).get("pred_dist"))
    mech = ""
    if qt:
        nat_d = qt.get("cvbench_native", {}).get("D", 0)
        cen_d = qt.get("centralized", {}).get("D", 0)
        tot = sum(qt.get("cvbench_native", {}).values()) or 1
        mech = (f"\nMechanism check on the +19.51: Qwen answers “Cannot be determined” on "
                f"{nat_d}/{tot} temporal rows sequentially and\n{cen_d} stitched — most of the gain is the "
                "montage suppressing a refusal, not cross-camera fusion.")
    header(fig, "Per-task stitching effect — survives correction, below the floor",
           "centralized − sequential per CrossView-MEVA question type, paired question-level permutation,\n"
           "Holm-corrected across the 3 tasks within each backend. ★ = survives Holm at 0.05.")
    footer(fig, "Two deltas survive Holm where MVU-Eval had none — but NEITHER replicates across backends: each "
                "backend has\nexactly one significant task and the other backend moves the opposite way on it "
                "(ordering +5.72 vs −2.61;\ntemporal +19.51 vs −1.07). Both endpoints of both starred bars sit "
                "below that task's text-only floor." + mech)
    fig.savefig(os.path.join(OUT, "fig14_crossview_pertask.png"))
    plt.close(fig)


# ── fig 15: does the number of cameras change the answer? ──────────────────────
def fig_crossview_views():
    cv = S.get("crossview") or {}
    legs = [(b, l) for b, l in cv_legs() if l.get("by_views")]
    if not legs:
        return placeholder("fig15_crossview_views.png", "CrossView view-count sweep",
                           "no CrossView rows on disk")
    mf = cv["pool"]["majority"]["acc"]
    fig = plt.figure(**FIG_KW)
    MIN_N = 20   # bins below this are decoding noise (K=3 has 3 questions, K=11 has 6)
    for i, (backend, leg) in enumerate(legs[:2]):
        ax = fig.add_axes([0.07 + i * 0.49, 0.23, 0.39, 0.47])
        bins = [(int(k), v) for k, v in leg["by_views"].items() if v["n_q"] >= MIN_N]
        bins.sort()
        xs = [k for k, _ in bins]
        for key, label, color in ARMS:
            ys = [v["acc"].get(key) for _, v in bins]
            ax.plot(xs, ys, "-o", color=color, linewidth=2, markersize=5,
                    label=label if i == 0 else None)
        # the floor is NOT flat across bins (K=12 is 45.5): a single horizontal
        # line makes four arm x bin points look like they clear it when they do not
        fbv = cv.get("floor_by_views") or {}
        ax.step(xs + [xs[-1] + 0.5], [fbv[str(k)]["acc"] for k in xs] + [fbv[str(xs[-1])]["acc"]],
                where="mid", color=NEG, linestyle=(0, (1, 2)), linewidth=1.6,
                label="always-A floor, per bin" if i == 0 else None)
        trunc = [k for k, v in bins if v["truncated_from_more"]]
        if trunc:
            ax.axvspan(min(trunc) - 0.45, max(xs) + 0.45, color=GRID, alpha=0.55, zorder=0)
        for k, v in bins:   # rotated: the 12 and 13 bins are one unit apart
            ax.text(k, 2.5, f"n={v['n_q']}", ha="center", va="bottom", fontsize=8,
                    color=MUTED, rotation=90)
        style(ax, ymax=52)
        ax.set_xlabel("videos actually delivered to the model")
        if i == 0:
            ax.set_ylabel("accuracy, percent")
        ax.set_title(SHORT_BACKEND.get(backend, backend), fontsize=11, color=INK2, pad=8)
    fig.legend(loc="upper left", bbox_to_anchor=(0.07, 0.80), ncol=4, frameon=False,
               fontsize=9.5, handlelength=1.6)
    header(fig, "Does it matter how many cameras there are?",
           "Accuracy by the number of videos actually fed, CrossView-MEVA. Bins with fewer than "
           f"{MIN_N} questions are dropped\n(K=3 has 3, K=11 has 6). Dotted red = the always-A floor "
           "COMPUTED PER BIN (it is not flat — K=12 sits at 45.5).")
    n_tr = cv["census"]["truncated_by_cap"]
    footer(fig, "No arm has a camera-count cliff. On InternVL3 the arms cross — sequential leads at 2 cameras, "
                "stitching\nfrom 5 up — but that crossing is InternVL3-only: Qwen stitching leads in every bin. "
                f"The 13-video bin is\nNOT the richest condition: {n_tr} of its questions were truncated from "
                "14–16 cameras by the 13-slot cap.\nThe July-8 chart this replaces (\"65% at 2 → 0% at 5\") was "
                "n=17 and n=6 on a 60-question cap-4 subset.")
    fig.savefig(os.path.join(OUT, "fig15_crossview_views.png"))
    plt.close(fig)


# ── fig 16: the budget is unmatched here too — in the opposite direction ───────
def fig_crossview_budget():
    legs = [(b, l) for b, l in cv_legs() if l.get("tokens", {}).get("video_by_views")]
    if not legs:
        return placeholder("fig16_crossview_budget.png", "CrossView token budgets",
                           "no CrossView rows on disk")
    fig = plt.figure(**FIG_KW)
    for i, (backend, leg) in enumerate(legs[:2]):
        ax = fig.add_axes([0.08 + i * 0.48, 0.23, 0.37, 0.47])
        tv = leg["tokens"]["video_by_views"]
        counts = {k: v["n_q"] for k, v in leg["by_views"].items()}
        xs = sorted((int(k) for k in tv.get("cvbench_native", {}) if counts.get(k, 0) >= 20))
        for key, label, color in ARMS:
            if key == "per_stream":
                continue   # identical to sequential by construction, same frames
            ys = [tv[key][str(k)] for k in xs]
            ax.plot(xs, ys, "-o", color=color, linewidth=2, markersize=5,
                    label=label if i == 0 else None)
        ax.set_xlabel("videos per question")
        if i == 0:
            ax.set_ylabel("median visual tokens per question")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(length=0)
        ax.set_ylim(0, 40000)
        r = leg["tokens"]["over_native_mean_of_ratios"].get("centralized")
        ax.set_title(f"{SHORT_BACKEND.get(backend, backend)} — stitching carries {r:.2f}× "
                     "the tokens", fontsize=10.5, color=INK2, pad=8)
    fig.legend(loc="upper left", bbox_to_anchor=(0.08, 0.80), ncol=2, frameon=False,
               fontsize=9.5, handlelength=1.6)
    header(fig, "The unmatched budget works AGAINST stitching",
           "Measured visual tokens from the result rows, not the configs. Ratios below are the mean of the\n"
           "per-question ratio; by ratio-of-means InternVL3 is 0.11 — same quantity, two conventions.")
    footer(fig, "InternVL3 tiles the montage to a FLAT 2,048 visual tokens whether it is showing 2 cameras or 13,\n"
                "while sequential grows to 26,624 — so the stitched arm wins that leg while starved of tokens.\n"
                "The confound therefore does NOT explain the win away: on Qwen, where the budgets ARE matched\n"
                "(0.99×), stitching wins by MORE (+6.15, p<0.001) than on token-starved InternVL3 (+2.64).")
    fig.savefig(os.path.join(OUT, "fig16_crossview_budget.png"))
    plt.close(fig)


# ── fig 17: what CrossView can and cannot answer ──────────────────────────────
def fig_crossview_coverage():
    cv = S.get("crossview") or {}
    cov = cv.get("coverage")
    if not cov:
        return placeholder("fig17_crossview_coverage.png",
                           "CrossView coverage of the deck", "no CrossView section on disk")
    MARK = {"yes": ("✓", GREEN), "n/a": ("—", MUTED),
            "not run": ("✗", NEG), "blocked": ("✗", NEG)}
    fig = plt.figure(figsize=(10, 6.4), dpi=150)
    header(fig, "Which of these slides CrossView can answer",
           "Every question in this deck, and whether the CrossView-MEVA pool has the run behind it.\n"
           "The crosses are launch decisions, not missing plots.")
    y = 0.80
    for row in cov:
        sym, color = MARK.get(row["status"], ("?", MUTED))
        note = wrap(row["note"], 66)
        fig.text(0.055, y, sym, fontsize=13, color=color, fontweight="bold", va="top")
        fig.text(0.095, y, row["question"], fontsize=11, color=INK, va="top",
                 fontweight="bold" if row["status"] == "yes" else "normal")
        fig.text(0.44, y, note, fontsize=8.8, color=INK2, va="top")
        # row pitch follows the wrapped note, or a 3-line note eats the next row
        y -= 0.048 + 0.019 * note.count("\n")
    n_yes = sum(1 for r in cov if r["status"] == "yes")
    n_run = sum(1 for r in cov if r["status"] in ("not run", "blocked"))
    footer(fig, f"{n_yes} of {len(cov)} deck questions now have CrossView numbers. {n_run} are unanswered because that arm "
                "was never pointed at this\ndataset — the blind arm is the one that unblocks three of them at once, and it "
                "is the cheapest run on the board.")
    fig.savefig(os.path.join(OUT, "fig17_crossview_coverage.png"))
    plt.close(fig)


# ══ status panels for the 08-04 meeting asks (figs 18-19) ══════════════════════
# ── fig 18: which experiments have all three datasets ─────────────────────────
def fig_coverage_matrix():
    cm = S.get("coverage_matrix")
    if not cm:
        return placeholder("fig18_coverage_matrix.png",
                           "Three datasets side by side", "no coverage matrix in slide_stats")
    ds = [d for d in cm["datasets"] if d in DECK_DATASETS]
    rows = [{**r, "by_dataset": {d: r["by_dataset"][d] for d in ds},
             "n_datasets": sum(1 for d in ds if r["by_dataset"][d])}
            for r in cm["rows"]]
    fig = plt.figure(figsize=(10, 5.6), dpi=150)
    ax = fig.add_axes([0.42, 0.20, 0.55, 0.50])
    for j, d in enumerate(ds):
        for i, r in enumerate(rows):
            y = len(rows) - 1 - i
            n = r["by_dataset"][d]
            ax.add_patch(plt.Rectangle((j - 0.46, y - 0.42), 0.92, 0.84,
                                       facecolor=("#e7f2e7" if n else "#fbecec"),
                                       edgecolor=BASE, linewidth=0.8))
            ax.text(j, y + 0.08, "✓" if n else "✗", ha="center", va="center",
                    fontsize=15, color=(GREEN if n else NEG), fontweight="bold")
            ax.text(j, y - 0.24, f"{n:,} rows" if n else "not run", ha="center",
                    va="center", fontsize=8.5, color=(INK2 if n else NEG))
    ax.set_xlim(-0.5, len(ds) - 0.5)
    ax.set_ylim(-0.5, len(rows) - 0.5)
    ax.set_xticks(range(len(ds)))
    ax.set_xticklabels(ds, fontsize=10.5, color=INK)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([wrap(r["family"], 34) for r in rows][::-1],
                       fontsize=9.5, color=INK2)
    ax.xaxis.set_ticks_position("top")
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    complete = sum(1 for r in rows if r["n_datasets"] == len(ds))
    header(fig, "“Plot the datasets side by side for each experiment”",
           "The 08-04 meeting requirement, measured against the result rows on disk — not against "
           "what any\ndoc claims. A tick means that experiment actually ran on that dataset.")
    footer(fig, f"{complete} of {len(rows)} experiment families cover both datasets. Every chart in "
                "the deck beyond the arrangement row\nis therefore MVU-Eval only, because the CrossView rows do "
                "not exist. The two cheapest gaps are the blind\narm and the right-camera ablation on CrossView — "
                "both asked for by name in the meeting.")
    fig.savefig(os.path.join(OUT, "fig18_coverage_matrix.png"))
    plt.close(fig)


# ── fig 19: clarify lucky guessing, all three datasets ────────────────────────
def fig_lucky_guessing():
    legs = S["arrangement"].get("legs", {})
    pools = S["arrangement"].get("pools", {})
    order = [k for k in DECK_POOLS if k in pools]
    if not order or "task_floor" not in pools[order[0]]:
        return placeholder("fig19_lucky_guessing.png", "Clarify lucky guessing",
                           "no task_floor in slide_stats")
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.07, 0.22, 0.88, 0.48])
    W = 0.3
    for i, pk in enumerate(order):
        p = pools[pk]
        best = max((a["acc"] for k, leg in legs.items() if leg["pool"] == pk
                    for a in leg["arms"].values() if a), default=0)
        vals = [("best measured arm", best, SEQ),
                ("always the pool's\nmost common letter", p["majority"]["acc"], "#9a9892"),
                ("most common letter PER TASK\n(text only, leave-one-out)",
                 p["task_floor"]["acc"], NEG)]
        for j, (lab, v, c) in enumerate(vals):
            x = i + (j - 1) * (W + 0.02)
            ax.bar([x], [v], width=W, color=c, label=lab if i == 0 else None)
            ax.text(x, v + 0.8, f"{v:.1f}", ha="center", va="bottom", fontsize=10, color=INK)
        gap = p["task_floor"]["acc"] - best
        ax.text(i, max(best, p["task_floor"]["acc"]) + 6.5,
                f"{'−' if gap > 0 else '+'}{abs(gap):.1f}", ha="center", fontsize=12,
                color=(NEG if gap > 0 else GREEN), fontweight="bold")
        ax.hlines(p["chance"], i - 0.47, i + 0.47, color=MUTED,
                  linestyle=(0, (4, 3)), linewidth=1.2)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f"{pools[k]['label']}\n({pools[k]['modality']}, n={pools[k]['n']:,})"
                        for k in order], fontsize=10, color=INK2)
    style(ax, ymax=72)
    ax.set_ylabel("accuracy, percent")
    ax.legend(loc="upper left", bbox_to_anchor=(-0.01, 1.26), ncol=3, frameon=False,
              fontsize=9.5, handlelength=1.4)
    fails = [(pools[k]["label"], pools[k]["task_floor"]["acc"] - max(
        (a["acc"] for kk, leg in legs.items() if leg["pool"] == k
         for a in leg["arms"].values() if a), default=0)) for k in order]
    losers = [f"{lab} by {g:.1f}" for lab, g in fails if g > 0]
    over = max((pools[k]["task_floor"]["overfit"] for k in order), default=0)
    header(fig, "Clarify lucky guessing",
           "How much of each score a guesser gets for free. The red bar reads ONLY the question's task type and\n"
           "answers that task's most common letter — no images, no model. Dashed grey = random guessing.")
    footer(fig, ("The red bar is LEAVE-ONE-OUT: each question is scored with the modal letter computed from the "
                 "OTHER\nquestions, so the rule is not fitted on the answer it is graded against. That correction "
                 f"matters — it removes\nup to {over:.1f} points of overfit on the pool with the fewest questions "
                 "per task.\n"
                 + (f"Only {', '.join(losers)} still loses to the guesser — there the arms rank harnesses, "
                    "not competence." if losers
                    else "Every dataset now clears the guesser.")))
    fig.savefig(os.path.join(OUT, "fig19_lucky_guessing.png"))
    plt.close(fig)


# ── fig 20: the reference deck's single-view slide, our MVU-Eval swapped in ───
def fig_singleview_merged():
    ref = S.get("reference_single_view")
    sv = S.get("single_view") or {}
    if not ref or not sv.get("n_q_complete"):
        return placeholder("fig20_singleview_merged.png",
                           "Right camera vs lucky guessing", "no single-view data")
    ours = {"dataset": "MVU-Eval", "backend": "InternVL3-8B", "n_q": sv["n_q_complete"],
            "sequential": sv["sequential_all_views"], "luck": sv["luck_best_of_k"],
            "best": sv["best"]}
    legs = []
    for leg in ref["legs"]:
        # swap in our measured run wherever we actually have one
        if leg["dataset"] == "MVU-Eval" and leg["backend"] == "InternVL3-8B":
            legs.append(ours)
        else:
            legs.append(dict(leg))

    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.07, 0.235, 0.88, 0.45])
    W = 0.26
    SERIES = [("sequential", "sequential, all views", INK),
              ("luck", "what lucky guessing alone gives", "#9a9892"),
              ("best", "best single view", GREEN)]
    for gi, leg in enumerate(legs):
        for si, (key, label, color) in enumerate(SERIES):
            x = gi + (si - 1) * (W + 0.02)
            ax.bar([x], [leg[key]], width=W, color=color,
                   label=label if gi == 0 else None)
            ax.text(x, leg[key] + 1.0, f"{leg[key]:.1f}", ha="center", va="bottom",
                    fontsize=9.5, color=INK)
        gain = leg["best"] - leg["luck"]
        ax.text(gi, leg["best"] + 7.5, f"+{gain:.1f} over luck", ha="center",
                fontsize=10.5, color=GREEN, fontweight="bold")
    ax.set_xticks(range(len(legs)))
    ax.set_xticklabels([f"{l['backend']}\n{l['dataset']}\nn={l['n_q']}"
                        for l in legs], fontsize=9.5, color=INK2)
    style(ax, ymax=95)
    ax.set_ylabel("accuracy, percent")
    ax.legend(loc="upper left", bbox_to_anchor=(-0.01, 1.26), ncol=3,
              frameon=False, fontsize=9.5, handlelength=1.5)
    header(fig, "Does picking the right camera beat lucky guessing?",
           "Only the single view containing the answer, against showing all views — restricted to the questions\n"
           "whose text does not name a view, because naming a view already does the picking.")
    footer(fig, f"On MVU-Eval the best single view scores {sv['best']:.1f} against a luck baseline of "
                f"{sv['luck_best_of_k']:.1f}, so the real gain is\n"
                f"+{sv['best'] - sv['luck_best_of_k']:.1f} — not the "
                f"+{sv['best'] - sv['sequential_all_views']:.1f} it looks like against sequential. Most of the "
                "apparent headroom is\nmax-of-K noise: run enough views and keep the best, and you climb even "
                "when no view is genuinely better.")
    fig.savefig(os.path.join(OUT, "fig20_singleview_merged.png"))
    plt.close(fig)


# ── fig 21: the arrangement chart, his All-Angles + our two video datasets ────
def fig_arrangement_merged():
    ref = S.get("reference_arrangement")
    legs = ordered_legs()
    if not ref or not legs:
        return placeholder("fig21_arrangement_merged.png",
                           "Arrangement, all datasets", "no reference arrangement data")
    groups = [{**l, "label": l["dataset"],
               "sub": f"n={l['n_q']:,}" if l.get("n_q") else ""}
              for l in ref["legs"]]
    # MVU-Eval enters as its 128 SYNCHRONIZED questions, not the full 1,824:
    # every CrossView question is a synchronized rig, so the full pool would
    # compare it against 1,696 unrelated-clip questions with no cross-camera
    # structure. This is the apples-to-apples slice.
    s128 = S.get("sync128_legs") or {}
    for backend in ("InternVL3-8B", "Qwen2.5-VL-7B-Instruct"):
        arms = (s128.get("legs") or {}).get(backend)
        if arms:
            groups.append({
                "dataset": "MVU-Eval", "backend": backend, "label": "MVU-Eval",
                "n_q": s128["n_q"], "chance": s128["chance"],
                "sub": f"n={s128['n_q']}",
                **{k: (arms.get(k) or {}).get("acc") for k in
                   ("cvbench_native", "centralized", "per_stream")}})
    for _, leg in legs:
        if leg["pool"] != "meva1033":
            continue
        groups.append({
            "dataset": leg["label"], "backend": leg["backend"],
            "n_q": leg["n_pool"], "label": leg["label"], "chance": leg["chance"],
            "sub": f"n={leg['n_pool']:,}",
            **{k: (leg["arms"].get(k) or {}).get("acc") for k in
               ("cvbench_native", "centralized", "per_stream")}})

    fig = plt.figure(figsize=(11.5, 5.6), dpi=150)
    ax = fig.add_axes([0.06, 0.26, 0.92, 0.44])
    W = 0.26
    for gi, g in enumerate(groups):
        for ai, (key, label, color) in enumerate(ARMS):
            v = g.get(key)
            if v is None:
                continue
            x = gi + (ai - 1) * (W + 0.015)
            ax.bar([x], [v], width=W, color=color)
            ax.text(x, v + 0.8, f"{v:.1f}", ha="center", va="bottom",
                    fontsize=8.5, color=INK)
        # one clean segment inside this group's own x-extent: a shared axhline
        # bleeds across neighbouring groups whose chance level is different
        ax.hlines(g["chance"], gi - 0.44, gi + 0.44, color=MUTED,
                  linestyle=(0, (5, 4)), linewidth=1.4)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([f"{SHORT_BACKEND.get(g['backend'], g['backend'])}\n"
                        f"{g['label']}\n{g['sub']}" for g in groups],
                       fontsize=9, color=INK2)
    style(ax, ymax=64)
    ax.set_ylabel("accuracy, percent")
    import matplotlib.lines as mlines
    import matplotlib.patches as mpatches
    h = [mpatches.Patch(facecolor=c) for _, _, c in ARMS]
    l = [lab for _, lab, _ in ARMS]
    h.append(mlines.Line2D([], [], color=MUTED, linestyle=(0, (5, 4)), linewidth=1.4))
    l.append("random guessing")
    ax.legend(h, l, loc="upper left", bbox_to_anchor=(-0.005, 1.28), ncol=4,
              frameon=False, fontsize=9.5, handlelength=1.8)
    header(fig, "Does the arrangement matter? — synchronized questions only",
           "MVU-Eval enters as its 128 synchronized-rig questions, not the full 1,824, so every group here is "
           "a genuine\nmulti-camera rig. 4 passes per question, question-level permutation tests.")
    footer(fig, "Restricted to synchronized rigs, InternVL3 puts STITCHING first on both video datasets "
                "(46.3 on MVU-Eval,\n37.8 on CrossView) — the sequential-first result holds only on the full "
                "MVU pool, three quarters of which is\nunrelated clips with no cross-camera structure. "
                "Decentralized still never wins.\nQwen keeps sequential first on MVU-Eval by 1.2 points, so the "
                "flip is suggestive on one backend, not settled.")
    fig.savefig(os.path.join(OUT, "fig21_arrangement_merged.png"))
    plt.close(fig)


# ── fig 22: frame budget vs accuracy, overall and per question type ──────────
# 8 CVD-safe hues for the task lines; Overall is drawn in near-black on top.
TASK_HUES = ["#e06c2b", "#1b9e77", "#4a3aa7", "#c2185b",
             "#0e7fa8", "#8a6d1f", "#5a5a55", "#b5651d"]
PRETTY_MVU = {"MVU-Counting": "Counting", "MVU-OR": "Object recognition",
              "MVU-SU": "Spatial understanding", "MVU-ICL": "In-context learning",
              "MVU-RAG": "Retrieval", "MVU-KIR": "Knowledge reasoning",
              "MVU-Comparison": "Comparison", "MVU-TR": "Temporal reasoning"}


def fig_frame_budget_tasks():
    # x is frames PER VIDEO, the axis the reference chart uses. Only two budgets
    # have ever been run that way on MVU-Eval; the fixed-32-total protocol is not
    # a per-video setting (it splits 32 across however many cameras there are),
    # so it does not belong on this axis at all.
    try:
        pts = [("8 per video", 8, S["arrangement"]["mvu_full"]["cvbench_native"]),
               ("32 per video", 32, S["parity32pv"]["cvbench_native"])]
    except KeyError:
        return placeholder("fig22_framebudget_tasks.png",
                           "Frame budget vs accuracy", "budget arms not all present")
    if not all(a for _, _, a in pts):
        return placeholder("fig22_framebudget_tasks.png",
                           "Frame budget vs accuracy", "budget arms not all present")
    tasks = sorted(pts[0][2]["by_task"])
    xs = list(range(len(pts)))
    # colour only the tasks that actually move; the rest stay as quiet grey
    # context so the eye lands on the story instead of nine competing lines
    moved = sorted(tasks, key=lambda t: abs(pts[-1][2]["by_task"][t]["acc"]
                                            - pts[0][2]["by_task"][t]["acc"]),
                   reverse=True)[:3]

    fig = plt.figure(figsize=(10.5, 5.6), dpi=150)
    ax = fig.add_axes([0.07, 0.28, 0.63, 0.48])

    labels = []
    for t in tasks:
        ys = [a["by_task"][t]["acc"] for _, _, a in pts]
        if t in moved:
            c = TASK_HUES[moved.index(t)]
            ax.plot(xs, ys, "-o", color=c, linewidth=2.2, markersize=5, zorder=3)
            d = ys[-1] - ys[0]
            labels.append([ys[-1], c,
                           f"{PRETTY_MVU.get(t, t)}   {ys[-1]:.1f}  ({d:+.1f})", False])
        else:
            ax.plot(xs, ys, "-", color="#c9c8c2", linewidth=1.4, zorder=1)

    ys = [a["acc"] for _, _, a in pts]
    n = pts[0][2]["n_q"]
    se = [100 * ((y / 100) * (1 - y / 100) / n) ** 0.5 for y in ys]
    ax.fill_between(xs, [y - s for y, s in zip(ys, se)],
                    [y + s for y, s in zip(ys, se)], color=INK, alpha=0.12,
                    linewidth=0, zorder=3)
    ax.plot(xs, ys, "-o", color=INK, linewidth=3.2, markersize=7, zorder=4)
    # the final point's value lives in the right-hand label, not above the marker,
    # where it would sit on top of the label column
    for x, y in list(zip(xs, ys))[:-1]:
        ax.text(x, y + 2.0, f"{y:.1f}", ha="center", fontsize=10.5,
                color=INK, fontweight="bold", zorder=5)
    labels.append([ys[-1], INK,
                   f"Overall   {ys[-1]:.1f}  ({ys[-1] - ys[0]:+.1f})", True])

    labels.sort(key=lambda r: r[0])
    for i in range(1, len(labels)):
        if labels[i][0] - labels[i - 1][0] < 3.2:
            labels[i][0] = labels[i - 1][0] + 3.2
    for y, c, name, bold in labels:
        ax.text(len(pts) - 1 + 0.10, y, name, color=c, fontsize=11, va="center",
                ha="left", fontweight="bold" if bold else "normal")

    ax.set_xlim(-0.10, len(pts) - 1 + 0.06)
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{f}" for _, f, _ in pts], fontsize=13, color=INK)
    # second row under the ticks: what that budget actually costs per question
    for x, (_, f, a) in zip(xs, pts):
        ax.annotate(f"{f * S['frame_budget']['mean_k']:.0f} frames/question",
                    xy=(x, 0), xycoords=("data", "axes fraction"),
                    xytext=(0, -34), textcoords="offset points",
                    ha="center", fontsize=9.5, color=MUTED)
    ax.set_ylim(28, 78)
    style(ax)
    ax.set_ylabel("accuracy (%)")
    header(fig, "More frames does not buy accuracy",
           "MVU-Eval, InternVL3-8B, sequential arm. X axis is frames per VIDEO; a question carries several.\n"
           "Grey lines are the five task types that barely move.")
    footer(fig, "Quadrupling the per-video budget costs 2.7 points overall. Only 8 and 32 frames per video "
                "have been run\non this benchmark — 16, 64 and 128 do not exist yet, and at 13 cameras a "
                "64-frame budget would not fit the\ncontext window.")
    fig.savefig(os.path.join(OUT, "fig22_framebudget_tasks.png"))
    plt.close(fig)


# ── fig 23: centralized − sequential per question type, both datasets ────────
def fig_pertask_merged():
    mvu_legs = S.get("per_task_legs") or {}
    cv_legs = (S.get("crossview") or {}).get("legs") or {}
    if not mvu_legs:
        return placeholder("fig23_pertask_merged.png",
                           "Per-task stitching effect", "per_task_legs missing")
    BACKENDS = [("InternVL3-8B", CEN), ("Qwen2.5-VL-7B-Instruct", "#9a9892")]
    rows = []
    order = sorted(S["per_task"], key=lambda t: -S["per_task"][t]["delta"])
    for t in order:
        rows.append(("MVU-Eval", PRETTY_MVU.get(t, t),
                     {b: mvu_legs.get(b, {}).get(t) for b, _ in BACKENDS}))
    cv_order = sorted(next(iter(cv_legs.values()))["per_task"],
                      key=lambda t: -cv_legs["InternVL3-8B"]["per_task"][t]["delta"]) \
        if cv_legs else []
    for t in cv_order:
        rows.append(("CrossView-MEVA", t.replace("CrossView-MEVA-", ""),
                     {b: cv_legs.get(b, {}).get("per_task", {}).get(t) for b, _ in BACKENDS}))

    fig = plt.figure(figsize=(11, 7.2), dpi=150)
    ax = fig.add_axes([0.26, 0.20, 0.62, 0.58])
    H = 0.36
    for ri, (ds, name, per_b) in enumerate(rows):
        y0 = len(rows) - 1 - ri
        for bi, (b, color) in enumerate(BACKENDS):
            d = per_b.get(b)
            if not d:
                continue
            y = y0 + (0.5 - bi) * H
            v = d["delta"]
            ax.barh([y], [v], height=H * 0.84, color=color)
            star = " ★" if d.get("holm_significant") else ""
            ax.text(v + (0.5 if v >= 0 else -0.5), y, f"{v:+.2f}{star}",
                    va="center", ha=("left" if v >= 0 else "right"),
                    fontsize=9, color=INK2)
    ax.axvline(0, color=INK, linewidth=1)
    # separate the two datasets
    split = sum(1 for r in rows if r[0] == "MVU-Eval")
    ax.axhline(len(rows) - split - 0.5, color=BASE, linewidth=1)
    tr = ax.get_yaxis_transform()
    ax.text(-0.30, len(rows) - split / 2 - 0.5, "MVU-Eval\n1,824 q", transform=tr,
            fontsize=10.5, color=INK, ha="center", va="center", fontweight="bold")
    ax.text(-0.30, (len(rows) - split) / 2 - 0.5, "CrossView\n1,033 q", transform=tr,
            fontsize=10.5, color=INK, ha="center", va="center", fontweight="bold")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[1] for r in rows][::-1], fontsize=10, color=INK2)
    ax.set_xlim(-25, 25)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xlabel("change in accuracy from stitching (centralized − sequential), percentage points",
                  fontsize=10, labelpad=8)
    import matplotlib.patches as mpatches
    ax.legend([mpatches.Patch(color=c) for _, c in BACKENDS],
              [SHORT_BACKEND.get(b, b) for b, _ in BACKENDS],
              loc="upper left", bbox_to_anchor=(-0.005, 1.09), ncol=2,
              frameon=False, fontsize=10, handlelength=1.4)
    header(fig, "Where stitching helps, and where it hurts",
           "centralized − sequential per question type. ★ = survives Holm correction for multiple tests.")
    footer(fig, "The reference deck's one survivor was Counting at +6.83. Here Counting is the WORST cell on "
                "the board:\n−2.86 on InternVL3 and −20.70 on Qwen, the latter significant. Stitching is broadly "
                "harmful to Qwen on\nMVU-Eval — 6 of its 8 task deltas are significantly negative.\n"
                "Every surviving POSITIVE effect is on CrossView, where the cameras are genuinely synchronized.")
    fig.savefig(os.path.join(OUT, "fig23_pertask_merged.png"))
    plt.close(fig)


# ── fig 24: what the three datasets are and why they exist ──────────────────
def fig_dataset_intro():
    P = S["arrangement"]["pools"]
    cv = (S.get("crossview") or {}).get("census", {})
    cols = [
        {"name": "All-Angles Bench", "tag": "still images, 2–5 views",
         "why": "Can a model reason about ONE scene photographed from several "
                "angles at the same instant? Correspondence, relative position, "
                "and counting without double-counting the same person.",
         "rows": [("Media", "still frames"),
                  ("Questions", "2,132  (1,962 Ego-Exo4D + 170 EgoHumans)"),
                  ("Views per question", "2–5, mean 2.4"),
                  ("Question types", "6 — attribute ID, camera pose, counting,\n"
                                     "manipulation, relative direction/distance"),
                  ("Cameras aligned?", "same moment, different angles"),
                  ("Answer options", "3"),
                  ("What we ran", "all 2,132")]},
        {"name": "MVU-Eval", "tag": "video, 2–13 clips",
         "why": "Can a model answer over SEVERAL VIDEOS at once? Mostly unrelated "
                "clips rather than one scene, so it tests retrieval and comparison "
                "across sources more than cross-camera fusion.",
         "rows": [("Media", "video clips"),
                  ("Questions", f"{P['mvu_full']['n']:,}"),
                  ("Views per question", "2–13, mean 4.7"),
                  ("Question types", "8 — temporal, retrieval, knowledge, counting,\n"
                                     "spatial, comparison, object recog., in-context"),
                  ("Cameras aligned?", "only 128 (7%) are synchronized rigs;\n"
                                       "the rest are unrelated clips"),
                  ("Answer options", "2–11 (mostly 4)"),
                  ("What we ran", "all 1,824, both backends")]},
        {"name": "CrossView-MEVA", "tag": "video, 2–13 cameras",
         "why": "Can a model follow events across OVERLAPPING FIXED CAMERAS "
                "watching one site? When something happened, in what order, and "
                "from which viewpoint.",
         "rows": [("Media", "surveillance video"),
                  ("Questions", f"{P['meva1033']['n']:,} of 2,481 in the local export"),
                  ("Views per question", "2–13, mean 9.1 (capped from up to 16)"),
                  ("Question types", "3 — event ordering, spatial, temporal"),
                  ("Cameras aligned?", "every question is one site in one\n"
                                       "5-minute window — fully synchronized"),
                  ("Answer options", "4"),
                  ("What we ran", "all 1,033, both backends")]},
    ]
    fig = plt.figure(figsize=(13, 7.4), dpi=150)
    header(fig, "Three benchmarks, three degrees of “multi-camera”",
           "What each dataset is for. They differ mainly in how much the cameras actually share a scene — "
           "which is\nexactly what our arrangement results turn on.")
    W, x0, gap = 0.293, 0.045, 0.015
    for ci, c in enumerate(cols):
        x = x0 + ci * (W + gap)
        fig.patches.append(plt.Rectangle((x, 0.115), W, 0.70, transform=fig.transFigure,
                                         facecolor="#f6f5f1", edgecolor=GRID, linewidth=1))
        fig.text(x + 0.015, 0.775, c["name"], fontsize=14, fontweight="bold", color=INK)
        fig.text(x + 0.015, 0.745, c["tag"], fontsize=10, color=CEN)
        # 44 chars is what actually fits this card at 9.5pt; 52 overflows the edge
        fig.text(x + 0.015, 0.715, wrap(c["why"], 44), fontsize=9.5, color=INK2, va="top")
        y = 0.585
        for k, v in c["rows"]:
            fig.text(x + 0.015, y, k.upper(), fontsize=7.6, color=MUTED,
                     fontweight="bold", va="top")
            fig.text(x + 0.015, y - 0.026, v, fontsize=9.3, color=INK, va="top")
            y -= 0.031 + 0.026 * (1 + v.count("\n"))
    footer(fig, "Read left to right as the cameras drifting apart: All-Angles is one instant from several angles, "
                "CrossView is one\nsite over one window, MVU-Eval is mostly unrelated clips. Stitching the views "
                "into a single frame helps on the\nfirst two and hurts on the third — the arrangement result "
                "tracks this axis, not the model.")
    fig.savefig(os.path.join(OUT, "fig24_dataset_intro.png"))
    plt.close(fig)


if __name__ == "__main__":
    fig_dataset_intro()
    fig_pertask_merged()
    fig_frame_budget_tasks()
    fig_arrangement_merged()
    fig_singleview_merged()
    fig_coverage_matrix(); fig_lucky_guessing()
    fig_arrangement(); fig_sync(); fig_pertask(); fig_clip(); fig_budget()
    fig_blind(); fig_singleview(); fig_defects(); fig_headroom()
    fig_singleview_tasks(); fig_frame_budget(); fig_task_relevance()
    fig_crossview_arms(); fig_crossview_pertask(); fig_crossview_views()
    fig_crossview_budget(); fig_crossview_coverage()
    print("wrote", OUT, ":", sorted(os.listdir(OUT)))
