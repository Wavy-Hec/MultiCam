#!/usr/bin/env python3
"""Fallback generator for the video-boundary marker images.

The internvl2 wrapper's multi-video path (lmms-eval/lmms_eval/models/internvl2.py)
loads ./res/video{1..4}.png and ./res/end{1..4}.png as separator frames inserted
before/after each video's frames.

NOTE: the repo ALREADY ships these 8 markers in lmms-eval/res/, so you normally do
not need this script. It is a fallback for environments where they are missing; by
default it SKIPS files that already exist (use --force to overwrite).

The wrapper references them by the RELATIVE path "./res/...", so the images must
live under <cwd>/res when you launch lmms_eval (i.e. run lmms_eval from lmms-eval/).

Run only if markers are missing (no GPU needed):
  python3 analysis/make_markers.py
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(REPO, "lmms-eval", "res")


def make_marker(text, size, out_path):
    img = Image.new("RGB", size, (0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except IOError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size[0] - tw) // 2, (size[1] - th) // 2), text, font=font, fill=(255, 255, 255))
    img.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    ap.add_argument("--size", type=int, default=448)
    ap.add_argument("--max-videos", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="overwrite existing markers")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    size = (args.size, args.size)
    wrote = skipped = 0
    for i in range(1, args.max_videos + 1):
        for name, text in ((f"video{i}.png", f"The video {i}"), (f"end{i}.png", f"Video {i} End")):
            path = os.path.join(args.out_dir, name)
            if os.path.exists(path) and not args.force:
                skipped += 1
                continue
            make_marker(text, size, path)
            wrote += 1
    print(f"markers in {args.out_dir}: wrote {wrote}, skipped {skipped} existing "
          f"(use --force to overwrite)")
    print("Run lmms_eval from the directory that contains this 'res/' folder "
          "(or symlink it into your CWD).")


if __name__ == "__main__":
    main()
