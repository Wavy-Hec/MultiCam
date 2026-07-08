"""CVBench-native presentation: the exact method described in CVBench --- the
multiple clips are fed to ONE model as separate, sequential video blocks (each
clip's frames presented as a temporal sequence with a ``"Video k:"`` marker),
not stitched. This is the baseline the stitching harness is compared against at
an equal frame budget.

It is the production ``build_messages(no_video=False)`` path, wrapped as a
Method with per-question timing + seed/temperature plumbing.
"""
from .base import Method, Result, result_fields
from ..reuse import build_messages, parse_choice, gt_choice


class CVBenchNativeMethod(Method):
    name = "cvbench_native"

    def answer(self, rec, video_root, seed=None) -> Result:
        messages, yn = build_messages(rec, video_root, self.nframes, no_video=False)
        f = result_fields(rec)
        gold = gt_choice(rec["answer"], yn)
        try:
            g = self.backend.generate(messages, max_new_tokens=self.max_new_tokens,
                                      seed=seed, temperature=self.temperature)
            pred = parse_choice(g.text, yn)
            return Result(
                **f, method=self.name, backend=self.backend.name,
                prediction=pred, gold=gold,
                correct=(pred.strip().upper() == gold.strip().upper()),
                abstained=(pred == ""),
                seed=seed, temperature=self.temperature,
                latency_s=g.latency_s,
                input_tokens=g.input_tokens, video_tokens=g.video_tokens,
                output_tokens=g.output_tokens, num_model_calls=1,
            )
        except Exception as e:
            return Result(**f, method=self.name, backend=self.backend.name,
                          prediction="", gold=gold, correct=False, abstained=True,
                          seed=seed, temperature=self.temperature,
                          num_model_calls=1, error=f"{type(e).__name__}: {e}")
