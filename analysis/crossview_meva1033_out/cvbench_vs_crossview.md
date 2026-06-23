# CVBench vs CrossView — baseline comparison

Separate benchmarks (CVBench = 1–4 *unrelated* clips, association; CrossView = synchronized multi-cam, capped to ≤4 views here), shown side-by-side. CrossView numbers are this run's MCQ subset (temporal / event_ordering / spatial).

## Overall accuracy

| model | CVBench | CrossView |
|---|---:|---:|
| internvl3 | 55.6% (25/45) | 34.0% (351/1033) |
| qwen3vl | 62.2% (28/45) | 32.0% (331/1033) |
| qwen3vl_blind | 40.0% (18/45) | — |

## Accuracy by num_videos the model saw (1–4)


**internvl3**

| #videos | CVBench | CrossView |
|---:|---:|---:|
| 2 | 40.0% (n=15) | 48.0% (n=75) |
| 3 | 62.5% (n=16) | 66.7% (n=3) |
| 4 | 64.3% (n=14) | 32.8% (n=955) |

**qwen3vl**

| #videos | CVBench | CrossView |
|---:|---:|---:|
| 2 | 53.3% (n=15) | 44.0% (n=75) |
| 3 | 68.8% (n=16) | 0.0% (n=3) |
| 4 | 64.3% (n=14) | 31.2% (n=955) |

**qwen3vl_blind**

| #videos | CVBench | CrossView |
|---:|---:|---:|
| 2 | 46.7% (n=15) | — |
| 3 | 37.5% (n=16) | — |
| 4 | 35.7% (n=14) | — |
