"""
Teacher Orchestrator

Simplified architecture: Safety check -> Master Tutor -> State update.
The master tutor handles all teaching responsibilities in a single LLM call.
"""

import re
import time
import logging
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional, List, Tuple, Union
from pydantic import BaseModel, Field

from shared.services.llm_service import LLMService
from tutor.models.session_state import SessionState, Question
from tutor.models.messages import create_teacher_message, create_student_message
from tutor.models.agent_logs import AgentLogEntry, get_agent_log_store
from tutor.agents.base_agent import AgentContext
from tutor.agents.safety import SafetyAgent, SafetyOutput
from tutor.agents.master_tutor import MasterTutorAgent, TutorTurnOutput
from tutor.prompts.orchestrator_prompts import WELCOME_MESSAGE_PROMPT
from tutor.services.pixi_code_generator import PixiCodeGenerator

logger = logging.getLogger("tutor.orchestrator")


class TurnResult(BaseModel):
    """Result of processing a turn."""
    response: str = Field(description="Teacher response to send")
    audio_text: Optional[str] = Field(default=None, description="Hinglish spoken version for TTS")
    intent: str = Field(description="Detected intent")
    specialists_called: List[str] = Field(default_factory=list)
    state_changed: bool = Field(default=False)
    visual_explanation: Optional[Dict[str, Any]] = Field(default=None, description="Structured visual explanation for frontend rendering")
    question_format: Optional[Dict[str, Any]] = Field(default=None, description="Structured question format for frontend")


class TeacherOrchestrator:
    """
    Central orchestrator for the tutoring system.

    Uses a single master tutor agent for all teaching responsibilities,
    with a separate safety gate.
    """

    def __init__(self, llm_service: LLMService, *, visuals_enabled: bool = True):
        self.llm = llm_service
        self.visuals_enabled = visuals_enabled
        self.pixi_generator = PixiCodeGenerator(llm_service)
        self.agent_logs = get_agent_log_store()

        self.safety_agent = SafetyAgent(self.llm)
        self.master_tutor = MasterTutorAgent(self.llm, timeout_seconds=60)

        logger.info("TeacherOrchestrator initialized (single master tutor architecture, visuals=%s)", visuals_enabled)

    async def _generate_pixi_code(self, visual_explanation) -> Optional[Dict[str, Any]]:
        """Generate Pixi.js code for a visual explanation and return the full visual dict.

        Returns None if code generation fails or visuals are disabled via the
        show_visuals_in_tutor_flow feature flag, so the frontend won't show a
        broken 'Visualise' button.  Also strips visual_prompt from the payload
        to avoid leaking internal prompts to the client.

        This method MUST never raise — any exception is logged and returns None
        so that a failed visual never crashes the turn.
        """
        if not self.visuals_enabled:
            return None
        try:
            pixi_code = await self.pixi_generator.generate(
                visual_prompt=visual_explanation.visual_prompt,
                output_type=visual_explanation.output_type,
            )
            if not pixi_code:
                logger.warning("Pixi code generation returned empty — skipping visual")
                return None
            visual_dict = visual_explanation.model_dump()
            visual_dict["pixi_code"] = pixi_code
            visual_dict.pop("visual_prompt", None)
            return visual_dict
        except Exception as e:
            logger.error(f"Pixi code generation crashed — skipping visual: {e}", exc_info=True)
            return None

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

    async def _translate_to_english(self, text: str) -> str:
        """Translate Hinglish/Hindi student input to English.

        Uses gpt-4o-mini for speed (~200-500ms vs 2-5s with main model).
        Skips only for trivially non-translatable input (empty, pure numbers).
        Does NOT skip for ASCII text since Roman-script Hinglish is all-ASCII
        but still needs translation.
        """
        # Skip only for empty or pure-number input
        stripped = text.strip()
        if not stripped or all(c.isdigit() or c in ' +-*/=.,()%^' for c in stripped):
            return text

        _translation_prompt = (Path(__file__).parent.parent / "prompts" / "translation.txt").read_text()
        prompt = _translation_prompt.format(text=text)

        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.llm.call_fast(
                prompt=prompt,
                json_mode=True,
            ),
        )

        import json
        raw = result.get("output_text", "")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            return parsed.get("english", text).strip()
        except (json.JSONDecodeError, AttributeError):
            return text

    async def process_turn(
        self,
        session: SessionState,
        student_message: str,
    ) -> TurnResult:
        """
        Process a single conversation turn.

        Flow: translate + safety (parallel) -> master tutor -> state update -> return response.
        """
        start_time = time.time()
        turn_id = session.get_current_turn_id()
        import asyncio

        logger.info(f"Turn started: {turn_id} for session {session.session_id}")

        # Run safety on ALL messages (including post-completion) before any processing.
        # Build safety context with original message.
        safety_context = AgentContext(
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

        # Post-completion short circuits — run safety + translation in parallel
        if session.is_complete and session.mode == "clarify_doubts":
            translated_msg, safety_result = await asyncio.gather(
                self._translate_to_english(student_message),
                self.safety_agent.execute(safety_context),
            )
            if not safety_result.is_safe:
                return TurnResult(
                    response=self._handle_unsafe_message(session, safety_result),
                    intent="unsafe", specialists_called=["safety"], state_changed=True,
                )
            return await self._process_post_completion(session, translated_msg)
        max_extension_turns = 10
        extension_turns = session.turn_count - (session.topic.study_plan.total_steps * 2 if session.topic else 0)
        if session.is_complete and (not session.allow_extension or extension_turns > max_extension_turns):
            translated_msg, safety_result = await asyncio.gather(
                self._translate_to_english(student_message),
                self.safety_agent.execute(safety_context),
            )
            if not safety_result.is_safe:
                return TurnResult(
                    response=self._handle_unsafe_message(session, safety_result),
                    intent="unsafe", specialists_called=["safety"], state_changed=True,
                )
            return await self._process_post_completion(session, translated_msg)

        # Normal flow: reuse safety_context built above
        # Run translation + safety in parallel (saves 2-5s)
        safety_start = time.time()
        translated_msg, safety_result = await asyncio.gather(
            self._translate_to_english(student_message),
            self.safety_agent.execute(safety_context),
        )
        student_message = translated_msg
        safety_duration = int((time.time() - safety_start) * 1000)

        # Increment turn counter and add translated student message
        session.increment_turn()
        session.add_message(create_student_message(student_message))

        # Build tutor context with translated message
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

        self._log_agent_event(
            session_id=session.session_id,
            turn_id=turn_id,
            agent_name="orchestrator",
            event_type="turn_started",
            input_summary=f"Student: {student_message[:100]}{'...' if len(student_message) > 100 else ''}",
            metadata={"current_step": session.current_step, "turn_count": session.turn_count},
        )

        try:

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
            elif session.mode == "practice":
                return await self._process_practice_turn(session, context, turn_id, start_time)

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
            session.add_message(create_teacher_message(tutor_output.response, audio_text=tutor_output.audio_text))

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
                audio_text=tutor_output.audio_text,
                intent=tutor_output.intent,
                specialists_called=["master_tutor"],
                state_changed=state_changed,
                visual_explanation=await self._generate_pixi_code(tutor_output.visual_explanation) if tutor_output.visual_explanation else None,
                question_format=tutor_output.question_format.model_dump() if tutor_output.question_format else None,
            )

        except Exception as e:
            logger.error(
                f"Turn failed ({type(e).__name__}): {e}",
                exc_info=True,
                extra={"session_id": session.session_id, "turn_id": turn_id},
            )
            return TurnResult(
                response="I apologize, but I had a moment of confusion. Could you please repeat that?",
                intent="error",
                specialists_called=[],
                state_changed=False,
            )

    async def process_turn_stream(
        self,
        session: SessionState,
        student_message: str,
    ) -> AsyncGenerator[Tuple[str, Union[str, TurnResult]], None]:
        """Process a turn with streaming. Yields tuples:

        - ("token", str)         — text chunk for the student-facing response
        - ("result", TurnResult) — final result with state updates applied (always last)

        Non-streamable modes (exam, post-completion) fall back to process_turn.
        """
        start_time = time.time()
        turn_id = session.get_current_turn_id()
        import asyncio

        # --- Pre-streaming checks ---

        # Build safety context with original message (used for all paths)
        safety_context = AgentContext(
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

        # Post-completion short circuits — run safety + translation in parallel
        if session.is_complete and session.mode == "clarify_doubts":
            translated_msg, safety_result = await asyncio.gather(
                self._translate_to_english(student_message),
                self.safety_agent.execute(safety_context),
            )
            if not safety_result.is_safe:
                yield ("result", TurnResult(
                    response=self._handle_unsafe_message(session, safety_result),
                    intent="unsafe", specialists_called=["safety"], state_changed=True,
                ))
                return
            result = await self._process_post_completion(session, translated_msg)
            yield ("result", result)
            return

        max_extension_turns = 10
        extension_turns = session.turn_count - (session.topic.study_plan.total_steps * 2 if session.topic else 0)
        if session.is_complete and (not session.allow_extension or extension_turns > max_extension_turns):
            translated_msg, safety_result = await asyncio.gather(
                self._translate_to_english(student_message),
                self.safety_agent.execute(safety_context),
            )
            if not safety_result.is_safe:
                yield ("result", TurnResult(
                    response=self._handle_unsafe_message(session, safety_result),
                    intent="unsafe", specialists_called=["safety"], state_changed=True,
                ))
                return
            result = await self._process_post_completion(session, translated_msg)
            yield ("result", result)
            return

        # Run translation + safety in parallel (saves 2-5s)
        safety_start = time.time()
        translated_msg, safety_result = await asyncio.gather(
            self._translate_to_english(student_message),
            self.safety_agent.execute(safety_context),
        )
        student_message = translated_msg
        safety_duration = int((time.time() - safety_start) * 1000)

        # Increment turn and add translated student message
        session.increment_turn()
        session.add_message(create_student_message(student_message))

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

        try:
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
                yield ("result", TurnResult(
                    response=response, intent="unsafe",
                    specialists_called=["safety"], state_changed=True,
                ))
                return

            # Exam, clarify_doubts, and practice: fall back to non-streaming
            if session.mode in ("exam", "clarify_doubts", "practice"):
                if session.mode == "clarify_doubts":
                    result = await self._process_clarify_turn(session, context, turn_id, start_time)
                elif session.mode == "exam":
                    result = await self._process_exam_turn(session, context, turn_id, start_time)
                else:  # practice
                    result = await self._process_practice_turn(session, context, turn_id, start_time)
                yield ("result", result)
                return

            # Streaming master tutor (teach_me mode)
            tutor_start = time.time()
            self.master_tutor.set_session(session)
            tutor_output = None

            async for msg_type, data in self.master_tutor.execute_stream(context):
                if msg_type == "token":
                    yield ("token", data)
                elif msg_type == "result":
                    tutor_output = data

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
                    "streamed": True,
                },
            )

            self._check_response_sanitization(session.session_id, turn_id, tutor_output.response)

            # Apply state updates (same as process_turn)
            state_changed = self._apply_state_updates(session, tutor_output)
            session.add_message(create_teacher_message(tutor_output.response, audio_text=tutor_output.audio_text))

            turn_entry = f"Turn {session.turn_count}: {tutor_output.turn_summary}"
            session.session_summary.turn_timeline.append(turn_entry)
            if len(session.session_summary.turn_timeline) > 30:
                session.session_summary.turn_timeline = session.session_summary.turn_timeline[-30:]

            if tutor_output.answer_correct is not None:
                mastery_values = list(session.mastery_estimates.values())
                avg_mastery = sum(mastery_values) / len(mastery_values) if mastery_values else 0.5
                if tutor_output.answer_correct and avg_mastery >= 0.6:
                    session.session_summary.progress_trend = "improving"
                elif not tutor_output.answer_correct and avg_mastery < 0.4:
                    session.session_summary.progress_trend = "struggling"
                else:
                    session.session_summary.progress_trend = "steady"

            if session.current_step_data:
                concept = session.current_step_data.concept
                if concept and concept not in session.session_summary.concepts_taught:
                    session.session_summary.concepts_taught.append(concept)

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Turn completed (streamed): {turn_id} ({duration_ms}ms)")

            self._log_agent_event(
                session_id=session.session_id,
                turn_id=turn_id,
                agent_name="orchestrator",
                event_type="turn_completed",
                duration_ms=duration_ms,
                metadata={"intent": tutor_output.intent, "state_changed": state_changed, "streamed": True},
            )

            # Yield the text result immediately so the frontend gets it without
            # waiting for the (potentially slow) Pixi code generation LLM call.
            yield ("result", TurnResult(
                response=tutor_output.response,
                audio_text=tutor_output.audio_text,
                intent=tutor_output.intent,
                specialists_called=["master_tutor"],
                state_changed=state_changed,
                visual_explanation=None,
                question_format=tutor_output.question_format.model_dump() if tutor_output.question_format else None,
            ))

            # Generate Pixi code in a separate step and yield as a "visual" message
            if tutor_output.visual_explanation:
                visual_dict = await self._generate_pixi_code(tutor_output.visual_explanation)
                if visual_dict:
                    yield ("visual", visual_dict)

        except Exception as e:
            logger.error(
                f"Streaming turn failed ({type(e).__name__}): {e}",
                exc_info=True,
                extra={"session_id": session.session_id, "turn_id": turn_id},
            )
            yield ("result", TurnResult(
                response="I apologize, but I had a moment of confusion. Could you please repeat that?",
                intent="error",
                specialists_called=[],
                state_changed=False,
            ))

    async def _process_post_completion(self, session: SessionState, student_message: str) -> TurnResult:
        """Handle post-completion messages (shared by process_turn and process_turn_stream)."""
        session.add_message(create_student_message(student_message))
        response = await self._generate_post_completion_response(session, student_message)
        session.add_message(create_teacher_message(response))
        return TurnResult(
            response=response,
            intent="session_complete",
            specialists_called=[],
            state_changed=True,
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

    def _handle_explanation_phase(self, session: SessionState, output: TutorTurnOutput) -> bool:
        """Handle explanation phase lifecycle based on tutor output."""
        current_step = session.current_step_data
        if not current_step or current_step.type != "explain":
            return False

        changed = False

        # Initialize explanation phase if not started
        ep = session.get_current_explanation()
        if ep is None or ep.step_id != current_step.step_id:
            ep = session.start_explanation(current_step.concept, current_step.step_id)
            changed = True

        # Handle prior knowledge skip
        if output.student_shows_prior_knowledge:
            ep.skip_reason = "student_demonstrated_knowledge"
            ep.phase = "complete"
            session.current_explanation_concept = None
            logger.info(
                f"Explanation skipped for '{ep.concept}' — student demonstrated prior knowledge"
            )
            return True

        # Apply phase transition from tutor output
        if output.explanation_phase_update:
            new_phase = output.explanation_phase_update
            if new_phase in ("opening", "explaining", "informal_check", "complete"):
                ep.phase = new_phase
                changed = True
            elif new_phase == "skip":
                ep.phase = "complete"
                ep.skip_reason = "tutor_skipped"
                session.current_explanation_concept = None
                return True

        # Track building blocks covered
        if output.explanation_building_blocks_covered:
            for block in output.explanation_building_blocks_covered:
                if block not in ep.building_blocks_covered:
                    ep.building_blocks_covered.append(block)
            changed = True

        # Handle informal check result
        if output.student_shows_understanding is not None:
            if output.student_shows_understanding:
                ep.informal_check_passed = True
                ep.phase = "complete"
                session.current_explanation_concept = None
                changed = True
            else:
                ep.student_engaged = True
                changed = True

        # Increment turn counter
        ep.tutor_turns_in_phase += 1

        # Mark complete if phase is done
        if ep.phase == "complete" and session.current_explanation_concept == current_step.concept:
            session.current_explanation_concept = None

        return changed

    def _apply_state_updates(self, session: SessionState, output: TutorTurnOutput) -> bool:
        """Apply structured state updates from master tutor output."""
        changed = False

        # 0. Handle explanation phase lifecycle
        if self._handle_explanation_phase(session, output):
            changed = True

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

        # 4. Advance step + coverage tracking (with explanation guard)
        if output.advance_to_step and output.advance_to_step > session.current_step:
            # Check if current step is an explain step that isn't complete yet
            current_step = session.current_step_data
            if current_step and current_step.type == "explain" and not session.can_advance_past_explanation():
                logger.info(
                    f"Advancement to step {output.advance_to_step} blocked — "
                    f"explanation for '{current_step.concept}' is not yet complete "
                    f"(phase={session.get_current_explanation().phase if session.get_current_explanation() else 'none'})"
                )
            else:
                for step_id in range(session.current_step, output.advance_to_step):
                    step = session.topic.study_plan.get_step(step_id) if session.topic else None
                    if step:
                        session.concepts_covered_set.add(step.concept)
                while session.current_step < output.advance_to_step:
                    session.advance_step()
                # Clear explanation concept when advancing past explain step
                if current_step and current_step.type == "explain":
                    session.current_explanation_concept = None
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

        session.add_message(create_teacher_message(tutor_output.response, audio_text=tutor_output.audio_text))

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
            audio_text=tutor_output.audio_text,
            intent=tutor_output.intent,
            specialists_called=["master_tutor"],
            state_changed=True,
            visual_explanation=await self._generate_pixi_code(tutor_output.visual_explanation) if tutor_output.visual_explanation else None,
            question_format=tutor_output.question_format.model_dump() if tutor_output.question_format else None,
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

        # Fractional scoring: use answer_score if available, fallback to binary
        score = tutor_output.answer_score if tutor_output.answer_score is not None else (1.0 if tutor_output.answer_correct else 0.0)
        current_q.score = round(max(0.0, min(1.0, score)), 2)
        current_q.marks_rationale = tutor_output.marks_rationale or tutor_output.turn_summary or ""

        # Derive categorical result from fractional score
        if current_q.score >= 0.8:
            current_q.result = "correct"
            session.exam_total_correct += 1
        elif current_q.score >= 0.2:
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

            total = len(session.exam_questions)
            total_score = session.exam_feedback.score
            review_lines = [
                f"Q{q.question_idx + 1}: {q.score:.1f}/1 — {q.marks_rationale}"
                for q in session.exam_questions
            ]
            response = (
                "Exam complete!\n"
                f"Final Score: **{total_score:.1f}/{total}** ({session.exam_feedback.percentage:.1f}%)\n\n"
                "Question Review:\n"
                + "\n".join(review_lines)
            )
        else:
            next_q = session.exam_questions[session.exam_current_question_idx]
            response = f"**Question {next_q.question_idx + 1}:** {next_q.question_text}"

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

    async def _process_practice_turn(
        self, session: SessionState, context: AgentContext, turn_id: str, start_time: float
    ) -> TurnResult:
        """Process a Practice turn.

        Reuses _apply_state_updates() and _handle_question_lifecycle() from the
        teach_me path for scaffolded correction, misconception tracking, mastery
        updates, and question lifecycle state. Adds practice-specific question
        counting and mastery completion check on top.
        """
        # Count this student turn as an answered question.
        # Increment BEFORE the LLM call so even if the tutor ends the session
        # this turn, the final answer is counted.
        session.practice_questions_answered += 1

        # Track per-concept question count for the "at least 2 per concept" rule.
        # We use the concept from the CURRENT pending question (set on the
        # previous tutor turn) — that's the concept this student answer pertains to.
        if session.last_question and session.last_question.concept:
            concept = session.last_question.concept
            session.practice_concept_question_counts[concept] = (
                session.practice_concept_question_counts.get(concept, 0) + 1
            )

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
                "mode": "practice",
                "intent": tutor_output.intent,
                "answer_correct": tutor_output.answer_correct,
                "question_asked": tutor_output.question_asked is not None,
                "session_complete": tutor_output.session_complete,
                "questions_answered": session.practice_questions_answered,
            },
        )

        self._check_response_sanitization(session.session_id, turn_id, tutor_output.response)

        # Reuse existing state update machinery. This gives practice sessions:
        #  - scaffolded correction (wrong → probe → hint → explain)
        #  - misconception tracking
        #  - question lifecycle state
        #  - mastery updates
        # We ignore advance_to_step since practice has no step progression —
        # _apply_state_updates guards against step advancement when session_complete
        # is set on a non-final step, but practice plans have no meaningful concept
        # of a "final step", so we just don't look at advance_to_step in practice.
        self._apply_state_updates(session, tutor_output)

        # Practice-specific mastery completion check, layered on top of standard updates.
        self._check_practice_mastery(session, tutor_output)

        session.add_message(create_teacher_message(
            tutor_output.response, audio_text=tutor_output.audio_text
        ))

        # Update turn timeline
        turn_entry = f"Turn {session.turn_count}: {tutor_output.turn_summary}"
        session.session_summary.turn_timeline.append(turn_entry)
        if len(session.session_summary.turn_timeline) > 30:
            session.session_summary.turn_timeline = session.session_summary.turn_timeline[-30:]

        duration_ms = int((time.time() - start_time) * 1000)
        self._log_agent_event(
            session_id=session.session_id,
            turn_id=turn_id,
            agent_name="orchestrator",
            event_type="turn_completed",
            duration_ms=duration_ms,
            metadata={
                "mode": "practice",
                "intent": tutor_output.intent,
                "questions_answered": session.practice_questions_answered,
                "mastery_achieved": session.practice_mastery_achieved,
            },
        )

        return TurnResult(
            response=tutor_output.response,
            audio_text=tutor_output.audio_text,
            intent=tutor_output.intent,
            specialists_called=["master_tutor"],
            state_changed=True,
            visual_explanation=await self._generate_pixi_code(tutor_output.visual_explanation)
                if tutor_output.visual_explanation else None,
            question_format=tutor_output.question_format.model_dump()
                if tutor_output.question_format else None,
        )

    def _check_practice_mastery(self, session: SessionState, tutor_output: "TutorTurnOutput") -> None:
        """Enforce FR-27: practice session completion criteria.

        Rules:
        - Minimum 5 questions answered before session can end on mastery
        - 70% mastery across ALL canonical concepts (not just touched ones)
        - At least 2 questions per key concept
        - Maximum ~20 questions — hard cap for attention-aware wrap-up
        """
        MIN_QUESTIONS = 5
        MAX_QUESTIONS = 20
        MASTERY_THRESHOLD = 0.7
        MIN_QUESTIONS_PER_CONCEPT = 2

        if session.practice_mastery_achieved:
            return

        # Hard cap — force wrap up regardless of mastery state
        if session.practice_questions_answered >= MAX_QUESTIONS:
            session.practice_mastery_achieved = True
            logger.info(
                f"Practice session {session.session_id} hit max questions cap "
                f"({session.practice_questions_answered})"
            )
            return

        # Minimum gate
        if session.practice_questions_answered < MIN_QUESTIONS:
            return

        # All canonical concepts must be at/above threshold.
        # mastery_estimates is seeded with all concepts at 0.0 in create_session
        # for practice, so this checks the full topic — not a narrow slice.
        if not session.mastery_estimates:
            return

        all_mastered = all(
            score >= MASTERY_THRESHOLD
            for score in session.mastery_estimates.values()
        )
        if not all_mastered:
            return

        # Each concept must have had at least 2 questions
        all_covered = all(
            session.practice_concept_question_counts.get(concept, 0) >= MIN_QUESTIONS_PER_CONCEPT
            for concept in session.mastery_estimates.keys()
        )
        if not all_covered:
            return

        # If LLM also signaled completion, honor it.
        # Otherwise, we let the LLM run one more turn — it will see full mastery
        # in its context and wrap up naturally on the next turn.
        if tutor_output.session_complete:
            session.practice_mastery_achieved = True
            logger.info(f"Practice session {session.session_id} reached mastery")

    async def generate_practice_welcome(self, session: SessionState) -> tuple[str, Optional[str]]:
        """Generate a practice-specific welcome message.

        Uses master_tutor.generate_practice_welcome() which loads the
        PRACTICE_WELCOME_PROMPT (question-first, not explanation-first).
        """
        try:
            self.master_tutor.set_session(session)
            output = await self.master_tutor.generate_practice_welcome(session)

            # Save the first question to session state so scaffolded correction
            # works on the very first student response.
            if output.question_asked:
                from tutor.models.session_state import Question
                current_concept = (
                    session.current_step_data.concept if session.current_step_data else None
                )
                session.set_question(Question(
                    question_text=output.question_asked,
                    expected_answer=output.expected_answer or "",
                    concept=output.question_concept or current_concept or "practice",
                ))

            return output.response, output.audio_text
        except Exception as e:
            logger.warning(f"Master tutor practice welcome failed, using fallback: {e}")
            topic = session.topic.topic_name if session.topic else "this topic"
            fallback = f"Let's practice {topic}! Ready?"
            return fallback, fallback

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
        total_score = round(sum(q.score for q in session.exam_questions), 1)
        return ExamFeedback(
            score=total_score,
            total=total,
            percentage=round(total_score / total * 100, 1) if total else 0.0,
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

    def _parse_welcome_result(self, result: dict, fallback: str) -> tuple[str, str | None]:
        """Parse LLM JSON result into (message, audio_text) tuple."""
        import json
        raw = result.get("output_text", "")
        # Try parsing JSON from the LLM response
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            response = parsed.get("response", fallback).strip()
            audio_text = parsed.get("audio_text")
            if audio_text:
                audio_text = audio_text.strip()
            return (response, audio_text)
        except (json.JSONDecodeError, AttributeError):
            # LLM returned plain text instead of JSON — use as message, no audio_text
            return (raw.strip() if raw else fallback, None)

    async def generate_welcome_message(self, session: SessionState) -> tuple[str, str | None]:
        """Generate a welcome message for a new session.

        Returns (message, audio_text) tuple.
        """
        if not session.topic:
            return ("Welcome! Let's start learning together.", None)

        from tutor.prompts.language_utils import get_response_language_instruction, get_audio_language_instruction

        prompt = WELCOME_MESSAGE_PROMPT.render(
            grade=session.student_context.grade,
            topic_name=session.topic.topic_name,
            subject=session.topic.subject,
            learning_objectives="\n".join(
                f"- {obj}" for obj in session.topic.guidelines.learning_objectives
            ),
            language_level=session.student_context.language_level,
            preferred_examples=", ".join(session.student_context.preferred_examples),
            response_language_instruction=get_response_language_instruction(
                session.student_context.text_language_preference
            ),
            audio_language_instruction=get_audio_language_instruction(
                session.student_context.audio_language_preference
            ),
        )

        # Add personality context for personalized welcome
        if session.student_context.tutor_brief:
            prompt += (
                f"\n\nStudent Personality:\n{session.student_context.tutor_brief}\n\n"
                "Use this personality to make the welcome message feel personal and tailored. "
                "Address the student by name."
            )
        elif session.student_context.student_name:
            prompt += f"\n\nThe student's name is {session.student_context.student_name}. Address them by name."

        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.llm.call(
                prompt=prompt,
                reasoning_effort="none",
                json_mode=True,
            ),
        )

        return self._parse_welcome_result(result, "Welcome! Let's start learning.")

    async def generate_clarify_welcome(self, session: SessionState) -> tuple[str, str | None]:
        """Generate a welcome message for Clarify Doubts mode.

        Returns (message, audio_text) tuple.
        """
        if not session.topic:
            return ("Hi! I'm here to help answer your questions. What would you like to know?", None)

        from tutor.prompts.language_utils import get_response_language_instruction, get_audio_language_instruction

        topic_name = session.topic.topic_name
        response_lang_instr = get_response_language_instruction(session.student_context.text_language_preference)
        audio_lang_instr = get_audio_language_instruction(session.student_context.audio_language_preference)
        prompt = (
            f"You are a friendly tutor starting a Clarify Doubts session with a Grade {session.student_context.grade} student.\n\n"
            f"Topic: {topic_name}\n"
            f"Subject: {session.topic.subject}\n\n"
            f"Generate a warm, brief welcome that:\n"
            f"1. Greets the student\n"
            f"2. Says you're here to answer their questions about {topic_name}\n"
            f"3. Invites them to ask whatever they're curious or confused about\n\n"
            f"Keep it to 1-2 sentences. Use {session.student_context.language_level} language. No emojis.\n\n"
            f"Return JSON with two fields:\n"
            f'- "response": The welcome message. {response_lang_instr}\n'
            f'- "audio_text": The spoken version for TTS. {audio_lang_instr}'
        )

        if session.student_context.tutor_brief:
            prompt += (
                f"\n\nStudent Personality:\n{session.student_context.tutor_brief}\n\n"
                "Use this personality to make the welcome feel personal. Address the student by name."
            )
        elif session.student_context.student_name:
            prompt += f"\n\nThe student's name is {session.student_context.student_name}. Address them by name."

        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.llm.call(prompt=prompt, reasoning_effort="none", json_mode=True),
        )
        return self._parse_welcome_result(result, f"Hi! I'm here to help with {topic_name}. What questions do you have?")

    async def generate_exam_welcome(self, session: SessionState) -> tuple[str, str | None]:
        """Generate a welcome message for Exam mode.

        Returns (message, audio_text) tuple.
        """
        if not session.topic:
            return ("Let's test your knowledge! I'll ask you some questions. Ready?", None)

        from tutor.prompts.language_utils import get_response_language_instruction, get_audio_language_instruction

        topic_name = session.topic.topic_name
        num_questions = len(session.exam_questions) if session.exam_questions else 7
        response_lang_instr = get_response_language_instruction(session.student_context.text_language_preference)
        audio_lang_instr = get_audio_language_instruction(session.student_context.audio_language_preference)
        prompt = (
            f"You are a friendly tutor starting an exam session with a Grade {session.student_context.grade} student.\n\n"
            f"Topic: {topic_name}\n"
            f"Number of questions: {num_questions}\n\n"
            f"Generate a brief welcome that:\n"
            f"1. Greets the student warmly\n"
            f"2. Explains this is a {num_questions}-question exam on {topic_name}\n"
            f"3. Encourages them to do their best\n"
            f"4. Asks if they're ready\n\n"
            f"Keep it to 2-3 sentences. Use {session.student_context.language_level} language. No emojis.\n\n"
            f"Return JSON with two fields:\n"
            f'- "response": The welcome message. {response_lang_instr}\n'
            f'- "audio_text": The spoken version for TTS. {audio_lang_instr}'
        )

        if session.student_context.tutor_brief:
            prompt += (
                f"\n\nStudent Personality:\n{session.student_context.tutor_brief}\n\n"
                "Use this personality to make the welcome feel personal. Address the student by name."
            )
        elif session.student_context.student_name:
            prompt += f"\n\nThe student's name is {session.student_context.student_name}. Address them by name."

        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.llm.call(prompt=prompt, reasoning_effort="none", json_mode=True),
        )
        return self._parse_welcome_result(result, f"Let's test your knowledge of {topic_name}! I'll ask you {num_questions} questions. Ready?")

    async def generate_tutor_welcome(self, session: SessionState) -> tuple[str, Optional[str]]:
        try:
            self.master_tutor.set_session(session)
            output = await self.master_tutor.generate_welcome(session)
            return output.response, output.audio_text
        except Exception as e:
            logger.warning(f"Master tutor welcome failed, using fallback: {e}")
            topic = session.topic.topic_name if session.topic else "this topic"
            fallback = f"Let's learn about {topic}! I'll walk you through it, and then we can talk about any questions."
            return fallback, fallback

    async def generate_bridge_turn(self, session: SessionState, bridge_type: str) -> TurnResult:
        try:
            self.master_tutor.set_session(session)
            output = await self.master_tutor.generate_bridge(session, bridge_type)

            state_changed = self._apply_state_updates(session, output)

            session.add_message(create_teacher_message(output.response, audio_text=output.audio_text))
            session.session_summary.turn_timeline.append(output.turn_summary)

            return TurnResult(
                response=output.response,
                audio_text=output.audio_text,
                intent=output.intent,
                state_changed=state_changed,
                question_format=output.question_format.model_dump() if output.question_format else None,
            )
        except Exception as e:
            logger.warning(f"Master tutor bridge failed, using fallback: {e}")
            if bridge_type == "understood":
                fallback = "Great! Now let's make sure you've got it. Can you tell me in your own words what you just learned?"
            else:
                fallback = "No worries — let me try explaining this a different way."

            session.add_message(create_teacher_message(fallback, audio_text=fallback))

            return TurnResult(response=fallback, audio_text=fallback, intent="continuation", state_changed=False)

    async def generate_simplified_card(
        self,
        session: SessionState,
        card_title: str,
        card_content: str,
        all_cards: list[dict],
        reason: str,
        previous_attempts: list[dict] | None = None,
    ) -> dict:
        """Generate a simplified version of a specific explanation card.

        Returns a dict with card content (title, content, audio_text, card_type).
        """
        try:
            self.master_tutor.set_session(session)
            result = await self.master_tutor.generate_simplified_card(
                session=session,
                card_title=card_title,
                card_content=card_content,
                all_cards=all_cards,
                reason=reason,
                previous_attempts=previous_attempts or [],
            )
            return result
        except Exception as e:
            logger.exception(f"Simplified card generation failed: {e}")
            raise
