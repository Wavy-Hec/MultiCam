#!/usr/bin/env python3
"""Build the single-view experiment pool: the MVU-Eval questions whose text and
options do NOT name a specific video ("Which video ...", "A. Video 2"), because
naming a view already does the picking — the same restriction the mentor's
single-view slides apply. Prints the census (kept/dropped per task, view-count
distribution, projected single-view model calls) and writes the kept records
verbatim (harness schema unchanged) to analysis/mvueval_noview_subset.json.

Run (no GPU): python3 analysis/build_singleview_subset.py
"""
import argparse
import json
import os
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))

# "Video 2", "video2", "Video_2", "second video", "first/last video" — any of
# these lets the question do the view-picking itself
NAMES_VIDEO = re.compile(
    r"\bvideo[\s_]*\d+\b|\b(first|second|third|fourth|fifth|last)\s+video\b",
    re.IGNORECASE)


def names_a_video(rec):
    texts = [rec["question"]] + list(rec["options"])
    return any(NAMES_VIDEO.search(t) for t in texts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", default=os.path.join(HERE, "mvueval_qa.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "mvueval_noview_subset.json"))
    args = ap.parse_args()

    pool = json.load(open(args.qa))
    kept, dropped = [], []
    for r in pool:
        (dropped if names_a_video(r) else kept).append(r)

    json.dump(kept, open(args.out, "w"), indent=2, ensure_ascii=False)

    kt = Counter(r["task_type"] for r in kept)
    dt = Counter(r["task_type"] for r in dropped)
    kv = Counter(r["orig_num_cameras"] for r in kept)
    calls = sum(r["orig_num_cameras"] for r in kept)
    print(f"pool {len(pool)} -> kept {len(kept)} (no video named), "
          f"dropped {len(dropped)} (question/options name a video)")
    print("kept by task:   ", dict(sorted(kt.items())))
    print("dropped by task:", dict(sorted(dt.items())))
    print("kept by views:  ", dict(sorted(kv.items())))
    print(f"single-view model calls per pass: {calls} "
          f"({4 * calls} rows at 4 passes)")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
