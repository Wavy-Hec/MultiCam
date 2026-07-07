# Stitch pipeline crop audit — does 2×2 stitching trim frame content?

*2026-07-06. Evidence images: `analysis/stitch_audit_meva.png`, `analysis/stitch_audit_cvbench.png`
(regenerate with `python analysis/stitch_crop_audit.py`, no GPU).*

## Verdict

**No cropping: the full field of view of every camera reaches the model — but the resize is
NOT aspect-preserving either.** Each frame is squashed whole into a square 448×448 cell by a
plain distorting resize at `bench/methods/stitch.py:92`; there is no letterbox/pillarbox
padding anywhere in the pipeline. So Harsh's "cells are trimmed" is wrong, and "aspect-preserving
resize + padded" is also wrong — it's option three: **anisotropic full-frame resize**.

## The one-frame trace (code evidence)

All model-input stitching lives in `bench/methods/stitch.py` (pure decord + PIL), called by
`CentralizedMethod._prepare` (`bench/methods/centralized.py:54`) as
`build_montages(paths, nframes=8, T=8, cell_px=448, label_prefix=...)`.

| stage | code | what happens to the pixels |
|---|---|---|
| decode | `stitch.py:48` `Image.fromarray(vr[i].asnumpy())` | **full frame**, native size (e.g. 1920×1080; decord gives the whole frame, no ROI) |
| cell | `stitch.py:92` `cell = frame.resize((cell_w, cell_h))` | whole frame → **448×448, aspect distorted** (16:9 compressed 1.78× horizontally; 9:16 compressed vertically). No `.crop`, no `ImageOps.fit`, no slicing — this is the only geometry op |
| paste | `stitch.py:93` `canvas.paste(cell, (x0, y0 + label_band))` | lossless paste into the grid |
| canvas | `stitch.py:78` `Image.new("RGB", (cols*448, rows*(448+22)))` | K=4 → **896×940** montage (2×2 cells + 22px label bands) |

There is **no crop operation in the file** (or in `centralized.py`): grep for
`crop|CenterCrop|fit|getRectSubPix` in `bench/methods/` hits nothing on the model-input path.

### Label bands do NOT occlude content — and they ARE model input

`stitch.py:77` adds the band as **extra canvas height** (`cell_total_h = cell_h + label_band`);
the band rectangle + "Camera i"/"Video i" text are drawn at `y0..y0+22` (`stitch.py:84-86`) and
the frame is pasted **below** it at `y0+22` (`stitch.py:93`). Zero frame pixels are covered.
The montages (bands included) go straight into the message content at `centralized.py:71-74`.

### Downstream backends don't crop either

- **InternVL3** (`bench/backends/internvl.py`): montage images go through `load_image` →
  `dynamic_preprocess` with **`max_tiles=1` (our runs' default)** → the entire 896×940 montage is
  resized to 448×448 by `T.Resize((448,448))` (`internvl.py:33-39`) — again distorting, not
  cropping. Net at model input: each camera occupies ≈224×214 effective px. With
  `--internvl-max-tiles > 1`, `dynamic_preprocess` (`internvl.py:58-81`) *partition-tiles* the
  image (tiles' union covers the whole frame, `.crop` at `:77` is tiling, not trimming) plus a
  full-frame thumbnail — still nothing discarded.
- **Qwen** (`bench/backends/qwen.py:30-40`): `qwen_vl_utils` `smart_resize` with
  `do_resize=False` on the HF processor — **aspect-preserving**, no crop.

### CVBench vs MEVA path

Identical geometry code. The only difference is cosmetic: `montage_kind="video"` swaps the
cell label text to "Video i" and the preamble (`centralized.py:22-29`); `label_prefix` is the
sole parameter that changes (`stitch.py:108`).

### The slide/doc figures are a different code path (this may be what Harsh saw)

`bench/qual_make_figs.py` and `bench/cvbench_report_figs.py` re-render montages for **human**
figures and draw extra opaque badges **on the pixels** (`t1/t2…` at `qual_make_figs.py:62`,
"montage t{i}" at `:78`; same pattern at `cvbench_report_figs.py:152,165`). Those badges exist
only in the PNGs under `bench/results/figs_qualitative/` / `cvbench_obsidian/` — **the model
never sees them**. Slides (`analysis/make_slides_v2.py`) label images with PPTX text boxes
beside the frames, not on them.

## Empirical proof (real pipeline, real data)

`analysis/stitch_crop_audit.py` runs the actual `build_montages` on two real 4-camera
questions, extracts each grid cell back out of the montage, and diffs it pixel-for-pixel
against an independent **full-frame** resize (a crop-free reference):

- **MEVA id=0** (mixed sources: 1920×1080, 1920×1080, **352×240**, 1920×1072):
  max |cell − full-frame resize| = **[0, 0, 0, 0]** → pixel-identical, nothing trimmed.
- **CVBench cvb-3** (four **portrait 1080×1920** clips — the worst case for crop-vs-pad
  ambiguity): max diff = **[0, 0, 0, 0]**. The evidence figure makes the distortion obvious:
  the portrait frames appear whole but horizontally stretched; the third panel shows the
  letterboxed alternative the pipeline does *not* produce.

Evidence images (post-ready):

- `analysis/stitch_audit_meva.png` — raw frames (native dims) → actual 896×940 montage →
  cell vs full-resize vs letterbox comparison.
- `analysis/stitch_audit_cvbench.png` — same layout, portrait-clip question.

## Caveat worth knowing (not a crop)

The double squash (source → 448² cell, then InternVL's 896×940 → 448² at `max_tiles=1`) means
a 1920-px-wide camera view lands on ~224 px at the model. That resolution loss — not cropping —
is the plausible real cost of stitching at K=4, consistent with the full-1000 result
(centralized 52.3% vs temporal 61.6% at K=4; see `analysis/d2_acc_by_clipcount.png`).
