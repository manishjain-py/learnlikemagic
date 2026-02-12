"""
Safety Agent - Content Moderation

Fast safety gate that checks student messages before the master tutor runs.
"""

from typing import Type, Optional
from pydantic import BaseModel, Field

from tutor.agents.base_agent import BaseAgent, AgentContext
from tutor.prompts.templates import SAFETY_TEMPLATE


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
    """

    @property
    def agent_name(self) -> str:
        return "safety"

    def get_output_model(self) -> Type[BaseModel]:
        return SafetyOutput

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
