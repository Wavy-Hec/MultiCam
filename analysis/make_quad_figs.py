#!/usr/bin/env python3
"""The sponsor quad chart: per-task accuracy of the selection arms, and the
four figures that fit one 2x2 slide.

This answers the two things the collaborator asked for — "accuracy /
question-wise accuracy of the selection method" and "plots for the quad
chart" — from the rescored rows only, and cross-checks every cell it
computes against the numbers already on disk.

Stats (analysis/records/quad_stats.json):

  cells        per dataset x budget x arm, the pooled and per-task 4-pass
               accuracy with the std over the four per-pass accuracies
               (make_ladder_figs.acc_stats), ASSERTED equal to
               analysis/records/ladder_stats.json to 0.01
  blind        the matched-protocol no-video leg (direct answer, T=0.1,
               4 passes) pooled and per task, ASSERTED against the
               registry's 30.99 / 34.50 / 29.31
  paired_vs_fs per budget and arm, the per-question outcome against native
               uniform: win / tie / loss counts over ids (mean correctness
               over the four passes), mean delta, paired-t p, sign-test p
               and a 95% t-interval (make_ladder_figs.paired), pooled and
               per task
  question_wise at 96 frames, how many ids an arm gets right on 0/1/2/3/4
               passes, and the two exclusive counts per task: ids the arm
               gets right on all four passes and native gets wrong on all
               four, and the reverse

Figures (analysis/figs_deck/), each sized to stay legible inside one
quadrant of a slide:

  fig_quad_ladder.png    accuracy vs total frames per dataset, band = std
                         over passes, dashed neutral line = no-video floor
  fig_quad_pertask.png   per-task accuracy at 96 frames, grouped by arm,
                         neutral dash = the no-video floor for that task
  fig_quad_delta.png     paired delta vs native per task at 96 frames,
                         whisker = 95% CI, filled marker = paired-t p < 0.05
  fig_quad_selector.png  selector accuracy per task (segment coverage) from
                         analysis/records/selection_coverage.json, with both
                         keep-count-matched nulls that file carries — drawn
                         independently per camera, and this row's own picks
                         shifted together (the one to read on EgoExo, where a
                         hit counts on any camera and independent draws gain
                         spread the selector did not aim for); skipped with a
                         note when that file is not on disk

Usage (cvbench env, or plain python3 with numpy/scipy/matplotlib):
  python3 analysis/make_quad_figs.py
  python3 analysis/make_quad_figs.py --no-figs
"""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
from split_ladder_by_query import DATASETS, BUDGETS, BASELINE_METHOD  # noqa: E402
from make_ladder_figs import (  # noqa: E402
    load_rows, acc_stats, per_id, paired, short_task, style,
    ARM_COLOR, ARM_LABEL, ARM_ORDER, INK, INK2, RULE, SURFACE,
)

GENERATED = "2026-09-17"
FIGS = os.path.join(HERE, "figs_deck")
RECORDS = os.path.join(HERE, "records")
LADDER_STATS = os.path.join(RECORDS, "ladder_stats.json")
COVERAGE = os.path.join(RECORDS, "selection_coverage.json")
OUT_JSON = os.path.join(RECORDS, "quad_stats.json")
TOL = 0.01
HEAD = 96  # the budget the quad chart reports

# the matched-protocol blind legs: no video, direct answer, T=0.1, 4 passes.
# MVU's leg was never re-scored (registry: rescored=false) and so lives in
# bench/results/, not bench/results/rescored/ — the glob covers both.
BLIND = {
    "MVU-Eval": ("bench_mvueval_qa_internvl_t1iv_blind*.jsonl", 30.99),
    "CrossView-EgoExo": ("bench_crossview_egoexo500_internvl_bdd_shard*.jsonl", 34.50),
    "CrossView-MEVA": ("bench_crossview_meva1033_subset_internvl_mp4bdd_shard*.jsonl", 29.31),
}
BLIND_LABEL = "no video"
# panel width ratios follow the task count (MVU 8 : EgoExo 2 : MEVA 3)
DS_ORDER = ["MVU-Eval", "CrossView-EgoExo", "CrossView-MEVA"]
# panel titles: the narrow per-task panels have no room for the full names,
# which the suptitle and the deck caption carry anyway
DS_SHORT = {"MVU-Eval": "MVU-Eval", "CrossView-EgoExo": "EgoExo",
            "CrossView-MEVA": "MEVA"}


# --------------------------------------------------------------------------- #
# loading                                                                      #
# --------------------------------------------------------------------------- #
def blind_rows(pattern):
    """The blind leg's rows. Prefers bench/results/rescored/, falls back to
    bench/results/ for legs that were never re-scored."""
    paths = sorted(glob.glob(os.path.join(REPO, "bench", "results", "rescored", pattern)))
    where = "rescored"
    if not paths:
        paths = sorted(glob.glob(os.path.join(REPO, "bench", "results", pattern)))
        where = "raw (leg never rescored)"
    rows = []
    for p in paths:
        with open(p) as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    rows.append({k: r.get(k) for k in
                                 ("id", "pass_idx", "correct", "task_type",
                                  "prediction", "gold", "method")})
    return rows, [os.path.relpath(p, REPO) for p in paths], where


def pass_counts(rows):
    """{id: number of passes the arm got right}."""
    d = defaultdict(int)
    ids = set()
    for r in rows:
        ids.add(r["id"])
        if r["correct"]:
            d[r["id"]] += 1
    return {i: d.get(i, 0) for i in ids}


# --------------------------------------------------------------------------- #
# stats                                                                        #
# --------------------------------------------------------------------------- #
def cell_stats(rows, tasks):
    c = acc_stats(rows)
    c["per_task"] = {}
    for t in tasks:
        s = acc_stats([r for r in rows if r["task_type"] == t])
        if s:
            c["per_task"][t] = s
    return c


def win_tie_loss(a, b, ids):
    """Counts of ids where arm a's per-question mean beats / ties / trails b."""
    ids = [i for i in ids if i in a and i in b]
    win = sum(1 for i in ids if a[i] > b[i])
    loss = sum(1 for i in ids if a[i] < b[i])
    return {"win": win, "tie": len(ids) - win - loss, "loss": loss, "n": len(ids)}


def compute_dataset(ds, subset, stem, arms):
    recs = json.load(open(os.path.join(HERE, subset)))
    task = {r["id"]: r.get("task_type", "?") for r in recs}
    tasks = sorted(set(task.values()))
    task_n = {t: sum(1 for i in task if task[i] == t) for t in tasks}
    out = {"n": len(recs), "tasks": tasks, "task_n": task_n,
           "cells": {}, "paired_vs_fs": {}, "question_wise": {}}

    legs_by_budget = {}
    for B in BUDGETS:
        legs = {}
        for arm in ARM_ORDER:
            if arm not in arms:
                continue
            rows = load_rows(stem, arms[arm], B,
                             BASELINE_METHOD if arm == "fs" else None)
            if rows:
                legs[arm] = rows
        if not legs:
            continue
        legs_by_budget[B] = legs
        out["cells"][str(B)] = {arm: cell_stats(rows, tasks) for arm, rows in legs.items()}

        # (c) paired per-question outcome versus native uniform
        if "fs" in legs:
            pid = {arm: per_id(rows) for arm, rows in legs.items()}
            con = {}
            for arm in legs:
                if arm == "fs":
                    continue
                ids = [i for i in task if i in pid[arm] and i in pid["fs"]]
                entry = {"all": _pair_entry(pid[arm], pid["fs"], ids), "per_task": {}}
                for t in tasks:
                    sub = [i for i in ids if task[i] == t]
                    entry["per_task"][t] = _pair_entry(pid[arm], pid["fs"], sub)
                con[arm] = entry
            out["paired_vs_fs"][str(B)] = con

    # (d) question-wise histogram and the exclusive counts, at the head budget
    legs = legs_by_budget.get(HEAD, {})
    if legs:
        pc = {arm: pass_counts(rows) for arm, rows in legs.items()}
        qw = {}
        for arm, counts in pc.items():
            hist = {"all": _hist(counts, list(counts)),
                    "per_task": {t: _hist(counts, [i for i in counts if task.get(i) == t])
                                 for t in tasks}}
            if "fs" in pc and arm != "fs":
                fsc = pc["fs"]
                ids = [i for i in counts if i in fsc]
                hist["exclusive_vs_fs"] = {
                    "all": _exclusive(counts, fsc, ids),
                    "per_task": {t: _exclusive(counts, fsc, [i for i in ids if task.get(i) == t])
                                 for t in tasks}}
            qw[arm] = hist
        out["question_wise"][str(HEAD)] = qw
    return out


def _pair_entry(a, b, ids):
    p = paired(a, b, ids)
    e = dict(win_tie_loss(a, b, ids))
    if p:
        e.update({"delta": p["delta"], "t_p": p["t_p"], "sign_p": p["sign_p"],
                  "ci95": p["ci95"], "n_paired": p["n"]})
    return e


def _hist(counts, ids):
    h = [0, 0, 0, 0, 0]
    for i in ids:
        k = counts[i]
        if 0 <= k <= 4:
            h[k] += 1
    return h


def _exclusive(arm, fs, ids):
    return {"arm_all4_fs_all0": sum(1 for i in ids if arm[i] == 4 and fs[i] == 0),
            "fs_all4_arm_all0": sum(1 for i in ids if fs[i] == 4 and arm[i] == 0),
            "n": len(ids)}


def check_ladder(results, ladder):
    """Every cell this script computed against analysis/records/ladder_stats.json."""
    bad = []
    for ds, res in results.items():
        ref = ladder.get("results", {}).get(ds)
        if ref is None:
            bad.append(f"{ds}: absent from ladder_stats.json")
            continue
        for B, cells in res["cells"].items():
            rcells = ref.get("cells", {}).get(B, {})
            for arm, c in cells.items():
                rc = rcells.get(arm)
                if rc is None:
                    bad.append(f"{ds} B={B} {arm}: absent from ladder_stats.json")
                    continue
                for key in ("acc", "pass_std"):
                    if abs(c[key] - rc[key]) > TOL:
                        bad.append(f"{ds} B={B} {arm} {key}: {c[key]:.4f} vs {rc[key]:.4f}")
                if c["n_rows"] != rc["n_rows"] or c["n_ids"] != rc["n_ids"]:
                    bad.append(f"{ds} B={B} {arm} n: {c['n_rows']}/{c['n_ids']} "
                               f"vs {rc['n_rows']}/{rc['n_ids']}")
                for t, s in c["per_task"].items():
                    rs = rc.get("per_task", {}).get(t)
                    if rs is None:
                        bad.append(f"{ds} B={B} {arm} {t}: absent from ladder_stats.json")
                        continue
                    for key in ("acc", "pass_std"):
                        if abs(s[key] - rs[key]) > TOL:
                            bad.append(f"{ds} B={B} {arm} {short_task(t)} {key}: "
                                       f"{s[key]:.4f} vs {rs[key]:.4f}")
    return bad


# --------------------------------------------------------------------------- #
# figure helpers                                                               #
# --------------------------------------------------------------------------- #
def quad_style():
    """make_ladder_figs.style(), with every text size lifted to >= 9 pt so the
    figure survives being dropped into one quadrant of a slide."""
    style()
    plt.rcParams.update({
        "font.size": 9.0, "axes.titlesize": 9.5, "axes.labelsize": 9.0,
        "xtick.labelsize": 9.0, "ytick.labelsize": 9.0, "legend.fontsize": 9.0,
        "figure.dpi": 100,
    })


def snap_gaps(fig, records, px=2.0, ref_dpi=100.0):
    """Give every adjacent bar a `px`-wide gap of bare surface.

    `records` is a list of (axes, patch, centre, slot_width) — the bar is
    re-laid around its slot centre once the layout is final, so the gap is a
    true 2 px of surface rather than a fraction guessed in data units.
    """
    fig.canvas.draw()
    for ax, patch, centre, slot in records:
        bb = ax.get_window_extent()
        span = ax.get_xlim()[1] - ax.get_xlim()[0]
        inches = bb.width / fig.dpi
        if inches <= 0:
            continue
        gap = (px / ref_dpi) / inches * span
        w = max(slot - gap, slot * 0.5)
        patch.set_width(w)
        patch.set_x(centre - w / 2)


def task_labels(res, tasks):
    """'Temporal' with 'n = 250 questions' on the line under it — short enough
    to stay legible once the label is laid at 45 degrees."""
    return [f"{short_task(t)}\n{res['task_n'][t]} q" for t in tasks]


def set_cat_axis(ax, res, tasks):
    x = np.arange(len(tasks), dtype=float)
    ax.set_xticks(x)
    ax.set_xticklabels(task_labels(res, tasks), fontsize=9, rotation=45,
                       ha="right", rotation_mode="anchor")
    ax.set_xlim(-0.62, len(tasks) - 0.38)
    ax.grid(False, axis="x")
    return x


def spread(ys, gap):
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    for a, b in zip(order, order[1:]):
        if out[b] - out[a] < gap:
            out[b] = out[a] + gap
    return out


def arms_at(res, B):
    return [a for a in ARM_ORDER if a in res["cells"].get(str(B), {})]


def legend_handles(arms, blind=True):
    hs = [plt.Line2D([], [], color=ARM_COLOR[a], lw=2, marker="o", ms=6,
                     mec=SURFACE, mew=1.5, label=ARM_LABEL[a]) for a in arms]
    if blind:
        hs.append(plt.Line2D([], [], color=RULE, lw=1.4, ls=(0, (4, 3)),
                             label=BLIND_LABEL))
    return hs


def bar_legend_handles(arms, blind=True):
    hs = [matplotlib.patches.Patch(facecolor=ARM_COLOR[a], edgecolor="none",
                                   label=ARM_LABEL[a]) for a in arms]
    if blind:
        # same colour and dash as fig_ladder's floor: one quantity, one code
        hs.append(plt.Line2D([], [], color=RULE, lw=1.6, ls=(0, (4, 3)),
                             label=BLIND_LABEL))
    return hs


# --------------------------------------------------------------------------- #
# figure 1 — the ladder                                                        #
# --------------------------------------------------------------------------- #
def fig_ladder(results, out):
    quad_style()
    vals = []
    for ds in DS_ORDER:
        res = results[ds]
        vals.append(res["blind"]["acc"])
        for B in BUDGETS:
            for c in res["cells"].get(str(B), {}).values():
                vals += [c["acc"] - c["pass_std"], c["acc"] + c["pass_std"]]
    lo, hi = min(vals), max(vals)
    pad = 0.09 * (hi - lo)
    lo, hi = lo - pad, hi + pad
    gap = 0.052 * (hi - lo)
    xl = BUDGETS[-1] + 11

    fig, axes = plt.subplots(1, len(DS_ORDER), figsize=(7.0, 3.6), sharey=True)
    all_arms = []
    for ax, ds in zip(axes, DS_ORDER):
        res = results[ds]
        ends = []
        for arm in ARM_ORDER:
            xs = [B for B in BUDGETS if arm in res["cells"].get(str(B), {})]
            if not xs:
                continue
            if arm not in all_arms:
                all_arms.append(arm)
            ys = [res["cells"][str(B)][arm]["acc"] for B in xs]
            sd = [res["cells"][str(B)][arm]["pass_std"] for B in xs]
            ax.fill_between(xs, [y - s for y, s in zip(ys, sd)],
                            [y + s for y, s in zip(ys, sd)],
                            color=ARM_COLOR[arm], alpha=0.10, lw=0, zorder=2)
            ax.plot(xs, ys, color=ARM_COLOR[arm], lw=2.0, marker="o", ms=6,
                    mec=SURFACE, mew=1.5, zorder=3)
            ends.append((arm, xs[-1], ys[-1]))
        b = res["blind"]["acc"]
        ax.axhline(b, color=RULE, lw=1.4, ls=(0, (4, 3)), zorder=1)
        ax.annotate(f"{BLIND_LABEL}  {b:.1f}", (BUDGETS[0] - 7, b), xytext=(0, 4),
                    textcoords="offset points", ha="left", va="bottom",
                    fontsize=9, color=INK2, zorder=4)
        # end labels: nudged apart only as far as the block allows, each tied
        # back to its own line by a leader in the arm colour
        ys0 = [e[2] for e in ends]
        tg = spread(ys0, gap)
        tg = [t + (float(np.mean(ys0)) - float(np.mean(tg))) for t in tg]
        if min(tg) < lo + gap * 0.6:
            tg = [t + (lo + gap * 0.6 - min(tg)) for t in tg]
        if max(tg) > hi - gap * 0.6:
            tg = [t - (max(tg) - (hi - gap * 0.6)) for t in tg]
        for (arm, x, y), t in zip(ends, tg):
            ax.plot([x + 1.5, xl - 1.5], [y, t], color=ARM_COLOR[arm], lw=0.9,
                    solid_capstyle="round", zorder=2)
            ax.annotate(f"{y:.1f}", (xl, t), ha="left", va="center",
                        fontsize=9, color=INK, zorder=4)
        ax.set_title(DS_SHORT[ds])
        ax.set_xticks(BUDGETS)
        ax.set_xlim(BUDGETS[0] - 10, BUDGETS[-1] + 28)
        ax.set_ylim(lo, hi)
        ax.set_xlabel("total frames")
        ax.grid(False, axis="x")
    axes[0].set_ylabel("accuracy (%)")
    fig.legend(handles=legend_handles(all_arms), loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, 0.005), handlelength=2.0, columnspacing=1.6)
    fig.suptitle("InternVL3-8B · 4 passes at T=0.1 · band = spread over passes",
                 fontsize=9, color=INK2, y=0.985)
    fig.subplots_adjust(left=0.075, right=0.995, top=0.855, bottom=0.275, wspace=0.10)
    fig.savefig(out, dpi=300)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# figure 2 — per-task accuracy at the head budget                              #
# --------------------------------------------------------------------------- #
def fig_pertask(results, out, B=HEAD):
    quad_style()
    ratios = [len(results[ds]["tasks"]) for ds in DS_ORDER]
    fig, axes = plt.subplots(1, len(DS_ORDER), figsize=(7.2, 4.0),
                             gridspec_kw={"width_ratios": ratios, "wspace": 0.10})
    recs, all_arms = [], []
    for ax, ds in zip(axes, DS_ORDER):
        res = results[ds]
        tasks = res["tasks"]
        arms = arms_at(res, B)
        all_arms += [a for a in arms if a not in all_arms]
        x = set_cat_axis(ax, res, tasks)
        # 0.84 of the band, so the leftover stays air. The mark spec's <= 24 px
        # cap is in CSS px, the scale snap_gaps() also works in (ref_dpi 100),
        # i.e. 72 px at this figure's 300 dpi save: the widest bar here is 29,
        # under a third of it, so there is nothing to cap.
        slot = 0.84 / len(arms)
        for k, arm in enumerate(arms):
            c = res["cells"][str(B)][arm]
            for xi, t in zip(x, tasks):
                centre = xi + (k - (len(arms) - 1) / 2) * slot
                bar = ax.bar(centre, c["per_task"][t]["acc"], slot,
                             color=ARM_COLOR[arm], linewidth=0, zorder=3)[0]
                recs.append((ax, bar, centre, slot))
        for xi, t in zip(x, tasks):
            bt = res["blind"]["per_task"].get(t)
            if bt:
                ax.hlines(bt["acc"], xi - 0.42, xi + 0.42, color=RULE, lw=1.6,
                          linestyles=(0, (4, 3)), zorder=4)
        ax.set_ylim(0, 80)
        ax.set_yticks([0, 20, 40, 60, 80])
        ax.set_title(DS_SHORT[ds])
        if ds != DS_ORDER[0]:
            ax.set_yticklabels([])
    axes[0].set_ylabel("accuracy (%)")
    fig.legend(handles=bar_legend_handles(all_arms), loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, 0.005), handlelength=1.6, columnspacing=1.4)
    fig.suptitle(f"Accuracy per question type at {B} total frames · "
                 "dash = same questions, no video", fontsize=9, color=INK2, y=0.985)
    fig.subplots_adjust(left=0.072, right=0.995, top=0.855, bottom=0.305)
    snap_gaps(fig, recs)
    fig.savefig(out, dpi=300)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# figure 3 — paired delta per task                                             #
# --------------------------------------------------------------------------- #
def fig_delta(results, out, B=HEAD):
    quad_style()
    ratios = [len(results[ds]["tasks"]) for ds in DS_ORDER]
    vals = []
    for ds in DS_ORDER:
        for arm, e in results[ds]["paired_vs_fs"].get(str(B), {}).items():
            for v in e["per_task"].values():
                if "ci95" in v:
                    vals += list(v["ci95"])
    pad = 0.10 * (max(vals) - min(vals))
    ylo, yhi = min(vals) - pad, max(vals) + pad

    fig, axes = plt.subplots(1, len(DS_ORDER), figsize=(7.2, 4.0), sharey=True,
                             gridspec_kw={"width_ratios": ratios, "wspace": 0.10})
    all_arms = []
    for ax, ds in zip(axes, DS_ORDER):
        res = results[ds]
        tasks = res["tasks"]
        con = res["paired_vs_fs"].get(str(B), {})
        arms = [a for a in ARM_ORDER if a in con]
        all_arms += [a for a in arms if a not in all_arms]
        x = set_cat_axis(ax, res, tasks)
        slot = 0.56 / max(1, len(arms))
        for k, arm in enumerate(arms):
            for xi, t in zip(x, tasks):
                e = con[arm]["per_task"].get(t) or {}
                if "delta" not in e:
                    continue
                xx = xi + (k - (len(arms) - 1) / 2) * slot
                lo, hi = e["ci95"]
                ax.errorbar(xx, e["delta"],
                            yerr=[[e["delta"] - lo], [hi - e["delta"]]],
                            fmt="none", ecolor=ARM_COLOR[arm], elinewidth=1.3,
                            capsize=0, zorder=2)
                sig = e["t_p"] < 0.05
                ax.plot([xx], [e["delta"]], marker="o", ms=7,
                        color=ARM_COLOR[arm],
                        mfc=ARM_COLOR[arm] if sig else SURFACE,
                        mec=ARM_COLOR[arm], mew=1.6, zorder=3)
        ax.axhline(0, color=RULE, lw=1.0, zorder=1)
        ax.set_ylim(ylo, yhi)
        ax.set_title(DS_SHORT[ds])
    axes[0].set_ylabel("Δ accuracy vs native uniform (pts)")
    axes[0].annotate("above 0 = selection wins", (0.04, 0.97), xycoords="axes fraction",
                     va="top", ha="left", fontsize=9, color=INK2)
    hs = [plt.Line2D([], [], color=ARM_COLOR[a], lw=1.6, marker="o", ms=7,
                     mfc=ARM_COLOR[a], mec=ARM_COLOR[a], label=ARM_LABEL[a])
          for a in all_arms]
    hs.append(plt.Line2D([], [], color=INK2, lw=1.6, marker="o", ms=7, mfc=SURFACE,
                         mec=INK2, label="hollow = p ≥ 0.05"))
    fig.legend(handles=hs, loc="lower center", ncol=2, bbox_to_anchor=(0.5, 0.005),
               handlelength=1.8, columnspacing=1.6)
    fig.suptitle(f"Same questions, paired over 4 passes, at {B} total frames · "
                 "whisker = 95% CI", fontsize=9, color=INK2, y=0.985)
    fig.subplots_adjust(left=0.105, right=0.995, top=0.855, bottom=0.325)
    fig.savefig(out, dpi=300)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# figure 4 — selector accuracy (needs selection_coverage.json)                 #
# --------------------------------------------------------------------------- #
def fig_selector(out, B=HEAD, path=COVERAGE):
    if not os.path.exists(path):
        print(f"\nNOTE: {os.path.relpath(path, REPO)} is not on disk — "
              f"skipping {os.path.basename(out)} (selector-accuracy figure). "
              "Re-run this script once the coverage export has landed.")
        return False
    cov = json.load(open(path)).get("summary", {})
    quad_style()
    dss = [d for d in ("CrossView-EgoExo", "CrossView-MEVA") if d in cov]
    if not dss:
        print(f"\nNOTE: {os.path.relpath(path, REPO)} carries no EgoExo/MEVA "
              f"summary — skipping {os.path.basename(out)}.")
        return False
    ratios, panels = [], []
    for ds in dss:
        arms = [a for a in ("sg", "sgva") if str(B) in cov[ds].get(a, {})]
        tasks = []
        for a in arms:
            for t in cov[ds][a][str(B)].get("per_task", {}):
                if t not in tasks:
                    tasks.append(t)
        tasks.sort()
        if arms and tasks:
            panels.append((ds, arms, tasks))
            ratios.append(len(tasks))
    if not panels:
        print(f"\nNOTE: no sg/sgva cells at {B} frames in "
              f"{os.path.relpath(path, REPO)} — skipping {os.path.basename(out)}.")
        return False
    fig, axes = plt.subplots(1, len(panels), figsize=(6.6, 4.0), sharey=True,
                             gridspec_kw={"width_ratios": ratios, "wspace": 0.10},
                             squeeze=False)
    recs, all_arms = [], []
    for ax, (ds, arms, tasks) in zip(axes[0], panels):
        all_arms += [a for a in arms if a not in all_arms]
        n_of = {}
        for t in tasks:
            for a in arms:
                d = cov[ds][a][str(B)].get("per_task", {}).get(t)
                if d and "n" in d:
                    n_of[t] = d["n"]
                    break
        x = np.arange(len(tasks), dtype=float)
        ax.set_xticks(x)
        ax.set_xticklabels([f"{short_task(t)}\n{n_of.get(t, '?')} q" for t in tasks],
                           fontsize=9, rotation=45, ha="right", rotation_mode="anchor")
        ax.set_xlim(-0.62, len(tasks) - 0.38)
        ax.grid(False, axis="x")
        # cap the slot so two arms do not become slabs in a two-task panel
        slot = min(0.8 / len(arms), 0.26)
        for k, arm in enumerate(arms):
            cell = cov[ds][arm][str(B)]["per_task"]
            for xi, t in zip(x, tasks):
                d = cell.get(t)
                if not d or d.get("seg_cov_all") is None:
                    continue
                # the file already stores these as percentages
                centre = xi + (k - (len(arms) - 1) / 2) * slot
                bar = ax.bar(centre, d["seg_cov_all"], slot,
                             color=ARM_COLOR[arm], linewidth=0, zorder=3)[0]
                recs.append((ax, bar, centre, slot))
                # two keep-count-matched nulls, both ticks: the hollow circle
                # is the deck's "not significant" glyph and is not reused here.
                # "independent" draws each camera on its own, so on a union
                # metric (EgoExo) it gains spread the selector did not aim for;
                # "shifted" keeps this row's own picks and their cross-camera
                # overlap and only moves them, so it is the targeting null.
                if d.get("random_seg_cov_all") is not None:
                    ax.plot([centre], [d["random_seg_cov_all"]], marker="_", ms=9,
                            color=INK2, mew=1.6, ls="none", zorder=5)
                if d.get("shift_seg_cov_all") is not None:
                    ax.plot([centre], [d["shift_seg_cov_all"]], marker="d", ms=5,
                            mfc=SURFACE, mec=INK2, mew=1.2, ls="none", zorder=5)
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_title(DS_SHORT.get(ds, ds))
    axes[0][0].set_ylabel("questions with every event kept (%)")
    hs = [matplotlib.patches.Patch(facecolor=ARM_COLOR[a], edgecolor="none",
                                   label=ARM_LABEL[a]) for a in all_arms]
    hs.append(plt.Line2D([], [], color=INK2, marker="_", ms=9, mew=1.6,
                         ls="none", label="chance · drawn per camera"))
    hs.append(plt.Line2D([], [], color=INK2, marker="d", ms=5, mfc=SURFACE,
                         mec=INK2, mew=1.2, ls="none",
                         label="chance · same picks, shifted"))
    fig.legend(handles=hs, loc="lower center", ncol=2, bbox_to_anchor=(0.5, 0.005),
               handlelength=1.6, columnspacing=1.4)
    fig.suptitle(f"Does the selector keep the annotated evidence? {B} total frames · "
                 "EgoExo counts a hit on any camera", fontsize=9, color=INK2, y=0.985)
    fig.subplots_adjust(left=0.115, right=0.995, top=0.855, bottom=0.345)
    snap_gaps(fig, recs)
    fig.savefig(out, dpi=300)
    plt.close(fig)
    return True


# --------------------------------------------------------------------------- #
# report                                                                       #
# --------------------------------------------------------------------------- #
def fmt_p(p):
    return "n/a" if p is None else ("<.001" if p < 0.001 else f"{p:.3f}")


def print_report(results, B=HEAD):
    print(f"\n=== pooled and per-task accuracy at {B} total frames "
          "(4-pass mean ± std over passes)")
    for ds in DS_ORDER:
        res = results[ds]
        tasks = res["tasks"]
        print(f"\n-- {ds}  ({res['n']} questions)")
        head = "  arm                       pooled  " + "  ".join(
            f"{short_task(t)[:12]:>12s}" for t in tasks)
        print(head)
        for arm in arms_at(res, B):
            c = res["cells"][str(B)][arm]
            print(f"  {ARM_LABEL[arm]:<24s} {c['acc']:5.2f} ±{c['pass_std']:.2f}  " + "  ".join(
                f"{c['per_task'][t]['acc']:12.2f}" for t in tasks))
        b = res["blind"]
        print(f"  {'no video (blind)':<24s} {b['acc']:5.2f} ±{b['pass_std']:.2f}  " + "  ".join(
            f"{b['per_task'][t]['acc']:12.2f}" for t in tasks))

    print(f"\n=== per-question outcome vs native uniform at {B} frames "
          "(mean over 4 passes per question)")
    for ds in DS_ORDER:
        res = results[ds]
        print(f"\n-- {ds}")
        for arm, e in res["paired_vs_fs"].get(str(B), {}).items():
            a = e["all"]
            print(f"  {ARM_LABEL[arm]:<24s} win {a['win']:4d} / tie {a['tie']:4d} / "
                  f"loss {a['loss']:4d} of {a['n']:4d}   Δ {a['delta']:+.2f} "
                  f"[{a['ci95'][0]:+.2f},{a['ci95'][1]:+.2f}]  t p={fmt_p(a['t_p'])}  "
                  f"sign p={fmt_p(a['sign_p'])}")
            for t in res["tasks"]:
                v = e["per_task"].get(t) or {}
                if "delta" not in v:
                    continue
                print(f"      {short_task(t):<20s} win {v['win']:4d} / tie {v['tie']:4d} / "
                      f"loss {v['loss']:4d}   Δ {v['delta']:+.2f}  t p={fmt_p(v['t_p'])}")

    print(f"\n=== question-wise consistency at {B} frames "
          "(ids by number of passes correct, 0..4)")
    for ds in DS_ORDER:
        res = results[ds]
        qw = res["question_wise"].get(str(B), {})
        print(f"\n-- {ds}")
        for arm in arms_at(res, B):
            h = qw[arm]["all"]
            print(f"  {ARM_LABEL[arm]:<24s} 0:{h[0]:4d} 1:{h[1]:4d} 2:{h[2]:4d} "
                  f"3:{h[3]:4d} 4:{h[4]:4d}")
        for arm in arms_at(res, B):
            ex = qw[arm].get("exclusive_vs_fs")
            if not ex:
                continue
            print(f"  {ARM_LABEL[arm]:<24s} all-4 vs all-0 against native: " + "  ".join(
                f"{short_task(t)} {ex['per_task'][t]['arm_all4_fs_all0']}↑/"
                f"{ex['per_task'][t]['fs_all4_arm_all0']}↓" for t in res["tasks"])
                + f"   pooled {ex['all']['arm_all4_fs_all0']}↑/"
                  f"{ex['all']['fs_all4_arm_all0']}↓")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", default=OUT_JSON)
    ap.add_argument("--figs", default=FIGS)
    ap.add_argument("--no-figs", action="store_true")
    ap.add_argument("--allow-mismatch", action="store_true",
                    help="report a cross-check mismatch but still exit 0")
    args = ap.parse_args()

    results, sources = {}, {}
    for ds, (subset, stem, arms) in DATASETS.items():
        results[ds] = compute_dataset(ds, subset, stem, arms)
        sources[ds] = {"subset": f"analysis/{subset}", "stem": stem, "tags": arms}

    # (b) the matched-protocol blind legs
    blind_bad = []
    for ds, (pattern, expect) in BLIND.items():
        rows, paths, where = blind_rows(pattern)
        if not rows:
            blind_bad.append(f"{ds}: no blind rows for {pattern}")
            continue
        b = cell_stats(rows, results[ds]["tasks"])
        b["expected_acc"] = expect
        b["files"] = paths
        b["source"] = where
        results[ds]["blind"] = b
        if abs(b["acc"] - expect) > TOL:
            blind_bad.append(f"{ds} blind acc: {b['acc']:.4f} vs registry {expect:.2f}")

    ladder = json.load(open(LADDER_STATS))
    ladder_bad = check_ladder(results, ladder)

    print_report(results)

    if ladder_bad or blind_bad:
        print("\n!! CROSS-CHECK MISMATCHES")
        for m in ladder_bad + blind_bad:
            print(f"   {m}")
    else:
        print(f"\ncross-check OK: every cell matches {os.path.relpath(LADDER_STATS, REPO)} "
              f"to {TOL}, and the three blind legs match the registry.")

    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    json.dump({"generated": GENERATED,
               "head_budget": HEAD,
               "budgets": list(BUDGETS),
               "arms": ARM_LABEL,
               "sources": sources,
               "checked_against": {"ladder_stats": os.path.relpath(LADDER_STATS, REPO),
                                   "tolerance_pts": TOL},
               "assertions": {"ladder_stats_mismatches": ladder_bad,
                              "blind_mismatches": blind_bad},
               "datasets": results},
              open(args.json, "w"), indent=1, default=str)
    print(f"\nwrote {args.json}")

    if not args.no_figs:
        os.makedirs(args.figs, exist_ok=True)
        fig_ladder(results, os.path.join(args.figs, "fig_quad_ladder.png"))
        fig_pertask(results, os.path.join(args.figs, "fig_quad_pertask.png"))
        fig_delta(results, os.path.join(args.figs, "fig_quad_delta.png"))
        ok4 = fig_selector(os.path.join(args.figs, "fig_quad_selector.png"))
        print(f"figures -> {args.figs}"
              f"{'' if ok4 else '  (fig_quad_selector.png not rendered)'}")

    if (ladder_bad or blind_bad) and not args.allow_mismatch:
        raise AssertionError(f"{len(ladder_bad) + len(blind_bad)} cross-check "
                             "mismatch(es); see the list above")


if __name__ == "__main__":
    main()
