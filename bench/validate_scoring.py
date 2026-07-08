"""CPU-only gate: re-score an existing eval JSON through the bench parse+metrics
path and confirm it reproduces the stored accuracy. No GPU / no model load.

Usage (from repo root):
  python -m bench.validate_scoring [path/to/eval_*.json]
Default: the canonical 60-Q CrossView Qwen run (expected 19/60 = 31.7%).
"""
import json
import os
import sys

from .reuse import parse_choice, gt_choice, is_yesno, REPO
from . import metrics

DEFAULT = os.path.join(REPO, "Video-R1", "src", "r1-v", "eval_results",
                       "eval_crossview_subset_qwen3vl.json")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    blob = json.load(open(path))
    res = blob.get("results", blob)
    rows, mismatch = [], 0
    for r in res:
        yn = is_yesno(r["options"])
        pred = parse_choice(r.get("output", ""), yn)
        gold = gt_choice(r["answer"], yn)
        if "prediction" in r and pred != r["prediction"]:
            mismatch += 1
        rows.append(dict(
            id=r["id"], task_type=r["task_type"], source=r.get("source"),
            orig_num_cameras=r.get("orig_num_cameras"), cap_answer_safe=r.get("cap_answer_safe"),
            num_videos=r.get("num_videos", 0), method="centralized", backend="(stored-output)",
            prediction=pred, gold=gold,
            correct=(pred.strip().upper() == gold.strip().upper()), abstained=(pred == "")))
    s = metrics.summarize(rows)
    print(f"file: {path}")
    print(f"re-scored overall: {s['overall']['correct']}/{s['overall']['total']} "
          f"= {s['overall']['acc']*100:.1f}%")
    print(f"prediction mismatches vs stored 'prediction': {mismatch}")
    stored = blob.get("summary", {}).get("overall_acc")
    if stored is not None:
        print(f"stored summary.overall_acc: {stored:.2f}%")
    print("by task_type:", {k: f"{v['correct']}/{v['total']}" for k, v in s["by_task_type"].items()})


if __name__ == "__main__":
    main()
