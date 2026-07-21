"""Generate every figure for the CVBench Obsidian bundle, written straight into
bench/results/cvbench_obsidian/ with descriptive names so Obsidian ![[...]] embeds
resolve. Produces:

  cvbench_headtohead.png       MEVA vs CVBench (copied/redrawn)
  cvbench_accuracy.png         overall + by video-count (native vs stitch)
  cvbench_montage_anatomy.png  one montage (independent clips tiled together)
  cvbench_ex{ID}_native.png    per-example native input (k clips x 16 frames)
  cvbench_ex{ID}_stitch.png    per-example stitch input (16 montages)

Run from repo root:  python -m bench.cvbench_report_figs
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
from decord import VideoReader, cpu

from .methods.stitch import build_montages, sample_frame_indices

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results", "cvbench_obsidian")
os.makedirs(OUT, exist_ok=True)
VR = os.path.join(HERE, "..", "Video-R1", "src", "r1-v", "Evaluation", "CVBench")
SUB = {r["id"]: r for r in json.load(open(os.path.join(HERE, "..", "analysis", "cvbench_temporal_subset.json")))}
FONT = ImageFont.load_default()
NATIVE, CAMERA, VIDEO = "#7f7f7f", "#1f77b4", "#2ca02c"
STITCH = CAMERA  # back-compat
EXAMPLES = ["cvb-16", "cvb-28", "cvb-471"]
RES = os.path.join(HERE, "results")
P_NAT = os.path.join(RES, "cvbench_temporal_native.jsonl")
P_CAM = os.path.join(RES, "cvbench_temporal_stitch.jsonl")              # Camera-labeled
P_VID = os.path.join(RES, "cvbench_temporal_stitch_videolabels.jsonl")  # Video-labeled (corrected)
P_MEVA = os.path.join(RES, "exp64_internvl.jsonl")                      # MEVA: native + centralized


def _load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def _load_by_id(path):
    return {r["id"]: r for r in _load(path)}


def _acc(rows):
    rows = list(rows)
    return 100 * sum(1 for r in rows if r.get("correct")) / len(rows) if rows else float("nan")


def vids(r):
    return [r[k] for k in ["video_1", "video_2", "video_3", "video_4"] if r.get(k)]


def _label(draw, xy, text, bg=(20, 20, 20)):
    x, y = xy
    w = draw.textlength(text, font=FONT)
    draw.rectangle([x, y, x + w + 6, y + 14], fill=bg)
    draw.text((x + 3, y + 2), text, fill=(255, 255, 255), font=FONT)


# ---- head-to-head (redrawn here so the bundle is self-contained) ----
def headtohead():
    """MEVA vs CVBench, native vs both stitch labelings — computed from the jsonl.
    MEVA has no Video-labeled run (its cameras genuinely ARE synchronized, so
    'Camera' is the truthful label there); that bar is left blank."""
    meva = _load(P_MEVA)
    m_nat = _acc(r for r in meva if r["method"] == "cvbench_native")
    m_cam = _acc(r for r in meva if r["method"] == "centralized")
    nat, cam, vid = _load_by_id(P_NAT), _load_by_id(P_CAM), _load_by_id(P_VID)
    c_nat, c_cam, c_vid = _acc(nat.values()), _acc(cam.values()), _acc(vid.values())

    groups = ["MEVA\n(4 synchronized cameras,\none scene)", "CVBench\n(2-4 independent clips,\ndifferent scenes)"]
    native_v = [m_nat, c_nat]
    camera_v = [m_cam, c_cam]
    video_v = [float("nan"), c_vid]   # MEVA: no Video-labeled run
    x = range(2); w = 0.27
    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    bars = [
        ax.bar([i - w for i in x], native_v, w, label="CVBench-native (sequential clips)", color=NATIVE),
        ax.bar([i for i in x], camera_v, w, label="Stitch — Camera-labeled", color=CAMERA),
        ax.bar([i + w for i in x], video_v, w, label="Stitch — Video-labeled (corrected)", color=VIDEO),
    ]
    ax.axhline(25, ls="--", color="red", alpha=0.5); ax.text(1.30, 26, "chance ~25%", color="red", fontsize=9)
    for grp in bars:
        for r in grp:
            h = r.get_height()
            if h == h:  # skip nan
                ax.text(r.get_x()+r.get_width()/2, h+0.7, f"{h:.1f}%", ha="center", fontsize=9, weight="bold")
    ax.text(0 + w, 2.0, "n/a\n(synced)", ha="center", va="bottom", fontsize=8, color="#999")
    ax.annotate(f"stitch +{m_cam-m_nat:.0f}", (0, m_cam+3.0), ha="center", color=CAMERA, fontsize=10, weight="bold")
    ax.annotate(f"stitch +{c_vid-c_nat:.1f}", (1 + w, c_vid+3.0), ha="center", color=VIDEO, fontsize=10, weight="bold")
    ax.set_xticks(list(x)); ax.set_xticklabels(groups); ax.set_ylabel("Accuracy (%)"); ax.set_ylim(0, 70)
    ax.set_title("Stitching wins on both datasets — with the truthful montage label\nCamera for MEVA's synced views, Video for CVBench's independent clips (InternVL3-8B)")
    ax.legend(); ax.grid(axis="y", alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(OUT, "cvbench_headtohead.png"), dpi=150); plt.close(fig)


def accuracy():
    """CVBench overall + by video-count: native vs Camera-labeled vs Video-labeled stitch."""
    nat, cam, vid = _load_by_id(P_NAT), _load_by_id(P_CAM), _load_by_id(P_VID)
    ids = list(nat)
    def nv(i):
        return nat[i].get("num_videos") or nat[i].get("orig_num_cameras")
    sels = [("Overall\n(130)", lambda i: True),
            ("2 videos\n(48)", lambda i: nv(i) == 2),
            ("3 videos\n(23)", lambda i: nv(i) == 3),
            ("4 videos\n(59)", lambda i: nv(i) == 4)]
    groups = [s[0] for s in sels]
    def series(d):
        return [_acc(d[i] for i in ids if sel(i)) for _, sel in sels]
    nat_v, cam_v, vid_v = series(nat), series(cam), series(vid)
    x = range(len(sels)); w = 0.27
    fig, ax = plt.subplots(figsize=(10, 5.6))
    bars = [
        ax.bar([i - w for i in x], nat_v, w, label="CVBench-native", color=NATIVE),
        ax.bar([i for i in x], cam_v, w, label="Stitch — Camera-labeled", color=CAMERA),
        ax.bar([i + w for i in x], vid_v, w, label="Stitch — Video-labeled (corrected)", color=VIDEO),
    ]
    ax.axhline(25, ls="--", color="red", alpha=0.5); ax.text(3.25, 26, "chance ~25%", color="red", fontsize=9)
    for grp in bars:
        for r in grp:
            h = r.get_height()
            if h == h:
                ax.text(r.get_x()+r.get_width()/2, h+0.7, f"{h:.0f}%", ha="center", fontsize=8)
    ax.set_xticks(list(x)); ax.set_xticklabels(groups); ax.set_ylabel("Accuracy (%)"); ax.set_ylim(0, 78)
    ax.set_title("Relabeling montage cells Camera→Video flips stitch above native (identical pixels)\nInternVL3-8B · 130 CVBench temporal-logic questions")
    ax.legend(); ax.grid(axis="y", alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(OUT, "cvbench_accuracy.png"), dpi=150); plt.close(fig)


def native_grid(rec, out, cell=150):
    paths = [os.path.join(VR, v) for v in vids(rec)]
    rows = []
    for vp in paths:
        try:
            vr = VideoReader(vp, ctx=cpu(0), num_threads=1)
            idx = sample_frame_indices(len(vr), 16)
            rows.append([Image.fromarray(vr[i].asnumpy()).convert("RGB") for i in idx])
        except Exception:
            rows.append([Image.new("RGB", (cell, cell), (0, 0, 0))] * 16)
    ch = int(cell * 0.6); lblw = 70
    canvas = Image.new("RGB", (lblw + 16 * cell, len(rows) * ch), (245, 245, 245))
    d = ImageDraw.Draw(canvas)
    for r, frames in enumerate(rows):
        y = r * ch
        _label(d, (4, y + ch//2 - 7), f"Video {r+1}", bg=(40, 60, 120))
        for c, fr in enumerate(frames):
            canvas.paste(fr.resize((cell, ch)), (lblw + c*cell, y))
            if r == 0: _label(d, (lblw + c*cell + 2, 2), f"t{c+1}")
    canvas.save(out, "PNG")


def stitch_sheet(rec, out, per=270):
    paths = [os.path.join(VR, v) for v in vids(rec)]
    montages = build_montages(paths, nframes=16, T=16, cell_px=448, label_prefix="Video")
    cols = 4; rows = (len(montages)+cols-1)//cols
    canvas = Image.new("RGB", (cols*per, rows*per), (245, 245, 245))
    d = ImageDraw.Draw(canvas)
    for i, m in enumerate(montages):
        r, c = divmod(i, cols)
        canvas.paste(m.resize((per, per)), (c*per, r*per))
        _label(d, (c*per+3, r*per+3), f"montage t{i+1}", bg=(120, 40, 40))
    canvas.save(out, "PNG")
    return montages


def main():
    headtohead(); accuracy()
    zoom = False
    for i in EXAMPLES:
        rec = SUB[i]; sid = i.replace("cvb-", "")
        native_grid(rec, os.path.join(OUT, f"cvbench_ex{sid}_native.png"))
        montages = stitch_sheet(rec, os.path.join(OUT, f"cvbench_ex{sid}_stitch.png"))
        print(f"{i}: k={rec['orig_num_cameras']} montages={len(montages)}")
        if not zoom:
            montages[len(montages)//2].save(os.path.join(OUT, "cvbench_montage_anatomy.png"), "PNG")
            zoom = True
    print("wrote figures ->", OUT)


if __name__ == "__main__":
    main()
