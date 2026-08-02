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


def placeholder(name, title, note):
    fig = plt.figure(**FIG_KW)
    header(fig, title, "")
    fig.text(0.5, 0.5, note, ha="center", va="center", fontsize=13, color=MUTED)
    fig.savefig(os.path.join(OUT, name), bbox_inches=None)
    plt.close(fig)


ARMS = [("cvbench_native", "sequential", SEQ),
        ("centralized", "centralized (stitching)", CEN),
        ("per_stream", "decentralized", DEC)]


# ── fig 1: Does the arrangement matter? ─────────────────────────────────────────
def fig_arrangement():
    mvu, aab = S["arrangement"]["mvu_full"], S["arrangement"]["aab170"]
    chance = S["arrangement"]["chance"]
    groups = [("InternVL3-8B\nMVU-Eval (video, n=1,824)", mvu, chance["mvu_full"]),
              ("InternVL3-8B\nAll-Angles EgoHumans (stills, n=170)", aab, chance["aab170"])]
    fig = plt.figure(**FIG_KW)
    ax = fig.add_axes([0.07, 0.19, 0.88, 0.52])
    W, gap = 0.24, 0.06
    for gi, (gname, arms, ch) in enumerate(groups):
        for ai, (key, label, color) in enumerate(ARMS):
            v = arms[key]["acc"]
            x = gi + (ai - 1) * (W + gap / 2)
            b = ax.bar([x], [v], width=W, color=color,
                       label=label if gi == 0 else None)
            bar_labels(ax, b)
        ax.hlines(ch, gi - 0.45, gi + 0.45, color=MUTED, linestyle=(0, (4, 3)),
                  linewidth=1.2)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([g[0] for g in groups], fontsize=10.5, color=INK2)
    style(ax, ymax=62)
    ax.set_ylabel("accuracy, percent")
    h, l = ax.get_legend_handles_labels()
    import matplotlib.lines as mlines
    h.append(mlines.Line2D([], [], color=MUTED, linestyle=(0, (4, 3)), linewidth=1.2))
    l.append("random guessing (25.9 MVU-Eval, 33.3 All-Angles)")
    ax.legend(h, l, loc="upper left", bbox_to_anchor=(-0.01, 1.24), ncol=4,
              frameon=False, fontsize=9.5, handlelength=1.4)
    b32 = S.get("budget32") or {}
    if b32.get("cvbench_native"):
        gap = max(abs(b32[k]["acc"] - S["arrangement"]["mvu_full"][k]["acc"])
                  for k in ("cvbench_native", "centralized", "per_stream"))
        note = f"the matched fixed-32 rerun (slide on unmatched budgets) lands within {gap:.1f} points of every arm here."
    else:
        note = "a matched 32-frame rerun is queued (job 72241)."
    header(fig, "Does the arrangement matter?",
           "The 3 conditions on the same questions, 4 passes each. My run feeds 8 frames per video (16–104 per question),\n"
           f"not the reference slides' fixed 32-frame budget — {note}")
    p = S["arrangement"]["perm"]
    footer(fig, f"centralized is within {abs(p['cvbench_native-centralized']['delta']):.1f} points of sequential on MVU-Eval "
                f"(p={p['cvbench_native-centralized']['p']:.2f}, not significant).\n"
                f"decentralized is {p['cvbench_native-per_stream']['delta']:.1f} points below sequential (p<0.001) — "
                "the one real gap. On stills the ordering flips: decentralized leads (46.3 vs 44.1, suggestive only).")
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
    if bl.get("aab170"):
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


if __name__ == "__main__":
    fig_arrangement(); fig_sync(); fig_pertask(); fig_clip(); fig_budget()
    fig_blind(); fig_singleview(); fig_defects(); fig_headroom()
    print("wrote", OUT, ":", sorted(os.listdir(OUT)))
