"""Prompt templates and loading utilities."""
from .loader import (
    PromptLoader,
    get_teaching_prompt,
    get_grading_prompt,
    get_remediation_prompt,
    get_fallback_responses
)

__all__ = [
    "PromptLoader",
    "get_teaching_prompt",
    "get_grading_prompt",
    "get_remediation_prompt",
    "get_fallback_responses"
]
