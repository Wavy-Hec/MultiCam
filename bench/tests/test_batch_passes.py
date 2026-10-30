"""--batch-passes / --batch-questions and the answer span: the Qwen3.8
additions that change how rows are produced without changing what a row means.

* QwenBackend._out: under answer_after_think an ENDED trace is parsed from the
  reply after its last </think> (its native thinking quotes "<answer> and
  </answer>"; a preflight run scored " and " as an abstention) and its think
  is everything before; a trace cut at max_new_tokens keeps the whole-text
  parse even though it contains quoted </think> tokens, and its think is the
  whole trace; every other checkpoint parses the whole text as before.
* turn_length: a batched sample reports the token count a single call would.
* QwenBackend.generate_many: one generate call per batch, rows mapped back to
  their prompt, seeded with a stable hash of the call's prompts and pass
  labels (call_seed) that every row stamps with its slot; greedy or
  single-sequence calls keep the unbatched per-pass seeding.
* BlindMethod: a call that runs out of GPU memory is retried in halves, the
  questions first, then the passes; any other failure is an error row per
  member. An error row stamps batch_n only for a call of two or more
  sequences, as a success row does (sampled calls; at T=0 the passes run as
  separate generate calls, and an error row still stamps batch_n=n).
* the run_bench loop: a record's pending passes reach ONE answer_n call, up to
  N records with identical pending passes ONE answer_many call, in pass order
  and resume-aware; without the flags, or without a batched path, one call per
  pass as always; a failed call writes error rows and the leg goes on;
  --batch-questions is refused without --batch-passes.
* metrics.summarize splits a batched call's wall clock over its rows, and
  counts a row as batched only when it stamps batch_n > 1.
* analysis/rescore_answers.rescore_row honours the row's parsed_from stamp.

Pure CPU — fake processor/model/backends stand in for the model. Runnable either way:

    pytest bench/tests/test_batch_passes.py
    python  bench/tests/test_batch_passes.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile

import pytest
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from bench import metrics
from bench.backends.qwen import QwenBackend, call_seed, decode_identity, turn_length
from bench.methods.base import GenOut, think_of
from bench.methods.blind import BlindMethod
from bench.reuse import parse_choice

THINK = ("We have no videos. The user asks for the final answer between <answer> and "
         "</answer>, reasoning between the <think> and </think> tags. Counting options ... pick C.")
TRACE = THINK + "\n</think>\n\n<answer>C</answer>"
EOS = torch.tensor([248046, 248044])
KNOBS = ("QWEN_ENABLE_THINKING", "QWEN_REASONING_EFFORT")
REC = {"id": 7, "task_type": "toy", "question": "q?", "answer": "B", "options": ["A. x", "B. y"]}


@contextlib.contextmanager
def _knobs(**env):
    """The Qwen template knobs set to exactly `env` (none by default), so a
    QWEN_* exported in the calling shell cannot change what a test sees."""
    with pytest.MonkeyPatch.context() as mp:
        for k in KNOBS:
            mp.delenv(k, raising=False)
        for k, v in env.items():
            mp.setenv(k, v)
        yield


class _Proc:
    """batch_decode returns a fixed text, whatever the ids."""
    def __init__(self, text):
        self.text = text

    def batch_decode(self, ids, **kw):
        return [self.text]


def _backend(text, model="Qwen/Qwen3.8-27B", **env):
    """A QwenBackend without a model: _out's decode-dependent logic only."""
    b = QwenBackend.__new__(QwenBackend)
    with _knobs(**env):
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


def test_an_unsplit_thinking_trace_stores_its_reasoning():
    """The template opened the <think> block, so a trace it never closed is
    reasoning throughout. extract_think's first <think>...</think> match on it
    is the QUOTE of the prompt's tags, which stored the word 'and'. Only the
    stored think changes: the answer is still parsed from the whole text."""
    cut = THINK + " so the answer is B and then it ran out of tok"
    g = _out(_backend(cut), ended=False)
    assert think_of(g) == cut.strip()
    assert g.answer_text is None and g.parsed_from is None and g.answer_span == cut
    g = _out(_backend("it stopped without closing anything"), ended=True)
    assert think_of(g) == "it stopped without closing anything" and g.parsed_from is None
    # thinking off: the template closed the block itself; nothing is reasoning
    g = _out(_backend("<answer>B</answer>", QWEN_ENABLE_THINKING="0"), ended=True)
    assert g.think_text is None and think_of(g) == "" and g.parsed_from is None


def test_other_checkpoints_parse_the_whole_text():
    # whatever QWEN_* the calling shell exports: they are refused on this checkpoint
    with _knobs(QWEN_ENABLE_THINKING="0", QWEN_REASONING_EFFORT="medium"):
        g = _out(_backend(TRACE, "Qwen/Qwen3-VL-8B-Thinking"), ended=True)
    assert g.answer_text is None and g.think_text is None and g.parsed_from is None
    g = _out(_backend(THINK, "Qwen/Qwen3-VL-8B-Thinking"), ended=False)
    assert g.answer_text is None and g.think_text is None


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


# --- QwenBackend.generate_many on a stand-in model -------------------------------
END, PAD = 248046, 248044          # Qwen3.8's end-of-turn id and its pad (also an eos id)


class _Enc(dict):
    """BatchFeature-like: keys and attributes, .to() a no-op."""
    def __init__(self, ids, mask):
        super().__init__(input_ids=ids, attention_mask=mask)
        self.input_ids, self.attention_mask = ids, mask

    def to(self, device):
        return self


class _Tok:
    padding_side = "right"


class _GenProc:
    """One token per prompt character; the chat template renders the prompt's
    text itself, so call_seed hashes exactly that."""
    def __init__(self):
        self.tokenizer = _Tok()
        self.sides = []

    def apply_chat_template(self, messages, **kw):
        return "".join(item["text"] for m in messages for item in m["content"]
                       if item.get("type") == "text")

    def __call__(self, text, padding=True, return_tensors="pt", **kw):
        self.sides.append(self.tokenizer.padding_side)
        seqs = [[20 + (ord(c) % 7) for c in t] for t in text]
        width = max(map(len, seqs))
        ids, mask = [], []
        for s in seqs:
            pad = [0] * (width - len(s))
            if self.tokenizer.padding_side == "left":
                ids.append(pad + s)
                mask.append([0] * len(pad) + [1] * len(s))
            else:
                ids.append(s + pad)
                mask.append([1] * len(s) + [0] * len(pad))
        return _Enc(torch.tensor(ids), torch.tensor(mask))

    def batch_decode(self, ids, skip_special_tokens=True, clean_up_tokenization_spaces=False):
        return [" ".join(str(i) for i in row if not (skip_special_tokens and i in (END, PAD)))
                for row in ids.tolist()]


class _Model:
    """HF-like generate: prompt i expands to rows i*n .. i*n+n-1; a row's first
    token names its (prompt, sample); row 1 never ends (runs to the cap). Records
    the seed each call ran under (torch.initial_seed after manual_seed)."""
    device = torch.device("cpu")

    def __init__(self):
        self.calls = []

    def generate(self, input_ids, attention_mask, num_return_sequences=1, **kw):
        n = num_return_sequences
        self.calls.append(dict(kw, n=n, shape=tuple(input_ids.shape), seed=torch.initial_seed()))
        rows = [[(r // n) * 100 + r % n, 11, 12, 13, 14] if r == 1 else
                [(r // n) * 100 + r % n, 11, END, PAD, PAD] for r in range(input_ids.shape[0] * n)]
        return torch.cat([input_ids.repeat_interleave(n, dim=0), torch.tensor(rows)], dim=1)


def _gen_backend(model_id="Qwen/Qwen3.8-27B"):
    b = QwenBackend.__new__(QwenBackend)
    b.model_path, b.name = model_id, model_id.split("/")[-1]
    with _knobs():
        b.decode = decode_identity(model_id)
    b._template_kwargs = {}
    b.model, b.processor = _Model(), _GenProc()
    b._eos_ids = torch.tensor([END, PAD])
    b._pvi = lambda messages, **kw: (None, None, {})
    b._vid_id, b._img_id, b.patch_size = 7, 8, 16
    return b


def _m(text):
    return [{"role": "user", "content": [{"type": "text", "text": text}]}]


def test_one_prompt_n_passes_is_one_call_with_the_preset_sampling():
    b = _gen_backend()
    out = b.generate_n(_m("abcd"), 64, seeds=[11, 12, 13, 14], temperature=0.6)
    assert len(b.model.calls) == 1
    c = b.model.calls[0]
    assert (c["n"], c["do_sample"], c["temperature"], c["top_p"], c["top_k"]) == (4, True, 0.6, 0.95, 20)
    assert c["seed"] == call_seed([11, 12, 13, 14], ["abcd"])
    assert [(g.batch_n, g.call_seed, g.batch_slot) for g in out] == [(4, c["seed"], j) for j in range(4)]
    assert [g.input_tokens for g in out] == [4] * 4
    assert [g.text.split()[0] for g in out] == ["0", "1", "2", "3"]
    assert out[0].output_tokens == 3                         # through its first end-of-turn token
    assert out[1].output_tokens == 5 and out[1].text == "1 11 12 13 14"   # never ended: counted whole


def test_several_prompts_are_left_padded_and_rows_map_back_to_their_prompt():
    b = _gen_backend()
    out = b.generate_many([_m("abcd"), _m("abcdefg")], 64, seeds=[1, 2, 3], temperature=0.6)
    c = b.model.calls[0]
    assert len(b.model.calls) == 1 and c["n"] == 3 and c["shape"] == (2, 7)
    assert b.processor.sides == ["left"] and b.processor.tokenizer.padding_side == "right"  # restored
    assert [[g.input_tokens for g in row] for row in out] == [[4] * 3, [7] * 3]  # unpadded lengths
    assert [[g.text.split()[0] for g in row] for row in out] == [["0", "1", "2"], ["100", "101", "102"]]
    assert [[(g.batch_n, g.batch_slot) for g in row] for row in out] == \
        [[(6, 0), (6, 1), (6, 2)], [(6, 3), (6, 4), (6, 5)]]


def test_a_batched_call_is_seeded_by_a_hash_of_its_prompts_and_passes():
    """Every call once restarted from seeds[0], so batch slot s replayed one
    noise stream across all calls of a leg, whatever the question. The call
    seed now follows the call's content: the same call reproduces its stream,
    other questions, another option order or other passes draw another."""
    b = _gen_backend()
    o1, o2 = _m("Which one? A. red B. blue"), _m("Which one? A. blue B. red")   # O1 / O2
    o3 = _m("How many? A. 1 B. 2")
    out = b.generate_many([o1, o3], 64, seeds=[1, 2, 3, 4], temperature=0.6)
    b.generate_many([o1, o3], 64, seeds=[1, 2, 3, 4], temperature=0.6)     # the same call again
    b.generate_many([o2, o3], 64, seeds=[1, 2, 3, 4], temperature=0.6)     # the other option order
    b.generate_many([o3, o1], 64, seeds=[1, 2, 3, 4], temperature=0.6)     # the questions swapped
    b.generate_n(o1, 64, seeds=[1, 2, 3, 4], temperature=0.6)              # one of them alone
    b.generate_many([o1, o3], 64, seeds=[3, 4], temperature=0.6)           # other pending passes
    seeds = [c["seed"] for c in b.model.calls]
    assert seeds[0] == seeds[1] == call_seed([1, 2, 3, 4], [b._prompt(o1), b._prompt(o3)])
    assert len(set(seeds[1:])) == 5, seeds
    assert all(0 <= s < 2 ** 31 for s in seeds)
    # every row stamps its call's seed and its slot i * n + j
    assert [[(g.call_seed, g.batch_slot) for g in row] for row in out] == \
        [[(seeds[0], i * 4 + j) for j in range(4)] for i in range(2)]


def test_call_seed_is_the_same_in_every_process():
    # sha256, not hash() (randomized per process): a fixed value for fixed
    # inputs. Changing it changes every batched stream: bump CALL_SEED_SCHEME.
    assert call_seed([1, 2, 3, 4], ["Which one? A. red B. blue"]) == 331277807
    assert call_seed([1, 2, 3, 4], ["Which one? A. blue B. red"]) == 972595114


def test_greedy_and_single_sequence_calls_keep_the_unbatched_seeding():
    b = _gen_backend()
    out = b.generate_many([_m("abcd")], 64, seeds=[1, 2], temperature=0.0)
    assert [c["do_sample"] for c in b.model.calls] == [False, False]
    assert all(g.batch_n is None and g.call_seed is None and g.batch_slot is None for g in out[0])
    b = _gen_backend()
    out = b.generate_many([_m("abcd")], 64, seeds=[5], temperature=0.6)
    c = b.model.calls[0]
    assert (c["n"], c["seed"]) == (1, 5)                       # seeded with its own pass seed
    assert out[0][0].batch_n is None and out[0][0].call_seed is None


def test_legacy_checkpoint_sampling_is_unchanged():
    b = _gen_backend("Qwen/Qwen3-VL-8B-Thinking")
    assert b._sampling(8192, 0.7) == (True, dict(max_new_tokens=8192, do_sample=True,
                                                 temperature=0.7, top_p=0.9))
    assert b._sampling(8192, 0.0) == (False, dict(max_new_tokens=8192, do_sample=False))
    b = _gen_backend()
    assert b._sampling(8192, 0.6) == (True, dict(max_new_tokens=8192, do_sample=True,
                                                 temperature=0.6, top_p=0.95, top_k=20))


def test_several_visual_prompts_are_refused():
    b = _gen_backend()
    vis = [{"role": "user", "content": [{"type": "video", "video": "x.mp4"},
                                        {"type": "text", "text": "q"}]}]
    with pytest.raises(ValueError, match="text-only"):
        b.generate_many([_m("abcd"), vis], 64, seeds=[1, 2], temperature=0.6)
    assert not b.model.calls


# --- the run_bench loop and BlindMethod, on fake backends ------------------------
class _FakeBackend:
    name = "Qwen3.8-27B"

    def __init__(self):
        self.calls = []
        # what a real QwenBackend('Qwen/Qwen3.8-27B') stamps; a resume compares it
        # against backend_decode('qwen38'), so a fake that stamped None would be
        # refused (correctly) on the second run
        with _knobs():
            self.decode = decode_identity("Qwen/Qwen3.8-27B")

    def _g(self, seed, n=None, call=None, slot=None):
        return GenOut(text=f"<answer>{'A' if seed % 2 else 'B'}</answer>", input_tokens=10,
                      video_tokens=0, output_tokens=3, latency_s=1.0, batch_n=n,
                      call_seed=call, batch_slot=slot)

    def generate(self, messages, max_new_tokens, *, seed=None, temperature=0.0):
        self.calls.append(("one", seed))
        return self._g(seed)

    def generate_n(self, messages, max_new_tokens, *, seeds, temperature=0.0):
        self.calls.append(("n", tuple(seeds)))
        return [self._g(s, len(seeds), 1000 + seeds[0], j) for j, s in enumerate(seeds)]

    def generate_many(self, messages_list, max_new_tokens, *, seeds, temperature=0.0):
        self.calls.append(("many", len(messages_list), tuple(seeds)))
        n = len(seeds)
        return [[self._g(s, n * len(messages_list), 2000 + len(messages_list), i * n + j)
                 for j, s in enumerate(seeds)] for i in range(len(messages_list))]


class _OomBackend(_FakeBackend):
    """Runs out of GPU memory on any call of more than `limit` sequences."""
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def generate_n(self, messages, max_new_tokens, *, seeds, temperature=0.0):
        if len(seeds) > self.limit:
            self.calls.append(("oom", 1, len(seeds)))
            raise torch.cuda.OutOfMemoryError("CUDA out of memory (fake)")
        return super().generate_n(messages, max_new_tokens, seeds=seeds, temperature=temperature)

    def generate_many(self, messages_list, max_new_tokens, *, seeds, temperature=0.0):
        if len(messages_list) * len(seeds) > self.limit:
            self.calls.append(("oom", len(messages_list), len(seeds)))
            raise torch.cuda.OutOfMemoryError("CUDA out of memory (fake)")
        return super().generate_many(messages_list, max_new_tokens, seeds=seeds,
                                     temperature=temperature)


def _main(d, out, fake, *flags, n_rec=3, env=None, log=None):
    """run_bench.main() with make_backend returning `fake` and the Qwen template
    knobs set to exactly `env`; its stdout is appended to `log` when given."""
    import bench.run_bench as rb
    sub = os.path.join(d, "toy_subset.json")
    json.dump([{"id": i, "task_type": "toy", "question": "q?", "answer": "A",
                "options": ["A. x", "B. y"]} for i in range(n_rec)], open(sub, "w"))
    argv = ["run_bench", "--subset", sub, "--methods", "blind", "--backends", "qwen38",
            "--passes", "4", "--seeds", "11,12,13,14", "--temperature", "1.0", "--out", out,
            *flags]
    old_argv, old_make = sys.argv, rb.make_backend
    sys.argv, rb.make_backend = argv, (lambda *a, **k: fake)
    buf = io.StringIO()
    try:
        with _knobs(**(env or {})), contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(io.StringIO()):
            rb.main()
    finally:
        sys.argv, rb.make_backend = old_argv, old_make
        if log is not None:
            log.append(buf.getvalue())


def _run(d, out, fake, *flags, **kw):
    """_main, then every row of `out`."""
    _main(d, out, fake, *flags, **kw)
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
        # each row carries its call's seed and its own slot in that call
        assert [(r["call_seed"], r["batch_slot"]) for r in rows] == \
            [(2002, s) for s in range(8)] * 2 + [(1011, s) for s in range(4)]


def test_unbatched_loop_is_one_call_per_pass():
    with tempfile.TemporaryDirectory() as d:
        fake = _FakeBackend()
        rows = _run(d, os.path.join(d, "u.jsonl"), fake)
        assert fake.calls == [("one", s) for _ in range(3) for s in (11, 12, 13, 14)], fake.calls
        assert len(rows) == 12
        assert all(r["batch_n"] is None and r["call_seed"] is None and r["batch_slot"] is None
                   for r in rows)


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
            raise RuntimeError("device-side assert")

        def generate_many(self, *a, **k):
            raise RuntimeError("device-side assert")
    m = BlindMethod(Boom(), temperature=1.0)
    res = m.answer_n(REC, "/nonexistent", seeds=[1, 2, 3])
    assert [r.seed for r in res] == [1, 2, 3]
    assert all(r.error and r.abstained and r.batch_n == 3 for r in res)
    res = m.answer_many([REC, dict(REC, id=8)], "/nonexistent", seeds=[1, 2])
    assert [[r.id for r in rr] for rr in res] == [[7, 7], [8, 8]]
    assert all(r.error and r.batch_n == 4 for rr in res for r in rr)
    # a call of one sequence is a plain generate call: no batch_n, as on success
    res = m.answer_n(REC, "/nonexistent", seeds=[5])
    assert [(r.seed, r.batch_n) for r in res] == [(5, None)] and res[0].error


def test_out_of_memory_is_retried_in_halves_questions_first():
    recs = [dict(REC, id=i) for i in range(4)]
    b = _OomBackend(limit=8)
    res = BlindMethod(b, temperature=1.0).answer_many(recs, "/x", seeds=[1, 2, 3, 4])
    assert b.calls == [("oom", 4, 4), ("many", 2, (1, 2, 3, 4)), ("many", 2, (1, 2, 3, 4))], b.calls
    assert [[(r.id, r.seed, r.error) for r in rr] for rr in res] == \
        [[(i, s, None) for s in (1, 2, 3, 4)] for i in range(4)]
    # one question still too big: then its passes are halved
    b = _OomBackend(limit=2)
    res = BlindMethod(b, temperature=1.0).answer_many(recs[:2], "/x", seeds=[1, 2, 3, 4])
    assert b.calls == [("oom", 2, 4), ("oom", 1, 4), ("n", (1, 2)), ("n", (3, 4)),
                       ("oom", 1, 4), ("n", (1, 2)), ("n", (3, 4))], b.calls
    assert [[(r.id, r.seed, r.batch_n, r.error) for r in rr] for rr in res] == \
        [[(i, s, 2, None) for s in (1, 2, 3, 4)] for i in range(2)]


def test_only_a_sequence_that_fails_alone_becomes_an_error_row():
    b = _OomBackend(limit=0)
    res = BlindMethod(b, temperature=1.0).answer_many([REC, dict(REC, id=8)], "/x", seeds=[1, 2])
    assert [[(r.id, r.seed) for r in rr] for rr in res] == [[(7, 1), (7, 2)], [(8, 1), (8, 2)]]
    # each failed alone, in a call of its own: not a batched row
    assert all(r.error.startswith("OutOfMemoryError") and r.abstained and r.batch_n is None
               for rr in res for r in rr)
    assert "batched_rows" not in metrics.summarize([r.to_dict() for rr in res for r in rr])
    # down to single sequences, never below: 2x2, 1x2, 1x1, 1x1, 1x2, 1x1, 1x1
    assert [c for c in b.calls if c[0] == "oom"] == \
        [("oom", 2, 2), ("oom", 1, 2), ("oom", 1, 1), ("oom", 1, 1),
         ("oom", 1, 2), ("oom", 1, 1), ("oom", 1, 1)], b.calls


def test_runner_recovers_from_out_of_memory_without_error_rows():
    with tempfile.TemporaryDirectory() as d:
        fake = _OomBackend(limit=8)
        rows = _run(d, os.path.join(d, "o.jsonl"), fake, "--batch-passes",
                    "--batch-questions", "4", n_rec=4)
        assert fake.calls == [("oom", 4, 4)] + [("many", 2, (11, 12, 13, 14))] * 2, fake.calls
        assert [(r["id"], r["pass_idx"], r["error"]) for r in rows] == \
            [(i, p, None) for i in range(4) for p in range(1, 5)]
        assert all(r["batch_n"] == 8 for r in rows)


def test_a_failed_batched_call_writes_error_rows_and_the_leg_goes_on():
    class Flaky(_FakeBackend):
        def generate_many(self, messages_list, max_new_tokens, *, seeds, temperature=0.0):
            if not self.calls:
                self.calls.append(("boom", len(messages_list), tuple(seeds)))
                raise RuntimeError("device-side assert (fake)")
            return super().generate_many(messages_list, max_new_tokens, seeds=seeds,
                                         temperature=temperature)
    with tempfile.TemporaryDirectory() as d:
        fake = Flaky()
        rows = _run(d, os.path.join(d, "f.jsonl"), fake, "--batch-passes",
                    "--batch-questions", "2", n_rec=4)
        assert fake.calls == [("boom", 2, (11, 12, 13, 14)), ("many", 2, (11, 12, 13, 14))]
        err = [r for r in rows if r["error"]]
        assert [(r["id"], r["pass_idx"], r["seed"]) for r in err] == \
            [(i, p, 10 + p) for i in (0, 1) for p in range(1, 5)]
        assert all(r["error"].startswith("RuntimeError") and r["abstained"] and r["batch_n"] == 8
                   and r["decode"] for r in err)
        assert len(rows) == 16 and not any(r["error"] for r in rows if r["id"] in (2, 3))


def test_batch_questions_needs_batch_passes_and_a_positive_count():
    with tempfile.TemporaryDirectory() as d:
        for flags, msg in ((["--batch-questions", "6"], "without --batch-passes"),
                           (["--batch-passes", "--batch-questions", "0"], ">= 1"),
                           (["--batch-passes", "--batch-questions", "-2"], ">= 1")):
            fake = _FakeBackend()
            with pytest.raises(SystemExit, match=msg):
                _main(d, os.path.join(d, "x.jsonl"), fake, *flags)
            assert not fake.calls and not os.path.exists(os.path.join(d, "x.jsonl"))


def test_batch_questions_without_a_multi_question_path_says_so():
    class PerQuestion:
        """generate / generate_n only: nothing to group questions into."""
        name = _FakeBackend.name

        def __init__(self):
            self._fake = _FakeBackend()
            self.decode, self.calls = self._fake.decode, self._fake.calls
            self.generate, self.generate_n = self._fake.generate, self._fake.generate_n
    with tempfile.TemporaryDirectory() as d:
        fake, log = PerQuestion(), []
        rows = _run(d, os.path.join(d, "p.jsonl"), fake, "--batch-passes",
                    "--batch-questions", "2", log=log)
        assert "NOTE --batch-questions: blind on Qwen3.8-27B has no multi-question path" in log[0]
        assert fake.calls == [("n", (11, 12, 13, 14))] * 3 and len(rows) == 12


def test_batch_passes_without_a_batched_path_runs_one_call_per_pass():
    """InternVL (no generate_n) and every arm but blind (no answer_n) go through
    the same sbatch; --batch-passes must leave them on one call per pass, not
    route them into a batch call that fails into error rows."""
    class Plain:
        name = _FakeBackend.name

        def __init__(self):
            self._fake = _FakeBackend()
            self.decode, self.calls, self.generate = \
                self._fake.decode, self._fake.calls, self._fake.generate

    class NoBatch(BlindMethod):
        @property
        def answer_n(self):
            raise AttributeError("answer_n")

        @property
        def answer_many(self):
            raise AttributeError("answer_many")

    import bench.run_bench as rb
    with tempfile.TemporaryDirectory() as d:
        plain, log = Plain(), []
        rows = _run(d, os.path.join(d, "n.jsonl"), plain, "--batch-passes",
                    "--batch-questions", "2", log=log)
        assert plain.calls == [("one", s) for _ in range(3) for s in (11, 12, 13, 14)], plain.calls
        assert "NOTE --batch-passes: blind on Qwen3.8-27B has no batched path" in log[0]
        fake = _FakeBackend()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(rb, "make_method",
                       lambda mname, backend, args: NoBatch(backend, temperature=args.temperature))
            rows += _run(d, os.path.join(d, "m.jsonl"), fake, "--batch-passes")
        assert fake.calls == [("one", s) for _ in range(3) for s in (11, 12, 13, 14)], fake.calls
        assert len(rows) == 24 and not any(r["error"] for r in rows)
        assert all(r["batch_n"] is None and r["call_seed"] is None for r in rows)


def test_summary_splits_a_batched_calls_wall_clock_over_its_rows():
    base = dict(method="blind", backend="B", task_type="toy", correct=True, abstained=False,
                num_model_calls=1, input_tokens=10, output_tokens=3)
    unbatched = [dict(base, latency_s=2.0), dict(base, latency_s=4.0, num_model_calls=3)]
    s = metrics.summarize(unbatched)
    assert (s["latency_s"]["mean"], s["latency_s"]["p50"], s["tokens"]["calls_mean"]) == (3.0, 2.0, 2.0)
    assert "batched_rows" not in s
    # one 24-sequence call of 48 s, and one row sampled alone in 6 s
    batched = [dict(base, latency_s=48.0, batch_n=24) for _ in range(24)] + [dict(base, latency_s=6.0)]
    s = metrics.summarize(batched)
    assert s["latency_s"]["p50"] == 2.0 and s["latency_s"]["n"] == 25
    assert abs(s["latency_s"]["mean"] - (48.0 + 6.0) / 25) < 1e-12
    assert abs(s["tokens"]["calls_mean"] - 2 / 25) < 1e-12        # two calls over 25 rows
    assert s["batched_rows"] == 24
    assert "batched: 24/25 rows" in metrics.format_summary(batched)
    assert "batched" not in metrics.format_summary(unbatched)
    # batch_n 1 (an error row of a one-sequence call, as once stamped) ran alone
    alone = dict(base, latency_s=6.0, batch_n=1, error="OutOfMemoryError: x")
    assert metrics.summarize(batched + [alone])["batched_rows"] == 24
    assert "batched_rows" not in metrics.summarize(unbatched + [alone])
    assert "batched" not in metrics.format_summary(unbatched + [alone])


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
