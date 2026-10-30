# `analysis/`

Flat by convention (see `CLAUDE.md`): scripts, curated inputs, and gitignored outputs
share this directory with no subdirectories. This file says which is which. Every
script runs from the repo root as `python3 analysis/<name>.py`.

## 1. Scripts by kind

43 files total (`ls analysis/*.py analysis/*.sh analysis/*.sbatch analysis/demo_ui.html`). "Writes" is the
generator's own default output path (or `--out`/`OUT` constant); many also print a
report to stdout regardless.

### Converters

| Script | Purpose | Writes |
|---|---|---|
| `convert_allangles.py` | Converts All-Angles-Bench multi-view still-image QA into the harness record schema | `allangles_qa.json`, `allangles_dev_subset.json` |
| `convert_crossview.py` | Converts UT Austin CrossView (Multi-Camera VQA) annotations into the harness record schema | `crossview_qa.json` (untracked), `crossview_subset.json`, `crossview_subset_fetch.json`, `crossview_subset_videos.txt` |
| `convert_cvbench.py` | Converts CVBench (cross-video QA, HF `Dongyh35/CVBench`, pinned revision) into the harness record schema; its O1 output is byte-identical to the file the archived full-1000 legs ran on (git blob `beae9447`), so new legs join those by id; `--order O2` writes the reversed-option twin, which is not a pure position control on the 48 questions whose options point at other positions (see its docstring); a control that pins those options goes under a new subset name (`--out`): regenerated in place, the O2 file keeps its name, so anything keyed on the name would still accept its existing rows and score them against a different key (`cvbench_text_answerability.py` refuses rows whose stored `correct` disagrees with the key) | `cvbench_full_runnable_subset.json`, `cvbench_full_runnable_subset_o2.json` |
| `convert_mvueval.py` | Converts MVU-Eval (multi-video QA, NeurIPS 2025 D&B) into the harness record schema | `mvueval_qa.json`, `mvueval_dev_subset.json`, `mvueval_dev_videos.txt`, `mvueval_dev_fetch.json` |

### Fetchers

| Script | Purpose | Writes |
|---|---|---|
| `fetch_agibot_videos.py` | Incrementally fetches AgiBot World videos for the CrossView benchmark | videos into the release root; `.agibot_tree_cache.json` |
| `fetch_egoexo_videos.py` | Fetches the Ego-Exo4D videos a CrossView subset references into the release root | videos into the release root (via the external `egoexo` CLI, `--run`) |
| `fetch_meva_videos.py` | Downloads the MEVA videos a CrossView subset references into the release root | videos into the release root |

### Exporters

| Script | Purpose | Writes |
|---|---|---|
| `export_question_records.py` | One analysis-ready record per (dataset, backend, method, question, pass) | `records/` (`registry.json`, per-leg record JSONL) |
| `export_shared_results.py` | Packages the valid result legs for the shared multicam-harness repo | an external `--out` root: `multicam_results/`, `data/subsets/`, `registry.json`, `summary.csv`, `README.md` |

### Figure / deck generators

| Script | Purpose | Writes |
|---|---|---|
| `make_cvbench_text_figs.py` | The CVBench text-only figures: no-video accuracy vs baselines, per-task accuracy, text-answerable shares against chance and a shuffled-answers null, passes-right histogram, with-video accuracy by text label, thinking-minus-no-thinking with 95% intervals, answer habits (letters and Yes/No), the full-1000 history and stitch sweep, trace length, O1-vs-O2 consistency; reads two `cvbench_text_answerability.py --blind-o2` JSONs (`--bm` thinking, `--nt` no-thinking control; every Qwen number but figure 11's trace lengths comes from them, and each needs 4 usable passes on every `--subset` question in both orders), the row files the `--bm` JSON's provenance lists (those trace lengths; each is checked against its sha256, a `--bm` that lists none is refused, and `--results` is only where a file listed by its name alone is looked for), the O1 subset (`--subset`, for the longest-option chance) and the rows of the earlier with-video InternVL3-8B legs, archived outside git (`--archive`, required); every input is read and checked before `--out` is created; value labels are rounded half-up from counts where the analysis JSON has them, else from its two-decimal values | `figs_deck/fig_cvbench_*.png` and `fig_cvbench_data.json` (the plotted numbers and the counts behind each value label), or `--out` |
| `make_deck_html.py` | Assembles the results deck HTML from `figs_deck/*.png`, base64-embedded | a required positional `<out.html>` path (no default under `analysis/`) |
| `make_deck_pptx.py` | Assembles the results deck as PowerPoint, "Part 2" of the July-28 slides | `deck_part2.pptx` |
| `make_frame_sweep_fig.py` | Accuracy vs frame budget, small multiples across the three datasets | `figs_deck/fig_frame_sweep*.png` |
| `make_headline_figs.py` | Two slide-headline figures assembled from already-dumped series JSONs | `bench/results/figs_task1_overview/*.png` (not under `analysis/`) |
| `make_ladder_figs.py` | The segment-selection ladder as numbers and as the Task-1 figures | `figs_deck/fig_ladder_*.png`, `fig_meva_defect.png`; optional `--json` (e.g. `records/ladder_stats.json`) |
| `make_quad_figs.py` | The sponsor quad chart: pooled and per-task accuracy of every arm and of the matched-protocol no-video leg, the per-question win/tie/loss against native uniform, and the 0-4 passes-correct histogram; cross-checks every cell against `records/ladder_stats.json` and the registry's blind accuracies and refuses to finish on a mismatch. The four quad-chart figures are sized to stay legible in one quadrant of a slide; the selector panel plots both of that file's chance nulls and is skipped with a note when `records/selection_coverage.json` is absent | `records/quad_stats.json`, `figs_deck/fig_quad_{ladder,pertask,delta,selector}.png` |
| `make_repq_doc.py` | Builds the representative-questions doc the mentor requested (2026-08-01) | `repq_doc.html`, `repq_doc_manifest.json` |
| `make_repq_pptx.py` | Renders the representative-questions doc as an importable PowerPoint deck | `repq_deck.pptx` |
| `make_slide_figs.py` | Renders the July-30 results deck figures (the InternVL3-8B slide remake) | `figs_deck/*.png` |
| `render_demo.py` | Per-question demo figures for the four-camera MEVA demo: the segment timeline with the kept segments, selected frames and annotated event windows per camera, the per-arm answer panel with the trace excerpt, and a demo-set summary beside the meva1033 ladder. `--selection-method` picks whose selection is drawn — `segment_select_siglip` (default) or `segment_select_viclip_opt`; the scorer name and the query mode on the header and the colorbar are read from the row's `frame_alloc`, and the summary ladder grows the ViCLIP-opt rungs when a ViCLIP arm is rendered | `figs_demo/` for the SigLIP set, `figs_demo_viclip/` (`--out`) for the ViCLIP set (`q<id>_selection.png`, `q<id>_answer.png`, `summary.png`, `manifest.json`) |
| `make_demo_walls.py` | One 2x2 camera-wall MP4 per demo question from `figs_demo/manifest.json`: the four streams on a shared clip clock over the annotated event window, each tile carrying its evidence/padding badge, SigLIP segment strip, kept segments, event bars and playhead, dimmed whenever the selector did not send that moment, closing on a per-arm answer card; `walls_all.mp4` is rebuilt from every wall present in the output directory, so a `--ids` re-render never truncates the reel (`walls_manifest.json` lists the ids it carries) | `figs_demo/walls/` (`q<id>_wall.mp4`, `q<id>_wall_snapshot.png`, `walls_all.mp4`, `walls_manifest.json`) |
| `demo_live_tail.py` | Tails a result JSONL and prints one line per answer as it lands (id, arm, prediction vs gold, latency, tokens, kept segments per camera), for the recorded demo's terminal segment; `--replay` re-prints an existing file | stdout |
| `demo_ui.html` | Screen-recording replay page for the four-camera demo (one self-contained file, no CDN). When `figs_case/` is present it opens on the case study that heads the rail: question 954 of the full MEVA pool, each camera alone against all four cameras with selection, in five steps (the case wall clip with each camera's answers, the 8-frame figure, the four-camera wall, the 96-frame figure, reset); below it, How it works puts the pipeline figure on stage. Then the five demo questions: five numbered buttons (or keys 1-5; the left and right arrows walk the rail) reveal the camera-wall clip, the selection figure, an answer card built from the manifest, and one reasoning trace; the SigLIP/ViCLIP switch swaps both the asset root and the reasoning rows, and falls back to the SigLIP trace with a note when the ViCLIP rows are absent. Without `figs_case/` it opens on the first question | writes nothing - reads `figs_demo/`, `figs_demo_viclip/`, `figs_case/` (optional) and `bench/results/bench_demo_*_demo_reason.jsonl`/`_demo_global.jsonl`/`_demo_viclip_reason.jsonl`/`_demo_viclip_global_reason.jsonl`; serve the repo root and open `analysis/demo_ui.html` |
| `restyle_task1_figs.py` | Re-renders the Task-1 figures from the JSON series `bench/plots.py` dumps | `bench/results/figs_task1_*/*_v2.png` (not under `analysis/`) |

### Stats / splits

| Script | Purpose | Writes |
|---|---|---|
| `allangles_consistency.py` | All-Angles-Bench paired-question consistency report (the paper's CC/WW/IC split) | stdout only |
| `counting_failures.py` | Counting-failure analysis: dedup failure vs perception miss vs guess | optional `--out-md`/`--out-json` (no default; stdout otherwise) |
| `crossview_question_types.py` | Question-type analysis of the UT Austin CrossView annotations | `crossview_question_types.md` |
| `cvbench_text_answerability.py` | Is a question answerable from text alone? Scores a blind leg per question (text-answerable = right in at least 3 of its 4 passes; a question with fewer than 4 usable rows refuses the leg unless `--allow-partial`) against chance, per-(task, answer space) modal-gold floors (in-sample and leave-one-out), the longest-option rule and the leg's own answer-bias null (within-stratum permutation of pass-sets); sets the text-answerable count beside its expectation at chance and under that null; with `--blind-o2` adds the reversed-option twin and a both-orders label with two nulls (orders shuffled independently, and paired so habits that hold across orders stay in the null), overall, per task and by format; reports unclosed traces and batched GPU time; crosses the labels with optional `--sighted` legs and `--slice` id lists. Each null is `--permutations` draws (default 100,000); p is stored to 5 decimals, so from 200,000 draws on its floor reads 0.0 (`draws_ge_observed_*` is the exact count). Refuses a leg whose rows span more than one TAG, decode stamp or backend, whose `dataset` stamp is not the subset they are scored against, or whose stored `correct` disagrees with their prediction against that subset's gold, compared as the blind arm compares them (a subset regenerated under its old name with another key); a `--json` that names a directory or ends in a separator, an existing `--json` file that cannot be written, a `--seed` below 0 and a `--slice` file that is missing or not JSON are refused before anything is computed. The JSON opens with a provenance block (argv, inputs with sha256, seed, draws, the script's git blob) whose paths, argv's included, are relative to the repo inside the checkout and a file name alone outside it (the sha256 still identifies the file); each order's `files` lists the row files as globbed, so pass repo-relative globs | stdout; optional `--json` (e.g. `records/cvbench_text_answerability_<tag>.json`) |
| `evidence_class_accuracy.py` | Per-evidence-class accuracy for every valid MEVA leg, at zero new GPU hours | `docs/evidence_class_splits_<date>.md` (gitignored) |
| `letter_floors.py` | Answer-letter bias for any CrossView-style pool: gold-letter skew, chance, in-sample and leave-one-out task-conditioned modal-letter floors, option-text/fixed-distractor and identity-ordering diagnostics; `--group-by` regroups the LOO hits, `--converter-check` compares each harness record to its release item | stdout; optional `--json` (e.g. `records/letter_floors_<pool>.json`) |
| `mvueval_slide_stats.py` | Canonical statistics for the July-30 results deck, into one self-describing JSON | `slide_stats.json` |
| `split_ladder_by_query.py` | Splits the segment-selection ladder by whether the scorer had a content query | stdout; optional `--json` (e.g. `records/split_ladder.json`) |

### Labeling and bank

| Script | Purpose | Writes |
|---|---|---|
| `label_evidence_class.py` | Stamps every MEVA benchmark question with its evidence-locality class | `records/evidence_labels.json` |
| `make_question_bank.py` | Builds the DOD-relevant question bank: real MEVA questions per evidence class | `dod_question_bank.json` |

### Bounds

| Script | Purpose | Writes |
|---|---|---|
| `build_singleview_subset.py` | Builds the single-view pool: MVU-Eval questions whose text/options don't name a view | `mvueval_noview_subset.json` |
| `single_view_oracle.py` | Upper bound on one pool and one model: the optimal-view oracle | stdout; optional `--json`/`--md` (no default) |

### Selection diagnostics / calibration

| Script | Purpose | Writes |
|---|---|---|
| `clip_scorer_gate.py` | Offline scorer gate: is CLIP/SigLIP similarity good enough to drive clip selection? | stdout; optional `--out` JSON dump (no default) |
| `clip_scorer_gate.sbatch` | Sbatch wrapper for the offline per-option similarity gate (meeting item 5b) | `records/gate_peropt.json` (`$OUT` default); `logs/%j.gate.{out,err}` |
| `clip_selection_diagnostic.py` | Selection-accuracy diagnostic for the clip-selection methods (no GPU) | stdout; optional `--json` (e.g. `sampler_diag.json`) |
| `calibrate_union_tau.py` | Calibrates the option-union similarity threshold from existing gate outputs | stdout only |
| `selection_event_coverage.py` | The segment selector's own accuracy against the CrossView release annotations, no GPU: per arm, budget and question type, how often every annotated event landed in a kept segment (MEVA on the camera the release annotated it on, Ego-Exo4D on any camera of the shared take clock), the same statistic under two keep-count-matched nulls (one drawn independently per camera, one that shifts the row's own picks together and so keeps their cross-camera overlap), a per-camera-event coverage column with its exact chance, and how often a frame the model actually saw fell within 3 s of the event; counts the ViCLIP arm's keep-everything rows and re-reports those cells without them; MVU-Eval carries no event annotations and is skipped | stdout; `records/selection_coverage.json` (`--json`) |

### Rescoring

| Script | Purpose | Writes |
|---|---|---|
| `rescore_answers.py` | Re-derives prediction/correct/abstained from the stored `response_text` (on rows stamped `parsed_from: after_think`, from the reply after the last `</think>`, as the harness parsed them); its per-leg table never pools two run TAGs or decode stamps | `bench/results/rescored/<basename>` (+ `_summary.json`); not under `analysis/` |

### Env

| Script | Purpose | Writes |
|---|---|---|
| `setup_env.sh` | One-time env setup for the CVBench thinking-eval: clones `vlm` into the `cvbench` conda env | no file; creates the `cvbench` conda env |

## 2. Tracked non-script inputs

25 files (`git ls-files analysis | grep -E "\.(json|txt)$"`). Counts measured
2026-10-30:

- **result files keyed on it**: `ls bench/results/ | grep -c "^bench_<stem>_"`,
  `stem` = the filename without its extension.
- **registry legs**: rows in `analysis/records/registry.json`'s `legs` list whose
  `subset` field equals the bare filename.

| File | Role | Result files | Registry legs | Status |
|---|---|---:|---:|---|
| `allangles_dev_subset.json` | eval subset | 0 | 0 | generator default (`convert_allangles.py --out-subset`); README example; superseded by `allangles_egohumans_qa.json` for live runs |
| `allangles_egohumans_qa.json` | pre-subset pool | 19 | 7 | live; tracked output of `convert_allangles.py --require-local` |
| `allangles_qa.json` | pre-subset pool | 24 | 8 | live; generator default (`convert_allangles.py --out-qa`) |
| `crossview_combined_subset.json` | eval subset | 7 | 0 | live; README/`bench/run_bench.py` example |
| `crossview_egoexo500.json` | eval subset | 114 | 22 | live |
| `crossview_egoexo_subset.json` | eval subset | 0 | 0 | generator default (`fetch_egoexo_videos.py --subset`); superseded by `crossview_egoexo500.json` for live runs |
| `crossview_meva1033_subset.json` | eval subset | 328 | 28 | live; default subset for most MEVA analysis scripts |
| `crossview_meva4cam_subset.json` | eval subset | 0 | 0 | sole consumer `bench/legacy/qual_make_figs.py` (retired, no other referrers) |
| `crossview_meva_cap13.json` | eval subset | 166 | 27 | live |
| `crossview_nuscenes12_subset.json` | eval subset | 0 | 0 | live; 12-record stratified preflight pool (3 per task type) drawn from `crossview_nuscenes1497_subset.json`; preflight results are staged outside `bench/results/` and are never registered |
| `crossview_nuscenes1497_subset.json` | eval subset | 16 | 1 | live; 1497 nuScenes MCQ records, four task types, six cameras each; compiled 2026-09-09 from the release annotations by a gitignored shim (no tracked generator); blind-only pool — no nuScenes media is on disk |
| `crossview_subset.json` | eval subset | 0 | 0 | generator default (`convert_crossview.py --out-subset`, `fetch_meva_videos.py --subset`); superseded by `crossview_meva1033_subset.json` / `crossview_meva_cap13.json` for live runs |
| `crossview_subset_fetch.json` | fetch manifest | 0 | 0 | generator default (`convert_crossview.py --out-fetch`); consumed by `hosting/fetch_videos.py` |
| `crossview_subset_videos.txt` | video list | 0 | 0 | generator default (`convert_crossview.py --out-videos`); consumed by `bench/gen_clip_summaries.py` |
| `cvbench_full_runnable_subset.json` | eval subset | 40 | 0 | live; the full 1000-question CVBench pool (O1), tracked output of `convert_cvbench.py` and byte-identical to the file the archived full-1000 legs ran on (git blob `beae9447f7fb91d9529e6064a8a07f39da106d54`; those legs are keyed on this stem but are not in `bench/results/`); the recipe's 40 includes the 20 files of its O2 twin, whose stem extends this one; no CVBench clips are on disk, so it runs blind-only until `CVBench.zip` is extracted under a `VIDEO_ROOT` |
| `cvbench_full_runnable_subset_o2.json` | eval subset | 20 | 0 | live; the O2 order of the two-order text-only protocol (`convert_cvbench.py --order O2`): the same 1000 questions, joined to O1 by id, with 999 option lists reversed — the gold letter remapped on the 863 lettered ones, the gold word kept on the 136 Yes/No ones — and `cvb-996`, whose four options are packed into one string, kept as is; on 48 questions an option points at other positions (`cvb-89`'s "Both A and C." and 47 All/None of the above options, moved from D to A), so there O2 is not a pure position control |
| `cvbench_preflight30_subset.json` | eval subset | 0 | 0 | live; 30-record stratified preflight pool drawn from `cvbench_full_runnable_subset.json`, with no tracked generator: task types sorted, one shared `random.Random(0)`, `rng.sample(records_of_type, 2)` per type (records in file order), re-sorted by CVBench id as a number, written with `json.dump(records, fh, ensure_ascii=False)`; preflight results are staged outside `bench/results/` and are never registered |
| `demo_meva4cam_subset.json` | eval subset | 18 | 0 | live; 5-record four-camera MEVA demo subset (ids 860, 749, 251, 1, 130) behind `render_demo.py`; result stem `bench_demo_meva4cam_subset_*`; not registered; the demo legs ran as one-off jobs |
| `dod_question_bank.json` | curated bank | 0 | 0 | tracked output of `make_question_bank.py` |
| `mvueval_dev_fetch.json` | fetch manifest | 0 | 0 | generator default (`convert_mvueval.py --out-fetch`) |
| `mvueval_dev_subset.json` | eval subset | 57 | 0 | live; generator default (`convert_mvueval.py --out-subset`); README example |
| `mvueval_dev_videos.txt` | video list | 0 | 0 | generator default (`convert_mvueval.py --out-videos`) |
| `mvueval_noview_subset.json` | eval subset | 20 | 13 | live; tracked output of `build_singleview_subset.py` |
| `mvueval_qa.json` | pre-subset pool | 442 | 45 | live; generator default (`convert_mvueval.py --out-qa`); README example |
| `mvueval_smokefix.json` | eval subset | 4 | 0 | live (two smoke legs, 4 result files); hand-built, no generator, no registry entry |

Regenerate the counts:

```bash
for f in analysis/*.json analysis/*.txt; do
  [ -f "$f" ] || continue
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 || continue
  stem=$(basename "$f"); stem="${stem%.json}"; stem="${stem%.txt}"
  echo "$stem: $(ls bench/results/ | grep -c "^bench_${stem}_")"
done
python3 -c "
import json, collections
reg = json.load(open('analysis/records/registry.json'))
c = collections.Counter(l['subset'] for l in reg['legs'])
for k, v in sorted(c.items()): print(k, v)
"
```

`registry.json` lists only registered legs (8 subset keys appear there at all); the
`bench/results/` tree is the census of what was ever run, including smoke tests and
superseded pools the registry never picked up — the test for "was this subset ever
run" is always the results tree, never the registry. A subset's **filename** is a
result-file key (`run_bench.sbatch` builds `bench_<basename>_<env><tag>`), so never
rename one — see `CLAUDE.md`.

## 3. Sibling imports

Cross-file `import`s among `analysis/*.py` (one script importing a name from
another, or `runpy`-executing one for its globals). Renaming any of these files
needs the importer fixed too:

- `fetch_agibot_videos.py` -> `convert_crossview` (`MAX_SLOTS`)
- `fetch_egoexo_videos.py` -> `convert_crossview` (`MAX_SLOTS`)
- `fetch_meva_videos.py` -> `convert_crossview` (`MAX_SLOTS`)
- `clip_scorer_gate.py` -> `clip_selection_diagnostic` (`VIDEO_RE`, `gold_option_video`)
- `make_deck_pptx.py` -> `make_deck_html` (`runpy.run_path`, lifts `SLIDES`, `S`, `TASK_ORDER`, `PRETTY`)
- `convert_crossview.py` -> `crossview_question_types` (`normalize`)
- `letter_floors.py` -> `crossview_question_types` (`normalize`)
- `letter_floors.py` -> `evidence_class_accuracy` (`loo_floor`)
- `export_shared_results.py` -> `export_question_records` (`RES`, `leg_tag`)
- `single_view_oracle.py` -> `evidence_class_accuracy` (`class_maps`, `loo_floor`)
- `make_frame_sweep_fig.py` -> `clip_scorer_gate` (`modal_letter_floor`)
- `make_ladder_figs.py` -> `split_ladder_by_query` (`DATASETS`, `BUDGETS`, `BASELINE_METHOD`, `RES`)
- `selection_event_coverage.py` -> `split_ladder_by_query` (`DATASETS`, `BUDGETS`, `RES`)
- `make_quad_figs.py` -> `make_ladder_figs` (`load_rows`, `acc_stats`, `per_id`, `paired`, `style`, the arm palette) and `split_ladder_by_query` (`DATASETS`, `BUDGETS`, `BASELINE_METHOD`)
- `make_question_bank.py` -> `label_evidence_class` (imported as `lec`)
- `make_repq_pptx.py` -> `make_repq_doc` (imported as `R`)
- `make_repq_doc.py` -> `build_singleview_subset` (`NAMES_VIDEO`)
- `make_repq_doc.py` -> `clip_selection_diagnostic` (`VIDEO_RE`, `gold_option_video`)
- `make_repq_doc.py` -> `mvueval_slide_stats` (`NUSC`, `load_rows`)

## 4. Gitignored outputs

Generated on disk here, untracked, regenerated by the named script:

- `records/` — `export_question_records.py` (also written into piecemeal by
  `label_evidence_class.py`, `single_view_oracle.py`, `clip_scorer_gate.py` /
  `.sbatch`, `clip_selection_diagnostic.py`, `split_ladder_by_query.py`,
  `make_ladder_figs.py`, `make_quad_figs.py`, `selection_event_coverage.py`,
  `letter_floors.py` and `cvbench_text_answerability.py` under `--json`)
- `logs/` — Slurm `--output`/`--error` targets (`run_bench.sbatch`,
  `gen_clip_summaries.sbatch`, `clip_scorer_gate.sbatch`)
- `figs_deck/` — `make_slide_figs.py` (also `make_frame_sweep_fig.py`,
  `make_ladder_figs.py`, `make_quad_figs.py`, `make_cvbench_text_figs.py`)
- `figs_demo/` — `render_demo.py` (and `figs_demo/walls/` — `make_demo_walls.py`)
- `figs_demo_viclip/` — `render_demo.py --selection-method segment_select_viclip_opt`
- `figs_case/` — not rendered here: copy `demo/figs_case/` from adihebbalae/multicam-harness, where
  `demo/scripts/render_case_contrast.py` and `render_case_wall.py` render it (`demo_ui.html` runs without it)
- `slide_stats.json` — `mvueval_slide_stats.py`
- `sampler_diag.json` — `clip_selection_diagnostic.py`
- `repq_doc.*`, `*.pptx` — `make_repq_doc.py` / `make_repq_pptx.py` / `make_deck_pptx.py`
- `counting_failures*` — `counting_failures.py`
- `.agibot_tree_cache.json` — `fetch_agibot_videos.py`
