"""Selection-accuracy diagnostic for the clip-selection methods (no GPU).

Reads the eval results JSONL(s) (rows carry ``frame_alloc.selected``) plus the
question subset, and reports per method:
  (a) |selected| distribution, %ALL, fallback counts — catches the route arm
      degenerating to always-ALL (safe but useless) or over-pruning;
  (b) on questions whose text names exactly ONE video ("In Video 2 ..."):
      recall of the named video in the selected set (parseable ground truth);
  (c) on questions with video-identity options ("A. Video 1 / B. Video 2 /
      C. Both ..."): how often route correctly kept ALL, and whether a top-1
      selector agrees with the gold option's video;
  (d) accuracy conditioned on the named video being kept vs dropped.

Usage:
  python analysis/clip_selection_diagnostic.py \
      --results 'bench/results/bench_cvbench_temporal_subset_internvl_clipsel*.jsonl' \
      --subset analysis/cvbench_temporal_subset.json
"""
import argparse
import glob
import json
import re
from collections import Counter, defaultdict

VIDEO_RE = re.compile(r"[Vv]ideo\s*(\d+)")


import os


def load_rows(patterns):
    rows = []
    for pat in patterns:
        paths = sorted(glob.glob(pat))
        if not paths and os.path.exists(pat):
            paths = [pat]
        if not paths:
            print(f"warning: no files match {pat}")
            continue
        for p in paths:
            with open(p) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            pass
    return rows


def gold_option_video(rec):
    """The single video number named in the GOLD option text, else None."""
    letter = str(rec.get("answer", "")).strip().upper()
    for o in rec.get("options", []):
        if o.strip().upper().startswith(letter + "."):
            nums = set(VIDEO_RE.findall(o))
            return int(next(iter(nums))) if len(nums) == 1 else None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", nargs="+", required=True,
                    help="results JSONL path(s) or glob(s)")
    ap.add_argument("--subset", required=True)
    args = ap.parse_args()

    recs = {r["id"]: r for r in json.load(open(args.subset))}
    q_named = {}      # id -> the single video number the QUESTION names
    q_identopt = set()  # ids whose OPTIONS reference video identities
    for i, r in recs.items():
        nums = {int(n) for n in VIDEO_RE.findall(r["question"])}
        if len(nums) == 1:
            q_named[i] = next(iter(nums))
        if any(VIDEO_RE.search(o) for o in r["options"]):
            q_identopt.add(i)

    rows = [r for r in load_rows(args.results)
            if (r.get("frame_alloc") or {}).get("selected") is not None]
    if not rows:
        raise SystemExit("no rows with frame_alloc.selected found")

    by_method = defaultdict(list)
    for r in rows:
        by_method[r["method"]].append(r)

    for method, mrows in sorted(by_method.items()):
        # selection is deterministic per question -> analyze one row per id,
        # but keep every row for accuracy (passes differ only in sampling)
        per_id = {}
        inconsistent = set()
        for r in mrows:
            first = per_id.setdefault(r["id"], r)
            if r["frame_alloc"]["selected"] != first["frame_alloc"]["selected"]:
                inconsistent.add(r["id"])   # resume-after-cache-change can do this
        n_q, n_rows = len(per_id), len(mrows)
        acc = 100.0 * sum(r["correct"] for r in mrows) / n_rows

        sizes = Counter()
        n_all = 0
        fallbacks = Counter()
        sum_frames = []
        for r in per_id.values():
            fa = r["frame_alloc"]
            sel, K = fa["selected"], fa.get("K", len(fa.get("durations_s", [])))
            sizes[len(sel)] += 1
            n_all += (len(sel) == K)
            fallbacks[fa.get("selection_fallback") or "none"] += 1
            sum_frames.append(fa.get("sum_nframes"))

        print(f"\n=== {method} ===")
        print(f"questions={n_q} rows={n_rows} accuracy={acc:.1f}%")
        if inconsistent:
            print(f"WARNING: {len(inconsistent)} id(s) have differing 'selected' "
                  f"across rows (resumed run with a changed summary cache?) — "
                  f"kept/dropped buckets below use each id's first row: "
                  f"{sorted(inconsistent)[:10]}")
        print(f"|selected| dist: {dict(sorted(sizes.items()))}  "
              f"ALL-kept: {n_all}/{n_q} ({100.0 * n_all / n_q:.0f}%)")
        print(f"fallbacks: {dict(fallbacks)}")
        good = [s for s in sum_frames if s]
        if good:
            print(f"mean frames shown: {sum(good) / len(good):.1f}")

        # (b) + (d): questions naming exactly one video
        named = [(i, r) for i, r in per_id.items() if i in q_named]
        if named:
            kept = [(i, r) for i, r in named
                    if q_named[i] in r["frame_alloc"]["selected"]]
            print(f"named-video questions: {len(named)}; named clip kept "
                  f"(recall): {len(kept)}/{len(named)}")
            for label, subset_ids in (("kept", {i for i, _ in kept}),
                                      ("dropped", {i for i, _ in named} - {i for i, _ in kept})):
                sub = [r for r in mrows if r["id"] in subset_ids]
                if sub:
                    a = 100.0 * sum(r["correct"] for r in sub) / len(sub)
                    print(f"  accuracy when named clip {label}: {a:.1f}% "
                          f"(n={len(sub)} rows)")

        # (c): video-identity-option questions
        ident = [(i, r) for i, r in per_id.items() if i in q_identopt]
        if ident:
            kept_all = sum(1 for i, r in ident
                           if len(r["frame_alloc"]["selected"]) ==
                           r["frame_alloc"].get("K", 0))
            print(f"video-identity-option questions: {len(ident)}; kept ALL for "
                  f"{kept_all} ({100.0 * kept_all / len(ident):.0f}%)")
            # agreement is only defined where the gold option names exactly ONE
            # video (~half of identity-option golds are 'Both'/orderings -> None)
            top1 = [(i, r) for i, r in ident
                    if len(r["frame_alloc"]["selected"]) == 1
                    and gold_option_video(recs[i]) is not None]
            skipped = sum(1 for i, r in ident
                          if len(r["frame_alloc"]["selected"]) == 1
                          and gold_option_video(recs[i]) is None)
            agree = [i for i, r in top1
                     if gold_option_video(recs[i]) == r["frame_alloc"]["selected"][0]]
            if top1 or skipped:
                print(f"  single-clip selections with a single-video gold: "
                      f"{len(top1)}; selector matched it on {len(agree)} "
                      f"({skipped} skipped: gold names 0 or >1 videos)")


if __name__ == "__main__":
    main()
