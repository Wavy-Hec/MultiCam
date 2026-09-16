# `analysis/`

Flat by convention (see `CLAUDE.md`): scripts, curated inputs, and gitignored outputs
share this directory with no subdirectories. This file says which is which. Every
script runs from the repo root as `python3 analysis/<name>.py`.

## 1. Scripts by kind

38 files total (`ls analysis/*.py analysis/*.sh analysis/*.sbatch analysis/demo_ui.html`). "Writes" is the
generator's own default output path (or `--out`/`OUT` constant); many also print a
report to stdout regardless.

### Converters

| Script | Purpose | Writes |
|---|---|---|
| `convert_allangles.py` | Converts All-Angles-Bench multi-view still-image QA into the harness record schema | `allangles_qa.json`, `allangles_dev_subset.json` |
| `convert_crossview.py` | Converts UT Austin CrossView (Multi-Camera VQA) annotations into the harness record schema | `crossview_qa.json` (untracked), `crossview_subset.json`, `crossview_subset_fetch.json`, `crossview_subset_videos.txt` |
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
| `make_deck_html.py` | Assembles the results deck HTML from `figs_deck/*.png`, base64-embedded | a required positional `<out.html>` path (no default under `analysis/`) |
| `make_deck_pptx.py` | Assembles the results deck as PowerPoint, "Part 2" of the July-28 slides | `deck_part2.pptx` |
| `make_frame_sweep_fig.py` | Accuracy vs frame budget, small multiples across the three datasets | `figs_deck/fig_frame_sweep*.png` |
| `make_headline_figs.py` | Two slide-headline figures assembled from already-dumped series JSONs | `bench/results/figs_task1_overview/*.png` (not under `analysis/`) |
| `make_ladder_figs.py` | The segment-selection ladder as numbers and as the Task-1 figures | `figs_deck/fig_ladder_*.png`, `fig_meva_defect.png`; optional `--json` (e.g. `records/ladder_stats.json`) |
| `make_repq_doc.py` | Builds the representative-questions doc the mentor requested (2026-08-01) | `repq_doc.html`, `repq_doc_manifest.json` |
| `make_repq_pptx.py` | Renders the representative-questions doc as an importable PowerPoint deck | `repq_deck.pptx` |
| `make_slide_figs.py` | Renders the July-30 results deck figures (the InternVL3-8B slide remake) | `figs_deck/*.png` |
| `render_demo.py` | Per-question demo figures for the four-camera MEVA demo: the segment timeline with the kept segments, selected frames and annotated event windows per camera, the per-arm answer panel with the trace excerpt, and a demo-set summary beside the meva1033 ladder. `--selection-method` picks whose selection is drawn — `segment_select_siglip` (default) or `segment_select_viclip_opt`; the scorer name and the query mode on the header and the colorbar are read from the row's `frame_alloc`, and the summary ladder grows the ViCLIP-opt rungs when a ViCLIP arm is rendered | `figs_demo/` for the SigLIP set, `figs_demo_viclip/` (`--out`) for the ViCLIP set (`q<id>_selection.png`, `q<id>_answer.png`, `summary.png`, `manifest.json`) |
| `make_demo_walls.py` | One 2x2 camera-wall MP4 per demo question from `figs_demo/manifest.json`: the four streams on a shared clip clock over the annotated event window, each tile carrying its evidence/padding badge, SigLIP segment strip, kept segments, event bars and playhead, dimmed whenever the selector did not send that moment, closing on a per-arm answer card; `walls_all.mp4` is rebuilt from every wall present in the output directory, so a `--ids` re-render never truncates the reel (`walls_manifest.json` lists the ids it carries) | `figs_demo/walls/` (`q<id>_wall.mp4`, `q<id>_wall_snapshot.png`, `walls_all.mp4`, `walls_manifest.json`) |
| `demo_live_tail.py` | Tails a result JSONL and prints one line per answer as it lands (id, arm, prediction vs gold, latency, tokens, kept segments per camera), for the recorded demo's terminal segment; `--replay` re-prints an existing file | stdout |
| `demo_ui.html` | Screen-recording replay page for the four-camera demo (one self-contained file, no CDN): pick one of the five questions, then five numbered buttons (or keys 1-5, arrows to change question) reveal the camera-wall clip, the selection figure, an answer card built from the manifest, and one reasoning trace; the SigLIP/ViCLIP switch swaps the asset root | writes nothing - reads `figs_demo/`, `figs_demo_viclip/` and `bench/results/bench_demo_*_demo_reason.jsonl`/`_demo_global.jsonl`; serve the repo root and open `analysis/demo_ui.html` |
| `restyle_task1_figs.py` | Re-renders the Task-1 figures from the JSON series `bench/plots.py` dumps | `bench/results/figs_task1_*/*_v2.png` (not under `analysis/`) |

### Stats / splits

| Script | Purpose | Writes |
|---|---|---|
| `allangles_consistency.py` | All-Angles-Bench paired-question consistency report (the paper's CC/WW/IC split) | stdout only |
| `counting_failures.py` | Counting-failure analysis: dedup failure vs perception miss vs guess | optional `--out-md`/`--out-json` (no default; stdout otherwise) |
| `crossview_question_types.py` | Question-type analysis of the UT Austin CrossView annotations | `crossview_question_types.md` |
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

### Rescoring

| Script | Purpose | Writes |
|---|---|---|
| `rescore_answers.py` | Re-derives prediction/correct/abstained from the stored `response_text` | `bench/results/rescored/<basename>` (+ `_summary.json`); not under `analysis/` |

### Env

| Script | Purpose | Writes |
|---|---|---|
| `setup_env.sh` | One-time env setup for the CVBench thinking-eval: clones `vlm` into the `cvbench` conda env | no file; creates the `cvbench` conda env |

## 2. Tracked non-script inputs

19 files (`git ls-files analysis | grep -E "\.(json|txt)$"`). Counts measured
2026-09-03:

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
| `crossview_egoexo500.json` | eval subset | 108 | 21 | live |
| `crossview_egoexo_subset.json` | eval subset | 0 | 0 | generator default (`fetch_egoexo_videos.py --subset`); superseded by `crossview_egoexo500.json` for live runs |
| `crossview_meva1033_subset.json` | eval subset | 308 | 23 | live; default subset for most MEVA analysis scripts |
| `crossview_meva4cam_subset.json` | eval subset | 0 | 0 | sole consumer `bench/legacy/qual_make_figs.py` (retired, no other referrers) |
| `crossview_meva_cap13.json` | eval subset | 166 | 27 | live |
| `crossview_nuscenes12_subset.json` | eval subset | 0 | 0 | live; 12-record stratified preflight pool (3 per task type) drawn from `crossview_nuscenes1497_subset.json`; preflight results are staged outside `bench/results/` and are never registered |
| `crossview_nuscenes1497_subset.json` | eval subset | 16 | 1 | live; 1497 nuScenes MCQ records, four task types, six cameras each; compiled 2026-09-09 from the release annotations by a gitignored shim (no tracked generator); blind-only pool — no nuScenes media is on disk |
| `crossview_subset.json` | eval subset | 0 | 0 | generator default (`convert_crossview.py --out-subset`, `fetch_meva_videos.py --subset`); superseded by `crossview_meva1033_subset.json` / `crossview_meva_cap13.json` for live runs |
| `crossview_subset_fetch.json` | fetch manifest | 0 | 0 | generator default (`convert_crossview.py --out-fetch`); consumed by `hosting/fetch_videos.py` |
| `crossview_subset_videos.txt` | video list | 0 | 0 | generator default (`convert_crossview.py --out-videos`); consumed by `bench/gen_clip_summaries.py` |
| `demo_meva4cam_subset.json` | eval subset | 8 | 0 | live; 5-record four-camera MEVA demo subset (ids 860, 749, 251, 1, 130) behind `render_demo.py`; result stem `bench_demo_meva4cam_subset_*`; not registered; the demo legs ran as one-off kimq jobs 99072-99075 |
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

`registry.json` lists only registered legs (7 subset keys appear there at all); the
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
  `make_ladder_figs.py`, `letter_floors.py` under `--json`)
- `logs/` — Slurm `--output`/`--error` targets (`run_bench.sbatch`,
  `gen_clip_summaries.sbatch`, `clip_scorer_gate.sbatch`)
- `figs_deck/` — `make_slide_figs.py` (also `make_frame_sweep_fig.py`,
  `make_ladder_figs.py`)
- `figs_demo/` — `render_demo.py` (and `figs_demo/walls/` — `make_demo_walls.py`)
- `figs_demo_viclip/` — `render_demo.py --selection-method segment_select_viclip_opt`
- `slide_stats.json` — `mvueval_slide_stats.py`
- `sampler_diag.json` — `clip_selection_diagnostic.py`
- `repq_doc.*`, `*.pptx` — `make_repq_doc.py` / `make_repq_pptx.py` / `make_deck_pptx.py`
- `counting_failures*` — `counting_failures.py`
- `.agibot_tree_cache.json` — `fetch_agibot_videos.py`
