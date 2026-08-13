"""Calibrate the option-union similarity threshold from EXISTING gate outputs.

The _optu arms (bench/methods/option_union.py) keep a clip when its similarity
to ANY answer option passes a threshold. Raw cosine scales differ per scorer
(CLIP ~0.15-0.35, SigLIP lower and wider), so an absolute --sel-tau must be
calibrated per scorer — and the per-option score matrices the offline gate
already wrote (analysis/records/gate_peropt*.json, ``by_option`` = [clips x
options]) are exactly the data to do it with. No GPU, no new scoring.

There is no clip-level ground truth on these pools (the gates report
primary=secondary=0), so this cannot pick tau by retrieval recall; it picks
tau by SELECTIVITY — what fraction of a question's clips the union keeps —
which is the lever the arm actually pulls (keep everything = sequential
baseline in disguise; keep argmax-only = top-1 selection). Report per
groundable/degenerate stratum: a tau whose keep-rate looks the same on the
boilerplate stratum is not selecting on content.

Usage:
  python3 analysis/calibrate_union_tau.py                 # all gate files
  python3 analysis/calibrate_union_tau.py --target-keep 0.5
"""
import argparse
import glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GLOB = os.path.join(HERE, "records", "gate_peropt*.json")


def question_matrices(entries):
    """[(groundable, M[K, n_opts])] for entries carrying a usable by_option."""
    out = []
    for e in entries:
        bo = e.get("by_option")
        if not bo:
            continue
        M = np.asarray(bo, dtype=float)
        if M.ndim != 2 or M.shape[0] < 2:
            continue
        out.append((bool(e.get("groundable")), M))
    return out


def union_keep(M, tau):
    """Fraction of clips the union keeps at absolute threshold ``tau``, with
    the per-option argmax guarantee the arm applies (union is never empty)."""
    K, n_opts = M.shape
    kept = set()
    for j in range(n_opts):
        kept |= {i for i in range(K) if M[i, j] >= tau}
        kept.add(int(np.argmax(M[:, j])))
    return len(kept) / K


def quantile_keep(M, q):
    """Same, with each option's own q-quantile as its threshold."""
    K, n_opts = M.shape
    kept = set()
    for j in range(n_opts):
        t = np.quantile(M[:, j], q)
        kept |= {i for i in range(K) if M[i, j] >= t}
        kept.add(int(np.argmax(M[:, j])))
    return len(kept) / K


def summarize(mats, taus, quantiles):
    scores = np.concatenate([M.ravel() for _, M in mats])
    rows_abs = []
    for tau in taus:
        keeps = [union_keep(M, tau) for _, M in mats]
        rows_abs.append((tau, float(np.mean(keeps)),
                         float(np.mean([k >= 0.999 for k in keeps])),
                         float(np.mean([abs(k * M.shape[0] - len(set(
                             int(np.argmax(M[:, j])) for j in range(M.shape[1])))) < 1e-9
                             for k, (_, M) in zip(keeps, mats)]))))
    rows_q = []
    for q in quantiles:
        keeps = [quantile_keep(M, q) for _, M in mats]
        rows_q.append((q, float(np.mean(keeps)),
                       float(np.mean([k >= 0.999 for k in keeps]))))
    return scores, rows_abs, rows_q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gates", nargs="*", default=None,
                    help=f"gate JSON files/globs (default {DEFAULT_GLOB})")
    ap.add_argument("--target-keep", type=float, default=0.5,
                    help="recommend the tau whose mean union keep-rate is "
                         "closest to this fraction of clips")
    ap.add_argument("--quantiles", default="0.6,0.75,0.85,0.9")
    args = ap.parse_args()

    paths = []
    for g in (args.gates or [DEFAULT_GLOB]):
        paths += sorted(glob.glob(g)) if any(c in g for c in "*?[") else [g]
    paths = [p for p in dict.fromkeys(paths)
             if os.path.exists(p) and "backup" not in os.path.basename(p)]
    if not paths:
        raise SystemExit(f"no gate files found (looked at {args.gates or DEFAULT_GLOB})")
    quantiles = [float(q) for q in args.quantiles.split(",") if q.strip()]

    for path in paths:
        entries = json.load(open(path))
        by_model = {}
        for e in entries:
            by_model.setdefault(e.get("model", "?"), []).append(e)
        for model, ents in by_model.items():
            mats = question_matrices(ents)
            if not mats:
                print(f"\n== {os.path.basename(path)} [{model}] — no by_option "
                      "matrices (rerun the gate with --per-option)")
                continue
            pool = ents[0].get("set", "?")
            for label, sel in (("groundable", [m for m in mats if m[0]]),
                               ("degenerate", [m for m in mats if not m[0]])):
                if not sel:
                    continue
                scores, rows_abs, rows_q = summarize(
                    sel, taus=np.percentile(
                        np.concatenate([M.ravel() for _, M in sel]),
                        [50, 70, 80, 85, 90, 93, 95, 97, 99]).tolist(),
                    quantiles=quantiles)
                print(f"\n== {os.path.basename(path)} [{model}] {pool} "
                      f"— {label}, n={len(sel)} questions")
                print(f"   score dist: p5={np.percentile(scores, 5):.4f} "
                      f"p50={np.percentile(scores, 50):.4f} "
                      f"p95={np.percentile(scores, 95):.4f}")
                print("   abs tau -> mean union keep-rate (share keeping ALL clips)")
                best = min(rows_abs, key=lambda r: abs(r[1] - args.target_keep))
                for tau, keep, all_frac, _ in rows_abs:
                    mark = "  <-- recommend (--sel-tau)" if tau == best[0] else ""
                    print(f"     {tau:.4f} -> {keep:5.1%}  (ALL: {all_frac:5.1%}){mark}")
                print("   quantile q -> mean union keep-rate (share keeping ALL)")
                for q, keep, all_frac in rows_q:
                    print(f"     q={q:.2f} -> {keep:5.1%}  (ALL: {all_frac:5.1%})")


if __name__ == "__main__":
    main()
