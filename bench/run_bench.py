"""Run the multi-camera benchmark: methods x backends over a subset.

Usage (from repo root):
  python -m bench.run_bench --subset analysis/crossview_combined_subset.json \
      --methods centralized,per_stream --backends qwen3vl,qwen3vl-instruct --limit 5

Writes one Result per line to a JSONL (resumable), then prints + saves a
per-(method/backend) summary. Backends load once and are reused across methods.
"""
import argparse
import json
import os

from .reuse import DEFAULT_VIDEO_ROOT
from .methods.centralized import CentralizedMethod
from .methods.per_stream import PerStreamMethod
from .backends.qwen import QwenBackend, QWEN_ALIASES
from . import metrics

METHODS = {"centralized": CentralizedMethod, "per_stream": PerStreamMethod}


def make_backend(alias):
    if alias in QWEN_ALIASES:
        return QwenBackend(QWEN_ALIASES[alias])
    if "/" in alias:  # raw HF id, assumed Qwen-family / generic image-text-to-text
        return QwenBackend(alias)
    raise SystemExit(
        f"unknown backend '{alias}'. Known: {list(QWEN_ALIASES)}. "
        "(InternVL3 runs via the lmms-eval leg, not this backend yet.)")


def load_done(path):
    done = set()
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                done.add((r.get("id"), r.get("method"), r.get("backend")))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", required=True)
    ap.add_argument("--methods", default="centralized")
    ap.add_argument("--backends", default="qwen3vl")
    ap.add_argument("--limit", type=int, default=0, help="only first N records (smoke test)")
    ap.add_argument("--video-root", default=DEFAULT_VIDEO_ROOT)
    ap.add_argument("--nframes", type=int, default=8)
    ap.add_argument("--max-new-tokens", type=int, default=8192)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    data = json.load(open(args.subset))
    if args.limit:
        data = data[: args.limit]
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    for m in methods:
        if m not in METHODS:
            raise SystemExit(f"unknown method '{m}'. Known: {list(METHODS)}")

    out = args.out or os.path.join(
        os.path.dirname(__file__), "results",
        f"bench_{os.path.splitext(os.path.basename(args.subset))[0]}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    done = load_done(out)
    print(f"subset={args.subset} n={len(data)} methods={methods} backends={backends}")
    print(f"video_root={args.video_root}\nout={out} (already done: {len(done)})", flush=True)

    from tqdm import tqdm
    with open(out, "a") as fh:
        for b in backends:
            backend = make_backend(b)  # loads the model once
            for mname in methods:
                method = METHODS[mname](backend, nframes=args.nframes,
                                        max_new_tokens=args.max_new_tokens)
                todo = [r for r in data if (r["id"], mname, backend.name) not in done]
                for rec in tqdm(todo, desc=f"{mname}/{backend.name}"):
                    res = method.answer(rec, args.video_root)
                    fh.write(json.dumps(res.to_dict(), ensure_ascii=False) + "\n")
                    fh.flush()

    rows = [json.loads(l) for l in open(out) if l.strip()]
    print(metrics.format_summary(rows))
    sumpath = out.replace(".jsonl", "_summary.json")
    json.dump(metrics.summarize_by_method_backend(rows), open(sumpath, "w"), indent=2)
    print(f"\nsummary -> {sumpath}")


if __name__ == "__main__":
    main()
