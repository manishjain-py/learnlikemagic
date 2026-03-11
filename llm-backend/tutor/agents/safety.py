"""
Safety Agent - Content Moderation

Fast safety gate that checks student messages before the master tutor runs.
Includes a rule-based pre-filter that short-circuits obviously safe messages
(~95% of kids' tutoring messages) without an LLM call.
"""

import re
from typing import Type, Optional
from pydantic import BaseModel, Field

from tutor.agents.base_agent import BaseAgent, AgentContext
from tutor.prompts.templates import SAFETY_TEMPLATE


# Allow-list approach: only short-circuit messages that are PROVABLY safe.
# Everything else goes to the LLM for proper safety classification.
# This catches ~60-70% of kid tutoring messages (math, short answers, common words).

# Pure math expressions: "3 + 4", "42", "1/2 + 3/4"
_MATH_ONLY = re.compile(r"^[\d\s\+\-\*\/\=\.\,\(\)\%\^\×\÷]+$")

# Common safe single-word or very short answers kids give in tutoring
_SAFE_SHORT_ANSWERS = frozenset({
    "yes", "no", "ok", "okay", "ya", "yep", "nope", "nah",
    "sure", "maybe", "idk", "hmm", "hm", "right", "correct",
    "true", "false", "done", "ready", "next", "hi", "hello",
    "thanks", "thank you", "bye", "haan", "nahi", "theek hai",
})


def _is_provably_safe(text: str) -> bool:
    """Allow-list check: return True ONLY for messages that are certainly safe.

    Uses a conservative allow-list approach: only short-circuits for math
    expressions, very short messages (1-2 chars), and known safe words.
    All other messages go through the LLM safety check.
    """
    stripped = text.strip()

    # Empty or single-char messages (e.g., "5", "?", "a")
    if len(stripped) <= 2:
        return True

    # Pure math/numbers: "3 + 4 = 7", "42", "1/2"
    if _MATH_ONLY.match(stripped):
        return True

    # Known safe short answers (case-insensitive, exact match)
    if stripped.lower() in _SAFE_SHORT_ANSWERS:
        return True

    # Everything else goes to LLM — fail-safe, not fail-open
    return False


class SafetyOutput(BaseModel):
    """Output model for Safety Agent."""

    is_safe: bool = Field(description="Whether the message is safe")
    violation_type: Optional[str] = Field(default=None, description="Type of violation if unsafe")
    guidance: Optional[str] = Field(default=None, description="Guidance message if unsafe")
    should_warn: bool = Field(default=False, description="Whether to issue a warning")
    reasoning: str = Field(default="", description="Reasoning for safety decision")


class SafetyAgent(BaseAgent):
    """
    Safety Agent for content moderation.

    Checks for inappropriate language, harmful content, personal info sharing,
    attempts to derail the lesson, and bullying/harassment.

    Uses gpt-4o-mini (fast model) since safety checks are simple classification tasks.
    """

    def __init__(self, llm_service, timeout_seconds: int = 15):
        super().__init__(llm_service, timeout_seconds=timeout_seconds, use_fast_model=True)

    @property
    def agent_name(self) -> str:
        return "safety"

    def get_output_model(self) -> Type[BaseModel]:
        return SafetyOutput

    async def execute(self, context: AgentContext):
        """Override to add allow-list pre-filter. Skips LLM only for provably safe messages.

        If the fast model (gpt-4o-mini) returns malformed output, fails safe
        by treating the message as unsafe rather than crashing the turn.
        """
        if _is_provably_safe(context.student_message):
            return SafetyOutput(
                is_safe=True,
                reasoning="Allow-list pre-filter: message is provably safe (math/short answer)",
            )
        # LLM-based check with fail-safe fallback
        try:
            return await super().execute(context)
        except Exception as e:
            import logging
            logging.getLogger("tutor.safety").warning(
                f"Safety LLM check failed ({type(e).__name__}: {e}), failing safe"
            )
            return SafetyOutput(
                is_safe=False,
                violation_type="safety_check_error",
                guidance="Let's keep our conversation focused on learning. Could you rephrase that?",
                reasoning=f"Safety check failed ({type(e).__name__}), failing safe",
            )

    def build_prompt(self, context: AgentContext) -> str:
        additional = context.additional_context
        return SAFETY_TEMPLATE.render(
            message=context.student_message,
            context=additional.get("lesson_context", "tutoring session"),
        )

    def _summarize_output(self, output: SafetyOutput) -> dict:
        return {
            "is_safe": output.is_safe,
            "violation_type": output.violation_type,
            "should_warn": output.should_warn,
        }
