#!/usr/bin/env python3
"""Are CVBench questions answerable from text alone? Per-question and per-task
analysis of a blind (no-video) leg — optionally its reversed-option twin —
against chance, the answer key's own skew, the leg's own answer bias and a
zero-parameter option heuristic, and optionally against sighted legs.

A blind leg's accuracy mixes three things: guessing at chance, riding a skewed
answer distribution (a letter / Yes-No preference that needs no question at
all), and inferring the answer from the question and option TEXT. Only the
third is "answerable through text alone", so besides raw accuracy this reports:

  * chance: mean 1/n_options over the harness's own letter set (letters_for);
  * key floors per stratum of (task type, answer space) — Yes/No questions
    answer "Yes"/"No", lettered ones a letter from their own set (A-B or
    A-D), so two strata never share an answer space: the in-sample modal-gold rate (an upper bound on any
    task-conditioned letter guesser) and its leave-one-out version with ties
    split evenly (a stratum with no other question scores chance), plus the
    "pick the longest option" rule on lettered questions (ties split);
  * the leg's BIAS NULL: within each stratum the questions' whole pass-sets of
    predictions are permuted. That keeps the model's answer distribution AND
    its within-question consistency, and breaks only the link between a
    prediction and the question it was made for, so observed accuracy above
    it depends on WHICH question was asked;
  * per question: k of n passes correct (error rows excluded), labelled
        text-answerable  k/n >= 0.75 (3 or 4 of 4),
        unstable         some but not most passes right,
        not              0 passes right,
        error            every pass errored,
    with the count of text-answerable questions expected under (a) pure
    guessing at chance and (b) the bias null, so the count is luck-subtracted.
    Each text-answerable question is split by whether its majority answer is
    its stratum's modal prediction computed WITHOUT it (a default the model
    gives anyway) or a departure from it (the most direct evidence of a
    content-driven answer); strata under 5 other questions say n/a;
  * with --blind-o2 (the same questions with options reversed, written by
    convert_cvbench.py --order O2): the same tables for O2, and a BOTH-ORDERS
    label — text-answerable in O1 and in O2 — with its own chance and
    bias-null expectations. A letter-position preference cannot pass both
    orders, so this is the strict text-answerable set on lettered questions;
    a Yes/No answer is a word, so a Yes/No habit passes both, and the label
    is also split by format. The both-orders bias null comes two ways:
    independent (each order's pass-sets permuted separately) and paired (one
    permutation moves a question's O1 and O2 pass-sets together, which keeps
    habits that hold across orders: the conservative baseline);
  * trace hygiene: rows whose answer was parsed from the whole text although
    the leg thinks natively (parsed_from != after_think: the trace never closed
    its thinking block, usually the token cap), and how many sit at the leg's
    longest output.

--sighted LABEL=GLOB crosses each sighted (method, backend) leg's per-question
passes-correct with the blind label. --slice NAME=IDS.json repeats the headline
on a list of question ids (strings 'cvb-<n>', ints, or records with an 'id').

Writes only the --json path; stdout otherwise, and --help writes nothing.

Run (no GPU, no videos needed):
  python3 analysis/cvbench_text_answerability.py \\
      --blind 'bench/results/bench_cvbench_full_runnable_subset_cvbench_q38bd_shard*.jsonl' \\
      --blind-o2 'bench/results/bench_cvbench_full_runnable_subset_o2_cvbench_q38bd_shard*.jsonl' \\
      --json analysis/records/cvbench_text_answerability_q38bd.json
"""
import argparse
import glob
import json
import math
import os
import random
import re
import sys
from collections import Counter, defaultdict
from statistics import mean, pstdev

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

# the harness's own scorer helpers, so letters and gold match the rows exactly
from bench.reuse import gt_choice, is_yesno, letters_for, parse_choice  # noqa: E402

SUBSET = os.path.join(HERE, "cvbench_full_runnable_subset.json")
SUBSET_O2 = os.path.join(HERE, "cvbench_full_runnable_subset_o2.json")
_PREFIX = re.compile(r"^\s*[A-M]\s*[.)]\s*")
_CLIP = re.compile(r"videos?(?:\s*id)?\s*\d+", re.IGNORECASE)
_REF_WORDS = re.compile(r"\b(?:both|neither|none|all|only|of|the|them|above|and|nor|or)\b",
                        re.IGNORECASE)
MIN_STRATUM = 5


def ref_body(body):
    """True when an option names clips and nothing else ('Video 2.', 'Both of
    them.', 'Videos 1 and 2.', 'Video 2 - Video 1 - Video 3', '2-1-3'): no text
    cue can choose among such options, only the key's structure."""
    b = body.strip().rstrip(".").strip()
    if not b:
        return False
    if re.fullmatch(r"\d+(?:\s*(?:-|,|->|→|>)\s*\d+)+", b):
        return True                                   # an ordering of clip numbers
    rest = _CLIP.sub(" ", b)
    if rest == b and not _REF_WORDS.search(b):
        return False
    if re.search(r"video", b, re.IGNORECASE):
        rest = re.sub(r"\d+", " ", rest)              # 'Videos 1 and 2'
    rest = _REF_WORDS.sub(" ", rest)
    return re.sub(r"[&,\-→>\s]+", "", rest) == ""


def video_ref_options(rec):
    bodies = [_PREFIX.sub("", o, count=1) for o in rec["options"]]
    return len(bodies) > 1 and all(ref_body(b) for b in bodies)


def load_rows(patterns):
    files = sorted({f for p in patterns for f in glob.glob(p) if not f.endswith("_summary.json")})
    rows, torn, dups, seen = [], 0, 0, set()
    for f in files:
        with open(f) as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    torn += 1
                    continue
                key = (r.get("id"), r.get("method"), r.get("backend"), r.get("pass_idx"))
                if key in seen:
                    dups += 1
                    continue
                seen.add(key)
                rows.append(r)
    return files, rows, torn, dups


def question_meta(rec):
    opts = rec["options"]
    yn = is_yesno(opts)
    letters = letters_for(opts)
    gold = gt_choice(rec["answer"], yn, letters=letters)
    space = ["Yes", "No"] if yn else list(letters)
    return dict(yn=yn, letters=letters, gold=gold, fmt="YN" if yn else letters, space=space,
                chance=1.0 / len(space), task=rec["task_type"])


def stratum(m):
    return (m["task"], m["fmt"])


def longest_option_hit(rec, meta):
    """Expected hit of 'pick the longest option' (ties split), None on Yes/No
    and on malformed rows whose options do not map one-to-one onto letters."""
    if meta["yn"] or len(rec["options"]) != len(meta["letters"]):
        return None
    lens = [len(_PREFIX.sub("", o, count=1).strip()) for o in rec["options"]]
    top = max(lens)
    tied = [meta["letters"][i] for i, n in enumerate(lens) if n == top]
    return (1.0 / len(tied)) if meta["gold"] in tied else 0.0


def key_floors(metas, ids):
    """(in-sample, leave-one-out) modal-gold hit rates per (task, format)
    stratum learned over the WHOLE pool and scored on `ids`; ties split, and a
    question alone in its stratum scores chance on the leave-one-out side."""
    by = defaultdict(Counter)
    for m in metas.values():
        by[stratum(m)][m["gold"].upper()] += 1
    ins = loo = 0.0
    for q in ids:
        m = metas[q]
        c, g = by[stratum(m)], m["gold"].upper()
        top = max(c.values())
        modal = [k for k, v in c.items() if v == top]
        ins += (1.0 / len(modal)) if g in modal else 0.0
        c2 = c.copy()
        c2[g] -= 1
        if sum(c2.values()) == 0:
            loo += m["chance"]
            continue
        top2 = max(c2.values())
        modal2 = [k for k, v in c2.items() if v == top2]
        loo += (1.0 / len(modal2)) if g in modal2 else 0.0
    return ins / len(ids), loo / len(ids)


def p_at_least(k, n, p):
    return sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))


def need(n):
    """Smallest k that labels a question text-answerable at n passes."""
    return math.ceil(0.75 * n) if n else 0


def pct(x):
    return None if x is None else round(100.0 * x, 2)


class Leg:
    """One blind leg over one subset: rows per question (error rows kept apart)."""

    def __init__(self, subset, patterns, name):
        self.name = name
        self.recs = {r["id"]: r for r in json.load(open(subset))}
        self.metas = {q: question_meta(r) for q, r in self.recs.items()}
        self.files, rows, self.torn, self.dups = load_rows(patterns)
        rows = [r for r in rows if r.get("method") == "blind"]
        if not rows:
            raise SystemExit(f"{name}: no blind rows in {patterns}")
        self.backends = sorted({r.get("backend") for r in rows})
        self.decodes = sorted({json.dumps(r.get("decode"), sort_keys=True) for r in rows})
        if len(self.backends) > 1:
            raise SystemExit(f"{name}: blind rows mix backends {self.backends}; pass one leg at a time")
        if len(self.decodes) > 1:
            raise SystemExit(f"{name}: blind rows mix decode settings {self.decodes}; "
                             "pass one leg (one TAG) at a time")
        stray = sorted({r["id"] for r in rows} - set(self.recs))
        if stray:
            raise SystemExit(f"{name}: {len(stray)} row id(s) not in {subset}, e.g. {stray[:3]}")
        self.rows = {q: {} for q in self.recs}          # every row, for accuracy
        for r in rows:
            self.rows[r["id"]][r.get("pass_idx")] = r
        self.ids = [q for q in self.recs if self.rows[q]]
        self.ok = {q: {pi: r for pi, r in self.rows[q].items() if not r.get("error")}
                   for q in self.ids}                   # non-error rows, for k-of-n
        self.thinking = json.loads(self.decodes[0] or "null") or {}
        self.thinking = self.thinking.get("enable_thinking") is not False and \
            self.thinking.get("answer_after_think", False)

    def kn(self, q):
        ok = self.ok[q]
        return sum(1 for r in ok.values() if r.get("correct") is True), len(ok)

    def label(self, q):
        k, n = self.kn(q)
        if n == 0:
            return "error"
        if k / n >= 0.75:
            return "text-answerable"
        return "not" if k == 0 else "unstable"

    def pass_accs(self, ids):
        """Per-pass accuracy over `ids`, error rows counted wrong (bench/metrics.py)."""
        by_pass = defaultdict(list)
        for q in ids:
            for pi, r in self.rows[q].items():
                by_pass[pi].append(1.0 if r.get("correct") is True else 0.0)
        return {pi: mean(v) for pi, v in sorted(by_pass.items()) if v}

    def predsets(self, ids):
        return {q: [r.get("prediction", "") for _, r in sorted(self.ok[q].items())] for q in ids}


def mstd(accs):
    v = list(accs.values())
    if not v:
        return {"mean": None, "std": None, "n_passes": 0}
    return {"mean": pct(mean(v)), "std": pct(pstdev(v)) if len(v) > 1 else 0.0, "n_passes": len(v)}


def permutation_null(legs, ids, B, seed, paired=False):
    """Within-stratum permutation of whole pass-sets, independently per leg —
    or, with paired, one permutation per draw shared by every leg, so a donor
    question's pass-sets in all legs travel together (strata are then the
    tuple of the legs' strata, over questions with rows in every leg).
    Observed and null totals of correct passes (leg 0) and of text-answerable
    questions — in every leg at once when several legs are given (the
    both-orders label) — with 2.5/97.5 percentiles and one-sided p values."""
    rng = random.Random(seed)
    sets = [leg.predsets(ids) for leg in legs]
    golds = [{q: leg.metas[q]["gold"].strip().upper() for q in ids} for leg in legs]
    strata = [defaultdict(list) for _ in legs]
    if paired:
        for q in ids:
            if all(s[q] for s in sets):
                strata[0][tuple(stratum(leg.metas[q]) for leg in legs)].append(q)
        strata = strata[:1]
    else:
        for li, leg in enumerate(legs):
            for q in ids:
                if sets[li][q]:
                    strata[li][stratum(leg.metas[q])].append(q)

    def score(assigns):
        tot, ta = 0, 0
        for q in ids:
            all_ta = True
            for li in range(len(legs)):
                src = assigns[li].get(q)
                ps = sets[li][src] if src is not None else []
                k = sum(1 for p in ps if p.strip().upper() == golds[li][q])
                if li == 0:
                    tot += k
                all_ta &= bool(ps) and k >= need(len(ps))
            ta += all_ta
        return tot, ta

    ident = [{q: q for q in ids if sets[li][q]} for li in range(len(legs))]
    obs_tot, obs_ta = score(ident)
    null_tot, null_ta = [], []
    for _ in range(B):
        assigns = []
        for st in strata:
            a = {}
            for g in st.values():
                perm = g[:]
                rng.shuffle(perm)
                a.update(zip(g, perm))
            assigns.append(a)
        if paired:
            assigns = assigns * len(legs)
        t, n_ta = score(assigns)
        null_tot.append(t)
        null_ta.append(n_ta)
    null_tot.sort()
    null_ta.sort()
    q = lambda xs, f: xs[min(len(xs) - 1, int(f * len(xs)))]
    return {
        "observed_correct": obs_tot,
        "null_mean_correct": round(mean(null_tot), 2),
        "null_95_correct": [q(null_tot, 0.025), q(null_tot, 0.975)],
        "p_correct": round((1 + sum(1 for t in null_tot if t >= obs_tot)) / (B + 1), 5),
        "observed_text_answerable": obs_ta,
        "null_mean_text_answerable": round(mean(null_ta), 2),
        "null_95_text_answerable": [q(null_ta, 0.025), q(null_ta, 0.975)],
        "p_text_answerable": round((1 + sum(1 for t in null_ta if t >= obs_ta)) / (B + 1), 5),
        "B": B,
    }


def summarize(leg, ids, args, with_null=True):
    lab = Counter(leg.label(q) for q in ids)
    exp_chance = 0.0
    for q in ids:
        k, n = leg.kn(q)
        exp_chance += p_at_least(need(n), n, leg.metas[q]["chance"]) if n else 0.0
    lof = [x for x in (longest_option_hit(leg.recs[q], leg.metas[q]) for q in ids) if x is not None]
    ins, loo = key_floors(leg.metas, ids) if ids else (None, None)
    out = {
        "n_questions": len(ids),
        "n_rows": sum(len(leg.rows[q]) for q in ids),
        "n_correct": sum(1 for q in ids for r in leg.rows[q].values() if r.get("correct") is True),
        "accuracy": mstd(leg.pass_accs(ids)),
        "per_pass": {str(k): pct(v) for k, v in leg.pass_accs(ids).items()},
        "chance": pct(mean(leg.metas[q]["chance"] for q in ids)) if ids else None,
        "key_floor_insample": pct(ins),
        "key_floor_loo": pct(loo),
        "longest_option": {"acc": pct(mean(lof)) if lof else None, "n": len(lof)},
        "abstained_rows": sum(1 for q in ids for r in leg.rows[q].values()
                              if r.get("abstained") and not r.get("error")),
        "error_rows": sum(1 for q in ids for r in leg.rows[q].values() if r.get("error")),
        "labels": dict(lab),
        "expected_text_answerable_at_chance": round(exp_chance, 2),
    }
    if with_null and ids:
        out["bias_null"] = permutation_null([leg], ids, args.permutations, args.seed)
    return out


def per_question(leg):
    """Labels, and whether a text-answerable majority answer departs from the
    stratum's modal prediction computed without the question itself."""
    strat = defaultdict(Counter)
    members = Counter()
    sets = leg.predsets(leg.ids)
    for q in leg.ids:
        strat[stratum(leg.metas[q])].update(sets[q])
        members[stratum(leg.metas[q])] += 1
    out, split = {}, Counter()
    for q in leg.ids:
        m = leg.metas[q]
        k, n = leg.kn(q)
        lab = leg.label(q)
        own = Counter(sets[q])
        rest = strat[stratum(m)] - own
        kind = None
        default = None
        if members[stratum(m)] - 1 >= MIN_STRATUM and rest:
            default = sorted(rest.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        if lab == "text-answerable":
            qmodal = sorted(own.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            kind = ("n/a" if default is None else
                    "stratum-default" if qmodal == default else "departs-from-default")
            split[kind] += 1
        out[q] = dict(task=m["task"], fmt=m["fmt"], gold=m["gold"], preds=sets[q], k=k, n=n,
                      label=lab, kind=kind, chance=round(m["chance"], 4),
                      video_ref_options=video_ref_options(leg.recs[q]),
                      stratum_default_without_q=default)
    return out, split


def hygiene(leg):
    """Trace and cost accounting over non-error rows; GPU time per row is
    latency_s / batch_n (a batched call's wall clock is shared)."""
    ok = [r for q in leg.ids for r in leg.ok[q].values()]
    toks = [r.get("output_tokens") or 0 for r in ok]
    longest = max(toks) if toks else 0
    unclosed = [r for r in ok if leg.thinking and r.get("parsed_from") != "after_think"]
    by_task = Counter(r.get("task_type") for r in unclosed)
    return {
        "rows": len(ok),
        "output_tokens_mean": round(mean(toks), 1) if toks else None,
        "output_tokens_max": longest,
        "gpu_hours": round(sum((r.get("latency_s") or 0) / (r.get("batch_n") or 1) for r in ok) / 3600, 2),
        "batch_n": dict(Counter(r.get("batch_n") for r in ok)),
        "unclosed_thinking_rows": len(unclosed),
        "unclosed_at_longest_output": sum(1 for r in unclosed if (r.get("output_tokens") or 0) == longest),
        "unclosed_by_task": dict(by_task),
    }


def reparse(leg):
    """Rows whose stored prediction differs from a parse of the text after the
    last </think> — 0 by construction on rows parsed_from after_think; on a
    leg written without the split it shows what the split would change."""
    changed, flips, with_think = [], Counter(), 0
    for q in leg.ids:
        m = leg.metas[q]
        for r in leg.ok[q].values():
            t = r.get("response_text") or ""
            if "</think>" not in t:
                continue
            with_think += 1
            p2 = parse_choice(t.rsplit("</think>", 1)[1], m["yn"], letters=m["letters"],
                              options=leg.recs[q].get("options"))
            if p2 != r.get("prediction", ""):
                c1 = r.get("correct") is True
                c2 = p2.strip().upper() == m["gold"].strip().upper()
                changed.append((q, r.get("pass_idx"), r.get("prediction"), p2))
                flips[f"{'R' if c1 else 'W'}->{'R' if c2 else 'W'}"] += 1
    return {"rows_with_think_close": with_think, "changed": len(changed),
            "flips": dict(flips), "examples": changed[:8]}


def report_leg(leg, args):
    print(f"\n######## {leg.name}: {len(leg.files)} file(s), backend {leg.backends[0]}, decode {leg.decodes}")
    passes = Counter(len(leg.rows[q]) for q in leg.ids)
    print(f"  questions with rows {len(leg.ids)}/{len(leg.recs)}; passes per question "
          f"{dict(sorted(passes.items()))}; torn lines {leg.torn}; duplicate keys {leg.dups}")
    if max(passes) < 4:
        print(f"  WARNING: at most {max(passes)} pass(es) per question - the k-of-4 labels and the "
              "text-answerable counts below are not meaningful yet")
    overall = summarize(leg, leg.ids, args)
    print("== overall")
    print(json.dumps(overall, indent=1))
    by_task = defaultdict(list)
    for q in leg.ids:
        by_task[leg.metas[q]["task"]].append(q)
    per_task = {}
    print("== per task (acc mean+/-pstdev | chance | key floor in-sample / LOO | longest-option | "
          "text-answerable observed / at chance / bias-null mean [95%] p | acc null p)")
    for t in sorted(by_task):
        s = summarize(leg, by_task[t], args)
        per_task[t] = s
        bn = s["bias_null"]
        print(f"  {t:40s} n={s['n_questions']:4d} acc {s['accuracy']['mean']}+/-{s['accuracy']['std']} | "
              f"{s['chance']} | {s['key_floor_insample']} / {s['key_floor_loo']} | "
              f"{s['longest_option']['acc']} (n={s['longest_option']['n']}) | "
              f"TA {s['labels'].get('text-answerable', 0)} / {s['expected_text_answerable_at_chance']} / "
              f"{bn['null_mean_text_answerable']} {bn['null_95_text_answerable']} p={bn['p_text_answerable']} | "
              f"p={bn['p_correct']}")
    questions, split = per_question(leg)
    print("== text-answerable by majority answer vs its stratum's default (leave-one-out):", dict(split))
    vref = [q for q in leg.ids if questions[q]["video_ref_options"]]
    vref_s = summarize(leg, vref, args, with_null=False) if vref else None
    if vref_s:
        print(f"== clip-reference-only option sets (n={len(vref)}; no text cue can choose): "
              f"acc {vref_s['accuracy']['mean']}+/-{vref_s['accuracy']['std']} vs chance "
              f"{vref_s['chance']}, key floors {vref_s['key_floor_insample']} / "
              f"{vref_s['key_floor_loo']}, labels {vref_s['labels']}")
    hyg, rep = hygiene(leg), reparse(leg)
    print(f"== hygiene: {hyg}")
    print(f"== post-</think> re-parse: {rep}")
    return dict(files=leg.files, backend=leg.backends[0], decode=leg.decodes,
                passes_per_question=dict(passes), torn_lines=leg.torn, duplicate_keys=leg.dups,
                overall=overall, per_task=per_task, text_answerable_split=dict(split),
                video_ref_options=vref_s, hygiene=hyg, reparse=rep, questions=questions)


def both_orders_split(o1, o2, qs, args):
    """Both-orders split of `qs`, its chance expectation, and both bias nulls."""
    ta = lambda leg, q: leg.label(q) == "text-answerable"
    n_both = sum(1 for q in qs if ta(o1, q) and ta(o2, q))
    n_one = sum(1 for q in qs if ta(o1, q) != ta(o2, q))
    exp = 0.0
    for q in qs:
        p = 1.0
        for leg in (o1, o2):
            k, n = leg.kn(q)
            p *= p_at_least(need(n), n, leg.metas[q]["chance"]) if n else 0.0
        exp += p
    out = {"n": len(qs), "both": n_both, "one": n_one, "neither": len(qs) - n_both - n_one,
           "expected_both_at_chance": round(exp, 2)}
    for tag, paired in (("", False), ("_paired", True)):
        nt = permutation_null([o1, o2], qs, args.permutations, args.seed, paired=paired)
        out.update({f"null_mean_both{tag}": nt["null_mean_text_answerable"],
                    f"null_95_both{tag}": nt["null_95_text_answerable"],
                    f"p_both{tag}": nt["p_text_answerable"]})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subset", default=SUBSET)
    ap.add_argument("--blind", action="append", required=True,
                    help="glob of the blind leg's JSONL shards (repeatable)")
    ap.add_argument("--subset-o2", default=SUBSET_O2)
    ap.add_argument("--blind-o2", action="append", default=[],
                    help="glob of the reversed-option (O2) twin leg's shards (repeatable)")
    ap.add_argument("--sighted", action="append", default=[], metavar="LABEL=GLOB",
                    help="a sighted leg on the same questions (repeatable)")
    ap.add_argument("--slice", action="append", default=[], metavar="NAME=IDS.json",
                    help="repeat the headline on these question ids (repeatable)")
    ap.add_argument("--permutations", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", default=None, help="write every table + per-question labels here")
    args = ap.parse_args()

    o1 = Leg(args.subset, args.blind, "O1")
    out = {"O1": report_leg(o1, args)}
    legs = [o1]
    if args.blind_o2:
        o2 = Leg(args.subset_o2, args.blind_o2, "O2")
        if set(o2.recs) != set(o1.recs):
            raise SystemExit("--subset-o2 does not hold the same question ids as --subset")
        if o2.backends != o1.backends or o2.decodes != o1.decodes:
            raise SystemExit(f"O1/O2 legs differ in backend or decode: {o1.backends} {o1.decodes} "
                             f"vs {o2.backends} {o2.decodes}")
        out["O2"] = report_leg(o2, args)
        legs.append(o2)
        both = [q for q in o1.ids if q in set(o2.ids)]
        lab = Counter()
        exp_chance = 0.0
        for q in both:
            l1, l2 = o1.label(q), o2.label(q)
            lab["text-answerable in both orders" if l1 == l2 == "text-answerable" else
                "text-answerable in one order" if "text-answerable" in (l1, l2) else
                "not in either order"] += 1
            p = 1.0
            for leg in (o1, o2):
                k, n = leg.kn(q)
                p *= p_at_least(need(n), n, leg.metas[q]["chance"]) if n else 0.0
            exp_chance += p
        null = permutation_null([o1, o2], both, args.permutations, args.seed)
        null_p = permutation_null([o1, o2], both, args.permutations, args.seed, paired=True)
        out["both_orders"] = {"n_questions": len(both), "labels": dict(lab),
                              "expected_both_at_chance": round(exp_chance, 2), "bias_null": null,
                              "bias_null_paired": null_p}
        by_task, by_fmt = defaultdict(list), defaultdict(list)
        for q in both:
            by_task[o1.metas[q]["task"]].append(q)
            by_fmt["yes/no" if o1.metas[q]["yn"] else "lettered"].append(q)
        out["both_orders"]["per_task"] = {t: both_orders_split(o1, o2, qs, args)
                                          for t, qs in sorted(by_task.items())}
        out["both_orders"]["by_format"] = {f: both_orders_split(o1, o2, qs, args)
                                           for f, qs in sorted(by_fmt.items())}
        print(f"\n######## BOTH ORDERS: {json.dumps(out['both_orders'], indent=1)}")

    out["sighted"] = {}
    for spec in args.sighted:
        label, _, pat = spec.partition("=")
        sf, srows, storn, sdups = load_rows([pat])
        legs_s = defaultdict(lambda: defaultdict(dict))
        for r in srows:
            if r.get("id") in o1.recs and not r.get("error"):
                key = (r.get("method"), r.get("backend"), json.dumps(r.get("decode"), sort_keys=True))
                legs_s[key][r["id"]][r.get("pass_idx")] = r
        for (meth, be, dec), sq in sorted(legs_s.items()):
            name = f"{label}:{meth}/{be}"
            if dec != "null":
                name += f"/{dec}"
            cross = {}
            for lab_ in ("text-answerable", "unstable", "not"):
                qs = [q for q in o1.ids if o1.label(q) == lab_ and sq.get(q)]
                vals = [mean(1.0 if r.get("correct") is True else 0.0 for r in sq[q].values()) for q in qs]
                cross[lab_] = {"n": len(qs), "sighted_acc": pct(mean(vals)) if vals else None}
            rescue = sum(1 for q in o1.ids if o1.label(q) == "not" and sq.get(q)
                         and sum(r.get("correct") is True for r in sq[q].values()) / len(sq[q]) >= 0.75)
            lost = sum(1 for q in o1.ids if o1.label(q) == "text-answerable" and sq.get(q)
                       and not any(r.get("correct") is True for r in sq[q].values()))
            by_pass = defaultdict(list)
            for q in o1.ids:
                for pi, r in sq.get(q, {}).items():
                    by_pass[pi].append(1.0 if r.get("correct") is True else 0.0)
            sacc = mstd({pi: mean(v) for pi, v in by_pass.items() if v})
            out["sighted"][name] = {"files": len(sf), "rows": len(srows), "torn": storn, "dups": sdups,
                                    "accuracy_on_blind_questions": sacc, "by_blind_label": cross,
                                    "blind_not_but_sighted_ge_0.75": rescue,
                                    "blind_text_answerable_but_sighted_never": lost}
            print(f"== sighted {name}: acc {sacc['mean']}+/-{sacc['std']} over {sacc['n_passes']} passes; "
                  f"by blind (O1) label {cross}; pixels rescue {rescue}; blind-only {lost}")

    out["slices"] = {}
    for spec in args.slice:
        name, _, path = spec.partition("=")
        raw = json.load(open(path))
        want = set()
        for x in raw:
            x = x["id"] if isinstance(x, dict) else x
            want.add(x if str(x).startswith("cvb-") else f"cvb-{x}")
        missing = sorted(want - set(o1.recs))
        if missing:
            raise SystemExit(f"slice {name}: {len(missing)} id(s) not in the pool, e.g. {missing[:3]}")
        qs = [q for q in o1.ids if q in want]
        out["slices"][name] = summarize(o1, qs, args)
        print(f"== slice {name}: {len(qs)}/{len(want)} ids with rows: "
              f"acc {out['slices'][name]['accuracy']}, labels {out['slices'][name]['labels']}")

    if args.json:
        json.dump(out, open(args.json, "w"), indent=1)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
