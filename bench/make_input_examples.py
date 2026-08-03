"""Render the LITERAL visual input each method sends to the model, for the two
benchmarks currently in play — All-Angles-Bench (EgoHumans stills) and MVU-Eval
dev (videos) — so the pixels can be eyeballed offline.

This is the era-2 sibling of ``bench/qual_make_figs.py`` (which is hard-wired to
the retired CrossView/exp64 setup). Everything that produces pixels here is
imported from the production code, never re-implemented:

  bench.reuse.build_messages / video_paths / image_paths / num_images
  bench.methods.stitch.build_montages / build_image_montage / sample_frame_indices
  bench.methods.clip_select.FrameSelectMethod._candidates / _resize   (no model, no CLIP)
  bench.backends.internvl.get_index / dynamic_preprocess / find_closest_aspect_ratio

so a cell in these PNGs is the same PIL object the backend tensorizes.

For each chosen question it writes into ``bench/results/figs_inputs_era2/``:

  <ds>_<id>_native.png        NATIVE: each view/clip as the model receives it
                              (video: the 8 frames InternVL's get_index picks,
                              each squashed to one 448x448 tile; stills: the
                              per-view 448px tile decomposition + thumbnail).
  <ds>_<id>_centralized.png   CENTRALIZED: the real labelled grid montage(s).
  <ds>_<id>_montage_zoom.png  one montage at FULL size — burned-in "View i" /
                              "Video i" labels and the anisotropic squash.
  mvu_<id>_frameselect.png    MVU only: the frames frame_select actually kept,
                              grouped by source video, replayed from the
                              ``frame_alloc.selected_times_s`` of a real result
                              row (CLIP is NOT re-run).

plus ``manifest.json`` and ``source_media/`` (the raw clips/images).

CPU only: no model is loaded and CUDA is masked off at import time. Run from the
repo root under the ``cvbench`` conda env (needs decord + PIL):

  python -m bench.make_input_examples
  python -m bench.make_input_examples --auto-pick --no-copy-media

RUN CONFIG. The defaults below are not guesses: they were recovered from the
completed InternVL3-8B legs by reproducing each row's token accounting exactly
(``input_tokens - video_tokens`` against the InternVL3 tokenizer, and
``video_tokens/256`` against the tile counts ``dynamic_preprocess`` yields):
nframes=8; centralized T=4 montages on MVU-Eval with "Video i" labels and T=1
"View i" montage on All-Angles; cell_px=448; internvl_max_tiles=4 for the
native/centralized/per_stream legs and 1 for the clip-experiment leg.
``--verify-tokens`` (on by default) re-checks that against the result rows and
prints MATCH/MISMATCH per figure.
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import shutil
import time

# CPU-only guarantee: torch is pulled in transitively (bench.reuse -> eval_thinking,
# bench.backends.internvl). Mask the GPUs before any of that imports.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("DECORD_EOF_RETRY_MAX", "20480")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from decord import VideoReader, cpu  # noqa: E402

from .reuse import build_messages, image_paths, num_images, video_paths  # noqa: E402
from .methods.stitch import (build_image_montage, build_montages,  # noqa: E402
                             sample_frame_indices)
from .methods.centralized import (MONTAGE_PREFIX_VIDEO,  # noqa: E402
                                  MONTAGE_PREFIX_VIEW)
from .methods.clip_select import FrameSelectMethod  # noqa: E402
from .backends.internvl import (dynamic_preprocess,  # noqa: E402
                                find_closest_aspect_ratio, get_index)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# --------------------------------------------------------------------------- #
# defaults (see module docstring: recovered from the real runs, not invented)
DEF_OUT = os.path.join(HERE, "results", "figs_inputs_era2")
DEF_AAB_SUBSET = os.path.join(REPO, "analysis", "allangles_egohumans_qa.json")
DEF_AAB_ROOT = os.path.join(REPO, "data", "allangles")
DEF_MVU_SUBSET = os.path.join(REPO, "analysis", "mvueval_dev_subset.json")
DEF_MVU_ROOT = os.path.join(REPO, "data", "mvueval")
DEF_AAB_RESULTS = "bench/results/bench_allangles_egohumans_qa_internvl_aabfull_shard*.jsonl"
DEF_MVU_RESULTS = ("bench/results/bench_mvueval_dev_subset_internvl_mvudev_shard*.jsonl,"
                   "bench/results/bench_mvueval_dev_subset_internvl_clipexp_shard*.jsonl")
# chosen deliberately: low- and high-view-count questions where the methods
# disagree most across the 4 passes (--auto-pick re-derives them from the rows)
DEF_AAB_IDS = "3,37"
DEF_MVU_IDS = "394,813,257"
DEF_MEDIA_IDS = "aab:3,aab:37,mvu:394,mvu:813,mvu:257"

FS_METHODS = ("frame_select", "clip_select_top1", "temporal_weighted")
ALL_METHODS = ("cvbench_native", "centralized", "per_stream") + FS_METHODS
BACKEND_LABEL = "InternVL3-8B"   # set from --backend in main(); captions only

# --------------------------------------------------------------------------- #
# text rendering


def _font_paths():
    out = []
    try:
        import matplotlib
        out.append(os.path.join(os.path.dirname(matplotlib.__file__),
                                "mpl-data", "fonts", "ttf", "DejaVuSans.ttf"))
        out.append(os.path.join(os.path.dirname(matplotlib.__file__),
                                "mpl-data", "fonts", "ttf", "DejaVuSans-Bold.ttf"))
    except Exception:
        pass
    out += ["/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    return out


_FONT_CACHE = {}


def font(size=16, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    f = None
    for p in _font_paths():
        if os.path.exists(p) and (("Bold" in p) == bool(bold)):
            try:
                f = ImageFont.truetype(p, size)
                break
            except Exception:
                pass
    if f is None:
        for p in _font_paths():
            if os.path.exists(p):
                try:
                    f = ImageFont.truetype(p, size)
                    break
                except Exception:
                    pass
    if f is None:
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:
            f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


_MEASURE = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def wrap_px(text, fnt, max_px):
    """Greedy wrap of ``text`` to ``max_px`` pixels using the real font metrics."""
    lines = []
    for para in str(text).split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            trial = w if not cur else cur + " " + w
            if _MEASURE.textlength(trial, font=fnt) <= max_px or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines or [""]


def label(draw, xy, text, fnt, fill=(255, 255, 255), bg=(25, 25, 25), pad=4):
    x, y = xy
    w = _MEASURE.textlength(text, font=fnt)
    h = fnt.size + 2 * pad if hasattr(fnt, "size") else 16
    draw.rectangle([x, y, x + w + 2 * pad, y + h], fill=bg)
    draw.text((x + pad, y + pad - 1), text, fill=fill, font=fnt)
    return int(w + 2 * pad), int(h)


def caption_image(width, blocks, pad=16, max_text_px=1750):
    """Render the caption band. ``blocks`` = list of (text, style) where style is
    one of title/sub/body/mono/good/bad/note."""
    styles = {
        "title": (dict(size=23, bold=True), (12, 12, 12), 9),
        "sub":   (dict(size=17, bold=True), (35, 35, 90), 5),
        "body":  (dict(size=16), (25, 25, 25), 3),
        "mono":  (dict(size=15), (60, 60, 60), 2),
        "good":  (dict(size=16, bold=True), (10, 105, 30), 3),
        "bad":   (dict(size=16), (150, 30, 30), 3),
        "note":  (dict(size=15), (95, 60, 10), 4),
    }
    maxw = min(width - 2 * pad, max_text_px)
    rendered = []
    for text, style in blocks:
        fkw, color, gap = styles.get(style, styles["body"])
        fnt = font(**fkw)
        for ln in wrap_px(text, fnt, maxw):
            rendered.append((ln, fnt, color, fnt.size + gap))
    h = pad * 2 + sum(r[3] for r in rendered)
    im = Image.new("RGB", (width, h), (252, 252, 250))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, width - 1, h - 1], outline=(200, 200, 195))
    y = pad
    for ln, fnt, color, adv in rendered:
        d.text((pad, y), ln, fill=color, font=fnt)
        y += adv
    return im


def stack(caption, body, bg=(252, 252, 250)):
    w = max(caption.width, body.width)
    im = Image.new("RGB", (w, caption.height + body.height), bg)
    im.paste(caption, (0, 0))
    im.paste(body, (0, caption.height))
    return im


# --------------------------------------------------------------------------- #
# "as the model receives it": the real InternVL tile decomposition


def tile_grid(img, max_num, image_size=448):
    """(cols, rows) of the tile grid ``dynamic_preprocess`` will use — computed
    with the production ``find_closest_aspect_ratio`` and the same candidate set,
    so the display layout matches the real tiling."""
    w, h = img.size
    target_ratios = sorted({(i, j) for n in range(1, max_num + 1)
                            for i in range(1, n + 1) for j in range(1, n + 1)
                            if 1 <= i * j <= max_num}, key=lambda x: x[0] * x[1])
    return find_closest_aspect_ratio(w / h, target_ratios, w, h, image_size)


def delivered_tiles(img, max_num):
    """The literal 448x448 tiles the InternVL backend feeds the vision tower."""
    return dynamic_preprocess(img, image_size=448, use_thumbnail=True, max_num=max_num)


def tile_strip(img, max_num, tile_px):
    """Render one view/frame the way the model gets it: the tile grid (thin red
    seams between tiles) plus the appended thumbnail tile when there is one."""
    tiles = delivered_tiles(img, max_num)
    has_thumb = len(tiles) > 1
    blocks = tiles[:-1] if has_thumb else tiles
    cols, rows = tile_grid(img, max_num)
    if cols * rows != len(blocks):  # defensive: fall back to a single row
        cols, rows = len(blocks), 1
    seam = 2
    gw = cols * tile_px + (cols - 1) * seam
    gh = rows * tile_px + (rows - 1) * seam
    gap = 18 if has_thumb else 0
    tw = tile_px if has_thumb else 0
    strip = Image.new("RGB", (gw + gap + tw, max(gh, tile_px if has_thumb else gh)),
                      (200, 40, 40))
    for i, t in enumerate(blocks):
        c, r = i % cols, i // cols
        strip.paste(t.resize((tile_px, tile_px)),
                    (c * (tile_px + seam), r * (tile_px + seam)))
    if has_thumb:
        strip.paste(tiles[-1].resize((tile_px, tile_px)), (gw + gap, 0))
        d = ImageDraw.Draw(strip)
        label(d, (gw + gap + 3, 3), "thumb", font(12), bg=(120, 0, 0))
    return strip, len(tiles)


# --------------------------------------------------------------------------- #
# contact sheet


def contact_sheet(rows, width_hint=0, row_gap=10, left=250, pad=10,
                  bg=(244, 244, 242), label_pos="top"):
    """rows = [(row_label, [(cell_img, cell_label), ...], row_note)]."""
    fl, fc, fn = font(17, bold=True), font(12), font(13)
    row_h, row_w = [], []
    for _, cells, _ in rows:
        row_h.append(max([c.height for c, _ in cells] or [40]))
        row_w.append(sum(c.width for c, _ in cells) + pad * max(0, len(cells) - 1))
    width = max(width_hint, left + (max(row_w) if row_w else 0) + pad)
    height = pad + sum(h + row_gap + 20 for h in row_h)
    im = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(im)
    y = pad
    for (rlabel, cells, rnote), h in zip(rows, row_h):
        d.rectangle([0, y, left - 6, y + h - 1], fill=(238, 238, 246))
        for i, ln in enumerate(wrap_px(rlabel, fl, left - 20)):
            d.text((8, y + 6 + i * (fl.size + 3)), ln, fill=(25, 25, 70), font=fl)
        if rnote:
            base = 6 + len(wrap_px(rlabel, fl, left - 20)) * (fl.size + 3) + 4
            for i, ln in enumerate(wrap_px(rnote, fn, left - 20)):
                d.text((8, y + base + i * (fn.size + 2)), ln, fill=(90, 90, 90), font=fn)
        x = left
        for cimg, clabel in cells:
            im.paste(cimg, (x, y))
            d.rectangle([x, y, x + cimg.width - 1, y + cimg.height - 1],
                        outline=(180, 180, 180))
            if clabel:
                # 'bottom' keeps the montage's own burned-in "View i"/"Video i"
                # band (top-left of every cell) unobstructed
                ly = (y + 2) if label_pos == "top" else (y + cimg.height - fc.size - 10)
                label(d, (x + 2, ly), clabel, fc, bg=(20, 20, 20))
            x += cimg.width + pad
        y += h + 20 + row_gap
    return im


# --------------------------------------------------------------------------- #
# results rows


def load_rows(globs, backend=None):
    rows = []
    for g in globs:
        for f in sorted(_glob.glob(g if os.path.isabs(g) else os.path.join(REPO, g))):
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if backend and r.get("backend") != backend:
                        continue
                    rows.append(r)
    return rows


def by_question(rows):
    out = {}
    for r in rows:
        out.setdefault(r.get("id"), {}).setdefault(r.get("method"), []).append(r)
    for q in out.values():
        for m in q:
            q[m].sort(key=lambda r: (r.get("pass_idx") or 0))
    return out


def method_summary(qrows):
    """{method: {"n":4,"correct":3,"acc":0.75,"preds":[...],"gold":"C"}}"""
    out = {}
    for m, rr in qrows.items():
        out[m] = {
            "n": len(rr),
            "correct": sum(1 for r in rr if r.get("correct")),
            "acc": (sum(1 for r in rr if r.get("correct")) / len(rr)) if rr else None,
            "preds": [(r.get("prediction") or "-") for r in rr],
            "gold": rr[0].get("gold") if rr else None,
            "video_tokens": rr[0].get("video_tokens") if rr else None,
            "input_tokens": rr[0].get("input_tokens") if rr else None,
        }
    return out


def pred_line(msum, backend="InternVL3-8B"):
    parts = []
    for m in ALL_METHODS:
        s = msum.get(m)
        if not s:
            continue
        parts.append(f"{m} {s['correct']}/{s['n']} [{','.join(s['preds'])}]")
    return f"{backend}, {max([s['n'] for s in msum.values()] or [0])} passes @ temp 0.7 " \
           f"--- " + "   |   ".join(parts)


def spread(msum):
    accs = [s["acc"] for s in msum.values() if s["acc"] is not None]
    return (max(accs) - min(accs)) if accs else 0.0


def auto_pick(qmap, recs, k_low, k_high, n_each=1):
    """Highest method-disagreement question at the low and high view counts."""
    picked = []
    for want in (k_low, k_high):
        cands = []
        for qid, qrows in qmap.items():
            rec = recs.get(qid)
            if rec is None:
                continue
            k = num_images(rec) or len(video_paths(rec, ""))
            if k != want:
                continue
            cands.append((spread(method_summary(qrows)), -int(qid), qid))
        cands.sort(reverse=True)
        picked += [c[2] for c in cands[:n_each]]
    return picked


# --------------------------------------------------------------------------- #
# media metadata


def clip_meta(vp):
    try:
        vr = VideoReader(vp, ctx=cpu(0), num_threads=1)
        n = len(vr)
        fps = float(vr.get_avg_fps())
        h, w = vr[0].asnumpy().shape[:2]
        return {"frames": n, "fps": round(fps, 3),
                "duration_s": round(n / fps, 2) if fps > 0 else None,
                "width": int(w), "height": int(h)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def image_meta(ip):
    try:
        with Image.open(ip) as im:
            return {"width": im.width, "height": im.height, "format": im.format}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def describe_view(dataset, rel, k, meta):
    if dataset == "aab":
        parts = rel.replace("\\", "/").split("/")
        cam = os.path.splitext(parts[-1])[0]
        scene = "/".join(parts[1:-1]) if len(parts) > 2 else "/".join(parts[:-1])
        return (f"View {k}: EgoHumans scene {scene}, camera {cam} "
                f"({meta.get('width')}x{meta.get('height')} still)")
    return (f"Video {k}: clip {os.path.basename(rel)} "
            f"({meta.get('width')}x{meta.get('height')}, {meta.get('frames')} frames, "
            f"{meta.get('duration_s')}s @ {meta.get('fps')}fps)")


# --------------------------------------------------------------------------- #
# figure builders


def caption_head(dataset_name, rec, k, unit, msum, what, delivered, extra=()):
    gold = rec["answer"].strip()
    blocks = [
        (f"{dataset_name}  |  question id={rec['id']}  |  {rec.get('task_type')}  |  "
         f"K={k} {unit}", "title"),
        (f"Q: {rec['question']}", "body"),
    ]
    for o in rec["options"]:
        is_gold = o.strip().upper().startswith(gold.upper())
        blocks.append((("    " + o + ("     <=== GOLD" if is_gold else "")),
                       "good" if is_gold else "body"))
    blocks.append((f"gold answer: {gold}", "sub"))
    blocks.append((pred_line(msum, BACKEND_LABEL), "mono"))
    blocks.append((f"WHAT THIS IMAGE SHOWS: {what}", "sub"))
    blocks.append((delivered, "note"))
    for e in extra:
        blocks.append((e, "mono"))
    return blocks


def fig_native(dataset, rec, root, msum, nframes, max_tiles, cell_px, out_path):
    """The NATIVE input: every view/clip exactly as build_messages hands it over."""
    is_img = num_images(rec) > 0
    rows, tiles_total, per_view = [], 0, []
    if is_img:
        paths = image_paths(rec, root)
        k = len(paths)
        for i, ip in enumerate(paths, 1):
            im = Image.open(ip).convert("RGB")
            strip, ntiles = tile_strip(im, max_tiles, tile_px=230)
            tiles_total += ntiles
            per_view.append(ntiles)
            rows.append((f"View {i}", [(strip, f"{ntiles} tiles of 448x448")],
                         f"{os.path.basename(ip)}\n{im.width}x{im.height} original"))
        what = (f"the {k} view images fed sequentially as 'View i:' + <image>, each one "
                f"cut by InternVL's dynamic_preprocess into the 448x448 tiles below "
                f"(red seams = tile boundaries; the last square is the whole-image "
                f"thumbnail tile). Nothing is cropped away, but each tile is an "
                f"anisotropic resize.")
        delivered = (f"delivered: {tiles_total} tiles x 256 = {tiles_total * 256} image "
                     f"tokens (per view: {per_view})")
    else:
        paths = video_paths(rec, root)
        k = len(paths)
        for i, vp in enumerate(paths, 1):
            cells = []
            try:
                vr = VideoReader(vp, ctx=cpu(0), num_threads=1)
                n = len(vr)
                fps = float(vr.get_avg_fps())
                idx = get_index(None, fps, n - 1, first_idx=0, num_segments=nframes)
                for j, fi in enumerate(idx, 1):
                    fi = int(min(max(0, int(fi)), n - 1))
                    frame = Image.fromarray(vr[fi].asnumpy()).convert("RGB")
                    # load_video() always tiles video frames with max_num=1
                    tile = delivered_tiles(frame, 1)[0]
                    cells.append((tile.resize((190, 190)),
                                  f"F{j} idx{fi} t={fi / fps:.1f}s" if fps > 0 else f"F{j}"))
                note = (f"{os.path.basename(vp)}\n{n} frames @ {fps:.1f}fps, "
                        f"{vr[0].asnumpy().shape[1]}x{vr[0].asnumpy().shape[0]}")
            except Exception as e:
                cells = [(Image.new("RGB", (190, 190), (0, 0, 0)), "decode failed")]
                note = f"{os.path.basename(vp)}\n{type(e).__name__}"
            tiles_total += len(cells)
            per_view.append(len(cells))
            rows.append((f"Video {i}", cells, note))
        what = (f"the {k} clips fed sequentially as 'Video i:' + a video block. Each cell "
                f"is one sampled frame as the model receives it: InternVL's get_index "
                f"picks {nframes} uniform frames per clip and load_video squashes each to "
                f"a single 448x448 tile (max_num=1), so wide frames are anisotropically "
                f"compressed.")
        delivered = (f"delivered: {tiles_total} tiles x 256 = {tiles_total * 256} image "
                     f"tokens (per clip: {per_view})")

    body = contact_sheet(rows, width_hint=1250)
    cap = caption_image(max(body.width, 1250),
                        caption_head(dataset, rec, k, "views" if is_img else "clips",
                                     msum, what, delivered))
    out = stack(cap, body)
    out.save(out_path, "PNG")
    return out.size, tiles_total * 256


def fig_centralized(dataset, rec, root, msum, nframes, montage_frames, cell_px,
                    max_tiles, montage_kind, out_path, zoom_path):
    """The CENTRALIZED input: the real labelled grid montage(s), then one at 1:1."""
    is_img = num_images(rec) > 0
    if is_img:
        paths = image_paths(rec, root)
        montages = build_image_montage(paths, cell_px=cell_px, label_prefix="View")
        prefix_name, cell_word = "View", "views"
    else:
        paths = video_paths(rec, root)
        T = montage_frames if montage_frames > 0 else nframes
        prefix_name = {"video": "Video", "camera": "Camera", "view": "View"}[montage_kind]
        montages = build_montages(paths, nframes=nframes, T=T, cell_px=cell_px,
                                  label_prefix=prefix_name)
        cell_word = "clips"
    k = len(paths)

    per_m = [len(delivered_tiles(m, max_tiles)) for m in montages]
    tiles_total = sum(per_m)
    # which of the nframes decoded timesteps each montage came from (real helper)
    t_idx = [0] if is_img else sample_frame_indices(nframes, len(montages))
    shown = 430 if len(montages) > 1 else 620
    cells = [(m.resize((shown, max(1, int(shown * m.height / m.width)))),
              (f"montage t{i + 1}" if is_img else
               f"montage t{i + 1} (decoded step {t_idx[i] + 1}/{nframes})")
              + f"  {m.width}x{m.height}px  {per_m[i]} tiles")
             for i, m in enumerate(montages)]
    rows = [("all montages", cells,
             f"{len(montages)} image(s)\nsent as ONE visual input")]
    what = (f"the single fused input: the {k} {cell_word} tiled into "
            f"{len(montages)} labelled grid montage(s) of {cell_px}px cells. Every cell "
            f"carries a burned-in '{prefix_name} i' band; the montage never crops, it "
            f"anisotropically squashes each whole frame into a square cell.")
    delivered = (f"delivered: {len(montages)} montage image(s) -> {tiles_total} tiles x 256 "
                 f"= {tiles_total * 256} image tokens.")
    preamble = "run-time preamble: " + ((MONTAGE_PREFIX_VIEW.format(k=k)) if is_img
                                        else MONTAGE_PREFIX_VIDEO.format(
                                            T=len(montages), k=k))
    body = contact_sheet(rows, width_hint=1250, label_pos="bottom")
    cap = caption_image(max(body.width, 1250),
                        caption_head(dataset, rec, k, "views" if is_img else "clips",
                                     msum, what, delivered, extra=[preamble]))
    out = stack(cap, body)
    out.save(out_path, "PNG")

    # --- zoom: one montage at 1:1, no resampling
    zm = montages[len(montages) // 2]
    zwhat = (f"ONE montage at 1:1 ({zm.width}x{zm.height}px), unscaled — read the "
             f"burned-in '{prefix_name} i' labels and see the anisotropic squashing "
             f"of each {cell_px}x{cell_px} cell.")
    zcap = caption_image(max(zm.width, 1250),
                         caption_head(dataset, rec, k, "views" if is_img else "clips",
                                      msum, zwhat, delivered, extra=[preamble]))
    zout = stack(zcap, zm)
    zout.save(zoom_path, "PNG")
    return out.size, zout.size, tiles_total * 256, len(montages)


def fig_frameselect(dataset, rec, root, msum, alloc, cell_px, out_path):
    """Which frames frame_select kept, and from which source clip — replayed from
    the recorded frame_alloc (the deterministic uniform candidate pool is rebuilt
    with the method's own _candidates/_resize; CLIP is not re-run)."""
    paths = video_paths(rec, root)
    k = len(paths)
    fs = FrameSelectMethod(None, budget=int(alloc.get("budget", 64)),
                           candidates_per_video=int(alloc.get("candidates_per_video", 32)),
                           cell_px=cell_px)
    times = {int(v): ts for v, ts in (alloc.get("selected_times_s") or {}).items()}
    rows, tiles_total, per_video = [], 0, {}
    for i, vp in enumerate(paths, 1):
        want = times.get(i, [])
        cands = fs._candidates(vp)          # the real uniform candidate pool
        cells = []
        for t in want:
            if not cands:
                break
            j = min(range(len(cands)),
                    key=lambda a: abs((cands[a][0] if cands[a][0] is not None else 0.0)
                                      - (t if t is not None else 0.0)))
            im = fs._resize(cands[j][1])    # the real resize the method applies
            tile = delivered_tiles(im, 1)[0]   # clip-exp leg ran max_tiles=1
            cells.append((tile.resize((118, 118)), f"t={t}s"))
        per_video[i] = len(cells)
        tiles_total += len(cells)
        if not cells:
            msg = "0 frames kept -- this clip contributed NOTHING"
            f0 = font(16, bold=True)
            blank = Image.new("RGB", (int(_MEASURE.textlength(msg, font=f0)) + 28, 118),
                              (250, 232, 232))
            ImageDraw.Draw(blank).text((14, 48), msg, fill=(165, 25, 25), font=f0)
            cells = [(blank, "")]
        rows.append((f"Video {i}", cells,
                     f"{os.path.basename(vp)}\n{per_video[i]} of "
                     f"{alloc.get('n_selected')} frames kept"))
    what = (f"the {alloc.get('n_selected')} frames frame_select actually kept out of the "
            f"{alloc.get('n_candidates')} candidates it pooled across all {k} clips "
            f"(CLIP-scored against the question with {alloc.get('clip_model')}), grouped "
            f"by source clip in temporal order. Per-clip kept: "
            f"{alloc.get('selected_per_video')}"
            + ("" if not alloc.get("selection_fallback")
               else f"  [FALLBACK: {alloc['selection_fallback']}]"))
    if len(paths) * int(alloc.get("candidates_per_video", 32)) <= int(alloc.get("budget", 64)):
        what += ("   NOTE: the candidate pool is <= the budget here, so selection "
                 "degenerates to 'keep everything'.")
    delivered = (f"delivered: {tiles_total} frames as separate IMAGE inputs, 1 tile each "
                 f"(max_tiles=1 on the clip-experiment leg) = {tiles_total * 256} image "
                 f"tokens; each frame is resized to <= {cell_px}px then squashed to "
                 f"448x448.")
    body = contact_sheet(rows, width_hint=1250)
    cap = caption_image(max(body.width, 1250),
                        caption_head(dataset, rec, k, "clips", msum, what, delivered))
    out = stack(cap, body)
    out.save(out_path, "PNG")
    return out.size, tiles_total * 256


def fig_frameselect_slide(dataset, rec, root, msum, alloc, cell_px, out_path,
                          max_cells=6, cell=220):
    """Slide-friendly re-render of fig_frameselect: at most ``max_cells`` large
    thumbnails per clip (evenly subsampled from the kept frames), a verdict
    banner, and the gold clip highlighted. Same recorded frame_alloc replay —
    CLIP is not re-run and nothing is re-selected."""
    import re as _re
    paths = video_paths(rec, root)
    fs = FrameSelectMethod(None, budget=int(alloc.get("budget", 64)),
                           candidates_per_video=int(alloc.get("candidates_per_video", 32)),
                           cell_px=cell_px)
    times = {int(v): ts for v, ts in (alloc.get("selected_times_s") or {}).items()}
    gold_letter = str(rec.get("answer", "")).strip().upper()
    gold_opt = next((str(o).strip() for o in rec.get("options", [])
                     if str(o).strip().upper().startswith((gold_letter + ".",
                                                           gold_letter + ")"))), "")
    gm = _re.search(r"VIDEO\s+(\d+)", gold_opt.upper())
    gold_v = int(gm.group(1)) if gm else None
    fsum = msum.get("frame_select") or {}
    n_pass, n_ok = fsum.get("n") or 0, fsum.get("correct") or 0
    good = n_pass > 0 and n_ok == n_pass
    GREEN, GREEN_BG = (23, 105, 46), (223, 240, 225)
    RED, RED_BG = (165, 25, 25), (250, 229, 229)
    INK, MUT = (18, 18, 18), (95, 95, 95)

    LEFT, PAD, GAP = 330, 12, 16
    width = LEFT + max_cells * cell + (max_cells - 1) * PAD + 24
    f_q, f_sub, f_ban = font(30, bold=True), font(21), font(26, bold=True)
    f_row, f_note, f_t = font(26, bold=True), font(19), font(16)

    row_imgs = []
    for i, vp in enumerate(paths, 1):
        want = list(times.get(i, []))
        shown = want
        if len(want) > max_cells:
            idx = sorted({round(j * (len(want) - 1) / (max_cells - 1))
                          for j in range(max_cells)})
            shown = [want[j] for j in idx]
        cands = fs._candidates(vp) if shown else []
        cells = []
        for t in shown:
            if not cands:
                break
            j = min(range(len(cands)),
                    key=lambda a: abs((cands[a][0] if cands[a][0] is not None else 0.0)
                                      - (t if t is not None else 0.0)))
            tile = delivered_tiles(fs._resize(cands[j][1]), 1)[0]
            cells.append((tile.resize((cell, cell)), f"t={t}s"))
        row_imgs.append((i, len(want), cells))

    q_lines = wrap_px("Q: " + rec["question"], f_q, width - 40)
    banner_h = 56
    head_h = 16 + len(q_lines) * (f_q.size + 6) + 10 + f_sub.size + 18 + banner_h + 14
    row_h = cell + 12
    height = head_h + len(row_imgs) * (row_h + GAP) + 44

    im = Image.new("RGB", (width, height), (250, 250, 248))
    d = ImageDraw.Draw(im)
    y = 16
    for ln in q_lines:
        d.text((20, y), ln, fill=INK, font=f_q)
        y += f_q.size + 6
    preds = ",".join(fsum.get("preds") or [])
    d.text((20, y + 4),
           f"gold: {gold_letter}. {gold_opt.split('.', 1)[-1].strip()}   |   "
           f"CLIP sampler kept {alloc.get('n_selected')} of "
           f"{alloc.get('n_candidates')} candidate frames   |   "
           f"sampler-arm answers: [{preds}]", fill=MUT, font=f_sub)
    y += f_sub.size + 18
    if good:
        btxt = (f"GOOD CASE — every clip keeps frames; the model answered "
                f"correctly on {n_ok}/{n_pass} passes")
        bfg, bbg = GREEN, GREEN_BG
    else:
        btxt = (f"FAILURE — the sampler kept 0 frames of the GOLD clip "
                f"(Video {gold_v}); the model was wrong on all {n_pass} passes")
        bfg, bbg = RED, RED_BG
    d.rectangle([12, y, width - 12, y + banner_h], fill=bbg, outline=bfg, width=3)
    d.text((28, y + (banner_h - f_ban.size) // 2 - 2), btxt, fill=bfg, font=f_ban)
    y += banner_h + 14

    for i, n_kept, cells in row_imgs:
        is_gold = (i == gold_v)
        band = GREEN_BG if (is_gold and n_kept) else (RED_BG if is_gold
                                                      else (238, 238, 244))
        d.rectangle([0, y, LEFT - 10, y + row_h - 1], fill=band)
        d.text((16, y + 10), f"Video {i}", fill=INK, font=f_row)
        ny = y + 10 + f_row.size + 8
        if is_gold:
            label(d, (16, ny), "GOLD" if n_kept else "GOLD — DELETED",
                  font(20, bold=True), fill=(255, 255, 255),
                  bg=(GREEN if n_kept else RED), pad=6)
            ny += 40
        note = (f"{n_kept} of {alloc.get('n_selected')} frames kept"
                + (f" — showing {len(cells)}" if n_kept > len(cells) else ""))
        for lnn in wrap_px(note, f_note, LEFT - 32):
            d.text((16, ny), lnn, fill=MUT, font=f_note)
            ny += f_note.size + 4
        x = LEFT
        if cells:
            for cimg, clabel in cells:
                im.paste(cimg, (x, y))
                d.rectangle([x, y, x + cell - 1, y + cell - 1],
                            outline=(175, 175, 175))
                label(d, (x + 4, y + cell - f_t.size - 12), clabel, f_t)
                x += cell + PAD
        else:
            bw = max_cells * cell + (max_cells - 1) * PAD
            d.rectangle([x, y, x + bw - 1, y + cell - 1], fill=RED_BG,
                        outline=RED, width=4)
            msg1 = "0 frames kept — the sampler deleted the evidence"
            msg2 = f"(this clip is the gold answer: {gold_letter}. Video {i})"
            fm1, fm2 = font(30, bold=True), font(22)
            d.text((int(x + (bw - _MEASURE.textlength(msg1, font=fm1)) // 2),
                    y + cell // 2 - 40), msg1, fill=RED, font=fm1)
            d.text((int(x + (bw - _MEASURE.textlength(msg2, font=fm2)) // 2),
                    y + cell // 2 + 6), msg2, fill=RED, font=fm2)
        if is_gold:
            d.rectangle([0, y, width - 1, y + row_h - 1],
                        outline=(GREEN if n_kept else RED), width=4)
        y += row_h + GAP
    d.text((20, y + 4), "Frames shown are the actual recorded selection "
                        "(frame_alloc replay); CLIP scores not re-run.",
           fill=MUT, font=font(16))
    im.save(out_path, "PNG")
    return im.size


# --------------------------------------------------------------------------- #


def main():
    ap = argparse.ArgumentParser(
        description="Export the literal visual inputs of each method (CPU only).")
    ap.add_argument("--out", default=DEF_OUT)
    ap.add_argument("--aab-subset", default=DEF_AAB_SUBSET)
    ap.add_argument("--aab-root", default=DEF_AAB_ROOT)
    ap.add_argument("--mvu-subset", default=DEF_MVU_SUBSET)
    ap.add_argument("--mvu-root", default=DEF_MVU_ROOT)
    ap.add_argument("--aab-results", default=DEF_AAB_RESULTS,
                    help="comma-separated globs of result JSONLs (All-Angles leg)")
    ap.add_argument("--mvu-results", default=DEF_MVU_RESULTS,
                    help="comma-separated globs of result JSONLs (MVU-Eval legs)")
    ap.add_argument("--backend", default="InternVL3-8B",
                    help="only read result rows from this backend ('' = all)")
    ap.add_argument("--aab-ids", default=DEF_AAB_IDS)
    ap.add_argument("--mvu-ids", default=DEF_MVU_IDS)
    ap.add_argument("--auto-pick", action="store_true",
                    help="ignore --*-ids; re-derive the low/high view-count questions "
                         "with the largest method disagreement")
    ap.add_argument("--nframes", type=int, default=8)
    ap.add_argument("--montage-frames", type=int, default=4,
                    help="centralized montages per MVU question (the real runs used 4)")
    ap.add_argument("--cell-px", type=int, default=448)
    ap.add_argument("--montage-kind", default="video", choices=["camera", "video", "view"],
                    help="montage cell labels for MVU-Eval (still-image records always "
                         "use 'View'); the real runs used 'video'")
    ap.add_argument("--internvl-max-tiles", type=int, default=4,
                    help="tiles per IMAGE input on the native/centralized leg")
    ap.add_argument("--copy-media", dest="copy_media", action="store_true", default=True)
    ap.add_argument("--no-copy-media", dest="copy_media", action="store_false")
    ap.add_argument("--media-ids", default=DEF_MEDIA_IDS,
                    help="comma list of ds:id to copy raw media for ('all' = every example)")
    ap.add_argument("--media-budget-mb", type=float, default=200.0)
    ap.add_argument("--verify-tokens", dest="verify", action="store_true", default=True)
    ap.add_argument("--no-verify-tokens", dest="verify", action="store_false")
    args = ap.parse_args()

    global BACKEND_LABEL
    os.makedirs(args.out, exist_ok=True)
    backend = args.backend or None
    BACKEND_LABEL = backend or "all backends"

    aab_recs = {r["id"]: r for r in json.load(open(args.aab_subset))}
    mvu_recs = {r["id"]: r for r in json.load(open(args.mvu_subset))}
    aab_q = by_question(load_rows(args.aab_results.split(","), backend))
    mvu_q = by_question(load_rows(args.mvu_results.split(","), backend))

    if args.auto_pick:
        aab_ids = auto_pick(aab_q, aab_recs, 2, 5)
        mvu_ids = auto_pick(mvu_q, mvu_recs, 2, 8)
    else:
        aab_ids = [int(x) for x in args.aab_ids.split(",") if x.strip() != ""]
        mvu_ids = [int(x) for x in args.mvu_ids.split(",") if x.strip() != ""]

    manifest = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": REPO,
        "generator": "bench/make_input_examples.py",
        "backend_of_result_rows": backend,
        "run_config_used_for_rendering": {
            "nframes": args.nframes, "cell_px": args.cell_px,
            "montage_frames_mvu": args.montage_frames,
            "montage_kind_mvu": args.montage_kind,
            "montage_kind_allangles": "view (forced by the code for still-image records)",
            "internvl_max_tiles_native_centralized": args.internvl_max_tiles,
            "internvl_max_tiles_clip_experiment": 1,
            "note": ("recovered from the completed InternVL3-8B rows by matching "
                     "input_tokens-video_tokens against the InternVL3 tokenizer and "
                     "video_tokens/256 against dynamic_preprocess tile counts"),
        },
        "questions": [],
        "source_media": {},
    }

    todo = ([("aab", i, aab_recs, aab_q, args.aab_root, "All-Angles-Bench (EgoHumans stills)")
             for i in aab_ids]
            + [("mvu", i, mvu_recs, mvu_q, args.mvu_root, "MVU-Eval dev (videos)")
               for i in mvu_ids])

    print(f"out={args.out}\nexamples: "
          f"aab={aab_ids} mvu={mvu_ids} (auto_pick={args.auto_pick})\n")

    for ds, qid, recs, qmap, root, dsname in todo:
        rec = recs.get(qid)
        if rec is None:
            print(f"!! {ds}:{qid} not in subset — skipped")
            continue
        qrows = qmap.get(qid, {})
        msum = method_summary(qrows)
        is_img = num_images(rec) > 0
        paths = image_paths(rec, root) if is_img else video_paths(rec, root)
        k = len(paths)
        stem = os.path.join(args.out, f"{ds}_{qid}")
        entry = {"dataset": ds, "dataset_name": dsname, "id": qid,
                 "task_type": rec.get("task_type"),
                 "question_type": rec.get("question_type"),
                 "num_views": k, "modality": "images" if is_img else "videos",
                 "question": rec["question"], "options": rec["options"],
                 "gold": rec["answer"],
                 "method_disagreement_spread": round(spread(msum), 3),
                 "method_results": msum, "figures": {}, "views": [],
                 "token_check": {}}

        s1, tok1 = fig_native(dsname, rec, root, msum, args.nframes,
                              args.internvl_max_tiles, args.cell_px,
                              stem + "_native.png")
        entry["figures"]["native"] = os.path.basename(stem + "_native.png")
        s2, s3, tok2, nm = fig_centralized(
            dsname, rec, root, msum, args.nframes,
            args.montage_frames if not is_img else 0, args.cell_px,
            args.internvl_max_tiles, args.montage_kind,
            stem + "_centralized.png", stem + "_montage_zoom.png")
        entry["figures"]["centralized"] = os.path.basename(stem + "_centralized.png")
        entry["figures"]["montage_zoom"] = os.path.basename(stem + "_montage_zoom.png")
        print(f"{ds}:{qid} K={k}  native{s1} centralized{s2} zoom{s3}")

        tok3 = None
        if not is_img:
            fsrows = qrows.get("frame_select") or []
            alloc = next((r.get("frame_alloc") for r in fsrows if r.get("frame_alloc")), None)
            if alloc:
                s4, tok3 = fig_frameselect(dsname, rec, root, msum, alloc,
                                           args.cell_px, stem + "_frameselect.png")
                entry["figures"]["frame_select"] = os.path.basename(
                    stem + "_frameselect.png")
                entry["frame_select_alloc"] = alloc
                print(f"        frameselect{s4}")
                s5 = fig_frameselect_slide(dsname, rec, root, msum, alloc,
                                           args.cell_px,
                                           stem + "_frameselect_slide.png")
                entry["figures"]["frame_select_slide"] = os.path.basename(
                    stem + "_frameselect_slide.png")
                print(f"        frameselect_slide{s5}")
            else:
                print(f"        (no frame_alloc row for {qid}; frameselect skipped)")

        if args.verify:
            for mname, computed in (("cvbench_native", tok1), ("centralized", tok2),
                                    ("frame_select", tok3)):
                rec_tok = (msum.get(mname) or {}).get("video_tokens")
                if computed is None or rec_tok is None:
                    continue
                ok = (computed == rec_tok)
                entry["token_check"][mname] = {
                    "rendered_image_tokens": computed,
                    "recorded_video_tokens": rec_tok, "match": ok}
                print(f"        token check {mname:15s} rendered={computed:6d} "
                      f"recorded={rec_tok:6d}  {'MATCH' if ok else 'MISMATCH'}")

        for i, p in enumerate(paths, 1):
            meta = image_meta(p) if is_img else clip_meta(p)
            slot = (f"image_{i}" if is_img else f"video_{i}")
            entry["views"].append({
                "slot": slot, "label": (f"View {i}" if is_img else f"Video {i}"),
                "source_rel": rec.get(slot), "source_abs": p,
                "bytes": os.path.getsize(p) if os.path.exists(p) else None,
                "media": meta,
                "what_it_is": describe_view(ds, rec.get(slot) or "", i, meta)})
        manifest["questions"].append(entry)

    # ------------------------------------------------------------------ media
    if args.copy_media:
        mdir = os.path.join(args.out, "source_media")
        os.makedirs(mdir, exist_ok=True)
        wanted = args.media_ids.strip()
        keys = ([f"{q['dataset']}:{q['id']}" for q in manifest["questions"]]
                if wanted == "all" else [w.strip() for w in wanted.split(",") if w.strip()])
        copied, skipped, total = [], [], 0
        budget = args.media_budget_mb * 1e6
        for q in manifest["questions"]:
            key = f"{q['dataset']}:{q['id']}"
            if key not in keys:
                skipped.append({"question": key, "reason": "not in --media-ids"})
                continue
            size = sum(v["bytes"] or 0 for v in q["views"])
            if total + size > budget:
                skipped.append({"question": key, "reason": "over --media-budget-mb",
                                "bytes": size})
                continue
            sub = os.path.join(mdir, f"{q['dataset']}_{q['id']}")
            os.makedirs(sub, exist_ok=True)
            for v in q["views"]:
                if not v["source_abs"] or not os.path.exists(v["source_abs"]):
                    continue
                name = os.path.basename(v["source_abs"])
                dst = os.path.join(sub, name)
                if os.path.exists(dst) and os.path.getsize(dst) != (v["bytes"] or -1):
                    name = f"{v['slot']}_{name}"
                    dst = os.path.join(sub, name)
                shutil.copy2(v["source_abs"], dst)
                v["copied_to"] = os.path.relpath(dst, args.out)
            total += size
            copied.append({"question": key, "bytes": size,
                           "dir": os.path.relpath(sub, args.out)})
            print(f"media {key}: {size / 1e6:.1f} MB -> {os.path.relpath(sub, args.out)}")
        manifest["source_media"] = {"copied": copied, "skipped": skipped,
                                    "total_bytes": total,
                                    "total_mb": round(total / 1e6, 1),
                                    "budget_mb": args.media_budget_mb}

    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(f"\nwrote -> {args.out}")
    print(f"manifest -> {os.path.join(args.out, 'manifest.json')}")


if __name__ == "__main__":
    main()
