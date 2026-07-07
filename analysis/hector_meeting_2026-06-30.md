# Hector — Meeting Notes (Streaming Video QA Multi-Agent System)

**Meeting:** Streaming Video QA Multi-Agent System Research Meeting
**Date noted:** 2026-06-30
**Scope of this file:** *only the parts that involve Hector.* Everything about ReAgent-V,
streaming triggers, Christine/Lucas/Shawn's tasks, and the poster has been dropped except where
it gives you context. The full team summary lives in the original meeting notes.

> **What this is for:** a single page you can read/download to know (a) what you presented,
> (b) what the advisor actually asked for, and (c) exactly what you owe and by when — all
> cross-linked to your real CVBench numbers in
> [`analysis/adaptive_frames_experiment.md`](adaptive_frames_experiment.md).

---

## ⏱️ TL;DR — your action items

| # | Deliverable | Due | Status |
|---|---|---|---|
| **D1** | Slides / Google Doc clearly explaining the **clip-selection methodology** | Next meeting | to do |
| **D2** | Quantitative results: **stitching vs non-stitching** × **varying clip counts**, on CVBench (or the UT dataset) | **Wed 2026-07-01** (tomorrow) | ✅ data in hand — just assemble (see §3) |
| **D3** | A **principled, question-driven adaptive clip-selection** mechanism (not the current fixed sequential order) | ongoing research | design drafted (see §4) |

**The one sentence to remember:** the advisor reframed your priorities — **clip *selection*
(which clips, how many) is now the PRIMARY problem; intra-clip frame *sampling* is SECONDARY.**
Your duration-weighted frame work is the secondary decision; the new headline is question-driven
clip selection.

---

## 1. What you presented

- A **multi-clip video QA benchmark** on a subset of **temporally-correlated** questions, with
  **thinking mode now enabled**.
- **Weighted frame sampling** — the 64-frame budget is split **proportional to each clip's
  duration**: e.g. ~17 frames for a ~111–117 s clip, **~2 frames for a ~10 s clip**
  (your real worked example: cvb-974 → `[17, 17, 2, 28]`).
- **Preliminary finding:** duration-based **even-split** sampling slightly **outperforms
  stitching**, and the gap **grows as the number of clips increases**.
- **Your hypothesis:** many clips in the dataset are **independently answerable** — they don't
  need to reference each other — so cramming them into a single stitched frame is
  *counterproductive*.

---

## 2. The advisor's critical feedback (the part that changes your roadmap)

> **"There is no principled method for selecting *which* of the n available clips are relevant to
> a given question."**

- Right now selection is **sequential and fixed** — you feed all K clips in order. It is **not
  question-driven or adaptive**.
- The advisor's priority order, made explicit:
  1. **PRIMARY — clip selection:** *which* clips and *how many*. Getting this wrong directly causes
     wrong answers or context bloat.
  2. **SECONDARY — intra-clip frame sampling:** how many / which frames within a chosen clip.
- **Mandate:** resolve clip selection **before** optimizing frame-sampling strategy.

So: your frame-sampling work (duration-weighted, adaptive_content / adaptive_query) is the
*secondary* lever. The new center of gravity is **question-driven adaptive clip selection (D3).**

---

## 3. D2 — stitching vs non-stitching × clip count (Wednesday deliverable) ✅

You already have these numbers. CVBench **full-1000**, InternVL3-8B, 4 passes, temp 0.7,
64-frame budget. *Non-stitch* = clips shown sequentially; *stitch* = `centralized` 2×2 spatial
montage.

**Accuracy by clip count K (mean ± std over 4 passes):**

| method | K=2 (n=487) | K=3 (n=236) | K=4 (n=277) | all |
|---|---|---|---|---|
| non-stitch (duration) | 62.7 ± 1.0 | 60.4 ± 2.6 | **61.6 ± 0.6** | **61.8** |
| non-stitch (even) | 61.6 ± 0.8 | 59.9 ± 1.2 | 60.1 ± 1.2 | **60.8** |
| stitch (2×2) | 59.2 ± 1.4 | 59.6 ± 1.7 | **52.3 ± 2.9** | **57.4** |

**Δ (best non-stitch − stitch), by K:  K=2 +3.4 · K=3 +0.7 · K=4 +9.2 pts**

**What it shows (and why it backs your hypothesis):** stitching is roughly competitive at low K
but **collapses at K=4 (52.3% vs 61.6%, −9.2 pts)** — as more clips are packed into one 2×2
montage, each view loses effective resolution / temporal coverage and the model can't read them.
That is direct evidence that *forcing independently-answerable clips into one stitched frame
hurts*, and it gets worse exactly where clip selection matters most (more clips ⇒ more chance some
are irrelevant). This is the empirical motivation for **D3**.

*Figure + regenerator:* `d2_acc_by_clipcount.png`, regenerate with
`python bench/cvbench_d2_clipcount_fig.py` (no GPU; reads the pooled ALL JSONL).

---

## 4. D3 — principled adaptive clip selection (the primary problem)

Today clip selection is the **identity** (use all K, split budget by duration). Proposed
direction — lift the **CLIP-by-question idea you already built at the frame level** up to the
**clip level**:

1. **Score each clip's relevance to the question** — CLIP/SigLIP text-image similarity between the
   question and a cheap uniform thumbnail set per clip (or a lightweight VLM relevance pass).
2. **Select clips** — keep the top-`m` by relevance (or threshold) instead of always using all K.
   This *is* the "which clips / how many" decision the advisor flagged.
3. **Allocate the 64-frame budget by relevance** (not just duration) across selected clips — a
   relevance-weighted generalization of `allocate_frames`.
4. **Ablate** vs the fixed-sequential baseline: does question-driven selection beat "use
   everything," especially at larger K and when some clips are irrelevant?

This attacks the primary decision while reusing the infrastructure you built for the secondary one
(frame-level CLIP scoring + `frame_indices` plumbing).

---

## 5. D1 — what to put in the slides / Google Doc

- The **primary vs secondary** framing up front (clip selection first, frame sampling second).
- The pipeline end-to-end: **how many frames per clip** = `allocate_frames` (proportional,
  largest-remainder); **which frames within a clip** = backend's uniform sampler. Note explicitly
  that **clip selection itself is currently the identity** — that's the gap.
- **cvb-974 as the worked example** (10 s clip → 2 frames vs 194 s clip → 28 frames).
- The **D2 result** (§3) as the evidence, and the **D3 plan** (§4) as the path forward.

---

## 6. Where you fit in the team plan

- **You:** prepare presentation materials (slides or Google Doc), **deliver numeric results by
  Wednesday** (D2), and develop a clearer explanation of the **clip-selection methodology** before
  the next meeting. Then build the adaptive selection mechanism (D3).
- Others (context only): Christine → ReAgent-V toward streaming + OVO benchmarks; Lucas →
  additional baseline evals; Shawn → Em-Guard / StreamReady / Dispider trigger frameworks on
  OmniPro. **All baselines kept** for the paper even though ReAgent-V is the primary focus.
- Team norm reiterated: **send pre-meeting briefing materials in advance.**

---

## 7. Dates to keep on your radar

- **Wed 2026-07-01** — D2 numeric results due.
- **Next meeting** — D1 deck + clearer clip-selection methodology.
- **Jul 30–31, Washington DC** — DoD HPC UMI Symposium (~20 posters, incl. this project). Poster
  is high-level only, no implementation details; Christine finalizing with Shawn. Lucas presenting.
  *(Not your deliverable, but your work feeds the poster.)*

---

## Pointers

- **Your full, results-grounded working doc:** [`analysis/adaptive_frames_experiment.md`](adaptive_frames_experiment.md)
  (D1/D2/D3 + verified appendices on how frames are chosen today).
- **Method writeup:** `analysis/cvbench_temporal_method.md`.
- **D2 figure regenerator:** `bench/cvbench_d2_clipcount_fig.py`.
