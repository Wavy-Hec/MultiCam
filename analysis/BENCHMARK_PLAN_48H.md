# 48-Hour Coding Plan — Multi-Camera VLM Benchmark

*Benchmark state-of-the-art systems on multi-camera reasoning across accuracy, latency, and cost —
and answer: **for which question categories does a distributed (per-stream) agent beat a centralized
(single-VLM) one?***

> **Scope guard:** these 48h build the *harness* and validate it on smoke sets. **No full
> experiments are run** (full GPU sweeps, NeuS-QA, and the 2-camera temporal-alignment study are
> gated roadmap, see §8). The deliverable is a reproducible `bench/` that *can* run the sweeps.

---

## 1. Research question & framing

Nobody has systematically benchmarked how VLM *systems* (not just single models) reason over
multiple synchronized camera streams. Given a multi-stream question, we compare **architectures**
and measure them on **multiple axes**, stratified by question category.

**Hypothesis (from the existing failure analysis, `why_models_fail.md`):** a centralized VLM loses
cross-view correspondence and temporal grounding (it perceives sparse frames as static and falls
back on language priors). A distributed "1-VLM-per-stream" agent may help **Spatial** (independent
per-camera grounding) but hurt **Temporal / Event-Ordering** (which need cross-stream synchronization
that a per-stream split destroys). The benchmark will confirm or refute this per category.

---

## 2. Metrics

| ID | Metric | Definition | Source today |
|----|--------|-----------|--------------|
| **M1** | Accuracy | overall + by `task_type` + by `orig_num_cameras` (the "more cameras = harder" curve) + by `source` (MEVA/EgoExo4D) + by `cap_answer_safe` (**never pool**) | exists (`summarize`, `eval_thinking.py:261`) |
| **M2** | Latency | per-question wall-clock; for distributed also **parallelizable** latency (`max` over per-stream calls + aggregator) vs the serial sum | **none — new instrumentation** |
| **M3** | Cost/efficiency | input+output tokens, model calls/question, peak VRAM, GPU-seconds (or $) per question | tokens partly exist (`<|video_pad|>` count, `eval_thinking.py:226-229`); the rest new |
| **M4** | Calibration | abstention rate (`prediction==""`) + escape-option rate (C/"cannot be determined") | derivable from parser |

---

## 3. Methods (architectures under test)

- **A0 — Centralized "today's VLM".** One VLM ingests *all* clips in one prompt. **Already exists:**
  `build_messages()` (`Video-R1/src/eval_thinking.py:121`) interleaves a `"Video k:"` text marker +
  each clip; generation at `:233`. We wrap it as a `Method` and add timing.
- **A1 — Distributed "1-VLM-per-stream".** Each clip gets an independent VLM *perception* pass
  ("describe what is relevant to this question in this camera, with timestamps"); then a single
  *aggregator* pass reasons over the K text descriptions + the question/options → answer. This is
  the agentic decomposition; it makes the cross-view-correspondence cost explicit and measurable.
- **A2 — Router (stub only).** Per-category route to A0 or A1. Interface + a trivial rule this 48h;
  the learned/empirical router is future work once A0/A1 numbers exist.
- **A3 — NeuS-QA (out of scope).** Reconstruct the scene (NeuS/3D), then QA over the reconstruction.
  Stub interface only — "next week".

---

## 4. Existing assets to reuse (do **not** reimplement)

| Need | Reuse | Location |
|------|-------|----------|
| Centralized message assembly | `build_messages(rec, video_root, nframes, no_video)` | `eval_thinking.py:121` |
| Model load (generic VLM) | `load_model(model_path, dtype)` — already generic `AutoProcessor`/`AutoModelForImageTextToText` | `eval_thinking.py:147` |
| Frame sampling kept intact | `process_vision_info(..., return_video_metadata=True)` | `eval_thinking.py:212` |
| Token accounting | `<|video_pad|>` count → `video_tokens`/`text_tokens` | `eval_thinking.py:226-229` |
| Answer parsing (abstain-safe) | `parse_choice(text, is_yesno)`, `gt_choice` | `eval_thinking.py:81`, `:100` |
| Helpers | `num_videos`, `video_paths` | `eval_thinking.py:108`, `:112` |
| Aggregation shape | `summarize(results, output)` | `eval_thinking.py:261` |
| InternVL backend | lmms-eval `internvl2.py` multi-video branch | `lmms-eval/.../models/internvl2.py:345`, `num_frame:180` |
| Dev pool (100 Q) | `analysis/crossview_combined_subset.json` (60 MEVA + 40 EgoExo4D; schema: `id, task_type, video_1..4, question, options, answer, source, question_type, orig_num_cameras, dropped_cameras, cap_answer_safe, orig_id`) | tracked |
| Scale pool (1,033 Q) | `analysis/crossview_meva1033_subset.json` | tracked |

---

## 5. Package layout (new `bench/`)

```
bench/
  bench_spec.md              # frozen spec: metrics, methods, pools, Result schema
  methods/
    base.py                  # Method ABC + Result dataclass
    centralized.py           # A0 — adapter over eval_thinking.build_messages + shared generate
    per_stream.py            # A1 — per-clip perception + aggregator
    router.py                # A2 — stub
  backends/
    base.py                  # Backend ABC: generate(messages|prompt, **gen) -> (text, in_tok, out_tok, latency)
    qwen3vl.py               # reuse eval_thinking.load_model + process_vision_info path
    qwen25vl.py              # CHOSEN 3rd backend: Qwen2.5-VL-7B-Instruct — same generic
                             #   AutoProcessor/AutoModelForImageTextToText path → ~no new loader code
                             #   (LLaVA-OneVision-7B is the cross-family alternative if needed)
    internvl3.py             # wrap lmms-eval internvl2.py multi-video path
  metrics.py                 # accuracy / latency / token / abstention aggregation
  run_bench.py               # CLI: --methods --backends --subset --limit ; writes per-question JSONL
  report.py                  # method x category table (acc, latency, tokens) + curves -> MD/CSV/PNG
  README.md
```

**`Result` schema** (one row per question per method×backend):
```
{ id, task_type, source, orig_num_cameras, cap_answer_safe,
  method, backend, prediction, gold, correct,
  latency_s, perception_latency_s, aggregate_latency_s,    # M2
  input_tokens, output_tokens, num_model_calls, peak_vram_mb,  # M3
  abstained }                                               # M4
```

---

## 6. Hour-by-hour

### Day 1 (0–24h) — harness + methods + backends
- **H0–2 — Spec & scaffold.** Freeze `bench/bench_spec.md` (metrics, methods, pools, `Result`
  schema above). Create the package skeleton + empty interfaces.
- **H2–6 — Method interface + A0 adapter.** `Method.answer(rec, video_root) -> Result`. Wrap the
  centralized path: call the imported `build_messages` + a shared `generate`. **Add per-question
  `time.perf_counter` timing** around generation (new — no timing today). Emit a tidy per-question
  JSONL. Acceptance: A0 runs one question end-to-end and produces a `Result`.
- **H6–10 — Metrics + verification.** `metrics.py`: accuracy by `task_type`/`orig_num_cameras`/
  `source`/`cap_answer_safe`, latency p50/p95, token sums, abstention/escape rates. **Correctness
  gate:** re-score the existing `eval_crossview_subset_qwen3vl.json` through `metrics.py` and confirm
  it reproduces the known **19/60** / per-task split (proves the harness scores identically).
- **H10–16 — A1 distributed.** Per-stream perception prompt (one VLM call per clip, question-aware,
  asks for timestamped observations) + an aggregator prompt (reasons over the K descriptions →
  `<answer>`). Record `perception_latency_s` per stream, `aggregate_latency_s`, `num_model_calls`,
  serial total, and the parallelizable estimate (`max(perception)+aggregate`).
- **H16–20 — 3rd backend (Qwen2.5-VL-7B, swappable).** Add `qwen25vl.py` behind the `Backend`
  interface (drops into the generic transformers path). Confirm all three backends emit a parseable
  `<answer>` on one shared question.
- **H20–24 — Smoke test + checkpoint.** Run `5 Q/category` across {A0,A1}×{qwen3vl,qwen25vl} on the
  combined pool (NOT a full run). Fix bugs. Commit.

### Day 2 (24–48h) — reporting, analysis scaffolding, launch plan
- **H24–28 — `report.py`.** Method×category table (acc, latency, tokens) + accuracy-vs-
  `orig_num_cameras` curve per method → MD + CSV + PNG.
- **H28–32 — Centralized-vs-distributed analysis.** Per-category comparison (which method wins on
  Spatial / Temporal / Event-Ordering) + a simple significance check (bootstrap CI on the smoke
  set; the real test runs after the gated full sweep).
- **H32–36 — Latency model.** Document and implement the parallel-distributed latency estimate
  (per-stream calls assumed concurrent under a real distributed system) vs measured serial latency.
- **H36–40 — Robustness-sweep scaffolding.** Parameterize `nframes` and the camera cap; build the
  accuracy/cost-tradeoff plotting — **code only, runs gated**.
- **H40–44 — Docs + sbatch templates + matrix.** `bench/README.md`; per-method sbatch templates
  (mirroring `analysis/run_eval_crossview.sbatch`); the experiment matrix (methods × backends ×
  pools × seeds).
- **H44–48 — Dry-run the matrix + launch plan.** Enumerate the full sweep as a DAG **without
  executing**; produce a resource/time/cost estimate and a one-command launch script. Final commit / PR.

**Acceptance (end of 48h):** one command —
`python bench/run_bench.py --methods centralized,per_stream --backends qwen3vl,qwen25vl --subset analysis/crossview_combined_subset.json --limit 5`
— produces the method×category accuracy+latency+token table; A0 reproduces the existing eval
numbers; A1 logs both latency modes.

---

## 7. Explicitly out of scope (gated; do **not** run in the 48h)
- Full GPU sweeps over the 1,033-Q (and combined) pools for every method×backend.
- API/frontier backends (network latency would distort M2; add later if wanted).
- NeuS-QA (A3) beyond a stub.
- The 2-camera temporal-alignment experiment (§8).

## 8. Roadmap beyond 48h (the user's longer-horizon ideas)
1. **2-camera temporal alignment → VLM.** Take 2 synchronized cameras, temporally align them, feed
   the aligned pair to a VLM — does fixing the sync recover the temporal signal the sparse-sampling
   analysis showed is lost?
2. **Agentic processing architecture.** Improve *how* streams are processed (selection, summarization,
   cross-view linking) before deciding centralized vs distributed.
3. **Distributed vs centralized at scale.** Run the §6 harness on the full pools to get
   per-category verdicts with real significance.
4. **NeuS-QA.** Reconstruct the scene and answer over the 3D representation — a genuinely different
   architecture than frame-sampling VLMs.

---

*Numbers and code anchors reflect the verified `analysis/ORIENTATION.md` as of 2026-06-22. Re-confirm
`eval_thinking.py` line numbers before coding if the file has changed.*
