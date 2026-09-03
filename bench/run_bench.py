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

from .reuse import (DEFAULT_VIDEO_ROOT, STRICT_ANSWER_PROMPT, ALLOW_AVI,
                    media_remap, video_paths)
from .methods.centralized import CentralizedMethod
from .methods.per_stream import PerStreamMethod
from .methods.cvbench_native import CVBenchNativeMethod
from .methods.temporal import TemporalWeightedMethod
from .methods.blind import BlindMethod
from .methods.single_view import SingleViewMethod
from .methods.clip_select import (SummarySelectMethod, ClipScoreSelectMethod,
                                  FrameSelectMethod)
from .methods.option_union import (OptionUnionFrameSelect, OptionUnionClipSelect,
                                   QuerySearchMethod)
from .methods.segment_select import SegmentSelectMethod
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

# Option-union arms (Follow-up 1): a frame/clip is kept when ANY answer
# option's similarity threshold passes (--sel-tau / --sel-tau-q); the kept
# sets are unioned. The clip-level arm additionally accepts the scorer tag
# 'viclip' (video-native joint 8-frame embedding, loaded from VICLIP_DIR —
# not an HF transformers id, so it is deliberately absent from SCORER_ALIASES).
OPTION_UNION_FRAME_RE = re.compile(
    r"^frame_select(?:_(?P<tag>(?!optu(?:_|$))[a-z0-9]+))?_optu$")
OPTION_UNION_CLIP_RE = re.compile(
    r"^clip_select(?:_(?P<tag>(?!optu(?:_|$))[a-z0-9]+))?_optu$")
# Tool-based query search (Follow-up 2): the backend writes visual search
# phrases from Question+Options, CLIP/SigLIP retrieves the frames.
QUERY_SEARCH_RE = re.compile(r"^query_search(?:_(?P<tag>[a-z0-9]+))?$")
# segment_select: top-K segments PER clip -> per-segment frames -> question-wide
# near-duplicate removal -> even thinning to the budget (methods/segment_select.py).
# Same tag/_opt grammar as frame_select, plus 'viclip' (joint tube embeddings for
# segment relevance; --clip-model still supplies the dedup embeddings) and
# 'random' (relevance-free CONTROL: segments kept by a deterministic per-record
# hash, no scorer model loads; requires --dedup-tau 1 and takes no _opt/_stmt
# suffix — it never reads a query); budget
# 0/omitted = matched nframes x K; --segments-keep 0 = budget-derived top-K.
# Query mode suffix: none = the question, _opt = each answer option, _stmt =
# each Roman-numbered statement of an event-ordering question (falls back to
# the options on records without statements; clip_select.query_for).
SEGMENT_SELECT_RE = re.compile(
    r"^segment_select(?:_(?P<tag>(?!(?:opt|stmt)(?:_|$))[a-z0-9]+))?"
    r"(?P<qmode>_opt|_stmt)?$")
SEGMENT_QUERY_MODES = {None: "question", "_opt": "options", "_stmt": "statements"}

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
    # --budget omitted (None): legacy selection arms keep their historic 64;
    # the _optu/query_search arms default to matched (0 -> nframes x K inside
    # the method). The legacy arms do NOT implement the 0 convention — at
    # budget 0 frame_select would answer BLIND with error=null — so explicit
    # 0 is rejected for them in the validation loop below.
    legacy_budget = 64 if args.budget is None else args.budget
    union_budget = 0 if args.budget is None else args.budget
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
        return TemporalWeightedMethod(backend, budget=legacy_budget, floor=args.floor,
                                      weighting=args.weighting, nframes=args.nframes,
                                      max_new_tokens=args.max_new_tokens,
                                      temperature=args.temperature,
                                      reasoning=not args.no_reasoning)
    if mname.startswith("summary_select_"):
        return SummarySelectMethod(
            backend, summaries_path=args.summaries,
            mode=mname.rsplit("_", 1)[1], budget=legacy_budget, floor=args.floor,
            sel_max_new_tokens=args.sel_max_new_tokens, nframes=args.nframes,
            max_new_tokens=args.max_new_tokens, temperature=args.temperature,
            reasoning=not args.no_reasoning)
    ouf = OPTION_UNION_FRAME_RE.match(mname)
    if ouf:
        tag = ouf.group("tag")
        if tag == "viclip":
            raise SystemExit(
                "frame_select_viclip_optu: ViCLIP embeds a whole clip jointly "
                "and has no per-frame scores — use clip_select_viclip_optu, or "
                "a CLIP/SigLIP tag for the frame-level arm.")
        if tag and tag not in SCORER_ALIASES:
            raise SystemExit(f"unknown frame_select scorer tag '{tag}'. "
                             f"Known: {list(SCORER_ALIASES)}")
        return OptionUnionFrameSelect(
            backend, tau=args.sel_tau, tau_q=args.sel_tau_q,
            budget=union_budget, candidates_per_video=args.frame_candidates,
            clip_model=SCORER_ALIASES[tag] if tag else args.clip_model,
            cell_px=args.cell_px, name=mname,
            nframes=args.nframes, max_new_tokens=args.max_new_tokens,
            temperature=args.temperature, reasoning=not args.no_reasoning)
    ouc = OPTION_UNION_CLIP_RE.match(mname)
    if ouc:
        tag = ouc.group("tag")
        if tag and tag != "viclip" and tag not in SCORER_ALIASES:
            raise SystemExit(f"unknown clip_select scorer tag '{tag}'. "
                             f"Known: {list(SCORER_ALIASES) + ['viclip']}")
        scorer = ("viclip" if tag == "viclip"
                  else SCORER_ALIASES[tag] if tag else args.clip_model)
        return OptionUnionClipSelect(
            backend, scorer=scorer, tau=args.sel_tau, tau_q=args.sel_tau_q,
            thumbs=args.sel_thumbs, budget=union_budget, floor=args.floor,
            nframes=args.nframes, max_new_tokens=args.max_new_tokens,
            temperature=args.temperature, name=mname,
            reasoning=not args.no_reasoning)
    qs = QUERY_SEARCH_RE.match(mname)
    if qs:
        tag = qs.group("tag")
        if tag == "viclip":
            raise SystemExit("query_search_viclip: ViCLIP has no per-frame "
                             "scores; use a CLIP/SigLIP tag.")
        if tag and tag not in SCORER_ALIASES:
            raise SystemExit(f"unknown query_search scorer tag '{tag}'. "
                             f"Known: {list(SCORER_ALIASES)}")
        return QuerySearchMethod(
            backend, n_queries=args.n_queries,
            query_max_new_tokens=args.query_max_new_tokens,
            budget=union_budget, candidates_per_video=args.frame_candidates,
            clip_model=SCORER_ALIASES[tag] if tag else args.clip_model,
            cell_px=args.cell_px, name=mname,
            nframes=args.nframes, max_new_tokens=args.max_new_tokens,
            temperature=args.temperature, reasoning=not args.no_reasoning)
    sg = SEGMENT_SELECT_RE.match(mname)
    if sg:
        tag = sg.group("tag")
        if tag and tag not in ("viclip", "random") \
                and tag not in SCORER_ALIASES:
            raise SystemExit(f"unknown segment_select scorer tag '{tag}'. "
                             f"Known: {list(SCORER_ALIASES) + ['viclip', 'random']}")
        if tag == "random" and sg.group("qmode"):
            raise SystemExit(
                f"{mname}: the random control never reads a query — drop the "
                "_opt/_stmt suffix (spell it segment_select_random)")
        # 'viclip' scores segment RELEVANCE with joint tube embeddings; the
        # per-frame dedup embeddings still come from --clip-model (a tube
        # embedding has no per-frame components), so both models load.
        # 'random' loads neither: a deterministic per-record hash replaces
        # the score, and __init__ refuses it with dedup on.
        return SegmentSelectMethod(
            backend, budget=union_budget,
            segments_per_video=args.segments_per_video,
            segments_keep=args.segments_keep,
            frames_per_segment=args.frames_per_segment,
            dedup_tau=args.dedup_tau,
            seg_scorer=tag if tag in ("viclip", "random") else None,
            seg_reduce=args.seg_reduce,
            seg_pool=args.seg_pool,
            clip_model=(SCORER_ALIASES[tag] if tag in SCORER_ALIASES
                        else args.clip_model),
            cell_px=args.cell_px, name=mname,
            nframes=args.nframes, max_new_tokens=args.max_new_tokens,
            temperature=args.temperature, reasoning=not args.no_reasoning,
            query=SEGMENT_QUERY_MODES[sg.group("qmode")])
    fm = FRAME_SELECT_RE.match(mname)
    if fm:
        tag = fm.group("tag")
        if tag and tag not in SCORER_ALIASES:
            raise SystemExit(f"unknown frame_select scorer tag '{tag}'. "
                             f"Known: {list(SCORER_ALIASES)}")
        return FrameSelectMethod(
            backend, budget=legacy_budget,
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
            budget=legacy_budget, floor=args.floor,
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
    """(backends, datasets, media_remaps) already present in an output file we
    would append to. media_remaps holds the sighted rows' `media_remap`
    stamps, with "unstamped" for rows written before the stamp existed (i.e.
    before the MEVA remux — those decoded the wrong frames)."""
    backends, datasets, remaps = set(), set(), set()
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
                if r.get("method") != "blind":
                    remaps.add(r["media_remap"] if "media_remap" in r else "unstamped")
    return backends, datasets, remaps


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
    ap.add_argument("--budget", type=int, default=None,
                    help="selection arms: TOTAL frames per question, split across clips. "
                         "Omitted: the legacy selection arms keep their historic 64 and "
                         "the _optu/query_search arms default to MATCHED (nframes x K, "
                         "the sequential arm's budget). Explicit 0 = matched, and is "
                         "only legal for the _optu/query_search arms")
    ap.add_argument("--sel-tau", type=float, default=0.0,
                    help="_optu arms: absolute per-option similarity cutoff "
                         "(scorer-specific; calibrate with "
                         "analysis/calibrate_union_tau.py); 0 = quantile mode")
    ap.add_argument("--sel-tau-q", type=float, default=0.85,
                    help="_optu arms: per-option quantile when --sel-tau is 0 — "
                         "a frame/clip passes an option when it is in that "
                         "option's top (1-q) fraction")
    ap.add_argument("--n-queries", type=int, default=4,
                    help="query_search: visual search phrases generated per question")
    ap.add_argument("--query-max-new-tokens", type=int, default=256,
                    help="query_search: token cap for the phrase-generation call")
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
    ap.add_argument("--segments-per-video", type=int, default=8,
                    help="segment_select: contiguous equal-time segments each clip "
                         "is split into (fewer when the clip is shorter)")
    ap.add_argument("--segments-keep", type=int, default=4,
                    help="segment_select: most-relevant segments kept PER clip "
                         "(straight top-K over the per-option score matrix). "
                         "0 = AUTO: K = --seg-pool // (frames_per_segment x "
                         "n_streams), clamped to [1, min(16, "
                         "segments_per_video)]")
    ap.add_argument("--seg-pool", type=int, default=128,
                    help="segment_select with --segments-keep 0: pooled-frame "
                         "target the auto top-K fills with whole segments, "
                         "split evenly across the record's streams (128 with "
                         "8-frame segments: 4 streams -> 4 segments/clip, "
                         "16+ -> 1). Auto K never exceeds --segments-per-video, "
                         "so reaching 16 on 1-stream records needs "
                         "--segments-per-video 16+")
    ap.add_argument("--frames-per-segment", type=int, default=8,
                    help="segment_select: frames sampled uniformly within each segment")
    ap.add_argument("--dedup-tau", type=float, default=0.95,
                    help="segment_select: image-embedding cosine at/above which a "
                         "pooled frame is dropped as a near-duplicate. Must be in "
                         "(0, 1]; 1.0 DISABLES dedup — this is NOT the --sel-tau "
                         "'0 = off' convention (0 would collapse every question "
                         "to one frame and is rejected). Scorer-specific scale; "
                         "question-wide scope; static-camera footage (MEVA) "
                         "collapses at the 0.95 default — calibrate or use 1.0 "
                         "there")
    ap.add_argument("--seg-reduce", choices=("max", "coverage"), default="max",
                    help="segment_select _stmt legs: how the per-statement score "
                         "matrix picks the kept segments. 'max' (default) = each "
                         "segment keeps its best single-statement score, straight "
                         "top-K (the historic reduce, shared with _opt). "
                         "'coverage' = each statement first claims its own argmax "
                         "segment (statement order; remaining slots by best "
                         "score), so one salient statement cannot absorb every "
                         "slot. Applies only where the effective query mode is "
                         "statements — fallback records and _opt/question legs "
                         "reduce by max regardless, so a coverage leg's "
                         "non-ordering half stays an exact replicate")
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
    ap.add_argument("--montage-kind", default="camera",
                    choices=["camera", "video", "view", "neutral"],
                    help="centralized montage framing: 'camera' (synced views, default), "
                         "'video' (independent clips — 'Video i' labels matching the "
                         "question wording), 'view' (still-image sets force this), or "
                         "'neutral' (matched-prompt control: NO preamble, 'Video i' "
                         "labels — the montage-arm-only preamble is a confound in the "
                         "centralized-vs-native comparison)")
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
                and not FRAME_SELECT_RE.match(m) and not SINGLE_VIEW_RE.match(m)
                and not OPTION_UNION_FRAME_RE.match(m)
                and not OPTION_UNION_CLIP_RE.match(m)
                and not QUERY_SEARCH_RE.match(m)
                and not SEGMENT_SELECT_RE.match(m)):
            raise SystemExit(f"unknown method '{m}'. Known: {list(METHODS)} "
                             f"or clip_select[_<scorer>]_top<m> or frame_select[_<scorer>] "
                             f"or frame_select[_<scorer>]_optu or clip_select[_<scorer>|_viclip]_optu "
                             f"or query_search[_<scorer>] or segment_select[_<scorer>][_opt|_stmt] "
                             f"or single_view<i>")
        # explicit --budget 0 is a matched-budget request only the new arms
        # implement; the legacy selection arms would select 0 frames and run
        # BLIND with error=null (frame_select) or emit 0-frame clips. Check
        # the new-arm regexes FIRST: tagless 'frame_select_optu' also matches
        # FRAME_SELECT_RE (as tag='optu'), but dispatches to the new arm.
        # segment_select tags are checked HERE, not just in make_method: the
        # backend loop loads the 8B model (and can drain a whole prior method)
        # before make_method runs, so a typo like 'segment_select_optu' —
        # inviting, since every sibling option-guided arm spells it '_optu'
        # while this arm spells it '_opt' — would burn hours of queued GPU
        # time before dying. Fail at submit instead.
        sgm = SEGMENT_SELECT_RE.match(m)
        if sgm and sgm.group("tag") and sgm.group("tag") not in ("viclip", "random") \
                and sgm.group("tag") not in SCORER_ALIASES:
            tag = sgm.group("tag")
            hint = (" ('_optu' is the option-union arms' suffix; this arm's "
                    "option-guided variant is spelled '_opt', e.g. "
                    "segment_select_opt or segment_select_siglip_opt)"
                    if tag == "optu" else "")
            raise SystemExit(f"unknown segment_select scorer tag '{tag}'. "
                             f"Known: {list(SCORER_ALIASES) + ['viclip', 'random']}.{hint}")
        # the random control's constraints fail at submit too, not after the
        # 8B model load: it never reads a query (no _opt/_stmt), and dedup
        # would rank duplicate survivors by an image-tower relevance score,
        # reintroducing the very signal the control removes
        if sgm and sgm.group("tag") == "random":
            if sgm.group("qmode"):
                raise SystemExit(
                    f"{m}: the random control never reads a query — drop the "
                    "_opt/_stmt suffix (spell it segment_select_random)")
            if args.dedup_tau < 1.0:
                raise SystemExit(
                    f"{m}: dedup (--dedup-tau {args.dedup_tau} < 1) would pick "
                    "duplicate survivors by image-tower relevance inside the "
                    "relevance-free control — run it with --dedup-tau 1")
        # same submit-time rule for the Qwen path: SegmentSelectMethod refuses
        # it (fabricated PIL-list timestamps), and that refusal must not wait
        # for the model load either
        if sgm and os.environ.get("SEGMENT_SELECT_QWEN_UNSAFE", "0") != "1" and any(
                b in QWEN_ALIASES or ("/" in b and "internvl" not in b.lower())
                for b in backends):
            raise SystemExit(
                f"{m} on a Qwen backend: the per-clip PIL-list video items get "
                "fabricated timestamps from qwen_vl_utils (see "
                "SegmentSelectMethod.__init__); attach real frame times first, "
                "or set SEGMENT_SELECT_QWEN_UNSAFE=1 knowingly.")
        # --seg-reduce coverage only ever fires where the effective query mode
        # is statements, i.e. on a _stmt method: on every other segment_select
        # method it silently no-ops — the leg would burn a full GPU array
        # producing selections byte-identical to the max-reduce leg while the
        # sbatch log echoes seg_reduce=coverage. Same fail-at-submit rule as
        # the tag typos above.
        if sgm and args.seg_reduce == "coverage" and sgm.group("qmode") != "_stmt":
            raise SystemExit(
                f"{m}: --seg-reduce coverage applies only to _stmt methods "
                "(statement queries); on this method it would silently no-op "
                "and reproduce the max-reduce selection. Drop SEG_REDUCE or "
                "use a segment_select_*_stmt method.")
        budget_zero_ok = (OPTION_UNION_FRAME_RE.match(m)
                          or OPTION_UNION_CLIP_RE.match(m)
                          or QUERY_SEARCH_RE.match(m)
                          or SEGMENT_SELECT_RE.match(m))
        if (args.budget is not None and args.budget <= 0 and not budget_zero_ok
                and (FRAME_SELECT_RE.match(m) or CLIP_SELECT_RE.match(m)
                     or m == "temporal_weighted"
                     or m.startswith("summary_select_"))):
            raise SystemExit(
                f"--budget {args.budget}: 0 = 'match nframes x K' exists only "
                f"for the _optu/query_search arms; '{m}' would select 0 frames "
                "and answer blind. Give the legacy selection arms an explicit "
                "positive --budget (or omit the flag for their default 64).")
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
    prior_backends, prior_datasets, prior_remaps = existing_identity(out)
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
    # media provenance: MEVA rows written before the 2026-08-27 remux decoded
    # the wrong frames and carry no stamp; resume/append must not pool them
    # with remuxed rows under a reused TAG
    this_remap = {media_remap(rec) for rec in data} - {None}
    prior_stamped = prior_remaps - {"unstamped", None}
    # refuse when (a) this run names .avi records and the file holds rows
    # written before the stamp existed (pre-remux MEVA), or (b) the file's
    # stamps disagree with this run's (avi-raw vs avi->mp4, or an mp4-spelled
    # MEVA subset over remuxed rows). A new/empty file, or a non-MEVA file
    # (stamps None), is always compatible.
    mixed = ((this_remap and "unstamped" in prior_remaps)
             or (prior_stamped and prior_stamped != this_remap))
    if mixed and not args.allow_mixed:
        raise SystemExit(
            f"refusing to append to {out}\n"
            f"  it holds rows with media_remap {sorted(map(str, prior_remaps))}; "
            f"this run would stamp {sorted(map(str, this_remap)) or [None]}\n"
            "  (rows without the stamp predate the MEVA remux and decoded the "
            "wrong frames). Use a new TAG.\n"
            "  Pass --allow-mixed only if you genuinely intend one mixed file.")

    print(f"subset={args.subset} n={len(data)} methods={methods} backends={backends} "
          f"passes={args.passes} seeds={seeds} temp={args.temperature} "
          f"strict_prompt={int(STRICT_ANSWER_PROMPT)} allow_avi={int(ALLOW_AVI)}")
    print(f"dataset={dataset} run_id={run_id} node={node}")
    print(f"video_root={args.video_root}\nout={out} (already done: {len(done)})", flush=True)

    # resolve every record's media BEFORE the model loads: a missing .mp4
    # sibling (MEVA remux) must fail here, not after an 8B load on a GPU node
    if any(m != "blind" for m in methods):
        missing = []
        for rec in data:
            try:
                video_paths(rec, args.video_root)
            except FileNotFoundError as e:
                missing.append(str(e).split(":")[0])
        if missing:
            raise SystemExit(
                f"{len(missing)} record(s) name an .avi without a verified .mp4 "
                "sibling (run hosting/remux_avi.py, then --check); first: "
                f"{missing[:3]}")

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
                    # .avi records decode from their remuxed .mp4 sibling
                    # (eval_thinking.resolve_media); stamp it so rows from
                    # before the remux (wrapped frames) never pool with these
                    row["media_remap"] = (None if method.name == "blind"
                                          else media_remap(rec))
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
