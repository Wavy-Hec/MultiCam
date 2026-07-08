# Hosting the CrossView benchmark videos

The CrossView release (`crossview-release-annotations/crossview-release/`)
ships annotations only. The 7,760 referenced videos (MEVA 2,227, Ego-Exo4D
2,037, AgiBotWorld 1,996, nuScenes 1,500) live on the lab NAS. This folder
hosts them on Hugging Face as a **private** dataset repo so collaborators
without NAS access can pull exactly what they need.

Design: one set of **store-mode zip shards per source dataset**
(`shards/meva-000.zip`, ...) with internal paths equal to the annotation
`video_paths` (`videos/meva/...`). Store-mode zips allow fetching single
videos via HTTP range requests — nobody has to download terabytes to look at
20 failure cases. `shards/shard_index.csv` maps each video to its shard.

## For the uploader (Adi — or anyone who can read `/nas/mars/...`)

```bash
# one-time setup (any python >= 3.8)
pip install -U huggingface_hub
hf auth login          # paste a WRITE token from https://hf.co/settings/tokens

cd <wherever>/crossview-release    # the dir containing video_manifest.csv

# 1. size pass — fills the manifest's empty bytes column, prints totals
python3 package_and_upload.py size
#    -> REPORT THE TOTAL GB BACK BEFORE UPLOADING:
#       < 100 GB: free HF account is enough
#       < 1 TB:   the uploading account needs HF PRO ($9/month)

# 2. pack per-dataset zip shards (needs ~total-size free disk for shards/)
python3 package_and_upload.py pack
#    short on disk? pack+upload one dataset at a time:
#    python3 package_and_upload.py pack --datasets meva

# 3. upload (idempotent — safe to re-run after an interruption)
python3 package_and_upload.py upload --repo <hf-username>/crossview-videos
```

Then send back: the repo id, the size-pass totals, and
`video_manifest.filled.csv`. Grant collaborators read access on the repo
settings page (or create it under a shared HF org).

`package_and_upload.py` is self-contained — copying this one file to the NAS
machine is enough.

## For consumers (Hector, Adi)

```bash
pip install -U huggingface_hub remotezip
hf auth login          # READ token; account must have repo access
export CROSSVIEW_HF_REPO=<hf-username>/crossview-videos

# qualitative pass: fetch only the videos one QA file references
python3 hosting/fetch_videos.py subset \
    --qa crossview-release-annotations/crossview-release/annotations/multi-cam-dataset/meva/qa_best_camera.json

# full-eval stage: everything for one dataset
python3 hosting/fetch_videos.py dataset meva

# sanity check before running evals
python3 hosting/fetch_videos.py verify --qa <same json>
```

Videos land under
`crossview-release-annotations/crossview-release/videos/...`, so the relative
`video_paths` in the QA JSONs resolve against the release root unchanged.
Point eval code at that root.

Suggested split: one dataset per person (e.g. Hector: MEVA, Adi: Ego-Exo4D),
same task — question-type breakdown, then qualitative failure cases with a
thinking model, then accuracy vs num-cameras.

## Licensing — read before sharing

| Dataset     | License                  | Rehostable?                          |
|-------------|--------------------------|--------------------------------------|
| MEVA        | CC-BY-4.0                | Yes, with attribution                |
| AgiBotWorld | CC-BY-NC-SA-4.0          | Yes, non-commercial, same license    |
| Ego-Exo4D   | Meta license (signed)    | **No** — "may not provide access to the Database, in whole or in part" |
| nuScenes    | Non-commercial, gated    | **No** — registration required       |

Consequences:

- The HF repo **must stay private**. Only grant access to collaborators, and
  only ones who have themselves signed the Ego-Exo4D license and registered
  for nuScenes (sign-up: https://ego-exo4d-data.org / https://www.nuscenes.org).
- For an eventual public release: mirror only the MEVA + AgiBotWorld shards
  to a public repo, and ship download-and-place instructions (official
  sources + `video_manifest.csv` mapping) for Ego-Exo4D and nuScenes.
