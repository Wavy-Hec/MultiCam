#!/bin/bash
# One-time env setup for the CVBench thinking-eval. Run on the LOGIN node (internet).
#
# The user's `vlm` conda env already has a GPU-ready stack (torch 2.10+cu128,
# transformers 5.2, qwen_vl_utils, accelerate, timm, av, matplotlib). It is only
# missing `decord` (InternVL video reader) and `lmms_eval`. To avoid disturbing the
# working `vlm` env, we CLONE it to `cvbench` and add the two packages there.
#
#   bash analysis/setup_env.sh
set -euo pipefail

SRC_ENV=${SRC_ENV:-vlm}
ENV_NAME=${ENV_NAME:-cvbench}
source "$(conda info --base)/etc/profile.d/conda.sh"

if conda env list | grep -qE "^${ENV_NAME}\s"; then
    echo "env '$ENV_NAME' already exists; reusing."
else
    echo "cloning $SRC_ENV -> $ENV_NAME ..."
    conda create -y -n "$ENV_NAME" --clone "$SRC_ENV"
fi

conda activate "$ENV_NAME"
python -m pip install --upgrade pip

# decord for InternVL's video reader; remotezip for subset video fetch.
python -m pip install decord remotezip

# lmms-eval (registers the mvr / mvr_think tasks + internvl2 wrapper).
# Cloned env already satisfies most deps; install editable so our task edits apply.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python -m pip install -e "${REPO_ROOT}/lmms-eval"

python - <<'PY'
import importlib
for m in ("torch","transformers","qwen_vl_utils","decord","lmms_eval","accelerate"):
    try:
        importlib.import_module(m); print(f"  ok  {m}")
    except Exception as e:
        print(f"  ?? {m}: {e}")
PY
echo "env '$ENV_NAME' ready."
