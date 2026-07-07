"""K-filtered views of the full-1000 CVBench runnable subset, for the D3
top-m selection arms. When top_m >= K the selection keeps ALL clips and the
prompt is byte-identical to temporal_weighted (whose full-1000 rows already
exist), so the top2 arm only needs K>=3 questions and the top3 arm only K=4 —
the remaining bins are composed from the temporal_weighted baseline at
analysis time.

Records are copied unchanged (same ids), so results pool/resume cleanly.

Usage:  python analysis/make_cvbench_k_subsets.py
Writes: analysis/cvbench_full_k34_subset.json  (K >= 3)
        analysis/cvbench_full_k4_subset.json   (K == 4)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "cvbench_full_runnable_subset.json")


def num_videos(rec):
    return sum(1 for i in range(1, 5) if rec.get(f"video_{i}"))


def main():
    recs = json.load(open(SRC))
    for name, keep in (("cvbench_full_k34_subset.json", lambda k: k >= 3),
                       ("cvbench_full_k4_subset.json", lambda k: k == 4)):
        sub = [r for r in recs if keep(num_videos(r))]
        out = os.path.join(HERE, name)
        json.dump(sub, open(out, "w"), indent=1)
        ks = [num_videos(r) for r in sub]
        print(f"{out}: {len(sub)} records, K dist "
              f"{ {k: ks.count(k) for k in sorted(set(ks))} }")


if __name__ == "__main__":
    main()
