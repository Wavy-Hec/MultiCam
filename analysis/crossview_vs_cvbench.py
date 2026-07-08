#!/usr/bin/env python3
"""Side-by-side CVBench vs CrossView accuracy table.

Reads the two accuracy_by_cameras.json files written by analyze_failures.py
(one per benchmark) and emits a single markdown comparing each model on each
benchmark: overall accuracy and accuracy by num_videos (1-4, the comparable
range). The benchmarks stay separate (different tasks); this only juxtaposes
the numbers.

Usage:
  python3 analysis/crossview_vs_cvbench.py \
      --cvbench analysis/accuracy_by_cameras.json \
      --crossview analysis/crossview_out/accuracy_by_cameras.json \
      --out analysis/crossview_out/cvbench_vs_crossview.md
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    return json.load(open(path)) if path and os.path.exists(path) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cvbench", default=os.path.join(HERE, "accuracy_by_cameras.json"))
    ap.add_argument("--crossview",
                    default=os.path.join(HERE, "crossview_out", "accuracy_by_cameras.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "crossview_out", "cvbench_vs_crossview.md"))
    args = ap.parse_args()

    cv = load(args.cvbench)
    xv = load(args.crossview)
    if cv is None and xv is None:
        raise SystemExit("neither accuracy file found; run analyze_failures.py first")

    benches = [("CVBench", cv), ("CrossView", xv)]
    models = sorted({m for _, d in benches if d for m in d.get("overall", {})})

    md = ["# CVBench vs CrossView — baseline comparison\n",
          "Separate benchmarks (CVBench = 1–4 *unrelated* clips, association; "
          "CrossView = synchronized multi-cam, capped to ≤4 views here), shown "
          "side-by-side. CrossView numbers are this run's MCQ subset "
          "(temporal / event_ordering / spatial).\n",
          "## Overall accuracy\n",
          "| model | " + " | ".join(b for b, _ in benches) + " |",
          "|---|" + "|".join("---:" for _ in benches) + "|"]
    for m in models:
        cells = []
        for _, d in benches:
            o = (d or {}).get("overall", {}).get(m)
            cells.append(f"{o['acc']:.1f}% ({o['correct']}/{o['total']})" if o else "—")
        md.append(f"| {m} | " + " | ".join(cells) + " |")

    md.append("\n## Accuracy by num_videos the model saw (1–4)\n")
    for m in models:
        md.append(f"\n**{m}**\n")
        md.append("| #videos | " + " | ".join(b for b, _ in benches) + " |")
        md.append("|---:|" + "|".join("---:" for _ in benches) + "|")
        nvs = sorted({int(k) for _, d in benches if d
                      for k in d.get("by_num_videos", {}).get(m, {})})
        for nv in nvs:
            cells = []
            for _, d in benches:
                e = (d or {}).get("by_num_videos", {}).get(m, {}).get(str(nv))
                cells.append(f"{e['acc']:.1f}% (n={e['total']})" if e else "—")
            md.append(f"| {nv} | " + " | ".join(cells) + " |")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w").write("\n".join(md) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
