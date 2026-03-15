"""
Autoresearch Email Reports

Sends compact iteration reports via macOS Mail app using osascript.
No SMTP credentials needed — uses the default Mail account.
"""

import html
import subprocess
import tempfile
from pathlib import Path


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
) -> bool:
    """Send a compact HTML iteration report email via macOS Mail.

    Returns True if email sent successfully, False otherwise.
    """
    if not email_to:
        print("  [email] No recipient specified, skipping email.")
        return False

    delta = ""
    if baseline_avg is not None:
        diff = avg_score - baseline_avg
        arrow = "+" if diff > 0 else ""
        delta = f" ({arrow}{diff:.2f})"

    status_labels = {"keep": "KEEP", "discard": "DISCARD", "crash": "CRASH", "baseline": "BASELINE"}
    status_label = status_labels.get(status, status.upper())

    # Build score rows
    score_rows = ""
    dimensions = list(scores.keys()) if scores else []
    for dim in dimensions:
        current = scores.get(dim, 0)
        dim_label = dim.replace("_", " ").title()
        if baseline_scores and dim in baseline_scores:
            base = baseline_scores[dim]
            d = current - base
            arrow = "+" if d > 0 else ""
            score_rows += f"<tr><td>{dim_label}</td><td>{current:.1f}</td><td>{base:.1f}</td><td>{arrow}{d:.1f}</td></tr>\n"
        else:
            score_rows += f"<tr><td>{dim_label}</td><td>{current:.1f}</td><td>-</td><td>-</td></tr>\n"

    # Build problems list
    problems_html = ""
    if problems_summary:
        problems_html = "<h3>Top Problems</h3><ul>"
        for p in problems_summary[:5]:
            problems_html += f"<li>{html.escape(p)}</li>"
        problems_html += "</ul>"

    # Truncate diff for email
    diff_display = prompt_diff[:2000] + "\n..." if len(prompt_diff) > 2000 else prompt_diff
    diff_escaped = html.escape(diff_display)

    subject = f"[Autoresearch #{iteration}] {status_label} | {avg_score:.1f}/10{delta} — {description[:60]}"

    body_html = f"""<html><body style="font-family: monospace; font-size: 14px; max-width: 700px;">
<h2>Autoresearch Iteration #{iteration}</h2>
<table style="border-collapse: collapse; margin-bottom: 16px;">
<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">Status</td><td>{status_label}</td></tr>
<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">Description</td><td>{html.escape(description)}</td></tr>
<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">Avg Score</td><td><b>{avg_score:.2f}/10</b>{delta}</td></tr>
</table>

<h3>Scores by Dimension</h3>
<table style="border-collapse: collapse; border: 1px solid #ccc;">
<tr style="background: #f0f0f0;">
<th style="padding: 4px 12px; border: 1px solid #ccc;">Dimension</th>
<th style="padding: 4px 12px; border: 1px solid #ccc;">Current</th>
<th style="padding: 4px 12px; border: 1px solid #ccc;">Baseline</th>
<th style="padding: 4px 12px; border: 1px solid #ccc;">Delta</th>
</tr>
{score_rows}
</table>

{problems_html}

<h3>Prompt Changes</h3>
<pre style="background: #f5f5f5; padding: 12px; overflow-x: auto; font-size: 12px; max-height: 400px; overflow-y: auto;">{diff_escaped}</pre>
</body></html>"""

    # Write HTML to a temp file, then use osascript to send via Mail.app
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(body_html)
            html_path = f.name

        # AppleScript to create and send email via Mail.app
        # Use 'html content' property so Mail.app renders HTML instead of showing raw tags
        applescript = f'''
tell application "Mail"
    set htmlContent to (read POSIX file "{html_path}")
    set newMessage to make new outgoing message with properties {{subject:"{_escape_applescript(subject)}", visible:false}}
    set html content of newMessage to htmlContent
    tell newMessage
        make new to recipient at end of to recipients with properties {{address:"{_escape_applescript(email_to)}"}}
    end tell
    send newMessage
end tell
'''
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True, text=True, timeout=30,
        )

        # Clean up temp file
        Path(html_path).unlink(missing_ok=True)

        if result.returncode == 0:
            print(f"  [email] Report sent to {email_to} via Mail.app")
            return True
        else:
            print(f"  [email] Mail.app error: {result.stderr.strip()}")
            return False

    except Exception as e:
        print(f"  [email] Failed to send: {e}")
        return False


def _escape_applescript(s: str) -> str:
    """Escape a string for use inside AppleScript double quotes."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
