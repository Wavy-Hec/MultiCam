"""Counting-failure analysis: is the model failing to DEDUPLICATE across views,
or is it guessing?

The Aug-4 meeting asked whether counting errors "stem from deduplication issues
or random guesses". Deduplication can only fail when the SAME entity is visible
in several synchronized views, so the question is only well-posed on one pool:

  All-Angles  "Here are multiple camera views which are pointing to the same
              scene, could you count how many tripods in total are in the
              scene?"  -> 4 views of one scene. 100% of its option sets are
              pure integers.
  MVU-Eval    "Which of the three videos shows the room with the most chairs?"
              -> UNRELATED videos, argmax not counting. 0% numeric options.
              There is no shared entity to merge, so dedup cannot be the
              mechanism; it is reported separately as view selection.
  CrossView   has no counting category at all.

Because All-Angles counting options are always consecutive integers, the signed
count error (predicted - gold) is computable for every row with no trace parsing
at all, which is a far stronger discriminator than grepping reasoning text:

  stable OVER-count   -> failed to merge the same entity across views = DEDUP
  stable UNDER-count  -> missed instances                             = PERCEPTION
  unstable, no sign   -> no visual grounding                          = GUESS

"Stable" means the 4 independent passes agree. A dedup error is systematic and
repeats; a guess moves.

THE BLIND CONTROL IS MANDATORY. A model shown no images at all still over-counts
here (+0.46 in the pilot, against per_stream's +0.51), because the option
ordering carries a language prior. Every number below is therefore reported both
raw and as a delta against the blind arm on the same questions; without that
subtraction the prior reads as a dedup failure.

Usage:
  python analysis/counting_failures.py \
      --results 'bench/results/bench_allangles*.jsonl' \
      --subset analysis/allangles_qa.json analysis/allangles_egohumans_qa.json \
      --out-md analysis/counting_failures.md --out-json analysis/counting_failures.json
"""
import argparse
import collections
import glob
import json
import os
import re
import statistics
import sys

LETTERS = "ABCDEFGHIJKLM"
OPT_PREFIX = re.compile(r"^\s*[A-Za-z]\s*[.)]\s*")


def strip_letter(opt):
    """'A. 3' -> '3'. Same regex the harness uses (eval_thinking.py)."""
    return OPT_PREFIX.sub("", str(opt)).strip()


def load_subsets(paths):
    """[(name, {id: rec})] — several pools may be given; rows are matched to the
    pool whose record at that id carries the same task_type."""
    out = []
    for p in paths:
        with open(p) as f:
            recs = json.load(f)
        out.append((os.path.basename(p), {r["id"]: r for r in recs}))
    return out


def match_record(subsets, row):
    """The subset record this row came from, disambiguated by task_type."""
    rid, tt = row.get("id"), row.get("task_type")
    fallback = None
    for _, by_id in subsets:
        rec = by_id.get(rid)
        if rec is None:
            continue
        if rec.get("task_type") == tt:
            return rec
        fallback = fallback or rec
    return fallback


def option_value(rec, letter):
    """Integer behind an option letter, or None if the options are not numeric."""
    if not letter:
        return None
    i = LETTERS.find(str(letter).strip().upper()[:1])
    opts = rec.get("options") or []
    if i < 0 or i >= len(opts):
        return None
    v = strip_letter(opts[i])
    return int(v) if re.fullmatch(r"\d+", v) else None


def protocol_of(row):
    """Rows from different protocols must never be pooled. The reasoning-off
    campaign (temp 0.1, direct answer) and the older thinking-on series
    (temp 0.7) disagree on both decoding and prompt, so a single glob over
    bench/results would otherwise average them into one meaningless number.

    Keyed on temperature alone: it is recorded exactly on every row, whereas an
    empty ``think`` also happens on a truncated thinking-run and would split one
    leg in two."""
    return f"temp={row.get('temperature')}"


def numeric_options(rec):
    opts = rec.get("options") or []
    return bool(opts) and all(re.fullmatch(r"\d+", strip_letter(o)) for o in opts)


def load_rows(patterns, subsets, task_filter="Counting"):
    """Counting rows joined to their subset record."""
    rows = []
    seen_files = 0
    for pat in patterns:
        for path in sorted(glob.glob(pat)):
            seen_files += 1
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if task_filter not in str(r.get("task_type") or ""):
                        continue
                    rec = match_record(subsets, r)
                    if rec is None:
                        continue
                    r["_rec"] = rec
                    rows.append(r)
    return rows, seen_files


# --------------------------------------------------------------------------- #
# per-question classification                                                  #
# --------------------------------------------------------------------------- #
def classify(errs, preds, abstains):
    """One question, one arm, over its passes.

    errs     signed (pred - gold) per pass, None where unparseable
    preds    raw prediction letters per pass
    abstains abstention flag per pass
    """
    if abstains and sum(abstains) > len(abstains) / 2:
        return "abstention"
    vals = [e for e in errs if e is not None]
    if not vals:
        return "unparsed"
    if all(v == 0 for v in vals):
        return "correct"
    stable = len({p for p in preds if p}) <= 1
    mean_err = statistics.mean(vals)
    if not stable:
        # moved between passes: a guess unless it moved but kept one sign
        if all(v > 0 for v in vals):
            return "dedup_failure_unstable"
        if all(v < 0 for v in vals):
            return "perception_miss_unstable"
        return "random_guess"
    return "dedup_failure" if mean_err > 0 else "perception_miss"


def classify_selection(preds, corrects, abstains):
    """Non-numeric ('which video...') questions, one arm, over its passes.

    There is no count to be wrong about, so the only axis is whether the model
    lands on the same clip every time. A stable wrong answer is a systematic
    misreading; an unstable one is a guess.
    """
    if abstains and sum(abstains) > len(abstains) / 2:
        return "abstention"
    if corrects and all(corrects):
        return "correct"
    distinct = {p for p in preds if p}
    if not distinct:
        return "unparsed"
    if len(distinct) > 1:
        return "random_guess"
    return "stable_wrong" if not any(corrects) else "partly_correct"


def arm_stats(rows):
    """(backend, method) -> per-question and pooled statistics."""
    by_q = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        rec = r["_rec"]
        gv = option_value(rec, r.get("gold"))
        pv = option_value(rec, r.get("prediction"))
        key = (r.get("backend"), r.get("method"), protocol_of(r))
        by_q[key][r.get("id")].append({
            "pass_idx": r.get("pass_idx"),
            "err": (pv - gv) if (pv is not None and gv is not None) else None,
            "pred": str(r.get("prediction") or "").strip().upper(),
            "abstained": bool(r.get("abstained")),
            "correct": bool(r.get("correct")),
        })

    out = {}
    for key, qs in by_q.items():
        errs_all, mech = [], collections.Counter()
        per_q = {}
        flips = 0
        for qid, passes in qs.items():
            e = [p["err"] for p in passes]
            pr = [p["pred"] for p in passes]
            ab = [p["abstained"] for p in passes]
            m = classify(e, pr, ab)
            mech[m] += 1
            errs_all.extend([v for v in e if v is not None])
            if len({p for p in pr if p}) > 1:
                flips += 1
            per_q[qid] = {"mech": m, "errs": e, "preds": pr}
        n = len(errs_all)
        out[key] = {
            "n_questions": len(qs),
            "n_rows": n,
            "mean_signed_err": statistics.mean(errs_all) if n else None,
            "over_pct": 100 * sum(1 for e in errs_all if e > 0) / n if n else None,
            "under_pct": 100 * sum(1 for e in errs_all if e < 0) / n if n else None,
            "exact_pct": 100 * sum(1 for e in errs_all if e == 0) / n if n else None,
            "pass_flip_pct": 100 * flips / len(qs) if qs else None,
            "mechanisms": dict(mech),
            "per_question": per_q,
        }
    return out


def fmt(x, nd=3, pct=False):
    if x is None:
        return "—"
    return f"{x:.1f}" if pct else f"{x:+.{nd}f}"


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", nargs="+", required=True,
                    help="bench/results JSONL path(s) or glob(s)")
    ap.add_argument("--subset", nargs="+", required=True,
                    help="subset JSON(s) supplying question/option text")
    ap.add_argument("--task-filter", default="Counting",
                    help="substring of task_type to analyse (default: Counting)")
    ap.add_argument("--blind-method", default="blind",
                    help="method name used as the no-image control")
    ap.add_argument("--per-bucket", type=int, default=3,
                    help="trace excerpts to dump per (arm x mechanism)")
    ap.add_argument("--trace-chars", type=int, default=700)
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--out-json", default=None)
    a = ap.parse_args()

    subsets = load_subsets(a.subset)
    rows, nfiles = load_rows(a.results, subsets, a.task_filter)
    if not rows:
        print(f"no '{a.task_filter}' rows matched across {nfiles} file(s)", file=sys.stderr)
        return 1

    numeric = [r for r in rows if numeric_options(r["_rec"])]
    nonnum = [r for r in rows if not numeric_options(r["_rec"])]
    sel_mech = {}  # ((backend, method), id) -> label, for the non-numeric pool

    L = []
    L.append(f"# Counting failures — dedup vs guess (`{a.task_filter}`)\n")
    L.append(f"Generated by `analysis/counting_failures.py` from {nfiles} result file(s): "
             f"**{len(rows)}** rows, of which **{len(numeric)}** have numeric option sets "
             f"(the signed-count-error analysis) and **{len(nonnum)}** do not "
             f"(reported separately as view selection).\n")

    stats = arm_stats(numeric) if numeric else {}

    # ---- blind control -----------------------------------------------------
    blind_keys = [k for k in stats if k[1] == a.blind_method]
    blind_by_backend = {(k[0], k[2]): stats[k] for k in blind_keys}

    if numeric:
        L.append("## Signed count error (prediction − gold)\n")
        L.append("A positive mean is over-counting, the signature of failing to merge the same "
                 "entity seen from several views. `Δ blind` subtracts the no-image control on the "
                 "same pool — without it, the option-ordering language prior reads as a dedup "
                 "failure.\n")
        L.append("| backend | method | protocol | questions | rows | mean err | Δ blind | "
                 "over% | under% | exact% | pass-flip% |")
        L.append("|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
        for key in sorted(stats, key=lambda k: (str(k[0]), str(k[1]))):
            s = stats[key]
            b = blind_by_backend.get((key[0], key[2]))
            delta = (s["mean_signed_err"] - b["mean_signed_err"]) \
                if (b and s["mean_signed_err"] is not None
                    and b["mean_signed_err"] is not None and key[1] != a.blind_method) else None
            L.append(f"| {key[0]} | `{key[1]}` | {key[2]} | {s['n_questions']} | {s['n_rows']} | "
                     f"{fmt(s['mean_signed_err'])} | {fmt(delta)} | "
                     f"{fmt(s['over_pct'], pct=True)} | {fmt(s['under_pct'], pct=True)} | "
                     f"{fmt(s['exact_pct'], pct=True)} | {fmt(s['pass_flip_pct'], pct=True)} |")

        # ---- mechanism mix -------------------------------------------------
        L.append("\n## Mechanism mix (one label per question, decided over its passes)\n")
        L.append("`dedup_failure` = every pass agrees and over-counts. `perception_miss` = agrees "
                 "and under-counts. `random_guess` = predictions move between passes with no "
                 "consistent sign. `*_unstable` = moved but kept one sign.\n")
        mechs = sorted({m for s in stats.values() for m in s["mechanisms"]})
        L.append("| backend | method | protocol | " + " | ".join(f"`{m}`" for m in mechs) + " |")
        L.append("|---|---|---|" + "--:|" * len(mechs))
        for key in sorted(stats, key=lambda k: (str(k[0]), str(k[1]))):
            s = stats[key]
            tot = max(1, s["n_questions"])
            cells = []
            for m in mechs:
                c = s["mechanisms"].get(m, 0)
                cells.append(f"{c} ({100*c/tot:.0f}%)")
            L.append(f"| {key[0]} | `{key[1]}` | {key[2]} | " + " | ".join(cells) + " |")

        # ---- the task1_spec hypothesis -------------------------------------
        L.append("\n## Hypothesis test — decentralized should over-count more than centralized\n")
        L.append("`docs/task1_spec.md` predicts the decentralized harness excels at per-view "
                 "perception but must merge in text, so it should over-count more than the "
                 "centralized montage.\n")
        L.append("| backend | protocol | per_stream | centralized | difference |")
        L.append("|---|---|--:|--:|--:|")
        for backend, proto in sorted({(k[0], k[2]) for k in stats}):
            ps = stats.get((backend, "per_stream", proto))
            ce = stats.get((backend, "centralized", proto))
            if not ps or not ce:
                continue
            d = ps["mean_signed_err"] - ce["mean_signed_err"]
            verdict = "as predicted" if d > 0 else "**opposite**"
            L.append(f"| {backend} | {proto} | {fmt(ps['mean_signed_err'])} | "
                     f"{fmt(ce['mean_signed_err'])} | {fmt(d)} ({verdict}) |")

    # ---- non-numeric pools (MVU): view selection, not counting -------------
    if nonnum:
        L.append("\n## Non-numeric counting questions — view selection, not deduplication\n")
        L.append("These ask which of several **unrelated** videos contains the most of "
                 "something. No entity is shared between the clips, so deduplication is not the "
                 "mechanism; the failure is picking the wrong clip.\n")
        sel = collections.defaultdict(lambda: [0, 0, 0])
        per_pass = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in nonnum:
            k = (r.get("backend"), r.get("method"), protocol_of(r))
            sel[k][1] += 1
            sel[k][0] += 1 if r.get("correct") else 0
            if r.get("abstained"):
                sel[k][2] += 1
            per_pass[k][r.get("id")].append(
                (str(r.get("prediction") or "").strip().upper(),
                 bool(r.get("correct")), bool(r.get("abstained"))))
        for k, qs in per_pass.items():
            for qid, tup in qs.items():
                sel_mech[(k, qid)] = classify_selection([t[0] for t in tup],
                                                        [t[1] for t in tup],
                                                        [t[2] for t in tup])
        mset = sorted({m for m in sel_mech.values()})
        L.append("| backend | method | protocol | accuracy | abstain% | pass-flip% | "
                 + " | ".join(f"`{m}`" for m in mset) + " |")
        L.append("|---|---|---|--:|--:|--:|" + "--:|" * len(mset))
        for k in sorted(sel, key=lambda x: (str(x[0]), str(x[1]))):
            c, n, ab = sel[k]
            qs = per_pass[k]
            fp = 100 * sum(1 for v in qs.values()
                           if len({t[0] for t in v if t[0]}) > 1) / max(1, len(qs))
            mine = collections.Counter(sel_mech[(k, qid)] for qid in qs)
            cells = [f"{mine.get(m,0)} ({100*mine.get(m,0)/max(1,len(qs)):.0f}%)" for m in mset]
            L.append(f"| {k[0]} | `{k[1]}` | {k[2]} | {100*c/n:.1f}% ({c}/{n}) | "
                     f"{100*ab/n:.1f} | {fp:.1f} | " + " | ".join(cells) + " |")
        L.append("\nA high `random_guess` share with near-chance accuracy is the signature the "
                 "meeting asked about: the arm is not reading the clips, it is picking.\n")
        L.append("> **Read `random_guess` only within a protocol.** Instability across passes is "
                 "partly decoding noise, and that noise is a function of temperature: the same "
                 "arm flips on ~78% of questions at `temp=0.7` and ~2% at `temp=0.1`. So the "
                 "guess-vs-systematic split is only clean on the low-temperature reasoning-off "
                 "series; at `temp=0.7` the `random_guess` column overstates guessing and "
                 "`stable_wrong` understates it.\n")

    # ---- qualitative: traces ----------------------------------------------
    traced = [r for r in rows if (r.get("think") or "").strip()]
    L.append(f"\n## Reasoning traces\n")
    if not traced:
        L.append("No rows in this selection carry a reasoning trace. The reasoning-off campaign "
                 "writes `think: \"\"` by construction, so trace excerpts must come from the "
                 "thinking-on legs.\n")
    else:
        L.append(f"{len(traced)} of {len(rows)} rows carry a trace. Up to {a.per_bucket} "
                 f"excerpt(s) per (arm × mechanism).\n")
        qmech = dict(sel_mech)
        for key, s in stats.items():
            for qid, d in s["per_question"].items():
                qmech[(key, qid)] = d["mech"]
        buckets = collections.defaultdict(list)
        for r in traced:
            key = (r.get("backend"), r.get("method"), protocol_of(r))
            m = qmech.get((key, r.get("id")), "unclassified")
            if m in ("correct",):
                continue
            buckets[(key, m)].append(r)
        for (key, m) in sorted(buckets, key=lambda x: (str(x[0]), x[1])):
            L.append(f"\n### {key[0]} / `{key[1]}` — {m}\n")
            for r in buckets[(key, m)][:a.per_bucket]:
                rec = r["_rec"]
                gv, pv = option_value(rec, r.get("gold")), option_value(rec, r.get("prediction"))
                t = re.sub(r"\s+", " ", (r.get("think") or "").strip())
                t = t[:a.trace_chars] + (" …[trimmed]" if len(t) > a.trace_chars else "")
                L.append(f"- **id {r.get('id')}**, pass {r.get('pass_idx')} — "
                         f"gold `{r.get('gold')}`"
                         + (f" ({gv})" if gv is not None else "")
                         + f", predicted `{r.get('prediction')}`"
                         + (f" ({pv})" if pv is not None else "") + "  ")
                L.append(f"  Q: {str(rec.get('question',''))[:200]}  ")
                L.append(f"  trace: {t}\n")

    md = "\n".join(L) + "\n"
    print(md)
    if a.out_md:
        with open(a.out_md, "w") as f:
            f.write(md)
        print(f"[wrote] {a.out_md}", file=sys.stderr)
    if a.out_json:
        payload = {
            "task_filter": a.task_filter,
            "n_rows": len(rows),
            "n_numeric_rows": len(numeric),
            "arms": {f"{k[0]}/{k[1]}/{k[2]}": {kk: vv for kk, vv in v.items() if kk != "per_question"}
                     for k, v in stats.items()},
        }
        with open(a.out_json, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"[wrote] {a.out_json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
