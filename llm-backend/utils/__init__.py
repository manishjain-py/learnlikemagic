"""Utility functions and helpers."""
from .formatting import (
    format_conversation_history,
    extract_last_turn,
    build_turn_response
)
from .constants import (
    MASTERY_EMA_ALPHA,
    MASTERY_COMPLETION_THRESHOLD,
    MASTERY_ADVANCE_THRESHOLD,
    MAX_STEPS,
    SCORE_EXCELLENT,
    SCORE_GOOD,
    SCORE_PARTIAL,
    MIN_CONFIDENCE_FOR_ADVANCE,
    DEFAULT_GUIDELINE,
    DEFAULT_MESSAGE
)
from .exceptions import (
    LearnLikeMagicException,
    SessionNotFoundException,
    GuidelineNotFoundException,
    LLMProviderException,
    DatabaseException
)

__all__ = [
    # Formatting
    "format_conversation_history",
    "extract_last_turn",
    "build_turn_response",
    # Constants
    "MASTERY_EMA_ALPHA",
    "MASTERY_COMPLETION_THRESHOLD",
    "MASTERY_ADVANCE_THRESHOLD",
    "MAX_STEPS",
    "SCORE_EXCELLENT",
    "SCORE_GOOD",
    "SCORE_PARTIAL",
    "MIN_CONFIDENCE_FOR_ADVANCE",
    "DEFAULT_GUIDELINE",
    "DEFAULT_MESSAGE",
    # Exceptions
    "LearnLikeMagicException",
    "SessionNotFoundException",
    "GuidelineNotFoundException",
    "LLMProviderException",
    "DatabaseException"
]
