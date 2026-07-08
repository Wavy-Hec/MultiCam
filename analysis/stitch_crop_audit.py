"""Empirical audit: does the 2x2 spatial-stitch pipeline CROP frame content?

Answer from code (bench/methods/stitch.py):
  - compose_montage() line 92: ``cell = frame.resize((cell_w, cell_h))`` — a
    plain PIL resize of the FULL decoded frame to a 448x448 square. No crop,
    no aspect-preserving pad: the whole field of view is kept but the aspect
    ratio is distorted (16:9 gets squashed horizontally).
  - The "Camera i"/"Video i" label band (lines 77-93) is an EXTRA 22px strip
    above each cell; the frame is pasted BELOW it (y0+label_band), so labels
    never occlude frame pixels. Montages feed the model directly
    (centralized.py lines 71-74), so the bands ARE model input.

This script proves it on real data:
  1. Runs the actual pipeline entry point (build_montages, same call as
     CentralizedMethod._prepare) on one 4-camera MEVA question and one
     CVBench question that includes a non-16:9 clip.
  2. Extracts each grid cell back out of the montage and diffs it pixel-for-
     pixel against an independent full-frame resize (crop-free reference) —
     max abs diff 0 == nothing was trimmed.
  3. Saves side-by-side evidence PNGs (raw frames w/ native dims -> montage,
     plus cell vs full-resize vs letterboxed-alternative comparison).

Usage (internvl env, no GPU):
  python analysis/stitch_crop_audit.py
Writes: analysis/stitch_audit_meva.png, analysis/stitch_audit_cvbench.png
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
from decord import VideoReader, cpu                              # noqa: E402
from bench.methods.stitch import (build_montages, sample_frame_indices,
                                  grid_layout)                   # noqa: E402
from bench.reuse import video_paths, DEFAULT_VIDEO_ROOT          # noqa: E402

CELL, BAND = 448, 22   # pipeline defaults (compose_montage signature)
CVBENCH_ROOT = os.path.join(os.path.dirname(_HERE),
                            "Video-R1/src/r1-v/Evaluation/CVBench")


def decode_frame(vp, t_frac=0.0, nframes=8):
    """The exact frame the pipeline uses at timestep index 0 of T=nframes."""
    vr = VideoReader(vp, ctx=cpu(0), num_threads=1)
    idx = sample_frame_indices(len(vr), nframes)
    return Image.fromarray(vr[idx[0]].asnumpy()).convert("RGB")


def letterbox(img, w, h, color=(0, 0, 0)):
    """The aspect-preserving alternative the pipeline does NOT do."""
    s = min(w / img.width, h / img.height)
    rw, rh = round(img.width * s), round(img.height * s)
    out = Image.new("RGB", (w, h), color)
    out.paste(img.resize((rw, rh)), ((w - rw) // 2, (h - rh) // 2))
    return out


def annotate(img, text, band=26):
    out = Image.new("RGB", (img.width, img.height + band), (255, 255, 255))
    out.paste(img, (0, band))
    ImageDraw.Draw(out).text((4, 6), text, fill=(0, 0, 0))
    return out


def audit(tag, paths, label_prefix, out_png):
    print(f"\n=== {tag}: K={len(paths)} clips, label_prefix={label_prefix!r} ===")
    raws = [decode_frame(vp) for vp in paths]
    for i, (vp, im) in enumerate(zip(paths, raws), 1):
        print(f"  clip {i}: {im.width}x{im.height}  {os.path.basename(vp)}")

    # actual pipeline call (CentralizedMethod._prepare passes nframes=8, T=8)
    montage = build_montages(paths, nframes=8, T=8, cell_px=CELL,
                             label_prefix=label_prefix)[0]
    rows, cols = grid_layout(len(paths))
    print(f"  montage: {montage.width}x{montage.height} "
          f"({cols}x{rows} grid of {CELL}x{CELL} cells + {BAND}px label bands)")

    # cell-extraction proof: montage cell == full-frame distorting resize
    max_diffs = []
    for i, raw in enumerate(raws):
        r, c = divmod(i, cols)
        x0, y0 = c * CELL, r * (CELL + BAND)
        cell = montage.crop((x0, y0 + BAND, x0 + CELL, y0 + BAND + CELL))
        ref = raw.resize((CELL, CELL))            # crop-free reference
        d = int(np.abs(np.asarray(cell, dtype=np.int16)
                       - np.asarray(ref, dtype=np.int16)).max())
        max_diffs.append(d)
    print(f"  max |montage cell - full-frame resize| per clip: {max_diffs} "
          f"(0 = pixel-identical = nothing cropped)")

    # evidence figure: raw frames / montage / cell-vs-alternatives strip
    thumb_h = 220
    raw_thumbs = [annotate(im.resize((max(1, round(im.width * thumb_h / im.height)),
                                      thumb_h)),
                           f"raw clip {i+1}: {im.width}x{im.height}")
                  for i, im in enumerate(raws)]
    row1_w = sum(t.width + 8 for t in raw_thumbs)
    strip = []
    j = int(np.argmax([abs(im.width / im.height - 1.0) for im in raws]))
    r, c = divmod(j, cols)
    cell = montage.crop((c * CELL, r * (CELL + BAND) + BAND,
                         c * CELL + CELL, r * (CELL + BAND) + BAND + CELL))
    strip = [annotate(cell, f"pipeline cell (clip {j+1}): full frame, distorted"),
             annotate(raws[j].resize((CELL, CELL)), "= full-frame resize (diff 0)"),
             annotate(letterbox(raws[j], CELL, CELL),
                      "letterbox alternative (NOT what pipeline does)")]
    row3_w = sum(s.width + 8 for s in strip)
    W = max(row1_w, montage.width + 8, row3_w) + 8
    H = (thumb_h + 26) + montage.height + (CELL + 26) + 26 * 3 + 32
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    x, y = 8, 4
    draw.text((x, y), f"{tag} - raw sampled frames (native size):", fill=(0, 0, 0))
    y += 18
    for t in raw_thumbs:
        canvas.paste(t, (x, y)); x += t.width + 8
    y += thumb_h + 26 + 6
    draw.text((8, y), f"actual pipeline montage ({montage.width}x{montage.height}, "
                      f"model input):", fill=(0, 0, 0))
    y += 18
    canvas.paste(montage, (8, y))
    y += montage.height + 6
    draw.text((8, y), "cell-level proof (most non-square clip):", fill=(0, 0, 0))
    y += 18
    x = 8
    for s in strip:
        canvas.paste(s, (x, y)); x += s.width + 8
    canvas.save(out_png)
    print(f"  evidence -> {out_png}")
    return max_diffs


def main():
    # MEVA / CrossView: first 4-camera record, default video root
    meva = json.load(open(os.path.join(_HERE, "crossview_meva4cam_subset.json")))
    rec = meva[0]
    paths = video_paths(rec, DEFAULT_VIDEO_ROOT)
    d1 = audit(f"MEVA {rec['id']}", paths, "Camera",
               os.path.join(_HERE, "stitch_audit_meva.png"))

    # CVBench: pick the question whose clips have the most non-16:9 clip
    cvb = json.load(open(os.path.join(_HERE, "cvbench_full_runnable_subset.json")))
    best, best_dev = None, -1.0
    for r in cvb:
        ps = video_paths(r, CVBENCH_ROOT)
        if len(ps) < 4:
            continue
        try:
            devs = []
            for vp in ps:
                vr = VideoReader(vp, ctx=cpu(0), num_threads=1)
                h, w = vr[0].shape[:2]
                devs.append(abs(w / h - 16 / 9))
            dev = max(devs)
        except Exception:
            continue
        if dev > best_dev:
            best, best_dev = r, dev
        if best_dev > 0.8:        # found a clearly portrait/square clip; stop
            break
    d2 = audit(f"CVBench {best['id']}", video_paths(best, CVBENCH_ROOT), "Video",
               os.path.join(_HERE, "stitch_audit_cvbench.png"))

    verdict = "NO CROPPING" if max(d1 + d2) == 0 else "DIFF FOUND — investigate"
    print(f"\nVERDICT: {verdict} (max cell-vs-full-resize diff: {max(d1 + d2)})")


if __name__ == "__main__":
    main()
