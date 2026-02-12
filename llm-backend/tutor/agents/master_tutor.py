"""
Master Tutor Agent

Single agent that replaces the multi-agent pipeline. Sees full session context
and returns both the student-facing response and structured state updates in
one LLM call.
"""

from typing import Any, Dict, Optional, Type

from pydantic import BaseModel, Field

from tutor.agents.base_agent import BaseAgent, AgentContext
from tutor.models.session_state import SessionState
from tutor.prompts.master_tutor_prompts import (
    MASTER_TUTOR_SYSTEM_PROMPT,
    MASTER_TUTOR_TURN_PROMPT,
)
from tutor.prompts.templates import format_list_for_prompt
from tutor.utils.prompt_utils import format_conversation_history


class MasteryUpdate(BaseModel):
    """A single mastery score update for a concept."""
    concept: str = Field(description="The concept name")
    score: float = Field(description="Mastery score from 0.0 to 1.0")


class TutorTurnOutput(BaseModel):
    """Structured output from the master tutor — response + state updates."""

    response: str = Field(description="Your response to the student as the tutor")
    intent: str = Field(
        description="What the student was doing: answer, question, confusion, off_topic, or continuation"
    )

    # Answer evaluation
    answer_correct: Optional[bool] = Field(
        default=None, description="If student answered a question: was it correct? null if not answering"
    )
    misconceptions_detected: list[str] = Field(
        default_factory=list, description="Any misconceptions revealed in student's message"
    )
    mastery_signal: Optional[str] = Field(
        default=None, description="Mastery signal: strong, adequate, or needs_remediation"
    )

    # State updates
    advance_to_step: Optional[int] = Field(
        default=None, description="Step number to advance to if student is ready"
    )
    mastery_updates: list[MasteryUpdate] = Field(
        default_factory=list, description="Updated mastery scores for concepts"
    )

    # Question tracking
    question_asked: Optional[str] = Field(
        default=None, description="If your response contains a question, write it here"
    )
    expected_answer: Optional[str] = Field(
        default=None, description="The expected/correct answer to your question"
    )
    question_concept: Optional[str] = Field(
        default=None, description="Which concept the question tests"
    )

    # Session completion
    session_complete: bool = Field(
        default=False,
        description="Set to true when the student has completed the final step and demonstrated understanding. This ends the session.",
    )

    # Turn summary
    turn_summary: str = Field(description="One-sentence summary of this turn (max 80 chars)")
    reasoning: str = Field(default="", description="Your internal reasoning (not shown to student)")


class MasterTutorAgent(BaseAgent):
    """Single master tutor handling all teaching responsibilities."""

    def __init__(self, llm_service, timeout_seconds: int = 60, reasoning_effort: str = "none"):
        super().__init__(llm_service, timeout_seconds=timeout_seconds, reasoning_effort=reasoning_effort)
        self._session: Optional[SessionState] = None

    @property
    def agent_name(self) -> str:
        return "master_tutor"

    def get_output_model(self) -> Type[BaseModel]:
        return TutorTurnOutput

    def set_session(self, session: SessionState) -> None:
        self._session = session

    def build_prompt(self, context: AgentContext) -> str:
        session = self._session
        if not session:
            raise ValueError("Session not set. Call set_session() before execute().")

        system_prompt = self._build_system_prompt(session)
        turn_prompt = self._build_turn_prompt(session, context)

        return f"{system_prompt}\n\n---\n\n{turn_prompt}"

    def _build_system_prompt(self, session: SessionState) -> str:
        topic = session.topic

        steps_lines = []
        for step in topic.study_plan.steps:
            hint = f": {step.content_hint}" if step.content_hint else ""
            steps_lines.append(f"  Step {step.step_id} [{step.type}] {step.concept}{hint}")
        steps_formatted = "\n".join(steps_lines)

        misconceptions = format_list_for_prompt(topic.guidelines.common_misconceptions)

        return MASTER_TUTOR_SYSTEM_PROMPT.render(
            grade=session.student_context.grade,
            language_level=session.student_context.language_level,
            preferred_examples=", ".join(session.student_context.preferred_examples),
            topic_name=topic.topic_name,
            teaching_approach=topic.guidelines.teaching_approach,
            steps_formatted=steps_formatted,
            common_misconceptions=misconceptions,
        )

    def _build_turn_prompt(self, session: SessionState, context: AgentContext) -> str:
        current_step = session.current_step_data

        if current_step:
            current_step_info = f"[{current_step.type}] {current_step.concept}"
            content_hint = current_step.content_hint if current_step.content_hint else "None"
        else:
            current_step_info = "Complete"
            content_hint = "None"

        if session.mastery_estimates:
            mastery_lines = [
                f"  {concept}: {score:.1f}" for concept, score in session.mastery_estimates.items()
            ]
            mastery_formatted = "\n".join(mastery_lines)
        else:
            mastery_formatted = "  No data yet"

        if session.misconceptions:
            misconceptions = ", ".join(m.description for m in session.misconceptions)
        else:
            misconceptions = "None detected"

        if session.session_summary.turn_timeline:
            turn_timeline = " | ".join(session.session_summary.turn_timeline[-5:])
        else:
            turn_timeline = "Session just started"

        if session.awaiting_response and session.last_question:
            q = session.last_question
            awaiting_answer_section = (
                f"**IMPORTANT — Student is answering this question:**\n"
                f"Question: {q.question_text}\n"
                f"Expected Answer: {q.expected_answer}\n"
                f"Concept: {q.concept}\n"
                f"Evaluate their answer and set answer_correct accordingly."
            )
        else:
            awaiting_answer_section = ""

        conversation = format_conversation_history(session.conversation_history, max_turns=10)
        if not conversation.strip():
            conversation = "(No prior messages — this is the first turn)"

        return MASTER_TUTOR_TURN_PROMPT.render(
            current_step=session.current_step,
            total_steps=session.topic.study_plan.total_steps if session.topic else 0,
            current_step_info=current_step_info,
            content_hint=content_hint,
            mastery_formatted=mastery_formatted,
            misconceptions=misconceptions,
            turn_timeline=turn_timeline,
            awaiting_answer_section=awaiting_answer_section,
            conversation_history=conversation,
            student_message=context.student_message,
        )

    def _summarize_output(self, output: BaseModel) -> Dict[str, Any]:
        if isinstance(output, TutorTurnOutput):
            return {
                "intent": output.intent,
                "answer_correct": output.answer_correct,
                "advance_to_step": output.advance_to_step,
                "mastery_updates": {u.concept: u.score for u in output.mastery_updates},
                "question_asked": output.question_asked is not None,
                "response_length": len(output.response),
            }
        return super()._summarize_output(output)
