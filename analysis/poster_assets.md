# Poster assets — CVBench + CrossView (UT Austin Multi-Camera)

One-stop index of everything useful for the poster: the dataset clarification,
verbatim temporal-logic example questions, the figures/charts (with paths), and
the headline numbers. All numbers verified against the source files.

## 0. Two benchmarks (the 45-vs-60 thing)

These are **two separate benchmarks shown side-by-side**, not one number changing:

- **CVBench = 45-question subset** — the original benchmark (1–4 *unrelated*
  clips, association/reasoning across them). Every CVBench header reads `/45`.
- **CrossView = 60-question subset = UT Austin SwarmLab "Multi-Camera" VQA** —
  *synchronized* multi-camera (1–16 views, capped to ≤4 here). It **was** run;
  this subset is MEVA-only, 60 = 20 Temporal + 20 Event-Ordering + 20 Spatial.

So yes — UT Austin's dataset is in the project; the `/45` you kept seeing is the
other (original CVBench) benchmark reported next to it.

## 1. Temporal-logic example questions (verbatim — verified)

The 5 CVBench temporal questions (complexity ≥ L1) that are both in the eval
subset (so real per-model predictions exist) **and** carry a neuro-symbolic
temporal-logic view. Deliberately a 3-correct / 2-wrong mix for the thinking
model. Text/options/gold verbatim from `analysis/cvbench_temporal_logic_team.json`;
predictions regenerate via `analysis/temporal_complexity.py` (`temporal_failures.md`). Models: **Qwen3-VL-8B-Thinking**
(qwen3vl), **InternVL3-8B** (internvl3), **qwen3vl_blind** (no video).

### Card A — id 18 · event-sequencing · L2 · 3 videos (Multi-video Temporal Reasoning)
> **Q:** What is the correct video sequence for processing artifacts?
> A. 3-1-2.  B. 2-3-1.  **C. 2-1-3.** ✅  D. 1-2-3.

- **LTL template:** `F(e1 ∧ F(e2 ∧ F(e3 …)))` — recover the true total order of N events (options are permutations).
- **qwen3vl ✅ C** · internvl3 ✗ D · blind ✗ A
- Use: clean success-vs-baseline contrast on an ordering question.

### Card B — id 248 · event-sequencing · L2 · 4 videos (Multi-video Temporal Reasoning)
> **Q:** Based on the interconnections, what is the correct chronological order of the rescue process depicted across the videos?
> A. 3-4-1-2.  B. 4-1-2-3.  C. 1-2-3-4.  **D. 2-4-3-1.** ✅

- **LTL template:** `F(e1 ∧ F(e2 ∧ F(e3 …)))`.
- **qwen3vl ✅ D** · internvl3 ✗ C (1-2-3-4) · blind ✗ A
- Use: gold is the *maximally scrambled* option → illustrates the **given-order bias** (§5.4): baselines default to identity order 1-2-3-4; the thinking model recovers true order.

### Card C — id 27 · cross-stream-precedence · L2 · 2 videos (Multi-video Temporal Reasoning)
> **Q:** Following the flow of the trial, did video 1 happen before video 2?
> Yes.  **No.** ✅

- **LTL template:** `F(e_vi) ∧ F(e_vj) ∧ (e_vi ≺ e_vj)` — precedence across streams; CVBench gives **no cross-stream clock**, so order must come from content.
- **qwen3vl ✅ No** · internvl3 ✗ Yes · blind ✓ No
- Use: InternVL3's trace literally cites the prompt's "This is video 1" marker → vivid **harness-artifact shortcut** (§5.5). Caveat: blind also gets it right → one "temporal" case is answerable from text priors alone.

### Card D — id 0 · multi-event-relation · L2 · 2 videos (Cross-video Scene Recognition)
> **Q:** Did both videos feature a team successfully scoring a decisive goal or point during the match's closing moments?
> Yes.  **No.** ✅(gold)

- **LTL template:** multiple temporal references jointly satisfied (triggers: *during, closing, moments*).
- **qwen3vl ✗** (no parseable answer — runaway rumination, no `<answer>` tag, §5.6) · internvl3 ✗ Yes · blind ✗ Yes
- Use: bounded-window joint-event question all three miss; show the **token-budget truncation** failure beside a success. Attribute Qwen's as "no parseable answer," not a confident wrong pick.

### Card E — id 2 · bounded-eventually · L1 · 2 videos (Cross-video Event Retrieval)
> **Q:** Which video shows the celebration of a team after successfully leading or winning in the match?
> A. Video 1.  **B. Video 2.** ✅(gold)  C. Both of them.  D. None of them.

- **LTL template:** `F_[window](e)` — event within a referenced window.
- **qwen3vl ✗ A** · internvl3 ✗ A · blind ✗ A (all default to Video 1)
- Use: even single-reference temporal grounding across 2 streams is hard; everyone picks Video 1.

**Poster layout suggestion:** four columns, one per LTL pattern (event-sequencing,
cross-stream-precedence, multi-event-relation, bounded-eventually); each card =
verbatim Q+options + LTL template + gold + a correct/wrong badge per model.
InternVL3 is 0/5 across these (clean baseline-failure column).
**Honesty caveat:** complexity labels are rule-based/coarse.

## 2. Figures & charts (paths + where to use)

**Project results — CrossView (all committed, `analysis/crossview_out/`):**
- `accuracy_vs_orig_cameras.png` — accuracy vs *original* synchronized-camera count (2,3,5,7,12); InternVL3 craters to 0% @5. **Headline "true multicam is hard" figure.**
- `accuracy_vs_cameras.png` — accuracy vs #videos seen (2/3/4); InternVL3 65%→25%.
- `accuracy_by_task.png` — task bars; anchors the "Qwen 0/20 event-ordering" headline.
- `cvbench_vs_crossview.md` — **main side-by-side results table** (regenerate via `crossview_vs_cvbench.py`, then lift directly).
- `crossview_camera_curve.md` — camera-count table + caption for the orig-cameras figure (regenerate via `crossview_camera_curve.py`).
- `qwen3vl_failures.md` / `internvl3_failures.md` — verbatim failure traces → "why models fail" callout quotes (regenerate via `analyze_failures.py`).

**Project results — CVBench (committed, `analysis/`):**
- `accuracy_vs_cameras.png` — CVBench does **not** degrade with #videos (contrast panel).
- `accuracy_vs_temporal.png` — accuracy by L0/L1/L2 (flag tiny L1=1/L2=4 n).
- `temporal_complexity_dist.png` — subset vs full-set temporal mix (methods sidebar).
- `blind_sanity.md` — source/citation for the 40% blind baseline.
- id57 failure caption + intro text — see `mentor_report.md` §6 and `analysis/failure_examples/` (the former `cvbench_multicam_failures.md` is no longer tracked).
- `crossview_question_types.md` — "what is CrossView / 1–16 cameras" background + stats.

**Qualitative multi-video example (id57, UNTRACKED — `analysis/failure_examples/`):**
- `id57_joint_counting_grid2x2.mp4` — 2×2 synchronized grid, cleanest "what the model sees" visual.
- `id57_joint_counting_stitched.mp4` — 4 clips stitched.
- `id57_video{1..4}_frames.jpg` — 8-frame contact sheets; **video4 is the "gotcha"** (beverages in the cart, not a display — the clip the model discounted → said 3, gold 4).

**Upstream CVBench paper art (committed, `assets/` — NOT our results):**
- `figure1.png` (task taxonomy + histograms), `figure2.png` (QA examples),
  `results_1/2/3.png` (published leaderboards: Human/GPT-4o/InternVL2.5 etc.).
  Use only as benchmark intro / reference baselines.

## 3. Headline numbers (verified)

- **Overall:** CVBench — qwen3vl 62.2% (28/45), internvl3 55.6% (25/45), blind 40.0% (18/45). CrossView — internvl3 38.3% (23/60), qwen3vl 31.7% (19/60).
- **Video helps:** blind 40.0% → qwen3vl 62.2% = **+22.2 pp** (+10 questions) over language priors (audited clean, 0 vision tokens / 0 leakage).
- **CrossView Event-Ordering collapse:** qwen3vl **0/20 = 0%**; internvl3 6/20 = 30%.
- **CrossView by task:** Spatial qwen 65% / internvl 40%; Temporal qwen 30% / internvl 45%; Event-Ordering qwen 0% / internvl 30%.
- **Degradation with cameras (CrossView):** internvl3 64.7% (2 videos) → 25.0% (4 videos); by original cameras internvl3 65%@2 → 13%@7. **CVBench does NOT degrade** (contrast).
- **Scale:** CVBench = 1000 QA / 1315 videos / 15 task types / 1–4 unrelated clips. CrossView = 6,354 usable QA / 1–16 synchronized cameras / 4 sources (MEVA, Ego-Exo4D, AgiBotWorld, nuScenes); this run = 60-Q MEVA MCQ subset.

## 4. Caveats for the poster
1. CVBench (45) and CrossView (60) are **different benchmarks**, side-by-side — not the same questions.
2. Subset sizes are small (45 / 60) and some buckets are tiny (L1=1, L2=4; 3-camera n=3) — report as illustrative, not significance-tested.
3. CrossView here is **MEVA-only, ≤4-camera cap**; all 60 are answer-safe (no lossy ego-exo4d cap in this run).
4. The `assets/` figures are upstream paper art; project results live in `analysis/`.
5. id57 media and `temporal_questions_130.md` / `cvbench_temporal_logic_team.json` are **untracked** — `git add` them before relying on them being in the repo.
