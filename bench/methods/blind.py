"""BLIND baseline: the exact production prompt scaffold with ZERO visual input
(``build_messages(no_video=True)``). Whatever it scores is the text-prior floor
every sighted arm must clear; the per-question delta vs ``cvbench_native`` is
the "do the pixels help" measurement.

``answer_n`` samples several passes of one question in a single batched
backend call (run_bench --batch-passes, on a backend with ``generate_n``), and
``answer_many`` several questions' passes in one call (--batch-questions, on a
backend with ``generate_many``); the rows are built exactly as ``answer``
builds them, plus ``batch_n``, ``call_seed`` and ``batch_slot``. A batched call
that runs out of GPU memory is retried split in halves, the questions first and
then one question's passes, down to single sequences; only a sequence that
fails on its own becomes an error row.
"""
import torch

from .base import Method, Result, result_fields, think_of
from ..reuse import build_messages, gt_choice, letters_of, parse_choice


class BlindMethod(Method):
    name = "blind"

    def _prepare(self, rec, video_root):
        messages, yn = build_messages(rec, video_root, self.nframes, no_video=True, reasoning=self.reasoning)
        letters = letters_of(rec)
        return messages, yn, letters, gt_choice(rec["answer"], yn, letters=letters)

    def _row(self, rec, g, yn, letters, gold, seed):
        pred = parse_choice(g.answer_span, yn, letters=letters, options=rec.get('options'))
        return Result(
            **result_fields(rec), method=self.name, backend=self.backend.name,
            prediction=pred, gold=gold,
            correct=(pred.strip().upper() == gold.strip().upper()),
            abstained=(pred == ""),
            seed=seed, temperature=self.temperature,
            latency_s=g.latency_s,
            input_tokens=g.input_tokens, video_tokens=g.video_tokens,
            output_tokens=g.output_tokens, num_model_calls=1, batch_n=g.batch_n,
            call_seed=g.call_seed, batch_slot=g.batch_slot,
            parsed_from=g.parsed_from, response_text=g.text, think=think_of(g),
        )

    def _error(self, rec, gold, seed, e, batch_n=None):
        return Result(**result_fields(rec), method=self.name, backend=self.backend.name,
                      prediction="", gold=gold, correct=False, abstained=True,
                      seed=seed, temperature=self.temperature, batch_n=batch_n,
                      num_model_calls=1, error=f"{type(e).__name__}: {e}")

    def answer(self, rec, video_root, seed=None) -> Result:
        messages, yn, letters, gold = self._prepare(rec, video_root)
        try:
            g = self.backend.generate(messages, max_new_tokens=self.max_new_tokens,
                                      seed=seed, temperature=self.temperature)
            return self._row(rec, g, yn, letters, gold, seed)
        except Exception as e:
            return self._error(rec, gold, seed, e)

    def answer_n(self, rec, video_root, seeds):
        """One Result per seed, from ONE backend.generate_n call."""
        return self.answer_many([rec], video_root, seeds)[0]

    def answer_many(self, recs, video_root, seeds):
        """One list of Results (one per seed) per record, from ONE backend call
        over every record x every seed (generate_many; generate_n for one)."""
        prep = [self._prepare(r, video_root) for r in recs]
        return self._call(recs, prep, list(seeds))

    def _call(self, recs, prep, seeds):
        try:
            if len(recs) == 1:
                gens = [self.backend.generate_n(prep[0][0], max_new_tokens=self.max_new_tokens,
                                                seeds=seeds, temperature=self.temperature)]
            else:
                gens = self.backend.generate_many([p[0] for p in prep],
                                                  max_new_tokens=self.max_new_tokens,
                                                  seeds=seeds, temperature=self.temperature)
            return [[self._row(r, g, yn, letters, gold, s) for g, s in zip(gl, seeds)]
                    for r, (_, yn, letters, gold), gl in zip(recs, prep, gens)]
        # error rows stamp batch_n only for a call of two or more sequences: a
        # one-sequence call is a plain generate call, whose rows stamp None
        except torch.cuda.OutOfMemoryError as e:
            if len(recs) * len(seeds) == 1:
                return [[self._error(recs[0], prep[0][3], seeds[0], e, batch_n=None)]]
        except Exception as e:
            n = len(recs) * len(seeds)
            return [[self._error(r, gold, s, e, batch_n=(n if n > 1 else None)) for s in seeds]
                    for r, (_, _, _, gold) in zip(recs, prep)]
        # Out of memory with more than one sequence in the call. A resume never
        # retries an error row, so retry now, in halves, on a released cache
        # (released here, outside the except: the failed call's tensors are
        # freed once its exception is cleared).
        torch.cuda.empty_cache()
        if len(recs) > 1:
            h = len(recs) // 2
            return self._call(recs[:h], prep[:h], seeds) + self._call(recs[h:], prep[h:], seeds)
        h = len(seeds) // 2
        return [self._call(recs, prep, seeds[:h])[0] + self._call(recs, prep, seeds[h:])[0]]
