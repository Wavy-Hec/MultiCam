"""Re-render the Task-1 figures from the JSON series bench/plots.py dumps.

bench/plots.py deliberately writes every figure's plotted numbers to a sibling
JSON so charts can be restyled without touching the raw shards or the GPU. This
script is that path: it reads plot{1,3,4}_*.json + plot2_*.json and re-renders
with a consistent, larger-type style — harness carried by hue (3 hues), backend
by line/fill style — writing *_v2.png next to the originals. The originals are
untouched; nothing here reads bench/results/*.jsonl.

    python3 analysis/restyle_task1_figs.py            # all figs_task1_* dirs
    python3 analysis/restyle_task1_figs.py --dirs bench/results/figs_task1_mvueval_qa
"""
import argparse
import glob
import json
import os
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# palette: first three slots of the validated categorical set (all-pairs safe)
HUES = {"Centralized": "#2a78d6", "Sequential": "#1baf7a", "Decentralized": "#eb6834"}
HARNESS_ORDER = ["Centralized", "Sequential", "Decentralized"]
INK, INK2, GRID, SPINE, SURFACE = "#0b0b0b", "#52514e", "#e6e5e2", "#b9b7b2", "#fcfcfb"
DPI = 170

POOL_TITLES = {
    "crossview_meva_cap13": "CrossView-MEVA",
    "crossview_egoexo500": "CrossView-EgoExo",
    "allangles_qa": "All-Angles-Bench",
    "mvueval_qa": "MVU-Eval",
}

plt.rcParams.update({
    "font.size": 12, "axes.titlesize": 15, "axes.labelsize": 12.5,
    "xtick.labelsize": 11, "ytick.labelsize": 11, "legend.fontsize": 11,
    "axes.edgecolor": SPINE, "axes.linewidth": 1.0,
    "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})


def split_method(m):
    backend, harness = [s.strip() for s in m.split("·")]
    if harness == "Native interleaved":
        harness = "Sequential"
    backend = "InternVL3" if "InternVL" in backend else "Qwen2.5"
    return backend, harness


def series_key(m):
    b, h = split_method(m)
    return (HARNESS_ORDER.index(h), 0 if b == "InternVL3" else 1)


def strip_prefix(cats):
    """Drop the shared 'Pool-Name-' prefix so category labels carry only signal."""
    if len(cats) == 1:
        return [cats[0].rsplit("-", 1)[-1]]
    pre = os.path.commonprefix(cats)
    cut = pre.rfind("-") + 1
    return [c[cut:] if cut else c for c in cats]


def style_axis(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def legend_handles():
    hs = [Patch(facecolor=HUES[h], label=h) for h in HARNESS_ORDER]
    hs.append(Line2D([], [], color=INK2, linewidth=2.2, label="InternVL3-8B (solid)"))
    hs.append(Line2D([], [], color=INK2, linewidth=2.2, linestyle=(0, (4.5, 2.5)),
                     label="Qwen2.5-VL-7B (dashed)"))
    return hs


def bar_legend_handles():
    hs = [Patch(facecolor=HUES[h], label=h) for h in HARNESS_ORDER]
    hs.append(Patch(facecolor=INK2, label="InternVL3-8B (solid)"))
    hs.append(Patch(facecolor=INK2, alpha=0.4, edgecolor=INK2, linewidth=1.3,
                    label="Qwen2.5-VL-7B (tinted)"))
    return hs


def head(fig, title, pool_title, sub_y=0.905):
    fig.suptitle(title, x=0.06, y=0.975, ha="left", fontsize=15.5,
                 fontweight="bold", color=INK)
    fig.text(0.06, sub_y, f"{pool_title} · reasoning off · temp 0.1 · 4 passes · error bars = ±std",
             ha="left", fontsize=11.5, color=INK2)


def plot1(d, out, pool_title):
    cats = strip_prefix(d["categories"])
    series = sorted(d["series"], key=lambda s: series_key(s["method"]))
    n = len(cats)
    fig_w = max(9.5, 1.0 + 1.75 * n)
    fig, ax = plt.subplots(figsize=(fig_w, 5.6))
    group_w, bar_gap = 0.76, 0.012
    bw = group_w / 6
    for j, s in enumerate(series):
        b, h = split_method(s["method"])
        xs = [i - group_w / 2 + j * bw + bw / 2 + (bar_gap if j % 2 else 0) for i in range(n)]
        kw = dict(color=HUES[h], width=bw - bar_gap, zorder=3)
        if b == "Qwen2.5":
            kw.update(alpha=0.42, edgecolor=HUES[h], linewidth=1.3)
        ax.bar(xs, s["mean_pct"], yerr=s.get("std_pct"), error_kw=dict(
            ecolor=INK2, elinewidth=1.0, capsize=0, zorder=4), **kw)
    ax.set_xticks(range(n))
    ax.set_xticklabels(["\n".join(textwrap.wrap(c.replace("-", " "), 16)) for c in cats])
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, min(100, max(max(s["mean_pct"]) for s in series) * 1.22))
    style_axis(ax)
    ax.legend(handles=bar_legend_handles(), ncol=3, frameon=False, loc="upper left",
              bbox_to_anchor=(0, 1.02), columnspacing=1.4, handlelength=1.4)
    head(fig, "Plot 1 — Accuracy by question category", pool_title)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def plot2(d, out, pool_title):
    series = sorted(d["series"], key=lambda s: series_key(s["method"]))
    fig, ax = plt.subplots(figsize=(11.5, 4.8))
    rows, ticks, labels = [], [], []
    y = 0
    for j, s in enumerate(series):
        b, h = split_method(s["method"])
        if j and j % 2 == 0:
            y -= 0.55  # gap between harness groups
        rows.append((y, s, b, h))
        ticks.append(y)
        labels.append(f"{h} — {b}")
        y -= 1
    p75s = [s["p75"] for s in d["series"]]
    p25s = [s["p25"] for s in d["series"]]
    use_log = max(p75s) / max(min(p25s), 1) > 15
    for y0, s, b, h in rows:
        kw = dict(color=HUES[h], height=0.62, zorder=3)
        if b == "Qwen2.5":
            kw.update(alpha=0.42, edgecolor=HUES[h], linewidth=1.3)
        ax.barh(y0, (s["p75"] - s["p25"]) / 1000, left=s["p25"] / 1000, **kw)
        ax.plot([s["median"] / 1000] * 2, [y0 - 0.31, y0 + 0.31],
                color=INK, linewidth=2.2, zorder=5)
        ax.plot(s["mean"] / 1000, y0, "o", color=INK2, markersize=5, zorder=5)
        ax.annotate(f'{s["median"]/1000:.1f} s', (s["p75"] / 1000, y0),
                    xytext=(7, 0), textcoords="offset points", va="center",
                    fontsize=10.5, color=INK2)
    if use_log:
        ax.set_xscale("log")
        lo, hi = min(p25s) / 1000, max(p75s) / 1000
        ticks_s = [t for t in (0.2, 0.5, 1, 2, 5, 10, 20, 40, 80) if lo * 0.7 <= t <= hi * 1.5]
        ax.set_xticks(ticks_s)
        ax.set_xticklabels([f"{t:g}" for t in ticks_s])
        ax.minorticks_off()
    ax.set_yticks(ticks)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Per-question inference time (s)" + (" — log scale" if use_log else ""))
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(left=False)
    head(fig, "Plot 2 — Latency per question (p25–p75, │ median, ● mean)", pool_title)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def line_style(b, h):
    kw = dict(color=HUES[h], linewidth=2.4, markersize=7, marker="o")
    if b == "Qwen2.5":
        kw.update(linestyle=(0, (4.5, 2.5)), markerfacecolor=SURFACE,
                  markeredgecolor=HUES[h], markeredgewidth=1.8)
    return kw


def plot3(d, out, pool_title):
    series = sorted(d["series"], key=lambda s: series_key(s["method"]))
    fig, ax = plt.subplots(figsize=(11.5, 6.0))
    cams = sorted({c for s in series for c in s["cameras"]})
    for s in series:
        b, h = split_method(s["method"])
        ax.errorbar(s["cameras"], s["mean_pct"], yerr=s.get("std_pct"),
                    ecolor=INK2, elinewidth=1.0, capsize=0, zorder=3,
                    **line_style(b, h))
    ax.set_xticks(cams)
    ax.set_xlabel(f'Number of cameras ({d.get("x_field", "cameras")})')
    ax.set_ylabel("Accuracy (%)")
    style_axis(ax)
    ax.legend(handles=legend_handles(), ncol=3, frameon=False, loc="upper left",
              bbox_to_anchor=(0, 1.02), columnspacing=1.4, handlelength=1.9)
    head(fig, "Plot 3 — Accuracy vs camera count", pool_title)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def plot4(d, out, pool_title):
    cats = d["categories"]
    short = dict(zip(cats, strip_prefix(cats)))
    ncol = min(3, len(cats))
    nrow = (len(cats) + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(4.3 * ncol + 1.2, 3.6 * nrow + 1.3),
                             sharey=True, squeeze=False)
    by_cat = {}
    for s in d["series"]:
        by_cat.setdefault(s["category"], []).append(s)
    for i, cat in enumerate(cats):
        ax = axes[i // ncol][i % ncol]
        for s in sorted(by_cat.get(cat, []), key=lambda s: series_key(s["method"])):
            b, h = split_method(s["method"])
            kw = line_style(b, h)
            kw.update(markersize=5, linewidth=2.0)
            ax.plot(s["cameras"], s["mean_pct"], **kw)
        ax.set_title(short[cat].replace("-", " "), fontsize=12.5, color=INK)
        cams = sorted({c for s in by_cat.get(cat, []) for c in s["cameras"]})
        ax.set_xticks(cams)
        style_axis(ax)
    for i in range(len(cats), nrow * ncol):
        axes[i // ncol][i % ncol].axis("off")
    for r in range(nrow):
        axes[r][0].set_ylabel("Accuracy (%)")
    fig.suptitle("Plot 4 — Accuracy by category vs camera count", x=0.06, y=0.988,
                 ha="left", fontsize=15.5, fontweight="bold", color=INK)
    fig.text(0.06, 0.958, f"{pool_title} · reasoning off · temp 0.1 · 4 passes · ±std omitted per facet (see JSON)",
             ha="left", fontsize=11.5, color=INK2)
    fig.legend(handles=legend_handles(), ncol=5, frameon=False,
               loc="upper left", bbox_to_anchor=(0.055, 0.952), columnspacing=1.3,
               handlelength=1.8)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dirs", nargs="+",
                    default=sorted(glob.glob(os.path.join(REPO, "bench/results/figs_task1_*"))))
    args = ap.parse_args()
    renders = {"plot1_accuracy_by_category": plot1, "plot2_latency_per_question": plot2,
               "plot3_accuracy_vs_cameras": plot3, "plot4_category_vs_cameras": plot4}
    for d in args.dirs:
        pool = os.path.basename(d).replace("figs_task1_", "")
        title = POOL_TITLES.get(pool, pool)
        for stem, fn in renders.items():
            src = os.path.join(d, f"{stem}.json")
            if not os.path.exists(src):
                continue
            out = os.path.join(d, f"{stem}_v2.png")
            fn(json.load(open(src)), out, title)
            print("wrote", out)


if __name__ == "__main__":
    main()
