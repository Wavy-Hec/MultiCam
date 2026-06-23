#!/bin/bash
### Multi-camera benchmark sweep. Mirrors analysis/run_eval_crossview.sbatch env.
### Usage:
###   # tiny smoke:
###   LIMIT=5 METHODS=centralized BACKENDS=qwen3vl sbatch bench/run_bench.sbatch
###   # full off-peak sweep tonight (chain a report job with --dependency=afterok:<jobid>):
###   sbatch --begin=02:00 bench/run_bench.sbatch
#SBATCH --job-name=bench-multicam
#SBATCH --output=analysis/logs/%j.bench.out
#SBATCH --error=analysis/logs/%j.bench.err
#SBATCH -N 1
#SBATCH -p gpul40q
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=6
#SBATCH --time=08:00:00

set -euo pipefail
REPO=/home/hectorlugo02/CVBench
cd "$REPO"
source ~/anaconda3/etc/profile.d/conda.sh
conda activate cvbench

export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
export DECORD_EOF_RETRY_MAX=${DECORD_EOF_RETRY_MAX:-20480}
export PYTORCH_ALLOC_CONF=${PYTORCH_ALLOC_CONF:-expandable_segments:True}

SUBSET=${SUBSET:-analysis/crossview_combined_subset.json}
METHODS=${METHODS:-centralized,per_stream}
BACKENDS=${BACKENDS:-qwen3vl,qwen3vl-instruct}
LIMIT=${LIMIT:-0}
NFRAMES=${NFRAMES:-8}
OUT=${OUT:-bench/results/bench_$(basename "${SUBSET%.json}").jsonl}

LIMIT_ARG=""
if [ "$LIMIT" != "0" ]; then LIMIT_ARG="--limit $LIMIT"; fi

echo "RUN @ $(date '+%F %T') subset=$SUBSET methods=$METHODS backends=$BACKENDS limit=$LIMIT out=$OUT"
python -m bench.run_bench --subset "$SUBSET" --methods "$METHODS" --backends "$BACKENDS" \
    --nframes "$NFRAMES" --out "$OUT" $LIMIT_ARG
echo "DONE @ $(date '+%F %T')"
