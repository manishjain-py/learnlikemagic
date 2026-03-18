"""
Autoresearch Email Reports — Explanation Quality

Sends a plain-text summary email with a comprehensive HTML report attached.
Uses macOS Mail app via osascript — no SMTP credentials needed.
"""

import html
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
    topic_title: str,
) -> str:
    """Build HTML report for explanation quality evaluation."""

    delta_str = ""
    if baseline_avg is not None:
        diff = avg_score - baseline_avg
        arrow = "+" if diff > 0 else ""
        delta_str = f" ({arrow}{diff:.2f})"

    # Score table
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

    # Prompt diff
    diff_escaped = html.escape(prompt_diff or "(no changes)")

    status_color = {
        "KEEP": "#2e7d32", "DISCARD": "#c62828", "CRASH": "#c62828",
        "BASELINE": "#1565c0", "PENDING": "#f57f17",
    }.get(status_label, "#333")

    report_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Explanation Quality #{iteration} — {status_label}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 900px; margin: 0 auto; padding: 24px; color: #333; line-height: 1.5; }}
        h1 {{ border-bottom: 2px solid #1565c0; padding-bottom: 8px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
        th {{ background: #f5f5f5; padding: 8px 16px; border: 1px solid #ddd; text-align: left; }}
        pre {{ background: #f5f5f5; padding: 16px; overflow-x: auto; font-size: 13px;
               border-radius: 4px; border: 1px solid #ddd; white-space: pre-wrap; word-wrap: break-word; }}
    </style>
</head>
<body>
    <h1>Explanation Quality — Iteration #{iteration}</h1>

    <table>
        <tr><td style="padding:6px 16px;font-weight:bold;width:140px;">Status</td>
            <td style="padding:6px 16px;"><span style="color:{status_color};font-weight:bold;font-size:18px;">
            {status_label}</span></td></tr>
        <tr><td style="padding:6px 16px;font-weight:bold;">Hypothesis</td>
            <td style="padding:6px 16px;">{html.escape(description)}</td></tr>
        <tr><td style="padding:6px 16px;font-weight:bold;">Topic</td>
            <td style="padding:6px 16px;">{html.escape(topic_title)}</td></tr>
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
</body>
</html>"""

    return report_html


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
    topic_title: str = "",
) -> bool:
    """Send email with plain-text summary + attached HTML report."""
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

    subject = f"[ExplQuality #{iteration}] {status_label} | {avg_score:.1f}/10{delta} — {description[:60]}"

    scores_text = "\n".join(
        f"  {dim.replace('_', ' ').title():.<30} {score:.1f}/10"
        for dim, score in sorted(scores.items())
    )
    body_text = (
        f"Explanation Quality Iteration #{iteration}\n"
        f"Status: {status_label}\n"
        f"Topic: {topic_title}\n"
        f"Score: {avg_score:.2f}/10{delta}\n"
        f"Hypothesis: {description}\n\n"
        f"Scores:\n{scores_text}\n\n"
        f"Open the attached HTML report for the full picture."
    )

    report_html = _build_html_report(
        iteration=iteration,
        description=description,
        status_label=status_label,
        scores=scores,
        baseline_scores=baseline_scores,
        avg_score=avg_score,
        baseline_avg=baseline_avg,
        prompt_diff=prompt_diff,
        topic_title=topic_title,
    )

    try:
        report_filename = f"expl_quality_{iteration}_{status_label.lower()}.html"
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
