# CVBench: multi-camera understanding — failure analysis (thinking VLMs)

**Status:** Stage A (qualitative) **complete**. Both subset runs finished on the cluster:
**Qwen3-VL-8B-Thinking 62.2%** (28/45) and **InternVL3-8B 55.6%** (25/45), both prompted
to emit a visible `<think>…</think>` trace so we can read *why* they fail. The failure-mode
evidence in §5 is quoted verbatim from the models' own traces (full dumps:
`analysis/qwen3vl_failures.md`, `analysis/internvl3_failures.md`). Stage B — the full
1000-question run for a reliable accuracy-vs-cameras plot — is staged but deferred (§7).

## 1. What CVBench tests, and what "cameras" means here

CVBench is a cross-video benchmark: each question is answered over **1–4 videos**
(`video_1..video_4`) that are asynchronous, multi-view, or contextually related, across
**15 task types**. There are no literal camera IDs, so we treat **number of videos per
question as the "number of cameras"** — the axis the PI wants accuracy plotted against.
All questions are multiple-choice (A–D) or yes/no.

The 15 task types group into three families:
- **Object association** — object recognition, attribute recognition, joint counting, entity matching
- **Event association** — anomaly detection, scene recognition, key-action recognition, event retrieval
- **Complex reasoning** — multi-view scene understanding, temporal reasoning, spatial navigation, difference captioning, counterfactual reasoning, summarization, procedural transfer

## 2. Example question types (verbatim from the dataset)

> Cross-video reasoning means the answer can't be read off any single clip — the model
> must bind entities/events *across* clips. These are the cases multicam understanding
> is supposed to cover.

**Object association — Cross-video Object Recognition (id 12, 4 videos)**
> "What kind of thing appears in multiple videos as an essential part of baking?"
> A. Oven. / B. Digital thermometer. / C. Ingredients Flour. / D. Digital kitchen scale.
> **Answer: C**

**Object association — Cross-video Entity Matching (id 247, 4 videos)**
> "Did the player with number 19 receive emergency assistance in all the relevant videos?"
> Yes. / No.  **Answer: Yes**

**Object association — Multi-video Attribute Recognition (id 35, 2 videos)**
> "What visual attribute connects the individual in both videos?"
> A. The use of branded products. / B. Vibrant blue shirt. / C. Outdoor settings. / D. Silver watch.
> **Answer: B**

**Event association — Cross-video Event Retrieval (id 33, 2 videos)**
> "Which video conveys the theme of overcoming negative traits like fear or jealousy?"
> A. Video 1. / B. Video 2. / C. Both Video 1 and Video 2. / D. Neither Video 1 nor Video 2.
> **Answer: B**

**Complex reasoning — Multi-video Temporal Reasoning (id 248, 4 videos)**
> "Based on the interconnections, what is the correct chronological order of the rescue
> process depicted across the videos?"
> A. 3-4-1-2. / B. 4-1-2-3. / C. 1-2-3-4. / D. 2-4-3-1.  **Answer: D**

**Complex reasoning — Joint-video Spatial Navigating (id 270, 3 videos)**
> "If sitting on a large chair close to the television, how to get to the stove?"
> A.…top-right…top-right… / B.…top-left…top-left… / C.…top-right…top-left… / D.…top-left…top-right…
> **Answer: C**

(The Stage-A subset — 45 questions spanning all 15 task types and 2/3/4-video buckets —
is in `analysis/subset.json`.)

## 3. Method

- **Subset:** `analysis/select_subset.py` → 45 questions (all 15 task types; 2/3/4-video spread).
- **Data:** `analysis/download_videos.py subset` pulls just those ~101 clips from the HF
  archive `Dongyh35/CVBench` (one 40 GB zip; we range-extract only what we need).
- **Thinking:** both models are prompted for `<think>…</think>` then `<answer>…</answer>`.
  Qwen3-VL runs via `Video-R1/src/eval_thinking.py`; InternVL3 via lmms-eval task
  `mvr_think` with `--log_samples` (the full trace lands in the samples `resps` field).
- **Analysis:** `analysis/parse_lmms_samples.py` normalizes the InternVL3 logs; then
  `analysis/analyze_failures.py` writes per-model accuracy (overall / by #videos / by task)
  and `<label>_failures.md` containing every wrong case *with its reasoning trace*.

**How the camera views are fed.** There is no special multi-camera input format: the
clips are concatenated into ONE token sequence, separated only by markers — the Qwen leg
interleaves plain-text labels (`Video 1:` … `Video 2:` …), the lmms-eval/InternVL leg
splices in tiny rendered marker *clips* ("This is video N"). Each clip contributes 8
evenly-spaced frames as vision tokens, each frame stamped with its within-clip timestamp.
Crucially, **no cross-clip synchronization information exists** — nothing tells the model
how clip 1's timeline relates to clip 2's. Any cross-video temporal claim must be inferred
from content alone, so part of what the benchmark measures is whether the model can
maintain the multicam structure that exists only in the prompt layout (see §5.4/§5.5 for
what happens when it can't).

## 4. Accuracy vs. number of cameras

Plots: `analysis/accuracy_vs_cameras.png` and `analysis/accuracy_by_task.png` (from
`analysis/plot_accuracy.py`; raw numbers in `analysis/accuracy_by_cameras.json`).

| #videos | Qwen3-VL acc | InternVL3 acc | n |
|--------:|:------------:|:-------------:|--:|
| 2 | 53.3% | 40.0% | 15 |
| 3 | 68.8% | 62.5% | 16 |
| 4 | 64.3% | 64.3% | 14 |
| **all** | **62.2%** | **55.6%** | **45** |

Two reads, with the small-n caveat (~15 questions per bucket):

1. Accuracy does **not** fall monotonically with more cameras — the **2-video bucket is
   the hardest for both models**. Reading the traces, that bucket is dominated by
   discrimination/verification forms ("Which video shows X?", "Did both videos…?") whose
   gold is often "None of them"/"No", and both models show a strong premise-acceptance
   bias (§5.1). At 3–4 videos the questions skew toward association ("what is shared
   across the videos"), where partial perception of each clip still narrows the options.
2. The failure *modes* do shift with camera count even where accuracy doesn't:
   aggregation errors (counting, find-the-common-element) appear almost exclusively at
   4 videos (§5.3), and given-order bias on ordering questions persists at every count
   (§5.4).

The Stage-B full run (1000 questions; n = 487/236/277 per bucket) is what can settle the
actual curve — this subset only suggests its shape.

### 4.1 Blind baseline (no video input)

Rerunning Qwen3-VL with **identical prompts but zero visual input**
(`eval_thinking.py --no_video`, results in
`Video-R1/src/r1-v/eval_results/eval_subset_qwen3vl_novideo.json`) scores
**40.0%** (18/45), vs ~31% blended chance (25% MCQ / 50% yes-no) and 62.2% with video.
So seeing the videos is worth ~22 points on this subset, and ~9 points of the with-video
score is recoverable from text priors alone. Three things the baseline exposes:

- **Some task types are largely text-guessable from option wording**: blind gets 3/3
  Multi-video Attribute Recognition, 2/2 Multi-video Key-Action Recognition, 2/2 Video
  Difference Caption. Worth flagging as benchmark artifacts (distinctively-worded gold
  options) when reporting per-task accuracy.
- **3 questions flip the wrong way with vision** (ids 1, 81, 247): blind language priors
  answer them correctly, while the with-video run talks itself out of the right answer
  (e.g. id 247: blind accepts the premise "player 19 was assisted" → Yes (gold), while
  with video the model misreads jersey numbers in sampled frames and answers No).
- **Rumination is endemic, not video-induced**: 26/45 blind runs and 22/45 with-video
  runs produced no `<answer>` tag before the 2048-token budget; the regex fallback over
  the tail recovers a choice either way (§5.6 counts only the failures).

The blind series is plotted in `accuracy_vs_cameras.png`: it *declines* with camera
count (46.7% → 37.5% → 35.7%) while the with-video lines rise from 2→3, so the vision
gap **widens** with the number of cameras (~7 pts at 2 videos → ~30 pts at 3–4). The
marginal value of actually seeing the videos grows as more cameras are involved — more
evidence that the weak 2-video bucket is a text/premise problem, not a perception one.

### 4.2 Temporal complexity of questions vs failures

Metric (`analysis/temporal_complexity.py`, rule-based and spot-checked): every question
is scored **L0 non-temporal** / **L1 temporal reference** (a single event or moment is
referenced, e.g. "during the closing moments") / **L2 temporally complex** (multiple
events must be *related in time*: permutation answer options like "2-4-3-1", explicit
cross-video ordering, or ≥2 temporal keywords). Polysemous words ("when", "step", the
"which of the following" boilerplate) are deliberately excluded after spot-checking.

**How much of CVBench is temporal:** of the full 1,000 questions, **130 (13%) carry
temporal context — 47 L1 + 83 L2**. Temporal content crosses task-type lines: only 75
questions are the dedicated "Multi-video Temporal Reasoning" type, so ~55 temporal
questions hide inside other task types (e.g. id 0 is Scene Recognition but hinges on
"closing moments"). Distribution plot: `temporal_complexity_dist.png`; per-id labels:
`temporal_complexity.json`.

**Accuracy vs temporal level** (subset, `accuracy_vs_temporal.png` — n's are tiny,
treat as anecdote):

| level | n | Qwen3-VL | InternVL3 | Qwen3-VL blind |
|--|--:|:--:|:--:|:--:|
| L0 non-temporal | 40 | 62.5% | 62.5% | 42.5% |
| L1+L2 temporal | 5 | 60.0% (3/5) | **0.0% (0/5)** | 20.0% (1/5) |

The signal worth chasing: **InternVL3 failed every temporal question** (ids 0, 18, 27,
248 + the L1 case) — fully consistent with its given-order bias (§5.4) and
marker-shortcut (§5.5) traces, where it never extracts order from content. Qwen3-VL
handles ordering questions better (3/4 L2) when its budget survives. With n=5 this is
qualitative; the full set has **130 temporal questions**, so the Stage-B run would give
a statistically usable temporal bucket — added reason to run it.

All temporal questions any model failed, with all three models' traces side by side:
`analysis/temporal_failures.md`.

## 5. Failure modes (confirmed from the traces)

All 37 wrong cases (17 Qwen3-VL, 20 InternVL3) were read; quotes are verbatim from the
models' own reasoning. Modes 5.1–5.5 were on the original candidate list and are
confirmed; 5.6–5.7 emerged from the traces and were not anticipated.

### 5.1 Premise acceptance / yes-bias on verification questions
The question's framing is imported as evidence; golds of "None of them"/"No" suffer
most — this is what sinks the 2-video bucket.
- **InternVL3, id 0** (gold **No**, said Yes): "Since both videos show instances of a
  team scoring a decisive goal or point in the closing moments of the match, the answer
  is yes" — asserted without ever locating either goal.
- **Qwen3-VL, id 8** (gold **D. None of them**, said A): the trace recycles the question
  text as if it were a content description — "the user's note for Video 1 says 'the
  skier falls down to emphasize the exciting atmosphere.' Wait, no, actually…" — and
  never resolves whether a fall is actually visible in either clip.

### 5.2 Single-video shortcutting
Answers from the one clip that looks informative; the trace never engages the others.
- **InternVL3, id 197** (gold C, said D): "the candle holder is seen on a glass shelf
  above the television in the hallway. This is the only location mentioned in the
  video" — "the video", singular, on a 2-video question that requires fusing both
  apartment walkthroughs.
- **InternVL3, id 2** (gold B, said A): describes Video 1's goal celebration in detail,
  then dismisses Video 2 with "no clear celebration … visible in the provided frames".

### 5.3 Cross-video aggregation failure (counting / find-the-common-element)
Each clip gets summarized by its *salient* object, and the non-salient shared element is
lost. Appears almost exclusively at 4 videos.
- **Qwen3-VL, id 57** (gold **4**, said 3): "Videos 1, 2, and 3 all prominently show
  beverages. Video 4 does not have beverages prominently displayed" — the sweep misses
  the one clip where beverages are background rather than the subject. Verified against
  the exact 8 frames the model saw (`analysis/failure_examples/id57_video4_frames.jpg`):
  Video 4's cart holds a gallon orange-juice jug and bottled drinks, but they appear
  *inside the shopper's cart*, whereas Videos 1–3 show beverages as *store displays* —
  the model pattern-matched "beverage display" from the first three clips and discounted
  the in-cart evidence. (Caveat: the gold's "prominently" is itself a judgment call.)
  All four clips stitched for review: `analysis/failure_examples/id57_joint_counting_stitched.mp4`.
- **Qwen3-VL, id 50** (gold B. Notebook, said A): "Video 1: Notebook … Video 2: Backpack
  … Video 3: Pens … None of these objects appear in all three videos" — then burns the
  rest of its token budget re-deriving the same three salient objects in a loop instead
  of re-inspecting the clips for a non-salient common one.
- **InternVL3, id 12** (gold C. Flour, said D): promotes the salient gadget — "the
  digital kitchen scale appears in multiple videos … in 'Video 2' it is used to measure
  the temperature of the bread" — also mislabeling a thermometer as a scale to make the
  story work.

### 5.4 Temporal mis-ordering: given-order bias
On "order the clips" questions, both models default to the presentation order 1-2-3-4
instead of inferring order from content, then invent a narrative to justify it.
(Quantified in §4.2: InternVL3 is 0/5 on all temporal questions in the subset.)
- **Both models, id 248** (gold **D. 2-4-3-1**, both said C. 1-2-3-4). InternVL3:
  "Video 1 shows the initial emergency response… Video 4 shows the final steps of the
  rescue process… Therefore, the correct order is C. 1-2-3-4."
- **InternVL3, id 18** (gold C. 2-1-3, said D. 1-2-3): identical pattern on artifact
  processing.

### 5.5 Harness-artifact shortcut: reasoning over the boundary markers
The lmms-eval leg inserts short "This is video N" marker clips so the model can tell
clips apart. InternVL3 used the markers *as the evidence*:
- **InternVL3, id 27** (gold **No**): "Based on the sequence of the video titles, 'This
  is video 1' appears before 'This is video 2' … Therefore, it is logical to conclude
  that video 1 occurred before video 2 in the trial's progression." (It also answered
  "A" to this Yes/No question — the answer format drifted too.)

### 5.6 Runaway rumination → token-budget truncation (Qwen3-VL only)
**10 of Qwen3-VL's 17 failures** (ids 8, 163, 2, 67, 0, 197, 50, 270, 12, 10) never
produced an `<answer>` tag: the trace loops ("Wait, let me check again…") re-parsing the
*prompt structure* — frame timestamps, "the user's description" — instead of the pixels,
until the 2048-token budget cuts it off mid-sentence (marked "no `<think>` tag parsed"
in the dump). In id 0, answer extraction failed entirely and the raw rumination became
the recorded prediction. 6 of the 10 are 2-video questions. This is partly a harness
interaction (budget + tag parsing), but the underlying behavior is real: under
uncertainty the model interrogates the prompt text rather than re-attending to the
videos — id 197 spends ~1500 tokens trying to reconstruct "the user's formatting" of
the timestamps. InternVL3 shows the opposite pathology: terse post-hoc rationalizations
("Based on the video content, …") that assert conclusions without inspectable reasoning.

### 5.7 Spatial-frame errors across views, compounded by frame sampling
- **Both models, id 270** (gold C): each reads the rooms correctly in isolation but
  flips left/right when stitching the views into one floor plan (Qwen3-VL said A,
  InternVL3 said B — same fusion step, different wrong turn).
- **Frame-sampling blindness** (8 frames/video) feeds several modes above: in id 247
  (gold **Yes**) Qwen3-VL hunts for jersey number 19 across 4 clips, reads "6"/"8" in
  the sampled frames, and concludes the player "does not exist", answering No.

**Net read:** per-clip perception is mostly fine in the traces; the *binding* step —
same entity/event tracked across clips — is where both models fail. Qwen3-VL fails by
over-deliberating about the prompt; InternVL3 by under-deliberating about the videos.

## 6. Reproduce

```bash
# 0) (one-time) deps on the cluster env
pip install huggingface_hub remotezip

# 1) subset + subset videos  (CPU / login node)
#    (boundary markers already ship in lmms-eval/res/; run make_markers.py only if missing)
python3 analysis/select_subset.py --n 45
python3 analysis/download_videos.py subset
python3 analysis/download_videos.py verify --qa analysis/subset.json   # expect 0 missing

# 2) GPU node (L40 / A100)
#    Qwen3-VL (Thinking):
python3 Video-R1/src/eval_thinking.py \
    --model_path Qwen/Qwen3-VL-8B-Thinking \
    --input_json analysis/subset.json \
    --output Video-R1/src/r1-v/eval_results/eval_subset_qwen3vl.json \
    --nframes 8 --max_new_tokens 2048
#    InternVL3-8B via lmms-eval (run from lmms-eval/ so ./res markers resolve):
cd lmms-eval && python3 -m lmms_eval \
    --model internvl2 \
    --model_args pretrained=OpenGVLab/InternVL3-8B,num_frame=8 \
    --tasks mvr_think --batch_size 1 --log_samples \
    --output_path ./logs/ ; cd ..

# 3) analyze (CPU)
python3 analysis/parse_lmms_samples.py \
    --samples lmms-eval/logs/*InternVL3-8B*/*_samples_mvr_think.jsonl \
    --out analysis/internvl3_normalized.json
python3 analysis/analyze_failures.py \
    qwen3vl=Video-R1/src/r1-v/eval_results/eval_subset_qwen3vl.json \
    internvl3=analysis/internvl3_normalized.json
python3 analysis/plot_accuracy.py
```

## 7. Open items / caveats
- **Stage B (deferred):** `python3 analysis/download_videos.py full` (40 GB from HF
  `Dongyh35/CVBench`), then `analysis/run_eval.sbatch` with
  `SUBSET=Video-R1/src/r1-v/Evaluation/CVBench.json` (1000 questions; n = 487/236/277
  per video bucket) to settle the accuracy-vs-cameras curve. At that scale, swap
  `eval_thinking.py` to a vLLM backend for speed.
- Qwen3-VL's truncation failures (§5.6) conflate "wrong" with "ran out of tokens": rerun
  those 10 questions with a larger `--max_new_tokens` (e.g. 4096) before quoting
  per-task accuracy for Qwen3-VL.
- InternVL3's prompt-induced "thinking" (`mvr_think`) mostly yields post-hoc assertions;
  its native reasoning system prompt may give more diagnostic traces.
- 8 frames/video is the benchmark default; id 247-style failures (§5.7) are sampling
  artifacts — worth a frame-count sweep if a task looks unfairly penalized.
- §5.5 is a harness artifact to keep in mind when reading traces: the "This is video N"
  marker clips can themselves become (false) evidence for temporal questions.
