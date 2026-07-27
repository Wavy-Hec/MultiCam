# MultiCam: Multi-Camera Visual QA Evaluation of Open VLMs

This repo evaluates **centralized vs. decentralized multi-camera harnesses** for visual
question answering with open vision-language models — **Qwen3-VL-8B (Thinking)** and
**InternVL3-8B** — on multi-view benchmarks:

- **All-Angles-Bench** — multi-view still-image QA over synchronized camera views of
  the same scene (cross-view correspondence, counting, relative direction, camera pose).
- **MVU-Eval** — multi-video QA, up to thirteen clips per question, including
  synchronized multi-camera driving and cross-angle sports subsets.
- **CrossView / MEVA** — multi-camera surveillance QA over synchronized MEVA camera
  views from the CrossView release.

The core question: given the K views of a question, is it better to fuse them into a
single model input (centralized — spatial stitching or budgeted temporal sequencing),
or to run one independent perception pass per view and aggregate the text descriptions
(decentralized)?

Every arm runs 4 independent sampled passes (temperature 0.7, fixed seeds), so each
accuracy comes with a std. All runs keep the models' `<think>` traces so failures stay
interpretable. The harness reports accuracy (mean ± std) per model × harness, plus
per-task, per-camera-count, latency, and token breakdowns.

## Get started

### Environments

Two conda envs (no project venvs). The split exists because transformers 5.x breaks
InternVL3's `trust_remote_code` modeling files:

| env        | used for                        | transformers |
|------------|---------------------------------|--------------|
| `cvbench`  | Qwen3-VL legs, plots, analysis  | 5.2.0        |
| `internvl` | InternVL3-8B legs               | 4.48.3       |

The sbatch launcher picks the env via `ENV=...` (default `cvbench`).

### Data layout

Benchmark data lives under `data/` (untracked). Question subsets are JSONs under
`analysis/`, produced by the converter scripts there.

- **All-Angles-Bench**: `hf download ch-chenyu/All-Angles-Bench --repo-type dataset
  --local-dir data/allangles`, then `python analysis/convert_allangles.py`. The
  EgoHumans scenes ship with the download; the Ego-Exo4D scenes require accepting the
  Ego-Exo4D license (credentials arrive by email), downloading the downscaled takes
  with the `egoexo` CLI, and running the benchmark's `scripts/process_ego4d_exo.py`.
- **MVU-Eval**: QA file and videos from the `MVU-Eval-Team/MVU-Eval-Data` HF dataset
  into `data/mvueval/`, then `python analysis/convert_mvueval.py`.
- **CrossView/MEVA**: annotations live in `crossview-release-annotations/` (on-disk
  only); videos are fetched per-file from a private HF shard repo — see
  `hosting/README.md`.
- **Outputs**: JSONL rows under `bench/results/` (untracked — run outputs never go in
  git), logs under `analysis/logs/`.

### Running the benchmark

Everything goes through `bench/run_bench.sbatch`, a thin env-var wrapper around
`python -m bench.run_bench` (Slurm-array sharding via `CHUNK` shards ×
`OFFSET=$SLURM_ARRAY_TASK_ID`; runs are resumable on `(id, method, backend, pass)`).
Submit from the repo root.

```bash
# tiny smoke test (Qwen, 5 records):
LIMIT=5 BACKENDS=qwen3vl sbatch bench/run_bench.sbatch

# MEVA InternVL3 leg, sharded 8 ways:
ENV=internvl SUBSET=analysis/crossview_meva1033_subset.json BACKENDS=internvl3 \
  CHUNK=8 sbatch --array=0-7 bench/run_bench.sbatch

# All-Angles-Bench, all three arms, Qwen:
SUBSET=analysis/allangles_dev_subset.json VIDEO_ROOT=data/allangles \
  METHODS=cvbench_native,centralized,per_stream MONTAGE_KIND=view \
  sbatch bench/run_bench.sbatch

# MVU-Eval decentralized (per_stream) InternVL3, sharded 8 ways:
ENV=internvl SUBSET=analysis/mvueval_dev_subset.json BACKENDS=internvl3 \
  METHODS=per_stream STREAM_KIND=video VIDEO_ROOT=data/mvueval CHUNK=8 \
  sbatch --array=0-7 bench/run_bench.sbatch
```

Useful knobs (env var → CLI flag, with defaults): `METHODS` (`centralized,per_stream`),
`BACKENDS` (`qwen3vl`), `NFRAMES` (8 frames/clip), `PASSES` (4), `SEEDS` (`1,2,3,4`),
`TEMPERATURE` (0.7), `BUDGET` (64 total frames for the temporal method), `WEIGHTING`
(`duration` | `even`), `STREAM_KIND` / `MONTAGE_KIND` (`camera` | `video` | `view`
labels), `MAX_NEW_TOKENS` (8192), `TAG` (suffix to separate runs sharing a subset+env).
See the header of `bench/run_bench.sbatch` and `python -m bench.run_bench --help`.

### Scoring, reports, figures

```bash
# CPU-only gate: re-score a stored eval JSON through the bench parse+metrics path:
python -m bench.validate_scoring [path/to/eval_*.json]

# summary table + plots from pooled result JSONLs (one benchmark per call):
python -m bench.plots --jsonl bench/results/<leg1>.jsonl bench/results/<leg2>.jsonl \
    --out-dir bench/results/figs_<name>

# per-question random-guessing floor for any subset:
python -m bench.chance_level --subset analysis/<subset>.json

# All-Angles-Bench paired-question consistency (CC/WW/IC) report:
python analysis/allangles_consistency.py --results 'bench/results/<legs>*.jsonl' \
    --subset analysis/allangles_dev_subset.json
```

## Methods

Method names are what you pass in `METHODS=` / `--methods` and what gets recorded in
each result row. All methods share the same question/options/`<think>`/`<answer>` text
scaffold, so only the visual presentation differs between arms. On still-image
benchmarks the same methods operate on the question's view images instead of decoding
clips.

| method | file | what it does |
|---|---|---|
| `centralized` | `bench/methods/centralized.py` + `stitch.py` | Centralized stitch: tiles the K views into labeled grid-montage images fed to one model (temporally aligned frames for videos, one montage for stills). `--montage-kind camera\|video\|view` picks the cell labels. |
| `temporal_weighted` | `bench/methods/temporal.py` | Centralized temporal sequencing: one model sees the clips sequentially under a single total frame budget split in proportion to duration; `--weighting even` is the budget-matched control. |
| `cvbench_native` | `bench/methods/cvbench_native.py` | Sequential native presentation: each clip or view as its own input block at a flat per-clip `--nframes`. Baseline at equal frame budget. |
| `per_stream` | `bench/methods/per_stream.py` | Decentralized "1-VLM-per-stream": an independent perception pass per view, then a text-only aggregation pass reasons over the K descriptions. Latency reported both serial and max-parallel. |
| `summary_select_route` / `summary_select_top1` | `bench/methods/clip_select.py` | Question-driven clip selection via cached per-clip text summaries: a text-only selector call picks the clips, then the full frame budget is spent on the selection. |
| `clip_select_top{m}`, `clip_select_siglip_top{m}` | `bench/methods/clip_select.py` | No-LLM selector: score each clip by CLIP (or SigLIP) text-image similarity between the question and a few thumbnails, keep the top-m clips. |

Backends: `qwen3vl` (Qwen/Qwen3-VL-8B-Thinking; also `qwen3vl-instruct`) in
`bench/backends/qwen.py`, `internvl3` (OpenGVLab/InternVL3-8B) in
`bench/backends/internvl.py`.

## Repo layout

| path | contents |
|---|---|
| `bench/` | The harness: `run_bench.py` / `run_bench.sbatch` (runner + Slurm launcher), `methods/` (the arms above), `backends/` (Qwen3-VL, InternVL3), `metrics.py`, `plots.py`, `report.py`, `validate_scoring.py` (CPU gate), `chance_level.py`. Results land in `bench/results/` (untracked). |
| `analysis/` | Question subsets, converters and subset builders, job scripts, and run logs. Intentionally flat; scripts cross-reference these paths. |
| `data/` | Benchmark data roots (`allangles/`, `mvueval/`); on-disk only, not tracked. |
| `Video-R1/` | Vendored upstream eval scaffold, plus this repo's own `src/eval_thinking.py` (thinking-trace eval entry point whose parse/scoring helpers `bench/reuse.py` imports). |
| `hosting/` | Tooling to shard/upload/fetch the CrossView videos via a private HF dataset repo. |
| `crossview-release-annotations/` | CrossView dataset release (annotations); on-disk only, not tracked in git. |
| `lmms-eval/` | Vendored eval framework — still a live dependency for the legacy InternVL3 lmms-eval leg (`analysis/run_eval_crossview.sbatch`, the `crossview` task config). |
| `paper/` | This project's write-up (`multicam_benchmark.tex`). |

## Attribution and licenses

- **All-Angles-Bench**: [repo](https://github.com/Chenyu-Wang567/All-Angles-Bench),
  [paper](https://arxiv.org/abs/2504.15280), MIT-licensed metadata; Ego-Exo4D imagery
  is governed by the Ego-Exo4D license and is not redistributed here.
- **MVU-Eval**: [repo](https://github.com/NJU-LINK/MVU-Eval),
  [paper](https://arxiv.org/abs/2511.07250),
  [data](https://huggingface.co/datasets/MVU-Eval-Team/MVU-Eval-Data) (Apache-2.0).
- **CrossView release**: UT Austin multi-camera dataset release; **MEVA** videos are
  CC-BY-4.0.
- Vendored trees: [EvolvingLMMs-Lab/lmms-eval](https://github.com/EvolvingLMMs-Lab/lmms-eval)
  and [tulerfeng/Video-R1](https://github.com/tulerfeng/Video-R1), whose authors we
  thank. Everything under `bench/` and `analysis/` is this project's own work.

This repo began as an evaluation harness for the CVBench dataset
([Hokhim2/CVBench](https://github.com/Hokhim2/CVBench)); that work is archived at tag
`cvbench-final`.

## Related repos

The shared team harness lives at
[adihebbalae/multicam-harness](https://github.com/adihebbalae/multicam-harness); a port
of this repo's `bench/` into that layout is maintained there.
