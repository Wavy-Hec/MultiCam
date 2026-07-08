#!/usr/bin/env python3
"""Normalize lmms-eval per-sample logs into the shared record schema.

The InternVL3 path runs through lmms-eval (task mvr_think) with --log_samples,
which writes <output>/<model>/<datetime>_samples_mvr_think.jsonl. Each line has
the full raw model response (with the <think> trace) in `resps`. This converts
those lines into the same schema produced by Video-R1/src/eval_thinking.py so
analyze_failures.py / plot_accuracy.py can treat both models identically.

Shared schema per record:
  id, task_type, num_videos, question, options, answer, output, think, prediction, correct

Usage:
  python3 analysis/parse_lmms_samples.py \
      --samples logs/InternVL3-8B/2026-..._samples_mvr_think.jsonl \
      --out analysis/internvl3_normalized.json
"""
import argparse
import json
import os
import re


def extract_think(text):
    m = re.search(r"<think>\s*(.*?)\s*</think>", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_answer_tag(text):
    m = re.search(r"<answer>\s*(.*?)\s*</answer>", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def parse_choice(text, is_yesno):
    src = extract_answer_tag(text) or text
    if is_yesno:
        m = re.search(r"(?i)\b(yes|no)\b", src)
        return m.group(1).capitalize() if m else src.strip()
    m = re.search(r"(?i)\b([ABCD])\b", src)
    return m.group(1).upper() if m else src.strip()


def first_str(resps):
    """resps is typically [["text"]] or ["text"]; dig out the first string."""
    x = resps
    while isinstance(x, (list, tuple)) and x:
        x = x[0]
    return x if isinstance(x, str) else ""


def num_videos(doc):
    return sum(1 for i in range(1, 5) if doc.get(f"video_{i}"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True, help="lmms-eval *_samples_mvr_think.jsonl")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    results = []
    with open(args.samples) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            doc = rec.get("doc", {})
            output = first_str(rec.get("resps")) or first_str(rec.get("filtered_resps"))
            options = doc.get("options", [])
            is_yesno = all(o.strip().strip(".").lower() in ("yes", "no") for o in options) if options else False
            pred = parse_choice(output, is_yesno)
            gold = str(doc.get("answer", "")).strip()
            gold_norm = gold.capitalize() if is_yesno else gold.upper()
            results.append({
                "id": doc.get("id"),
                "task_type": doc.get("task_type"),
                "num_videos": num_videos(doc),
                "question": doc.get("question"),
                "options": options,
                "answer": doc.get("answer"),
                "output": output,
                "think": extract_think(output),
                "prediction": pred,
                "correct": pred.strip().upper() == gold_norm.strip().upper(),
            })

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump({"results": results}, open(args.out, "w"), indent=2, ensure_ascii=False)
    n_ok = sum(1 for r in results if r["correct"])
    print(f"Normalized {len(results)} records -> {args.out}  ({n_ok} correct)")


if __name__ == "__main__":
    main()
