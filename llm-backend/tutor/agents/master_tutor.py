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
from tutor.prompts.clarify_doubts_prompts import (
    CLARIFY_DOUBTS_SYSTEM_PROMPT,
    CLARIFY_DOUBTS_TURN_PROMPT,
)
from tutor.prompts.templates import format_list_for_prompt
from tutor.utils.prompt_utils import format_conversation_history


class VisualAnimationStep(BaseModel):
    """A single step in a visual animation sequence."""
    action: str = Field(description="What happens: 'appear', 'highlight', 'merge', 'label', 'fade'")
    target: str = Field(description="Which group/element: 'group1', 'group2', 'result', 'all', or a part index like 'part_3'")
    label: Optional[str] = Field(default=None, description="Text label to display during this step")
    delay_ms: int = Field(default=600, description="Delay before this step in milliseconds")


class VisualExplanation(BaseModel):
    """Structured visual explanation that the frontend renders as an animation."""
    scene_type: str = Field(
        description="Type of visual: 'addition', 'subtraction', 'fraction', 'multiplication', 'number_line', 'counting'. "
        "Use null/omit if no visual is helpful for this turn."
    )
    title: Optional[str] = Field(default=None, description="Short title for the visual (e.g., '4 + 4 = 8')")
    # Addition/subtraction/counting fields
    group1_count: Optional[int] = Field(default=None, description="Number of objects in first group")
    group2_count: Optional[int] = Field(default=None, description="Number of objects in second group")
    result_count: Optional[int] = Field(default=None, description="Total/result count")
    object_emoji: Optional[str] = Field(default=None, description="Emoji to represent objects (e.g., '🍎', '⭐')")
    # Fraction fields
    total_parts: Optional[int] = Field(default=None, description="Total equal parts in the fraction bar")
    highlighted_parts: Optional[int] = Field(default=None, description="Number of parts to highlight")
    fraction_label: Optional[str] = Field(default=None, description="Fraction label like '3/4'")
    # Multiplication fields
    rows: Optional[int] = Field(default=None, description="Number of rows in multiplication array")
    cols: Optional[int] = Field(default=None, description="Number of columns in multiplication array")
    # Animation steps
    animation_steps: list[VisualAnimationStep] = Field(
        default_factory=list,
        description="Ordered animation steps. If empty, the frontend uses a default animation sequence for the scene_type."
    )
    narration: Optional[str] = Field(default=None, description="Short narration text synced with the visual")


class MasteryUpdate(BaseModel):
    """A single mastery score update for a concept."""
    concept: str = Field(description="The concept name")
    score: float = Field(description="Mastery score from 0.0 to 1.0")


class TutorTurnOutput(BaseModel):
    """Structured output from the master tutor — response + state updates."""

    response: str = Field(description="Your response to the student as the tutor")
    audio_text: str = Field(
        description="Hinglish (Hindi-English mix) casual spoken version of your response for TTS. "
        "Use Roman script throughout. Mix Hindi conversational glue with English technical terms. "
        "Never shown to the student — audio only."
    )
    intent: str = Field(
        description="What the student was doing: answer, answer_change, question, confusion, novel_strategy, off_topic, or continuation"
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
    answer_score: Optional[float] = Field(
        default=None, description="Fractional score 0.0–1.0 for the student's answer. Used in exam mode for partial credit."
    )
    marks_rationale: Optional[str] = Field(
        default=None, description="Brief justification for the score awarded (1-2 sentences)"
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

    # Explanation phase tracking (only used during explain steps)
    explanation_phase_update: Optional[str] = Field(
        default=None,
        description="Update explanation phase: 'opening', 'explaining', 'informal_check', 'complete', or 'skip'. Only set during explain steps."
    )
    explanation_building_blocks_covered: list[str] = Field(
        default_factory=list,
        description="Building blocks covered in THIS turn (from the step's building_blocks list)"
    )
    student_shows_understanding: Optional[bool] = Field(
        default=None,
        description="During informal_check phase: did the student demonstrate understanding? null if not checking."
    )
    student_shows_prior_knowledge: Optional[bool] = Field(
        default=None,
        description="Set true if the student clearly demonstrates they already know this concept and explanation can be skipped."
    )

    # Session completion
    session_complete: bool = Field(
        default=False,
        description="Set to true when the student has completed the final step and demonstrated understanding. This ends the session.",
    )

    # Visual explanation (optional — only when a visual would genuinely help)
    visual_explanation: Optional[VisualExplanation] = Field(
        default=None,
        description="Optional structured visual explanation to render as an animation. "
        "Include ONLY when a visual would genuinely help the student understand the concept better — "
        "e.g., counting, addition, subtraction, fractions, multiplication arrays. "
        "Do NOT include for every turn — only when explaining a concept that benefits from visual representation. "
        "Set to null when no visual is needed."
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

    def _compute_pacing_directive(self, session: SessionState) -> str:
        """One-line pacing instruction based on session signals."""
        turn = session.turn_count  # already 1 on first msg (orchestrator increments before tutor)
        mastery_values = list(session.mastery_estimates.values())
        avg_mastery = sum(mastery_values) / len(mastery_values) if mastery_values else 0.0
        trend = session.session_summary.progress_trend

        if turn == 1:
            return (
                "PACING: FIRST TURN — Start with a curiosity-building hook that connects "
                "to the student's world. End with an inviting question like 'Have you ever "
                "noticed...?' or 'What do you think would happen if...?' — NOT a test "
                "question. Keep it to 2-3 sentences. Set explanation_phase_update='opening'."
            )

        # Explanation-aware pacing: when current step is an explain step
        current_step = session.current_step_data
        if current_step and current_step.type == "explain":
            ep = session.get_current_explanation()
            if ep:
                return self._compute_explanation_pacing(ep, current_step)
            else:
                # Explain step but no explanation phase initialized yet — start it
                return (
                    "PACING: EXPLAIN — Begin with a curiosity hook for this concept. "
                    "ONE idea in 2-3 sentences with an everyday example. End with an "
                    "engaging check-in: 'Does that make sense?' Set explanation_phase_update='opening'."
                )

        # Also accelerate if most concepts are strong (early fast-track detection)
        if mastery_values:
            # Count concepts with mastery >= 0.7
            strong_concepts = sum(1 for v in mastery_values if v >= 0.7)
            total_concepts = len(mastery_values)
            if strong_concepts >= total_concepts * 0.6 and total_concepts > 0:
                # Most concepts are strong — treat as accelerate-eligible
                if avg_mastery >= 0.65 and trend == "improving":
                    avg_mastery = 0.8  # Force accelerate path

        if avg_mastery >= 0.8 and trend == "improving":
            if session.is_complete:
                return (
                    "PACING: EXTEND — Student has aced the plan. Push to harder territory — "
                    "bigger numbers, trickier problems, edge cases. Do NOT wrap up "
                    "or defer to 'next session'. Challenge them. Keep responses concise."
                )
            return (
                "PACING: ACCELERATE — Student is doing well. Keep explanations concise "
                "but still TEACH before testing — explain the next concept briefly (1-2 sentences) "
                "then check understanding. Don't skip explanations entirely — condense them. "
                "If they request harder material, go BEYOND the study plan — larger numbers, "
                "edge cases, puzzles. Cut praise to brief acknowledgments."
            )

        has_real_data = any(v > 0 for v in mastery_values)
        if (has_real_data and avg_mastery < 0.4) or trend == "struggling":
            return (
                "PACING: SIMPLIFY — Student is struggling. Shorter sentences, 1-2 ideas "
                "per response. Yes/no or simple-choice questions. ONE analogy max. "
                "No tables or multi-step breakdowns. After a correct answer, give them "
                "another similar problem to consolidate BEFORE introducing new concepts."
            )

        # Check for recent breakthrough after struggle: consolidate
        if has_real_data and 0.4 <= avg_mastery < 0.65 and trend == "steady":
            if session.last_question and session.last_question.wrong_attempts >= 2:
                return (
                    "PACING: CONSOLIDATE — Student is getting it but still shaky. "
                    "Give them a similar problem at the SAME level to build confidence. "
                    "Don't introduce new concepts yet. Keep it short and encouraging."
                )

        pacing = "PACING: STEADY — Progressing normally. One idea at a time."

        # Add attention span warning if session is getting long
        attention_span = getattr(session.student_context, 'attention_span', None) if session.student_context else None
        if attention_span and turn > 1:
            turn_thresholds = {"short": 8, "medium": 14, "long": 20}
            threshold = turn_thresholds.get(attention_span)
            if threshold and turn >= threshold:
                pacing += (
                    f" SESSION LENGTH: This student's attention span is '{attention_span}' "
                    f"and we're at turn {turn}. Start wrapping up — summarize what was covered "
                    f"and suggest continuing next time."
                )

        return pacing

    @staticmethod
    def _compute_explanation_pacing(ep, current_step) -> str:
        """Compute pacing directive specific to explanation phases."""
        from tutor.models.session_state import ExplanationPhase

        blocks = current_step.explanation_building_blocks or []
        blocks_remaining = [b for b in blocks if b not in ep.building_blocks_covered]

        if ep.phase == "opening":
            return (
                "PACING: EXPLAIN (opening) — Begin the core explanation. Present ONE idea "
                "in 2-3 sentences with an everyday example. Check in: 'Does that make sense?' "
                "Do NOT ask a test question yet. Set explanation_phase_update='explaining'."
            )

        if ep.phase == "explaining":
            if blocks_remaining:
                next_block = blocks_remaining[0]
                remaining_count = len(blocks_remaining)
                return (
                    f"PACING: EXPLAIN (building) — Continue explaining. Cover the next idea: "
                    f"'{next_block}'. ({remaining_count} building block(s) remaining — do NOT skip ahead "
                    f"to questions.) Use a different representation (story, real-world example, "
                    f"visual description). ONE idea per turn. Add this to "
                    f"explanation_building_blocks_covered. Keep explanation_phase_update='explaining'. "
                    f"Do NOT set advance_to_step or ask test questions yet."
                )
            else:
                return (
                    "PACING: EXPLAIN (summarize) — All building blocks covered. Summarize the "
                    "key idea in 1-2 sentences. Then ask an informal understanding check: "
                    "'Can you explain this back in your own words?' or 'What would happen if...?' "
                    "Set explanation_phase_update='informal_check'."
                )

        if ep.phase == "informal_check":
            if ep.informal_check_passed:
                return (
                    "PACING: EXPLAIN (done) — Student showed understanding. Acknowledge briefly "
                    "and transition naturally to the next activity. Set explanation_phase_update='complete'."
                )
            else:
                return (
                    "PACING: EXPLAIN (check) — Evaluate the student's response to the informal check. "
                    "If they show understanding, set student_shows_understanding=true and "
                    "explanation_phase_update='complete'. If not, clarify the gap, try a different "
                    "angle, and ask again. Keep explanation_phase_update='informal_check'."
                )

        # Phase is complete or not_started — fall through to normal pacing
        return "PACING: STEADY — Progressing normally. One idea at a time."

    @staticmethod
    def _build_explanation_context(session: SessionState) -> str:
        """Build explanation plan context for the turn prompt."""
        current_step = session.current_step_data
        if not current_step or current_step.type != "explain":
            return ""

        ep = session.get_current_explanation()
        lines = ["## Explanation Plan"]

        if current_step.explanation_approach:
            lines.append(f"**Approach**: {current_step.explanation_approach}")
        if current_step.explanation_analogy:
            lines.append(f"**Suggested Analogy**: {current_step.explanation_analogy}")

        blocks = current_step.explanation_building_blocks or []
        if blocks:
            covered = ep.building_blocks_covered if ep else []
            remaining = [b for b in blocks if b not in covered]
            lines.append(f"**Building Blocks** (cover one per turn):")
            for b in blocks:
                marker = "done" if b in covered else "TODO"
                lines.append(f"  - [{marker}] {b}")
            if remaining:
                lines.append(f"**Next to cover**: {remaining[0]}")

        if ep:
            lines.append(f"**Current Phase**: {ep.phase}")
            lines.append(f"**Tutor Turns in Explanation**: {ep.tutor_turns_in_phase}")
            lines.append(f"**Min Turns Required**: {current_step.min_explanation_turns}")
            if ep.informal_check_passed:
                lines.append("**Informal Check**: PASSED")

        return "\n".join(lines)

    def _compute_student_style(self, session: SessionState) -> str:
        """Compute response-style guidance from student's communication patterns."""
        student_msgs = [
            m for m in session.conversation_history if m.role == "student"
        ]
        if not student_msgs:
            return "STYLE: Unknown (first turn). Start short."

        # Word count
        word_counts = [len(m.content.split()) for m in student_msgs]
        avg_words = sum(word_counts) / len(word_counts)

        # Engagement signals
        asks_questions = any("?" in m.content for m in student_msgs)
        uses_emojis = any(
            any(ord(c) > 0x1F600 for c in m.content) for m in student_msgs
        )
        # Disengagement: are responses getting shorter over 4+ messages?
        shortening = False
        if len(word_counts) >= 4:
            recent = word_counts[-4:]
            shortening = recent[-1] < recent[0] * 0.4 and recent[-1] <= 5

        parts = []
        if avg_words <= 5:
            parts.append(f"STYLE: QUIET ({avg_words:.0f} words/msg avg) — respond in 2-3 sentences MAX.")
        elif avg_words <= 15:
            parts.append(f"STYLE: Moderate ({avg_words:.0f} words/msg) — 3-5 sentences.")
        else:
            parts.append(f"STYLE: Expressive ({avg_words:.0f} words/msg) — can elaborate more.")

        if asks_questions:
            parts.append("Student asks questions — encourage this, answer them.")
        if uses_emojis:
            parts.append("Student uses emojis — you can mirror lightly.")
        if shortening:
            parts.append("⚠️ Responses getting shorter — possible disengagement. Re-engage: try a different angle or ask what they think.")

        return " ".join(parts)

    def build_prompt(self, context: AgentContext) -> str:
        session = self._session
        if not session:
            raise ValueError("Session not set. Call set_session() before execute().")

        system_prompt = self._build_system_prompt(session)
        turn_prompt = self._build_turn_prompt(session, context)

        return f"{system_prompt}\n\n---\n\n{turn_prompt}"

    def _build_system_prompt(self, session: SessionState) -> str:
        from tutor.prompts.language_utils import get_response_language_instruction, get_audio_language_instruction

        topic = session.topic
        personalization_block = self._build_personalization_block(session.student_context)

        response_language_instruction = get_response_language_instruction(
            session.student_context.text_language_preference
        )
        audio_language_instruction = get_audio_language_instruction(
            session.student_context.audio_language_preference
        )

        if session.mode == "clarify_doubts":
            concepts = topic.study_plan.get_concepts()
            concepts_list = "\n".join(f"- {c}" for c in concepts) if concepts else "None"
            return CLARIFY_DOUBTS_SYSTEM_PROMPT.render(
                grade=session.student_context.grade,
                topic_name=topic.topic_name,
                subject=topic.subject,
                curriculum_scope=topic.guidelines.scope_boundary,
                concepts_list=concepts_list,
                language_level=session.student_context.language_level,
                personalization_block=personalization_block,
                response_language_instruction=response_language_instruction,
                audio_language_instruction=audio_language_instruction,
            )

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
            personalization_block=personalization_block,
            topic_name=topic.topic_name,
            curriculum_scope=topic.guidelines.scope_boundary,
            steps_formatted=steps_formatted,
            common_misconceptions=misconceptions,
            response_language_instruction=response_language_instruction,
            audio_language_instruction=audio_language_instruction,
        )

    @staticmethod
    def _build_personalization_block(ctx) -> str:
        """Build a personalization section from student context profile data."""
        # If tutor_brief exists, use rich personality
        if getattr(ctx, 'tutor_brief', None):
            return f"## Student Personality Profile\n{ctx.tutor_brief}\n"

        # Fallback: current minimal personalization
        lines = []
        if getattr(ctx, 'student_name', None):
            lines.append(f"The student's name is {ctx.student_name}. Address them by name.")
        if getattr(ctx, 'student_age', None):
            lines.append(f"The student is {ctx.student_age} years old.")
        if getattr(ctx, 'about_me', None):
            lines.append(f"About the student: {ctx.about_me}")
        if not lines:
            return ""
        return "## Student Profile\n" + "\n".join(lines) + "\n"

    def _build_turn_prompt(self, session: SessionState, context: AgentContext) -> str:
        if session.mode == "clarify_doubts":
            return self._build_clarify_turn_prompt(session, context)

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
            # Detect recurring misconceptions (mentioned 2+ times)
            desc_counts: dict[str, int] = {}
            for m in session.misconceptions:
                desc_counts[m.description] = desc_counts.get(m.description, 0) + 1
            recurring = [d for d, c in desc_counts.items() if c >= 2]
            misconception_parts = [m.description for m in session.misconceptions]
            misconceptions = ", ".join(misconception_parts)
            if recurring:
                misconceptions += (
                    f"\n⚠️ RECURRING MISCONCEPTION(S): {'; '.join(recurring)} — "
                    "this keeps reappearing. Name it explicitly to the student and "
                    "create a targeted exercise to address it directly."
                )
        else:
            misconceptions = "None detected"

        if session.session_summary.turn_timeline:
            turn_timeline = " | ".join(session.session_summary.turn_timeline[-5:])
        else:
            turn_timeline = "Session just started"

        if session.awaiting_response and session.last_question:
            q = session.last_question
            attempt_num = q.wrong_attempts + 1

            if q.wrong_attempts == 0:
                strategy = "Evaluate their answer."
            elif q.wrong_attempts == 1:
                strategy = "PROBING QUESTION — help them find the error."
            elif q.wrong_attempts == 2:
                strategy = "TARGETED HINT — point at the specific mistake."
            elif q.wrong_attempts == 3:
                strategy = (
                    "EXPLAIN directly and warmly. Previous approaches haven't "
                    "worked — try a COMPLETELY DIFFERENT method (e.g., simpler "
                    "sub-problem, visual/hands-on activity, work backwards)."
                )
            else:
                strategy = (
                    "⚠️ STRATEGY CHANGE NEEDED — Student has failed this 4+ times. "
                    "STOP retrying the same problem. Step BACK to a simpler prerequisite "
                    "skill, or break the problem into smaller pieces they can succeed at."
                )

            prev = ""
            if q.previous_student_answers:
                prev = f"\nPrevious wrong answers: {'; '.join(q.previous_student_answers[-3:])}"

            awaiting_answer_section = (
                f"**IMPORTANT — Student is answering (attempt #{attempt_num}):**\n"
                f"Question: {q.question_text}\n"
                f"Expected: {q.expected_answer}\n"
                f"Concept: {q.concept}\n"
                f"Strategy: {strategy}{prev}"
            )
        else:
            awaiting_answer_section = ""

        # Exam mode: inject exam question context with expected answer and scoring instructions
        if session.mode == "exam" and session.exam_current_question_idx < len(session.exam_questions):
            eq = session.exam_questions[session.exam_current_question_idx]
            awaiting_answer_section = (
                f"**EXAM EVALUATION — Question {eq.question_idx + 1}/{len(session.exam_questions)}:**\n"
                f"Question: {eq.question_text}\n"
                f"Expected answer: {eq.expected_answer}\n"
                f"Concept: {eq.concept}\n"
                f"Difficulty: {eq.difficulty}\n\n"
                "Score the student's answer from 0.0 to 1.0. If the question has multiple parts, "
                "award partial credit proportionally (e.g., 1 of 3 parts correct = ~0.3). "
                "Set `answer_score` to the fractional score and `marks_rationale` to a brief "
                "1-2 sentence justification explaining what the student got right/wrong and why "
                "this score was awarded. Also set `answer_correct` based on whether the core answer is right."
            )

        # Check for recent feedback in turn timeline
        recent_timeline = session.session_summary.turn_timeline[-3:] if session.session_summary.turn_timeline else []
        has_restart = any("[FEEDBACK-RESTART]" in entry for entry in recent_timeline)
        has_continue_feedback = any("[FEEDBACK]" in entry for entry in recent_timeline)
        if has_restart:
            feedback_notice = (
                "\n## IMPORTANT: Session Was Restarted\n"
                "The session was restarted with a new study plan based on parent/student feedback. "
                "This is a fresh start — greet the student warmly, briefly acknowledge the change "
                "(e.g., \"Let's take a fresh look at this!\"), and begin teaching from step 1.\n\n"
            )
            awaiting_answer_section = feedback_notice + awaiting_answer_section
        elif has_continue_feedback:
            feedback_notice = (
                "\n## IMPORTANT: Study Plan Was Just Updated\n"
                "The study plan was adjusted based on parent/student feedback. "
                "Acknowledge naturally (e.g., \"Let's try a different approach!\") "
                "and continue with the current step.\n\n"
            )
            awaiting_answer_section = feedback_notice + awaiting_answer_section

        # Compute dynamic signals
        pacing_directive = self._compute_pacing_directive(session)
        student_style = self._compute_student_style(session)
        explanation_context = self._build_explanation_context(session)

        conversation = format_conversation_history(session.conversation_history, max_turns=10)
        if not conversation.strip():
            conversation = "(No prior messages — this is the first turn)"

        return MASTER_TUTOR_TURN_PROMPT.render(
            current_step=session.current_step,
            total_steps=session.topic.study_plan.total_steps if session.topic else 0,
            current_step_info=current_step_info,
            content_hint=content_hint,
            explanation_context=explanation_context,
            mastery_formatted=mastery_formatted,
            misconceptions=misconceptions,
            turn_timeline=turn_timeline,
            pacing_directive=pacing_directive,
            student_style=student_style,
            awaiting_answer_section=awaiting_answer_section,
            conversation_history=conversation,
            student_message=context.student_message,
        )

    def _build_clarify_turn_prompt(self, session: SessionState, context: AgentContext) -> str:
        concepts_discussed = ", ".join(session.concepts_discussed) if session.concepts_discussed else "None yet"
        conversation = format_conversation_history(session.conversation_history, max_turns=10)
        if not conversation.strip():
            conversation = "(No prior messages — this is the first turn)"

        return CLARIFY_DOUBTS_TURN_PROMPT.render(
            concepts_discussed=concepts_discussed,
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
