"""Aggregate per-question Result rows into the benchmark metrics (M1-M4).

Pure-stdlib (no numpy) so it runs anywhere, including the login node for the
CPU scoring-validation gate.
"""
from collections import defaultdict


def _pct(xs, q):
    xs = sorted(v for v in xs if v is not None)
    if not xs:
        return None
    i = min(len(xs) - 1, int(round(q * (len(xs) - 1))))
    return xs[i]


def _acc(rows):
    n = len(rows)
    c = sum(1 for r in rows if r.get("correct"))
    return {"correct": c, "total": n, "acc": (c / n if n else None)}


def _by(rows, key):
    g = defaultdict(list)
    for r in rows:
        g[r.get(key)].append(r)
    return {str(k): _acc(v) for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}


def summarize(rows):
    """rows: list of Result dicts (a single method x backend, or pooled)."""
    lat = [r.get("latency_s") for r in rows if r.get("latency_s") is not None]
    intok = [r.get("input_tokens") for r in rows if r.get("input_tokens") is not None]
    outtok = [r.get("output_tokens") for r in rows if r.get("output_tokens") is not None]
    calls = [r.get("num_model_calls") for r in rows if r.get("num_model_calls") is not None]
    n = len(rows)
    return {
        "n": n,
        "overall": _acc(rows),                       # M1
        "by_task_type": _by(rows, "task_type"),
        "by_orig_num_cameras": _by(rows, "orig_num_cameras"),
        "by_source": _by(rows, "source"),
        "by_cap_answer_safe": _by(rows, "cap_answer_safe"),
        "latency_s": {                               # M2
            "p50": _pct(lat, 0.50), "p95": _pct(lat, 0.95),
            "mean": (sum(lat) / len(lat) if lat else None), "n": len(lat),
        },
        "tokens": {                                  # M3
            "input_mean": (sum(intok) / len(intok) if intok else None),
            "output_mean": (sum(outtok) / len(outtok) if outtok else None),
            "calls_mean": (sum(calls) / len(calls) if calls else None),
        },
        "abstain_rate": (sum(1 for r in rows if r.get("abstained")) / n if n else None),  # M4
        "errors": sum(1 for r in rows if r.get("error")),
    }


def summarize_by_method_backend(rows):
    """Group rows by (method, backend) and summarize each -> the headline table."""
    g = defaultdict(list)
    for r in rows:
        g[(r.get("method"), r.get("backend"))].append(r)
    return {f"{m}/{b}": summarize(v) for (m, b), v in sorted(g.items())}


def format_summary(rows):
    out = []
    for key, s in summarize_by_method_backend(rows).items():
        ov = s["overall"]
        lat = s["latency_s"]
        out.append(f"\n=== {key} ===")
        acc = f'{ov["acc"]*100:.1f}%' if ov["acc"] is not None else "n/a"
        out.append(f'  overall: {ov["correct"]}/{ov["total"]} = {acc}   '
                   f'abstain={s["abstain_rate"]*100:.0f}%  errors={s["errors"]}'
                   if ov["total"] else "  (no rows)")
        if lat["p50"] is not None:
            out.append(f'  latency_s: p50={lat["p50"]:.1f} p95={lat["p95"]:.1f} mean={lat["mean"]:.1f}')
        if s["tokens"]["input_mean"] is not None:
            out.append(f'  tokens: in~{s["tokens"]["input_mean"]:.0f} out~{s["tokens"]["output_mean"]:.0f} '
                       f'calls~{s["tokens"]["calls_mean"]:.1f}')
        out.append("  by task_type: " + ", ".join(
            f'{k} {v["correct"]}/{v["total"]}' for k, v in s["by_task_type"].items()))
    return "\n".join(out)
