#!/usr/bin/env python
"""Random-guessing ("chance") accuracy for CVBench, from the actual option lists.

CVBench is not a uniform 4-way multiple-choice set: 861 of the 1000 questions
have 4 options and 139 are yes/no.  So "what would a model score if it just
guessed?" is not one number -- it is the per-question expectation

    chance = mean over questions of 1 / (number of answer options)

i.e. the accuracy of a guesser that picks uniformly at random among the options
it is actually shown.  Pooled over a set this is the mean of the per-question
chance levels, so it differs by task category: categories that are all 4-option
sit at 25.0%, while Cross-video Scene Recognition (122 of 149 questions are
yes/no) sits at 45.5%, and the 1000-question pool lands at 28.5%.

Source-data caveat: one row (id 996, Cross-video Procedural Transfer) is
malformed -- its four choices are concatenated into a single string
("A. ... , B. ... , C. ... , D. ..."), so a naive len(options) reads it as 1
option (chance 100%).  We detect embedded letter markers and count it as 4.

    conda activate cvbench
    python -m bench.chance_level        # prints the per-category table
"""
import json
import os
import re
import warnings
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CVBENCH_JSON = os.path.join(REPO, "Video-R1", "src", "r1-v", "Evaluation",
                            "CVBench.json")

# "A. " at the start of a string, or ", B. " / "; C. " inside one -- the marker
# pattern used to recover the option count from a concatenated options string.
_MARKER = re.compile(r"(?:^|[,;]\s*)([A-H])\.\s")

# Frozen fallback (verified 2026-07-22 against CVBench.json): chance % per task
# type, used only if the source json cannot be read.
FALLBACK_CHANCE = {
    "Cross-video Scene Recognition":        45.47,
    "Cross-video Entity Matching":          27.70,
    "Joint-video Spatial Navigating":       26.19,
    "Multi-video Attribute Recognition":    26.09,
    "Multi-video Temporal Reasoning":       25.67,
    "Cross-video Counterfactual Reasoning": 25.48,
    "Cross-video Object Recognition":       25.37,
    "Cross-video Anomaly Detection":        25.30,
    "Cross-video Event Retrieval":          25.00,
    "Joint-video Counting":                 25.00,
    "Multi-view Scene Understanding":       25.00,
    "Joint-video Summarization":            25.00,
    "Multi-video Key-Action Recognition":   25.00,
    "Cross-video Procedural Transfer":      25.00,
    "Video Difference Caption":             25.00,
}
FALLBACK_OVERALL = 28.48


def n_options(row):
    """Effective number of answer options for one CVBench row."""
    opts = row.get("options") or []
    if len(opts) == 1:
        markers = set(_MARKER.findall(opts[0]))
        if len(markers) >= 2:          # concatenated choices (see module docstring)
            return len(markers)
    return len(opts)


def load_rows(path=CVBENCH_JSON):
    with open(path) as fh:
        return json.load(fh)


def chance_table(path=CVBENCH_JSON):
    """-> (per_task, overall, detail, provenance).

    per_task : task_type -> chance in accuracy %
    overall  : chance in accuracy % over every question
    detail   : task_type -> {"n": int, "hist": {n_options: count}}
    """
    if not os.path.exists(path):
        warnings.warn(f"{path} not found -- using frozen fallback chance levels.")
        return dict(FALLBACK_CHANCE), FALLBACK_OVERALL, {}, "frozen fallback"

    per_task_counts = defaultdict(list)
    for row in load_rows(path):
        per_task_counts[row["task_type"]].append(n_options(row))

    per_task, detail = {}, {}
    all_counts = []
    for task, counts in per_task_counts.items():
        per_task[task] = 100.0 * sum(1.0 / k for k in counts) / len(counts)
        detail[task] = {"n": len(counts), "hist": dict(sorted(Counter(counts).items()))}
        all_counts.extend(counts)
    overall = 100.0 * sum(1.0 / k for k in all_counts) / len(all_counts)
    return per_task, overall, detail, os.path.relpath(path, REPO)


def chance_for(task_type, path=CVBENCH_JSON):
    """Chance % for one task_type, or the pooled chance when task_type is None."""
    per_task, overall, _, _ = chance_table(path)
    return overall if task_type is None else per_task[task_type]


def main():
    per_task, overall, detail, prov = chance_table()
    print(f"\nCVBench random-guessing baseline   (source: {prov})")
    print("chance = mean over questions of 1 / (number of answer options)\n")
    print(f"{'task type':40s} {'n':>5s} {'option counts':>20s} {'chance %':>9s}")
    print("-" * 78)
    for task in sorted(per_task, key=lambda t: -per_task[t]):
        d = detail.get(task, {})
        print(f"{task:40s} {d.get('n', 0):5d} {str(d.get('hist', '')):>20s} "
              f"{per_task[task]:9.2f}")
    print("-" * 78)
    n_all = sum(d["n"] for d in detail.values()) if detail else 1000
    print(f"{'OVERALL (pooled)':40s} {n_all:5d} {'':>20s} {overall:9.2f}\n")


if __name__ == "__main__":
    main()
