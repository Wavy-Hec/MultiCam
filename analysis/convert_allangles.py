#!/usr/bin/env python3
"""Convert All-Angles-Bench (multi-view still-image QA) into the harness record
schema so bench/run_bench.py can evaluate it with the centralized (stitch),
decentralized (per_stream), and native interleaved arms.

Source: data/allangles/data.json from the ch-chenyu/All-Angles-Bench HF dataset
(2,132 questions, 90 scenes, 6 categories, 3-way MCQ A/B/C). Each record's
``image_path`` is an ORDERED list of view images; the question text references
"View 1", "View 2", ... in that order, so order is preserved verbatim into
``image_1..image_N``. ``pair_idx`` is a reciprocal pointer to the record's
rephrased/perspective-swapped twin (85% of questions are paired); the dev
subset samples by PAIR GROUP so both twins always land together, keeping the
CC/WW/IC consistency metric (analysis/allangles_consistency.py) computable.

The EgoHumans scenes ship with the HF download; the Ego-Exo4D scenes (~92% of
questions) require the Ego-Exo4D license. Until those frames are fetched, run
with ``--require-local`` to emit an EgoHumans-only runnable pool — results on
that slice are NOT comparable to published full-benchmark numbers.

Outputs (under analysis/):
  allangles_qa.json           - full converted pool (or the --require-local slice)
  allangles_dev_subset.json   - pair-group-stratified dev subset (~100 questions)

Run (no GPU):
  python3 analysis/convert_allangles.py                       # full pool
  python3 analysis/convert_allangles.py --require-local       # EgoHumans-only
"""
import argparse
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA_ROOT = os.path.join(REPO, "data", "allangles")

LETTERS = ["A", "B", "C"]
MAX_VIEWS = 5  # observed views-per-question distribution: 2 (typical), 4, 5


def task_type_of(category):
    pretty = category.replace("_", " ").title().replace(" ", "-")
    return f"AAB-{pretty}"


def convert(data_json, require_local_root=None):
    stats = Counter()
    items = json.load(open(data_json))
    pool = []
    for item in items:
        stats["read"] += 1
        ans = str(item["answer"]).strip().upper()
        if ans not in LETTERS:
            stats["drop_bad_answer"] += 1
            continue
        views = item["image_path"]
        if not views or len(views) > MAX_VIEWS:
            stats["drop_bad_views"] += 1
            continue
        options = [f"{k}. {item[k]}" for k in LETTERS]
        out = {
            "id": None,  # stable int assigned after global sort
            "task_type": task_type_of(item["category"]),
            "question": item["question"],
            "options": options,
            "answer": ans,
            # provenance / analysis extras (harness ignores unknown keys)
            "source": item["sourced_dataset"],
            "question_type": item["category"],
            "orig_num_cameras": len(views),
            "cap_answer_safe": True,  # nothing is ever dropped
            "pair_idx": "",           # remapped to the twin's new id after sort
            "orig_id": str(item["index"]),
            "orig_pair_idx": str(item["pair_idx"]),
        }
        for i, ip in enumerate(views, 1):
            out[f"image_{i}"] = ip
        if require_local_root:
            if any(not os.path.exists(os.path.join(require_local_root, ip))
                   for ip in views):
                stats["drop_missing_local"] += 1
                continue
        pool.append(out)
        stats["kept"] += 1

    # stable, reproducible id assignment; then remap pair pointers to new ids
    pool.sort(key=lambda r: (r["task_type"], r["source"], int(r["orig_id"])))
    by_orig = {}
    for i, r in enumerate(pool):
        r["id"] = i
        by_orig[r["orig_id"]] = r
    for r in pool:
        twin = by_orig.get(r.pop("orig_pair_idx"))
        r["pair_idx"] = str(twin["id"]) if twin is not None else ""
    return pool, stats


def pair_groups(records):
    """Group records so a question and its twin travel together (singletons for
    unpaired questions and for pairs whose twin fell out of the pool)."""
    by_id = {str(r["id"]): r for r in records}
    seen, groups = set(), []
    for r in records:
        if r["id"] in seen:
            continue
        group = [r]
        seen.add(r["id"])
        twin = by_id.get(r["pair_idx"])
        if twin is not None and twin["id"] not in seen:
            group.append(twin)
            seen.add(twin["id"])
        groups.append(group)
    return groups


def select(records, n):
    """~n-question dev subset stratified by task_type x source, sampled by pair
    group (twins never split; the subset may exceed n by at most one record)."""
    strata = defaultdict(list)
    for g in pair_groups(records):
        r0 = g[0]
        strata[(r0["task_type"], r0["source"])].append(g)
    for key in strata:
        strata[key].sort(key=lambda g: g[0]["id"])

    chosen, idx = [], {k: 0 for k in strata}
    while len(chosen) < n and any(idx[k] < len(strata[k]) for k in strata):
        for k in sorted(strata):
            if len(chosen) >= n:
                break
            if idx[k] < len(strata[k]):
                chosen.extend(strata[k][idx[k]])
                idx[k] += 1
    chosen.sort(key=lambda r: r["id"])
    return chosen


def report(tag, recs):
    by_type = Counter(r["task_type"] for r in recs)
    by_src = Counter(r["source"] for r in recs)
    by_views = Counter(r["orig_num_cameras"] for r in recs)
    paired = sum(1 for r in recs if r["pair_idx"] != "")
    print(f"\n{tag}: {len(recs)} questions")
    print("  by source:", dict(by_src))
    print("  by task_type:")
    for k in sorted(by_type):
        print(f"    {by_type[k]:>4}  {k}")
    print("  by views:", dict(sorted(by_views.items())))
    print(f"  paired (twin in set): {paired}")
    print("  chance floor: 33.33% (uniform 3-way MCQ)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-json", default=os.path.join(DATA_ROOT, "data.json"))
    ap.add_argument("--n", type=int, default=100, help="dev subset size")
    ap.add_argument("--require-local", nargs="?", const=DATA_ROOT, default=None,
                    metavar="DATA_ROOT",
                    help="drop questions whose view images are not on disk under "
                         "this root (EgoHumans-only interim pool while the "
                         "Ego-Exo4D license is pending)")
    ap.add_argument("--out-qa", default=os.path.join(HERE, "allangles_qa.json"))
    ap.add_argument("--out-subset", default=os.path.join(HERE, "allangles_dev_subset.json"))
    args = ap.parse_args()

    pool, stats = convert(args.data_json, require_local_root=args.require_local)
    json.dump(pool, open(args.out_qa, "w"), indent=2, ensure_ascii=False)
    subset = select(pool, args.n)
    json.dump(subset, open(args.out_subset, "w"), indent=2, ensure_ascii=False)

    print("conversion stats:", dict(stats))
    report("FULL POOL", pool)
    report("DEV SUBSET", subset)
    print(f"\nwrote:\n  {args.out_qa}\n  {args.out_subset}")
    if args.require_local:
        print("NOTE: --require-local slice (EgoHumans-only until Ego-Exo4D frames "
              "are fetched) — do not compare to published full-benchmark numbers.")


if __name__ == "__main__":
    main()
