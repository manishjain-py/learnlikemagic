"""
Teacher Orchestrator

Simplified architecture: Safety check -> Master Tutor -> State update.
The master tutor handles all teaching responsibilities in a single LLM call.
"""

import time
import logging
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

from shared.services.llm_service import LLMService
from tutor.models.session_state import SessionState, Question
from tutor.models.messages import create_teacher_message, create_student_message
from tutor.models.agent_logs import AgentLogEntry, get_agent_log_store
from tutor.agents.base_agent import AgentContext
from tutor.agents.safety import SafetyAgent, SafetyOutput
from tutor.agents.master_tutor import MasterTutorAgent, TutorTurnOutput
from tutor.prompts.orchestrator_prompts import WELCOME_MESSAGE_PROMPT

logger = logging.getLogger("tutor.orchestrator")


class TurnResult(BaseModel):
    """Result of processing a turn."""
    response: str = Field(description="Teacher response to send")
    intent: str = Field(description="Detected intent")
    specialists_called: List[str] = Field(default_factory=list)
    state_changed: bool = Field(default=False)


class TeacherOrchestrator:
    """
    Central orchestrator for the tutoring system.

    Uses a single master tutor agent for all teaching responsibilities,
    with a separate safety gate.
    """

    def __init__(self, llm_service: LLMService):
        self.llm = llm_service
        self.agent_logs = get_agent_log_store()

        self.safety_agent = SafetyAgent(self.llm)
        self.master_tutor = MasterTutorAgent(self.llm, timeout_seconds=60)

        logger.info("TeacherOrchestrator initialized (single master tutor architecture)")

    def _log_agent_event(
        self,
        session_id: str,
        turn_id: str,
        agent_name: str,
        event_type: str,
        input_summary: Optional[str] = None,
        output: Optional[Dict[str, Any]] = None,
        reasoning: Optional[str] = None,
        duration_ms: Optional[int] = None,
        prompt: Optional[str] = None,
        model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = AgentLogEntry(
            session_id=session_id,
            turn_id=turn_id,
            agent_name=agent_name,
            event_type=event_type,
            input_summary=input_summary,
            output=output,
            reasoning=reasoning,
            duration_ms=duration_ms,
            prompt=prompt,
            model=model,
            metadata=metadata or {},
        )
        self.agent_logs.add_log(entry)

    async def process_turn(
        self,
        session: SessionState,
        student_message: str,
    ) -> TurnResult:
        """
        Process a single conversation turn.

        Flow: safety check -> master tutor -> state update -> return response.
        """
        start_time = time.time()
        turn_id = session.get_current_turn_id()

        logger.info(f"Turn started: {turn_id} for session {session.session_id}")

        self._log_agent_event(
            session_id=session.session_id,
            turn_id=turn_id,
            agent_name="orchestrator",
            event_type="turn_started",
            input_summary=f"Student: {student_message[:100]}{'...' if len(student_message) > 100 else ''}",
            metadata={"current_step": session.current_step, "turn_count": session.turn_count},
        )

        try:
            # Check if session is already complete
            if session.is_complete:
                # Still record the student's message in history
                session.add_message(create_student_message(student_message))
                return TurnResult(
                    response="We've wrapped up this lesson — great work! Start a new session whenever you're ready to keep going.",
                    intent="session_complete",
                    specialists_called=[],
                    state_changed=False,
                )

            # Increment turn counter and add student message
            session.increment_turn()
            session.add_message(create_student_message(student_message))

            # Build context for agents
            context = AgentContext(
                session_id=session.session_id,
                turn_id=turn_id,
                student_message=student_message,
                current_step=session.current_step,
                current_concept=(
                    session.current_step_data.concept if session.current_step_data else None
                ),
                student_grade=session.student_context.grade,
                language_level=session.student_context.language_level,
            )

            # Step 1: Safety check
            safety_start = time.time()
            safety_result: SafetyOutput = await self.safety_agent.execute(context)
            safety_duration = int((time.time() - safety_start) * 1000)

            self._log_agent_event(
                session_id=session.session_id,
                turn_id=turn_id,
                agent_name="safety",
                event_type="completed",
                input_summary=f"Check: {student_message[:80]}",
                output=self._extract_output_dict(safety_result),
                duration_ms=safety_duration,
            )

            if not safety_result.is_safe:
                response = self._handle_unsafe_message(session, safety_result)
                return TurnResult(
                    response=response, intent="unsafe",
                    specialists_called=["safety"], state_changed=True,
                )

            # Step 2: Master tutor
            tutor_start = time.time()
            self.master_tutor.set_session(session)
            tutor_output: TutorTurnOutput = await self.master_tutor.execute(context)
            tutor_duration = int((time.time() - tutor_start) * 1000)

            self._log_agent_event(
                session_id=session.session_id,
                turn_id=turn_id,
                agent_name="master_tutor",
                event_type="completed",
                output=self._extract_output_dict(tutor_output),
                reasoning=tutor_output.reasoning,
                duration_ms=tutor_duration,
                prompt=self.master_tutor.last_prompt,
                metadata={
                    "intent": tutor_output.intent,
                    "answer_correct": tutor_output.answer_correct,
                    "advance_to_step": tutor_output.advance_to_step,
                    "question_asked": tutor_output.question_asked is not None,
                    "session_complete": tutor_output.session_complete,
                },
            )

            # Step 3: Apply state updates
            state_changed = self._apply_state_updates(session, tutor_output)

            # Add teacher response to history
            session.add_message(create_teacher_message(tutor_output.response))

            # Update session summary
            turn_entry = f"Turn {session.turn_count}: {tutor_output.turn_summary}"
            session.session_summary.turn_timeline.append(turn_entry)
            if len(session.session_summary.turn_timeline) > 30:
                session.session_summary.turn_timeline = session.session_summary.turn_timeline[-30:]

            # Update progress trend
            if tutor_output.answer_correct is not None:
                mastery_values = list(session.mastery_estimates.values())
                avg_mastery = sum(mastery_values) / len(mastery_values) if mastery_values else 0.5
                if tutor_output.answer_correct and avg_mastery >= 0.6:
                    session.session_summary.progress_trend = "improving"
                elif not tutor_output.answer_correct and avg_mastery < 0.4:
                    session.session_summary.progress_trend = "struggling"
                else:
                    session.session_summary.progress_trend = "steady"

            # Track concepts taught
            if session.current_step_data:
                concept = session.current_step_data.concept
                if concept and concept not in session.session_summary.concepts_taught:
                    session.session_summary.concepts_taught.append(concept)

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Turn completed: {turn_id} ({duration_ms}ms)")

            self._log_agent_event(
                session_id=session.session_id,
                turn_id=turn_id,
                agent_name="orchestrator",
                event_type="turn_completed",
                duration_ms=duration_ms,
                metadata={"intent": tutor_output.intent, "state_changed": state_changed},
            )

            return TurnResult(
                response=tutor_output.response,
                intent=tutor_output.intent,
                specialists_called=["master_tutor"],
                state_changed=state_changed,
            )

        except Exception as e:
            logger.error(f"Turn failed: {e}", exc_info=True)
            return TurnResult(
                response="I apologize, but I had a moment of confusion. Could you please repeat that?",
                intent="error",
                specialists_called=[],
                state_changed=False,
            )

    def _apply_state_updates(self, session: SessionState, output: TutorTurnOutput) -> bool:
        """Apply structured state updates from master tutor output."""
        changed = False

        # 1. Update mastery scores
        for update in output.mastery_updates:
            session.update_mastery(update.concept, update.score)
            changed = True

        # 2. Track misconceptions
        current_concept = (
            session.current_step_data.concept if session.current_step_data else "unknown"
        )
        for misconception in output.misconceptions_detected:
            session.add_misconception(current_concept, misconception)
            changed = True

        # 3. Track questions
        if output.question_asked:
            session.set_question(Question(
                question_text=output.question_asked,
                expected_answer=output.expected_answer or "",
                concept=output.question_concept or current_concept,
            ))
            changed = True
        elif output.answer_correct is not None:
            session.clear_question()
            changed = True

        # 4. Advance step
        if output.advance_to_step and output.advance_to_step > session.current_step:
            while session.current_step < output.advance_to_step:
                session.advance_step()
            changed = True

        # 5. Track off-topic
        if output.intent == "off_topic":
            session.off_topic_count += 1
            changed = True

        # 6. Handle session completion (only honor on final step to prevent premature endings)
        if output.session_complete:
            total = session.topic.study_plan.total_steps if session.topic else 0
            if session.current_step >= total:
                # Advance past final step to trigger is_complete
                while not session.is_complete:
                    if not session.advance_step():
                        break
                changed = True
            else:
                logger.warning(
                    f"LLM signaled session_complete on step {session.current_step}/{total}, ignoring"
                )

        return changed

    def _handle_unsafe_message(self, session: SessionState, safety: SafetyOutput) -> str:
        session.safety_flags.append(safety.violation_type or "unknown")
        if safety.should_warn:
            session.warning_count += 1

        if safety.guidance:
            return safety.guidance
        return "Let's keep our conversation focused on learning. How can I help you with the lesson?"

    def _extract_output_dict(self, output: Any) -> Dict[str, Any]:
        if output is None:
            return {}
        if hasattr(output, "model_dump"):
            return output.model_dump()
        if isinstance(output, dict):
            return output
        return {"value": str(output)}

    async def generate_welcome_message(self, session: SessionState) -> str:
        """Generate a welcome message for a new session."""
        if not session.topic:
            return "Welcome! Let's start learning together."

        prompt = WELCOME_MESSAGE_PROMPT.render(
            grade=session.student_context.grade,
            topic_name=session.topic.topic_name,
            subject=session.topic.subject,
            learning_objectives="\n".join(
                f"- {obj}" for obj in session.topic.guidelines.learning_objectives
            ),
            language_level=session.student_context.language_level,
            preferred_examples=", ".join(session.student_context.preferred_examples),
        )

        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.llm.call_gpt_5_2(
                prompt=prompt,
                reasoning_effort="none",
                json_mode=False,
            ),
        )

        return result.get("output_text", "Welcome! Let's start learning.").strip()
