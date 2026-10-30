"""The `decode` stamp: the Qwen sampling / chat-template settings a row was
generated with, and the resume guard that keeps two settings out of one file.

QWEN_ENABLE_THINKING / QWEN_REASONING_EFFORT live only in the submit-time env,
and resume keys on (id, method, backend, pass_idx) alone, so a thinking-off
resume of a thinking-on file would otherwise append into it as if compatible.
These tests pin what `decode_identity` resolves, what `existing_identity` reads
back, and that `main` refuses the mismatch before any model loads.

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from bench.backends.qwen import decode_identity
from bench.run_bench import backend_decode, existing_identity, main

BACKEND = "Qwen3.8-27B"            # what alias 'qwen38' resolves to (QWEN_ALIASES)
DATASET = "toy_subset"
KNOBS = ("QWEN_ENABLE_THINKING", "QWEN_REASONING_EFFORT")


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
        assert d["enable_thinking"] is True and d["reasoning_effort"] == "medium", d


def _refused(**env):
    with _env(**env):
        try:
            decode_identity(env.pop("_model", "Qwen/Qwen3.8-27B"))
        except SystemExit as e:
            return str(e)
    raise AssertionError(f"not refused: {env}")


def test_bad_or_contradictory_knobs_are_refused_before_any_load():
    assert "use one of" in _refused(QWEN_ENABLE_THINKING="maybe")
    assert "accepts" in _refused(QWEN_REASONING_EFFORT="high")          # template raises on it
    assert "no effect" in _refused(QWEN_ENABLE_THINKING="0", QWEN_REASONING_EFFORT="low")
    # a checkpoint whose template has no knobs: a leaked export must not stamp
    # (or block the resume of) a leg whose generation it cannot change
    with _env(QWEN_ENABLE_THINKING="0"):
        try:
            decode_identity("Qwen/Qwen3-VL-8B-Thinking")
        except SystemExit as e:
            assert "no such knobs" in str(e), e
        else:
            raise AssertionError("knob on a knob-less checkpoint was not refused")


def test_existing_identity_reads_stamps_and_ignores_unstamped_rows():
    with _env(), tempfile.TemporaryDirectory() as d:
        stamp = decode_identity("Qwen/Qwen3.8-27B")
        p = _write(os.path.join(d, "f.jsonl"),
                   [_row(id=0), _row(id=1, decode=stamp), _row(id=2, decode=None)])
        decs = existing_identity(p)[4]
        assert decs == {json.dumps(stamp, sort_keys=True), "null"}, decs


def test_thinking_off_resume_of_thinking_on_file_is_refused():
    with tempfile.TemporaryDirectory() as d:
        with _env():
            on = decode_identity("Qwen/Qwen3.8-27B")
        p = _write(os.path.join(d, "f.jsonl"), [_row(id=0, decode=on)])
        with _env(QWEN_ENABLE_THINKING="0"):
            got, msg = _run_main(["--subset", _subset(d), "--methods", "blind",
                                  "--backends", "qwen38", "--out", p])
        assert got == "refused" and "decoded with" in msg, (got, msg)


def test_matching_and_unstamped_files_resume():
    with tempfile.TemporaryDirectory() as d:
        with _env():
            on = decode_identity("Qwen/Qwen3.8-27B")
            same = _write(os.path.join(d, "same.jsonl"), [_row(id=0, decode=on)])
            old = _write(os.path.join(d, "old.jsonl"), [_row(id=0)])
            for p in (same, old):
                got, msg = _run_main(["--subset", _subset(d), "--methods", "blind",
                                      "--backends", "qwen38", "--out", p])
                assert got == "reached", (p, msg)


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
