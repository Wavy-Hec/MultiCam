# bench/ — multi-camera benchmark spec (frozen)

Implements `analysis/BENCHMARK_PLAN_48H.md`. Given a multi-stream question, run N **methods**
× M **backends** and log accuracy + latency + cost per question-category.

## Metrics (one `Result` row per question × method × backend)
- **M1 Accuracy** — overall + by `task_type` / `orig_num_cameras` / `source` / `cap_answer_safe` (never pool).
- **M2 Latency** — `latency_s` (end-to-end serial); for `per_stream` also `perception_latency_serial_s`
  (sum) and `perception_latency_par_s` (`max`, the true-parallel estimate) + `aggregate_latency_s`.
- **M3 Cost** — `input_tokens`, `video_tokens`, `output_tokens`, `num_model_calls`.
- **M4 Calibration** — `abstained` (empty prediction), aggregated to an abstain rate.

## Methods (`bench/methods/`)
- `centralized` (A0) — one VLM ingests all clips; wraps `eval_thinking.build_messages`.
- `per_stream` (A1) — one perception pass per clip → text aggregator pass.
- *(A2 router / A3 NeuS-QA: roadmap, not built.)*

## Backends (`bench/backends/`)
- `qwen3vl` → `Qwen/Qwen3-VL-8B-Thinking` (cached ✅)
- `qwen3vl-instruct` → `Qwen/Qwen3-VL-8B-Instruct` (cached ✅) — the immediately-available 3rd
  backend (Qwen2.5-VL-7B is NOT cached and `HF_HUB_OFFLINE=1`; download it first to use it).
- InternVL3-8B → runs via the existing **lmms-eval** leg, not a bench backend yet.

## Pools
- Dev (100 Q): `analysis/crossview_combined_subset.json` (60 MEVA + 40 EgoExo4D).
- Scale (1,033 Q): `analysis/crossview_meva1033_subset.json`.
- `video_root` = `crossview-release-annotations/crossview-release` (resolves MEVA .avi + EgoExo4D .mp4).

## Commands
```bash
# CPU gate — reproduce 19/60 from a stored eval JSON (no GPU):
python -m bench.validate_scoring

# GPU smoke (tiny) — on a gpul40q node / via bench/run_bench.sbatch:
python -m bench.run_bench --subset analysis/crossview_combined_subset.json \
    --methods centralized --backends qwen3vl --limit 5

# full sweep (scheduled off-peak): see bench/run_bench.sbatch + sbatch --begin/--dependency
```
Reuses (single source of truth) `Video-R1/src/eval_thinking.py`: `build_messages`, `parse_choice`,
`gt_choice`, `num_videos`, `video_paths`, `load_model`, `process_vision_info` path, `<|video_pad|>`
token accounting.
