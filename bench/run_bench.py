"""Run the multi-camera benchmark: methods x backends x passes over a subset.

Usage (from repo root):
  python -m bench.run_bench --subset analysis/crossview_combined_subset.json \
      --methods centralized,per_stream --backends qwen3vl \
      --passes 4 --seeds 1,2,3,4 --temperature 0.7 --limit 5

A "pass" = one sampled generation (temperature>0) at a fixed seed, with the
(deterministic) frames held fixed; Table 1's std is taken over the passes.
Writes one Result per line to a JSONL (resumable on (id,method,backend,pass)),
then prints + saves a per-(method/backend) summary. Backends load once and are
reused across methods/passes. ``--chunk N --offset i`` shards the subset
(``data[i::N]``) for Slurm-array sweeps.
"""
import argparse
import json
import os
import re
import socket

from .reuse import DEFAULT_VIDEO_ROOT, STRICT_ANSWER_PROMPT
from .methods.centralized import CentralizedMethod
from .methods.per_stream import PerStreamMethod
from .methods.cvbench_native import CVBenchNativeMethod
from .methods.temporal import TemporalWeightedMethod
from .methods.blind import BlindMethod
from .methods.single_view import SingleViewMethod
from .methods.clip_select import (SummarySelectMethod, ClipScoreSelectMethod,
                                  FrameSelectMethod)
from .backends.qwen import QwenBackend, QWEN_ALIASES
from . import metrics

METHODS = {"centralized": CentralizedMethod, "per_stream": PerStreamMethod,
           "cvbench_native": CVBenchNativeMethod,
           "temporal_weighted": TemporalWeightedMethod,
           "blind": BlindMethod,
           # (adaptive_content / adaptive_query — the within-clip frame-selection
           # ablation — were retired 2026-07-02 after losing/tying uniform; archived
           # result: git show 6ef38ac^:analysis/adaptive_frames_experiment.md §B.)
           # D3 clip selection: spend the budget on the clips a question needs.
           # summary_select_* = cached per-clip summaries -> one text-only
           # selector call (route may answer ALL; top1 forces one clip);
           # clip_select_top1 = CLIP question-vs-thumbnail scoring, no LLM call.
           "summary_select_route": SummarySelectMethod,
           "summary_select_top1": SummarySelectMethod,
           "clip_select_top1": ClipScoreSelectMethod}

# clip_select method names are generated, not enumerated: an optional scorer
# tag (must be in SCORER_ALIASES), an optional _opt marker, then the top-m
# count, e.g. clip_select_top2, clip_select_siglip_top1,
# clip_select_siglip_opt_top1. The matched string becomes the method's recorded
# name, so scorer and query variants never collide in rows/resume keys.
# _opt scores frames against each ANSWER OPTION instead of the question — the
# answer-choice-guided selection arm. The tag cannot itself be "opt".
CLIP_SELECT_RE = re.compile(
    r"^clip_select(?:_(?P<tag>(?!opt(?:_|$))[a-z0-9]+))?(?P<opt>_opt)?_top(?P<m>\d+)$")
# single_view<i>: feed only view/clip i (methods/single_view.py); records with
# fewer than i views are skipped, so single_view1..13 sweeps a mixed-K pool.
SINGLE_VIEW_RE = re.compile(r"^single_view(?P<i>\d+)$")
# frame_select: global top-budget frame selection across ALL clips (optional
# scorer tag, e.g. frame_select_siglip; optional _opt for option-guided
# scoring); the budget comes from --budget.
FRAME_SELECT_RE = re.compile(
    r"^frame_select(?:_(?P<tag>(?!opt(?:_|$))[a-z0-9]+))?(?P<opt>_opt)?$")
SCORER_ALIASES = {"siglip": "google/siglip-so400m-patch14-384",
                  "siglip2": "google/siglip2-so400m-patch14-384"}

# alias -> HF id (cached locally; runs under the `internvl` conda env, NOT cvbench,
# because cvbench's transformers breaks the InternVL3 remote code).
INTERNVL_ALIASES = {"internvl3": "OpenGVLab/InternVL3-8B"}


def make_backend(alias, nframes=8, internvl_max_tiles=1):
    if alias in QWEN_ALIASES:
        return QwenBackend(QWEN_ALIASES[alias])
    if alias in INTERNVL_ALIASES:
        from .backends.internvl import InternVL3Backend
        return InternVL3Backend(INTERNVL_ALIASES[alias], num_frame=nframes,
                                max_tiles=internvl_max_tiles)
    if "/" in alias:  # raw HF id
        if "internvl" in alias.lower():
            from .backends.internvl import InternVL3Backend
            return InternVL3Backend(alias, num_frame=nframes, max_tiles=internvl_max_tiles)
        return QwenBackend(alias)
    raise SystemExit(
        f"unknown backend '{alias}'. Known: {list(QWEN_ALIASES) + list(INTERNVL_ALIASES)}.")


def make_method(mname, backend, args):
    if mname == "centralized":
        return CentralizedMethod(backend, nframes=args.nframes,
                                 max_new_tokens=args.max_new_tokens,
                                 temperature=args.temperature,
                                 montage_frames=args.montage_frames, cell_px=args.cell_px,
                                 montage_kind=args.montage_kind,
                                 total_frames=args.total_frames,
                                 reasoning=not args.no_reasoning)
    if mname == "per_stream":
        return PerStreamMethod(backend, nframes=args.nframes,
                               max_new_tokens=args.max_new_tokens,
                               temperature=args.temperature,
                               perception_max_new_tokens=args.perception_max_new_tokens,
                               stream_kind=args.stream_kind,
                               total_frames=args.total_frames,
                               reasoning=not args.no_reasoning)
    if mname == "cvbench_native":
        return CVBenchNativeMethod(backend, nframes=args.nframes,
                                   max_new_tokens=args.max_new_tokens,
                                   temperature=args.temperature,
                                   total_frames=args.total_frames,
                                   reasoning=not args.no_reasoning)
    sv = SINGLE_VIEW_RE.match(mname)
    if sv:
        return SingleViewMethod(backend, view_idx=int(sv.group("i")),
                                nframes=args.nframes,
                                max_new_tokens=args.max_new_tokens,
                                temperature=args.temperature, name=mname,
                                reasoning=not args.no_reasoning)
    if mname == "temporal_weighted":
        return TemporalWeightedMethod(backend, budget=args.budget, floor=args.floor,
                                      weighting=args.weighting, nframes=args.nframes,
                                      max_new_tokens=args.max_new_tokens,
                                      temperature=args.temperature,
                                      reasoning=not args.no_reasoning)
    if mname.startswith("summary_select_"):
        return SummarySelectMethod(
            backend, summaries_path=args.summaries,
            mode=mname.rsplit("_", 1)[1], budget=args.budget, floor=args.floor,
            sel_max_new_tokens=args.sel_max_new_tokens, nframes=args.nframes,
            max_new_tokens=args.max_new_tokens, temperature=args.temperature,
            reasoning=not args.no_reasoning)
    fm = FRAME_SELECT_RE.match(mname)
    if fm:
        tag = fm.group("tag")
        if tag and tag not in SCORER_ALIASES:
            raise SystemExit(f"unknown frame_select scorer tag '{tag}'. "
                             f"Known: {list(SCORER_ALIASES)}")
        return FrameSelectMethod(
            backend, budget=args.budget,
            candidates_per_video=args.frame_candidates,
            clip_model=SCORER_ALIASES[tag] if tag else args.clip_model,
            cell_px=args.cell_px, name=mname,
            nframes=args.nframes, max_new_tokens=args.max_new_tokens,
            temperature=args.temperature, reasoning=not args.no_reasoning,
            query="options" if fm.group("opt") else "question")
    mm = CLIP_SELECT_RE.match(mname)
    if mm:
        tag = mm.group("tag")
        if tag and tag not in SCORER_ALIASES:
            raise SystemExit(f"unknown clip_select scorer tag '{tag}'. "
                             f"Known: {list(SCORER_ALIASES)}")
        return ClipScoreSelectMethod(
            backend, top_m=int(mm.group("m")), thumbs=args.sel_thumbs,
            clip_model=SCORER_ALIASES[tag] if tag else args.clip_model,
            stat=args.sel_stat, name=mname,
            budget=args.budget, floor=args.floor,
            nframes=args.nframes, max_new_tokens=args.max_new_tokens,
            temperature=args.temperature, reasoning=not args.no_reasoning,
            query="options" if mm.group("opt") else "question")
    return METHODS[mname](backend, nframes=args.nframes,
                          max_new_tokens=args.max_new_tokens, temperature=args.temperature,
                          reasoning=not args.no_reasoning)


def load_done(path):
    """Completed (id, method, backend, pass_idx) keys for resume."""
    done = set()
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                done.add((r.get("id"), r.get("method"), r.get("backend"), r.get("pass_idx")))
    return done


def existing_identity(path):
    """(backends, datasets) already present in an output file we would append to."""
    backends, datasets = set(), set()
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("backend"):
                    backends.add(r["backend"])
                if r.get("dataset"):
                    datasets.add(r["dataset"])
    return backends, datasets


def run_identity(subset):
    """(dataset, run_id, node) stamped onto every row of this run."""
    dataset = os.path.splitext(os.path.basename(subset))[0]
    jid = os.environ.get("SLURM_ARRAY_JOB_ID") or os.environ.get("SLURM_JOB_ID")
    task = os.environ.get("SLURM_ARRAY_TASK_ID")
    node = os.environ.get("SLURMD_NODENAME") or socket.gethostname()
    run_id = f"slurm-{jid}" + (f"_{task}" if task else "") if jid else f"{node}-{os.getpid()}"
    return dataset, run_id, node


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", required=True)
    ap.add_argument("--methods", default="centralized")
    ap.add_argument("--backends", default="qwen3vl")
    ap.add_argument("--limit", type=int, default=0, help="only first N records (smoke test)")
    ap.add_argument("--video-root", default=DEFAULT_VIDEO_ROOT)
    ap.add_argument("--nframes", type=int, default=8)
    ap.add_argument("--max-new-tokens", type=int, default=8192)
    ap.add_argument("--perception-max-new-tokens", type=int, default=1024,
                    help="per_stream: token cap for each per-view perception call "
                         "(1024 truncates thinking backends mid-<think>; raise for those)")
    ap.add_argument("--passes", type=int, default=4, help="independent sampled passes for std")
    ap.add_argument("--seeds", default="1,2,3,4", help="comma seeds; len must cover --passes")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--no-reasoning", action="store_true",
                    help="direct-answer prompt: no <think> trace requested. There is no "
                         "model-side switch — the visible reasoning is produced BY the "
                         "prompt, so turning it off means asking for the answer directly. "
                         "Pair with a low --temperature.")
    ap.add_argument("--budget", type=int, default=64,
                    help="temporal_weighted: TOTAL frames per question, split across clips")
    ap.add_argument("--total-frames", type=int, default=0,
                    help="centralized/cvbench_native/per_stream: hold the TOTAL frame "
                         "count per question fixed (split evenly across its clips) "
                         "instead of a flat --nframes per clip; 0 = off")
    ap.add_argument("--floor", type=int, default=2,
                    help="temporal_weighted: per-clip minimum frames")
    ap.add_argument("--weighting", default="duration", choices=["duration", "even"],
                    help="temporal_weighted: split the budget by clip duration "
                         "('duration') or evenly ('even', the budget-matched control)")
    ap.add_argument("--clip-model", default="openai/clip-vit-base-patch32",
                    help="clip_select_*: HF CLIP/SigLIP model id for image-text "
                         "scoring; a scorer tag in the method name (e.g. "
                         "clip_select_siglip_top1) takes precedence")
    ap.add_argument("--summaries",
                    default=os.path.join(os.path.dirname(__file__), "results",
                                         "clip_summaries_internvl3.jsonl"),
                    help="summary_select_*: per-clip summary cache JSONL (or glob); "
                         "generate with bench/gen_clip_summaries.py")
    ap.add_argument("--sel-thumbs", type=int, default=8,
                    help="clip_select_*: uniform thumbnails scored per clip")
    ap.add_argument("--sel-stat", default="max", choices=["max", "mean"],
                    help="clip_select_*: rank clips by max- or mean-over-thumbnails "
                         "similarity (both are recorded in frame_alloc regardless)")
    ap.add_argument("--frame-candidates", type=int, default=32,
                    help="frame_select: uniform candidate frames decoded PER clip; "
                         "the global top-(--budget) across all clips' candidates is kept")
    ap.add_argument("--sel-max-new-tokens", type=int, default=512,
                    help="summary_select_*: token cap for the selector call")
    ap.add_argument("--montage-frames", type=int, default=0,
                    help="centralized montages per question (0 -> = nframes)")
    ap.add_argument("--cell-px", type=int, default=448)
    ap.add_argument("--stream-kind", default="camera", choices=["camera", "video", "view"],
                    help="per_stream: label/phrase clips as synced 'camera' views "
                         "(MEVA, byte-identical to the original prompt) or independent "
                         "'video' clips (matches questions whose text says 'Video k', "
                         "wording, mirroring --montage-kind)")
    ap.add_argument("--montage-kind", default="camera", choices=["camera", "video", "view"],
                    help="centralized montage framing: 'camera' (synced views, default) "
                         "or 'video' (independent clips — 'Video i' labels matching the question wording)")
    ap.add_argument("--internvl-max-tiles", type=int, default=1,
                    help="InternVL tiles per montage image (4 lets a 2x2 montage keep per-camera 448 res)")
    ap.add_argument("--chunk", type=int, default=0, help="number of shards (Slurm array)")
    ap.add_argument("--offset", type=int, default=0, help="this shard index in [0,chunk)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--allow-mixed", action="store_true",
                    help="permit appending to a file that already holds a different "
                         "backend or dataset (default: refuse — filenames key on the "
                         "conda env, not the model, so two backends sharing an env "
                         "would silently land in one file)")
    args = ap.parse_args()

    data = json.load(open(args.subset))
    if args.chunk and args.chunk > 1:
        data = data[args.offset::args.chunk]
    if args.limit:
        data = data[: args.limit]
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    for m in methods:
        if (m not in METHODS and not CLIP_SELECT_RE.match(m)
                and not FRAME_SELECT_RE.match(m) and not SINGLE_VIEW_RE.match(m)):
            raise SystemExit(f"unknown method '{m}'. Known: {list(METHODS)} "
                             f"or clip_select[_<scorer>]_top<m> or frame_select[_<scorer>] "
                             f"or single_view<i>")
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()][: args.passes]
    if len(seeds) < args.passes:
        raise SystemExit(f"need >= {args.passes} seeds, got {seeds}")

    out = args.out or os.path.join(
        os.path.dirname(__file__), "results",
        f"bench_{os.path.splitext(os.path.basename(args.subset))[0]}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    done = load_done(out)
    dataset, run_id, node = run_identity(args.subset)

    # Output filenames key on the conda ENV, not the model (run_bench.sbatch), so
    # two backends sharing an env — Qwen2.5-VL and Qwen3-VL both run under
    # 'cvbench' — would append into ONE file and silently pollute every
    # glob-based leg in export_handoff.py. Rows stay distinguishable via
    # `backend`, but the file does not. Refuse rather than mix.
    prior_backends, prior_datasets = existing_identity(out)
    # backend.name is the HF id basename, so resolve aliases the same way
    want_backends = {
        (QWEN_ALIASES.get(b) or INTERNVL_ALIASES.get(b) or b).rstrip("/").split("/")[-1]
        for b in backends}
    stray_b = prior_backends - want_backends
    stray_d = prior_datasets - {dataset}
    if (stray_b or stray_d) and not args.allow_mixed:
        raise SystemExit(
            f"refusing to append to {out}\n"
            + (f"  it already holds backend(s) {sorted(stray_b)}; this run is "
               f"{sorted(want_backends)}\n" if stray_b else "")
            + (f"  it already holds dataset(s) {sorted(stray_d)}; this run is "
               f"'{dataset}'\n" if stray_d else "")
            + "  Set a distinct TAG (run_bench.sbatch) or --out so each "
              "(dataset, backend) gets its own file.\n"
              "  Pass --allow-mixed only if you genuinely intend one mixed file.")

    print(f"subset={args.subset} n={len(data)} methods={methods} backends={backends} "
          f"passes={args.passes} seeds={seeds} temp={args.temperature} "
          f"strict_prompt={int(STRICT_ANSWER_PROMPT)}")
    print(f"dataset={dataset} run_id={run_id} node={node}")
    print(f"video_root={args.video_root}\nout={out} (already done: {len(done)})", flush=True)

    from tqdm import tqdm
    with open(out, "a") as fh:
        for b in backends:
            backend = make_backend(b, nframes=args.nframes,
                                   internvl_max_tiles=args.internvl_max_tiles)  # loads the model once
            for mname in methods:
                method = make_method(mname, backend, args)
                # process all passes of a record consecutively so the centralized
                # montage cache (and fixed frames) are reused across passes.
                # Resume must key on method.name (what rows record), not mname:
                # e.g. WEIGHTING=even runs under mname 'temporal_weighted' but
                # writes method='temporal_even'.
                jobs = [(rec, pi, sd) for rec in data
                        for pi, sd in enumerate(seeds, 1)
                        if (rec["id"], method.name, backend.name, pi) not in done]
                for rec, pass_idx, seed in tqdm(jobs, desc=f"{mname}/{backend.name}"):
                    res = method.answer(rec, args.video_root, seed=seed)
                    if res is None:  # single_view<i> on a record with < i views
                        continue
                    res.pass_idx = pass_idx
                    res.dataset, res.run_id, res.node = dataset, run_id, node
                    row = res.to_dict()
                    # the strict prompt is a generation change visible only in
                    # the submit-time env; stamp rows so v1/v2 never pool silently
                    row["strict_prompt"] = STRICT_ANSWER_PROMPT
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()

    # a SIGKILL mid-write (Slurm timeout) can leave one torn trailing line;
    # load_done skips it on resume, so the summary must skip it too or the
    # resumed job dies AFTER all its compute with no _summary.json
    rows = []
    with open(out) as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    print(metrics.format_summary(rows))
    sumpath = out.replace(".jsonl", "_summary.json")
    json.dump(metrics.summarize_by_method_backend_passes(rows), open(sumpath, "w"), indent=2)
    print(f"\nsummary -> {sumpath}")


if __name__ == "__main__":
    main()
