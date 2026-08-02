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

``frame_select`` rows store ``selected_per_video`` (frame counts) rather than
``selected``; the set of videos with a nonzero count is derived as its
``selected``, and those rows additionally get (e): the share of the kept
frames that came from the question-named video, against the uniform 1/K
baseline (candidates are equal per video, so uniform selection gives 1/K).

Usage:
  python analysis/clip_selection_diagnostic.py \
      --results 'bench/results/bench_crossview_meva1033_subset_internvl_clipsel*.jsonl' \
      --subset analysis/crossview_meva1033_subset.json \
      [--json analysis/sampler_diag.json]
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
    ap.add_argument("--json", default=None,
                    help="dump the computed stats (incl. per-question named "
                         "shares) to this path")
    args = ap.parse_args()

    recs = {r["id"]: r for r in json.load(open(args.subset))}
    q_named = {}      # id -> the single video number the QUESTION names
    q_identopt = set()  # ids whose OPTIONS reference video identities
    g_named = {}      # id -> the single video number the GOLD OPTION names
    for i, r in recs.items():
        nums = {int(n) for n in VIDEO_RE.findall(r["question"])}
        if len(nums) == 1:
            q_named[i] = next(iter(nums))
        if any(VIDEO_RE.search(o) for o in r["options"]):
            q_identopt.add(i)
        gv = gold_option_video(r)
        if gv is not None:
            g_named[i] = gv

    rows = []
    for r in load_rows(args.results):
        fa = r.get("frame_alloc") or {}
        if fa.get("selected") is None and fa.get("selected_per_video"):
            fa["selected"] = sorted(int(v) for v, c
                                    in fa["selected_per_video"].items() if c > 0)
        if fa.get("selected") is not None:
            rows.append(r)
    if not rows:
        raise SystemExit("no rows with frame_alloc.selected found")

    by_method = defaultdict(list)
    for r in rows:
        by_method[r["method"]].append(r)

    dump = {}
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

        mstats = dump[method] = {
            "n_q": n_q, "n_rows": n_rows, "acc": round(acc, 2),
            "sizes": {str(k): v for k, v in sorted(sizes.items())},
            "all_kept_pct": round(100.0 * n_all / n_q, 1),
            "fallbacks": dict(fallbacks),
            "mean_frames": round(sum(good) / len(good), 1) if good else None,
        }

        # (b) + (d) + (e), against two parseable ground truths:
        #   named       — the QUESTION text names exactly one video
        #   gold_named  — the GOLD OPTION names exactly one video ("B. Video 3");
        #                 on MVU-Eval the former is empty and the latter is the
        #                 usable signal (the answer IS a clip identity)
        for gt_key, gt_label, gt_map in (("named", "question-named", q_named),
                                         ("gold_named", "gold-named", g_named)):
            named = [(i, r) for i, r in per_id.items() if i in gt_map]
            if not named:
                continue
            kept = [(i, r) for i, r in named
                    if gt_map[i] in r["frame_alloc"]["selected"]]
            uni_recall = sum(1.0 / (recs[i].get("orig_num_cameras") or 1)
                             for i, _ in named) / len(named)
            print(f"{gt_label}-video questions: {len(named)}; {gt_label} clip kept "
                  f"(recall): {len(kept)}/{len(named)} "
                  f"({100.0 * len(kept) / len(named):.1f}%; random single pick "
                  f"would keep it {100.0 * uni_recall:.1f}%)")
            mstats[gt_key] = {"n": len(named), "kept": len(kept),
                              "recall_kept": round(100.0 * len(kept) / len(named), 1),
                              "random_pick_recall": round(100.0 * uni_recall, 1)}
            for label, subset_ids in (("kept", {i for i, _ in kept}),
                                      ("dropped", {i for i, _ in named} - {i for i, _ in kept})):
                sub = [r for r in mrows if r["id"] in subset_ids]
                if sub:
                    a = 100.0 * sum(r["correct"] for r in sub) / len(sub)
                    print(f"  accuracy when {gt_label} clip {label}: {a:.1f}% "
                          f"(n={len(sub)} rows)")
                    mstats[gt_key][f"acc_{label}"] = round(a, 1)
                    mstats[gt_key][f"n_rows_{label}"] = len(sub)

            # (e) share of kept frames, for methods recording per-video counts
            per_q = {}
            for i, r in named:
                fa = r["frame_alloc"]
                spv = fa.get("selected_per_video")
                if not spv or not fa.get("n_selected"):
                    continue
                per_q[i] = {
                    "share": round(spv.get(str(gt_map[i]), 0)
                                   / fa["n_selected"], 4),
                    "named": gt_map[i], "K": fa["K"],
                    "n_candidates": fa.get("n_candidates"),
                    "n_selected": fa["n_selected"],
                    "budget": fa.get("budget"),
                    "named_kept": gt_map[i] in fa["selected"],
                    "selected_per_video": spv,
                }
            if per_q:
                shares = sorted(d["share"] for d in per_q.values())
                uni = [1.0 / d["K"] for d in per_q.values()]
                mean_share = sum(shares) / len(shares)
                med_share = shares[len(shares) // 2]
                mean_uni = sum(uni) / len(uni)
                print(f"  {gt_label}-clip share of kept frames: mean {mean_share:.3f} "
                      f"/ median {med_share:.3f} vs uniform 1/K baseline "
                      f"{mean_uni:.3f} (n={len(shares)})")
                mstats[gt_key].update(
                    mean_share=round(mean_share, 4),
                    median_share=round(med_share, 4),
                    mean_uniform_share=round(mean_uni, 4))
                mstats[f"per_question_{gt_key}"] = per_q

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
            mstats["ident"] = {"n": len(ident), "kept_all": kept_all,
                               "top1_with_single_gold": len(top1),
                               "top1_agree": len(agree)}

    if args.json:
        json.dump(dump, open(args.json, "w"), indent=1)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
