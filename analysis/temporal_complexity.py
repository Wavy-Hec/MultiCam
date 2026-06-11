#!/usr/bin/env python3
"""Temporal-complexity scoring for CVBench questions, vs model failures.

Rule-based, transparent metric over the question TEXT (no LLM labeling), answering:
how many questions involve temporal context, how many involve relating MULTIPLE
temporal events, and do failures concentrate there?

Levels:
  0  non-temporal          - no temporal language, no ordering options
  1  temporal reference    - a single temporal event/moment is referenced
                             ("during the closing moments", temporal task type)
  2  temporally complex    - multiple events must be RELATED in time: permutation
                             options ("2-4-3-1"), explicit cross-video ordering
                             ("did video 1 happen before video 2"), or >=2 temporal
                             keywords in the question

Outputs (all under analysis/):
  temporal_complexity.json      - per-id features + level (full 1000 and 45 subset),
                                  counts, and per-model accuracy by level
  temporal_complexity_dist.png  - % of questions per level, full set vs subset
  accuracy_vs_temporal.png      - accuracy per level per model (subset eval results)
  temporal_failures.md          - every level>=1 subset question any model got wrong,
                                  with per-model predictions and trace excerpts

Run (CPU, no GPU needed):
  python3 analysis/temporal_complexity.py
  python3 analysis/temporal_complexity.py --spot 15   # print spot-check sample
"""
import argparse
import json
import os
import random
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FULL_SRC = os.path.join(REPO, "Video-R1", "src", "r1-v", "Evaluation", "CVBench.json")
SUBSET_SRC = os.path.join(HERE, "subset.json")

MODELS = {
    "qwen3vl": os.path.join(REPO, "Video-R1", "src", "r1-v", "eval_results",
                            "eval_subset_qwen3vl.json"),
    "internvl3": os.path.join(HERE, "internvl3_normalized.json"),
    "qwen3vl_blind": os.path.join(REPO, "Video-R1", "src", "r1-v", "eval_results",
                                  "eval_subset_qwen3vl_novideo.json"),
}

LEVEL_NAMES = {0: "non-temporal", 1: "temporal reference", 2: "temporally complex"}

# 'when'/'step'/'stage' are deliberately excluded: in this benchmark they are almost
# always conditional/procedural ("when comparing...", "next step") not temporal events
TEMPORAL_KW = re.compile(
    r"\b(before|after|then|first|last|during|while|order|sequence|chronolog\w*"
    r"|earlier|later|earliest|latest|beginning|end|ending|closing|initial|final\w*"
    r"|subsequent\w*|preced\w*|follow\w*|next|prior|simultaneous\w*|timeline|moment\w*"
    r"|progress\w*)\b", re.I)

# positional uses of "first/last video" and prompt-style "the following" are not
# temporal events -- strip them before counting keywords
POSITIONAL = re.compile(r"\b(first|second|third|fourth|last|final)\s+(video|clip)s?\b", re.I)
BOILERPLATE = re.compile(r"\bthe following\b", re.I)

# an option that is an ordering permutation, e.g. "3-4-1-2"
PERM_OPT = re.compile(r"^\s*\d(\s*-\s*\d)+\s*\.?\s*$")

ORDER_WORDS = re.compile(r"\b(order|sequence|chronolog\w*|timeline)\b", re.I)
VIDEO_BEFORE_AFTER = re.compile(
    r"video\s*\d[^.?]*\b(before|after|preced\w*|follow\w*)\b"
    r"|\b(before|after)\b[^.?]*video\s*\d", re.I)


def option_body(opt):
    # strip a leading "A." / "B." label if present
    m = re.match(r"^\s*[A-D]\s*\.\s*(.*)$", opt, re.S)
    return m.group(1) if m else opt


def features(rec):
    q = rec["question"]
    # the cleaned text is used for BOTH keyword counting and the cross-order check, so
    # "which of the following" boilerplate can't masquerade as temporal language
    q_clean = BOILERPLATE.sub(" ", POSITIONAL.sub(" ", q))
    kws = [m.group(0).lower() for m in TEMPORAL_KW.finditer(q_clean)]
    has_perm = any(PERM_OPT.match(option_body(o)) for o in rec.get("options", []))
    cross_order = bool(
        (ORDER_WORDS.search(q_clean) and re.search(r"\bvideos?\b", q_clean, re.I))
        or VIDEO_BEFORE_AFTER.search(q_clean))
    return {
        "n_temporal_kw": len(kws),
        "temporal_kw": kws,
        "has_permutation_options": has_perm,
        "asks_cross_video_order": cross_order,
        "is_temporal_task": rec.get("task_type") == "Multi-video Temporal Reasoning",
        "n_video_refs": len(set(re.findall(r"\bvideos?\s*(\d)\b", q, re.I))),
    }


def level(f):
    if f["has_permutation_options"] or f["asks_cross_video_order"] or f["n_temporal_kw"] >= 2:
        return 2
    if f["n_temporal_kw"] == 1 or f["is_temporal_task"]:
        return 1
    return 0


def score_all(records):
    out = {}
    for r in records:
        f = features(r)
        f["level"] = level(f)
        f["task_type"] = r["task_type"]
        out[r["id"]] = f
    return out


def counts(scored):
    c = defaultdict(int)
    for f in scored.values():
        c[f["level"]] += 1
    return {k: c[k] for k in (0, 1, 2)}


def load_results(path):
    data = json.load(open(path))
    return data["results"] if isinstance(data, dict) and "results" in data else data


def fmt_trace(r, limit=700):
    think = (r.get("think") or "").strip()
    if not think:
        think = "(no <think> tag parsed) " + (r.get("output") or "").strip()
    if len(think) > limit:
        think = think[:limit].rsplit(" ", 1)[0] + " […truncated; full trace in the eval json]"
    return think


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spot", type=int, default=0,
                    help="print N random scored questions for manual spot-check and exit")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    full = json.load(open(FULL_SRC))
    subset = json.load(open(SUBSET_SRC))
    full_scored = score_all(full)
    subset_ids = [r["id"] for r in subset]

    if args.spot:
        rng = random.Random(args.seed)
        by_id = {r["id"]: r for r in full}
        for rid in rng.sample(list(full_scored), args.spot):
            f = full_scored[rid]
            print(f"id {rid} [{f['task_type']}] level={f['level']} kw={f['temporal_kw']}"
                  f" perm={f['has_permutation_options']} cross_order={f['asks_cross_video_order']}")
            print(f"   Q: {by_id[rid]['question'][:140]}")
        return

    # by construction every temporal-task question is level >= 1; keep the invariant loud
    assert all(f["level"] >= 1 for f in full_scored.values() if f["is_temporal_task"])

    full_counts = counts(full_scored)
    sub_counts = counts({i: full_scored[i] for i in subset_ids})
    print(f"full set ({len(full)}):   " + "  ".join(
        f"L{k} {LEVEL_NAMES[k]}: {v}" for k, v in full_counts.items()))
    print(f"subset  ({len(subset)}):  " + "  ".join(
        f"L{k} {LEVEL_NAMES[k]}: {v}" for k, v in sub_counts.items()))

    # ---- accuracy by level per model (45-question subset) ----
    results = {m: {r["id"]: r for r in load_results(p)} for m, p in MODELS.items()}
    acc_by_level = {}
    for m, recs in results.items():
        buckets = defaultdict(lambda: [0, 0])
        for rid, r in recs.items():
            lv = full_scored[rid]["level"]
            buckets[lv][0] += 1 if r.get("correct") else 0
            buckets[lv][1] += 1
        acc_by_level[m] = {lv: {"correct": c, "total": t, "acc": 100 * c / t}
                           for lv, (c, t) in sorted(buckets.items())}
        print(f"\n{m} accuracy by temporal level:")
        for lv, v in acc_by_level[m].items():
            print(f"  L{lv} {LEVEL_NAMES[lv]:<19} {v['correct']}/{v['total']} = {v['acc']:.1f}%")

    out_json = os.path.join(HERE, "temporal_complexity.json")
    json.dump({
        "levels": {str(k): v for k, v in LEVEL_NAMES.items()},
        "full_counts": full_counts,
        "subset_counts": sub_counts,
        "accuracy_by_level": acc_by_level,
        "by_id": {str(k): v for k, v in sorted(full_scored.items())},
        "subset_ids": subset_ids,
    }, open(out_json, "w"), indent=2)
    print(f"\nwrote {out_json}")

    # ---- plots ----
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    levels = [0, 1, 2]
    x = np.arange(3)
    plt.figure(figsize=(7, 5))
    full_pct = [100 * full_counts[l] / len(full) for l in levels]
    sub_pct = [100 * sub_counts[l] / len(subset) for l in levels]
    plt.bar(x - 0.18, full_pct, width=0.36, label=f"full set (n={len(full)})")
    plt.bar(x + 0.18, sub_pct, width=0.36, label=f"eval subset (n={len(subset)})")
    for xi, (fp, fc) in zip(x, zip(full_pct, [full_counts[l] for l in levels])):
        plt.text(xi - 0.18, fp + 1, f"n={fc}", ha="center", fontsize=9)
    for xi, (sp, sc) in zip(x, zip(sub_pct, [sub_counts[l] for l in levels])):
        plt.text(xi + 0.18, sp + 1, f"n={sc}", ha="center", fontsize=9)
    plt.xticks(x, [f"L{l}\n{LEVEL_NAMES[l]}" for l in levels])
    plt.ylabel("% of questions")
    plt.title("CVBench: temporal complexity of questions")
    plt.legend()
    plt.grid(axis="y", alpha=0.3)
    p1 = os.path.join(HERE, "temporal_complexity_dist.png")
    plt.tight_layout(); plt.savefig(p1, dpi=150); plt.close()
    print(f"wrote {p1}")

    plt.figure(figsize=(7, 5))
    width = 0.26
    for i, m in enumerate(MODELS):
        ys = [acc_by_level[m].get(l, {}).get("acc", float("nan")) for l in levels]
        plt.bar(x + (i - 1) * width, ys, width=width, label=m)
    for l, xi in zip(levels, x):
        n = acc_by_level["qwen3vl"].get(l, {}).get("total", 0)
        plt.text(xi, 2, f"n={n}", ha="center", fontsize=9)
    plt.xticks(x, [f"L{l}\n{LEVEL_NAMES[l]}" for l in levels])
    plt.ylabel("Accuracy (%)")
    plt.ylim(0, 100)
    plt.title("CVBench subset: accuracy vs temporal complexity")
    plt.legend()
    plt.grid(axis="y", alpha=0.3)
    p2 = os.path.join(HERE, "accuracy_vs_temporal.png")
    plt.tight_layout(); plt.savefig(p2, dpi=150); plt.close()
    print(f"wrote {p2}")

    # ---- temporal failure cases ----
    by_id = {r["id"]: r for r in subset}
    md = ["# Temporal failure cases (level >= 1 questions any model got wrong)\n",
          "Levels: L1 = single temporal reference, L2 = multiple events must be "
          "related in time (see analysis/temporal_complexity.py for the metric).\n"]
    cases = [rid for rid in subset_ids
             if full_scored[rid]["level"] >= 1
             and any(not results[m][rid].get("correct") for m in MODELS)]
    cases.sort(key=lambda rid: (-full_scored[rid]["level"], rid))
    for rid in cases:
        f = full_scored[rid]
        rec = by_id[rid]
        trig = [t for t, on in [("permutation options", f["has_permutation_options"]),
                                ("cross-video order", f["asks_cross_video_order"]),
                                (f"keywords: {', '.join(f['temporal_kw'])}", f["n_temporal_kw"] > 0)]
                if on]
        opts = "\n".join(f"  {o}" for o in rec.get("options", []))
        md.append(f"\n## id {rid} — L{f['level']} ({LEVEL_NAMES[f['level']]}) — "
                  f"{rec['task_type']} — triggers: {'; '.join(trig)}\n")
        md.append(f"**Q:** {rec['question']}\n\n**Options:**\n{opts}\n\n"
                  f"**Gold:** {rec['answer']}\n")
        for m in MODELS:
            r = results[m][rid]
            mark = "✓" if r.get("correct") else "✗"
            md.append(f"\n**{m} {mark} predicted {r.get('prediction')}**\n\n"
                      f"> {fmt_trace(r).replace(chr(10), chr(10) + '> ')}\n")
    p3 = os.path.join(HERE, "temporal_failures.md")
    open(p3, "w").write("\n".join(md))
    print(f"wrote {p3} ({len(cases)} questions)")


if __name__ == "__main__":
    main()
