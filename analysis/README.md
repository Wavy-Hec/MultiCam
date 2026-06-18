# `analysis/` — Multi-Camera VLM Benchmark

This directory holds the evaluation + analysis pipeline for benchmarking how vision-language
models reason over **multiple camera views**. Two benchmarks share one "thinking" eval harness:

| Benchmark | Source | Subset | Clips per question |
|---|---|---|---|
| **CVBench / MVR** | HF `Dongyh35/CVBench` | 45 Q (`subset.json`) | 1–4 *unrelated* clips |
| **CrossView** | UT Austin SwarmLab Multi-Camera | 60 Q (`crossview_subset.json`); 1,033-Q MEVA pool (`crossview_meva1033_subset.json`) | 2–4 *synchronized* views (capped to ≤4) |

Models: `Qwen3-VL-8B-Thinking` (own harness, `Video-R1/src/eval_thinking.py`) and `InternVL3-8B`
(lmms-eval `crossview_think` / `mvr_think` task). Both get **8 frames/video** and emit
`<think>…</think><answer>…</answer>` so failures are interpretable from the reasoning traces.

> The advisor deliverable is **failure-mode analysis** read from the `<think>` traces — accuracy
> is the means, not the end.

---

## Read these first (canonical files)

1. `reports → mentor_report.md` + `mentor_summary_2026-06-17.md` — top-level findings & status.
2. `input_pipeline.md` — how each model is fed video (frame sampling, ordering, token layout). Verified against code.
3. `blind_sanity.md` — proof the no-video baseline is genuinely text-only (0 vision tokens, no metadata leak).
4. `crossview_subset_questions.md` — the 60 CrossView questions with gold answers, true camera count, cap flags.
5. Figures: `reasoning_gain.png` (video uplift over blind), `crossview_out/accuracy_vs_orig_cameras_internvl3.png` (the "multi-camera is hard" curve).

## Headline numbers (re-counted from the result JSONs)

| Run | Model | Accuracy | Notes |
|---|---|---|---|
| CVBench 45-Q, video | Qwen3-VL | 28/45 = 62.2% | real |
| CVBench 45-Q, blind | Qwen3-VL | 18/45 = 40.0% | +22pp video gain |
| CVBench 45-Q | InternVL3 | 25/45 = 55.6% | real |
| CrossView 60-Q | InternVL3 | 23/60 = 38.3% | **clean / reportable** |
| CrossView 60-Q | Qwen3-VL | 19/60 = 31.7% | **superseded** — old run was a truncation/parser artifact (Event-Ordering a mechanical 0/20). Being re-run with an 8192-token budget + abstain-on-truncation parser; old file kept as `*.contaminated-*.bak`. |

---

## What correlates with what (pipeline dependency map)

Each pipeline is `script(s) → input → output → report`. Eval result JSONs live under
`Video-R1/src/r1-v/eval_results/`; normalized InternVL results + analysis artifacts live here.

**1. CVBench eval (with-video & blind)**
```
select_subset.py            → subset.json (45 Q)
run_eval.sbatch ─┬ eval_thinking.py (Qwen)          → eval_subset_qwen3vl.json
                 └ lmms-eval mvr_think (InternVL3)   → internvl3_normalized.json
run_eval_novideo.sbatch → eval_thinking.py --no_video → eval_subset_qwen3vl_novideo.json
analyze_failures.py  → accuracy_by_cameras.json, qwen3vl_failures.md, qwen3vl_blind_failures.md
plot_accuracy.py     → accuracy_vs_cameras.png, accuracy_by_task.png
make_reasoning_gain.py (blind vs video) → reasoning_gain.png
verification: inspect_inputs.py → inspect_inputs_data.json → input_pipeline.md;
             inspect_blind.py  → inspect_blind_data.json  → blind_sanity.md
```

**2. CrossView eval (MEVA / [deferred] EgoExo4D, AgiBot)**
```
convert_crossview.py (imports crossview_question_types.py)
   raw annotations (crossview-release-annotations/) → crossview_subset.json (+ _fetch.json, _videos.txt)
fetch_meva_videos.py --subset … → MEVA .avi clips (public S3, no creds)
run_eval_crossview.sbatch ─┬ eval_thinking.py (Qwen, +--no_video blind)  → eval_crossview_subset_qwen3vl[_novideo].json
                           └ lmms-eval crossview_think (InternVL3) → (parse_lmms_samples.py) → crossview_internvl3_normalized.json
crossview_camera_curve.py → crossview_out/accuracy_by_orig_cameras.json + accuracy_vs_orig_cameras[_internvl3].png + camera_curve.md
plot_accuracy.py          → crossview_out/accuracy_vs_cameras.png, accuracy_by_task.png
crossview_vs_cvbench.py   → crossview_out/cvbench_vs_crossview.md
analyze_failures.py       → crossview_out/{qwen3vl,internvl3}_failures.md
```

**3. Temporal-complexity analysis (CVBench)**
```
temporal_complexity.py  → temporal_complexity.json, temporal_complexity_dist.png, accuracy_vs_temporal.png, temporal_failures.md
make_team_json.py (imports temporal_complexity.py) → cvbench_temporal_logic_team.json
```

**4. Slides** — `make_slides.py` reads the figures above + `poster_assets.md` → `multicam_progress.pptx`.

---

## How to run

```bash
conda activate cvbench          # never a python venv (see ~/.claude memory conda-not-venv)

# CrossView 60-Q, clean Qwen + blind baseline (InternVL already clean):
RUN_BLIND=1 RUN_QWEN=1 RUN_INTERNVL=0 sbatch analysis/run_eval_crossview.sbatch

# CrossView at scale (1,033-Q MEVA pool), both models + blind:
SUBSET=analysis/crossview_meva1033_subset.json FETCH=analysis/crossview_meva1033_fetch.json \
  RUN_BLIND=1 sbatch analysis/run_eval_crossview.sbatch
```
**InternVL3 env caveat:** it needs `transformers<5`. If the `cvbench` env (transformers 5) errors
(`all_tied_weights_keys`), run the InternVL leg with `INTERNVL_ENV=internvl` (a `cvbench` clone
pinned to `transformers==4.48.3`). The Qwen leg stays on `cvbench`.

---

## Datasets

| Source | Status | Videos | License |
|---|---|---|---|
| **MEVA** | ✅ ready (60-Q + 1,033-Q pools, 100% cap-answer-safe) | public S3 `mevadata-public-01`, no creds | CC-BY |
| Ego-Exo4D | ⛔ deferred — needs license (~48h) + AWS creds; 58/60 lossy-capped | gated | research |
| AgiBot | ⛔ deferred — HF gate + `HF_TOKEN` + ~810 GB tars | gated | CC BY-NC-SA |
| nuScenes | ⛔ skipped — fixed 6 cams → 100% lossy under the ≤4 cap | — | — |

Extension walkthroughs: `egoexo_setup.md`, `agibot_setup.md`.

---

## Regenerating intermediate files

The pre-subset master pools (`crossview_qa.json`, `crossview_full_qa.json`,
`crossview_combined_qa.json`, `crossview_egoexo_qa.json`, `crossview_agibot_qa.json`) are
**derived and not committed** — regenerate from annotations in <1s:
```bash
python analysis/convert_crossview.py --sources meva,ego-exo4d,agibot     # writes crossview_qa.json + the MEVA subset
```
The HF Arrow datasets (`mvr_dataset/`, `crossview_dataset/`) are rebuilt automatically by the
sbatch scripts from the `*_subset.json` files.
