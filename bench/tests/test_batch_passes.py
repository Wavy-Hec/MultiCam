"""--batch-passes / --batch-questions and the answer span: the Qwen3.8
additions that change how rows are produced without changing what a row means.

* QwenBackend._out: under answer_after_think an ENDED trace is parsed from the
  reply after its last </think> (its native thinking quotes "<answer> and
  </answer>"; preflight 144724 scored " and " as an abstention) and its think
  is everything before; a trace cut at max_new_tokens keeps the whole-text
  parse even though it contains quoted </think> tokens; every other checkpoint
  parses the whole text as before.
* turn_length: a batched sample reports the token count a single call would.
* the run_bench loop: a record's pending passes reach ONE answer_n call, up to
  N records with identical pending passes ONE answer_many call, in pass order
  and resume-aware; without the flags, one call per pass as always.
* analysis/rescore_answers.rescore_row honours the row's parsed_from stamp.

Pure CPU — fake processor/backends stand in for the model. Runnable either way:

    pytest bench/tests/test_batch_passes.py
    python  bench/tests/test_batch_passes.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from bench.backends.qwen import QwenBackend, decode_identity, turn_length
from bench.methods.base import GenOut
from bench.methods.blind import BlindMethod
from bench.reuse import parse_choice

THINK = ("We have no videos. The user asks for the final answer between <answer> and "
         "</answer>, reasoning between the <think> and </think> tags. Counting options ... pick C.")
TRACE = THINK + "\n</think>\n\n<answer>C</answer>"
EOS = torch.tensor([248046, 248044])


class _Proc:
    """batch_decode returns a fixed text, whatever the ids."""
    def __init__(self, text):
        self.text = text

    def batch_decode(self, ids, **kw):
        return [self.text]


def _backend(text, model="Qwen/Qwen3.8-27B"):
    """A QwenBackend without a model: _out's decode-dependent logic only."""
    b = QwenBackend.__new__(QwenBackend)
    b.decode = decode_identity(model)
    b.processor = _Proc(text)
    b._eos_ids = EOS
    return b


def _out(b, ended):
    seq = torch.tensor([5, 6, 7, 248046] if ended else [5, 6, 7, 8])
    return b._out(seq, input_tokens=1, video_tokens=0, latency_s=0.0)


def test_ended_trace_parses_the_reply_not_the_quoted_tags():
    whole = GenOut(text=TRACE, input_tokens=1, video_tokens=0, output_tokens=1, latency_s=0.0)
    assert parse_choice(whole.answer_span, False) == ""            # the bug: " and "
    g = _out(_backend(TRACE), ended=True)
    assert g.answer_span.strip() == "<answer>C</answer>" and g.parsed_from == "after_think"
    assert parse_choice(g.answer_span, False) == "C"
    assert g.think_text == THINK.strip() and g.output_tokens == 4


def test_truncated_trace_keeps_the_whole_text_despite_quoted_close_tags():
    cut = THINK + " so the answer is B and then it ran out of tok"
    g = _out(_backend(cut), ended=False)
    assert "</think>" in g.text                                     # the quote
    assert g.answer_text is None and g.parsed_from is None and g.answer_span == cut
    # the historical whole-text rule then applies unchanged: the quoted tag pair
    # is the first <answer> match, so a cut-off trace abstains (no committed
    # answer) — exactly what the parser does for any model
    assert parse_choice(g.answer_span, False) == ""
    plain = "no tags quoted here ... so the answer is B and then it ran out of tok"
    g = _out(_backend(plain), ended=False)
    assert parse_choice(g.answer_span, False) == "B"                # conclusion fallback


def test_other_checkpoints_parse_the_whole_text():
    g = _out(_backend(TRACE, "Qwen/Qwen3-VL-8B-Thinking"), ended=True)
    assert g.answer_text is None and g.think_text is None and g.parsed_from is None


def test_turn_length_matches_a_single_call():
    assert turn_length(torch.tensor([5, 6, 248046, 248044, 248044]), EOS) == (3, True)
    assert turn_length(torch.tensor([5, 6, 7]), EOS) == (3, False)   # hit max_new_tokens
    assert turn_length(torch.tensor([248044, 248044]), EOS) == (1, True)


def test_rescore_honours_parsed_from():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "analysis"))
    from rescore_answers import rescore_row
    rec = {"options": ["A. 0", "B. 1", "C. 2", "D. 4"], "answer": "C"}
    assert rescore_row({"response_text": TRACE, "parsed_from": "after_think"}, rec) == ("C", True, False)
    assert rescore_row({"response_text": TRACE}, rec) == ("", False, True)   # legacy rows: whole text


class _FakeBackend:
    name = "Qwen3.8-27B"

    def __init__(self):
        self.calls = []
        # what a real QwenBackend('Qwen/Qwen3.8-27B') stamps; a resume compares it
        # against backend_decode('qwen38'), so a fake that stamped None would be
        # refused (correctly) on the second run
        self.decode = decode_identity("Qwen/Qwen3.8-27B")

    def _g(self, seed, n=None):
        return GenOut(text=f"<answer>{'A' if seed % 2 else 'B'}</answer>", input_tokens=10,
                      video_tokens=0, output_tokens=3, latency_s=1.0, batch_n=n)

    def generate(self, messages, max_new_tokens, *, seed=None, temperature=0.0):
        self.calls.append(("one", seed))
        return self._g(seed)

    def generate_n(self, messages, max_new_tokens, *, seeds, temperature=0.0):
        self.calls.append(("n", tuple(seeds)))
        return [self._g(s, len(seeds)) for s in seeds]

    def generate_many(self, messages_list, max_new_tokens, *, seeds, temperature=0.0):
        self.calls.append(("many", len(messages_list), tuple(seeds)))
        return [[self._g(s, len(seeds) * len(messages_list)) for s in seeds] for _ in messages_list]


def _run(d, out, fake, *flags, n_rec=3):
    """run_bench.main() with make_backend returning `fake`."""
    import bench.run_bench as rb
    sub = os.path.join(d, "toy_subset.json")
    json.dump([{"id": i, "task_type": "toy", "question": "q?", "answer": "A",
                "options": ["A. x", "B. y"]} for i in range(n_rec)], open(sub, "w"))
    argv = ["run_bench", "--subset", sub, "--methods", "blind", "--backends", "qwen38",
            "--passes", "4", "--seeds", "11,12,13,14", "--temperature", "1.0", "--out", out,
            *flags]
    old_argv, old_make = sys.argv, rb.make_backend
    sys.argv, rb.make_backend = argv, (lambda *a, **k: fake)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rb.main()
    finally:
        sys.argv, rb.make_backend = old_argv, old_make
    return [json.loads(l) for l in open(out)]


def test_batched_loop_one_call_per_record_in_pass_order():
    with tempfile.TemporaryDirectory() as d:
        fake = _FakeBackend()
        rows = _run(d, os.path.join(d, "b.jsonl"), fake, "--batch-passes")
        assert fake.calls == [("n", (11, 12, 13, 14))] * 3, fake.calls
        assert [(r["id"], r["pass_idx"], r["seed"]) for r in rows] == \
            [(i, p, 10 + p) for i in range(3) for p in range(1, 5)]
        assert all(r["batch_n"] == 4 for r in rows)
        assert [r["correct"] for r in rows[:4]] == [True, False, True, False]


def test_question_batches_group_records_with_identical_pending_passes():
    with tempfile.TemporaryDirectory() as d:
        fake = _FakeBackend()
        rows = _run(d, os.path.join(d, "q.jsonl"), fake, "--batch-passes",
                    "--batch-questions", "2", n_rec=5)
        assert fake.calls == [("many", 2, (11, 12, 13, 14))] * 2 + [("n", (11, 12, 13, 14))], fake.calls
        assert [(r["id"], r["pass_idx"], r["seed"]) for r in rows] == \
            [(i, p, 10 + p) for i in range(5) for p in range(1, 5)]
        assert [r["batch_n"] for r in rows] == [8] * 16 + [4] * 4


def test_unbatched_loop_is_one_call_per_pass():
    with tempfile.TemporaryDirectory() as d:
        fake = _FakeBackend()
        rows = _run(d, os.path.join(d, "u.jsonl"), fake)
        assert fake.calls == [("one", s) for _ in range(3) for s in (11, 12, 13, 14)], fake.calls
        assert all(r["batch_n"] is None for r in rows) and len(rows) == 12


def test_batched_resume_batches_only_the_pending_passes():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "r.jsonl")
        rows = _run(d, out, _FakeBackend(), "--batch-passes", "--batch-questions", "4")
        # keep record 0 complete, record 1 with passes 1-2, record 2 with none
        keep = [r for r in rows if r["id"] == 0 or (r["id"] == 1 and r["pass_idx"] <= 2)]
        with open(out, "w") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in keep)
        fake = _FakeBackend()
        rows = _run(d, out, fake, "--batch-passes", "--batch-questions", "4")
        # record 1 (passes 3-4 pending) cannot share a call with record 2 (all four)
        assert fake.calls == [("n", (13, 14)), ("n", (11, 12, 13, 14))], fake.calls
        assert len(rows) == 12
        assert sorted((r["id"], r["pass_idx"]) for r in rows) == \
            [(i, p) for i in range(3) for p in range(1, 5)]


def test_blind_batched_error_rows_carry_every_seed():
    class Boom(_FakeBackend):
        def generate_n(self, *a, **k):
            raise RuntimeError("cuda oom")

        def generate_many(self, *a, **k):
            raise RuntimeError("cuda oom")
    m = BlindMethod(Boom(), temperature=1.0)
    rec = {"id": 7, "task_type": "toy", "question": "q?", "answer": "B", "options": ["A. x", "B. y"]}
    res = m.answer_n(rec, "/nonexistent", seeds=[1, 2, 3])
    assert [r.seed for r in res] == [1, 2, 3]
    assert all(r.error and r.abstained and r.batch_n == 3 for r in res)
    res = m.answer_many([rec, dict(rec, id=8)], "/nonexistent", seeds=[1, 2])
    assert [[r.id for r in rr] for rr in res] == [[7, 7], [8, 8]]
    assert all(r.error and r.batch_n == 4 for rr in res for r in rr)


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
