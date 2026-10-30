"""The `decode` stamp: the Qwen sampling / chat-template settings a row was
generated with, and the resume guards that keep two settings out of one file.

QWEN_ENABLE_THINKING / QWEN_REASONING_EFFORT, TEMPERATURE, REASONING and
MAX_NEW_TOKENS live only in the submit-time env, and resume keys on (id,
method, backend, pass_idx) alone, so a resume under other settings would
otherwise append into the file as if compatible. These tests pin what
`decode_identity` resolves (one spelling per rendered prompt, and which preset
a model path takes), what `existing_identity` reads back (in that spelling,
whatever an older row stamped), and that `main` refuses each mismatch before
any model loads.

Pure CPU — no backend, no video, no Slurm. Runnable either way:

    pytest bench/tests/test_decode_identity.py
    python  bench/tests/test_decode_identity.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import types

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from bench.backends.qwen import CALL_SEED_SCHEME, canonical_decode, decode_identity
from bench.run_bench import backend_decode, existing_identity, main

BACKEND = "Qwen3.8-27B"            # what alias 'qwen38' resolves to (QWEN_ALIASES)
DATASET = "toy_subset"
KNOBS = ("QWEN_ENABLE_THINKING", "QWEN_REASONING_EFFORT")
# the stamps every row of the two shipped Qwen3.8 legs carries: thinking at
# effort medium, and the no-thinking control
Q38_THINKING = {"top_p": 0.95, "top_k": 20, "answer_after_think": True,
                "enable_thinking": None, "reasoning_effort": "medium"}
Q38_NO_THINKING = {"top_p": 0.95, "top_k": 20, "answer_after_think": True,
                   "enable_thinking": False, "reasoning_effort": None}


@contextlib.contextmanager
def _env(**kw):
    old = {k: os.environ.get(k) for k in KNOBS}
    try:
        for k in KNOBS:
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in kw.items()})
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _row(**kw):
    r = {"id": 0, "method": "blind", "backend": BACKEND, "dataset": DATASET,
         "pass_idx": 1, "correct": True, "media_remap": None}
    r.update(kw)
    return r


def _write(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


def _subset(d):
    p = os.path.join(d, DATASET + ".json")
    json.dump([{"id": i, "task_type": "toy", "answer": "A",
                "options": ["A. x", "B. y"], "video_1": "c1.mp4", "video_2": "c2.mp4"}
               for i in range(2)], open(p, "w"))
    return p


def _run_main(argv):
    """main() under `argv` -> ('refused', message) or ('reached', None) when it
    got past every submit-time guard to make_backend (replaced by a tripwire so
    no checkpoint is pulled onto a CPU node)."""
    import bench.run_bench as rb

    class _Reached(Exception):
        pass

    def _tripwire(*a, **kw):
        raise _Reached()

    old_argv, old_make = sys.argv, rb.make_backend
    sys.argv = ["run_bench"] + argv
    rb.make_backend = _tripwire
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            main()
    except SystemExit as e:
        return "refused", str(e)
    except _Reached:
        return "reached", None
    finally:
        sys.argv, rb.make_backend = old_argv, old_make
    raise AssertionError(f"main() neither refused nor reached make_backend: {argv}")


def _blind(d, out, *flags):
    return ["--subset", _subset(d), "--methods", "blind", "--backends", "qwen38",
            "--out", out, *flags]


def test_presets_and_knobs():
    with _env():
        legacy = decode_identity("Qwen/Qwen3-VL-8B-Thinking")
        assert legacy == {"top_p": 0.9, "top_k": None, "answer_after_think": False,
                          "enable_thinking": None, "reasoning_effort": None}, legacy
        q38 = decode_identity("Qwen/Qwen3.8-27B")
        assert (q38["top_p"], q38["top_k"], q38["answer_after_think"]) == (0.95, 20, True), q38
        assert backend_decode("qwen38") == q38
        assert backend_decode("internvl3") is None
    with _env(QWEN_ENABLE_THINKING="0"):
        assert decode_identity("Qwen/Qwen3.8-27B")["enable_thinking"] is False
    with _env(QWEN_ENABLE_THINKING="off"):
        assert decode_identity("Qwen/Qwen3.8-27B")["enable_thinking"] is False
    with _env(QWEN_ENABLE_THINKING="1", QWEN_REASONING_EFFORT="medium"):
        d = decode_identity("Qwen/Qwen3.8-27B")
        # thinking on IS the template default, so it stamps as unset
        assert d["enable_thinking"] is None and d["reasoning_effort"] == "medium", d


def test_explicit_template_defaults_stamp_as_unset():
    """The Qwen3.8 template renders the same prompt for an unset knob and its
    explicit default (`enable_thinking is undefined or enable_thinking is
    true`, `reasoning_effort|default('xhigh')`), so the two must stamp alike or
    a resume spelled the other way is refused for nothing."""
    with _env():
        unset = decode_identity("Qwen/Qwen3.8-27B")
    for env in ({"QWEN_ENABLE_THINKING": "1"}, {"QWEN_ENABLE_THINKING": "true"},
                {"QWEN_REASONING_EFFORT": "xhigh"}, {"QWEN_REASONING_EFFORT": "XHigh"},
                {"QWEN_ENABLE_THINKING": "on", "QWEN_REASONING_EFFORT": "xhigh"}):
        with _env(**env):
            assert decode_identity("Qwen/Qwen3.8-27B") == unset, env
    # the shipped legs' stamps are what the same env still resolves to
    with _env(QWEN_REASONING_EFFORT="medium"):
        assert decode_identity("Qwen/Qwen3.8-27B") == Q38_THINKING
    with _env(QWEN_ENABLE_THINKING="1", QWEN_REASONING_EFFORT="medium"):
        assert decode_identity("Qwen/Qwen3.8-27B") == Q38_THINKING
    with _env(QWEN_ENABLE_THINKING="0"):
        assert decode_identity("Qwen/Qwen3.8-27B") == Q38_NO_THINKING


def test_reasoning_effort_is_case_insensitive():
    for spelled in ("MEDIUM", " Medium ", "medium"):
        with _env(QWEN_REASONING_EFFORT=spelled):
            assert decode_identity("Qwen/Qwen3.8-27B") == Q38_THINKING, spelled
    with _env(QWEN_REASONING_EFFORT="Low"):
        assert decode_identity("Qwen/Qwen3.8-27B")["reasoning_effort"] == "low"


def _refused(model="Qwen/Qwen3.8-27B", **env):
    with _env(**env):
        try:
            decode_identity(model)
        except SystemExit as e:
            return str(e)
    raise AssertionError(f"not refused: {env}")


def test_bad_or_contradictory_knobs_are_refused_before_any_load():
    assert "use one of" in _refused(QWEN_ENABLE_THINKING="maybe")
    msg = _refused(QWEN_REASONING_EFFORT="High")                  # the template raises on it
    assert "'High'" in msg and "accepts only xhigh, medium, low" in msg, msg
    assert "no effect" in _refused(QWEN_ENABLE_THINKING="0", QWEN_REASONING_EFFORT="low")
    assert "no effect" in _refused(QWEN_ENABLE_THINKING="0", QWEN_REASONING_EFFORT="xhigh")
    # a checkpoint whose template has no knobs: a leaked export must not stamp
    # (or block the resume of) a leg whose generation it cannot change; an
    # explicit default is still a knob that checkpoint does not have
    for env in ({"QWEN_ENABLE_THINKING": "0"}, {"QWEN_ENABLE_THINKING": "1"},
                {"QWEN_REASONING_EFFORT": "xhigh"}):
        assert "no such knobs" in _refused("Qwen/Qwen3-VL-8B-Thinking", **env), env


def test_preset_matches_a_path_to_the_checkpoint():
    """The preset (sampling + the after-</think> parse) must not hinge on the
    exact HF id string: a trailing slash or a local copy of the checkpoint ran
    with the legacy decode and the whole-text parse."""
    with _env():
        q38 = decode_identity("Qwen/Qwen3.8-27B")
        legacy = decode_identity("Qwen/Qwen3-VL-8B-Thinking")
        # (paths no other test resolves: the NOTE is printed once per process)
        for path in ("Qwen/Qwen3.8-27B/", "/models/a/Qwen3.8-27B", "/scratch/a/qwen3.8-27b//"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                got, again = decode_identity(path), backend_decode(path)
            assert got == again == q38, (path, got)
            # said once per path, however often it is resolved
            assert buf.getvalue().count("NOTE") == 1 and "Qwen/Qwen3.8-27B" in buf.getvalue(), \
                buf.getvalue()
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            assert decode_identity("/models/Qwen3.8-27B-old") == legacy
            assert decode_identity("Qwen/Qwen3-VL-8B-Thinking") == legacy
        assert buf.getvalue() == ""
    with _env(QWEN_ENABLE_THINKING="0"), contextlib.redirect_stdout(io.StringIO()):
        assert decode_identity("/models/a/Qwen3.8-27B/") == Q38_NO_THINKING


def _construct(model_path, **env):
    """QwenBackend.__init__ with load_model replaced by a stand-in: what the
    constructor derives from decode_identity, without any weights."""
    import bench.backends.qwen as qwen

    class _Tok:
        def convert_tokens_to_ids(self, t):
            return {"<|video_pad|>": 7, "<|image_pad|>": 8}[t]

    proc = types.SimpleNamespace(tokenizer=_Tok(),
                                 image_processor=types.SimpleNamespace(patch_size=16))
    model = types.SimpleNamespace(device=torch.device("cpu"),
                                  generation_config=types.SimpleNamespace(eos_token_id=[1, 2]))
    old = qwen.load_model
    qwen.load_model = lambda path, dt: (model, proc)
    try:
        with _env(**env):
            return qwen.QwenBackend(model_path)
    finally:
        qwen.load_model = old


def test_only_non_default_knobs_reach_the_template():
    assert _construct("Qwen/Qwen3-VL-8B-Thinking")._template_kwargs == {}
    assert _construct("Qwen/Qwen3.8-27B")._template_kwargs == {}
    assert _construct("Qwen/Qwen3.8-27B", QWEN_ENABLE_THINKING="yes",
                      QWEN_REASONING_EFFORT="XHIGH")._template_kwargs == {}
    assert _construct("Qwen/Qwen3.8-27B", QWEN_ENABLE_THINKING="0")._template_kwargs == \
        {"enable_thinking": False}
    # lower-cased: the template itself only accepts lower case
    assert _construct("Qwen/Qwen3.8-27B", QWEN_REASONING_EFFORT="Medium")._template_kwargs == \
        {"reasoning_effort": "medium"}
    with contextlib.redirect_stdout(io.StringIO()):
        b = _construct("/models/b/Qwen3.8-27B", QWEN_REASONING_EFFORT="low")
    assert b.name == "Qwen3.8-27B" and b.decode["top_p"] == 0.95
    assert b._template_kwargs == {"reasoning_effort": "low"}


def test_existing_identity_reads_stamps_and_ignores_unstamped_rows():
    with _env(), tempfile.TemporaryDirectory() as d:
        stamp = decode_identity("Qwen/Qwen3.8-27B")
        # a row stamped decode=None (a backend with no such settings) is a stamp
        p = _write(os.path.join(d, "f.jsonl"),
                   [_row(id=0), _row(id=1, decode=stamp), _row(id=2, decode=None)])
        assert existing_identity(p)[4] == {json.dumps(stamp, sort_keys=True), "null"}
        # ... a row that predates the stamp is not: alone it adds nothing
        old = _write(os.path.join(d, "old.jsonl"), [_row(id=0), _row(id=1)])
        assert existing_identity(old)[4] == set()
        assert existing_identity(old)[5] == {"temperature": set(), "reasoning": set(),
                                             "max_new_tokens": set()}


def test_existing_identity_reads_the_run_settings():
    with tempfile.TemporaryDirectory() as d:
        p = _write(os.path.join(d, "f.jsonl"),
                   [_row(id=0, temperature=0.6, reasoning=False, max_new_tokens=8192),
                    _row(id=1, temperature=0.7),        # predates the reasoning / cap stamps
                    _row(id=2, temperature=None),       # a row with no temperature
                    _row(id=3)])
        assert existing_identity(p)[5] == {"temperature": {0.6, 0.7}, "reasoning": {False},
                                           "max_new_tokens": {8192}}


def test_thinking_off_resume_of_thinking_on_file_is_refused():
    with tempfile.TemporaryDirectory() as d:
        with _env():
            on = decode_identity("Qwen/Qwen3.8-27B")
        p = _write(os.path.join(d, "f.jsonl"), [_row(id=0, decode=on)])
        with _env(QWEN_ENABLE_THINKING="0"):
            got, msg = _run_main(_blind(d, p))
        assert got == "refused" and "decoded with" in msg, (got, msg)


def test_matching_and_unstamped_files_resume():
    with tempfile.TemporaryDirectory() as d:
        with _env():
            on = decode_identity("Qwen/Qwen3.8-27B")
            same = _write(os.path.join(d, "same.jsonl"), [_row(id=0, decode=on)])
            old = _write(os.path.join(d, "old.jsonl"), [_row(id=0)])
            for p in (same, old):
                got, msg = _run_main(_blind(d, p))
                assert got == "reached", (p, msg)
        # an explicit default resumes a file written with the knob unset
        with _env(QWEN_ENABLE_THINKING="1", QWEN_REASONING_EFFORT="xhigh"):
            got, msg = _run_main(_blind(d, same))
        assert got == "reached", msg


def test_a_file_stamped_with_an_explicit_default_as_spelled_resumes():
    """Rows stamped before an explicit template default mapped to None carry
    it as spelled: enable_thinking true for QWEN_ENABLE_THINKING=1, and
    reasoning_effort "xhigh" for QWEN_REASONING_EFFORT=xhigh. Such a row
    rendered the prompt the unset knob renders, so its file resumes under the
    same env (or the knob unset) and is refused only when the prompt differs."""
    base = {"top_p": 0.95, "top_k": 20, "answer_after_think": True}
    with _env():
        unset = decode_identity("Qwen/Qwen3.8-27B")
    medium = {"QWEN_ENABLE_THINKING": "1", "QWEN_REASONING_EFFORT": "medium"}
    xhigh = {"QWEN_ENABLE_THINKING": "1", "QWEN_REASONING_EFFORT": "xhigh"}
    # (as stamped, the env that stamped it, the same prompt spelled today)
    for stamp, env, same in (
            (dict(base, enable_thinking=True, reasoning_effort="medium"), medium, Q38_THINKING),
            (dict(base, enable_thinking=True, reasoning_effort=None),
             {"QWEN_ENABLE_THINKING": "1"}, unset),
            (dict(base, enable_thinking=None, reasoning_effort="xhigh"),
             {"QWEN_REASONING_EFFORT": "xhigh"}, unset),
            (dict(base, enable_thinking=True, reasoning_effort="xhigh"), xhigh, unset)):
        assert canonical_decode(stamp) == same, stamp
        with tempfile.TemporaryDirectory() as d:
            p = _write(os.path.join(d, "f.jsonl"), [_row(id=0, decode=stamp)])
            assert existing_identity(p)[4] == {json.dumps(same, sort_keys=True)}
            with _env(**env):
                got, msg = _run_main(_blind(d, p))
            assert got == "reached", (stamp, msg)
            if same == unset:
                with _env():
                    assert _run_main(_blind(d, p))[0] == "reached", stamp
            # another prompt, or the batched scheme, is still another decode
            for other in ({"QWEN_ENABLE_THINKING": "0"}, {"QWEN_REASONING_EFFORT": "low"}):
                with _env(**other):
                    got, msg = _run_main(_blind(d, p))
                assert got == "refused" and "decoded with" in msg, (stamp, other, got)
            with _env(**env):
                assert _run_main(_blind(d, p, "--batch-passes"))[0] == "refused", stamp
    # every other key is kept (rng included), and a None stamp stays None
    assert canonical_decode(dict(base, enable_thinking=True, reasoning_effort="xhigh",
                                 rng=CALL_SEED_SCHEME)) == dict(unset, rng=CALL_SEED_SCHEME)
    assert canonical_decode(None) is None


def test_shipped_stamps_resume_unbatched_and_refuse_the_new_batched_scheme():
    """The shipped legs' rows carry no `rng`: their batched calls were all
    reseeded with the first pass's seed. An unbatched resume under the same
    env still matches them; a batched one (call-hash seeding) is refused."""
    with tempfile.TemporaryDirectory() as d:
        for stamp, env in ((Q38_THINKING, {"QWEN_REASONING_EFFORT": "medium"}),
                           (Q38_NO_THINKING, {"QWEN_ENABLE_THINKING": "0"})):
            p = _write(os.path.join(d, "shipped.jsonl"),
                       [_row(id=0, decode=stamp, temperature=0.6)])
            # already in canonical form: compared exactly as written
            assert canonical_decode(stamp) == stamp
            assert existing_identity(p)[4] == {json.dumps(stamp, sort_keys=True)}
            with _env(**env):
                assert _run_main(_blind(d, p, "--temperature", "0.6"))[0] == "reached"
                got, msg = _run_main(_blind(d, p, "--temperature", "0.6", "--batch-passes",
                                            "--batch-questions", "6"))
                assert got == "refused" and CALL_SEED_SCHEME in msg, (got, msg)
                assert _run_main(_blind(d, p, "--temperature", "0.6", "--batch-passes",
                                        "--allow-mixed"))[0] == "reached"
        # a file of the current batched scheme resumes batched, not unbatched
        p = _write(os.path.join(d, "batched.jsonl"),
                   [_row(id=0, decode=dict(Q38_THINKING, rng=CALL_SEED_SCHEME))])
        with _env(QWEN_REASONING_EFFORT="medium"):
            assert _run_main(_blind(d, p, "--batch-passes"))[0] == "reached"
            got, msg = _run_main(_blind(d, p))
            assert got == "refused" and "decoded with" in msg, (got, msg)


def test_temperature_reasoning_and_cap_mismatches_are_refused():
    with _env(), tempfile.TemporaryDirectory() as d:
        p = _write(os.path.join(d, "f.jsonl"),
                   [_row(id=0, temperature=0.6, reasoning=True, max_new_tokens=8192)])
        same = ["--temperature", "0.6", "--max-new-tokens", "8192"]
        assert _run_main(_blind(d, p, *same))[0] == "reached"
        for flags, key in ((["--temperature", "0.6", "--max-new-tokens", "8192",
                             "--no-reasoning"], "reasoning"),
                           (["--temperature", "0.7", "--max-new-tokens", "8192"], "temperature"),
                           (["--temperature", "0.6", "--max-new-tokens", "4096"],
                            "max_new_tokens")):
            got, msg = _run_main(_blind(d, p, *flags))
            assert got == "refused" and f"it holds rows with {key}" in msg, (flags, got, msg)
            assert _run_main(_blind(d, p, *flags, "--allow-mixed"))[0] == "reached"
        # rows that predate the stamps are not compared on them
        old = _write(os.path.join(d, "old.jsonl"), [_row(id=0)])
        assert _run_main(_blind(d, old, "--temperature", "0.1", "--no-reasoning",
                                "--max-new-tokens", "64"))[0] == "reached"


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
