# Multi-Camera Video QA — Project Status & Experiment-Plan Gap Analysis

**Date:** 2026-07-01
**Scope:** Consolidated status of (1) live/running state, (2) the Multi-Clip Video QA / temporal work, and (3) the formal centralized-vs-decentralized experiment plan. Every claim below was cross-checked against repo code, generated reports, and raw result JSONL.

---

## 0. Live state (as of 2026-07-01)

**Nothing is running.** No SLURM jobs in queue, no Python/bench processes, no logs or result files touched in the last 24h. Last repo activity: the meeting note (2026-06-30 08:27) and the D2 clip-count figure regenerated 2026-07-01 08:46.

> ⚠️ `analysis/adaptive_frames_experiment.md` mentions adaptive frame runs on **SLURM array 58447** as "live / results pending" — that array is **not running now**. The `adaptive_content` / `adaptive_query` Appendix-B rows are still `_pending_`; the array either died or finished without being recorded. Decision point (see §4).

---

## 1. Multi-Clip Video QA — the update (temporal experiment)

*This is the standup content, verified against the repo. Every headline number below reproduces from the raw run data.*

Multi-clip QA on the temporally-correlated CVBench subset, with **duration-weighted frame sampling** — the 64-frame budget split by clip length (worked example **cvb-974 → 17/17/2/28**: durations 111.2 / 117.0 / 9.9 / 193.7 s). Sequential clips beat 2×2 stitching, and the gap grows with more clips — likely because many clips are independently answerable, so stitching hurts.

**Flagged limitation:** there is currently **no method for which clips are relevant to the question** — all *n* clips are fed in a fixed sequential order, so it is **not** question-driven or adaptive yet.

**Advisor feedback:** *clip selection* (which clips, how many) is the **PRIMARY** decision; *frame sampling* is **SECONDARY**. (The meeting note attributes this to "the advisor" and does not name Dr. Datta — check attribution before quoting. Exact logged quote: *"There is no principled method for selecting which of the n available clips are relevant to a given question."*)

**By Wed (2026-07-01):** stitch vs non-stitch by clip count on CVBench — the stitch **collapses at 4 clips (52.3% vs 61.6%)**.

**Next:** a clear methodology writeup, then a **question-driven adaptive clip-selection** mechanism — score each clip's relevance to the question, keep the ones that matter, and spend the budget there.

### 1a. Verified results (full-1000 CVBench, InternVL3-8B, 4 passes, temp 0.7, 64-frame budget)

| Method | Overall acc | Raw count |
|---|---|---|
| temporal_weighted (duration) | **61.8% ± 0.7** | 2473 / 4000 |
| temporal_even | 60.8% ± 0.8 | 2431 / 4000 |
| centralized (2×2 stitch) | 57.4% ± 1.4 | 2297 / 4000 |

**By clip count K** (stitch collapse):

| K | stitch (2×2) | non-stitch (weighted) | Δ |
|---|---|---|---|
| 2 | 59.2% | 62.7% | +3.4 |
| 3 | 59.6% | 60.4% | +0.7 |
| 4 | **52.3%** (580/1108) | **61.6%** (682/1108) | **+9.2** |

> **Wording nuance:** "gap grows with more clips" is only *loosely* true — non-stitch wins at every K, but the per-K gap is **non-monotone** (+3.4 → +0.7 → +9.2); it dips at K=3 before the K=4 collapse. Safer phrasing: *"non-stitch wins at every clip count, and the gap blows open at 4 clips."*

Source of truth: `bench/results/bench_cvbench_full_runnable_subset_internvl_ALL_report.{md,csv}` (12,000 rows = 3 arms × 1000 Q × 4 passes; SLURM arrays 58246/58247/58248). Regenerate the D2 figure with `python bench/cvbench_d2_clipcount_fig.py` (no GPU).

### 1b. Deliverable status (from the 2026-06-30 meeting note)

| ID | Deliverable | Status |
|---|---|---|
| **D2** | Stitch vs non-stitch by clip count (due Wed 2026-07-01) | ✅ **DONE** — data in hand, table + `analysis/d2_acc_by_clipcount.png` regenerated today |
| **D1** | Methodology slides / Google Doc | ⏳ **Not started as slides** — the markdown writeup `analysis/cvbench_temporal_method.md` is complete and is the source material, but no deck exists |
| **D3** | Question-driven adaptive **clip** selection | 🟡 **Design only** — see mismatch note below |

**D3 mismatch to watch:** `bench/methods/adaptive.py` exists and *is* wired into the runner (`adaptive_content`, `adaptive_query`), but it does **within-clip FRAME selection** (motion keyframes / CLIP text-image scoring of *frames*) — **not clip selection**. All K clips are still kept and the duration-weighted per-clip budget is unchanged. So what's built is the *secondary* (frame) lever the advisor de-prioritized; the *primary* lever (scoring which **clips** matter) is not implemented. The reusable primitive for D3 is `adaptive_query`'s CLIP scorer, lifted from frame- to clip-granularity.

### 1c. Uncommitted state

`bench/run_bench.py` + `bench/backends/internvl.py` modified; `bench/methods/adaptive.py` **untracked** — together the adaptive-frame plumbing (a `frame_indices` override path + `consumes_frame_indices` guard + an index-clamp bugfix). Internally consistent, reads as finished, but **not committed**. Plus untracked docs/figures. Nothing lost; nothing committed.

---

## 2. Formal Experiment Plan (the proposal)

*Reproduced as given, for reference. §3 audits the repo against this.*

### Prior Work in Vision-Language Models

Vision-language models inherently possess limited context windows, rendering the naive parsing of continuous multi-camera streams into the context window inadequate for complex question answering. Furthermore, these models are prone to hallucination. Existing literature highlights three primary failure modes in this domain: the inability to count objects correctly due to neuro-symbolic limitations, the confounding of visual details across objects known as the binding problem, and a phenomenon of blind faith where models exclusively default to language priors when confronted with conflicting visual evidence [1, 2, 3, 4]. When adapted to process video data, current multi-modal language models continue to demonstrate significant gaps in visual and temporal understanding, particularly concerning activity and motion [5]. Our own preliminary investigations, including Neus-QA and NSVS, explicitly demonstrate this temporal reasoning deficit when models are tasked with questions requiring the composition of multiple events in a prescribed sequence for single-camera understanding.

### Objective and Hypothesis

Despite the introduction of multi-camera datasets, there is a critical absence of targeted analysis regarding the specific failure modes of vision-language models when reasoning across multiple distinct camera streams. Because multi-camera videos are highly data-intensive, simply stitching the footage together will rapidly exhaust the model's context window and natively yield poor responses. Consequently, the mechanism by which multi-camera inputs are presented to the model — called the **"harness"** — is critical. This presentation can be **centralized**, where multiple camera inputs are visually organized into a coherent stream for the model to interpret, or **decentralized**, where the model independently processes single-camera perspectives and centrally aggregates the resulting textual information for downstream reasoning.

Our primary objective is to systematically uncover the common failure modes associated with these distinct harnesses. Insight into multi-camera understanding failures will form the foundational basis for designing harnesses for organizing complex multi-camera video streams.

We hypothesize that neither harness will achieve universal superiority across all question typologies. Specifically, we anticipate that **centralized** harnesses will exhibit superior performance on tasks requiring complex spatio-temporal reasoning across disjoint views, whereas **decentralized** harnesses will excel in foundational perception tasks, such as object counting per perspective.

### Experiment Plan

To test this hypothesis, we propose the evaluation of two distinct multi-camera harnesses.

1. **Centralized method** — temporally aligns the video streams and spatially stitches the corresponding images across multiple views to provide a unified input for question answering.
2. **Decentralized method** — the model analyzes each single-camera perspective independently, generates textual summaries pertinent to the given query for each stream, and subsequently aggregates these distinct informational sources in a centralized text-based module to formulate the final answer. *(2nd step does not require video.)*

### Metrics and Datasets

Evaluation on the **CVBench** and **CrossView** datasets. Comparative performance measured against core metrics: general video-QA accuracy and latency, segmented across question categories and number of cameras.

### Plots

- **Table 1 — General Video QA Accuracy:** overall accuracy + std (4 independent passes) for all configurations of the two selected models across both harnesses [4 methods]. Columns: Methods, Harness, Accuracy.
- **Plot 1 — QA Accuracy per Question Category (bar):** Y = accuracy (std error bars), X = question types; grouped bars per model+harness.
- **Plot 2 — Latency Analysis:** X = Methods; Y = inference time (ms), per question.
- **Plot 3 — Accuracy vs. Camera Count (line):** X = number of cameras; Y = accuracy.
- **Plot 4 — Accuracy per Question Type vs. Camera Count (line):** X = number of cameras; Y = accuracy, per question category.

---

## 3. Gap analysis — have we done the formal plan?

**Short answer:** the *pipeline* for the formal plan is fully built and validated end-to-end; the *experiment at scale* is not done. All four configs co-occur only in a 3-question smoke test; the dev-scale run is CrossView + Qwen only, with a half-complete decentralized arm; CVBench has **zero** decentralized runs.

### 3a. Element-by-element

| Proposal element | Status | Detail |
|---|---|---|
| **(A) Centralized harness** (align + spatial stitch) | ✅ **Done** | `bench/methods/centralized.py` + `stitch.py`: proportional frame alignment, `grid_layout` (K≤4 → 2×2), labeled cells, single VLM call. Wired in `run_bench.py`; 10,276 rows run incl. CrossView. |
| **(B) Decentralized harness** (per-cam text summary → text-only aggregate) | ✅ **Done** (code) | `bench/methods/per_stream.py` — **verified genuine 2-step map-reduce**: step 1 = independent VLM call per camera emitting query-relevant text; step 2 = **text-only** aggregator (zero pixels). A 4-camera row shows `num_model_calls=5` (4 perception + 1 aggregate). **Not** the temporal non-stitch method. |
| **Two models** | 🟡 **Partial** | Both backends runnable: InternVL3-8B + Qwen3-VL-8B (Thinking/Instruct). **Qwen2.5-VL specifically is not wired** (commented out, not cached) — the real 2nd model is Qwen3-VL. No single run pairs 2 distinct models × both harnesses. |
| **CVBench dataset** | 🟡 **Partial** | Centralized runs exist at full-1000 scale, but only as part of the *temporal* experiment (centralized vs temporal_even/weighted). **No decentralized (`per_stream`) run on CVBench at all.** Single model (InternVL3). |
| **CrossView dataset** | 🟡 **Partial** | Fully wired (MEVA + EgoExo4D local; AgiBot gated/not local). Real formal both-harness run exists but **Qwen-only, 50 Q**, decentralized arm 27/50 ids. |
| **Table 1** (4 configs, 4-pass std) | 🟡 **Partial** | Generator `bench/plots.py::table1()` done. **All 4 configs co-occur only in the n=3 smoke** (`figs_smoke/table1.csv`, n=12). Dev run (`figs_dev_combined`, 50 Q) is **Qwen-only** — `dev_combined_internvl.jsonl` is 0 bytes. Never on CVBench. |
| **Plot 1** (acc per category, bar) | 🟡 **Partial** | `plot1_category` done; PNGs exist. Full 2×2 only at n=12 smoke; dev figure Qwen-only; CrossView-only. |
| **Plot 2** (latency ms) | ✅ **Done** (instrumentation) / 🟡 partial (final figure) | Per-question latency fully instrumented in **both** backends (`time.perf_counter` around generate) → `latency_s`, `perception_latency_par/serial_s`, `aggregate_latency_s` in every row; `plot2_latency` renders ms box plots. Only the final formal 4-config figure is unrendered. |
| **Plot 3** (acc vs #cameras, line) | 🟡 **Partial** | `plot3_cameras` done (X = real `orig_num_cameras`). Same coverage gap. ⚠️ Do **not** confuse with the temporal clip-count figures (`cvbench_d2_clipcount_fig.py`, `cvbench_temporal_figs.py`) — those relabel the axis as *clips* and compare stitch-vs-sequential, not centralized-vs-decentralized. |
| **Plot 4** (acc per type vs #cameras, line) | 🟡 **Partial** | `plot4_category_cameras` done (task_type × camera cross-tab). Full version only at n=12 smoke (very sparse); dev Qwen-only. |

### 3b. Real formal-harness numbers that exist today

**CrossView dev run (`figs_dev_combined`, Qwen3-VL-8B-Thinking only, 50 Q, 4 passes):**

| Harness | Accuracy | n |
|---|---|---|
| Centralized | 42.0% ± 2.0 | 200 |
| Decentralized | 30.13% ± 6.72 | 106 (only 27/50 ids) |

**Smoke run (`figs_smoke`, all 4 configs, n=12 = 3 Q × 4 passes — plumbing validation only, not a real eval):**

| Config | Accuracy |
|---|---|
| InternVL3-8B · Centralized | 41.67% ± 27.64 |
| Qwen3-VL · Centralized | 50.0% ± 16.67 |
| InternVL3-8B · Decentralized | 25.0% ± 27.64 |
| Qwen3-VL · Decentralized | 0.0% ± 0.0 |

> ⚠️ The larger CrossView numbers floating in the tree — `analysis/crossview_meva1033_out` (Qwen 32.0% / InternVL3 34.0%, n=1033) — were produced by the **OLD two-leg thinking harness** with plain `video_1..4` ingestion. They have **no** stitch-centralized vs text-decentralized contrast and do **not** satisfy the formal spec.

---

## 4. What's needed to finish the formal plan

1. **Run InternVL3 through the formal harness.** `dev_combined_internvl.jsonl` is 0 bytes — the InternVL leg never executed on CrossView. This is the single biggest gap (2 of 4 Table-1 configs missing).
2. **Complete the Qwen decentralized arm** on CrossView (27/50 → 50/50 ids; 106 → 200 rows).
3. **Run centralized + decentralized on CVBench.** Currently CVBench has zero `per_stream` rows; the CVBench centralized numbers live only inside the temporal experiment.
4. **Scale past 50 questions** toward the full CrossView pool for meaningful per-category × per-camera-count breakdowns (Plots 1/3/4 are sparse at dev scale).
5. **Render the final formal 4-config figure set** (Table 1 + Plots 1–4) once the runs above land — the generators (`bench/plots.py`) already exist and are validated.

### Decision points

- **Temporal side:** relaunch the dead adaptive-frame array (58447) vs. skip it and go straight to clip-level selection (advisor said frame sampling is secondary).
- **Commit** the adaptive WIP + untracked docs/figures so nothing floats.
- **D1 deck** from the existing `cvbench_temporal_method.md`.

---

## Appendix — key files

| Purpose | Path |
|---|---|
| Centralized harness | `bench/methods/centralized.py`, `bench/methods/stitch.py` |
| Decentralized harness (2-step) | `bench/methods/per_stream.py` |
| Temporal methods | `bench/methods/temporal.py` |
| Adaptive frame selection (WIP, untracked) | `bench/methods/adaptive.py` |
| Table 1 + Plots 1–4 generator | `bench/plots.py` (+ `bench/metrics.py`) |
| Backends | `bench/backends/internvl.py`, `bench/backends/qwen.py` |
| Runner | `bench/run_bench.py` |
| CVBench full-1000 report (temporal) | `bench/results/bench_cvbench_full_runnable_subset_internvl_ALL_report.{md,csv}` |
| Formal-harness dev run (CrossView, Qwen) | `bench/results/figs_dev_combined/` (table1.csv, plot1–4 PNGs) |
| Formal-harness smoke (all 4 configs, n=3) | `bench/results/figs_smoke/` |
| CrossView subset | `analysis/crossview_combined_subset.json` (`analysis/convert_crossview.py`) |
| D2 clip-count figure | `analysis/d2_acc_by_clipcount.png` (`bench/cvbench_d2_clipcount_fig.py`) |
| Methodology writeup | `analysis/cvbench_temporal_method.md` |
| Adaptive experiment doc | `analysis/adaptive_frames_experiment.md` |
| Meeting note | `analysis/hector_meeting_2026-06-30.md` |
