# bench/legacy

Retired entry points with zero referrers elsewhere in the repo. Kept for
provenance, not maintained — do not wire new code to them.

| File | Introduced | Era |
|---|---|---|
| `report.py` | `3581017` (2026-06-23) | initial JSONL-to-markdown/CSV report, from the first centralized/decentralized harness build (`b2e0d38`) |
| `exp64_make_figs.py` | `7a5cc1a` (2026-06-27) | exp64 native-vs-stitching figures + reasoning-trace capture |
| `how_it_works_fig.py` | `7a5cc1a` (2026-06-27) | exp64 native-vs-stitching figures + reasoning-trace capture |
| `qual_make_figs.py` | `7a5cc1a` (2026-06-27) | exp64 native-vs-stitching figures + reasoning-trace capture; hard-wired to the retired CrossView/exp64 setup (see `bench/make_input_examples.py` for the era-2 sibling) |
| `capture_trace.py` | `7a5cc1a` (2026-06-27), last touched `2e66e57` (2026-07-27) | exp64 trace capture, later extended for still-image multi-view records |

Run as `python -m bench.legacy.<name>`.
