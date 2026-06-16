# CrossView: accuracy vs original number of cameras

`num_videos` is capped at 4 by the harness; this uses `orig_num_cameras` (the true synchronized-camera count, 1-16) recovered from `crossview_subset.json`.

`cap_answer_safe=false` (ego-exo4d, >4 cameras) means the cap may have dropped the answer-bearing view -- treat those as a lower bound.


## qwen3vl — overall 19/60 = 31.7%

**By original #cameras:**

| #cameras | acc | n |
|---:|---:|---:|
| 2 | 35% | 17 |
| 3 | 33% | 3 |
| 5 | 33% | 6 |
| 7 | 40% | 15 |
| 12 | 21% | 19 |

**Cap quality (answer-bearing view retained?):**

- answer-safe: 31.7% (n=60)
- answer-lossy (ego-exo4d >4 cap): 0.0% (n=0) — lower bound
- ego-exo4d safe vs lossy: 0.0% (n=0) vs 0.0% (n=0)

## internvl3 — overall 23/60 = 38.3%

**By original #cameras:**

| #cameras | acc | n |
|---:|---:|---:|
| 2 | 65% | 17 |
| 3 | 67% | 3 |
| 5 | 0% | 6 |
| 7 | 13% | 15 |
| 12 | 42% | 19 |

**Cap quality (answer-bearing view retained?):**

- answer-safe: 38.3% (n=60)
- answer-lossy (ego-exo4d >4 cap): 0.0% (n=0) — lower bound
- ego-exo4d safe vs lossy: 0.0% (n=0) vs 0.0% (n=0)