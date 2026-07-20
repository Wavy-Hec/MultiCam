#!/usr/bin/env bash
# One-command pool + report for the stitch frame-budget sweep: the centralized
# 2x2-stitch arm re-run at several per-clip frame budgets on the CVBench
# full-1000 subset (InternVL3-8B, MONTAGE_KIND=video, 4 sampled passes,
# 8-way sharded — launch lines in the README). Every leg records
# method='centralized'; only the output TAG distinguishes budgets. Pooling
# therefore renames each leg's rows to stitch<NN>_f<N> keyed by that tag, so
# the arms stay distinct in one report instead of collapsing into one method.
# Safe to run anytime (idempotent): pools whatever sweep shards exist.
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root (CVBench/)
PY="${PY:-$HOME/anaconda3/envs/cvbench/bin/python}"
R=bench/results
OUT=$R/bench_cvbench_STITCH_SWEEP_combined.jsonl

# TAG -> frames per clip. Plain 'fullstitch' is the original full-run stitch
# leg (16 frames/clip); the others were launched as TAG=_fullstitch<N> with
# NFRAMES=<N> and nothing else changed.
TAGS=(fullstitch8 fullstitch fullstitch32 fullstitch64 fullstitch128)
declare -A FRAMES=([fullstitch8]=8 [fullstitch]=16 [fullstitch32]=32 [fullstitch64]=64 [fullstitch128]=128)

shopt -s nullglob
: > "$OUT.tmp"
pooled=0
for tag in "${TAGS[@]}"; do
  n=${FRAMES[$tag]}
  shards=( "$R"/bench_cvbench_full_runnable_subset_internvl_"${tag}"_shard*.jsonl )
  if (( ${#shards[@]} == 0 )); then
    echo "SKIP $tag (f$n): no shards found"
    continue
  fi
  rows=$(cat "${shards[@]}" | wc -l)
  echo "pool  $tag (f$n): ${#shards[@]} shard file(s), $rows rows -> stitch$(printf '%02d' "$n")_f$n"
  "$PY" - "$n" "${shards[@]}" <<'PYEOF' >> "$OUT.tmp"
import json, sys
n = int(sys.argv[1])
name = f"stitch{n:02d}_f{n}"
for path in sys.argv[2:]:
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        r["method"] = name
        print(json.dumps(r))
PYEOF
  pooled=$((pooled + 1))
done
if (( pooled == 0 )); then
  echo "No sweep shards found under $R — run the SLURM legs first."; rm -f "$OUT.tmp"; exit 1
fi
mv "$OUT.tmp" "$OUT"
echo "Combined rows: $(wc -l < "$OUT") -> $OUT"

echo "=== bench.report ==="
"$PY" -m bench.report --jsonl "$OUT"

echo
echo "DONE. Artifacts:"
echo "  $OUT"
echo "  ${OUT%.jsonl}_report.md  /  _report.csv"
echo
echo "Headline:"
sed -n '/## Headline/,/## Accuracy by task_type/p' "${OUT%.jsonl}_report.md" | head -12
