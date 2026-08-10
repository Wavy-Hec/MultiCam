"""Render the Task-1 deliverables from a bench results JSONL:

  Table 1  overall accuracy mean+/-std (4 passes) for the 2 models x 2 harnesses
  Plot 1   accuracy per question category (grouped bar, std error bars)
  Plot 2   latency per question (box, X = methods, Y = ms)
  Plot 3   accuracy vs camera count (line, X = orig_num_cameras)
  Plot 4   accuracy per question category vs camera count (line, faceted)

Usage (from repo root, after concatenating the per-leg shards):
  python -m bench.plots --jsonl bench/results/dev_combined_qwen.jsonl \
      bench/results/dev_combined_internvl.jsonl --out-dir bench/results/figs_dev
"""
import argparse
import csv
import json
from collections import defaultdict
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import metrics  # noqa: E402

HARNESS = {"centralized": "Centralized", "per_stream": "Decentralized",
           "cvbench_native": "Native interleaved"}


def label(key):
    method, backend = key.split("/", 1)
    return f"{backend} · {HARNESS.get(method, method)}"


def load_rows(paths):
    rows = []
    for p in paths:
        with open(p) as fh:
            rows += [json.loads(l) for l in fh if l.strip()]
    return rows


def _pct(x):
    return None if x is None else 100.0 * x


def dump(out_dir, name, payload):
    """Persist the exact plotted series next to the PNG.

    Every figure writes its own numbers, so a chart can be restyled, recoloured
    or rebuilt in another tool without touching bench/results/*.jsonl — and
    without ever re-running the GPU job that produced them.
    """
    with open(os.path.join(out_dir, f"{name}.json"), "w") as f:
        json.dump(payload, f, indent=1)


def table1(by, out_dir):
    lines = ["# Table 1 — General Video QA Accuracy (mean ± std over passes)", "",
             "| Method (model · harness) | n (rows) | passes | accuracy (%) |",
             "|---|--:|--:|--:|"]
    csv_rows = []
    for key, s in by.items():
        op = s["overall_passes"]
        m, sd, npass = _pct(op["mean"]), _pct(op["std"]), op["n_passes"]
        acc = "—" if m is None else f"{m:.1f} ± {sd:.1f}"
        lines.append(f"| {label(key)} | {s['overall']['total']} | {npass} | {acc} |")
        csv_rows.append({"method": label(key), "n": s["overall"]["total"],
                         "passes": npass,
                         "acc_mean_pct": (None if m is None else round(m, 2)),
                         "acc_std_pct": (None if sd is None else round(sd, 2))})
    with open(os.path.join(out_dir, "table1.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(out_dir, "table1.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["method", "n", "passes", "acc_mean_pct", "acc_std_pct"])
        w.writeheader()
        w.writerows(csv_rows)
    dump(out_dir, "table1", {"rows": csv_rows})
    return "\n".join(lines)


def plot1_category(by, out_dir):
    cats = sorted({c for s in by.values() for c in s["by_task_type_passes"]})
    keys = list(by)
    n = len(keys)
    width = 0.8 / max(n, 1)
    fig, ax = plt.subplots(figsize=(max(7, 1.4 * len(cats) * n / 2), 5))
    for i, key in enumerate(keys):
        d = by[key]["by_task_type_passes"]
        means = [_pct(d.get(c, {}).get("mean")) or 0 for c in cats]
        stds = [_pct(d.get(c, {}).get("std")) or 0 for c in cats]
        x = [j + i * width for j in range(len(cats))]
        ax.bar(x, means, width=width, yerr=stds, capsize=3, label=label(key))
    ax.set_xticks([j + width * (n - 1) / 2 for j in range(len(cats))])
    ax.set_xticklabels(cats, rotation=15)
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("Plot 1 — Accuracy per question category")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "plot1_accuracy_by_category.png"), dpi=150)
    plt.close(fig)
    dump(out_dir, "plot1_accuracy_by_category", {
        "categories": cats,
        "series": [{"method": label(k),
                    "mean_pct": [_pct(by[k]["by_task_type_passes"].get(c, {}).get("mean")) for c in cats],
                    "std_pct": [_pct(by[k]["by_task_type_passes"].get(c, {}).get("std")) for c in cats]}
                   for k in by]})


def plot2_latency(rows, out_dir):
    g = {}
    for r in rows:
        if r.get("latency_s") is None:
            continue
        k = f'{r.get("method")}/{r.get("backend")}'
        g.setdefault(k, []).append(r["latency_s"] * 1000.0)
    keys = sorted(g)
    fig, ax = plt.subplots(figsize=(max(7, 2 * len(keys)), 5))
    ax.boxplot([g[k] for k in keys], showfliers=False)
    ax.set_xticklabels([label(k) for k in keys], rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Inference time per question (ms)")
    ax.set_title("Plot 2 — Latency per question")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "plot2_latency_per_question.png"), dpi=150)
    plt.close(fig)
    import statistics as _st
    dump(out_dir, "plot2_latency_per_question", {
        "unit": "ms",
        "series": [{"method": label(k), "n": len(g[k]),
                    "median": round(_st.median(g[k]), 1),
                    "mean": round(_st.mean(g[k]), 1),
                    "p25": round(_st.quantiles(g[k], n=4)[0], 1) if len(g[k]) > 3 else None,
                    "p75": round(_st.quantiles(g[k], n=4)[2], 1) if len(g[k]) > 3 else None}
                   for k in keys]})


def _cam_axis(d):
    cams = []
    for c in d:
        try:
            cams.append(int(c))
        except (ValueError, TypeError):
            continue
    return sorted(cams)


def plot3_cameras(by, out_dir):
    fig, ax = plt.subplots(figsize=(8, 5))
    for key in by:
        d = by[key]["by_orig_num_cameras_passes"]
        cams = _cam_axis(d)
        xs, ys, es = [], [], []
        for c in cams:
            m = _pct(d[str(c)]["mean"])
            if m is None:
                continue
            xs.append(c)
            ys.append(m)
            es.append(_pct(d[str(c)]["std"]) or 0)
        if xs:
            ax.errorbar(xs, ys, yerr=es, marker="o", capsize=3, label=label(key))
    ax.set_xlabel("Number of cameras (orig_num_cameras)")
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("Plot 3 — Accuracy vs camera count")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "plot3_accuracy_vs_cameras.png"), dpi=150)
    plt.close(fig)
    dump(out_dir, "plot3_accuracy_vs_cameras", {
        "x_field": "orig_num_cameras",
        "series": [{"method": label(k),
                    "cameras": _cam_axis(by[k]["by_orig_num_cameras_passes"]),
                    "mean_pct": [_pct(by[k]["by_orig_num_cameras_passes"][str(c)]["mean"])
                                 for c in _cam_axis(by[k]["by_orig_num_cameras_passes"])],
                    "std_pct": [_pct(by[k]["by_orig_num_cameras_passes"][str(c)]["std"])
                                for c in _cam_axis(by[k]["by_orig_num_cameras_passes"])]}
                   for k in by]})


def plot4_category_cameras(by, out_dir):
    cats = sorted({c for s in by.values() for c in s["by_task_camera_passes"]})
    if not cats:
        return
    fig, axes = plt.subplots(1, len(cats), figsize=(5 * len(cats), 4.5), squeeze=False)
    for ci, cat in enumerate(cats):
        ax = axes[0][ci]
        for key in by:
            d = by[key]["by_task_camera_passes"].get(cat, {})
            cams = _cam_axis(d)
            xs, ys = [], []
            for c in cams:
                m = _pct(d[str(c)]["mean"])
                if m is None:
                    continue
                xs.append(c)
                ys.append(m)
            if xs:
                ax.plot(xs, ys, marker="o", label=label(key))
        ax.set_title(cat)
        ax.set_xlabel("Number of cameras")
        ax.set_ylabel("Accuracy (%)")
        ax.grid(alpha=0.3)
        if ci == len(cats) - 1:
            ax.legend(fontsize=7)
    fig.suptitle("Plot 4 — Accuracy per question category vs camera count")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "plot4_category_vs_cameras.png"), dpi=150)
    plt.close(fig)
    dump(out_dir, "plot4_category_vs_cameras", {
        "categories": cats,
        "series": [{"method": label(k), "category": cat,
                    "cameras": _cam_axis(by[k]["by_task_camera_passes"].get(cat, {})),
                    "mean_pct": [_pct(by[k]["by_task_camera_passes"][cat][str(c)]["mean"])
                                 for c in _cam_axis(by[k]["by_task_camera_passes"].get(cat, {}))]}
                   for cat in cats for k in by]})


def intersect_cells(rows, strict=True):
    """Restrict every arm to the (id, pass_idx) cells ALL arms of that backend
    completed.

    Without this, a leg that died to walltime is compared against a complete one
    and the winner can flip: on the All-Angles Qwen leg, per_stream covered 292
    of 680 cells and read +3.09 over native, when on the 292 they share it is
    -4.45. Table 1 printed the row count but nothing reconciled it, so the sign
    error was invisible.
    """
    cells = defaultdict(lambda: defaultdict(set))
    for r in rows:
        cells[r.get("backend")][r["method"]].add((r["id"], r.get("pass_idx")))
    keep, dropped = {}, []
    for backend, per_method in cells.items():
        common = set.intersection(*per_method.values()) if per_method else set()
        keep[backend] = common
        for method, got in sorted(per_method.items()):
            if len(got) > len(common):
                dropped.append(f"  {backend} · {method}: {len(got)} cells -> "
                               f"{len(common)} shared ({len(got) - len(common)} dropped)")
    if dropped:
        print("Table 1 restricted to cells all arms completed:")
        print("\n".join(dropped))
        if strict:
            print("  (pass --no-strict-cells to report arms on their own row sets)")
    return [r for r in rows if (r["id"], r.get("pass_idx")) in keep.get(r.get("backend"), set())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", nargs="+", required=True, help="one or more results JSONL")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-strict-cells", action="store_true",
                    help="do NOT restrict arms to their shared (id, pass) cells "
                         "— only for inspecting an incomplete leg")
    args = ap.parse_args()
    rows = load_rows(args.jsonl)
    if not args.no_strict_cells:
        rows = intersect_cells(rows)
    out_dir = args.out_dir or os.path.join(os.path.dirname(args.jsonl[0]), "figs")
    os.makedirs(out_dir, exist_ok=True)
    by = metrics.summarize_by_method_backend_passes(rows)
    print(table1(by, out_dir))
    plot1_category(by, out_dir)
    plot2_latency(rows, out_dir)
    plot3_cameras(by, out_dir)
    plot4_category_cameras(by, out_dir)
    print(f"\nwrote Table 1 + Plots 1-4 -> {out_dir}")


if __name__ == "__main__":
    main()
