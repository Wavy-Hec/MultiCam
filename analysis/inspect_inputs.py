#!/usr/bin/env python3
"""Task A: read-only inspection of the CVBench model-input pipelines.

Verifies, against the ACTUAL code both harnesses ran (imported, not
re-implemented), for 5 deterministic sample questions:
  * which frames each harness samples from each video_N file,
  * how multiple videos are combined into one model input (order, markers,
    token layout),
  * that the combined input is positionally aligned with the question JSON
    (video_1..video_4 order, _segN files at the right slots).

Produces a markdown-ready report on stdout and raw data in
analysis/inspect_inputs_data.json. Read-only: no eval code is touched.

Run (CPU, no GPU, conda env `cvbench`, offline):
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
      conda run -n cvbench python3 analysis/inspect_inputs.py [--full-processor]

--full-processor additionally replicates eval_thinking.py:190-200 on CPU
(processor + real pixel tensors) and decodes input_ids to show the true
expanded vision-token stream. Without it, only the chat-template string
(unexpanded placeholders) is inspected.
"""
import argparse
import importlib.metadata
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
VIDEO_ROOT = os.path.join(REPO, "Video-R1", "src", "r1-v", "Evaluation", "CVBench")
SUBSET = os.path.join(HERE, "subset.json")
SAMPLES_JSONL = os.path.join(
    REPO, "lmms-eval", "logs", "OpenGVLab__InternVL3-8B",
    "20260610_132552_samples_mvr_think.jsonl")
THINK_ERR_LOG = os.path.join(HERE, "logs", "56677.cvbench_think.err")
QWEN_MODEL = "Qwen/Qwen3-VL-8B-Thinking"
EXPECTED_PICKS = [0, 4, 3, 17, 19]

# verbatim from lmms-eval/lmms_eval/models/internvl2.py:361 (the multi-video cue text)
INTERNVL_CUE = (
    "Please pay close attention to the video frames with special cues that are "
    "interspersed at the beginning and end of a video's content. For example, frames "
    "with the words \"The video X\" represent the beginning of the video called video X, "
    "and frames with the words \"Video X End\" represent the end of the video called video X.")


def assert_env():
    import decord
    import qwen_vl_utils
    import transformers

    import lmms_eval
    qvu = qwen_vl_utils.__file__
    info = {
        "qwen_vl_utils_file": qvu,
        "qwen_vl_utils_version": importlib.metadata.version("qwen-vl-utils"),
        "lmms_eval_file": lmms_eval.__file__,
        "transformers_version": transformers.__version__,
        "decord_version": decord.__version__,
        "torchcodec_present": importlib.util.find_spec("torchcodec") is not None,
    }
    # the run imported the pip-installed qwen_vl_utils, NOT the repo copy
    assert "site-packages" in qvu, qvu
    assert lmms_eval.__file__.startswith(REPO), lmms_eval.__file__
    # production log proves the decord backend was used in the real run
    backend_line = ""
    if os.path.exists(THINK_ERR_LOG):
        for line in open(THINK_ERR_LOG, errors="replace"):
            if "using decord" in line:
                backend_line = line.strip()
                break
    info["decord_backend_log_line"] = backend_line
    assert not info["torchcodec_present"], "torchcodec present: backend chain would differ from the run"
    return info


def select_samples(recs):
    """Deterministic: lowest id per n_videos bucket (2,3,4), then lowest-id
    question with a _seg file, then lowest-id 4-video question with a _seg file."""
    recs = sorted(recs, key=lambda r: r["id"])

    def vids(r):
        return [r[f"video_{i}"] for i in range(1, 5) if r.get(f"video_{i}")]

    picks = []
    for bucket in (2, 3, 4):
        picks.append(next(r["id"] for r in recs if len(vids(r)) == bucket))
    picks.append(next(r["id"] for r in recs
                      if any("_seg" in v for v in vids(r)) and r["id"] not in picks))
    picks.append(next(r["id"] for r in recs
                      if any("_seg" in v for v in vids(r)) and len(vids(r)) == 4
                      and r["id"] not in picks))
    assert picks == EXPECTED_PICKS, f"subset.json changed? picks={picks}"
    return picks


def qwen_video_trace(path):
    """Frame sampling exactly as the eval did: the installed qwen_vl_utils
    fetch_video with the same ele the eval builds ({'video': path, 'nframes': 8})
    and the same image_patch_size=16 (eval_thinking.py:179, Qwen3-VL)."""
    import decord
    from qwen_vl_utils.vision_process import fetch_video
    vr = decord.VideoReader(path)
    raw = {"total_frames": len(vr), "fps": round(float(vr.get_avg_fps()), 3)}
    out = fetch_video({"type": "video", "video": path, "nframes": 8},
                      image_patch_size=16, return_video_metadata=True)
    video, meta = out  # (tensor, metadata) per vision_process.py:477
    # indices must come from the segment file itself (proves _seg handling)
    assert meta["total_num_frames"] == raw["total_frames"], (path, meta, raw)
    assert len(meta["frames_indices"]) == 8
    return {
        **raw,
        "frame_indices": list(meta["frames_indices"]),
        "tensor_shape": list(video.shape),  # (T,C,H,W) after smart_resize
        "backend": meta["video_backend"],
    }


def internvl_video_trace(path):
    """Frame sampling exactly as the eval did: lmms_eval.models.internvl2
    get_index + load_video with num_segments=8, max_num=1, input_size=448
    (internvl2.py:355, num_frame=8 from run_eval.sbatch:57)."""
    import decord
    from lmms_eval.models.internvl2 import get_index, load_video
    vr = decord.VideoReader(path)
    fps, max_frame = float(vr.get_avg_fps()), len(vr) - 1
    idx = get_index(None, fps, max_frame, first_idx=0, num_segments=8)
    pixel_values, num_patches_list = load_video(path, num_segments=8, max_num=1, input_size=448)
    assert len(num_patches_list) == 8
    return {
        "frame_indices": [int(i) for i in idx],
        "num_patches_per_frame": num_patches_list,  # measured, not assumed
        "tensor_shape": list(pixel_values.shape),   # (sum(patches), 3, 448, 448)
    }


def load_processor():
    from transformers import AutoProcessor
    return AutoProcessor.from_pretrained(QWEN_MODEL, trust_remote_code=True)


def qwen_layout(rec, processor, full_processor=False):
    """Message construction + chat-template layout exactly as eval_thinking.py
    main() does it (lines 182-200), CPU-only."""
    sys.path.insert(0, os.path.join(REPO, "Video-R1", "src"))
    from eval_thinking import build_messages
    messages, is_yesno = build_messages(rec, VIDEO_ROOT, 8, no_video=False)
    content = messages[0]["content"]
    n_vid = sum(1 for c in content if c.get("type") == "video")

    # structural check of the content list: ("Video k:", video_k)* then prompt
    for k in range(1, n_vid + 1):
        assert content[2 * (k - 1)] == {"type": "text", "text": f"Video {k}:"}
        assert content[2 * k - 1]["type"] == "video"
        assert content[2 * k - 1]["nframes"] == 8
    assert content[-1]["type"] == "text" and len(content) == 2 * n_vid + 1

    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    # template-level ordering: "Video k:" marker text precedes the k-th vision block
    vis_starts = [m.start() for m in re.finditer(re.escape("<|vision_start|>"), text)]
    assert len(vis_starts) == n_vid, (len(vis_starts), n_vid)
    marker_pos = [text.index(f"Video {k}:") for k in range(1, n_vid + 1)]
    q_pos = text.index(rec["question"][:60])
    order_ok = all(marker_pos[k] < vis_starts[k] for k in range(n_vid)) \
        and all(vis_starts[k] < marker_pos[k + 1] for k in range(n_vid - 1)) \
        and vis_starts[-1] < q_pos
    assert order_ok

    out = {"n_videos": n_vid, "template_text": text, "is_yesno": is_yesno}

    if full_processor:
        # replicate eval_thinking.py:190-200 verbatim (minus .to(device))
        from qwen_vl_utils import process_vision_info
        image_inputs, video_inputs, video_kwargs = process_vision_info(
            messages, return_video_kwargs=True, return_video_metadata=True,
            image_patch_size=16)
        assert video_kwargs == {"do_sample_frames": False}, video_kwargs
        video_inputs, video_metadata = map(list, zip(*video_inputs))
        inputs = processor(text=[text], images=image_inputs, videos=video_inputs,
                           video_metadata=video_metadata, do_resize=False,
                           padding=True, return_tensors="pt", **video_kwargs)
        ids = inputs.input_ids[0].tolist()
        dec = processor.tokenizer.decode(ids)

        # Qwen3-VL expands each video into nframes/2 vision blocks (temporal
        # merge of 2 frames per block), each preceded by a "<T seconds>"
        # timestamp computed from the sampled frame indices.
        block_re = re.compile(r"<([\d.]+) seconds><\|vision_start\|>((?:<\|video_pad\|>)+)<\|vision_end\|>")
        blocks = [{"pos": m.start(), "t": float(m.group(1)),
                   "n_video_pad": m.group(2).count("<|video_pad|>")} for m in block_re.finditer(dec)]
        assert len(blocks) == n_vid * 4, (len(blocks), n_vid)  # 8 frames -> 4 blocks/video

        # group blocks under their "Video k:" marker by character position
        marker_pos_d = [dec.index(f"Video {k}:") for k in range(1, n_vid + 1)] + [len(dec)]
        per_video = []
        for k in range(n_vid):
            grp = [b for b in blocks if marker_pos_d[k] < b["pos"] < marker_pos_d[k + 1]]
            assert len(grp) == 4, (k, len(grp))
            per_video.append({"video_n": k + 1,
                              "timestamps_s": [b["t"] for b in grp],
                              "video_pad_per_block": [b["n_video_pad"] for b in grp]})
        out["token_stream"] = {"total_tokens": len(ids), "blocks_per_video": per_video}
    return out


def check_timestamps(qlay, traces):
    """The in-stream '<T seconds>' markers must equal the mean timestamp of each
    temporally-merged pair of SAMPLED frame indices of the matching video_N file
    -- direct evidence each vision block came from the right file's frames."""
    if "token_stream" not in qlay:
        return False
    for pv, tr in zip(qlay["token_stream"]["blocks_per_video"], traces):
        idx, fps = tr["qwen"]["frame_indices"], tr["qwen"]["fps"]
        expect = [(idx[2 * i] + idx[2 * i + 1]) / 2 / fps for i in range(4)]
        for got, exp in zip(pv["timestamps_s"], expect):
            assert abs(got - exp) < 0.11, (pv["video_n"], got, exp)
        # pads per block = (H/32)*(W/32) of the resized frames
        _, _, h, w = tr["qwen"]["tensor_shape"]
        assert all(p == (h // 32) * (w // 32) for p in pv["video_pad_per_block"])
    return True


def internvl_layout(rec, traces):
    """Rebuild the internvl2.py:345-362 multi-video assembly from the imported
    pieces + the measured per-frame patch counts; cross-check contexts against
    the stored lmms-eval per-sample 'input' field."""
    from lmms_eval.tasks.mvr.utils import mvr_doc_to_text_think
    kwargs = {"pre_prompt": "", "post_prompt1": "", "post_prompt2": ""}
    contexts = mvr_doc_to_text_think(rec, kwargs)

    stored = None
    if os.path.exists(SAMPLES_JSONL):
        for line in open(SAMPLES_JSONL):
            d = json.loads(line)
            if d["doc"]["id"] == rec["id"]:
                stored = d["input"]
                break
    if stored is not None:
        assert stored == contexts, f"id {rec['id']}: stored input != mvr_doc_to_text_think output"

    # assembly per internvl2.py:349-361
    layout, num_patches_lists = [], []
    for j, tr in enumerate(traces, 1):
        a = len(num_patches_lists) + 1
        num_patches_lists += [1] + tr["num_patches_per_frame"] + [1]
        b = len(num_patches_lists)
        layout.append({"video_pos": j,
                       "frame_slots": f"Frame{a} (marker 'This is video {j}'), "
                                      f"Frame{a+1}-Frame{b-1} (8 sampled frames), "
                                      f"Frame{b} (marker 'Video {j} End')",
                       "slot_range": [a, b]})
    video_prefix = "".join(f"Frame{i+1}: <image>\n" for i in range(len(num_patches_lists)))
    question = video_prefix + INTERNVL_CUE + contexts
    return {"contexts": contexts, "stored_input_matches": stored is not None,
            "n_image_slots": len(num_patches_lists), "layout": layout,
            "final_question_string": question}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full-processor", action="store_true")
    args = ap.parse_args()

    env = assert_env()
    print("## Environment fingerprint\n")
    for k, v in env.items():
        print(f"- {k}: `{v}`")

    recs = {r["id"]: r for r in json.load(open(SUBSET))}
    picks = select_samples(list(recs.values()))
    print(f"\nSample ids (deterministic rule): {picks}\n")

    processor = load_processor()
    data = {"env": env, "picks": picks, "questions": {}}

    for qid in picks:
        rec = recs[qid]
        vids = [rec[f"video_{i}"] for i in range(1, 5) if rec.get(f"video_{i}")]
        print(f"\n### id {qid} ({len(vids)} videos, {rec['task_type']})")
        traces = []
        for n, rel in enumerate(vids, 1):
            path = os.path.normpath(os.path.join(VIDEO_ROOT, rel))
            assert os.path.exists(path), path
            q = qwen_video_trace(path)
            iv = internvl_video_trace(path)
            traces.append({"video_n": n, "rel": rel, **{"qwen": q, "internvl": iv}})
            print(f"- video_{n} `{rel}`: {q['total_frames']} frames @ {q['fps']}fps | "
                  f"qwen idx {q['frame_indices']} (resized {q['tensor_shape'][2]}x{q['tensor_shape'][3]}) | "
                  f"internvl idx {iv['frame_indices']} (tiles/frame {set(iv['num_patches_per_frame'])})")

        qlay = qwen_layout(rec, processor, full_processor=args.full_processor)
        ts_checked = check_timestamps(qlay, traces)
        ilay = internvl_layout(rec, [t["internvl"] for t in traces])
        print(f"- qwen layout OK (marker->block order asserted"
              f"{', timestamps match sampled frame indices' if ts_checked else ''}); "
              f"internvl slots: {[l['frame_slots'] for l in ilay['layout']]}")
        if "token_stream" in qlay:
            ts = qlay["token_stream"]
            print(f"- token stream: {ts['total_tokens']} tokens; per video "
                  f"{[(pv['timestamps_s'], pv['video_pad_per_block'][0]) for pv in ts['blocks_per_video']]}")
        data["questions"][qid] = {"videos": traces, "qwen_layout": qlay, "internvl_layout": ilay}

    out = os.path.join(HERE, "inspect_inputs_data.json")
    json.dump(data, open(out, "w"), indent=1)
    print(f"\nwrote {out}")
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
