"""SINGLE-VIEW oracle probe: feed ONLY view/clip ``i`` of a question, keeping the
text scaffold byte-identical to ``cvbench_native`` (the prompt still says "all
the listed videos" and the attached item keeps its true "Video i:" marker, so
nothing is renumbered). Running ``single_view1..single_viewK`` over a question
set yields the per-view accuracy matrix from which best/random/worst single-view
curves are computed post-hoc — the "does picking the right view matter" slide.

Registered as generated names (``single_view<i>``, regex in run_bench). Records
with fewer than ``i`` views return ``None`` and are skipped by the runner, so a
13-method sweep over a mixed-K pool only pays for the views that exist.

Intended for questions whose text does not name a specific video (naming a view
already does the picking); build that subset with
``analysis/build_singleview_subset.py``.
"""
from .base import Method, Result, result_fields
from ..reuse import (build_messages, extract_think, gt_choice, letters_of,
                     num_images, num_videos, parse_choice)


class SingleViewMethod(Method):
    def __init__(self, backend, view_idx=1, nframes=8, max_new_tokens=8192,
                 temperature=0.0, name=None, reasoning=True):
        super().__init__(backend, nframes=nframes, max_new_tokens=max_new_tokens,
                         temperature=temperature, reasoning=reasoning)
        self.view_idx = view_idx
        self.name = name or f"single_view{view_idx}"

    def answer(self, rec, video_root, seed=None):
        k = num_videos(rec) or num_images(rec)
        if self.view_idx > k:
            return None  # runner skips: this question has no view i
        messages, yn = build_messages(rec, video_root, self.nframes, no_video=False, reasoning=self.reasoning)
        content = messages[0]["content"]
        # content is [marker, visual] * K + [prompt]; keep pair i and the prompt
        visual_i = 2 * (self.view_idx - 1)
        kept = [content[visual_i], content[visual_i + 1], content[-1]]
        assert kept[1]["type"] in ("video", "image") and kept[0]["type"] == "text", \
            f"unexpected content layout at view {self.view_idx}"
        messages = [{"role": "user", "content": kept}]
        f = result_fields(rec)
        letters = letters_of(rec)
        gold = gt_choice(rec["answer"], yn, letters=letters)
        alloc = {"view_idx": self.view_idx, "K": k}
        try:
            g = self.backend.generate(messages, max_new_tokens=self.max_new_tokens,
                                      seed=seed, temperature=self.temperature)
            pred = parse_choice(g.text, yn, letters=letters, options=rec.get('options'))
            return Result(
                **f, method=self.name, backend=self.backend.name,
                prediction=pred, gold=gold,
                correct=(pred.strip().upper() == gold.strip().upper()),
                abstained=(pred == ""),
                seed=seed, temperature=self.temperature,
                latency_s=g.latency_s,
                input_tokens=g.input_tokens, video_tokens=g.video_tokens,
                output_tokens=g.output_tokens, num_model_calls=1,
                response_text=g.text, think=extract_think(g.text),
                frame_alloc=alloc,
            )
        except Exception as e:
            return Result(**f, method=self.name, backend=self.backend.name,
                          prediction="", gold=gold, correct=False, abstained=True,
                          seed=seed, temperature=self.temperature,
                          num_model_calls=1, frame_alloc=alloc,
                          error=f"{type(e).__name__}: {e}")
