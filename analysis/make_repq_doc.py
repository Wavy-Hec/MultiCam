"""Build the representative-questions doc requested by the mentor (2026-08-01).

One self-contained HTML (deck-style, data-URI images) with:
  - every MVU-Eval category (8) and All-Angles category (6): a composition
    fact panel + 2-3 verbatim representative questions with media thumbnails;
  - Appendix A: the CLIP frame-sampler answers (encoder, no thresholds,
    quantitative alignment, 4 qualitative contact sheets);
  - Appendix B: the selection methodology, verbatim.

Question selection is DETERMINISTIC and RESULTS-BLIND: picks use only dataset
text/metadata (never model accuracy), there is no RNG anywhere, and the rules
are printed in the doc itself.  Numbers in fact panels come exclusively from
analysis/slide_stats.json and analysis/sampler_diag.json — nothing is computed
inside the rendering code except dataset-text composition facts.

Usage:
  python3 analysis/make_repq_doc.py --list-sampler-ids     # print the 4 QE ids
  python3 analysis/make_repq_doc.py                        # build everything
  python3 analysis/make_repq_doc.py --verify               # re-check the build
"""
import argparse
import base64
import glob
import html
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RES = os.path.join(REPO, "bench", "results")
sys.path.insert(0, HERE)

from build_singleview_subset import NAMES_VIDEO                   # noqa: E402
from clip_selection_diagnostic import VIDEO_RE, gold_option_video  # noqa: E402
from mvueval_slide_stats import NUSC, load_rows                    # noqa: E402

MVU_POOL = os.path.join(HERE, "mvueval_qa.json")
AAB_POOL = os.path.join(HERE, "allangles_qa.json")
AAB_EGO_POOL = os.path.join(HERE, "allangles_egohumans_qa.json")
STATS = os.path.join(HERE, "slide_stats.json")
DIAG = os.path.join(HERE, "sampler_diag.json")
GATE = os.path.join(RES, "clip_scorer_gate.json")
MVU_MEDIA = os.path.join(REPO, "data", "mvueval")
AAB_MEDIA = os.path.join(REPO, "data", "allangles")

# category display names follow the July-28 slides; codes are MVU-Eval's own
MVU_NAMES = {
    "MVU-TR": "Temporal reasoning", "MVU-RAG": "Retrieval (RAG)",
    "MVU-KIR": "Knowledge reasoning (KIR)", "MVU-Counting": "Counting",
    "MVU-SU": "Spatial understanding", "MVU-ICL": "In-context learning",
    "MVU-Comparison": "Comparison", "MVU-OR": "Object recognition",
}
SCANNET = re.compile(r"^scene\d{4}_\d{2}\.mp4$")
DIR_FAMILY = {
    "temp_grounding-videos": "temporal-grounding",
    "temp_ordering-videos": "temporal-ordering",
    "temp_cap_filling-videos": "caption-filling",
    "video_editing-video": "video-editing",
}
MVU_METHODS = ["blind", "cvbench_native", "centralized", "per_stream",
               "frame_select", "clip_select_top1", "temporal_weighted"]
AAB_METHODS = ["blind", "cvbench_native", "centralized", "per_stream"]
METHOD_LABEL = {
    "blind": "blind", "cvbench_native": "sequential",
    "centralized": "stitching", "per_stream": "decentralized",
    "frame_select": "frame_select", "clip_select_top1": "clip_top1",
    "temporal_weighted": "temporal",
}
LONG_Q = 1500          # chars before a question collapses behind <details>
MAX_THUMBS = 8


# ------------------------------------------------------------ dataset facts
def vids_of(rec):
    return [rec[f"video_{i}"] for i in range(1, 14) if rec.get(f"video_{i}")]


def imgs_of(rec):
    return [v for k, v in sorted(rec.items()) if k.startswith("image_")]


def source_family(vname):
    if NUSC.match(vname):
        return "nuScenes"
    if SCANNET.match(vname):
        return "ScanNet"
    if "/" in vname:
        return DIR_FAMILY.get(vname.split("/")[0], "YouTube/other")
    return "YouTube/other"


def family_sig(rec):
    return " + ".join(sorted({source_family(v) for v in vids_of(rec)}))


_PARENT = re.compile(r"(.+?)_(?:event|clip|clips|segment)[_\d]")


def same_parent_segments(recs):
    """Non-sync questions whose clips are all segments cut from ONE source
    video (the temp_grounding/temp_ordering construction)."""
    n = 0
    for r in recs:
        vs = vids_of(r)
        if len(vs) >= 2 and all(NUSC.match(v) for v in vs):
            continue
        ps = [_PARENT.match(v.rsplit("/", 1)[-1]) for v in vs]
        if len(ps) > 1 and all(ps) and len({m.group(1) for m in ps}) == 1:
            n += 1
    return n


def q_flags(rec):
    body = re.compile(r"^[A-M]\.\s*")
    opts = [body.sub("", o).strip().casefold() for o in rec["options"]]
    vids = vids_of(rec)
    return {
        "names_video": any(NAMES_VIDEO.search(t)
                           for t in [rec["question"]] + list(rec["options"])),
        "ident_options": any(VIDEO_RE.search(o) for o in rec["options"]),
        "dup_options": len(set(opts)) < len(opts),
        "many_options": len(rec["options"]) > 6,
        "is_sync": len(vids) >= 2 and all(NUSC.match(v) for v in vids),
    }


FLAG_LABEL = {
    "names_video": "text/options name a specific video",
    "ident_options": "answer options are video identities",
    "dup_options": "duplicated option text",
    "many_options": "more than 6 options",
}


def composition(recs, video=True):
    n = len(recs)
    kdist = Counter(len(vids_of(r)) if video else len(imgs_of(r)) for r in recs)
    flags = {k: sum(q_flags(r)[k] for r in recs)
             for k in ("names_video", "ident_options", "dup_options",
                       "many_options", "is_sync")}
    return {
        "n": n,
        "k_dist": dict(sorted(kdist.items())),
        "families": dict(Counter(family_sig(r) for r in recs).most_common())
        if video else {},
        "flag_counts": flags,
        "chance": round(sum(100.0 / len(r["options"]) for r in recs) / n, 1),
        "opt_mode": Counter(len(r["options"]) for r in recs).most_common(1)[0][0],
    }


# ------------------------------------------------- deterministic selection
def median_by_qlen(recs):
    rs = sorted(recs, key=lambda r: (len(r["question"]), r["id"]))
    return rs[len(rs) // 2]


def pick_mvu(cat_recs):
    """Slots A (modal exemplar) / B (dominant defect >=20%) / C (sync)."""
    picks, taken = [], set()

    kdist = Counter(len(vids_of(r)) for r in cat_recs)
    k_star = min(k for k, c in kdist.items() if c == max(kdist.values()))
    stratum = [r for r in cat_recs if len(vids_of(r)) == k_star]
    sigs = Counter(family_sig(r) for r in stratum)
    sig_star = min(s for s, c in sigs.items() if c == max(sigs.values()))
    stratum = [r for r in stratum if family_sig(r) == sig_star]
    a = median_by_qlen(stratum)
    picks.append((a, "modal exemplar",
                  f"modal K={k_star}, modal sources '{sig_star}', "
                  f"median question length"))
    taken.add(a["id"])

    rates = {k: sum(q_flags(r)[k] for r in cat_recs) / len(cat_recs)
             for k in FLAG_LABEL}
    flag, rate = max(rates.items(), key=lambda kv: kv[1])
    if rate >= 0.20:
        cands = [r for r in cat_recs if q_flags(r)[flag] and r["id"] not in taken]
        if cands:
            b = median_by_qlen(cands)
            picks.append((b, f"defect: {FLAG_LABEL[flag]} ({rate:.0%})",
                          f"median-length among the {rate:.0%} flagged "
                          f"'{flag}' records, excluding earlier slots' picks"))
            taken.add(b["id"])

    sync = [r for r in cat_recs if q_flags(r)["is_sync"]]
    if sync:
        cands = [r for r in sync if r["id"] not in taken]
        if cands:
            c = median_by_qlen(cands)
            picks.append((c, "sync-slice exemplar",
                          "median-length among the category's synchronized "
                          "nuScenes 6-camera questions, excluding earlier "
                          "slots' picks"))
        else:
            picks = [(r, tag + " · also sync", rule) if r["id"] in
                     {s["id"] for s in sync} else (r, tag, rule)
                     for r, tag, rule in picks]
    return picks


def pick_aab(cat_recs):
    """Slots A/B from EgoHumans (media on disk) + T text-only Ego-Exo4D."""
    picks = []
    ego = [r for r in cat_recs if r.get("source") == "EgoHumans"]
    exo = [r for r in cat_recs if r.get("source") != "EgoHumans"]
    if ego:
        kdist = Counter(len(imgs_of(r)) for r in ego)
        k_star = min(k for k, c in kdist.items() if c == max(kdist.values()))
        a = median_by_qlen([r for r in ego if len(imgs_of(r)) == k_star])
        picks.append((a, "modal exemplar (EgoHumans)",
                      f"modal K={k_star} among EgoHumans, median length"))
        far = max(kdist) if k_star != max(kdist) else min(kdist)
        if far != k_star:
            cands = [r for r in ego if len(imgs_of(r)) == far
                     and r["id"] != a["id"]]
            if cands:
                b = median_by_qlen(cands)
                picks.append((b, f"far view-count exemplar (K={far})",
                              f"median-length at the far view count {far}"))
    if exo:
        kdist = Counter(len(imgs_of(r)) for r in exo)
        k_star = min(k for k, c in kdist.items() if c == max(kdist.values()))
        t = median_by_qlen([r for r in exo if len(imgs_of(r)) == k_star])
        picks.append((t, "Ego-Exo4D exemplar — text only (license pending)",
                      f"modal K={k_star} among Ego-Exo4D, median length"))
    return picks


def pick_sampler_ids(diag):
    """QE-aligned / QE-typical / QE-missed / QE-degenerate from frame_select's
    per-question gold-named shares. Universe U: gold option names exactly one
    video, K>=3, candidate pool exceeds the budget (non-degenerate)."""
    pq = {int(i): d for i, d in
          diag["frame_select"]["per_question_gold_named"].items()}
    U = {i: d for i, d in pq.items()
         if d["K"] >= 3 and d["n_candidates"] > d["budget"]}
    out = {}
    out["aligned"] = sorted(U, key=lambda i: (-U[i]["share"], i))[0]
    order = sorted(U, key=lambda i: (U[i]["share"], i))
    out["typical"] = order[len(order) // 2]
    missed = [i for i, d in U.items()
              if d["selected_per_video"].get(str(d["named"]), 0) == 0]
    out["missed"] = sorted(missed, key=lambda i: (-U[i]["K"], i))[0]
    out["degenerate"] = min(i for i, d in pq.items() if d["K"] == 2)
    assert len(set(out.values())) == 4, f"sampler picks collide: {out}"
    return out


# ------------------------------------------------------------ results join
def load_chips(picked_mvu, picked_aab):
    globs_mvu = ["bench_mvueval_qa_internvl_mvufull_shard*.jsonl",
                 "bench_mvueval_qa_internvl_mvufullclip_shard*.jsonl",
                 "bench_mvueval_qa_internvl_mvublind*shard*.jsonl"]
    globs_aab = ["bench_allangles_egohumans_qa_internvl_aabfull_shard*.jsonl",
                 "bench_allangles_egohumans_qa_internvl_aabblind*.jsonl"]
    chips = {"mvu": defaultdict(dict), "aab": defaultdict(dict)}
    for ds, globs, ids in (("mvu", globs_mvu, picked_mvu),
                           ("aab", globs_aab, picked_aab)):
        for g in globs:
            for r in load_rows(g):
                if r["id"] in ids:
                    chips[ds][r["id"]].setdefault(r["method"], {})[
                        r["pass_idx"]] = (str(r.get("prediction") or "—"),
                                          bool(r["correct"]))
    return chips


def chip_text(per_method, methods):
    bits = []
    for m in methods:
        passes = per_method.get(m)
        if not passes:
            continue
        seq = [passes[p] for p in sorted(passes)]
        c = sum(ok for _, ok in seq)
        preds = ",".join(p for p, _ in seq)
        bits.append(f"{METHOD_LABEL[m]} {c}/{len(seq)} [{preds}]")
    return " · ".join(bits)


def chip_html(per_method, methods):
    bits = []
    for m in methods:
        passes = per_method.get(m)
        if not passes:
            continue
        seq = [passes[p] for p in sorted(passes)]
        c = sum(ok for _, ok in seq)
        preds = ",".join(p for p, _ in seq)
        cls = "ok" if c >= 3 else ("bad" if c <= 1 else "")
        bits.append(f'<span class="chip {cls}" title="per-pass predictions: '
                    f'{html.escape(preds)}">{METHOD_LABEL[m]} {c}/{len(seq)}'
                    f'</span>')
    return "".join(bits)


# ------------------------------------------------------------------- media
_PLACEHOLDER = ('<div class="thumb fail"><div class="tlabel">%s</div>'
                'decode failed</div>')


def jpeg_data_uri(img, q):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=q)
    return ("data:image/jpeg;base64,"
            + base64.b64encode(buf.getvalue()).decode()), buf.tell()


def video_middle_frame(path, h):
    import decord
    from PIL import Image
    vr = decord.VideoReader(path, num_threads=1)
    arr = vr[len(vr) // 2].asnumpy()
    img = Image.fromarray(arr)
    return img.resize((max(1, round(img.width * h / img.height)), h))


def image_thumb(path, h):
    from PIL import Image
    img = Image.open(path)
    return img.resize((max(1, round(img.width * h / img.height)), h))


def thumb_row(rec, video, q, h, assets, qkey):
    parts, media = [], (vids_of(rec) if video else imgs_of(rec))
    label = "Video" if video else "View"
    root = MVU_MEDIA if video else AAB_MEDIA
    for i, m in enumerate(media[:MAX_THUMBS], 1):
        cap = f"{label} {i}"
        try:
            img = (video_middle_frame if video else image_thumb)(
                os.path.join(root, m), h)
            uri, nbytes = jpeg_data_uri(img, q)
            assets.append({"question": qkey, "slot": cap, "source": m,
                           "bytes": nbytes})
            parts.append(f'<div class="thumb"><div class="tlabel">{cap} '
                         f'<span class="tfile">{html.escape(os.path.basename(m))}'
                         f'</span></div><img src="{uri}" alt="{cap}"></div>')
        except Exception:
            assets.append({"question": qkey, "slot": cap, "source": m,
                           "bytes": 0, "error": "decode failed"})
            parts.append(_PLACEHOLDER % f"{cap} {html.escape(os.path.basename(m))}")
    if len(media) > MAX_THUMBS:
        parts.append(f'<div class="thumb more">+{len(media) - MAX_THUMBS} more '
                     f'{label.lower()}s</div>')
    return f'<div class="thumbrow">{"".join(parts)}</div>'


# --------------------------------------------------------------- rendering
def esc(s):
    return html.escape(str(s))


def render_question(rec, tag, rule, chips_pm, methods, video, q, h, assets,
                    text_only=False):
    qkey = f"{'mvu' if video else 'aab'}:{rec['id']}"
    flags = q_flags(rec)
    fl = [FLAG_LABEL[k] for k in FLAG_LABEL if flags[k]]
    if flags["is_sync"]:
        fl.append("synchronized nuScenes 6-cam rig")
    kn = len(vids_of(rec)) if video else len(imgs_of(rec))
    fam = f" · sources: {family_sig(rec)}" if video else ""
    qtext = rec["question"]
    if len(qtext) > LONG_Q:
        qbody = (f"<details><summary>{esc(qtext[:200])}… "
                 f"({len(qtext):,} chars — click to expand)</summary>"
                 f"<div class='qtext'>{esc(qtext)}</div></details>")
    else:
        qbody = f"<div class='qtext'>{esc(qtext)}</div>"
    gold = str(rec["answer"]).strip().upper()
    opts = "".join(
        f"<li class='{'gold' if o.strip().upper().startswith(gold + '.') else ''}'>"
        f"{esc(o)}</li>" for o in rec["options"])
    thumbs = ("" if text_only else thumb_row(rec, video, q, h, assets, qkey))
    if text_only:
        thumbs = ('<p class="noimg">images not on disk — Ego-Exo4D license '
                  'pending</p>')
    chips = chip_html(chips_pm, methods) if chips_pm else ""
    label = "Video" if video else "View"
    root = "data/mvueval" if video else "data/allangles"
    src_items = []
    for i, m in enumerate(vids_of(rec) if video else imgs_of(rec), 1):
        yt = YT_ID.match(os.path.basename(m))
        link = (f' — <a href="https://www.youtube.com/watch?v={yt.group(1)}"'
                f' target="_blank" rel="noopener">likely YouTube source</a>'
                if yt and video else "")
        src_items.append(f"<li>{label} {i}: <code>{esc(root)}/{esc(m)}</code>"
                         f"{link}</li>")
    bundle = (f'<p class="pickrule">byte-identical copies: '
              f'<code>bench/results/repq_media/'
              f'{"mvu" if video else "aab"}_{rec["id"]}/</code></p>'
              if not text_only else "")
    sources = (f'<details class="mediasrc"><summary>source files '
               f'({len(src_items)})</summary><ul>{"".join(src_items)}</ul>'
               f'{bundle}</details>')
    return f"""
<div class="qcard">
  <div class="qhead"><span class="chip pick">{esc(tag)}</span>
    <span class="meta">id {rec['id']} · {kn} {'videos' if video else 'views'}{fam}
    {(' · <b>' + ' · '.join(esc(x) for x in fl) + '</b>') if fl else ''}</span></div>
  {qbody}
  <ol class="opts">{opts}</ol>
  {thumbs}
  <div class="chiprow">{chips}</div>
  {sources}
  <p class="pickrule">pick rule: {esc(rule)}</p>
</div>"""


def fmt_pct(x):
    return f"{x:.1f}" if isinstance(x, (int, float)) else "—"


def bold_max(vals):
    """Format a row of accuracies, bolding the maximum (bold = best arm)."""
    nums = [v for v in vals if isinstance(v, (int, float))]
    top = max(nums) if nums else None
    return [f"<b>{fmt_pct(v)}</b>" if v == top else fmt_pct(v) for v in vals]


def fam_str(families):
    items = list(families.items())
    s = " · ".join(f"{k} {v}" for k, v in items[:3])
    if len(items) > 3:
        s += f" · +{sum(v for _, v in items[3:])} more"
    return s


def mvu_panel(cat, comp, S):
    arr = S["arrangement"]["mvu_full"]
    clip = S["clip"]
    bt = lambda blk: blk["by_task"].get(cat, {}).get("acc")
    blind = S["blind"]["mvu_full"]["by_task"].get(cat, {}).get("acc")
    ia = S["blind"]["images_add_by_task"].get(cat, {})
    pt = S["per_task"].get(cat, {})
    kd = " · ".join(f"{k}:{v}" for k, v in comp["k_dist"].items())
    f = comp["flag_counts"]
    cells = bold_max([blind, bt(arr["cvbench_native"]), bt(arr["centralized"]),
                      bt(arr["per_stream"]), bt(clip["frame_select"]),
                      bt(clip["clip_select_top1"]),
                      bt(clip["temporal_weighted"])])
    return f"""
<div class="tablewrap"><table>
<tr><th colspan="6">composition — n={comp['n']} ({100 * comp['n'] / S['meta']['mvu_n']:.0f}% of pool) ·
  videos/q {kd} · sources: {fam_str(comp['families'])} · sync {f['is_sync']} ·
  names-a-video {100 * f['names_video'] / comp['n']:.0f}% ·
  identity options {100 * f['ident_options'] / comp['n']:.0f}% ·
  option count mode {comp['opt_mode']} · chance {comp['chance']}%
  (mean over the category's option counts)</th></tr>
<tr><th>blind</th><th>sequential</th><th>stitching</th><th>decentralized</th>
    <th>frame_select / clip_top1 / temporal</th><th>stitch Δ · images add</th></tr>
<tr>
 <td>{cells[0]}</td><td>{cells[1]}</td><td>{cells[2]}</td><td>{cells[3]}</td>
 <td>{cells[4]} / {cells[5]} / {cells[6]}</td>
 <td>{pt.get('delta', 0):+.2f} (p={pt.get('p', 1):.2f}{', Holm-sig' if pt.get('holm_significant') else ''})
     · {ia.get('delta', 0):+.1f} (p={ia.get('p', 1):.3f})</td>
</tr></table></div>"""


def aab_panel(cat, comp_full, comp_ego, S):
    arr = S["arrangement"]["aab170"]
    bt = lambda blk: blk["by_task"].get(cat, {}).get("acc")
    bl = S["blind"]["aab170"]["by_task"].get(cat, {})
    blind, bl_n = bl.get("acc"), bl.get("n_q")
    arm_n = arr["cvbench_native"]["by_task"].get(cat, {}).get("n_q")
    kd = " · ".join(f"{k}:{v}" for k, v in comp_full["k_dist"].items())
    note = "accuracies on the EgoHumans 170 only"
    if bl_n and arm_n and bl_n < arm_n:
        note += (f"; blind covers {bl_n}/{arm_n} — completion run queued")
    cells = bold_max([blind, bt(arr["cvbench_native"]), bt(arr["centralized"]),
                      bt(arr["per_stream"])])
    return f"""
<div class="tablewrap"><table>
<tr><th colspan="5">composition — n={comp_full['n']} in the full pool
  ({comp_ego['n']} EgoHumans with media on disk) · views/q {kd} ·
  option count mode {comp_full['opt_mode']} · chance {comp_full['chance']}%
  (mean over the category's option counts)</th></tr>
<tr><th>blind</th><th>sequential</th><th>stitching</th><th>decentralized</th>
    <th>note</th></tr>
<tr><td>{cells[0]}</td><td>{cells[1]}</td><td>{cells[2]}</td><td>{cells[3]}</td>
 <td>{note}</td></tr>
</table></div>"""


def gate_stats():
    """Recompute recall@1/@2 from the persisted scorer-gate probe rows
    (CVBench-era pool; the probe that gated the frame_select launch)."""
    out = {}
    for e in json.load(open(GATE)):
        if e["set"] != "primary":
            continue
        key = "CLIP B/32" if "clip" in e["model"] else "SigLIP so400m"
        order = sorted(range(len(e["max"])), key=lambda j: -e["max"][j])
        d = out.setdefault(key, {"n": 0, "r1": 0, "r2": 0, "rand": 0.0})
        d["n"] += 1
        d["r1"] += (order[0] + 1 == e["target"])
        d["r2"] += (e["target"] in (order[0] + 1, order[1] + 1)
                    if len(order) > 1 else order[0] + 1 == e["target"])
        d["rand"] += 1.0 / len(e["max"])
    for d in out.values():
        d["recall1"] = round(100.0 * d["r1"] / d["n"], 1)
        d["recall2"] = round(100.0 * d["r2"] / d["n"], 1)
        d["random_floor"] = round(100.0 * d["rand"] / d["n"], 1)
    return out


def sheet_img(figdir, qid, q):
    from PIL import Image
    path = os.path.join(figdir, f"mvu_{qid}_frameselect.png")
    img = Image.open(path)
    if img.width > 1500:
        img = img.resize((1500, round(img.height * 1500 / img.width)))
    uri, nbytes = jpeg_data_uri(img, max(q, 80))
    return uri, nbytes, path


YT_ID = re.compile(r"^([A-Za-z0-9_-]{11})\.(mp4|mkv|webm)$")


def media_link(path, dataset):
    """Human-usable pointer for one source file: bundle-relative path plus a
    best-effort YouTube link when the basename looks like a video id."""
    base = os.path.basename(path)
    m = YT_ID.match(base)
    yt = (f" — likely source: https://www.youtube.com/watch?v={m.group(1)}"
          if m and dataset == "mvu" else "")
    return f"`{path}`{yt}"


def export_media(mvu_picks, aab_picks, qe, out_dir):
    """Copy the byte-identical source clips/images of every picked question
    into per-question folders, with an index."""
    import shutil
    os.makedirs(out_dir, exist_ok=True)
    index, total = [], 0
    mvu_pool = {r["id"]: r for r in json.load(open(MVU_POOL))}
    ids_mvu = sorted({r["id"] for ps in mvu_picks.values() for r, _, _ in ps}
                     | set(qe.values()))
    for i in ids_mvu:
        rec = mvu_pool[i]
        d = os.path.join(out_dir, f"mvu_{i}")
        os.makedirs(d, exist_ok=True)
        files = []
        for k, v in enumerate(vids_of(rec), 1):
            src = os.path.join(MVU_MEDIA, v)
            dst = os.path.join(d, f"video{k}__{os.path.basename(v)}")
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            total += os.path.getsize(dst)
            files.append(os.path.basename(dst))
        index.append({"question": f"mvu:{i}", "task_type": rec["task_type"],
                      "text": rec["question"][:200], "files": files})
    for ps in aab_picks.values():
        for rec, _, _ in ps:
            if rec.get("source") != "EgoHumans":
                continue
            d = os.path.join(out_dir, f"aab_{rec['id']}")
            os.makedirs(d, exist_ok=True)
            files = []
            for k, v in enumerate(imgs_of(rec), 1):
                src = os.path.join(AAB_MEDIA, v)
                dst = os.path.join(d, f"view{k}__{os.path.basename(v)}")
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                total += os.path.getsize(dst)
                files.append(os.path.basename(dst))
            index.append({"question": f"aab:{rec['id']}",
                          "task_type": rec["task_type"],
                          "text": rec["question"][:200], "files": files})
    json.dump(index, open(os.path.join(out_dir, "index.json"), "w"), indent=1)
    with open(os.path.join(out_dir, "README.txt"), "w") as fh:
        fh.write("Source media for every question shown in repq_doc.html /\n"
                 "repq_doc.md, byte-identical originals. Folder mvu_<id> /\n"
                 "aab_<id> matches the question id printed on each card.\n"
                 "Files are prefixed with their Video/View number.\n"
                 "See index.json for the question text of each folder.\n")
    return len(index), total


def emit_markdown(path, S, diag, gate, mvu_by_cat, aab_by_cat, mvu_picks,
                  aab_picks, chips, ego_o2i, qe, media_dir):
    mvu_cats = sorted(mvu_by_cat, key=lambda c: -len(mvu_by_cat[c]))
    aab_cats = sorted(aab_by_cat, key=lambda c: -len(aab_by_cat[c]))
    L = []
    L.append("# Representative questions by category — MVU-Eval & All-Angles")
    L.append(f"\n_backend {S['meta']['backend']} · {S['meta']['passes']} "
             "passes per question · companion to the results deck_\n")
    L.append("## How the questions were chosen\n")
    L.append("Selection is deterministic and results-blind: every pick uses "
             "only dataset text and metadata — never model accuracy — and "
             "there is no randomness anywhere. Per category: **(A)** the "
             "modal exemplar (median-length question at the category's most "
             "common view count and source mix); **(B)** a defect exemplar "
             "when ≥20% of the category carries a text flag; **(C)** a "
             "synchronized-rig exemplar where the category intersects the "
             "128 nuScenes 6-camera questions. Full rules incl. tie-breaks "
             "in Appendix B. Per-question results are shown for transparency "
             "but played no part in selection.\n")

    def q_block(rec, tag, rule, chip_line, dataset, video):
        vs = vids_of(rec) if video else imgs_of(rec)
        flags = q_flags(rec)
        fl = [FLAG_LABEL[k] for k in FLAG_LABEL if flags[k]]
        if flags["is_sync"]:
            fl.append("synchronized nuScenes 6-cam rig")
        o = [f"### {tag} — id {rec['id']}\n"]
        qt = rec["question"]
        o.append("> " + qt.replace("\n", "\n> ") + "\n")
        gold = str(rec["answer"]).strip().upper()
        for opt in rec["options"]:
            mark = " **← gold**" if opt.strip().upper().startswith(gold + ".") else ""
            o.append(f"- {opt}{mark}")
        o.append("")
        meta = [f"{len(vs)} {'videos' if video else 'views'}"]
        if video:
            meta.append(f"sources: {family_sig(rec)}")
        if fl:
            meta.append(" · ".join(fl))
        o.append(f"_{' · '.join(meta)}_\n")
        if chip_line:
            o.append(f"results: {chip_line}\n")
        label = "video" if video else "view"
        for k, v in enumerate(vs, 1):
            folder = f"{media_dir}/{dataset}_{rec['id']}" if media_dir else None
            if folder and (video or rec.get("source") == "EgoHumans"):
                o.append(f"- {label} {k}: "
                         f"{media_link(f'{folder}/{label}{k}__{os.path.basename(v)}', dataset)}")
            else:
                o.append(f"- {label} {k}: `{v}` (image not on disk — "
                         "license pending)" if not video else
                         f"- {label} {k}: `{v}`")
        o.append(f"\n_pick rule: {rule}_\n")
        return "\n".join(o)

    # MVU
    d = S["defects"]
    L.append(f"## MVU-Eval at a glance — {S['meta']['mvu_n']:,} questions\n")
    L.append(f"- {d['mvu_names_video']['names_a_video']:,} questions "
             f"({100 * d['mvu_names_video']['names_a_video'] / S['meta']['mvu_n']:.0f}%) "
             "name a specific video in text/options")
    L.append(f"- {S['meta']['sync_n']} questions "
             f"({100 * S['meta']['sync_n'] / S['meta']['mvu_n']:.0f}%) are "
             "synchronized nuScenes 6-cam rigs; the rest are non-synchronized "
             "clip sets")
    L.append(f"- chance {S['arrangement']['chance']['mvu_full']}% · majority "
             f"floor {S['arrangement']['majority_floor']['mvu_full']['acc']:.2f}%\n")
    arr = S["arrangement"]["mvu_full"]
    L.append("| arm | blind | sequential | stitching | decentralized | "
             "frame_select | clip_top1 | temporal |")
    L.append("|---|---|---|---|---|---|---|---|")
    L.append("| overall | " + " | ".join(
        f"{v:.1f}" for v in [S['blind']['mvu_full']['acc'],
                             arr['cvbench_native']['acc'],
                             arr['centralized']['acc'],
                             arr['per_stream']['acc'],
                             S['clip']['frame_select']['acc'],
                             S['clip']['clip_select_top1']['acc'],
                             S['clip']['temporal_weighted']['acc']]) + " |\n")
    for cat in mvu_cats:
        comp = composition(mvu_by_cat[cat])
        pt = S["per_task"].get(cat, {})
        ia = S["blind"]["images_add_by_task"].get(cat, {})
        L.append(f"## {MVU_NAMES.get(cat, cat)} (`{cat}`) — "
                 f"{comp['n']} questions\n")
        f = comp["flag_counts"]
        L.append(f"_videos/q {dict(comp['k_dist'])} · sources "
                 f"{fam_str(comp['families'])} · sync {f['is_sync']} · "
                 f"names-a-video {100 * f['names_video'] / comp['n']:.0f}% · "
                 f"identity options {100 * f['ident_options'] / comp['n']:.0f}% · "
                 f"chance {comp['chance']}% · stitch Δ {pt.get('delta', 0):+.2f} "
                 f"(p={pt.get('p', 1):.2f}) · images add {ia.get('delta', 0):+.1f} "
                 f"(p={ia.get('p', 1):.3f})_\n")
        bt = lambda blk: blk["by_task"].get(cat, {}).get("acc")
        L.append("| blind | sequential | stitching | decentralized | "
                 "frame_select | clip_top1 | temporal |")
        L.append("|---|---|---|---|---|---|---|")
        L.append("| " + " | ".join(fmt_pct(v) for v in [
            S["blind"]["mvu_full"]["by_task"].get(cat, {}).get("acc"),
            bt(arr["cvbench_native"]), bt(arr["centralized"]),
            bt(arr["per_stream"]), bt(S["clip"]["frame_select"]),
            bt(S["clip"]["clip_select_top1"]),
            bt(S["clip"]["temporal_weighted"])]) + " |\n")
        for rec, tag, rule in mvu_picks[cat]:
            cl = chip_text(chips["mvu"].get(rec["id"], {}), MVU_METHODS)
            L.append(q_block(rec, tag, rule, cl, "mvu", True))

    # AAB
    aab_all = [r for rs in aab_by_cat.values() for r in rs]
    ego_n = sum(1 for r in aab_all if r.get("source") == "EgoHumans")
    L.append(f"## All-Angles at a glance — {len(aab_all):,} questions\n")
    L.append(f"Still images, 2–5 synchronized cameras. "
             f"{len(aab_all) - ego_n:,} questions are Ego-Exo4D (images "
             f"license-blocked); accuracies below are on the {ego_n}-question "
             "EgoHumans slice.\n")
    for cat in aab_cats:
        comp_full = composition(aab_by_cat[cat], video=False)
        L.append(f"## {cat.replace('AAB-', '').replace('-', ' ')} "
                 f"(`{cat}`) — {comp_full['n']} questions\n")
        bt = lambda blk: blk["by_task"].get(cat, {}).get("acc")
        aarr = S["arrangement"]["aab170"]
        L.append("| blind | sequential | stitching | decentralized |")
        L.append("|---|---|---|---|")
        L.append("| " + " | ".join(fmt_pct(v) for v in [
            S["blind"]["aab170"]["by_task"].get(cat, {}).get("acc"),
            bt(aarr["cvbench_native"]), bt(aarr["centralized"]),
            bt(aarr["per_stream"])]) + " |\n")
        for rec, tag, rule in aab_picks[cat]:
            cl = chip_text(chips["aab"].get(ego_o2i.get(rec["orig_id"], -1),
                                            {}), AAB_METHODS)
            L.append(q_block(rec, tag, rule, cl, "aab", False))

    # Appendix A
    fs, t1 = diag["frame_select"], diag["clip_select_top1"]
    g, gt = fs["gold_named"], t1["gold_named"]
    L.append("## Appendix A — the CLIP frame sampler\n")
    L.append("**Encoder:** `openai/clip-vit-base-patch32` (HF AutoModel), "
             f"identical on all {fs['n_rows']:,} full-pool frame_select rows.\n")
    L.append("**Feature-distance thresholds:** none — no distance or motion "
             "threshold anywhere. Fixed-budget question-conditioned top-k: "
             "32 uniform candidates/clip → one CLIP text-image cosine pass "
             "(raw question only) → global top-64, no per-clip floor.\n")
    L.append(f"**Alignment** (the {g['n']} questions whose gold option names "
             f"one video): frame_select keeps the relevant clip "
             f"{g['recall_kept']:.1f}% of the time, mean share "
             f"{g['mean_share']:.3f} vs {g['mean_uniform_share']:.3f} "
             f"uniform; accuracy {g['acc_kept']:.1f}% kept vs "
             f"{g['acc_dropped']:.1f}% dropped. clip_top1 picks the right "
             f"clip {gt['recall_kept']:.1f}% (random "
             f"{gt['random_pick_recall']:.1f}%), {gt['acc_kept']:.1f}% when "
             f"right vs {gt['acc_dropped']:.1f}% when wrong. Earlier scorer "
             f"gate: recall@1 {gate['CLIP B/32']['recall1']:.1f}% CLIP / "
             f"{gate['SigLIP so400m']['recall1']:.1f}% SigLIP vs "
             f"{gate['CLIP B/32']['random_floor']:.1f}% random.\n")
    L.append("**Qualitative contact sheets** (fixed rules, ids "
             f"{qe['aligned']}/{qe['typical']}/{qe['missed']}/"
             f"{qe['degenerate']}):\n")
    for kind in ("aligned", "typical", "missed", "degenerate"):
        L.append(f"- QE-{kind}: `bench/results/figs_repq_sampler/"
                 f"mvu_{qe[kind]}_frameselect.png` — source clips in "
                 f"`{media_dir}/mvu_{qe[kind]}/`")
    L.append("\n## Appendix B — selection rules (verbatim)\n")
    L.append("Pick primitive: sort a stratum by (question length, id), take "
             "the middle element — no RNG; ties break to the lowest id. MVU "
             "slots: A = modal video-count → modal source-family mix → median "
             "length; B = median-length flagged record when a text flag "
             "covers ≥20% of the category, excluding questions already shown "
             "in an earlier slot; C = median-length synchronized-rig member, "
             "same exclusion. AAB slots: A = modal view count within the "
             "EgoHumans slice; B = far view count when that slice spans more "
             "than one (currently none does); T = modal Ego-Exo4D exemplar, "
             "text-only until the license clears. Sampler picks over the "
             "gold-named share distribution (universe: K≥3, candidate pool > "
             "budget): aligned = argmax share; typical = median; missed = "
             "zero share, largest K; degenerate = lowest-id K=2.\n")
    open(path, "w").write("\n".join(L) + "\n")


def slack_snippet(diag, gate):
    fs, t1 = diag["frame_select"], diag["clip_select_top1"]
    g = fs["gold_named"]
    return (
        "Encoder: openai/clip-vit-base-patch32 (HF AutoModel), same on every "
        "run (recorded per-row). There is no feature-distance threshold — ours "
        "isn't distance-based keyframing (that's the MOG2 motion sampler). "
        "It's fixed-budget question-conditioned top-k: 32 uniform candidate "
        "frames per clip, one CLIP text-image cosine pass against the raw "
        "question, keep the global top-64 across all clips (no per-clip floor, "
        "so a clip can get 0 frames).\n"
        f"Alignment vs parseable ground truth (the {g['n']} full-pool questions "
        "whose gold option names one video): frame_select keeps the relevant "
        f"clip {g['recall_kept']:.0f}% of the time but only mildly concentrates "
        f"on it — {g['mean_share']:.3f} mean share of kept frames vs "
        f"{g['mean_uniform_share']:.3f} uniform; accuracy is "
        f"{g['acc_kept']:.1f}% when it's kept vs {g['acc_dropped']:.1f}% when "
        f"dropped. A pick-one-clip variant chooses the right clip "
        f"{t1['gold_named']['recall_kept']:.0f}% of the time (random "
        f"{t1['gold_named']['random_pick_recall']:.0f}%) and scores "
        f"{t1['gold_named']['acc_kept']:.1f}% when right vs "
        f"{t1['gold_named']['acc_dropped']:.1f}% when wrong — the selector, "
        "not the harness, is the bottleneck (earlier scorer gate: recall@1 "
        f"{gate['CLIP B/32']['recall1']:.1f}% CLIP / "
        f"{gate['SigLIP so400m']['recall1']:.1f}% SigLIP vs "
        f"{gate['CLIP B/32']['random_floor']:.1f}% random). Qualitative "
        "keep/drop contact sheets (aligned, typical, and failure cases, picked "
        "by fixed rules) are in Appendix A of the doc.")


CSS = """
:root {
  --bg:#fcfcfb; --card:#ffffff; --ink:#141413; --ink2:#52514e; --muted:#898781;
  --line:#e3e2db; --accent:#2a78d6; --neg:#c23a39; --chipbg:#eef4fc;
  --okbg:#eaf5ea; --ok:#1d6b1d; --badbg:#fbecec; --gold:#f5efd8;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    --bg:#1a1a19; --card:#232322; --ink:#f2f1ec; --ink2:#c3c2b7; --muted:#8f8d86;
    --line:#33332f; --accent:#3987e5; --neg:#e66767; --chipbg:#1f2c3d;
    --okbg:#1e2e1e; --ok:#7fc97f; --badbg:#3a2222; --gold:#3a341f;
  }
}
:root[data-theme="dark"] {
  --bg:#1a1a19; --card:#232322; --ink:#f2f1ec; --ink2:#c3c2b7; --muted:#8f8d86;
  --line:#33332f; --accent:#3987e5; --neg:#e66767; --chipbg:#1f2c3d;
  --okbg:#1e2e1e; --ok:#7fc97f; --badbg:#3a2222; --gold:#3a341f;
}
:root[data-theme="light"] {
  --bg:#fcfcfb; --card:#ffffff; --ink:#141413; --ink2:#52514e; --muted:#898781;
  --line:#e3e2db; --accent:#2a78d6; --neg:#c23a39; --chipbg:#eef4fc;
  --okbg:#eaf5ea; --ok:#1d6b1d; --badbg:#fbecec; --gold:#f5efd8;
}
body { background:var(--bg); color:var(--ink);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
  margin:0; padding:2.5rem 1.25rem 4rem; }
main { max-width:1020px; margin:0 auto; display:flex; flex-direction:column;
  gap:2rem; }
h1 { font-size:1.7rem; line-height:1.2; margin:0; text-wrap:balance; }
h2 { font-size:1.25rem; margin:1.2rem 0 .4rem; }
h3 { font-size:1.05rem; margin:.8rem 0 .3rem; }
.sub { color:var(--ink2); margin:.4rem 0 0; max-width:70ch; }
.callout { border-left:3px solid var(--accent); background:var(--card);
  border-radius:0 8px 8px 0; padding:.9rem 1.1rem; }
.callout p { margin:.3rem 0; color:var(--ink2); max-width:75ch; }
.callout b { color:var(--ink); }
.chip { display:inline-block; background:var(--chipbg); color:var(--accent);
  border-radius:999px; padding:.1rem .6rem; font-size:.78rem; font-weight:600;
  margin:.1rem .15rem .1rem 0; }
.chip.ok { background:var(--okbg); color:var(--ok); }
.chip.bad { background:var(--badbg); color:var(--neg); }
.chip.pick { background:var(--gold); color:var(--ink); }
.tablewrap { overflow-x:auto; border:1px solid var(--line); border-radius:8px; }
table { border-collapse:collapse; width:100%; font-size:.88rem; min-width:640px;
  font-variant-numeric:tabular-nums; }
th { text-align:left; font-weight:600; color:var(--ink2);
  border-bottom:1px solid var(--line); padding:.5rem .7rem;
  background:var(--card); }
td { padding:.5rem .7rem; border-bottom:1px solid var(--line);
  vertical-align:top; }
tr:last-child td { border-bottom:none; }
.qcard { background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:1rem 1.1rem; margin:.8rem 0; }
.qhead { display:flex; flex-wrap:wrap; gap:.4rem; align-items:baseline;
  margin-bottom:.4rem; }
.meta { color:var(--muted); font-size:.82rem; }
.qtext { white-space:pre-wrap; margin:.4rem 0; max-width:85ch; }
.opts { margin:.4rem 0 .6rem; padding-left:1.2rem; list-style:none; }
.opts li { padding:.1rem .4rem; border-radius:4px; max-width:80ch; }
.opts li.gold { background:var(--gold); font-weight:600; }
.thumbrow { display:flex; flex-wrap:wrap; gap:.5rem; margin:.6rem 0; }
.thumb { border:1px solid var(--line); border-radius:6px; overflow:hidden;
  background:var(--card); }
.thumb img { display:block; height:140px; width:auto; max-width:100%; }
.thumb .tlabel { font-size:.72rem; color:var(--ink2); padding:.15rem .4rem;
  border-bottom:1px solid var(--line); }
.thumb .tfile { color:var(--muted); }
.thumb.fail, .thumb.more { display:flex; flex-direction:column;
  align-items:center; justify-content:center; min-width:120px; height:160px;
  color:var(--muted); font-size:.8rem; padding:.4rem; }
.chiprow { margin:.4rem 0 0; }
.pickrule, .noimg { color:var(--muted); font-size:.78rem; margin:.4rem 0 0; }
.mediasrc { margin:.4rem 0 0; font-size:.78rem; color:var(--muted); }
.mediasrc summary { cursor:pointer; }
.mediasrc ul { margin:.3rem 0; padding-left:1.2rem; }
.mediasrc a { color:var(--accent); }
.imgcard { background:#ffffff; border:1px solid var(--line); border-radius:8px;
  overflow:hidden; margin:.6rem 0; }
.imgcard img { display:block; width:100%; height:auto; }
.cap { color:var(--ink2); font-size:.9rem; margin:.2rem 0 .8rem; max-width:85ch; }
code { background:var(--card); border:1px solid var(--line); border-radius:4px;
  padding:.05rem .35rem; font-size:.85em; }
footer { color:var(--muted); font-size:.85rem; border-top:1px solid var(--line);
  padding-top:1.2rem; }
"""


def build(args):
    from datetime import date
    S = json.load(open(STATS))
    diag = json.load(open(DIAG))
    gate = gate_stats()
    mvu = json.load(open(MVU_POOL))
    aab = json.load(open(AAB_POOL))
    mvu_by_cat = defaultdict(list)
    for r in mvu:
        mvu_by_cat[r["task_type"]].append(r)
    aab_by_cat = defaultdict(list)
    for r in aab:
        aab_by_cat[r["task_type"]].append(r)

    qe = pick_sampler_ids(diag)
    if args.list_sampler_ids:
        print(json.dumps(qe))
        return 0

    mvu_cats = sorted(mvu_by_cat, key=lambda c: -len(mvu_by_cat[c]))
    aab_cats = sorted(aab_by_cat, key=lambda c: -len(aab_by_cat[c]))
    mvu_picks = {c: pick_mvu(mvu_by_cat[c]) for c in mvu_cats}
    aab_picks = {c: pick_aab(aab_by_cat[c]) for c in aab_cats}

    # AAB result rows live in the 170-question EgoHumans file's OWN id space;
    # picks come from the full pool, so join the two through orig_id
    ego_o2i = {r["orig_id"]: r["id"]
               for r in json.load(open(AAB_EGO_POOL))}
    picked_mvu = {r["id"] for ps in mvu_picks.values() for r, _, _ in ps}
    picked_aab = {ego_o2i[r["orig_id"]] for ps in aab_picks.values()
                  for r, _, _ in ps if r.get("source") == "EgoHumans"}
    chips = load_chips(picked_mvu, picked_aab)

    manifest = {"generated": str(date.today()),
                "sources": {p: os.path.getmtime(p) for p in
                            (STATS, DIAG, GATE, MVU_POOL, AAB_POOL)},
                "sampler_ids": qe, "assets": [], "mvu_picks": [],
                "aab_picks": [], "categories": {}, "gate": gate}

    for attempt, (q, h) in enumerate([(args.jpeg_q, args.thumb_h), (60, 110)]):
        manifest["assets"] = []
        parts = []
        d = S["defects"]
        letters = d["mvu_gold_letter_dist"]
        arr = S["arrangement"]["mvu_full"]

        parts.append(f"""
<header>
  <h1>Representative questions by category — MVU-Eval &amp; All-Angles</h1>
  <p class="sub">Every category of both benchmarks, with verbatim questions,
  the frames the model actually sees, and per-arm outcomes
  ({S['meta']['backend']}, {S['meta']['passes']} passes). Companion to the
  results deck.</p>
  <div class="callout"><p><b>How the questions were chosen.</b> Selection is
  deterministic and results-blind: every pick uses only dataset text and
  metadata — never model accuracy — and there is no randomness anywhere. Per
  category we show (A) the <b>modal exemplar</b>: the median-length question at
  the category's most common view count and source mix; (B) a <b>defect
  exemplar</b> when ≥20% of the category carries a text flag (options naming
  videos, duplicated options, &gt;6 options); (C) a <b>synchronized-rig
  exemplar</b> where the category intersects the 128 nuScenes 6-camera
  questions. The complete rules, including tie-breaks, are in Appendix B.
  Per-question results are shown for transparency but played no part in
  selection — each chip is one arm's correct passes out of 4 (hover for its
  per-pass answers; the gold option is highlighted; in accuracy tables bold
  marks the row's best arm).</p></div>
</header>""")

        # ---- MVU at a glance
        opt4 = d["mvu_option_count_dist"].get("4", 0)
        n_ident = sum(1 for r in mvu if q_flags(r)["ident_options"])
        n_seg = same_parent_segments(mvu)
        arm_names = ["blind", "sequential", "stitching", "decentralized",
                     "frame_select", "clip_top1", "temporal"]
        arm_cells = bold_max([
            S["blind"]["mvu_full"]["acc"], arr["cvbench_native"]["acc"],
            arr["centralized"]["acc"], arr["per_stream"]["acc"],
            S["clip"]["frame_select"]["acc"],
            S["clip"]["clip_select_top1"]["acc"],
            S["clip"]["temporal_weighted"]["acc"]])
        arms_row = " · ".join(f"{n} {c}" for n, c in zip(arm_names, arm_cells))
        parts.append(f"""
<section><h2>MVU-Eval at a glance — {S['meta']['mvu_n']:,} questions</h2>
<div class="tablewrap"><table>
<tr><th>fact</th><th>value</th></tr>
<tr><td>questions naming a specific video in text/options</td>
    <td>{d['mvu_names_video']['names_a_video']:,}
    ({100 * d['mvu_names_video']['names_a_video'] / S['meta']['mvu_n']:.0f}%);
    for {n_ident:,} ({100 * n_ident / S['meta']['mvu_n']:.0f}%) the answer
    options themselves are video identities ("A. Video 1 …")</td></tr>
<tr><td>synchronized multi-camera questions (nuScenes 6-cam rigs)</td>
    <td>{S['meta']['sync_n']} ({100 * S['meta']['sync_n'] / S['meta']['mvu_n']:.0f}%);
    the other {S['meta']['unrelated_n']:,} are non-synchronized clip sets
    (incl. {n_seg} whose clips are segments cut from one source video)</td></tr>
<tr><td>gold-letter skew</td><td>A {letters.get('A')} · B {letters.get('B')} ·
    C {letters.get('C')} · D {letters.get('D')} · E–K
    {sum(v for k, v in letters.items() if k > 'D')}</td></tr>
<tr><td>options per question</td><td>4 options for {opt4:,}
    ({100 * opt4 / S['meta']['mvu_n']:.0f}%); range 2–11 ·
    chance {S['arrangement']['chance']['mvu_full']}% · majority floor
    {S['arrangement']['majority_floor']['mvu_full']['acc']:.2f}%
    (always "{S['arrangement']['majority_floor']['mvu_full']['letter']}")</td></tr>
<tr><td>overall accuracy by arm</td><td>{arms_row}</td></tr>
<tr><td>single best view (545 q where no video is named)</td>
    <td>best {S['single_view']['best']} vs sequential
    {S['single_view']['sequential_all_views']} vs luck-only best-of-K
    {S['single_view']['luck_best_of_k']} — picking the right view is worth
    +{S['single_view']['best'] - S['single_view']['sequential_all_views']:.1f},
    of which +{S['single_view']['best'] - S['single_view']['luck_best_of_k']:.1f}
    survives the luck correction</td></tr>
</table></div></section>""")

        # ---- MVU categories
        for cat in mvu_cats:
            comp = composition(mvu_by_cat[cat])
            manifest["categories"][cat] = {"composition": comp}
            cards = "".join(
                render_question(r, tag, rule, chips["mvu"].get(r["id"], {}),
                                MVU_METHODS, True, q, h, manifest["assets"])
                for r, tag, rule in mvu_picks[cat])
            parts.append(f"""
<section><h2>{esc(MVU_NAMES.get(cat, cat))} <span class="meta">{esc(cat)} ·
{comp['n']} questions</span></h2>
{mvu_panel(cat, comp, S)}
{cards}</section>""")

        # ---- AAB
        aab_ego_n = sum(1 for r in aab if r.get("source") == "EgoHumans")
        aab_blind_n = S["blind"]["aab170"]["n_q"]
        blind_note = (f" (blind covers {aab_blind_n}/{aab_ego_n} — completion "
                      f"run queued)" if aab_blind_n < aab_ego_n else "")
        aab_cells = bold_max([
            S["blind"]["aab170"]["acc"],
            S["arrangement"]["aab170"]["cvbench_native"]["acc"],
            S["arrangement"]["aab170"]["centralized"]["acc"],
            S["arrangement"]["aab170"]["per_stream"]["acc"]])
        parts.append(f"""
<section><h2>All-Angles at a glance — {len(aab):,} questions</h2>
<p class="sub">Still images, 2–5 synchronized cameras per scene.
{len(aab) - aab_ego_n:,} of {len(aab):,} questions come from Ego-Exo4D, whose
images require a separate license we are still waiting on — the accuracies
below are computed on the {aab_ego_n}-question EgoHumans slice (media on
disk). Blind {aab_cells[0]}{blind_note} · sequential {aab_cells[1]} ·
stitching {aab_cells[2]} · decentralized {aab_cells[3]} · chance
{S['arrangement']['chance']['aab170']}% · majority floor
{S['arrangement']['majority_floor']['aab170']['acc']:.2f}%.</p></section>""")

        for cat in aab_cats:
            comp_full = composition(aab_by_cat[cat], video=False)
            ego = [r for r in aab_by_cat[cat] if r.get("source") == "EgoHumans"]
            comp_ego = composition(ego, video=False) if ego else {"n": 0}
            manifest["categories"][cat] = {"composition": comp_full}
            cards = "".join(
                render_question(
                    r, tag, rule,
                    chips["aab"].get(ego_o2i.get(r["orig_id"], -1), {}),
                    AAB_METHODS, False, q, h, manifest["assets"],
                    text_only=(r.get("source") != "EgoHumans"))
                for r, tag, rule in aab_picks[cat])
            parts.append(f"""
<section><h2>{esc(cat.replace('AAB-', '').replace('-', ' '))}
<span class="meta">{esc(cat)} · {comp_full['n']} questions</span></h2>
{aab_panel(cat, comp_full, comp_ego, S)}
{cards}</section>""")

        # ---- Appendix A
        fs, t1 = diag["frame_select"], diag["clip_select_top1"]
        g, gt = fs["gold_named"], t1["gold_named"]
        sheets = []
        captions = {
            "aligned": "QE-aligned — the (tied) highest concentration in the "
                       "pool, lowest id shown: CLIP piles the kept frames onto "
                       "the gold-named clip.",
            "typical": "QE-typical — the median case: selection barely departs "
                       "from uniform.",
            "missed": "QE-missed — the gold-named clip received ZERO frames "
                      "(red banner): the method silently deleted the evidence "
                      "the question depends on.",
            "degenerate": "QE-degenerate — at K=2 the candidate pool (≤2×32) "
                          "can never exceed the 64-frame budget (here 2×32 = "
                          "64 exactly), so selection keeps everything and is "
                          "a no-op.",
        }
        for kind in ("aligned", "typical", "missed", "degenerate"):
            qid = qe[kind]
            share = diag["frame_select"]["per_question_gold_named"][str(qid)]
            uri, nbytes, path = sheet_img(args.sampler_figs, qid, q)
            manifest["assets"].append({"question": f"mvu:{qid}",
                                       "slot": f"sheet:{kind}",
                                       "source": path, "bytes": nbytes})
            sheets.append(
                f'<div class="imgcard"><img src="{uri}" alt="{kind}"></div>'
                f'<p class="cap"><b>{captions[kind]}</b> Question id {qid}, '
                f'K={share["K"]}, gold-named clip = Video {share["named"]}, '
                f'share of kept frames {share["share"]:.2f} (uniform would be '
                f'{1 / share["K"]:.2f}).</p>')
        parts.append(f"""
<section><h2>Appendix A — the CLIP frame sampler</h2>
<h3>"What encoder are you using?"</h3>
<p class="sub"><code>openai/clip-vit-base-patch32</code> via HuggingFace
AutoModel (default in <code>bench/methods/clip_select.py</code>); every one of
the {fs['n_rows']:,} full-pool frame_select rows records exactly this
checkpoint. SigLIP-so400m was probed as an alternative scorer in an offline
gate (below) but has not been used in a full run.</p>
<h3>"What feature-distance thresholds do you use to compute keyframes?"</h3>
<p class="sub"><b>None.</b> There is no feature-distance or motion threshold
anywhere in this sampler — it is not distance-based keyframe detection (that is
the MOG2 motion sampler, a separate method). Ours is fixed-budget,
question-conditioned top-k: 32 uniform candidate frames per clip → one CLIP
text-image cosine pass, where the text is the raw question only → keep the
global top-64 across all clips. No per-clip floor, so a clip can contribute
zero frames. The pick-one-clip variant (clip_top1) scores 8 uniform thumbnails
per clip and keeps the clip with the highest max cosine. The control arm
(temporal) samples 64 frames uniformly, split across clips by duration.</p>
<h3>Does the selection align with what is actually relevant?</h3>
<p class="sub">Parseable ground truth: the {g['n']} full-pool questions whose
gold option names exactly one video — for these, the relevant clip is known.
frame_select keeps that clip {g['recall_kept']:.1f}% of the time (it rarely
deletes it outright) but concentrates only mildly: the relevant clip gets a
{g['mean_share']:.3f} mean share of the kept frames vs
{g['mean_uniform_share']:.3f} under uniform sampling. Accuracy is
{g['acc_kept']:.1f}% when the relevant clip is kept vs {g['acc_dropped']:.1f}%
when it is dropped. clip_top1 picks the right clip {gt['recall_kept']:.1f}%
of the time (random single pick: {gt['random_pick_recall']:.1f}%) and scores
{gt['acc_kept']:.1f}% when right vs {gt['acc_dropped']:.1f}% when wrong — so
the ceiling on selection is the scorer, not the harness. An earlier offline
gate on the previous benchmark said the same: recall@1 at naming the right
clip {gate['CLIP B/32']['recall1']:.1f}% (CLIP) /
{gate['SigLIP so400m']['recall1']:.1f}% (SigLIP) against a
{gate['CLIP B/32']['random_floor']:.1f}% random floor, with near-zero score
margins.</p>
<h3>Qualitative examples</h3>
<p class="sub">Each contact sheet shows exactly the frames frame_select kept,
grouped by source video in temporal order (t= labels are timestamps; a red
banner marks a clip that contributed nothing). The four examples are picked by
fixed rules from the {g['n']} gold-named questions — best share, median share,
zero-share failure, and the K=2 degenerate regime — not by hand.</p>
{''.join(sheets)}</section>""")

        # ---- Appendix B
        parts.append(f"""
<section><h2>Appendix B — methodology &amp; provenance</h2>
<p class="sub">Pick primitive: sort a stratum by (question length, id) and take
the middle element — no RNG; all remaining ties break to the lowest id. MVU
slots: A = modal video-count → modal source-family mix → median length;
B = median-length flagged record when a text flag covers ≥20% of the category,
<b>excluding questions already shown in an earlier slot of the same
category</b>; C = median-length synchronized-rig member, with the same
exclusion. AAB slots: A = modal view count within the EgoHumans
(media-on-disk) slice; B = the far view count when that slice spans more than
one — currently no category does, so no B cards appear; T = modal Ego-Exo4D
exemplar, text-only until the license clears. Qualitative sampler picks over
the gold-named share distribution (universe: K≥3, candidate pool &gt; budget):
aligned = argmax share (ties → lowest id); typical = median; missed = zero
share, most clips first (largest K, then lowest id); degenerate = the
lowest-id K=2 question.</p>
<p class="sub">Fact-panel numbers come only from
<code>analysis/slide_stats.json</code> (permutation seed
{S['meta']['perm']['seed']}) and <code>analysis/sampler_diag.json</code>;
composition columns are recomputed from dataset text at build time. Regenerate:
<code>python3 analysis/mvueval_slide_stats.py</code> →
<code>python3 analysis/clip_selection_diagnostic.py --results
'bench/results/bench_mvueval_qa_internvl_mvufullclip_shard*.jsonl' --subset
analysis/mvueval_qa.json --json analysis/sampler_diag.json</code> →
<code>python3 analysis/make_repq_doc.py</code>.</p>
</section>
<footer>Built {manifest['generated']} · backend {S['meta']['backend']} ·
{S['meta']['passes']} passes per question · manifest:
<code>analysis/repq_doc_manifest.json</code></footer>""")

        doc = (f"<title>Representative questions — MVU-Eval & All-Angles</title>\n"
               f"<style>{CSS}</style>\n<main>{''.join(parts)}</main>\n")
        size_mb = len(doc.encode()) / 1e6
        if size_mb <= 12 or attempt == 1:
            break
        print(f"size {size_mb:.1f} MB > 12 MB — retrying with q=60, h=110")

    if size_mb > args.max_html_mb:
        raise SystemExit(f"HTML {size_mb:.1f} MB exceeds --max-html-mb "
                         f"{args.max_html_mb}")

    # manifest pick records (verbatim copies for --verify)
    for ds, picks, key in (("mvu", mvu_picks, "mvu_picks"),
                           ("aab", aab_picks, "aab_picks")):
        for cat, ps in picks.items():
            for r, tag, rule in ps:
                manifest[key].append({
                    "id": r["id"], "task_type": r["task_type"], "tag": tag,
                    "rule": rule, "question": r["question"],
                    "options": r["options"], "answer": r["answer"]})

    with open(args.out, "w") as fh:
        fh.write(doc)
    manifest["html_bytes"] = len(doc.encode())
    json.dump(manifest, open(args.manifest, "w"), indent=1)
    snippet = slack_snippet(diag, gate)
    open(args.slack_out, "w").write(snippet)

    if args.media_out:
        n_folders, n_bytes = export_media(mvu_picks, aab_picks, qe,
                                          args.media_out)
        print(f"wrote {args.media_out} ({n_folders} question folders, "
              f"{n_bytes/1e6:.0f} MB)")
    if args.md_out:
        emit_markdown(args.md_out, S, diag, gate, mvu_by_cat, aab_by_cat,
                      mvu_picks, aab_picks, chips, ego_o2i, qe,
                      args.media_out or "")
        print(f"wrote {args.md_out}")

    by_kind = Counter()
    for a in manifest["assets"]:
        by_kind[a["slot"].split(":")[0] if ":" in a["slot"] else "thumb"] \
            += a["bytes"]
    print(f"wrote {args.out} ({size_mb:.1f} MB; assets: "
          f"{ {k: f'{v/1e6:.1f}MB' for k, v in by_kind.items()} })")
    print(f"wrote {args.manifest}")
    print(f"wrote {args.slack_out}\n\n--- Slack snippet ---\n{snippet}")
    return 0


# ------------------------------------------------------------------ verify
def verify(args):
    M = json.load(open(args.manifest))
    S = json.load(open(STATS))
    diag = json.load(open(DIAG))
    doc = open(args.out).read()
    pools = {"mvu": {r["id"]: r for r in json.load(open(MVU_POOL))},
             "aab": {r["id"]: r for r in json.load(open(AAB_POOL))}}
    errs = []

    # (a) picks byte-identical to pool records
    for key, ds in (("mvu_picks", "mvu"), ("aab_picks", "aab")):
        for p in M[key]:
            rec = pools[ds].get(p["id"])
            if rec is None:
                errs.append(f"{ds} id {p['id']} not in pool")
                continue
            for f in ("question", "options", "answer", "task_type"):
                if rec[f] != p[f]:
                    errs.append(f"{ds} id {p['id']} field {f} differs from pool")

    # (b) all 14 category sections present with >=1 card
    for cat in list(MVU_NAMES) + [c for c in M["categories"] if
                                  c.startswith("AAB-")]:
        n_cards = sum(1 for p in M["mvu_picks"] + M["aab_picks"]
                      if p["task_type"] == cat)
        if n_cards == 0:
            errs.append(f"{cat}: no cards")
        if cat not in M["categories"]:
            errs.append(f"{cat}: no composition block")
    if len([c for c in M["categories"] if c.startswith("MVU-")]) != 8:
        errs.append("MVU categories != 8")
    if len([c for c in M["categories"] if c.startswith("AAB-")]) != 6:
        errs.append("AAB categories != 6")

    # (c) every by_task accuracy quoted in the doc matches slide_stats
    for cat in MVU_NAMES:
        v = S["arrangement"]["mvu_full"]["cvbench_native"]["by_task"][cat]["acc"]
        if f"{v:.1f}" not in doc:
            errs.append(f"{cat}: native by_task acc {v:.1f} not found in doc")

    # (d) appendix numbers match sampler_diag
    g = diag["frame_select"]["gold_named"]
    for v in (f"{g['recall_kept']:.1f}%", f"{g['mean_share']:.3f}",
              f"{g['acc_dropped']:.1f}%"):
        if v not in doc:
            errs.append(f"appendix number {v} not found in doc")

    # (b2) result chips present on every card except the text-only
    # Ego-Exo4D exemplars (no rows exist for those)
    n_empty = doc.count('<div class="chiprow"></div>')
    n_textonly = sum(1 for p in M["aab_picks"] if "Ego-Exo4D" in p["tag"])
    if n_empty != n_textonly:
        errs.append(f"{n_empty} cards have empty result chips but only "
                    f"{n_textonly} text-only picks expected")

    # (e) clip_model uniform across all frame_select rows
    models = set()
    for r in load_rows("bench_mvueval_qa_internvl_mvufullclip_shard*.jsonl"):
        if r["method"] == "frame_select":
            models.add((r.get("frame_alloc") or {}).get("clip_model"))
    if models != {"openai/clip-vit-base-patch32"}:
        errs.append(f"clip_model not uniform: {models}")

    # (f) embedded sheets match the picked sampler ids
    sheet_ids = {int(re.search(r"mvu_(\d+)_frameselect", a["source"]).group(1))
                 for a in M["assets"] if a["slot"].startswith("sheet:")}
    if sheet_ids != set(M["sampler_ids"].values()):
        errs.append(f"sheet ids {sheet_ids} != picked {M['sampler_ids']}")

    # (g) size
    if M["html_bytes"] > args.max_html_mb * 1e6:
        errs.append(f"html {M['html_bytes']/1e6:.1f} MB > {args.max_html_mb}")
    if os.path.getsize(args.out) != M["html_bytes"]:
        errs.append("html on disk differs from manifest html_bytes")

    if errs:
        print("VERIFY FAILED:")
        for e in errs:
            print(" -", e)
        return 1
    print(f"VERIFY OK — {len(M['mvu_picks'])} MVU + {len(M['aab_picks'])} AAB "
          f"picks, {len(M['assets'])} assets, "
          f"{M['html_bytes']/1e6:.1f} MB html")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "repq_doc.html"))
    ap.add_argument("--manifest",
                    default=os.path.join(HERE, "repq_doc_manifest.json"))
    ap.add_argument("--slack-out",
                    default=os.path.join(HERE, "repq_doc_slack.txt"))
    ap.add_argument("--sampler-figs",
                    default=os.path.join(RES, "figs_repq_sampler"))
    ap.add_argument("--md-out", default="",
                    help="also emit a markdown twin to this path")
    ap.add_argument("--media-out", default="",
                    help="copy the picked questions' source clips/images "
                         "into per-question folders under this directory")
    ap.add_argument("--jpeg-q", type=int, default=72)
    ap.add_argument("--thumb-h", type=int, default=140)
    ap.add_argument("--max-html-mb", type=float, default=15)
    ap.add_argument("--list-sampler-ids", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    sys.exit(verify(args) if args.verify else build(args))


if __name__ == "__main__":
    main()
