#!/usr/bin/env python3
"""InternVL3-only CrossView charts for the deck.

Qwen's CrossView run is invalid (truncation + scorer-default artifact), so the
deck shows ONLY the trustworthy InternVL3 series — no bars we then tell the
viewer to ignore. Regenerate the full two-model charts in crossview_out/ after
the Qwen re-run.

Run:  ~/anaconda3/envs/cvbench/bin/python analysis/make_crossview_internvl_charts.py
"""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OC = json.load(open("analysis/crossview_out/accuracy_by_orig_cameras.json"))
iv = OC["by_orig_cameras"]["internvl3"]
cams = sorted(int(k) for k in iv)
acc = [iv[str(k)]["acc"] for k in cams]
nn = [iv[str(k)]["total"] for k in cams]

fig, ax = plt.subplots(figsize=(8.4, 5.0), dpi=150)
ax.plot(cams, acc, "-o", color="#ff7f0e", lw=2.4, ms=8)
for c, a, m in zip(cams, acc, nn):
    ax.annotate(f"{a:.0f}%\n(n={m})", (c, a), textcoords="offset points", xytext=(0, 10),
                ha="center", fontsize=9)
ax.set_xlabel("Original number of synchronized cameras")
ax.set_ylabel("Accuracy (%)")
ax.set_ylim(0, 100)
ax.set_title("CrossView: InternVL3 accuracy drops as more cameras are involved\n"
             "(65% at 2 cameras → 0% at 5; noisy at high counts, small n)", fontsize=10.5)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("analysis/crossview_out/accuracy_vs_orig_cameras_internvl3.png")

# by task type
BT = json.load(open("analysis/crossview_out/accuracy_by_cameras.json"))["by_task_type"]["internvl3"]
order = ["CrossView-MEVA-Temporal", "CrossView-MEVA-Event-Ordering", "CrossView-MEVA-Spatial"]
labels = ["Temporal\n(when did it happen?)", "Event-Ordering\n(put events in order)", "Spatial\n(where / which view?)"]
vals = [BT[k]["acc"] for k in order]
fig, ax = plt.subplots(figsize=(8.4, 5.0), dpi=150)
bars = ax.bar(np.arange(len(order)), vals, 0.55, color="#ff7f0e")
for r in bars:
    ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 1.5, f"{r.get_height():.0f}%",
            ha="center", fontsize=11, fontweight="bold")
ax.set_xticks(np.arange(len(order)))
ax.set_xticklabels(labels, fontsize=10)
ax.set_ylabel("Accuracy (%)")
ax.set_ylim(0, 100)
ax.set_title("CrossView: InternVL3 accuracy by question type (20 each)", fontsize=11)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig("analysis/crossview_out/accuracy_by_task_internvl3.png")
print("wrote accuracy_vs_orig_cameras_internvl3.png + accuracy_by_task_internvl3.png")
