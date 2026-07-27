#!/usr/bin/env python
"""Random-guessing ("chance") accuracy for a question subset, from the actual
option lists.

Benchmarks are rarely uniform k-way multiple-choice sets: option counts vary by
question (some subsets mix yes/no rows with 3-, 4-, or more-way choices).  So
"what would a model score if it just guessed?" is not one number -- it is the
per-question expectation

    chance = mean over questions of 1 / (number of answer options)

i.e. the accuracy of a guesser that picks uniformly at random among the options
it is actually shown.  Pooled over a set this is the mean of the per-question
chance levels, so it differs by task category.

Malformed-row caveat: if a row's choices are concatenated into a single string
("A. ... , B. ... , C. ... , D. ..."), a naive len(options) reads it as 1
option (chance 100%).  We detect embedded letter markers and count them.

    python -m bench.chance_level --subset analysis/crossview_meva1033_subset.json
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# "A. " at the start of a string, or ", B. " / "; C. " inside one -- the marker
# pattern used to recover the option count from a concatenated options string.
_MARKER = re.compile(r"(?:^|[,;]\s*)([A-M])\.\s")


def n_options(row):
    """Effective number of answer options for one subset row."""
    opts = row.get("options") or []
    if len(opts) == 1:
        markers = set(_MARKER.findall(opts[0]))
        if len(markers) >= 2:          # concatenated choices (see module docstring)
            return len(markers)
    return len(opts)


def load_rows(path):
    with open(path) as fh:
        return json.load(fh)


def chance_table(path):
    """-> (per_task, overall, detail, provenance).

    per_task : task_type -> chance in accuracy %
    overall  : chance in accuracy % over every question
    detail   : task_type -> {"n": int, "hist": {n_options: count}}
    """
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


def chance_for(task_type, path):
    """Chance % for one task_type, or the pooled chance when task_type is None."""
    per_task, overall, _, _ = chance_table(path)
    return overall if task_type is None else per_task[task_type]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", required=True,
                    help="question subset JSON (list of records with options + task_type)")
    args = ap.parse_args()

    per_task, overall, detail, prov = chance_table(args.subset)
    print(f"\nRandom-guessing baseline   (source: {prov})")
    print("chance = mean over questions of 1 / (number of answer options)\n")
    print(f"{'task type':40s} {'n':>5s} {'option counts':>20s} {'chance %':>9s}")
    print("-" * 78)
    for task in sorted(per_task, key=lambda t: -per_task[t]):
        d = detail.get(task, {})
        print(f"{task:40s} {d.get('n', 0):5d} {str(d.get('hist', '')):>20s} "
              f"{per_task[task]:9.2f}")
    print("-" * 78)
    n_all = sum(d["n"] for d in detail.values())
    print(f"{'OVERALL (pooled)':40s} {n_all:5d} {'':>20s} {overall:9.2f}\n")


if __name__ == "__main__":
    main()
