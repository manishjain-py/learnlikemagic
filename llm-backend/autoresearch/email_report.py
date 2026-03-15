"""
Autoresearch Email Reports

Sends a plain-text summary email with a comprehensive HTML report attached.
The HTML report includes: hypothesis, prompt diff, full conversation transcript,
evaluation scores, dimension analysis, and problems found.

Uses macOS Mail app via osascript — no SMTP credentials needed.
"""

import html
import json
import subprocess
import tempfile
from pathlib import Path


def _build_html_report(
    iteration: int,
    description: str,
    status_label: str,
    scores: dict,
    baseline_scores: dict | None,
    avg_score: float,
    baseline_avg: float | None,
    prompt_diff: str,
    run_dirs: list[str],
) -> str:
    """Build a comprehensive HTML report from run directory data."""

    delta_str = ""
    if baseline_avg is not None:
        diff = avg_score - baseline_avg
        arrow = "+" if diff > 0 else ""
        delta_str = f" ({arrow}{diff:.2f})"

    # --- Score table ---
    score_rows = ""
    for dim in sorted(scores.keys()):
        current = scores[dim]
        dim_label = dim.replace("_", " ").title()
        if baseline_scores and dim in baseline_scores:
            base = baseline_scores[dim]
            d = current - base
            arrow = "+" if d > 0 else ""
            color = "#2e7d32" if d > 0 else ("#c62828" if d < 0 else "#333")
            score_rows += (
                f'<tr><td style="padding:6px 16px;border:1px solid #ddd;">{dim_label}</td>'
                f'<td style="padding:6px 16px;border:1px solid #ddd;text-align:center;">{current:.1f}</td>'
                f'<td style="padding:6px 16px;border:1px solid #ddd;text-align:center;">{base:.1f}</td>'
                f'<td style="padding:6px 16px;border:1px solid #ddd;text-align:center;color:{color};font-weight:bold;">{arrow}{d:.1f}</td></tr>\n'
            )
        else:
            score_rows += (
                f'<tr><td style="padding:6px 16px;border:1px solid #ddd;">{dim_label}</td>'
                f'<td style="padding:6px 16px;border:1px solid #ddd;text-align:center;">{current:.1f}</td>'
                f'<td style="padding:6px 16px;border:1px solid #ddd;text-align:center;">-</td>'
                f'<td style="padding:6px 16px;border:1px solid #ddd;text-align:center;">-</td></tr>\n'
            )

    # --- Per-run sections (conversation + evaluation) ---
    run_sections = ""
    for i, run_dir_str in enumerate(run_dirs, 1):
        run_dir = Path(run_dir_str)
        run_label = f"Run {i}" if len(run_dirs) > 1 else "Session"

        # Load evaluation
        eval_data = {}
        eval_path = run_dir / "evaluation.json"
        if eval_path.exists():
            try:
                eval_data = json.loads(eval_path.read_text())
            except Exception:
                pass

        run_score = eval_data.get("avg_score", "?")
        run_scores = eval_data.get("scores", {})
        summary = eval_data.get("summary", "")
        dim_analysis = eval_data.get("dimension_analysis", {})
        problems = eval_data.get("problems", [])

        # Run score badge
        run_scores_str = " | ".join(
            f"{d.replace('_', ' ').title()}: {s}" for d, s in run_scores.items()
        )

        # Dimension analysis
        dim_html = ""
        if dim_analysis:
            dim_html = '<div style="margin:12px 0;">'
            for dim_name, analysis in dim_analysis.items():
                dim_html += (
                    f'<p><strong>{dim_name.replace("_", " ").title()}</strong>: '
                    f'{html.escape(analysis)}</p>'
                )
            dim_html += "</div>"

        # Problems
        problems_html = ""
        if problems:
            problems_html = '<h4 style="color:#c62828;margin-top:16px;">Problems Found</h4><ul style="margin:0;">'
            for p in problems:
                sev = p.get("severity", "?").upper()
                title = html.escape(p.get("title", ""))
                desc = html.escape(p.get("description", ""))
                quote = html.escape(p.get("quote", ""))
                root = p.get("root_cause", "?")
                sev_color = {"CRITICAL": "#c62828", "MAJOR": "#e65100", "MINOR": "#f9a825"}.get(sev, "#666")
                problems_html += (
                    f'<li style="margin-bottom:12px;">'
                    f'<span style="color:{sev_color};font-weight:bold;">[{sev}]</span> '
                    f'<strong>{title}</strong> <em>(root: {html.escape(root)})</em><br>'
                    f'<span style="color:#555;">{desc}</span>'
                )
                if quote:
                    problems_html += (
                        f'<br><blockquote style="margin:6px 0 0 0;padding:4px 12px;'
                        f'border-left:3px solid #ccc;color:#666;font-style:italic;">'
                        f'{quote}</blockquote>'
                    )
                problems_html += "</li>"
            problems_html += "</ul>"

        # Conversation transcript
        conv_html = ""
        conv_path = run_dir / "conversation.md"
        if conv_path.exists():
            try:
                conv_md = conv_path.read_text()
                conv_html = _markdown_conversation_to_html(conv_md)
            except Exception:
                conv_html = '<p style="color:#999;">Could not load conversation.</p>'

        run_sections += f"""
        <div style="margin-top:32px;border-top:3px solid #1565c0;padding-top:16px;">
            <h2 style="color:#1565c0;">{run_label} — Score: {run_score}/10</h2>
            <p style="color:#666;margin:4px 0;">{run_scores_str}</p>

            <h3>Evaluator Summary</h3>
            <p>{html.escape(summary)}</p>

            {dim_html}
            {problems_html}

            <details style="margin-top:20px;">
                <summary style="cursor:pointer;font-size:16px;font-weight:bold;color:#1565c0;">
                    Full Conversation Transcript
                </summary>
                <div style="margin-top:12px;">
                    {conv_html}
                </div>
            </details>
        </div>
        """

    # --- Prompt diff ---
    diff_escaped = html.escape(prompt_diff or "(no changes)")

    # --- Assemble full report ---
    status_color = {
        "KEEP": "#2e7d32", "DISCARD": "#c62828", "CRASH": "#c62828",
        "BASELINE": "#1565c0", "PENDING": "#f57f17",
    }.get(status_label, "#333")

    report_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Autoresearch #{iteration} — {status_label}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 900px; margin: 0 auto; padding: 24px; color: #333; line-height: 1.5; }}
        h1 {{ border-bottom: 2px solid #1565c0; padding-bottom: 8px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
        th {{ background: #f5f5f5; padding: 8px 16px; border: 1px solid #ddd; text-align: left; }}
        pre {{ background: #f5f5f5; padding: 16px; overflow-x: auto; font-size: 13px;
               border-radius: 4px; border: 1px solid #ddd; white-space: pre-wrap; word-wrap: break-word; }}
        .tutor-msg {{ background: #e3f2fd; border-left: 4px solid #1565c0; padding: 10px 14px;
                      margin: 8px 0; border-radius: 0 4px 4px 0; }}
        .student-msg {{ background: #fff3e0; border-left: 4px solid #e65100; padding: 10px 14px;
                        margin: 8px 0; border-radius: 0 4px 4px 0; }}
        .turn-label {{ font-weight: bold; font-size: 13px; color: #666; margin-bottom: 4px; }}
        details {{ border: 1px solid #ddd; border-radius: 4px; padding: 12px; background: #fafafa; }}
        summary {{ font-size: 16px; }}
    </style>
</head>
<body>
    <h1>Autoresearch Iteration #{iteration}</h1>

    <table>
        <tr><td style="padding:6px 16px;font-weight:bold;width:140px;">Status</td>
            <td style="padding:6px 16px;"><span style="color:{status_color};font-weight:bold;font-size:18px;">
            {status_label}</span></td></tr>
        <tr><td style="padding:6px 16px;font-weight:bold;">Hypothesis</td>
            <td style="padding:6px 16px;">{html.escape(description)}</td></tr>
        <tr><td style="padding:6px 16px;font-weight:bold;">Avg Score</td>
            <td style="padding:6px 16px;"><strong style="font-size:18px;">{avg_score:.2f}/10</strong>{delta_str}</td></tr>
    </table>

    <h2>Scores by Dimension</h2>
    <table>
        <tr style="background:#f5f5f5;">
            <th style="padding:8px 16px;border:1px solid #ddd;">Dimension</th>
            <th style="padding:8px 16px;border:1px solid #ddd;text-align:center;">Current</th>
            <th style="padding:8px 16px;border:1px solid #ddd;text-align:center;">Baseline</th>
            <th style="padding:8px 16px;border:1px solid #ddd;text-align:center;">Delta</th>
        </tr>
        {score_rows}
    </table>

    <h2>Prompt Changes</h2>
    <pre>{diff_escaped}</pre>

    {run_sections}
</body>
</html>"""

    return report_html


def _markdown_conversation_to_html(md_text: str) -> str:
    """Convert conversation.md to styled HTML with tutor/student message bubbles."""
    lines = md_text.split("\n")
    html_parts = []
    current_role = None
    current_turn = ""
    buffer = []

    for line in lines:
        if line.startswith("### [Turn"):
            # Flush previous buffer
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
            # Skip header lines
            continue
        else:
            buffer.append(line)

    # Flush last buffer
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


def send_iteration_report(
    iteration: int,
    description: str,
    status: str,
    scores: dict,
    baseline_scores: dict | None,
    avg_score: float,
    baseline_avg: float | None,
    problems_summary: list[str],
    prompt_diff: str,
    email_to: str | None = None,
    run_dirs: list[str] | None = None,
) -> bool:
    """Send email with plain-text summary + attached HTML report.

    Returns True if email sent successfully, False otherwise.
    """
    if not email_to:
        print("  [email] No recipient specified, skipping email.")
        return False

    status_labels = {"keep": "KEEP", "discard": "DISCARD", "crash": "CRASH", "baseline": "BASELINE"}
    status_label = status_labels.get(status, status.upper())

    delta = ""
    if baseline_avg is not None:
        diff = avg_score - baseline_avg
        arrow = "+" if diff > 0 else ""
        delta = f" ({arrow}{diff:.2f})"

    subject = f"[Autoresearch #{iteration}] {status_label} | {avg_score:.1f}/10{delta} — {description[:60]}"

    # Plain-text email body — brief summary
    scores_text = "\n".join(
        f"  {dim.replace('_', ' ').title():.<25} {score:.1f}/10"
        for dim, score in sorted(scores.items())
    )
    body_text = (
        f"Autoresearch Iteration #{iteration}\n"
        f"Status: {status_label}\n"
        f"Score: {avg_score:.2f}/10{delta}\n"
        f"Hypothesis: {description}\n\n"
        f"Scores:\n{scores_text}\n\n"
        f"Open the attached HTML report for the full picture —\n"
        f"conversation transcript, evaluation analysis, prompt diff, and problems found."
    )

    # Build comprehensive HTML report
    report_html = _build_html_report(
        iteration=iteration,
        description=description,
        status_label=status_label,
        scores=scores,
        baseline_scores=baseline_scores,
        avg_score=avg_score,
        baseline_avg=baseline_avg,
        prompt_diff=prompt_diff,
        run_dirs=run_dirs or [],
    )

    try:
        # Write HTML report to a temp file
        report_filename = f"autoresearch_{iteration}_{status_label.lower()}.html"
        report_path = Path(tempfile.gettempdir()) / report_filename
        report_path.write_text(report_html)

        # AppleScript: plain-text email with HTML file attachment
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
            print(f"  [email] Report sent to {email_to} (attached: {report_filename})")
            return True
        else:
            print(f"  [email] Mail.app error: {result.stderr.strip()}")
            return False

    except Exception as e:
        print(f"  [email] Failed to send: {e}")
        return False


def _escape_applescript(s: str) -> str:
    """Escape a string for use inside AppleScript double quotes."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
