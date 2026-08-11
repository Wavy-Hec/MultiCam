#!/usr/bin/env python3
"""Thinking-enabled multi-video eval for Qwen-family VLMs (e.g. Qwen3-VL-*-Thinking).

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
import functools
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

# Reasoning-off variant (the 08-04 meeting's "turn reasoning off" setting).
# There is no model-side switch for this on either backend — the visible trace
# is produced BY the prompt above, so removing reasoning means asking for the
# answer directly. The <answer> tags stay so one parser serves both modes.
QUESTION_TEMPLATE_DIRECT = (
    "{Question}\n"
    "Answer immediately with your final choice. Do not explain, do not reason "
    "step by step, and do not write anything before the answer. Give only your "
    "final answer between the <answer> and </answer> tags."
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


# Widest supported multiple-choice letter range and slot count. Records carry
# up to MAX_SLOTS video_i (or image_i) fields; option letters are always the
# per-record prefix of LETTERS_ALL — never the blanket range (a bare \b[A-M]\b
# would match prose words like "I"/"A" in the tag-missing fallback).
LETTERS_ALL = "ABCDEFGHIJKLM"
MAX_SLOTS = 13


def letters_for(options):
    """Option letters for one record's options list ("ABCD" for 4 options).
    Malformed single-string option rows fall back to the classic ABCD."""
    n = len(options or [])
    return LETTERS_ALL[:n] if 2 <= n <= len(LETTERS_ALL) else "ABCD"


# Explicit "the answer is X" style conclusions, used ONLY when the model never
# emitted an <answer> tag (e.g. a truncated trace). We take the LAST such match
# (closest to the model's conclusion). Scanning the whole trace for any bare
# A/B/C/D is wrong: it grabs prose like "a vehicle" / "options A to D", which
# fabricated a lucky 'A' on truncated runs and made 0/20 structural.
@functools.lru_cache(maxsize=None)
def _conclude_mc_re(letters):
    return re.compile(
        r"(?i)(?:final\s+answer|best\s+answer|correct\s+answer|the\s+answer|answer)\s*"
        r"(?:is|:|=|would\s+be)?\s*\(?([" + letters + r"])\b"
    )


_CONCLUDE_MC = _conclude_mc_re("ABCD")
_CONCLUDE_YN = re.compile(
    r"(?i)(?:final\s+answer|the\s+answer|answer)\s*(?:is|:|=)?\s*\(?(yes|no)\b"
)


# A model that refuses inside <answer> is abstaining, not choosing. Scoring it
# as a letter is the difference between "wrong" and "wrong AND attributed to an
# option it never picked" — and it lands almost entirely on per_stream, the arm
# whose aggregator is most likely to give up.
_REFUSAL = re.compile(
    r"(?i)^\W*(n/?a\b|none\s+of\s+the\s+(above|options|provided)|none\b|"
    r"cannot\s+be\s+determined|can(?:no|')t\s+(?:be\s+)?determin|unknown\b|"
    r"unanswerable\b|not\s+determinable|insufficient\b|unclear\b)")


def _body_to_letter(body, letters, options=None):
    """Map an <answer> body to a single option letter, or "" to abstain.

    The old rule was `re.search("(?i)\\b([ABCD])\\b", body)` — first match wins,
    case-insensitive. That reads the English article "a" as option A, so
    'None of the above... does not show a lady' scored as a confident A. It also
    took the first of several listed letters ('A\\nB\\nC' -> A) and stored
    non-letter prose as a prediction with abstained=False.
    """
    body = body.strip()
    # 1. a bare letter, with or without decoration: "A", "(A)", "A.", "A:"
    m = re.fullmatch(r"\W*([" + letters + r"])\W*", body, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 2. the body quotes an option verbatim -> that option's letter. Must come
    #    BEFORE the refusal check: "Cannot be determined" is a real option on
    #    CrossView temporal questions, not a refusal.
    if options:
        norm = re.sub(r"\W+", " ", body).strip().lower()
        # the body may repeat the option's own "A." prefix. Strip it from the
        # body as well as the option, or "a they approach the car" never matches
        # "they approach the car". Requires the delimiter, so an option that
        # simply begins with the word "A" is untouched.
        norm_lead = re.sub(r"^\s*[A-Za-z]\s*[.)]\s*", "", body)
        norm_lead = re.sub(r"\W+", " ", norm_lead).strip().lower()
        for i, opt in enumerate(options[:len(letters)]):
            otext = re.sub(r"^\s*[A-Za-z]\s*[.)]\s*", "", str(opt))
            otext = re.sub(r"\W+", " ", otext).strip().lower()
            if otext and any(n == otext or n.startswith(otext)
                             for n in (norm, norm_lead)):
                return letters[i].upper()
    # 3. an explicit refusal -> abstain
    if _REFUSAL.match(body):
        return ""
    # 4. a standalone option letter. Case-insensitive EXCEPT for lowercase "a"
    #    and "i", which are English words — reading those as options is what
    #    scored 'does not show a lady' as a confident A. Ambiguous if several.
    found = {m.group(1).upper() for m in re.finditer(r"\b([" + letters + r"])\b",
                                                     body, re.IGNORECASE)
             if not (m.group(1) in ("a", "i"))}
    if len(found) == 1:
        return found.pop()
    return ""


def _leading_letter_option(body, letters, options):
    """Map ``"A. <the option's own text>"`` to ``"A"``, else "".

    This is the dominant reasoning-off shape on InternVL3, which answers with the
    letter AND the option text and no tags at all. It is safe to trust at any
    length precisely because the text after the letter has to BE that option — a
    thinking trace that merely opens with "A." cannot match.
    """
    if not options:
        return ""
    m = re.match(r"\W*([" + letters + r"])\s*[.):]\s*(.+)", body,
                 re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    letter = m.group(1).upper()
    i = letters.upper().index(letter)
    if i >= len(options):
        return ""
    otext = re.sub(r"^\s*[A-Za-z]\s*[.)]\s*", "", str(options[i]))
    otext = re.sub(r"\W+", " ", otext).strip().lower()
    rest = re.sub(r"\W+", " ", m.group(2)).strip().lower()
    if otext and (rest == otext or rest.startswith(otext)):
        return letter
    return ""


def parse_choice(text, is_yesno, letters="ABCD", options=None):
    """Final answer = <answer>..</answer> if present. If the tag is missing
    (e.g. a truncated trace), fall back ONLY to an explicit "the answer is X"
    conclusion (last match); otherwise abstain (return "") rather than grabbing
    an incidental letter from the reasoning prose."""
    ans = extract_answer(text)
    if is_yesno:
        if ans:
            m = re.search(r"(?i)\b(yes|no)\b", ans)
            return m.group(1).capitalize() if m else ans.strip()
        ms = list(_CONCLUDE_YN.finditer(text))
        return ms[-1].group(1).capitalize() if ms else ""
    if ans:
        return _body_to_letter(ans, letters, options)
    ms = list(_conclude_mc_re(letters).finditer(text))
    if ms:
        return ms[-1].group(1).upper()
    # reasoning-off mode: the model may answer with no tags at all, either as a
    # bare "B" or as the full "B. <option text>".
    stripped = text.strip()
    if not stripped:
        return ""
    # the letter-plus-its-own-option-text shape is unambiguous however long it
    # runs, and it is 98% of what the length cap below used to throw away.
    lead = _leading_letter_option(stripped, letters, options)
    if lead:
        return lead
    # anything else is only trusted on a SHORT response — running _body_to_letter
    # over a long thinking trace would pick up incidental letters, which is
    # exactly the failure the tag-missing fallback exists to avoid.
    if len(stripped) <= 40:
        return _body_to_letter(stripped, letters, options)
    return ""


def gt_choice(answer, is_yesno, letters="ABCD"):
    a = answer.strip()
    if is_yesno:
        return a.capitalize()
    m = re.search(r"(?i)([" + letters + r"])", a)
    return m.group(1).upper() if m else a.upper()


def num_videos(rec):
    return sum(1 for i in range(1, MAX_SLOTS + 1) if rec.get(f"video_{i}"))


def video_paths(rec, video_root):
    out = []
    for i in range(1, MAX_SLOTS + 1):
        v = rec.get(f"video_{i}")
        if v:
            out.append(os.path.normpath(os.path.join(video_root, v)))
    return out


def num_images(rec):
    return sum(1 for i in range(1, MAX_SLOTS + 1) if rec.get(f"image_{i}"))


def image_paths(rec, image_root):
    """Ordered view-image paths of a still-image record (image_1..image_N).
    Order is semantically load-bearing: question text references "View k"."""
    out = []
    for i in range(1, MAX_SLOTS + 1):
        v = rec.get(f"image_{i}")
        if v:
            out.append(os.path.normpath(os.path.join(image_root, v)))
    return out


# Prompt v2: enumerate every legal letter instead of eliding past six, and say
# outright that the options are exhaustive. Both are answer-hygiene fixes, but
# they change generation, so they are OFF by default — turning them on mid-
# campaign would put a prompt difference across the dataset comparison and would
# invalidate the completed legs that later runs are meant to be compared with.
# Set STRICT_ANSWER_PROMPT=1 to run a clean v2 campaign.
STRICT_ANSWER_PROMPT = os.environ.get("STRICT_ANSWER_PROMPT", "0") == "1"

_NO_REFUSAL = (" The options are exhaustive: choose the single best one even if "
               "you are uncertain. Do not answer N/A, none of the above, or "
               "cannot be determined unless that is itself one of the options.")


def _letters_phrase(letters):
    """Human phrasing of the letter range: "A, B, C, or D" (byte-identical to
    the original 4-option prompt), "A or B", "A, B, or C", and an elided
    "A, B, ..., or J" once enumerating would bloat the prompt.

    The elision is a measured defect: on the 106 MVU-Eval records with 7-11
    options the model is never told that F..I are legal, and abstains 6-21% of
    the time there against 2-4% on 2-6 options. STRICT_ANSWER_PROMPT enumerates
    them all."""
    if len(letters) == 2:
        return f"{letters[0]} or {letters[1]}"
    if len(letters) <= 6 or STRICT_ANSWER_PROMPT:
        return ", ".join(letters[:-1]) + f", or {letters[-1]}"
    return f"{letters[0]}, {letters[1]}, ..., or {letters[-1]}"


def build_messages(rec, video_root, nframes, no_video=False, reasoning=True):
    options = rec["options"]
    is_yesno = all(o.strip().strip(".").lower() in ("yes", "no") for o in options)
    # still-image records (image_1..N view images) share the text scaffold but
    # speak of "views" and attach image items instead of video clips
    is_image = num_images(rec) > 0
    unit = "views" if is_image else "videos"
    if is_yesno:
        option_prompt = ("Select the best answer to the following yes-no question based on "
                         f"all the listed {unit}.")
        post = "Provide only the single word (Yes or No) within the <answer> </answer> tags."
    else:
        letters = letters_for(options)
        option_prompt = ("Select the best answer to the following multiple-choice question "
                         f"based on all the listed {unit}.")
        post = (f"Provide only the single option letter ({_letters_phrase(letters)}) "
                "within the <answer> </answer> tags.")
        if STRICT_ANSWER_PROMPT:
            post += _NO_REFUSAL

    question = rec["question"] + "\n" + "\n".join(options)
    template = QUESTION_TEMPLATE if reasoning else QUESTION_TEMPLATE_DIRECT
    full_prompt = option_prompt + "\n" + template.format(Question=question) + "\n" + post

    # interleave a text marker before each clip/view; with no_video (blind
    # baseline) keep the prompt text identical but attach zero visual input
    content = []
    if not no_video:
        if is_image:
            for k, ip in enumerate(image_paths(rec, video_root), 1):
                content.append({"type": "text", "text": f"View {k}:"})
                content.append({"type": "image", "image": ip})
        else:
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
    ap.add_argument("--video_root", required=True)
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
        total_tokens = video_tokens = text_tokens = None
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
            # text-vs-video token accounting for the token benchmark: count the
            # <|video_pad|> placeholders the processor expanded (one per vision
            # token); the remainder is text/scaffold. video_tokens==0 when --no_video.
            total_tokens = int(inputs.input_ids.shape[1])
            vid_id = processor.tokenizer.convert_tokens_to_ids("<|video_pad|>")
            video_tokens = int((inputs.input_ids[0] == vid_id).sum())
            text_tokens = total_tokens - video_tokens
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
        rec_out["num_frames"] = 0 if args.no_video else args.nframes * rec_out["num_videos"]
        rec_out["total_input_tokens"] = total_tokens
        rec_out["video_tokens"] = video_tokens
        rec_out["text_tokens"] = text_tokens
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
