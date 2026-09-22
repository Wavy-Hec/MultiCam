#!/usr/bin/env python3
"""Did the segment selector keep the moments the question is about?

The ladder scores the selection arms by the model's final answer, which mixes
the selector's aim with the model's reading of what it was handed. This is the
selector's own accuracy, measured against the CrossView release annotations and
with no GPU: every question in the two CrossView pools carries annotated
evidence moments (event windows for MEVA, take-clock instants for Ego-Exo4D),
and every selection row stamps which segments it kept and which frame times it
actually sent. Joining the two says, per question type and budget, how often
the arm kept every annotated moment, how often a random selector of the same
shape would have, and how often a frame actually reached the model near the
moment.

MVU-Eval is skipped: its records carry no event annotations at all (the release
ships question/options/answer only), so there is nothing to score a selector
against there.

Metrics, per (dataset, arm, budget) and per question type:

  seg_cov_all      % of questions where EVERY annotated event is covered by a
                   kept segment. MEVA: the event window [start_sec, end_sec]
                   must intersect a kept segment ON THE CAMERA the release
                   annotated it on. Ego-Exo4D: the cameras are frame-aligned on
                   one take clock, so the instant need only fall inside a kept
                   segment on at least one delivered camera - i.e. a UNION over
                   the delivered cameras.
  seg_cov_any      the same with >= 1 event covered
  mean_frac_cov    mean over questions of covered events / annotated events
  random_seg_cov   seg_cov_all under a random selector that draws, INDEPENDENTLY
                   PER CAMERA, a uniform subset of the SAME size as that row's
                   kept set for that camera (Monte Carlo, rng seed 0, N_DRAWS
                   per question). Read it as a keep-count-matched reference, not
                   as "the number seg_cov_all has to beat": where coverage is a
                   union over cameras (Ego-Exo4D, and the MEVA camera-agnostic
                   variant) independent draws spread over the segment grid while
                   both real selectors concentrate on the same segments across
                   cameras, so the independent draw wins the union metric by
                   diversification alone. Two controls for that are reported
                   alongside it:
  shift_seg_cov_all seg_cov_all under a null that keeps each row's ACTUAL kept
                   pattern and its cross-camera overlap, circularly shifting
                   every camera by one shared random offset (exact: averaged
                   over all S offsets). Same concentration, no targeting.
  cam_event_cov    coverage scored per CAMERA-EVENT pair instead of by union:
                   covered candidate (event, delivered camera) pairs / candidate
                   pairs, with random_cam_event_cov its exact keep-count-matched
                   chance, mean of 1 - C(S-h, k)/C(S, k) over the same pairs
                   (h = segments of that camera intersecting the event). This is
                   the targeting comparison; it is unaffected by how the picks
                   correlate across cameras.
  frame_prox_all   % of questions where every event has a frame the model
                   actually saw within PAD_S of its window (the selection rows
                   stamp selected_times_s; the native-uniform arm stamps no
                   times and its grid is reconstructed, see below).

What counts as an "annotated event": MEVA temporal and event ordering carry real
[start, end] windows; MEVA SPATIAL carries no window in the headline definition -
the event is the single closest-approach INSTANT verification.closest_frame / 30
fps, so its segment is the one containing that moment (the entity presence window
debug_info.entity_*.timestamp is a third reading and is not scored here; the
overlap window debug_info.overlap_frames is, as spatial_overlap_variant).
Ego-Exo4D events are instants on the take clock.

Segment geometry is the harness's own (bench/methods/segment_select.py): a clip
of n frames split into S segments has bounds[s] = round(s*n/S), so segment sid
spans seconds [bounds[sid]/fps, bounds[sid+1]/fps).

The native-uniform arm stamps only {total_frames, per_view}, so its frame times
are reconstructed from the sampler it actually runs through: cvbench_native
sets nframes per video item and InternVL3Backend.load_video falls through to
backends/internvl.py get_index with bound=None, i.e. start_idx 0,
end_idx = n_total - 1, seg_size = end_idx / nframes and
idx_j = int(seg_size/2 + round(seg_size*j)) clamped to [0, n_total-1]. n_total
and fps come from the same id's selection row at the same budget
(frame_alloc.per_video_decode), which decodes the same resolved file. That arm
has no kept segments, so its seg_cov / random entries are null by construction.

Usage (cvbench env, or plain python3 - numpy only):
  python3 analysis/selection_event_coverage.py
  python3 analysis/selection_event_coverage.py --json analysis/records/selection_coverage.json
  python3 analysis/selection_event_coverage.py --draws 2000
"""
import argparse
import glob
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
# canonical stems/tags/budgets, so this never drifts from the ladder
from split_ladder_by_query import DATASETS, BUDGETS, RES  # noqa: E402

GENERATED = "2026-09-17"
OUT_JSON = os.path.join(HERE, "records", "selection_coverage.json")
RELEASE_ANN = os.path.join(REPO, "crossview-release-annotations", "crossview-release",
                           "annotations", "multi-cam-dataset")
SUBSET_DIR = HERE

# the two pools with event annotations; MVU-Eval has none (see the docstring)
POOLS = {
    "CrossView-EgoExo": {"release": "ego-exo4d", "subset": "crossview_egoexo500.json"},
    "CrossView-MEVA": {"release": "meva", "subset": "crossview_meva1033_subset.json"},
}
# native uniform carries no kept segments; it is here only for frame_prox
ARMS = ("fs", "sg", "sgva")
SELECTION_ARMS = ("sg", "sgva")
ARM_METHOD = {"fs": "cvbench_native", "sg": "segment_select_siglip",
              "sgva": "segment_select_viclip_opt"}
ARM_LABEL = {"fs": "native uniform", "sg": "SigLIP top-4 · question",
             "sgva": "ViCLIP auto-K · options"}

PAD_S = 3.0          # render_demo.pick_thumb_idx's convention
N_DRAWS = 2000       # Monte Carlo draws per question for the random selector
RNG_SEED = 0
MEVA_SPATIAL_FPS = 30.0   # the release's own frame rate for closest_frame
ORDERING_FALLBACK_END_S = 2.0   # ordered_events carry no end; render_demo's rule

CAM_RE = re.compile(r"\.(G\d+)\.")          # MEVA camera token in a media path
TS_RE = re.compile(r"([0-9.]+)\s*-\s*([0-9.]+)\s*s")
FRAME_RANGE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")

NOTES = []


def note(msg):
    if msg not in NOTES:
        NOTES.append(msg)


# --------------------------------------------------------------------------
# release annotations
# --------------------------------------------------------------------------
_ANN_CACHE = {}


def annotations(release, qtype):
    key = (release, qtype)
    if key not in _ANN_CACHE:
        path = os.path.join(RELEASE_ANN, release, f"qa_{qtype}.json")
        if not os.path.exists(path):
            note(f"release annotations missing: {path}")
            _ANN_CACHE[key] = []
        else:
            with open(path) as fh:
                _ANN_CACHE[key] = json.load(fh)
    return _ANN_CACHE[key]


def release_item(rec, release):
    """The release QA item a harness record came from: qa_<type>.json indexed by
    the integer after '#' in orig_id (same join as render_demo.release_item)."""
    qtype = rec.get("question_type")
    orig = rec.get("orig_id") or ""
    if "#" not in orig:
        note(f"{release} id {rec.get('id')}: no orig_id index")
        return None
    slot, _, idx = orig.partition("#")
    items = annotations(release, qtype)
    if not items:
        return None
    try:
        idx = int(idx)
    except ValueError:
        note(f"{release} id {rec.get('id')}: orig_id '{orig}' has no integer index")
        return None
    if not (0 <= idx < len(items)):
        note(f"{release} id {rec.get('id')}: orig_id index {idx} out of range")
        return None
    item = items[idx]
    got = ((item.get("metadata") or {}).get("slot"))
    if got and slot and got != slot:
        note(f"{release} id {rec.get('id')}: orig_id slot '{slot}' != annotation slot '{got}'")
    return item


def _dbg_end(dbg):
    """End second parsed out of a debug_info entry's "a-b s" timestamp."""
    if not isinstance(dbg, dict):
        return None
    m = TS_RE.search(str(dbg.get("timestamp") or ""))
    return float(m.group(2)) if m else None


def egoexo_events(item):
    """[{camera: None, start_sec, end_sec, end_estimated}] for one Ego-Exo4D
    item. Every annotated moment is an INSTANT on the take clock that all the
    frame-aligned cameras share, so it carries no camera and no end: temporal
    annotates the target plus each grounding event, event ordering annotates
    every ordered event."""
    md = item.get("metadata") or {}
    out = []
    if isinstance(md.get("ordered_events"), list):
        for i, ev in enumerate(md["ordered_events"]):
            t = ev.get("start_timestamp")
            if t is None:
                continue
            out.append({"label": f"#{i + 1}", "camera": None, "start_sec": float(t),
                        "end_sec": float(t), "end_estimated": False,
                        "description": ev.get("activity") or ""})
    else:
        tgt = md.get("target") or {}
        if tgt.get("start_timestamp") is not None:
            out.append({"label": "target", "camera": None,
                        "start_sec": float(tgt["start_timestamp"]),
                        "end_sec": float(tgt["start_timestamp"]), "end_estimated": False,
                        "description": tgt.get("activity") or ""})
        for i, g in enumerate(md.get("grounding") or []):
            if g.get("start_timestamp") is None:
                continue
            out.append({"label": f"grounding#{i + 1}", "camera": None,
                        "start_sec": float(g["start_timestamp"]),
                        "end_sec": float(g["start_timestamp"]), "end_estimated": False,
                        "description": g.get("activity") or ""})
    return out


def meva_events(item, qtype, variant="default"):
    """[{camera, start_sec, end_sec, end_estimated}] for one MEVA item, each
    window clip-relative to the camera the release annotated it on.

    temporal        verification.event_a / event_b, both with real ends
    event_ordering  verification.ordered_events[], whose end comes from
                    debug_info.events[i].timestamp when that entry's camera
                    matches and is estimated as start + 2 s otherwise
    spatial         the closest-approach instant closest_frame / 30 fps on the
                    entity's camera (variant "default"), or the overlap window
                    debug_info.overlap_frames / 30 fps (variant "overlap")
    """
    md = item.get("metadata") or {}
    ver = md.get("verification") or {}
    dbg = md.get("debug_info") or {}
    out = []

    def mk(ev, label, dbg_ev):
        if not isinstance(ev, dict) or ev.get("camera") is None:
            return None
        start = ev.get("start_sec")
        if start is None:
            return None
        end, est = ev.get("end_sec"), False
        if end is None:
            end = _dbg_end(dbg_ev)
        if end is None:
            end, est = float(start) + ORDERING_FALLBACK_END_S, True
        return {"label": label, "camera": str(ev["camera"]), "start_sec": float(start),
                "end_sec": float(end), "end_estimated": est,
                "description": ev.get("description") or ev.get("activity") or ""}

    if qtype == "spatial":
        if variant == "overlap":
            m = FRAME_RANGE_RE.search(str(dbg.get("overlap_frames") or ""))
            if not m:
                return []
            lo, hi = int(m.group(1)) / MEVA_SPATIAL_FPS, int(m.group(2)) / MEVA_SPATIAL_FPS
        else:
            cf = ver.get("closest_frame")
            if cf is None:
                return []
            lo = hi = float(cf) / MEVA_SPATIAL_FPS
        seen = set()
        for key in ("entity_a", "entity_b"):
            ent = dbg.get(key) or {}
            cam = ent.get("camera")
            if cam is None or cam in seen:
                continue
            seen.add(cam)
            out.append({"label": key, "camera": str(cam), "start_sec": lo, "end_sec": hi,
                        "end_estimated": False, "description": ent.get("description") or ""})
        return out

    if isinstance(ver.get("ordered_events"), list):
        dbg_events = dbg.get("events") if isinstance(dbg.get("events"), list) else []
        for i, ev in enumerate(ver["ordered_events"]):
            d = dbg_events[i] if i < len(dbg_events) else None
            if isinstance(d, dict) and ev.get("camera") and d.get("camera") != ev.get("camera"):
                d = None
            w = mk(ev, f"#{i + 1}", d)
            if w:
                out.append(w)
    else:
        for key, label in (("event_a", "A"), ("event_b", "B")):
            w = mk(ver.get(key), label, dbg.get(key))
            if w:
                out.append(w)
    return out


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------
def load_selection_rows(stem, tag, budget, method):
    """[{id, pass_idx, task_type, frame_alloc}] for one leg, method-filtered the
    way make_ladder_figs.compute() filters (the MVU files hold several arms;
    these do not, but the filter is free insurance)."""
    rows = []
    for path in sorted(glob.glob(os.path.join(RES, f"{stem}_{tag}{budget}_shard*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("method") != method:
                    continue
                rows.append({"id": r["id"], "pass_idx": r.get("pass_idx"),
                             "task_type": r.get("task_type"),
                             "frame_alloc": r.get("frame_alloc") or {}})
    return rows


def kept_signature(fa):
    """Hashable form of segments_kept_per_video, for the pass-invariance check."""
    kept = fa.get("segments_kept_per_video") or {}
    return tuple(sorted((str(k), tuple(sorted(v or []))) for k, v in kept.items()))


def collapse_passes(rows):
    """{id: (frame_alloc of the lowest pass, n_passes, all_passes_agree)}."""
    by_id = defaultdict(list)
    for r in rows:
        by_id[r["id"]].append(r)
    out = {}
    for i, rs in by_id.items():
        rs.sort(key=lambda r: (r["pass_idx"] if r["pass_idx"] is not None else -1))
        sigs = {kept_signature(r["frame_alloc"]) for r in rs}
        out[i] = (rs[0]["frame_alloc"], len(rs), len(sigs) == 1)
    return out


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def segment_bounds_s(n_total, n_segments, fps, segment_frames=None):
    """[(start_s, end_s)] per segment, bench/methods/segment_select.py's own
    geometry: bounds[s] = round(s * n / S), segment sid = frames
    [bounds[sid], bounds[sid+1]). A --segment-seconds row stamps
    ``segment_frames`` (its window w) and is cut [s * w for s < S] + [n]."""
    if not n_total or not n_segments or not fps:
        return []
    if segment_frames:
        b = [s * int(segment_frames) for s in range(n_segments)] + [n_total]
    else:
        b = [round(s * n_total / n_segments) for s in range(n_segments + 1)]
    return [(b[s] / fps, b[s + 1] / fps) for s in range(n_segments)]


def uniform_frame_times_s(nframes, n_total, fps):
    """The frame times the native-uniform arm actually sends for one clip:
    backends/internvl.py get_index with bound=None, then load_video's clamp."""
    if not nframes or not n_total or not fps:
        return []
    max_frame = n_total - 1
    seg = float(max_frame) / nframes
    idx = [int(0 + (seg / 2) + np.round(seg * j)) for j in range(nframes)]
    idx = [int(min(max(0, k), max_frame)) for k in idx]
    return [k / fps for k in idx]


def window_hits_segment(ev, span):
    """Closed intersection of the event window with a segment's time span; for
    an instant (start == end) this is plain containment."""
    return ev["start_sec"] <= span[1] and ev["end_sec"] >= span[0]


# --------------------------------------------------------------------------
# per-question scoring
# --------------------------------------------------------------------------
def camera_slots(rec, source):
    """{camera token: [slot keys]} and the ordered slot keys. The slot keys are
    "1".."N" over the DELIVERED videos (video_paths() drops the null slots), the
    same order frame_alloc keys use. Ego-Exo4D carries no camera in its
    annotations, so its map is empty and every slot is a candidate."""
    slots, cams = [], defaultdict(list)
    n = 0
    for i in range(1, 14):
        v = rec.get(f"video_{i}")
        if not v:
            continue
        n += 1
        key = str(n)
        slots.append(key)
        if source == "meva":
            m = CAM_RE.search(v)
            if m:
                cams[m.group(1)].append(key)
            else:
                note(f"meva id {rec.get('id')}: no camera token in {v}")
    return slots, dict(cams)


def event_slots(ev, slots, cams, source, ignore_camera=False):
    """Which delivered slots an event can be covered on."""
    if ignore_camera or source != "meva" or ev["camera"] is None:
        return slots                      # shared take clock: any camera counts
    return cams.get(ev["camera"], [])


def score_question(events, fa, slots, cams, source, rng, draws, ignore_camera=False):
    """Coverage of one question under one row's selection.

    Returns a dict; the selection-dependent fields are None for an arm that
    keeps no segments (native uniform), which only gets frame proximity."""
    kept = fa.get("segments_kept_per_video") or {}
    decode = fa.get("per_video_decode") or []
    times = fa.get("selected_times_s") or {}
    per_view = fa.get("per_view") or []

    # per-slot decode meta, keyed the way frame_alloc keys are
    meta = {}
    for j, key in enumerate(slots):
        d = decode[j] if j < len(decode) else None
        if isinstance(d, dict):
            meta[key] = d

    has_sel = bool(kept)

    # ---- kept-segment coverage -------------------------------------------
    hit = {}          # event index -> {slot: [segment ids that intersect it]}
    if has_sel:
        spans = {}
        for key, d in meta.items():
            spans[key] = segment_bounds_s(d.get("n_total"), d.get("n_segments"), d.get("fps"),
                                          d.get("segment_frames"))
        for ei, ev in enumerate(events):
            per = {}
            for key in event_slots(ev, slots, cams, source, ignore_camera):
                sp = spans.get(key) or []
                per[key] = [sid for sid, span in enumerate(sp) if window_hits_segment(ev, span)]
            hit[ei] = per
        covered = []
        for ei, ev in enumerate(events):
            ok = False
            for key, sids in hit[ei].items():
                keep = set(kept.get(key) or [])
                if keep & set(sids):
                    ok = True
                    break
            covered.append(ok)
        n_cov = int(sum(covered))
        cov_all = bool(events) and n_cov == len(events)
        frac = n_cov / len(events) if events else float("nan")
        p_rand = random_all_prob(events, hit, kept, meta, rng, draws)
        p_shift = shift_all_prob(events, hit, kept, meta)
        n_pairs, n_pairs_cov, pair_rand = camera_event_pairs(events, hit, kept, meta)
    else:
        n_cov, cov_all, frac, p_rand, p_shift = None, None, None, None, None
        n_pairs, n_pairs_cov, pair_rand = None, None, None

    # ---- frame proximity --------------------------------------------------
    if has_sel:
        sent = {k: [float(t) for t in (v or [])] for k, v in times.items()}
    else:
        sent = {}
        for j, key in enumerate(slots):
            d = meta.get(key) or {}
            nf = per_view[j] if j < len(per_view) else None
            sent[key] = uniform_frame_times_s(nf, d.get("n_total"), d.get("fps"))
    prox = []
    for ev in events:
        lo, hi = ev["start_sec"] - PAD_S, ev["end_sec"] + PAD_S
        prox.append(any(lo <= t <= hi
                        for key in event_slots(ev, slots, cams, source, ignore_camera)
                        for t in sent.get(key, [])))
    prox_all = bool(events) and all(prox)

    kept_per_cam = {k: sorted(v or []) for k, v in kept.items()} if has_sel else None
    return {"n_covered": n_cov, "covered_all": cov_all, "frac": frac,
            "p_random_all": p_rand, "p_shift_all": p_shift,
            "n_cam_events": n_pairs, "n_cam_events_covered": n_pairs_cov,
            "cam_event_random_sum": pair_rand,
            "frame_prox_all": prox_all, "n_frame_prox": int(sum(prox)),
            "kept_per_cam": kept_per_cam,
            "selection_noop": bool(fa.get("selection_noop")) if has_sel else None}


def camera_event_pairs(events, hit, kept, meta):
    """Per-CAMERA-EVENT coverage of one question, the metric that does not care
    how the picks correlate across cameras: over every candidate (event,
    delivered camera) pair, how many were covered by that camera's own kept set,
    and the exact keep-count-matched chance summed over the same pairs
    (1 - C(S-h, k)/C(S, k), h = that camera's segments intersecting the event).
    Returns (n_pairs, n_pairs_covered, sum_of_chance)."""
    n_pairs = n_cov = 0
    rand_sum = 0.0
    for ei in range(len(events)):
        for key, sids in hit[ei].items():
            d = meta.get(key) or {}
            S = d.get("n_segments") or 0
            if S <= 0:
                continue
            k = min(len(kept.get(key) or []), S)
            n_pairs += 1
            if set(kept.get(key) or []) & set(sids):
                n_cov += 1
            h = len({sid for sid in sids if 0 <= sid < S})
            if h == 0 or k == 0:
                p = 0.0
            elif S - h < k:
                p = 1.0
            else:
                p = 1.0 - math.comb(S - h, k) / math.comb(S, k)
            rand_sum += p
    return n_pairs, n_cov, rand_sum


def shift_all_prob(events, hit, kept, meta):
    """P(every event covered) under a null that keeps this row's ACTUAL kept
    pattern on every camera - its size and its shape, and so the overlap between
    cameras - and circularly shifts all of them together by one shared offset.
    Exact: the mean over all S offsets. Where random_all_prob diversifies across
    cameras (it draws each independently), this one is as concentrated as the
    selector it is standing in for, so it isolates targeting from spread."""
    if not events:
        return float("nan")
    slots = sorted({key for per in hit.values() for key in per})
    S_ref = 0
    for key in slots:
        S_ref = max(S_ref, (meta.get(key) or {}).get("n_segments") or 0)
    if S_ref <= 0:
        return float("nan")
    ok = 0
    for u in range(S_ref):
        shifted = {}
        for key in slots:
            S = (meta.get(key) or {}).get("n_segments") or 0
            if S <= 0:
                continue
            off = int(round(u * S / S_ref))
            shifted[key] = {(sid + off) % S for sid in (kept.get(key) or [])
                            if 0 <= sid < S}
        good = True
        for ei in range(len(events)):
            if not any(shifted.get(key, set()) & set(sids)
                       for key, sids in hit[ei].items()):
                good = False
                break
        if good:
            ok += 1
    return ok / S_ref


def random_all_prob(events, hit, kept, meta, rng, draws):
    """Monte Carlo P(every event covered) when each camera keeps a uniform
    random subset of the SAME size as this row's kept set for that camera.

    The draws are INDEPENDENT ACROSS CAMERAS, which matters wherever coverage is
    a union over cameras: independent draws spread over the grid, so this null
    beats a selector that concentrates on the same segments on every camera even
    when that selector is aiming better per camera. Compare against
    cam_event_cov / shift_seg_cov_all before reading a gap here as competence."""
    if not events:
        return float("nan")
    slots = sorted({key for per in hit.values() for key in per})
    masks = {}
    for key in slots:
        d = meta.get(key) or {}
        S = d.get("n_segments") or 0
        k = len(kept.get(key) or [])
        if S <= 0:
            continue
        k = min(k, S)
        if k == 0:
            masks[key] = np.zeros((draws, S), dtype=bool)
            continue
        if k == S:
            masks[key] = np.ones((draws, S), dtype=bool)
            continue
        order = np.argpartition(rng.random((draws, S)), k - 1, axis=1)[:, :k]
        m = np.zeros((draws, S), dtype=bool)
        np.put_along_axis(m, order, True, axis=1)
        masks[key] = m
    ok = np.ones(draws, dtype=bool)
    for ei in range(len(events)):
        ev_ok = np.zeros(draws, dtype=bool)
        for key, sids in hit[ei].items():
            m = masks.get(key)
            if m is None or not sids:
                continue
            ev_ok |= m[:, sids].any(axis=1)
        ok &= ev_ok
    return float(ok.mean())


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------
def pct(v):
    return None if v is None else round(100 * float(v), 2)


def aggregate(entries):
    """Pooled cell from a list of per-question dicts."""
    n = len(entries)
    if not n:
        return None
    sel = [e for e in entries if e["covered_all"] is not None]
    n_pairs = sum(e["n_cam_events"] or 0 for e in sel)
    out = {"n": n,
           "seg_cov_all": pct(np.mean([e["covered_all"] for e in sel])) if sel else None,
           "seg_cov_any": pct(np.mean([e["n_covered"] > 0 for e in sel])) if sel else None,
           "mean_frac_covered": pct(np.mean([e["n_covered"] / e["n_events"] for e in sel])) if sel else None,
           "random_seg_cov_all": pct(np.mean([e["p_random_all"] for e in sel])) if sel else None,
           "shift_seg_cov_all": pct(np.mean([e["p_shift_all"] for e in sel])) if sel else None,
           "cam_event_cov": pct(sum(e["n_cam_events_covered"] for e in sel) / n_pairs) if n_pairs else None,
           "random_cam_event_cov": pct(sum(e["cam_event_random_sum"] for e in sel) / n_pairs) if n_pairs else None,
           "n_cam_events": int(n_pairs) if sel else None,
           "n_selection_noop": int(sum(1 for e in sel if e.get("selection_noop"))) if sel else None,
           "frame_prox_all": pct(np.mean([e["frame_prox_all"] for e in entries])),
           "mean_frac_frame_prox": pct(np.mean([e["n_frame_prox"] / e["n_events"] for e in entries])),
           "n_events_total": int(sum(e["n_events"] for e in entries)),
           "n_events_end_estimated": int(sum(e["n_events_end_estimated"] for e in entries))}
    return out


def build_cell(entries, n_excluded_fallback, n_no_events):
    pooled = aggregate(entries) or {}
    pooled["n_excluded_fallback"] = n_excluded_fallback
    pooled["n_no_events"] = n_no_events
    per_task = {}
    by_task = defaultdict(list)
    for e in entries:
        by_task[e["task_type"]].append(e)
    for t, es in sorted(by_task.items()):
        # n_excluded_fallback / n_no_events are counted before a dropped row is
        # attributed to a task, so they exist pooled only and are not faked here
        per_task[t] = aggregate(es)
    cell = {"pooled": pooled, "per_task": per_task}
    # the ViCLIP auto-K arm degenerates to keep-everything on some records; those
    # enter the cell at cov_all=100 / p_random=100 by construction, so the cell is
    # reported a second time without them whenever there are any
    kept = [e for e in entries if not e.get("selection_noop")]
    if pooled.get("n_selection_noop"):
        excl = aggregate(kept) or {}
        excl["n_excluded_selection_noop"] = int(pooled["n_selection_noop"])
        cell["pooled_excl_selection_noop"] = excl
        cell["per_task_excl_selection_noop"] = {
            t: aggregate(es) for t, es in sorted(
                ((t, [e for e in es if not e.get("selection_noop")])
                 for t, es in by_task.items())) if es}
    return cell


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=OUT_JSON, help="output JSON path")
    ap.add_argument("--draws", type=int, default=N_DRAWS,
                    help="Monte Carlo draws per question for the random selector")
    args = ap.parse_args()

    summary, per_question, pass_inv = {}, {}, {}
    spatial_overlap, cam_agnostic = {}, {}

    for ds, cfg in POOLS.items():
        subset_name, stem, tags = DATASETS[ds]
        with open(os.path.join(SUBSET_DIR, subset_name)) as fh:
            recs = {r["id"]: r for r in json.load(fh)}
        release = cfg["release"]
        source = "meva" if release == "meva" else "ego-exo4d"

        # events per record, once (they do not depend on arm or budget)
        ev_cache, slot_cache = {}, {}
        ov_cache = {}
        for rid, rec in recs.items():
            item = release_item(rec, release)
            if source == "meva":
                ev = meva_events(item, rec.get("question_type")) if item else []
                ov_cache[rid] = (meva_events(item, rec.get("question_type"), "overlap")
                                 if item and rec.get("question_type") == "spatial" else None)
            else:
                ev = egoexo_events(item) if item else []
            ev_cache[rid] = ev
            slot_cache[rid] = camera_slots(rec, source)

        summary[ds], per_question[ds], pass_inv[ds] = {}, {}, {}
        spatial_overlap[ds], cam_agnostic[ds] = {}, {}
        for arm in ARMS:
            tag = tags[arm]
            summary[ds][arm], per_question[ds][arm], pass_inv[ds][arm] = {}, {}, {}
            spatial_overlap[ds][arm], cam_agnostic[ds][arm] = {}, {}
            for budget in BUDGETS:
                rows = load_selection_rows(stem, tag, budget, ARM_METHOD[arm])
                if not rows:
                    note(f"{ds} {arm}{budget}: no rows on disk")
                    continue
                by_id = collapse_passes(rows)
                n_pass_mismatch = sum(1 for _, (_, _, ok) in by_id.items() if not ok)
                if arm in SELECTION_ARMS:
                    # the native-uniform arm stamps no kept segments, so the
                    # signature would be empty for every pass and the check
                    # would be vacuously green: it is not reported for it
                    pass_inv[ds][arm][str(budget)] = {
                        "n_ids": len(by_id),
                        "n_passes_per_id": sorted({npass for _, npass, _ in by_id.values()}),
                        "n_ids_kept_differs_across_passes": n_pass_mismatch}
                if n_pass_mismatch and arm in SELECTION_ARMS:
                    note(f"{ds} {arm}{budget}: {n_pass_mismatch} ids whose kept segments "
                         "differ across passes; pass 0 used anyway (see pass_invariance)")

                # the native-uniform arm needs the selection leg's decode meta
                decode_from = None
                if arm == "fs":
                    sg_rows = load_selection_rows(stem, tags["sg"], budget,
                                                  ARM_METHOD["sg"])
                    decode_from = {i: fa.get("per_video_decode")
                                   for i, (fa, _, _) in collapse_passes(sg_rows).items()}

                rng = np.random.default_rng(RNG_SEED)
                entries, ov_entries, ca_entries = [], [], []
                n_fb, n_noev = 0, 0
                for rid, (fa, _, _) in sorted(by_id.items()):
                    if fa.get("selection_fallback") is not None:
                        n_fb += 1
                        continue
                    events = ev_cache.get(rid) or []
                    if not events:
                        n_noev += 1
                        continue
                    slots, cams = slot_cache[rid]
                    if arm == "fs":
                        fa = dict(fa)
                        fa["per_video_decode"] = (decode_from or {}).get(rid) or []
                        if not fa["per_video_decode"]:
                            note(f"{ds} fs{budget} id {rid}: no selection row to take "
                                 "n_total/fps from; frame_prox skipped")
                            continue
                    rec = recs[rid]
                    sc = score_question(events, fa, slots, cams, source, rng, args.draws)
                    entries.append(dict(
                        sc, id=rid, task_type=rec.get("task_type"),
                        n_events=len(events),
                        n_events_end_estimated=sum(1 for e in events if e["end_estimated"])))
                    if source == "meva":
                        # the same questions with the camera constraint dropped
                        # (an event counts as covered if ANY delivered camera
                        # kept a segment spanning its window) - reported only as
                        # a diagnostic, see the notes
                        sca = score_question(events, fa, slots, cams, source, rng,
                                             args.draws, ignore_camera=True)
                        ca_entries.append(dict(
                            sca, id=rid, task_type=rec.get("task_type"),
                            n_events=len(events), kept_per_cam=None,
                            n_events_end_estimated=0))
                    ov = ov_cache.get(rid)
                    if ov:
                        sco = score_question(ov, fa, slots, cams, source, rng, args.draws)
                        ov_entries.append(dict(
                            sco, id=rid, task_type=rec.get("task_type"),
                            n_events=len(ov), kept_per_cam=None,
                            n_events_end_estimated=0))

                summary[ds][arm][str(budget)] = build_cell(entries, n_fb, n_noev)
                per_question[ds][arm][str(budget)] = [
                    {k: e[k] for k in ("id", "task_type", "n_events", "n_covered",
                                       "covered_all", "p_random_all", "p_shift_all",
                                       "n_cam_events", "n_cam_events_covered",
                                       "frame_prox_all", "selection_noop",
                                       "kept_per_cam")} for e in entries]
                if ov_entries:
                    spatial_overlap[ds][arm][str(budget)] = aggregate(ov_entries)
                if ca_entries:
                    cam_agnostic[ds][arm][str(budget)] = build_cell(ca_entries, n_fb, n_noev)
                print(f"  .. {ds} {arm}{budget}: {len(entries)} questions", file=sys.stderr)

    if not any(spatial_overlap[d][a] for d in spatial_overlap for a in spatial_overlap[d]):
        spatial_overlap = {}
    cam_agnostic = {d: v for d, v in cam_agnostic.items()
                    if any(v[a] for a in v)}

    note("MVU-Eval is absent by design: its release ships no event annotations, so "
         "there is nothing to score a selector against.")
    note(f"Event windows are intersected with kept segments closed on both ends; "
         f"frame proximity uses a +/-{PAD_S:g}s pad (render_demo.pick_thumb_idx's).")
    note("The closed intersection is deliberate - an event abutting a kept segment "
         "counts for it - and so differs from the harness's own half-open membership "
         "[bounds[sid], bounds[sid+1]). It can credit a boundary event to both "
         "adjacent segments, which needs exact float equality with bounds[s]/fps and "
         "never changes a covered/not-covered verdict on its own.")
    note("random_seg_cov_all draws each camera INDEPENDENTLY while both selectors pick "
         "the same segments on every camera (Ego-Exo4D sg@96 keeps 0.92 of the 8 "
         "segments in union against 0.98 for a size-matched independent draw). Where "
         "coverage is a union over cameras that hands the random selector a "
         "diversification edge it did not earn by aiming, and it can invert the "
         "arm-vs-random sign: read cam_event_cov against random_cam_event_cov (per "
         "camera-event, no union) and seg_cov_all against shift_seg_cov_all "
         "(concentration-matched) before calling a selector better or worse than "
         "chance.")
    note("A spatial event is the closest-approach INSTANT verification.closest_frame / "
         "30 fps, not a window: the spatial headline is scored against a zero-width "
         "moment while temporal and event ordering are scored against real windows. "
         "See definitions.annotated_event and spatial_overlap_variant.")
    note("Kept segments do not depend on the frame budget: both selection arms use "
         "8 segments per clip and a keep count set by the pool, so 32/64/96 differ "
         "only in how many frames come out of the SAME kept segments. seg_cov_all "
         "and random_seg_cov_all are therefore identical across budgets by "
         "construction; only frame_prox_all moves.")
    note("fps for both the segment spans and the reconstructed uniform grid comes from "
         "frame_alloc.per_video_decode, which stamps round(fps, 2); at 30 fps this is "
         "exact, and at 29.97 the worst-case drift over a five-minute clip is ~0.003 s "
         "against a 3 s pad.")
    note("The MEVA headline numbers hold the selector to the camera the release "
         "annotated each event on. Dropping that constraint (see "
         "meva_camera_agnostic_variant) raises seg_cov_all by 30-50 points, into the "
         "same high-80s-to-high-90s regime an earlier hand computation of this pool "
         "reported; that computation is not on disk in this repo, so the agreement is "
         "a regime match and not a reproduction. Its random_seg_cov_all rises with it, "
         "which is most of the jump.")
    note("No MEVA ordered_event needed the start + 2 s end fallback: every one of "
         "them matched a debug_info.events entry on the same camera and took its "
         "real end (n_events_end_estimated is 0 in every cell).")
    note("MEVA spatial has one annotated moment per question: entity_a and entity_b "
         "sit on the same camera in all 431 records, so the two-event case the "
         "definition allows for never fires.")

    payload = {
        "generated": GENERATED,
        "definitions": {
            "annotated_event": "MEVA temporal / event ordering: the release's real "
                               "[start_sec, end_sec] window. MEVA SPATIAL: a single "
                               "INSTANT, verification.closest_frame / 30 fps - not the "
                               "entity presence window debug_info.entity_*.timestamp "
                               "(a third reading, scored nowhere here) and not "
                               "debug_info.overlap_frames (scored as "
                               "spatial_overlap_variant). Ego-Exo4D: an instant on the "
                               "take clock (target + grounding, or each ordered event).",
            "seg_cov_all": "percent of questions where EVERY annotated event is covered "
                           "by a kept segment (MEVA: on the camera the release annotated "
                           "it on; Ego-Exo4D: on any delivered camera, shared take clock, "
                           "i.e. a union over cameras)",
            "seg_cov_any": "percent of questions where at least one annotated event is covered",
            "mean_frac_covered": "mean over questions of (covered events / annotated events), percent",
            "random_seg_cov_all": "seg_cov_all under a random selector that keeps, per "
                                  "camera, a uniform random subset of the same size as "
                                  f"this row's kept set ({N_DRAWS} Monte Carlo draws per "
                                  "question, numpy default_rng(0)), averaged over "
                                  "questions. THE DRAWS ARE INDEPENDENT ACROSS CAMERAS "
                                  "while both real selectors concentrate on the same "
                                  "segments on every camera, so wherever coverage is a "
                                  "union over cameras (Ego-Exo4D; the MEVA "
                                  "camera-agnostic variant) this null wins by "
                                  "diversification and is NOT a bar the selector has to "
                                  "clear - use cam_event_cov or shift_seg_cov_all to ask "
                                  "whether the selector aims well",
            "shift_seg_cov_all": "seg_cov_all under a null that keeps each row's actual "
                                 "kept pattern on every camera, and so its cross-camera "
                                 "overlap, and circularly shifts all cameras together by "
                                 "one shared offset; exact, averaged over all S offsets. "
                                 "Matched to the selector in size AND concentration, so "
                                 "the gap to seg_cov_all is targeting alone",
            "cam_event_cov": "coverage scored per camera-event pair: covered candidate "
                             "(event, delivered camera) pairs / candidate pairs. Not a "
                             "union, so it is unaffected by how the picks correlate "
                             "across cameras; on MEVA, where each event is pinned to one "
                             "camera, it is close to the per-event coverage",
            "random_cam_event_cov": "cam_event_cov's exact keep-count-matched chance: the "
                                    "mean of 1 - C(S-h, k)/C(S, k) over the same candidate "
                                    "pairs (S segments, k kept on that camera, h segments "
                                    "of that camera intersecting the event)",
            "n_cam_events": "candidate (event, delivered camera) pairs behind cam_event_cov",
            "n_selection_noop": "questions in the cell whose row is flagged "
                                "frame_alloc.selection_noop - the arm kept every segment "
                                "on every camera, so seg_cov_all and random_seg_cov_all "
                                "are both 100 there by construction. They are counted, "
                                "not dropped; pooled_excl_selection_noop / "
                                "per_task_excl_selection_noop re-report the cell without "
                                "them",
            "frame_prox_all": "percent of questions where every annotated event has a "
                              f"frame the model actually saw within {PAD_S:g}s of its "
                              "window (selection arms: frame_alloc.selected_times_s; "
                              "native uniform: the reconstructed get_index grid)",
            "mean_frac_frame_prox": "mean over questions of (events with a frame within "
                                    "the pad / annotated events), percent",
            "n_events_end_estimated": "annotated events whose end second was not in the "
                                      "release and was taken as start + 2 s (MEVA event "
                                      "ordering only)",
            "n_excluded_fallback": "rows dropped because frame_alloc.selection_fallback "
                                   "was not null (pooled only: a dropped row is counted "
                                   "before it is attributed to a question type, so the "
                                   "per_task cells carry no exclusion counts)",
            "n_no_events": "questions dropped because the release item carried no "
                           "annotated event (pooled only, as above)",
            "meva_camera_agnostic_variant": "MEVA re-scored with the camera "
                                            "constraint dropped: an event counts as "
                                            "covered if ANY delivered camera kept a "
                                            "segment spanning its window. Not the "
                                            "headline definition - a kept segment on a "
                                            "camera the event was not annotated on is "
                                            "not evidence for it. Being a union, it "
                                            "carries the same caveat as Ego-Exo4D: its "
                                            "random_seg_cov_all jumps too.",
            "spatial_overlap_variant": "MEVA spatial re-scored against "
                                       "debug_info.overlap_frames / 30 fps instead of the "
                                       "closest-approach instant",
        },
        "config": {"pad_s": PAD_S, "draws": args.draws, "rng_seed": RNG_SEED,
                   "arms": {a: ARM_METHOD[a] for a in ARMS},
                   "tags": {ds: DATASETS[ds][2] for ds in POOLS},
                   "meva_spatial_fps": MEVA_SPATIAL_FPS},
        "summary": summary,
        "spatial_overlap_variant": spatial_overlap,
        "meva_camera_agnostic_variant": cam_agnostic,
        "per_question": per_question,
        "pass_invariance": pass_inv,
        "notes": NOTES,
    }
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w") as fh:
        json.dump(payload, fh, indent=1)

    print_table(summary, spatial_overlap, cam_agnostic, pass_inv)
    print(f"\nwrote {args.json}")


def fmt(v):
    return "  -  " if v is None else f"{v:5.1f}"


def print_table(summary, spatial_overlap, cam_agnostic, pass_inv):
    for ds in summary:
        print(f"\n=== {ds} ===")
        print(f"{'arm':<26} {'bud':>4} {'n':>5} "
              f"{'cov_all':>8} {'rand':>6} {'shift':>6} {'camev':>6} {'camrnd':>7} "
              f"{'cov_any':>8} {'frac':>6} {'frameprox':>10} {'noop':>5}")
        for arm in ARMS:
            for budget in BUDGETS:
                cell = summary[ds].get(arm, {}).get(str(budget))
                if not cell:
                    continue
                p = cell["pooled"]
                noop = p.get("n_selection_noop")
                print(f"{ARM_LABEL[arm]:<26} {budget:>4} {p['n']:>5} "
                      f"{fmt(p['seg_cov_all']):>8} {fmt(p['random_seg_cov_all']):>6} "
                      f"{fmt(p.get('shift_seg_cov_all')):>6} "
                      f"{fmt(p.get('cam_event_cov')):>6} {fmt(p.get('random_cam_event_cov')):>7} "
                      f"{fmt(p['seg_cov_any']):>8} {fmt(p['mean_frac_covered']):>6} "
                      f"{fmt(p['frame_prox_all']):>10} "
                      f"{'  -  ' if noop is None else f'{noop:>5}'}")
                ex = cell.get("pooled_excl_selection_noop")
                if ex:
                    print(f"{'  (excl selection_noop)':<26} {budget:>4} {ex['n']:>5} "
                          f"{fmt(ex['seg_cov_all']):>8} {fmt(ex['random_seg_cov_all']):>6} "
                          f"{fmt(ex.get('shift_seg_cov_all')):>6} "
                          f"{fmt(ex.get('cam_event_cov')):>6} "
                          f"{fmt(ex.get('random_cam_event_cov')):>7} "
                          f"{fmt(ex['seg_cov_any']):>8} {fmt(ex['mean_frac_covered']):>6} "
                          f"{fmt(ex['frame_prox_all']):>10}")
        print(f"\n  per task @96")
        for arm in ARMS:
            cell = summary[ds].get(arm, {}).get("96")
            if not cell:
                continue
            for t, c in cell["per_task"].items():
                short = t.replace("CrossView-", "").replace("MEVA-", "").replace("EgoExo4D-", "")
                print(f"  {ARM_LABEL[arm]:<26} {short:<16} n={c['n']:>4} "
                      f"cov_all={fmt(c['seg_cov_all'])} rand={fmt(c['random_seg_cov_all'])} "
                      f"shift={fmt(c.get('shift_seg_cov_all'))} "
                      f"camev={fmt(c.get('cam_event_cov'))}/{fmt(c.get('random_cam_event_cov'))} "
                      f"frac={fmt(c['mean_frac_covered'])} prox={fmt(c['frame_prox_all'])}")
            ca = cam_agnostic.get(ds, {}).get(arm, {}).get("96")
            if ca:
                for t, c in ca["per_task"].items():
                    short = t.replace("CrossView-", "").replace("MEVA-", "")
                    print(f"  {ARM_LABEL[arm]:<26} {short + '[any cam]':<16} n={c['n']:>4} "
                          f"cov_all={fmt(c['seg_cov_all'])} rand={fmt(c['random_seg_cov_all'])} "
                          f"shift={fmt(c.get('shift_seg_cov_all'))} "
                          f"camev={fmt(c.get('cam_event_cov'))}/{fmt(c.get('random_cam_event_cov'))} "
                          f"frac={fmt(c['mean_frac_covered'])} prox={fmt(c['frame_prox_all'])}")
            ov = spatial_overlap.get(ds, {}).get(arm, {}).get("96")
            if ov:
                print(f"  {ARM_LABEL[arm]:<26} {'Spatial[overlap]':<16} n={ov['n']:>4} "
                      f"cov_all={fmt(ov['seg_cov_all'])} rand={fmt(ov['random_seg_cov_all'])} "
                      f"shift={fmt(ov.get('shift_seg_cov_all'))} "
                      f"camev={fmt(ov.get('cam_event_cov'))}/{fmt(ov.get('random_cam_event_cov'))} "
                      f"frac={fmt(ov['mean_frac_covered'])} prox={fmt(ov['frame_prox_all'])}")
    print("\n=== pass invariance (kept segments identical across the 4 passes) ===")
    for ds in pass_inv:
        for arm in ARMS:
            for budget in BUDGETS:
                pi = pass_inv[ds].get(arm, {}).get(str(budget))
                if not pi:
                    continue
                print(f"  {ds:<18} {arm:<5} {budget:>3}  ids={pi['n_ids']:>5} "
                      f"passes={pi['n_passes_per_id']} mismatches="
                      f"{pi['n_ids_kept_differs_across_passes']}")


if __name__ == "__main__":
    main()
