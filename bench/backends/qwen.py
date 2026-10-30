"""Qwen-family VLM backend (Qwen3-VL-* Thinking/Instruct, Qwen2.5-VL-*, Qwen3.8).

Mirrors the inference path in ``eval_thinking.py`` exactly (same
``process_vision_info`` call with ``return_video_metadata=True`` so the
``nframes`` sampling is preserved, same ``<|video_pad|>`` token accounting) so
that the centralized method reproduces the existing harness's numbers.

``return_video_metadata=True`` is right for BOTH families under transformers>=5:
the Qwen2.5-VL processor derives ``second_per_grid_ts`` from that metadata
(processing_qwen2_5_vl.py:100-116) and no longer reads qwen-vl-utils' legacy
``fps`` back-compat kwarg. Patch size auto-detects (16px Qwen3-VL, 14px
Qwen2.5-VL), so Qwen2.5-VL bills ~1.3x the visual tokens for identical input.

Qwen3.8-27B (a Qwen3.5-architecture VLM) loads through the same path. Its chat
template takes ``enable_thinking`` / ``reasoning_effort``; both stay at the
template default (thinking on, effort xhigh) unless QWEN_ENABLE_THINKING /
QWEN_REASONING_EFFORT are set at submit time, and every row stamps the
requested values as ``decode`` (null = the template's own default, however it
was spelled) so legs that differ in them never pool.
"""
import hashlib
import json
import os
import time

import torch

from ..reuse import load_model
from ..methods.base import Backend, GenOut

# Per-checkpoint presets. Every Qwen leg before Qwen3.8 ran with top_p 0.9, the
# checkpoint's own generation_config top_k and a whole-text answer parse, and
# still does; Qwen3.8-27B takes its model card's thinking-mode sampling, in both
# modes: the no-thinking control keeps it on purpose, to match the reference
# protocol it is a control for.
# Temperature stays a submit-time TEMPERATURE for every backend (the card's is 1.0).
#   answer_after_think: Qwen3.8's template pre-opens <think>, and its native
#     reasoning restates the prompt's instruction ("final answer between
#     <answer> and </answer>"), so the first <answer> tag in the raw text is
#     often inside the reasoning (a preflight run parsed " and " and scored an
#     abstention). When the generation ENDED, the answer is parsed from the reply
#     after the last </think>, as the template itself splits reasoning from
#     content; a trace cut at max_new_tokens keeps the whole-text parse (its
#     </think> occurrences are quotes of the prompt, not a closed block).
#   template_knobs: the chat template reads enable_thinking / reasoning_effort.
# A key matches its HF id exactly, or a path whose last component is the id's
# last component, case ignored (a trailing slash, or a local copy of the
# checkpoint); QwenBackend.name is that component either way.
QWEN_DECODE = {
    "Qwen/Qwen3.8-27B": {"top_p": 0.95, "top_k": 20, "answer_after_think": True,
                         "template_knobs": True},
}
REASONING_EFFORTS = ("xhigh", "medium", "low")   # what the Qwen3.8 template accepts (default first)
_TRUE, _FALSE = ("1", "true", "yes", "on"), ("0", "false", "no", "off")
# The seeding scheme of a batched generate call (call_seed); run_bench stamps it
# as `rng` in the decode stamp of a --batch-passes leg, so rows drawn under
# another scheme never pool with these. Bump it whenever call_seed changes.
CALL_SEED_SCHEME = "call_hash_v1"
_NOTED = set()   # model paths whose preset NOTE has been printed


def _env_flag(name):
    v = os.environ.get(name, "").strip().lower()
    if v == "":
        return None
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise SystemExit(f"{name}={os.environ[name]!r}: use one of {_TRUE + _FALSE}")


def _preset(model_path):
    """(QWEN_DECODE key, preset) for ``model_path``, ``(None, {})`` when no
    preset matches. A match on the last path component prints a NOTE (once
    per path), so a preset never applies to a path without a word."""
    if model_path in QWEN_DECODE:
        return model_path, QWEN_DECODE[model_path]
    base = model_path.rstrip("/").split("/")[-1].lower()
    for key, preset in QWEN_DECODE.items():
        if key.split("/")[-1].lower() == base:
            if model_path not in _NOTED:
                _NOTED.add(model_path)
                print(f"NOTE {model_path}: decodes with the {key} preset (matched on its "
                      "last path component)", flush=True)
            return key, preset
    return None, {}


def canonical_decode(d):
    """The decode stamp ``d`` spelled one way per rendered prompt. The template
    reads `enable_thinking is undefined or enable_thinking is true` and
    `reasoning_effort|default('xhigh')`, so an explicit default (thinking on,
    or effort xhigh while thinking) renders what an unset knob renders and
    maps to None. decode_identity returns this form, and run_bench reads a
    file's stamps back in it: rows stamped before the mapping carry an
    explicit default as spelled. Every other key (rng included) is kept; a
    None stamp stays None."""
    if not isinstance(d, dict):
        return d
    d = dict(d)
    if d.get("enable_thinking") is True:
        d["enable_thinking"] = None
    if d.get("reasoning_effort") == REASONING_EFFORTS[0] and d.get("enable_thinking") is not False:
        d["reasoning_effort"] = None
    return d


def decode_identity(model_path):
    """The sampling / chat-template / parse settings a QwenBackend on
    ``model_path`` runs with: the checkpoint's preset, and each template knob
    as requested, None meaning the checkpoint's or template's own default. An
    explicit default (thinking on, or effort xhigh while thinking) renders the
    same prompt as an unset knob, so it stamps as None too (canonical_decode).
    Resolved without loading the model, so run_bench can stamp rows and refuse
    a bad knob or a resume that would change them before any GPU work."""
    key, preset = _preset(model_path)
    thinking = _env_flag("QWEN_ENABLE_THINKING")
    effort = os.environ.get("QWEN_REASONING_EFFORT", "").strip().lower() or None
    if not preset.get("template_knobs"):
        if thinking is not None or effort is not None:
            raise SystemExit(
                f"QWEN_ENABLE_THINKING / QWEN_REASONING_EFFORT are set but {model_path}'s "
                "chat template has no such knobs (only checkpoints with template_knobs in "
                "bench/backends/qwen.py QWEN_DECODE read them, matched by HF id or by the "
                "path's last component); unset them")
    elif effort is not None:
        if effort not in REASONING_EFFORTS:
            raise SystemExit(
                f"QWEN_REASONING_EFFORT={os.environ['QWEN_REASONING_EFFORT']!r}: the {key} "
                f"template accepts only {', '.join(REASONING_EFFORTS)} (any case); unset it "
                "for the template default, xhigh")
        if thinking is False:
            raise SystemExit("QWEN_REASONING_EFFORT has no effect with QWEN_ENABLE_THINKING=0; "
                             "unset one of them")
    return canonical_decode({
        "top_p": preset.get("top_p", 0.9),
        "top_k": preset.get("top_k"),
        "answer_after_think": preset.get("answer_after_think", False),
        "enable_thinking": thinking,
        "reasoning_effort": effort,
    })


def turn_length(seq, eos_ids):
    """(generated tokens through the first end-of-turn token inclusive, whether
    the turn ended). A row that never emitted one ran out of max_new_tokens and
    is counted whole."""
    hits = torch.isin(seq, eos_ids).nonzero()
    return (int(hits[0]) + 1, True) if len(hits) else (int(seq.shape[0]), False)


def call_seed(seeds, prompts):
    """The seed ONE batched generate call runs under (CALL_SEED_SCHEME): a
    sha256 of its base seed (seeds[0]), its exact rendered prompts in order and
    its pass labels, folded to 31 bits. Rerunning the same call draws the same
    stream; other questions, another option order or other pending passes draw
    another. (Seeding every call with seeds[0] replayed one noise stream per
    batch slot across every call of a leg.) Text-only prompts, as
    generate_many requires: a visual prompt renders its media as a
    placeholder, so the hash would not see the clip. Only a call of two or
    more sequences draws its own stream: an unbatched call, or a one-sequence
    call in a batched leg, is still seeded with its pass seed (generate), so
    pass p of every such question shares one noise stream. hashlib, not
    hash(): Python randomizes str hashes per process."""
    key = json.dumps([seeds[0], list(prompts), list(seeds)])
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:4], "big") & 0x7FFFFFFF


class QwenBackend(Backend):
    def __init__(self, model_path, dtype="bfloat16"):
        self.model_path = model_path
        self.name = model_path.rstrip("/").split("/")[-1]
        self.decode = decode_identity(model_path)
        # only set knobs reach the template, so an unset one renders exactly
        # what the bare template call always rendered
        self._template_kwargs = {k: self.decode[k] for k in ("enable_thinking", "reasoning_effort")
                                 if self.decode[k] is not None}
        dt = torch.bfloat16 if dtype == "bfloat16" else torch.float16
        self.model, self.processor = load_model(model_path, dt)
        # Qwen3-VL uses 16px patches, Qwen2/2.5-VL 14px.
        self.patch_size = getattr(self.processor.image_processor, "patch_size", None) or 14
        from qwen_vl_utils import process_vision_info
        self._pvi = process_vision_info
        self._vid_id = self.processor.tokenizer.convert_tokens_to_ids("<|video_pad|>")
        self._img_id = self.processor.tokenizer.convert_tokens_to_ids("<|image_pad|>")
        eos = self.model.generation_config.eos_token_id
        self._eos_ids = torch.tensor(eos if isinstance(eos, (list, tuple)) else [eos],
                                     device=self.model.device)

    def _prompt(self, messages):
        return self.processor.apply_chat_template(messages, tokenize=False,
                                                  add_generation_prompt=True,
                                                  **self._template_kwargs)

    def _inputs(self, messages):
        """Processor inputs for one prompt, with its total and visual token counts."""
        proc = self.processor
        text = self._prompt(messages)
        image_inputs, video_inputs, video_kwargs = self._pvi(
            messages, return_video_kwargs=True, return_video_metadata=True,
            image_patch_size=self.patch_size)
        if video_inputs is not None:
            video_inputs, video_metadata = map(list, zip(*video_inputs))
        else:
            video_metadata = None
        inputs = proc(text=[text], images=image_inputs, videos=video_inputs,
                      video_metadata=video_metadata, do_resize=False, padding=True,
                      return_tensors="pt", **video_kwargs).to(self.model.device)
        total = int(inputs.input_ids.shape[1])
        vid = int((inputs.input_ids[0] == self._vid_id).sum())
        if self._img_id is not None:
            vid += int((inputs.input_ids[0] == self._img_id).sum())
        return inputs, total, vid

    def _sampling(self, max_new_tokens, temperature):
        do_sample = temperature is not None and temperature > 0
        gen_kwargs = dict(max_new_tokens=max_new_tokens, do_sample=do_sample)
        if do_sample:
            gen_kwargs.update(temperature=temperature, top_p=self.decode["top_p"])
            if self.decode["top_k"] is not None:
                gen_kwargs.update(top_k=self.decode["top_k"])
        return do_sample, gen_kwargs

    def _out(self, seq, *, ended=None, **acct):
        """GenOut for one generated row. `ended` is decided from the tokens, never
        from the text: Qwen3.8 quotes '<think> and </think>' while thinking, so a
        trace cut at max_new_tokens still contains '</think>'. Under
        answer_after_think an ended trace is parsed from the reply after its last
        </think> and its think_text is everything before it. A thinking trace
        with no such split (cut at max_new_tokens, or never closed) is reasoning
        throughout, since the template opened the block: its think_text is the
        whole text, while the answer is still parsed from the whole text."""
        n_tok, hit_end = turn_length(seq, self._eos_ids)
        out = self.processor.batch_decode(seq[None, :n_tok], skip_special_tokens=True,
                                          clean_up_tokenization_spaces=False)[0]
        ended = hit_end if ended is None else ended
        answer = think = None
        if self.decode["answer_after_think"] and ended and "</think>" in out:
            think, answer = out.rsplit("</think>", 1)
            think = think.strip()
        elif self.decode["answer_after_think"] and self.decode["enable_thinking"] is not False:
            # not extract_think(out): its first <think>...</think> match is the
            # quote of the prompt's tags, which stored the word "and"
            think = out.strip()
        return GenOut(text=out, output_tokens=n_tok, answer_text=answer, think_text=think, **acct)

    def generate(self, messages, max_new_tokens, *, seed=None, temperature=0.0) -> GenOut:
        inputs, total, vid = self._inputs(messages)
        do_sample, gen_kwargs = self._sampling(max_new_tokens, temperature)
        if do_sample and seed is not None:
            torch.manual_seed(seed)
        t0 = time.perf_counter()
        with torch.no_grad():
            gen = self.model.generate(**inputs, **gen_kwargs)
        dt = time.perf_counter() - t0
        trimmed = gen[0, inputs.input_ids.shape[1]:]
        # a single call stops AT its end-of-turn token, so the whole row counts
        g = self._out(trimmed, input_tokens=total, video_tokens=vid, latency_s=dt)
        g.output_tokens = int(trimmed.shape[0])
        return g

    def generate_n(self, messages, max_new_tokens, *, seeds, temperature=0.0):
        """len(seeds) sampled passes of ONE prompt in one generate call
        (num_return_sequences), seeded once with call_seed. Decode-bound on a
        27B checkpoint, the batch costs about what one sequence does. Each
        sample reports exactly what a single call would: its text, and
        output_tokens through its first end-of-turn token (a single call stops
        there; the batch pads finished rows). latency_s is the batched call's
        wall clock, shared by its samples, and batch_n records the batch size.
        Greedy decoding or a single seed falls back to plain generate calls."""
        return self.generate_many([messages], max_new_tokens, seeds=seeds,
                                  temperature=temperature)[0]

    def generate_many(self, messages_list, max_new_tokens, *, seeds, temperature=0.0):
        """Every prompt in `messages_list` x len(seeds) sampled passes in ONE
        generate call; returns one list of GenOut per prompt. Several prompts
        are LEFT-padded into one batch: the Qwen3.5 linear-attention layers
        zero padded positions (apply_mask_to_padding_states) and get_rope_index
        skips them, so a padded row decodes as it would alone (up to bf16
        batch-shape effects). Prompts are text-only by contract: a visual one
        is refused among several, and alone (generate_n) it decodes, but its
        call_seed hashes only the rendered text, where the media is a
        placeholder. batch_n = sequences in the call, batch_slot = a sample's
        row among them (prompt i, pass j -> i * len(seeds) + j), and call_seed
        = the one seed the call runs under, a hash of its rendered prompts and
        pass labels (call_seed())."""
        do_sample, gen_kwargs = self._sampling(max_new_tokens, temperature)
        if not do_sample or len(messages_list) * len(seeds) < 2:
            return [[self.generate(m, max_new_tokens, seed=s, temperature=temperature)
                     for s in seeds] for m in messages_list]
        if len(messages_list) == 1:
            inputs, total, vid = self._inputs(messages_list[0])
            totals, vids = [total], [vid]
            prompts = [self._prompt(messages_list[0])]   # the text _inputs tokenized
        else:
            for m in messages_list:
                if any(isinstance(msg.get("content"), list) and
                       any(item.get("type") in ("image", "video") for item in msg["content"])
                       for msg in m):
                    raise ValueError("generate_many batches several prompts only when they are "
                                     "text-only; send visual prompts one at a time")
            prompts = [self._prompt(m) for m in messages_list]
            tok = self.processor.tokenizer
            side, tok.padding_side = tok.padding_side, "left"
            try:
                inputs = self.processor(text=prompts, padding=True,
                                        return_tensors="pt").to(self.model.device)
            finally:
                tok.padding_side = side
            totals = [int(x) for x in inputs.attention_mask.sum(dim=1)]
            vids = [0] * len(messages_list)
        n = len(seeds)
        seed = call_seed(seeds, prompts)
        torch.manual_seed(seed)
        t0 = time.perf_counter()
        with torch.no_grad():
            gen = self.model.generate(**inputs, num_return_sequences=n, **gen_kwargs)
        dt = time.perf_counter() - t0
        trimmed = gen[:, inputs.input_ids.shape[1]:]
        # num_return_sequences expands prompt i into rows i*n .. i*n+n-1
        return [[self._out(trimmed[i * n + j], input_tokens=totals[i], video_tokens=vids[i],
                           latency_s=dt, batch_n=int(trimmed.shape[0]),
                           call_seed=seed, batch_slot=i * n + j)
                 for j in range(n)] for i in range(len(messages_list))]


# alias -> HF model id (must be cached locally; HF_HUB_OFFLINE=1 on this cluster)
QWEN_ALIASES = {
    "qwen3vl": "Qwen/Qwen3-VL-8B-Thinking",
    "qwen3vl-instruct": "Qwen/Qwen3-VL-8B-Instruct",
    "qwen25vl": "Qwen/Qwen2.5-VL-7B-Instruct",
    "qwen38": "Qwen/Qwen3.8-27B",
}
