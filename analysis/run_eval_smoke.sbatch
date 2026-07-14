#!/bin/bash
### Smoke test: validate env + GPU + both models + data on 3 questions before the full run.

#SBATCH --job-name=cvbench-smoke
#SBATCH --output=analysis/logs/%j.cvbench_smoke.out
#SBATCH --error=analysis/logs/%j.cvbench_smoke.err
#SBATCH -N 1
#SBATCH -p gpul40q
#SBATCH --gres=gpu:1
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=6
set -euo pipefail

echo "CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-unset}"
source ~/anaconda3/etc/profile.d/conda.sh
conda activate cvbench
export DECORD_EOF_RETRY_MAX=20480
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
# job 56671 OOMed with 13.9 GiB reserved-but-unallocated (fragmentation from
# variable-length multi-video sequences under eager attention)
export PYTORCH_ALLOC_CONF=expandable_segments:True

REPO=$HOME/CVBench
cd "$REPO"

echo "=== smoke 0/2: rebuild mvr_dataset from analysis/subset.json ==="
python - analysis/subset.json <<'PY'
import json, sys
from datasets import Dataset, DatasetDict
recs = json.load(open(sys.argv[1]))
DatasetDict({"test": Dataset.from_list(recs)}).save_to_disk("mvr_dataset.tmp")
print(f"mvr_dataset rebuilt: {len(recs)} rows")
PY
rm -rf mvr_dataset && mv mvr_dataset.tmp mvr_dataset

QWEN_OUT=analysis/logs/cvbench_smoke_qwen3vl.json
if [ -z "${SKIP_QWEN:-}" ]; then
echo "=== smoke 1/2: Qwen3-VL on 3 questions ==="
rm -f "$QWEN_OUT"   # eval_thinking.py resumes from existing output; smoke must run fresh
python Video-R1/src/eval_thinking.py \
    --model_path Qwen/Qwen3-VL-8B-Thinking \
    --input_json analysis/subset.json \
    --output "$QWEN_OUT" \
    --nframes 8 --max_new_tokens 1024 --limit 3
python - "$QWEN_OUT" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))["results"]
ok = sum(1 for x in r if x.get("think") and x.get("prediction"))
print(f"qwen smoke: {len(r)} results, {ok} with non-empty think+prediction")
assert len(r) == 3 and ok >= 2, "Qwen smoke gate FAILED"
PY
else
echo "=== smoke 1/2: Qwen3-VL SKIPPED (SKIP_QWEN set; already validated) ==="
fi

echo "=== smoke 2/2: InternVL3 on 3 questions ==="
# InternVL3 remote code predates transformers 5; run this leg from the
# transformers==4.48.3 overlay venv (shares torch/decord with cvbench).
IVL_PY=$HOME/CVBench/.venv-internvl/bin/python
# lmms_eval swallows exceptions and exits 0 unless verbosity=DEBUG
( cd lmms-eval && "$IVL_PY" -m lmms_eval \
    --model internvl2 \
    --model_args "pretrained=OpenGVLab/InternVL3-8B,num_frame=8" \
    --tasks mvr_think --batch_size 1 --log_samples --limit 3 \
    --verbosity=DEBUG \
    --output_path ./logs_smoke/ )
SAMPLES=$(ls -t lmms-eval/logs_smoke/*nternVL*/*_samples_mvr_think.jsonl 2>/dev/null | head -1)
[ -n "$SAMPLES" ] || { echo "FATAL: InternVL produced no samples jsonl"; exit 1; }
python - "$SAMPLES" <<'PY'
import json, sys
lines = [json.loads(l) for l in open(sys.argv[1])]
trace = lines[0]["resps"][0][0]
print(f"internvl smoke: {len(lines)} samples, first resp {len(trace)} chars")
print(trace[:300])
assert len(lines) == 3 and len(trace) > 50, "InternVL smoke gate FAILED (no visible trace)"
PY

echo "SMOKE OK @ $(date '+%F %T'). Inspect $QWEN_OUT and $SAMPLES."
