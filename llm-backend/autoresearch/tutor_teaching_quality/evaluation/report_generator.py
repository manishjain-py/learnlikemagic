"""
Report Generator

Generates human-readable markdown reports and machine-readable JSON
for each evaluation run. Supports card phase content in transcripts.
"""

import json
from datetime import datetime
from pathlib import Path

from autoresearch.tutor_teaching_quality.evaluation.config import EvalConfig
from autoresearch.tutor_teaching_quality.evaluation.evaluator import CARD_PHASE_DIMENSIONS


class ReportGenerator:
    """Generates all run artifacts: conversation, review, and problems files."""

    def __init__(self, run_dir: Path, config: EvalConfig, started_at: str | None = None, persona: dict | None = None):
        self.run_dir = run_dir
        self.config = config
        self.started_at = started_at or datetime.now().isoformat()
        self.persona = persona

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

    def save_conversation_md(self, conversation: list[dict], card_phase_data: dict | None = None):
        lines = [
            "# Conversation Transcript",
            "",
            f"**Topic:** {self.config.topic_id}",
            f"**Tutor Model:** {self.config.tutor_model_label}",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Messages:** {len(conversation)}",
        ]

        # Add persona information if available
        if self.persona:
            lines.extend([
                f"**Student Persona:** {self.persona['name']} ({self.persona['persona_id']})",
                f"**Persona Description:** {self.persona.get('description', 'No description')}",
                f"**Correct Answer Probability:** {int(self.persona.get('correct_answer_probability', 0.6) * 100)}%",
            ])

        # Add card phase metadata if present
        if card_phase_data:
            cards = card_phase_data.get("cards", [])
            variant = card_phase_data.get("variant_key", "?")
            total = card_phase_data.get("total_variants", 1)
            lines.extend([
                f"**Card Phase:** Yes ({len(cards)} cards, variant {variant} of {total})",
            ])

        lines.extend([
            "",
            "---",
            "",
        ])

        # Render card phase section if cards exist in conversation
        card_entries = [m for m in conversation if m.get("role") == "explanation_card"]
        if card_entries:
            lines.extend([
                "## Explanation Cards (Pre-Session)",
                "",
                "*The student was shown these explanation cards before the interactive session began.*",
                "",
            ])
            for entry in card_entries:
                card = entry.get("card_data", {})
                card_idx = card.get("card_idx", "?")
                card_type = card.get("card_type", "")
                title = card.get("title", "")
                lines.append(f"### Card {card_idx} ({card_type}): {title}")
                lines.append("")
                lines.append(card.get("content", entry["content"]))
                visual = card.get("visual")
                if visual:
                    lines.extend(["", "```", visual, "```"])
                lines.append("")

            lines.extend([
                "---",
                "",
                "## Interactive Session",
                "",
            ])

        # Render dialogue entries
        for msg in conversation:
            role = msg.get("role", "unknown")
            if role == "explanation_card":
                continue  # Already rendered above

            turn = msg.get("turn", "?")
            phase = msg.get("phase", "")

            if role == "tutor":
                phase_suffix = ""
                if phase == "card_phase_welcome":
                    phase_suffix = " (Card Phase Welcome)"
                elif phase == "card_to_interactive_transition":
                    phase_suffix = " (Transition)"
                elif phase == "welcome":
                    phase_suffix = " (Welcome)"
                lines.append(f"### [Turn {turn}] TUTOR{phase_suffix}")
            elif role == "student":
                lines.append(f"### [Turn {turn}] STUDENT")
            else:
                lines.append(f"### [Turn {turn}] {role.upper()}")

            lines.append("")
            lines.append(msg["content"])
            lines.append("")

        path = self.run_dir / "conversation.md"
        with open(path, "w") as f:
            f.write("\n".join(lines))

    def save_conversation_json(self, conversation: list[dict], metadata: dict | None = None, card_phase_data: dict | None = None):
        data = {
            "config": self.config.to_dict(),
            "generated_at": datetime.now().isoformat(),
            "message_count": len(conversation),
            "has_card_phase": card_phase_data is not None,
            "card_phase_data": card_phase_data,
            "messages": conversation,
            "session_metadata": metadata or {},
        }

        path = self.run_dir / "conversation.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def save_review(self, evaluation: dict, has_card_phase: bool = False):
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
        ]

        if has_card_phase:
            lines.append("**Card Phase:** Yes (E2E evaluation)")

        # Add persona information if available
        if self.persona:
            lines.extend([
                f"**Student Persona:** {self.persona['name']} ({self.persona['persona_id']})",
                f"**Persona Description:** {self.persona.get('description', 'No description')}",
                f"**Correct Answer Probability:** {int(self.persona.get('correct_answer_probability', 0.6) * 100)}%",
            ])

        lines.extend([
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
        ])

        for dim, score in scores.items():
            display_name = dim.replace("_", " ").title()
            bar = _score_bar(score)
            # Mark card-phase-specific dimensions
            marker = " *" if dim in CARD_PHASE_DIMENSIONS else ""
            lines.append(f"| {display_name}{marker} | {score}/10 {bar} |")

        if has_card_phase:
            lines.append("")
            lines.append("*\\* Card-phase-specific dimension (only scored when explanation cards are present)*")

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
        ]

        # Add persona information if available
        if self.persona:
            lines.extend([
                f"**Student Persona:** {self.persona['name']} ({self.persona['persona_id']})",
                f"**Persona Description:** {self.persona.get('description', 'No description')}",
            ])

        lines.append("")

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
        "missed_student_signal": "Review how the tutor prompt handles student cues (confusion, boredom, confidence). Add explicit instructions to detect and respond to these signals.",
        "wrong_pacing": "Adjust the pacing directive logic — check mastery thresholds and attention span handling to better calibrate speed for different student types.",
        "repetitive_approach": "Strengthen the 'never repeat' teaching rule. Add variety tracking so the tutor tries different explanation styles (visual, story, analogy) on retry.",
        "emotional_mismatch": "Improve emotional attunement instructions in the tutor prompt. Calibrate praise to match difficulty and celebrate breakthroughs proportionally.",
        "missed_misconception": "Enhance misconception detection and tracking. Ensure the tutor probes confident wrong answers instead of simply correcting them.",
        "over_scaffolding": "Reduce hand-holding for students showing mastery. Let the pacing directive accelerate more aggressively when mastery signals are strong.",
        "conversation_history_window": "Increase the conversation history window or improve the turn summary to preserve conversational arc across the sliding window.",
        "prompt_quality": "Review and improve the relevant agent prompts for clarity, specificity, and natural language generation.",
        "model_capability": "This may be a model limitation. Consider testing with different models or adjusting temperature/sampling.",
        "card_content_ignored": "Improve the pre-computed explanation summary injection in master_tutor_prompts.py. The tutor should actively reference and build on card content, not just avoid repeating it.",
        "abrupt_transition": "Replace the hardcoded transition message with an LLM-generated bridge that references card content and probes understanding before jumping to practice.",
        "card_repetition": "Strengthen the 'DO NOT repeat' instruction in the precomputed_explanation_summary_section, or improve the summary to be more specific about what was covered.",
        "other": "Investigate the specific turns cited to determine whether this is a prompt, model, or architectural issue.",
    }
    return suggestions.get(cause, "")
