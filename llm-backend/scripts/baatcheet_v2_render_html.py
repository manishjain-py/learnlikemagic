"""
Baatcheet V2 HTML Renderer — turn a run's plan.json + dialogue.json into a
standalone pretty HTML file readable in any browser.

Usage:
    python scripts/baatcheet_v2_render_html.py path/to/run-dir/
    # writes path/to/run-dir/dialogue.html
"""

import argparse
import html
import json
import re
from pathlib import Path


MOVE_COLORS = {
    "hook":                 ("#fef3c7", "#92400e"),  # amber bg / dark amber text
    "activate":             ("#fef3c7", "#92400e"),
    "concretize":           ("#dbeafe", "#1e40af"),
    "notate":               ("#dbeafe", "#1e40af"),
    "trap-set":             ("#fee2e2", "#991b1b"),  # red — the trap
    "fall":                 ("#ffedd5", "#9a3412"),  # orange — wrong-answer moment
    "student-act":          ("#dcfce7", "#166534"),  # green — physical action
    "observe":              ("#ecfccb", "#3f6212"),  # lime — observation
    "funnel":               ("#fce7f3", "#9d174d"),  # pink — focusing question
    "articulate":           ("#e0e7ff", "#3730a3"),  # indigo — rule named
    "escalate":             ("#e0f2fe", "#075985"),  # sky — extension
    "callback":             ("#f3e8ff", "#6b21a8"),  # purple — threading
    "practice-guided":      ("#fef9c3", "#854d0e"),
    "practice-independent": ("#fef9c3", "#854d0e"),
    "reframe":              ("#fce7f3", "#9d174d"),
    "visual":               ("#e5e7eb", "#374151"),
    "check-in":             ("#e5e7eb", "#374151"),
    "close":                ("#fef3c7", "#854d0e"),
}


def render_inline_md(text: str) -> str:
    """Convert **bold** to <strong>; escape everything else."""
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    out = []
    for p in parts:
        if p.startswith("**") and p.endswith("**"):
            out.append(f"<strong>{html.escape(p[2:-2])}</strong>")
        else:
            out.append(html.escape(p))
    return "".join(out)


def phase_for_slot(slot: int, macro_structure: list, card_plan: list) -> str:
    """Walk the macro_structure phases in order, allocating slots cumulatively."""
    if not card_plan:
        return ""
    start_slot = card_plan[0]["slot"]
    cursor = start_slot
    for phase in macro_structure:
        end = cursor + phase["card_count"]
        if cursor <= slot < end:
            return phase["phase"]
        cursor = end
    return ""


def build_html(run_dir: Path) -> str:
    plan = json.loads((run_dir / "plan.json").read_text())
    visuals_path = run_dir / "dialogue_with_visuals.json"
    if visuals_path.exists():
        dialogue = json.loads(visuals_path.read_text())
        has_visuals = True
    else:
        dialogue = json.loads((run_dir / "dialogue.json").read_text())
        has_visuals = False
    summary_path = run_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    scores_path = run_dir / "eval_scores.json"
    scores = json.loads(scores_path.read_text()) if scores_path.exists() else None

    misconceptions = plan.get("misconceptions", [])
    spine = plan.get("spine", {})
    materials = plan.get("concrete_materials", [])
    macro = plan.get("macro_structure", [])
    card_plan = plan.get("card_plan", [])
    cards = dialogue.get("cards", [])
    plan_by_slot = {s["slot"]: s for s in card_plan}

    topic = summary.get("topic", "Baatcheet V2 Dialogue")
    run_label = summary.get("run_label", run_dir.name)

    # ---- HTML head ----
    css = """
    :root {
      --bg: #fafaf7;
      --surface: #ffffff;
      --border: #e5e7eb;
      --text: #1f2937;
      --muted: #6b7280;
      --tutor: #2563eb;
      --tutor-bg: #eff6ff;
      --peer: #d97706;
      --peer-bg: #fffbeb;
      --summary: #7c3aed;
      --summary-bg: #f5f3ff;
    }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 0 0 80px;
      line-height: 1.55;
    }
    header.page {
      background: linear-gradient(135deg, #1e3a8a 0%, #6d28d9 100%);
      color: white;
      padding: 32px 24px 24px;
      text-align: center;
    }
    header.page h1 { margin: 0 0 8px; font-size: 22px; font-weight: 600; letter-spacing: -0.01em; }
    header.page .meta { opacity: 0.85; font-size: 13px; }
    header.page .meta b { font-weight: 600; }
    main { max-width: 880px; margin: 0 auto; padding: 0 16px; }
    .panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px 22px;
      margin-top: 20px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      font-weight: 600;
    }
    .spine-line { font-size: 16px; line-height: 1.6; }
    .spine-line .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; margin-right: 4px; }
    .spine-line + .spine-line { margin-top: 8px; }
    .misconception-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .misconception {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 14px;
      background: #fafafa;
    }
    .misconception .id-name { font-weight: 600; font-size: 13px; color: #991b1b; }
    .misconception .desc { color: var(--muted); font-size: 13px; margin-top: 4px; }
    .misconception .disproof { font-size: 12px; margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); color: #166534; }
    .scores {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .score-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 6px 10px;
      background: #fafafa;
      border-radius: 6px;
      border: 1px solid var(--border);
      font-size: 13px;
    }
    .score-pill {
      font-weight: 600;
      padding: 1px 7px;
      border-radius: 999px;
      font-size: 12px;
    }
    .score-5 { background: #dcfce7; color: #166534; }
    .score-4 { background: #d1fae5; color: #047857; }
    .score-3 { background: #fef3c7; color: #92400e; }
    .score-2 { background: #fee2e2; color: #991b1b; }
    .score-1 { background: #fecaca; color: #7f1d1d; }
    .verdict {
      margin-top: 12px;
      padding: 10px 14px;
      background: #dcfce7;
      border: 1px solid #86efac;
      border-radius: 10px;
      color: #166534;
      font-weight: 600;
      font-size: 14px;
    }

    /* Phase divider */
    .phase-divider {
      margin: 32px 0 12px;
      text-align: center;
      position: relative;
    }
    .phase-divider .line {
      position: absolute; top: 50%; left: 0; right: 0; height: 1px; background: var(--border); z-index: 0;
    }
    .phase-divider .label {
      position: relative;
      display: inline-block;
      background: var(--bg);
      padding: 0 12px;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      font-weight: 600;
      z-index: 1;
    }

    /* Card / chat bubble */
    .card {
      display: flex;
      gap: 12px;
      margin: 14px 0;
      align-items: flex-start;
    }
    .card.peer { flex-direction: row-reverse; }
    .card.summary, .card.system { justify-content: center; }
    .avatar {
      width: 36px; height: 36px; border-radius: 50%;
      flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      font-weight: 600; font-size: 13px; color: white;
    }
    .card.tutor .avatar { background: var(--tutor); }
    .card.peer .avatar { background: var(--peer); }
    .card.summary .avatar, .card.system .avatar { background: var(--summary); }
    .bubble {
      max-width: 78%;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 12px 16px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.05);
      position: relative;
    }
    .card.tutor .bubble { background: var(--tutor-bg); border-color: #bfdbfe; border-top-left-radius: 4px; }
    .card.peer .bubble { background: var(--peer-bg); border-color: #fde68a; border-top-right-radius: 4px; }
    .card.summary .bubble, .card.system .bubble { background: var(--summary-bg); border-color: #ddd6fe; max-width: 90%; }
    .bubble-head {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 6px;
      font-size: 12px;
      color: var(--muted);
    }
    .speaker { font-weight: 600; color: var(--text); }
    .card.peer .bubble-head { justify-content: flex-end; }
    .move-chip {
      padding: 2px 9px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.02em;
    }
    .card-id {
      color: var(--muted);
      font-size: 11px;
      font-variant-numeric: tabular-nums;
    }
    .target-chip {
      padding: 1px 7px;
      border-radius: 4px;
      background: #f3f4f6;
      color: var(--muted);
      font-size: 10px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      font-weight: 500;
    }
    .target-M1 { background: #fee2e2; color: #991b1b; }
    .target-M2 { background: #fed7aa; color: #9a3412; }
    .target-M3 { background: #fef3c7; color: #92400e; }
    .target-spine { background: #f5f3ff; color: #6d28d9; }
    .lines { font-size: 15px; line-height: 1.5; }
    .lines p { margin: 0; }
    .lines p + p { margin-top: 4px; }
    .visual-intent {
      margin-top: 8px;
      padding: 8px 10px;
      background: #f9fafb;
      border-left: 3px solid #9ca3af;
      border-radius: 4px;
      font-size: 13px;
      color: var(--muted);
      font-style: italic;
    }
    .visual-figure {
      margin-top: 10px;
      padding: 12px;
      background: #fffbea;
      border: 1px solid #fde68a;
      border-radius: 10px;
      text-align: center;
    }
    .visual-figure svg {
      max-width: 100%;
      height: auto;
      display: block;
      margin: 0 auto;
      background: white;
      border-radius: 6px;
    }
    .visual-figure .caption {
      margin-top: 8px;
      font-size: 12px;
      color: var(--muted);
      font-style: italic;
    }
    .visual-figure .why {
      margin-top: 4px;
      font-size: 11px;
      color: #92400e;
      letter-spacing: 0.02em;
    }
    .check-in-block {
      margin-top: 8px;
      padding: 10px 12px;
      background: #f9fafb;
      border-radius: 8px;
      font-size: 13px;
    }
    .check-in-block .ci-type { font-weight: 600; color: var(--summary); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; }
    .toggle { color: var(--muted); cursor: pointer; font-size: 12px; user-select: none; }
    .legend {
      display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px;
    }
    .legend .move-chip { font-size: 10px; padding: 1px 7px; }
    footer { text-align: center; color: var(--muted); font-size: 12px; margin-top: 40px; }
    """

    # ---- Header ----
    plan_meta = summary.get("plan_meta", {})
    dialogue_meta = summary.get("dialogue", {})
    total_cost = (plan_meta.get("cost_usd") or 0) + (dialogue_meta.get("cost_usd") or 0)
    total_time = (plan_meta.get("duration_s") or 0) + (dialogue_meta.get("duration_s") or 0)
    head_meta_bits = []
    if summary.get("dialogue_effort"):
        head_meta_bits.append(f"effort: <b>{summary['dialogue_effort']}</b>")
    if total_cost:
        head_meta_bits.append(f"total cost: <b>${total_cost:.2f}</b>")
    if total_time:
        head_meta_bits.append(f"total time: <b>{total_time:.0f}s</b>")
    head_meta_bits.append(f"cards: <b>{len(cards)}</b>")
    if has_visuals:
        n_with_svg = sum(1 for c in cards if c.get("visual_svg"))
        head_meta_bits.append(f"visualised: <b>{n_with_svg}</b>")

    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\">
  <title>{html.escape(topic)} — Baatcheet V2</title>
  <style>{css}</style>
</head>
<body>
  <header class=\"page\">
    <h1>{html.escape(topic)}</h1>
    <div class=\"meta\">Baatcheet V2 dialogue · run <b>{html.escape(run_label)}</b> · {' · '.join(head_meta_bits)}</div>
  </header>
  <main>""")

    # ---- Spine panel ----
    parts.append('<section class="panel">')
    parts.append('<h2>Narrative spine</h2>')
    parts.append(f'<div class="spine-line"><span class="label">Situation</span>{html.escape(spine.get("situation",""))}</div>')
    if spine.get("particulars"):
        parts.append(f'<div class="spine-line"><span class="label">Particulars</span>{html.escape(", ".join(spine.get("particulars", [])))}</div>')
    parts.append(f'<div class="spine-line"><span class="label">Opening hook</span>{html.escape(spine.get("opening_hook",""))}</div>')
    parts.append(f'<div class="spine-line"><span class="label">Closing resolution</span>{html.escape(spine.get("closing_resolution",""))}</div>')
    parts.append('</section>')

    # ---- Misconceptions panel ----
    parts.append('<section class="panel">')
    parts.append('<h2>Designed misconceptions (each gets one trap-resolve cycle)</h2>')
    parts.append('<div class="misconception-grid">')
    for m in misconceptions:
        parts.append(f"""<div class="misconception">
            <div class="id-name"><span class="target-chip target-{m['id']}">{m['id']}</span> {html.escape(m.get('name',''))}</div>
            <div class="desc">{html.escape(m.get('description',''))}</div>
            <div class="disproof"><b>Concrete disproof:</b> {html.escape(m.get('concrete_disproof',''))}</div>
        </div>""")
    parts.append('</div>')
    parts.append('</section>')

    # ---- Concrete materials panel ----
    if materials:
        parts.append('<section class="panel">')
        parts.append('<h2>Concrete materials the student uses</h2>')
        parts.append('<ul style="margin:0; padding-left:20px;">')
        for mat in materials:
            parts.append(f'<li><b>{html.escape(mat.get("item",""))}</b> — {html.escape(mat.get("use",""))}</li>')
        parts.append('</ul>')
        parts.append('</section>')

    # ---- Eval panel ----
    if scores:
        parts.append('<section class="panel">')
        parts.append('<h2>Mechanical eval — V2 rubric (1=absent, 5=exemplary)</h2>')
        avg = scores.get("average", 0)
        verdict_text = "PASS — V2 architecture lands" if avg >= 4.0 else ("PARTIAL — needs targeted iteration" if avg >= 3.5 else "FAIL")
        parts.append('<div class="scores">')
        for k, v in sorted(scores.get("scores", {}).items()):
            label = k.split("_", 1)[1].replace("_", " ")
            note = scores.get("notes", {}).get(k, "")
            parts.append(f'<div class="score-row"><span title="{html.escape(note)}">{html.escape(label)}</span><span class="score-pill score-{v}">{v}/5</span></div>')
        parts.append('</div>')
        parts.append(f'<div class="verdict">{verdict_text} · average <b>{avg:.2f}/5</b></div>')
        parts.append('</section>')

    # ---- Move legend ----
    parts.append('<section class="panel">')
    parts.append('<h2>Move legend (the pedagogical move each card performs)</h2>')
    parts.append('<div class="legend">')
    for move, (bg, fg) in MOVE_COLORS.items():
        parts.append(f'<span class="move-chip" style="background:{bg}; color:{fg};">{move}</span>')
    parts.append('</div>')
    parts.append('</section>')

    # ---- Cards ----
    parts.append('<h2 style="margin-top: 36px; font-size: 18px;">Dialogue (40 cards)</h2>')
    last_phase = None
    for c in cards:
        slot = c.get("card_idx")
        plan_slot = plan_by_slot.get(slot, {})
        move = plan_slot.get("move", "?")
        target = plan_slot.get("target", "")
        speaker = c.get("speaker") or "system"
        speaker_name = c.get("speaker_name") or ("Mr. Verma" if speaker == "tutor" else ("Meera" if speaker == "peer" else "Summary"))
        ctype = c.get("card_type", "")

        phase = phase_for_slot(slot, macro, card_plan)
        if phase and phase != last_phase:
            label = phase.replace("_", " ").upper()
            parts.append(f'<div class="phase-divider"><span class="line"></span><span class="label">{html.escape(label)}</span></div>')
            last_phase = phase

        bg, fg = MOVE_COLORS.get(move, ("#f3f4f6", "#374151"))
        chip = f'<span class="move-chip" style="background:{bg}; color:{fg};">{html.escape(move)}</span>'
        target_chip = ""
        if target:
            target_class = f"target-{target}" if target in {"M1", "M2", "M3", "spine"} else ""
            target_chip = f'<span class="target-chip {target_class}">{html.escape(target)}</span>'

        # Avatar initials
        if speaker == "tutor":
            avatar = "MV"
        elif speaker == "peer":
            avatar = "M"
        else:
            avatar = "✓"

        # Lines
        lines_html = "".join(f"<p>{render_inline_md(line.get('display',''))}</p>" for line in c.get("lines", []))

        extras = ""
        # Inline SVG visualisation if present (from baatcheet_v2_visualize pass)
        svg_str = c.get("visual_svg")
        if svg_str:
            caption = c.get("visual_intent", "")
            why = c.get("visual_why", "")
            # SVG is trusted output from our prompt pipeline; embed as-is
            extras += '<div class="visual-figure">'
            extras += svg_str
            if caption:
                extras += f'<div class="caption">{html.escape(caption)}</div>'
            if why:
                extras += f'<div class="why">why: {html.escape(why)}</div>'
            extras += '</div>'
        elif c.get("visual_intent"):
            extras += f'<div class="visual-intent">📐 visual: {html.escape(c["visual_intent"])}</div>'
        if c.get("check_in"):
            ci = c["check_in"]
            ci_lines = [f'<div class="ci-type">check-in · {html.escape(ci.get("activity_type",""))}</div>',
                        f'<div><b>Instruction:</b> {html.escape(ci.get("instruction",""))}</div>']
            if ci.get("statement"):
                ci_lines.append(f'<div><b>Statement:</b> {html.escape(ci["statement"])}</div>')
            if ci.get("options"):
                ci_lines.append(f'<div><b>Options:</b> {html.escape(", ".join(ci["options"]))}</div>')
            ci_lines.append(f'<div><b>Hint:</b> {html.escape(ci.get("hint",""))}</div>')
            extras += '<div class="check-in-block">' + "".join(ci_lines) + '</div>'

        bubble_head = f'<div class="bubble-head"><span class="speaker">{html.escape(speaker_name)}</span><span class="card-id">card {slot}</span>{chip}{target_chip}</div>'

        css_class = "card " + (speaker if speaker in ("tutor", "peer") else ("summary" if ctype == "summary" else "system"))
        parts.append(f"""
        <div class="{css_class}">
          <div class="avatar">{avatar}</div>
          <div class="bubble">{bubble_head}<div class="lines">{lines_html}</div>{extras}</div>
        </div>""")

    parts.append("""<footer>
        Baatcheet V2 — designed-lesson architecture · two-stage generation (plan → cards) · see <code>docs/feature-development/baatcheet/dialogue-quality-v2-designed-lesson.md</code>
        </footer>
        </main>
        </body>
        </html>""")

    return "".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--out", default=None, help="Output HTML path (defaults to run_dir/dialogue.html)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_path = Path(args.out) if args.out else run_dir / "dialogue.html"

    html_text = build_html(run_dir)
    out_path.write_text(html_text)
    print(f"Wrote {out_path} ({len(html_text)} chars)")


if __name__ == "__main__":
    main()
