"""
Ingestion Evaluation Report Generator

Generates human-readable markdown reports and machine-readable JSON
for each book ingestion evaluation run.
"""

import json
from datetime import datetime
from pathlib import Path

from autoresearch.book_ingestion_quality.evaluation.config import IngestionEvalConfig


class IngestionReportGenerator:
    """Generates all run artifacts for a book ingestion evaluation."""

    def __init__(self, run_dir: Path, config: IngestionEvalConfig, started_at: str | None = None):
        self.run_dir = run_dir
        self.config = config
        self.started_at = started_at or datetime.now().isoformat()

    def save_config(self):
        config_data = self.config.to_dict()
        config_data["started_at"] = self.started_at
        with open(self.run_dir / "config.json", "w") as f:
            json.dump(config_data, f, indent=2)

    def save_pipeline_output(self, pipeline_output: dict):
        """Save the raw pipeline output (topics, pages, metadata)."""
        with open(self.run_dir / "pipeline_output.json", "w") as f:
            json.dump(pipeline_output, f, indent=2, default=str)

    def save_evaluation_json(self, evaluation: dict):
        scores = evaluation.get("scores", {})
        avg_score = sum(scores.values()) / len(scores) if scores else 0

        data = {
            "evaluated_at": datetime.now().isoformat(),
            "avg_score": round(avg_score, 2),
            "scores": scores,
            "dimension_analysis": evaluation.get("dimension_analysis", {}),
            "per_topic_assessment": evaluation.get("per_topic_assessment", []),
            "problems": evaluation.get("problems", []),
            "summary": evaluation.get("summary", ""),
        }

        with open(self.run_dir / "evaluation.json", "w") as f:
            json.dump(data, f, indent=2)

    def save_topics_md(self, pipeline_output: dict):
        """Save extracted topics as readable markdown."""
        chapter = pipeline_output["chapter"]
        book = pipeline_output["book_metadata"]
        topics = pipeline_output["topics"]

        lines = [
            "# Extracted Topics",
            "",
            f"**Book:** {book['title']}",
            f"**Subject:** {book['subject']} | **Grade:** {book['grade']} | **Board:** {book['board']}",
            f"**Chapter {chapter['chapter_number']}:** {chapter['chapter_title']}",
            f"**Pages:** {chapter.get('start_page', '?')} - {chapter.get('end_page', '?')}",
            f"**Extraction Mode:** {pipeline_output.get('extraction_mode', '?')}",
            f"**Total Topics:** {len(topics)}",
            "",
            "---",
            "",
        ]

        for i, topic in enumerate(topics, 1):
            lines.append(f"## {i}. {topic['topic_title']}")
            lines.append(f"**Key:** `{topic['topic_key']}`")
            lines.append(f"**Pages:** {topic.get('source_page_start', '?')} - {topic.get('source_page_end', '?')}")
            lines.append(f"**Sequence:** {topic.get('sequence_order', '?')}")
            lines.append("")
            lines.append("### Guidelines")
            lines.append(topic.get("guidelines", "(none)"))
            lines.append("")
            if topic.get("summary"):
                lines.append("### Summary")
                lines.append(topic["summary"])
                lines.append("")
            lines.append("---")
            lines.append("")

        with open(self.run_dir / "topics.md", "w") as f:
            f.write("\n".join(lines))

    def save_review(self, evaluation: dict, pipeline_output: dict):
        """Save the evaluation review as readable markdown."""
        scores = evaluation.get("scores", {})
        analysis = evaluation.get("dimension_analysis", {})
        per_topic = evaluation.get("per_topic_assessment", [])
        problems = evaluation.get("problems", [])
        summary = evaluation.get("summary", "No summary available.")

        chapter = pipeline_output["chapter"]
        book = pipeline_output["book_metadata"]
        avg_score = sum(scores.values()) / len(scores) if scores else 0

        lines = [
            "# Ingestion Evaluation Review",
            "",
            f"**Book:** {book['title']}",
            f"**Chapter {chapter['chapter_number']}:** {chapter['chapter_title']}",
            f"**Evaluator:** {self.config.evaluator_model_label}",
            f"**Average Score:** {avg_score:.1f}/10",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
            "## Summary",
            "",
            summary,
            "",
            "---",
            "",
            "## Scores",
            "",
            "| Dimension | Score |",
            "|-----------|-------|",
        ]

        for dim, score in scores.items():
            display = dim.replace("_", " ").title()
            bar = "#" * int(score) + "." * (10 - int(score))
            lines.append(f"| {display} | {score}/10 {bar} |")

        lines.extend(["", "---", "", "## Detailed Analysis", ""])

        for dim, text in analysis.items():
            display = dim.replace("_", " ").title()
            score = scores.get(dim, "?")
            lines.append(f"### {display} ({score}/10)")
            lines.append("")
            lines.append(text)
            lines.append("")

        # Per-topic assessment
        if per_topic:
            lines.extend(["---", "", "## Per-Topic Assessment", ""])
            lines.append("| Topic | Granularity | Guidelines OK | Copyright | Notes |")
            lines.append("|-------|------------|---------------|-----------|-------|")
            for t in per_topic:
                gran = t.get("granularity_verdict", "?")
                guide = "Y" if t.get("guidelines_sufficient") else "N"
                copy = "!" if t.get("copyright_concern") else "-"
                notes = t.get("notes", "")[:80]
                lines.append(f"| {t.get('topic_title', '?')} | {gran} | {guide} | {copy} | {notes} |")
            lines.append("")

        # Problems
        if problems:
            lines.extend(["---", "", "## Top Problems", ""])
            for i, prob in enumerate(problems, 1):
                severity = prob.get("severity", "unknown").upper()
                lines.append(f"### {i}. {prob.get('title', 'Untitled')} [{severity}]")
                lines.append("")
                lines.append(f"**Affected Topics:** {prob.get('affected_topics', [])}")
                lines.append(f"**Root Cause:** `{prob.get('root_cause', 'unknown')}`")
                lines.append("")
                lines.append(prob.get("description", ""))
                lines.append("")
                evidence = prob.get("evidence", "")
                if evidence:
                    lines.append(f"> {evidence}")
                    lines.append("")

        with open(self.run_dir / "review.md", "w") as f:
            f.write("\n".join(lines))
