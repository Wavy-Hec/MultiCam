# Multi-Camera Video QA — Status Update: Next-Steps Audit + Stitch-Crop Verdict

**Date:** 2026-07-07
**Scope:** (1) Status of the two mentor next-steps — decentralized harness on CVBench and question-driven clip selection — with the completed D3 130-set results; (2) definitive re-verification of the 2×2 stitch crop question (Harsh vs. aspect-preserving debate). Every number below was recomputed from raw shard JSONL by an independent pass and reproduced exactly; the stitch claims were adversarially re-checked against the *current* (uncommitted) working tree today.

---

## 0. Live state (as of 2026-07-07)

Two jobs **PENDING** on `gpul40q` (both Reason=Priority, backfill estimate **2026-07-09 12:32**):

| Job | Name | What it is |
|---|---|---|
| **63727** [0-7] | `bench-multicam` | **The decentralized CVBench run** — `METHODS=per_stream BACKENDS=internvl3 STREAM_KIND=video SUBSET=analysis/cvbench_full_runnable_subset.json TAG=_fullperstream`, full 1000 Q, 4 passes, 16 h walltime. Outputs → `bench/results/bench_cvbench_full_runnable_subset_internvl_fullperstream_shard{0..7}.jsonl` |
| **63676** | `clipsel-gate-smoke` | CLIP-B/32 vs SigLIP-so400m scorer gate (`analysis/clip_scorer_gate.py`) + 5-question `clip_select_siglip_top1/top4` smoke |

> ⚠️ **Commit before Thursday:** job 63727 reads the repo at start time and depends on the **uncommitted** diffs (`per_stream.py` `stream_kind`, `run_bench.py` `--stream-kind` + clip-select registration + resume-key fix, `run_bench.sbatch` STREAM_KIND/SUMMARIES plumbing). Reverting or breaking those before it starts would fail the run or silently fall back to the "camera view" prompt (the ~5-pt labeling artifact, job 58000).

---

## 1. Next-step ①: Decentralized harness on CVBench — **queued, not run**

- CVBench still has **zero `per_stream` rows**. The only existing per_stream results (`bench_crossview_combined_subset_cvbench_shard*`) are the **CrossView benchmark with Qwen3-VL-Thinking** — the `_cvbench` in those filenames is the *conda env name*, not the dataset. Do not quote them as CVBench decentralized numbers.
- **Per-question category results will be automatic:** every record in `cvbench_full_runnable_subset.json` carries `task_type` (15 categories), the harness copies it into every result row, and `bench/metrics.py` emits `by_task_type` in every summary — exactly as the completed ALL report already does for the three "use everything" methods (temporal_weighted **61.8 ± 0.7%** > temporal_even 60.8 ± 0.8% > centralized 2×2 stitch 57.4 ± 1.4%, n=4000 each).
- After the 8 shards finish, run the same merge step used for `bench_cvbench_full_runnable_subset_internvl_ALL` to get the per-category report.

---

## 2. Next-step ②: Question-driven clip selection — **done on the 130-set (2026-07-02); selection does NOT beat "use everything" yet**

The D3 eval that MEMORY/docs had as "in flight" is **complete**: 130 temporal questions × 3 arms × 4 passes = 1,560 records, 0 errors, 0 missing, summaries 100% cache hits (357-clip cache). Source: `bench/results/bench_cvbench_temporal_subset_internvl_clipsel_shard{0..7}.jsonl`; baselines (identical 130-id set, verified) from the Jun 27 `dur/even/stitch` shards.

### 2a. Headline (pooled 4 passes, n=520/arm)

| Arm | Acc | vs temporal_weighted 55.8% |
|---|---|---|
| `summary_select_route` (LLM selector over cached clip summaries; may keep ALL) | **53.8%** (280/520) | **−1.9** |
| `summary_select_top1` (forced 1 clip — hard-pruning diagnostic) | 45.6% (237/520) | −10.2 |
| `clip_select_top1` (CLIP ViT-B/32 text↔thumbnail similarity, no LLM) | 37.1% (193/520) | −18.7 |
| *baseline* temporal_weighted (use everything) | **55.8%** (290/520) | — |
| *baseline* temporal_even | 51.5% (268/520) | — |
| *baseline* centralized 2×2 stitch | 51.5% (268/520) | — |

### 2b. Ablation vs "use everything" by clip count — the "biggest gains at large n" hypothesis

| n clips (Q) | route | weighted | stitch | route vs weighted |
|---|---|---|---|---|
| 2 (48) | 60.4% | **63.5%** | 62.5% | −3.1 |
| 3 (23) | 41.3% | **50.0%** | 51.1% | −8.7 |
| 4 (59) | **53.4%** | 51.7% | 42.8% | **+1.7** (vs stitch **+10.6**) |

**Verdict: the hypothesis holds only at n=4, and weakly.** Route pruned 49/130 questions; matched on those questions it scores 53.1% vs the baseline's 58.2% (net −10 correct answers). Pruning helps only at n=4 (+4.0 pts on 25 Q — within noise given per-pass stds of 1.4–4.4 pts) and clearly hurts at n=2/3. On the 81 kept-ALL questions route reproduces temporal_weighted **byte-identically** (324/324 predictions), confirming the harness plumbing and isolating pruning as the only lever. Clip counts only span 2–4 here — the "large n" regime where irrelevant clips dominate barely exists in this subset, which is the charitable reading of the negative result.

### 2c. What remains for D3

- **SigLIP has never scored anything.** `clip_select_top1` ran only with CLIP-B/32 (worst arm). The `clip_scorer_gate.py` pre-check (named-clip recall@1/@2, margin, gold-option agreement) is written but unrun — that is pending job **63676**. Gate first; don't spend full-1000 GPU-hours on `clip_select_*` if the scorer can't even find named clips.
- **k-subsets built, nothing run:** `analysis/cvbench_full_k34_subset.json` (513 recs; K=3:236, K=4:277) and `cvbench_full_k4_subset.json` (277 recs) exist for full-1000 top-m arms (top-2 needs K≥3, top-3 needs K=4; `top_m ≥ K` reproduces temporal_weighted byte-identically, so other bins compose from existing baseline rows).
- v1 splits the frame budget by **duration** even after selection (`present_selected()` has a relevance-weights hook for v2) — current results isolate the *selection* lever only.
- Token accounting: all arms spend the full 64-frame budget (~17.2k answer-call input tokens); route adds only a ~585-token text-only selector call.

---

## 3. Stitch crop question — settled (re-verified 2026-07-07 against current working tree)

**Definitive sentence:** *No cropping — the full field of view of every camera reaches the model — but the resize is NOT aspect-preserving either: each whole frame is anisotropically squashed into a square 448×448 cell by the plain `frame.resize((cell_w, cell_h))` at `bench/methods/stitch.py:92`, the only geometry op on the model-input path; there is no letterbox padding anywhere.* So "cells are trimmed" is wrong, **and** "aspect-preserving resize + padded" is also wrong — it's option three: **anisotropic full-frame resize**.

Full audit: `analysis/stitch_crop_audit.md` (2026-07-06). Today's re-verification (4 adversarial passes + empirical re-run):

- **Empirical re-run reproduces exactly** (`python analysis/stitch_crop_audit.py`, internvl env, no GPU): MEVA id=0 (1920×1080 ×2, 352×240, 1920×1072) and CVBench cvb-3 (four portrait 1080×1920) → 896×940 montages, max |montage cell − full-frame resize| = **[0,0,0,0]** on every clip → `VERDICT: NO CROPPING`. Evidence PNGs rewritten byte-identical (deterministic).
- **Working-tree drift checked:** `stitch.py` and `centralized.py` are byte-identical to HEAD, so every line citation still resolves. The uncommitted `internvl.py` diff is **geometry-neutral** (adds an optional `frame_indices` override to `load_video` + clamping; the montage/image branch is untouched, `max_tiles=1` default unchanged in all three places).
- **Backend near-miss dismissed:** `internvl.py:77 resized_img.crop(box)` is a full-coverage tiling partition (at `max_tiles=1` the single box is the whole resized image) — zero pixels discarded. Qwen path: `do_resize=False`, `smart_resize` aspect-preserving, zero crop code.
- **Label bands do not occlude and ARE model input:** the 22px "Camera i"/"Video i" band is *extra canvas height*; the frame is pasted below it (`stitch.py:77–93`). The opaque badges Harsh may have seen (`qual_make_figs.py:62,:78`, `cvbench_report_figs.py:152,:165`) exist only in human-facing figure PNGs — those scripts are `__main__`-only and imported nowhere in the harness; slides label via PPTX text boxes beside frames.
- **CVBench vs MEVA paths are geometrically identical** — only the label text/preamble differ.
- Two scope footnotes: (a) the new `clip_select.py` CLIP scorer's HF processor center-crops its *selection thumbnails* to 224 — ranking input only, never seen by the answering VLM; (b) `lmms-eval`'s separator frames (`make_markers.py`) are whole synthetic inserted frames in that separate pipeline, not badges over video pixels.

**Slack-ready evidence images:** `analysis/stitch_audit_meva.png`, `analysis/stitch_audit_cvbench.png` — raw frames (native dims) → actual pipeline montage → cell vs full-resize (diff 0) vs the letterbox alternative the pipeline does *not* produce.

**Real cost of stitching (not cropping):** the double squash (source → 448² cell; then 896×940 montage → 448² at `max_tiles=1`) leaves each camera ≈224×214 effective px — consistent with the stitch collapse at K=4 (52.3% vs 61.6%).

---

## 4. Action items

1. **Commit the working-tree diffs** (`per_stream.py`, `run_bench.py`, `run_bench.sbatch`, `internvl.py`) plus the untracked D3 files before job 63727's ~Thu start.
2. When 63727 lands: merge shards → ALL-style report → per-`task_type` decentralized-vs-centralized table (the formal Table 1 comparison).
3. When 63676 lands: read the gate numbers; only if SigLIP materially beats CLIP-B/32 on named-clip recall, queue `clip_select_siglip_top{1,2}` on the k-subsets.
4. D3 writeup framing: lead with the honest negative (route −1.9 overall), the n=4 crossover, and the byte-identical kept-ALL check as evidence the comparison is apples-to-apples.
