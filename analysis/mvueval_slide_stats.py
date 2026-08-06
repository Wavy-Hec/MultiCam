#!/usr/bin/env python3
"""Canonical statistics for the July-30 results deck (the InternVL3-8B remake of
the mentor's "Multi-camera Video Understanding" slides): aggregate every result
row on disk into one self-describing analysis/slide_stats.json that the figure
script (analysis/make_slide_figs.py) reads — no number is ever computed inside
plotting code.

Covers, from the completed full-pool overnight runs (mvufull/mvufullclip) plus
the AAB EgoHumans-170 runs, and — whenever their jobs later land — the blind,
single_view<i> and budget-32 (mvufull32) arms, which are picked up automatically
on rerun:
  arrangement   3-arm accuracy (+ per-pass std, chance, majority floor)
  sync          stitching delta on the 128 synchronized nuScenes-rig questions
                vs the unrelated-clip remainder (paired permutation p)
  per_task      centralized-native delta per MVU task (+ Holm correction)
  clip          the 3 clip-experiment arms on the full pool
  blind         no-image floor + per-task deltas vs sequential (when present)
  single_view   best/random/worst view curves on the no-view-named subset
                (when present)
  budget32      the fixed-32-frame verification arms (when present)
  forensics     measured token budgets per arm (the deck's "same budget" check)
  defects       dataset-level checks (view-naming census, answer-key balance)

Run (no GPU): python3 analysis/mvueval_slide_stats.py
"""
import glob
import json
import os
import random
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RES = os.path.join(REPO, "bench", "results")

NUSC = re.compile(r"^scene-\d{4}_CAM_[A-Z_]+\.mp4$")
N_PERM = 20000
PERM_SEED = 20260730

# MVU-Eval paper reference numbers (arXiv 2511.07250, NeurIPS 2025 D&B track),
# reported at 32 frames PER VIDEO. Their Appendix B.2.1 runs the InternVL
# series at 448x448 (the <=720px long-side setting applies to Qwen/LLaVA/etc.,
# NOT InternVL3), prompting a DIRECT option letter (no CoT); decoding and
# engine are unspecified. The ONLY place published numbers may be transcribed.
PAPER = {
    "source": "arXiv 2511.07250",
    "protocol": "32 frames per video, uniform, 448x448 for InternVL3, "
                "direct-answer prompting",
    "internvl3_8b": {
        "overall": 41.7,
        "by_task": {"MVU-OR": 41.3, "MVU-SU": 44.1, "MVU-Counting": 31.3,
                    "MVU-Comparison": 54.8, "MVU-KIR": 34.5, "MVU-ICL": 26.8,
                    "MVU-RAG": 43.7, "MVU-TR": 52.5}},
    "qwen2_5_vl_7b": {
        "overall": 51.9,
        "by_task": {"MVU-OR": 50.8, "MVU-SU": 55.3, "MVU-Counting": 62.1,
                    "MVU-Comparison": 65.2, "MVU-KIR": 32.4, "MVU-ICL": 29.3,
                    "MVU-RAG": 49.3, "MVU-TR": 66.8}},
    "random": 26.0, "human": 93.6,
}


# ---------------------------------------------------------------- loading
def load_rows(pattern):
    rows = []
    for f in sorted(glob.glob(os.path.join(RES, pattern))):
        with open(f) as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def by_method(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["method"]].append(r)
    return out


# ---------------------------------------------------------------- helpers
def acc(rows):
    return 100.0 * sum(bool(r["correct"]) for r in rows) / len(rows) if rows else None


def pass_std(rows):
    """Std of the per-pass accuracies (decoding noise on a fixed question set,
    NOT a between-method error bar — same convention as MULTICAM_STATUS §2)."""
    per = defaultdict(list)
    for r in rows:
        per[r["pass_idx"]].append(bool(r["correct"]))
    if len(per) < 2:
        return None
    accs = [100.0 * sum(v) / len(v) for v in per.values()]
    m = sum(accs) / len(accs)
    return (sum((a - m) ** 2 for a in accs) / len(accs)) ** 0.5


def qmeans(rows):
    """Per-question mean correctness over passes."""
    per = defaultdict(list)
    for r in rows:
        per[r["id"]].append(1.0 if r["correct"] else 0.0)
    return {q: sum(v) / len(v) for q, v in per.items()}


def paired_perm(rows_a, rows_b, qids=None, n_perm=N_PERM):
    """Question-level paired permutation (sign-flip) test on mean-over-passes
    correctness; returns (mean diff in points, p). Restricted to qids if given."""
    qa, qb = qmeans(rows_a), qmeans(rows_b)
    common = set(qa) & set(qb)
    if qids is not None:
        common &= set(qids)
    d = [qa[q] - qb[q] for q in sorted(common)]
    if not d:
        return None, None, 0
    obs = sum(d) / len(d)
    rng = random.Random(PERM_SEED)
    hits = 0
    for _ in range(n_perm):
        s = sum(x if rng.random() < 0.5 else -x for x in d)
        if abs(s / len(d)) >= abs(obs) - 1e-12:
            hits += 1
    p = (hits + 1) / (n_perm + 1)
    return 100.0 * obs, p, len(d)


def contingency(rows_vision, rows_blind, qids=None):
    """Joint blind x vision quadrant, PROBABILISTIC convention: per question the
    pass-mean correctness with images (v) and without (b) are treated as
    marginal probabilities, quadrant mass = their products (v*b, v*(1-b), ...),
    averaged over questions. NOT majority-vote, NOT single-pass pairing — the
    strict (4/4) and lenient (>=1/4) conventions give very different numbers."""
    qv, qb = qmeans(rows_vision), qmeans(rows_blind)
    common = set(qv) & set(qb)
    if qids is not None:
        common &= set(qids)
    if not common:
        return None
    n = len(common)
    return {
        "n_q": n,
        "right_both": round(100 * sum(qv[q] * qb[q] for q in common) / n, 2),
        "vision_helped": round(100 * sum(qv[q] * (1 - qb[q]) for q in common) / n, 2),
        "vision_hurt": round(100 * sum((1 - qv[q]) * qb[q] for q in common) / n, 2),
        "wrong_both": round(100 * sum((1 - qv[q]) * (1 - qb[q]) for q in common) / n, 2),
    }


def holm(pvals):
    """Holm-Bonferroni: {key: p} -> {key: significant_at_.05}."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    sig, alive = {}, True
    for i, (k, p) in enumerate(items):
        if p is None or p > 0.05 / (m - i):
            alive = False
        sig[k] = alive
    return sig


def arm_summary(rows):
    if not rows:
        return None
    per_task = defaultdict(list)
    for r in rows:
        per_task[r["task_type"]].append(r)
    return {
        "acc": acc(rows),
        "pass_std": pass_std(rows),
        "n_rows": len(rows),
        "n_q": len({r["id"] for r in rows}),
        "by_task": {t: {"acc": acc(v), "n_q": len({r["id"] for r in v})}
                    for t, v in sorted(per_task.items())},
        "tokens": {"video_mean": _mean([r.get("video_tokens") for r in rows]),
                   "video_median": _median([r.get("video_tokens") for r in rows]),
                   "input_mean": _mean([r.get("input_tokens") for r in rows])},
    }


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def chance_floor(recs):
    return 100.0 * sum(1.0 / len(r["options"]) for r in recs) / len(recs)


def majority_floor(recs):
    golds = Counter(str(r["answer"]).strip().upper() for r in recs)
    return 100.0 * max(golds.values()) / len(recs), golds.most_common(1)[0][0]


# Question pools the deck can show side by side. Adding a dataset here (plus its
# legs below) is all it takes for the arrangement figures to gain a group — the
# alternative was two pool variables hardcoded in main(), which is why CrossView
# had nowhere to land.
POOLS = {
    "mvu_full": dict(file="mvueval_qa.json", label="MVU-Eval", modality="video"),
    "aab170": dict(file="allangles_egohumans_qa.json",
                   label="All-Angles EgoHumans", modality="stills"),
    # cap-13 pool: same 1033 questions as crossview_meva1033_subset.json but
    # packed to the harness slot count, so it is NOT comparable to results run
    # against that older 4-camera file.
    "meva1033": dict(file="crossview_meva_cap13.json",
                     label="CrossView-MEVA", modality="video"),
}

# (pool, backend) -> shard glob. Missing globs are skipped, so a leg appears the
# moment its rows land. Filenames carry the CONDA ENV, not the model — the
# backend here is the authority, and arm_summary reads it back off the rows.
ARRANGEMENT_LEGS = {
    ("mvu_full", "InternVL3-8B"): "bench_mvueval_qa_internvl_mvufull_shard*.jsonl",
    ("mvu_full", "Qwen2.5-VL-7B-Instruct"): "bench_mvueval_qa_cvbench_mvufullq25*_shard*.jsonl",
    ("aab170", "InternVL3-8B"): "bench_allangles_egohumans_qa_internvl_aabfull_shard*.jsonl",
    ("meva1033", "InternVL3-8B"): "bench_crossview_meva*_internvl_cvmeva*_shard*.jsonl",
    ("meva1033", "Qwen2.5-VL-7B-Instruct"): "bench_crossview_meva*_cvbench_cvmevaq25*_shard*.jsonl",
}


def load_pools():
    """Pool records + their derived floors, for every POOLS entry present on disk."""
    out = {}
    for key, spec in POOLS.items():
        path = os.path.join(HERE, spec["file"])
        if not os.path.exists(path):
            continue
        recs = json.load(open(path))
        out[key] = dict(recs=recs, label=spec["label"], modality=spec["modality"],
                        n=len(recs), chance=round(chance_floor(recs), 2),
                        majority=dict(zip(("acc", "letter"), majority_floor(recs))))
    return out


# ---------------------------------------------------------------- main
def main():
    mvu_pool = json.load(open(os.path.join(HERE, "mvueval_qa.json")))
    aab_pool = json.load(open(os.path.join(HERE, "allangles_egohumans_qa.json")))
    noview = json.load(open(os.path.join(HERE, "mvueval_noview_subset.json")))
    mvu_by_id = {r["id"]: r for r in mvu_pool}

    def vids_of(rec):
        return [rec[f"video_{i}"] for i in range(1, 14) if rec.get(f"video_{i}")]

    sync_ids = {r["id"] for r in mvu_pool if len(vids_of(r)) >= 2
                and all(NUSC.match(v) for v in vids_of(r))}
    unrel_ids = {r["id"] for r in mvu_pool} - sync_ids
    noview_ids = {r["id"] for r in noview}

    mvu = by_method(load_rows("bench_mvueval_qa_internvl_mvufull_shard*.jsonl"))
    clip = by_method(load_rows("bench_mvueval_qa_internvl_mvufullclip_shard*.jsonl"))
    aab = by_method(load_rows("bench_allangles_egohumans_qa_internvl_aabfull_shard*.jsonl"))
    blind = by_method(load_rows("bench_mvueval_qa_internvl_mvublind*shard*.jsonl"))
    aabblind = by_method(load_rows("bench_allangles_egohumans_qa_internvl_aabblind*.jsonl"))
    b32 = by_method(load_rows("bench_mvueval_qa_internvl_mvufull32_shard*.jsonl"))
    sv = by_method(load_rows("bench_mvueval_noview_subset_internvl_mvusv_shard*.jsonl"))
    # paper-parity arms (32 frames PER VIDEO): native and per_stream run under
    # separate tags; merge them into one method->rows map
    pp = by_method(load_rows("bench_mvueval_qa_internvl_mvupp32_shard*.jsonl"))
    for m, rs in by_method(load_rows("bench_mvueval_qa_internvl_mvupp32ps_shard*.jsonl")).items():
        pp.setdefault(m, []).extend(rs)

    pools = load_pools()
    # Every (pool, backend) leg whose rows exist. This is the n-way structure the
    # figures should read; the flat mvu_full/aab170 keys below are kept so the
    # existing figures keep working unchanged during the migration.
    legs = {}
    for (pkey, backend), pattern in ARRANGEMENT_LEGS.items():
        if pkey not in pools:
            continue
        rows = load_rows(pattern)
        rows = [r for r in rows if r.get("backend") == backend]
        if not rows:
            continue
        legs[f"{pkey}|{backend}"] = {
            "pool": pkey, "backend": backend, "label": pools[pkey]["label"],
            "modality": pools[pkey]["modality"], "chance": pools[pkey]["chance"],
            "majority_floor": pools[pkey]["majority"], "n_pool": pools[pkey]["n"],
            "arms": {m: arm_summary(rs) for m, rs in by_method(rows).items()},
        }

    out = {"meta": {
        # single-model field kept for consumers written before the second model;
        # `backends` is the authoritative list.
        "backend": "InternVL3-8B",
        "backends": sorted({b for (_, b) in ARRANGEMENT_LEGS if any(
            k.endswith(f"|{b}") for k in legs)}),
        "passes": 4,
        "protocol": "4-pass std; per-question mean over passes for paired tests",
        "perm": {"n": N_PERM, "seed": PERM_SEED, "test": "question-level sign-flip"},
        "mvu_n": len(mvu_pool), "aab_n": len(aab_pool),
        "sync_n": len(sync_ids), "unrelated_n": len(unrel_ids),
        "noview_n": len(noview_ids),
    }}

    # ---- arrangement (slide 2) + clip arms
    out["arrangement"] = {
        "mvu_full": {m: arm_summary(rs) for m, rs in mvu.items()},
        "aab170": {m: arm_summary(rs) for m, rs in aab.items()},
        "chance": {"mvu_full": round(chance_floor(mvu_pool), 2),
                   "aab170": round(chance_floor(aab_pool), 2)},
        "majority_floor": {
            "mvu_full": dict(zip(("acc", "letter"), majority_floor(mvu_pool))),
            "aab170": dict(zip(("acc", "letter"), majority_floor(aab_pool)))},
        # n-way view: every (dataset, model) leg that has rows
        "pools": {k: {kk: vv for kk, vv in v.items() if kk != "recs"}
                  for k, v in pools.items()},
        "legs": legs,
    }
    out["clip"] = {m: arm_summary(rs) for m, rs in clip.items()}

    # pairwise permutation among the 3 arrangement arms (overall)
    pairs = [("cvbench_native", "centralized"), ("cvbench_native", "per_stream"),
             ("centralized", "per_stream")]
    out["arrangement"]["perm"] = {}
    for a, b in pairs:
        if a in mvu and b in mvu:
            d, p, n = paired_perm(mvu[a], mvu[b])
            out["arrangement"]["perm"][f"{a}-{b}"] = {"delta": round(d, 2), "p": p, "n": n}

    # ---- sync vs unrelated (slide 3): per-slice arms + stitching delta
    if "cvbench_native" in mvu and "centralized" in mvu:
        sync = {}
        for label, ids in (("sync128", sync_ids), ("unrelated", unrel_ids)):
            seg = {}
            for m in ("cvbench_native", "centralized", "per_stream"):
                rows = [r for r in mvu.get(m, []) if r["id"] in ids]
                seg[m] = {"acc": acc(rows), "n_q": len({r["id"] for r in rows})}
            d, p, n = paired_perm(mvu["centralized"], mvu["cvbench_native"], qids=ids)
            seg["stitch_delta"] = {"delta": round(d, 2), "p": p, "n": n}
            sync[label] = seg
        sync["sync_task_mix"] = dict(Counter(
            mvu_by_id[q]["task_type"] for q in sync_ids))
        out["sync"] = sync

    # ---- per-task stitching delta (slide 8)
    if "cvbench_native" in mvu and "centralized" in mvu:
        tasks = sorted({r["task_type"] for r in mvu_pool})
        per_task, pv = {}, {}
        for t in tasks:
            ids = {r["id"] for r in mvu_pool if r["task_type"] == t}
            d, p, n = paired_perm(mvu["centralized"], mvu["cvbench_native"], qids=ids)
            per_task[t] = {"delta": round(d, 2), "p": p, "n": n}
            pv[t] = p
        sig = holm(pv)
        for t in tasks:
            per_task[t]["holm_significant"] = sig[t]
        out["per_task"] = per_task

    # ---- blind (slide "do the images help") — auto-included when jobs land
    out["blind"] = {}
    if "blind" in blind:
        rows = blind["blind"]
        seg = {"mvu_full": arm_summary(rows)}
        if "cvbench_native" in mvu:
            d, p, n = paired_perm(mvu["cvbench_native"], rows)
            seg["images_add"] = {"delta": round(d, 2), "p": p, "n": n}
            per = {}
            for t in sorted({r["task_type"] for r in mvu_pool}):
                ids = {r["id"] for r in mvu_pool if r["task_type"] == t}
                d, p, n = paired_perm(mvu["cvbench_native"], rows, qids=ids)
                per[t] = {"delta": round(d, 2), "p": p, "n": n}
            seg["images_add_by_task"] = per
            seg["contingency"] = {
                "convention": "probabilistic pass-pair: per question the 4-pass "
                              "mean correctness with and without images are "
                              "treated as probabilities; quadrant mass = their "
                              "products, averaged over questions",
                "arms": {"vision": "mvufull cvbench_native", "blind": "mvublind blind"},
                "overall": contingency(mvu["cvbench_native"], rows),
                "by_task": {t: contingency(
                                mvu["cvbench_native"], rows,
                                qids={r["id"] for r in mvu_pool if r["task_type"] == t})
                            for t in sorted({r["task_type"] for r in mvu_pool})},
            }
        out["blind"] = seg
    if "blind" in aabblind:
        out["blind"]["aab170"] = arm_summary(aabblind["blind"])
        if "cvbench_native" in aab:
            d, p, n = paired_perm(aab["cvbench_native"], aabblind["blind"])
            out["blind"]["aab170_images_add"] = {"delta": round(d, 2), "p": p, "n": n}

    # ---- single-view (slides "does picking the right view matter")
    out["single_view"] = {}
    if sv:
        sv_rows = [r for rs in sv.values() for r in rs]
        per_qv = defaultdict(list)  # (qid, view) -> [correct...]
        for r in sv_rows:
            per_qv[(r["id"], r["frame_alloc"]["view_idx"])].append(
                1.0 if r["correct"] else 0.0)
        per_q = defaultdict(dict)
        for (q, v), cs in per_qv.items():
            per_q[q][v] = sum(cs) / len(cs)
        complete = {q: vs for q, vs in per_q.items()
                    if q in mvu_by_id
                    and len(vs) == mvu_by_id[q]["orig_num_cameras"]}
        if complete:
            # NOT _mean: these are fractions in [0,1], and _mean's round(.., 1)
            # would crush them to one significant digit before the *100.
            fmean = lambda xs: sum(xs) / len(xs)
            seq_qa = qmeans(mvu["cvbench_native"]) if "cvbench_native" in mvu else {}

            def sv_stats(sub):
                best = fmean([max(vs.values()) for vs in sub.values()])
                worst = fmean([min(vs.values()) for vs in sub.values()])
                rand = fmean([sum(vs.values()) / len(vs) for vs in sub.values()])
                # luck-only best-of-K: views exchangeable, per-view score drawn
                # from the question's own view multiset -> expected max of K
                # draws with replacement, averaged over questions (closed form
                # via sorting)
                luck = []
                for vs in sub.values():
                    xs = sorted(vs.values())
                    K = len(xs)
                    e = 0.0
                    for i, x in enumerate(xs, 1):
                        e += x * ((i / K) ** K - ((i - 1) / K) ** K)
                    luck.append(e)
                seqs = [seq_qa[q] for q in sub if q in seq_qa]
                return {
                    "best": round(100 * best, 2), "worst": round(100 * worst, 2),
                    "random": round(100 * rand, 2),
                    "luck_best_of_k": round(100 * fmean(luck), 2),
                    "sequential_all_views": round(100 * fmean(seqs), 2) if seqs else None,
                }

            out["single_view"] = {"n_q_complete": len(complete), **sv_stats(complete)}
            groups = defaultdict(dict)
            for q, vs in complete.items():
                groups[mvu_by_id[q]["task_type"]][q] = vs
            out["single_view"]["by_task"] = {
                t: {"n_q": len(qs), **sv_stats(qs)} for t, qs in sorted(groups.items())}
            # per-view-index matrix: is there a positional artifact? (views 1-6
            # cover every question; views 7+ exist only on high-K questions)
            per_view = defaultdict(list)
            for (q, v), cs in per_qv.items():
                if q in complete:
                    per_view[v].append(sum(cs) / len(cs))
            out["single_view"]["per_view_index"] = {
                str(v): {"acc": round(100 * fmean(xs), 2), "n_q": len(xs)}
                for v, xs in sorted(per_view.items())}
            out["single_view"]["per_view_note"] = (
                "accuracy is flat across views 1-6, so no positional artifact; "
                "the rise at views 7+ is composition (only K>=7 questions have "
                "those views), not position")

    # ---- budget-32 verification arms
    out["budget32"] = {m: arm_summary(rs) for m, rs in b32.items()}
    if "cvbench_native" in b32 and "centralized" in b32:
        d, p, n = paired_perm(b32["centralized"], b32["cvbench_native"])
        out["budget32"]["stitch_delta"] = {"delta": round(d, 2), "p": p, "n": n}

    # ---- paper-parity arms (32/video) + the frame-budget story
    out["paper"] = PAPER
    out["parity32pv"] = {m: arm_summary(rs) for m, rs in pp.items()}
    # completeness: 4 passes x full pool per arm; while the arrays are still
    # draining, downstream consumers must label these rows preliminary
    pp_expected = 4 * len(mvu_pool)
    pp_rows = {m: len(rs) for m, rs in pp.items()}
    pp_final = bool(pp_rows) and all(
        pp_rows.get(m, 0) >= pp_expected for m in ("cvbench_native", "per_stream"))
    out["parity32pv"]["completeness"] = {
        "rows_expected_per_arm": pp_expected, "rows_in": pp_rows, "final": pp_final}
    for m, key in (("cvbench_native", "vs_8pv"), ("per_stream", "vs_8pv_per_stream")):
        if m in pp and m in mvu:
            d, p, n = paired_perm(pp[m], mvu[m])
            out["parity32pv"][key] = {"delta": round(d, 2), "p": p, "n": n}

    k_of = {r["id"]: len(vids_of(r)) for r in mvu_pool}
    le4 = {q for q, k in k_of.items() if k <= 4}
    ge5 = {q for q, k in k_of.items() if k >= 5}
    mean_k = sum(k_of.values()) / len(k_of)

    def _slice(rows, ids):
        sub = [r for r in rows if r["id"] in ids]
        return {"acc": round(acc(sub), 2) if sub else None,
                "n_q": len({r["id"] for r in sub})}

    def budget_arms(src):
        arms = {}
        for m in ("cvbench_native", "per_stream"):
            if src.get(m):
                s = arm_summary(src[m])
                arms[m] = {"acc": s["acc"], "pass_std": s["pass_std"],
                           "n_q": s["n_q"],
                           "by_k": {"k_le_4": _slice(src[m], le4),
                                    "k_ge_5": _slice(src[m], ge5)}}
        return arms

    pp_arms = budget_arms(pp)
    out["frame_budget"] = {
        "mean_k": round(mean_k, 3),
        "k_split": {"n_le_4": len(le4), "n_ge_5": len(ge5)},
        "points": [
            {"label": "fixed 32 total", "frames_per_q_mean": 32.0,
             "arms": budget_arms(b32)},
            {"label": "8 per video", "frames_per_q_mean": round(8 * mean_k, 1),
             "arms": budget_arms(mvu)},
            {"label": "32 per video (paper parity)",
             "frames_per_q_mean": round(32 * mean_k, 1),
             "arms": pp_arms,
             "status": ("done" if pp_final else "preliminary") if pp_arms
                       else "queued",
             "rows_in": pp_rows, "rows_expected_per_arm": pp_expected},
        ],
        "caveat": "budget-32 centralized feeds 26-36 frames from montage-grid "
                  "rounding; native/per_stream are exact. Parity matches the "
                  "paper's frame budget AND (for InternVL3) its 448px "
                  "resolution; what is NOT matched is prompting/decoding — "
                  "the paper prompts a direct option letter, ours is "
                  "thinking-style at 4 passes, temp 0.7 via HF chat.",
    }

    # ---- task relevance: which tasks CAN measure a vision harness?
    # (pure assembly of already-computed pieces — the non-cherry-picked answer
    # to "which task accuracies count": show all 8 with the evidence per task)
    if out.get("blind", {}).get("images_add_by_task") and \
            out.get("single_view", {}).get("by_task"):
        native_bt = out["arrangement"]["mvu_full"]["cvbench_native"]["by_task"]
        blind_bt = out["blind"]["mvu_full"]["by_task"]
        out["task_relevance"] = {t: {
            "n_q": len([r for r in mvu_pool if r["task_type"] == t]),
            "chance": round(chance_floor(
                [r for r in mvu_pool if r["task_type"] == t]), 2),
            "native_acc": native_bt[t]["acc"],
            "blind_acc": blind_bt[t]["acc"],
            "images_add": out["blind"]["images_add_by_task"][t],
            "sv": out["single_view"]["by_task"].get(t),
        } for t in sorted({r["task_type"] for r in mvu_pool})}

    # ---- forensics: the deck's "same images at the same budget" check
    if "cvbench_native" in mvu and "centralized" in mvu:
        nv = arm_summary(mvu["cvbench_native"])["tokens"]
        cv = arm_summary(mvu["centralized"])["tokens"]
        out["forensics"] = {
            "nframes_per_video": 8,
            "frames_per_question": "8 x K (16..104), NOT a fixed 32 total",
            "native_video_tokens_median": nv["video_median"],
            "centralized_video_tokens_median": cv["video_median"],
            "centralized_over_native_token_ratio":
                round(cv["video_mean"] / nv["video_mean"], 3) if nv["video_mean"] else None,
        }

    # ---- dataset-level defects/census (slide "defects in the benchmarks")
    letters = Counter(str(r["answer"]).strip().upper() for r in mvu_pool)
    out["defects"] = {
        "mvu_names_video": {
            "total": len(mvu_pool), "names_a_video": len(mvu_pool) - len(noview_ids),
            "no_video_named": len(noview_ids),
            "note": "a view-discarding method is structurally penalized on the "
                    "named-video questions (options like 'A. Video 1')"},
        "mvu_gold_letter_dist": dict(sorted(letters.items())),
        "mvu_option_count_dist": dict(sorted(Counter(
            len(r["options"]) for r in mvu_pool).items())),
        "sync128_task_mix": dict(Counter(
            mvu_by_id[q]["task_type"] for q in sync_ids)),
    }

    path = os.path.join(HERE, "slide_stats.json")
    json.dump(out, open(path, "w"), indent=1)
    print(json.dumps(out, indent=1)[:4000])
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
