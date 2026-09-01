#!/usr/bin/env python3
"""Per-evidence-class accuracy for every valid MEVA leg — zero new GPU hours.

Joins analysis/records/evidence_labels.json (label_evidence_class.py) to the
rescored per-question rows of every registered media-valid MEVA leg and splits
accuracy by evidence class: C2 (one camera, a time window — the spatial pool)
vs C4 (windows across cameras — temporal + event ordering). C1/C3/C5 are empty
in the harness pool, which is itself the finding that motivates the bank work.

Per class it reports the mean and std over passes (decoding variance, frames
fixed) plus the LEAVE-ONE-OUT task-conditioned modal-letter floor restricted
to that class — a class split is only readable against its own floor, because
the classes inherit different task mixes. Each leg's pooled accuracy is
cross-checked against the registry's number and the run refuses on a mismatch:
reading the wrong files must fail, not average.

Run from the repo root (labels first):
  python3 analysis/label_evidence_class.py
  python3 analysis/evidence_class_accuracy.py
Writes docs/evidence_class_splits_<date>.md (docs/ is gitignored prose).
"""
import glob
import json
import os
import time
from collections import Counter, defaultdict
from statistics import fmean, pstdev

LABELS = "analysis/records/evidence_labels.json"
REGISTRY = "analysis/records/registry.json"
SUBSET_OF = {"crossview_meva1033_subset.json": ("analysis/crossview_meva1033_subset.json", "meva1033"),
             "crossview_meva_cap13.json": ("analysis/crossview_meva_cap13.json", "cap13")}
RESULTS = "bench/results"
CLASSES = ("C2", "C4")


def class_maps(labels):
    """{subset_alias: {record_id: evidence_class}}"""
    maps = defaultdict(dict)
    for row in labels["labels"]:
        for alias, rid in row["ids"].items():
            maps[alias][rid] = row["evidence_class"]
    return maps


def loo_floor(records, restrict_ids=None):
    """Leave-one-out task-conditioned modal-letter accuracy, optionally
    restricted to a set of record ids (the class): the guesser still learns
    per TASK over the whole pool — it cannot see the class — but is scored
    only on the restricted questions."""
    by_task = defaultdict(Counter)
    for r in records:
        by_task[r["task_type"]][r["answer"].strip().upper()] += 1
    hit = tot = 0
    for r in records:
        if restrict_ids is not None and r["id"] not in restrict_ids:
            continue
        c = by_task[r["task_type"]].copy()
        g = r["answer"].strip().upper()
        c[g] -= 1
        guess = max(sorted(c), key=lambda k: c[k])
        hit += (guess == g)
        tot += 1
    return 100.0 * hit / tot if tot else None


def leg_rows(leg):
    base = os.path.join(RESULTS, "rescored" if leg["rescored"] else "")
    files = sorted(glob.glob(os.path.join(base, leg["glob"])))
    files = [f for f in files if not f.endswith("_summary.json")]
    rows = []
    for f in files:
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


def split(rows, cmap):
    """{class: (mean_pct, std_pct, n_q)} over passes, plus pooled overall."""
    per = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # cls -> pass -> [hit, tot]
    pooled = [0, 0]
    for r in rows:
        if r.get("error"):
            continue
        cls = cmap.get(r.get("id"))
        pi = r.get("pass_idx")
        if cls is None:
            raise SystemExit(f"row id={r.get('id')} has no label — labels stale?")
        per[cls][pi][1] += 1
        per[cls][pi][0] += bool(r.get("correct"))
        pooled[1] += 1
        pooled[0] += bool(r.get("correct"))
    out = {}
    for cls, passes in per.items():
        accs = [100.0 * h / t for h, t in passes.values() if t]
        nq = max(t for _, t in passes.values())
        out[cls] = (fmean(accs), pstdev(accs) if len(accs) > 1 else 0.0, nq)
    overall = 100.0 * pooled[0] / pooled[1] if pooled[1] else None
    return out, overall


def main():
    labels = json.load(open(LABELS))
    maps = class_maps(labels)
    reg = json.load(open(REGISTRY))["legs"]
    legs = [l for l in reg if l.get("media_ok")
            and l.get("subset") in SUBSET_OF and not l.get("media_mixed")]

    subsets, floors = {}, {}
    for fname, (path, alias) in SUBSET_OF.items():
        recs = json.load(open(path))
        subsets[alias] = recs
        floors[alias] = {
            cls: loo_floor(recs, {i for i, c in maps[alias].items() if c == cls})
            for cls in CLASSES}
        floors[alias]["overall"] = loo_floor(recs)

    lines = [f"# MEVA accuracy by evidence class — {time.strftime('%Y-%m-%d')}",
             "", "Every valid (`media_ok`) registered MEVA leg, re-split by the",
             "evidence-locality labels. C2 = one camera, a window (spatial);",
             "C4 = windows across cameras (temporal + event ordering).",
             "Mean ± std over passes; floors are leave-one-out task-conditioned.", ""]
    cache = {}
    for alias in subsets:
        f = floors[alias]
        lines += [f"## {alias} pool",
                  f"floor (LOO): overall {f['overall']:.2f} · "
                  f"C2 {f['C2']:.2f} · C4 {f['C4']:.2f}", "",
                  "| method | backend | budget | C2 acc | C4 acc | overall |",
                  "|---|---|---|---|---|---|"]
        for leg in legs:
            if SUBSET_OF[leg["subset"]][1] != alias:
                continue
            key = (leg["glob"], leg["rescored"])
            if key not in cache:
                cache[key] = leg_rows(leg)
            rows = [r for r in cache[key]
                    if r.get("method") == leg["method"]
                    and r.get("backend") == leg["backend"]]
            if not rows:
                continue
            cls, overall = split(rows, maps[alias])
            if abs(overall - leg["accuracy_pct"]) > 0.1:
                raise SystemExit(
                    f"{leg['method']}/{leg['backend']} {leg['glob']}: recomputed "
                    f"{overall:.2f} != registry {leg['accuracy_pct']} — wrong files?")
            c2 = cls.get("C2"); c4 = cls.get("C4")
            fmt = lambda c: f"{c[0]:.2f} ± {c[1]:.2f} (n={c[2]})" if c else "—"
            lines.append(f"| {leg['method']} | {leg['backend']} | {leg['budget']} "
                         f"| {fmt(c2)} | {fmt(c4)} | {overall:.2f} |")
            print(f"{alias:9s} {leg['method']:28s} {leg['backend'][:9]:9s} "
                  f"{leg['budget'][:26]:26s} C2 {fmt(c2):24s} C4 {fmt(c4):24s} "
                  f"all {overall:.2f}")
        lines.append("")

    out = f"docs/evidence_class_splits_{time.strftime('%Y-%m-%d')}.md"
    os.makedirs("docs", exist_ok=True)
    with open(out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nfloors: {json.dumps(floors)}")
    print(f"table -> {out}")


if __name__ == "__main__":
    main()
