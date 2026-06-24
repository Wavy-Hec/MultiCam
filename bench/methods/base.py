"""Core abstractions for the multi-camera benchmark.

A ``Method`` is an *architecture* (how the camera streams are fed to a model);
a ``Backend`` is the underlying VLM. ``Method.answer(rec, video_root)`` returns
a ``Result`` carrying the prediction plus the latency / token / calibration
metrics (M1-M4 in bench_spec.md).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional

from ..reuse import num_videos


@dataclass
class GenOut:
    """One VLM generation call's output + accounting."""
    text: str
    input_tokens: int
    video_tokens: int
    output_tokens: int
    latency_s: float


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
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)


def result_fields(rec):
    """Stratification keys copied verbatim from the question record."""
    return dict(
        id=rec.get("id"),
        task_type=rec.get("task_type"),
        source=rec.get("source"),
        orig_num_cameras=rec.get("orig_num_cameras"),
        cap_answer_safe=rec.get("cap_answer_safe"),
        num_videos=num_videos(rec),
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
                 temperature: float = 0.0):
        self.backend = backend
        self.nframes = nframes
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature

    def answer(self, rec, video_root, seed=None) -> Result:
        raise NotImplementedError
