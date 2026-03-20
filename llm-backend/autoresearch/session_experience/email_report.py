"""
Session Experience Email Reports

Sends plain-text summary + HTML report attachment with:
- Per-topic naturalness scores and flagged issues
- Full conversation transcripts
- Prompt analysis and recommendations
- Prompt diff

Uses macOS Mail app via osascript (same as tutor_teaching_quality pipeline).
"""

import html
import json
import subprocess
import tempfile
from pathlib import Path


def _build_html_report(
    iteration: int,
    description: str,
    avg_naturalness: float,
    avg_weighted_issues: float,
    baseline: dict | None,
    per_topic: list[dict],
    recommendations: list[str],
    prompt_diff: str,
    run_dirs: list[str],
) -> str:
    """Build comprehensive HTML report."""

    delta_nat = ""
    delta_issues = ""
    if baseline:
        d_nat = avg_naturalness - baseline.get("avg_naturalness", 0)
        d_iss = avg_weighted_issues - baseline.get("avg_weighted_issues", 0)
        delta_nat = f" ({'+' if d_nat > 0 else ''}{d_nat:.2f})"
        delta_issues = f" ({'+' if d_iss > 0 else ''}{d_iss:.1f})"

    # Per-topic rows
    topic_rows = ""
    for r in per_topic:
        status_color = "#2e7d32" if r["status"] == "ok" else "#c62828"
        counts = r.get("issue_counts", {})
        issues_str = f"{counts.get('critical', 0)}C {counts.get('major', 0)}M {counts.get('minor', 0)}m"
        topic_rows += (
            f'<tr>'
            f'<td style="padding:6px 12px;border:1px solid #ddd;">{html.escape(r["topic_name"])}</td>'
            f'<td style="padding:6px 12px;border:1px solid #ddd;text-align:center;">{r["naturalness_score"]}/10</td>'
            f'<td style="padding:6px 12px;border:1px solid #ddd;text-align:center;">{r["weighted_issues"]}</td>'
            f'<td style="padding:6px 12px;border:1px solid #ddd;text-align:center;">{issues_str}</td>'
            f'<td style="padding:6px 12px;border:1px solid #ddd;text-align:center;color:{status_color};">{r["status"]}</td>'
            f'</tr>\n'
        )

    # Recommendations
    rec_html = ""
    if recommendations:
        rec_html = '<h2>Top Recommendations</h2><ol style="margin:0;">'
        for rec in recommendations[:5]:
            rec_html += f'<li style="margin-bottom:8px;">{html.escape(rec)}</li>'
        rec_html += "</ol>"

    # Per-run sections with conversation + evaluation
    run_sections = ""
    for i, run_dir_str in enumerate(run_dirs):
        run_dir = Path(run_dir_str)
        topic_result = per_topic[i] if i < len(per_topic) else {}
        topic_name = topic_result.get("topic_name", f"Topic {i+1}")

        # Load evaluation
        eval_data = {}
        eval_path = run_dir / "experience_evaluation.json"
        if eval_path.exists():
            try:
                eval_data = json.loads(eval_path.read_text())
            except Exception:
                pass

        flow = html.escape(eval_data.get("flow_assessment", ""))
        strengths = html.escape(eval_data.get("strongest_moments", ""))
        flagged = eval_data.get("flagged_messages", [])

        # Flagged messages
        flagged_html = ""
        if flagged:
            flagged_html = '<h4 style="color:#c62828;">Flagged Messages</h4>'
            for f in flagged:
                sev = f.get("severity", "?").upper()
                sev_color = {"CRITICAL": "#c62828", "MAJOR": "#e65100", "MINOR": "#f9a825"}.get(sev, "#666")
                flagged_html += (
                    f'<div style="margin:8px 0;padding:8px 12px;border-left:3px solid {sev_color};background:#fafafa;">'
                    f'<strong style="color:{sev_color};">[{sev}]</strong> '
                    f'Turn {f.get("turn", "?")} — {html.escape(f.get("issue_category", "?"))}<br>'
                    f'<em>"{html.escape(f.get("message_snippet", ""))}"</em><br>'
                    f'<span style="color:#555;">{html.escape(f.get("description", ""))}</span>'
                    f'</div>'
                )

        # Load prompt analysis
        analysis_html = ""
        analysis_path = run_dir / "prompt_analysis.json"
        if analysis_path.exists():
            try:
                analysis_data = json.loads(analysis_path.read_text())
                top_rec = analysis_data.get("top_recommendation", "")
                if top_rec:
                    analysis_html = (
                        f'<h4>Prompt Analysis</h4>'
                        f'<p><strong>Top fix:</strong> {html.escape(top_rec)}</p>'
                    )
                patterns = analysis_data.get("cross_cutting_patterns", [])
                if patterns:
                    analysis_html += '<ul style="margin:4px 0;">'
                    for p in patterns:
                        analysis_html += f'<li><strong>[{html.escape(p.get("fix_priority", "?").upper())}]</strong> {html.escape(p.get("pattern", ""))}</li>'
                    analysis_html += '</ul>'
            except Exception:
                pass

        # Conversation transcript
        conv_html = ""
        conv_path = run_dir / "conversation.md"
        if conv_path.exists():
            try:
                conv_md = conv_path.read_text()
                conv_html = _markdown_conversation_to_html(conv_md)
            except Exception:
                conv_html = '<p style="color:#999;">Could not load conversation.</p>'

        score = topic_result.get("naturalness_score", "?")
        run_sections += f"""
        <div style="margin-top:32px;border-top:3px solid #1565c0;padding-top:16px;">
            <h2 style="color:#1565c0;">{html.escape(topic_name)} — {score}/10</h2>
            <p><strong>Flow:</strong> {flow}</p>
            <p><strong>Strengths:</strong> {strengths}</p>
            {flagged_html}
            {analysis_html}
            <details style="margin-top:16px;border:1px solid #ddd;border-radius:4px;padding:12px;background:#fafafa;">
                <summary style="cursor:pointer;font-weight:bold;color:#1565c0;">Full Conversation</summary>
                <div style="margin-top:12px;">{conv_html}</div>
            </details>
        </div>"""

    diff_escaped = html.escape(prompt_diff or "(no changes)")

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Session Experience #{iteration}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 900px; margin: 0 auto; padding: 24px; color: #333; line-height: 1.5; }}
        h1 {{ border-bottom: 2px solid #1565c0; padding-bottom: 8px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
        th {{ background: #f5f5f5; padding: 8px 12px; border: 1px solid #ddd; text-align: left; }}
        pre {{ background: #f5f5f5; padding: 16px; overflow-x: auto; font-size: 13px;
               border-radius: 4px; border: 1px solid #ddd; white-space: pre-wrap; }}
        .tutor-msg {{ background: #e3f2fd; border-left: 4px solid #1565c0; padding: 10px 14px;
                      margin: 8px 0; border-radius: 0 4px 4px 0; }}
        .student-msg {{ background: #fff3e0; border-left: 4px solid #e65100; padding: 10px 14px;
                        margin: 8px 0; border-radius: 0 4px 4px 0; }}
        .turn-label {{ font-weight: bold; font-size: 13px; color: #666; margin-bottom: 4px; }}
    </style>
</head>
<body>
    <h1>Session Experience — Iteration #{iteration}</h1>

    <table>
        <tr><td style="padding:6px 12px;font-weight:bold;width:160px;">Hypothesis</td>
            <td style="padding:6px 12px;">{html.escape(description)}</td></tr>
        <tr><td style="padding:6px 12px;font-weight:bold;">Avg Naturalness</td>
            <td style="padding:6px 12px;"><strong style="font-size:18px;">{avg_naturalness:.2f}/10</strong>{delta_nat}</td></tr>
        <tr><td style="padding:6px 12px;font-weight:bold;">Avg Weighted Issues</td>
            <td style="padding:6px 12px;"><strong style="font-size:18px;">{avg_weighted_issues:.1f}</strong>{delta_issues} (lower is better)</td></tr>
    </table>

    <h2>Per-Topic Results</h2>
    <table>
        <tr style="background:#f5f5f5;">
            <th style="padding:8px 12px;border:1px solid #ddd;">Topic</th>
            <th style="padding:8px 12px;border:1px solid #ddd;text-align:center;">Naturalness</th>
            <th style="padding:8px 12px;border:1px solid #ddd;text-align:center;">Weighted Issues</th>
            <th style="padding:8px 12px;border:1px solid #ddd;text-align:center;">Issue Breakdown</th>
            <th style="padding:8px 12px;border:1px solid #ddd;text-align:center;">Status</th>
        </tr>
        {topic_rows}
    </table>

    {rec_html}

    <h2>Prompt Changes</h2>
    <pre>{diff_escaped}</pre>

    {run_sections}
</body>
</html>"""


def _markdown_conversation_to_html(md_text: str) -> str:
    """Convert conversation.md to styled HTML."""
    lines = md_text.split("\n")
    html_parts = []
    current_role = None
    current_turn = ""
    buffer = []

    for line in lines:
        if line.startswith("### [Turn"):
            if buffer and current_role:
                content = "\n".join(buffer).strip()
                if content:
                    css_class = "tutor-msg" if current_role == "TUTOR" else "student-msg"
                    html_parts.append(
                        f'<div class="{css_class}">'
                        f'<div class="turn-label">{html.escape(current_turn)}</div>'
                        f'{html.escape(content)}</div>'
                    )
                buffer = []
            current_turn = line.replace("### ", "").strip()
            current_role = "TUTOR" if "TUTOR" in line else "STUDENT"
        elif line.startswith("# ") or line.startswith("**") or line.startswith("---"):
            continue
        else:
            buffer.append(line)

    if buffer and current_role:
        content = "\n".join(buffer).strip()
        if content:
            css_class = "tutor-msg" if current_role == "TUTOR" else "student-msg"
            html_parts.append(
                f'<div class="{css_class}">'
                f'<div class="turn-label">{html.escape(current_turn)}</div>'
                f'{html.escape(content)}</div>'
            )

    return "\n".join(html_parts) if html_parts else '<p style="color:#999;">No conversation data.</p>'


def send_experience_report(
    iteration: int,
    description: str,
    avg_naturalness: float,
    avg_weighted_issues: float,
    baseline: dict | None,
    per_topic: list[dict],
    recommendations: list[str],
    prompt_diff: str,
    email_to: str | None = None,
    run_dirs: list[str] | None = None,
) -> bool:
    if not email_to:
        print("  [email] No recipient, skipping.")
        return False

    delta = ""
    if baseline:
        d = avg_naturalness - baseline.get("avg_naturalness", 0)
        delta = f" ({'+' if d > 0 else ''}{d:.2f})"

    subject = f"[Session Experience #{iteration}] nat={avg_naturalness:.1f}/10{delta} issues={avg_weighted_issues:.0f} — {description[:50]}"

    body_text = (
        f"Session Experience Iteration #{iteration}\n"
        f"Naturalness: {avg_naturalness:.2f}/10{delta}\n"
        f"Weighted Issues: {avg_weighted_issues:.1f}\n"
        f"Hypothesis: {description}\n\n"
        f"Open the attached HTML report for details."
    )

    report_html = _build_html_report(
        iteration, description, avg_naturalness, avg_weighted_issues,
        baseline, per_topic, recommendations, prompt_diff, run_dirs or [],
    )

    try:
        report_filename = f"session_experience_{iteration}.html"
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
            print(f"  [email] Sent to {email_to} ({report_filename})")
            return True
        else:
            print(f"  [email] Mail.app error: {result.stderr.strip()}")
            return False

    except Exception as e:
        print(f"  [email] Failed: {e}")
        return False


def _escape_applescript(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
