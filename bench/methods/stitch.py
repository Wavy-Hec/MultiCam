"""Spatial-stitching for the CENTRALIZED harness.

The mentor spec's centralized method "temporally aligns the video streams and
spatially stitches the corresponding images across multiple views to provide a
unified input." This module turns the K (<=4) camera clips of one question into
``T`` grid-montage images: for each of T aligned timesteps, the synchronized
frame from every camera is tiled into one labeled grid image.

Pure decord + PIL, no model. Frames are sampled at the SAME normalized positions
within each clip (proportional alignment), which degrades gracefully when clips
differ slightly in length/fps (MEVA: same 30fps but sub-second start offsets;
EgoExo4D: frame-aligned). Output is a list of ``PIL.Image`` consumed unchanged by
the Qwen backend and via ``load_image`` by the InternVL backend.
"""
from __future__ import annotations

import math
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

from decord import VideoReader, cpu


def sample_frame_indices(n_total: int, nframes: int) -> List[int]:
    """``linspace(0, n_total-1, nframes)`` rounded to ints (mirrors the per-clip
    nframes sampling used elsewhere in the harness)."""
    if n_total <= 0:
        return [0] * nframes
    if nframes <= 1:
        return [0]
    step = (n_total - 1) / (nframes - 1)
    return [int(round(i * step)) for i in range(nframes)]


def decode_aligned_frames(video_paths: List[str], nframes: int) -> List[List[Optional[Image.Image]]]:
    """Per camera, decode ``nframes`` frames at proportional positions.

    Returns ``frames[k][t]`` (PIL.Image), or ``None`` for a frame whose clip
    failed to decode (compose_montage fills those cells black).
    """
    per_cam: List[List[Optional[Image.Image]]] = []
    for vp in video_paths:
        try:
            vr = VideoReader(vp, ctx=cpu(0), num_threads=1)
            n = len(vr)
            idx = sample_frame_indices(n, nframes)
            frames = [Image.fromarray(vr[i].asnumpy()).convert("RGB") for i in idx]
        except Exception:
            frames = [None] * nframes  # decode failure -> black cells
        per_cam.append(frames)
    return per_cam


def grid_layout(k: int) -> tuple[int, int]:
    """(rows, cols) for K camera cells. cols = ceil(sqrt(k)); K<=4 -> at most 2x2."""
    k = max(1, k)
    cols = math.ceil(math.sqrt(k))
    rows = math.ceil(k / cols)
    return rows, cols


def _label_font():
    try:
        return ImageFont.load_default()
    except Exception:  # extremely defensive; load_default is bundled with PIL
        return None


def compose_montage(frames: List[Optional[Image.Image]], labels: List[str],
                    cell_w: int = 448, cell_h: int = 448,
                    pad_color=(0, 0, 0), label_band: int = 22) -> Image.Image:
    """Tile one timestep's per-camera frames into a single labeled grid image."""
    k = len(frames)
    rows, cols = grid_layout(k)
    font = _label_font()
    cell_total_h = cell_h + label_band
    canvas = Image.new("RGB", (cols * cell_w, rows * cell_total_h), pad_color)
    draw = ImageDraw.Draw(canvas)
    for i in range(k):
        r, c = divmod(i, cols)
        x0, y0 = c * cell_w, r * cell_total_h
        # label band
        draw.rectangle([x0, y0, x0 + cell_w, y0 + label_band], fill=(30, 30, 30))
        if font is not None:
            draw.text((x0 + 4, y0 + 4), labels[i], fill=(255, 255, 255), font=font)
        # frame (black if missing)
        frame = frames[i]
        if frame is None:
            cell = Image.new("RGB", (cell_w, cell_h), pad_color)
        else:
            cell = frame.resize((cell_w, cell_h))
        canvas.paste(cell, (x0, y0 + label_band))
    return canvas


def build_montages(video_paths: List[str], nframes: int = 8, T: Optional[int] = None,
                   cell_px: int = 448, label_prefix: str = "Camera") -> List[Image.Image]:
    """Decode the K clips and compose ``T`` grid montages (one per aligned timestep).

    ``T`` defaults to ``nframes`` (each sampled timestep gets a montage); pass
    ``T=1`` for the strict "single unified image" reading. ``label_prefix`` sets the
    per-cell caption ("Camera" for synced views, "Video" for independent clips).
    """
    T = nframes if (T is None or T <= 0) else T
    per_cam = decode_aligned_frames(video_paths, nframes)  # [K][nframes]
    k = len(video_paths)
    labels = [f"{label_prefix} {i + 1}" for i in range(k)]
    # pick T timestep indices among the nframes decoded positions
    t_idx = sample_frame_indices(nframes, T)
    montages = []
    for t in t_idx:
        frames_t = [per_cam[c][t] if t < len(per_cam[c]) else None for c in range(k)]
        montages.append(compose_montage(frames_t, labels, cell_w=cell_px, cell_h=cell_px))
    return montages
