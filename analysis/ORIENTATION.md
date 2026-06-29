# ORIENTATION — CVBench / CrossView Multi-Camera VLM Benchmark

> "Where can I look to understand everything we did, and see how the inputs and outputs were enabled."
> This is the single starting document. Every claim below is anchored to a real `file:line`. Read top to bottom once, then use it as a map.

Repo root: `/home/hectorlugo02/CVBench` · branch `crossview-benchmark` · all paths absolute.

---

## Table of contents

1. [What this project is](#1-what-this-project-is)
2. [Reading order — start here](#2-reading-order--start-here)
3. [The end-to-end pipeline](#3-the-end-to-end-pipeline)
4. [How INPUTS are enabled (Qwen leg vs InternVL leg)](#4-how-inputs-are-enabled-qwen-leg-vs-internvl-leg)
5. [How OUTPUTS are enabled (parsing, abstain, scoring, schema)](#5-how-outputs-are-enabled-parsing-abstain-scoring-schema)
6. [Datasets](#6-datasets)
7. [How to run it](#7-how-to-run-it)
8. [Results inventory](#8-results-inventory)
9. [Headline numbers & key findings](#9-headline-numbers--key-findings)
10. [Glossary](#10-glossary)

---

## 1. What this project is

We benchmark how vision-language models *reason over multiple synchronized (or unrelated) camera views*, and we read the failures off the models' own `<think>` traces. Two benchmarks share one "thinking" eval harness: **CVBench / MVR** (HF `Dongyh35/CVBench`, 1–4 unrelated clips per question) and **CrossView** (UT Austin Multi-Camera, 2–4 synchronized views per question, capped to ≤4). Two models are compared: **Qwen3-VL-8B-Thinking** (its own harness, `Video-R1/src/eval_thinking.py`) vs **InternVL3-8B** (`lmms-eval` `crossview_think` / `mvr_think` task). The advisor deliverable is **failure-mode analysis** — accuracy is the means, the interpretable `<think>` traces are the end.

---

## 2. Reading order — start here

1. `/home/hectorlugo02/CVBench/analysis/README.md` — pipeline index, headline numbers, dataset status, run commands.
2. `/home/hectorlugo02/CVBench/analysis/mentor_report.md` — canonical living report: findings + validity issues (§6 incl. the Event-Ordering artifact and its fix).
3. `/home/hectorlugo02/CVBench/analysis/mentor_summary_2026-06-17.md` — dated snapshot with the `2026-06-22` UPDATE banner (re-run done, MEVA scaled to 1,033).
4. `/home/hectorlugo02/CVBench/analysis/input_pipeline.md` — verified trace of question JSON → model input (frame sampling, ordering, vision-token layout) per leg.
5. `/home/hectorlugo02/CVBench/analysis/blind_sanity.md` — proof the no-video baseline is genuinely text-only (0 vision tokens, no metadata leak, 40% recounted 3 ways).
6. `/home/hectorlugo02/CVBench/analysis/crossview_subset_questions.md` — the 60 CrossView questions with gold answers, true camera count, cap flags.
7. CVBench failure cases grouped by task type, traces quoted verbatim — regenerate the full `qwen3vl_failures.md` / `internvl3_failures.md` dumps on demand via `analyze_failures.py` (no longer tracked; the distilled taxonomy is item 8).
8. `/home/hectorlugo02/CVBench/analysis/crossview_meva1033_out/failure_examples_curated.md` — the 1,033-Q failure taxonomy digest (the headline failure table).
9. Dataset extensions when needed: `/home/hectorlugo02/CVBench/analysis/egoexo_setup.md`, `/home/hectorlugo02/CVBench/analysis/agibot_setup.md`.

---

## 3. The end-to-end pipeline

```
                 raw annotations                          subset + fetch list
crossview-release-annotations/  ──convert_crossview.py──►  crossview_*_subset.json
  (+ HF Dongyh35/CVBench)         (select_subset.py for      (+ _fetch.json, _videos.txt)
                                   the 45-Q CVBench set)               │
                                                                       │ fetch_meva_videos.py --subset …
                                                                       │ fetch_egoexo_videos.py (gated)
                                                                       ▼
                                                          local clips (.avi MEVA / .mp4 EgoExo4D)
                                                          under  Video-R1/src/r1-v/Evaluation/CVBench/
                                                          and    crossview-release-annotations/crossview-release/
                                                                       │
                       ┌─────────────────────────── sbatch ───────────┴────────────────────────┐
                       │  run_eval.sbatch (CVBench)   run_eval_crossview.sbatch (CrossView)      │
                       │  run_eval_novideo.sbatch (blind)                                        │
                       ▼                                                                          ▼
        eval_thinking.py  (Qwen leg)                            lmms-eval  crossview_think / mvr_think  (InternVL leg)
                       │                                                       │ logs/.../*_samples_*.jsonl
                       ▼                                                       ▼  parse_lmms_samples.py
   Video-R1/src/r1-v/eval_results/eval_*_qwen3vl[_novideo].json    analysis/crossview_internvl3*_normalized.json
                       │                                                       │
                       └───────────────────────────┬───────────────────────────┘
                                                    ▼
                  analyze_failures.py ──► crossview_out*/{qwen3vl,internvl3}_failures.md (regen on demand), accuracy_by_cameras.json
                  crossview_camera_curve.py ──► accuracy_vs_orig_cameras*.png, crossview_camera_curve.md (regen on demand)
                  plot_accuracy.py ──► accuracy_vs_cameras.png, accuracy_by_task.png
                  crossview_vs_cvbench.py ──► cvbench_vs_crossview.md (regen on demand)
                  make_slides_v2.py ──► multicam_progress_v2.pptx
   verification:  inspect_inputs.py ──► input_pipeline.md   ·   inspect_blind.py ──► blind_sanity.md
```

Pipeline-map source: `/home/hectorlugo02/CVBench/analysis/README.md:40` (dependency map) and `:45-77` (per-leg arrows).

---

## 4. How INPUTS are enabled (Qwen leg vs InternVL leg)

Both legs read the same `*_subset.json` records (`id`, `task_type`, `video_1..4`, `question`, `options`, `answer`) and both sample **8 frames per video**, but they differ in *which* 8 frames, *how* they mark "this is video k", and *how* video becomes vision tokens.

### 4a. Qwen leg — `/home/hectorlugo02/CVBench/Video-R1/src/eval_thinking.py`

- **Frame count default = 8**: `--nframes type=int default=8` at `eval_thinking.py:168`; `--max_new_tokens default=2048` at `:169` (raised to 8192 at run time — see §5).
- **Message assembly**: `build_messages(rec, video_root, nframes, no_video=False)` at `eval_thinking.py:121` interleaves a text marker before each clip. The marker is a literal text node `{"type":"text","text": f"Video {k}:"}` at `eval_thinking.py:141`, followed by the video node at `:142`, inside the `if not no_video:` loop.
- **Think prompt**: `QUESTION_TEMPLATE` at `eval_thinking.py:40-48`. The body begins with the `{Question}\n` substitution (line 41); the "Please think about this question as if you were a human pondering deeply…" instruction is line 42; the `<think>…</think>` / `<answer>…</answer>` instruction is lines 46-47.
- **Frame sampling formula (linspace, endpoint-inclusive, fps-ignored)**: `torch.linspace(0, total_frames-1, 8).round()`, documented at `input_pipeline.md:67` and present in the installed `qwen_vl_utils 0.0.14` (`vision_process.py:317`). It **always includes frame 0 and the last frame**.
- **No re-sampling**: `return_video_metadata=True` is passed to `process_vision_info` at `eval_thinking.py:213` — REQUIRED, or the HF processor silently re-samples to 4 frames and the timestamps become meaningless. The package's `do_sample_frames` defaults to `False` (`vision_process.py:528`).
- **Vision-token layout**: each video expands to `nframes/2 = 4` vision blocks (temporal merge of 2 frames per block), each block `<T seconds><|vision_start|><|video_pad|>×N<|vision_end|>` with `N = (H/32)·(W/32)` (≈720 for the observed 640×1152). See `input_pipeline.md:84`.
- **Blind / no-video path**: `if not no_video:` at `eval_thinking.py:139` guards the entire video-interleaving loop; with `--no_video` the content list is a single text item, prompts unchanged. Audited in `blind_sanity.md:24`.

### 4b. InternVL leg — `lmms-eval`

- **Prompt construction**: `mvr_doc_to_text_think()` at `/home/hectorlugo02/CVBench/lmms-eval/lmms_eval/tasks/mvr/utils.py:297` builds `option_prompt + question + options + THINK_INSTRUCTION + post_prompt`. The think instruction `THINK_INSTRUCTION` ("Reason step by step over ALL the listed videos… `<think>`…`</think>`, then `<answer>`…`</answer>`") is at `utils.py:286`. No `<image>` markers here — they are added by the model wrapper.
- **Video path resolution**: `mvr_doc_to_visual()` at `utils.py:101` returns `[cache_dir + '/' + doc[f'video_{i}'] for i in range(1,5) if doc[f'video_{i}'] is not None]`.
- **Frame count default = 8**: `num_frame: int = 8` at `/home/hectorlugo02/CVBench/lmms-eval/lmms_eval/models/internvl2.py:180`.
- **Frame sampling formula (segment midpoints, endpoints EXCLUDED)**: `get_index(...)` at `internvl2.py:91` computes `frame_indices = [int(start_idx + (seg_size/2) + round(seg_size*idx)) for idx in range(num_segments)]` where `seg_size = (end-start)/8`. It **never samples frame 0 or the last frame**. Documented at `input_pipeline.md:126`.
- **Per-frame preprocessing**: `load_video(..., input_size=448, max_num=1, num_segments=8)` at `internvl2.py:103` calls `dynamic_preprocess(...)` at `:52` per frame; `max_num=1` forces 1×1 tiling → exactly one 448×448 tile per frame.
- **Multi-video assembly (the `len(visuals) > 1` branch)** at `internvl2.py:345`: for each video `j`, load a marker image `start_img`, the 8 frames, and an end marker `end_img`, concatenate `[start, frames, end]`. Marker filenames at `:350` (`./res/video{j+1}.png`, `./res/end{j+1}.png`); slot accounting `num_patches_lists += [1] + num_patches_list + [1]` at `:358` → **10 slots per video (1 + 8 + 1)**, each frame ≈258 vision tokens (`input_pipeline.md:136`, `:154`). The frame-slot text `Frame{i+1}: <image>\n` is built at `:360`. (The single-video fallback `else:` at `:363-370` is a different code path.)
- **Marker CWD gotcha**: `res/video{1-4}.png` / `res/end{1-4}.png` are loaded relative to the `lmms-eval/` CWD — run from the wrong directory and markers silently fail to load.

### 4c. Comparison table

| Mechanism | Qwen3-VL-8B-Thinking | InternVL3-8B |
|---|---|---|
| Entry point | `eval_thinking.py` | `lmms-eval` `crossview_think`/`mvr_think` |
| Frames per video | 8 (`eval_thinking.py:168`) | 8 (`internvl2.py:180`) |
| Sampling formula | `linspace(0, total-1, 8).round()` — endpoints **included** (`input_pipeline.md:67`) | segment midpoints — endpoints **excluded** (`internvl2.py:91`) |
| Per-video marker | text `"Video k:"` (`eval_thinking.py:141`) | pixel marker image `res/video{j}.png` + `res/end{j}.png` (`internvl2.py:350`) |
| Vision-token unit | 4 vision blocks/video (2-frame merge), `<|video_pad|>` count = (H/32)(W/32) (`input_pipeline.md:84`) | 10 slots/video (1+8+1), ≈258 tok/frame → ≈10.3k for 4 videos (`input_pipeline.md:154`) |
| Think prompt | `QUESTION_TEMPLATE` (`eval_thinking.py:40-48`) | `THINK_INSTRUCTION` (`utils.py:286`) |
| Token count source | instrumented (counts `<|video_pad|>`) | analytic (258 × 10 × #videos) |
| Blind/no-video | `--no_video` skips loop (`eval_thinking.py:139`) | not run blind |

> Why the asymmetry matters: on a 7,328-frame video Qwen picks `[0, 1047, …, 7327]` while InternVL picks `[457, 1373, …, 6868]` — a ≈±10% per-video frame difference and asymmetric vision-token budgets (~11.5k Qwen vs ~10.3k InternVL for 4-video questions). Verified by `/home/hectorlugo02/CVBench/analysis/inspect_inputs.py` (re-runs the imported production functions on ids `[0,4,3,17,19]`; `EXPECTED_PICKS` at `inspect_inputs.py:41`, Qwen trace `:101`, InternVL trace `:123`, timestamp check `:210`).

---

## 5. How OUTPUTS are enabled (parsing, abstain, scoring, schema)

### 5a. Answer parsing + the abstain-on-truncation fix (Qwen)

`parse_choice()` at `/home/hectorlugo02/CVBench/Video-R1/src/eval_thinking.py:81-97` is the core scorer:
1. `extract_answer()` (`:62`) reads the `<answer>X</answer>` tag; `extract_think()` (`:51`) reads `<think>…</think>`.
2. If no `<answer>` tag, fall back to `_CONCLUDE_MC` (`:72`) / `_CONCLUDE_YN` (`:76`) regexes that match **only explicit "the answer is X" conclusions**, taking the LAST match.
3. Otherwise **abstain** — return `""` (empty string). No stray-letter grabbing.

**The historical contaminated-run bug it fixed** (`mentor_report.md` §6.4 starting `:209`): Qwen scored a mechanical **0/20 on Event-Ordering**. All 20 traces truncated at the old 2048-token budget with no `<answer>` tag, and the *old* parser grabbed "the first A/B/C/D token anywhere in the text" (`mentor_report.md:215-216`), e.g. the article "a" in "a vehicle" — fabricating a lucky letter on every truncated trace. The fix (`mentor_report.md:230`): raise the budget `2048 → 8192` and harden the parser to abstain on a tagless/truncated trace. After the fix **54/60 emit `<answer>`, 3 abstain** (`mentor_report.md:236-237`), and Event-Ordering became a legitimate 7/20. The bad file is archived as `eval_crossview_subset_qwen3vl.json.contaminated-20260615.bak` — do not use it.

InternVL parsing is the simpler `parse_choice()` at `/home/hectorlugo02/CVBench/analysis/parse_lmms_samples.py:34` (`src = extract_answer_tag(text) or text`, `:35`) — full-text fallback, no explicit abstain; `extract_answer_tag` at `:29`, `first_str(resps)` unpacks `lmms-eval`'s nested resps at `:43`, `num_videos(doc)` at `:51`.

### 5b. 'correct' scoring + token accounting

- `correct = pred.strip().upper() == gt.strip().upper()` at `eval_thinking.py:252` — case- and whitespace-insensitive. An abstain (`""`) never equals any GT, so it counts as wrong.
- **Per-question token fields** (Qwen, instrumented): `total_tokens = inputs.input_ids.shape[1]` at `eval_thinking.py:226`; `vid_id = processor.tokenizer.convert_tokens_to_ids("<|video_pad|>")` at `:227` then `video_tokens = int((inputs.input_ids[0] == vid_id).sum())` at `:228`; `text_tokens = total - video` at `:229`; `num_frames = 0 if args.no_video else args.nframes * num_videos` at `:245`.
- InternVL token counts are **analytic** (258 × 10 × #videos), not instrumented — `mentor_summary_2026-06-17.md:80`; `parse_lmms_samples.py` does not emit token fields.

### 5c. Result JSON schema

Assembled at `eval_thinking.py:243` (`rec_out = dict(rec)`, fields filled `:243-252`); aggregated by `summarize()` at `:261`. Top level is `{"results": [...], "summary": {...}}` with `summary` keys `overall_acc`, `by_num_videos`, `by_task_type`. A CrossView record carries: `id, task_type, video_1..4, question, options, answer, source, question_type, orig_num_cameras, dropped_cameras, cap_answer_safe, orig_id, num_videos, num_frames, total_input_tokens, video_tokens, text_tokens, output, think, prediction, correct`. (Verified: first record of `eval_crossview_subset_qwen3vl.json`, id 14, has `num_videos:2, num_frames:16, total_input_tokens:6307, video_tokens:5920, text_tokens:387`.)

### 5d. The analyze_failures re-parse (30.9% vs 32.0%)

The eval JSON's stored `correct` field gives **319/1033 = 30.9%** for the 1,033-Q Qwen run. `analyze_failures.py` re-parses the raw `output` strings and recovers ~12 borderline answers the eval-time parser scored wrong, so the camera-curve reports cite **331/1033 = 32.0%**. The ~1pp gap is exactly those 12 parse-recoverable cases; failure-mechanism proportions are parser-insensitive. Source: `/home/hectorlugo02/CVBench/analysis/crossview_meva1033_out/failure_examples_curated.md` (parser note near the top).

---

## 6. Datasets

| Source | Status | Videos | Cap-safety | License |
|---|---|---|---|---|
| **MEVA** | ✅ ready (60-Q + 1,033-Q pools) | public S3 `mevadata-public-01`, no creds | 100% cap-answer-safe (`metadata.requires_cameras`) | CC-BY |
| **EgoExo4D** | ✅ **now downloaded** — 96/96 referenced files local + decord-readable (verified, 0 failures) | 96 files / 24 takes, frame-aligned downscaled-448 | 38/40 lossy (no per-camera grounding) | research (license was the only gate; now cleared on disk) |
| **AgiBot** | ⛔ gated — HF click-through + `HF_TOKEN` + ~810 GB tars for 77 mp4s | tar-granular shards (2–287 GB each) | cap-safe (≤3 cams), 499 clean MCQs | CC BY-NC-SA 4.0 |
| **nuScenes** | ⛔ skip — fixed 6 cameras → 100% lossy under the ≤4 cap | — | — | — |

Key concepts:
- **cap (≤4)**: the harness only feeds ≤4 clips; CrossView questions with more cameras are capped.
- **cap_answer_safe**: a flag (column in `crossview_subset_questions.md:3`) marking whether the gold answer is still recoverable after the cap. MEVA = 100% safe; EgoExo4D mostly lossy. **Report stratified by this flag; never pool.**
- **orig_num_cameras**: the true camera count (1–16) before capping; the x-axis of the "multi-camera is hard" curve.

Fetchers: `/home/hectorlugo02/CVBench/analysis/fetch_meva_videos.py` (S3, no creds), `/home/hectorlugo02/CVBench/analysis/fetch_egoexo_videos.py` (egoexo CLI), AgiBot per `agibot_setup.md`. EgoExo4D walkthrough: `egoexo_setup.md` (note: its "## Status" still says the license gate remains — that is now stale; the 96 files are present and decord-readable on disk).

EgoExo4D-local verification (this session): the EgoExo4D subset references 168 video slots → 96 unique files; all 96 exist under `crossview-release-annotations/crossview-release/videos/ego-exo4d/takes/` and all 96 open cleanly with `decord` in the `cvbench` env. A combined-eval result JSON does **not** exist yet (no `eval_*combined*` / `eval_*egoexo*` under `eval_results/`).

---

## 7. How to run it

```bash
conda activate cvbench          # never a python venv (see ~/.claude memory conda-not-venv)
```

**CrossView 60-Q, clean Qwen + blind baseline (InternVL already clean):**
```bash
RUN_BLIND=1 RUN_QWEN=1 RUN_INTERNVL=0 sbatch analysis/run_eval_crossview.sbatch
```

**CrossView at scale (1,033-Q MEVA pool), both models + blind:**
```bash
SUBSET=analysis/crossview_meva1033_subset.json FETCH=analysis/crossview_meva1033_fetch.json \
  RUN_BLIND=1 sbatch analysis/run_eval_crossview.sbatch
```

**Combined MEVA + EgoExo4D (100-Q), now that EgoExo4D videos are local:**
```bash
# subset already built: analysis/crossview_combined_subset.json (60 MEVA + 40 EgoExo4D)
SUBSET=analysis/crossview_combined_subset.json FETCH=analysis/crossview_combined_subset_fetch.json \
  RUN_BLIND=1 sbatch analysis/run_eval_crossview.sbatch
# MEVA half needs 0 fetch; EgoExo4D half resolves to the 96 local files (verified present + decord-readable).
# Stratify the report by cap_answer_safe — EgoExo4D is mostly lossy-capped.
```

The Qwen leg is invoked at `run_eval.sbatch:44` (`eval_thinking.py … --nframes 8 --max_new_tokens 2048`; raised to 8192 for the clean re-run) and the InternVL leg at `run_eval.sbatch:55` (`python -m lmms_eval --model internvl2 --model_args 'pretrained=${INTERNVL_CKPT},num_frame=8' --tasks mvr_think --batch_size 1 --log_samples`). The sbatch rebuilds `mvr_dataset` from the subset JSON in a heredoc at `run_eval.sbatch:34` (banner `:33`) to keep both harnesses in sync. Env vars at `run_eval.sbatch:18-21` (`DECORD_EOF_RETRY_MAX=20480`, `HF_HUB_OFFLINE=1`, `PYTORCH_ALLOC_CONF=expandable_segments:True`). Blind invocation at `run_eval_novideo.sbatch:27` (`--no_video --max_new_tokens 2048`).

**conda env caveats:**
- Use the `cvbench` conda env for the Qwen leg. Never a project `.venv`.
- InternVL3 needs `transformers<5`. The `cvbench` env has transformers 5 (errors with `all_tied_weights_keys`). Run the InternVL leg with `INTERNVL_ENV=internvl` — a `cvbench` clone pinned to `transformers==4.48.3`. (`run_eval.sbatch:55` actually invokes the overlay interpreter `$IVL_PY`, not bare `python`.)

Regenerate the derived (uncommitted) QA pools in <1s: `python analysis/convert_crossview.py --sources meva,ego-exo4d,agibot`.

---

## 8. Results inventory

All under `/home/hectorlugo02/CVBench/Video-R1/src/r1-v/eval_results/` unless noted. Accuracies recounted from each JSON in this session.

| File | Model | Benchmark | n | Video/Blind | Status | Accuracy |
|---|---|---|---:|---|---|---|
| `eval_crossview_subset_qwen3vl.json` | Qwen3-VL | CrossView | 60 | video | **canonical** (8192 + abstain) | 19/60 = 31.7% |
| `eval_crossview_subset_qwen3vl.json.contaminated-20260615.bak` | Qwen3-VL | CrossView | 60 | video | **contaminated — do not use** | 31.7% by coincidence; only 9/19 correct Qs overlap |
| `eval_crossview_subset_qwen3vl_novideo.json` | Qwen3-VL | CrossView | 60 | blind | canonical | 22/60 = 36.7% |
| `eval_crossview_meva1033_qwen3vl.json` | Qwen3-VL | CrossView (MEVA pool) | 1033 | video | canonical | 319/1033 = 30.9% (32.0% after re-parse) |
| `eval_subset_qwen3vl.json` | Qwen3-VL | CVBench | 45 | video | canonical | 28/45 = 62.2% |
| `eval_subset_qwen3vl_novideo.json` | Qwen3-VL | CVBench | 45 | blind | canonical | 18/45 = 40.0% |
| `eval_CVBench_mvr_greedy_output.json` | Qwen3-VL (MVR greedy) | CVBench full | 1000 | video | canonical (`final_acc[0].mean_acc`) | 520/1000 = 52.5% |
| `analysis/crossview_internvl3_normalized.json` | InternVL3 | CrossView | 60 | video | canonical (no summary key) | 23/60 = 38.3% |
| `analysis/crossview_internvl3_meva1033_normalized.json` | InternVL3 | CrossView (MEVA pool) | 1033 | video | canonical | 351/1033 = 34.0% |

Gotchas: `overall_acc` is stored as a percentage-scaled float (e.g. `31.6667`), divide by 100 for fraction. CVBench MVR uses `final_acc` as a *list* of dicts `{mean_acc, mean_mra}`, not a scalar — read `final_acc[0].mean_acc`. InternVL normalized files have **no** `summary` key — compute accuracy from `correct` flags. Blind vs video direction flips by dataset: CrossView blind (36.7%) **beats** video (31.7%); CVBench video (62.2%) **beats** blind (40.0%).

---

## 9. Headline numbers & key findings

- **CVBench 45-Q (real benchmark):** Qwen3-VL **62.2%** video vs **40.0%** blind (**+22pp video gain** — video genuinely helps); InternVL3 55.6%.
- **CrossView 60-Q (clean / reportable):** InternVL3 **38.3%** > Qwen3-VL **31.7%**. The Qwen 31.7% matches the old contaminated run *only by coincidence* — the composition is now legitimate: Event-Ordering **7/20** (was a mechanical 0/20 artifact), Spatial 9/20, Temporal 3/20; 54/60 emit `<answer>`, 3 abstain. On CrossView, **video input HURTS** Qwen (blind 36.7% > video 31.7%) — opposite of CVBench.
- **CrossView at scale (1,033-Q MEVA):** Qwen3-VL **30.9%** stored / **32.0%** after analyze_failures re-parse; InternVL3 **34.0%**.
- **Failure taxonomy (Qwen, 1,033-Q, of 714 wrong)** — `crossview_meva1033_out/failure_examples_curated.md`:
  - **wrong_reasoned: 626** (Spatial 273, Temporal 222, Event-Ordering 131) — the dominant failure: the model reads frames but reasons to the wrong conclusion.
  - **truncation_no_answer: 69**, of which **60 are Event-Ordering** — long ordering chains still run out of budget; abstain (not fabricate) is correct behavior now.
  - given_order_bias 13 (all Event-Ordering); single_video_shortcut 6 (all Spatial).
- **Temporal task flip:** on the 1,033-Q pool Temporal accuracy is **Qwen 25% (75/305) vs InternVL3 51% (157/305)** — the two models have nearly opposite temporal strengths. (Conversely InternVL3 is weaker on Event-Ordering 25% and Spatial 28%.) Both confuse *video-level timestamps* with *game/event-level time* — temporal grounding is the hard core (regenerate `temporal_failures.md` via `temporal_complexity.py`).
- **Multi-camera is hard:** accuracy degrades with `orig_num_cameras` (the curve in `crossview_out*/accuracy_vs_orig_cameras*.png`), the central thesis of the project.

---

## 10. Glossary

- **leg** — one of the two parallel eval harnesses: the *Qwen leg* (`eval_thinking.py`) or the *InternVL leg* (`lmms-eval`).
- **thinking trace** — the `<think>…</think>` reasoning block the model emits before its `<answer>`; the primary object of analysis (failures are read from it).
- **abstain** — `parse_choice()` returns `""` when there is no `<answer>` tag and no explicit "the answer is X" conclusion, instead of grabbing an incidental letter. Abstains score as wrong but are honest (the fix for the contaminated 0/20 artifact).
- **cap (≤4)** — the harness feeds at most 4 clips per question; CrossView questions with more views are capped.
- **cap_answer_safe** — flag marking whether the gold answer is still recoverable after the ≤4 cap (MEVA 100% safe, EgoExo4D mostly lossy). Always stratify reports by it; never pool.
- **orig_num_cameras** — the true camera count (1–16) before capping; x-axis of the "multi-camera is hard" curve.
- **blind / no-video** — the `--no_video` baseline: identical prompts, zero clips, zero vision tokens (`eval_thinking.py:139`); measures the language prior only.
- **contaminated run** — the archived `*.contaminated-20260615.bak` Qwen CrossView result scored by the old stray-letter parser on truncated traces; superseded by the 8192 + abstain re-run.
- **normalized (InternVL)** — `parse_lmms_samples.py` output that re-shapes `lmms-eval` per-sample logs into the shared record schema (no token fields, no `summary`).
- **MVR** — "Multi-Video Reasoning", the CVBench task family / lmms-eval task name (`mvr_think`).
- **wrong_reasoned** — the dominant failure mechanism: model perceives the frames but reasons to the wrong answer (vs truncation or shortcut failures).
```
