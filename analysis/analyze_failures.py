#!/usr/bin/env python3
"""Summarize accuracy and dump failure cases (with reasoning traces) per model.

Consumes one or more normalized result files (label=path), each shaped like
{"results": [ {id, task_type, num_videos, question, options, answer, output,
               think, prediction, correct}, ... ]} -- produced by either
Video-R1/src/eval_thinking.py (Qwen path) or analysis/parse_lmms_samples.py
(InternVL3 path).

For each model it prints accuracy overall / by number-of-videos / by task type,
and writes analysis/<label>_failures.md listing every wrong answer together with
its <think> reasoning trace so failure modes can be read off and categorized.
It also writes analysis/accuracy_by_cameras.json for plot_accuracy.py.

Usage:
  python3 analysis/analyze_failures.py \
      qwen3vl=Video-R1/src/r1-v/eval_results/eval_subset_qwen3vl.json \
      internvl3=analysis/internvl3_normalized.json
"""
import argparse
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    data = json.load(open(path))
    return data["results"] if isinstance(data, dict) and "results" in data else data


def acc_table(results, key):
    buckets = defaultdict(lambda: [0, 0])
    for r in results:
        c = 1 if r.get("correct") else 0
        buckets[r.get(key)][0] += c
        buckets[r.get(key)][1] += 1
    return buckets


def fmt_case(r):
    opts = "\n".join(f"  {o}" for o in (r.get("options") or []))
    think = (r.get("think") or "").strip()
    if not think:
        # no parsed <think>; show the raw output so we still see the model's words
        think = "(no <think> tag parsed) RAW OUTPUT:\n" + (r.get("output") or "").strip()
    return (
        f"### id {r.get('id')} — {r.get('task_type')} — {r.get('num_videos')} video(s)\n\n"
        f"**Q:** {r.get('question')}\n\n"
        f"**Options:**\n{opts}\n\n"
        f"**Gold:** {r.get('answer')}   **Predicted:** {r.get('prediction')}\n\n"
        f"**Reasoning trace:**\n\n> " + think.replace("\n", "\n> ") + "\n"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="label=path pairs")
    ap.add_argument("--out-dir", default=HERE)
    args = ap.parse_args()

    combined = {"by_num_videos": {}, "by_task_type": {}, "overall": {}}

    for item in args.inputs:
        label, path = item.split("=", 1)
        results = load(path)
        total = len(results)
        correct = sum(1 for r in results if r.get("correct"))
        overall = 100 * correct / total if total else 0

        nv = acc_table(results, "num_videos")
        tt = acc_table(results, "task_type")

        print(f"\n===== {label} ({path}) =====")
        print(f"Overall: {correct}/{total} = {overall:.1f}%")
        print("By num videos:")
        for k in sorted(nv, key=lambda x: (x is None, x)):
            c, t = nv[k]
            print(f"  {k} video(s): {c}/{t} = {100*c/t if t else 0:.1f}%")
        print("By task type:")
        for k in sorted(tt, key=lambda x: (x is None, x)):
            c, t = tt[k]
            print(f"  {c}/{t}  {k}")

        combined["overall"][label] = {"correct": correct, "total": total, "acc": overall}
        combined["by_num_videos"][label] = {
            str(k): {"correct": nv[k][0], "total": nv[k][1],
                     "acc": 100 * nv[k][0] / nv[k][1] if nv[k][1] else 0}
            for k in nv}
        combined["by_task_type"][label] = {
            str(k): {"correct": tt[k][0], "total": tt[k][1],
                     "acc": 100 * tt[k][0] / tt[k][1] if tt[k][1] else 0}
            for k in tt}

        # failure dump
        wrong = [r for r in results if not r.get("correct")]
        wrong.sort(key=lambda r: (r.get("num_videos") or 0, r.get("task_type") or ""))
        md = [f"# {label}: failure cases ({len(wrong)}/{total} wrong, "
              f"overall {overall:.1f}%)\n",
              "Grouped to read off *why* the model fails on multi-video reasoning.\n"]
        cur = None
        for r in wrong:
            if r.get("task_type") != cur:
                cur = r.get("task_type")
                md.append(f"\n## {cur}\n")
            md.append(fmt_case(r))
        out_md = os.path.join(args.out_dir, f"{label}_failures.md")
        open(out_md, "w").write("\n".join(md))
        print(f"  wrote {out_md} ({len(wrong)} cases)")

    out_json = os.path.join(args.out_dir, "accuracy_by_cameras.json")
    json.dump(combined, open(out_json, "w"), indent=2, ensure_ascii=False)
    print(f"\nwrote {out_json}")


if __name__ == "__main__":
    main()
