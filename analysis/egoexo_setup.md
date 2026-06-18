# EgoExo4D enablement — license + download walkthrough

Goal: run the **combined MEVA + EgoExo4D** CrossView eval. The MEVA half is already
local; the only gate is the license-gated EgoExo4D video download. Everything below
the license step is pre-staged — once your credentials arrive it is two commands.

## Status (already done, no license needed)
- Combined subset built → `analysis/crossview_combined_subset.json`
  (100 questions = 60 MEVA + 40 EgoExo4D, 20 per type across all 5 task types).
- MEVA videos: all 84 referenced clips already present locally (0 to fetch).
- EgoExo4D gap: **96 video files across 24 takes** (downscaled-448 frame-aligned).
- Downloader installed: `ego4d` 1.7.3 (CLI `egoexo`) in conda env `cvbench`.
- Fetch helper verified: `analysis/fetch_egoexo_videos.py`.

## Step 1 — accept the license TODAY (only you can do this)
Free for research; approval takes **~48h** and the issued AWS keys **expire in 14 days**,
so start the clock now but don't run the download until you can finish within 14 days.
- Form: <https://ego4d.dev/request/ego-exo4d> (a.k.a. <https://ego4ddataset.com/egoexo-license/>).
- Sign **as an individual** for your own use, or have a **director/executive** sign on
  behalf of the institution (org-wide coverage needs director-level signatory). If this
  is institutional, kick off that sign-off first — it's the longest pole.
- You'll be emailed an AWS **access key + secret key**.

## Step 2 — configure credentials (when the email arrives)
```bash
source ~/anaconda3/etc/profile.d/conda.sh && conda activate cvbench
aws configure --profile egoexo        # paste Access Key, then Secret Key; Enter twice for defaults
```
(`awscli` ships with the env; if missing: `pip install awscli`.)

## Step 3 — fetch metadata (the take_name → take_uid map)
The downloader filters by take **UID**, but our annotations use take **names**, so grab
`takes.json` first (small; needs your credentials):
```bash
egoexo -o /tmp/egoexo_meta --parts metadata --s3_profile egoexo
TAKES_JSON=$(find /tmp/egoexo_meta -name takes.json | head -1)   # location varies; locate it
```

## Step 4 — download ONLY this subset's videos (~a few GB)
The helper maps the 24 take names → UIDs and runs the restricted download into the exact
release layout the harness expects (`videos/ego-exo4d/takes/<take>/frame_aligned_videos/downscaled/448/<cam>.mp4`):
```bash
python3 analysis/fetch_egoexo_videos.py \
    --subset analysis/crossview_combined_subset.json \
    --takes-json "$TAKES_JSON" --s3-profile egoexo --run
```
Equivalent manual command it runs:
`egoexo -o <release>/videos/ego-exo4d --parts downscaled_takes/448 --release v2 -y --s3_profile egoexo --uids <24 uids>`

⚠️ Always keep `--parts downscaled_takes/448` **and** `--uids` together — a bare
`egoexo -o <dir>` starts the multi-TB full download.

## Step 5 — verify, then run the combined eval
```bash
python3 analysis/fetch_egoexo_videos.py --subset analysis/crossview_combined_subset.json --check   # expect missing: 0
SUBSET=analysis/crossview_combined_subset.json FETCH=analysis/crossview_combined_subset_fetch.json \
    sbatch analysis/run_eval_crossview.sbatch
```

## Reporting caveat (don't skip)
EgoExo4D has no per-camera grounding, so 38/40 of its subset questions are **lossy-capped**
(`cap_answer_safe=false`) — its score is a **lower bound**. MEVA stays answer-safe. Report
them stratified by `cap_answer_safe` (every record carries the tag); never pool the two
into one accuracy. The clean cross-source comparison is on **temporal + event_ordering**
only (MEVA-spatial has no EgoExo4D counterpart).

## Sources
Ego-Exo4D docs — Getting Started, CLI Downloader, Downscaled Takes, Metadata
(`docs.ego-exo4d-data.org`); `facebookresearch/Ego4d` README + egoexo download README.
