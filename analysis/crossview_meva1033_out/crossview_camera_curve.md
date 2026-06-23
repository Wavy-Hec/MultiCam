# CrossView: accuracy vs original number of cameras

`num_videos` is capped at 4 by the harness; this uses `orig_num_cameras` (the true synchronized-camera count, 1-16) recovered from `crossview_subset.json`.

`cap_answer_safe=false` (ego-exo4d, >4 cameras) means the cap may have dropped the answer-bearing view -- treat those as a lower bound.


## qwen3vl — overall 331/1033 = 32.0%

**By original #cameras:**

| #cameras | acc | n |
|---:|---:|---:|
| 2 | 44% | 75 |
| 3 | 0% | 3 |
| 5 | 33% | 226 |
| 7 | 34% | 215 |
| 11 | 0% | 6 |
| 12 | 23% | 44 |
| 13 | 36% | 25 |
| 14 | 29% | 419 |
| 15 | 46% | 13 |
| 16 | 43% | 7 |

**Cap quality (answer-bearing view retained?):**

- answer-safe: 32.0% (n=1033)
- answer-lossy (ego-exo4d >4 cap): 0.0% (n=0) — lower bound
- ego-exo4d safe vs lossy: 0.0% (n=0) vs 0.0% (n=0)

## internvl3 — overall 351/1033 = 34.0%

**By original #cameras:**

| #cameras | acc | n |
|---:|---:|---:|
| 2 | 48% | 75 |
| 3 | 67% | 3 |
| 5 | 28% | 226 |
| 7 | 31% | 215 |
| 11 | 0% | 6 |
| 12 | 39% | 44 |
| 13 | 40% | 25 |
| 14 | 35% | 419 |
| 15 | 38% | 13 |
| 16 | 43% | 7 |

**Cap quality (answer-bearing view retained?):**

- answer-safe: 34.0% (n=1033)
- answer-lossy (ego-exo4d >4 cap): 0.0% (n=0) — lower bound
- ego-exo4d safe vs lossy: 0.0% (n=0) vs 0.0% (n=0)