"""Render the qualitative visual inputs for the exp64 report's example questions.

For each example question id, writes into bench/results/figs_qualitative/:
  qual_<id>_native.png   the NATIVE input: 4 cameras x 16 uniformly-sampled frames
  qual_<id>_stitch.png   the STITCH input: the 16 time-synced 2x2 grid montages
and once:
  qual_montage_zoom.png  a single montage at full size (shows the 'Camera i' labels)

These are the literal pixels each method sends to InternVL3-8B. Run from repo root:
  python -m bench.qual_make_figs
"""
import os

from PIL import Image, ImageDraw, ImageFont
from decord import VideoReader, cpu

from .reuse import DEFAULT_VIDEO_ROOT, video_paths
from .methods.stitch import build_montages, sample_frame_indices

import json

HERE = os.path.dirname(os.path.abspath(__file__))
FIGS = os.path.join(HERE, "results", "figs_qualitative")
os.makedirs(FIGS, exist_ok=True)
SUB = {r["id"]: r for r in json.load(open(os.path.join(
    HERE, "..", "analysis", "crossview_meva4cam_subset.json")))}

NFRAMES = 16
EXAMPLES = [106, 300, 1008]
FONT = ImageFont.load_default()


def _label(draw, xy, text, fill=(255, 255, 255), bg=(20, 20, 20)):
    x, y = xy
    w = draw.textlength(text, font=FONT)
    draw.rectangle([x, y, x + w + 6, y + 14], fill=bg)
    draw.text((x + 3, y + 2), text, fill=fill, font=FONT)


def native_grid(rec, out, cell=150):
    """4 cameras (rows) x 16 frames (cols): exactly the native method's 64 frames."""
    paths = video_paths(rec, DEFAULT_VIDEO_ROOT)
    rows = []
    for vp in paths:
        try:
            vr = VideoReader(vp, ctx=cpu(0), num_threads=1)
            idx = sample_frame_indices(len(vr), NFRAMES)
            frames = [Image.fromarray(vr[i].asnumpy()).convert("RGB") for i in idx]
        except Exception:
            frames = [Image.new("RGB", (cell, cell), (0, 0, 0))] * NFRAMES
        rows.append(frames)
    ch = int(cell * 0.66)  # keep frames landscape-ish
    lblw = 78
    canvas = Image.new("RGB", (lblw + NFRAMES * cell, len(rows) * ch), (245, 245, 245))
    draw = ImageDraw.Draw(canvas)
    for r, frames in enumerate(rows):
        y = r * ch
        _label(draw, (4, y + ch // 2 - 7), f"Camera {r+1}", bg=(40, 60, 120))
        for c, fr in enumerate(frames):
            canvas.paste(fr.resize((cell, ch)), (lblw + c * cell, y))
            if r == 0:
                _label(draw, (lblw + c * cell + 2, 2), f"t{c+1}")
    canvas.save(out, "PNG")
    return canvas.size


def stitch_sheet(rec, out, per=280):
    """The 16 montages (4x4 contact sheet): exactly the stitch method's input images."""
    paths = video_paths(rec, DEFAULT_VIDEO_ROOT)
    montages = build_montages(paths, nframes=NFRAMES, T=NFRAMES, cell_px=448)
    cols = 4
    rows = (len(montages) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * per, rows * per), (245, 245, 245))
    draw = ImageDraw.Draw(canvas)
    for i, m in enumerate(montages):
        r, c = divmod(i, cols)
        canvas.paste(m.resize((per, per)), (c * per, r * per))
        _label(draw, (c * per + 3, r * per + 3), f"montage t{i+1}", bg=(120, 40, 40))
    canvas.save(out, "PNG")
    return canvas.size, montages


def main():
    zoom_saved = False
    for i in EXAMPLES:
        rec = SUB[i]
        s1 = native_grid(rec, os.path.join(FIGS, f"qual_{i}_native.png"))
        s2, montages = stitch_sheet(rec, os.path.join(FIGS, f"qual_{i}_stitch.png"))
        print(f"id={i}: native{s1} stitch{s2}")
        if not zoom_saved and montages:
            montages[len(montages) // 2].save(
                os.path.join(FIGS, "qual_montage_zoom.png"), "PNG")
            zoom_saved = True
    print("wrote ->", FIGS)


if __name__ == "__main__":
    main()
