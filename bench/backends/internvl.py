"""InternVL3-8B backend for the multi-camera benchmark.

Mirrors ``QwenBackend``'s interface (``name`` + ``generate(messages, max_new_tokens,
*, seed, temperature) -> GenOut``) so the same Methods drive it. The chat-style
``messages`` content is flattened into InternVL's ``model.chat(...)`` convention:
each ``{"type":"image"}`` (a montage) and each frame of a ``{"type":"video"}``
becomes an ``<image>`` placeholder backed by a tile in ``num_patches_list``; a
text-only message (the per-stream aggregator) runs with ``pixel_values=None``.

IMPORTANT: run this backend under the ``internvl`` conda env (transformers 4.48.3).
``cvbench``'s newer transformers breaks the InternVL3 remote code.

Preprocessing helpers (build_transform / dynamic_preprocess / load_image /
load_video) are copied from ``lmms-eval/lmms_eval/models/internvl2.py`` so we
don't depend on the (absent) ``internvl`` training package.
"""
import time

import numpy as np
import torch
import torchvision.transforms as T
from PIL import Image
from torchvision.transforms.functional import InterpolationMode
from decord import VideoReader, cpu
from transformers import AutoModel, AutoTokenizer

from ..methods.base import Backend, GenOut

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def build_transform(input_size):
    return T.Compose([
        T.Lambda(lambda img: img.convert("RGB") if img.mode != "RGB" else img),
        T.Resize((input_size, input_size), interpolation=InterpolationMode.BICUBIC),
        T.ToTensor(),
        T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])


def find_closest_aspect_ratio(aspect_ratio, target_ratios, width, height, image_size):
    best_ratio_diff = float("inf")
    best_ratio = (1, 1)
    area = width * height
    for ratio in target_ratios:
        target_aspect_ratio = ratio[0] / ratio[1]
        ratio_diff = abs(aspect_ratio - target_aspect_ratio)
        if ratio_diff < best_ratio_diff:
            best_ratio_diff = ratio_diff
            best_ratio = ratio
        elif ratio_diff == best_ratio_diff:
            if area > 0.5 * image_size * image_size * ratio[0] * ratio[1]:
                best_ratio = ratio
    return best_ratio


def dynamic_preprocess(image, min_num=1, max_num=6, image_size=448, use_thumbnail=False):
    orig_width, orig_height = image.size
    aspect_ratio = orig_width / orig_height
    target_ratios = set((i, j) for n in range(min_num, max_num + 1)
                        for i in range(1, n + 1) for j in range(1, n + 1)
                        if i * j <= max_num and i * j >= min_num)
    target_ratios = sorted(target_ratios, key=lambda x: x[0] * x[1])
    target_aspect_ratio = find_closest_aspect_ratio(
        aspect_ratio, target_ratios, orig_width, orig_height, image_size)
    target_width = image_size * target_aspect_ratio[0]
    target_height = image_size * target_aspect_ratio[1]
    blocks = target_aspect_ratio[0] * target_aspect_ratio[1]
    resized_img = image.resize((target_width, target_height))
    processed_images = []
    for i in range(blocks):
        box = ((i % (target_width // image_size)) * image_size,
               (i // (target_width // image_size)) * image_size,
               ((i % (target_width // image_size)) + 1) * image_size,
               ((i // (target_width // image_size)) + 1) * image_size)
        processed_images.append(resized_img.crop(box))
    assert len(processed_images) == blocks
    if use_thumbnail and len(processed_images) != 1:
        processed_images.append(image.resize((image_size, image_size)))
    return processed_images


def load_image(image, input_size=448, max_num=6):
    transform = build_transform(input_size=input_size)
    images = dynamic_preprocess(image, image_size=input_size, use_thumbnail=True, max_num=max_num)
    return torch.stack([transform(im) for im in images])


def get_index(bound, fps, max_frame, first_idx=0, num_segments=32):
    if bound:
        start, end = bound[0], bound[1]
    else:
        start, end = -100000, 100000
    start_idx = max(first_idx, round(start * fps))
    end_idx = min(round(end * fps), max_frame)
    seg_size = float(end_idx - start_idx) / num_segments
    return np.array([int(start_idx + (seg_size / 2) + np.round(seg_size * idx))
                     for idx in range(num_segments)])


def load_video(video_path, bound=None, input_size=448, max_num=1, num_segments=32,
               frame_indices=None):
    vr = VideoReader(video_path, ctx=cpu(0), num_threads=1)
    max_frame = len(vr) - 1
    fps = float(vr.get_avg_fps())
    pixel_values_list, num_patches_list = [], []
    transform = build_transform(input_size=input_size)
    # A method may pass explicit ``frame_indices`` to override frame choice;
    # every current method leaves it None and gets the uniform get_index grid,
    # so this is a no-op for centralized / temporal_* / cvbench_native / *_select.
    if frame_indices is None:
        frame_indices = get_index(bound, fps, max_frame, first_idx=0, num_segments=num_segments)
    for frame_index in frame_indices:
        frame_index = int(min(max(0, int(frame_index)), max_frame))   # clamp into range
        img = Image.fromarray(vr[frame_index].asnumpy()).convert("RGB")
        tiles = dynamic_preprocess(img, image_size=input_size, use_thumbnail=True, max_num=max_num)
        pv = torch.stack([transform(t) for t in tiles])
        num_patches_list.append(pv.shape[0])
        pixel_values_list.append(pv)
    return torch.cat(pixel_values_list), num_patches_list


class InternVL3Backend(Backend):
    # honors a per-video ``frame_indices`` override (see load_video); a method
    # that relies on explicit indices can assert this flag so it never silently
    # collapses to uniform sampling on a backend that ignores the key.
    consumes_frame_indices = True

    def __init__(self, model_path="OpenGVLab/InternVL3-8B", num_frame=8, max_tiles=1,
                 device="cuda:0"):
        self.model_path = model_path
        self.name = model_path.rstrip("/").split("/")[-1]
        self.num_frame = num_frame
        self.max_tiles = max_tiles
        self.device = device

        # InternVL remote code calls .item() on a torch.linspace during __init__;
        # route device-less linspace to CPU while from_pretrained constructs the
        # model (harmless no-op on transformers 4.48.3; required on >=5).
        _orig_linspace = torch.linspace

        def _cpu_linspace(*args, **kwargs):
            kwargs.setdefault("device", "cpu")
            return _orig_linspace(*args, **kwargs)

        torch.linspace = _cpu_linspace
        try:
            self.model = AutoModel.from_pretrained(
                model_path, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True,
                trust_remote_code=True, device_map=device).eval()
        finally:
            torch.linspace = _orig_linspace

        # Without flash-attn the remote code forces eager attention, which OOMs on
        # multi-image prompts; the LLM picks its kernel from config at runtime.
        lm_cfg = getattr(getattr(self.model, "language_model", None), "config", None)
        if lm_cfg is not None and getattr(lm_cfg, "_attn_implementation", None) == "eager":
            lm_cfg._attn_implementation = "sdpa"
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self.num_image_token = getattr(self.model, "num_image_token", 256)

    def _flatten(self, content):
        """messages content list -> (question_str, pixel_values|None, num_patches_list|None)."""
        parts, pixel_chunks, npl = [], [], []
        for item in content:
            t = item.get("type")
            if t == "text":
                parts.append(item["text"])
            elif t == "image":
                px = load_image(item["image"], input_size=448, max_num=self.max_tiles)
                pixel_chunks.append(px)
                npl.append(px.shape[0])
                parts.append("<image>\n")
            elif t == "video":
                nf = item.get("nframes", self.num_frame)
                px, sub = load_video(item["video"], num_segments=nf, max_num=1, input_size=448,
                                     frame_indices=item.get("frame_indices"))
                pixel_chunks.append(px)
                npl.extend(sub)
                parts.append("".join(f"Frame{i+1}: <image>\n" for i in range(len(sub))))
        question = "".join(parts)
        if pixel_chunks:
            pixel_values = torch.cat(pixel_chunks, dim=0).to(torch.bfloat16).to(self.device)
            return question, pixel_values, npl
        return question, None, None

    def generate(self, messages, max_new_tokens, *, seed=None, temperature=0.0) -> GenOut:
        content = messages[0]["content"]
        question, pixel_values, npl = self._flatten(content)
        do_sample = temperature is not None and temperature > 0
        if do_sample and seed is not None:
            torch.manual_seed(seed)
        gen_cfg = dict(num_beams=1, max_new_tokens=max_new_tokens, do_sample=do_sample)
        if do_sample:
            gen_cfg.update(temperature=temperature, top_p=0.9)
        t0 = time.perf_counter()
        with torch.no_grad():
            response = self.model.chat(self.tokenizer, pixel_values, question, gen_cfg,
                                       num_patches_list=npl, history=None, return_history=True)[0]
        dt = time.perf_counter() - t0

        # best-effort token accounting (not directly comparable to Qwen's <|video_pad|>):
        # text tokens + the IMG_CONTEXT expansion (num_image_token per tile).
        text_tokens = int(self.tokenizer(question, return_tensors="pt").input_ids.shape[1])
        img_tokens = self.num_image_token * (sum(npl) if npl else 0)
        out_tokens = int(self.tokenizer(response, return_tensors="pt").input_ids.shape[1])
        return GenOut(text=response, input_tokens=text_tokens + img_tokens,
                      video_tokens=img_tokens, output_tokens=out_tokens, latency_s=dt)
