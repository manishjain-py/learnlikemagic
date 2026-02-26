"""
Teacher Orchestrator

Simplified architecture: Safety check -> Master Tutor -> State update.
The master tutor handles all teaching responsibilities in a single LLM call.
"""

import re
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
            # Clarify Doubts: always short-circuit once student ended the session
            # Teach Me: allow extension turns for advanced students
            if session.is_complete and session.mode == "clarify_doubts":
                session.add_message(create_student_message(student_message))
                response = await self._generate_post_completion_response(session, student_message)
                session.add_message(create_teacher_message(response))
                return TurnResult(
                    response=response,
                    intent="session_complete",
                    specialists_called=[],
                    state_changed=True,
                )
            max_extension_turns = 10
            extension_turns = session.turn_count - (session.topic.study_plan.total_steps * 2 if session.topic else 0)
            if session.is_complete and (not session.allow_extension or extension_turns > max_extension_turns):
                # Record both student message and assistant reply in history
                session.add_message(create_student_message(student_message))
                response = await self._generate_post_completion_response(session, student_message)
                session.add_message(create_teacher_message(response))
                return TurnResult(
                    response=response,
                    intent="session_complete",
                    specialists_called=[],
                    state_changed=True,
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

            # Mode-specific turn processing
            if session.mode == "clarify_doubts":
                return await self._process_clarify_turn(session, context, turn_id, start_time)
            elif session.mode == "exam":
                return await self._process_exam_turn(session, context, turn_id, start_time)

            # Step 2: Master tutor (teach_me mode)
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

            # Step 2b: Sanitization check on tutor response
            self._check_response_sanitization(session.session_id, turn_id, tutor_output.response)

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

    # Regex patterns that indicate system/diagnostic language leaked into student-facing response
    _LEAK_PATTERNS = re.compile(
        r"(?i)\b(?:the student'?s?|the message contains|the answer is incorrect because"
        r"|assessment:|diagnostic:|the learner|student appears to|misconception detected"
        r"|the response should)\b"
    )

    async def _generate_post_completion_response(self, session: SessionState, student_message: str) -> str:
        """Generate a context-aware response to a student's post-session message."""
        concepts = ", ".join(session.session_summary.concepts_taught) if session.session_summary.concepts_taught else "the topic"
        prompt = (
            f"You are a warm, friendly tutor. The tutoring session on '{session.topic.topic_name if session.topic else 'this topic'}' "
            f"has already ended. The student just said: \"{student_message}\"\n\n"
            f"Concepts covered: {concepts}\n\n"
            f"Respond naturally to whatever the student said. If they asked a question, answer it briefly. "
            f"If they said thanks, acknowledge warmly. Remind them they can start a new session to continue learning. "
            f"Keep it to 1-2 sentences. Speak directly to the student (use 'you')."
        )
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.llm.call(
                    prompt=prompt,
                    reasoning_effort="none",
                    json_mode=False,
                ),
            )
            return result.get("output_text", "").strip() or "Feel free to start a new session whenever you're ready!"
        except Exception as e:
            logger.warning(f"Failed to generate post-completion response: {e}")
            return "Feel free to start a new session whenever you're ready!"

    def _check_response_sanitization(self, session_id: str, turn_id: str, response: str) -> None:
        """Log a warning if the tutor response contains third-person diagnostic language."""
        match = self._LEAK_PATTERNS.search(response)
        if match:
            logger.warning(
                f"System note leak detected in response (session={session_id}, turn={turn_id}): "
                f"matched '{match.group()}' — response may contain internal language shown to student"
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

        # 3. Question lifecycle
        if self._handle_question_lifecycle(session, output, current_concept):
            changed = True

        # 4. Advance step + coverage tracking
        if output.advance_to_step and output.advance_to_step > session.current_step:
            for step_id in range(session.current_step, output.advance_to_step):
                step = session.topic.study_plan.get_step(step_id) if session.topic else None
                if step:
                    session.concepts_covered_set.add(step.concept)
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

    def _handle_question_lifecycle(
        self, session: SessionState, output: TutorTurnOutput, current_concept: str
    ) -> bool:
        """
        Handle question tracking with lifecycle awareness.

        Cases:
        1. Wrong answer on pending question → increment attempts, DON'T clear
        2. Correct answer → clear question (optionally track new one)
        3. New question, no pending → track it
        4. New question, different concept pending → replace
        5. Same concept follow-up while pending → keep original lifecycle
        """
        has_pending = session.last_question is not None

        # Case 1: Wrong answer on a pending question
        if output.answer_correct is False and has_pending:
            q = session.last_question
            q.wrong_attempts += 1
            # Record what the student said
            last_student = [m for m in session.conversation_history if m.role == "student"]
            if last_student:
                q.previous_student_answers.append(last_student[-1].content[:200])
            # Update phase
            if q.wrong_attempts == 1:
                q.phase = "probe"
            elif q.wrong_attempts == 2:
                q.phase = "hint"
            else:
                q.phase = "explain"
            # If tutor asked a probing/follow-up question, update expected answer
            # so the prompt shows the correct expected answer for the NEW question
            if output.question_asked:
                q.question_text = output.question_asked
                if output.expected_answer:
                    q.expected_answer = output.expected_answer
            return True

        # Case 2: Correct answer → clear, then maybe track new question
        if output.answer_correct is True:
            session.clear_question()
            if output.question_asked:
                session.set_question(Question(
                    question_text=output.question_asked,
                    expected_answer=output.expected_answer or "",
                    concept=output.question_concept or current_concept,
                ))
            return True

        # Case 3: New question, no pending
        if output.question_asked and not has_pending:
            session.set_question(Question(
                question_text=output.question_asked,
                expected_answer=output.expected_answer or "",
                concept=output.question_concept or current_concept,
            ))
            return True

        # Case 4: New question, different concept pending → replace
        if output.question_asked and has_pending:
            new_concept = output.question_concept or current_concept
            if new_concept != session.last_question.concept:
                session.set_question(Question(
                    question_text=output.question_asked,
                    expected_answer=output.expected_answer or "",
                    concept=output.question_concept or current_concept,
                ))
                return True
            # Case 5: Same concept follow-up → keep existing lifecycle
            return False

        # No question change
        return False

    def _handle_unsafe_message(self, session: SessionState, safety: SafetyOutput) -> str:
        session.safety_flags.append(safety.violation_type or "unknown")
        if safety.should_warn:
            session.warning_count += 1

        if safety.guidance:
            return safety.guidance
        return "Let's keep our conversation focused on learning. How can I help you with the lesson?"

    async def _process_clarify_turn(
        self, session: SessionState, context: AgentContext, turn_id: str, start_time: float
    ) -> TurnResult:
        """Process a Clarify Doubts turn."""
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
            metadata={"mode": "clarify_doubts", "intent": tutor_output.intent},
        )

        # Track concepts discussed (from mastery_updates or turn summary)
        if hasattr(tutor_output, 'mastery_updates') and tutor_output.mastery_updates:
            for update in tutor_output.mastery_updates:
                if update.concept not in session.concepts_discussed:
                    session.concepts_discussed.append(update.concept)
                session.concepts_covered_set.add(update.concept)

        # Mark session complete when student indicates they are done
        if tutor_output.intent == "done" or tutor_output.session_complete:
            session.clarify_complete = True
            logger.info(f"Clarify Doubts session {session.session_id} marked complete (intent={tutor_output.intent})")

        session.add_message(create_teacher_message(tutor_output.response))

        duration_ms = int((time.time() - start_time) * 1000)
        self._log_agent_event(
            session_id=session.session_id,
            turn_id=turn_id,
            agent_name="orchestrator",
            event_type="turn_completed",
            duration_ms=duration_ms,
            metadata={"mode": "clarify_doubts", "intent": tutor_output.intent, "clarify_complete": session.clarify_complete},
        )

        return TurnResult(
            response=tutor_output.response,
            intent=tutor_output.intent,
            specialists_called=["master_tutor"],
            state_changed=True,
        )

    async def _process_exam_turn(
        self, session: SessionState, context: AgentContext, turn_id: str, start_time: float
    ) -> TurnResult:
        """Process an Exam turn — evaluate answer and move to next question."""
        if session.exam_finished or session.exam_current_question_idx >= len(session.exam_questions):
            response = "The exam is already complete. Check your results!"
            session.add_message(create_teacher_message(response))
            return TurnResult(
                response=response,
                intent="exam_complete",
                specialists_called=[],
                state_changed=True,
            )

        current_q = session.exam_questions[session.exam_current_question_idx]

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
            metadata={"mode": "exam", "question_idx": session.exam_current_question_idx},
        )

        # Record student answer
        current_q.student_answer = context.student_message
        current_q.feedback = tutor_output.turn_summary

        # Determine result from mastery signal
        if tutor_output.answer_correct is True:
            current_q.result = "correct"
            session.exam_total_correct += 1
        elif tutor_output.answer_correct is False:
            if tutor_output.mastery_signal == "needs_remediation":
                current_q.result = "incorrect"
                session.exam_total_incorrect += 1
            else:
                current_q.result = "partial"
                session.exam_total_partial += 1
        else:
            current_q.result = "incorrect"
            session.exam_total_incorrect += 1

        # Move to next question (do not reveal correctness mid-exam)
        session.exam_current_question_idx += 1

        if session.exam_current_question_idx >= len(session.exam_questions):
            session.exam_finished = True
            session.exam_feedback = self._build_exam_feedback(session)
            response = (
                "✅ Exam complete! Here are your final results."
            )
        else:
            next_q = session.exam_questions[session.exam_current_question_idx]
            response = (
                "Got it — let's continue.\n\n"
                f"**Question {next_q.question_idx + 1}:** {next_q.question_text}"
            )

        session.add_message(create_teacher_message(response))

        duration_ms = int((time.time() - start_time) * 1000)
        self._log_agent_event(
            session_id=session.session_id,
            turn_id=turn_id,
            agent_name="orchestrator",
            event_type="turn_completed",
            duration_ms=duration_ms,
            metadata={"mode": "exam", "exam_finished": session.exam_finished},
        )

        return TurnResult(
            response=response,
            intent="exam_answer",
            specialists_called=["master_tutor"],
            state_changed=True,
        )

    @staticmethod
    def _build_exam_feedback(session: SessionState) -> "ExamFeedback":
        """Build structured exam feedback from question results."""
        from tutor.models.session_state import ExamFeedback

        answered = [q for q in session.exam_questions if q.result is not None]
        correct_concepts = [q.concept for q in answered if q.result == "correct"]
        partial_concepts = [q.concept for q in answered if q.result == "partial"]
        incorrect_concepts = [q.concept for q in answered if q.result == "incorrect"]

        strengths = list(set(correct_concepts))
        weak_areas = list(set(incorrect_concepts + partial_concepts))
        patterns = []
        if len(correct_concepts) > len(incorrect_concepts):
            patterns.append("Overall strong performance")
        elif len(incorrect_concepts) > len(correct_concepts):
            patterns.append("More practice needed across concepts")

        next_steps = []
        if weak_areas:
            next_steps.append(f"Review these concepts in Teach Me: {', '.join(weak_areas[:3])}")
        if partial_concepts:
            next_steps.append(f"Clarify your understanding of: {', '.join(list(set(partial_concepts))[:3])}")
        if not weak_areas:
            next_steps.append("Great job! Try a harder topic or retake to aim for a perfect score.")

        total = len(session.exam_questions)
        return ExamFeedback(
            score=session.exam_total_correct,
            total=total,
            percentage=round(session.exam_total_correct / total * 100, 1) if total else 0.0,
            strengths=strengths,
            weak_areas=weak_areas,
            patterns=patterns,
            next_steps=next_steps,
        )

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
            lambda: self.llm.call(
                prompt=prompt,
                reasoning_effort="none",
                json_mode=False,
            ),
        )

        return result.get("output_text", "Welcome! Let's start learning.").strip()

    async def generate_clarify_welcome(self, session: SessionState) -> str:
        """Generate a welcome message for Clarify Doubts mode."""
        if not session.topic:
            return "Hi! I'm here to help answer your questions. What would you like to know?"

        topic_name = session.topic.topic_name
        prompt = (
            f"You are a friendly tutor starting a Clarify Doubts session with a Grade {session.student_context.grade} student.\n\n"
            f"Topic: {topic_name}\n"
            f"Subject: {session.topic.subject}\n\n"
            f"Generate a warm, brief welcome that:\n"
            f"1. Greets the student\n"
            f"2. Says you're here to answer their questions about {topic_name}\n"
            f"3. Invites them to ask whatever they're curious or confused about\n\n"
            f"Keep it to 1-2 sentences. Use {session.student_context.language_level} language. No emojis."
        )

        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.llm.call(prompt=prompt, reasoning_effort="none", json_mode=False),
        )
        return result.get("output_text", f"Hi! I'm here to help with {topic_name}. What questions do you have?").strip()

    async def generate_exam_welcome(self, session: SessionState) -> str:
        """Generate a welcome message for Exam mode."""
        if not session.topic:
            return "Let's test your knowledge! I'll ask you some questions. Ready?"

        topic_name = session.topic.topic_name
        num_questions = len(session.exam_questions) if session.exam_questions else 7
        prompt = (
            f"You are a friendly tutor starting an exam session with a Grade {session.student_context.grade} student.\n\n"
            f"Topic: {topic_name}\n"
            f"Number of questions: {num_questions}\n\n"
            f"Generate a brief welcome that:\n"
            f"1. Greets the student warmly\n"
            f"2. Explains this is a {num_questions}-question exam on {topic_name}\n"
            f"3. Encourages them to do their best\n"
            f"4. Asks if they're ready\n\n"
            f"Keep it to 2-3 sentences. Use {session.student_context.language_level} language. No emojis."
        )

        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.llm.call(prompt=prompt, reasoning_effort="none", json_mode=False),
        )
        return result.get("output_text", f"Let's test your knowledge of {topic_name}! I'll ask you {num_questions} questions. Ready?").strip()
