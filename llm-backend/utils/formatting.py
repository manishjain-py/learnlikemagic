"""Formatting utilities for history, messages, and responses."""
from typing import List, Dict, Any, Tuple, Optional


def format_conversation_history(history: List[Dict[str, Any]]) -> str:
    """
    Format conversation history for LLM context.

    Args:
        history: List of history entries with 'role' and 'msg' keys

    Returns:
        Formatted string with "Teacher: ..." and "Student: ..." lines
    """
    if not history:
        return "(First turn - no history yet)"

    history_text = ""
    for entry in history:
        role = "Teacher" if entry["role"] == "teacher" else "Student"
        history_text += f"{role}: {entry['msg']}\n"
    return history_text


def extract_last_turn(
    history: List[Any],
    default_message: str = "Hello!"
) -> Tuple[str, List[str]]:
    """
    Extract message and hints from the last history entry.

    Args:
        history: List of HistoryEntry objects or dicts
        default_message: Message to return if history is empty

    Returns:
        Tuple of (message, hints)
    """
    if not history:
        return default_message, []

    last_msg = history[-1]

    # Handle both Pydantic models and dicts
    if hasattr(last_msg, 'msg'):
        message = last_msg.msg
        meta = last_msg.meta if hasattr(last_msg, 'meta') else None
    else:
        message = last_msg.get('msg', default_message)
        meta = last_msg.get('meta')

    hints = meta.get("hints", []) if meta else []
    return message, hints


def build_turn_response(
    history: List[Any],
    step_idx: int,
    mastery_score: float
) -> Dict[str, Any]:
    """
    Build a standardized turn response object.

    Args:
        history: Conversation history
        step_idx: Current step index
        mastery_score: Current mastery score

    Returns:
        Dictionary with message, hints, step_idx, mastery_score, is_complete
    """
    from .constants import MAX_STEPS, MASTERY_COMPLETION_THRESHOLD

    message, hints = extract_last_turn(history, "")

    return {
        "message": message,
        "hints": hints,
        "step_idx": step_idx,
        "mastery_score": mastery_score,
        "is_complete": step_idx >= MAX_STEPS or mastery_score >= MASTERY_COMPLETION_THRESHOLD
    }
