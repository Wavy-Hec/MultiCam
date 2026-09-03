# Working notes for this repo

Conventions and traps that are not obvious from reading the code. See `README.md`
for what the project is and how to run it.

## Layout

- `bench/` — the harness. This is the only thing that runs experiments. `run_bench.py`
  is the runner, `run_bench.sbatch` a thin env-var wrapper around it, `methods/` the
  arms, `backends/` the two model wrappers.
- `analysis/` — dataset converters, video fetchers, the record exporter, and the deck
  generators. Flat by convention; do not add subdirectories — the rule is for scripts,
  the gitignored output dirs (`figs_deck/`, `records/`, `logs/`) live there too.
  `analysis/README.md` indexes the scripts by kind and says which tracked JSON/TXT
  files are live eval subsets, fetch manifests, or generator defaults; add a line
  there when adding a script.
- `hosting/` — packaging and fetching for the CrossView video store.
- `Video-R1/` — vendored, but `src/eval_thinking.py` inside it is **ours**, not upstream.
- `bench/legacy/` — retired experiment entry points with no referrers, kept for
  provenance, not maintained.
- `docs/` — gitignored. Prose, runbooks, meeting notes, the task spec. The repo ships
  code; write-ups live outside git. `docs/archive/` holds superseded output whose
  generating script no longer exists; `docs/screenshots/` holds loose image exports.

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

**The checkout was renamed `~/CVBench` → `~/MultiCam`; the compat symlink is gone.**
The repo was renamed on disk on 2026-08-31, while jobs 92461/92462 were queued —
Slurm had already recorded `WorkDir`, `Command` and `StdOut` under the old absolute
path, and the pending tasks resolved all three through a compat symlink at
`~/CVBench`, removed on 2026-09-03. The three `.sbatch` files say `$HOME/MultiCam`,
so anything submitted since the rename was independent of the symlink. The conda
env is still `cvbench` and the sequential arm is still `cvbench_native` — both are
keys baked into 241 result filenames (`bench_<subset>_${ENV}<tag>_shard*.jsonl`),
`registry.json` and `records.jsonl`; renaming either orphans every historical leg.

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

**MEVA media is `.avi` on disk, and records must keep spelling it that way.**
`convert_crossview` defaults to `meva_ext='avi'`; do not regenerate subsets with
`mp4` — a `.mp4`-spelled record decodes the same file but loses the `media_remap`
stamp and misses the summary-cache keys.

**MEVA `.avi` must never reach a decoder.** decord returns the wrong frame on random
access into the release's AVI containers: the packets carry no pts, every seek lands
on keyframe 0 and decodes forward, so `vr[i]` comes back as frame `i` minus the
preceding keyframe index (`i mod 60` on the usual 60-frame grid) — every sighted arm
saw only the first seconds of each five-minute clip in every MEVA result produced
before 2026-08-27. `video_paths` resolves a record's `.avi` to the `.mp4` sibling
written by `hosting/remux_avi.py` (sequential decode identical; random access within
the H.264 reorder depth, at most three frames) and refuses to run without it
(`CVBENCH_ALLOW_AVI=1` only to reproduce the defect). Before submitting a MEVA leg:
`hosting/remux_avi.py --check` must exit 0, and the leg needs a NEW TAG — `run_bench`
refuses to resume into a file holding unstamped (pre-remux) rows. Rows since then
stamp `media_remap`, and the registry marks pre-remux legs `media_ok: false`.

## Before launching anything

Read `analysis/records/registry.json` — it records what has been run, with what config.
Regenerate it with `python3 analysis/export_question_records.py`. Prefer a filter over
that export to launching a new job.

- `registry.json` lists only registered legs; to ask whether a subset was ever run,
  test the results tree instead: `ls bench/results/ | grep "^bench_$(basename SUBSET .json)_"`
  — the two disagree (the results tree keys on more subset stems than the registry
  names). Never judge a subset dead from the registry alone.

## Git

- `origin` is the only remote. The original CVBench repo used to be wired up as
  `upstream` and was removed — this repo is not a GitHub fork of it, so nothing links
  the two any more. Do not add it back.
- Never `git push --all` — the local `backup/main-pre-scrub` branch holds an unpublished
  draft and must stay local.
- Keep results numbers, internal references and real names out of `README.md` and out of
  commit messages. Those belong in `docs/`, which is gitignored.
- Rendered figures, stats snapshots and result rows are regenerable and stay untracked.
  Curated question subsets are inputs and stay tracked. Their directory is not a key
  but their filename is — `run_bench.sbatch` builds the shard name from
  `basename "${SUBSET%.json}"` and `registry.json` stores the bare basename, so a
  subset can move between directories without touching a result filename, but
  renaming one orphans every leg that recorded the old name.
- `scratchpad/` is gitignored on purpose (staged launch scripts); it stays at the
  repo root because `analysis/export_question_records.py` cites the path.
