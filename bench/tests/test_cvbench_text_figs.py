"""analysis/make_cvbench_text_figs.py: what the CVBench text-only figures claim.

* value labels come from integer counts, rounded half-up: a ratio that is
  exactly a tie rounds up wherever its float lands (a float mean of per-pass
  accuracies printed one tenth low; a float tie formatted half-to-even), in
  figures 1, 3, 6, 7, 9 and 10;
* figure 7's labels are its bars' own values, the mean of per-question
  differences, also on a leg where some question has fewer rows;
* figures 8 (letters) and 11 read the legs --bm and --nt name, whatever their
  TAG: the letters from the analysis JSONs' answers, the trace lengths from
  the row files the --bm provenance lists, sha256-checked and deduplicated;
* every input is checked before --out is made: a bad one is refused in one
  line and leaves no directory behind, and so is a leg with partial questions;
* figure 1's longest-option row names the questions it is scored on and marks
  their own chance, and its axis label claims no single population;
* figures 2 and 5 name the with-video arm, and figure 2's title both models;
* figure 4 calls the paired null the model's own answers moved to other
  questions, a conservative baseline, and no figure calls a null luck or
  habits alone; it draws the band under the white mean notch and the
  observed ring over both, so a band end or the notch stays visible, and
  says the band is a central 95% while figure 3's dagger is one-sided;
* figures 3 and 7 say their per-task marks are uncorrected;
* figure 7 names both things the two legs differ in;
* figure 8's Yes/No panel carries its own scale and label;
* figure 10 says the 128-montage inputs pass the native positions with RoPE
  scaling applied, not that they overflow, and not that the scaling is why
  nothing is truncated;
* reference labels and markers keep clear of the data (figures 2, 8 and 10);
* figure 11's bars, and the count above its cut, are in fig_cvbench_data.json;
* figure 12's shades follow a continuous log scale, with a colorbar.

Pure CPU: synthetic analysis JSONs, result rows, archive rows and subset stand
in for the real ones. Runnable either way:

    pytest bench/tests/test_cvbench_text_figs.py
    python  bench/tests/test_cvbench_text_figs.py
"""
import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from statistics import mean

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "analysis"))

import make_cvbench_text_figs as figs                     # noqa: E402
from matplotlib.colors import to_hex                      # noqa: E402
from matplotlib.text import Text                          # noqa: E402

TASKS = ("Joint-video Counting", "Video Difference Caption")
# id: (task, format, options, gold, passes right of 4 for thinking O1 / O2 and
# no thinking O1 / O2, passes right of 4 with video). Two exact ties a float
# formats down: the with-video arms get 18 of 32 rows (56.25%), and Counting's
# thinking-minus-no-thinking difference is +6.25
QS = {"q0": (0, "YN", ["Yes", "No"], "Yes", (4, 3, 2, 4), 4),
      "q1": (0, "ABCD", ["A. red", "B. blue", "C. green", "D. tan"], "B", (4, 4, 1, 0), 0),
      "q2": (0, "AB", ["A. left", "B. right"], "A", (0, 1, 3, 3), 1),
      "q3": (1, "ABCD", ["A. one", "B. two", "C. three", "D. four"], "C", (3, 4, 4, 4), 4),
      "q4": (1, "ABCD", ["A. one, B. two, C. three, D. four"], "D", (0, 0, 0, 1), 0),   # one packed string
      "q5": (1, "YN", ["Yes", "No"], "No", (3, 3, 4, 4), 2),
      "q6": (0, "ABCD", ["A. cat", "B. dog", "C. cow", "D. owl"], "A", (1, 3, 3, 2), 3),
      "q7": (1, "ABCD", ["A. up", "B. down", "C. in", "D. out"], "D", (4, 3, 3, 1), 4)}
LONGEST_N = 5                       # lettered with options one-to-one on letters: not q0, q4, q5
STITCH32 = (495, 496, 495, 496)     # right of 1000 per pass: exactly 49.55%, a float mean of 49.5499...
TOKENS = (150, 199, 200, 750, 2500, 2501, 3000, 820)
INPUT = {"fullstitch8": 2000, "fullstitch": 4000, "fullstitch32": 8000, "fullstitch64": 16000,
         "fullstitch128": 33000}
STEMS = {"O1": "bench_cvbench_full_runnable_subset", "O2": "bench_cvbench_full_runnable_subset_o2"}
FIGURES = (figs.fig_overall, figs.fig_per_task, figs.fig_answerable, figs.fig_vs_null, figs.fig_hist,
           figs.fig_sighted_by_label, figs.fig_delta, figs.fig_letters, figs.fig_history, figs.fig_sweep,
           figs.fig_tokens, figs.fig_order_heat)


def _other(fmt, gold):
    return ("No" if gold == "Yes" else "Yes") if fmt == "YN" else ("B" if gold == "A" else "A")


def _summary(qs, ids, **extra):
    k = sum(qs[q]["k"] for q in ids)
    return {"n_questions": len(ids), "n_rows": 4 * len(ids), "n_correct": k,
            "accuracy": {"mean": round(100 * k / (4 * len(ids)), 2)}, "chance": 34.38,
            "key_floor_insample": 40.0, "key_floor_loo": 30.0, **extra}


def _leg(col):
    """An analysis JSON as cvbench_text_answerability.py writes it, with --blind-o2."""
    j = {}
    for o, c in (("O1", col), ("O2", col + 1)):
        qs = {q: {"task": TASKS[t], "fmt": fmt, "gold": gold, "k": ks[c], "n": 4,
                  "preds": [gold] * ks[c] + [_other(fmt, gold)] * (4 - ks[c]),
                  "label": "text-answerable" if ks[c] >= 3 else "not" if ks[c] == 0 else "unstable"}
              for q, (t, fmt, _, gold, ks, _) in QS.items()}
        j[o] = {"questions": qs,
                "per_task": {t: _summary(qs, [q for q in qs if qs[q]["task"] == t]) for t in TASKS},
                "overall": _summary(qs, list(qs), longest_option={"acc": 35.0, "n": LONGEST_N},
                                    bias_null={"null_mean_correct": 10.37})}
    names = ("not in either order", "text-answerable in one order", "text-answerable in both orders")
    lab = {q: names[sum(j[o]["questions"][q]["label"] == "text-answerable" for o in ("O1", "O2"))] for q in QS}
    per_task = {}
    for t in TASKS:
        ls = [lab[q] for q in QS if TASKS[QS[q][0]] == t]
        per_task[t] = {"n": len(ls), "both": ls.count(names[2]), "one": ls.count(names[1]),
                       "neither": ls.count(names[0]), "expected_both_at_chance": 0.1,
                       "null_mean_both": 0.5, "null_95_both": [0, 2], "p_both": 0.2,
                       "null_mean_both_paired": 1.0, "null_95_both_paired": [0, 2], "p_both_paired": 0.3}
    j["both_orders"] = {"labels": dict(Counter(lab.values())), "per_task": per_task,
                        "bias_null_paired": {"null_mean_text_answerable": 1.5, "null_95_text_answerable": [0, 3],
                                             "p_text_answerable": 0.04}}
    return j


def _rows(c, tokens):
    return [{"id": q, "method": "blind", "backend": "Qwen3.8-27B", "task_type": TASKS[t], "pass_idx": p,
             "gold": gold, "error": None, "prediction": gold if p <= ks[c] else _other(fmt, gold),
             "correct": p <= ks[c], **({"output_tokens": TOKENS[(4 * i + p) % len(TOKENS)]} if tokens else {})}
            for i, (q, (t, fmt, _, gold, ks, _)) in enumerate(QS.items()) for p in range(1, 5)]


def _archive(tag):
    if tag == "fullstitch32":                            # 1000 rows a pass
        return [{"id": f"s{i}", "task_type": TASKS[0], "pass_idx": p, "correct": i < c,
                 "input_tokens": INPUT[tag] + i % 50} for p, c in enumerate(STITCH32, 1) for i in range(1000)]
    return [{"id": q, "task_type": TASKS[t], "pass_idx": p, "correct": p <= vk,
             "input_tokens": INPUT.get(tag, 900) + 10 * p} for q, (t, *_, vk) in QS.items() for p in range(1, 5)]


def _write(path, rows):
    with open(path, "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _inputs(d, tags=("q38bm", "q38nt")):
    """(bm, nt, results dir, archive dir, subset) under d. Each analysis JSON's
    provenance lists O1's row files by file name alone, as the analysis records
    a file read from outside the checkout, so leg_rows looks them up in the
    results dir. O2's are listed by a path with a directory, which leg_rows
    resolves against the repo; they sit outside the results dir, so a lookup by
    file name alone would miss them."""
    res, arc, o2 = os.path.join(d, "results"), os.path.join(d, "archive"), os.path.join(d, "o2rows")
    os.makedirs(res)
    os.makedirs(arc)
    os.makedirs(o2)
    legs = []
    for tag, col in zip(tags, (0, 2), strict=True):
        leg, refs = _leg(col), {}
        for k, (o, stem) in enumerate(STEMS.items()):
            path = os.path.join(o2 if k else res, f"{stem}_cvbench_{tag}_shard0.jsonl")
            _write(path, _rows(col + k, col == 0))
            refs[o] = [{"path": os.path.relpath(path, figs.REPO) if k else os.path.basename(path),
                        "sha256": _sha(path)}]
        leg["provenance"] = {"rows": refs}
        legs.append(leg)
    for tag, _ in figs.ARMS:
        _write(os.path.join(arc, f"bench_cvbench_full_runnable_subset_internvl_{tag}_shard0.jsonl"), _archive(tag))
    subset = [{"id": q, "options": opts, "answer": gold} for q, (_, _, opts, gold, _, _) in QS.items()]
    return legs[0], legs[1], res, arc, subset


def _two_of_two(leg):
    """q3's O2 entry kept on 2 of its 4 rows, both right, as --allow-partial keeps it."""
    q = leg["O2"]["questions"]["q3"]
    q.update(k=2, n=2, preds=q["preds"][:2])
    return leg


_CACHE = {}


def _D():
    if "D" not in _CACHE:
        with tempfile.TemporaryDirectory() as d:
            _CACHE["D"] = figs.assemble(*_inputs(d))
    return _CACHE["D"]


@contextlib.contextmanager
def _figures():
    """The figure functions hand their figure back instead of saving it."""
    saved, made = figs.save, []
    figs.save = lambda fig, out, name: made.append(fig) or fig
    try:
        yield made
    finally:
        figs.save = saved
        for f in made:
            figs.plt.close(f)


def _texts(ax):
    return [t.get_text() for t in ax.texts]


def _main(*argv):
    """The script's main() on argv, its stdout dropped."""
    saved = sys.argv
    sys.argv = ["make_cvbench_text_figs.py", *argv]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            figs.main()
    finally:
        sys.argv = saved


def test_value_labels_round_half_up_from_counts():
    assert f"{mean(100 * c / 1000 for c in STITCH32):.1f}" == "49.5"      # the float mean lands under the tie
    assert figs.half_up(Fraction(100 * sum(STITCH32), 4000)) == Decimal("49.6")
    assert figs.half_up(Fraction(-13, 20)) == Decimal("-0.7")              # ties away from zero
    assert figs.half_up(12.5, 0) == Decimal("13")                          # a JSON float: the decimal it prints as
    D = _D()
    assert D["sighted"]["fullstitch32"]["n_correct"] == sum(STITCH32)
    # 18 of 32 with-video rows and a difference of +6.25: exact ties, formatted half-to-even as floats
    video, counting = D["sighted"]["fulldur"], D["tasks"]["Joint-video Counting"]["delta"]
    assert (video["n_correct"], video["rows"]) == (18, 32) and f"{video['acc']:.1f}" == "56.2"
    assert f"{counting:+.1f}" == "+6.2"
    both = dict(D["sighted_by_label"]["both"], n=8, acc=56.25, n_correct=18, rows=32)
    with _figures():
        texts = _texts(figs.fig_history(D, None).axes[0])
        assert "49.6%" in texts and "49.5%" not in texts
        # 5 of the 8 questions in both orders is 62.5%: formatting the float would print 62
        assert "63%" in _texts(figs.fig_answerable(D, None).axes[0])
        assert "56.3%" in _texts(figs.fig_overall(D, None).axes[0])
        sweep = _texts(figs.fig_sweep(D, None).axes[0])
        assert "sequential video, 64 frames (best arm)  56.3" in sweep
        assert "+6.3" in _texts(figs.fig_delta(D, None).axes[0])
        by_label = dict(D, sighted_by_label=dict(D["sighted_by_label"], both=both))
        assert "56.3%\n(n=8)" in _texts(figs.fig_sighted_by_label(by_label, None).axes[0])


def test_delta_labels_are_the_bars_own_values_on_a_partial_leg():
    with tempfile.TemporaryDirectory() as d:
        bm, nt, res, arc, subset = _inputs(d)
        D = figs.assemble(bm, _two_of_two(nt), res, arc, subset)

    def kn(j, q):
        return [sum(j[o]["questions"][q][x] for o in ("O1", "O2")) for x in ("k", "n")]
    want = {}
    for t in TASKS:
        want[figs.SHORT[t]] = 100 * mean(Fraction(*kn(bm, q)) - Fraction(*kn(nt, q))
                                         for q in QS if TASKS[QS[q][0]] == t)
        assert abs(D["tasks"][t]["delta"] - float(want[figs.SHORT[t]])) < 1e-9       # the bar
    want["All 1000 questions"] = 100 * mean(Fraction(*kn(bm, q)) - Fraction(*kn(nt, q)) for q in QS)
    with _figures():
        ax = figs.fig_delta(D, None).axes[0]
        rows = [t.get_text() for t in ax.get_yticklabels()]
        got = {rows[round(t.get_position()[1])]: t.get_text() for t in ax.texts if t.get_text()[:1] in ("+", "-")}
    assert got == {row: f"{figs.half_up(x):+}" for row, x in want.items()}
    # the legs' pooled counts would label this bar of -3.125 as -0.8
    assert got["Video Difference Caption"] == "-3.1"


def test_letters_and_tokens_come_from_the_legs_given():
    with tempfile.TemporaryDirectory() as d:
        bm, nt, res, arc, subset = _inputs(d, tags=("x2bm", "x2nt"))      # a rerun under a new TAG
        for stem in STEMS.values():                      # stale legs under the shipped TAGs: never read
            for tag in ("q38bm", "q38nt"):
                _write(os.path.join(res, f"{stem}_cvbench_{tag}_shard0.jsonl"),
                       [dict(r, prediction="A", output_tokens=99999) for r in _rows(0, True)])
        ref = bm["provenance"]["rows"]["O1"][0]
        first = os.path.join(res, ref["path"])
        with open(first) as fh:
            rows = [json.loads(line) for line in fh]
        _write(first, rows + [dict(rows[0], output_tokens=77777)])        # a duplicate row: dropped
        ref["sha256"] = _sha(first)
        D = figs.assemble(bm, nt, res, arc, subset)
        for broken, said in (({"sha256": "0" * 64}, "sha256 differs"), ({"path": "gone.jsonl"}, "missing")):
            leg = copy.deepcopy(bm)
            leg["provenance"]["rows"]["O1"][0].update(broken)
            try:
                figs.assemble(leg, nt, res, arc, subset)
            except SystemExit as e:
                assert said in str(e), str(e)
            else:
                raise AssertionError(f"a row file with {broken} was read")
    for order in ("O1", "O2"):
        lettered = [m for m in bm[order]["questions"].values() if m["gold"] in tuple("ABCD")]
        assert D["letters"]["n"] == len(lettered) == 6
        for key, j in (("bm", bm), ("nt", nt)):
            c = Counter(p for m in j[order]["questions"].values() if m["gold"] in tuple("ABCD") for p in m["preds"])
            assert D["letters"][order][key] == {x: 100 * c[x] / sum(c[y] for y in "ABCD") for x in "ABCD"}
    assert sorted(D["tokens"]["bm"]) == sorted(r["output_tokens"] for c in (0, 1) for r in _rows(c, True))


def test_bad_inputs_are_refused_in_one_line_before_out_is_made():
    with tempfile.TemporaryDirectory() as d:
        bm, nt, res, arc, subset = _inputs(d)
        stale = copy.deepcopy(bm)
        stale["provenance"]["rows"]["O1"][0]["sha256"] = "0" * 64
        objs = {"bm": bm, "nt": nt, "subset": subset, "partial": _two_of_two(copy.deepcopy(nt)), "stale": stale,
                "one_order": {k: v for k, v in bm.items() if k not in ("O2", "both_orders")},
                "no_provenance": {k: v for k, v in bm.items() if k != "provenance"}}
        p = {name: os.path.join(d, name + ".json") for name in objs}
        for name, obj in objs.items():
            with open(p[name], "w") as fh:
                json.dump(obj, fh)
        os.makedirs(os.path.join(d, "empty"))
        good = {"--bm": p["bm"], "--nt": p["nt"], "--subset": p["subset"], "--results": res, "--archive": arc}
        out = os.path.join(d, "figs")
        for flag, value, said in (("--subset", p["bm"], "not a list of question records"),
                                  ("--bm", p["subset"], "not an analysis JSON"),
                                  ("--bm", os.path.join(d, "absent.json"), "No such file"),
                                  ("--nt", p["one_order"], "without --blind-o2"),
                                  ("--nt", p["partial"], "without 4 usable passes"),
                                  ("--bm", p["no_provenance"], "provenance lists no O1 and O2 row files"),
                                  ("--bm", p["stale"], "sha256 differs"),
                                  ("--archive", os.path.join(d, "empty"), "holds no rows")):
            argv = dict(good, **{flag: value, "--out": out})
            try:
                _main(*[x for kv in argv.items() for x in kv])
            except SystemExit as e:
                assert said in str(e) and "\n" not in str(e), (flag, str(e))
            else:
                raise AssertionError(f"{flag} {value} was accepted")
            assert not os.path.exists(out), f"{flag}: --out made before the refusal"


def test_longest_option_row_has_its_own_population_and_chance():
    D = _D()
    assert D["longest_n"] == LONGEST_N and D["choices"]["longest_option"] == {"2": 1, "4": 4}
    with _figures():
        ax = figs.fig_overall(D, None).axes[0]
        assert (f"Pick the longest option ({LONGEST_N} lettered questions only)"
                in [t.get_text() for t in ax.get_yticklabels()])
        # one two-option and four four-option questions: 30%, marked on its own bar (row 4)
        assert [c for c in ax.collections if c.get_offsets().tolist() == [[30.0, 4.0]]]
        assert any(f"chance on these {LONGEST_N} questions, 30.0%" in t for t in _texts(ax))
        assert "34.4%" in _texts(ax)                     # the chance bar: all 8 questions
        assert not ax.get_xlabel().startswith("accuracy on the 1000")


def test_subset_must_be_the_one_the_analysis_ran_on():
    with tempfile.TemporaryDirectory() as d:
        bm, nt, res, arc, subset = _inputs(d)
        subset[4]["options"] = ["A. one", "B. two", "C. three", "D. four"]   # q4 no longer packed
        try:
            figs.assemble(bm, nt, res, arc, subset)
        except SystemExit as e:
            assert "longest-option" in str(e)
        else:
            raise AssertionError("a subset with other option counts was accepted")


def test_with_video_series_names_its_arm_and_the_other_model():
    D = _D()
    with _figures():
        per_task, hist = figs.fig_per_task(D, None), figs.fig_hist(D, None)
        for fig in (per_task, hist):
            labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
            assert any("InternVL3-8B" in s and "sequential, duration-weighted" in s for s in labels), labels
        title = per_task.axes[0].get_title(loc="left")
        assert "Qwen3.8-27B" in title and "InternVL3-8B" in title


def test_the_paired_null_is_a_conservative_baseline_never_habits_alone():
    D = _D()
    with _figures() as made:
        title = figs.fig_vs_null(D, None).axes[0].get_title(loc="left").replace("\n", " ")
        assert "the model's own answers moved to other questions" in title and "conservative baseline" in title
        for f in FIGURES:
            f(D, None)
        words = " ".join(t.get_text() for fig in made for t in fig.findobj(Text)).replace("\n", " ").lower()
    assert "luck" not in words and "habits alone" not in words


def test_null_band_ends_and_mean_notch_stay_visible():
    D = _D()
    with _figures():
        ax = figs.fig_vs_null(D, None).axes[0]
        bands = [ln for ln in ax.lines if ln.get_linewidth() > 3]
        assert len(bands) == len(TASKS) and all(ln.get_solid_capstyle() == "butt" for ln in bands)
        faces = {c: [to_hex(f) for f in c.get_facecolors()] for c in ax.collections}
        notches = [c for c, f in faces.items() if f == [figs.SURF]]        # the white mean notch
        rings = [c for c, f in faces.items() if not f]                      # the observed value: no face
        assert len(notches) == len(rings) == len(TASKS)
        assert all(to_hex(c.get_edgecolors()[0]) == figs.BLUE for c in rings)
        # the band under the notch and the ring over both: a band end or the notch shows inside a ring
        assert (max(ln.get_zorder() for ln in bands) < min(c.get_zorder() for c in notches)
                <= min(c.get_zorder() for c in rings))
        note = ax.get_xlabel().replace("\n", " ")
        assert "central 95%" in note and "one-sided" in note


def test_per_task_significance_marks_say_uncorrected():
    D = _D()
    with _figures():
        assert "(p >= 0.05, uncorrected)" in figs.fig_answerable(D, None).axes[0].get_xlabel()
        assert "interval includes 0 (uncorrected)" in figs.fig_delta(D, None).axes[0].get_xlabel()


def test_delta_figure_names_both_bundles():
    D = _D()
    with _figures():
        ax = figs.fig_delta(D, None).axes[0]
        words = " ".join([ax.get_title(loc="left"), ax.get_xlabel()] + _texts(ax)).replace("\n", " ")
        assert "thinking on, effort medium, with the reasoning prompt" in words
        assert "thinking off with the direct-answer prompt" in words
        assert "change from thinking" not in words


def test_yes_no_panel_has_its_own_scale_label():
    D = _D()
    with _figures():
        fig = figs.fig_letters(D, None)
        letters, yesno = fig.axes[0], fig.axes[2]
        assert yesno.get_ylabel() == f"share 'Yes' on the {D['yesno']['n']} Yes/No questions (%)"
        assert [t.get_text() for t in yesno.get_yticklabels()]          # its scale is labelled
        assert "lettered" in letters.get_ylabel()


def test_sweep_annotation_states_rope_scaling_not_overflow():
    D = _D()
    with _figures():
        note = " ".join(t for t in _texts(figs.fig_sweep(D, None).axes[0]) if "128 montages" in t)
        note = note.replace("\n", " ")
        assert "RoPE scaling" in note and "nothing is truncated" in note
        assert "so nothing" not in note                  # nothing truncates either way: no cause to name
        assert "max_position_embeddings" not in note
        lo, hi = D["stitch_input_tokens"]["fullstitch64"]
        assert f"64 montages: {lo:,}-{hi:,}" in note


def test_reference_labels_and_markers_keep_clear_of_the_data():
    D = _D()
    with _figures():
        yesno = figs.fig_letters(D, None).axes[2]
        fifty = [t for t in yesno.texts if t.get_text() == "50%"]
        assert len(fifty) == 1 and fifty[0].get_position()[0] > yesno.get_xlim()[1]    # past the O2 bars
        ax = figs.fig_per_task(D, None).axes[0]
        face = {c: to_hex(c.get_facecolors()[0]) for c in ax.collections}
        dots = [c for c, f in face.items() if f in (figs.BLUE, figs.ORANGE, figs.AQUA)]
        keys = [c for c, f in face.items() if f == figs.SURF]             # the hollow answer-key diamonds
        assert keys and max(c.get_zorder() for c in keys) < min(c.get_zorder() for c in dots)
        sweep = figs.fig_sweep(D, None).axes[0]
        chance = [t for t in sweep.texts if t.get_text().startswith("chance")]
        assert chance[0].get_position()[1] < D["chance"] and chance[0].get_verticalalignment() == "top"
        assert "figure 4" not in figs.fig_answerable(D, None).axes[0].get_xlabel()


def test_token_histogram_is_in_the_figure_data():
    with tempfile.TemporaryDirectory() as d:
        bm, nt, res, arc, subset = _inputs(d)
        paths = {}
        for name, obj in (("bm", bm), ("nt", nt), ("subset", subset)):
            paths[name] = os.path.join(d, name + ".json")
            with open(paths[name], "w") as fh:
                json.dump(obj, fh)
        out = os.path.join(d, "figs")
        _main("--bm", paths["bm"], "--nt", paths["nt"], "--results", res, "--archive", arc,
              "--subset", paths["subset"], "--out", out)
        assert len([f for f in os.listdir(out) if f.endswith(".png")]) == 12
        with open(os.path.join(out, "fig_cvbench_data.json")) as fh:
            data = json.load(fh)
    H = data["tokens_hist"]
    assert H["bin_edges"] == list(range(0, 2501, 100))
    # 150 and 199 share [100, 200), 200 opens the next bin, 2500 closes the last, 2501 and 3000 lie above
    assert (H["counts"][1], H["counts"][2], H["counts"][24], H["above_cut"]) == (16, 8, 8, 16)
    assert sum(H["counts"]) + H["above_cut"] == data["tokens"]["bm_n"] == 64
    with _figures():
        bars = figs.fig_tokens(_D(), None).axes[0].patches
        assert [p.get_height() for p in bars] == H["counts"]          # the drawn bars are the stored table


def test_order_heat_shades_follow_a_continuous_log_scale():
    D = dict(_D(), order_matrix=[[300, 12, 23, 40, 60], [11, 14, 16, 18, 20], [25, 30, 35, 45, 50],
                                 [10, 13, 21, 70, 90], [55, 65, 75, 85, 300]])
    with _figures():
        fig = figs.fig_order_heat(D, None)
        assert len(fig.axes) == 2                         # the heat map and its colorbar
        shade = {}
        for p in fig.axes[0].patches:
            x, y = p.get_xy()
            shade[D["order_matrix"][round(y + 0.47)][round(x + 0.47)]] = sum(p.get_facecolor()[:3])
        ramp = [shade[v] for v in sorted(shade)]
        assert all(a > b for a, b in zip(ramp, ramp[1:])), ramp   # every larger count is darker


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
