#!/bin/bash
### Per-clip summary-cache generation for the summary_select_* methods.
### One VLM call per unique clip; resumable; shard with CHUNK + --array.
###
### Usage:
###   # the 357 unique clips of the 130-question temporal subset (~45 min):
###   SUBSET=analysis/cvbench_temporal_subset.json sbatch bench/gen_clip_summaries.sbatch
###   # the full 1315-clip manifest, sharded 4 ways:
###   MANIFEST=analysis/cvbench_all_videos.txt CHUNK=4 sbatch --array=0-3 \
###     bench/gen_clip_summaries.sbatch
#SBATCH --job-name=clip-summaries
#SBATCH --output=analysis/logs/%A_%a.summaries.out
#SBATCH --error=analysis/logs/%A_%a.summaries.err
#SBATCH -N 1
#SBATCH -p gpul40q
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=6
#SBATCH --time=08:00:00

set -euo pipefail
REPO=/home/hectorlugo02/CVBench
cd "$REPO"
source ~/anaconda3/etc/profile.d/conda.sh
ENV=${ENV:-internvl}
conda activate "$ENV"

export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
export DECORD_EOF_RETRY_MAX=${DECORD_EOF_RETRY_MAX:-20480}
export PYTORCH_ALLOC_CONF=${PYTORCH_ALLOC_CONF:-expandable_segments:True}

BACKEND=${BACKEND:-internvl3}
VIDEO_ROOT=${VIDEO_ROOT:-Video-R1/src/r1-v/Evaluation/CVBench}
OUT=${OUT:-bench/results/clip_summaries_internvl3.jsonl}
LIMIT=${LIMIT:-0}
CHUNK=${CHUNK:-0}
OFFSET=${SLURM_ARRAY_TASK_ID:-${OFFSET:-0}}

SRC_ARG=""
if [ -n "${SUBSET:-}" ]; then SRC_ARG="--subset $SUBSET"; fi
if [ -n "${MANIFEST:-}" ]; then SRC_ARG="--manifest $MANIFEST"; fi
if [ -z "$SRC_ARG" ]; then echo "set SUBSET= or MANIFEST="; exit 2; fi
LIMIT_ARG=""
if [ "$LIMIT" != "0" ]; then LIMIT_ARG="--limit $LIMIT"; fi
SHARD_ARG=""
if [ "$CHUNK" != "0" ]; then SHARD_ARG="--chunk $CHUNK --offset $OFFSET"; fi
RETRY_ARG=""
if [ -n "${RETRY_ERRORS:-}" ]; then RETRY_ARG="--retry-errors"; fi

echo "SUMMARIES @ $(date '+%F %T') env=$ENV src=$SRC_ARG out=$OUT chunk=$CHUNK offset=$OFFSET"
python -m bench.gen_clip_summaries $SRC_ARG --backend "$BACKEND" \
    --video-root "$VIDEO_ROOT" --out "$OUT" $SHARD_ARG $LIMIT_ARG $RETRY_ARG
echo "DONE @ $(date '+%F %T')"
