"""Qwen-family VLM backend (Qwen3-VL-* Thinking/Instruct).

Mirrors the inference path in ``eval_thinking.py`` exactly (same
``process_vision_info`` call with ``return_video_metadata=True`` so the
``nframes`` sampling is preserved, same ``<|video_pad|>`` token accounting) so
that the centralized method reproduces the existing harness's numbers.
"""
import time

import torch

from ..reuse import load_model
from ..methods.base import Backend, GenOut


class QwenBackend(Backend):
    def __init__(self, model_path, dtype="bfloat16"):
        self.model_path = model_path
        self.name = model_path.rstrip("/").split("/")[-1]
        dt = torch.bfloat16 if dtype == "bfloat16" else torch.float16
        self.model, self.processor = load_model(model_path, dt)
        # Qwen3-VL uses 16px patches, Qwen2/2.5-VL 14px.
        self.patch_size = getattr(self.processor.image_processor, "patch_size", None) or 14
        from qwen_vl_utils import process_vision_info
        self._pvi = process_vision_info
        self._vid_id = self.processor.tokenizer.convert_tokens_to_ids("<|video_pad|>")

    def generate(self, messages, max_new_tokens) -> GenOut:
        proc = self.processor
        text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
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
        t0 = time.perf_counter()
        with torch.no_grad():
            gen = self.model.generate(**inputs, max_new_tokens=max_new_tokens)
        dt = time.perf_counter() - t0
        trimmed = gen[:, inputs.input_ids.shape[1]:]
        out = proc.batch_decode(trimmed, skip_special_tokens=True,
                                clean_up_tokenization_spaces=False)[0]
        return GenOut(text=out, input_tokens=total, video_tokens=vid,
                      output_tokens=int(trimmed.shape[1]), latency_s=dt)


# alias -> HF model id (must be cached locally; HF_HUB_OFFLINE=1 on this cluster)
QWEN_ALIASES = {
    "qwen3vl": "Qwen/Qwen3-VL-8B-Thinking",
    "qwen3vl-instruct": "Qwen/Qwen3-VL-8B-Instruct",
    # "qwen25vl": "Qwen/Qwen2.5-VL-7B-Instruct",  # not cached offline; download first
}
