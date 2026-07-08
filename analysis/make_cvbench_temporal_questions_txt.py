"""Render analysis/cvbench_temporal_subset.json to a human-readable .txt listing.

Each question gets its id, task type, camera count, temporal level, the question
text, options, answer, AND the video files it references (video_1..video_N), so
the listing is self-contained — you can tell which clips each question maps to
without opening the JSON. Paths are relative to the CVBench video root
(Video-R1/src/r1-v/Evaluation/CVBench).

Run from repo root:  python analysis/make_cvbench_temporal_questions_txt.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SUBSET = os.path.join(HERE, "cvbench_temporal_subset.json")
OUT = os.path.join(HERE, "cvbench_temporal_questions.txt")
VIDEO_ROOT = "Video-R1/src/r1-v/Evaluation/CVBench"


def videos_for(rec):
    return [rec[f"video_{i}"] for i in range(1, 5) if f"video_{i}" in rec]


def main():
    recs = json.load(open(SUBSET))
    lines = [
        f"CVBench temporal-logic subset — {len(recs)} questions used for analysis",
        "source: analysis/cvbench_temporal_subset.json",
        f"video paths are relative to {VIDEO_ROOT}/",
        "",
    ]
    for i, r in enumerate(recs, 1):
        vids = videos_for(r)
        lines.append(
            f"[{i:>3}] {r['id']:<8} | {r['task_type']} | "
            f"{r['orig_num_cameras']}cam | tlvl{r['temporal_level']}"
        )
        lines.append(f"      Q: {r['question']}")
        lines.append(f"      Options: {r['options']}")
        lines.append(f"      Answer: {r['answer']}")
        lines.append("      Videos:")
        for n, v in enumerate(vids, 1):
            lines.append(f"        video_{n}: {v}")
        lines.append("")

    with open(OUT, "w") as f:
        f.write("\n".join(lines))
    print(f"wrote {len(recs)} questions -> {OUT}")


if __name__ == "__main__":
    main()
