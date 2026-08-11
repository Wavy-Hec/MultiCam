"""Offline scorer gate: is CLIP/SigLIP question-vs-thumbnail similarity good
enough to drive clip selection? (No InternVL — minutes of GPU. Run BEFORE
spending full-1000 GPU-hours on a clip_select_* eval.)

Ground truth comes from two question families in the subset:
  primary    questions whose TEXT names exactly one video ("In Video 2 ...")
             -> named-clip recall@1 / recall@2, mean rank, score margin
  secondary  questions whose gold OPTION names exactly one video
             -> argmax agreement (noisier: the gold clip is where the answer
             is visible, not necessarily the clip most similar to the text)

Scoring mirrors ClipScoreSelectMethod._score_clip exactly (same thumbnail
indices, same clip_scores path incl. the SigLIP padding branch), so a scorer
that passes here is the scorer the eval will actually run.

Usage (internvl env; works with HF_HUB_OFFLINE=1 once checkpoints are cached):
  python analysis/clip_scorer_gate.py \
      --subset analysis/crossview_meva1033_subset.json \
      --models openai/clip-vit-base-patch32 google/siglip-so400m-patch14-384
"""
import argparse
import collections
import json
import os
import re
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))            # repo root -> bench pkg
sys.path.insert(0, _HERE)                              # analysis/ scripts
from decord import VideoReader, cpu                            # noqa: E402
from bench.methods.clip_select import clip_scores, option_texts  # noqa: E402
from bench.reuse import video_paths                            # noqa: E402
from clip_selection_diagnostic import VIDEO_RE, gold_option_video  # noqa: E402


def uniform_thumbs(vp, thumbs):
    """The exact frames ClipScoreSelectMethod._score_clip scores."""
    from PIL import Image
    vr = VideoReader(vp, ctx=cpu(0), num_threads=1)
    n_total = len(vr)
    if n_total <= 0:
        raise ValueError("empty clip")
    idx = sorted({min(n_total - 1, int((j + 0.5) * n_total / thumbs))
                  for j in range(thumbs)})
    frames = vr.get_batch(idx).asnumpy()
    return [Image.fromarray(fr).convert("RGB") for fr in frames]


def _thumbs_small(args):
    """Decode one clip's thumbnails in a worker process.

    Decode dominates this gate — a 300 s MEVA .avi costs ~12 s to sample, so a
    40-question CrossView run is ~70 minutes single-threaded and a full-pool run
    is a day. Scoring is milliseconds by comparison. Frames are downscaled here,
    inside the worker, because the whole point is to keep what crosses the
    process boundary small; both scorers resize to 224/384 anyway, so nothing
    the model sees changes.
    """
    vp, thumbs, px = args
    try:
        ims = uniform_thumbs(vp, thumbs)
    except Exception as e:
        return vp, None, f"{type(e).__name__}: {e}"
    out = []
    for im in ims:
        w, h = im.size
        s = px / max(w, h)
        out.append(im.resize((max(1, int(w * s)), max(1, int(h * s)))) if s < 1.0 else im)
    return vp, out, None


def decode_thumbs(paths, thumbs, px=384, workers=0):
    """{path: [PIL] or None} for every unique path, decoded in parallel."""
    uniq = list(dict.fromkeys(paths))
    cache, errs = {}, {}
    if workers and len(uniq) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for vp, ims, err in ex.map(_thumbs_small,
                                       [(p, thumbs, px) for p in uniq], chunksize=1):
                cache[vp] = ims
                if err:
                    errs[vp] = err
    else:
        for p in uniq:
            vp, ims, err = _thumbs_small((p, thumbs, px))
            cache[vp] = ims
            if err:
                errs[vp] = err
    return cache, errs


def load_scorer(model_id):
    import torch
    from transformers import AutoModel, AutoProcessor
    dev = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = AutoModel.from_pretrained(model_id).to(dev).eval()
    proc = AutoProcessor.from_pretrained(model_id)
    return (model, proc, dev)


def question_text(rec, with_options):
    q = rec.get("question", "")
    if with_options:
        q = q + "\n" + "\n".join(rec.get("options", []))
    return q


# option_texts now lives in bench/methods/clip_select.py and is imported above:
# the harness arm and this gate MUST build the query identically, or the gate
# stops predicting what the arm will select.


def groundable(rec, min_words=3):
    """Can this question's options work as retrieval queries at all?

    Two ways they cannot: the option set is shared boilerplate repeated across
    the pool (every CrossView-MEVA Spatial question offers the same four
    distance bands, so the query would be identical for all 431 of them), or the
    options carry no content (roman-numeral orderings, bare 'Video 3', integers).
    Measured over the pools, this is the difference between ~555 usable video
    questions and the 3,357 that exist, so it has to be a reported stratum
    rather than a silent average.
    """
    opts = option_texts(rec)
    if len(opts) < 2:
        return False
    contentful = 0
    for o in opts:
        if re.fullmatch(r"(?i)(video|view)\s*\d+", o):
            continue
        if re.fullmatch(r"(?i)[ivx]+(\s*->\s*[ivx]+)+", o):
            continue
        if re.fullmatch(r"\d+", o):
            continue
        if len(o.split()) >= min_words:
            contentful += 1
    return contentful >= 2


LETTERS = "ABCDEFGHIJKLM"


def modal_letter_floor(recs):
    """Leave-one-out task-conditioned modal-letter floor.

    1/n_options is the wrong baseline wherever the answer key is skewed, and
    CrossView's is: 'C' is gold on 193 of 297 MEVA event-ordering questions and
    'A' on 165 of 305 temporal ones. A guesser that knows only the task type and
    answers its most common letter scores far above 1/n there, so a retriever
    that merely tracks that skew would look like it had found visual signal.
    Scored leave-one-out, so the floor is not fitted on the question it grades.

    Returns {question_id: True/False} for whether the floor gets it right.
    """
    by_task = {}
    for r in recs:
        by_task.setdefault(r.get("task_type"), []).append(
            str(r.get("answer", "")).strip().upper()[:1])
    counts = {tt: collections.Counter(v) for tt, v in by_task.items()}
    out = {}
    for r in recs:
        tt = r.get("task_type")
        gold = str(r.get("answer", "")).strip().upper()[:1]
        c = collections.Counter(counts[tt])
        c[gold] -= 1                      # leave this question out
        if not c or max(c.values()) <= 0:
            out[r["id"]] = False
            continue
        out[r["id"]] = (max(c.items(), key=lambda kv: (kv[1], kv[0]))[0] == gold)
    return out


def report_per_option(results, model_id, floor=None):
    """Does the highest-scoring OPTION match the gold option?

    This is the metric that decides whether option-conditioned selection can
    work at all. Clip recall only says the retriever found the right video;
    option agreement says the option text itself carries the discriminating
    signal, which is what follow-up 1 depends on. Reported against per-question
    chance (1/n_options) and split on whether the options are groundable, since
    pooling a boilerplate stratum in drags any real effect to chance.
    """
    rows = [(rec, pc) for label in ("all", "primary", "secondary")
            for _, _, pc, rec in results[label] if pc.get("by_option")]
    if not rows:
        print("  per-option: no scored rows")
        return
    strata = {"groundable": [], "boilerplate/degenerate": []}
    for rec, pc in rows:
        strata["groundable" if groundable(rec) else "boilerplate/degenerate"].append((rec, pc))
    print("  per-option — does argmax(option) equal the gold option?")
    print(f"  {'stratum':26s} {'n':>5} {'agree':>8} {'chance':>8} {'floor':>8} "
          f"{'vs floor':>9}  by task_type")
    for name, rs in strata.items():
        if not rs:
            continue
        hit, chance, by_tt, fl = 0, [], {}, 0
        for rec, pc in rs:
            mat = [bo for bo in pc["by_option"] if bo]
            if not mat:
                continue
            n_opt = len(mat[0])
            best = [max(bo[i] for bo in mat) for i in range(n_opt)]
            pred = LETTERS[best.index(max(best))]
            ok = pred == str(rec.get("answer", "")).strip().upper()[:1]
            hit += ok
            chance.append(1.0 / n_opt)
            if floor is not None:
                fl += bool(floor.get(rec["id"], False))
            tt = str(rec.get("task_type", "?")).split("-")[-1]
            d = by_tt.setdefault(tt, [0, 0])
            d[0] += ok
            d[1] += 1
        n = len(rs)
        ch = 100.0 * float(np.mean(chance)) if chance else 0.0
        ag = 100.0 * hit / max(n, 1)
        tt_s = "  ".join(f"{k} {100.0*v[0]/v[1]:.0f}% ({v[1]})"
                         for k, v in sorted(by_tt.items()))
        fp = 100.0 * fl / max(n, 1) if floor is not None else float("nan")
        print(f"  {name:26s} {n:5d} {ag:7.1f}% {ch:7.1f}% {fp:7.1f}% "
              f"{ag - fp:+8.1f}  {tt_s}")
    print("  'floor' is the leave-one-out task-conditioned modal-letter guesser; where the "
          "answer key is\n  skewed it, not 1/n, is the number to beat. The degenerate stratum "
          "is a negative control --\n  its options carry no visual content, so any lift it "
          "shows is artefact, and the groundable\n  stratum only demonstrates visual signal "
          "to the extent it clears BOTH the floor and that control.")


def rank_of(target, scores):
    """1-based rank of clip ``target`` (1-based) under descending scores."""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    return order.index(target - 1) + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", default="analysis/crossview_meva1033_subset.json")
    ap.add_argument("--video-root", default="crossview-release-annotations/crossview-release")
    ap.add_argument("--models", nargs="+",
                    default=["openai/clip-vit-base-patch32",
                             "google/siglip-so400m-patch14-384"])
    ap.add_argument("--thumbs", type=int, default=8)
    ap.add_argument("--workers", type=int, default=0,
                    help="parallel decode processes (decode dominates; 0 = serial)")
    ap.add_argument("--thumb-px", type=int, default=384,
                    help="longest side thumbnails are downscaled to before scoring")
    ap.add_argument("--limit", type=int, default=0, help="first N questions only")
    ap.add_argument("--per-option", action="store_true",
                    help="score each answer option SEPARATELY and reduce by max "
                         "over options (meeting follow-up 1); the question is "
                         "never used. Contrast with --with-options, which embeds "
                         "question+all options as ONE string.")
    ap.add_argument("--min-option-words", type=int, default=3,
                    help="--per-option: content words an option needs to count as "
                         "groundable when stratifying")
    ap.add_argument("--with-options", action="store_true",
                    help="score question+options text instead of the question "
                         "alone (a pivot option; production scores question only)")
    ap.add_argument("--out", default=None, help="optional per-question JSON dump")
    args = ap.parse_args()

    recs = json.load(open(args.subset))
    if args.limit:
        recs = recs[:args.limit]
    primary, secondary, allq = [], [], []   # (rec, paths, target 1-based)
    for rec in recs:
        paths = video_paths(rec, args.video_root)
        K = len(paths)
        allq.append((rec, paths, None))
        nums = {int(n) for n in VIDEO_RE.findall(rec["question"])}
        if len(nums) == 1 and 1 <= next(iter(nums)) <= K:
            primary.append((rec, paths, next(iter(nums))))
        else:
            g = gold_option_video(rec)
            if g is not None and 1 <= g <= K:
                secondary.append((rec, paths, g))
    print(f"subset={args.subset}  n={len(recs)}  "
          f"primary(named-in-question)={len(primary)}  "
          f"secondary(gold-option-names-one-video)={len(secondary)}")
    if not primary and not secondary:
        # CrossView asks about events, not clip identity, so no question or gold
        # option ever names a video and the clip-level ground truth is empty.
        # Option agreement does not need it -- it only needs the gold letter.
        print("  no clip-level ground truth in this pool (no question or gold option "
              "names a video); clip recall is undefined here, option agreement is not.")
    for label, qs in (("primary", primary), ("secondary", secondary)):
        ks = [len(p) for _, p, _ in qs]
        if ks:
            print(f"  {label}: K dist "
                  f"{ {k: ks.count(k) for k in sorted(set(ks))} }  "
                  f"random recall@1 {100.0 * np.mean([1.0 / k for k in ks]):.1f}%")

    floor = modal_letter_floor(recs)
    all_paths = [vp for _, paths, _ in allq for vp in paths]
    print(f"decoding {len(set(all_paths))} unique clip(s) "
          f"x {args.thumbs} thumbs with {args.workers or 1} worker(s) ...")
    thumb_cache, decode_errs = decode_thumbs(all_paths, args.thumbs,
                                             args.thumb_px, args.workers)
    if decode_errs:
        print(f"  {len(decode_errs)} clip(s) failed to decode; first: "
              f"{list(decode_errs.items())[0]}")

    dump = []
    for model_id in args.models:
        mode = ("per-option (max over options, question unused)" if args.per_option
                else "question+options" if args.with_options else "question")
        print(f"\n=== {model_id} (thumbs={args.thumbs}, text={mode}) ===")
        bundle = load_scorer(model_id)
        results = {"primary": [], "secondary": [], "all": []}
        n_err = 0
        buckets = [("primary", primary), ("secondary", secondary)]
        if args.per_option:
            buckets.append(("all", allq))
        for label, qs in buckets:
            for rec, paths, target in qs:
                text = (option_texts(rec) if args.per_option
                        else question_text(rec, args.with_options))
                per_clip = {"max": [], "mean": [], "by_option": []}
                for vp in paths:
                    try:
                        ims = thumb_cache.get(vp)
                        if not ims:
                            raise ValueError(decode_errs.get(vp, "no thumbnails"))
                        sims = clip_scores(bundle, text, ims)
                        if sims.ndim == 2:
                            # [thumbs, options] -> best thumb per option, then the
                            # max across options is the clip's score (follow-up 1)
                            per_opt = sims.max(axis=0)
                            per_clip["by_option"].append([float(x) for x in per_opt])
                            per_clip["max"].append(float(per_opt.max()))
                            per_clip["mean"].append(float(sims.mean(axis=0).max()))
                        else:
                            per_clip["max"].append(float(np.max(sims)))
                            per_clip["mean"].append(float(np.mean(sims)))
                    except Exception as e:
                        n_err += 1
                        per_clip["max"].append(float("-inf"))
                        per_clip["mean"].append(float("-inf"))
                        per_clip["by_option"].append(None)
                if all(x == float("-inf") for x in per_clip["max"]):
                    continue
                if label == "all":
                    results["all"].append((rec["id"], None, per_clip, rec))
                    dump.append({"model": model_id, "set": "all", "id": rec["id"],
                                 "task_type": rec.get("task_type"),
                                 "groundable": groundable(rec, args.min_option_words),
                                 **per_clip})
                    continue
                results[label].append((rec["id"], target, per_clip, rec))
                dump.append({"model": model_id, "set": label, "id": rec["id"],
                             "target": target, "task_type": rec.get("task_type"),
                             "groundable": groundable(rec, args.min_option_words),
                             **per_clip})
        if n_err:
            print(f"  decode/score errors on {n_err} clip(s)")

        for stat in ("max", "mean"):
            prim = results["primary"]
            ranks = [rank_of(t, pc[stat]) for _, t, pc, _ in prim]
            r1 = sum(r == 1 for r in ranks)
            r2 = sum(r <= 2 for r in ranks)
            margins = []
            for _, t, pc, _ in prim:
                s = pc[stat]
                others = [x for i, x in enumerate(s) if i != t - 1]
                margins.append(s[t - 1] - max(others))
            sec = results["secondary"]
            sec_hit = sum(rank_of(t, pc[stat]) == 1 for _, t, pc, _ in sec)
            print(f"  stat={stat:4s}  primary recall@1 {r1}/{len(prim)} "
                  f"({100.0 * r1 / max(len(prim), 1):.0f}%)  "
                  f"recall@2 {r2}/{len(prim)} ({100.0 * r2 / max(len(prim), 1):.0f}%)  "
                  f"mean rank {np.mean(ranks):.2f}  "
                  f"mean margin(named-best other) {np.mean(margins):+.4f}")
            print(f"             secondary argmax-agreement {sec_hit}/{len(sec)} "
                  f"({100.0 * sec_hit / max(len(sec), 1):.0f}%)")

        if args.per_option:
            report_per_option(results, model_id, floor)

    if args.out:
        json.dump(dump, open(args.out, "w"), indent=1)
        print(f"\nper-question scores -> {args.out}")


if __name__ == "__main__":
    main()
