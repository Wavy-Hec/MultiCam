#!/bin/bash
### CVBench thinking-eval (Stage A: 45-question subset) — Qwen3-VL-8B-Thinking + InternVL3-8B.
### Modeled on eval_g1_imitation_vlm_all.sh. Smoke-test first with run_eval_smoke.sbatch.

#SBATCH --job-name=cvbench-think
#SBATCH --output=/home/hectorlugo02/CVBench/analysis/logs/%j.cvbench_think.out
#SBATCH --error=/home/hectorlugo02/CVBench/analysis/logs/%j.cvbench_think.err
#SBATCH -N 1
#SBATCH -p gpul40q
#SBATCH --gres=gpu:1
#SBATCH --time=2-00:00:00
#SBATCH --cpus-per-task=6
set -euo pipefail

echo "CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-unset}"
source ~/anaconda3/etc/profile.d/conda.sh
conda activate cvbench
export DECORD_EOF_RETRY_MAX=20480
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}   # weights pre-downloaded on the login node
# avoid allocator fragmentation OOM on multi-video questions (see job 56671)
export PYTORCH_ALLOC_CONF=expandable_segments:True

REPO=/home/hectorlugo02/CVBench
cd "$REPO"

QWEN_CKPT=${QWEN_CKPT:-Qwen/Qwen3-VL-8B-Thinking}
INTERNVL_CKPT=${INTERNVL_CKPT:-OpenGVLab/InternVL3-8B}
SUBSET=${SUBSET:-analysis/subset.json}
LIMIT_ARG=${LIMIT_ARG:-}          # e.g. "--limit 3" for a smoke run

echo "RUN STARTED @ $(date '+%F %T')  | Qwen=$QWEN_CKPT  InternVL=$INTERNVL_CKPT  subset=$SUBSET $LIMIT_ARG"

echo "=== 0/3  rebuild mvr_dataset from $SUBSET (keeps the lmms-eval leg in sync) ==="
python - "$SUBSET" <<'PY'
import json, sys
from datasets import Dataset, DatasetDict
recs = json.load(open(sys.argv[1]))
DatasetDict({"test": Dataset.from_list(recs)}).save_to_disk("mvr_dataset.tmp")
print(f"mvr_dataset rebuilt: {len(recs)} rows")
PY
rm -rf mvr_dataset && mv mvr_dataset.tmp mvr_dataset

echo "=== 1/3  Qwen3-VL thinking eval ==="
python Video-R1/src/eval_thinking.py \
    --model_path "$QWEN_CKPT" \
    --input_json "$SUBSET" \
    --output Video-R1/src/r1-v/eval_results/eval_subset_qwen3vl.json \
    --nframes 8 --max_new_tokens 2048 $LIMIT_ARG

echo "=== 2/3  InternVL3 thinking eval (lmms-eval; run from lmms-eval/ so ./res markers resolve) ==="
# InternVL3 remote code predates transformers 5; run this leg from the
# transformers==4.48.3 overlay venv (shares torch/decord with cvbench).
IVL_PY=/home/hectorlugo02/CVBench/.venv-internvl/bin/python
# verbosity=DEBUG so lmms_eval re-raises instead of swallowing exceptions (exit 0)
( cd lmms-eval && "$IVL_PY" -m lmms_eval \
    --model internvl2 \
    --model_args "pretrained=${INTERNVL_CKPT},num_frame=8" \
    --tasks mvr_think --batch_size 1 --log_samples \
    --verbosity=DEBUG \
    --output_path ./logs/ ${LIMIT_ARG} )

echo "=== 3/3  analyze ==="
# newest jsonl only: each run writes a fresh timestamped file into the same dir
SAMPLES=$(ls -t lmms-eval/logs/*nternVL*/*_samples_mvr_think.jsonl 2>/dev/null | head -1)
[ -n "$SAMPLES" ] || { echo "FATAL: InternVL produced no samples jsonl"; exit 1; }
python analysis/parse_lmms_samples.py \
    --samples "$SAMPLES" \
    --out analysis/internvl3_normalized.json
python analysis/analyze_failures.py \
    qwen3vl=Video-R1/src/r1-v/eval_results/eval_subset_qwen3vl.json \
    internvl3=analysis/internvl3_normalized.json
python analysis/plot_accuracy.py

echo "RUN DONE @ $(date '+%F %T')"
echo "See analysis/{qwen3vl,internvl3}_failures.md and analysis/accuracy_vs_cameras.png"
