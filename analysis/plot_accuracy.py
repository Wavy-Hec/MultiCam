#!/usr/bin/env python3
"""Plot accuracy vs. number of videos ("cameras") from accuracy_by_cameras.json.

Consumes the JSON written by analyze_failures.py and produces:
  analysis/accuracy_vs_cameras.png   - accuracy vs #videos, one line per model
  analysis/accuracy_by_task.png      - per-task-type accuracy bars per model

Usage:
  python3 analysis/plot_accuracy.py
  python3 analysis/plot_accuracy.py --in analysis/accuracy_by_cameras.json
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(HERE, "accuracy_by_cameras.json"))
    ap.add_argument("--out-cameras", default=os.path.join(HERE, "accuracy_vs_cameras.png"))
    ap.add_argument("--out-tasks", default=os.path.join(HERE, "accuracy_by_task.png"))
    ap.add_argument("--title", default="CVBench", help="benchmark name used in plot titles")
    args = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    data = json.load(open(args.inp))
    by_nv = data["by_num_videos"]
    models = list(by_nv.keys())

    # ---- accuracy vs #videos ----
    cams = sorted({int(k) for m in models for k in by_nv[m]})
    plt.figure(figsize=(7, 5))
    for m in models:
        ys = [by_nv[m].get(str(c), {}).get("acc", float("nan")) for c in cams]
        ns = [by_nv[m].get(str(c), {}).get("total", 0) for c in cams]
        plt.plot(cams, ys, marker="o", label=m)
        for x, y, n in zip(cams, ys, ns):
            if n:
                plt.annotate(f"n={n}", (x, y), textcoords="offset points", xytext=(0, 6),
                             fontsize=8, ha="center")
    plt.xticks(cams)
    plt.xlabel("Number of videos per question (\"cameras\")")
    plt.ylabel("Accuracy (%)")
    plt.title(f"{args.title}: accuracy vs. number of videos")
    plt.ylim(0, 100)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(args.out_cameras, dpi=150)
    print("wrote", args.out_cameras)

    # ---- per-task accuracy ----
    by_tt = data["by_task_type"]
    tasks = sorted({k for m in models for k in by_tt[m]})
    plt.figure(figsize=(12, 6))
    x = np.arange(len(tasks))
    w = 0.8 / max(1, len(models))
    for i, m in enumerate(models):
        ys = [by_tt[m].get(t, {}).get("acc", 0) for t in tasks]
        plt.bar(x + i * w, ys, width=w, label=m)
    plt.xticks(x + w * (len(models) - 1) / 2, tasks, rotation=60, ha="right", fontsize=8)
    plt.ylabel("Accuracy (%)")
    plt.ylim(0, 100)
    plt.title(f"{args.title}: accuracy by task type")
    plt.legend()
    plt.tight_layout()
    plt.savefig(args.out_tasks, dpi=150)
    print("wrote", args.out_tasks)


if __name__ == "__main__":
    main()
