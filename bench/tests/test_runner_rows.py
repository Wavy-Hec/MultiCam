"""What run_bench's write loop puts in a result file beyond the Result itself,
read back from files that main() wrote: the stamps a resume compares (decode,
with the batched seeding scheme as `rng`; reasoning; max_new_tokens;
temperature), the refusal of a resume under other settings, and an intact
append after a torn last line, even one cut inside a multi-byte character.

Pure CPU — the fake backend and runner of test_batch_passes.py. Runnable
either way:

    pytest bench/tests/test_runner_rows.py
    python  bench/tests/test_runner_rows.py
"""
import json
import os
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)

from bench.backends.qwen import CALL_SEED_SCHEME
from bench.run_bench import existing_identity, load_done
from test_batch_passes import _FakeBackend, _main, _run

ALL_KEYS = [(i, p) for i in range(3) for p in range(1, 5)]


class _Unicode(_FakeBackend):
    """Replies in non-ASCII text, which rows keep as raw UTF-8 bytes
    (json.dumps(ensure_ascii=False))."""
    def _g(self, seed, *a, **kw):
        g = super()._g(seed, *a, **kw)
        g.text = "думаю → 思考 " + g.text
        return g


def test_every_row_carries_the_stamps_a_resume_compares():
    with tempfile.TemporaryDirectory() as d:
        fake = _FakeBackend()
        rows = _run(d, os.path.join(d, "u.jsonl"), fake)
        assert len(rows) == 12
        for r in rows:
            # an unbatched leg stamps exactly the backend's decode, as it always did
            assert r["decode"] == fake.decode and "rng" not in r["decode"]
            assert (r["temperature"], r["reasoning"], r["max_new_tokens"]) == (1.0, True, 8192)
        rows = _run(d, os.path.join(d, "b.jsonl"), fake, "--batch-passes", "--no-reasoning",
                    "--max-new-tokens", "512", "--temperature", "0.6")
        assert len(rows) == 12
        for r in rows:
            assert r["decode"] == dict(fake.decode, rng=CALL_SEED_SCHEME)
            assert (r["temperature"], r["reasoning"], r["max_new_tokens"]) == (0.6, False, 512)


def test_a_resume_under_other_settings_is_refused():
    """End to end: the first run writes the stamps, the second compares them
    (a complete file would otherwise be 'resumed' as a silent no-op)."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "s.jsonl")
        first = _run(d, out, _FakeBackend())                 # T 1.0, reasoning on, cap 8192
        for flags, key in ((["--temperature", "0.7"], "temperature"),
                           (["--no-reasoning"], "reasoning"),
                           (["--max-new-tokens", "4096"], "max_new_tokens")):
            fake = _FakeBackend()
            with pytest.raises(SystemExit, match=f"it holds rows with {key}"):
                _main(d, out, fake, *flags)
            assert not fake.calls
        with pytest.raises(SystemExit, match="decoded with"):
            _main(d, out, _FakeBackend(), env={"QWEN_ENABLE_THINKING": "0"})
        with pytest.raises(SystemExit, match="decoded with"):
            _main(d, out, _FakeBackend(), "--batch-passes")
        # the same settings resume (nothing is left to run)
        fake = _FakeBackend()
        assert _run(d, out, fake) == first and not fake.calls


def test_a_resume_after_a_torn_last_line_appends_every_missing_row():
    """A SIGKILL mid-write leaves a fragment with no newline. Appended straight
    onto it, the first new row fused with the fragment into one unparseable
    line, so its (id, pass) stayed missing after the resume."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "t.jsonl")
        rows = _run(d, out, _FakeBackend())
        torn = json.dumps(rows[5])[:40]
        with open(out, "w") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in rows[:5])
            fh.write(torn)
        fake = _FakeBackend()
        _main(d, out, fake)
        assert len(fake.calls) == 7                          # the torn row and the six after it
        good, bad = [], []
        for line in open(out).read().splitlines():
            try:
                good.append(json.loads(line))
            except json.JSONDecodeError:
                bad.append(line)
        assert bad == [torn]                                 # only the fragment is lost
        assert sorted((r["id"], r["pass_idx"]) for r in good) == ALL_KEYS
        # and a file that ends cleanly gets nothing extra
        size = os.path.getsize(out)
        _main(d, out, _FakeBackend())
        assert os.path.getsize(out) == size


def test_a_tear_inside_a_multibyte_character_is_skipped_like_any_other():
    """The cut can fall inside a multi-byte character. Read as strict UTF-8,
    that fragment raised in load_done and existing_identity, so the resume
    died before it ran, and in the summary once the resume had ended the
    fragment and it sat mid-file, after all the compute."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "m.jsonl")
        _run(d, out, _Unicode())
        lines = open(out, "rb").read().split(b"\n")
        frag = lines[5][:lines[5].index("→".encode()) + 2]   # two of the arrow's three bytes
        with open(out, "wb") as fh:
            fh.write(b"\n".join(lines[:5]) + b"\n" + frag)
        assert len(load_done(out)) == 5 and existing_identity(out)[0] == {_FakeBackend.name}
        summary = out.replace(".jsonl", "_summary.json")
        os.remove(summary)
        fake = _Unicode()
        _main(d, out, fake)
        assert len(fake.calls) == 7                          # the torn row and the six after it
        good, bad = [], []
        for line in open(out, errors="replace").read().split("\n")[:-1]:
            try:
                good.append(json.loads(line))
            except json.JSONDecodeError:
                bad.append(line)
        assert bad == [frag.decode("utf-8", errors="replace")]
        assert sorted((r["id"], r["pass_idx"]) for r in good) == ALL_KEYS
        # rewritten, every row counted once and the fragment skipped
        assert json.load(open(summary))[f"blind/{_FakeBackend.name}"]["n"] == 12


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
