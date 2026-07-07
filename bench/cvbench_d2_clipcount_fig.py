"""D2 deliverable: accuracy as a function of CLIP COUNT (K), stitch vs non-stitch,
on the full-1000 CVBench run (InternVL3-8B, 4 passes, 64-frame budget).

Non-stitch = temporal_weighted / temporal_even (clips shown sequentially).
Stitch     = centralized (2x2 spatial montage of synchronized views).

Emits a markdown table (stdout) + a grouped bar chart with per-pass error bars.
"""
import json, collections, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(REPO, "bench/results/bench_cvbench_full_runnable_subset_internvl_ALL.jsonl")
OUT_PNG = os.path.join(REPO, "analysis/d2_acc_by_clipcount.png")

METHODS = [("temporal_weighted", "non-stitch (duration)"),
           ("temporal_even",     "non-stitch (even)"),
           ("centralized",       "stitch (2x2)")]
KS = [2, 3, 4]

# correct[(method,K,pass)] = (n_correct, n_total); questions[(method,K)] = set(ids)
cell = collections.defaultdict(lambda: [0, 0])
qids = collections.defaultdict(set)
for line in open(F):
    if not line.strip():
        continue
    r = json.loads(line)
    m, k, p = r["method"], r.get("num_videos"), r.get("pass_idx")
    if m not in dict(METHODS) or k not in KS:
        continue
    c = cell[(m, k, p)]
    c[1] += 1
    c[0] += 1 if r.get("correct") else 0
    qids[(m, k)].add(r["id"])


def mean_std(m, k):
    """per-pass accuracies -> (mean%, std%) over the 4 passes."""
    accs = [c[0] / c[1] for (mm, kk, p), c in cell.items() if mm == m and kk == k and c[1]]
    a = np.array(accs) * 100.0
    return a.mean(), a.std()


# ---- markdown table ----
print("\n### D2 — accuracy by clip count K (full-1000, InternVL3-8B, mean±std over 4 passes)\n")
hdr = "| method | " + " | ".join(f"K={k} (n={len(qids[(METHODS[0][0],k)])})" for k in KS) + " | all |"
print(hdr)
print("|" + "---|" * (len(KS) + 2))
overall = {}
for m, label in METHODS:
    tot_c = sum(cell[(m, k, p)][0] for k in KS for p in (1, 2, 3, 4))
    tot_n = sum(cell[(m, k, p)][1] for k in KS for p in (1, 2, 3, 4))
    overall[m] = 100 * tot_c / tot_n
    cells = " | ".join(f"{mean_std(m,k)[0]:.1f} ± {mean_std(m,k)[1]:.1f}" for k in KS)
    print(f"| {label} | {cells} | **{overall[m]:.1f}** |")

# Δ non-stitch(best) − stitch, per K -> does stitch lose more as K grows?
print("\n**Δ (best non-stitch − stitch), by K:**")
for k in KS:
    best_ns = max(mean_std("temporal_weighted", k)[0], mean_std("temporal_even", k)[0])
    st = mean_std("centralized", k)[0]
    print(f"  K={k}: {best_ns - st:+.1f} pts")

# ---- grouped bar chart ----
x = np.arange(len(KS)); w = 0.26
colors = ["#2c7fb8", "#7fcdbb", "#d95f0e"]
fig, ax = plt.subplots(figsize=(8, 5))
for i, (m, label) in enumerate(METHODS):
    means = [mean_std(m, k)[0] for k in KS]
    stds = [mean_std(m, k)[1] for k in KS]
    bars = ax.bar(x + (i - 1) * w, means, w, yerr=stds, capsize=3,
                  label=label, color=colors[i])
    for b, mv in zip(bars, means):
        ax.text(b.get_x() + b.get_width() / 2, mv + 0.6, f"{mv:.1f}",
                ha="center", va="bottom", fontsize=8)
ax.set_xticks(x)
ax.set_xticklabels([f"K={k}\n(n={len(qids[('temporal_weighted',k)])})" for k in KS])
ax.set_ylabel("Accuracy (%)")
ax.set_title("CVBench (full-1000, InternVL3-8B): accuracy by clip count\nstitch vs non-stitch, 64-frame budget, mean±std over 4 passes")
ax.set_ylim(40, 75)
ax.legend(loc="upper right", fontsize=9)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(OUT_PNG, dpi=150)
print(f"\nfigure -> {OUT_PNG}")
