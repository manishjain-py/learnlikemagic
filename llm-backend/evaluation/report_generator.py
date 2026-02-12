"""
Report Generator

Generates human-readable markdown reports and machine-readable JSON
for each evaluation run.
"""

import json
from datetime import datetime
from pathlib import Path

from evaluation.config import EvalConfig


class ReportGenerator:
    """Generates all run artifacts: conversation, review, and problems files."""

    def __init__(self, run_dir: Path, config: EvalConfig, started_at: str | None = None):
        self.run_dir = run_dir
        self.config = config
        self.started_at = started_at or datetime.now().isoformat()

    def save_config(self):
        config_data = self.config.to_dict()
        config_data["started_at"] = self.started_at
        config_path = self.run_dir / "config.json"
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)

    def save_evaluation_json(self, evaluation: dict):
        scores = evaluation.get("scores", {})
        avg_score = sum(scores.values()) / len(scores) if scores else 0

        data = {
            "evaluated_at": datetime.now().isoformat(),
            "avg_score": round(avg_score, 2),
            "scores": scores,
            "dimension_analysis": evaluation.get("dimension_analysis", {}),
            "problems": evaluation.get("problems", []),
            "summary": evaluation.get("summary", ""),
        }

        path = self.run_dir / "evaluation.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def save_conversation_md(self, conversation: list[dict]):
        lines = [
            "# Conversation Transcript",
            "",
            f"**Topic:** {self.config.topic_id}",
            f"**Tutor Model:** {self.config.tutor_model_label}",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Messages:** {len(conversation)}",
            "",
            "---",
            "",
        ]

        for msg in conversation:
            role = "TUTOR" if msg["role"] == "tutor" else "STUDENT"
            turn = msg.get("turn", "?")
            lines.append(f"### [Turn {turn}] {role}")
            lines.append("")
            lines.append(msg["content"])
            lines.append("")

        path = self.run_dir / "conversation.md"
        with open(path, "w") as f:
            f.write("\n".join(lines))

    def save_conversation_json(self, conversation: list[dict], metadata: dict | None = None):
        data = {
            "config": self.config.to_dict(),
            "generated_at": datetime.now().isoformat(),
            "message_count": len(conversation),
            "messages": conversation,
            "session_metadata": metadata or {},
        }

        path = self.run_dir / "conversation.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def save_review(self, evaluation: dict):
        scores = evaluation.get("scores", {})
        analysis = evaluation.get("dimension_analysis", {})
        problems = evaluation.get("problems", [])
        summary = evaluation.get("summary", "No summary available.")

        avg_score = sum(scores.values()) / len(scores) if scores else 0

        lines = [
            "# Evaluation Review",
            "",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Topic:** {self.config.topic_id}",
            f"**Tutor Model:** {self.config.tutor_model_label}",
            f"**Evaluator Model:** {self.config.evaluator_model_label}",
            f"**Average Score:** {avg_score:.1f}/10",
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
            display_name = dim.replace("_", " ").title()
            bar = _score_bar(score)
            lines.append(f"| {display_name} | {score}/10 {bar} |")

        lines.extend(["", "---", "", "## Detailed Analysis", ""])

        for dim, text in analysis.items():
            display_name = dim.replace("_", " ").title()
            score = scores.get(dim, "?")
            lines.append(f"### {display_name} ({score}/10)")
            lines.append("")
            lines.append(text)
            lines.append("")

        if problems:
            lines.extend(["---", "", "## Top Problems", ""])
            for i, prob in enumerate(problems, 1):
                severity = prob.get("severity", "unknown").upper()
                lines.append(f"### {i}. {prob.get('title', 'Untitled')} [{severity}]")
                lines.append("")
                lines.append(f"**Turns:** {prob.get('turns', [])}")
                lines.append(f"**Root Cause:** `{prob.get('root_cause', 'unknown')}`")
                lines.append("")
                lines.append(prob.get("description", ""))
                lines.append("")
                quote = prob.get("quote", "")
                if quote:
                    lines.append(f"> {quote}")
                    lines.append("")

        path = self.run_dir / "review.md"
        with open(path, "w") as f:
            f.write("\n".join(lines))

    def save_problems(self, evaluation: dict):
        problems = evaluation.get("problems", [])

        lines = [
            "# Identified Problems",
            "",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Topic:** {self.config.topic_id}",
            "",
        ]

        if problems:
            lines.extend([
                "## Overview",
                "",
                "| # | Problem | Severity | Root Cause |",
                "|---|---------|----------|------------|",
            ])
            for i, prob in enumerate(problems, 1):
                lines.append(
                    f"| {i} | {prob.get('title', 'Untitled')} | {prob.get('severity', '?')} | `{prob.get('root_cause', '?')}` |"
                )
            lines.extend(["", "---", ""])

        cause_counts: dict[str, int] = {}
        for prob in problems:
            cause = prob.get("root_cause", "other")
            cause_counts[cause] = cause_counts.get(cause, 0) + 1

        if cause_counts:
            lines.extend(["## Root Cause Distribution", ""])
            for cause, count in sorted(cause_counts.items(), key=lambda x: -x[1]):
                lines.append(f"- **{cause}**: {count} problem(s)")
            lines.extend(["", "---", ""])

        lines.extend(["## Detailed Problems", ""])
        for i, prob in enumerate(problems, 1):
            severity = prob.get("severity", "unknown").upper()
            lines.append(f"### {i}. {prob.get('title', 'Untitled')}")
            lines.append("")
            lines.append(f"- **Severity:** {severity}")
            lines.append(f"- **Turns:** {prob.get('turns', [])}")
            lines.append(f"- **Root Cause:** `{prob.get('root_cause', 'unknown')}`")
            lines.append("")
            lines.append(f"**Description:** {prob.get('description', '')}")
            lines.append("")
            quote = prob.get("quote", "")
            if quote:
                lines.append(f"**Evidence:**")
                lines.append(f"> {quote}")
                lines.append("")

            cause = prob.get("root_cause", "other")
            suggestion = _root_cause_suggestion(cause)
            if suggestion:
                lines.append(f"**Suggested Fix:** {suggestion}")
                lines.append("")

        if not problems:
            lines.append("No problems identified.")

        path = self.run_dir / "problems.md"
        with open(path, "w") as f:
            f.write("\n".join(lines))


def _score_bar(score: int) -> str:
    filled = int(score)
    empty = 10 - filled
    return "#" * filled + "." * empty


def _root_cause_suggestion(cause: str) -> str:
    suggestions = {
        "conversation_history_window": "Increase the conversation history window or implement better context compression that preserves conversational arc.",
        "session_summary_lossy": "Improve session summary to capture narrative context (how things flowed) not just facts (what happened).",
        "multi_agent_composition": "Improve response composition to feel holistic rather than stitched together from multiple specialist outputs.",
        "turn_level_processing": "Add session-level narrative tracking so each turn decision considers the broader conversation trajectory.",
        "rigid_study_plan": "Make the study plan more adaptive -- allow lingering on difficult concepts and skipping ahead when understood.",
        "prompt_quality": "Review and improve the relevant agent prompts for clarity, specificity, and natural language generation.",
        "model_capability": "This may be a model limitation. Consider testing with different models or adjusting temperature/sampling.",
    }
    return suggestions.get(cause, "")
