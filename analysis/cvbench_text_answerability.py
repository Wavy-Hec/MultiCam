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
    A-D), so two strata never share an answer space: the in-sample
    modal-gold rate (an upper bound on any task-conditioned letter guesser)
    and its leave-one-out version. In both a tie for the modal answer is
    split evenly (1/m when the gold is one of m tied answers), and on the
    leave-one-out side a question alone in its stratum scores chance. Plus
    the "pick the longest option" rule on lettered questions (ties split);
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
    guessing at chance and (b) the bias null, as baselines for the count.
    Every question needs 4 usable (non-error) rows: on fewer, k/n >= 0.75
    relaxes the rule (2 of 2 would pass), so such a leg is refused unless
    --allow-partial asks to label those questions on the rows they have.
    Each text-answerable question is split by whether its majority answer is
    its stratum's modal prediction computed WITHOUT it (a default the model
    gives anyway) or a departure from it (the most direct evidence of a
    content-driven answer); strata under 5 other questions say n/a;
  * with --blind-o2 (the same questions with options reversed, written by
    convert_cvbench.py --order O2): the same tables for O2, and a BOTH-ORDERS
    label — text-answerable in O1 and in O2 — with its own chance and
    bias-null expectations. A letter-position preference cannot pass both
    orders (except on cvb-996, whose packed options O2 keeps as is), so this
    is the strict text-answerable set on lettered questions;
    a Yes/No answer is a word, so a Yes/No habit passes both, and the label
    is also split by format (convert_cvbench.py describes the 48 questions
    whose reversed options point at other positions). The both-orders bias
    null comes two ways: independent (each order's pass-sets permuted
    separately) and paired (one permutation moves a question's O1 and O2
    pass-sets together, which keeps habits that hold across orders: the
    conservative baseline);
  * trace hygiene: rows whose answer was parsed from the whole text although
    the leg thinks natively (parsed_from != after_think: the trace never closed
    its thinking block, usually the token cap), and how many sit at the leg's
    longest output.

Every null is --permutations draws (default 100,000) from
numpy.random.default_rng(--seed), in blocks of draws; its 95% range is the
2.5th / 97.5th percentile of the sorted draws and p = (1 + draws >= observed)
/ (B + 1), so 1 / (B + 1) is the floor. p is stored to 5 decimals (from
200,000 draws on, the floor rounds to 0.0); draws_ge_observed_* is the exact
count. Percentages computed from counts are exact fractions rounded half-up,
where round() on a binary float sends some ties down; per-pass and sighted
accuracies keep their counts beside them.

The JSON opens with a provenance block: argv, the row and subset files with
their sha256, seed, draws, generator and this script's git blob id. A path
inside the checkout is stored relative to it, any other path as its file
name alone (its sha256 still identifies it); argv's path values, the part
after LABEL= / NAME= and the --json path included, follow the same rule.

A leg is checked before its rows are deduplicated on (id, method, backend,
pass_idx), which a second TAG of the same questions shares: its rows must
come from one run TAG (file name without the shard suffix), one decode stamp
and one backend, and their `dataset` stamp must name the subset they are
scored against (O1 rows against --subset, O2 rows against --subset-o2).
Each row's stored `correct` must also agree with its prediction against that
subset's gold, compared as the blind arm compares them, so a subset
regenerated under its old name with another key is refused, not mixed in.
Every input is read, the --json path checked and its directory created
before the first table.

--sighted LABEL=GLOB crosses each sighted (method, backend) leg's per-question
passes-correct with the blind label (one run TAG per glob). --slice
NAME=IDS.json repeats the headline on a list of question ids (strings
'cvb-<n>', ints, or records with an 'id'): the O1 summary, and with
--blind-o2 the O2 one under the slice's "O2" key.

Writes only the --json path (and its directory); stdout otherwise, and --help
writes nothing.

Run (no GPU, no videos needed), once per leg: TAG _q38bm (thinking) and _q38nt
(the no-thinking control):
  python3 analysis/cvbench_text_answerability.py \\
      --blind 'bench/results/bench_cvbench_full_runnable_subset_cvbench_q38bm_shard*.jsonl' \\
      --blind-o2 'bench/results/bench_cvbench_full_runnable_subset_o2_cvbench_q38bm_shard*.jsonl' \\
      --json analysis/records/cvbench_text_answerability_q38bm.json
"""
import argparse
import glob
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from statistics import mean, pstdev

import numpy as np

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
PASSES = 4                       # the pass count the >= 3-of-4 label is defined on
CHUNK = 10_000                   # null draws per block: memory ~ CHUNK x questions
GENERATOR = "numpy.random.default_rng/" + type(np.random.default_rng(0).bit_generator).__name__


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


def run_stem(path):
    """The run a result file belongs to: its name without the shard suffix
    (bench_<subset>_<ENV><TAG>, as run_bench.sbatch names it), shared by every
    shard of one TAG and by no two TAGs."""
    return re.sub(r"(?:_shard\d+)?\.jsonl$", "", os.path.basename(path))


def read_rows(patterns):
    """(files, [(file, row)], torn lines) for every row the globs match, in
    file order and before any deduplication."""
    files = sorted({f for p in patterns for f in glob.glob(p) if not f.endswith("_summary.json")})
    rows, torn = [], 0
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
                rows.append((f, r))
    return files, rows, torn


def dedup(rows):
    """The first row per (id, method, backend, pass_idx), and how many were dropped."""
    out, seen = [], set()
    for r in rows:
        key = (r.get("id"), r.get("method"), r.get("backend"), r.get("pass_idx"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out, len(rows) - len(out)


def blind_correct(r, gold):
    """`correct` as the blind arm sets it (bench/methods/blind.py): the
    prediction against the gold, both stripped and upper-cased; False on an
    error row."""
    return not r.get("error") and (r.get("prediction") or "").strip().upper() == gold.strip().upper()


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
    """Expected hit of 'pick the longest option' (ties split) as an exact
    fraction, None on Yes/No and on malformed rows whose options do not map
    one-to-one onto letters."""
    if meta["yn"] or len(rec["options"]) != len(meta["letters"]):
        return None
    lens = [len(_PREFIX.sub("", o, count=1).strip()) for o in rec["options"]]
    top = max(lens)
    tied = [meta["letters"][i] for i, n in enumerate(lens) if n == top]
    return Fraction(1, len(tied)) if meta["gold"] in tied else Fraction(0)


def key_floors(metas, ids):
    """(in-sample, leave-one-out) modal-gold hit rates per (task, format)
    stratum learned over the WHOLE pool and scored on `ids`, as exact
    fractions; ties split, and a question alone in its stratum scores chance
    on the leave-one-out side."""
    by = defaultdict(Counter)
    for m in metas.values():
        by[stratum(m)][m["gold"].upper()] += 1
    ins = loo = Fraction(0)
    for q in ids:
        m = metas[q]
        c, g = by[stratum(m)], m["gold"].upper()
        top = max(c.values())
        modal = [k for k, v in c.items() if v == top]
        ins += Fraction(1, len(modal)) if g in modal else 0
        c2 = c.copy()
        c2[g] -= 1
        if sum(c2.values()) == 0:
            loo += Fraction(1, len(m["space"]))
            continue
        top2 = max(c2.values())
        modal2 = [k for k, v in c2.items() if v == top2]
        loo += Fraction(1, len(modal2)) if g in modal2 else 0
    return ins / len(ids), loo / len(ids)


def p_at_least(k, n, p):
    return sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))


def need(n):
    """Smallest k that labels a question text-answerable at n passes."""
    return math.ceil(0.75 * n) if n else 0


def half_up(x, places=2):
    """An exact number (int or Fraction) rounded half-up to `places` decimals.
    round() on a binary float sends some ties down: round(2.675, 2) is 2.67
    (2.675 is no float) and round(0.125, 2) is 0.12 (half to even)."""
    if isinstance(x, float):
        raise TypeError("half_up() takes an exact number (int or Fraction), not a float")
    x = Fraction(x)
    with localcontext() as ctx:
        ctx.prec = 60                       # no quotient of counts this size can cross a tie
        d = Decimal(x.numerator) / Decimal(x.denominator)
    return float(d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def pct(x):
    """An exact ratio (int or Fraction) as a percentage, 2 dp, half-up."""
    return None if x is None else half_up(100 * x)


class Leg:
    """One blind leg over one subset: rows per question (error rows kept apart).

    Refused before its rows are deduplicated (a second TAG or decode of the
    same questions shares every dedup key, so its rows would silently vanish):
    rows from more than one run TAG, decode stamp or backend, and rows whose
    `dataset` stamp names another subset (O1 rows scored against O2's gold, or
    the reverse). Also refused: rows whose stored `correct` disagrees with
    blind_correct against the subset's gold (a key regenerated under the same
    name) and, unless allow_partial, a question with fewer than PASSES usable
    (non-error) rows."""

    def __init__(self, subset, patterns, name, allow_partial=False):
        self.name = name
        with open(subset, encoding="utf-8") as fh:
            self.recs = {r["id"]: r for r in json.load(fh)}
        self.metas = {q: question_meta(r) for q, r in self.recs.items()}
        self.files, raw, self.torn = read_rows(patterns)
        raw = [(f, r) for f, r in raw if r.get("method") == "blind"]
        if not raw:
            raise SystemExit(f"{name}: no blind rows in {patterns}")
        stems = sorted({run_stem(f) for f, _ in raw})
        self.backends = sorted({r.get("backend") for _, r in raw})
        self.decodes = sorted({json.dumps(r.get("decode"), sort_keys=True) for _, r in raw})
        if len(stems) > 1:
            raise SystemExit(f"{name}: blind rows come from {len(stems)} runs {stems}; "
                             "pass one leg (one TAG) at a time")
        if len(self.backends) > 1:
            raise SystemExit(f"{name}: blind rows mix backends {self.backends}; pass one leg at a time")
        if len(self.decodes) > 1:
            raise SystemExit(f"{name}: blind rows mix decode settings {self.decodes}; "
                             "pass one leg (one TAG) at a time")
        want = os.path.splitext(os.path.basename(subset))[0]
        other = sorted({str(r["dataset"]) for _, r in raw if r.get("dataset") not in (None, want)})
        if other:
            raise SystemExit(f"{name}: rows stamp dataset {other} but are scored against {subset}; "
                             "O1 and O2 swapped?")
        rows, self.dups = dedup([r for _, r in raw])
        stray = sorted({r["id"] for r in rows} - set(self.recs))
        if stray:
            raise SystemExit(f"{name}: {len(stray)} row id(s) not in {subset}, e.g. {stray[:3]}")
        # rows keep their own `correct`, the nulls and floors use the subset's
        # gold: a key changed under the same name would mix the two
        rekeyed = sorted({r["id"] for _, r in raw
                          if (r.get("correct") is True) != blind_correct(r, self.metas[r["id"]]["gold"])})
        if rekeyed:
            raise SystemExit(f"{name}: {len(rekeyed)} question(s) have rows whose stored `correct` disagrees "
                             f"with their prediction against the gold in {subset}, e.g. {rekeyed[:3]}; "
                             "was the subset regenerated with another key under the same name?")
        self.rows = {q: {} for q in self.recs}          # every row, for accuracy
        for r in rows:
            self.rows[r["id"]][r.get("pass_idx")] = r
        self.ids = [q for q in self.recs if self.rows[q]]
        self.ok = {q: {pi: r for pi, r in self.rows[q].items() if not r.get("error")}
                   for q in self.ids}                   # non-error rows, for k-of-n
        self.short = [q for q in self.recs if len(self.ok.get(q, ())) < PASSES]
        if self.short and not allow_partial:
            raise SystemExit(f"{name}: {len(self.short)} question(s) have fewer than {PASSES} usable "
                             f"(non-error) rows, e.g. {self.short[:3]}, and k/n >= 0.75 on fewer passes "
                             "relaxes the label; pass --allow-partial to label them on the rows they have")
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

    def pass_counts(self, ids):
        """{pass: (correct, rows)} over `ids`, error rows counted wrong (bench/metrics.py)."""
        cnt = defaultdict(lambda: [0, 0])
        for q in ids:
            for pi, r in self.rows[q].items():
                cnt[pi][0] += r.get("correct") is True
                cnt[pi][1] += 1
        return {pi: tuple(cnt[pi]) for pi in sorted(cnt)}

    def pass_accs(self, ids):
        """Per-pass accuracy over `ids` as exact fractions."""
        return {pi: Fraction(c, n) for pi, (c, n) in self.pass_counts(ids).items()}

    def predsets(self, ids):
        return {q: [r.get("prediction", "") for _, r in sorted(self.ok[q].items())] for q in ids}


def mstd(accs):
    """Mean and population SD over passes of per-pass accuracies given as
    exact fractions: the mean exact and rounded half-up, the SD a float."""
    v = list(accs.values())
    if not v:
        return {"mean": None, "std": None, "n_passes": 0}
    sd = round(100.0 * pstdev([float(a) for a in v]), 2) if len(v) > 1 else 0.0
    return {"mean": pct(sum(v) / len(v)), "std": sd, "n_passes": len(v)}


def null_draws(legs, ids, B, seed, paired=False):
    """The observed (correct passes of leg 0, questions text-answerable in
    every leg) and B null draws of each as numpy arrays; see permutation_null.

    Per stratum, donor j's outcome for receiver i (its passes matching i's
    gold; whether they clear need()) is tabled once, and each block of draws
    permutes donors within strata with numpy.random.default_rng(seed)."""
    rng = np.random.default_rng(seed)
    sets = [leg.predsets(ids) for leg in legs]
    golds = [{q: leg.metas[q]["gold"].strip().upper() for q in ids} for leg in legs]
    votes = [{q: Counter(p.strip().upper() for p in s[q]) for q in ids} for s in sets]

    def hits(li, q, src):                   # donor src's passes on q's gold, leg li
        return votes[li][src][golds[li][q]]

    def passes(li, q, src):                 # ... and whether they label q text-answerable
        n = len(sets[li][src])
        return n > 0 and hits(li, q, src) >= need(n)

    # permutation groups, independent of one another: (the legs that share
    # the group's permutation, its strata)
    if paired:
        st = defaultdict(list)
        for q in ids:
            if all(s[q] for s in sets):
                st[tuple(stratum(leg.metas[q]) for leg in legs)].append(q)
        groups = [(range(len(legs)), list(st.values()))]
    else:
        groups = []
        for li, leg in enumerate(legs):
            st = defaultdict(list)
            for q in ids:
                if sets[li][q]:
                    st[stratum(leg.metas[q])].append(q)
            groups.append(([li], list(st.values())))
    col = {q: i for i, q in enumerate(ids)}
    tables = []
    for shared, strata in groups:
        tables.append([(np.array([col[q] for q in g]),
                        np.array([[hits(0, q, s) for s in g] for q in g], np.int64) if 0 in shared else None,
                        np.array([[all(passes(li, q, s) for li in shared) for s in g] for q in g], bool))
                       for g in strata])

    obs_tot = sum(hits(0, q, q) for q in ids if sets[0][q])
    obs_ta = sum(all(passes(li, q, q) for li in range(len(legs))) for q in ids)
    null_tot, null_ta = np.empty(B, np.int64), np.empty(B, np.int64)
    for lo in range(0, B, CHUNK):
        c = min(CHUNK, B - lo)
        tot = np.zeros(c, np.int64)
        ta = np.ones((c, len(ids)), bool)           # text-answerable in every leg so far
        for tabs in tables:
            got = np.zeros((c, len(ids)), bool)
            for cols, h, t in tabs:
                ar = np.arange(len(cols))
                donor = rng.permuted(np.broadcast_to(ar, (c, len(ar))), axis=1)
                if h is not None:
                    tot += h[ar, donor].sum(axis=1)
                got[:, cols] = t[ar, donor]
            ta &= got
        null_tot[lo:lo + c] = tot
        null_ta[lo:lo + c] = ta.sum(axis=1)
    return obs_tot, obs_ta, null_tot, null_ta


def permutation_null(legs, ids, B, seed, paired=False):
    """Within-stratum permutation of whole pass-sets, independently per leg —
    or, with paired, one permutation per draw shared by every leg, so a donor
    question's pass-sets in all legs travel together (strata are then the
    tuple of the legs' strata, over questions with rows in every leg).
    Observed and null totals of correct passes (leg 0) and of text-answerable
    questions — in every leg at once when several legs are given (the
    both-orders label) — with 2.5/97.5 percentiles and one-sided p values."""
    obs_tot, obs_ta, null_tot, null_ta = null_draws(legs, ids, B, seed, paired)

    def tail(obs, null):
        srt = np.sort(null)
        at = lambda f: int(srt[min(B - 1, int(f * B))])
        ge = int((null >= obs).sum())
        return (half_up(Fraction(int(null.sum()), B)), [at(0.025), at(0.975)],
                round((1 + ge) / (B + 1), 5), ge)

    m_c, r_c, p_c, ge_c = tail(obs_tot, null_tot)
    m_t, r_t, p_t, ge_t = tail(obs_ta, null_ta)
    return {
        "observed_correct": obs_tot,
        "null_mean_correct": m_c,
        "null_95_correct": r_c,
        "p_correct": p_c,
        "observed_text_answerable": obs_ta,
        "null_mean_text_answerable": m_t,
        "null_95_text_answerable": r_t,
        "p_text_answerable": p_t,
        "B": B,
        "draws_ge_observed_correct": ge_c,
        "draws_ge_observed_text_answerable": ge_t,
        "seed": seed,
        "generator": GENERATOR,
    }


def summarize(leg, ids, args, with_null=True):
    lab = Counter(leg.label(q) for q in ids)
    exp_chance = 0.0
    for q in ids:
        k, n = leg.kn(q)
        exp_chance += p_at_least(need(n), n, leg.metas[q]["chance"]) if n else 0.0
    lof = [x for x in (longest_option_hit(leg.recs[q], leg.metas[q]) for q in ids) if x is not None]
    ins, loo = key_floors(leg.metas, ids) if ids else (None, None)
    counts = leg.pass_counts(ids)
    out = {
        "n_questions": len(ids),
        "n_rows": sum(len(leg.rows[q]) for q in ids),
        "n_correct": sum(1 for q in ids for r in leg.rows[q].values() if r.get("correct") is True),
        "accuracy": mstd(leg.pass_accs(ids)),
        "per_pass": {str(k): pct(Fraction(c, n)) for k, (c, n) in counts.items()},
        "per_pass_counts": {str(k): [c, n] for k, (c, n) in counts.items()},
        "chance": pct(sum(Fraction(1, len(leg.metas[q]["space"])) for q in ids) / len(ids)) if ids else None,
        "key_floor_insample": pct(ins),
        "key_floor_loo": pct(loo),
        "longest_option": {"acc": pct(sum(lof) / len(lof)) if lof else None, "n": len(lof)},
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
    if leg.short:
        print(f"  WARNING: --allow-partial: {len(leg.short)} question(s) have fewer than {PASSES} usable "
              "rows; those with rows are labelled ceil(0.75 n) of the n they have")
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
    return dict(files=[path_ref(f) for f in leg.files], backend=leg.backends[0], decode=leg.decodes,
                passes_per_question=dict(passes), torn_lines=leg.torn, duplicate_keys=leg.dups,
                partial_questions=len(leg.short),
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


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_blob(path):
    """The blob id `git hash-object` prints for a file checked out with LF line ends."""
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def path_ref(path):
    """A path (or glob) as the JSON stores it, in the provenance block and in
    each order's `files`: relative to the repo when inside the checkout, else
    its file name alone, so no user's home or scratch directory reaches the
    JSON."""
    p = os.path.abspath(path)
    rel = os.path.relpath(p, REPO)
    return os.path.basename(p) if rel == os.pardir or rel.startswith(os.pardir + os.sep) else rel


def file_ref(path):
    """{path (path_ref), sha256}: the hash still identifies a file outside the checkout."""
    return {"path": path_ref(path), "sha256": sha256_of(path)}


# the options whose values are paths or globs: True for a LABEL=<path> spec
PATH_OPTS = {"--subset": False, "--blind": False, "--subset-o2": False, "--blind-o2": False,
             "--sighted": True, "--slice": True, "--json": False}


def argv_ref(argv):
    """argv with every path-valued token through path_ref: the script, and a
    path option's value given as '--opt value' or '--opt=value' (the option
    abbreviated or not; after LABEL= in a spec). Run on an argv argparse has
    accepted, so an abbreviation names one option."""
    def opt(tok):
        if tok in PATH_OPTS:
            return tok
        hits = [o for o in PATH_OPTS if tok.startswith("--") and o.startswith(tok)]
        return hits[0] if len(hits) == 1 else None

    def ref(o, val):
        label, eq, p = val.partition("=")
        return f"{label}={path_ref(p)}" if PATH_OPTS[o] and eq else path_ref(val)

    out, want = [path_ref(argv[0])], None
    for tok in argv[1:]:
        if want:
            out.append(ref(want, tok))
            want = None
            continue
        name, eq, val = tok.partition("=")
        o = opt(name)
        out.append(f"{name}={ref(o, val)}" if o and eq else tok)
        want = o if not eq else None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subset", default=SUBSET)
    ap.add_argument("--blind", action="append", required=True,
                    help="glob of the blind leg's JSONL shards (repeatable; one TAG)")
    ap.add_argument("--subset-o2", default=SUBSET_O2)
    ap.add_argument("--blind-o2", action="append", default=[],
                    help="glob of the reversed-option (O2) twin leg's shards (repeatable)")
    ap.add_argument("--sighted", action="append", default=[], metavar="LABEL=GLOB",
                    help="a sighted leg on the same questions (repeatable; one TAG per glob)")
    ap.add_argument("--slice", action="append", default=[], metavar="NAME=IDS.json",
                    help="repeat the headline on these question ids, per order (repeatable)")
    ap.add_argument("--permutations", type=int, default=100_000, help="draws per null")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--allow-partial", action="store_true",
                    help=f"label a question with fewer than {PASSES} usable rows on the n it has "
                         "(ceil(0.75 n) of n) instead of refusing the leg")
    ap.add_argument("--json", default=None, help="write every table + per-question labels here")
    args = ap.parse_args(argv)

    # every input is read before the first table, so a bad flag fails before any null runs
    if args.permutations < 1:
        raise SystemExit("--permutations must be at least 1")
    if args.seed < 0:
        raise SystemExit("--seed must be at least 0")
    if args.json:
        if os.path.basename(args.json) in ("", os.curdir, os.pardir) or os.path.isdir(args.json):
            raise SystemExit(f"--json: {args.json} names a directory; give the file to write")
        if os.path.exists(args.json) and not os.access(args.json, os.W_OK):
            raise SystemExit(f"--json: {args.json} exists and is not writable")
        d = os.path.dirname(os.path.abspath(args.json))
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            raise SystemExit(f"--json: cannot create {d}: {e}") from e
        if not os.access(d, os.W_OK):
            raise SystemExit(f"--json: {d} is not writable")
    o1 = Leg(args.subset, args.blind, "O1", args.allow_partial)
    o2 = None
    if args.blind_o2:
        o2 = Leg(args.subset_o2, args.blind_o2, "O2", args.allow_partial)
        if set(o2.recs) != set(o1.recs):
            raise SystemExit("--subset-o2 does not hold the same question ids as --subset")
        if o2.backends != o1.backends or o2.decodes != o1.decodes:
            raise SystemExit(f"O1/O2 legs differ in backend or decode: {o1.backends} {o1.decodes} "
                             f"vs {o2.backends} {o2.decodes}")
    sighted = []
    for spec in args.sighted:
        label, _, pat = spec.partition("=")
        sf, raw, storn = read_rows([pat])
        if not raw:
            raise SystemExit(f"--sighted {spec}: no rows match")
        stems = sorted({run_stem(f) for f, _ in raw})
        if len(stems) > 1:
            raise SystemExit(f"--sighted {label}: rows come from {len(stems)} runs {stems}; "
                             "pass one leg (one TAG) per --sighted")
        srows, sdups = dedup([r for _, r in raw])
        if not any(r.get("id") in o1.recs for r in srows):
            raise SystemExit(f"--sighted {label}: no row is on a question of {args.subset}")
        sighted.append((label, sf, srows, storn, sdups))
    slices = []
    for spec in args.slice:
        name, _, path = spec.partition("=")
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as e:                 # ValueError: not UTF-8 JSON
            raise SystemExit(f"--slice {spec}: {e}") from e
        want = set()
        for x in raw:
            x = x["id"] if isinstance(x, dict) else x
            want.add(x if str(x).startswith("cvb-") else f"cvb-{x}")
        missing = sorted(want - set(o1.recs))
        if missing:
            raise SystemExit(f"slice {name}: {len(missing)} id(s) not in the pool, e.g. {missing[:3]}")
        slices.append((name, path, want))

    prov = {"argv": argv_ref(sys.argv if argv is None else [sys.argv[0], *argv]),
            "script": file_ref(__file__), "script_git_blob": git_blob(__file__),
            "seed": args.seed, "permutations": args.permutations, "generator": GENERATOR,
            "numpy": np.__version__, "draws_per_block": CHUNK, "allow_partial": args.allow_partial,
            "subsets": {"O1": file_ref(args.subset)}, "rows": {"O1": [file_ref(f) for f in o1.files]},
            "sighted": {label: [file_ref(f) for f in sf] for label, sf, *_ in sighted},
            "slices": {name: file_ref(path) for name, path, _ in slices}}
    if o2:
        prov["subsets"]["O2"] = file_ref(args.subset_o2)
        prov["rows"]["O2"] = [file_ref(f) for f in o2.files]
    out = {"provenance": prov, "O1": report_leg(o1, args)}
    if o2:
        out["O2"] = report_leg(o2, args)
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
    for label, sf, srows, storn, sdups in sighted:
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
                hit = [sum(r.get("correct") is True for r in sq[q].values()) for q in qs]
                n_r = [len(sq[q]) for q in qs]
                vals = [Fraction(h, n) for h, n in zip(hit, n_r, strict=True)]
                cross[lab_] = {"n": len(qs), "sighted_acc": pct(sum(vals) / len(vals)) if vals else None,
                               "sighted_correct": sum(hit), "sighted_rows": sum(n_r)}
            rescue = sum(1 for q in o1.ids if o1.label(q) == "not" and sq.get(q)
                         and sum(r.get("correct") is True for r in sq[q].values()) / len(sq[q]) >= 0.75)
            lost = sum(1 for q in o1.ids if o1.label(q) == "text-answerable" and sq.get(q)
                       and not any(r.get("correct") is True for r in sq[q].values()))
            by_pass = defaultdict(lambda: [0, 0])
            for q in o1.ids:
                for pi, r in sq.get(q, {}).items():
                    by_pass[pi][0] += r.get("correct") is True
                    by_pass[pi][1] += 1
            sacc = mstd({pi: Fraction(c, n) for pi, (c, n) in by_pass.items()})
            out["sighted"][name] = {"files": len(sf), "rows": len(srows), "torn": storn, "dups": sdups,
                                    "accuracy_on_blind_questions": sacc,
                                    "correct_on_blind_questions": sum(c for c, _ in by_pass.values()),
                                    "rows_on_blind_questions": sum(n for _, n in by_pass.values()),
                                    "by_blind_label": cross,
                                    "blind_not_but_sighted_ge_0.75": rescue,
                                    "blind_text_answerable_but_sighted_never": lost}
            print(f"== sighted {name}: acc {sacc['mean']}+/-{sacc['std']} over {sacc['n_passes']} passes; "
                  f"by blind (O1) label {cross}; pixels rescue {rescue}; blind-only {lost}")

    out["slices"] = {}
    for name, _path, want in slices:
        qs = [q for q in o1.ids if q in want]
        out["slices"][name] = summarize(o1, qs, args)
        print(f"== slice {name}: {len(qs)}/{len(want)} ids with rows: "
              f"acc {out['slices'][name]['accuracy']}, labels {out['slices'][name]['labels']}")
        if o2:
            qs = [q for q in o2.ids if q in want]
            s2 = out["slices"][name]["O2"] = summarize(o2, qs, args)
            print(f"== slice {name} (O2): {len(qs)}/{len(want)} ids with rows: "
                  f"acc {s2['accuracy']}, labels {s2['labels']}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(out, fh, indent=1)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
