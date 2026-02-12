"""
Prompt construction utilities.

Provides reusable functions for formatting conversation history,
building context sections, and other prompt helpers.
"""

from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tutor.models.messages import Message, StudentContext


def format_conversation_history(
    messages: list["Message"],
    max_turns: int = 5,
    include_role: bool = True,
) -> str:
    """Format conversation history for inclusion in prompts."""
    if not messages:
        return "No conversation history."

    recent = messages[-max_turns:]
    lines = []
    for msg in recent:
        role_prefix = f"{msg.role.capitalize()}: " if include_role else ""
        lines.append(f"{role_prefix}{msg.content}")

    return "\n".join(lines)


def build_context_section(
    student_context: "StudentContext",
    mastery_estimates: dict[str, float],
) -> str:
    """Build a context section for prompts with student info and mastery."""
    mastery_lines = []
    for concept, score in mastery_estimates.items():
        level = _mastery_score_to_label(score)
        mastery_lines.append(f"  - {concept}: {level} ({score:.0%})")

    mastery_section = (
        "\n".join(mastery_lines)
        if mastery_lines
        else "  No mastery data yet"
    )

    examples = ", ".join(student_context.preferred_examples) if student_context.preferred_examples else "general"

    return f"""Student Context:
- Grade: {student_context.grade}
- Board: {student_context.board}
- Language Level: {student_context.language_level}
- Preferred Example Topics: {examples}

Current Mastery:
{mastery_section}"""


def _mastery_score_to_label(score: float) -> str:
    """Convert mastery score to human-readable label."""
    if score >= 0.9:
        return "Mastered"
    elif score >= 0.7:
        return "Strong"
    elif score >= 0.5:
        return "Adequate"
    elif score >= 0.3:
        return "Developing"
    else:
        return "Needs Work"


def truncate_text(text: str, max_length: int = 500, suffix: str = "...") -> str:
    """Truncate text to a maximum length with suffix."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def format_study_plan_step(step: dict[str, Any]) -> str:
    """Format a study plan step for prompt inclusion."""
    step_type = step.get("type", "unknown")
    concept = step.get("concept", "unknown")
    hint = step.get("content_hint", "")
    return f"Step {step.get('step_id', '?')}: {step_type.upper()} - {concept}\n  Hint: {hint}"


def format_misconceptions(misconceptions: list[str]) -> str:
    """Format list of misconceptions for prompt inclusion."""
    if not misconceptions:
        return "No misconceptions detected."
    lines = [f"- {m}" for m in misconceptions]
    return "Known Misconceptions:\n" + "\n".join(lines)
