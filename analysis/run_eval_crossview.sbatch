#!/bin/bash
### CrossView (UT Austin Multi-Camera VQA) thinking-eval — Qwen3-VL-8B-Thinking + InternVL3-8B.
### Mirrors analysis/run_eval.sbatch but points at the CrossView subset, release-root
### videos, and the lmms-eval `crossview_think` task. Kept separate from CVBench.
###
### Prereqs (run once, on a node with internet, BEFORE submitting):
###   # 1. build a MEVA-only subset with .avi paths (public MEVA ships .avi)
###   python3 analysis/convert_crossview.py --sources meva --meva-video-ext avi --n 60
###   # 2. download just this subset's MEVA videos from the open S3 bucket (no creds)
###   python3 analysis/fetch_meva_videos.py --subset analysis/crossview_subset.json
###   # (ego-exo4d/agibot/nuscenes need signed licenses; add later. The HF-repo
###   #  route in hosting/fetch_videos.py is an alternative if videos get uploaded.)

#SBATCH --job-name=crossview-think
#SBATCH --output=/home/hectorlugo02/CVBench/analysis/logs/%j.crossview_think.out
#SBATCH --error=/home/hectorlugo02/CVBench/analysis/logs/%j.crossview_think.err
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
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
export PYTORCH_ALLOC_CONF=expandable_segments:True

REPO=/home/hectorlugo02/CVBench
cd "$REPO"

QWEN_CKPT=${QWEN_CKPT:-Qwen/Qwen3-VL-8B-Thinking}
INTERNVL_CKPT=${INTERNVL_CKPT:-OpenGVLab/InternVL3-8B}
INTERNVL_ENV=${INTERNVL_ENV:-cvbench}   # conda env for the InternVL leg (NOT a python venv)
SUBSET=${SUBSET:-analysis/crossview_subset.json}
FETCH=${FETCH:-analysis/crossview_subset_fetch.json}
VIDEO_ROOT=${VIDEO_ROOT:-$REPO/crossview-release-annotations/crossview-release}
OUTDIR=${OUTDIR:-analysis/crossview_out}
LIMIT_ARG=${LIMIT_ARG:-}          # e.g. "--limit 3" for a smoke run
RUN_BLIND=${RUN_BLIND:-0}         # set 1 to also run the no-video language-prior baseline
RUN_QWEN=${RUN_QWEN:-1}           # set 0 to skip the Qwen leg (e.g. already done)
RUN_INTERNVL=${RUN_INTERNVL:-1}   # set 0 to skip the InternVL leg
FETCH_MEVA=${FETCH_MEVA:-0}       # set 1 to auto-fetch missing MEVA clips in pre-flight (public S3)
# Output paths are env-overridable so a second subset (e.g. the 1,033-Q MEVA pool)
# can run without clobbering the 60-Q results.
QOUT=${QOUT:-Video-R1/src/r1-v/eval_results/eval_crossview_subset_qwen3vl.json}
QOUT_BLIND=${QOUT_BLIND:-Video-R1/src/r1-v/eval_results/eval_crossview_subset_qwen3vl_novideo.json}
INTERNVL_OUT=${INTERNVL_OUT:-analysis/crossview_internvl3_normalized.json}
mkdir -p "$OUTDIR"

echo "RUN STARTED @ $(date '+%F %T')  | Qwen=$QWEN_CKPT  InternVL=$INTERNVL_CKPT  subset=$SUBSET $LIMIT_ARG"

if [ "$FETCH_MEVA" = "1" ]; then
  echo "=== pre-flight: auto-fetch any missing MEVA clips ($SUBSET; public S3, no creds) ==="
  python analysis/fetch_meva_videos.py --subset "$SUBSET" \
      || echo "WARN: some MEVA clips errored; the verify step below will catch hard-missing ones"
fi

echo "=== pre-flight: verify subset videos are present under $VIDEO_ROOT ==="
python hosting/fetch_videos.py --release-root "$VIDEO_ROOT" verify --qa "$FETCH" || {
    echo "FATAL: CrossView videos missing. Fetch them first (see header)."; exit 1; }

echo "=== 0/3  (re)build crossview_dataset from $SUBSET (keeps the lmms-eval leg in sync) ==="
python - "$SUBSET" <<'PY'
import json, sys
from datasets import Dataset, DatasetDict
recs = json.load(open(sys.argv[1]))
DatasetDict({"test": Dataset.from_list(recs)}).save_to_disk("crossview_dataset.tmp")
print(f"crossview_dataset rebuilt: {len(recs)} rows")
PY
rm -rf crossview_dataset && mv crossview_dataset.tmp crossview_dataset

if [ "$RUN_QWEN" = "1" ]; then
  echo "=== 1/3  Qwen3-VL thinking eval (video_root = CrossView release root) ==="
  python Video-R1/src/eval_thinking.py \
      --model_path "$QWEN_CKPT" \
      --input_json "$SUBSET" \
      --output "$QOUT" \
      --video_root "$VIDEO_ROOT" \
      --nframes 8 --max_new_tokens 8192 $LIMIT_ARG
fi

if [ "$RUN_BLIND" = "1" ]; then
    echo "=== 1b   Qwen3-VL blind (no-video) baseline ==="
    python Video-R1/src/eval_thinking.py \
        --model_path "$QWEN_CKPT" \
        --input_json "$SUBSET" \
        --output "$QOUT_BLIND" \
        --video_root "$VIDEO_ROOT" --no_video \
        --nframes 8 --max_new_tokens 8192 $LIMIT_ARG
fi

if [ "$RUN_INTERNVL" = "1" ]; then
  echo "=== 2/3  InternVL3 thinking eval (conda env: $INTERNVL_ENV; from lmms-eval/ so ./res markers resolve) ==="
  # Use a CONDA env (never a python venv). InternVL3 needs transformers<5; the
  # default cvbench has transformers 5 and FAILS (all_tied_weights_keys), so run
  # this leg in a clone:
  #   conda create -y -n internvl --clone cvbench
  #   ~/anaconda3/envs/internvl/bin/pip install 'transformers==4.48.3'
  #   then submit with: INTERNVL_ENV=internvl
  ( cd lmms-eval && conda activate "$INTERNVL_ENV" && python -m lmms_eval \
      --model internvl2 \
      --model_args "pretrained=${INTERNVL_CKPT},num_frame=8" \
      --tasks crossview_think --batch_size 1 --log_samples \
      --verbosity=DEBUG \
      --output_path ./logs/ ${LIMIT_ARG} ) \
      || echo "WARN: InternVL leg failed (transformers compat in env '$INTERNVL_ENV'?); continuing to analysis."
fi

echo "=== 3/3  analyze (over whatever result files exist) ==="
ARGS=""
[ -f "$QOUT" ] && ARGS="qwen3vl=$QOUT"
SAMPLES=$(ls -t lmms-eval/logs/*nternVL*/*_samples_crossview_think.jsonl 2>/dev/null | head -1)
if [ -n "$SAMPLES" ]; then
    python analysis/parse_lmms_samples.py --samples "$SAMPLES" \
        --out "$INTERNVL_OUT"
    ARGS="$ARGS internvl3=$INTERNVL_OUT"
fi
[ -n "$ARGS" ] || { echo "FATAL: no result files to analyze"; exit 1; }
python analysis/analyze_failures.py $ARGS --out-dir "$OUTDIR"
python analysis/plot_accuracy.py \
    --in "$OUTDIR/accuracy_by_cameras.json" \
    --out-cameras "$OUTDIR/accuracy_vs_cameras.png" \
    --out-tasks "$OUTDIR/accuracy_by_task.png" \
    --title CrossView
python analysis/crossview_camera_curve.py $ARGS --subset "$SUBSET" --out-dir "$OUTDIR"
python analysis/crossview_vs_cvbench.py \
    --cvbench analysis/accuracy_by_cameras.json \
    --crossview "$OUTDIR/accuracy_by_cameras.json" \
    --out "$OUTDIR/cvbench_vs_crossview.md"

echo "RUN DONE @ $(date '+%F %T')"
echo "See $OUTDIR/{qwen3vl,internvl3}_failures.md, accuracy_vs_orig_cameras.png, cvbench_vs_crossview.md"
