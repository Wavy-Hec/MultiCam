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
import json
import os
import re
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))            # repo root -> bench pkg
sys.path.insert(0, _HERE)                              # analysis/ scripts
from decord import VideoReader, cpu                            # noqa: E402
from bench.methods.clip_select import clip_scores              # noqa: E402
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


OPT_PREFIX = re.compile(r"^\s*[A-Za-z]\s*[.)]\s*")   # == Video-R1/src/eval_thinking.py


def option_texts(rec):
    """The answer options as retrieval queries, letter prefix stripped.

    This is the meeting's follow-up 1 formulation: score against EACH option and
    reduce by max, with the question never used. Unlike --with-options, which
    embeds one concatenated blob, each option is embedded on its own, so nothing
    is lost to the text encoder's 64/77-token cap.
    """
    return [OPT_PREFIX.sub("", str(o)).strip() for o in rec.get("options", [])]


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


def report_per_option(results, model_id):
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
    print(f"  {'stratum':26s} {'n':>5} {'agree':>8} {'chance':>8} {'lift':>7}  by task_type")
    for name, rs in strata.items():
        if not rs:
            continue
        hit, chance, by_tt = 0, [], {}
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
            tt = str(rec.get("task_type", "?")).split("-")[-1]
            d = by_tt.setdefault(tt, [0, 0])
            d[0] += ok
            d[1] += 1
        n = len(rs)
        ch = 100.0 * float(np.mean(chance)) if chance else 0.0
        ag = 100.0 * hit / max(n, 1)
        tt_s = "  ".join(f"{k} {100.0*v[0]/v[1]:.0f}% ({v[1]})"
                         for k, v in sorted(by_tt.items()))
        print(f"  {name:26s} {n:5d} {ag:7.1f}% {ch:7.1f}% {ag - ch:+6.1f}  {tt_s}")
    print("  A lift near zero on the groundable stratum means the option text carries no "
          "visual signal;\n  option-conditioned selection cannot beat question-conditioned "
          "selection and 4a is not worth GPU time.")


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
                        sims = clip_scores(bundle, text, uniform_thumbs(vp, args.thumbs))
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
            report_per_option(results, model_id)

    if args.out:
        json.dump(dump, open(args.out, "w"), indent=1)
        print(f"\nper-question scores -> {args.out}")


if __name__ == "__main__":
    main()
