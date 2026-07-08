"""Head-to-head figure: does spatial stitching help on MEVA (synchronized cameras)
vs CVBench (independent cross-videos)? Writes bench/results/figs_exp64/headtohead.png.

Run from repo root:  python -m bench.cvbench_make_figs
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
OUT = os.path.join(RES, "figs_exp64", "headtohead.png")

NATIVE, CAMERA, VIDEO = "#7f7f7f", "#1f77b4", "#2ca02c"

# All numbers computed from the jsonl so the figure can't drift from the data.
P_MEVA = os.path.join(RES, "exp64_internvl.jsonl")              # MEVA: native + centralized
P_CNAT = os.path.join(RES, "cvbench_temporal_native.jsonl")
P_CCAM = os.path.join(RES, "cvbench_temporal_stitch.jsonl")              # Camera-labeled
P_CVID = os.path.join(RES, "cvbench_temporal_stitch_videolabels.jsonl")  # Video-labeled (corrected)


def _acc(rows):
    rows = list(rows)
    return 100 * sum(1 for r in rows if r.get("correct")) / len(rows) if rows else float("nan")


def _load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def main():
    meva = _load(P_MEVA)
    m_nat = _acc(r for r in meva if r["method"] == "cvbench_native")
    m_cam = _acc(r for r in meva if r["method"] == "centralized")
    c_nat, c_cam, c_vid = _acc(_load(P_CNAT)), _acc(_load(P_CCAM)), _acc(_load(P_CVID))

    groups = ["MEVA\n(4 synchronized cameras,\none scene)", "CVBench\n(2-4 independent clips,\ndifferent scenes)"]
    native_v = [m_nat, c_nat]
    camera_v = [m_cam, c_cam]
    video_v = [float("nan"), c_vid]   # MEVA has no Video-labeled run (its cameras ARE synced)
    x = range(len(groups))
    w = 0.27
    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    bar_groups = [
        ax.bar([i - w for i in x], native_v, w, label="CVBench-native (sequential clips)", color=NATIVE),
        ax.bar([i for i in x], camera_v, w, label="Stitch — Camera-labeled", color=CAMERA),
        ax.bar([i + w for i in x], video_v, w, label="Stitch — Video-labeled (corrected)", color=VIDEO),
    ]
    ax.axhline(25, ls="--", color="red", alpha=0.5)
    ax.text(len(groups) - 0.7, 26, "chance ~25%", color="red", fontsize=9)
    for grp in bar_groups:
        for r in grp:
            h = r.get_height()
            if h == h:  # skip nan
                ax.text(r.get_x() + r.get_width() / 2, h + 0.7,
                        f"{h:.1f}%", ha="center", fontsize=9, weight="bold")
    ax.text(0 + w, 2.0, "n/a\n(synced)", ha="center", va="bottom", fontsize=8, color="#999")
    ax.annotate(f"stitch +{m_cam-m_nat:.0f}", (0, m_cam + 3.0), ha="center", color=CAMERA, fontsize=10, weight="bold")
    ax.annotate(f"stitch +{c_vid-c_nat:.1f}", (1 + w, c_vid + 3.0), ha="center", color=VIDEO, fontsize=10, weight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(groups)
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 70)
    ax.set_title("Stitching wins on both datasets — with the truthful montage label\n"
                 "Camera for MEVA's synced views, Video for CVBench's independent clips (InternVL3-8B)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT, dpi=150)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
