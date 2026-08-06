"""Bundle the benchmark results into a self-describing, *mergeable* handoff so a
collaborator can compare against them — or pool their own runs with them — without
needing this repo.

The bundle is a two-way exchange format, not just a dump:

* ``manifest.json`` describes every leg (dataset, subset + its sha256, backend,
  question count, chance and majority floors, frame budget) and the code version
  that produced it. Nothing about a leg is implied by its filename.
* the row schema is **generated from** ``methods.base.Result`` rather than
  hand-written prose, so it cannot drift from the code.
* ``merge_results.py`` ships inside the bundle: it pools any set of leg JSONLs —
  ours, theirs, or both — keying on ``(dataset, id)`` and reports per-arm accuracy.

Why ``(dataset, id)`` and not ``id``: ``id`` is a per-subset integer starting at 0,
so All-Angles q42, MVU-Eval q42 and CrossView-MEVA q42 collide. Rows written before
2026-08-05 carry no ``dataset`` field, so this exporter stamps it from the leg
definition — existing results become mergeable without rewriting 1.9 GB in place.

Run from repo root (no GPU):
  python -m bench.export_handoff            # writes bench/results/handoff/ + .tar.gz
"""
import csv
import dataclasses
import glob
import hashlib
import json
import os
import shutil
import subprocess
import tarfile

from . import metrics
from .methods.base import Result

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
REPO = os.path.dirname(HERE)


def leg(pattern, dataset, subset, backend, budget, note=None):
    return dict(glob=pattern, dataset=dataset, subset=subset, backend=backend,
                budget=budget, note=note)


# Every leg carries its own provenance. Empty globs are skipped, so legs appear in
# the bundle automatically once their shards land.
LEGS = {
    "mvueval_dev_task1_internvl3": leg(
        "bench_mvueval_dev_subset_internvl_mvudev_shard*.jsonl",
        "mvueval_dev_subset", "analysis/mvueval_dev_subset.json",
        "InternVL3-8B", "8 frames/clip"),
    "mvueval_dev_task1_qwen3vl": leg(
        "bench_mvueval_dev_subset_cvbench_mvudev_shard*.jsonl",
        "mvueval_dev_subset", "analysis/mvueval_dev_subset.json",
        "Qwen3-VL-8B-Thinking", "8 frames/clip"),
    "mvueval_dev_clipexp_internvl3": leg(
        "bench_mvueval_dev_subset_internvl_clipexp_shard*.jsonl",
        "mvueval_dev_subset", "analysis/mvueval_dev_subset.json",
        "InternVL3-8B", "64-frame matched"),
    "mvueval_dev_clipexp_qwen3vl": leg(
        "bench_mvueval_dev_subset_cvbench_clipexp_shard*.jsonl",
        "mvueval_dev_subset", "analysis/mvueval_dev_subset.json",
        "Qwen3-VL-8B-Thinking", "64-frame matched"),
    "allangles_task1_internvl3": leg(
        "bench_allangles_egohumans_qa_internvl_aabfull_shard*.jsonl",
        "allangles_egohumans_qa", "analysis/allangles_egohumans_qa.json",
        "InternVL3-8B", "n/a (still images)"),
    "allangles_task1_qwen3vl_PARTIAL": leg(
        "bench_allangles_egohumans_qa_cvbench_aabfull_shard*.jsonl",
        "allangles_egohumans_qa", "analysis/allangles_egohumans_qa.json",
        "Qwen3-VL-8B-Thinking", "n/a (still images)",
        "Cancelled mid-array; per-method question sets are NOT identical. Compare "
        "only on the intersection of ids. Its centralized arm is additionally "
        "token-starved by 448px montage cells — config-confounded, not an "
        "architecture result."),
    "mvueval_full_task1_internvl3": leg(
        "bench_mvueval_qa_internvl_mvufull_shard*.jsonl",
        "mvueval_qa", "analysis/mvueval_qa.json", "InternVL3-8B", "8 frames/clip"),
    "mvueval_full_clipexp_internvl3": leg(
        "bench_mvueval_qa_internvl_mvufullclip_shard*.jsonl",
        "mvueval_qa", "analysis/mvueval_qa.json", "InternVL3-8B", "64-frame matched",
        "PRE-DATES the frame_select per-clip floor fix (2026-08-05): 39.9% of "
        "frame_select rows dropped >=1 camera view entirely. Do not quote until re-run."),
    "mvueval_full_budget32_internvl3": leg(
        "bench_mvueval_qa_internvl_mvufull32_shard*.jsonl",
        "mvueval_qa", "analysis/mvueval_qa.json", "InternVL3-8B", "32 frames/question"),
    "mvueval_full_blind_internvl3": leg(
        "bench_mvueval_qa_internvl_mvublind*shard*.jsonl",
        "mvueval_qa", "analysis/mvueval_qa.json", "InternVL3-8B", "0 (blind)"),
    "mvueval_singleview_internvl3": leg(
        "bench_mvueval_noview_subset_internvl_mvusv_shard*.jsonl",
        "mvueval_noview_subset", "analysis/mvueval_noview_subset.json",
        "InternVL3-8B", "8 frames/clip, single view"),
    "allangles_blind_internvl3": leg(
        "bench_allangles_egohumans_qa_internvl_aabblind*.jsonl",
        "allangles_egohumans_qa", "analysis/allangles_egohumans_qa.json",
        "InternVL3-8B", "0 (blind)"),
    "mvueval_full_parity32pv_internvl3": leg(
        "bench_mvueval_qa_internvl_mvupp32*_shard*.jsonl",
        "mvueval_qa", "analysis/mvueval_qa.json", "InternVL3-8B", "32 frames/video"),
    # CrossView. The combined-subset leg exists; the MEVA legs land from the
    # 2026-08-05 plan and are empty-glob-skipped until then.
    "crossview_combined_qwen3vl_PARTIAL": leg(
        "bench_crossview_combined_subset_cvbench_shard*.jsonl",
        "crossview_combined_subset", "analysis/crossview_combined_subset.json",
        "Qwen3-VL-8B-Thinking", "8 frames/clip",
        "centralized complete (50 q); per_stream incomplete; no native arm. Built "
        "under the OLD 4-camera cap — not comparable to cap-13 records."),
    # Same questions as crossview_meva1033_subset.json but packed to the harness
    # slot count, which is what these shards were actually run against — they
    # stamp dataset=crossview_meva_cap13, so declare that pool, not the 4-cam one.
    "crossview_meva_task1_internvl3": leg(
        "bench_crossview_meva*_internvl_cvmeva*_shard*.jsonl",
        "crossview_meva_cap13", "analysis/crossview_meva_cap13.json",
        "InternVL3-8B", "8 frames/clip"),
    "crossview_meva_task1_qwen25vl": leg(
        "bench_crossview_meva*_cvbench_cvmevaq25*_shard*.jsonl",
        "crossview_meva_cap13", "analysis/crossview_meva_cap13.json",
        "Qwen2.5-VL-7B-Instruct", "8 frames/clip"),
    "mvueval_full_task1_qwen25vl": leg(
        "bench_mvueval_qa_cvbench_mvufullq25*_shard*.jsonl",
        "mvueval_qa", "analysis/mvueval_qa.json",
        "Qwen2.5-VL-7B-Instruct", "8 frames/clip"),
}

MERGE_HELPER = '''#!/usr/bin/env python3
"""Pool any set of leg JSONLs — ours, yours, or both — and report per-arm accuracy.

Rows are keyed on (dataset, id). `id` alone is a per-subset integer starting at 0,
so pooling datasets on it silently fuses different questions.

    python3 merge_results.py *.jsonl
    python3 merge_results.py ours/*.jsonl theirs/*.jsonl --by dataset
"""
import argparse, collections, json, glob, os, statistics, sys


def load(paths):
    rows = []
    for p in paths:
        for f in sorted(glob.glob(p)) or [p]:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    # rows written before 2026-08-05 have no `dataset`; fall back to
                    # the manifest mapping if present, else the filename stem.
                    if not r.get("dataset"):
                        r["dataset"] = LEG_DATASET.get(os.path.basename(f).split(".")[0], "unknown")
                    rows.append(r)
    return rows


LEG_DATASET = {}
_m = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json")
if os.path.exists(_m):
    LEG_DATASET = {k: v["dataset"] for k, v in json.load(open(_m))["legs"].items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--by", default="dataset", choices=["dataset", "none"])
    a = ap.parse_args()
    rows = load(a.paths)
    if not rows:
        sys.exit("no rows loaded")

    groups = collections.defaultdict(list)
    for r in rows:
        key = (r.get("dataset") if a.by == "dataset" else "all",
               r.get("method"), r.get("backend"))
        groups[key].append(r)

    print(f"{len(rows):,} rows | {len({(r['dataset'], r['id']) for r in rows}):,} distinct questions "
          f"| runs: {sorted({r.get('run_id') or 'legacy' for r in rows})}\\n")
    hdr = f"{'dataset':28s} {'method':20s} {'backend':24s} {'n_q':>6} {'rows':>7} {'acc%':>7} {'std':>6}"
    print(hdr); print("-" * len(hdr))
    for (ds, m, b), rs in sorted(groups.items(), key=lambda x: str(x[0])):
        n_q = len({r["id"] for r in rs})
        acc = 100 * sum(bool(r.get("correct")) for r in rs) / len(rs)
        byp = collections.defaultdict(list)
        for r in rs:
            if r.get("pass_idx"):
                byp[r["pass_idx"]].append(bool(r.get("correct")))
        pa = [100 * sum(v) / len(v) for v in byp.values() if v]
        std = statistics.pstdev(pa) if len(pa) > 1 else float("nan")
        print(f"{str(ds):28s} {str(m):20s} {str(b):24s} {n_q:6d} {len(rs):7d} {acc:7.2f} {std:6.2f}")


if __name__ == "__main__":
    main()
'''


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def row_schema():
    """Field list generated from the dataclass, so prose can never drift from code."""
    return [{"field": f.name, "type": str(f.type)}
            for f in dataclasses.fields(Result)]


def subset_stats(rel):
    """(n_questions, chance_pct, majority_floor_pct) for a subset file."""
    path = os.path.join(REPO, rel)
    if not os.path.exists(path):
        return None, None, None
    try:
        recs = json.load(open(path))
    except Exception:
        return None, None, None
    n = len(recs)
    chances, golds = [], []
    for r in recs:
        opts = r.get("options")
        k = len(opts) if isinstance(opts, (list, dict)) else 0
        if k:
            chances.append(1.0 / k)
        if r.get("answer"):
            golds.append(str(r["answer"]).strip().upper())
    chance = round(100 * sum(chances) / len(chances), 2) if chances else None
    floor = None
    if golds:
        floor = round(100 * max(golds.count(g) for g in set(golds)) / len(golds), 2)
    return n, chance, floor


def merge(pattern):
    rows, files = [], sorted(glob.glob(os.path.join(RESULTS, pattern)))
    for f in files:
        for line in open(f):
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows, files


def main():
    out = os.path.join(RESULTS, "handoff")
    os.makedirs(out, exist_ok=True)
    csv_rows, manifest_legs, subsets_used = [], {}, set()

    for name, spec in LEGS.items():
        rows, files = merge(spec["glob"])
        if not rows:
            continue
        # Stamp identity onto legacy rows (written before Result gained these
        # fields) so the bundle is mergeable without rewriting the originals.
        stamped = 0
        for r in rows:
            if not r.get("dataset"):
                r["dataset"] = spec["dataset"]
                stamped += 1
        with open(os.path.join(out, f"{name}.jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

        backends = sorted({r.get("backend") for r in rows if r.get("backend")})
        n_q, chance, floor = subset_stats(spec["subset"])
        subsets_used.add(spec["subset"])
        sub_path = os.path.join(REPO, spec["subset"])
        manifest_legs[name] = dict(
            dataset=spec["dataset"], subset=os.path.basename(spec["subset"]),
            subset_sha256=(sha256(sub_path) if os.path.exists(sub_path) else None),
            backend_declared=spec["backend"], backends_observed=backends,
            frame_budget=spec["budget"], n_questions_in_subset=n_q,
            chance_pct=chance, majority_floor_pct=floor,
            n_rows=len(rows), n_shards=len(files),
            dataset_stamped_rows=stamped, note=spec["note"])

        by = metrics.summarize_by_method_backend_passes(rows)
        for k, s in by.items():
            ov, op = s["overall"], s["overall_passes"]
            n_qq = len({r["id"] for r in rows if f'{r["method"]}/{r["backend"]}' == k})
            csv_rows.append(dict(
                leg=name, dataset=spec["dataset"], method_backend=k,
                frame_budget=spec["budget"], n_questions=n_qq, n_rows=ov["total"],
                accuracy_pct=(None if ov["acc"] is None else round(ov["acc"] * 100, 2)),
                acc_mean_pct=(None if op["mean"] is None else round(op["mean"] * 100, 2)),
                acc_std_pct=(None if op["std"] is None else round(op["std"] * 100, 2)),
                n_passes=op["n_passes"], chance_pct=chance, majority_floor_pct=floor,
                abstain_pct=(None if s["abstain_rate"] is None else round(s["abstain_rate"] * 100, 1)),
                errors=s["errors"]))
        flag = f"  [{stamped} rows dataset-stamped]" if stamped else ""
        print(f"{name}: {len(rows)} rows from {len(files)} shards{flag}")

    if not csv_rows:
        raise SystemExit("no legs matched — nothing to export")

    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        w.writeheader()
        w.writerows(csv_rows)

    sub_dir = os.path.join(out, "subsets")
    os.makedirs(sub_dir, exist_ok=True)
    for s in sorted(subsets_used):
        p = os.path.join(REPO, s)
        if os.path.exists(p):
            shutil.copy2(p, sub_dir)

    manifest = dict(
        format_version=2,
        generated_by="bench/export_handoff.py",
        git_sha=git_sha(),
        merge_key=["dataset", "id"],
        merge_key_note=("`id` is a per-subset integer starting at 0, so it is NOT "
                        "unique across datasets. Always key on (dataset, id). Rows "
                        "written before 2026-08-05 lack `dataset`/`run_id`/`node`; "
                        "this exporter stamps `dataset` from the leg definition."),
        protocol=dict(passes=4, seeds=[1, 2, 3, 4], temperature=0.7,
                      montage="T=4 grid, 448px cells, 'Video i' labels",
                      per_stream="per-view perception (1024-token cap) -> text-only aggregator",
                      scoring="abstained (no letter parsed) is scored incorrect"),
        row_schema=row_schema(),
        legs=manifest_legs,
    )
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    with open(os.path.join(out, "merge_results.py"), "w") as f:
        f.write(MERGE_HELPER)
    os.chmod(os.path.join(out, "merge_results.py"), 0o755)

    with open(os.path.join(out, "README.md"), "w") as f:
        f.write(render_readme(manifest))

    tar_path = os.path.join(RESULTS, "handoff.tar.gz")
    with tarfile.open(tar_path, "w:gz") as t:
        t.add(out, arcname="multicam_results_handoff")
    print(f"\nbundle -> {out}  |  tarball -> {tar_path} "
          f"({os.path.getsize(tar_path) / 1e6:.1f} MB)")
    print(f"legs: {len(manifest_legs)}  |  schema fields: {len(manifest['row_schema'])}")


def render_readme(manifest):
    """Prose generated from the manifest, so it cannot drift from the data."""
    lines = ["# MultiCam benchmark results — handoff bundle", "",
             "One merged JSONL per experiment leg (one row = one question x method x "
             "backend x sampling pass), plus the exact question subsets and a "
             "machine-readable `manifest.json`.", "",
             f"Code version: `{manifest['git_sha'] or 'unknown'}`", "",
             "## Merging with your own results", "",
             "```bash", "python3 merge_results.py *.jsonl              # ours",
             "python3 merge_results.py *.jsonl /path/to/yours/*.jsonl  # pooled",
             "```", "",
             f"**Key on `{tuple(manifest['merge_key'])}`.** {manifest['merge_key_note']}", "",
             "To contribute a leg, emit rows with the schema below and set `dataset` "
             "to the subset basename you ran against (see `subsets/`); `run_id` keeps "
             "your rows distinguishable from ours.", "",
             "## Protocol", ""]
    for k, v in manifest["protocol"].items():
        lines.append(f"- **{k}**: {v}")
    lines += ["", "## Legs", "",
              "| leg | dataset | backend(s) | budget | rows | n_q | chance% | floor% |",
              "|---|---|---|---|--:|--:|--:|--:|"]
    for name, m in manifest["legs"].items():
        lines.append(
            f"| `{name}` | {m['dataset']} | {', '.join(m['backends_observed']) or '—'} | "
            f"{m['frame_budget']} | {m['n_rows']} | {m['n_questions_in_subset']} | "
            f"{m['chance_pct']} | {m['majority_floor_pct']} |")
    notes = [(n, m["note"]) for n, m in manifest["legs"].items() if m.get("note")]
    if notes:
        lines += ["", "## Caveats", ""]
        for n, note in notes:
            lines.append(f"- **`{n}`** — {note}")
    lines += ["", "## Row schema", "",
              "Generated from `bench/methods/base.py::Result` — this list cannot "
              "drift from the code.", "", "| field | type |", "|---|---|"]
    for f in manifest["row_schema"]:
        lines.append(f"| `{f['field']}` | {f['type']} |")
    lines += ["", "Notes: rows written before the trace fix have "
              "`response_text`/`think` = null; `per_stream` rows may carry "
              "`frame_alloc.perception_texts`. MVU-Eval option counts vary per "
              "question (2-10), so always use the per-question chance in "
              "`manifest.json`, never a flat 1/4.", "",
              "Regenerate: `python -m bench.export_handoff`", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
