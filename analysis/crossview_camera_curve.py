#!/usr/bin/env python3
"""Accuracy vs the ORIGINAL number of cameras for CrossView results.

`num_videos` in the result files is capped at 4 (the harness only ingests
video_1..4), so the informative multi-camera axis is `orig_num_cameras` (1-16),
recovered by joining results to analysis/crossview_subset.json by `id`. Also
reports the cap-quality split: ego-exo4d questions whose >4 cap may have dropped
the answer-bearing view (`cap_answer_safe=false`) vs answer-safe ones (all MEVA
+ small-camera ego-exo4d) -- so the lossy-cap numbers can be read as a lower
bound rather than a model verdict.

Outputs (under --out-dir):
  accuracy_by_orig_cameras.json   - by original #cameras / task_type / cap split
  crossview_camera_curve.md       - human-readable summary
  accuracy_vs_orig_cameras.png    - accuracy vs original #cameras, one line/model

Usage:
  python3 analysis/crossview_camera_curve.py \
      qwen3vl=Video-R1/src/r1-v/eval_results/eval_crossview_subset_qwen3vl.json \
      internvl3=analysis/crossview_internvl3_normalized.json \
      --subset analysis/crossview_subset.json --out-dir analysis/crossview_out
"""
import argparse
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    d = json.load(open(path))
    return d["results"] if isinstance(d, dict) and "results" in d else d


def rate(flags):
    c = sum(1 for x in flags if x)
    return {"correct": c, "total": len(flags), "acc": 100 * c / len(flags) if flags else 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="label=path result files")
    ap.add_argument("--subset", default=os.path.join(HERE, "crossview_subset.json"))
    ap.add_argument("--out-dir", default=os.path.join(HERE, "crossview_out"))
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    meta = {r["id"]: r for r in json.load(open(args.subset))}

    out = {"by_orig_cameras": {}, "by_task_type": {}, "cap_split": {}, "overall": {}}
    md = ["# CrossView: accuracy vs original number of cameras\n",
          "`num_videos` is capped at 4 by the harness; this uses `orig_num_cameras` "
          "(the true synchronized-camera count, 1-16) recovered from "
          "`crossview_subset.json`.\n",
          "`cap_answer_safe=false` (ego-exo4d, >4 cameras) means the cap may have "
          "dropped the answer-bearing view -- treat those as a lower bound.\n"]

    for item in args.inputs:
        label, path = item.split("=", 1)
        if not os.path.exists(path):
            print(f"skip {label}: {path} not found")
            continue
        results = load(path)
        by_orig, by_task = defaultdict(list), defaultdict(list)
        safe, lossy = [], []
        ego_safe, ego_lossy = [], []
        unmatched = 0
        for r in results:
            m = meta.get(r["id"])
            if m is None:
                unmatched += 1
                continue
            ok = bool(r.get("correct"))
            by_orig[m["orig_num_cameras"]].append(ok)
            by_task[m["task_type"]].append(ok)
            (safe if m["cap_answer_safe"] else lossy).append(ok)
            if m["source"] == "ego-exo4d":
                (ego_safe if m["cap_answer_safe"] else ego_lossy).append(ok)

        out["overall"][label] = rate([bool(r.get("correct")) for r in results
                                      if r["id"] in meta])
        out["by_orig_cameras"][label] = {str(k): rate(v) for k, v in sorted(by_orig.items())}
        out["by_task_type"][label] = {k: rate(v) for k, v in sorted(by_task.items())}
        out["cap_split"][label] = {
            "answer_safe": rate(safe), "answer_lossy": rate(lossy),
            "ego_answer_safe": rate(ego_safe), "ego_answer_lossy": rate(ego_lossy)}

        ov = out["overall"][label]
        md.append(f"\n## {label} — overall {ov['correct']}/{ov['total']} = {ov['acc']:.1f}%"
                  + (f"  ({unmatched} unmatched ids)" if unmatched else ""))
        md.append("\n**By original #cameras:**\n")
        md.append("| #cameras | acc | n |\n|---:|---:|---:|")
        for k in sorted(by_orig):
            rr = out["by_orig_cameras"][label][str(k)]
            md.append(f"| {k} | {rr['acc']:.0f}% | {rr['total']} |")
        cs = out["cap_split"][label]
        md.append("\n**Cap quality (answer-bearing view retained?):**\n")
        md.append(f"- answer-safe: {cs['answer_safe']['acc']:.1f}% "
                  f"(n={cs['answer_safe']['total']})")
        md.append(f"- answer-lossy (ego-exo4d >4 cap): {cs['answer_lossy']['acc']:.1f}% "
                  f"(n={cs['answer_lossy']['total']}) — lower bound")
        md.append(f"- ego-exo4d safe vs lossy: "
                  f"{cs['ego_answer_safe']['acc']:.1f}% (n={cs['ego_answer_safe']['total']}) "
                  f"vs {cs['ego_answer_lossy']['acc']:.1f}% (n={cs['ego_answer_lossy']['total']})")

    json.dump(out, open(os.path.join(args.out_dir, "accuracy_by_orig_cameras.json"), "w"),
              indent=2, ensure_ascii=False)
    open(os.path.join(args.out_dir, "crossview_camera_curve.md"), "w").write("\n".join(md))

    # plot accuracy vs original #cameras
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        models = list(out["by_orig_cameras"].keys())
        cams = sorted({int(k) for m in models for k in out["by_orig_cameras"][m]})
        if cams:
            plt.figure(figsize=(7, 5))
            for m in models:
                ys = [out["by_orig_cameras"][m].get(str(c), {}).get("acc", float("nan")) for c in cams]
                ns = [out["by_orig_cameras"][m].get(str(c), {}).get("total", 0) for c in cams]
                plt.plot(cams, ys, marker="o", label=m)
                for x, y, n in zip(cams, ys, ns):
                    if n:
                        plt.annotate(f"n={n}", (x, y), textcoords="offset points",
                                     xytext=(0, 6), fontsize=8, ha="center")
            plt.xlabel("Original number of synchronized cameras")
            plt.ylabel("Accuracy (%)")
            plt.title("CrossView: accuracy vs original #cameras (model sees ≤4)")
            plt.ylim(0, 100)
            plt.grid(True, alpha=0.3)
            plt.legend()
            plt.tight_layout()
            png = os.path.join(args.out_dir, "accuracy_vs_orig_cameras.png")
            plt.savefig(png, dpi=150)
            print("wrote", png)
    except Exception as e:
        print("plot skipped:", type(e).__name__, e)

    print(f"wrote {args.out_dir}/accuracy_by_orig_cameras.json + crossview_camera_curve.md")


if __name__ == "__main__":
    main()
