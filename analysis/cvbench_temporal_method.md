# CVBench — Duration-Weighted Temporal Sequencing

*Mentor's "Next tasks" — implementation + experiment writeup.*
*Status: code landed; 130-question 3-way run on InternVL3 in progress; full-1000 download running. This doc is updated as results land.*

---

## 1. What was asked (the 6 sub-tasks) and how each is met

| # | Mentor's task | How it's implemented |
|---|---|---|
| 1 | **Arrange the videos in sequence** (Vid1 → Vid2 → Vid3) | The K clips of a question are fed to the model **sequentially** in their given `video_1..video_N` order, each preceded by a `=== Video k of K ===` banner. We do **not** reorder them — some CVBench questions *ask* for the chronological order (permutation answers), so the given index order is presented and the model reasons about ordering. |
| 2 | **64-frame budget weighted by duration** (2m/4m/2m → 16/32/16) | A single **total** budget (default 64) is split across the clips **in proportion to each clip's duration** via largest-remainder apportionment (`allocate_frames`). Reproduces the board's example exactly: `[120,240,120]s → [16,32,16]`. |
| 3 | **Sample frames uniformly within each clip** up to its allotment | Each clip is passed as a `{"type":"video","nframes":n_k}` block; the backend samples `n_k` frames **uniformly** across that clip's full duration (`internvl.load_video` / Qwen `process_vision_info`). |
| 4 | **Enable reasoning mode** | The `<think>…</think> / <answer>…</answer>` scaffold (`QUESTION_TEMPLATE`) is in every prompt; `max_new_tokens=8192`. The full reasoning trace is now **persisted** to the results JSONL (`response_text`, `think`) so failures are interpretable. |
| 5 | **Prompts that disambiguate which frames belong to which video** | A prefix paragraph explains the sequential, duration-weighted layout; each clip gets a `=== Video k of K — n_k frames sampled uniformly across its full duration (~Ds) ===` banner; frames are labeled `Frame1, Frame2, …` within each clip. |
| 6 | **Confirm the "2×2 case" is the spatial stitching** | **Confirmed — yes.** See §4. |

---

## 2. The "130 set" and the full set

- **130 set** = `analysis/cvbench_temporal_subset.json` — the CVBench *temporal-logic* questions (rule-based `temporal_level ≥ 1`): **130 questions, 357 distinct clips, 2/3/4 clips per question = 48/23/59.** All 357 clips are present on disk and decode (the stale `cvbench_temporal_missing.txt` predates the Jun-25 download — ignore it).
- **Full set** = the 1000-question `CVBench.json`. It references **1315 distinct clips**; 435 were on disk, **880 are being downloaded** from the public HF dataset (`Dongyh35/CVBench`) for the overnight run. The runnable subset is rebuilt by `analysis/make_cvbench_full_runnable_subset.py` as clips arrive.

---

## 3. The duration-weighted frame allocator

`bench/methods/temporal.py :: allocate_frames(weights, budget=64, floor=2, caps=None)`

1. **Proportional split** of the whole budget by clip weight (duration), using **largest-remainder (Hamilton)** apportionment so the per-clip counts **sum exactly to the budget**. Pure proportional when nothing else binds → `[120,240,120] → [16,32,16]`.
2. **Caps**: a clip is never asked for more frames than it physically has (`len(VideoReader)`); any surplus is redistributed to the other clips.
3. **Floor** (default 2) is a **safety net only** — applied *after* the proportional split, it raises a clip whose share rounded below 2 up to 2 (borrowing from the clips most above their own floor). On the real 130 it never fires, so the split stays purely proportional.

**Worked examples (verified against the live module):**

| Durations (s) | Allocation (budget 64) | Note |
|---|---|---|
| `[120, 240, 120]` | `[16, 32, 16]` | the board's canonical example, reproduced exactly |
| `[146.6, 258.1]` (cvb-0, 2 clips) | `[23, 41]` | longer clip gets more |
| `[146.6, 52.1, 99.5]` | `[32, 11, 21]` | uneven 3-clip |
| `[52.1, 99.5, 58.3, 152.6]` (cvb-15, 4 clips) | `[9, 18, 10, 27]` | 4-clip, sums to 64 |
| `[130, 3]` | `[62, 2]` | floor net guarantees the tiny clip ≥ 2 |

All 130 questions verified: every allocation sums to 64 and respects per-clip frame caps.

---

## 4. The 2×2 question — answered

**Yes — the "2×2 case" is the spatial-stitching method we already use, named `centralized` in the harness** (`bench/methods/centralized.py` + `bench/methods/stitch.py`).

- `stitch.grid_layout(k)` tiles the K synchronized frames into a grid: 1 clip → 1×1, 2 → 1×2, **3–4 clips → 2×2** (one empty cell for k=3). The grid is built with PIL, each cell labeled.
- For CVBench's *independent* clips it runs with `--montage-kind video` (cells labeled "Video i", with a preamble that says the clips are unrelated rather than synchronized).
- This is the method behind the earlier "stitching helps" results. So the temporal-sequencing method here is a **different** presentation (sequential frames, duration-weighted budget) that we now compare **head-to-head against** the 2×2 spatial stitch at an equal 64-frame budget.

---

## 5. The 3-way experiment (equal 64-frame budget, InternVL3-8B, 4 passes)

All three arms run on the **same** 130 questions, **same** backend (InternVL3-8B under the `internvl` conda env), **same** total frame budget (64), **4 sampled passes** (temp 0.7, seeds 1-4) for std error bars.

| Arm | Method | What it isolates |
|---|---|---|
| **A. duration-weighted** | `temporal_weighted` (`--weighting duration`) | the new method — frames split by clip duration |
| **B. even split (control)** | `temporal_even` (`--weighting even`) | identical sequencing/markers/total, but frames split **evenly** ⇒ isolates *"does duration weighting help?"* (this is the budget-matched `cvbench_native`) |
| **C. 2×2 spatial stitch** | `centralized --montage-kind video` | the spatial baseline (the "2×2 case") |

> Arms A and B use distinct result labels (`temporal_weighted` vs `temporal_even`) so they don't collide on the JSONL resume key.

**Reporting:** accuracy ± std by method, **and within each clip-count stratum (2/3/4 clips)** — the 48/23/59 mix means a pooled headline can hide a Simpson's-paradox effect, so per-stratum is the honest comparison.

---

## 6. How to run

```bash
# Arm A — duration-weighted, 4-pass, InternVL3, CVBench videos
ENV=internvl BACKENDS=internvl3 METHODS=temporal_weighted WEIGHTING=duration \
  SUBSET=analysis/cvbench_temporal_subset.json \
  VIDEO_ROOT=Video-R1/src/r1-v/Evaluation/CVBench \
  BUDGET=64 FLOOR=2 PASSES=4 SEEDS=1,2,3,4 TEMPERATURE=0.7 MAX_NEW_TOKENS=8192 \
  OUT=bench/results/bench_cvbench_temporal_internvl.jsonl \
  CHUNK=4 sbatch --array=0-3 bench/run_bench.sbatch

# Arm B — even split: same command with WEIGHTING=even
# Arm C — 2x2 stitch: METHODS=centralized MONTAGE_KIND=video NFRAMES=16

# Report
python -m bench.report --jsonl bench/results/bench_cvbench_temporal_internvl.jsonl
```

For the overnight full set: after the download finishes, `python analysis/make_cvbench_full_runnable_subset.py` rebuilds `analysis/cvbench_full_runnable_subset.json`, then the same three arms run with `SUBSET=analysis/cvbench_full_runnable_subset.json`.

---

## 7. Results

*(filled in as the runs complete)*

### 130-question set — InternVL3-8B, 64-frame budget, 4 passes

| Method | Accuracy ± std | 2-clip | 3-clip | 4-clip |
|---|---|---|---|---|
| temporal_weighted (duration) | _pending_ | | | |
| temporal_even (control) | _pending_ | | | |
| centralized (2×2 stitch) | _pending_ | | | |

### Full set — _pending download + run_

---

## 8. Files

| File | Role |
|---|---|
| `bench/methods/temporal.py` | `TemporalWeightedMethod` + `allocate_frames` / `largest_remainder` |
| `bench/methods/base.py` | `Result` gains `response_text`, `think`, `frame_alloc` |
| `bench/run_bench.py` | registers method; `--budget` / `--floor` / `--weighting` |
| `bench/run_bench.sbatch` | `BUDGET` / `FLOOR` / `WEIGHTING` env passthrough |
| `analysis/make_cvbench_temporal_subset.py` | builds the 130 temporal-logic subset |
| `analysis/make_cvbench_full_runnable_subset.py` | builds the full runnable subset (grows with the download) |
| `analysis/cvbench_temporal_subset.json` | the 130 questions |
