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
      --subset analysis/cvbench_full_runnable_subset.json \
      --video-root Video-R1/src/r1-v/Evaluation/CVBench \
      --models openai/clip-vit-base-patch32 google/siglip-so400m-patch14-384
"""
import argparse
import json
import os
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


def rank_of(target, scores):
    """1-based rank of clip ``target`` (1-based) under descending scores."""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    return order.index(target - 1) + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", default="analysis/cvbench_full_runnable_subset.json")
    ap.add_argument("--video-root", default="Video-R1/src/r1-v/Evaluation/CVBench")
    ap.add_argument("--models", nargs="+",
                    default=["openai/clip-vit-base-patch32",
                             "google/siglip-so400m-patch14-384"])
    ap.add_argument("--thumbs", type=int, default=8)
    ap.add_argument("--with-options", action="store_true",
                    help="score question+options text instead of the question "
                         "alone (a pivot option; production scores question only)")
    ap.add_argument("--out", default=None, help="optional per-question JSON dump")
    args = ap.parse_args()

    recs = json.load(open(args.subset))
    primary, secondary = [], []   # (rec, paths, target 1-based)
    for rec in recs:
        paths = video_paths(rec, args.video_root)
        K = len(paths)
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
    for label, qs in (("primary", primary), ("secondary", secondary)):
        ks = [len(p) for _, p, _ in qs]
        if ks:
            print(f"  {label}: K dist "
                  f"{ {k: ks.count(k) for k in sorted(set(ks))} }  "
                  f"random recall@1 {100.0 * np.mean([1.0 / k for k in ks]):.1f}%")

    dump = []
    for model_id in args.models:
        print(f"\n=== {model_id} (thumbs={args.thumbs}, "
              f"text={'question+options' if args.with_options else 'question'}) ===")
        bundle = load_scorer(model_id)
        results = {"primary": [], "secondary": []}
        n_err = 0
        for label, qs in (("primary", primary), ("secondary", secondary)):
            for rec, paths, target in qs:
                text = question_text(rec, args.with_options)
                per_clip = {"max": [], "mean": []}
                for vp in paths:
                    try:
                        sims = clip_scores(bundle, text, uniform_thumbs(vp, args.thumbs))
                        per_clip["max"].append(float(np.max(sims)))
                        per_clip["mean"].append(float(np.mean(sims)))
                    except Exception as e:
                        n_err += 1
                        per_clip["max"].append(float("-inf"))
                        per_clip["mean"].append(float("-inf"))
                if all(x == float("-inf") for x in per_clip["max"]):
                    continue
                results[label].append((rec["id"], target, per_clip))
                dump.append({"model": model_id, "set": label, "id": rec["id"],
                             "target": target, **per_clip})
        if n_err:
            print(f"  decode/score errors on {n_err} clip(s)")

        for stat in ("max", "mean"):
            prim = results["primary"]
            ranks = [rank_of(t, pc[stat]) for _, t, pc in prim]
            r1 = sum(r == 1 for r in ranks)
            r2 = sum(r <= 2 for r in ranks)
            margins = []
            for _, t, pc in prim:
                s = pc[stat]
                others = [x for i, x in enumerate(s) if i != t - 1]
                margins.append(s[t - 1] - max(others))
            sec = results["secondary"]
            sec_hit = sum(rank_of(t, pc[stat]) == 1 for _, t, pc in sec)
            print(f"  stat={stat:4s}  primary recall@1 {r1}/{len(prim)} "
                  f"({100.0 * r1 / max(len(prim), 1):.0f}%)  "
                  f"recall@2 {r2}/{len(prim)} ({100.0 * r2 / max(len(prim), 1):.0f}%)  "
                  f"mean rank {np.mean(ranks):.2f}  "
                  f"mean margin(named-best other) {np.mean(margins):+.4f}")
            print(f"             secondary argmax-agreement {sec_hit}/{len(sec)} "
                  f"({100.0 * sec_hit / max(len(sec), 1):.0f}%)")

    if args.out:
        json.dump(dump, open(args.out, "w"), indent=1)
        print(f"\nper-question scores -> {args.out}")


if __name__ == "__main__":
    main()
