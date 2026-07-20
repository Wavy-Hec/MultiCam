# CVBench: Multi-Camera Video QA Evaluation of Open VLMs

This repo evaluates **centralized vs. decentralized multi-camera harnesses** for video
question answering with open vision-language models — **Qwen3-VL-8B (Thinking)** and
**InternVL3-8B** — on two benchmarks:

- **CVBench** — 1,000 cross-video QA pairs, 2–4 clips per question, 15 task types.
- **CrossView / MEVA** — multi-camera surveillance QA over synchronized MEVA camera
  views from the CrossView release.

The core question: given the K clips of a question, is it better to fuse them into a
single model input (centralized — spatial stitching or budgeted temporal sequencing),
or to run one independent perception pass per stream and aggregate the text
descriptions (decentralized)?

Every arm runs 4 independent sampled passes (temperature 0.7, fixed seeds), so each
accuracy comes with a std. All runs keep the models' `<think>` traces so failures stay
interpretable. The harness reports accuracy (mean ± std) per model × harness, plus
per-task, per-camera-count, latency, and token breakdowns.

## Get started

### Environments

Two pre-provisioned conda envs on the cluster (no project venvs). The split exists
because transformers 5.x breaks InternVL3's `trust_remote_code` modeling files:

| env        | used for                        | transformers |
|------------|---------------------------------|--------------|
| `cvbench`  | Qwen3-VL legs, plots, analysis  | 5.2.0        |
| `internvl` | InternVL3-8B legs               | 4.48.3       |

The sbatch launcher picks the env via `ENV=...` (default `cvbench`).

### Data layout

- **CVBench videos**: `Video-R1/src/r1-v/Evaluation/CVBench/<group_dir>/<youtube_id>.mp4`
  — paths are taken verbatim from the subset JSON's `video_1..video_4` fields. Download
  the videos from the [HF dataset](https://huggingface.co/datasets/Dongyh35/CVBench)
  and place them there.
- **CrossView/MEVA videos**: annotations live in `crossview-release-annotations/`
  (on-disk only, not in git); videos are fetched per-file from a private HF shard repo
  — see `hosting/README.md`.
- **Question subsets**: JSONs under `analysis/`, e.g.
  `analysis/cvbench_full_runnable_subset.json` (the full 1,000 CVBench questions) and
  `analysis/crossview_meva1033_subset.json` (MEVA). The harness default `--video-root`
  is the CrossView release, so CVBench runs must set
  `VIDEO_ROOT=Video-R1/src/r1-v/Evaluation/CVBench`.
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

# full MEVA InternVL3 leg, sharded 8 ways:
ENV=internvl SUBSET=analysis/crossview_meva1033_subset.json BACKENDS=internvl3 \
  CHUNK=8 sbatch --array=0-7 bench/run_bench.sbatch

# full-1000 CVBench decentralized (per_stream) InternVL3 run, sharded 8 ways:
ENV=internvl SUBSET=analysis/cvbench_full_runnable_subset.json BACKENDS=internvl3 \
  METHODS=per_stream STREAM_KIND=video TAG=_fullperstream CHUNK=8 \
  VIDEO_ROOT=Video-R1/src/r1-v/Evaluation/CVBench \
  sbatch --array=0-7 bench/run_bench.sbatch

# stitch frame-budget sweep leg: the centralized 2x2-stitch arm at N frames per
# clip with nothing else changed (one leg per N; the sweep used N = 8/16/32/64/128).
# Note the 128-frame leg overruns InternVL3-8B's native context window and leans
# on the model's dynamic RoPE scaling — interpret that arm with care:
ENV=internvl SUBSET=analysis/cvbench_full_runnable_subset.json BACKENDS=internvl3 \
  METHODS=centralized MONTAGE_KIND=video NFRAMES=32 TAG=_fullstitch32 CHUNK=8 \
  VIDEO_ROOT=Video-R1/src/r1-v/Evaluation/CVBench \
  sbatch --array=0-7 bench/run_bench.sbatch
```

Useful knobs (env var → CLI flag, with defaults): `METHODS` (`centralized,per_stream`),
`BACKENDS` (`qwen3vl`), `NFRAMES` (8 frames/clip), `PASSES` (4), `SEEDS` (`1,2,3,4`),
`TEMPERATURE` (0.7), `BUDGET` (64 total frames for the temporal method), `WEIGHTING`
(`duration` | `even`), `STREAM_KIND` / `MONTAGE_KIND` (`camera` | `video` labels),
`MAX_NEW_TOKENS` (8192), `TAG` (suffix to separate runs sharing a subset+env). See the
header of `bench/run_bench.sbatch` and `python -m bench.run_bench --help` for the full
list.

### Scoring, reports, figures

```bash
# CPU-only gate: re-score a stored eval JSON through the bench parse+metrics path
# and confirm it reproduces the stored accuracy (no GPU, no model load):
python -m bench.validate_scoring [path/to/eval_*.json]

# summary table + plots from pooled result JSONLs:
python -m bench.plots --jsonl bench/results/<leg1>.jsonl bench/results/<leg2>.jsonl \
    --out-dir bench/results/figs_<name>

# one-command pool + report + figures for the CVBench full-1000 shards:
bash bench/finalize_cvbench_full.sh

# pool the stitch frame-budget sweep legs into one per-budget report — every leg
# records method='centralized', so this renames each leg's rows to stitch<NN>_f<N>
# (keyed by the leg's TAG) before reporting, keeping the arms distinct:
bash bench/pool_stitch_sweep.sh
```

## Methods

Method names are what you pass in `METHODS=` / `--methods` and what gets recorded in
each result row. All methods share the same question/options/`<think>`/`<answer>` text
scaffold, so only the visual presentation differs between arms.

| method | file | what it does |
|---|---|---|
| `centralized` | `bench/methods/centralized.py` + `stitch.py` | Centralized 2×2 stitch: temporally aligns the K clips and tiles the synchronized frames into labeled grid-montage images, fed to one model. `--montage-kind camera\|video` picks the cell labels. |
| `temporal_weighted` | `bench/methods/temporal.py` | Centralized temporal sequencing: one model sees the clips sequentially under a single total frame budget (default 64) split across clips in proportion to duration; `--weighting even` is the budget-matched control (recorded as `temporal_even`). |
| `cvbench_native` | `bench/methods/cvbench_native.py` | The benchmark's own presentation: each clip as a separate sequential video block at a flat per-clip `--nframes`. Baseline for the stitching comparison at equal frame budget. |
| `per_stream` | `bench/methods/per_stream.py` | Decentralized "1-VLM-per-stream": an independent perception pass per clip, then a text-only aggregation pass reasons over the K descriptions. Latency reported both serial and max-parallel. |
| `summary_select_route` / `summary_select_top1` | `bench/methods/clip_select.py` | Question-driven clip selection via cached per-clip text summaries (`bench/gen_clip_summaries.py`, passed with `--summaries`): one text-only selector call picks the clips, then the full frame budget is spent on the selection. |
| `clip_select_top{m}`, `clip_select_siglip_top{m}` | `bench/methods/clip_select.py` | No-LLM selector: score each clip by CLIP (or SigLIP) text–image similarity between the question and a few thumbnails, keep the top-m clips. |

Backends: `qwen3vl` (Qwen/Qwen3-VL-8B-Thinking; also `qwen3vl-instruct`) in
`bench/backends/qwen.py`, `internvl3` (OpenGVLab/InternVL3-8B) in
`bench/backends/internvl.py`.

## Repo layout

| path | contents |
|---|---|
| `bench/` | The harness: `run_bench.py` / `run_bench.sbatch` (runner + Slurm launcher), `methods/` (the arms above), `backends/` (Qwen3-VL, InternVL3), `metrics.py`, `plots.py`, `report.py`, `validate_scoring.py` (CPU gate), figure scripts. Results land in `bench/results/` (untracked). |
| `analysis/` | Question subsets, subset/data builders, job scripts, and run logs. Intentionally flat; scripts cross-reference these paths. |
| `Video-R1/` | Vendored from upstream: the eval scaffold and the CVBench videos under `src/r1-v/Evaluation/CVBench/`; plus this fork's own `src/eval_thinking.py` (thinking-trace eval entry point whose parse/scoring helpers `bench/reuse.py` imports). |
| `hosting/` | Tooling to shard/upload/fetch the CrossView videos via a private HF dataset repo (store-mode zips, per-file HTTP range fetch). |
| `crossview-release-annotations/` | CrossView dataset release (annotations); on-disk only, not tracked in git. |
| `lmms-eval/` | Vendored eval framework — still a live dependency for the legacy InternVL3 lmms-eval legs (`analysis/run_eval*.sbatch`, the `crossview`/`mvr` task configs). |
| `paper/` | This project's write-up (`multicam_benchmark.tex`). |

## Attribution

This repo is a fork of [Hokhim2/CVBench](https://github.com/Hokhim2/CVBench), the
dataset/eval repo for the CVBench benchmark:

- Paper: http://arxiv.org/abs/2508.19542
- Dataset: https://huggingface.co/datasets/Dongyh35/CVBench

The upstream code (kept here as the vendored `Video-R1/` and `lmms-eval/` trees) is in
turn adapted from [EvolvingLMMs-Lab/lmms-eval](https://github.com/EvolvingLMMs-Lab/lmms-eval)
and [tulerfeng/Video-R1](https://github.com/tulerfeng/Video-R1), whose authors we also
thank. Everything under `bench/` and `analysis/` is this project's own work on top of
that foundation.

**Dataset citation** (cite this for the CVBench benchmark itself, not for this harness):

```bibtex
@misc{cvbench2025,
  title={CVBench: A Benchmark for Cross-Video Multimodal Reasoning},
  author={CVBench Team},
  year={2025},
  url={https://huggingface.co/datasets/Dongyh35/CVBench}
}
```

## Related repos

The shared team harness lives at
[adihebbalae/multicam-harness](https://github.com/adihebbalae/multicam-harness); a port
of this repo's `bench/` into that layout is in progress there.
