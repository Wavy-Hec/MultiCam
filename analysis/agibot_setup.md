# AgiBot enablement — incremental license + download walkthrough

Goal: add **AgiBot** (robot dual-arm manipulation, head + 2 wrist cameras) to the
CrossView benchmark alongside MEVA, **incrementally** — grab a little now, more over
time — without committing to the full multi-TB pull up front.

## Status (already done, no license needed)
- AgiBot **wired** into the converter (`SOURCE_FILES`/`SOURCE_LABEL`, temporal +
  event_ordering) and the harness (`TASK_CATEGORIES` has `CrossView-AgiBot-*`).
- **Cap-safe**: ≤3 cameras (head_color + hand_right/left_color) → the ≤4 cap never
  drops a view. 499 clean MCQs, **0 lossy** (unlike EgoExo4D — no "lower bound" caveat).
- Subsets built: `crossview_agibot_subset.json` (40 Qs) and the triple
  `crossview_full_subset.json` (MEVA+EgoExo4D+AgiBot).
- Incremental fetch helper: `analysis/fetch_agibot_videos.py`.
- Converter flag `--require-local <root>`: builds a runnable subset from whatever
  videos are present, so a partial fetch is immediately usable.

## The reality (why it's incremental, not "a few GB")
On Hugging Face, AgiBot videos are **not** individually addressable — each episode's
mp4s are bundled inside a **per-task `.tar` shard** (2–287 GB each) in the gated
`agibot-world/AgiBotWorld-Beta` repo. The smallest fetch unit is a whole task tar.
Fully covering our 40-Q subset = ~810 GB of tars (to keep 77 small mp4s). So we fetch
**cheapest tars first, capped by `--budget-gb`, deleting each tar after extracting**
(peak disk ≈ one tar). Disk is fine — `/home` has ~9 TB free; **do not** use `/tmp`.

## Step 1 — accept the HF gate + get a token (only you; instant)
- Accept (instant click-through, no 48h wait): **<https://huggingface.co/datasets/agibot-world/AgiBotWorld-Beta>** → "Agree and access repository".
- License: **CC BY-NC-SA 4.0 — non-commercial.** Fine for research; don't use commercially.
- Token on this machine:
```bash
source ~/anaconda3/etc/profile.d/conda.sh && conda activate cvbench
export HF_TOKEN=hf_xxxxxxxx        # or: hf auth login   (huggingface_hub is installed)
```

## Step 2 — fetch a little now (cheapest tars)
```bash
python3 analysis/fetch_agibot_videos.py --budget-gb 10            # plan only (free, public)
python3 analysis/fetch_agibot_videos.py --budget-gb 10 --run      # ~4–10 GB -> a handful of episodes
```
Defaults target the full AgiBot pool, so cheapest-first maximizes episodes-per-GB and
coverage grows across runs. (First run lists 163 tasks from HF — ~1–2 min, then cached.)

## Step 3 — build a runnable MEVA+AgiBot subset from what's local
```bash
python3 analysis/convert_crossview.py --sources meva,agibot --meva-video-ext avi \
    --require-local crossview-release-annotations/crossview-release \
    --n 100 --out-subset analysis/crossview_meva_agibot_subset.json \
    --out-qa analysis/crossview_meva_agibot_qa.json \
    --out-videos analysis/crossview_meva_agibot_videos.txt \
    --out-fetch analysis/crossview_meva_agibot_fetch.json
```
This keeps every MEVA question (videos local) + only the AgiBot questions whose videos
you've fetched so far. Re-run it any time you fetch more — it grows automatically.

## Step 4 — run the eval
```bash
SUBSET=analysis/crossview_meva_agibot_subset.json FETCH=analysis/crossview_meva_agibot_fetch.json \
    sbatch analysis/run_eval_crossview.sbatch
```

## Step 5 — get more over time
```bash
python3 analysis/fetch_agibot_videos.py --budget-gb 100 --run     # adds more cheapest tars; skips local
python3 analysis/fetch_agibot_videos.py --check                   # coverage report
```
Each run extends coverage; already-fetched episodes are skipped. Rebuild the subset
(Step 3) and re-run (Step 4) whenever you want the bigger AgiBot slice.

## Notes
- AgiBot adds DOMAIN diversity (embodied robot manipulation), not camera-count range
  (fixed ≤3 cams) — don't read scaling-curve conclusions from it.
- Sources: HF dataset page + live tree API (tar layout/sizes, `gated:auto`),
  github.com/OpenDriveLab/AgiBot-World (CC BY-NC-SA 4.0, structure).
