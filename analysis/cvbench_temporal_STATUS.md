# CVBench Temporal — Run Status & Handoff (2026-06-28)

Companion to `cvbench_temporal_method.md` (the method writeup). This doc captures
**what is new in this session**, **how the inputs are fed to the model**, and **how
to finalize the in-flight full run** (including whether you can close Claude Code).

---

## TL;DR — what's new this session

1. **130-question 3-way run finished and is now reported + verified.** Duration-weighted
   sampling **wins by +4.3 pts** over the budget-matched even split at the *same* 64-frame
   budget, and is 4× more seed-stable (±0.7 vs ±2.7). Numbers below; full table in
   `cvbench_temporal_method.md §7`.
2. **Full-1000 run is executing** on SLURM (3 arms × 8 shards). Download fully succeeded —
   **1000 runnable questions, 0 blocked.**
3. **Finalization is now one command** (`bench/finalize_cvbench_full.sh`) so the full-set
   report/figures don't depend on keeping Claude Code open.

---

## 130-question result (InternVL3-8B, 64-frame budget, 4 passes) — VERIFIED

| Method | Accuracy ± std | 2-clip | 3-clip | 4-clip | in-tok | abstain/err |
|---|---|---|---|---|---|---|
| **temporal_weighted (duration)** | **55.8 ± 0.7%** | 63.5% | 50.0% | **51.7%** | 17.2k | 0% / 0 |
| temporal_even (budget-matched control) | 51.5 ± 2.7% | 59.9% | 43.5% | 47.9% | 17.2k | 0% / 0 |
| centralized (2×2 spatial stitch) | 51.5 ± 2.6% | 62.5% | 51.1% | 42.8% | 4.4k | 0% / 0 |

The gain concentrates at **4 clips** (+8.9 over stitch) — exactly where clip-length disparity
is largest and the 2×2 grid crushes each clip to ¼ resolution. Stitch degrades monotonically
with clip count (62.5 → 51.1 → 42.8); duration-weighting holds flat.

**Verification (independent re-derivation from raw JSONL):** all 3 arms cover the *same* 130 Q
× 4 passes, *identical* 48/23/59 clip mix (no Simpson's-paradox confound), budget locked at 64,
weighting tags correct, 0 errors — and the recomputed acc±std exactly matches `report.py`.

Artifacts: `bench/results/bench_cvbench_temporal_subset_internvl_ALL.jsonl`,
`…_ALL_report.{md,csv}`, `bench/results/figs_temporal_130/{acc_by_method,acc_by_numclips,acc_by_task}.png`.

---

## How we put the inputs into the model

Each CVBench question references **K independent clips (K ≤ 4)**. We compare **three ways of
presenting those K clips to one VLM at the same 64-frame budget:**

### A. Duration-weighted sequential (the new method — `temporal_weighted`)
The K clips are fed **one after another** as separate video blocks. A single **total** budget of
64 frames is split across the clips **in proportion to each clip's duration** (largest-remainder
apportionment, summing to exactly 64); within each clip the frames are sampled **uniformly**. A
banner announces each clip so the model can tell them apart. Built in
`bench/methods/temporal.py :: TemporalWeightedMethod._prepare`. The content list is:

```
[text]  <prefix: K clips, sequential, 64 frames split by duration, banners explained>
[text]  === Video 1 of K — n₁ frames … (~D₁s); clip 1 of the sequence ===
[video] clip 1   (nframes = n₁, sampled uniformly)
[text]  === Video 2 of K — n₂ frames … (~D₂s); clip 2 of the sequence ===
[video] clip 2   (nframes = n₂)
   … one (banner, video) pair per clip …
[text]  <scaffold: question + options + <think>/<answer> reasoning instructions>
```

### B. Even split (the control — `temporal_even`)
**Byte-for-byte identical** framing and banners, but the 64 frames are split **evenly**
(64/K per clip). This is the only thing that differs from A → it isolates *"does weighting help?"*

### C. 2×2 spatial stitch (the baseline — `centralized`, `--montage-kind video`)
The clips' frames are tiled into a **single composite 2×2 grid image** (per timestep), 16 frames
each. Cheaper in tokens (~4.4k vs ~17k) because tiling shrinks the pixels, but each clip loses
resolution — which is why it collapses as clips are added.

### Worked example — the *literal* prompt for `cvb-974` (4 clips)

A construction-timelapse question whose four clips are segments seg1–seg4 (durations
111 / 117 / **10** / **194** s). Duration-weighting allocates frames where the footage is:

| clip | duration | **duration-weighted** | even (control) |
|---|---|---|---|
| Video 1 | 111.2 s | 17 | 16 |
| Video 2 | 117.0 s | 17 | 16 |
| Video 3 | **9.9 s** | **2** | 16 |
| Video 4 | **193.7 s** | **28** | 16 |
| **total** | | **64** | 64 |

The tiny 10 s clip needs only 2 frames; weighting redirects the freed frames to the 194 s clip
(28 vs 16). **The exact text the model receives:**

```
The following 4 video clips are INDEPENDENT (different, unrelated scenes) and are
presented SEQUENTIALLY, one after another. They are NOT time-synchronized. A total
budget of 64 frames is split across the 4 clips in proportion to each clip's duration
(longer clips get more frames); within each clip the frames are sampled UNIFORMLY
across its full duration. A banner '=== Video k of 4 ===' precedes each clip's frames,
and frames are labeled Frame1, Frame2, ... within that clip. Keep track of which frames
belong to which Video; reason about each Video separately and then jointly to answer.

=== Video 1 of 4 — 17 frames sampled uniformly across its full duration (~111s); clip 1 of the sequence ===
<17 frames of C3iI6S7TuCA_seg1.mp4>
=== Video 2 of 4 — 17 frames sampled uniformly across its full duration (~117s); clip 2 of the sequence ===
<17 frames of C3iI6S7TuCA_seg2.mp4>
=== Video 3 of 4 — 2 frames sampled uniformly across its full duration (~10s); clip 3 of the sequence ===
<2 frames of C3iI6S7TuCA_seg3.mp4>
=== Video 4 of 4 — 28 frames sampled uniformly across its full duration (~194s); clip 4 of the sequence ===
<28 frames of C3iI6S7TuCA_seg4.mp4>

Select the best answer to the following multiple-choice question based on all the listed videos.
According to the videos, how does the construction project progress from its beginning to final stages?
A. Earthwork - foundation - structural framework - interior and exterior finishes.
B. Structural framework - roofing - earthwork - interior finishes.
C. Interior finishes - earthwork - foundation - structural framework.
D. Exterior finishes - structural framework - roofing - earthwork.
Please think about this question … Provide your detailed reasoning between the <think> and
</think> tags, and then give your final answer between the <answer> and </answer> tags.
Provide only the single option letter (A, B, C, or D) within the <answer> </answer> tags.
```

Model answered **A** (correct). The full `<think>` trace is persisted per row in
`Result.response_text` / `Result.think` (mentor's "enable reasoning mode" → interpretable failures).
Reproduce this rendering with the snippet in `cvbench_temporal_method.md §9 (Appendix)`.

---

## Full-1000 run — status & how to finalize

3 arms over `analysis/cvbench_full_runnable_subset.json` (1000 Q), InternVL3-8B, 4-pass,
64-frame budget. SLURM arrays:

| Arm | Job | Output prefix |
|---|---|---|
| duration-weighted | `58246` (fulldur) | `…_internvl_fulldur_shard*.jsonl` |
| even split | `58247` (fulleven) | `…_internvl_fulleven_shard*.jsonl` |
| 2×2 stitch | `58248` (stitch, queued) | `…_internvl_<stitch>_shard*.jsonl` |

**To finalize (after all jobs leave `squeue`):**
```bash
cd ~/CVBench && bash bench/finalize_cvbench_full.sh
```
This pools every full-run shard, renders `…_ALL_report.{md,csv}` and the figures under
`bench/results/figs_temporal_full/`, and prints the headline + per-#clips numbers to paste into
`cvbench_temporal_method.md §7`. It's idempotent and discriminates arms by the `method` field,
so it works regardless of the stitch arm's exact filename.

---

## Can I close Claude Code?

**Yes — the benchmark is unaffected.** The SLURM jobs run on the cluster's GPU nodes, completely
independent of Claude Code; results stream to `bench/results/*.jsonl` on disk no matter what.

The *only* thing tied to a live Claude session is the **auto-finalize convenience** (Claude turning
raw results into the report/figures/table). So:

- **Leave Claude open** → it auto-finalizes when the run completes (a background monitor is watching
  the queue) and writes the full-set §7 table for you.
- **Close Claude** → totally fine. When you're back, run `bash bench/finalize_cvbench_full.sh`
  (≈1 min) to produce the report + figures, then reopen Claude to fill in the prose table if you want.
