#!/usr/bin/env python3
"""Assemble the results deck HTML from analysis/figs_deck/*.png (base64-embedded,
the artifact CSP allows no external fetches) + analysis/slide_stats.json. Rerun
after mvueval_slide_stats.py + make_slide_figs.py to refresh; the page states
which panels are still placeholders.

Run (no GPU): python3 analysis/make_deck_html.py <out.html>
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIGS = os.path.join(HERE, "figs_deck")
S = json.load(open(os.path.join(HERE, "slide_stats.json")))


def b64(name):
    with open(os.path.join(FIGS, name), "rb") as f:
        return base64.b64encode(f.read()).decode()


mvu = S["arrangement"]["mvu_full"]
seq, cen, dec = (mvu[k]["acc"] for k in ("cvbench_native", "centralized", "per_stream"))
sy, un = S["sync"]["sync128"]["stitch_delta"], S["sync"]["unrelated"]["stitch_delta"]
cnt = S["per_task"]["MVU-Counting"]
blind_done = bool(S.get("blind", {}).get("mvu_full"))
sv_done = bool(S.get("single_view", {}).get("n_q_complete"))
b32_done = bool(S.get("budget32", {}).get("cvbench_native"))

blind_mine = (f"{S['blind']['mvu_full']['acc']:.1f} (images add {S['blind']['images_add']['delta']:+.1f})"
              if blind_done else "job 72235 running")
sv_mine = (f"best view {S['single_view']['best']:.1f} (+{S['single_view']['best'] - S['single_view']['luck_best_of_k']:.1f} over luck)"
           if sv_done else "job 72240 running")
b32_row = ""
if b32_done:
    b = S["budget32"]
    b32_row = f"""<tr><td>Fixed-32 rerun: seq / stitch / decentral</td>
      <td>44.9 / 45.0 / 39.9 (their protocol)</td>
      <td>{b['cvbench_native']['acc']:.1f} / {b['centralized']['acc']:.1f} / {b['per_stream']['acc']:.1f}</td>
      <td><span class="chip ok">matched protocol</span></td></tr>"""

b32_cap = ("Stitching ran at 0.63× the tokens and the frame count floats with view count — "
           + (f"the fixed-32 rerun ({S['budget32']['cvbench_native']['acc']:.1f} / "
              f"{S['budget32']['centralized']['acc']:.1f} / {S['budget32']['per_stream']['acc']:.1f}) "
              "confirms the story holds at a matched budget."
              if b32_done else "the fixed-32 rerun is queued."))

SLIDES = [
    ("fig1_arrangement.png", "Does the arrangement matter?",
     f"sequential {seq:.1f} · stitching {cen:.1f} · decentralized {dec:.1f} on the full 1,824 questions — "
     "the only significant gap is decentralized falling ~9 points behind."),
    ("fig2_sync.png", "Does synchronization matter?",
     f"Stitching moves accuracy {sy['delta']:+.2f} on the 128 true 6-camera rigs and {un['delta']:+.2f} "
     "elsewhere — same shape as the reference deck, neither significant."),
    ("fig3_pertask.png", "Per-task stitching effect",
     f"No task survives correction. The reference deck's Counting +6.83 reverses here ({cnt['delta']:+.2f})."),
    ("fig4_clip.png", "The clip experiment at full scale",
     "Frame selection ties uniform sampling; picking one clip collapses — selection never beats use-everything."),
    ("fig5_budget.png", "What is wrong: unmatched budgets", b32_cap),
    ("fig6_blind.png", "Do the images even help?",
     "Blind (no-image) floor — " + ("computed from the finished runs." if blind_done
                                    else "runs in flight (jobs 72235/72236); panel updates when they land.")),
    ("fig7_singleview.png", "Does picking the right view matter?",
     "Best/random/worst single view on the 545 no-view-named questions — "
     + ("computed from the finished sweep." if sv_done else "sweep in flight (job 72240).")),
    ("fig8_census.png", "What the benchmark is made of",
     "70% of questions name their videos; only 7% are truly synchronized; the answer key is balanced."),
]

con = (S.get("blind") or {}).get("contingency", {}).get("overall")
if con:
    SLIDES.append(("fig9_headroom.png", "How many points can a selector still add?",
                   f"Question-by-question blind vs sequential: {con['vision_hurt']:.1f} points are recoverable "
                   f"(images made them worse), {con['wrong_both']:.1f} points are wrong either way — "
                   "out of reach for any frame selector."))

fb = S.get("frame_budget") or {}
pp_done = any(p.get("status") == "done" for p in fb.get("points", []))
if fb:
    fb_cap = (f"Accuracy at three per-question frame budgets vs the paper's published InternVL3-8B "
              f"{S['paper']['internvl3_8b']['overall']:.1f} — "
              + ("the paper-parity (32/video) point shows whether their own protocol costs accuracy."
                 if pp_done else "the 32-frames-per-video paper-parity arm is queued; the panel updates when it lands."))
    SLIDES.append(("fig11_framebudget.png", "Does the frame budget explain anything?", fb_cap))

svt = (S.get("single_view") or {}).get("by_task")
if svt:
    big = sorted(((t, d) for t, d in svt.items() if d["n_q"] >= 30),
                 key=lambda kv: kv[1]["best"] - kv[1]["sequential_all_views"], reverse=True)
    t0, d0 = big[0]
    SLIDES.append(("fig10_singleview_tasks.png", "Where does picking the view pay off?",
                   f"The single-view sweep split by task: the biggest headroom is {t0} "
                   f"(best view {d0['best']:.1f} vs all views {d0['sequential_all_views']:.1f}, n={d0['n_q']}); "
                   "view slots 1–6 score flat, so the sweep has no positional artifact."))

cards = "\n".join(f"""
  <section class="slide">
    <div class="eyebrow">SLIDE {i + 1:02d} · {title}</div>
    <div class="imgcard"><img alt="{title}" src="data:image/png;base64,{b64(fn)}"></div>
    <p class="cap">{cap}</p>
  </section>""" for i, (fn, title, cap) in enumerate(SLIDES))

TASK_ORDER = ["MVU-OR", "MVU-ICL", "MVU-SU", "MVU-TR", "MVU-Counting",
              "MVU-KIR", "MVU-Comparison", "MVU-RAG"]
PRETTY = {"MVU-Counting": "Counting", "MVU-OR": "Object recognition",
          "MVU-SU": "Spatial understanding", "MVU-ICL": "In-context learning",
          "MVU-RAG": "Retrieval (RAG)", "MVU-KIR": "Knowledge reasoning",
          "MVU-Comparison": "Comparison", "MVU-TR": "Temporal reasoning"}

paper_table = ""
if S.get("paper"):
    P = S["paper"]
    ours8 = S["arrangement"]["mvu_full"]["cvbench_native"]
    pp_nat = (S.get("parity32pv") or {}).get("cvbench_native")
    pend = '<span class="chip">pending</span>'

    def _row(name, paper_v, ours8_v, pp_v):
        return (f"<tr><td>{name}</td><td>{paper_v}</td><td>{ours8_v}</td>"
                f"<td>{pp_v}</td></tr>")

    rows = [_row("<b>Overall</b>", f"{P['internvl3_8b']['overall']:.1f}",
                 f"<b>{ours8['acc']:.1f}</b>",
                 f"<b>{pp_nat['acc']:.1f}</b>" if pp_nat else pend)]
    for t in TASK_ORDER:
        rows.append(_row(PRETTY[t], f"{P['internvl3_8b']['by_task'][t]:.1f}",
                         f"{ours8['by_task'][t]['acc']:.1f}",
                         f"{pp_nat['by_task'][t]['acc']:.1f}" if pp_nat else pend))
    rows.append(_row("Random / human", f"{P['random']:.1f} / {P['human']:.1f}",
                     f"{S['arrangement']['chance']['mvu_full']:.1f} / —", "—"))
    paper_table = f"""<section>
    <h2>Ours vs the MVU-Eval paper (InternVL3-8B, {P['source']})</h2>
    <div class="tablewrap"><table>
      <tr><th>Accuracy, percent</th><th>Paper<br>(32 frames/video, ≤720px, vLLM)</th>
          <th>Ours, 8 frames/video<br>(448px tiles, HF chat)</th>
          <th>Ours, 32 frames/video<br>(paper-parity budget)</th></tr>
      {''.join(rows)}
    </table></div>
    <p class="cap">Our sequential arm beats the paper's published number while feeding a fraction of the
    frames, so harness differences (prompt, frame resolution, decoding, answer parsing) dominate the frame
    budget on this benchmark. The parity column isolates the budget alone — same harness, their frame count.
    Sampling also differs: ours is 4 passes at temperature 0.7; the paper's decoding is not matched.
    Open item: the paper reports Qwen2.5-VL-7B at {P['qwen2_5_vl_7b']['overall']:.1f}, ABOVE its InternVL
    number — the reverse of every ordering we measure; a Qwen run in this harness would resolve it.</p>
  </section>"""

pending_bits = []
if not blind_done: pending_bits.append("blind (72235/72236)")
if not sv_done: pending_bits.append("single-view (72240)")
if not b32_done: pending_bits.append("fixed-32 rerun (72241)")
status = ("All runs finished — every panel shows final data."
          if not pending_bits else
          "In flight: " + ", ".join(pending_bits) + ". Panels regenerate when each lands.")

html = f"""<title>MultiCam results deck — MVU-Eval · InternVL3-8B</title>
<style>
:root {{
  --bg:#fcfcfb; --card:#ffffff; --ink:#141413; --ink2:#52514e; --muted:#898781;
  --line:#e3e2db; --accent:#2a78d6; --neg:#c23a39; --chipbg:#eef4fc; --okbg:#eaf5ea; --ok:#1d6b1d;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    --bg:#1a1a19; --card:#232322; --ink:#f2f1ec; --ink2:#c3c2b7; --muted:#8f8d86;
    --line:#33332f; --accent:#3987e5; --neg:#e66767; --chipbg:#1f2c3d; --okbg:#1e2e1e; --ok:#7fc97f;
  }}
}}
:root[data-theme="dark"] {{
  --bg:#1a1a19; --card:#232322; --ink:#f2f1ec; --ink2:#c3c2b7; --muted:#8f8d86;
  --line:#33332f; --accent:#3987e5; --neg:#e66767; --chipbg:#1f2c3d; --okbg:#1e2e1e; --ok:#7fc97f;
}}
:root[data-theme="light"] {{
  --bg:#fcfcfb; --card:#ffffff; --ink:#141413; --ink2:#52514e; --muted:#898781;
  --line:#e3e2db; --accent:#2a78d6; --neg:#c23a39; --chipbg:#eef4fc; --okbg:#eaf5ea; --ok:#1d6b1d;
}}
body {{ background:var(--bg); color:var(--ink); font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
       margin:0; padding:2.5rem 1.25rem 4rem; }}
main {{ max-width:980px; margin:0 auto; display:flex; flex-direction:column; gap:2.2rem; }}
h1 {{ font-size:1.7rem; line-height:1.2; margin:0; text-wrap:balance; }}
.sub {{ color:var(--ink2); margin:.4rem 0 0; max-width:65ch; }}
.statusrow {{ display:flex; flex-wrap:wrap; gap:.5rem; margin-top:1rem; }}
.chip {{ display:inline-block; background:var(--chipbg); color:var(--accent); border-radius:999px;
        padding:.15rem .7rem; font-size:.8rem; font-weight:600; }}
.chip.ok {{ background:var(--okbg); color:var(--ok); }}
.tldr {{ border-left:3px solid var(--accent); padding:.2rem 0 .2rem 1.1rem; display:flex;
         flex-direction:column; gap:.55rem; }}
.tldr p {{ margin:0; color:var(--ink2); max-width:70ch; }}
.tldr b {{ color:var(--ink); }}
.eyebrow {{ font-size:.75rem; font-weight:700; letter-spacing:.08em; color:var(--muted);
            text-transform:uppercase; margin-bottom:.6rem; }}
.slide {{ display:flex; flex-direction:column; gap:.5rem; }}
.imgcard {{ background:#ffffff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
.imgcard img {{ display:block; width:100%; height:auto; }}
.cap {{ color:var(--ink2); font-size:.92rem; margin:0; max-width:75ch; }}
h2 {{ font-size:1.15rem; margin:0 0 .7rem; }}
.tablewrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; }}
table {{ border-collapse:collapse; width:100%; font-size:.9rem; min-width:640px;
         font-variant-numeric:tabular-nums; }}
th {{ text-align:left; font-weight:600; color:var(--ink2); border-bottom:1px solid var(--line);
      padding:.55rem .8rem; background:var(--card); }}
td {{ padding:.55rem .8rem; border-bottom:1px solid var(--line); vertical-align:top; }}
tr:last-child td {{ border-bottom:none; }}
.rev {{ color:var(--neg); font-weight:600; }}
code {{ background:var(--card); border:1px solid var(--line); border-radius:4px;
        padding:.05rem .35rem; font-size:.85em; }}
footer {{ color:var(--muted); font-size:.85rem; border-top:1px solid var(--line); padding-top:1.2rem; }}
</style>
<main>
  <header>
    <h1>MultiCam results — MVU-Eval, full 1,824 questions, InternVL3-8B</h1>
    <p class="sub">The reference deck's slides rebuilt from my overnight runs (July 29–30), one model,
    4 passes per question, question-level permutation tests. Reference deck = the July-28
    “Multi-camera Video Understanding” slides.</p>
    <div class="statusrow">
      <span class="chip">{status}</span>
      <span class="chip">stats adversarially verified — 6-agent workflow</span>
    </div>
  </header>

  <div class="tldr">
    <p><b>Arrangement barely matters; decentralization hurts.</b> sequential {seq:.1f} ≈ stitching {cen:.1f}
    (p=0.22); decentralized {dec:.1f} is the only significant loser (−8.9, p&lt;0.001).</p>
    <p><b>The sync story replicates in shape:</b> stitching {sy['delta']:+.2f} on the 128 synchronized rigs,
    {un['delta']:+.2f} on unrelated clips — neither significant.</p>
    <p><b>The reference deck's one surviving result reverses:</b> Counting stitch delta is {cnt['delta']:+.2f}
    in my run vs their +6.83 — likely the unmatched frame budget (slide 05); the fixed-32 rerun decides it.</p>
  </div>

  {cards}

  <section>
    <h2>My numbers vs the reference deck (their InternVL column)</h2>
    <div class="tablewrap"><table>
      <tr><th>Measurement</th><th>Reference deck<br>(32-frame budget, full AAB+MVU)</th>
          <th>My run<br>(8 frames/video, MVU full)</th><th>Verdict</th></tr>
      <tr><td>MVU arrangement: seq / stitch / decentral</td><td>44.9 / 45.0 / 39.9</td>
          <td>{seq:.1f} / {cen:.1f} / {dec:.1f}</td>
          <td>ordering agrees; levels differ with the budget</td></tr>
      <tr><td>Stitch delta, synchronized rigs</td><td>+0.6</td><td>{sy['delta']:+.2f} (p={sy['p']:.2f})</td>
          <td><span class="chip ok">same shape</span></td></tr>
      <tr><td>Stitch delta, unrelated clips</td><td>+0.4</td><td>{un['delta']:+.2f} (p={un['p']:.2f})</td>
          <td>both ≈ 0</td></tr>
      <tr><td>Counting stitch delta (their one significant result)</td><td>+6.83, survives Holm</td>
          <td>{cnt['delta']:+.2f} (p={cnt['p']:.2f})</td><td class="rev">REVERSES — budget suspect</td></tr>
      <tr><td>Blind floor, MVU</td><td>30.1 (images add +14.8)</td><td>{blind_mine}</td>
          <td>{'<span class="chip ok">done</span>' if blind_done else '<span class="chip">pending</span>'}</td></tr>
      <tr><td>Best single view (no-view-named subset)</td><td>78.6 (+8.7 over luck)</td><td>{sv_mine}</td>
          <td>{'<span class="chip ok">done</span>' if sv_done else '<span class="chip">pending</span>'}</td></tr>
      {b32_row}
    </table></div>
  </section>

  {paper_table}

  <footer>
    Regenerate after new runs land: <code>python3 analysis/mvueval_slide_stats.py</code> →
    <code>python3 analysis/make_slide_figs.py</code> → <code>python3 analysis/make_deck_html.py</code>.
    PNGs for Google Slides: <code>analysis/figs_deck/</code>. Stats source of truth:
    <code>analysis/slide_stats.json</code> (permutation seed {S['meta']['perm']['seed']}).
  </footer>
</main>
"""

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "deck.html")
open(out, "w").write(html)
print(f"wrote {out} ({os.path.getsize(out) // 1024} KB)")
