# MultiCam: Multi-Camera Visual QA Evaluation of Open VLMs

Given a question about a scene observed by several cameras, is it better to fuse
the views into a single model input, or to run the model once per view and reason
over the text descriptions? This repo benchmarks that question with open
vision-language models (Qwen3-VL-8B Thinking, Qwen2.5-VL-7B Instruct,
InternVL3-8B) across three presentation harnesses:

- **Native** — each view or clip fed sequentially to one model, unmodified.
- **Centralized (stitch)** — the views are tiled into labeled grid-montage images
  and fed as one unified visual input.
- **Decentralized (per-stream)** — one independent perception pass per view, then
  a text-only aggregation pass reasons over the descriptions.

Every arm runs multiple sampled passes so each accuracy carries a std, and all
runs keep the models' reasoning traces so failures stay interpretable.

## Benchmarks

- **All-Angles-Bench** — multi-view still-image QA over synchronized camera views
  of the same scene (counting, relative direction, camera pose, cross-view
  correspondence).
- **MVU-Eval** — multi-video QA with up to thirteen clips per question, including
  synchronized multi-camera driving and cross-angle sports subsets.
- **CrossView / MEVA** — multi-camera surveillance video QA over synchronized
  MEVA views.

## Quick start

Two conda envs are used (`cvbench` for Qwen legs and analysis; `internvl` for
InternVL3, which needs an older transformers). Benchmark data lives under
`data/` (untracked); question subsets are JSONs under `analysis/`, produced by
the converter scripts there (`convert_allangles.py`, `convert_mvueval.py`,
`convert_crossview.py`).

All-Angles-Bench downloads from its HF release; its Ego-Exo4D scenes additionally
require accepting the Ego-Exo4D license. MVU-Eval downloads from its HF release.
CrossView/MEVA setup is described in `hosting/README.md`.

Runs go through `bench/run_bench.sbatch`, a thin env-var wrapper around
`python -m bench.run_bench` (Slurm-array sharded, resumable):

```bash
# All-Angles-Bench, all three arms:
SUBSET=analysis/allangles_dev_subset.json VIDEO_ROOT=data/allangles \
  METHODS=cvbench_native,centralized,per_stream MONTAGE_KIND=view STREAM_KIND=view \
  CELL_PX=1024 sbatch bench/run_bench.sbatch

# MVU-Eval, decentralized arm, InternVL3:
ENV=internvl SUBSET=analysis/mvueval_dev_subset.json VIDEO_ROOT=data/mvueval \
  METHODS=per_stream STREAM_KIND=video BACKENDS=internvl3 \
  sbatch bench/run_bench.sbatch
```

On still-image sets raise `CELL_PX`: the centralized arm resizes every view into a
`CELL_PX` square montage cell, so the default gives it far fewer visual tokens per
view than the native arm, which sees the images at source resolution. A larger cell
narrows that gap rather than closing it — compare the recorded `input_tokens` across
arms before reading a centralized-vs-native difference as an architecture effect.

See the header of `bench/run_bench.sbatch` and `python -m bench.run_bench --help`
for the full set of knobs.

Scoring and figures: `python -m bench.plots` builds the summary table and plots
from result JSONLs (one benchmark per call); `python -m bench.chance_level`
prints a subset's random-guessing floor; `analysis/allangles_consistency.py`
reports paired-question consistency for All-Angles-Bench. Results land in
`bench/results/` (untracked).

## Attribution and licenses

- **All-Angles-Bench**: [repo](https://github.com/Chenyu-Wang567/All-Angles-Bench),
  [paper](https://arxiv.org/abs/2504.15280) (MIT metadata; Ego-Exo4D imagery is
  governed by the Ego-Exo4D license and not redistributed here).
- **MVU-Eval**: [repo](https://github.com/NJU-LINK/MVU-Eval),
  [paper](https://arxiv.org/abs/2511.07250),
  [data](https://huggingface.co/datasets/MVU-Eval-Team/MVU-Eval-Data) (Apache-2.0).
- **CrossView release**: UT Austin multi-camera dataset; **MEVA** videos are CC-BY-4.0.
- Vendored trees: [EvolvingLMMs-Lab/lmms-eval](https://github.com/EvolvingLMMs-Lab/lmms-eval)
  and [tulerfeng/Video-R1](https://github.com/tulerfeng/Video-R1), whose authors we
  thank. Everything under `bench/` and `analysis/` is this project's own work.

This repo began as an evaluation harness for the CVBench dataset
([Hokhim2/CVBench](https://github.com/Hokhim2/CVBench)); that work is archived at
tag `cvbench-final`.

The shared team harness lives at
[adihebbalae/multicam-harness](https://github.com/adihebbalae/multicam-harness).
