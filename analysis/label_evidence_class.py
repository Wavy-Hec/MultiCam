#!/usr/bin/env python3
"""Stamp every MEVA benchmark question with its evidence-locality class.

The five classes (where the answer's evidence lives):
  C1  one timestamp in one camera        C2  a time window in one camera
  C3  one timestamp across m cameras     C4  time windows across m cameras
  C5  time windows across ALL cameras

Assignment is a pure function of release metadata — (question_type,
requires_cameras, verification) — no text parsing, no judgment. The benchmark
records dropped that metadata at conversion, so this script joins each record
back to its release item via (question_type, orig_id-index) and REFUSES to
label on a failed join or a question-text mismatch: a silent misjoin would
mislabel quietly, which is worse than stopping.

Rules (v1, 2026-08-31):
  spatial        -> C2  (single required camera; the distractors — "cross
                         paths", "stay near" — quantify over the window, so
                         one frame cannot falsify them)
  temporal       -> C4  (two interval events on two distinct cameras; asserted)
  event_ordering -> C4  (3-4 events over >1 distinct camera; asserted, and a
                         hypothetical single-camera item degrades to C2)
  counting       -> C5  ("Across all camera views..." — the negative evidence
                         lives in every feed; the positive-evidence reading
                         (C2/C4 by requires_cameras) is recorded per item)
  summarization  -> C5
  camera         -> AMBIGUOUS: positive evidence is one moment in one camera
                    (C1) but verification needs every feed (C5); both readings
                    are recorded and the field stays 'pending-ruling'

Two definitional rulings are pending with the mentor and change nothing above:
whether C1/C3 mean literal frames (empty here: median event 3.13 s) or single
timestamps, and which reading the camera questions take.

Outputs (regenerable, untracked like everything under analysis/records/):
  analysis/records/evidence_labels.json
Run from the repo root: python3 analysis/label_evidence_class.py
"""
import json
import os
from collections import Counter

RELEASE = os.path.join("crossview-release-annotations", "crossview-release",
                       "annotations", "multi-cam-dataset", "meva")
SUBSETS = {"meva1033": "analysis/crossview_meva1033_subset.json",
           "cap13": "analysis/crossview_meva_cap13.json"}
OUT = "analysis/records/evidence_labels.json"

QA_FILES = {"temporal": "qa_temporal.json",
            "event_ordering": "qa_event_ordering.json",
            "spatial": "qa_spatial.json",
            "counting": "qa_counting.json",
            "camera": "qa_best_camera.json",
            "summarization": "qa_summarization.json"}


def load_release():
    rel = {}
    for qt, fname in QA_FILES.items():
        with open(os.path.join(RELEASE, fname)) as fh:
            rel[qt] = json.load(fh)
    return rel


def event_spans(qt, item):
    """Per-event (start_s, end_s|None) list from the verification block."""
    v = (item.get("metadata") or {}).get("verification") or {}
    if qt == "temporal":
        return [(e.get("start_sec"), e.get("end_sec"))
                for e in (v.get("event_a"), v.get("event_b")) if e]
    if qt == "event_ordering":
        return [(e.get("start_sec"), None) for e in v.get("ordered_events") or []]
    if qt == "counting":
        return [(k.get("start_sec"), k.get("end_sec"))
                for k in v.get("key_frames") or []]
    if qt == "camera":
        t = v.get("entrance_time_sec")
        return [(t, t)] if t is not None else []
    return []


def distinct_evidence_cameras(qt, item):
    v = (item.get("metadata") or {}).get("verification") or {}
    if qt == "temporal":
        return len({e.get("camera") for e in (v.get("event_a"), v.get("event_b"))
                    if e})
    if qt == "event_ordering":
        return len({e.get("camera") for e in v.get("ordered_events") or []})
    return None


def classify(qt, item):
    """(evidence_class, basis). Pure function of release metadata."""
    rc = (item.get("metadata") or {}).get("requires_cameras") or []
    if qt == "spatial":
        return "C2", "single required camera; distractors quantify over the window"
    if qt == "temporal":
        n = distinct_evidence_cameras(qt, item)
        assert n == 2, f"temporal item with {n} evidence cameras"
        return "C4", "two interval events on two distinct cameras"
    if qt == "event_ordering":
        n = distinct_evidence_cameras(qt, item)
        return (("C4", f"{n} distinct evidence cameras") if n and n > 1
                else ("C2", "all ordered events on one camera"))
    if qt == "counting":
        alt = "C2" if len(rc) == 1 else "C4"
        return "C5", f"'across all camera views' phrasing; positive-evidence reading would be {alt}"
    if qt == "summarization":
        return "C5", "scene characterization over every feed"
    if qt == "camera":
        return "AMBIGUOUS(C1|C5)", ("positive evidence = one entrance moment in "
                                    "one camera; verification = scan all feeds "
                                    "for an earlier appearance — pending ruling")
    raise SystemExit(f"unknown question_type {qt!r}")


def main():
    rel = load_release()

    # --- harness pool: join both subsets back to the release, fail-loud ------
    subsets = {name: json.load(open(path)) for name, path in SUBSETS.items()}
    by_key = {}     # (question_type, orig_id) -> label row
    for name, records in subsets.items():
        for r in records:
            if r.get("source") != "meva":
                raise SystemExit(f"{name}: non-meva record id={r.get('id')}")
            qt, orig_id = r["question_type"], r["orig_id"]
            idx = int(orig_id.rsplit("#", 1)[1])
            item = rel[qt][idx]
            if item["question"].strip() != r["question"].strip():
                raise SystemExit(
                    f"join mismatch: {name} id={r['id']} {qt}#{idx} — release "
                    "question text differs; refusing to label on a bad join")
            key = f"{qt}#{idx}"
            row = by_key.get(key)
            if row is None:
                cls, basis = classify(qt, item)
                spans = event_spans(qt, item)
                row = by_key[key] = {
                    "join_key": key, "question_type": qt,
                    "task_type": r["task_type"], "evidence_class": cls,
                    "basis": basis,
                    "n_required_cameras": len((item.get("metadata") or {})
                                              .get("requires_cameras") or []),
                    "event_spans_s": spans,
                    "ids": {},
                }
            row["ids"][name] = r["id"]

    n_sub = {name: len(recs) for name, recs in subsets.items()}
    if not all(n == len(by_key) for n in n_sub.values()):
        raise SystemExit(f"subset sizes {n_sub} != joined {len(by_key)}")

    # --- release-wide summary (incl. the pools the harness never sees) -------
    release_counts = {}
    for qt, items in rel.items():
        c = Counter(classify(qt, it)[0] for it in items)
        release_counts[qt] = dict(c)

    dist = Counter(r["evidence_class"] for r in by_key.values())
    out = {
        "note": "Evidence-locality labels for the MEVA pools. Key on "
                "(question_type, orig_id-index); benchmark record ids DIFFER "
                "between subsets and are carried per subset under ids{}.",
        "rules_version": "v1 (2026-08-31)",
        "pending_rulings": [
            "C1/C3 defined by timestamp (recommended) vs literal frame",
            "camera/first-entrance questions: C1 (positive evidence) vs C5 "
            "(verification set)",
        ],
        "harness_pool_distribution": dict(dist),
        "release_distribution_by_type": release_counts,
        "labels": sorted(by_key.values(), key=lambda r: r["join_key"]),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")

    print(f"labeled {len(by_key)} harness questions -> {OUT}")
    print("harness pool:", dict(dist))
    print("release-wide by type:", json.dumps(release_counts))
    durs = [e - s for r in by_key.values() for s, e in r["event_spans_s"]
            if s is not None and e is not None]
    durs.sort()
    if durs:
        print(f"event durations (harness pool, n={len(durs)}): "
              f"min {durs[0]:.2f}s  median {durs[len(durs)//2]:.2f}s  "
              f"max {durs[-1]:.2f}s  <=0.5s: {sum(1 for d in durs if d <= 0.5)}")


if __name__ == "__main__":
    main()
