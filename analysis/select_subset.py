#!/usr/bin/env python3
"""Select a small, diverse CVBench subset for the qualitative multicam failure pass.

Samples ~N questions that span all 15 task types and the num-videos buckets
(1-2 / 3 / 4 videos per question), so the qualitative read covers how models
scale with the number of "cameras" (videos).

Outputs:
  analysis/subset.json        - selected records (same shape as CVBench.json)
  analysis/subset_videos.txt  - deduped relative video paths referenced by the subset

Run (no GPU needed):
  python3 analysis/select_subset.py --n 40
"""
import argparse
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_SRC = os.path.join(REPO, "Video-R1", "src", "r1-v", "Evaluation", "CVBench.json")

# Illustrative questions referenced in the report; always include if present.
ALWAYS_INCLUDE = [10, 247, 248, 270]


def num_videos(rec):
    return sum(1 for i in range(1, 5) if rec.get(f"video_{i}"))


def video_paths(rec):
    return [rec[f"video_{i}"] for i in range(1, 5) if rec.get(f"video_{i}")]


def select(records, n, per_type_cap):
    by_type = defaultdict(list)
    for r in records:
        by_type[r["task_type"]].append(r)

    chosen, chosen_ids = [], set()

    def take(rec):
        if rec["id"] not in chosen_ids:
            chosen.append(rec)
            chosen_ids.add(rec["id"])

    # 1) pin the illustrative examples
    by_id = {r["id"]: r for r in records}
    for rid in ALWAYS_INCLUDE:
        if rid in by_id:
            take(by_id[rid])

    # 2) build, per task type, an ordering that interleaves num-video buckets
    #    (so a type contributes 2-, 3-, and 4-video questions before repeating a count)
    type_order = {}
    for task_type, group in by_type.items():
        buckets = defaultdict(list)
        for r in group:
            buckets[num_videos(r)].append(r)
        for b in buckets:
            buckets[b].sort(key=lambda r: r["id"])
        interleaved, idx = [], {b: 0 for b in buckets}
        while any(idx[b] < len(buckets[b]) for b in sorted(buckets)):
            for b in sorted(buckets):
                if idx[b] < len(buckets[b]):
                    interleaved.append(buckets[b][idx[b]])
                    idx[b] += 1
        type_order[task_type] = interleaved

    # round-robin ACROSS types, one per type per pass -> every type appears before
    # any type gets a third, guaranteeing all 15 task types are represented
    for pass_i in range(per_type_cap):
        for task_type in sorted(type_order):
            if len(chosen) >= n:
                break
            seq = type_order[task_type]
            if pass_i < len(seq):
                take(seq[pass_i])
        if len(chosen) >= n:
            break

    # 3) top up to n by id order if we are short
    if len(chosen) < n:
        for r in sorted(records, key=lambda r: r["id"]):
            if len(chosen) >= n:
                break
            take(r)

    chosen.sort(key=lambda r: (r["task_type"], num_videos(r), r["id"]))
    return chosen[:n] if n else chosen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--n", type=int, default=40, help="target subset size")
    ap.add_argument("--per-type-cap", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(HERE, "subset.json"))
    ap.add_argument("--videos-out", default=os.path.join(HERE, "subset_videos.txt"))
    args = ap.parse_args()

    with open(args.src) as f:
        records = json.load(f)

    subset = select(records, args.n, args.per_type_cap)

    with open(args.out, "w") as f:
        json.dump(subset, f, indent=2, ensure_ascii=False)

    vids = sorted({v for r in subset for v in video_paths(r)})
    with open(args.videos_out, "w") as f:
        f.write("\n".join(vids) + "\n")

    # report
    by_type = defaultdict(int)
    by_nv = defaultdict(int)
    for r in subset:
        by_type[r["task_type"]] += 1
        by_nv[num_videos(r)] += 1
    print(f"Selected {len(subset)} questions ({len(vids)} unique videos)")
    print(f"  -> {args.out}")
    print(f"  -> {args.videos_out}")
    print("\nBy task type:")
    for k in sorted(by_type):
        print(f"  {by_type[k]:>2}  {k}")
    print("\nBy num videos:")
    for k in sorted(by_nv):
        print(f"  {k} video(s): {by_nv[k]}")


if __name__ == "__main__":
    main()
