"""
Simplification Quality Email Reports

Sends plain-text summary + HTML report attachment with:
- Overall average and per-dimension score breakdown
- Delta from baseline (if available)
- Per-card detail sections: original + depth-1 + depth-2 simplified cards
- Evaluation scores, rationales, issues, suggestions per card
- Prompt diff

Uses macOS Mail app via osascript (same as other pipelines).
"""

import html
import json
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("autoresearch.simplification_quality")

DIMENSIONS = [
    "reason_adherence",
    "content_differentiation",
    "simplicity",
    "concept_accuracy",
    "presentation_quality",
]

DIMENSION_LABELS = {
    "reason_adherence": "Reason Adherence",
    "content_differentiation": "Content Differentiation",
    "simplicity": "Simplicity",
    "concept_accuracy": "Concept Accuracy",
    "presentation_quality": "Presentation Quality",
}


def _load_card_details(run_dirs: list[str]) -> list[dict]:
    """Load card details from run directories."""
    all_cards = []
    for rd in run_dirs:
        detail_path = Path(rd) / "cards_detail.json"
        if detail_path.exists():
            try:
                with open(detail_path) as f:
                    cards = json.load(f)
                all_cards.extend(cards)
            except Exception:
                pass
    return all_cards


def _build_html_report(
    iteration: int,
    avg_score: float,
    per_dimension: dict,
    depth_1_avg: float,
    depth_2_avg: float,
    baseline_score: float | None,
    description: str,
    card_details: list[dict],
    prompt_diff: str,
) -> str:
    """Build comprehensive HTML report."""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Delta from baseline
    delta_html = ""
    if baseline_score is not None:
        d = avg_score - baseline_score
        arrow = "&#8593;" if d > 0 else "&#8595;"
        color = "#2e7d32" if d > 0 else "#c62828"
        delta_html = f' <span style="color:{color};font-weight:bold;">({arrow} {"+" if d > 0 else ""}{d:.2f})</span>'

    # Score summary table — per-dimension rows
    dim_rows = ""
    for dim in DIMENSIONS:
        score = per_dimension.get(dim)
        val = f"{score:.1f}/10" if score is not None else "n/a"
        label = DIMENSION_LABELS.get(dim, dim)
        dim_rows += (
            f'<tr>'
            f'<td style="padding:6px 12px;border:1px solid #ddd;">{html.escape(label)}</td>'
            f'<td style="padding:6px 12px;border:1px solid #ddd;text-align:center;">{val}</td>'
            f'</tr>\n'
        )

    # Per-card detail sections
    card_sections = ""
    for i, card_data in enumerate(card_details):
        card_title = html.escape(card_data.get("card_title", f"Card {i+1}"))
        orig = card_data.get("original_card", {})
        orig_title = html.escape(orig.get("title", ""))
        orig_content = html.escape(orig.get("content", ""))

        # Depth sections
        depth_sections = ""
        for depth in [1, 2]:
            depth_key = f"depth_{depth}"
            depth_data = card_data.get(depth_key)
            if not depth_data:
                continue

            bg = "#e3f2fd" if depth == 1 else "#e8f5e9"
            border_color = "#1565c0" if depth == 1 else "#2e7d32"
            label = f"Depth {depth}"

            reason = html.escape(depth_data.get("reason", ""))
            simp_card = depth_data.get("card", {})
            simp_title = html.escape(simp_card.get("title", ""))
            simp_content = html.escape(simp_card.get("content", ""))

            # Scores per dimension from evaluation
            evaluation = depth_data.get("evaluation", {})
            scores_html = ""
            for dim in DIMENSIONS:
                dim_data = evaluation.get(dim, {})
                s = dim_data.get("score") if isinstance(dim_data, dict) else None
                rationale = html.escape(str(dim_data.get("rationale", ""))) if isinstance(dim_data, dict) and dim_data.get("rationale") else ""
                s_str = f"{s}/10" if s is not None else "n/a"
                s_color = "#2e7d32" if s is not None and s >= 7 else "#e65100" if s is not None and s >= 4 else "#c62828" if s is not None else "#666"
                dim_label = DIMENSION_LABELS.get(dim, dim)
                rationale_part = f' — <span style="color:#555;">{rationale}</span>' if rationale else ""
                scores_html += (
                    f'<div style="margin:2px 0;">'
                    f'<strong style="color:{s_color};">{s_str}</strong> {html.escape(dim_label)}'
                    f'{rationale_part}</div>'
                )

            # Overall assessment
            assessment = html.escape(str(evaluation.get("overall_assessment", "")))
            assessment_html = f'<p style="margin-top:8px;"><strong>Assessment:</strong> {assessment}</p>' if assessment else ""

            # Issues and suggestions
            issues = evaluation.get("specific_issues", [])
            suggestions = evaluation.get("suggestions", [])
            extras_html = ""
            if issues:
                extras_html += '<div style="margin-top:8px;"><strong style="color:#c62828;">Issues:</strong><ul style="margin:4px 0;">'
                for issue in issues:
                    extras_html += f'<li>{html.escape(str(issue))}</li>'
                extras_html += '</ul></div>'
            if suggestions:
                extras_html += '<div style="margin-top:8px;"><strong style="color:#1565c0;">Suggestions:</strong><ul style="margin:4px 0;">'
                for sug in suggestions:
                    extras_html += f'<li>{html.escape(str(sug))}</li>'
                extras_html += '</ul></div>'

            depth_sections += f"""
            <div style="margin-top:12px;padding:12px;background:{bg};border-left:4px solid {border_color};border-radius:0 4px 4px 0;">
                <h4 style="margin:0 0 8px 0;color:{border_color};">{label}
                    <span style="background:{border_color};color:#fff;padding:2px 8px;border-radius:10px;font-size:12px;margin-left:8px;">{reason}</span>
                </h4>
                <p style="margin:4px 0;"><strong>Title:</strong> {simp_title}</p>
                <div style="margin:8px 0;padding:8px;background:rgba(255,255,255,0.6);border-radius:4px;white-space:pre-wrap;font-size:14px;">{simp_content}</div>
                <div style="margin-top:8px;">{scores_html}</div>
                {assessment_html}
                {extras_html}
            </div>"""

        card_sections += f"""
        <details style="margin-top:24px;border:1px solid #ddd;border-radius:4px;padding:0;">
            <summary style="cursor:pointer;font-weight:bold;padding:12px;background:#f5f5f5;border-bottom:1px solid #ddd;">
                {card_title}
            </summary>
            <div style="padding:12px;">
                <div style="padding:12px;background:#f0f0f0;border-left:4px solid #999;border-radius:0 4px 4px 0;">
                    <h4 style="margin:0 0 8px 0;color:#666;">Original Card</h4>
                    <p style="margin:4px 0;"><strong>Title:</strong> {orig_title}</p>
                    <div style="margin:8px 0;padding:8px;background:rgba(255,255,255,0.6);border-radius:4px;white-space:pre-wrap;font-size:14px;">{orig_content}</div>
                </div>
                {depth_sections}
            </div>
        </details>"""

    diff_escaped = html.escape(prompt_diff or "(no changes)")

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Simplification Quality #{iteration}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 900px; margin: 0 auto; padding: 24px; color: #333; line-height: 1.5; }}
        h1 {{ border-bottom: 2px solid #7b1fa2; padding-bottom: 8px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
        th {{ background: #f5f5f5; padding: 8px 12px; border: 1px solid #ddd; text-align: left; }}
        pre {{ background: #f5f5f5; padding: 16px; overflow-x: auto; font-size: 13px;
               border-radius: 4px; border: 1px solid #ddd; white-space: pre-wrap; }}
    </style>
</head>
<body>
    <h1>Simplification Quality — Iteration #{iteration}</h1>

    <table>
        <tr><td style="padding:6px 12px;font-weight:bold;width:200px;">Description</td>
            <td style="padding:6px 12px;">{html.escape(description)}</td></tr>
        <tr><td style="padding:6px 12px;font-weight:bold;">Timestamp</td>
            <td style="padding:6px 12px;">{timestamp}</td></tr>
        <tr><td style="padding:6px 12px;font-weight:bold;">Overall Average</td>
            <td style="padding:6px 12px;"><strong style="font-size:18px;">{avg_score:.2f}/10</strong>{delta_html}</td></tr>
        <tr><td style="padding:6px 12px;font-weight:bold;">Depth 1 Avg</td>
            <td style="padding:6px 12px;">{depth_1_avg:.2f}/10</td></tr>
        <tr><td style="padding:6px 12px;font-weight:bold;">Depth 2 Avg</td>
            <td style="padding:6px 12px;">{depth_2_avg:.2f}/10</td></tr>
    </table>

    <h2>Score Breakdown by Dimension</h2>
    <table>
        <tr style="background:#f5f5f5;">
            <th style="padding:8px 12px;border:1px solid #ddd;">Dimension</th>
            <th style="padding:8px 12px;border:1px solid #ddd;text-align:center;">Score</th>
        </tr>
        {dim_rows}
        <tr style="background:#f5f5f5;font-weight:bold;">
            <td style="padding:6px 12px;border:1px solid #ddd;">Overall Average</td>
            <td style="padding:6px 12px;border:1px solid #ddd;text-align:center;">{avg_score:.1f}/10</td>
        </tr>
    </table>

    <h2>Per-Card Details</h2>
    {card_sections}

    <h2>Prompt Changes</h2>
    <details style="border:1px solid #ddd;border-radius:4px;padding:0;">
        <summary style="cursor:pointer;font-weight:bold;padding:12px;background:#f5f5f5;">Show diff</summary>
        <pre style="margin:0;border:none;border-radius:0;">{diff_escaped}</pre>
    </details>
</body>
</html>"""


def send_simplification_report(
    iteration: int,
    avg_score: float,
    per_dimension: dict,
    depth_1_avg: float,
    depth_2_avg: float,
    baseline: dict | None,
    description: str,
    per_topic: list[dict],
    prompt_diff: str,
    email_to: str = "manish@simplifyloop.com",
    run_dirs: list[str] | None = None,
) -> bool:
    if not email_to:
        logger.info("No recipient, skipping email.")
        return False

    baseline_score = baseline.get("avg_score") if baseline else None

    delta = ""
    if baseline_score is not None:
        d = avg_score - baseline_score
        delta = f" ({'+' if d > 0 else ''}{d:.2f})"

    subject = f"[Simplification #{iteration}] score={avg_score:.1f}/10{delta} — {description[:50]}"

    dim_lines = []
    for dim in DIMENSIONS:
        score = per_dimension.get(dim)
        label = DIMENSION_LABELS.get(dim, dim)
        dim_lines.append(f"  {label}: {score:.1f}/10" if score is not None else f"  {label}: n/a")

    body_text = (
        f"Simplification Quality Iteration #{iteration}\n"
        f"Overall: {avg_score:.2f}/10{delta}\n"
        f"Depth 1: {depth_1_avg:.2f}/10  Depth 2: {depth_2_avg:.2f}/10\n"
        + "\n".join(dim_lines) + "\n"
        f"Description: {description}\n\n"
        f"Open the attached HTML report for details."
    )

    # Load card details from run directories
    card_details = _load_card_details(run_dirs or [])

    report_html = _build_html_report(
        iteration, avg_score, per_dimension, depth_1_avg, depth_2_avg,
        baseline_score, description, card_details, prompt_diff,
    )

    try:
        report_filename = f"simplification_quality_{iteration}.html"
        report_path = Path(tempfile.gettempdir()) / report_filename
        report_path.write_text(report_html)

        applescript = f'''
tell application "Mail"
    set newMessage to make new outgoing message with properties {{subject:"{_escape_applescript(subject)}", content:"{_escape_applescript(body_text)}", visible:false}}
    tell newMessage
        make new to recipient at end of to recipients with properties {{address:"{_escape_applescript(email_to)}"}}
        make new attachment with properties {{file name:POSIX file "{report_path}"}} at after the last paragraph
    end tell
    send newMessage
end tell
'''
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True, text=True, timeout=30,
        )

        if result.returncode == 0:
            logger.info(f"Sent to {email_to} ({report_filename})")
            return True
        else:
            logger.error(f"Mail.app error: {result.stderr.strip()}")
            return False

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def _escape_applescript(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
