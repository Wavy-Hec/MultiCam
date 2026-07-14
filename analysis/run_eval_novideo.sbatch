#!/bin/bash
### Blind baseline: Qwen3-VL-8B-Thinking on the 45-question subset with NO video input.
### Same prompts as the Stage-A run; measures how far language priors alone get.

#SBATCH --job-name=cvbench-novideo
#SBATCH --output=analysis/logs/%j.cvbench_novideo.out
#SBATCH --error=analysis/logs/%j.cvbench_novideo.err
#SBATCH -N 1
#SBATCH -p gpul40q
#SBATCH --gres=gpu:1
#SBATCH --time=0-06:00:00
#SBATCH --cpus-per-task=6
set -euo pipefail

source ~/anaconda3/etc/profile.d/conda.sh
conda activate cvbench
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}   # weights pre-downloaded on the login node
export PYTORCH_ALLOC_CONF=expandable_segments:True

REPO=$HOME/CVBench
cd "$REPO"

python3 Video-R1/src/eval_thinking.py \
    --model_path "${QWEN_CKPT:-Qwen/Qwen3-VL-8B-Thinking}" \
    --input_json analysis/subset.json \
    --output Video-R1/src/r1-v/eval_results/eval_subset_qwen3vl_novideo.json \
    --no_video --max_new_tokens 2048

echo "DONE @ $(date '+%F %T')"
