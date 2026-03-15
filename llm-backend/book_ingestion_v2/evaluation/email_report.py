"""
Book Ingestion Evaluation Email Reports

Sends a plain-text summary email with a comprehensive HTML report attached.
The HTML report includes: scores, dimension analysis, per-topic assessment,
extracted topics, problems found, and original page texts.

Uses macOS Mail app via osascript — no SMTP credentials needed.
"""

import html
import json
import subprocess
import tempfile
from pathlib import Path


def _build_html_report(
    description: str,
    status_label: str,
    scores: dict,
    baseline_scores: dict | None,
    avg_score: float,
    baseline_avg: float | None,
    chapter_info: dict,
    book_metadata: dict,
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

    # --- Per-run sections ---
    run_sections = ""
    for i, run_dir_str in enumerate(run_dirs, 1):
        run_dir = Path(run_dir_str)
        run_label = f"Run {i}" if len(run_dirs) > 1 else "Evaluation"

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
        per_topic = eval_data.get("per_topic_assessment", [])
        problems = eval_data.get("problems", [])

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
                    f'{html.escape(str(analysis))}</p>'
                )
            dim_html += "</div>"

        # Per-topic assessment table
        topic_html = ""
        if per_topic:
            topic_html = '<h4 style="margin-top:16px;">Per-Topic Assessment</h4>'
            topic_html += (
                '<table style="border-collapse:collapse;width:100%;font-size:13px;">'
                '<tr style="background:#f5f5f5;">'
                '<th style="padding:6px 10px;border:1px solid #ddd;text-align:left;">Topic</th>'
                '<th style="padding:6px 10px;border:1px solid #ddd;text-align:center;">Granularity</th>'
                '<th style="padding:6px 10px;border:1px solid #ddd;text-align:center;">Guidelines</th>'
                '<th style="padding:6px 10px;border:1px solid #ddd;text-align:center;">Copyright</th>'
                '<th style="padding:6px 10px;border:1px solid #ddd;text-align:left;">Notes</th>'
                '</tr>'
            )
            for t in per_topic:
                gran = t.get("granularity_verdict", "?")
                gran_color = {"just_right": "#2e7d32", "too_broad": "#e65100", "too_narrow": "#1565c0"}.get(gran, "#333")
                guide_ok = t.get("guidelines_sufficient", True)
                guide_icon = "&#10004;" if guide_ok else "&#10008;"
                guide_color = "#2e7d32" if guide_ok else "#c62828"
                copy_flag = t.get("copyright_concern", False)
                copy_icon = "&#9888;" if copy_flag else "&#10004;"
                copy_color = "#c62828" if copy_flag else "#2e7d32"
                notes = html.escape(t.get("notes", ""))[:120]
                topic_title = html.escape(t.get("topic_title", "?"))

                topic_html += (
                    f'<tr>'
                    f'<td style="padding:6px 10px;border:1px solid #ddd;">{topic_title}</td>'
                    f'<td style="padding:6px 10px;border:1px solid #ddd;text-align:center;color:{gran_color};">{gran}</td>'
                    f'<td style="padding:6px 10px;border:1px solid #ddd;text-align:center;color:{guide_color};">{guide_icon}</td>'
                    f'<td style="padding:6px 10px;border:1px solid #ddd;text-align:center;color:{copy_color};">{copy_icon}</td>'
                    f'<td style="padding:6px 10px;border:1px solid #ddd;font-size:12px;color:#555;">{notes}</td>'
                    f'</tr>'
                )
            topic_html += '</table>'

        # Problems
        problems_html = ""
        if problems:
            problems_html = '<h4 style="color:#c62828;margin-top:16px;">Problems Found</h4><ul style="margin:0;">'
            for p in problems:
                sev = p.get("severity", "?").upper()
                title = html.escape(p.get("title", ""))
                desc = html.escape(p.get("description", ""))
                evidence = html.escape(p.get("evidence", ""))
                root = p.get("root_cause", "?")
                affected = p.get("affected_topics", [])
                sev_color = {"CRITICAL": "#c62828", "MAJOR": "#e65100", "MINOR": "#f9a825"}.get(sev, "#666")
                problems_html += (
                    f'<li style="margin-bottom:12px;">'
                    f'<span style="color:{sev_color};font-weight:bold;">[{sev}]</span> '
                    f'<strong>{title}</strong> <em>(root: {html.escape(root)})</em><br>'
                    f'<span style="color:#555;">{desc}</span>'
                )
                if affected:
                    problems_html += f'<br><span style="color:#888;font-size:12px;">Topics: {html.escape(", ".join(affected))}</span>'
                if evidence:
                    problems_html += (
                        f'<br><blockquote style="margin:6px 0 0 0;padding:4px 12px;'
                        f'border-left:3px solid #ccc;color:#666;font-style:italic;">'
                        f'{evidence}</blockquote>'
                    )
                problems_html += "</li>"
            problems_html += "</ul>"

        # Extracted topics (collapsible)
        topics_html = ""
        topics_path = run_dir / "topics.md"
        if topics_path.exists():
            try:
                topics_md = topics_path.read_text()
                topics_html = f'<pre style="font-size:12px;max-height:600px;overflow-y:auto;">{html.escape(topics_md)}</pre>'
            except Exception:
                topics_html = '<p style="color:#999;">Could not load topics.</p>'

        run_sections += f"""
        <div style="margin-top:32px;border-top:3px solid #1565c0;padding-top:16px;">
            <h2 style="color:#1565c0;">{run_label} — Score: {run_score}/10</h2>
            <p style="color:#666;margin:4px 0;">{run_scores_str}</p>

            <h3>Summary</h3>
            <p>{html.escape(summary)}</p>

            {dim_html}
            {topic_html}
            {problems_html}

            <details style="margin-top:20px;">
                <summary style="cursor:pointer;font-size:16px;font-weight:bold;color:#1565c0;">
                    Extracted Topics (Full)
                </summary>
                <div style="margin-top:12px;">
                    {topics_html}
                </div>
            </details>
        </div>
        """

    # --- Chapter info header ---
    ch_title = html.escape(chapter_info.get("chapter_title", "?"))
    ch_num = chapter_info.get("chapter_number", "?")
    book_title = html.escape(book_metadata.get("title", "?"))
    subject = html.escape(book_metadata.get("subject", "?"))
    grade = html.escape(str(book_metadata.get("grade", "?")))

    status_color = {
        "KEEP": "#2e7d32", "DISCARD": "#c62828", "CRASH": "#c62828",
        "BASELINE": "#1565c0", "PENDING": "#f57f17",
    }.get(status_label, "#333")

    report_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Ingestion Eval — Ch{ch_num}: {ch_title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 900px; margin: 0 auto; padding: 24px; color: #333; line-height: 1.5; }}
        h1 {{ border-bottom: 2px solid #1565c0; padding-bottom: 8px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
        th {{ background: #f5f5f5; padding: 8px 16px; border: 1px solid #ddd; text-align: left; }}
        pre {{ background: #f5f5f5; padding: 16px; overflow-x: auto; font-size: 13px;
               border-radius: 4px; border: 1px solid #ddd; white-space: pre-wrap; word-wrap: break-word; }}
        details {{ border: 1px solid #ddd; border-radius: 4px; padding: 12px; background: #fafafa; }}
        summary {{ font-size: 16px; }}
    </style>
</head>
<body>
    <h1>Book Ingestion Evaluation</h1>

    <table>
        <tr><td style="padding:6px 16px;font-weight:bold;width:140px;">Book</td>
            <td style="padding:6px 16px;">{book_title} ({subject}, Grade {grade})</td></tr>
        <tr><td style="padding:6px 16px;font-weight:bold;">Chapter</td>
            <td style="padding:6px 16px;">Ch{ch_num}: {ch_title}</td></tr>
        <tr><td style="padding:6px 16px;font-weight:bold;">Status</td>
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

    {run_sections}
</body>
</html>"""

    return report_html


def send_ingestion_report(
    description: str,
    status: str,
    scores: dict,
    baseline_scores: dict | None,
    avg_score: float,
    baseline_avg: float | None,
    chapter_info: dict,
    book_metadata: dict,
    email_to: str | None = None,
    run_dirs: list[str] | None = None,
) -> bool:
    """Send email with plain-text summary + attached HTML report."""
    if not email_to:
        print("  [email] No recipient specified, skipping email.")
        return False

    status_labels = {"keep": "KEEP", "discard": "DISCARD", "crash": "CRASH", "baseline": "BASELINE", "pending": "PENDING"}
    status_label = status_labels.get(status, status.upper())

    ch_num = chapter_info.get("chapter_number", "?")
    ch_title = chapter_info.get("chapter_title", "?")

    delta = ""
    if baseline_avg is not None:
        diff = avg_score - baseline_avg
        arrow = "+" if diff > 0 else ""
        delta = f" ({arrow}{diff:.2f})"

    subject = f"[Ingestion Eval] {status_label} | {avg_score:.1f}/10{delta} — Ch{ch_num}: {ch_title}"

    scores_text = "\n".join(
        f"  {dim.replace('_', ' ').title():.<25} {score:.1f}/10"
        for dim, score in sorted(scores.items())
    )
    body_text = (
        f"Book Ingestion Evaluation\n"
        f"Chapter: Ch{ch_num} — {ch_title}\n"
        f"Status: {status_label}\n"
        f"Score: {avg_score:.2f}/10{delta}\n"
        f"Description: {description}\n\n"
        f"Scores:\n{scores_text}\n\n"
        f"Open the attached HTML report for the full evaluation —\n"
        f"per-topic assessment, extracted topics, problems found."
    )

    report_html = _build_html_report(
        description=description,
        status_label=status_label,
        scores=scores,
        baseline_scores=baseline_scores,
        avg_score=avg_score,
        baseline_avg=baseline_avg,
        chapter_info=chapter_info,
        book_metadata=book_metadata,
        run_dirs=run_dirs or [],
    )

    try:
        report_filename = f"ingestion_eval_ch{ch_num}_{status_label.lower()}.html"
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
