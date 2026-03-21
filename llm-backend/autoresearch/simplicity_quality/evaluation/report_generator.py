"""
Simplicity Quality Report Generator

Generates run artifacts for the simplicity pipeline:
- Conversation transcript (reuses session_experience format)
- Simplicity evaluation (scores, flagged messages)
- Combined review for human consumption
"""

import json
from datetime import datetime
from pathlib import Path

from autoresearch.simplicity_quality.evaluation.config import SimplicityConfig


class SimplicityReportGenerator:
    """Generates all run artifacts for the simplicity pipeline."""

    def __init__(
        self,
        run_dir: Path,
        config: SimplicityConfig,
        topic_name: str = "",
        started_at: str | None = None,
        persona: dict | None = None,
    ):
        self.run_dir = run_dir
        self.config = config
        self.topic_name = topic_name
        self.started_at = started_at or datetime.now().isoformat()
        self.persona = persona

    def save_config(self):
        data = self.config.to_dict()
        data["started_at"] = self.started_at
        data["topic_name"] = self.topic_name
        with open(self.run_dir / "config.json", "w") as f:
            json.dump(data, f, indent=2)

    def save_conversation_json(
        self,
        conversation: list[dict],
        prompts: list[dict],
        metadata: dict | None = None,
        card_phase_data: dict | None = None,
    ):
        data = {
            "config": self.config.to_dict(),
            "topic_name": self.topic_name,
            "generated_at": datetime.now().isoformat(),
            "message_count": len(conversation),
            "has_card_phase": card_phase_data is not None,
            "card_phase_data": card_phase_data,
            "messages": conversation,
            "master_tutor_prompts": prompts,
            "session_metadata": metadata or {},
        }
        with open(self.run_dir / "conversation.json", "w") as f:
            json.dump(data, f, indent=2)

    def save_conversation_md(self, conversation: list[dict], card_phase_data: dict | None = None):
        lines = [
            "# Conversation Transcript",
            "",
            f"**Topic:** {self.topic_name} ({self.config.topic_id})",
            f"**Tutor Model:** {self.config.tutor_model_label}",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Messages:** {len(conversation)}",
        ]

        if self.persona:
            lines.append(f"**Student:** {self.persona['name']} ({self.persona.get('persona_id', '?')})")

        if card_phase_data:
            cards = card_phase_data.get("cards", [])
            variant = card_phase_data.get("variant_key", "?")
            lines.append(f"**Card Phase:** {len(cards)} cards, variant {variant}")

        lines.extend(["", "---", ""])

        # Render cards
        card_entries = [m for m in conversation if m.get("role") == "explanation_card"]
        if card_entries:
            lines.extend(["## Explanation Cards", ""])
            for entry in card_entries:
                card = entry.get("card_data", {})
                title = card.get("title", "")
                card_type = card.get("card_type", "")
                lines.append(f"### Card {card.get('card_idx', '?')} ({card_type}): {title}")
                lines.append("")
                lines.append(card.get("content", entry["content"]))
                lines.append("")
            lines.extend(["---", ""])

        # Render dialogue
        for msg in conversation:
            role = msg.get("role", "unknown")
            if role == "explanation_card":
                continue
            turn = msg.get("turn", "?")
            phase = msg.get("phase", "")

            if role == "tutor":
                phase_suffix = f" ({phase})" if phase else ""
                lines.append(f"### [Turn {turn}] TUTOR{phase_suffix}")
            elif role == "student":
                lines.append(f"### [Turn {turn}] STUDENT")
            else:
                lines.append(f"### [Turn {turn}] {role.upper()}")

            lines.extend(["", msg["content"], ""])

        with open(self.run_dir / "conversation.md", "w") as f:
            f.write("\n".join(lines))

    def save_simplicity_evaluation(self, evaluation: dict):
        """Save the simplicity evaluation results."""
        data = {
            "evaluated_at": datetime.now().isoformat(),
            "topic_name": self.topic_name,
            "overall_simplicity_score": evaluation.get("overall_simplicity_score", 0),
            "card_phase_simplicity": evaluation.get("card_phase_simplicity"),
            "interactive_tutor_simplicity": evaluation.get("interactive_tutor_simplicity", 0),
            "relatability": evaluation.get("relatability", 0),
            "progressive_building": evaluation.get("progressive_building", 0),
            "issue_count_by_severity": evaluation.get("issue_count_by_severity", {}),
            "flagged_messages": evaluation.get("flagged_messages", []),
            "simplicity_assessment": evaluation.get("simplicity_assessment", ""),
            "strongest_simplicity_moments": evaluation.get("strongest_simplicity_moments", ""),
        }
        with open(self.run_dir / "simplicity_evaluation.json", "w") as f:
            json.dump(data, f, indent=2)

    def save_review(self, evaluation: dict):
        """Save combined human-readable review."""
        flagged = evaluation.get("flagged_messages", [])
        overall = evaluation.get("overall_simplicity_score", "?")
        card_score = evaluation.get("card_phase_simplicity")
        tutor_score = evaluation.get("interactive_tutor_simplicity", "?")
        relatability = evaluation.get("relatability", "?")
        progressive = evaluation.get("progressive_building", "?")
        counts = evaluation.get("issue_count_by_severity", {})
        assessment = evaluation.get("simplicity_assessment", "")
        strengths = evaluation.get("strongest_simplicity_moments", "")

        lines = [
            "# Simplicity Quality Review",
            "",
            f"**Topic:** {self.topic_name}",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Overall Simplicity:** {overall}/10",
        ]
        if card_score is not None:
            lines.append(f"**Card Phase Simplicity:** {card_score}/10")
        lines.extend([
            f"**Interactive Tutor Simplicity:** {tutor_score}/10",
            f"**Relatability:** {relatability}/10",
            f"**Progressive Building:** {progressive}/10",
            f"**Issues:** {counts.get('critical', 0)} critical, {counts.get('major', 0)} major, {counts.get('minor', 0)} minor",
            "",
            "---",
            "",
            "## Simplicity Assessment",
            "",
            assessment,
            "",
            "## Strongest Simplicity Moments",
            "",
            strengths,
            "",
            "---",
            "",
            "## Flagged Messages",
            "",
        ])

        if not flagged:
            lines.append("No messages flagged — everything is radically simple!")
        else:
            for i, flag in enumerate(flagged, 1):
                severity = flag.get("severity", "?").upper()
                msg_type = flag.get("message_type", "?")
                turn = flag.get("turn", "?")

                lines.append(f"### {i}. {msg_type.upper()} — Turn {turn} [{severity}]")
                lines.append("")
                lines.append(f"> {flag.get('message_snippet', '')}")
                lines.append("")
                lines.append(f"**Too complex:** {flag.get('complex_part', '')}")
                lines.append(f"**Why:** {flag.get('why_complex', '')}")
                lines.append(f"**Simplify to:** {flag.get('simplification', '')}")
                lines.append("")

        with open(self.run_dir / "review.md", "w") as f:
            f.write("\n".join(lines))
