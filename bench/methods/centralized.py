"""CENTRALIZED harness (spec-faithful): one model ingests a SINGLE unified input
built by temporally aligning the camera streams and spatially STITCHING the
synchronized frames into grid-montage images (see ``stitch.build_montages``).

The text scaffold (question/options/<think>/<answer>) is taken verbatim from the
existing harness (``build_messages(..., no_video=True)``) so only the visual
presentation differs from the blind/per-stream paths. The montages for a question
are built once and cached, so the 4 sampling passes reuse identical pixels.
"""
from .base import Method, Result, result_fields
from .stitch import build_montages
from ..reuse import build_messages, parse_choice, gt_choice, video_paths

# "camera" — MEVA-style synchronized multi-view (default, unchanged).
MONTAGE_PREFIX_CAMERA = (
    "The following {T} image(s) are time-synchronized grid montages of {k} camera "
    "view(s), shown in chronological order. Each montage tiles the cameras into a "
    "grid; every cell is labeled 'Camera i' (top-left). Reason across the views and "
    "over time to answer.")
# "video" — CVBench-style INDEPENDENT clips (corrected preamble: matches the
# 'Video i' labels used in the question, and does not falsely call them synchronized).
MONTAGE_PREFIX_VIDEO = (
    "The following {T} image(s) are grid montages built from {k} independent video "
    "clips (different, unrelated scenes), shown in chronological order. Each montage "
    "tiles the {k} clips into a grid; every cell is labeled 'Video i' (top-left), "
    "corresponding to Video 1..Video {k} in the question. Reason about each Video "
    "separately as well as together, and over time, to answer.")
MONTAGE_PREFIXES = {"camera": MONTAGE_PREFIX_CAMERA, "video": MONTAGE_PREFIX_VIDEO}
MONTAGE_LABELS = {"camera": "Camera", "video": "Video"}
MONTAGE_PREFIX = MONTAGE_PREFIX_CAMERA  # backward-compat alias


class CentralizedMethod(Method):
    name = "centralized"

    def __init__(self, backend, nframes=8, max_new_tokens=8192, temperature=0.0,
                 montage_frames=0, cell_px=448, montage_kind="camera"):
        super().__init__(backend, nframes=nframes, max_new_tokens=max_new_tokens,
                         temperature=temperature)
        self.T = montage_frames if montage_frames and montage_frames > 0 else nframes
        self.cell_px = cell_px
        self.montage_kind = montage_kind  # "camera" (synced views) | "video" (independent clips)
        self._prefix = MONTAGE_PREFIXES[montage_kind]
        self._label = MONTAGE_LABELS[montage_kind]
        self._cache = {}  # rec id -> (montages, scaffold_text, yn, gold); last rec only

    def _prepare(self, rec, video_root):
        key = rec.get("id")
        if key in self._cache:
            return self._cache[key]
        base_msgs, yn = build_messages(rec, video_root, self.nframes, no_video=True)
        scaffold = base_msgs[0]["content"][0]["text"]
        paths = video_paths(rec, video_root)
        montages = build_montages(paths, nframes=self.nframes, T=self.T, cell_px=self.cell_px,
                                  label_prefix=self._label)
        gold = gt_choice(rec["answer"], yn)
        self._cache = {key: (montages, scaffold, yn, gold, len(paths))}  # keep only last rec
        return self._cache[key]

    def answer(self, rec, video_root, seed=None) -> Result:
        f = result_fields(rec)
        try:
            montages, scaffold, yn, gold, k = self._prepare(rec, video_root)
        except Exception as e:
            gold = gt_choice(rec["answer"], all(o.strip().strip(".").lower() in ("yes", "no")
                                                for o in rec["options"]))
            return Result(**f, method=self.name, backend=self.backend.name,
                          prediction="", gold=gold, correct=False, abstained=True,
                          pass_idx=None, seed=seed, temperature=self.temperature,
                          num_model_calls=1, error=f"stitch:{type(e).__name__}: {e}")
        content = [{"type": "text", "text": self._prefix.format(T=len(montages), k=k)}]
        content += [{"type": "image", "image": m} for m in montages]
        content += [{"type": "text", "text": scaffold}]
        messages = [{"role": "user", "content": content}]
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
        except Exception as e:  # keep the sweep alive; record the failure
            return Result(**f, method=self.name, backend=self.backend.name,
                          prediction="", gold=gold, correct=False, abstained=True,
                          seed=seed, temperature=self.temperature,
                          num_model_calls=1, error=f"{type(e).__name__}: {e}")
