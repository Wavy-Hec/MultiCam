#!/usr/bin/env python3
"""Task B: sanity check of the qwen3vl_blind (no-video) CVBench run.

1. Re-renders the EXACT blind input (chat-template string) for the same 5
   sample questions as inspect_inputs.py, using the real build_messages from
   eval_thinking.py with no_video=True, and asserts zero vision tokens.
2. Scans ALL 45 rendered blind prompts for leakage (filenames, ytid stems,
   _seg markers, fps/frame counts, paths) and proves every "video" mention is
   either intrinsic question/options wording or the fixed scaffold sentence.
3. Recounts blind accuracy three ways: stored `correct` flags, independent
   re-derivation via the eval's own parse_choice/gt_choice over the stored
   outputs, and the slurm stdout summary.

Read-only; outputs analysis/inspect_blind_data.json + markdown-ready stdout.

Run (CPU, conda env `cvbench`, offline):
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
      conda run -n cvbench python3 analysis/inspect_blind.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SUBSET = os.path.join(HERE, "subset.json")
NOVIDEO_JSON = os.path.join(REPO, "Video-R1", "src", "r1-v", "eval_results",
                            "eval_subset_qwen3vl_novideo.json")
WITHVIDEO_JSON = os.path.join(REPO, "Video-R1", "src", "r1-v", "eval_results",
                              "eval_subset_qwen3vl.json")
SLURM_OUT = os.path.join(HERE, "logs", "56689.cvbench_novideo.out")
SUBSET_VIDEOS = os.path.join(HERE, "subset_videos.txt")
QWEN_MODEL = "Qwen/Qwen3-VL-8B-Thinking"
PICK_IDS = [0, 4, 3, 17, 19]  # same deterministic picks as inspect_inputs.py

sys.path.insert(0, os.path.join(REPO, "Video-R1", "src"))
from eval_thinking import build_messages, gt_choice, parse_choice  # noqa: E402


def vision_token_check(processor, text):
    """Assert the rendered blind prompt contains no vision-related tokens,
    using the tokenizer's own added-token inventory (not a hardcoded list)."""
    tok = processor.tokenizer
    sus = {t: i for t, i in tok.get_added_vocab().items()
           if re.search(r"vision|image|video|img|box|quad", t, re.I)}
    ids = set(tok(text, add_special_tokens=False)["input_ids"])
    hits = {t: i for t, i in sus.items() if i in ids}
    assert not hits, hits
    for t in sus:
        assert t not in text, t
    return sorted(sus)


def render_blind(rec, processor):
    messages, is_yesno = build_messages(rec, "<unused>", 8, no_video=True)
    content = messages[0]["content"]
    assert len(content) == 1 and content[0]["type"] == "text", content
    text = processor.apply_chat_template(messages, tokenize=False,
                                         add_generation_prompt=True)
    return text, content[0]["text"], is_yesno


def scaffold_check(rec, body):
    """The blind text body must be EXACTLY scaffold + question + options +
    scaffold -- so any video mention is either intrinsic to the question or
    the fixed 'based on all the listed videos' scaffold sentence."""
    from eval_thinking import QUESTION_TEMPLATE
    options = rec["options"]
    is_yesno = all(o.strip().strip(".").lower() in ("yes", "no") for o in options)
    if is_yesno:
        op = ("Select the best answer to the following yes-no question based on "
              "all the listed videos.")
        post = "Provide only the single word (Yes or No) within the <answer> </answer> tags."
    else:
        op = ("Select the best answer to the following multiple-choice question "
              "based on all the listed videos.")
        post = "Provide only the single option letter (A, B, C, or D) within the <answer> </answer> tags."
    q = rec["question"] + "\n" + "\n".join(options)
    expect = op + "\n" + QUESTION_TEMPLATE.format(Question=q) + "\n" + post
    assert body == expect, rec["id"]


def leakage_scan(prompts_by_id, recs_by_id):
    """Search every rendered blind prompt for content-revealing metadata."""
    stems = set()
    for line in open(SUBSET_VIDEOS):
        base = os.path.basename(line.strip())
        if base:
            stems.add(re.sub(r"(_seg\d+)?\.mp4$", "", base))
    patterns = {
        ".mp4 filename": re.compile(r"\.mp4"),
        "_seg marker": re.compile(r"_seg\d"),
        "video path": re.compile(r"CVBench/|Evaluation/|r1-v/"),
        "fps/frame-count": re.compile(r"\bfps\b|\bnframes\b|\b\d+\s*frames\b", re.I),
        "frame marker": re.compile(r"\bFrame\d|This is video|Video \d End"),
        "timestamp marker": re.compile(r"<[\d.]+ seconds>"),
    }
    findings = []
    for qid, text in prompts_by_id.items():
        for name, pat in patterns.items():
            for m in pat.finditer(text):
                findings.append((qid, name, text[max(0, m.start() - 40):m.end() + 40]))
        for stem in stems:
            if stem in text:
                findings.append((qid, "ytid stem", stem))
        # every "video"-ish mention must come from question/options or scaffold
        intrinsic = recs_by_id[qid]["question"] + "\n".join(recs_by_id[qid]["options"])
        for m in re.finditer(r"[Vv]ideos?\b[^\n]{0,12}", text):
            frag = m.group(0)
            if frag not in intrinsic and "listed videos" not in frag and "all the listed" not in text[max(0, m.start() - 30):m.start()]:
                ctx = text[max(0, m.start() - 60):m.end() + 20]
                if "based on all the listed videos" not in ctx:
                    findings.append((qid, "unexplained video mention", ctx))
    return findings


def recount(path):
    data = json.load(open(path))
    results = data["results"]
    stored = sum(1 for r in results if r.get("correct"))
    rederived, mismatch, errors = 0, [], 0
    for r in results:
        is_yesno = all(o.strip().strip(".").lower() in ("yes", "no") for o in r["options"])
        pred = parse_choice(r["output"], is_yesno)
        gt = gt_choice(r["answer"], is_yesno)
        ok = pred.strip().upper() == gt.strip().upper()
        rederived += ok
        if ok != bool(r.get("correct")) or pred != r.get("prediction"):
            mismatch.append(r["id"])
        if r["output"] == "<answer>error</answer>":
            errors += 1
    return {"n": len(results), "stored_correct": stored, "rederived_correct": rederived,
            "flag_mismatches": mismatch, "error_sentinels": errors,
            "summary_acc": data.get("summary", {}).get("overall_acc")}


def main():
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(QWEN_MODEL, trust_remote_code=True)

    recs_by_id = {r["id"]: r for r in json.load(open(SUBSET))}
    assert len(recs_by_id) == 45

    # render ALL 45 blind prompts; structural + vision-token + scaffold checks
    prompts, sus_tokens = {}, None
    for qid, rec in recs_by_id.items():
        text, body, _ = render_blind(rec, processor)
        scaffold_check(rec, body)
        sus_tokens = vision_token_check(processor, text)
        prompts[qid] = text

    print("## Blind-run sanity\n")
    print(f"- rendered all 45 blind prompts; each content list is a single text item "
          f"(build_messages no_video branch, eval_thinking.py:117-122)")
    print(f"- vision-token sweep: none of the {len(sus_tokens)} vision/image/video-related "
          f"added tokens appear in any rendered prompt")

    findings = leakage_scan(prompts, recs_by_id)
    print(f"- leakage scan over all 45 prompts: {len(findings)} findings")
    for f in findings:
        print(f"  - id {f[0]} [{f[1]}]: …{f[2]}…")

    blind = recount(NOVIDEO_JSON)
    withv = recount(WITHVIDEO_JSON)
    slurm_line = ""
    if os.path.exists(SLURM_OUT):
        for line in open(SLURM_OUT):
            if line.startswith("Overall:"):
                slurm_line = line.strip()
    print(f"\n## Recount\n")
    print(f"- blind: stored {blind['stored_correct']}/{blind['n']}, re-derived "
          f"{blind['rederived_correct']}/{blind['n']}, summary {blind['summary_acc']}, "
          f"slurm '{slurm_line}', flag mismatches {blind['flag_mismatches']}, "
          f"error sentinels {blind['error_sentinels']}")
    print(f"- with-video: stored {withv['stored_correct']}/{withv['n']}, re-derived "
          f"{withv['rederived_correct']}/{withv['n']}, summary {withv['summary_acc']}, "
          f"error sentinels {withv['error_sentinels']}")
    assert blind["stored_correct"] == blind["rederived_correct"] == 18
    assert blind["n"] == 45 and not blind["flag_mismatches"]

    data = {
        "sample_prompts": {qid: prompts[qid] for qid in PICK_IDS},
        "vision_tokens_checked": sus_tokens,
        "leakage_findings": findings,
        "recount_blind": blind,
        "recount_with_video": withv,
        "slurm_line": slurm_line,
    }
    out = os.path.join(HERE, "inspect_blind_data.json")
    json.dump(data, open(out, "w"), indent=1, ensure_ascii=False)
    print(f"\nwrote {out}")
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
