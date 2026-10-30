"""CVBench text-only analysis: the converter's O2 transform, the answerability
script's labels, nulls, rounding and input guards, and rescore's leg table.

* analysis/convert_cvbench.reverse_options: Yes/No swapped with the gold word
  kept; lettered options reversed with the gold letter remapped and its text
  kept; a packed single-string row (cvb-996) kept as is; duplicated prefixes
  (cvb-431) re-lettered; a gold letter outside the options refused. The
  tracked O2 subset is exactly the transform of the tracked O1 subset.
* analysis/cvbench_text_answerability: the >= 3-of-4 label per order and in
  both orders; the independent and paired permutation nulls against their
  exact expectations (a uniform permutation gives each receiver a donor
  uniform over its stratum), on a partial leg too, where each donor is held
  to its own pass count; the 95% range's order statistics, p and the
  half-up null mean on a crafted null; half-up rounding of exact fractions;
  the refusals: a glob spanning two TAGs, two decode stamps or two backends
  (checked before the dedup that would hide them), an O1/O2 pair decoded
  differently, a question short of 4 usable rows (3 included) unless
  --allow-partial, rows stamped with the other order's dataset, rows whose
  stored `correct` follows a key since changed under the same name, and an
  unusable --json path, --seed, --slice file or sighted glob (one TAG per
  glob) before anything is computed; and a provenance block that holds no
  path outside the checkout.
* analysis/rescore_answers: the file label keeps 'cvbench_', and legs that
  differ only by TAG or decode print as separate lines.

Pure CPU — toy legs in a temp dir; the O2 check reads the tracked subsets.
Runnable either way:

    pytest bench/tests/test_cvbench_analysis.py
    python  bench/tests/test_cvbench_analysis.py
"""
import contextlib
import io
import json
import math
import os
import sys
import tempfile
from collections import Counter, defaultdict
from fractions import Fraction
from statistics import mean

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "analysis"))

import convert_cvbench as cc  # noqa: E402
import cvbench_text_answerability as cta  # noqa: E402
import rescore_answers as ra  # noqa: E402

SUB, SUB2 = "toy_cvbench_subset", "toy_cvbench_subset_o2"
DECODE = {"enable_thinking": None, "reasoning_effort": "medium"}

# O1 options; the O2 twin reverses them (gold A->D, B->C; Yes/No keep the word)
QUESTIONS = [("cvb-0", "ABCD", "A"), ("cvb-1", "ABCD", "B"), ("cvb-2", "ABCD", "C"),
             ("cvb-3", "ABCD", "D"), ("cvb-4", "YN", "Yes"), ("cvb-5", "YN", "Yes"),
             ("cvb-6", "YN", "No")]
IDS = [q for q, *_ in QUESTIONS]
# 4 passes per question: a B habit, plus answers that follow the option text
PREDS_O1 = {"cvb-0": "AAAB", "cvb-1": "BBBB", "cvb-2": "BBCC", "cvb-3": "BBBB",
            "cvb-4": ["Yes", "Yes", "Yes", "No"], "cvb-5": ["No"] * 4, "cvb-6": ["No"] * 4}
PREDS_O2 = {"cvb-0": "DDDB", "cvb-1": "BBBB", "cvb-2": "BBBC", "cvb-3": "BBAA",
            "cvb-4": ["Yes"] * 4, "cvb-5": ["No", "No", "Yes", "No"], "cvb-6": ["No", "No", "No", "Yes"]}
# by hand: O1 k = 3 4 2 0 3 0 4, O2 k = 3 0 3 2 4 1 3
LABELS_O1 = ["text-answerable", "text-answerable", "unstable", "not", "text-answerable", "not",
             "text-answerable"]
LABELS_O2 = ["text-answerable", "not", "text-answerable", "unstable", "text-answerable", "unstable",
             "text-answerable"]


def _records(order):
    out = []
    for q, kind, gold in QUESTIONS:
        if kind == "YN":
            opts = ["Yes.", "No."] if order == "O1" else ["No.", "Yes."]
        else:
            opts = [f"{c}. option text {c}" for c in "ABCD"]
            if order == "O2":
                opts = [f"{c}. option text {b}" for c, b in zip("ABCD", "DCBA", strict=True)]
                gold = "DCBA"["ABCD".index(gold)]
        out.append({"id": q, "task_type": "toy task", "question": f"{q}?", "options": opts,
                    "answer": gold})
    return out


def _write_subset(d, stem, order):
    path = os.path.join(d, f"{stem}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_records(order), fh)
    return path


def _rows(stem, order, preds, decode=DECODE, errors=()):
    gold = {r["id"]: cta.question_meta(r)["gold"] for r in _records(order)}
    rows = []
    for q, ps in preds.items():
        for i, p in enumerate(ps, 1):
            err = "boom" if (q, i) in errors else None
            rows.append({"id": q, "method": "blind", "backend": "Toy-1B", "pass_idx": i,
                         "prediction": "" if err else p, "correct": not err and p == gold[q],
                         "abstained": bool(err), "error": err, "dataset": stem, "decode": decode,
                         "task_type": "toy task", "response_text": f"<answer>{p}</answer>"})
    return rows


def _write_rows(d, stem, tag, rows, shard=0):
    """bench_<subset>_toy<TAG>_shard<n>.jsonl, the way run_bench.sbatch names a shard."""
    path = os.path.join(d, f"bench_{stem}_toy{tag}_shard{shard}.jsonl")
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


def _toy(d):
    """Both orders of the toy leg on disk: (O1 subset, O1 glob, O2 subset, O2 glob)."""
    s1, s2 = _write_subset(d, SUB, "O1"), _write_subset(d, SUB2, "O2")
    _write_rows(d, SUB, "_a", _rows(SUB, "O1", PREDS_O1))
    _write_rows(d, SUB2, "_a", _rows(SUB2, "O2", PREDS_O2))
    return (s1, os.path.join(d, f"bench_{SUB}_toy_a_shard*.jsonl"),
            s2, os.path.join(d, f"bench_{SUB2}_toy_a_shard*.jsonl"))


def _main(*argv):
    """cvbench_text_answerability.main(argv): (stdout, SystemExit message or None)."""
    buf, msg = io.StringIO(), None
    with contextlib.redirect_stdout(buf):
        try:
            cta.main(list(argv))
        except SystemExit as e:
            msg = str(e)
    return buf.getvalue(), msg


def _refused(fn, *words):
    try:
        fn()
    except SystemExit as e:
        assert all(w in str(e) for w in words), (words, str(e))
        return
    raise AssertionError(f"not refused (expected {words})")


def exact_null_means(legs, ids, paired=False):
    """E[correct passes of leg 0] and E[questions text-answerable in every leg]
    under the permutation null, in closed form: a uniform permutation of a
    stratum of n questions gives each receiver a donor uniform over the n, so
    E = sum over strata of (1/n) * sum_ij [donor j's passes give receiver i the
    outcome]; legs permuted independently multiply per receiver. Written apart
    from the script's tables, as the check on them."""
    sets = [leg.predsets(ids) for leg in legs]

    def k(li, q, s):
        g = legs[li].metas[q]["gold"].strip().upper()
        return sum(p.strip().upper() == g for p in sets[li][s])

    def ta(li, q, s):
        n = len(sets[li][s])
        return n > 0 and k(li, q, s) >= math.ceil(0.75 * n)

    def strata(which):                  # question -> its stratum's members
        by = defaultdict(list)
        for s in ids:
            if all(sets[li][s] for li in which):
                by[tuple((legs[li].metas[s]["task"], legs[li].metas[s]["fmt"]) for li in which)].append(s)
        return {q: g for g in by.values() for q in g}

    every = range(len(legs))
    e_tot = e_ta = Fraction(0)
    if paired:
        for q, g in strata(every).items():
            e_tot += Fraction(sum(k(0, q, s) for s in g), len(g))
            e_ta += Fraction(sum(all(ta(li, q, s) for li in every) for s in g), len(g))
        return e_tot, e_ta
    st = [strata([li]) for li in every]
    for q in ids:
        if q in st[0]:
            e_tot += Fraction(sum(k(0, q, s) for s in st[0][q]), len(st[0][q]))
        p = Fraction(1)
        for li in every:
            g = st[li].get(q)
            p *= Fraction(sum(ta(li, q, s) for s in g), len(g)) if g else 0
        e_ta += p
    return e_tot, e_ta


def mc_close(null, exact, sigmas=4.0):
    """(|mean - exact| within `sigmas` Monte Carlo standard errors, (mean, exact, se))."""
    n = len(null)
    m = sum(int(x) for x in null) / n
    se = math.sqrt(sum((int(x) - m) ** 2 for x in null) / (n - 1) / n)
    return abs(m - float(exact)) <= sigmas * se + 1e-12, (m, float(exact), se)


# ------------------------------------------------------------- convert ---

def test_o2_reverses_letters_and_keeps_the_gold_text():
    rec = {"id": "cvb-7", "options": ["A. red", "B. green", "C. blue", "D. none"], "answer": "B"}
    st = Counter()
    o2 = cc.reverse_options(rec, st)
    assert o2["options"] == ["A. none", "B. blue", "C. green", "D. red"] and o2["answer"] == "C"
    assert rec["options"][0] == "A. red" and rec["answer"] == "B"          # input untouched
    yn = cc.reverse_options({"id": "cvb-0", "options": ["Yes.", "No."], "answer": "No"}, st)
    assert yn["options"] == ["No.", "Yes."] and yn["answer"] == "No"
    assert st == Counter(o2_reversed=1, o2_yesno_swapped=1)


def test_o2_keeps_packed_options_and_reletters_duplicated_prefixes():
    packed = {"id": "cvb-996", "options": ["A. Use the same color paper, B. Reinforce wings with "
                                           "tape, C. Maintain precise folds and symmetry, D. Widen "
                                           "the wings of a paper airplane"], "answer": "D"}
    st = Counter()
    assert cc.reverse_options(packed, st) == packed and st["o2_kept_unsplittable"] == 1
    dup = {"id": "cvb-431", "options": ["A. Video 1.", "B. Video 2.", "B. Both of them.", "B. None of them."],
           "answer": "A"}
    o2 = cc.reverse_options(dup, st)
    assert o2["options"] == ["A. None of them.", "B. Both of them.", "C. Video 2.", "D. Video 1."]
    assert o2["answer"] == "D" and st["o2_relettered_bad_prefixes"] == 1


def test_o2_refuses_a_gold_letter_outside_the_options():
    for opts, ans in ((["A. x", "B. y"], "D"), (["A. x", "B. y", "C. z", "D. w"], "E"),
                      (["A. x", "B. y"], "AB")):
        try:
            cc.reverse_options({"id": "cvb-1", "options": opts, "answer": ans}, Counter())
        except ValueError as e:
            assert "cvb-1" in str(e)
        else:
            raise AssertionError(f"gold {ans!r} on {len(opts)} options was reversed")


def test_tracked_o2_subset_is_the_transform_of_tracked_o1():
    with open(os.path.join(REPO, "analysis", "cvbench_full_runnable_subset.json"), encoding="utf-8") as fh:
        o1 = json.load(fh)
    st = Counter()
    got = json.dumps([cc.reverse_options(r, st) for r in o1], ensure_ascii=False).encode("utf-8")
    with open(os.path.join(REPO, "analysis", "cvbench_full_runnable_subset_o2.json"), "rb") as fh:
        assert got == fh.read()
    assert st == Counter(o2_reversed=863, o2_yesno_swapped=136, o2_kept_unsplittable=1,
                         o2_relettered_bad_prefixes=1)


# ------------------------------------------------------------- rounding ---

def test_half_up_rounds_exact_ties_up():
    # round() on floats: 2.675 is no float, and 0.125 / 12.25 round half to even
    assert (round(2.675, 2), round(0.125, 2), round(12.25, 1)) == (2.67, 0.12, 12.2)
    assert cta.half_up(Fraction(2675, 1000)) == 2.68 and cta.half_up(Fraction(1, 8)) == 0.13
    assert cta.half_up(Fraction(1225, 100), 1) == 12.3
    assert cta.pct(Fraction(3, 4000)) == 0.08 and cta.pct(Fraction(1, 800)) == 0.13
    assert cta.half_up(Fraction(-1, 8)) == -0.13 and cta.pct(Fraction(1, 3)) == 33.33
    assert cta.pct(None) is None and cta.pct(1) == 100.0
    try:
        cta.pct(0.49325)
    except TypeError:
        pass
    else:
        raise AssertionError("a float reached the exact rounding")
    # four passes over 200 questions: the float mean of the per-pass accuracies
    # (the old path) rounds the tie 365/800 = 45.625 down; the SD is as before
    accs = {1: Fraction(80, 200), 2: Fraction(85, 200), 3: Fraction(101, 200), 4: Fraction(99, 200)}
    assert round(100.0 * mean([0.4, 0.425, 0.505, 0.495]), 2) == 45.62
    assert cta.mstd(accs) == {"mean": 45.63, "std": 4.48, "n_passes": 4}


# --------------------------------------------------------------- labels ---

def test_three_of_four_label_per_order_and_in_both_orders():
    with tempfile.TemporaryDirectory() as d:
        s1, g1, s2, g2 = _toy(d)
        o1, o2 = cta.Leg(s1, [g1], "O1"), cta.Leg(s2, [g2], "O2")
        assert [o1.label(q) for q in IDS] == LABELS_O1
        assert [o2.label(q) for q in IDS] == LABELS_O2
        assert cta.need(4) == 3 and o1.kn("cvb-0") == (3, 4) and o1.kn("cvb-2") == (2, 4)
        out, msg = _main("--subset", s1, "--blind", g1, "--subset-o2", s2, "--blind-o2", g2,
                         "--permutations", "50", "--json", os.path.join(d, "out.json"))
        assert msg is None, msg
        with open(os.path.join(d, "out.json")) as fh:
            j = json.load(fh)
    # cvb-0, cvb-4, cvb-6 pass both orders; cvb-1, cvb-2 one; cvb-3, cvb-5 neither
    assert j["both_orders"]["labels"] == {"text-answerable in both orders": 3,
                                          "text-answerable in one order": 2, "not in either order": 2}
    assert j["both_orders"]["by_format"]["lettered"]["both"] == 1
    assert j["both_orders"]["by_format"]["yes/no"]["both"] == 2
    assert j["O1"]["overall"]["labels"] == dict(Counter(LABELS_O1))
    assert j["O1"]["overall"]["per_pass_counts"] == {"1": [4, 7], "2": [4, 7], "3": [5, 7], "4": [3, 7]}
    assert j["O1"]["overall"]["n_correct"] == 16 and j["O1"]["overall"]["accuracy"]["mean"] == 57.14


# ---------------------------------------------------------------- nulls ---

def test_nulls_match_their_exact_expectations():
    with tempfile.TemporaryDirectory() as d:
        s1, g1, s2, g2 = _toy(d)
        o1, o2 = cta.Leg(s1, [g1], "O1"), cta.Leg(s2, [g2], "O2")
    B = 12_345                                       # one full block of draws and a partial one
    seen = {}
    for name, legs, paired in (("O1", [o1], False), ("O2", [o2], False), ("both", [o1, o2], False),
                               ("paired", [o1, o2], True)):
        obs_tot, obs_ta, null_tot, null_ta = cta.null_draws(legs, IDS, B, seed=0, paired=paired)
        e_tot, e_ta = exact_null_means(legs, IDS, paired)
        for null, exact in ((null_tot, e_tot), (null_ta, e_ta)):
            ok, info = mc_close(null, exact)
            assert ok, (name, info)
        seen[name] = (obs_tot, obs_ta, e_tot, e_ta)
    # by hand: observed (each question its own donor) and exact (each donor
    # equally likely); the paired null keeps the habits both orders share
    assert seen["O1"] == (16, 4, 9, Fraction(25, 12)) and seen["O2"] == (16, 4, 10, Fraction(25, 12))
    assert seen["both"] == (16, 3, 9, Fraction(35, 48)) and seen["paired"] == (16, 3, 9, Fraction(19, 12))
    # one seed, one stream; another seed, other draws
    a, b, c = (cta.null_draws([o1, o2], IDS, 2000, s, paired=True) for s in (0, 0, 1))
    assert (a[3] == b[3]).all() and not (a[3] == c[3]).all()
    # the summary's percentile and p rules
    n = cta.permutation_null([o1, o2], IDS, 2000, 0, paired=True)
    srt = sorted(int(x) for x in a[3])
    ge = sum(x >= 3 for x in srt)
    assert n["null_95_text_answerable"] == [srt[50], srt[1950]]
    assert n["draws_ge_observed_text_answerable"] == ge and n["p_text_answerable"] == round((1 + ge) / 2001, 5)
    assert n["null_mean_text_answerable"] == cta.half_up(Fraction(sum(srt), 2000))
    assert n["B"] == 2000 and n["seed"] == 0 and n["generator"] == cta.GENERATOR


def test_null_is_a_point_mass_when_every_donor_is_alike():
    with tempfile.TemporaryDirectory() as d:
        s1 = _write_subset(d, SUB, "O1")
        same = {q: ["No"] * 4 for q in ("cvb-4", "cvb-5", "cvb-6")}      # one Yes/No stratum
        _write_rows(d, SUB, "_a", _rows(SUB, "O1", same))
        leg = cta.Leg(s1, [os.path.join(d, "bench_*.jsonl")], "O1", allow_partial=True)
    n = cta.permutation_null([leg], ["cvb-4", "cvb-5", "cvb-6"], 300, 0)
    assert (n["observed_correct"], n["null_mean_correct"], n["null_95_correct"]) == (4, 4.0, [4, 4])
    assert n["p_correct"] == 1.0 and n["observed_text_answerable"] == 1


def test_a_partial_leg_holds_each_donor_to_its_own_pass_count():
    with tempfile.TemporaryDirectory() as d:
        s1 = _write_subset(d, SUB, "O1")
        # cvb-0's passes 3 and 4 errored, so as a donor its 2 usable rows
        # (B, B) clear need(2) = 2 for cvb-1 (gold B); judged on cvb-1's own
        # 4 passes, need(4) = 3, they would not
        _write_rows(d, SUB, "_a", _rows(SUB, "O1", dict(PREDS_O1, **{"cvb-0": "BBAA"}),
                                        errors={("cvb-0", 3), ("cvb-0", 4)}))
        leg = cta.Leg(s1, [os.path.join(d, "bench_*.jsonl")], "O1", allow_partial=True)
    assert leg.kn("cvb-0") == (0, 2)
    obs_tot, obs_ta, null_tot, null_ta = cta.null_draws([leg], IDS, 20_000, seed=0)
    e_tot, e_ta = exact_null_means([leg], IDS)
    # by hand: 3 of the 16 lettered donor/receiver pairs pass (donors cvb-0,
    # cvb-1 and cvb-3 for cvb-1) and 4 of the 9 Yes/No ones, so 3/4 + 4/3;
    # held to the receiver's pass count instead, cvb-0 fails cvb-1: 22/12
    assert (obs_tot, obs_ta, e_tot, e_ta) == (13, 3, Fraction(17, 2), Fraction(25, 12))
    for null, exact in ((null_tot, e_tot), (null_ta, e_ta)):
        ok, info = mc_close(null, exact)
        assert ok, info


def test_summary_rules_on_a_crafted_null():
    B = 2000
    # every draw distinct: the 95% range is the sorted draws at int(0.025 B)
    # and int(0.975 B), 50 and 1950, where 49 and 1949 are other values
    ta = np.random.default_rng(1).permutation(B)
    # mean 8250 / 2000 = 4.125, an exact tie: round() sends it down (half to
    # even), the stored mean is rounded half-up
    tot = np.array([4] * 1750 + [5] * 250)
    assert round(int(tot.sum()) / B, 2) == 4.12
    big = np.zeros(200_000, np.int64)
    real = cta.null_draws
    try:
        cta.null_draws = lambda *a, **k: (5, 1990, tot, ta)
        n = cta.permutation_null([], [], B, 0)
        cta.null_draws = lambda *a, **k: (1, 1, big, big)
        floor = cta.permutation_null([], [], len(big), 0)
    finally:
        cta.null_draws = real
    assert n["null_95_text_answerable"] == [50, 1950] and n["null_mean_text_answerable"] == 999.5
    assert n["null_95_correct"] == [4, 5] and n["null_mean_correct"] == 4.13
    # p from the exact count of draws >= observed: 10 of them >= 1990, 250 >= 5
    assert (n["draws_ge_observed_text_answerable"], n["p_text_answerable"]) == (10, 0.0055)
    assert (n["draws_ge_observed_correct"], n["p_correct"]) == (250, 0.12544)
    # p is stored to 5 decimals: from 200,000 draws on, the floor reads 0.0
    assert (floor["draws_ge_observed_correct"], floor["p_correct"]) == (0, 0.0)


# --------------------------------------------------------------- guards ---

def test_a_glob_over_two_tags_is_refused_before_dedup():
    with tempfile.TemporaryDirectory() as d:
        s1, g1, _, _ = _toy(d)
        # a second TAG of the same questions: every dedup key collides with _a's
        _write_rows(d, SUB, "_b", _rows(SUB, "O1", PREDS_O1, decode=dict(DECODE, enable_thinking=False)))
        _refused(lambda: cta.Leg(s1, [os.path.join(d, f"bench_{SUB}_toy_*_shard*.jsonl")], "O1"), "2 runs")
        # two shards of one TAG are one leg
        _write_rows(d, SUB, "_c", _rows(SUB, "O1", {q: PREDS_O1[q] for q in IDS[:3]}), shard=0)
        _write_rows(d, SUB, "_c", _rows(SUB, "O1", {q: PREDS_O1[q] for q in IDS[3:]}), shard=1)
        leg = cta.Leg(s1, [os.path.join(d, f"bench_{SUB}_toy_c_shard*.jsonl")], "O1")
        assert len(leg.files) == 2 and leg.dups == 0 and leg.ids == IDS


def test_one_tag_with_two_decode_stamps_is_refused():
    with tempfile.TemporaryDirectory() as d:
        s1 = _write_subset(d, SUB, "O1")
        _write_rows(d, SUB, "_a", _rows(SUB, "O1", PREDS_O1), shard=0)
        # a stale shard of the same questions under other settings
        _write_rows(d, SUB, "_a", _rows(SUB, "O1", PREDS_O1, decode=None), shard=1)
        _refused(lambda: cta.Leg(s1, [os.path.join(d, "bench_*_shard*.jsonl")], "O1"), "decode")


def test_one_tag_with_two_backends_and_o1_o2_decoded_differently_are_refused():
    with tempfile.TemporaryDirectory() as d:
        s1, g1, s2, _ = _toy(d)
        # a second backend's shard under the same TAG: its dedup keys differ,
        # so its rows would replace the first backend's pass by pass
        _write_rows(d, SUB, "_a", [dict(r, backend="Toy-2B") for r in _rows(SUB, "O1", PREDS_O1)], shard=1)
        _refused(lambda: cta.Leg(s1, [g1], "O1"), "backends", "Toy-2B")
        # one TAG each, but the O2 leg ran under other settings: not twins
        _write_rows(d, SUB2, "_n", _rows(SUB2, "O2", PREDS_O2, decode=dict(DECODE, enable_thinking=False)))
        out, msg = _main("--subset", s1, "--blind", os.path.join(d, f"bench_{SUB}_toy_a_shard0.jsonl"),
                         "--subset-o2", s2, "--blind-o2", os.path.join(d, f"bench_{SUB2}_toy_n_shard*.jsonl"),
                         "--permutations", "10")
    assert msg and "differ in backend or decode" in msg and "######## O1" not in out, msg


def test_short_questions_need_allow_partial():
    with tempfile.TemporaryDirectory() as d:
        s1 = _write_subset(d, SUB, "O1")
        # cvb-0: passes 3 and 4 errored, so 2 of its 2 usable rows are right
        _write_rows(d, SUB, "_a", _rows(SUB, "O1", dict(PREDS_O1, **{"cvb-0": "AABB"}),
                                        errors={("cvb-0", 3), ("cvb-0", 4)}))
        g = os.path.join(d, "bench_*.jsonl")
        _refused(lambda: cta.Leg(s1, [g], "O1"), "--allow-partial", "cvb-0")
        leg = cta.Leg(s1, [g], "O1", allow_partial=True)
        assert leg.kn("cvb-0") == (2, 2) and leg.label("cvb-0") == "text-answerable"
        assert leg.short == ["cvb-0"]
        # a question with no rows at all is short too
        _write_rows(d, SUB, "_a", _rows(SUB, "O1", {q: PREDS_O1[q] for q in IDS[:-1]}))
        _refused(lambda: cta.Leg(s1, [g], "O1"), "cvb-6")
        # and so is one with 3: 3 of 3 would pass where 3 of 4 is the bar
        _write_rows(d, SUB, "_a", _rows(SUB, "O1", PREDS_O1, errors={("cvb-0", 4)}))
        _refused(lambda: cta.Leg(s1, [g], "O1"), "--allow-partial", "cvb-0")
        assert cta.Leg(s1, [g], "O1", allow_partial=True).short == ["cvb-0"]


def test_a_key_changed_under_the_same_name_is_refused():
    with tempfile.TemporaryDirectory() as d:
        s1, g1, _, _ = _toy(d)
        assert cta.Leg(s1, [g1], "O1").kn("cvb-0") == (3, 4)
        # the subset regenerated in place with cvb-0's gold moved from A to B:
        # its rows still stamp its name, but their `correct` follows the old key
        recs = _records("O1")
        recs[0]["answer"] = "B"
        with open(s1, "w", encoding="utf-8") as fh:
            json.dump(recs, fh)
        _refused(lambda: cta.Leg(s1, [g1], "O1"), "`correct`", "cvb-0")
        out, msg = _main("--subset", s1, "--blind", g1, "--permutations", "10")
    assert msg and "regenerated" in msg and "######## O1" not in out, msg


def test_rows_of_the_other_order_are_refused():
    with tempfile.TemporaryDirectory() as d:
        s1, _, _, g2 = _toy(d)
        _refused(lambda: cta.Leg(s1, [g2], "O1"), "swapped", SUB2)
        out, msg = _main("--subset", s1, "--blind", g2, "--permutations", "10")
    assert msg and "swapped" in msg and SUB2 in msg, msg
    assert "######## O1" not in out                          # refused before any table


def test_json_directory_and_sighted_glob_are_checked_first():
    with tempfile.TemporaryDirectory() as d:
        s1, g1, s2, g2 = _toy(d)
        blocker = os.path.join(d, "a_file")
        open(blocker, "w").close()
        # a parent that cannot be created, an existing directory, a path that
        # ends in a separator and a file that cannot be written: refused
        # before the (missing) rows are looked for
        ro = os.path.join(d, "ro.json")
        open(ro, "w").close()
        os.chmod(ro, 0o444)
        bad = [os.path.join(blocker, "sub", "out.json"), d, os.path.join(d, "x") + os.sep]
        if not os.access(ro, os.W_OK):                       # root may write it anyway
            bad.append(ro)
        for target in bad:
            out, msg = _main("--blind", os.path.join(d, "no_such_*.jsonl"), "--json", target)
            assert msg and msg.startswith("--json") and "######## O1" not in out, (target, msg)
        assert not os.path.exists(os.path.join(d, "x"))
        out, msg = _main("--subset", s1, "--blind", g1, "--permutations", "10",
                         "--sighted", f"x={os.path.join(d, 'none_*.jsonl')}")
        assert msg and msg.startswith("--sighted") and "######## O1" not in out, msg
        # a parent that does not exist yet is created; the provenance block and
        # both orders' slice summaries are written
        sl = os.path.join(d, "slice.json")
        with open(sl, "w") as fh:
            json.dump([{"id": "cvb-0"}, 2], fh)
        path = os.path.join(d, "new", "dir", "out.json")
        out, msg = _main("--subset", s1, "--blind", g1, "--subset-o2", s2, "--blind-o2", g2,
                         "--slice", f"s={sl}", "--permutations", "20", "--seed", "7", "--json", path)
        assert msg is None, msg
        with open(path) as fh:
            j = json.load(fh)
    p = j["provenance"]
    assert p["seed"] == 7 and p["permutations"] == 20 and p["generator"] == cta.GENERATOR
    assert p["script_git_blob"] == cta.git_blob(cta.__file__) and len(p["script_git_blob"]) == 40
    assert len(p["rows"]["O1"]) == 1 and len(p["rows"]["O1"][0]["sha256"]) == 64
    assert set(p["subsets"]) == {"O1", "O2"} and "s" in p["slices"]
    assert p["argv"][1:3] == ["--subset", os.path.basename(s1)]
    assert j["slices"]["s"]["n_questions"] == 2 and j["slices"]["s"]["O2"]["n_questions"] == 2
    assert j["slices"]["s"]["labels"] == {"text-answerable": 1, "unstable": 1}
    assert j["slices"]["s"]["O2"]["labels"] == {"text-answerable": 2}


def test_a_sighted_glob_over_two_tags_is_refused():
    with tempfile.TemporaryDirectory() as d:
        s1, g1, _, _ = _toy(d)
        for tag in ("_sa", "_sb"):
            _write_rows(d, SUB, tag, [dict(r, method="cvbench_native", backend="Toy-8B")
                                      for r in _rows(SUB, "O1", PREDS_O1)])
        out, msg = _main("--subset", s1, "--blind", g1, "--permutations", "10",
                         "--sighted", f"x={os.path.join(d, f'bench_{SUB}_toy_s*_shard*.jsonl')}")
        assert msg and "2 runs" in msg and "one TAG" in msg and "######## O1" not in out, msg
        # one of them is one leg
        out, msg = _main("--subset", s1, "--blind", g1, "--permutations", "10",
                         "--sighted", f"x={os.path.join(d, f'bench_{SUB}_toy_sa_shard*.jsonl')}")
    assert msg is None and "== sighted x:cvbench_native/Toy-8B" in out, msg


def test_a_negative_seed_and_an_unreadable_slice_are_refused_first():
    with tempfile.TemporaryDirectory() as d:
        s1, g1, _, _ = _toy(d)
        out, msg = _main("--subset", s1, "--blind", g1, "--permutations", "10", "--seed", "-1")
        assert msg == "--seed must be at least 0" and "######## O1" not in out, msg
        torn = os.path.join(d, "torn.json")
        with open(torn, "w") as fh:
            fh.write('["cvb-0", ')
        for spec in (f"s={os.path.join(d, 'missing.json')}", f"s={torn}", "s"):
            out, msg = _main("--subset", s1, "--blind", g1, "--permutations", "10", "--slice", spec)
            assert msg and msg.startswith(f"--slice {spec}: ") and "\n" not in msg, (spec, msg)
            assert "######## O1" not in out


def test_provenance_holds_no_path_outside_the_checkout():
    # inside the checkout: relative to it; anywhere else: the file name alone
    assert cta.path_ref(os.path.join(REPO, "bench", "results", "bench_s_q38bm_shard*.jsonl")) == \
        "bench/results/bench_s_q38bm_shard*.jsonl"
    assert cta.path_ref("/elsewhere/user/bench_s_q38bm_shard0.jsonl") == "bench_s_q38bm_shard0.jsonl"
    with tempfile.TemporaryDirectory() as d:
        s1, g1, s2, g2 = _toy(d)
        sg = _write_rows(d, SUB, "_s", [dict(r, method="cvbench_native", backend="Toy-8B")
                                        for r in _rows(SUB, "O1", PREDS_O1)])
        sl = os.path.join(d, "slice.json")
        with open(sl, "w") as fh:
            json.dump(["cvb-0"], fh)
        # every form argparse takes: '--opt value', '--opt=value', abbreviated
        out, msg = _main("--subset", s1, "--blind", g1, "--subset-=" + s2, "--blind-o2=" + g2,
                         "--si", f"lab={sg}", f"--sl=s={sl}", "--perm", "10",
                         "--js", os.path.join(d, "out.json"))
        assert msg is None, msg
        with open(os.path.join(d, "out.json")) as fh:
            p = json.load(fh)["provenance"]
        ref = {f: {"path": f, "sha256": cta.sha256_of(os.path.join(d, f))} for f in os.listdir(d)}
    r1, r2, rs = (os.path.basename(g.replace("*", "0")) for g in (g1, g2, sg))
    assert p["argv"][1:] == ["--subset", f"{SUB}.json", "--blind", os.path.basename(g1),
                             f"--subset-={SUB2}.json", f"--blind-o2={os.path.basename(g2)}",
                             "--si", f"lab={rs}", "--sl=s=slice.json", "--perm", "10", "--js", "out.json"]
    assert p["subsets"] == {"O1": ref[f"{SUB}.json"], "O2": ref[f"{SUB2}.json"]}
    assert p["rows"] == {"O1": [ref[r1]], "O2": [ref[r2]]}
    assert p["sighted"] == {"lab": [ref[rs]]} and p["slices"] == {"s": ref["slice.json"]}
    assert p["script"]["path"] == "analysis/cvbench_text_answerability.py"
    blob, home = json.dumps(p), os.path.expanduser("~").rstrip(os.sep)
    assert d not in blob and (not home or home not in blob), blob


# -------------------------------------------------------------- rescore ---

def test_rescore_file_label_keeps_cvbench():
    assert ra.file_label("/x/bench_cvbench_full_runnable_subset_o2_cvbench_q38bm_shard13.jsonl") == \
        "cvbench_full_runnable_subset_o2_cvbench_q38bm_shard13"
    assert cta.run_stem("/x/bench_s_cvbench_q38bm_shard13.jsonl") == "bench_s_cvbench_q38bm"
    assert cta.run_stem("/x/bench_s_cvbench_q38bm.jsonl") == "bench_s_cvbench_q38bm"


def test_rescore_prints_one_line_per_tag_and_decode():
    with tempfile.TemporaryDirectory() as d:
        _write_subset(d, SUB, "O1")
        _write_rows(d, SUB, "_a", _rows(SUB, "O1", PREDS_O1))
        _write_rows(d, SUB, "_b", _rows(SUB, "O1", PREDS_O1, decode=dict(DECODE, enable_thinking=False)))
        # one TAG whose two shards were decoded differently
        _write_rows(d, SUB, "_c", _rows(SUB, "O1", {"cvb-0": "AAAA"}), shard=0)
        _write_rows(d, SUB, "_c", _rows(SUB, "O1", {"cvb-1": "BBBB"}, decode=None), shard=1)
        old = ra.RES, ra.RESCORED, ra.HERE
        ra.RES, ra.RESCORED, ra.HERE = d, os.path.join(d, "rescored"), d
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ra.main(["--results", "bench_*.jsonl", "--dry-run"])
        finally:
            ra.RES, ra.RESCORED, ra.HERE = old
        assert not os.path.exists(os.path.join(d, "rescored"))
    out = buf.getvalue()
    legs = [ln.split("  ")[0] for ln in out.splitlines() if ln.startswith(f"{SUB} / blind / Toy-1B")]
    assert sorted(legs)[:2] == [f"{SUB} / blind / Toy-1B / toy_a", f"{SUB} / blind / Toy-1B / toy_b"], out
    assert len(legs) == 4 and sum("/ toy_c / decode" in ln for ln in legs) == 2, out
    assert f"{SUB}_toy_a_shard0 " in out                      # 'cvbench_' intact in the file column


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        # SystemExit is NOT an Exception: a miswired guard would otherwise
        # abort this runner silently
        except (Exception, SystemExit) as e:                  # noqa: BLE001
            fails += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
        else:
            print(f"ok   {name}")
    print("FAILED" if fails else "ALL PASS")
    sys.exit(1 if fails else 0)
