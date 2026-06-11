#!/usr/bin/env python3
"""Thinking-enabled CVBench eval for Qwen-family VLMs (e.g. Qwen3-VL-*-Thinking).

Adapted from eval_bench.py, but:
  * parameterized (--model_path / --input_json / --output / --video_root / etc.)
    instead of hardcoded paths and a single checkpoint;
  * uses the model's own AutoProcessor chat template (so it works for Qwen3-VL,
    not just Qwen2.5-VL) -- no manual <|vision_start|> token surgery;
  * feeds each video as its own clip with a TEXT boundary marker ("Video k:")
    rather than concatenating all clips into one tensor;
  * prompts for visible reasoning between <think>..</think> and the final choice
    between <answer>..</answer>, and SAVES the full output + reasoning trace,
    the parsed prediction, correctness, num_videos and task_type per question.

Backend: HuggingFace transformers (robust for the qualitative subset). For the
Stage-B full 1000-question run, a vLLM backend would be faster; this script keeps
the simple transformers path so the reasoning traces are easy to capture/inspect.

Run on a GPU node (L40 / A100), from the repo root or Video-R1/:
  python3 Video-R1/src/eval_thinking.py \
      --model_path Qwen/Qwen3-VL-8B-Thinking \
      --input_json analysis/subset.json \
      --output Video-R1/src/r1-v/eval_results/eval_subset_qwen3vl.json \
      --nframes 8 --max_new_tokens 2048

Smoke test (first 3 questions):
  python3 Video-R1/src/eval_thinking.py --model_path <ckpt> \
      --input_json analysis/subset.json --output /tmp/smoke.json --limit 3
"""
import argparse
import json
import os
import re

import torch
from tqdm import tqdm

# ---------------------------------------------------------------------------

QUESTION_TEMPLATE = (
    "{Question}\n"
    "Please think about this question as if you were a human pondering deeply. "
    "Engage in an internal dialogue using expressions such as 'let me think', 'wait', "
    "'Hmm', 'oh, I see', 'let's break it down', etc, or other natural language thought "
    "expressions. It's encouraged to include self-reflection or verification in the "
    "reasoning process. Provide your detailed reasoning between the <think> and </think> "
    "tags, and then give your final answer between the <answer> and </answer> tags."
)


def extract_think(text):
    m = re.search(r"<think>\s*(.*?)\s*</think>", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Thinking checkpoints (e.g. Qwen3-VL-*-Thinking) open <think> inside the
    # generation prompt, so the decoded output holds only "trace...</think>".
    if "</think>" in text:
        return text.split("</think>", 1)[0].strip()
    return ""


def extract_answer(text):
    m = re.search(r"<answer>\s*(.*?)\s*</answer>", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def parse_choice(text, is_yesno):
    """Final answer = <answer>..</answer> if present, else fall back to a regex
    over the tail of the output."""
    ans = extract_answer(text)
    src = ans if ans else text
    if is_yesno:
        m = re.search(r"(?i)\b(yes|no)\b", src)
        return m.group(1).capitalize() if m else src.strip()
    m = re.search(r"(?i)\b([ABCD])\b", src)
    return m.group(1).upper() if m else src.strip()


def gt_choice(answer, is_yesno):
    a = answer.strip()
    if is_yesno:
        return a.capitalize()
    m = re.search(r"(?i)([ABCD])", a)
    return m.group(1).upper() if m else a.upper()


def num_videos(rec):
    return sum(1 for i in range(1, 5) if rec.get(f"video_{i}"))


def video_paths(rec, video_root):
    out = []
    for i in range(1, 5):
        v = rec.get(f"video_{i}")
        if v:
            out.append(os.path.normpath(os.path.join(video_root, v)))
    return out


def build_messages(rec, video_root, nframes, no_video=False):
    options = rec["options"]
    is_yesno = all(o.strip().strip(".").lower() in ("yes", "no") for o in options)
    if is_yesno:
        option_prompt = ("Select the best answer to the following yes-no question based on "
                         "all the listed videos.")
        post = "Provide only the single word (Yes or No) within the <answer> </answer> tags."
    else:
        option_prompt = ("Select the best answer to the following multiple-choice question "
                         "based on all the listed videos.")
        post = "Provide only the single option letter (A, B, C, or D) within the <answer> </answer> tags."

    question = rec["question"] + "\n" + "\n".join(options)
    full_prompt = option_prompt + "\n" + QUESTION_TEMPLATE.format(Question=question) + "\n" + post

    # interleave a text marker before each video clip; with no_video (blind
    # baseline) keep the prompt text identical but attach zero visual input
    content = []
    if not no_video:
        for k, vp in enumerate(video_paths(rec, video_root), 1):
            content.append({"type": "text", "text": f"Video {k}:"})
            content.append({"type": "video", "video": vp, "nframes": nframes})
    content.append({"type": "text", "text": full_prompt})
    return [{"role": "user", "content": content}], is_yesno


def load_model(model_path, dtype):
    from transformers import AutoProcessor
    try:
        from transformers import AutoModelForImageTextToText as AutoVLM
    except ImportError:  # older transformers
        from transformers import AutoModelForVision2Seq as AutoVLM
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
    model = AutoVLM.from_pretrained(
        model_path, torch_dtype=dtype, device_map="auto", trust_remote_code=True
    ).eval()
    return model, processor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_path", required=True)
    ap.add_argument("--input_json", required=True)
    ap.add_argument("--output", required=True)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--video_root",
                    default=os.path.join(here, "r1-v", "Evaluation", "CVBench"))
    ap.add_argument("--nframes", type=int, default=8, help="frames sampled per video")
    ap.add_argument("--max_new_tokens", type=int, default=2048)
    ap.add_argument("--limit", type=int, default=0, help="only run first N (smoke test)")
    ap.add_argument("--no_video", action="store_true",
                    help="blind baseline: same prompts, no video input")
    ap.add_argument("--dtype", default="bfloat16", choices=["bfloat16", "float16"])
    args = ap.parse_args()

    from qwen_vl_utils import process_vision_info

    with open(args.input_json) as f:
        data = json.load(f)
    if args.limit:
        data = data[: args.limit]

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    # resume
    results, done_ids = [], set()
    if os.path.exists(args.output):
        try:
            prev = json.load(open(args.output)).get("results", [])
            results = prev
            done_ids = {r["id"] for r in prev}
            print(f"Resuming: {len(done_ids)} already done")
        except Exception as e:
            print("could not resume:", e)

    torch.manual_seed(0)
    dtype = torch.bfloat16 if args.dtype == "bfloat16" else torch.float16
    model, processor = load_model(args.model_path, dtype)
    # Qwen3-VL vision encoder uses 16px patches, Qwen2/2.5-VL use 14px.
    patch_size = getattr(processor.image_processor, "patch_size", None) or 14

    for rec in tqdm([r for r in data if r["id"] not in done_ids], desc="eval"):
        messages, is_yesno = build_messages(rec, args.video_root, args.nframes,
                                            no_video=args.no_video)
        try:
            text = processor.apply_chat_template(messages, tokenize=False,
                                                 add_generation_prompt=True)
            # return_video_metadata is required so the processor keeps our
            # `nframes` sampling (do_sample_frames=False) and computes real
            # timestamps; without it Qwen3-VL silently re-samples to 4 frames.
            image_inputs, video_inputs, video_kwargs = process_vision_info(
                messages, return_video_kwargs=True, return_video_metadata=True,
                image_patch_size=patch_size)
            if video_inputs is not None:
                video_inputs, video_metadata = map(list, zip(*video_inputs))
            else:
                video_metadata = None
            inputs = processor(text=[text], images=image_inputs, videos=video_inputs,
                               video_metadata=video_metadata, do_resize=False,
                               padding=True, return_tensors="pt",
                               **video_kwargs).to(model.device)
            with torch.no_grad():
                # no do_sample override: Thinking models loop under greedy
                # decoding, so use the checkpoint's own generation defaults.
                gen = model.generate(**inputs, max_new_tokens=args.max_new_tokens)
            trimmed = gen[:, inputs.input_ids.shape[1]:]
            output = processor.batch_decode(trimmed, skip_special_tokens=True,
                                            clean_up_tokenization_spaces=False)[0]
        except Exception as e:
            print(f"\nerror on id={rec['id']}: {type(e).__name__}: {e}")
            output = "<answer>error</answer>"

        pred = parse_choice(output, is_yesno)
        gt = gt_choice(rec["answer"], is_yesno)
        rec_out = dict(rec)
        rec_out["num_videos"] = num_videos(rec)
        rec_out["output"] = output
        rec_out["think"] = extract_think(output)
        rec_out["prediction"] = pred
        rec_out["correct"] = (pred.strip().upper() == gt.strip().upper())
        results.append(rec_out)

        with open(args.output, "w") as f:
            json.dump({"results": results}, f, indent=2, ensure_ascii=False)

    summarize(results, args.output)


def summarize(results, output):
    from collections import defaultdict
    by_task = defaultdict(lambda: [0, 0])
    by_nv = defaultdict(lambda: [0, 0])
    correct = 0
    for r in results:
        c = 1 if r.get("correct") else 0
        correct += c
        by_task[r["task_type"]][0] += c
        by_task[r["task_type"]][1] += 1
        by_nv[r.get("num_videos", 0)][0] += c
        by_nv[r.get("num_videos", 0)][1] += 1
    overall = 100 * correct / len(results) if results else 0
    print(f"\nOverall: {correct}/{len(results)} = {overall:.1f}%")
    print("By num videos:")
    for k in sorted(by_nv):
        c, t = by_nv[k]
        print(f"  {k} video(s): {c}/{t} = {100*c/t:.1f}%")
    print("By task type:")
    for k in sorted(by_task):
        c, t = by_task[k]
        print(f"  {c}/{t}  {k}")
    # persist summary alongside results
    summary = {
        "overall_acc": overall,
        "by_num_videos": {str(k): {"correct": by_nv[k][0], "total": by_nv[k][1]} for k in by_nv},
        "by_task_type": {k: {"correct": by_task[k][0], "total": by_task[k][1]} for k in by_task},
    }
    full = json.load(open(output))
    full["summary"] = summary
    json.dump(full, open(output, "w"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
