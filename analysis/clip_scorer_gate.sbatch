#!/bin/bash
# Offline per-option similarity gate (meeting item 5b).
#
# Run this BEFORE spending GPU-hours on an option-conditioned eval: it answers
# whether the answer-option text carries any visual signal at all. Decode is the
# bottleneck (a 300 s MEVA .avi costs ~12 s to sample), so this asks for cores
# rather than a large GPU; the scorer uses whatever device is present.
#
#   sbatch analysis/clip_scorer_gate.sbatch                       # CrossView-MEVA
#   SUBSET=analysis/crossview_egoexo500.json \
#     OUT=analysis/records/gate_peropt_egoexo.json \
#     sbatch analysis/clip_scorer_gate.sbatch
#
#SBATCH --job-name=gate-peropt
#SBATCH --output=analysis/logs/%j.gate.out
#SBATCH --error=analysis/logs/%j.gate.err
#SBATCH -N 1
#SBATCH -p sxmq,gpul40q
### gpuq belongs to the physics group — do not submit there without permission.
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=24
#SBATCH --time=04:00:00
set -euo pipefail
cd "$HOME/CVBench"
source "$HOME/anaconda3/etc/profile.d/conda.sh"
conda activate "${ENV:-internvl}"
export HF_HUB_OFFLINE=1
export DECORD_EOF_RETRY_MAX=20480

SUBSET=${SUBSET:-analysis/crossview_meva_cap13.json}
OUT=${OUT:-analysis/records/gate_peropt.json}
MODELS=${MODELS:-openai/clip-vit-base-patch32}
WORKERS=${WORKERS:-24}
THUMBS=${THUMBS:-8}

mkdir -p "$(dirname "$OUT")" analysis/logs
echo "GATE @ $(hostname) subset=$SUBSET models=$MODELS workers=$WORKERS thumbs=$THUMBS"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true

python analysis/clip_scorer_gate.py \
  --subset "$SUBSET" \
  --workers "$WORKERS" \
  --thumbs "$THUMBS" \
  --models $MODELS \
  --per-option \
  --out "$OUT" \
  ${LIMIT:+--limit "$LIMIT"} \
  ${VIDEO_ROOT:+--video-root "$VIDEO_ROOT"}

echo "DONE -> $OUT"
