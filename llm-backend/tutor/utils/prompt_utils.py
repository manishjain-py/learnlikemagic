"""
Prompt construction utilities.

Provides reusable functions for formatting conversation history
and other prompt helpers.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tutor.models.messages import Message


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
