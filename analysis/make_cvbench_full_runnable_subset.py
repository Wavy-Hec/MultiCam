"""Build the FULL CVBench runnable subset for the bench/ harness.

Takes the 1000-question CVBench eval set (Video-R1/src/r1-v/Evaluation/CVBench.json),
keeps every question whose referenced videos ALL exist on disk, normalizes them
into the same record shape the harness expects (mirrors make_cvbench_temporal_subset.py,
minus the temporal-level filter), and writes analysis/cvbench_full_runnable_subset.json.

Questions whose videos are not (yet) downloaded are skipped and logged; run
analysis/download_videos.py first to fetch them, then re-run this to grow the set
toward the full 1000.

video_root for these records is Video-R1/src/r1-v/Evaluation/CVBench (pass it to
run_bench via --video-root).

Run from repo root:  python analysis/make_cvbench_full_runnable_subset.py
"""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CVBENCH = os.path.join(REPO, "Video-R1", "src", "r1-v", "Evaluation", "CVBench.json")
VIDEO_ROOT = os.path.join(REPO, "Video-R1", "src", "r1-v", "Evaluation", "CVBench")
OUT = os.path.join(HERE, "cvbench_full_runnable_subset.json")
BLOCKED_OUT = os.path.join(HERE, "cvbench_full_blocked.txt")


def clean_video(v):
    """Harness video_paths() uses `if v:` — the literal string 'None' is truthy and
    would try to open a file named None. Map None/''/'None'/'null' -> falsy (None)."""
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "None", "null") else s


def main():
    cv = json.load(open(CVBENCH))
    out, blocked = [], []
    for r in cv:
        tid = str(r["id"])
        vids = [clean_video(r.get(f"video_{i}")) for i in range(1, 5)]
        vids = [v for v in vids if v]
        if not vids:
            blocked.append((tid, "no-video"))
            continue
        missing = [v for v in vids if not os.path.exists(os.path.join(VIDEO_ROOT, v))]
        if missing:
            blocked.append((tid, missing[0]))
            continue
        rec = {
            "id": f"cvb-{tid}",
            "task_type": r["task_type"],
            "question": r["question"],
            "options": r["options"],
            "answer": r["answer"],
            "source": "cvbench",
            "question_type": "cvbench_full",
            "orig_num_cameras": len(vids),     # CVBench: # of videos in the question (1-4)
            "cap_answer_safe": True,
            "orig_id": tid,
        }
        for i, v in enumerate(vids, 1):
            rec[f"video_{i}"] = v
        out.append(rec)

    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    with open(BLOCKED_OUT, "w") as fh:
        fh.write("\n".join(f"{tid}\t{why}" for tid, why in blocked))

    print(f"wrote {len(out)} runnable questions -> {OUT}")
    print(f"  blocked (videos not on disk): {len(blocked)} -> {BLOCKED_OUT}")
    print("  video-count:", dict(sorted(collections.Counter(x["orig_num_cameras"] for x in out).items())))
    print(f"  video root: {VIDEO_ROOT}")


if __name__ == "__main__":
    main()
