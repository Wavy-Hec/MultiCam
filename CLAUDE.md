# Working notes for this repo

Conventions and traps that are not obvious from reading the code. See `README.md`
for what the project is and how to run it.

## Layout

- `bench/` — the harness. This is the only thing that runs experiments. `run_bench.py`
  is the runner, `run_bench.sbatch` a thin env-var wrapper around it, `methods/` the
  arms, `backends/` the two model wrappers.
- `analysis/` — dataset converters, video fetchers, the record exporter, and the deck
  generators. Flat by convention; do not add subdirectories.
- `hosting/` — packaging and fetching for the CrossView video store.
- `Video-R1/` — vendored, but `src/eval_thinking.py` inside it is **ours**, not upstream.
- `docs/` — gitignored. Prose, runbooks, meeting notes, the task spec. The repo ships
  code; write-ups live outside git.

## Environments

Two conda envs, both required:

- `cvbench` — Qwen legs and all analysis. A clone of `vlm` plus `decord`.
- `internvl` — InternVL3 only; it needs an older transformers, and `cvbench`'s newer
  one breaks the InternVL3 remote code.

Never create a project-local `.venv`. `analysis/setup_env.sh` builds `cvbench`.

## Traps

**Queued Slurm jobs read `bench/` Python at job-start, not at submit time.** Slurm
copies the batch script when you submit, so editing `run_bench.sbatch` cannot affect
a submitted job — but editing anything under `bench/` or `Video-R1/src/` can, and a
pending array task will pick up whatever is on disk when it starts. Editing harness
semantics while an array is draining splits one run across two code versions. Check
`squeue` before touching harness code, and prefer landing changes between campaigns.

**`bench/reuse.py` imports `eval_thinking` by path.** It does a `sys.path.insert` on
`Video-R1/src/` so the harness scores identically to the eval entry point. Moving or
renaming that file breaks every job that starts afterwards.

**The montage arm's visual budget is not the same as the sequential arm's.** The
centralized arm resizes every view into a `CELL_PX` square cell, and on the InternVL
backend it is `INTERNVL_MAX_TILES` — not `CELL_PX` — that sets the montage's token
count, because the backend re-tiles the canvas by aspect ratio. The sequential arm
scales with the number of views; the montage saturates. Compare `input_tokens` and
`video_tokens` across arms within a fixed camera count before reading any
centralized-vs-sequential difference as an architecture effect.

**Reasoning is imposed by the prompt, not by a model switch.** Neither backend has a
thinking toggle. `REASONING=0` swaps in a direct-answer template; the `<answer>` tags
stay so one parser serves both modes.

**`CHUNK` is the shard count, not the shard size.** Sharding is strided
(`data[offset::chunk]`), so `CHUNK` must equal the array width. Passing a record count
silently runs a handful of questions per shard and still writes a normal-looking
summary.

**MEVA media is `.avi`.** `convert_crossview.convert(..., require_local_root=...)`
returns nothing unless `meva_ext='avi'` is passed; the default is `.mp4`.

## Before launching anything

Read `analysis/records/registry.json` — it records what has been run, with what config.
Regenerate it with `python3 analysis/export_question_records.py`. Prefer a filter over
that export to launching a new job.

## Git

- `origin` is the only remote. The original CVBench repo used to be wired up as
  `upstream` and was removed — this repo is not a GitHub fork of it, so nothing links
  the two any more. Do not add it back.
- Never `git push --all` — the local `backup/main-pre-scrub` branch holds an unpublished
  draft and must stay local.
- Keep results numbers, internal references and real names out of `README.md` and out of
  commit messages. Those belong in `docs/`, which is gitignored.
- Rendered figures, stats snapshots and result rows are regenerable and stay untracked.
  Curated question subsets are inputs and stay tracked.
