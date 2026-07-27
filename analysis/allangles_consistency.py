#!/usr/bin/env python3
"""All-Angles-Bench paired-question consistency report (the paper's CC/WW/IC
split): 85% of AAB questions have a rephrased/perspective-swapped twin
(``pair_idx``); a model with genuine multi-view understanding should get both
right (CC) or both wrong (WW) — answering them inconsistently (IC) signals
view-dependent guessing. High IC on e.g. relative-distance is the paper's
headline failure mode, so we report IC alongside plain accuracy.

Reads the harness result JSONL(s) plus the subset JSON, pairs rows within each
(method, backend, pass_idx) leg, and prints per-leg and per-task CC/WW/IC
percentages (over pairs whose BOTH members were answered in that leg).

Usage (no GPU):
  python3 analysis/allangles_consistency.py \
      --results 'bench/results/bench_allangles_*.jsonl' \
      --subset analysis/allangles_dev_subset.json
"""
import argparse
import glob
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def load_rows(patterns):
    rows = []
    for pat in patterns:
        for path in sorted(glob.glob(pat)):
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
    return rows


def classify(a_correct, b_correct):
    if a_correct and b_correct:
        return "CC"
    if not a_correct and not b_correct:
        return "WW"
    return "IC"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", nargs="+", required=True,
                    help="result JSONL path(s) or glob(s)")
    ap.add_argument("--subset", required=True,
                    help="the subset JSON the legs were run on (source of pair_idx "
                         "for older rows that lack it)")
    args = ap.parse_args()

    subset = {str(r["id"]): r for r in json.load(open(args.subset))}
    rows = load_rows(args.results)
    if not rows:
        raise SystemExit("no result rows matched")

    legs = defaultdict(dict)  # (method, backend, pass_idx) -> id -> row
    for r in rows:
        rid = str(r["id"])
        pair = r.get("pair_idx") or subset.get(rid, {}).get("pair_idx") or ""
        r["_pair"] = str(pair)
        legs[(r["method"], r["backend"], r.get("pass_idx"))][rid] = r

    print(f"{len(rows)} rows -> {len(legs)} legs   (pairs counted once per leg)\n")
    per_leg_summary = defaultdict(lambda: Counter())
    for key in sorted(legs, key=str):
        by_id = legs[key]
        counted, tally = set(), Counter()
        by_task = defaultdict(Counter)
        for rid, r in by_id.items():
            pid = r["_pair"]
            if not pid or rid in counted or pid not in by_id:
                continue
            counted |= {rid, pid}
            cls = classify(bool(r["correct"]), bool(by_id[pid]["correct"]))
            tally[cls] += 1
            by_task[r["task_type"]][cls] += 1
        n = sum(tally.values())
        method, backend, pass_idx = key
        label = f"{method}/{backend}/pass{pass_idx}"
        if n == 0:
            print(f"{label:48s}  no complete pairs")
            continue
        pct = {k: 100.0 * tally[k] / n for k in ("CC", "WW", "IC")}
        print(f"{label:48s}  pairs={n:4d}  CC={pct['CC']:5.1f}%  "
              f"WW={pct['WW']:5.1f}%  IC={pct['IC']:5.1f}%")
        for tt in sorted(by_task):
            tn = sum(by_task[tt].values())
            print(f"    {tt:40s}  pairs={tn:3d}  "
                  f"IC={100.0 * by_task[tt]['IC'] / tn:5.1f}%")
        per_leg_summary[(method, backend)].update(tally)

    print("\npooled over passes:")
    for (method, backend), tally in sorted(per_leg_summary.items()):
        n = sum(tally.values())
        print(f"  {method}/{backend}: pairs={n}  "
              f"CC={100.0 * tally['CC'] / n:5.1f}%  "
              f"WW={100.0 * tally['WW'] / n:5.1f}%  "
              f"IC={100.0 * tally['IC'] / n:5.1f}%")


if __name__ == "__main__":
    main()
