"""
Session Experience Report Generator

Generates reports tailored to the session experience pipeline:
- Conversation transcript (same format as tutor_teaching_quality)
- Experience evaluation (flagged messages, naturalness score)
- Prompt analysis (root causes traced to specific instructions)
- Combined review for human consumption
"""

import json
from datetime import datetime
from pathlib import Path

from autoresearch.session_experience.evaluation.config import SessionExperienceConfig


class SessionExperienceReportGenerator:
    """Generates all run artifacts for the session experience pipeline."""

    def __init__(
        self,
        run_dir: Path,
        config: SessionExperienceConfig,
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
                phase_suffix = ""
                if phase:
                    phase_suffix = f" ({phase})"
                lines.append(f"### [Turn {turn}] TUTOR{phase_suffix}")
            elif role == "student":
                lines.append(f"### [Turn {turn}] STUDENT")
            else:
                lines.append(f"### [Turn {turn}] {role.upper()}")

            lines.extend(["", msg["content"], ""])

        with open(self.run_dir / "conversation.md", "w") as f:
            f.write("\n".join(lines))

    def save_experience_evaluation(self, evaluation: dict):
        """Save the naturalness evaluation results."""
        data = {
            "evaluated_at": datetime.now().isoformat(),
            "topic_name": self.topic_name,
            "naturalness_score": evaluation.get("overall_naturalness_score", 0),
            "issue_count_by_severity": evaluation.get("issue_count_by_severity", {}),
            "flagged_messages": evaluation.get("flagged_messages", []),
            "flow_assessment": evaluation.get("flow_assessment", ""),
            "strongest_moments": evaluation.get("strongest_moments", ""),
        }
        with open(self.run_dir / "experience_evaluation.json", "w") as f:
            json.dump(data, f, indent=2)

    def save_prompt_analysis(self, analysis: dict):
        """Save the prompt root-cause analysis."""
        with open(self.run_dir / "prompt_analysis.json", "w") as f:
            json.dump(analysis, f, indent=2)

    def save_review(self, evaluation: dict, analysis: dict):
        """Save combined human-readable review."""
        flagged = evaluation.get("flagged_messages", [])
        score = evaluation.get("overall_naturalness_score", "?")
        counts = evaluation.get("issue_count_by_severity", {})
        flow = evaluation.get("flow_assessment", "")
        strengths = evaluation.get("strongest_moments", "")

        lines = [
            "# Session Experience Review",
            "",
            f"**Topic:** {self.topic_name}",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Naturalness Score:** {score}/10",
            f"**Issues:** {counts.get('critical', 0)} critical, {counts.get('major', 0)} major, {counts.get('minor', 0)} minor",
            "",
            "---",
            "",
            "## Flow Assessment",
            "",
            flow,
            "",
            "## Strengths",
            "",
            strengths,
            "",
            "---",
            "",
            "## Flagged Messages",
            "",
        ]

        if not flagged:
            lines.append("No messages flagged.")
        else:
            for i, flag in enumerate(flagged, 1):
                severity = flag.get("severity", "?").upper()
                category = flag.get("issue_category", "unknown")
                turn = flag.get("turn", "?")

                lines.append(f"### {i}. Turn {turn} — {category} [{severity}]")
                lines.append("")
                lines.append(f"> {flag.get('message_snippet', '')}")
                lines.append("")
                lines.append(flag.get("description", ""))
                if flag.get("surrounding_context"):
                    lines.append(f"\n*Context:* {flag['surrounding_context']}")
                lines.append("")

        # Prompt analysis section
        analyses = analysis.get("analyses", [])
        patterns = analysis.get("cross_cutting_patterns", [])
        top_rec = analysis.get("top_recommendation", "")

        if analyses or patterns or top_rec:
            lines.extend(["---", "", "## Prompt Root-Cause Analysis", ""])

            if top_rec:
                lines.extend([
                    "### Top Recommendation",
                    "",
                    top_rec,
                    "",
                ])

            if patterns:
                lines.extend(["### Cross-Cutting Patterns", ""])
                for p in patterns:
                    priority = p.get("fix_priority", "?").upper()
                    lines.append(f"- **[{priority}]** {p.get('pattern', '')}")
                    lines.append(f"  Root cause: {p.get('root_cause', '')}")
                lines.append("")

            if analyses:
                lines.extend(["### Per-Message Analysis", ""])
                for a in analyses:
                    turn = a.get("turn", "?")
                    lines.append(f"**Turn {turn}** ({a.get('issue_category', '?')})")
                    for inst in a.get("root_instructions", []):
                        lines.append(f"  - Instruction: {inst.get('instruction', '')}")
                        lines.append(f"    Location: `{inst.get('location', '?')}`")
                        lines.append(f"    Mechanism: {inst.get('mechanism', '')}")
                    lines.append(f"  Fix: {a.get('suggested_fix', '')}")
                    lines.append(f"  Target: `{a.get('target_file', '?')}` ({a.get('fix_type', '?')})")
                    lines.append("")

        with open(self.run_dir / "review.md", "w") as f:
            f.write("\n".join(lines))

    def save_issues_summary(self, evaluation: dict):
        """Save a concise issues-only file for quick reference."""
        flagged = evaluation.get("flagged_messages", [])
        score = evaluation.get("overall_naturalness_score", "?")

        lines = [
            "# Issues Summary",
            "",
            f"**Naturalness Score:** {score}/10",
            f"**Total Issues:** {len(flagged)}",
            "",
        ]

        if flagged:
            # Group by category
            by_category: dict[str, list] = {}
            for flag in flagged:
                cat = flag.get("issue_category", "other")
                by_category.setdefault(cat, []).append(flag)

            lines.extend([
                "| Category | Count | Worst Severity |",
                "|----------|-------|----------------|",
            ])

            severity_order = {"critical": 0, "major": 1, "minor": 2}
            for cat, flags in sorted(by_category.items()):
                worst = min(flags, key=lambda f: severity_order.get(f.get("severity", "minor"), 3))
                lines.append(f"| {cat} | {len(flags)} | {worst.get('severity', '?')} |")

            lines.extend(["", "---", ""])

            for i, flag in enumerate(flagged, 1):
                sev = flag.get("severity", "?").upper()
                lines.append(f"{i}. **[{sev}]** Turn {flag.get('turn', '?')} — {flag.get('issue_category', '?')}: {flag.get('description', '')}")
        else:
            lines.append("No issues found.")

        with open(self.run_dir / "issues.md", "w") as f:
            f.write("\n".join(lines))
