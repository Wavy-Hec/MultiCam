#!/usr/bin/env python3
"""The segment-selection ladder as numbers and as the Task-1 figures.

For each dataset in ``split_ladder_by_query.DATASETS`` (MVU-Eval, CrossView-
EgoExo, CrossView-MEVA on its post-remux legs) and each registered arm at
32 / 64 / 96 total frames, this computes from the rescored rows:

  accuracy         4-pass mean and the std over the four per-pass accuracies
                   (bench/metrics.py's convention: pstdev), overall and per task
  contrasts        paired per-record differences between arms (mean over
                   passes per id, then arm A minus arm B) with a paired-t p, a
                   sign-test p and a 95% t-interval, overall and per task
  cost             the answer call's latency_s (mean / median / p95) and the
                   input / video / output token counts, plus — when the Slurm
                   logs are present — end-to-end wall-clock seconds per row
                   from the RUN/DONE stamps, which is what includes decoding
                   and the selection stage the row latency does not
  query split      the content-vs-clip-reference split of every contrast
                   (same rule as split_ladder_by_query.py)

and renders analysis/figs_deck/fig_ladder_task1.png (accuracy / latency /
tokens vs frames, one column per dataset), fig_ladder_pertask.png (per-task
bars), fig_ladder_query_split.png (paired deltas by query content) and
fig_meva_defect.png (the pre-remux MEVA legs against the rerun — the size of
the decode defect, never a baseline).

Reads bench/results/rescored/ only. The MEVA panel reads the _mp4* tags; the
pre-remux tags are read solely for the defect figure.

Usage (cvbench env):
  python analysis/make_ladder_figs.py
  python analysis/make_ladder_figs.py --json analysis/records/ladder_stats.json
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import stats  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
from split_ladder_by_query import DATASETS, BUDGETS, BASELINE_METHOD, RES  # noqa: E402
from bench.methods.clip_select import option_texts  # noqa: E402
from bench.methods.segment_select import _options_are_clip_refs  # noqa: E402

LOGS = os.path.join(HERE, "logs")
FIGS = os.path.join(HERE, "figs_deck")
# the pre-remux MEVA legs: decoded frame (i mod 60) of every clip; shown only
# to size the defect
OLD_MEVA_TAGS = {"fs": "fs", "sg": "sg", "sgva": "sgva"}

ARM_LABEL = {"fs": "native uniform", "sg": "SigLIP top-4 · question",
             "sgv": "ViCLIP top-4 · options", "sgva": "ViCLIP auto-K · options"}
ARM_ORDER = ["fs", "sg", "sgva", "sgv"]
# dataviz categorical slots 1-4 in fixed order (identity follows the arm, never
# its rank); pre-remux rows in the de-emphasis gray
ARM_COLOR = {"fs": "#2a78d6", "sg": "#eb6834", "sgva": "#1baf7a", "sgv": "#eda100"}
OLD_COLOR = "#8a8985"
INK, INK2, RULE, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8985", "#e6e5e2", "#fcfcfb"
SHORT_TASK = re.compile(r"^(?:CrossView-)?(?:MEVA-|EgoExo4D-|MVU-)")
CONTRASTS = [("sg", "fs"), ("sgva", "fs"), ("sgva", "sg"),
             ("sgv", "fs"), ("sgv", "sg"), ("sgva", "sgv")]


def short_task(t):
    return SHORT_TASK.sub("", t or "?")


def load_rows(stem, tag, budget, method_filter=None):
    rows = []
    for path in sorted(glob.glob(os.path.join(RES, f"{stem}_{tag}{budget}_shard*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if method_filter and r.get("method") != method_filter:
                    continue
                row = {k: r.get(k) for k in (
                    "id", "pass_idx", "correct", "latency_s", "input_tokens",
                    "video_tokens", "output_tokens", "task_type", "method",
                    "num_videos", "media_remap", "prediction", "gold")}
                # selection-stage wall time, stamped once per record and
                # copied onto its passes (rows from 2026-08-28 on)
                row["selection_latency_s"] = (r.get("frame_alloc") or {}).get("selection_latency_s")
                rows.append(row)
    return rows


def acc_stats(rows):
    """mean accuracy over rows + std over the per-pass accuracies (pstdev)."""
    if not rows:
        return None
    by_pass = defaultdict(list)
    for r in rows:
        by_pass[r["pass_idx"]].append(1.0 if r["correct"] else 0.0)
    per_pass = [100 * float(np.mean(v)) for _, v in sorted(by_pass.items())]
    return {"acc": 100 * float(np.mean([1.0 if r["correct"] else 0.0 for r in rows])),
            "pass_std": float(np.std(per_pass)) if len(per_pass) > 1 else 0.0,
            "per_pass": [round(x, 2) for x in per_pass],
            "n_rows": len(rows), "n_ids": len({r["id"] for r in rows})}


def per_id(rows):
    d = defaultdict(list)
    for r in rows:
        d[r["id"]].append(1.0 if r["correct"] else 0.0)
    return {i: float(np.mean(v)) for i, v in d.items()}


def loo_modal_floor(golds):
    """Leave-one-out modal-letter accuracy (%) of a gold-letter list: the
    score of always answering the most common letter, without the target
    record voting for itself (in-sample overfits by ~20 points on small
    tasks — see the CrossView floor note)."""
    c = defaultdict(int)
    for g in golds:
        c[g] += 1
    hits = 0
    for g in golds:
        c[g] -= 1
        hits += g == max(c, key=c.get)
        c[g] += 1
    return 100 * hits / len(golds) if golds else float("nan")


def letter_only_expectation(rows, task_of):
    """Accuracy (%) an arm would score if its predicted letter were
    independent of the content given the task: sum over tasks and letters
    of p_pred(L | task) x p_gold(L | task), weighted by task size. An arm
    whose raw gain over another comes with a matching shift of its letter
    distribution toward the modal gold letter gains here too; the
    difference acc - expectation is the content-driven part."""
    by_task = defaultdict(list)
    for r in rows:
        by_task[task_of[r["id"]]].append(r)
    exp = 0.0
    for t, rs in by_task.items():
        gold = defaultdict(int)
        pred = defaultdict(int)
        for r in rs:
            gold[str(r.get("gold") or "").strip().upper()[:1]] += 1
            pred[str(r.get("prediction") or "").strip().upper()[:1]] += 1
        exp += sum(pred[L] * gold[L] / len(rs) for L in pred)
    return 100 * exp / len(rows) if rows else float("nan")


def paired(a, b, ids):
    """arm a minus arm b over ids: delta (pts), paired-t p, sign p, 95% CI, n."""
    ids = [i for i in ids if i in a and i in b]
    if len(ids) < 2:
        return None
    d = np.array([a[i] - b[i] for i in ids])
    if np.allclose(d, 0):
        return {"delta": 0.0, "t_p": 1.0, "sign_p": 1.0, "ci95": [0.0, 0.0], "n": len(d)}
    t_p = float(stats.ttest_rel([a[i] for i in ids], [b[i] for i in ids]).pvalue)
    up, down = int((d > 0).sum()), int((d < 0).sum())
    sign_p = float(stats.binomtest(up, up + down).pvalue) if up + down else 1.0
    h = stats.t.ppf(0.975, len(d) - 1) * d.std(ddof=1) / np.sqrt(len(d))
    return {"delta": 100 * float(d.mean()), "t_p": t_p, "sign_p": sign_p,
            "ci95": [100 * float(d.mean() - h), 100 * float(d.mean() + h)],
            "n": len(d), "n_up": up, "n_down": down}


def cost_stats(rows):
    lat = np.array([r["latency_s"] for r in rows if r.get("latency_s") is not None])
    out = {}
    if len(lat):
        out.update(latency_s_mean=float(lat.mean()), latency_s_median=float(np.median(lat)),
                   latency_s_p95=float(np.percentile(lat, 95)))
    for k in ("input_tokens", "video_tokens", "output_tokens"):
        xs = [r[k] for r in rows if r.get(k) is not None]
        out[f"{k}_mean"] = float(np.mean(xs)) if xs else None
    out["num_videos_mean"] = float(np.mean([r["num_videos"] for r in rows
                                            if r.get("num_videos")]))
    # per record, not per row: the same value sits on all of a record's passes
    sel = {r["id"]: r["selection_latency_s"] for r in rows
           if r.get("selection_latency_s") is not None}
    out["selection_latency_s_mean"] = float(np.mean(list(sel.values()))) if sel else None
    return out


_STAMP = re.compile(r"^(RUN|DONE) @ (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def wall_per_row(stem, tag, budget):
    """End-to-end seconds per row from the job logs' RUN/DONE stamps, averaged
    over the leg's shards. None when the logs are not on disk."""
    needle = f"out=bench/results/{stem}_{tag}{budget}_shard"
    secs, rows = 0.0, 0
    for path in glob.glob(os.path.join(LOGS, "*.bench.out")):
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            continue
        if needle not in text:
            continue
        stamps = {}
        for line in text.splitlines():
            m = _STAMP.match(line)
            if m:
                stamps[m.group(1)] = datetime.strptime(m.group(2), "%Y-%m-%d %H:%M:%S")
        if "RUN" not in stamps or "DONE" not in stamps:
            continue
        m = re.search(r"out=(\S+_shard\d+\.jsonl)", text)
        shard = os.path.join(REPO, m.group(1)) if m else None
        if not shard or not os.path.exists(shard):
            continue
        with open(shard) as fh:
            n = sum(1 for l in fh if l.strip())
        secs += (stamps["DONE"] - stamps["RUN"]).total_seconds()
        rows += n
    return (secs / rows) if rows else None


def compute(ds, subset, stem, arms):
    recs = json.load(open(os.path.join(HERE, subset)))
    task = {r["id"]: r.get("task_type", "?") for r in recs}
    clipref = {r["id"]: _options_are_clip_refs(option_texts(r)) for r in recs}
    tasks = sorted({task[i] for i in task})
    gold = {r["id"]: str(r.get("answer") or "").strip().upper()[:1] for r in recs}
    out = {"n": len(recs), "tasks": tasks,
           "n_clip_ref": sum(clipref.values()), "cells": {}, "contrasts": {},
           "split": {},
           # the letter floors every cell should be read against
           "loo_modal_floor": loo_modal_floor(list(gold.values())),
           "loo_modal_floor_task": sum(
               loo_modal_floor([gold[i] for i in gold if task[i] == t])
               * sum(1 for i in gold if task[i] == t) for t in tasks) / len(recs),
           "loo_modal_floor_by_task": {t: loo_modal_floor([gold[i] for i in gold if task[i] == t])
                                       for t in tasks}}
    for B in BUDGETS:
        legs = {}
        for arm, tag in arms.items():
            rows = load_rows(stem, tag, B, BASELINE_METHOD if arm == "fs" else None)
            if rows:
                legs[arm] = rows
        if not legs:
            continue
        cells = {}
        for arm, rows in legs.items():
            c = acc_stats(rows)
            c["per_task"] = {t: acc_stats([r for r in rows if r["task_type"] == t])
                             for t in tasks}
            c.update(cost_stats(rows))
            c["letter_only_expectation"] = letter_only_expectation(rows, task)
            c["above_letter_prior"] = c["acc"] - c["letter_only_expectation"]
            c["per_task_above_letter_prior"] = {
                t: (c["per_task"][t]["acc"]
                    - letter_only_expectation([r for r in rows if r["task_type"] == t], task))
                for t in tasks}
            c["pred_letter_share"] = {
                L: 100 * sum(1 for r in rows if str(r.get("prediction") or "").upper()[:1] == L) / len(rows)
                for L in sorted({str(r.get("gold") or "").upper()[:1] for r in rows})}
            c["wall_s_per_row"] = wall_per_row(stem, arms[arm], B)
            cells[arm] = c
        out["cells"][B] = cells
        pid = {arm: per_id(rows) for arm, rows in legs.items()}
        ids_all = [i for i in task if all(i in pid[a] for a in pid)]
        con = {}
        for a, b in CONTRASTS:
            if a in pid and b in pid:
                con[f"{a}-{b}"] = {
                    "all": paired(pid[a], pid[b], ids_all),
                    "per_task": {t: paired(pid[a], pid[b], [i for i in ids_all if task[i] == t])
                                 for t in tasks}}
        out["contrasts"][B] = con
        split = {}
        for gname, flag in (("clip-ref options", True), ("content options", False)):
            ids = [i for i in ids_all if clipref[i] == flag]
            if not ids:
                continue
            cell = {"n": len(ids),
                    "acc": {arm: 100 * float(np.mean([pid[arm][i] for i in ids])) for arm in pid}}
            for a, b in CONTRASTS:
                if a in pid and b in pid:
                    cell[f"{a}-{b}"] = paired(pid[a], pid[b], ids)
            split[gname] = cell
        out["split"][B] = split
    return out


def compute_old_meva():
    subset, stem, _ = DATASETS["CrossView-MEVA"]
    out = {}
    for B in BUDGETS:
        out[B] = {}
        for arm, tag in OLD_MEVA_TAGS.items():
            rows = load_rows(stem, tag, B, BASELINE_METHOD if arm == "fs" else None)
            if rows:
                out[B][arm] = acc_stats(rows)
    return out


# --------------------------------------------------------------------------- #
# figures                                                                      #
# --------------------------------------------------------------------------- #
def style():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": RULE, "axes.linewidth": 0.6, "axes.spines.top": False,
        "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.6, "grid.linestyle": "-", "axes.axisbelow": True,
        "xtick.color": INK2, "ytick.color": INK2, "axes.labelcolor": INK2,
        "text.color": INK, "font.size": 9.5, "axes.titlesize": 10.5,
        "axes.titleweight": "semibold", "legend.frameon": False,
        "legend.fontsize": 8.5, "xtick.major.size": 0, "ytick.major.size": 0,
    })


def _spread_labels(ys, gap):
    """Label y-positions: the values themselves, nudged apart so that no two
    sit closer than ``gap`` (keeps the endpoint numbers legible)."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    for a, b in zip(order, order[1:]):
        if out[b] - out[a] < gap:
            out[b] = out[a] + gap
    return out


def arms_present(res):
    return [a for a in ARM_ORDER if any(a in res["cells"].get(B, {}) for B in BUDGETS)]


def fig_task1(results, out):
    """rows: accuracy / answer latency / input tokens; columns: datasets."""
    style()
    dss = list(results)
    fig, axes = plt.subplots(3, len(dss), figsize=(3.6 * len(dss), 8.4), sharex=True)
    axes = np.atleast_2d(axes)
    metric = [("acc", "accuracy (%)", None), ("latency_s_mean", "answer latency (s)", None),
              ("input_tokens_mean", "input tokens (k)", 1e-3)]
    for j, ds in enumerate(dss):
        res = results[ds]
        for i, (key, ylabel, scale) in enumerate(metric):
            ax = axes[i, j]
            ends = []
            for arm in arms_present(res):
                xs = [B for B in BUDGETS if arm in res["cells"].get(B, {})]
                ys = [res["cells"][B][arm][key] for B in xs]
                if scale:
                    ys = [y * scale for y in ys]
                ax.plot(xs, ys, color=ARM_COLOR[arm], lw=1.8, marker="o", ms=5.5,
                        mec=SURFACE, mew=1.2, label=ARM_LABEL[arm], zorder=3)
                if key == "acc":
                    sd = [res["cells"][B][arm]["pass_std"] for B in xs]
                    ax.fill_between(xs, [y - s for y, s in zip(ys, sd)],
                                    [y + s for y, s in zip(ys, sd)],
                                    color=ARM_COLOR[arm], alpha=0.13, lw=0, zorder=2)
                    ends.append((xs[-1], ys[-1]))
            # endpoint labels, pushed apart when two arms end within 0.7 pt
            for (x, y), ly in zip(ends, _spread_labels([e[1] for e in ends], 0.7)):
                ax.annotate(f"{y:.1f}", (x, ly), xytext=(5, 0), textcoords="offset points",
                            va="center", fontsize=8, color=INK2)
            ax.set_xticks(BUDGETS)
            if i == 0:
                ax.set_title(ds)
            if j == 0:
                ax.set_ylabel(ylabel)
            if i == 2:
                ax.set_xlabel("total frames per question")
            ax.set_xlim(24, 110)
    for i in range(3):
        lo = min(a.get_ylim()[0] for a in axes[i])
        hi = max(a.get_ylim()[1] for a in axes[i])
        for a in axes[i]:
            a.set_ylim(lo, hi)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    seen = {}
    for ax in axes.flat:
        for h, l in zip(*ax.get_legend_handles_labels()):
            seen.setdefault(l, h)
    fig.legend(seen.values(), seen.keys(), loc="lower center", ncol=min(4, len(seen)),
               bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("Segment-selection ladder · InternVL3-8B · temp 0.1 · reasoning off · 4 passes "
                 "(band = std over passes)", fontsize=10, color=INK2, y=0.995)
    fig.tight_layout(rect=(0, 0.04, 1, 0.98))
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_pertask(results, out):
    style()
    dss = list(results)
    fig, axes = plt.subplots(len(dss), len(BUDGETS), figsize=(4.6 * len(BUDGETS), 2.9 * len(dss)),
                             squeeze=False)
    for i, ds in enumerate(dss):
        res = results[ds]
        arms = arms_present(res)
        tasks = res["tasks"]
        x = np.arange(len(tasks))
        w = 0.8 / max(1, len(arms))
        for j, B in enumerate(BUDGETS):
            ax = axes[i, j]
            cells = res["cells"].get(B, {})
            for k, arm in enumerate(arms):
                if arm not in cells:
                    continue
                ys = [cells[arm]["per_task"][t]["acc"] for t in tasks]
                es = [cells[arm]["per_task"][t]["pass_std"] for t in tasks]
                ax.bar(x + (k - (len(arms) - 1) / 2) * w, ys, w * 0.92, color=ARM_COLOR[arm],
                       yerr=es, error_kw=dict(ecolor=INK2, elinewidth=0.7, capsize=0),
                       label=ARM_LABEL[arm], zorder=3)
            ax.set_xticks(x)
            ax.set_xticklabels([short_task(t) for t in tasks], rotation=0 if len(tasks) < 5 else 35,
                               ha="center" if len(tasks) < 5 else "right", fontsize=8.5)
            ax.set_title(f"{ds} · {B} frames")
            if j == 0:
                ax.set_ylabel("accuracy (%)")
            ax.set_ylim(0, 100)
            ax.grid(False, axis="x")
    seen = {}
    for ax in axes.flat:
        for h, l in zip(*ax.get_legend_handles_labels()):
            seen.setdefault(l, h)
    fig.legend(seen.values(), seen.keys(), loc="lower center", ncol=min(4, len(seen)),
               bbox_to_anchor=(0.5, -0.005))
    fig.suptitle("Accuracy per task · InternVL3-8B · 4-pass mean, whisker = std over passes",
                 fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_query_split(results, out):
    """Paired deltas versus native by query content; whisker = 95% CI, filled
    marker = paired-t p < 0.05."""
    style()
    dss = list(results)
    fig, axes = plt.subplots(1, len(dss), figsize=(4.2 * len(dss), 3.9), squeeze=False)
    groups = ["clip-ref options", "content options"]
    cons = [("sg", "fs"), ("sgva", "fs")]
    for j, ds in enumerate(dss):
        ax = axes[0, j]
        res = results[ds]
        xt, xl = [], []
        for bi, B in enumerate(BUDGETS):
            sp = res["split"].get(B, {})
            for gi, g in enumerate(groups):
                base = bi * (len(groups) + 0.6) + gi
                xt.append(base)
                xl.append(f"{B}f\n{'clip-ref' if gi == 0 else 'content'}")
                if g not in sp:
                    continue
                for ci, (a, b) in enumerate(cons):
                    key = f"{a}-{b}"
                    if key not in sp[g] or sp[g][key] is None:
                        continue
                    c = sp[g][key]
                    xx = base + (ci - 0.5) * 0.36
                    ax.errorbar(xx, c["delta"], yerr=[[c["delta"] - c["ci95"][0]],
                                                      [c["ci95"][1] - c["delta"]]],
                                fmt="o", ms=6, color=ARM_COLOR[a], ecolor=ARM_COLOR[a],
                                elinewidth=1.2, capsize=0,
                                mfc=ARM_COLOR[a] if c["t_p"] < 0.05 else SURFACE, mew=1.6,
                                label=f"{ARM_LABEL[a]} − native", zorder=3)
        ax.axhline(0, color=RULE, lw=0.8, zorder=1)
        ax.set_xticks(xt)
        ax.set_xticklabels(xl, fontsize=8)
        n_cr = res["n_clip_ref"]
        ax.set_title(f"{ds}\nclip-ref n={n_cr} · content n={res['n'] - n_cr}", fontsize=9.5)
        if j == 0:
            ax.set_ylabel("Δ accuracy vs native (pts)")
        ax.grid(False, axis="x")
    lo = min(a.get_ylim()[0] for a in axes.flat)
    hi = max(a.get_ylim()[1] for a in axes.flat)
    for a in axes.flat:
        a.set_ylim(lo, hi)
    seen = {}
    for ax in axes.flat:
        for h, l in zip(*ax.get_legend_handles_labels()):
            seen.setdefault(l, h)
    fig.legend(seen.values(), seen.keys(), loc="lower center", ncol=len(seen),
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Paired delta vs native by whether the scorer had a content query · "
                 "whisker = 95% CI, filled = paired-t p < 0.05", fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_meva_defect(new, old, out):
    style()
    arms = [a for a in ("fs", "sg", "sgva") if any(a in old[B] for B in BUDGETS)]
    fig, axes = plt.subplots(1, len(arms), figsize=(3.7 * len(arms), 3.5), sharey=True,
                             squeeze=False)
    for j, arm in enumerate(arms):
        ax = axes[0, j]
        xs = [B for B in BUDGETS if arm in old[B]]
        yo = [old[B][arm]["acc"] for B in xs]
        ax.plot(xs, yo, color=OLD_COLOR, lw=1.6, marker="o", ms=5, mec=SURFACE, mew=1.2,
                label="pre-remux rows (frame i mod 60 — invalid)", zorder=2)
        xs2 = [B for B in BUDGETS if arm in new["cells"].get(B, {})]
        yn = [new["cells"][B][arm]["acc"] for B in xs2]
        sd = [new["cells"][B][arm]["pass_std"] for B in xs2]
        ax.fill_between(xs2, [y - s for y, s in zip(yn, sd)], [y + s for y, s in zip(yn, sd)],
                        color=ARM_COLOR[arm], alpha=0.13, lw=0)
        ax.plot(xs2, yn, color=ARM_COLOR[arm], lw=1.8, marker="o", ms=5.5, mec=SURFACE, mew=1.2,
                label="corrected (remuxed .mp4, arm colour)", zorder=3)
        for x, a, b in zip(xs2, yn, yo):
            ax.annotate(f"{a - b:+.1f}", (x, max(a, b)), xytext=(0, 6), textcoords="offset points",
                        ha="center", fontsize=8, color=INK2)
        ax.set_title(ARM_LABEL[arm])
        ax.set_xticks(BUDGETS)
        ax.set_xlim(24, 104)
        ax.set_xlabel("total frames per question")
        if j == 0:
            ax.set_ylabel("accuracy (%)")
    seen = {}
    for ax in axes.flat:
        for h, l in zip(*ax.get_legend_handles_labels()):
            if l.startswith("pre-remux") or l.startswith("corrected"):
                seen.setdefault("pre-remux rows (frame i mod 60 — invalid)" if l.startswith("pre-remux") else l, h)
    fig.legend(seen.values(), seen.keys(), loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("CrossView-MEVA, 4-camera pool: the same nine legs before and after the decode fix "
                 "(annotation = corrected − pre-remux)", fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, 0.08, 1, 0.94))
    fig.savefig(out, dpi=200)
    plt.close(fig)


# --------------------------------------------------------------------------- #
def fmt_p(p):
    return "n/a" if p is None else ("<.001" if p < 0.001 else f"{p:.3f}")


def print_report(results, old_meva):
    for ds, res in results.items():
        print(f"\n== {ds}: {res['n']} records, clip-ref option sets {res['n_clip_ref']}; "
              f"LOO modal-letter floor {res['loo_modal_floor']:.2f} overall, "
              f"{res['loo_modal_floor_task']:.2f} task-conditioned")
        for B in BUDGETS:
            cells = res["cells"].get(B)
            if not cells:
                continue
            print(f"  B={B}")
            for arm in arms_present(res):
                if arm not in cells:
                    continue
                c = cells[arm]
                wall = c["wall_s_per_row"]
                print(f"    {arm:5s} acc {c['acc']:6.2f} ± {c['pass_std']:.2f}  "
                      f"lat {c['latency_s_mean']:.2f}s (med {c['latency_s_median']:.2f})  "
                      f"in {c['input_tokens_mean']:,.0f} vid {c['video_tokens_mean']:,.0f} "
                      f"out {c['output_tokens_mean']:.1f}"
                      + (f"  wall {wall:.1f}s/row" if wall else "")
                      + (f"  sel {c['selection_latency_s_mean']:.1f}s/rec" if c.get("selection_latency_s_mean") else "")
                      + f"  letter-exp {c['letter_only_expectation']:.1f} (+{c['above_letter_prior']:.1f})"
                      + "  | " + "  ".join(f"{short_task(t)} {c['per_task'][t]['acc']:.1f}"
                                            for t in res["tasks"]))
            for key, con in res["contrasts"][B].items():
                a = con["all"]
                if a is None:
                    continue
                print(f"    {key:9s} {a['delta']:+6.2f} [{a['ci95'][0]:+.2f},{a['ci95'][1]:+.2f}] "
                      f"t p={fmt_p(a['t_p'])} sign p={fmt_p(a['sign_p'])} n={a['n']}  | "
                      + "  ".join(f"{short_task(t)} {v['delta']:+.1f} (p={fmt_p(v['t_p'])})"
                                  for t, v in con["per_task"].items() if v))
    print("\n== CrossView-MEVA pre-remux legs (invalid; defect size = corrected − old)")
    new = results.get("CrossView-MEVA", {}).get("cells", {})
    for B in BUDGETS:
        for arm, c in old_meva.get(B, {}).items():
            n = new.get(B, {}).get(arm)
            print(f"  B={B} {arm:5s} old {c['acc']:.2f}  new {n['acc'] if n else float('nan'):.2f}  "
                  f"Δ {((n['acc'] - c['acc']) if n else float('nan')):+.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", default=os.path.join(HERE, "records", "ladder_stats.json"))
    ap.add_argument("--figs", default=FIGS)
    ap.add_argument("--no-figs", action="store_true")
    args = ap.parse_args()
    results = {}
    for ds, (subset, stem, arms) in DATASETS.items():
        results[ds] = compute(ds, subset, stem, arms)
    old_meva = compute_old_meva()
    print_report(results, old_meva)
    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    json.dump({"results": results, "meva_pre_remux": old_meva,
               "arms": ARM_LABEL, "budgets": BUDGETS},
              open(args.json, "w"), indent=1, default=str)
    print(f"\nwrote {args.json}")
    if args.no_figs:
        return
    os.makedirs(args.figs, exist_ok=True)
    fig_task1(results, os.path.join(args.figs, "fig_ladder_task1.png"))
    fig_pertask(results, os.path.join(args.figs, "fig_ladder_pertask.png"))
    fig_query_split(results, os.path.join(args.figs, "fig_ladder_query_split.png"))
    if "CrossView-MEVA" in results and any(old_meva.values()):
        fig_meva_defect(results["CrossView-MEVA"], old_meva,
                        os.path.join(args.figs, "fig_meva_defect.png"))
        # the four plain-language figures for a first-time reader
        story_figs(_str_keys(results), {str(k): v for k, v in old_meva.items()}, args.figs)
    print(f"figures -> {args.figs}")


def _str_keys(results):
    """The story figures index cells/contrasts by the JSON's string budgets."""
    out = {}
    for ds, res in results.items():
        r = dict(res)
        r["cells"] = {str(k): v for k, v in res["cells"].items()}
        r["contrasts"] = {str(k): v for k, v in res["contrasts"].items()}
        out[ds] = r
    return out



# --------------------------------------------------------------------------- #
# story figures: the four plots a first-time reader needs, plain labels        #
# --------------------------------------------------------------------------- #
PLAIN = {"fs": "uniform sampling", "sg": "SigLIP picks segments",
         "sgva": "ViCLIP picks segments", "sgv": "ViCLIP picks segments (fixed 4)"}
DS_PLAIN = {"MVU-Eval": "MVU-Eval (many unrelated videos)",
            "CrossView-EgoExo": "EgoExo (one activity, ego + exo cameras)",
            "CrossView-MEVA": "MEVA (surveillance, 4 fixed cameras)"}


def fig_story_meva(new, old, out):
    """Before / after the decode fix on MEVA, same axes."""
    style()
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.9), sharey=True)
    for ax, (title, src) in zip(axes, (("BEFORE the fix — model saw only the first 2 s (invalid)", "old"),
                                       ("AFTER the fix — model sees the whole 5-minute clip", "new"))):
        ends = []
        for arm in ("fs", "sg", "sgva"):
            if src == "old":
                xs = [B for B in BUDGETS if arm in old[str(B)]]
                ys = [old[str(B)][arm]["acc"] for B in xs]
                sd = [old[str(B)][arm]["pass_std"] for B in xs]
            else:
                xs = [B for B in BUDGETS if arm in new["cells"].get(str(B), {})]
                ys = [new["cells"][str(B)][arm]["acc"] for B in xs]
                sd = [new["cells"][str(B)][arm]["pass_std"] for B in xs]
            col = ARM_COLOR[arm] if src == "new" else {"fs": "#7d8f9a", "sg": "#b08f7d", "sgva": "#7fa693"}[arm]
            ax.fill_between(xs, [y - s for y, s in zip(ys, sd)], [y + s for y, s in zip(ys, sd)],
                            color=col, alpha=0.12, lw=0)
            ax.plot(xs, ys, color=col, lw=2, marker="o", ms=6, mec=SURFACE, mew=1.2, label=PLAIN[arm])
            ends.append((xs[-1], ys[-1]))
        for (x, y), ly in zip(ends, _spread_labels([e[1] for e in ends], 0.55)):
            ax.annotate(f"{y:.1f}", (x, ly), xytext=(6, 0), textcoords="offset points",
                        va="center", fontsize=8.5, color=INK2)
        ax.set_title(title, fontsize=9.5)
        ax.set_xticks(BUDGETS)
        ax.set_xlim(24, 108)
        ax.set_xlabel("frames shown to the model (total, across 4 cameras)")
    axes[0].set_ylabel("accuracy (%)")
    # the gap annotation on the after panel
    a96 = new["cells"]["96"]
    axes[1].annotate("", xy=(96, a96["sg"]["acc"]), xytext=(96, a96["fs"]["acc"]),
                     arrowprops=dict(arrowstyle="<->", color=INK2, lw=1))
    axes[1].annotate(f"+{a96['sg']['acc'] - a96['fs']['acc']:.1f}", (96, (a96["sg"]["acc"] + a96["fs"]["acc"]) / 2),
                     xytext=(-30, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
    axes[1].legend(loc="lower right", fontsize=8.5)
    fig.suptitle("MEVA: the same nine experiments before and after the decode fix (4-pass mean, band = spread over passes)",
                 fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_story_gain(results, out):
    """Does picking frames beat uniform sampling? Paired delta with 95% CI, per dataset."""
    style()
    dss = ["MVU-Eval", "CrossView-EgoExo", "CrossView-MEVA"]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True)
    for ax, ds in zip(axes, dss):
        res = results[ds]
        for k, arm in enumerate(("sg", "sgva")):
            xs, ys, lo, hi, sig = [], [], [], [], []
            for B in BUDGETS:
                c = res["contrasts"].get(str(B), {}).get(f"{arm}-fs", {}).get("all")
                if not c:
                    continue
                xs.append(B + (k - 0.5) * 9); ys.append(c["delta"])
                lo.append(c["delta"] - c["ci95"][0]); hi.append(c["ci95"][1] - c["delta"]); sig.append(c["t_p"] < 0.05)
            ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor=ARM_COLOR[arm], elinewidth=1.4, capsize=3)
            for x, y, s in zip(xs, ys, sig):
                ax.plot([x], [y], marker="o", ms=8, color=ARM_COLOR[arm], mfc=ARM_COLOR[arm] if s else SURFACE,
                        mew=1.8, label=PLAIN[arm] if x == xs[0] else None)
                ax.annotate(f"{y:+.1f}", (x, y), xytext=(-7 if k == 0 else 7, 0), textcoords="offset points",
                            ha="right" if k == 0 else "left", va="center", fontsize=8, color=INK2)
        ax.axhline(0, color=RULE, lw=1)
        ax.set_title(DS_PLAIN[ds], fontsize=9.5)
        ax.set_xticks(BUDGETS)
        ax.set_xlim(8, 116)
        ax.set_xlabel("frames shown to the model")
        ax.grid(False, axis="x")
    axes[0].set_ylabel("points vs uniform sampling\n(same questions, paired)")
    axes[0].annotate("above 0 = picking frames helps", (0.02, 0.97), xycoords="axes fraction", va="top", fontsize=8.5, color=INK2)
    handles, labels = axes[2].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Does picking frames beat uniform sampling? Whisker = 95% CI, filled = significant (p < 0.05)",
                 fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, 0.07, 1, 0.94))
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_story_tasks(res, out, B="96"):
    """Where the MEVA gain comes from: per task at one budget."""
    style()
    tasks = res["tasks"]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    x = np.arange(len(tasks)); w = 0.26
    for k, arm in enumerate(("fs", "sg", "sgva")):
        c = res["cells"][B][arm]
        ys = [c["per_task"][t]["acc"] for t in tasks]
        ax.bar(x + (k - 1) * w, ys, w * 0.92, color=ARM_COLOR[arm], label=PLAIN[arm], zorder=3)
        for xi, y in zip(x + (k - 1) * w, ys):
            ax.annotate(f"{y:.0f}", (xi, y), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8, color=INK2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{short_task(t)}\n{res['cells'][B]['fs']['per_task'][t]['n_ids']} questions" for t in tasks])
    ax.set_ylabel("accuracy (%)")
    ax.set_ylim(0, 70)
    ax.grid(False, axis="x")
    ax.legend(loc="upper left", fontsize=8.5)
    ax.set_title(f"MEVA at {B} frames: the gain is on Spatial and Event-Ordering questions", fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_story_cost(out):
    """Seconds per question at 64 frames on MEVA: first answer vs a repeat answer."""
    style()
    # medians of the tqdm per-iteration times (pass 1 / passes 2-4) from the shard logs, MEVA 64 frames
    first = {"fs": 15, "sg": 51, "sgva": 42}
    repeat = {"fs": 12, "sg": 2, "sgva": 2}
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    arms = ["fs", "sg", "sgva"]; x = np.arange(len(arms)); w = 0.36
    b1 = ax.bar(x - w / 2, [first[a] for a in arms], w, color=[ARM_COLOR[a] for a in arms], zorder=3, label="first answer (decode + pick + answer)")
    b2 = ax.bar(x + w / 2, [repeat[a] for a in arms], w, color=[ARM_COLOR[a] for a in arms], alpha=0.45, zorder=3, label="each repeat answer (selection reused)")
    for bars in (b1, b2):
        for b in bars:
            ax.annotate(f"{b.get_height():.0f} s", (b.get_x() + b.get_width() / 2, b.get_height()), xytext=(0, 3),
                        textcoords="offset points", ha="center", fontsize=8.5, color=INK2)
    ax.set_xticks(x); ax.set_xticklabels([PLAIN[a] for a in arms])
    ax.set_ylabel("seconds per question")
    ax.grid(False, axis="x")
    ax.legend(fontsize=8.5, loc="upper right")
    ax.set_title("Seconds per question, MEVA at 64 frames, one GPU\npicking segments is a one-off 40–50 s; uniform sampling re-decodes the clips every time", fontsize=9.5)
    ax.set_ylim(0, 58)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def story_figs(results, old_meva, figs_dir):
    fig_story_meva(results["CrossView-MEVA"], old_meva, os.path.join(figs_dir, "fig_story_meva.png"))
    fig_story_gain(results, os.path.join(figs_dir, "fig_story_gain.png"))
    fig_story_tasks(results["CrossView-MEVA"], os.path.join(figs_dir, "fig_story_tasks.png"))
    fig_story_cost(os.path.join(figs_dir, "fig_story_cost.png"))


if __name__ == "__main__":
    main()
