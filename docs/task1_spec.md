# Descriptions

**Summary:**

Consider a security scenario requiring a system to answer the question “what did the suspect do in between exiting the building and leaving the office room?” This requires models to track the person's trajectory across time, often monitored by spatially disjointed cameras. 

Our key observation driving is that contemporary multi-modal architectures lack the concurrent spatial understanding required to meticulously reason across disparate camera feeds, and temporal reasoning capabilities to accurately articulate sequences of events over extended time horizons across varying viewpoints. Furthermore, processing all camera streams jointly within a single model's context window creates an uninterpretable bottleneck that struggles with complex multi-view correlation. 

To overcome this, our key insight is to structure the information pipeline utilizing a distributed, neuro-symbolic method. Instead of a monolithic model, we assign localized deep learning agents to individual camera streams to autonomously organize query-specific contexts, extracting relevant features into structured, interpretable spatial scene graphs. These localized graphs are subsequently coalesced across the network into a merged coalition scene graph, serving as a comprehensive global representation of the queried event. By aggregating information in this format, inspired by distributed systems and multi-agent reinforcement learning, the system reliably organizes all necessary spatial and temporal data to resolve complex searches. Ultimately, this project aims to develop a scalable search algorithm demonstrating that query accuracy degrades significantly less as the number of cameras increases, exhibiting graceful scaling compared to standard monolithic VLM baselines. 

**Interns Needed:** 1 (Full Time)  
**Publication Role:** Interns can support implementation and experiments, while lead authorship may be shared depending on contribution level.

**List of Tasks:** 

1) Algorithm Construction and Iteration for Improving the Algorithm  
2) Setting up multi-camera datasets  
3) Setting multi-camera agents  
4) Benchmarking foundation models

# Task 1: Evaluations

**Prior Work in Vision-Language Models:**

Vision-language models inherently possess limited context windows, rendering the naive parsing of continuous multi-camera streams into the context window inadequate for complex question answering.   
Furthermore, these models are prone to hallucination. Existing literature highlights three primary failure modes in this domain: the inability to count objects correctly due to neuro-symbolic limitations, the confounding of visual details across objects known as the binding problem, and a phenomenon of blind faith where models exclusively default to language priors when confronted with conflicting visual evidence \[1, 2, 3, 4\]. When adapted to process video data, current multi-modal language models continue to demonstrate significant gaps in visual and temporal understanding, particularly concerning activity and motion \[5\]. Our own preliminary investigations, including Neus-QA and NSVS, explicitly demonstrate this temporal reasoning deficit when models are tasked with questions requiring the composition of multiple events in a prescribed sequence for single-camera understanding. 

**Objective and Hypothesis:**

Despite the introduction of multi-camera datasets, there is a critical absence of targeted analysis regarding the specific failure modes of vision-language models when reasoning across multiple distinct camera streams. Because multi-camera videos are highly data-intensive, simply stitching the footage together will rapidly exhaust the model's context window and natively yield poor responses. Consequently, the mechanism by which multi-camera inputs are presented to the model called "harness” is critical. This presentation can be centralized, where multiple camera inputs are visually organized into a coherent stream for the model to interpret, or decentralized, where the model independently processes single-camera perspectives and centrally aggregates the resulting textual information for downstream reasoning. 

Our primary objective is to systematically uncover the common failure modes associated with these distinct harnesses. Insight into multi-camera understanding failures will form the foundational basis for designing harnesses for organizing complex multi-camera video streams.

We hypothesize that neither harness will achieve universal superiority across all question typologies. Specifically, we anticipate that centralized harnesses will exhibit superior performance on tasks requiring complex spatio-temporal reasoning across disjoint views, whereas decentralized harnesses will excel in foundational perception tasks, such as object counting per perspective. 

**Experiment Plan**  
To test this hypothesis, we propose the evaluation of two distinct multi-camera harnesses. 

1. The first approach is a centralized method that temporally aligns the video streams and spatially stitches the corresponding images across multiple views to provide a unified input for question answering.  
2. The second approach is a decentralized method wherein the model analyzes each single-camera perspective independently, generates textual summaries pertinent to the given query for each stream, and subsequently aggregates these distinct informational sources in a centralized text-based module to formulate the final answer. 

Metrics and Datasets:

The evaluation will be conducted utilizing the CVBench and Cross View datasets. The comparative performance of the proposed harnesses will be measured against several core metrics. These metrics include general video question-answering accuracy and latency segmented across different question categories and number of cameras.

Plots:

* **Table 1: General Video QA Accuracy:** Displays overall accuracy and standard deviation (calculated across four independent passes) for all configurations of the two selected models operating across both proposed harnesses \[4 methods\].   
  * Column \- Methods, Harness, and accuracy  
* **Plot 1: QA Accuracy per Question Category (Bar Chart):** Illustrates accuracy on the vertical axis (using standard deviation for error bars) against specific question types on the horizontal axis, with grouped bars representing each model and harness combination.  
  * X axis \- Methods; Y axis \- accuracy  
* **Plot 2: Latency Analysis:** Provides a detailed breakdown of computational latency corresponding to each individual question.  
  * X axis \- Methods; Y axis \- inference time (ms)  
* **Plot 3: Accuracy vs. Camera Count (Line Plot):** Maps general question-answering accuracy on the vertical axis against the varying number of integrated cameras on the horizontal axis.  
  * X axis \- Number of Cameras; Y axis \- accuracy  
* **Plot 4: Accuracy per Question Type vs. Camera Count (Line Plot):** Details specific visual question-answering accuracy for distinct question categories as the number of cameras scales, providing insight into the resilience of each harness.  
  * X axis \- Number of Cameras; Y axis \- accuracy

**References**

**\[1\]**   
[**https://stillbreeze.github.io/Why-Vision-Language-Models-Continue-to-Suffer-from-the-Blind-Parrot-Syndrome/**](https://stillbreeze.github.io/Why-Vision-Language-Models-Continue-to-Suffer-from-the-Blind-Parrot-Syndrome/)  
**\[2\] [https://arxiv.org/pdf/2503.02199](https://arxiv.org/pdf/2503.02199)**  
**\[3\] [https://arxiv.org/pdf/2411.00238](https://arxiv.org/pdf/2411.00238)**  
**\[4\] [https://arxiv.org/pdf/2212.07796](https://arxiv.org/pdf/2212.07796)**  
**\[5\] https://proceedings.iclr.cc/paper\_files/paper/2025/hash/16ba99f25a235f1100a4014d71d34ad8-Abstract-Conference.html**

# Logs

## Harness (`bench/`) — implementation status (2026-06-24)

Task-1 evaluation harness now matches this spec. Two harnesses × two models × four passes:

- **Centralized** (`bench/methods/centralized.py` + `bench/methods/stitch.py`): temporally
  aligns the ≤4 clips (proportional frame sampling) and spatially **stitches** the
  synchronized frames into labeled grid montages (≤2×2), fed as one unified visual input.
- **Decentralized** (`bench/methods/per_stream.py`): per-camera perception pass → text-only
  aggregator.
- **Models**: `qwen3vl` = Qwen3-VL-8B-Thinking (env `cvbench`); `internvl3` = InternVL3-8B
  (env `internvl`, since cvbench's transformers breaks InternVL3's remote code).
- **4-pass protocol**: temperature 0.7, seeds 1–4, frames held fixed; Table 1 = accuracy
  mean ± std over the 4 passes (`bench/metrics.py:summarize_passes`).
- **Deliverables**: `bench/plots.py` → Table 1 + Plot 1 (per category) / 2 (latency) /
  3 (vs camera count, X = `orig_num_cameras`) / 4 (category × cameras).

### Run log

| date | run | subset | models | methods | passes | jobs | notes |
|---|---|---|---|---|---|---|---|
| 2026-06-24 | smoke | combined (3 q) | qwen3vl, internvl3 | centralized, per_stream | 4 | 57859, 57860 | 24+24 rows, 0 errors, real cross-pass variance; plumbing validated |
| 2026-06-24 | dev | combined (100 q) | qwen3vl, internvl3 | centralized, per_stream | 4 | 57865 (cvbench ×10 shards), 57866 (internvl ×4) | primary deliverable; Table 1 + Plots 1–4 → `bench/results/figs_dev_combined/` |

Notes:
- Qwen3-VL-Thinking is slow (~100–250 s/call, often hits the 8192-token cap) → sweeps are
  Slurm-array sharded; partition `gpul40q` has unlimited walltime.
- Full `meva1033` (1,033 q, cameras 2–16) scale sweep is gated on the dev Table 1 looking sane.
- Reproduce: see `bench/bench_spec.md` Commands.
