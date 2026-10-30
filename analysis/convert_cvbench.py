#!/usr/bin/env python3
"""Convert CVBench (cross-video QA, HF Dongyh35/CVBench) into the harness record
schema so bench/run_bench.py can evaluate it.

Source: data/test-00000-of-00001.parquet of the Dongyh35/CVBench HF dataset at
the pinned revision below (1,000 questions over 1,315 clips, 15 task types, 2-4
videos per question; Yes/No or lettered MCQ). The clips ship separately in the
same repo's CVBench.zip (~38 GB) and are NOT fetched here: the blind (text-only)
arm never opens media, and a sighted leg needs the zip extracted under a
VIDEO_ROOT first (records name clips relative to the zip root, e.g.
"0/0Hd95ulYOT8.mp4").

The record shape is the cvbench-final era's, unchanged (ids "cvb-<n>", the
release's raw option strings, source "cvbench"), and so is the output filename,
which result files are keyed on. New legs join the archived full-1000 InternVL3
legs by id (those rows predate the `dataset` stamp, and they live only in
~/cvbench_archive_2026-07-27.tgz under bench/results/). Every question is written — the old
builder dropped questions whose clips were missing on disk, which never fired
on the full set either (0 blocked at the tag).

--order O2 writes the same pool with every question's options in REVERSED
order and the gold letter remapped, the team's O1/O2 control for a gold-position
skew (CVBench's key has D as gold on 140 of 860 four-option questions). Ids are
unchanged, so an O2 leg joins its O1 twin by id. Yes/No questions swap
"Yes."/"No." (the gold stays the answer word). The one row whose four options
are packed into a single string (cvb-996) cannot be reversed and is kept as is;
cvb-431's duplicated "B." prefixes are re-lettered A-D in the reversed order.

Outputs (under analysis/):
  cvbench_full_runnable_subset.json     - the full 1000-question pool (O1)
  cvbench_full_runnable_subset_o2.json  - the same pool, options reversed (--order O2)

Run (no GPU, no videos needed):
  python3 analysis/convert_cvbench.py
  python3 analysis/convert_cvbench.py --order O2
"""
import argparse
import json
import os
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

HF_REPO = "Dongyh35/CVBench"
HF_REVISION = "81dfee5940506da256e3d52b76087307d2fe20f7"   # 2025-08-06, the release
HF_FILE = "data/test-00000-of-00001.parquet"
OUT = os.path.join(HERE, "cvbench_full_runnable_subset.json")
OUT_O2 = os.path.join(HERE, "cvbench_full_runnable_subset_o2.json")
LETTERS = "ABCDEFGHIJKLM"
_PREFIX = re.compile(r"^\s*([A-M])\s*[.)]\s*")


def reverse_options(rec, stats):
    """The O2 twin of one record: options reversed, gold remapped."""
    opts, ans = rec["options"], rec["answer"].strip()
    out = dict(rec)
    if len(opts) < 2:
        stats["o2_kept_unsplittable"] += 1                  # cvb-996: one packed string
        return out
    if all(o.strip().strip(".").lower() in ("yes", "no") for o in opts):
        out["options"] = opts[::-1]
        stats["o2_yesno_swapped"] += 1
        return out
    bodies = [_PREFIX.sub("", o, count=1) for o in opts]
    gold = LETTERS.index(ans.upper())
    out["options"] = [f"{LETTERS[i]}. {b}" for i, b in enumerate(bodies[::-1])]
    out["answer"] = LETTERS[len(opts) - 1 - gold]
    if [m.group(1) for m in map(_PREFIX.match, opts)] != list(LETTERS[:len(opts)]):
        stats["o2_relettered_bad_prefixes"] += 1             # cvb-431: A, B, B, B
    stats["o2_reversed"] += 1
    return out


def clean_video(v):
    """Harness video_paths() uses `if v:` — the literal string 'None' is truthy and
    would try to open a file named None. Map None/''/'None'/'null' -> falsy (None)."""
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "None", "null") else s


def load_release(parquet=None):
    if parquet is None:
        from huggingface_hub import hf_hub_download
        parquet = hf_hub_download(HF_REPO, HF_FILE, repo_type="dataset",
                                  revision=HF_REVISION)
    import pyarrow.parquet as pq
    return sorted(pq.read_table(parquet).to_pylist(), key=lambda r: int(r["id"]))


def convert(rows):
    out, stats = [], Counter()
    for r in rows:
        tid = str(r["id"])
        vids = [clean_video(r.get(f"video_{i}")) for i in range(1, 5)]
        vids = [v for v in vids if v]
        if not vids:
            stats["no_video"] += 1
            continue
        rec = {
            "id": f"cvb-{tid}",
            "task_type": r["task_type"],
            "question": r["question"],
            "options": list(r["options"]),
            "answer": r["answer"],
            "source": "cvbench",
            "question_type": "cvbench_full",
            "orig_num_cameras": len(vids),     # CVBench: # of videos in the question (2-4)
            "cap_answer_safe": True,
            "orig_id": tid,
        }
        for i, v in enumerate(vids, 1):
            rec[f"video_{i}"] = v
        out.append(rec)
    return out, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--parquet", default=None,
                    help="local copy of the release parquet (default: fetch the pinned "
                         "revision into the HF cache)")
    ap.add_argument("--order", choices=("O1", "O2"), default="O1",
                    help="O2: every question's options reversed, gold remapped")
    ap.add_argument("--out", default=None, help="default: the order's file under analysis/")
    args = ap.parse_args()
    args.out = args.out or (OUT if args.order == "O1" else OUT_O2)

    rows = load_release(args.parquet)
    out, stats = convert(rows)
    if args.order == "O2":
        out = [reverse_options(r, stats) for r in out]
    # compact, as the cvbench-final builder wrote it, so the file stays
    # byte-identical to the one the archived legs ran on
    json.dump(out, open(args.out, "w"), ensure_ascii=False)

    print(f"read {len(rows)} release rows -> wrote {len(out)} records -> {args.out}")
    if stats:
        print("  notes:", dict(stats))
    print("  videos/question:", dict(sorted(Counter(x["orig_num_cameras"] for x in out).items())))
    print("  options/question:", dict(sorted(Counter(len(x["options"]) for x in out).items())))
    print("  task types:", len({x["task_type"] for x in out}))


if __name__ == "__main__":
    main()
