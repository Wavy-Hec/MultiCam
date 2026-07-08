# Decentralized Per-Stream Run + SigLIP Clip-Selection Gate — Full Explainer

*Written 2026-07-08, while jobs 63676 and 63727 were running on `sxmq` (A100-SXM4-80GB). Every
claim below was verified against the code at the cited `file:line` on branch `crossview-benchmark`
(working tree == committed state at launch time).*

---

## 1. What is running

| Job | Name | What it is | Where | Output |
|---|---|---|---|---|
| **63727** (array 0–7) | `bench-multicam` | Full-1000 **decentralized (`per_stream`) CVBench** run, InternVL3-8B, 4 passes — CVBench's first decentralized rows | 8 shards × 1 A100 (sxm003/004) | `bench/results/bench_cvbench_full_runnable_subset_internvl_fullperstream_shard{0-7}.jsonl` |
| **63676** | `clipsel-gate-smoke` | Go/no-go gate for **question-driven clip selection with SigLIP** + 5-question smoke of the real eval arms | 1 A100 (sxm003) | `bench/results/clip_scorer_gate.json`, `bench/results/smoke_clipsel_siglip.jsonl` |

Both were queued on `gpul40q`, moved to `sxmq` with `scontrol update job <id> partition=gpul40q,sxmq`
on 2026-07-08 ~07:56 and started within seconds. The `internvl` conda env was verified on-node on
A100 first (torch 2.10+cu128 includes sm_80; **no flash-attn anywhere — InternVL3 runs plain SDPA**,
so there is no GPU-architecture-specific kernel risk).

Launch config (63727): `ENV=internvl SUBSET=analysis/cvbench_full_runnable_subset.json
BACKENDS=internvl3 METHODS=per_stream STREAM_KIND=video TAG=_fullperstream CHUNK=8
VIDEO_ROOT=Video-R1/src/r1-v/Evaluation/CVBench sbatch --array=0-7 bench/run_bench.sbatch`
→ `--nframes 8 --passes 4 --seeds 1,2,3,4 --temperature 0.7 --max-new-tokens 8192`.

---

## 2. Input dataset

`analysis/cvbench_full_runnable_subset.json` — **1000 questions**, videos resolve against
`Video-R1/src/r1-v/Evaluation/CVBench` (468 numbered dirs of YouTube-ID-named `.mp4`s).

- **Clips per question** (`video_1..video_4` fields; matches `orig_num_cameras` exactly):
  n=2 → 487 questions, n=3 → 236, n=4 → 277. Never more than 4.
- **15 task types**: Cross-video Scene Recognition 149, Multi-video Key-Action Recognition 88,
  Cross-video Anomaly Detection 84, Multi-video Temporal Reasoning 75, Cross-video Entity
  Matching 74, Cross-video Object Recognition 68, Joint-video Counting 60, Multi-view Scene
  Understanding 55, Video Difference Caption 55, Joint-video Summarization 52, Cross-video
  Counterfactual Reasoning 52, Cross-video Procedural Transfer 51, Cross-video Event Retrieval 49,
  Multi-video Attribute Recognition 46, Joint-video Spatial Navigating 42.
- **Answers**: 860 four-way MC (B 257 / A 232 / C 231 / D 140), 139 two-option (136 Yes/No:
  Yes 79 / No 57; 3 letter-answered, incl. two "Video 1 / Video 2" questions), 1 single-option
  oddity (cvb-996).
- **Record fields**: `id, task_type, question, options, answer, source, question_type,
  orig_num_cameras, cap_answer_safe, orig_id, video_1..video_4`.

**Sharding**: `--chunk 8 --offset i` strides the list as `data[i::8]` (`bench/run_bench.py:180-181`)
→ each shard owns 125 disjoint questions and writes 125 × 4 passes = **500 rows** (4000 total).

---

## 3. How a clip becomes model input ("the clipping")

This is the frame pipeline in `bench/backends/internvl.py` for a `{"type":"video"}` item:

1. **Frame selection** — `get_index` (`internvl.py:90-99`): the clip is split into **8 equal time
   segments** and the **midpoint frame of each segment** is taken. Fully deterministic — the same
   clip always yields the same 8 frames, on every pass and every machine.
2. **Decode** — decord reads exactly those 8 frames (no full-video decode).
3. **Resize** — each frame goes through `dynamic_preprocess` with `max_num=1`
   (`internvl.py:114-121, 58-81`): exactly **one 448×448 tile per frame**, the full frame
   **anisotropically resized** (PIL `image.resize((448,448))` inside `dynamic_preprocess`,
   `internvl.py:67-70`; the later `T.Resize((448,448))` at `internvl.py:33-39` is a no-op on the
   already-448 tile). **No cropping, no letterboxing** — same finding as the stitch audit: aspect ratio distorts, content is never lost.
4. **Tokens** — 256 visual tokens per tile (`internvl.py:161`) → **8 frames × 1 tile × 256 =
   2048 visual tokens per clip**. The text prompt sees `Video k:` + `Frame1: <image>\n … Frame8:
   <image>\n` + the instruction text (`internvl.py:181`).

Note: `--internvl-max-tiles 1` in the launch line only affects `{"type":"image"}` montage inputs
(`internvl.py:171`); for videos `max_num=1` is hard-coded (`internvl.py:177`), so the flag is a
**no-op for this run** — harmless.

**Generation** (`internvl.py:188-201`): `torch.manual_seed(seed)` before *every* call;
`do_sample=True, temperature=0.7, top_p=0.9, num_beams=1`.

---

## 4. The decentralized (`per_stream`) pipeline

Per question, exactly **n_clips + 1 model calls** (`bench/methods/per_stream.py:48-68`;
recorded in the row's `num_model_calls`). This simulates cameras that each perceive locally and
send only *text* to a central reasoner.

**Stage 1 — per-clip perception** (one call per clip, `per_stream.py:48-60`):
input = `Video k:` + that clip's 8 frames + `PERCEPTION_PROMPT` (`per_stream.py:11-16`):

> "You are looking at ONE video clip only. Describe what is visible that is relevant to the
> question below: any people and their appearance, their movements/trajectory, and the timestamps
> at which events occur. If nothing relevant is visible, say so plainly. Do NOT try to answer the
> question yet.  Question: {question}"

The question text is included but the **answer options are not**. Output capped at **1024** tokens
(`perception_max_new_tokens`, `per_stream.py:30,55`) — not the CLI's 8192.

With `--stream-kind video` the label/unit is ("Video", "video clip") (`per_stream.py:23,34`) —
the honest CVBench wording (the Camera-vs-Video labeling artifact fix from the flip-result
analysis).

**Stage 2 — text-only aggregation** (one call, `per_stream.py:62-68`): input =
`AGGREGATE_PREFIX` ("You are given independent descriptions of each video clip. Reason over ALL
of them together to answer.") + the n perception outputs as `Video k:\n{text}` blocks + the full
answer scaffold (question + options + think-then-`<answer>` template from
`Video-R1/src/eval_thinking.py:40-48`). Genuinely text-only: `_flatten` finds no media and passes
`pixel_values=None` (`internvl.py:184-186`). Cap **8192** tokens.

**Stage 3 — parse & score** (`per_stream.py:70-77`, `eval_thinking.py:81-97`): prediction = first
`[ABCD]` (or Yes/No) inside `<answer>…</answer>` of the *aggregator* output; if the tag is missing
(truncated trace), fall back only to an explicit "final/best/correct answer is X" conclusion;
otherwise **abstain** (`prediction=""`, counted wrong). `correct = (pred == gold)` case-insensitive.

**Cost of the full run**: one pass = 487·3 + 236·4 + 277·5 = 3,790 calls; 4 passes = **15,160
model calls**.

**Passes**: seeds 1–4 ↔ pass_idx 1–4 (`run_bench.py:190-192`), record-major so one question's 4
passes run consecutively (`run_bench.py:215-218`). Frames are bitwise identical across passes; the
*only* difference is the sampling seed. Table-1 std is taken over the 4 passes.

---

## 5. Output row schema

One JSONL row per (question, pass) = `Result` dataclass (`bench/methods/base.py:27-64`):

| Field | Meaning |
|---|---|
| `id, task_type, source, orig_num_cameras, cap_answer_safe, num_videos` | copied from the record for stratification (per-category tables come free via `metrics.py`) |
| `method` | `"per_stream"` — **stream_kind is NOT in the name**; don't mix camera/video runs in one file |
| `backend` | `"InternVL3-8B"` |
| `prediction / gold / correct / abstained` | parsed answer vs ground truth; `abstained` = empty prediction |
| `pass_idx, seed, temperature` | 1–4, 1–4, 0.7 |
| `latency_s` | serial wall-clock: all perception calls + aggregator |
| `perception_latency_serial_s` / `perception_latency_par_s` | sum vs **max** over per-clip calls — `par` is the latency a truly parallel camera network would see (the decentralized headline) |
| `aggregate_latency_s` | aggregator call alone |
| `input_tokens / video_tokens / output_tokens` | best-effort token accounting (2048·n visual; aggregator adds 0 visual) — not directly comparable to Qwen counts |
| `num_model_calls` | n_clips+1 (fewer on an error row) |
| `error` | null, or `"ExcType: msg"` — the row then has `prediction=""`, `correct=False` |
| `response_text / think / frame_alloc` | **always null for per_stream** — reasoning traces are not stored on this run |

**Resume** (`run_bench.py:112-123, 215-217`): on resubmit the harness re-reads the output file and
skips every `(id, method, backend, pass_idx)` already present. Granularity is one (question, pass):
a question killed mid-way restarts that pass from its first perception call.

---

## 6. Job 63676 — the SigLIP clip-selection gate

Tests the proposal *"score each clip against the question (CLIP/SigLIP), keep the top-m, spend the
budget there"* for **minutes of GPU** before committing a full-1000 run.

**Step 1 — offline scorer gate** (`analysis/clip_scorer_gate.py`): for the **172 questions with
parseable ground truth** (40 name a video in the question text, 132 in the gold option; the other
828 are skipped → 534 clip scorings per model), score every clip against the question with both
**CLIP-B/32** (scored 37.1% in the D3 130-set eval) and **SigLIP-so400m-384** (never used as scorer
before), 8 uniform thumbnails per clip, max & mean pooling. Uses the *exact* frame indices and
shared `clip_scores()` the real eval would use (`clip_scorer_gate.py:38-48` mirrors
`clip_select.py:488-500`) — a scorer that passes here is byte-for-byte the production scorer.
Reports **named-clip recall@1/@2, mean rank, score margin** vs a ~1/K random baseline →
`bench/results/clip_scorer_gate.json` + table in `analysis/logs/63676.gatesmoke.out`.

**Step 2 — end-to-end smoke**: `clip_select_siglip_top1` + `clip_select_siglip_top4`, 5 questions
× 2 methods × 4 passes = 40 InternVL3 calls → `bench/results/smoke_clipsel_siglip.jsonl`. Validates the
name→scorer wiring (`run_bench.py:47-49,96-105`), offline SigLIP load, both prompt branches — and
**top4 is an identity check**: with K≤4 clips it keeps everything, so its prompt is byte-identical
to the `temporal_weighted` baseline (`clip_select.py:222-228`).

**Decision rule**: SigLIP recall@1 must materially beat CLIP-B/32 *and* random, and the smoke must
run clean (top4 ≡ baseline). Then a full-1000 `clip_select_siglip` run is worth queueing — that's
where "biggest gains at large n" gets tested on the k≥3 (513 Q) / k=4 (277 Q) subsets already
built. If SigLIP ranks no better than CLIP, the cheap-scorer idea dies here.

**OUTCOME (2026-07-08, job complete):** gate **failed** — full SigLIP run not justified.

| Scorer | Primary recall@1 (n=40) | Primary recall@2 | Secondary agreement (n=132) | Margin named−best-other |
|---|---|---|---|---|
| Random | 37.1% | — | 34.6% | — |
| CLIP-B/32 | 42% (max) / 45% (mean) | 92% / 85% | **50% / 49%** | ≈ −0.0003 |
| SigLIP-so400m | **50% / 50%** | 90% / 85% | 47% / 47% | ≈ +0.001–0.003 |

SigLIP's primary-set edge is 2–3 questions out of 40 (noise); on the 3×-larger secondary set it is
*worse* than CLIP; margins are ≈0, so even correct picks are coin-flip-close — hard top-1 pruning
would drop the needed clip about half the time. Combined with D3 (CLIP selection lost to
use-everything 53.8 vs 55.8), cheap-scorer *pruning* is now dead on two independent measurements.
**Surviving variants** if selection is revisited: drop-lowest-1 at n=4 (recall@2 is 85–92% and n=4
was D3's only win; the 277-Q k4 subset exists), or soft relevance-weighted frame allocation (the
deferred `allocate_frames` v2 hook). The step-2 smoke ran clean (40 rows, 0 errors, 0 abstains) —
plumbing is validated for any future arm.

---

## 7. Verification — done and to-do

**Already verified (2026-07-08):**
- [x] A100 compatibility: torch cu128 has sm_80; bf16 + SDPA tested on-node; no flash-attn anywhere.
- [x] All 9 jobs started; logs show correct config (`methods=per_stream`, 125 Q/shard, 4 passes).
- [x] First rows healthy — watcher confirmed records flowing, zero Tracebacks/OOM.
- [x] Working tree was clean at launch: jobs run committed code.
- [x] Resume keys match what rows record (a killed shard can be resubmitted safely).

**End-of-run checklist:**
- [ ] `wc -l` each shard file — expect exactly 500 rows; resubmit the same array index for any short shard (resume skips done rows).
- [ ] `jq -c 'select(.error != null)' shard*.jsonl | wc -l` (or `grep -c '"error": "'`) for real errors — every row serializes `"error": null`, so a bare `grep -c '"error":'` counts ALL rows — **error rows count as done and are never retried**; requeue those ids deliberately if any.
- [ ] If a shard was killed mid-write, delete the truncated final JSON line before running summaries (a corrupt line crashes the end-of-run re-read at `run_bench.py:224`).
- [ ] Check abstain rate (`abstained==true`) — high abstain means truncated aggregator traces, not model wrongness.
- [x] Gate job: STEP 2 completed clean — 40 rows, 0 errors, 0 abstains; SigLIP wiring validated (accuracies on 5 questions carry no signal).
- [ ] Per-category table: `metrics.py` over the merged shards → Table 1 + per-task_type accuracy (the missing per-question-category InternVL3 result).

**Timing measured live**: an early 21-min window (~08:17) suggested ~71 s/row and put shards 1–2
past the 16 h limit, but the 53-min recheck (446 rows total, 36–89/shard) showed that was startup
noise — **all 8 shards project comfortably under the limit** (fastest ~5 h, slowest ~11.5 h;
finish expected the same evening). Resubmit command if a shard still times out: identical
`sbatch --array=<idx> ...` line — resume handles the rest.

---

## 8. Where this fits

- **Centralized vs decentralized (Task 1)**: these 4000 rows are the decentralized column for
  CVBench, against the existing centralized full-1000 results (weighted 61.8 / even 60.8 /
  2×2 stitch 57.4). `perception_latency_par_s` gives the parallel-latency argument.
- **Hardware note**: these rows come from A100-80GB; earlier full-1000 runs were L40S. Irrelevant
  for accuracy aggregates (4-pass sampling noise dominates), but say so if anyone audits per-row
  reproducibility.
