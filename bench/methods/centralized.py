"""A0 - Centralized "today's VLM": one model ingests all clips in one prompt.

This is exactly the existing harness path (``eval_thinking.build_messages``),
wrapped as a Method with per-question timing added.
"""
from .base import Method, Result, result_fields
from ..reuse import build_messages, parse_choice, gt_choice


class CentralizedMethod(Method):
    name = "centralized"

    def answer(self, rec, video_root) -> Result:
        messages, yn = build_messages(rec, video_root, self.nframes, no_video=False)
        f = result_fields(rec)
        gold = gt_choice(rec["answer"], yn)
        try:
            g = self.backend.generate(messages, max_new_tokens=self.max_new_tokens)
            pred = parse_choice(g.text, yn)
            return Result(
                **f, method=self.name, backend=self.backend.name,
                prediction=pred, gold=gold,
                correct=(pred.strip().upper() == gold.strip().upper()),
                abstained=(pred == ""),
                latency_s=g.latency_s,
                input_tokens=g.input_tokens, video_tokens=g.video_tokens,
                output_tokens=g.output_tokens, num_model_calls=1,
            )
        except Exception as e:  # keep the sweep alive; record the failure
            return Result(**f, method=self.name, backend=self.backend.name,
                          prediction="", gold=gold, correct=False, abstained=True,
                          num_model_calls=1, error=f"{type(e).__name__}: {e}")
