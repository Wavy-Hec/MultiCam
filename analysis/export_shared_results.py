#!/usr/bin/env python3
"""Package the valid result legs for the shared multicam-harness repo.

One merged JSONL per leg file group (a group = every method that wrote into
one shard glob), full rows, plus the registry that says what each file is,
a one-line-per-leg summary.csv, the subset JSONs a reader needs to resolve
(dataset, id), and a README. Reads the registry that
export_question_records.py writes, so run that first; nothing here touches
a GPU or the raw shards.

What goes in, and what does not:
  * media_ok legs only. The pre-remux MEVA legs decoded the first seconds of
    every clip (see CLAUDE.md) and are listed in the README as excluded.
  * incomplete legs stay in, flagged `complete: false` in registry.json and
    summary.csv — dropping a file group would drop its complete siblings.
  * rescored shards are preferred, raw shards are the fallback, exactly as
    the registry itself was built.
  * every row is stamped `dataset` (subset stem, if absent), `leg` and
    `source_commit`; nothing else is altered.

    python3 analysis/export_shared_results.py --out /path/to/stage           # plain JSONL
    python3 analysis/export_shared_results.py --out ~/multicam-harness --gzip --slim

`--out` is the ROOT the tree is written under: <out>/multicam_results/ and
<out>/data/subsets/ (only subsets missing there; existing files are never
overwritten, a differing one is reported).
"""
import argparse
import csv
import glob
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from export_question_records import RES, leg_tag  # noqa: E402

REGISTRY = os.path.join(HERE, "records", "registry.json")
SLIM_DROP = ("response_text", "think", "frame_alloc")
FOLDER = "multicam_results"


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def shard_files(g):
    files = sorted(glob.glob(os.path.join(RES, "rescored", g)))
    src = "rescored"
    if not files:
        files = sorted(glob.glob(os.path.join(RES, g)))
        src = "raw"
    return files, src


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="root to write under")
    ap.add_argument("--gzip", action="store_true", help="write legs/*.jsonl.gz")
    ap.add_argument("--slim", action="store_true",
                    help="also write slim/*.jsonl without response_text, think, frame_alloc")
    ap.add_argument("--allow-mismatch", action="store_true",
                    help="warn instead of stop when merged rows != registry rows")
    args = ap.parse_args()

    reg = json.load(open(REGISTRY))["legs"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO).decode().strip()

    groups = OrderedDict()
    for leg in reg:
        groups.setdefault(leg["glob"], []).append(leg)

    out_root = os.path.abspath(args.out)
    out = os.path.join(out_root, FOLDER)
    legs_dir = os.path.join(out, "legs")
    os.makedirs(legs_dir, exist_ok=True)
    slim_dir = os.path.join(out, "slim")
    if args.slim:
        os.makedirs(slim_dir, exist_ok=True)

    kept, excluded, summary_rows, sizes = [], [], [], {}
    for g, legs in groups.items():
        tag = leg_tag(g)
        if not all(l["media_ok"] for l in legs):
            excluded.append(dict(leg=tag, dataset=legs[0]["dataset"], subset=legs[0]["subset"],
                                 backend=legs[0]["backend"], glob=g,
                                 reason="pre-remux MEVA media: decoder returned the first "
                                        "seconds of every clip (see README)"))
            continue
        files, src = shard_files(g)
        if not files:
            print(f"!! no files for {g}", file=sys.stderr)
            continue
        subset = legs[0]["subset"]
        dataset = subset[:-5] if subset.endswith(".json") else subset
        expected = sum(l["rows"] for l in legs)
        backends = {l["backend"] for l in legs}

        name = f"{tag}.jsonl" + (".gz" if args.gzip else "")
        opener = (lambda p: gzip.open(p, "wt")) if args.gzip else (lambda p: open(p, "w"))
        n = 0
        fslim = open(os.path.join(slim_dir, f"{tag}.jsonl"), "w") if args.slim else None
        with opener(os.path.join(legs_dir, name)) as fo:
            for path in files:
                with open(path) as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        r = json.loads(line)
                        if r.get("backend") not in backends:
                            continue
                        r.setdefault("dataset", dataset)
                        r["leg"] = tag
                        r["source_commit"] = commit
                        fo.write(json.dumps(r) + "\n")
                        n += 1
                        if fslim:
                            for k in SLIM_DROP:
                                r.pop(k, None)
                            fslim.write(json.dumps(r) + "\n")
        if fslim:
            fslim.close()
        if n != expected:
            msg = f"{tag}: merged {n} rows, registry says {expected}"
            if not args.allow_mismatch:
                sys.exit("STOP " + msg + " (use --allow-mismatch to continue)")
            print("!! " + msg, file=sys.stderr)
        sizes[name] = os.path.getsize(os.path.join(legs_dir, name))
        for l in legs:
            e = dict(l)
            e["file"] = f"legs/{name}"
            e["leg"] = tag
            e["shards_source"] = src
            kept.append(e)
            summary_rows.append(dict(
                leg=tag, file=f"legs/{name}", dataset=l["dataset"], subset=l["subset"],
                backend=l["backend"], method=l["method"], budget=l["budget"],
                passes=l["passes"], questions_expected=l["questions_expected"],
                questions_run=l["questions_run"], rows=l["rows"], complete=l["complete"],
                accuracy_pct=l["accuracy_pct"], errors=l["errors"],
                reasoning=l["protocol"].get("reasoning"),
                temperature=",".join(str(t) for t in (l["protocol"].get("temperature") or [])),
            ))
        print(f"{tag:55s} {n:7d} rows  {sizes[name]/1e6:6.1f} MB  ({src})")

    # --- subsets a reader needs, only where the shared tree lacks them ---
    sub_dir = os.path.join(out_root, "data", "subsets")
    os.makedirs(sub_dir, exist_ok=True)
    needed = sorted({l["subset"] for l in kept})
    sub_report = []
    for s in needed:
        src_p = os.path.join(HERE, s)
        dst_p = os.path.join(sub_dir, s)
        if not os.path.exists(src_p):
            sub_report.append((s, "MISSING LOCALLY"))
            continue
        if os.path.exists(dst_p):
            same = sha16(src_p) == sha16(dst_p)
            sub_report.append((s, "present, identical" if same else "present, DIFFERS — left as is"))
            continue
        shutil.copy2(src_p, dst_p)
        sub_report.append((s, "copied"))

    # --- index files ---
    json.dump({"note": "One entry per (dataset, backend, method, budget) leg; `file` is the "
                       "merged row file, `complete` says whether every question ran. "
                       "Legs with media_ok=false are not shipped; see `excluded`.",
               "source_repo": "Wavy-Hec/MultiCam", "source_commit": commit,
               "legs": kept, "excluded": excluded},
              open(os.path.join(out, "registry.json"), "w"), indent=1)
    with open(os.path.join(out, "summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)

    write_readme(out, commit, kept, excluded, summary_rows, sub_report, args)

    total = sum(sizes.values())
    big = max(sizes.items(), key=lambda kv: kv[1])
    print(f"\n{len(sizes)} leg files, {len(kept)} registry legs, {len(excluded)} excluded groups")
    print(f"total {total/1e6:.0f} MB, largest {big[0]} {big[1]/1e6:.1f} MB")
    if args.slim:
        st = sum(os.path.getsize(os.path.join(slim_dir, f)) for f in os.listdir(slim_dir))
        print(f"slim/ {st/1e6:.0f} MB")
    for s, what in sub_report:
        print(f"subset {s}: {what}")
    print(f"written under {out_root}")


SCHEMA = [
    ("id", "question index within its subset; unique only with `dataset`"),
    ("dataset", "subset stem the row was run against (matches data/subsets/<dataset>.json)"),
    ("leg", "which merged file / campaign the row came from"),
    ("task_type, source, orig_num_cameras, num_videos", "copied from the question record"),
    ("cap_answer_safe", "whether the camera cap leaves the answer recoverable"),
    ("method", "arm: cvbench_native (sequential), centralized (montage), per_stream, blind, single_viewN, segment_select*"),
    ("backend", "model name"),
    ("prediction, gold, correct, abstained", "parsed letter, gold letter, 0/1, no letter parsed (scored incorrect)"),
    ("pass_idx, seed, temperature", "sampling pass; passes are independent decodes with frames fixed"),
    ("latency_s, perception_latency_*_s, aggregate_latency_s", "wall-clock; the per_stream arm splits perception and aggregation"),
    ("input_tokens, video_tokens, output_tokens, num_model_calls", "budget actually consumed — compare across arms before reading any accuracy gap"),
    ("response_text, think", "full model output and the <think> block (absent in slim/)"),
    ("frame_alloc", "frames per view the arm chose; on segment_select legs also the per-segment scores (absent in slim/)"),
    ("media_remap", "'avi->mp4' on MEVA rows decoded through the remux; the reason older MEVA legs are excluded"),
    ("error", "non-null when the call failed; such rows are counted in `errors`"),
    ("source_commit", "Wavy-Hec/MultiCam commit this bundle was exported from"),
]


def write_readme(out, commit, kept, excluded, summary_rows, sub_report, args):
    L = []
    L.append("# MultiCam benchmark results\n")
    L.append("Per-question result rows from the `Wavy-Hec/MultiCam` harness, one merged JSONL per leg "
             "file group, exported at commit `%s`.\n" % commit)
    L.append("A row is one question x method x backend x sampling pass. **Key on `(dataset, id)`** — "
             "`id` restarts at 0 in every subset. The question records live in `data/subsets/<dataset>.json`.\n")
    L.append("## Layout\n")
    L.append("```")
    L.append("registry.json   one entry per (dataset, backend, method, budget): file, rows, passes, accuracy, complete")
    L.append("summary.csv     the same, one line per leg, for a spreadsheet")
    L.append("legs/           merged rows, full fields" + (" (gzip; `gzip.open(path, 'rt')` or `zcat`)" if args.gzip else ""))
    if args.slim:
        L.append("slim/           the same rows without `response_text` / `think` / `frame_alloc`, plain JSONL")
    L.append("```\n")
    L.append("Several methods share one file: a file group is every arm that ran in one Slurm array. "
             "Filter on `method` and `backend`.\n")
    L.append("## Reading a leg\n")
    L.append("```python\nimport gzip, json, pandas as pd\n"
             "rows = [json.loads(l) for l in gzip.open('multicam_results/legs/<leg>.jsonl" + (".gz" if args.gzip else "") + "', 'rt')]\n"
             "df = pd.DataFrame(rows)\n"
             "df[df.method == 'cvbench_native'].groupby('pass_idx').correct.mean()   # per-pass accuracy of one arm\n"
             "df.groupby(['method', 'backend']).video_tokens.mean()               # the budget each arm actually used\n```\n")
    L.append("## Protocol\n")
    L.append("- passes: 4 per question (seeds 1-4, temperature 0.7) unless summary.csv says otherwise; "
             "reasoning is imposed by the prompt scaffold, `reasoning` in summary.csv says which template.")
    L.append("- scoring: the letter parsed from `<answer>` (or the bare reply); no letter parsed = abstained = incorrect. "
             "Rows were re-scored with the current parser (`shards_source` in registry.json).")
    L.append("- montage arm (`centralized`): every view resized into a fixed square cell; its token count saturates "
             "while the sequential arm's grows with views — compare `video_tokens` before reading an arm gap.")
    L.append("- MEVA rows decode the remuxed `.mp4` siblings of the release `.avi` (`media_remap`); "
             "see the exclusion note below.\n")
    L.append("## Row schema\n")
    L.append("| field | meaning |\n|---|---|")
    for k, v in SCHEMA:
        L.append(f"| `{k}` | {v} |")
    L.append("")
    L.append("## Legs\n")
    L.append("| leg | dataset | backend | method | budget | questions | rows | acc % | complete |\n|---|---|---|---|---|--:|--:|--:|---|")
    for r in summary_rows:
        L.append(f"| `{r['leg']}` | {r['dataset']} | {r['backend']} | {r['method']} | {r['budget']} | "
                 f"{r['questions_run']}/{r['questions_expected']} | {r['rows']} | {r['accuracy_pct']} | "
                 f"{'yes' if r['complete'] else 'NO'} |")
    inc = [r for r in summary_rows if not r["complete"]]
    if inc:
        L.append("\nLegs marked `NO` stopped before every question ran; their rows are real but the accuracy "
                 "is over the questions that ran. Do not pool them with a complete twin.\n")
    L.append("## Excluded: pre-remux MEVA legs\n")
    L.append("The MEVA release ships `.avi` containers whose packets carry no timestamps; random access "
             "through decord lands on keyframe 0 and decodes forward, so every seek returned a frame from "
             "the first seconds of the five-minute clip. Every MEVA leg run before 2026-08-27 saw only "
             "those seconds. Those legs are NOT in this folder and any MEVA number from an earlier bundle "
             "is superseded by the `mp4*` legs here.\n")
    L.append("| excluded group | subset | backend |\n|---|---|---|")
    for e in excluded:
        L.append(f"| `{e['leg']}` | {e['subset']} | {e['backend']} |")
    L.append("")
    L.append("## Subsets\n")
    for s, what in sub_report:
        L.append(f"- `data/subsets/{s}`: {what}")
    L.append("")
    L.append("## Regenerating\n")
    L.append("```\n# in Wavy-Hec/MultiCam\npython3 analysis/export_question_records.py\n"
             "python3 analysis/export_shared_results.py --out <multicam-harness checkout>"
             + (" --gzip" if args.gzip else "") + (" --slim" if args.slim else "") + "\n```\n")
    open(os.path.join(out, "README.md"), "w").write("\n".join(L))


if __name__ == "__main__":
    main()
