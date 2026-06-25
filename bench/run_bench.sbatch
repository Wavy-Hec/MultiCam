#!/bin/bash
### Multi-camera benchmark sweep (2 models x 2 harnesses x 4 passes).
### Supports Slurm-array sharding (OFFSET=$SLURM_ARRAY_TASK_ID, CHUNK=array size)
### and an env split: Qwen legs run under `cvbench`, InternVL3 under `internvl`
### (cvbench's transformers breaks the InternVL3 remote code).
###
### Usage:
###   # tiny smoke (Qwen, 5 records):
###   LIMIT=5 BACKENDS=qwen3vl sbatch bench/run_bench.sbatch
###   # full meva1033 Qwen leg, sharded 8 ways:
###   ENV=cvbench SUBSET=analysis/crossview_meva1033_subset.json BACKENDS=qwen3vl \
###     CHUNK=8 sbatch --array=0-7 bench/run_bench.sbatch
###   # full meva1033 InternVL3 leg, sharded 8 ways:
###   ENV=internvl SUBSET=analysis/crossview_meva1033_subset.json BACKENDS=internvl3 \
###     CHUNK=8 sbatch --array=0-7 bench/run_bench.sbatch
#SBATCH --job-name=bench-multicam
#SBATCH --output=analysis/logs/%A_%a.bench.out
#SBATCH --error=analysis/logs/%A_%a.bench.err
#SBATCH -N 1
#SBATCH -p gpul40q
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=6
#SBATCH --time=08:00:00

set -euo pipefail
REPO=/home/hectorlugo02/CVBench
cd "$REPO"
source ~/anaconda3/etc/profile.d/conda.sh
ENV=${ENV:-cvbench}
conda activate "$ENV"

export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
export DECORD_EOF_RETRY_MAX=${DECORD_EOF_RETRY_MAX:-20480}
export PYTORCH_ALLOC_CONF=${PYTORCH_ALLOC_CONF:-expandable_segments:True}

SUBSET=${SUBSET:-analysis/crossview_combined_subset.json}
METHODS=${METHODS:-centralized,per_stream}
BACKENDS=${BACKENDS:-qwen3vl}
LIMIT=${LIMIT:-0}
NFRAMES=${NFRAMES:-8}
PASSES=${PASSES:-4}
SEEDS=${SEEDS:-1,2,3,4}
TEMPERATURE=${TEMPERATURE:-0.7}
MONTAGE_FRAMES=${MONTAGE_FRAMES:-0}
MAX_NEW_TOKENS=${MAX_NEW_TOKENS:-8192}
INTERNVL_MAX_TILES=${INTERNVL_MAX_TILES:-1}
CHUNK=${CHUNK:-0}
# shard index: Slurm array task id if present, else OFFSET (default 0)
OFFSET=${SLURM_ARRAY_TASK_ID:-${OFFSET:-0}}

BASE="bench/results/bench_$(basename "${SUBSET%.json}")_${ENV}"
if [ "$CHUNK" != "0" ]; then
  OUT=${OUT:-${BASE}_shard${OFFSET}.jsonl}
  SHARD_ARG="--chunk $CHUNK --offset $OFFSET"
else
  OUT=${OUT:-${BASE}.jsonl}
  SHARD_ARG=""
fi
LIMIT_ARG=""
if [ "$LIMIT" != "0" ]; then LIMIT_ARG="--limit $LIMIT"; fi

echo "RUN @ $(date '+%F %T') env=$ENV subset=$SUBSET methods=$METHODS backends=$BACKENDS"
echo "     passes=$PASSES seeds=$SEEDS temp=$TEMPERATURE chunk=$CHUNK offset=$OFFSET out=$OUT"
python -m bench.run_bench --subset "$SUBSET" --methods "$METHODS" --backends "$BACKENDS" \
    --nframes "$NFRAMES" --passes "$PASSES" --seeds "$SEEDS" --temperature "$TEMPERATURE" \
    --montage-frames "$MONTAGE_FRAMES" --max-new-tokens "$MAX_NEW_TOKENS" \
    --internvl-max-tiles "$INTERNVL_MAX_TILES" --out "$OUT" $SHARD_ARG $LIMIT_ARG
echo "DONE @ $(date '+%F %T')"
