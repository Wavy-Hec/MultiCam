"""Bundle the benchmark results into a self-describing handoff directory
(merged per-leg JSONL + summary CSV + subset definitions + README) so a
collaborator can reproduce or compare against them (e.g. a Qwen leg run
elsewhere) without needing this repo. Re-run any time; legs whose shard files
have since grown or appeared (the full-MVU runs land overnight) are re-merged.

Run from repo root (no GPU):
  python -m bench.export_handoff            # writes bench/results/handoff/ + .tar.gz
"""
import csv
import glob
import json
import os
import shutil
import tarfile

from . import metrics

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
REPO = os.path.dirname(HERE)

# leg name -> shard glob (relative to bench/results). Empty globs are skipped,
# so the full-MVU legs appear in the bundle automatically once their shards exist.
LEGS = {
    "mvueval_dev_task1_internvl3":    "bench_mvueval_dev_subset_internvl_mvudev_shard*.jsonl",
    "mvueval_dev_task1_qwen3vl":      "bench_mvueval_dev_subset_cvbench_mvudev_shard*.jsonl",
    "mvueval_dev_clipexp_internvl3":  "bench_mvueval_dev_subset_internvl_clipexp_shard*.jsonl",
    "mvueval_dev_clipexp_qwen3vl":    "bench_mvueval_dev_subset_cvbench_clipexp_shard*.jsonl",
    "allangles_task1_internvl3":      "bench_allangles_egohumans_qa_internvl_aabfull_shard*.jsonl",
    "allangles_task1_qwen3vl_PARTIAL": "bench_allangles_egohumans_qa_cvbench_aabfull_shard*.jsonl",
    "mvueval_full_task1_internvl3":   "bench_mvueval_qa_internvl_mvufull_shard*.jsonl",
    "mvueval_full_clipexp_internvl3": "bench_mvueval_qa_internvl_mvufullclip_shard*.jsonl",
}
SUBSETS = ["analysis/mvueval_dev_subset.json", "analysis/mvueval_qa.json",
           "analysis/allangles_egohumans_qa.json"]

README = """# MultiCam benchmark results — handoff bundle

One merged JSONL per experiment leg (one row = one question x method x backend x
sampling pass), plus the exact question subsets, so an external run (e.g. a Qwen
leg) is comparable question-by-question via the shared `id` field.

## Loading
    import json
    rows = [json.loads(l) for l in open("mvueval_dev_task1_internvl3.jsonl")]
    # pandas: pd.read_json(path, lines=True)
    # torch:  torch.save(rows, "rows.pth")   # only if a .pth is really needed

## Run configuration (identical across legs unless noted)
- models: OpenGVLab/InternVL3-8B, Qwen/Qwen3-VL-8B-Thinking
- passes=4 (seeds 1,2,3,4), temperature 0.7; frames: nframes=8 per clip
- centralized: T=4 grid montages, 448 px cells, 'Video i' labels
  (InternVL max_tiles: 4 on the dev Task-1 leg, 9 on the full-MVU Task-1 leg)
- clip experiment (matched 64-frame budget): frame_select (global CLIP top-64),
  clip_select_top1 (best single video), temporal_weighted (uniform); 32
  candidate frames per clip; InternVL max_tiles=1 on these legs
- per_stream: per-view perception (1024-token cap) -> text-only aggregator
- MVU-Eval dev = 100 q (chance 24.8 / always-A floor 37.0); full = 1,824 q
  (chance 25.9 / floor 25.5). All-Angles EgoHumans = 170 q (chance 33.3 /
  floor 38.2).

## Row schema
id, task_type, source, orig_num_cameras, cap_answer_safe, num_videos, method,
backend, prediction, gold, correct, abstained, pair_idx, pass_idx, seed,
temperature, latency_s, perception_latency_{par,serial}_s, aggregate_latency_s,
input_tokens, video_tokens, output_tokens, num_model_calls, response_text,
think, frame_alloc, error.
Notes: rows written before the trace fix have response_text/think = null;
per_stream rows may carry frame_alloc.perception_texts (per-view descriptions);
abstained means no letter was parsed (usually output truncation) and is scored
incorrect.

## Caveats
- `allangles_task1_qwen3vl_PARTIAL`: the run was cancelled mid-array. Methods
  finish sequentially inside a shard, so the per-method question sets are NOT
  identical — compare methods only on the intersection of `id`s, never on the
  pooled file. cvbench_native is complete (170 q); centralized/per_stream are not,
  and additionally the Qwen centralized arm is token-starved by the 448 px
  montage cells (~37x fewer visual tokens than native) — treat it as config-
  confounded, not as an architecture result.
- MVU-Eval option counts vary per question (2-10); use per-question chance, not 1/4.
- 49 of the 100 dev questions (and many full-set ones) have options that name a
  specific video ("A. Video 1"), which structurally penalizes any view-discarding
  method (clip_select_top1).

Regenerate after new shards land:  python -m bench.export_handoff
"""


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
    csv_rows = []
    for leg, pattern in LEGS.items():
        rows, files = merge(pattern)
        if not rows:
            continue
        with open(os.path.join(out, f"{leg}.jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        by = metrics.summarize_by_method_backend_passes(rows)
        for k, s in by.items():
            ov, op = s["overall"], s["overall_passes"]
            n_q = len({r["id"] for r in rows if f'{r["method"]}/{r["backend"]}' == k})
            csv_rows.append(dict(
                leg=leg, method_backend=k, n_questions=n_q, n_rows=ov["total"],
                accuracy_pct=(None if ov["acc"] is None else round(ov["acc"] * 100, 2)),
                acc_mean_pct=(None if op["mean"] is None else round(op["mean"] * 100, 2)),
                acc_std_pct=(None if op["std"] is None else round(op["std"] * 100, 2)),
                n_passes=op["n_passes"],
                abstain_pct=(None if s["abstain_rate"] is None else round(s["abstain_rate"] * 100, 1)),
                errors=s["errors"]))
        print(f"{leg}: {len(rows)} rows from {len(files)} shards")
    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        w.writeheader()
        w.writerows(csv_rows)
    sub_dir = os.path.join(out, "subsets")
    os.makedirs(sub_dir, exist_ok=True)
    for s in SUBSETS:
        shutil.copy2(os.path.join(REPO, s), sub_dir)
    with open(os.path.join(out, "README.md"), "w") as f:
        f.write(README)
    tar_path = os.path.join(RESULTS, "handoff.tar.gz")
    with tarfile.open(tar_path, "w:gz") as t:
        t.add(out, arcname="multicam_results_handoff")
    print(f"bundle -> {out}  |  tarball -> {tar_path} "
          f"({os.path.getsize(tar_path) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
