"""Re-derive prediction/correct/abstained from the stored response_text.

`Video-R1/src/eval_thinking.py:parse_choice` used to refuse any tagless answer
longer than 40 characters. Under REASONING=0 InternVL3 answers with the letter
AND the option text and no tags at all --

    A. They approach and stay near each other (within a few meters)

-- 63 characters, so it scored as an abstention, i.e. wrong. The damage is
asymmetric across arms, because how often a model answers without the tags
depends on the arm's prompt scaffold -- so it biases arm-vs-arm comparisons
rather than shifting everything equally. Every row stores response_text, so this
is recoverable on disk with no GPU time.

Non-destructive: writes bench/results/rescored/<same basename> and never touches
the original.

The rescored copies go in a SUBDIRECTORY, not beside the originals, because
every consumer in the repo globs `bench_..._shard*.jsonl` — and `shard*` happily
matches `shard0_rescored.jsonl`, so a sibling file silently doubles every row in
export_question_records.py, mvueval_slide_stats.py and bench/plots.py.

    python3 analysis/rescore_answers.py                       # all result files
    python3 analysis/rescore_answers.py --results 'bench_crossview*t1iv*.jsonl'
    python3 analysis/rescore_answers.py --dry-run             # table only
"""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from bench.reuse import parse_choice, gt_choice, is_yesno, letters_of  # noqa: E402
from bench import metrics  # noqa: E402

RES = os.path.join(REPO, "bench", "results")
RESCORED = os.path.join(RES, "rescored")


def load_subset(dataset, cache):
    """The subset JSON a leg was run against, keyed by record id.

    run_bench stamps `dataset` as the subset basename minus .json, so the path
    is recoverable from the rows alone -- no need to reconstruct the launch.
    """
    if dataset not in cache:
        path = os.path.join(HERE, f"{dataset}.json")
        if not os.path.exists(path):
            cache[dataset] = None
        else:
            cache[dataset] = {r["id"]: r for r in json.load(open(path))}
    return cache[dataset]


def rescore_row(r, qrec):
    """Returns (prediction, correct, abstained) under the fixed parser.

    A row that carries an `error` is left abstaining: a crashed call and a
    refusing model share the abstained flag, and only `error` tells them apart.
    """
    if r.get("error"):
        return "", False, True
    options = qrec.get("options") or []
    yn = is_yesno(options)
    letters = letters_of(qrec)
    pred = parse_choice(r.get("response_text") or "", yn, letters=letters,
                        options=options)
    gold = gt_choice(qrec["answer"], yn, letters=letters)
    return pred, bool(pred) and pred == gold, pred == ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", nargs="+", default=["*.jsonl"],
                    help="globs under bench/results (default: every .jsonl)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the before/after table, write nothing")
    args = ap.parse_args()

    files = sorted({p for g in args.results for p in glob.glob(os.path.join(RES, g))})
    files = [p for p in files if os.path.dirname(p) != RESCORED.rstrip("/")]
    if not files:
        print("no result files matched")
        return

    cache, rows_by_leg = {}, defaultdict(lambda: [0, 0, 0, 0])
    missing_subsets, total_changed = set(), 0

    print(f"{'file':52s} {'rows':>7s} {'was':>7s} {'now':>7s} {'delta':>7s} {'recov':>6s}")
    for path in files:
        rows, changed, unresolved, was = [], 0, 0, 0
        with open(path) as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                was += bool(r.get("correct"))
                key = (r.get("dataset"), r.get("method"), r.get("backend"))
                rows_by_leg[key][2] += bool(r.get("correct"))
                sub = load_subset(r.get("dataset", ""), cache)
                qrec = None if sub is None else sub.get(r.get("id"))
                if sub is None:
                    missing_subsets.add(r.get("dataset", "?"))
                if qrec is None:
                    unresolved += 1
                else:
                    pred, correct, abstained = rescore_row(r, qrec)
                    if pred != r.get("prediction"):
                        changed += 1
                    r = dict(r, prediction=pred, correct=correct, abstained=abstained)
                rows.append(r)
                a = rows_by_leg[key]
                a[0] += 1
                a[1] += bool(r.get("correct"))
                a[3] += bool(r.get("abstained"))

        if not rows:
            continue
        now = sum(1 for r in rows if r.get("correct"))
        n = len(rows)
        total_changed += changed
        name = os.path.basename(path).replace("bench_", "").replace(".jsonl", "")
        print(f"{name[:52]:52s} {n:7d} {100*was/n:6.2f}% {100*now/n:6.2f}% "
              f"{100*(now-was)/n:+6.2f}% {changed:6d}"
              + ("  UNRESOLVED=%d" % unresolved if unresolved else ""))

        if not args.dry_run:
            os.makedirs(RESCORED, exist_ok=True)
            out = os.path.join(RESCORED, os.path.basename(path))
            with open(out, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            summ = metrics.summarize_by_method_backend_passes(rows)
            with open(out.replace(".jsonl", "_summary.json"), "w") as f:
                json.dump(summ, f, indent=1)

    print(f"\n{'dataset / method / backend':58s} {'rows':>7s} {'was':>7s} {'now':>7s} {'delta':>7s} {'abst':>6s}")
    for key in sorted(rows_by_leg, key=lambda k: tuple(str(x) for x in k)):
        n, now, was, ab = rows_by_leg[key]
        if not n:
            continue
        label = f"{key[0]} / {key[1]} / {key[2]}"
        print(f"{label[:58]:58s} {n:7d} {100*was/n:6.2f}% {100*now/n:6.2f}% "
              f"{100*(now-was)/n:+6.2f}% {100*ab/n:5.1f}%")

    print(f"\n{total_changed:,} predictions changed across {len(files)} files")
    if missing_subsets:
        print("subset JSON not found for: " + ", ".join(sorted(missing_subsets)))
    if args.dry_run:
        print("dry run - nothing written")


if __name__ == "__main__":
    main()
