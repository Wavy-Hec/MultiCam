"""Render a clean 'how the two methods work' schematic for the exp64 report.

Replaces the hard-to-read ASCII pipeline diagrams with one rendered figure:
  bench/results/figs_exp64/how_it_works.png

Run from repo root:  python -m bench.how_it_works_fig
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrow

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results", "figs_exp64", "how_it_works.png")

NATIVE = "#7f7f7f"
STITCH = "#1f77b4"
INK = "#222222"


def box(ax, x, y, w, h, text, fc="white", ec=INK, fs=11, weight="normal", tc=INK):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006,rounding_size=0.012",
                                fc=fc, ec=ec, lw=1.4))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, weight=weight, color=tc, wrap=True)


def arrow(ax, x0, y0, x1, y1, color=INK):
    ax.add_patch(FancyArrow(x0, y0, x1 - x0, y1 - y0, width=0.002,
                            head_width=0.018, head_length=0.02,
                            length_includes_head=True, fc=color, ec=color))


def main():
    fig, ax = plt.subplots(figsize=(13, 7.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.5, 0.975, "How each method turns ONE question into model input",
            ha="center", fontsize=15, weight="bold")
    ax.text(0.5, 0.945, "equal budget: 64 camera frames for both methods",
            ha="center", fontsize=11, color="#555")

    # shared input
    box(ax, 0.30, 0.86, 0.40, 0.055,
        "1 question  =  4 synchronized MEVA camera clips  +  4 answer options",
        fc="#f3f3f3", weight="bold", fs=11)
    arrow(ax, 0.42, 0.86, 0.25, 0.80)
    arrow(ax, 0.58, 0.86, 0.75, 0.80)

    # ---------------- LEFT: Method 1 (native) ----------------
    lx = 0.035
    box(ax, lx, 0.745, 0.43, 0.05, "METHOD 1 — CVBench-native",
        fc=NATIVE, ec=NATIVE, tc="white", weight="bold", fs=12.5)
    ax.text(lx + 0.215, 0.715, "sample 16 frames/clip, feed the 4 clips one after another",
            ha="center", fontsize=10, color="#333")
    # 4 camera filmstrips
    fx, fy0, fw, fh, gap = lx + 0.085, 0.665, 0.022, 0.030, 0.004
    for cam in range(4):
        y = fy0 - cam * (fh + 0.015)
        ax.text(lx + 0.075, y + fh / 2, f"Video {cam+1}\nCamera {cam+1}",
                ha="right", va="center", fontsize=8, color=INK)
        for f in range(16):
            ax.add_patch(Rectangle((fx + f * (fw + gap), y), fw, fh,
                                   fc="#dfe6ef", ec=NATIVE, lw=0.6))
        ax.text(fx + 16 * (fw + gap) + 0.005, y + fh / 2, "16", va="center",
                fontsize=8, color=NATIVE, weight="bold")
    box(ax, lx + 0.04, 0.46, 0.35, 0.045,
        "4 video blocks × 16 frames  =  64 frames", fc="#eef2f7", ec=NATIVE, fs=10.5)
    ax.text(lx + 0.215, 0.435,
            "model must cross-reference the cameras itself", ha="center",
            fontsize=9, style="italic", color="#666")

    # ---------------- RIGHT: Method 2 (stitch) ----------------
    rx = 0.535
    box(ax, rx, 0.745, 0.43, 0.05, "METHOD 2 — Spatial stitching (ours)",
        fc=STITCH, ec=STITCH, tc="white", weight="bold", fs=12.5)
    ax.text(rx + 0.215, 0.715, "tile the 4 cameras at each of 16 time steps into one 2×2 montage",
            ha="center", fontsize=10, color="#333")
    # one enlarged montage (2x2 with quadrant labels)
    mx, my, ms = rx + 0.025, 0.55, 0.105
    for i, (dx, dy, lab) in enumerate([(0, ms / 2, "Cam 1"), (ms / 2, ms / 2, "Cam 2"),
                                       (0, 0, "Cam 3"), (ms / 2, 0, "Cam 4")]):
        ax.add_patch(Rectangle((mx + dx, my + dy), ms / 2, ms / 2,
                               fc="#dbe7f4", ec=STITCH, lw=1.0))
        ax.text(mx + dx + ms / 4, my + dy + ms / 4, lab, ha="center", va="center",
                fontsize=8, color=STITCH, weight="bold")
    ax.text(mx + ms / 2, my - 0.025, "one montage (t)", ha="center", fontsize=8.5, color="#333")
    # a row of montage thumbnails t1..t16
    tx0, ty, ts = rx + 0.16, 0.60, 0.032
    for i in range(8):
        x = tx0 + i * (ts + 0.006)
        for dx in (0, ts / 2):
            for dy in (0, ts / 2):
                ax.add_patch(Rectangle((x + dx, ty + dy), ts / 2, ts / 2,
                                       fc="#dbe7f4", ec=STITCH, lw=0.4))
    ax.text(tx0 + 8 * (ts + 0.006) + 0.004, ty + ts / 2, "… t16", va="center",
            fontsize=8.5, color=STITCH, weight="bold")
    ax.text(tx0 + 0.10, ty + ts + 0.018, "16 montages (t1 … t16)", ha="center",
            fontsize=9, color="#333")
    box(ax, rx + 0.04, 0.46, 0.35, 0.045,
        "16 montages × 4 cameras  =  64 frames", fc="#eef2f7", ec=STITCH, fs=10.5)
    ax.text(rx + 0.215, 0.435,
            "cross-camera correspondence is shown to it", ha="center",
            fontsize=9, style="italic", color="#666")

    # ---------------- converge to model ----------------
    arrow(ax, 0.25, 0.455, 0.45, 0.345)
    arrow(ax, 0.75, 0.455, 0.55, 0.345)
    box(ax, 0.28, 0.27, 0.44, 0.07,
        "InternVL3-8B  —  one model call\nreads  <answer>X</answer>", fc="#fff6e0",
        ec="#b8860b", weight="bold", fs=12)
    arrow(ax, 0.5, 0.27, 0.5, 0.205)
    box(ax, 0.33, 0.135, 0.34, 0.06, "compare to gold answer  →  correct?  ✓ / ✗",
        fc="#eaf6ea", ec="#3a7d3a", fs=11)

    ax.text(0.5, 0.055,
            "Identical on every axis — same model, same 16 frames/clip, same question text, "
            "same scoring.\nOnly the visual packaging differs.",
            ha="center", fontsize=10, color="#444")

    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
