#!/usr/bin/env python3
"""Build one Discord-sendable JSON for the team: every CVBench question with its
temporal-complexity label, a neuro-symbolic (NeuS-QA-style) temporal-logic view,
and relevance flags for the lab's three projects.

Reuses the scoring in analysis/temporal_complexity.py verbatim (imported, not
re-implemented) so the labels here are exactly the ones being verified.

Output: analysis/cvbench_temporal_logic_team.json
  meta      - source, metric description, headline counts, project mapping,
              NeuS-QA citation, verification instructions
  questions - all 1000 records, sorted L2 -> L1 -> L0 (temporal evidence first)

Run (CPU): python3 analysis/make_team_json.py
"""
import datetime
import json
import os

import temporal_complexity as tc

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cvbench_temporal_logic_team.json")

SIMULTANEOUS = {"while", "simultaneous", "simultaneously"}

LTL_TEMPLATES = {
    "event-sequencing":
        "F(e1 & F(e2 & F(e3 ...))) -- recover the true total order of the N "
        "depicted events (answer options are permutations)",
    "cross-stream-precedence":
        "F(e_vi) & F(e_vj) & (e_vi precedes e_vj) -- precedence across streams; "
        "CVBench provides NO cross-stream clock, so order must be inferred from "
        "content alone",
    "simultaneity":
        "F(e1 & e2) -- two events must hold at the same time",
    "multi-event-relation":
        "multiple temporal references must be jointly satisfied (coarse bucket; "
        "see temporal.keywords for the triggers)",
    "bounded-eventually":
        "F_[window](e) -- an event occurs within a referenced temporal window "
        "(e.g. 'during the closing moments')",
}


def tl_pattern(f):
    if f["level"] == 0:
        return None
    if f["has_permutation_options"]:
        return "event-sequencing"
    if f["asks_cross_video_order"]:
        return "cross-stream-precedence"
    if any(k in SIMULTANEOUS for k in f["temporal_kw"]):
        return "simultaneity"
    if f["level"] == 2:
        return "multi-event-relation"
    return "bounded-eventually"


def main():
    full = json.load(open(tc.FULL_SRC))
    scored = tc.score_all(full)
    subset_ids = {r["id"] for r in json.load(open(tc.SUBSET_SRC))}
    results = {m: {r["id"]: bool(r.get("correct")) for r in tc.load_results(p)}
               for m, p in tc.MODELS.items()}

    questions = []
    for r in sorted(full, key=lambda r: (-scored[r["id"]]["level"], r["id"])):
        f = scored[r["id"]]
        videos = [r[k] for k in ("video_1", "video_2", "video_3", "video_4") if r.get(k)]
        pat = tl_pattern(f)
        rec = {
            "id": r["id"],
            "question": r["question"],
            "options": r["options"],
            "answer": r["answer"],
            "task_type": r["task_type"],
            "n_videos": len(videos),
            "videos": videos,
            "temporal": {
                "level": f["level"],
                "level_name": tc.LEVEL_NAMES[f["level"]],
                "keywords": f["temporal_kw"],
                "has_permutation_options": f["has_permutation_options"],
                "asks_cross_video_order": f["asks_cross_video_order"],
            },
            "neuro_symbolic": {
                "neusqa_amenable": f["level"] >= 1,
                "tl_pattern": pat,
                "ltl_template": LTL_TEMPLATES.get(pat),
            },
            "project_relevance": {
                "p1_temporal_logic": f["level"] >= 1,
                "p3_multistream": len(videos) >= 2,
                "p1_p3_overlap": f["level"] >= 1 and len(videos) >= 2,
            },
            "in_eval_subset": r["id"] in subset_ids,
        }
        if r["id"] in subset_ids:
            rec["eval_correct"] = {m: results[m].get(r["id"]) for m in results}
        questions.append(rec)

    cnt = tc.counts(scored)
    n_temporal_task = sum(1 for f in scored.values() if f["is_temporal_task"])
    meta = {
        "source": "CVBench (HF Dongyh35/CVBench), 1000 cross-video multiple-choice "
                  "questions over 1-4 asynchronous videos, 15 task types",
        "generated": datetime.date.today().isoformat(),
        "generated_by": "analysis/make_team_json.py (labels from "
                        "analysis/temporal_complexity.py, rule-based over question "
                        "text, no LLM labeling)",
        "metric": "L0 non-temporal; L1 temporal reference (one event/moment is "
                  "referenced); L2 temporally complex (multiple events must be "
                  "RELATED in time: permutation answer options, explicit cross-video "
                  "ordering, or >=2 temporal keywords). Polysemous words ('when', "
                  "'step') deliberately excluded after spot-checking.",
        "headline_counts": {
            "total": len(full),
            "L0_non_temporal": cnt[0],
            "L1_temporal_reference": cnt[1],
            "L2_temporally_complex": cnt[2],
            "temporal_total_L1_plus_L2": cnt[1] + cnt[2],
            "in_dedicated_temporal_task_type": n_temporal_task,
            "temporal_hidden_in_other_task_types": cnt[1] + cnt[2] - n_temporal_task,
        },
        "project_mapping": {
            "p1_temporal_logic": "level >= 1: question encodes temporal structure "
                                 "translatable to a temporal-logic spec over event "
                                 "propositions (Project 1: neuro-symbolic temporal "
                                 "logic for video understanding)",
            "p3_multistream": "n_videos >= 2: answering requires binding entities/"
                              "events across distributed, unsynchronized streams "
                              "(Project 3: multi-agent neuro-symbolic video search)",
            "p1_p3_overlap": "temporal AND multi-stream -- cross-stream temporal "
                             "queries, the Project 1 x Project 3 alignment target",
        },
        "neusqa_reference": "NeuS-QA: Grounding Long-Form Video Understanding in "
                            "Temporal Logic and Neuro-Symbolic Reasoning, AAAI 2026, "
                            "https://arxiv.org/abs/2509.18041 -- translates NL "
                            "questions to LTL and model-checks a video automaton; "
                            "'neusqa_amenable' marks questions translatable that way",
        "verification": "Labels are rule-based and coarse -- that is what to verify. "
                        "Re-run: python3 analysis/temporal_complexity.py ; random "
                        "spot-check: python3 analysis/temporal_complexity.py --spot 15",
        "eval_context": "in_eval_subset marks the 45-question Stage-A subset; "
                        "eval_correct gives per-model correctness for "
                        "Qwen3-VL-8B-Thinking (qwen3vl), InternVL3-8B (internvl3) "
                        "and a no-video blind baseline (qwen3vl_blind)",
    }

    json.dump({"meta": meta, "questions": questions}, open(OUT, "w"), indent=1)
    by_pat = {}
    for q in questions:
        p = q["neuro_symbolic"]["tl_pattern"]
        if p:
            by_pat[p] = by_pat.get(p, 0) + 1
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1e6:.2f} MB, {len(questions)} questions)")
    print("levels:", {tc.LEVEL_NAMES[k]: v for k, v in cnt.items()})
    print("tl_patterns:", by_pat)
    print("p1_p3_overlap:", sum(q["project_relevance"]["p1_p3_overlap"] for q in questions))


if __name__ == "__main__":
    main()
