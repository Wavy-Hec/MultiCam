"""The answer span in every arm and in the clip-summary cache.

A Qwen3.8 thinking trace quotes the prompt's "<answer> and </answer>" before
its own answer, so every arm must parse GenOut.answer_span (the reply after
</think>), stamp parsed_from, store the backend's own reasoning split as
think, and pass only the reply on: per-view perception texts, live clip
summaries and the summary cache. An arm left on g.text scores that quote as
an abstention.

SummarySelectMethod.answer is also the answer stage of the clip_select,
frame_select, option-union, query-search and segment_select arms (they assign
or inherit it), whose scorers cannot load on a CPU node.

Pure CPU — a fake backend; the steps that decode video (montage stitching,
clip durations, media resolution) are stubbed, so no clip is read. Runnable
either way:

    pytest bench/tests/test_answer_span_arms.py
    python  bench/tests/test_answer_span_arms.py
"""
import contextlib
import glob
import io
import json
import os
import re
import sys
import tempfile
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import bench.methods.centralized as centralized
import bench.methods.clip_select as clip_select
from bench.methods.base import GenOut
from bench.methods.blind import BlindMethod
from bench.methods.cvbench_native import CVBenchNativeMethod
from bench.methods.per_stream import PerStreamMethod
from bench.methods.single_view import SingleViewMethod
from bench.methods.temporal import TemporalWeightedMethod
from bench.reuse import parse_choice

THINK = ("The rules say the final answer goes between <answer> and </answer>, the reasoning "
         "between the <think> and </think> tags. Weighing both views, it is C.")
REPLY = "\n\n<answer>C</answer>"
OPTIONS = ["A. x", "B. y", "C. z", "D. w"]
REC = {"id": 1, "task_type": "t", "question": "Which one?", "answer": "C", "options": OPTIONS,
       "video_1": "a/c1.mp4", "video_2": "a/c2.mp4", "source": "s", "orig_num_cameras": 2,
       "cap_answer_safe": True}


class _Thinking:
    """A Qwen3.8-like backend whose every generation ENDED, so QwenBackend._out
    split it: answer_text is the reply after </think>, think_text the
    reasoning. reply_for(prompt text, messages) picks the reply."""
    name = "Qwen3.8-27B"

    def __init__(self, reply_for=lambda text, messages: REPLY):
        self.reply_for = reply_for
        self.prompts = []

    def generate(self, messages, max_new_tokens, *, seed=None, temperature=0.0):
        text = " ".join(item.get("text", "") for m in messages for item in m["content"]
                        if isinstance(item, dict))
        self.prompts.append(text)
        reply = self.reply_for(text, messages)
        return GenOut(text=THINK + "\n</think>" + reply, input_tokens=11, video_tokens=5,
                      output_tokens=7, latency_s=1.5, answer_text=reply, think_text=THINK)

    def generate_n(self, messages, max_new_tokens, *, seeds, temperature=0.0):
        return [self.generate(messages, max_new_tokens) for _ in seeds]

    def generate_many(self, messages_list, max_new_tokens, *, seeds, temperature=0.0):
        return [self.generate_n(m, max_new_tokens, seeds=seeds) for m in messages_list]


def _has_video(messages):
    return any(isinstance(item, dict) and item.get("type") == "video"
               for m in messages for item in m["content"])


def _parsed_from_the_reply(r):
    assert r.error is None, r.error
    assert (r.prediction, r.correct, r.abstained, r.parsed_from) == ("C", True, False, "after_think"), \
        (r.prediction, r.parsed_from)
    assert r.think == THINK and r.response_text == THINK + "\n</think>" + REPLY


def test_the_whole_text_would_abstain():
    # what an arm left on g.text scores: the quote is the first <answer> match
    assert parse_choice(THINK + "\n</think>" + REPLY, False, letters="ABCD", options=OPTIONS) == ""
    assert parse_choice(REPLY, False, letters="ABCD", options=OPTIONS) == "C"


def test_blind_one_call_per_pass_and_batched():
    m = BlindMethod(_Thinking(), temperature=0.7)
    rows = ([m.answer(REC, "/vr", seed=1)] + m.answer_n(REC, "/vr", seeds=[1, 2])
            + [r for rr in m.answer_many([REC, dict(REC, id=2)], "/vr", seeds=[1, 2]) for r in rr])
    assert len(rows) == 7
    for r in rows:
        _parsed_from_the_reply(r)


def test_cvbench_native():
    _parsed_from_the_reply(CVBenchNativeMethod(_Thinking(), nframes=8, temperature=0.7)
                           .answer(REC, "/vr", seed=3))


def test_single_view():
    _parsed_from_the_reply(SingleViewMethod(_Thinking(), view_idx=2, nframes=8, temperature=0.7,
                                            name="single_view2").answer(REC, "/vr", seed=3))


def test_per_stream_aggregates_the_perception_replies():
    seen = "\n\nA person in red walks left."
    b = _Thinking(lambda text, messages: seen if _has_video(messages) else REPLY)
    r = PerStreamMethod(b, nframes=8, temperature=0.7, stream_kind="video").answer(REC, "/vr", seed=3)
    _parsed_from_the_reply(r)
    descs = r.frame_alloc["perception_texts"]
    assert descs == [f"Video {k}:\n{seen.strip()}" for k in (1, 2)], descs
    assert THINK not in b.prompts[-1]           # the aggregator never reads a reasoning trace


def test_centralized():
    with pytest.MonkeyPatch.context() as mp:
        # no clip is decoded: one stand-in montage, sized like a two-camera grid
        mp.setattr(centralized, "build_montages",
                   lambda paths, **kw: [types.SimpleNamespace(size=(896, 448))])
        r = centralized.CentralizedMethod(_Thinking(), nframes=8, temperature=0.7) \
            .answer(REC, "/vr", seed=3)
    _parsed_from_the_reply(r)


def test_temporal_weighted():
    m = TemporalWeightedMethod(_Thinking(), budget=16, nframes=8, temperature=0.7)
    m._clip_meta = lambda vp: (30.0, 900)       # durations without decoding the clips
    _parsed_from_the_reply(m.answer(REC, "/vr", seed=3))


def _summary_reply(text, messages):
    if clip_select.SUMMARY_PROMPT in text:
        return "\n\nA person in red crosses the lot."
    if "SELECTED:" in text:
        return "\n\nSELECTED: 2"
    return REPLY


def test_summary_select_summarizes_selects_and_answers_on_replies():
    b = _Thinking(_summary_reply)
    with tempfile.TemporaryDirectory() as d, pytest.MonkeyPatch.context() as mp:
        cache = os.path.join(d, "summaries.jsonl")
        with open(cache, "w") as fh:            # clip 1 cached, clip 2 summarized live
            fh.write(json.dumps({"video": "a/c1.mp4", "summary": "A parked car.",
                                 "prompt_ver": clip_select.SUMMARY_PROMPT_VER}) + "\n")
        mp.setattr(clip_select, "_clip_meta", lambda vp: (30.0, 900))
        m = clip_select.SummarySelectMethod(b, summaries_path=cache, mode="route", budget=16,
                                            nframes=8, temperature=0.7)
        r = m.answer(REC, "/vr", seed=3)
    _parsed_from_the_reply(r)
    fa = r.frame_alloc
    assert fa["summary_source"] == ["cache", "live"]
    # the live summary is the reply alone, as the cache stores it
    assert fa["summaries_trunc"] == ["A parked car.", "A person in red crosses the lot."], fa
    assert (fa["selected"], fa["selection_fallback"]) == ([2], None)
    assert THINK not in b.prompts[1]            # nor does the selector read one


def test_the_summary_cache_stores_the_reply():
    """gen_clip_summaries builds the cache the summary_select arms read; it
    must store what their live fallback stores, the reply."""
    import bench.gen_clip_summaries as gen
    import bench.run_bench as rb
    b = _Thinking(_summary_reply)
    with tempfile.TemporaryDirectory() as d, pytest.MonkeyPatch.context() as mp:
        sub, out = os.path.join(d, "s.json"), os.path.join(d, "cache.jsonl")
        json.dump([REC], open(sub, "w"))
        mp.setattr(rb, "make_backend", lambda *a, **k: b)
        mp.setattr(gen, "resolve_media", lambda path: path)
        mp.setattr(gen, "_clip_meta", lambda vp: (30.0, 900))
        mp.setattr(sys, "argv", ["gen_clip_summaries", "--subset", sub, "--out", out,
                                 "--video-root", d, "--backend", "qwen38"])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            gen.main()
        rows = [json.loads(l) for l in open(out)]
        cache, _ = clip_select.load_summary_cache(out)
    assert [(r["video"], r["summary"], r["error"]) for r in rows] == \
        [(v, "A person in red crosses the lot.", None) for v in ("a/c1.mp4", "a/c2.mp4")]
    assert cache == {v: "A person in red crosses the lot." for v in ("a/c1.mp4", "a/c2.mp4")}


def test_no_arm_parses_or_stores_the_whole_text():
    """Source check over every arm, the ones without a CPU test above included:
    no parse of the raw text, and every row that stores response_text also
    stamps parsed_from and takes think from think_of."""
    for path in sorted(glob.glob(os.path.join(ROOT, "bench", "methods", "*.py"))):
        src, name = open(path).read(), os.path.basename(path)
        # (think_of itself falls back to extract_think(g.text): only a Result's
        # think= argument must not bypass it)
        for pat in (r"parse_choice\(\s*g\w*\.text\b", r"parse_selection\(\s*g\w*\.text\b",
                    r"think=extract_think\(\s*g\w*\.text\b"):
            assert not re.search(pat, src), f"{name}: {pat}"
        n = src.count("response_text=g.text")
        assert src.count("parsed_from=g.parsed_from") == n and src.count("think=think_of(g)") == n, \
            name


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
