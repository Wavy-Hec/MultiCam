#!/usr/bin/env python3
"""'How much the answer needs the video' chart: with-video vs text-only (blind)
accuracy by #clips, with a PER-GROUP random-chance baseline.

The gap (with-video minus text-only) is the slice of accuracy that REQUIRES
seeing the video. It is small on easy 2-clip questions and large (~30 pts) on
harder 3-4 clip questions. (Whether the model *reasons* over that content is a
separate question, answered by the think-trace failure analysis.)

Run:  ~/anaconda3/envs/cvbench/bin/python analysis/make_reasoning_gain.py
Out:  analysis/reasoning_gain.png
"""
import json
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BASE = "Video-R1/src/r1-v/eval_results/"


def stats(path):
    d = json.load(open(path))
    res = d["results"] if isinstance(d, dict) and "results" in d else d
    c, t, ch = defaultdict(int), defaultdict(int), defaultdict(list)
    for r in res:
        nv = r.get("num_videos") or sum(1 for i in range(1, 5) if r.get(f"video_{i}"))
        t[nv] += 1
        c[nv] += 1 if r.get("correct") else 0
        opts = r["options"]
        yn = all(o.strip().strip(".").lower() in ("yes", "no") for o in opts)
        ch[nv].append(0.5 if yn else 1.0 / len(opts))
    acc = {k: 100 * c[k] / t[k] for k in sorted(t)}
    chance = {k: 100 * sum(ch[k]) / len(ch[k]) for k in sorted(t)}
    return acc, {k: t[k] for k in sorted(t)}, chance


vid, n, chance = stats(BASE + "eval_subset_qwen3vl.json")
blind, _, _ = stats(BASE + "eval_subset_qwen3vl_novideo.json")
xs = sorted(vid)
v = [vid[k] for k in xs]
b = [blind[k] for k in xs]

fig, ax = plt.subplots(figsize=(8.4, 5.0), dpi=150)
x = np.arange(len(xs))
w = 0.36
bars_b = ax.bar(x - w / 2, b, w, label="Text-only (no video)", color="#9aa3ad")
bars_v = ax.bar(x + w / 2, v, w, label="With video", color="#1f77b4")

# per-group random-chance baseline (dashed segment over each group)
for i, k in enumerate(xs):
    ax.plot([x[i] - 0.46, x[i] + 0.46], [chance[k], chance[k]], ls="--", lw=1.4, color="#c0392b")
ax.plot([], [], ls="--", color="#c0392b", label="random chance (per group)")

for i, k in enumerate(xs):
    gain = v[i] - b[i]
    ax.annotate(f"+{gain:.0f} pts", (x[i], max(v[i], b[i]) + 4), ha="center",
                fontsize=13, fontweight="bold", color="#1e7e34")
for bars in (bars_b, bars_v):
    for r in bars:
        ax.text(r.get_x() + r.get_width() / 2, r.get_height() - 5,
                f"{r.get_height():.0f}%", ha="center", color="white", fontsize=10, fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels([f"{k} clips\n(n={n[k]})" for k in xs])
ax.set_ylabel("Accuracy (%)")
ax.set_ylim(0, 100)
ax.set_title("How much the answer needs the video — Qwen3-VL, CVBench\n"
             "gap (green) = accuracy that requires seeing the video; it jumps on harder, multi-clip questions",
             fontsize=10.5)
ax.legend(loc="upper left", fontsize=9.5)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig("analysis/reasoning_gain.png")
print("wrote analysis/reasoning_gain.png | video", [round(x) for x in v],
      "| blind", [round(x) for x in b], "| chance", {k: round(c) for k, c in chance.items()})
