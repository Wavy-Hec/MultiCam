"""Core abstractions for the multi-camera benchmark.

A ``Method`` is an *architecture* (how the camera streams are fed to a model);
a ``Backend`` is the underlying VLM. ``Method.answer(rec, video_root)`` returns
a ``Result`` carrying the prediction plus the latency / token / calibration
metrics (M1-M4; the spec doc left the repo — ``git show 6ef38ac^:bench/bench_spec.md``).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional

from ..reuse import extract_think, num_images, num_videos


@dataclass
class GenOut:
    """One VLM generation call's output + accounting."""
    text: str
    input_tokens: int
    video_tokens: int
    output_tokens: int
    latency_s: float
    # the span the answer is parsed from; None = the whole text, which is what
    # every backend gave before 2026-10-29. A backend whose template pre-opens
    # a native thinking block sets the reply after </think> (only when the
    # generation ended), because that block can quote the very
    # "<answer> and </answer>" tags the parser looks for; think_text is then
    # the reasoning before that </think>
    answer_text: Optional[str] = None
    think_text: Optional[str] = None
    # >1 when this output came from one batched call that sampled several
    # sequences (passes, or passes of several prompts); latency_s is then that
    # call's wall clock
    batch_n: Optional[int] = None

    @property
    def answer_span(self):
        return self.text if self.answer_text is None else self.answer_text

    @property
    def parsed_from(self):
        """'after_think' when the answer was parsed from the post-</think>
        reply, None for the whole text; rows stamp it so a rescore reproduces
        the harness's parse (analysis/rescore_answers.py)."""
        return None if self.answer_text is None else "after_think"


def think_of(g):
    """The reasoning trace a row stores: the backend's own split when it made
    one, else the first <think>...</think> block (extract_think)."""
    return g.think_text if g.think_text is not None else extract_think(g.text)


@dataclass
class Result:
    """One (question x method x backend) row written to the per-question JSONL."""
    id: object
    task_type: str
    source: Optional[str]
    orig_num_cameras: Optional[int]
    cap_answer_safe: Optional[bool]
    num_videos: int
    method: str
    backend: str
    prediction: str
    gold: str
    correct: bool
    abstained: bool
    pair_idx: Optional[str] = None   # paired-question twin id (All-Angles-Bench IC metric)
    # 4-pass protocol (Table 1 std): a "pass" = one sampled generation (temp>0)
    # at a fixed seed, with frames held fixed; std is taken over the passes.
    pass_idx: Optional[int] = None
    seed: Optional[int] = None
    temperature: Optional[float] = None
    # M2 latency
    latency_s: Optional[float] = None                  # end-to-end (serial) wall-clock
    perception_latency_par_s: Optional[float] = None   # A1: max over per-stream calls (true-parallel estimate)
    perception_latency_serial_s: Optional[float] = None  # A1: sum over per-stream calls
    aggregate_latency_s: Optional[float] = None        # A1: aggregator call
    # M3 cost
    input_tokens: Optional[int] = None
    video_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    num_model_calls: int = 1
    # >1: this pass was sampled inside one batched call with batch_n - 1 sibling
    # passes of the same prompt (GenOut.batch_n); latency_s is that call's wall
    # clock, so its GPU time per row is latency_s / batch_n. None = its own call
    batch_n: Optional[int] = None
    # 'after_think' when the prediction was parsed from the reply after the
    # native thinking block (GenOut.parsed_from); None = whole response_text
    parsed_from: Optional[str] = None
    # reasoning/audit (set by every method on success; None on legacy rows/errors)
    response_text: Optional[str] = None    # raw g.text (full <think>...<answer> trace)
    think: Optional[str] = None            # extract_think(g.text)
    frame_alloc: Optional[dict] = None     # frame-audit methods: per-clip durations +
                                           # allocated frame counts; per_stream: the
                                           # per-view perception_texts
    error: Optional[str] = None
    # Run identity. ``id`` is only unique WITHIN a subset (every pool restarts at
    # 0), so merging datasets — or two people's runs — needs these to key on.
    # Merge on (dataset, id); tell two operators' rows apart with run_id.
    # None on rows written before 2026-08-05.
    dataset: Optional[str] = None          # subset basename, e.g. "mvueval_qa"
    run_id: Optional[str] = None           # Slurm job/array id, else host+pid
    node: Optional[str] = None             # execution host, for GPU-placement audits

    def to_dict(self):
        return asdict(self)


def require_video_record(rec, method_name):
    """Raise unless ``rec`` carries video clips, which the clip/frame arms need.

    Those arms reach for ``video_paths()``, which looks only at ``video_i``. A
    still-image record (``image_i``, e.g. All-Angles) therefore yields an empty
    path list and the arm would run with ZERO visual items — scoring a blind run
    while being labelled a vision one. Fail loudly instead.
    """
    if num_videos(rec) == 0 and num_images(rec) > 0:
        raise ValueError(
            f"{method_name} needs video records but question id={rec.get('id')} "
            f"({rec.get('task_type')}) carries {num_images(rec)} still image(s) and no video. "
            "The clip/frame-selection arms sample frames out of clips, so they cannot run on "
            "still-image benchmarks. Use cvbench_native, centralized or per_stream instead.")


def result_fields(rec):
    """Stratification keys copied verbatim from the question record."""
    return dict(
        id=rec.get("id"),
        task_type=rec.get("task_type"),
        source=rec.get("source"),
        orig_num_cameras=rec.get("orig_num_cameras"),
        cap_answer_safe=rec.get("cap_answer_safe"),
        num_videos=num_videos(rec) or num_images(rec),
        pair_idx=rec.get("pair_idx") or None,
    )


class Backend:
    """A VLM that turns a chat ``messages`` list into text + token/latency stats.

    ``generate`` accepts a ``seed`` and ``temperature`` so the 4-pass protocol
    can vary the decoding sampling while holding the (deterministic) frames fixed.
    """
    name = "backend"

    def generate(self, messages, max_new_tokens, *, seed=None, temperature=0.0) -> GenOut:
        raise NotImplementedError


class Method:
    name = "method"

    def __init__(self, backend: Backend, nframes: int = 8, max_new_tokens: int = 8192,
                 temperature: float = 0.0, reasoning: bool = True):
        self.backend = backend
        self.nframes = nframes
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        # reasoning=False swaps the prompt for the direct-answer template: there
        # is no model-side thinking switch, the trace is produced by the prompt
        self.reasoning = reasoning

    def answer(self, rec, video_root, seed=None) -> Result:
        raise NotImplementedError
