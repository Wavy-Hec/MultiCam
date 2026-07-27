# Multi-camera video understanding — literature review for the direction decision

*2026-07-20. Deep-research run: 23 primary sources fetched, 115 claims extracted,
25 top claims adversarially verified (3 independent verifiers each; 23 confirmed,
2 refuted). Items marked ⚠ were extracted from the primary source but did not go
through the adversarial-verification pass — treat as read-the-paper-first.*

**TL;DR for Wednesday**: all three branches have real 2024–2026 exemplars, but
they are not equally adoptable. Pre-training exists only in autonomous driving
and needs calibrated rigs + dense annotations. Agentic is the most mature and
now has a system (AgentCVR ⚠) doing exactly cross-video QA with an 8B open
model — but open 8B controllers are the documented weak link. RL is the branch
most compatible with our current pipeline (same base models, same fixed-frame
regime, QA-pair supervision only), and it is the only branch with a verified fix
for the cross-view-consistency failure. There are also credible methods
*outside* all three branches (training-free token merging, inference-time
contrastive decoding, memory/database scene representations).

---

## Branch 1 — Pre-training (native multi-camera input)

### OmniDrive (arXiv 2405.01533, CVPR 2025) — verified
- 3D multi-view VLM-agent for driving; contrasts **Omni-L** (LLaVA-style MLP
  alignment extended to multi-view) vs **Omni-Q** (BEV/Q-Former-style with
  perception + carrier queries) as two ways for an LLM to natively consume
  6-camera input.
- Multi-view QA pre-training helps downstream QA: DriveLM 0.53 → 0.56
  (pre-training) → 0.58 (+LLaVA-665k). Gain over generic VQA data is modest
  (+0.01 over LLaVA-665k alone).
- **Refuted during verification (0–3): OmniDrive does NOT stitch views into
  composite images.** Do not cite it as a stitching precedent.

### BEV-InMLLM (arXiv 2401.00988, CVPR 2024) — verified
- Retrofits *frozen* single-view MLLMs (BLIP-2, MiniGPT-4, Video-LLaMA) for
  6-camera video with two small trainable add-ons: a **Multi-view Q-Former**
  (concat per-view tokens, cross-attend with learnable queries) and a
  plug-and-play **BEV injection** module over a frozen LSS/BEVFormer extractor.
- Gains decompose: ~9% over base MLLMs on NuInstruct; MV module alone +5-6% on
  risk/planning; removing BEV injection costs 2.1 overall and **4.1 on spatial
  tasks** — the strongest verified evidence that an explicit shared spatial
  representation specifically helps spatial multi-camera questions.
- Supervision catch: NuInstruct = 91K QA pairs SQL-generated from NuScenes
  annotations; needs calibrated rig + dense labels + BEV extractor. Does not
  transfer directly to CVBench's uncalibrated, unrelated-clip input.

**Branch verdict**: transferable *lesson* (cheap learned cross-view query
modules on a frozen backbone work; spatial questions want a unified spatial
representation), not a transferable *recipe* for CVBench.

---

## Branch 2 — Agentic / tool-use

### Stanford VideoAgent (arXiv 2403.10517, ECCV 2024) — verified
- Training-free loop: GPT-4 predicts an answer, self-scores confidence, calls
  CLIP segment retrieval + a VLM captioner until confident.
- 54.1% zero-shot EgoSchema / 71.3% NExT-QA using **8.4/8.2 frames on
  average** — parity-or-better with a 180-frame caption-everything baseline at
  ~20× fewer frames. (The 0.6-pt adaptive-vs-uniform margin on the 500-subset
  is within noise; the robust finding is frame-efficiency at parity, verified
  2–1 with that dissent noted.)
- **The reproduction caveat that matters for us (verified 3–0): the loop is
  highly sensitive to controller capability** — GPT-4 60.2% vs GPT-3.5 48.8%,
  Llama2-70B 45.4%, Mixtral-8x7B 37.8%, attributed mainly to structured-JSON
  output ability. Running InternVL3-8B/Qwen2.5-VL as the controller is the
  risky part, not the tools.

### VideoAgent, memory-augmented (arXiv 2403.11481, ECCV 2024) — verified
- Training-free agent over a pre-built structured memory: 2-second-segment
  temporal memory (captions + features) plus an **object-centric SQL database**
  (category, CLIP features, appearing segments); four tools (segment
  localization, caption retrieval, VQA, object-memory query).
- +6.6% NExT-QA, +26.0% EgoSchema over baselines. The SQL object memory
  extends naturally to multi-camera (add a camera-ID column, cross-camera
  re-ID via stored CLIP features) — plausible extension, not demonstrated.

### Deep Video Discovery (arXiv 2505.18079, NeurIPS 2025, Microsoft) — verified
- Agent autonomously plans over three search tools on a multi-granular
  database (global browse / clip search / frame inspect). **LVBench SOTA
  74.2%** vs prior best 60.8% and bare o3 57.1% — the +17.1 over bare o3
  isolates the agentic-search contribution from backbone strength.
- Single-long-video, built on proprietary o3 + GPT-4.1 captions.

### ⚠ AgentCVR (arXiv 2605.29643) — extracted, not adversarially verified
- **The closest published system to our setting**: multi-agent framework for
  cross-video reasoning (N≥2 independent streams). A Qwen3-VL-4B/8B master
  agent in thinking mode iteratively calls visual/audio sub-agents on specific
  video IDs and time intervals.
- Trained with "Script-Simulated RL": GRPO in a text-only surrogate
  environment built from LLM-generated video scripts — no human trajectories,
  no raw-video rollouts (~5× cheaper), transfers zero-shot to real videos.
- On CrossVid: AgentCVR-8B 42.03% vs single-pass Qwen3-VL-8B 29.47%,
  Qwen3-VL-32B 38.37%, VideoAgent-8B 30.01%; approaching GPT-4.1 (45.19%).
  Ablation: multi-agent architecture alone +7.7 pts, RL +4.8 more.
- Read this paper before Wednesday if you read only one: it bridges branches
  2 and 3 on our exact problem shape, with an 8B open controller.

**Branch verdict**: most mature branch; the frame-efficiency and
question-conditioned-search evidence is strong, and AgentCVR ⚠ suggests the
8B-controller cliff is climbable (multi-agent decomposition + RL on the
controller). A zero-training delta-sampler is the natural entry point to this
branch.

---

## Branch 3 — RL over a fixed frame set

### Video-R1 (arXiv 2503.21776, NeurIPS 2025) — verified
- First systematic R1-style rule-based GRPO for video; **T-GRPO** adds a
  contrastive temporal reward (r_t = 0.3 when ordered-frame rollouts beat
  shuffled-frame rollouts) forcing genuine use of temporal order.
- Video-R1-7B: 37.1% VSI-Bench (> GPT-4o 34.0%), 64.8% MVBench, 73.2%
  TempCompass. Built on **Qwen2.5-VL-7B**, max 16 frames in RL training,
  open code + checkpoint (we already have Video-R1 in the repo).
- Multi-video transfer is *inference, not demonstration* — but the recipe
  consumes exactly the fixed sampled frame set our duration-weighted pipeline
  produces, and the shuffle-contrast trick adapts naturally to the camera
  axis: **shuffle camera order / camera-frame assignment instead of frame
  order to reward genuine cross-camera reasoning.**

### ViaRL (arXiv 2505.15447) — verified
- RL-trained **frame selector**: Qwen2.5-VL-3B selector trained with
  REINFORCE++ using the downstream 7B answer model's accuracy as reward — QA
  pairs only, no frame-level annotations.
- 8 selected frames from 128 candidates: 73.5 on MLVU Needle QA vs 58.6 for
  uniform sampling at the same 8-frame budget (+14.9), matching dense-frame
  systems at 96–128 frames. Cleanest published head-to-head of learned
  question-conditioned selection vs fixed sampling, in our model family.
- Direct upgrade path from the delta-sampler experiment: heuristic delta
  selection first, RL selector if the signal is real.

### EgoExo-Con / View-GRPO (arXiv 2510.26113, NeurIPS 2025) — verified
- Diagnostic: Video-LLMs give inconsistent answers across views of the same
  event. Open-model consistency is barely over half of single-view accuracy;
  Qwen2.5-VL-7B: 33.0% verification / 6.9% grounding consistency (human:
  89.4/67.3). **Single-view accuracy does not predict cross-view consistency.**
- **View-GRPO** (GRPO + format/accuracy/reasoning rewards, GPT-5-distilled
  view-specific reasoning chains for SFT) is the only verified method that
  improves it: Qwen2.5-VL-7B 33.0→45.1 verification, 6.9→18.7 grounding.
  Caveats: authors' own benchmark; needs GPT-5 access for distillation.

### ⚠ Also found (extracted, not adversarially verified)
- **FrameThinker** (2509.24304): Qwen2.5-VL-7B as multi-turn agent, SFT then
  GRPO, actions = choose frame ranges / timestamp lookup / answer.
- **K-frames** (2510.13891): Qwen2.5-VL-3B scene-driven keyframe selector,
  final stage GRPO.
- **Query-adaptive frame selector** (CVPR 2026, Qin et al.): frozen-CLIP +
  0.4B transformer head, distilled then GRPO-refined — a *cheap plug-in*
  selector that never touches the answer VLM.

**Branch verdict**: most directly compatible with our pipeline and our
finding that sampling policy is the live variable. The camera-shuffle T-GRPO
variant is, as far as this review found, unclaimed territory.

---

## Branch 4 — outside the three branches

No verified training-free token-merging or neuro-symbolic *multi-camera*
method surfaced; the branch-4 picture is incomplete rather than empty
(retrieval limitation, stated in the run's caveats). What did surface:

- **HoliTom** (2505.21334, NeurIPS 2025) ⚠: training-free holistic token
  merging (outer-LLM temporal segmentation + merging, inner-LLM similarity
  merging); >90% visual-token reduction at 99.1% retained performance on a 7B
  video LLM. Drop-in candidate for cramming more cameras/frames into our
  fixed context — the redundancy it exploits is worst exactly when
  overlapping views are concatenated.
- **RSCD / MVH-Bench** (2603.23934) ⚠: multi-view hallucination benchmark
  (models confuse content *across* views — our entity-matching failure mode,
  quantified) + Reference Shift Contrastive Decoding, a training-free
  inference-time fix claiming up to +21/+35 pts on multi-view QA at 7-8B
  scale; beats generic single-image contrastive-decoding fixes. Also
  documents a strong yes-bias on multi-view binary questions (we've seen
  premise-acceptance in our traces).
- Verified partial exemplars reinterpreted from branches 1–2: SQL/CLIP object
  memory (VideoAgent 2403.11481) and frozen-BEV feature injection
  (BEV-InMLLM) as explicit scene representations.

---

## Cross-cutting evidence worth citing Wednesday

- **View selection is model-dependent and bad in our older backbone** ⚠
  (2606.09644, six-camera NuScenes diagnostic): Qwen2.5-VL-7B 12.62%
  view-selection accuracy vs Qwen3-VL-8B 61.64%, InternVL3 61.48%, Claude
  82.62%. Also: 192/732 trials answered correctly while citing the wrong
  camera — answer-only scoring overestimates grounded multi-camera reasoning.
- **Adjacent benchmarks** ⚠: CrossVid (2511.12263: 9,015 QA, best model
  Gemini-2.5-Pro 50.4% vs human 89.2%; InternVL3-8B *leads* multi-view
  spatial at 40.7%; frame budget 32→256 gains +5.7 on a 72B model — and its
  protocol is even-split, so duration-weighted is untested there);
  EgoExoBench (2507.18342: InternVL3-8B ~31.3%, humans 90.1%; **CoT can hurt
  cross-view QA by up to ~20 pts on some subtasks** — a caution for our
  thinking-trace setup); the published CVBench paper itself is arXiv
  2508.19542.
- **Refuted claims — do not reuse**: OmniDrive-stitches-views (0–3);
  Weaver-trains-from-answer-only-rewards (0–3; Weaver 2602.05829 exists as a
  trained agentic video system, but its supervision story is unestablished).

## How this maps to our decision

1. Our own data already argue against naive "more pixels" scaling (frame
   sweep flat-to-falling; stitch loses at equal tokens) — consistent with the
   agentic/RL literature's claim that *which* frames beats *how many*.
2. The cheapest experiments spanning the branches, in cost order:
   delta sampler (classical CV tool, zero training — bridges to agentic) →
   ViaRL-style RL selector (3B selector, QA-only supervision) →
   camera-shuffle T-GRPO on Video-R1's open recipe (novel, publishable) →
   VideoAgent/AgentCVR-style tool loop (controller risk at 8B, but AgentCVR
   shows a path).
3. Pre-training is the least actionable branch for CVBench-style uncalibrated
   input on our compute; its transferable idea (learned cross-view query
   module on a frozen backbone) is a middle-ground worth naming but not
   leading with.

## Open questions the run flagged

1. Any published method doing agentic/RL natively across *synchronized*
   cameras beyond View-GRPO's ego-exo pairs and annotation-heavy driving?
   (CVBench-style uncalibrated multi-camera QA looks genuinely open.)
2. Can an 8B open VLM controller survive a VideoAgent/DVD loop (constrained
   JSON decoding, distilled traces, AgentCVR-style multi-agent + RL)?
3. Does camera-shuffle T-GRPO beat duration-weighted sampling on CVBench?
4. Does a per-camera RL selector under a shared budget concentrate its gains
   in needle-style categories (as ViaRL did on MLVU)?
5. What does branch 4 actually contain that this retrieval missed?
