#!/usr/bin/env bash
# One-command finalize for the CVBench full-1000 3-way run.
# Safe to run anytime (idempotent): pools whatever full-run shards exist, then
# renders the report + comparison figures. Run it yourself after the SLURM jobs
# finish, or let Claude run it on auto-finalize — either way produces the same
# artifacts. Arms are discriminated by the `method` field in the rows
# (temporal_weighted / temporal_even / centralized), so the stitch arm's output
# filename does not need to be known ahead of time.
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root (CVBench/)
PY="${PY:-$HOME/anaconda3/envs/cvbench/bin/python}"
R=bench/results
ALL=$R/bench_cvbench_full_runnable_subset_internvl_ALL.jsonl
FIGS=$R/figs_temporal_full

shopt -s nullglob
shards=( $R/bench_cvbench_full_runnable_subset_internvl_*_shard*.jsonl )
if (( ${#shards[@]} == 0 )); then
  echo "No full-run shards found yet under $R — run the SLURM jobs first."; exit 1
fi
echo "Pooling ${#shards[@]} shard file(s) -> $ALL"
cat "${shards[@]}" > "$ALL"
echo "Combined rows: $(wc -l < "$ALL")"

echo "=== rows by method (expect ~equal across 3 arms when complete) ==="
"$PY" - "$ALL" <<'PYEOF'
import json,sys,collections
c=collections.Counter(); q=collections.defaultdict(set)
for l in open(sys.argv[1]):
    if l.strip():
        r=json.loads(l); c[r['method']]+=1; q[r['method']].add(r['id'])
for k in sorted(c): print(f"  {k:18s}: {c[k]:5d} rows  ({len(q[k])} unique Q)")
PYEOF

echo "=== bench.report ==="
"$PY" -m bench.report --jsonl "$ALL"

echo "=== figures ==="
"$PY" bench/cvbench_temporal_figs.py --jsonl "$ALL" --out-dir "$FIGS"

echo
echo "DONE. Artifacts:"
echo "  $ALL"
echo "  ${ALL%.jsonl}_report.md  /  _report.csv"
echo "  $FIGS/{acc_by_method,acc_by_numclips,acc_by_task}.png"
echo
echo "Headline + per-#clips (paste into analysis/cvbench_temporal_method.md §7):"
sed -n '/## Headline/,/## Accuracy by task_type/p' "${ALL%.jsonl}_report.md" | head -12
sed -n '/## Accuracy by orig_num_cameras/,$p' "${ALL%.jsonl}_report.md"
