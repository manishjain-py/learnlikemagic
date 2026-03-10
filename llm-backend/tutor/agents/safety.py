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


# Keywords/patterns that warrant an LLM safety check.
# Short, focused list — most kid tutoring messages won't match any of these.
_UNSAFE_PATTERNS = re.compile(
    r"(?i)\b("
    # Profanity / slurs (common ones kids might use)
    r"fuck|shit|ass(?:hole)?|bitch|damn|crap|dick|bastard|"
    r"nigger|faggot|retard|"
    # Violence / harm
    r"kill|murder|suicide|die|dead|weapon|gun|knife|bomb|hurt|attack|"
    # Personal info patterns
    r"my (?:phone|address|password|email|number)|"
    # Explicit / sexual
    r"sex|porn|nude|naked|"
    # Bullying
    r"stupid|idiot|dumb|loser|hate you|shut up|"
    # Off-topic / manipulation
    r"ignore (?:your|the) (?:instructions|rules|prompt)|pretend|roleplay|"
    r"you are not|forget (?:your|everything)"
    r")\b",
    re.IGNORECASE,
)

# Very short messages (1-2 chars) or pure numbers/math are always safe
_SAFE_PATTERN = re.compile(r"^[\d\s\+\-\*\/\=\.\,\(\)\%\^]+$")


def _is_obviously_safe(text: str) -> bool:
    """Fast rule-based check: return True if message is clearly safe."""
    stripped = text.strip()
    if len(stripped) <= 2:
        return True
    if _SAFE_PATTERN.match(stripped):
        return True
    if _UNSAFE_PATTERNS.search(stripped):
        return False
    # No unsafe patterns found — safe for a tutoring context
    return True


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
        """Override to add rule-based pre-filter. Skips LLM call for obviously safe messages."""
        if _is_obviously_safe(context.student_message):
            return SafetyOutput(
                is_safe=True,
                reasoning="Rule-based pre-filter: no unsafe patterns detected",
            )
        # Fall through to LLM-based check for flagged messages
        return await super().execute(context)

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
