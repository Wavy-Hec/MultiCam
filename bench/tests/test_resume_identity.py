"""The resume identity of a segment_select leg, and the submit-time refusals
that stand between a global leg and a silent no-op.

The selection MODE is a flag, not part of the method name: both modes write
`segment_select_viclip_opt` and resume keys on (id, method, backend, pass_idx),
so nothing but a top-level stamp tells a per_clip file from a global one. These
tests pin that stamp (`stamp_seg_identity`), what a resume reads back from it
(`existing_identity`), and the two guards that refuse a leg whose global
ranking could not decide anything (`check_global_regimes`, and the flag-guard
order inside `main`).

Pure CPU — no backend, no scorer model, no video, no Slurm. Runnable either way:

    pytest bench/tests/test_resume_identity.py
    python  bench/tests/test_resume_identity.py

Rows are synthetic on purpose: no global row exists on disk (the first campaign
has not run) and none of the segment_select rows written so far is a
prepare-error row, so real results cannot exercise either path.
"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from bench.run_bench import (check_global_regimes, existing_identity, main,
                             seg_identity, stamp_seg_identity)

# what BOTH modes write as `method`, and the backend basename 'internvl3'
# resolves to (INTERNVL_ALIASES) — the file-identity guards run before the
# segment one, so a fixture that disagrees would die with the wrong message
METHOD = "segment_select_viclip_opt"
BACKEND = "InternVL3-8B"
DATASET = "toy_subset"                       # = basename of the subset written below


def _args(**kw):
    """The runner's segment-selection defaults, overridden per test."""
    a = dict(seg_select="per_clip", seg_floor=1, budget=None, nframes=8,
             frames_per_segment=8)
    a.update(kw)
    return argparse.Namespace(**a)


def _row(**kw):
    """A row shaped like the write loop's output for a segment_select leg."""
    r = {"id": 1, "method": METHOD, "backend": BACKEND, "dataset": DATASET,
         "pass_idx": 1, "correct": True, "media_remap": None,
         "frame_alloc": {"mode": "segment_select", "K": 4,
                         "segment_select_mode": "per_clip", "seg_floor": None}}
    r.update(kw)
    return r


def _write(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


def _rec(rid, K):
    """A question record with K clips — enough for num_videos()."""
    rec = {"id": rid, "task_type": "toy", "answer": "A", "options": ["A. x", "B. y"]}
    rec.update({f"video_{i}": f"clip{i}.mp4" for i in range(1, K + 1)})
    return rec


def _subset(d, ks=(4, 4)):
    p = os.path.join(d, DATASET + ".json")
    json.dump([_rec(i, k) for i, k in enumerate(ks)], open(p, "w"))
    return p


def _run_main(argv):
    """main() under `argv`, returning its SystemExit message and stdout.

    Every call below must die at a submit-time guard. Nothing else in main()
    would stop it: the pre-flight media check only re-raises FileNotFoundError
    from video_paths, and the fixtures' non-existent `clipN.mp4` resolve
    without one (resolve_media raises only for an .avi with no .mp4 sibling),
    so the next statement is make_backend — which for 'internvl3' downloads and
    loads an 8B checkpoint. Replace it with a tripwire so a REGRESSED guard
    fails this test by name instead of pulling a model onto a CPU node.
    """
    import bench.run_bench as rb

    def _tripwire(*a, **kw):
        raise AssertionError(
            f"reached make_backend: a submit-time guard did not fire for {argv}")

    old_argv, old_make = sys.argv, rb.make_backend
    sys.argv = ["run_bench"] + argv
    rb.make_backend = _tripwire
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            main()
    except SystemExit as e:
        return str(e), buf.getvalue()
    finally:
        sys.argv, rb.make_backend = old_argv, old_make
    raise AssertionError(f"main() did not refuse: {argv}\n{buf.getvalue()}")


# --------------------------------------------------------------- identity ---

def test_per_clip_file_resumes_under_per_clip_flags():
    """(a) The common case: September's per_clip files must stay resumable."""
    with tempfile.TemporaryDirectory() as d:
        p = _write(os.path.join(d, "per_clip.jsonl"),
                   [_row(id=i, seg_select="per_clip", seg_floor=None)
                    for i in (1, 2, 3)])
        seg = existing_identity(p)[3]
        assert seg == {("per_clip", None)}, seg
        assert not seg - {seg_identity(_args())}          # nothing stray -> resumes


def test_pre_feature_rows_compare_equal_to_per_clip():
    """(d) Rows written before the flags existed carry NEITHER key (not a null
    value) and were per_clip by construction, so they must read as per_clip and
    pool with new per_clip rows in one file."""
    with tempfile.TemporaryDirectory() as d:
        legacy = _row(id=1)
        legacy.pop("seg_select", None)
        legacy.pop("seg_floor", None)
        assert "seg_select" not in legacy and "seg_floor" not in legacy
        p = _write(os.path.join(d, "legacy.jsonl"),
                   [legacy, _row(id=2, seg_select="per_clip", seg_floor=None)])
        seg = existing_identity(p)[3]
        assert seg == {("per_clip", None)}, seg           # ONE identity, not two
        assert not seg - {seg_identity(_args())}


def test_per_clip_file_is_refused_under_global():
    """(b) The silent-no-op case: same method name, same backend, same subset —
    only the flag differs, so without this the global leg finds every key done
    and appends nothing."""
    with tempfile.TemporaryDirectory() as d:
        p = _write(os.path.join(d, "per_clip.jsonl"),
                   [_row(id=i, seg_select="per_clip", seg_floor=None)
                    for i in (1, 2)])
        seg = existing_identity(p)[3]
        stray = seg - {seg_identity(_args(seg_select="global", seg_floor=1))}
        assert stray == {("per_clip", None)}, stray

        msg, _ = _run_main(["--subset", _subset(d), "--methods", METHOD,
                            "--backends", "internvl3", "--out", p,
                            "--seg-select", "global", "--budget", "96",
                            "--dedup-tau", "1"])
        assert "refusing to append" in msg, msg
        assert "'per_clip'" in msg and "'global'" in msg, msg   # names BOTH
        assert "NEW TAG" in msg, msg                            # names the remedy


def test_global_floors_do_not_pool():
    """(c) Two configured floors are two protocols; neither may resume the
    other's file."""
    with tempfile.TemporaryDirectory() as d:
        for mine, theirs in ((1, 2), (2, 1)):
            p = _write(os.path.join(d, f"g{mine}.jsonl"),
                       [_row(id=1, seg_select="global", seg_floor=mine)])
            seg = existing_identity(p)[3]
            assert seg == {("global", mine)}, seg
            assert not seg - {seg_identity(_args(seg_select="global",
                                                 seg_floor=mine))}
            assert seg - {seg_identity(_args(seg_select="global",
                                             seg_floor=theirs))} == seg


def test_capped_effective_floor_does_not_block_resume():
    """The defect this change exists to remove: select_segments caps the floor
    at N // K, so ONE floor-1 leg stamps frame_alloc.seg_floor 1 on its small-K
    records and 0 on its large-K ones. Identity reads the configured value, so
    the leg still resumes itself."""
    with tempfile.TemporaryDirectory() as d:
        p = _write(os.path.join(d, "mixed_k.jsonl"), [
            _row(id=1, seg_select="global", seg_floor=1,
                 frame_alloc={"segment_select_mode": "global", "K": 2,
                              "seg_floor": 1}),
            _row(id=2, seg_select="global", seg_floor=1,
                 frame_alloc={"segment_select_mode": "global", "K": 13,
                              "seg_floor": 0}),      # capped away by the budget
        ])
        seg = existing_identity(p)[3]
        assert seg == {("global", 1)}, seg
        assert not seg - {seg_identity(_args(seg_select="global", seg_floor=1))}


def test_error_rows_carry_the_keys():
    """(e) A prepare failure returns a Result with NO frame_alloc, so the mode
    can only live top-level; without the stamp one unreadable clip would make a
    global leg read back as per_clip and block every later resume."""
    args = _args(seg_select="global", seg_floor=1)
    err = _row(id=7, frame_alloc=None,
               error="prepare:FileNotFoundError: no candidate frames from any clip",
               correct=False)
    err.pop("seg_select", None)
    stamp_seg_identity(err, METHOD, args)
    assert err["seg_select"] == "global" and err["seg_floor"] == 1
    assert err["frame_alloc"] is None and err["error"].startswith("prepare:")

    with tempfile.TemporaryDirectory() as d:
        p = _write(os.path.join(d, "err.jsonl"), [err])
        assert existing_identity(p)[3] == {("global", 1)}

    # per_clip stamps a MEANINGFUL None floor, and no other method is stamped
    row = _row(id=8)
    stamp_seg_identity(row, METHOD, _args())
    assert (row["seg_select"], row["seg_floor"]) == ("per_clip", None)
    other = {"method": "centralized"}
    stamp_seg_identity(other, "centralized", args)
    assert "seg_select" not in other and "seg_floor" not in other


# ----------------------------------------------------------------- guards ---

def test_negative_floor_message_wins():
    """(f) A negative floor is also != 1, so the outside-global guard used to
    answer it first: 'applies only to --seg-select global' sends the operator to
    set SEG_SELECT instead of fixing the typo."""
    with tempfile.TemporaryDirectory() as d:
        msg, _ = _run_main(["--subset", _subset(d), "--methods", METHOD,
                            "--backends", "internvl3", "--seg-floor", "-2",
                            "--dedup-tau", "1"])
        assert "is negative" in msg, msg
        assert "applies only to" not in msg, msg
        # and it still fires under global, where the outside-global guard cannot
        msg, _ = _run_main(["--subset", _subset(d), "--methods", METHOD,
                            "--backends", "internvl3", "--seg-select", "global",
                            "--seg-floor", "-1", "--dedup-tau", "1"])
        assert "is negative" in msg, msg


def test_budget_below_K_is_refused_at_submit():
    """(g) SegmentSelectMethod._prepare raises `budget < K views` — but only
    after make_backend has loaded the model, and then once per pass."""
    args = _args(seg_select="global", budget=3)
    try:
        check_global_regimes([METHOD], [_rec(0, 4)], args)
    except SystemExit as e:
        assert "one frame per clip" in str(e), e
        assert "frames_per_segment x (K x seg_floor + 1)" in str(e), e
    else:
        raise AssertionError("budget 3 < K 4 was not refused")

    # via main(), i.e. the hoisted call site really runs before make_backend
    with tempfile.TemporaryDirectory() as d:
        msg, _ = _run_main(["--subset", _subset(d, ks=(4,)), "--methods", METHOD,
                            "--backends", "internvl3", "--seg-select", "global",
                            "--budget", "3", "--dedup-tau", "1"])
        assert "one frame per clip" in msg, msg


def test_inert_global_leg_is_refused_and_a_live_one_is_not():
    """N <= K x seg_floor is per_clip top-floor wearing a global tag. On MEVA
    (K=4, 8 frames/segment) that is BUDGET 32 — and the auto budget (nframes x
    K) too; 64 and 96 compete."""
    data = [_rec(0, 4), _rec(1, 4)]
    for budget in (None, 32):
        try:
            check_global_regimes([METHOD], data,
                                 _args(seg_select="global", budget=budget))
        except SystemExit as e:
            assert "inert" in str(e), e
            assert ("Raise --budget to at least frames_per_segment x "
                    "(K x seg_floor + 1)") in str(e), e
        else:
            raise AssertionError(f"budget {budget} was not refused")
    for budget in (64, 96):
        got = check_global_regimes([METHOD], data,
                                   _args(seg_select="global", budget=budget))
        assert got == {"competes": 2}, (budget, got)
    # floor 0 never has a floor pass to cancel the ranking
    got = check_global_regimes([METHOD], data,
                               _args(seg_select="global", seg_floor=0, budget=32))
    assert got == {"pure global": 2}, got


def test_capped_floor_warns_even_when_every_record_is_live():
    """A leg where the budget cancels the floor on EVERY record is not refused
    — the ranking still decides — but the starvation guard the operator asked
    for is not in force anywhere, so it must not pass in silence."""
    data = [_rec(0, 13), _rec(1, 13)]        # N = 64 // 8 = 8 < K, so f -> 0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = check_global_regimes([METHOD], data,
                                   _args(seg_select="global", budget=64))
    assert got == {"floor cancelled by the budget": 2}, got
    warns = [ln for ln in buf.getvalue().splitlines() if ln.startswith("WARNING")]
    assert len(warns) == 1, buf.getvalue()                 # not the mixed one
    assert "capped away on 2/2" in warns[0], warns
    assert "leave clips" in warns[0], warns
    # raising the budget past K x seg_floor puts the floor back and silences it
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = check_global_regimes([METHOD], data,
                                   _args(seg_select="global", budget=8 * 14))
    assert got == {"competes": 2}, got
    assert buf.getvalue() == "", buf.getvalue()


def test_mixed_regimes_warn_once_per_leg():
    """The scan reads only args and data, so a leg naming two segment arms must
    classify its records — and warn — ONCE, not once per method."""
    data = [_rec(0, 4), _rec(1, 8)]          # at budget 64: competes / degenerate
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = check_global_regimes([METHOD], data,
                                   _args(seg_select="global", budget=64))
    assert got == {"competes": 1, "degenerate (== per_clip top-1)": 1}, got
    assert buf.getvalue().startswith("WARNING "), buf.getvalue()

    with tempfile.TemporaryDirectory() as d:
        p = _write(os.path.join(d, "per_clip.jsonl"),
                   [_row(id=1, seg_select="per_clip", seg_floor=None)])
        msg, out = _run_main(["--subset", _subset(d, ks=(4, 8)),
                              "--methods", f"{METHOD},segment_select_random",
                              "--backends", "internvl3", "--out", p,
                              "--seg-select", "global", "--budget", "64",
                              "--dedup-tau", "1"])
        assert "refusing to append" in msg, msg          # died at the resume guard
        warns = [ln for ln in out.splitlines() if ln.startswith("WARNING")]
        assert len(warns) == 1, out
        assert "mixes selection regimes" in warns[0], warns


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        # SystemExit is NOT an Exception: every guard here raises it, so a
        # miswired test would otherwise abort this runner silently
        except (Exception, SystemExit) as e:                  # noqa: BLE001
            fails += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
        else:
            print(f"ok   {name}")
    print("FAILED" if fails else "ALL PASS")
    sys.exit(1 if fails else 0)
