# Repo cleanup report — 2026-06-23

Cleanup of the `crossview-benchmark` branch after a multi-agent read-only audit. Goal: keep ~166 GB
of external/regenerable data out of git, remove verified cruft, commit real work-product, **without
breaking the carefully `file:line`-anchored docs or the runtime pipeline**.

## `.gitignore` additions (kept out of git)
| Path | Size | Why |
|------|-----:|-----|
| `/crossview-release-annotations/` | **161 GB** | raw MEVA/EgoExo4D videos + annotations (licensed/re-downloadable) |
| `/Video-R1/src/r1-v/Evaluation/CVBench/` | 2.1 GB | eval video clips (regenerable from HF) |
| `/analysis/logs/`, `/analysis/download_subset.log` | 3.3 MB | SLURM/run logs |
| `/analysis/failure_examples/` | 14 MB | regenerable example media |
| `/analysis/slides_v2_figs/`, `*.pptx` | ~3 MB | slide figures + decks (rebuilt by `make_slides_v2.py`) |
| `/analysis/crossview_meva1033_out/{qwen3vl,internvl3}_failures.md` | 12.8 MB | raw per-question dumps (rebuilt by `analyze_failures.py`); the **curated digest** `failure_examples_curated.md` stays tracked |
| `*.contaminated*.bak` | — | eval-rerun backups |

## Deleted (md5/diff-verified cruft)
- `…/eval_crossview_subset_qwen3vl.json.contaminated-20260615.bak` — the "do not use" contaminated run.
- `analysis/crossview_meva1033_internvl3_normalized.json` — **exact** md5 duplicate of
  `crossview_internvl3_meva1033_normalized.json` (kept the canonical; dropped the dup row in ORIENTATION §8).
- `analysis/crossview_out_1033/`, `analysis/crossview_out_1033_iv/` — stale, superseded by `crossview_meva1033_out/`.
- `analysis/make_slides.py` — superseded by `make_slides_v2.py` (refs in `README.md`/`ORIENTATION.md` updated).

## Committed work-product (logical groups)
1. Repo hygiene (this `.gitignore` + cruft removal).
2. Canonical eval results: clean Qwen re-run, blind baseline, 1,033-Q Qwen (**35 MB — large, but
   not cheaply regenerable; tracked per the existing "track eval outputs" pattern**), InternVL3 normalized.
3. Analysis work-product: `ORIENTATION.md`, `why_models_fail.md`, refreshed reports/README,
   `crossview_out/` + `crossview_meva1033_out/` (small artifacts), subset definitions, scripts/figs.
4. Planning deliverables: `analysis/BENCHMARK_PLAN_48H.md`, `paper/multicam_benchmark.tex`, this file.

## Left untouched (intentionally not committed, not deleted)
- `.claude/` — local Claude Code session config.
- `eval_g1_imitation_vlm_all.sh` (repo root) — **a stray SLURM script from your `~/VLM/` (G1-imitation
  RL) project**, not part of CVBench. Left in place; you may want to move it back to `~/VLM/`.

## Directory reorg — deferred (with reason)
The audit's "+ safe reorg" (relocate into `analysis/{subsets,scripts,…}/`) was approved on the
assumption it broke no anchors. On execution we found the subset/data files are referenced across
**25+ files / 40+ sites** — including the *verified-trace* docs (`input_pipeline.md`,
`blind_sanity.md`, `crossview_subset_questions.md`), every fetcher script, all four `run_eval*.sbatch`,
and `HERE`-relative argparse defaults in `convert_crossview.py` / `select_subset.py`. Moving them would
risk the pipeline and the verified docs for marginal declutter. **The file moves were deferred** — see
the open question to the user. The flat layout is partly intentional (scripts write outputs relative
to their own directory).

## Verify
```bash
git ls-files | xargs -I{} du -h {} 2>/dev/null | sort -rh | head   # no raw videos; largest tracked blobs are eval JSONs
git status --short                                                  # clean except .claude/ + the stray .sh
grep -rn 'make_slides\.py' analysis/*.md                            # 0 stale refs
```
