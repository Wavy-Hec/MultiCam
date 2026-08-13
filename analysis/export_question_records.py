#!/usr/bin/env python3
"""One analysis-ready record per (dataset, backend, method, question, pass), so
every future plot is a filter over a file instead of another GPU run.

The result JSONLs in bench/results/ already carry the prediction, the gold and
the timings, but NOT which videos the question pointed at — those live in the
subset JSON. This joins the two, so a record can be grouped by camera count,
task type, source, token budget or latency without touching the raw shards
again.

Writes into analysis/records/:
  records.jsonl    one row per (dataset, backend, method, id, pass_idx)
  questions.jsonl  one row per (dataset, backend, method, id), averaged over passes
  registry.json    what has been run, with what config, at what accuracy —
                   check this BEFORE launching anything, it is the answer to
                   "have we already done this?"

Response text is deliberately not copied (it is ~1.9 GB across all legs); each
record keeps its length and a has_think flag so traces can still be located in
the source shard by (dataset, backend, method, id, pass_idx).

Run (no GPU):  python3 analysis/export_question_records.py
"""
import glob
import hashlib
import json
import os
import statistics
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RES = os.path.join(REPO, "bench", "results")
OUT = os.path.join(HERE, "records")

# (dataset, backend) -> subset file + shard glob. Same globs the stats script
# uses, so the two can never disagree about which rows belong to a leg.
LEGS = [
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_mvufull_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="MVU-Eval", backend="Qwen2.5-VL-7B-Instruct", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_cvbench_mvufullq25*_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_mvufull32_shard*.jsonl", budget="32 frames total"),
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_mvupp32*_shard*.jsonl", budget="32 frames/video"),
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_mvublind*shard*.jsonl", budget="no images"),
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_mvufullclip_shard*.jsonl", budget="64 frames total"),
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_noview_subset.json",
         glob="bench_mvueval_noview_subset_internvl_mvusv_shard*.jsonl",
         budget="8 frames/video, single view"),
    dict(dataset="CrossView-MEVA", backend="InternVL3-8B", subset="crossview_meva_cap13.json",
         glob="bench_crossview_meva_cap13_internvl_cvmeva_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="CrossView-MEVA", backend="Qwen2.5-VL-7B-Instruct",
         subset="crossview_meva_cap13.json",
         glob="bench_crossview_meva_cap13_cvbench_cvmevaq25_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="All-Angles", backend="InternVL3-8B", subset="allangles_egohumans_qa.json",
         glob="bench_allangles_egohumans_qa_internvl_aabfull_shard*.jsonl", budget="stills, cell_px=448"),
    dict(dataset="All-Angles", backend="Qwen3-VL-8B-Thinking", subset="allangles_egohumans_qa.json",
         glob="bench_allangles_egohumans_qa_cvbench_aabfull_shard*.jsonl", budget="stills, cell_px=448"),
    dict(dataset="All-Angles", backend="InternVL3-8B", subset="allangles_egohumans_qa.json",
         glob="bench_allangles_egohumans_qa_internvl_aabblind*.jsonl", budget="no images"),

    # --- reasoning-off / temp-0.1 campaign (2026-08-10 onward) --------------
    # Everything above ran reasoning ON at temp 0.7. These legs are the SECOND
    # protocol and are not comparable to it, which is why every row now records
    # `protocol` — the old table carried no temperature or reasoning field at
    # all, so the two campaigns were indistinguishable once exported.
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_t1iv_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="MVU-Eval", backend="Qwen2.5-VL-7B-Instruct", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_cvbench_t1q25_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="CrossView-MEVA", backend="InternVL3-8B", subset="crossview_meva_cap13.json",
         glob="bench_crossview_meva_cap13_internvl_t1iv_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="CrossView-MEVA", backend="Qwen2.5-VL-7B-Instruct",
         subset="crossview_meva_cap13.json",
         glob="bench_crossview_meva_cap13_cvbench_t1q25_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="CrossView-EgoExo", backend="InternVL3-8B", subset="crossview_egoexo500.json",
         glob="bench_crossview_egoexo500_internvl_*_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="CrossView-EgoExo", backend="Qwen2.5-VL-7B-Instruct",
         subset="crossview_egoexo500.json",
         glob="bench_crossview_egoexo500_cvbench_*_shard*.jsonl", budget="8 frames/video"),
    dict(dataset="All-Angles", backend="InternVL3-8B", subset="allangles_qa.json",
         glob="bench_allangles_qa_internvl_t1iv_shard*.jsonl", budget="stills, cell_px=448"),
    dict(dataset="All-Angles", backend="Qwen2.5-VL-7B-Instruct", subset="allangles_qa.json",
         glob="bench_allangles_qa_cvbench_t1q25_shard*.jsonl", budget="stills, cell_px=448"),
    # blind controls at temp 0.1 (jobs 86174-86177). Verified 08-13 against the
    # landed files: single-shard legs, so the outputs carry NO _shard suffix —
    # the glob matches both spellings in case a future rerun shards them.
    dict(dataset="All-Angles", backend="InternVL3-8B", subset="allangles_qa.json",
         glob="bench_allangles_qa_internvl_t1iv_blind*.jsonl", budget="no images"),
    dict(dataset="All-Angles", backend="Qwen2.5-VL-7B-Instruct", subset="allangles_qa.json",
         glob="bench_allangles_qa_cvbench_t1q25_blind*.jsonl", budget="no images"),
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_t1iv_blind*.jsonl", budget="no images"),
    dict(dataset="MVU-Eval", backend="Qwen2.5-VL-7B-Instruct", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_cvbench_t1q25_blind*.jsonl", budget="no images"),
    # frame sweep: sequential arm only, InternVL3 only, two video pools
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_fs32_shard*.jsonl", budget="32 frames total"),
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_fs64_shard*.jsonl", budget="64 frames total"),
    dict(dataset="MVU-Eval", backend="InternVL3-8B", subset="mvueval_qa.json",
         glob="bench_mvueval_qa_internvl_fs96_shard*.jsonl", budget="96 frames total"),
    dict(dataset="CrossView-MEVA", backend="InternVL3-8B", subset="crossview_meva_cap13.json",
         glob="bench_crossview_meva_cap13_internvl_fs32_shard*.jsonl", budget="32 frames total"),
    dict(dataset="CrossView-MEVA", backend="InternVL3-8B", subset="crossview_meva_cap13.json",
         glob="bench_crossview_meva_cap13_internvl_fs64_shard*.jsonl", budget="64 frames total"),
    dict(dataset="CrossView-MEVA", backend="InternVL3-8B", subset="crossview_meva_cap13.json",
         glob="bench_crossview_meva_cap13_internvl_fs96_shard*.jsonl", budget="96 frames total"),
]

MEDIA_KEYS = [f"video_{i}" for i in range(1, 14)] + [f"image_{i}" for i in range(1, 14)]


def media_of(rec):
    return [rec[k] for k in MEDIA_KEYS if rec.get(k)]


def sha256(path, cap=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(cap):
            h.update(chunk)
    return h.hexdigest()[:16]


def main():
    os.makedirs(OUT, exist_ok=True)
    subsets, registry, n_rec = {}, [], 0
    frec = open(os.path.join(OUT, "records.jsonl"), "w")
    fq = open(os.path.join(OUT, "questions.jsonl"), "w")

    for leg in LEGS:
        spath = os.path.join(HERE, leg["subset"])
        if spath not in subsets:
            if not os.path.exists(spath):
                continue
            recs = json.load(open(spath))
            subsets[spath] = ({r["id"]: r for r in recs}, sha256(spath), len(recs))
        by_id, ssha, n_pool = subsets[spath]

        # Prefer the rescored copies. The old answer parser dropped any tagless
        # response over 40 chars, which is how InternVL3 answers with reasoning
        # off, so the raw rows under-report it by up to 8 points — and this file
        # is what gets read before launching anything.
        files = sorted(glob.glob(os.path.join(RES, "rescored", leg["glob"])))
        rescored = bool(files)
        if not files:
            files = sorted(glob.glob(os.path.join(RES, leg["glob"])))
        if not files:
            continue
        # per (method, id) accumulators for the question-level file
        agg = defaultdict(list)
        seen_methods, n_rows = set(), 0
        # protocol accumulators: the LEGS table's `budget` is a hand-written
        # label, so without these the export cannot tell the reasoning-on/temp-0.7
        # campaign from the reasoning-off/temp-0.1 one
        proto = defaultdict(set)
        n_think = 0
        for path in files:
            with open(path) as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    if r.get("backend") != leg["backend"]:
                        continue
                    q = by_id.get(r["id"], {})
                    media = media_of(q)
                    lat = r.get("latency_s")
                    rec = {
                        "dataset": leg["dataset"], "backend": leg["backend"],
                        "method": r["method"], "budget": leg["budget"],
                        "pass_idx": r.get("pass_idx"), "id": r["id"],
                        "task_type": r.get("task_type"), "source": r.get("source"),
                        # what the question pointed at — the join the raw rows lack
                        "media": media, "n_media": len(media),
                        "n_delivered": r.get("num_videos"),
                        "orig_num_cameras": r.get("orig_num_cameras"),
                        "truncated": (bool(r.get("orig_num_cameras")
                                           and r.get("num_videos")
                                           and r["orig_num_cameras"] > r["num_videos"])),
                        "n_options": len(q.get("options", [])) or None,
                        "gold": r.get("gold"), "prediction": r.get("prediction"),
                        "correct": bool(r.get("correct")),
                        "abstained": bool(r.get("abstained")),
                        "latency_s": lat,
                        "latency_ms": None if lat is None else round(lat * 1000.0, 1),
                        "perception_latency_par_s": r.get("perception_latency_par_s"),
                        "aggregate_latency_s": r.get("aggregate_latency_s"),
                        "num_model_calls": r.get("num_model_calls"),
                        "input_tokens": r.get("input_tokens"),
                        "video_tokens": r.get("video_tokens"),
                        "output_tokens": r.get("output_tokens"),
                        "has_think": bool(r.get("think")),
                        "response_chars": len(r.get("response_text") or ""),
                        "error": r.get("error"), "run_id": r.get("run_id"),
                    }
                    frec.write(json.dumps(rec) + "\n")
                    n_rec += 1
                    n_rows += 1
                    seen_methods.add(r["method"])
                    agg[(r["method"], r["id"])].append(rec)
                    n_think += bool(r.get("think"))
                    if r.get("temperature") is not None:
                        proto["temperature"].add(r["temperature"])
                    fa = r.get("frame_alloc") or {}
                    for k in ("total_frames", "cell_px", "max_tiles"):
                        if fa.get(k) is not None:
                            proto[k].add(fa[k])

        for (method, qid), rs in sorted(agg.items()):
            r0 = rs[0]
            lats = [x["latency_s"] for x in rs if x["latency_s"] is not None]
            fq.write(json.dumps({
                **{k: r0[k] for k in ("dataset", "backend", "budget", "task_type",
                                      "source", "media", "n_media", "n_delivered",
                                      "orig_num_cameras", "truncated", "n_options",
                                      "gold")},
                "method": method, "id": qid, "n_passes": len(rs),
                "acc_mean": round(sum(x["correct"] for x in rs) / len(rs), 4),
                "n_correct": sum(x["correct"] for x in rs),
                "predictions": [x["prediction"] for x in rs],
                "abstain_rate": round(sum(x["abstained"] for x in rs) / len(rs), 4),
                "latency_s_mean": round(statistics.mean(lats), 3) if lats else None,
                "latency_ms_median": (round(statistics.median(lats) * 1000, 1)
                                      if lats else None),
                "video_tokens_mean": _mean(x["video_tokens"] for x in rs),
                "num_model_calls_mean": _mean(x["num_model_calls"] for x in rs),
            }) + "\n")

        for method in sorted(seen_methods):
            rs = [r for (m, _), v in agg.items() if m == method for r in v]
            # single_view<i> is only DEFINED on questions that have an i-th view,
            # so scoring it against the whole pool invents nine false gaps and
            # buries the real ones
            expected = n_pool
            if method.startswith("single_view"):
                i = int(method.replace("single_view", ""))
                expected = sum(1 for q in by_id.values() if len(media_of(q)) >= i)
            registry.append({
                "dataset": leg["dataset"], "backend": leg["backend"], "method": method,
                "budget": leg["budget"], "subset": leg["subset"], "subset_sha256": ssha,
                "subset_questions": n_pool, "questions_expected": expected,
                "questions_run": len({r["id"] for r in rs}),
                "rows": len(rs), "passes": len({r["pass_idx"] for r in rs}),
                "complete": len({r["id"] for r in rs}) >= expected,
                "accuracy_pct": round(100 * sum(r["correct"] for r in rs) / len(rs), 2),
                "errors": sum(1 for r in rs if r["error"]),
                "glob": leg["glob"],
                "rescored": rescored,
                # reasoning is read off the traces, not the launch env: with
                # REASONING=0 the direct-answer template leaves `think` empty
                "protocol": {
                    "temperature": sorted(proto["temperature"]),
                    "reasoning": ("off" if n_think == 0 else
                                  "on" if n_think == n_rows else
                                  f"mixed ({100*n_think//max(n_rows,1)}% traced)"),
                    "total_frames": sorted(proto["total_frames"]) or None,
                    "cell_px": sorted(proto["cell_px"]) or None,
                    "max_tiles": sorted(proto["max_tiles"]) or None,
                },
            })

    frec.close()
    fq.close()
    with open(os.path.join(OUT, "registry.json"), "w") as f:
        json.dump({"note": "Check this before launching: any row here has already been run.",
                   "legs": registry}, f, indent=1)
    print(f"records.jsonl   {n_rec:,} rows")
    print(f"questions.jsonl written")
    print(f"registry.json   {len(registry)} (dataset, backend, method, budget) legs")
    incomplete = [r for r in registry if not r["complete"]]
    if incomplete:
        print("\nINCOMPLETE legs:")
        for r in incomplete:
            print(f"  {r['dataset']:15s} {r['backend']:24s} {r['method']:16s} "
                  f"{r['questions_run']}/{r['questions_expected']} q")


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


if __name__ == "__main__":
    main()
