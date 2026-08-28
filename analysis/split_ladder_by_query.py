#!/usr/bin/env python3
"""Split the segment-selection ladder by whether the scorer had a content
query.

Under the ``_opt`` arms the selection scorer ranks segments against the
answer OPTIONS. On a large share of records every option is a bare clip
reference — "Video 3", "II -> I -> III" — so the ranking carried no content
at all. This script joins every registered row to its record's options, flags
those option sets with the harness's own rule (segment_select._CLIP_REF_RE,
the same one that stamps ``options_are_clip_refs`` on new rows), and reports
each dataset's ladder for content-option and clip-reference records
separately, with paired per-record tests for the arm contrasts.

Reads the rescored rows (bench/results/rescored/), never the raw ones — the
MVU fs64/fs96 raw files predate the parser fix and hold other methods too.

Usage (cvbench env):
  python analysis/split_ladder_by_query.py            # table to stdout
  python analysis/split_ladder_by_query.py --json analysis/records/split_ladder.json
"""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict

import numpy as np
from scipy import stats

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from bench.methods.clip_select import option_texts          # noqa: E402
from bench.methods.segment_select import _options_are_clip_refs  # noqa: E402

RES = os.path.join(REPO, "bench", "results", "rescored")
# dataset -> (subset json, file stem, {arm: tag}, baseline method filter)
DATASETS = {
    "MVU-Eval": ("mvueval_qa.json", "bench_mvueval_qa_internvl",
                 {"fs": "fs", "sg": "sg", "sgv": "sgv", "sgva": "sgva"}),
    "CrossView-EgoExo": ("crossview_egoexo500.json", "bench_crossview_egoexo500_internvl",
                         {"fs": "fs", "sg": "sg", "sgva": "sgva"}),
    # MEVA reads the post-remux legs (TAG=_mp4*): the bare fs/sg/sgva tags on
    # this subset decoded the wrong frames (see hosting/remux_avi.py) and are
    # kept on disk only to size that defect.
    "CrossView-MEVA": ("crossview_meva1033_subset.json",
                       "bench_crossview_meva1033_subset_internvl",
                       {"fs": "mp4fs", "sg": "mp4sg", "sgva": "mp4sgva"}),
}
BUDGETS = (32, 64, 96)
BASELINE_METHOD = "cvbench_native"


def load_leg(stem, tag, budget, method_filter=None):
    """{id: mean correctness over passes} for one leg."""
    per_id = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(RES, f"{stem}_{tag}{budget}_shard*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if method_filter and r.get("method") != method_filter:
                    continue
                per_id[r["id"]].append(1.0 if r.get("correct") else 0.0)
    return {i: float(np.mean(v)) for i, v in per_id.items()}


def paired(a, b, ids):
    """(delta_pts, t_p, sign_p, n) of a - b over the shared ids."""
    x = np.array([a[i] for i in ids])
    y = np.array([b[i] for i in ids])
    d = x - y
    if len(d) < 2 or np.allclose(d, 0):
        return 100 * float(d.mean()) if len(d) else float("nan"), float("nan"), float("nan"), len(d)
    t_p = float(stats.ttest_rel(x, y).pvalue)
    up, down = int((d > 0).sum()), int((d < 0).sum())
    sign_p = float(stats.binomtest(up, up + down).pvalue) if up + down else float("nan")
    return 100 * float(d.mean()), t_p, sign_p, len(d)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", default=None, help="also write the full result here")
    args = ap.parse_args()
    out = {}
    for ds, (subset, stem, arms) in DATASETS.items():
        recs = json.load(open(os.path.join(REPO, "analysis", subset)))
        flag = {r["id"]: _options_are_clip_refs(option_texts(r)) for r in recs}
        task = {r["id"]: r.get("task_type", "?") for r in recs}
        groups = {"clip-ref options": [i for i, f in flag.items() if f],
                  "content options": [i for i, f in flag.items() if not f]}
        print(f"\n== {ds}: {len(recs)} records — clip-ref option sets "
              f"{len(groups['clip-ref options'])} ({100*len(groups['clip-ref options'])/len(recs):.0f}%)")
        by_task = defaultdict(int)
        for i in groups["clip-ref options"]:
            by_task[task[i]] += 1
        print("   by task:", ", ".join(f"{k} {v}" for k, v in sorted(by_task.items())))
        out[ds] = {"n": len(recs), "clip_ref_by_task": dict(by_task), "cells": {}}
        for B in BUDGETS:
            legs = {}
            for arm, tag in arms.items():
                legs[arm] = load_leg(stem, tag, B, BASELINE_METHOD if arm == "fs" else None)
            if not legs.get("fs") or not legs.get("sg"):
                continue
            row = {}
            for gname, ids in groups.items():
                ids = [i for i in ids if all(i in legs[a] for a in legs)]
                if not ids:
                    continue
                cell = {"n": len(ids)}
                for arm in legs:
                    cell[f"acc_{arm}"] = 100 * float(np.mean([legs[arm][i] for i in ids]))
                contrasts = [("sg", "fs"), ("sgva", "fs")]
                if "sgv" in legs:
                    contrasts += [("sgv", "sg"), ("sgva", "sgv")]
                else:
                    contrasts += [("sgva", "sg")]
                for a, b in contrasts:
                    d, tp, sp, n = paired(legs[a], legs[b], ids)
                    cell[f"{a}-{b}"] = {"delta": d, "t_p": tp, "sign_p": sp}
                row[gname] = cell
            out[ds]["cells"][B] = row
            print(f"   B={B}")
            for gname, cell in row.items():
                accs = "  ".join(f"{a}={cell[f'acc_{a}']:.2f}" for a in legs)
                cons = "  ".join(f"{k} {v['delta']:+.2f} (t p={v['t_p']:.3f})"
                                 for k, v in cell.items() if isinstance(v, dict))
                print(f"     {gname:18} n={cell['n']:4}  {accs}")
                print(f"     {'':18}        {cons}")
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        json.dump(out, open(args.json, "w"), indent=1)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
