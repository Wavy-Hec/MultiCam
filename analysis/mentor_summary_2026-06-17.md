# CVBench / CrossView — Multi-Camera VLM Benchmark Status

**Date:** 2026-06-17
**Models compared:** `Qwen3-VL-8B-Thinking` vs `InternVL3-8B`
**Goal:** Benchmark how well VLMs reason over *multiple synchronized camera views* of the same scene.

> **UPDATE 2026-06-22 — the Qwen re-run flagged below is DONE.** Validity issues #1
> (Event-Ordering 0/20) and #5 (parser) are resolved: re-ran with
> `--max_new_tokens 8192` + an abstain-on-truncation parser. Event-Ordering is now
> **7/20 (35%)**, Spatial 9/20, Temporal 3/20; 54/60 emit `<answer>`, 3 abstain.
> Overall is still 31.7% (19/60) **by coincidence**, but now on a legitimate answer
> set — reportable. CrossView graphs regenerated. Also scaled MEVA to a **1,033-Q**
> pool (Qwen 32.0%, InternVL3 34.0%). Everything below is the original 06-17 snapshot.

---

## TL;DR

We have two benchmarks wired into one harness and have run both models end-to-end with reasoning traces. Current headline numbers are **InternVL3 38.3% vs Qwen 31.7%** on the 60-question CrossView set — **but those numbers are not yet a fair comparison.** I audited exactly how each model is fed video and found several measurement artifacts and harness asymmetries that need fixing before we report anything. **Both model runs were full GPU inference** — two 8B thinking VLMs decoded on an L40S GPU via Slurm (`run_eval_crossview.sbatch`, `--gres=gpu:1`), not a CPU/toy run; only the *remaining* parser/analysis fixes below are CPU-only.

---

## What's being benchmarked

| Benchmark | Source | Subset | Videos per question |
|---|---|---|---|
| **CVBench / MVR** | HF `Dongyh35/CVBench` | 45 q | 1–4 *unrelated* clips |
| **CrossView / MEVA** | UT Austin SwarmLab Multi-Camera | 60 q | 2–4 *synchronized* camera views |

CrossView 60-q is balanced: **20 Event-Ordering / 20 Spatial / 20 Temporal**, all MEVA.
Both models get **8 frames per video**.

---

## How each model actually receives the video

| | **Qwen3-VL** | **InternVL3** |
|---|---|---|
| Clip markers | *text* `"Video k:"` | *rendered image frames* ("This is video k" / "Video k End") |
| Frame sampling (8/video) | endpoint-inclusive `linspace` (includes first & last frame) | segment **midpoints** (excludes first & last) |
| Vision tokens (4-video q) | ~11.5k (4 merged blocks/clip) | ~10.3k (256 tok/frame, 448×448 tiles) |
| Think prompt | ~90-word "ponder deeply…" template | ~30-word "reason step by step" |
| Generation stop | **no stop**, runs full 2048-token budget | **stops at first blank line** (`until: ["\n\n"]`) |

> The two models do not even sample the same frames from the same video, and are fed different vision-token budgets through different scaffolding.

---

## ⚠️ Validity issues found (the important part)

1. **Qwen's Event-Ordering 0/20 is a parsing artifact, not a capability result.** With no stop sequence and a 2048-token budget, Qwen's traces run off the end without ever emitting an `<answer>` tag, and the old parser then grabbed a stray letter ("a" from prose) as the answer. Gold is never "A" on Event-Ordering → 0/20 was mechanically guaranteed. **Do not report this as "Qwen can't order events."**

2. **The two harnesses stop generation differently** (no-stop vs `\n\n`). This single difference drives both the failure asymmetry and any output-token comparison being unfair.

3. **Asymmetric prompts + vision-token budgets** make a naive token comparison measure the harness, not the model.

4. **41 of 60 CrossView questions were down-capped from 5–12 cameras to ≤4** before either model saw them. So an "accuracy vs. number of cameras" curve is partly measuring questions the model never received at full camera count.

5. **Both answer-parsers had mirror-image bugs** (grabbing stray letters with no abstention). InternVL also sometimes maps a correct reasoning trace to the wrong answer letter.

---

## Current results (with caveats above)

| Model | CrossView 60-q accuracy |
|---|---|
| InternVL3-8B | **38.3% (23/60)** |
| Qwen3-VL-8B-Thinking | **31.7% (19/60)** — depressed by the truncation artifact |

These should be treated as **provisional** until the re-run below.

---

## Proposed next steps

> Note: the completed runs above were **GPU** inference (Qwen3-VL-8B + InternVL3-8B on an L40S). Only the prep below is CPU.

**CPU prep (done / runs on a login node):**
1. ✅ Parser hardened to **abstain** on a tagless/truncated trace instead of grabbing a stray letter (`Video-R1/src/eval_thinking.py`).
2. ✅ **Token accounting instrumented** on the Qwen leg — every result record now logs `text_tokens` / `video_tokens` (count of `<|video_pad|>`) / `total_input_tokens` / `num_frames` (`eval_thinking.py`). InternVL counts are analytic (258 × 10 × #videos). The accuracy-vs-token-budget curve script (extension of `crossview_camera_curve.py`) is the one remaining CPU step.

**Needs GPU (not yet run):**
3. Clean Qwen CrossView re-run (token budget → ~8192 + the hardened parser) **and** the missing CrossView **blind** baseline `eval_crossview_subset_qwen3vl_novideo.json` — the 0-video-token floor that anchors the token benchmark. Both come from one `RUN_BLIND=1 sbatch run_eval_crossview.sbatch`.

**Then:**
4. Structured failure taxonomy: failure-mode × task × camera-count × model.
5. Dataset expansion — widen MEVA to `re_identification` / `perception` types (videos already on disk; directly tests cross-view person re-ID, the core skill both models struggle with).

---

## Candidate datasets to grow the benchmark

| Dataset | Status | Note |
|---|---|---|
| MEVA extra types (re-ID, perception) | available | videos on disk; lowest-effort expansion |
| **AgiBot** (≤3 cams: head + 2 wrist) | **WIRED ✅** | converter + harness done; cap-safe (0 lossy). Videos gated on HF **Beta** — **NOT Alpha** (Alpha has only 1 of our 16 subset tasks). Incremental `analysis/fetch_agibot_videos.py --budget-gb N` pulls cheapest tars first; CC BY-NC-SA (non-commercial). See `agibot_setup.md`. |
| **Ego-Exo4D** (ego+exo views) | **WIRED ✅, license signed** | awaiting AWS creds (~48h); 40-q subset built; `egoexo` CLI installed. See `egoexo_setup.md`. |
| nuScenes (6-cam surround) | **SKIP** | fixed 6 cams → 100 % lossy under the ≤4 cap; revisit only if the cap is raised to ≥6. |

Combined subsets built: `crossview_combined_subset.json` (MEVA+EgoExo4D) and `crossview_full_subset.json` (MEVA+EgoExo4D+AgiBot, the full benchmark).

---

## Artifacts to look at

**The 60 questions we evaluated** (readable): `analysis/crossview_subset_questions.md`
— every CrossView/MEVA question with its options, gold answer, true camera count, and
videos-seen. (Underlying data: `analysis/crossview_subset.json`.)

**Benchmark charts** (`analysis/crossview_out/` unless noted):
- `accuracy_vs_orig_cameras_internvl3.png` — accuracy vs the **true synchronized-camera
  count** (the headline "multi-camera is hard" figure; InternVL3 = trustworthy).
- `accuracy_vs_orig_cameras.png` — same axis, both models (⚠️ Qwen series contaminated by
  the parsing artifact until the re-run).
- `accuracy_vs_cameras.png` — accuracy vs **#videos the model actually saw** (≤4).
- `accuracy_by_task_internvl3.png` / `accuracy_by_task.png` — accuracy by task type
  (Temporal / Event-Ordering / Spatial).
- CVBench (`analysis/`): `accuracy_vs_cameras.png` (contrast — CVBench does *not* degrade
  with #videos), `accuracy_by_task.png`, `accuracy_vs_temporal.png`,
  `temporal_complexity_dist.png`, `reasoning_gain.png` (with-video uplift over blind).
- Deck: `analysis/multicam_progress.pptx`.
- *Coming* (the token benchmark): accuracy-vs-video-token-budget / #frames curves with the
  blind 0-token floor — pending the GPU re-run + the `crossview_camera_curve.py` extension.

The 3 analysis tasks (blind exploitation, blind sanity, input pipeline) are written up in
`analysis/mentor_report.md` §4 and `blind_sanity.md` / `input_pipeline.md`.

---

## One-line ask for mentor

> We can produce a *fair* head-to-head once we (a) match the generation/stop settings, (b) fix the answer parsers, and (c) re-run Qwen with a larger budget. Should I prioritize the clean re-run + token report next, or the dataset expansion?
