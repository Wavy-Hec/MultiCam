"""CPU gate for the --segment-seconds time partition (segment_select).

The PI's rule (2026-09-17): every camera stream is cut into 8-second clips, a
clip scores s(c, j) = max over the query texts of its similarity, and the 12
best (camera, clip) pairs over ALL cameras are kept — 96 frames. These tests
pin the partition arithmetic, that the count partition is untouched by the new
flag, the resume identity, and — on a synthetic clip, with a fake scorer and no
model — that the whole _prepare path delivers exactly those 12 x 8 frames at
full resolution.

Run from the repo root:  python -m pytest bench/tests/test_segment_seconds.py -q
"""
import argparse
import json
import os
import tempfile

import numpy as np
import pytest
from PIL import Image

from bench.methods import segment_select as ss
from bench.methods.segment_select import (SEGMENT_SELECT_GLOBAL_PREFIX,
                                          SEGMENT_SELECT_PREFIX,
                                          SegmentSelectMethod, _prefix_for,
                                          segment_bounds)
from bench.methods.viclip_scorer import VICLIP_SIDE
from bench.run_bench import (existing_identity, seg_identity,
                             stamp_seg_identity)


# ---------------------------------------------------------------- partition

def test_pi_example_64s_is_8_clips_under_both_rules():
    for fps in (10, 25, 30, 60):
        n = 64 * fps
        t = segment_bounds(n, fps, 8, 8.0)
        assert t == [8 * fps * s for s in range(9)], (fps, t)
        assert t == segment_bounds(n, fps, 8, 0.0)


def test_meva_camera_is_38_clips_not_8():
    b = segment_bounds(9000, 30.0, 8, 8.0)            # 300 s at 30 fps
    assert len(b) - 1 == 38
    assert all(b[s + 1] - b[s] == 240 for s in range(37))
    assert b[-1] - b[-2] == 120                       # a 4 s tail stands alone
    assert segment_bounds(9000, 30.0, 8, 0.0) == [1125 * s for s in range(9)]


def test_short_tail_joins_the_last_segment():
    b = segment_bounds(37 * 240 + 119, 30.0, 8, 8.0)  # tail just under half
    assert len(b) - 1 == 37 and b[-1] - b[-2] == 240 + 119
    b = segment_bounds(37 * 240, 30.0, 8, 8.0)        # no tail at all
    assert len(b) - 1 == 37 and b[-1] == 37 * 240


def test_clip_shorter_than_a_window_is_one_segment():
    assert segment_bounds(100, 30.0, 8, 8.0) == [0, 100]
    assert segment_bounds(1, 30.0, 8, 8.0) == [0, 1]


def test_bounds_are_a_partition():
    rng = np.random.default_rng(0)
    for _ in range(300):
        n = int(rng.integers(1, 40000))
        fps = float(rng.choice([7.5, 10, 23.976, 25, 29.97, 30, 59.94]))
        secs = float(rng.choice([1, 2.5, 8, 10]))
        b = segment_bounds(n, fps, 8, secs)
        assert b[0] == 0 and b[-1] == n
        assert all(b[i] < b[i + 1] for i in range(len(b) - 1)), (n, fps, b)
        w = max(1, round(fps * secs))
        assert all(b[i + 1] - b[i] == w for i in range(len(b) - 2))
        assert b[-1] - b[-2] < 1.5 * w or len(b) == 2


def test_time_partition_needs_a_frame_rate():
    for fps in (0, 0.0, None, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            segment_bounds(9000, fps, 8, 8.0)


def test_rows_can_rebuild_the_partition_from_their_stamps():
    """per_video_decode stamps n_total, n_segments and segment_frames (= w);
    analysis must rebuild a time partition from those, never the count rule."""
    rng = np.random.default_rng(3)
    for _ in range(500):
        n = int(rng.integers(1, 40000))
        fps = float(rng.choice([10, 23.976, 25, 29.97, 30, 59.94]))
        b = segment_bounds(n, fps, 8, 8.0)
        w, S = ss.segment_window_frames(fps, 8.0), len(b) - 1
        assert [s * w for s in range(S)] + [n] == b


def test_count_partition_is_unchanged():
    rng = np.random.default_rng(1)
    for _ in range(300):
        n = int(rng.integers(1, 40000))
        spv = int(rng.integers(1, 20))
        S = max(1, min(spv, n))
        want = [round(s * n / S) for s in range(S + 1)]   # the pre-flag rule
        assert segment_bounds(n, 30.0, spv, 0.0) == want
        assert segment_bounds(n, 0.0, spv) == want        # fps never read


# ------------------------------------------------------------------- prompt

def test_count_partition_prompt_is_byte_identical():
    for glob, const in ((False, SEGMENT_SELECT_PREFIX),
                        (True, SEGMENT_SELECT_GLOBAL_PREFIX)):
        old = const.format(K=4, S=8, top=12, n=96)
        assert _prefix_for(glob, 0.0, 8).format(K=4, top=12, n=96) == old


def test_time_partition_prompt_names_the_window():
    p = _prefix_for(True, 8.0, 8).format(K=4, top=12, n=96)
    assert "consecutive segments of about 8 seconds" in p
    assert "equal time segments" not in p and "{" not in p
    old = SEGMENT_SELECT_GLOBAL_PREFIX.format(K=4, S=8, top=12, n=96)
    assert p.replace("consecutive segments of about 8 seconds",
                     "up to 8 equal time segments") == old


# ----------------------------------------------------------------- identity

def _args(**kw):
    a = dict(seg_select="per_clip", seg_floor=1, segment_seconds=0.0)
    a.update(kw)
    return argparse.Namespace(**a)


def test_identity_keeps_the_pair_without_the_flag():
    assert seg_identity(_args()) == ("per_clip", None)
    assert seg_identity(_args(seg_select="global", seg_floor=0)) == ("global", 0)
    legacy = argparse.Namespace(seg_select="per_clip", seg_floor=1)  # no attr
    assert seg_identity(legacy) == ("per_clip", None)


def test_identity_carries_the_window_and_separates_the_partitions():
    a8 = _args(seg_select="global", seg_floor=0, segment_seconds=8.0)
    assert seg_identity(a8) == ("global", 0, 8.0)
    row = stamp_seg_identity({"method": "segment_select_viclip_auto"},
                             "segment_select_viclip_auto", a8)
    assert row["segment_seconds"] == 8.0
    plain = stamp_seg_identity({"method": "segment_select_viclip_auto"},
                               "segment_select_viclip_auto",
                               _args(seg_select="global", seg_floor=0))
    assert "segment_seconds" not in plain
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "leg.jsonl")
        with open(p, "w") as fh:
            fh.write(json.dumps(row) + "\n")
        prior = existing_identity(p)[3]
        assert prior == {("global", 0, 8.0)}
        assert not prior - {seg_identity(a8)}                      # resumes itself
        assert prior - {seg_identity(_args(seg_select="global", seg_floor=0))}
        assert prior - {seg_identity(_args(seg_select="global", seg_floor=0,
                                           segment_seconds=4.0))}
        with open(p, "w") as fh:
            fh.write(json.dumps(plain) + "\n")
        assert existing_identity(p)[3] - {seg_identity(a8)}        # and back


# --------------------------------------------------------------- thumbnails

def test_thumbnail_is_what_the_scorer_would_have_made():
    rng = np.random.default_rng(2)
    full = Image.fromarray(rng.integers(0, 256, (1072, 1920, 3), dtype=np.uint8))
    side = (VICLIP_SIDE, VICLIP_SIDE)
    from_full = np.asarray(full.convert("RGB").resize(side))       # _tube(full)
    thumb = full.convert("RGB").resize(side)                       # what we hold
    from_thumb = np.asarray(thumb.convert("RGB").resize(side))     # _tube(thumb)
    assert from_full.shape == (VICLIP_SIDE, VICLIP_SIDE, 3)
    assert np.array_equal(from_full, from_thumb)


def test_constructor():
    base = dict(name="segment_select_viclip_auto", dedup_tau=1.0)
    assert SegmentSelectMethod(object(), **base).segment_seconds == 0.0
    m = SegmentSelectMethod(object(), seg_scorer="viclip", segment_seconds=8, **base)
    assert m.segment_seconds == 8.0 and not m._needs_image_tower()
    with pytest.raises(ValueError):
        SegmentSelectMethod(object(), segment_seconds=-1, **base)
    assert SegmentSelectMethod(object(), name="segment_select_siglip_auto",
                               dedup_tau=1.0)._needs_image_tower()


# --------------------------------------------------- synthetic clip, no model

FPS, W, H = 10, 96, 64


def _write_clip(path, seconds, tint):
    cv2 = pytest.importorskip("cv2")
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    if not vw.isOpened():
        pytest.skip("cv2 cannot encode mp4v here")
    for i in range(seconds * FPS):
        fr = np.full((H, W, 3), tint, dtype=np.uint8)
        fr[:, : 1 + (i * (W - 1)) // (seconds * FPS)] = 255   # a moving edge
        vw.write(fr)
    vw.release()


@pytest.fixture(scope="module")
def clips():
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for k, secs in enumerate((64, 64, 64, 30)):               # 8+8+8+4 clips
            p = os.path.join(d, f"cam{k + 1}.mp4")
            _write_clip(p, secs, 40 * (k + 1))
            paths.append(p)
        yield d, paths


def test_decode_time_partition_and_full_reload(clips):
    _, paths = clips
    m = SegmentSelectMethod(object(), name="segment_select_viclip_auto",
                            dedup_tau=1.0, seg_scorer="viclip", segment_seconds=8)
    thumbs, meta = m._decode_segments(paths[0], thumb=True)
    fulls, meta2 = m._decode_segments(paths[0], thumb=False)
    assert meta == meta2 and meta["n_segments"] == 8 and meta["segment_frames"] == 80
    assert [e[0] for e in thumbs] == [s for s in range(8) for _ in range(8)]
    assert [e[3] for e in thumbs] == [e[3] for e in fulls]        # same indices
    # 8 frames per 8 s window = 1 fps, centred: 5, 15, ... inside each window
    assert [e[3] for e in thumbs[:8]] == [5 + 10 * j for j in range(8)]
    assert all(e[2].size == (VICLIP_SIDE, VICLIP_SIDE) for e in thumbs)
    assert all(e[2].size == (W, H) for e in fulls)
    _, meta30 = m._decode_segments(paths[3], thumb=True)
    assert meta30["n_segments"] == 4                              # 8+8+8+6 s
    assert meta30["segment_frames"] == 80                         # w, not a length

    pool = [(1, sid, t, im) for sid, t, im, fi in thumbs]
    pool_fi = [fi for *_, fi in thumbs]
    kept = [j for j, e in enumerate(pool) if e[1] in (2, 5)]
    back = m._load_full_frames(paths, pool, pool_fi, kept)
    assert back == kept
    for j in kept:
        assert pool[j][3].size == (W, H)
        assert np.array_equal(np.asarray(pool[j][3]), np.asarray(fulls[j][2]))
    assert all(pool[j][3].size == (VICLIP_SIDE, VICLIP_SIDE)
               for j in range(len(pool)) if j not in kept)


def _fake_scores(self, pool, queries):
    """Deterministic per-(camera, clip, query) scores; camera 2 is hottest."""
    out = {}
    for v, sid, t, im in pool:
        rng = np.random.default_rng(1000 * v + sid)
        out.setdefault(v, {})[sid] = rng.random(len(queries)) + (0.5 if v == 2 else 0)
    return out


def test_prepare_delivers_the_global_top12_at_full_resolution(clips, monkeypatch):
    d, paths = clips
    import bench.methods.viclip_scorer as vs
    monkeypatch.setattr(SegmentSelectMethod, "_viclip_segment_scores", _fake_scores)
    monkeypatch.setattr(vs, "viclip_text_overflow", lambda q, device=None: 0)
    rec = {"id": 7, "task_type": "CrossView-Toy-Event-Ordering",
           "question": "Order these: I. A man opens a door. II. A car stops. "
                       "III. A dog runs. Which sequence is correct?",
           "options": ["A. I -> II -> III", "B. III -> II -> I"], "answer": "A"}
    rec.update({f"video_{k + 1}": os.path.basename(p) for k, p in enumerate(paths)})
    m = SegmentSelectMethod(object(), name="segment_select_viclip_auto",
                            dedup_tau=1.0, seg_scorer="viclip", query="auto",
                            seg_select="global", seg_floor=0, budget=96,
                            segment_seconds=8)
    m.pool_records = [rec]
    content, yn, gold, fa = m._prepare(rec, d)

    # the query set is the three statements, and the score is their max
    assert fa["query_mode"] == "statements" and fa["n_query_texts"] == 3
    assert fa["query_texts"] == ["A man opens a door.", "A car stops.", "A dog runs."]
    raw = {}
    for v in range(1, 5):
        for sid in range(8 if v < 4 else 4):
            r = np.random.default_rng(1000 * v + sid).random(3) + (0.5 if v == 2 else 0)
            raw[(v, sid)] = float(r.max())
    assert {(int(v), int(s)): x for v, d_ in fa["segment_scores"].items()
            for s, x in d_.items()} == {k: round(x, 6) for k, x in raw.items()}

    # 28 candidate clips (8 + 8 + 8 + 4), the 12 best overall survive
    want = sorted(raw, key=lambda k: (-raw[k], k))[:12]
    got = [(int(v), s) for v, segs in fa["segments_kept_per_video"].items() for s in segs]
    assert sorted(got) == sorted(want)
    assert fa["segments_keep"] == 12 and fa["seg_floor"] == 0
    assert sum(1 for k in want if k[0] == 2) == 8          # no per-camera quota

    # 12 clips x 8 frames = 96 full-resolution frames reach the VLM
    images = [c["image"] for c in content if c.get("type") == "image"]
    assert len(images) == 96 == fa["n_selected"] == fa["n_kept_segment_frames"]
    assert fa["selection_on_thumbnails"] is True and fa["full_decode_dropped"] == 0
    assert fa["segment_seconds"] == 8.0 and fa["segments_per_video"] is None
    assert [pv["n_segments"] for pv in fa["per_video_decode"]] == [8, 8, 8, 4]
    assert fa["image_tower_ran"] is False
    assert "consecutive segments of about 8 seconds" in content[0]["text"]
    # every kept frame's time lies inside one of its camera's kept 8 s windows
    for v, times in fa["selected_times_s"].items():
        segs = fa["segments_kept_per_video"][v]
        assert all(int(t // 8) in segs for t in times), (v, times, segs)


def test_prepare_with_the_image_tower_scores_full_frames(clips, monkeypatch):
    """The SigLIP arm under --segment-seconds: the image tower reads the
    frames, so nothing is thumbnailed and the same 12 x 8 frames come out."""
    d, paths = clips

    def fake_clip_scores(bundle, query, frames, batch=32, return_image_embs=False):
        assert all(im.size == (W, H) for im in frames)            # never thumbnails
        n_q = len(query) if isinstance(query, list) else None
        rng = np.random.default_rng(len(frames))
        sc = rng.random((len(frames), n_q)) if n_q else rng.random(len(frames))
        embs = rng.standard_normal((len(frames), 16))
        embs /= np.linalg.norm(embs, axis=1, keepdims=True)
        return (sc, embs) if return_image_embs else sc

    monkeypatch.setattr(ss, "clip_scores", fake_clip_scores)
    monkeypatch.setattr(SegmentSelectMethod, "_ensure_clip", lambda self: None)
    rec = {"id": 9, "task_type": "toy", "question": "What happens?",
           "options": ["A. A man opens a door", "B. A car stops at a light"],
           "answer": "A"}
    rec.update({f"video_{k + 1}": os.path.basename(p) for k, p in enumerate(paths)})
    m = SegmentSelectMethod(object(), name="segment_select_siglip_auto",
                            dedup_tau=1.0, query="auto", seg_select="global",
                            seg_floor=0, budget=96, segment_seconds=8)
    content, yn, gold, fa = m._prepare(rec, d)
    assert fa["selection_on_thumbnails"] is False and fa["full_decode_dropped"] is None
    assert fa["image_tower_ran"] is True and fa["segment_seconds"] == 8.0
    assert [pv["n_segments"] for pv in fa["per_video_decode"]] == [8, 8, 8, 4]
    assert fa["segments_kept_total"] == 12 and fa["n_selected"] == 96
    images = [c["image"] for c in content if c.get("type") == "image"]
    assert len(images) == 96


def test_record_with_fewer_clips_than_the_budget_keeps_them_all(clips, monkeypatch):
    """Cameras shorter than ~12 s give one clip each: top-12 of 2 keeps both,
    16 frames are shown, and the row says selection did nothing."""
    d, paths = clips
    import bench.methods.viclip_scorer as vs
    monkeypatch.setattr(SegmentSelectMethod, "_viclip_segment_scores", _fake_scores)
    monkeypatch.setattr(vs, "viclip_text_overflow", lambda q, device=None: 0)
    short = []
    for k in range(2):
        p = os.path.join(d, f"short{k + 1}.mp4")
        _write_clip(p, 10, 60 * (k + 1))
        short.append(p)
    rec = {"id": 10, "task_type": "toy", "question": "What happens?",
           "options": ["A. A man opens a door", "B. A car stops at a light"],
           "answer": "A"}
    rec.update({f"video_{k + 1}": os.path.basename(p) for k, p in enumerate(short)})
    m = SegmentSelectMethod(object(), name="segment_select_viclip_auto",
                            dedup_tau=1.0, seg_scorer="viclip", query="auto",
                            seg_select="global", seg_floor=0, budget=96,
                            segment_seconds=8)
    content, yn, gold, fa = m._prepare(rec, d)
    assert [pv["n_segments"] for pv in fa["per_video_decode"]] == [1, 1]
    assert fa["segments_keep"] == 12 and fa["segments_kept_total"] == 2
    assert fa["selection_noop"] is True and fa["n_selected"] == 16


def test_prepare_count_partition_still_holds_full_frames(clips, monkeypatch):
    d, paths = clips
    import bench.methods.viclip_scorer as vs
    monkeypatch.setattr(SegmentSelectMethod, "_viclip_segment_scores", _fake_scores)
    monkeypatch.setattr(vs, "viclip_text_overflow", lambda q, device=None: 0)
    rec = {"id": 8, "task_type": "toy", "question": "What happens?",
           "options": ["A. A man opens a door", "B. A car stops at a light"],
           "answer": "A"}
    rec.update({f"video_{k + 1}": os.path.basename(p) for k, p in enumerate(paths)})
    m = SegmentSelectMethod(object(), name="segment_select_viclip_auto",
                            dedup_tau=1.0, seg_scorer="viclip", query="auto",
                            seg_select="global", seg_floor=0, budget=96)
    content, yn, gold, fa = m._prepare(rec, d)
    assert fa["segment_seconds"] is None and fa["segments_per_video"] == 8
    assert fa["selection_on_thumbnails"] is False and fa["full_decode_dropped"] is None
    assert [pv["n_segments"] for pv in fa["per_video_decode"]] == [8, 8, 8, 8]
    assert "segment_frames" not in fa["per_video_decode"][0]
    assert fa["n_selected"] == 96 and "up to 8 equal time segments" in content[0]["text"]
