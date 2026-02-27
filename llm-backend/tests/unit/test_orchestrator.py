"""
Unit tests for TeacherOrchestrator.

Tests the orchestration layer: safety gating, master tutor invocation,
state updates, question lifecycle, and error handling.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from tutor.orchestration.orchestrator import TeacherOrchestrator, TurnResult
from tutor.models.session_state import SessionState, Question, ExamQuestion, create_session
from tutor.models.study_plan import Topic, TopicGuidelines, StudyPlan, StudyPlanStep
from tutor.models.messages import StudentContext, Message
from tutor.agents.safety import SafetyOutput
from tutor.agents.master_tutor import TutorTurnOutput, MasteryUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_test_topic():
    return Topic(
        topic_id="t1",
        topic_name="Fractions",
        subject="Math",
        grade_level=3,
        guidelines=TopicGuidelines(
            learning_objectives=["Learn fractions"],
            common_misconceptions=["Bigger denominator means bigger fraction"],
        ),
        study_plan=StudyPlan(steps=[
            StudyPlanStep(step_id=1, type="explain", concept="Basics"),
            StudyPlanStep(step_id=2, type="check", concept="Basics"),
            StudyPlanStep(step_id=3, type="practice", concept="Basics"),
        ]),
    )


def make_test_session(**overrides):
    session = create_session(
        topic=make_test_topic(),
        student_context=StudentContext(grade=3),
    )
    for key, val in overrides.items():
        setattr(session, key, val)
    return session


def make_safe_result():
    return SafetyOutput(is_safe=True, reasoning="OK")


def make_unsafe_result():
    return SafetyOutput(
        is_safe=False,
        violation_type="harmful",
        guidance="Be nice",
        should_warn=True,
        reasoning="bad",
    )


def make_tutor_output(**overrides):
    defaults = dict(
        response="Good job!",
        intent="answer",
        answer_correct=True,
        mastery_updates=[MasteryUpdate(concept="Basics", score=0.8)],
        misconceptions_detected=[],
        turn_summary="Student answered correctly",
        reasoning="OK",
    )
    defaults.update(overrides)
    return TutorTurnOutput(**defaults)


def build_orchestrator():
    """Build a TeacherOrchestrator with a mock LLM service."""
    llm = Mock()
    orch = TeacherOrchestrator(llm)
    orch.safety_agent.execute = AsyncMock()
    orch.master_tutor.execute = AsyncMock()
    orch.master_tutor.set_session = Mock()
    # last_prompt is a read-only property on BaseAgent — mock the internal attribute instead
    orch.master_tutor._last_prompt = "mock prompt"
    return orch


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestOrchestratorInit:
    def test_creates_safety_and_master_tutor(self):
        llm = Mock()
        orch = TeacherOrchestrator(llm)
        assert orch.safety_agent is not None
        assert orch.master_tutor is not None
        assert orch.llm is llm

    def test_agents_receive_llm_service(self):
        llm = Mock()
        orch = TeacherOrchestrator(llm)
        assert orch.safety_agent.llm is llm
        assert orch.master_tutor.llm is llm


# ---------------------------------------------------------------------------
# process_turn — safe path
# ---------------------------------------------------------------------------

class TestProcessTurnSafe:
    @pytest.mark.asyncio
    async def test_safe_message_returns_tutor_response(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.return_value = make_safe_result()
        tutor_out = make_tutor_output()
        orch.master_tutor.execute.return_value = tutor_out

        session = make_test_session()
        result = await orch.process_turn(session, "Hello")

        assert isinstance(result, TurnResult)
        assert result.response == "Good job!"
        assert result.intent == "answer"
        assert "master_tutor" in result.specialists_called

    @pytest.mark.asyncio
    async def test_safe_message_increments_turn(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.return_value = make_safe_result()
        orch.master_tutor.execute.return_value = make_tutor_output()

        session = make_test_session()
        initial = session.turn_count
        await orch.process_turn(session, "Hello")
        assert session.turn_count == initial + 1

    @pytest.mark.asyncio
    async def test_safe_message_adds_student_and_teacher_messages(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.return_value = make_safe_result()
        orch.master_tutor.execute.return_value = make_tutor_output(response="Nice work!")

        session = make_test_session()
        await orch.process_turn(session, "My answer is 5")

        roles = [m.role for m in session.conversation_history]
        assert "student" in roles
        assert "teacher" in roles

    @pytest.mark.asyncio
    async def test_state_changed_flag_when_mastery_updated(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.return_value = make_safe_result()
        orch.master_tutor.execute.return_value = make_tutor_output(
            mastery_updates=[MasteryUpdate(concept="Basics", score=0.9)],
        )

        session = make_test_session()
        result = await orch.process_turn(session, "Hi")
        assert result.state_changed is True


# ---------------------------------------------------------------------------
# process_turn — unsafe path
# ---------------------------------------------------------------------------

class TestProcessTurnUnsafe:
    @pytest.mark.asyncio
    async def test_unsafe_message_returns_safety_response(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.return_value = make_unsafe_result()

        session = make_test_session()
        result = await orch.process_turn(session, "bad stuff")

        assert result.response == "Be nice"
        assert result.intent == "unsafe"
        assert "safety" in result.specialists_called

    @pytest.mark.asyncio
    async def test_unsafe_message_increments_warning_count(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.return_value = make_unsafe_result()

        session = make_test_session()
        await orch.process_turn(session, "bad stuff")
        assert session.warning_count == 1

    @pytest.mark.asyncio
    async def test_unsafe_message_appends_safety_flag(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.return_value = make_unsafe_result()

        session = make_test_session()
        await orch.process_turn(session, "bad stuff")
        assert "harmful" in session.safety_flags


# ---------------------------------------------------------------------------
# process_turn — completed session
# ---------------------------------------------------------------------------

class TestProcessTurnCompleted:
    @pytest.mark.asyncio
    async def test_completed_session_returns_post_completion(self):
        orch = build_orchestrator()
        # Mock the post-completion LLM call
        orch.llm.call_gpt_5_2 = Mock(return_value={"output_text": "Great session!"})

        session = make_test_session()
        # Advance past all steps to mark as complete
        session.current_step = 4  # past total_steps (3)
        assert session.is_complete is True
        session.allow_extension = False

        result = await orch.process_turn(session, "Thanks!")
        assert result.intent == "session_complete"
        assert result.state_changed is False

    @pytest.mark.asyncio
    async def test_completed_session_still_records_student_message(self):
        orch = build_orchestrator()
        orch.llm.call_gpt_5_2 = Mock(return_value={"output_text": "Bye!"})

        session = make_test_session()
        session.current_step = 4
        session.allow_extension = False

        await orch.process_turn(session, "Thank you!")
        student_msgs = [m for m in session.conversation_history if m.role == "student"]
        assert any("Thank you!" in m.content for m in student_msgs)


# ---------------------------------------------------------------------------
# process_turn — error handling
# ---------------------------------------------------------------------------

class TestProcessTurnError:
    @pytest.mark.asyncio
    async def test_exception_returns_error_response(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.side_effect = RuntimeError("LLM boom")

        session = make_test_session()
        result = await orch.process_turn(session, "Hi")

        assert result.intent == "error"
        assert "apologize" in result.response.lower() or "confusion" in result.response.lower()
        assert result.state_changed is False


# ---------------------------------------------------------------------------
# _apply_state_updates
# ---------------------------------------------------------------------------

class TestApplyStateUpdates:
    def test_mastery_updates(self):
        orch = build_orchestrator()
        session = make_test_session()
        output = make_tutor_output(
            mastery_updates=[MasteryUpdate(concept="Basics", score=0.75)],
            answer_correct=None,
        )
        changed = orch._apply_state_updates(session, output)
        assert changed is True
        assert session.mastery_estimates["Basics"] == 0.75

    def test_misconceptions_tracked(self):
        orch = build_orchestrator()
        session = make_test_session()
        output = make_tutor_output(
            misconceptions_detected=["Bigger denominator means bigger fraction"],
            mastery_updates=[],
            answer_correct=None,
        )
        changed = orch._apply_state_updates(session, output)
        assert changed is True
        assert len(session.misconceptions) == 1
        assert session.misconceptions[0].description == "Bigger denominator means bigger fraction"

    def test_advance_step(self):
        orch = build_orchestrator()
        session = make_test_session()
        assert session.current_step == 1
        output = make_tutor_output(
            advance_to_step=3,
            mastery_updates=[],
            answer_correct=None,
        )
        changed = orch._apply_state_updates(session, output)
        assert changed is True
        assert session.current_step == 3

    def test_does_not_advance_step_backwards(self):
        orch = build_orchestrator()
        session = make_test_session()
        session.current_step = 3
        output = make_tutor_output(
            advance_to_step=1,
            mastery_updates=[],
            answer_correct=None,
        )
        changed = orch._apply_state_updates(session, output)
        # advance_to_step < current_step, so no step change. May still be
        # changed due to mastery/question lifecycle returning True for correct answer.
        assert session.current_step == 3

    def test_off_topic_increments_counter(self):
        orch = build_orchestrator()
        session = make_test_session()
        output = make_tutor_output(
            intent="off_topic",
            mastery_updates=[],
            answer_correct=None,
        )
        orch._apply_state_updates(session, output)
        assert session.off_topic_count == 1

    def test_session_complete_on_final_step(self):
        orch = build_orchestrator()
        session = make_test_session()
        session.current_step = 3  # final step (3 total)
        output = make_tutor_output(
            session_complete=True,
            mastery_updates=[],
            answer_correct=None,
        )
        orch._apply_state_updates(session, output)
        assert session.is_complete is True

    def test_session_complete_ignored_on_early_step(self):
        orch = build_orchestrator()
        session = make_test_session()
        session.current_step = 1
        output = make_tutor_output(
            session_complete=True,
            mastery_updates=[],
            answer_correct=None,
        )
        orch._apply_state_updates(session, output)
        assert session.is_complete is False


# ---------------------------------------------------------------------------
# _handle_question_lifecycle
# ---------------------------------------------------------------------------

class TestQuestionLifecycle:
    def test_case1_wrong_answer_on_pending(self):
        """Wrong answer on pending question increments attempts and updates phase."""
        orch = build_orchestrator()
        session = make_test_session()
        session.set_question(Question(
            question_text="What is 1/2 + 1/2?",
            expected_answer="1",
            concept="Basics",
        ))
        # Add a student message so previous_student_answers can be filled
        session.add_message(Message(role="student", content="I think it's 3"))

        output = make_tutor_output(
            answer_correct=False,
            question_asked=None,
            mastery_updates=[],
        )
        changed = orch._handle_question_lifecycle(session, output, "Basics")
        assert changed is True
        assert session.last_question is not None
        assert session.last_question.wrong_attempts == 1
        assert session.last_question.phase == "probe"

    def test_case1_second_wrong_sets_hint_phase(self):
        orch = build_orchestrator()
        session = make_test_session()
        q = Question(
            question_text="What is 1/2 + 1/2?",
            expected_answer="1",
            concept="Basics",
        )
        q.wrong_attempts = 1
        q.phase = "probe"
        session.set_question(q)
        session.add_message(Message(role="student", content="2?"))

        output = make_tutor_output(
            answer_correct=False,
            question_asked=None,
            mastery_updates=[],
        )
        changed = orch._handle_question_lifecycle(session, output, "Basics")
        assert changed is True
        assert session.last_question.wrong_attempts == 2
        assert session.last_question.phase == "hint"

    def test_case1_third_wrong_sets_explain_phase(self):
        orch = build_orchestrator()
        session = make_test_session()
        q = Question(
            question_text="What is 1/2 + 1/2?",
            expected_answer="1",
            concept="Basics",
        )
        q.wrong_attempts = 2
        q.phase = "hint"
        session.set_question(q)
        session.add_message(Message(role="student", content="3?"))

        output = make_tutor_output(
            answer_correct=False,
            question_asked=None,
            mastery_updates=[],
        )
        changed = orch._handle_question_lifecycle(session, output, "Basics")
        assert changed is True
        assert session.last_question.wrong_attempts == 3
        assert session.last_question.phase == "explain"

    def test_case2_correct_answer_clears_question(self):
        """Correct answer clears the pending question."""
        orch = build_orchestrator()
        session = make_test_session()
        session.set_question(Question(
            question_text="What is 1/2 + 1/2?",
            expected_answer="1",
            concept="Basics",
        ))
        output = make_tutor_output(
            answer_correct=True,
            question_asked=None,
            mastery_updates=[],
        )
        changed = orch._handle_question_lifecycle(session, output, "Basics")
        assert changed is True
        assert session.last_question is None

    def test_case2_correct_answer_with_new_question(self):
        """Correct answer clears old question and sets new one."""
        orch = build_orchestrator()
        session = make_test_session()
        session.set_question(Question(
            question_text="Old Q?",
            expected_answer="old",
            concept="Basics",
        ))
        output = make_tutor_output(
            answer_correct=True,
            question_asked="New question?",
            expected_answer="new answer",
            question_concept="Basics",
            mastery_updates=[],
        )
        changed = orch._handle_question_lifecycle(session, output, "Basics")
        assert changed is True
        assert session.last_question is not None
        assert session.last_question.question_text == "New question?"

    def test_case3_new_question_no_pending(self):
        """New question when no question is pending."""
        orch = build_orchestrator()
        session = make_test_session()
        assert session.last_question is None

        output = make_tutor_output(
            answer_correct=None,
            question_asked="What is a fraction?",
            expected_answer="Part of a whole",
            question_concept="Basics",
            mastery_updates=[],
        )
        changed = orch._handle_question_lifecycle(session, output, "Basics")
        assert changed is True
        assert session.last_question is not None
        assert session.last_question.question_text == "What is a fraction?"

    def test_case4_new_question_different_concept_replaces(self):
        """New question on a different concept replaces the pending one."""
        orch = build_orchestrator()
        session = make_test_session()
        session.set_question(Question(
            question_text="Old Q?",
            expected_answer="old",
            concept="OldConcept",
        ))
        output = make_tutor_output(
            answer_correct=None,
            question_asked="New concept Q?",
            expected_answer="new",
            question_concept="NewConcept",
            mastery_updates=[],
        )
        changed = orch._handle_question_lifecycle(session, output, "NewConcept")
        assert changed is True
        assert session.last_question.question_text == "New concept Q?"
        assert session.last_question.concept == "NewConcept"

    def test_case5_same_concept_follow_up_keeps_existing(self):
        """Same concept follow-up keeps existing lifecycle."""
        orch = build_orchestrator()
        session = make_test_session()
        session.set_question(Question(
            question_text="Original Q?",
            expected_answer="original",
            concept="Basics",
        ))
        output = make_tutor_output(
            answer_correct=None,
            question_asked="Follow up Q?",
            expected_answer="follow up",
            question_concept="Basics",
            mastery_updates=[],
        )
        changed = orch._handle_question_lifecycle(session, output, "Basics")
        assert changed is False
        assert session.last_question.question_text == "Original Q?"

    def test_no_question_change(self):
        """No question asked and no answer evaluation returns False."""
        orch = build_orchestrator()
        session = make_test_session()
        output = make_tutor_output(
            answer_correct=None,
            question_asked=None,
            mastery_updates=[],
        )
        changed = orch._handle_question_lifecycle(session, output, "Basics")
        assert changed is False


# ---------------------------------------------------------------------------
# _handle_unsafe_message
# ---------------------------------------------------------------------------

class TestExamTurn:
    @pytest.mark.asyncio
    async def test_exam_turn_does_not_reveal_correctness_mid_exam(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.return_value = make_safe_result()
        orch.master_tutor.execute.return_value = make_tutor_output(
            response="That's incorrect. The right answer is 42.",
            answer_correct=False,
            mastery_signal="needs_remediation",
            turn_summary="Student got this wrong",
        )

        session = make_test_session(mode="exam")
        session.exam_questions = [
            ExamQuestion(
                question_idx=0,
                question_text="Q1?",
                concept="Basics",
                difficulty="easy",
                question_type="conceptual",
                expected_answer="A1",
            ),
            ExamQuestion(
                question_idx=1,
                question_text="Q2?",
                concept="Basics",
                difficulty="easy",
                question_type="conceptual",
                expected_answer="A2",
            ),
        ]

        result = await orch.process_turn(session, "my answer")

        assert "incorrect" not in result.response.lower()
        assert "right answer" not in result.response.lower()
        assert "Question 2" in result.response
        assert session.exam_finished is False

    @pytest.mark.asyncio
    async def test_exam_turn_final_response_shows_completion_only(self):
        orch = build_orchestrator()
        orch.safety_agent.execute.return_value = make_safe_result()
        orch.master_tutor.execute.return_value = make_tutor_output(
            response="Correct!",
            answer_correct=True,
            turn_summary="Student answered correctly",
        )

        session = make_test_session(mode="exam")
        session.exam_questions = [
            ExamQuestion(
                question_idx=0,
                question_text="Q1?",
                concept="Basics",
                difficulty="easy",
                question_type="conceptual",
                expected_answer="A1",
            ),
        ]

        result = await orch.process_turn(session, "A1")

        assert session.exam_finished is True
        assert "exam complete" in result.response.lower()
        assert "final score" in result.response.lower()
        assert "q1: ✅ correct" in result.response.lower()


class TestHandleUnsafeMessage:
    def test_returns_guidance(self):
        orch = build_orchestrator()
        session = make_test_session()
        safety = make_unsafe_result()
        msg = orch._handle_unsafe_message(session, safety)
        assert msg == "Be nice"

    def test_default_message_when_no_guidance(self):
        orch = build_orchestrator()
        session = make_test_session()
        safety = SafetyOutput(is_safe=False, reasoning="bad")
        msg = orch._handle_unsafe_message(session, safety)
        assert "focused on learning" in msg

    def test_appends_safety_flag(self):
        orch = build_orchestrator()
        session = make_test_session()
        safety = make_unsafe_result()
        orch._handle_unsafe_message(session, safety)
        assert "harmful" in session.safety_flags

    def test_increments_warning_when_should_warn(self):
        orch = build_orchestrator()
        session = make_test_session()
        safety = make_unsafe_result()
        orch._handle_unsafe_message(session, safety)
        assert session.warning_count == 1


# ---------------------------------------------------------------------------
# _extract_output_dict
# ---------------------------------------------------------------------------

class TestExtractOutputDict:
    def test_none_returns_empty_dict(self):
        orch = build_orchestrator()
        assert orch._extract_output_dict(None) == {}

    def test_pydantic_model_returns_dict(self):
        orch = build_orchestrator()
        output = make_safe_result()
        result = orch._extract_output_dict(output)
        assert isinstance(result, dict)
        assert "is_safe" in result

    def test_dict_returned_as_is(self):
        orch = build_orchestrator()
        d = {"key": "value"}
        assert orch._extract_output_dict(d) == d

    def test_other_types_wrapped(self):
        orch = build_orchestrator()
        result = orch._extract_output_dict(42)
        assert result == {"value": "42"}


# ---------------------------------------------------------------------------
# _check_response_sanitization
# ---------------------------------------------------------------------------

class TestCheckResponseSanitization:
    def test_no_warning_on_clean_response(self):
        orch = build_orchestrator()
        with patch("tutor.orchestration.orchestrator.logger") as mock_logger:
            orch._check_response_sanitization("s1", "t1", "Great job on fractions!")
            mock_logger.warning.assert_not_called()

    def test_warning_on_leak_pattern(self):
        orch = build_orchestrator()
        with patch("tutor.orchestration.orchestrator.logger") as mock_logger:
            orch._check_response_sanitization(
                "s1", "t1", "The student's answer is incorrect because of a misconception"
            )
            mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# generate_welcome_message
# ---------------------------------------------------------------------------

class TestGenerateWelcomeMessage:
    @pytest.mark.asyncio
    async def test_no_topic_returns_default(self):
        orch = build_orchestrator()
        session = make_test_session()
        session.topic = None
        msg = await orch.generate_welcome_message(session)
        assert msg == "Welcome! Let's start learning together."

    @pytest.mark.asyncio
    async def test_with_topic_calls_llm(self):
        orch = build_orchestrator()
        orch.llm.call_gpt_5_2 = Mock(return_value={"output_text": "Welcome to Fractions!"})

        session = make_test_session()
        msg = await orch.generate_welcome_message(session)
        assert msg == "Welcome to Fractions!"
        orch.llm.call_gpt_5_2.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_topic_missing_output_key_returns_fallback(self):
        orch = build_orchestrator()
        # When output_text key is missing entirely, .get() returns the default
        orch.llm.call_gpt_5_2 = Mock(return_value={})

        session = make_test_session()
        msg = await orch.generate_welcome_message(session)
        assert msg == "Welcome! Let's start learning."

    @pytest.mark.asyncio
    async def test_with_topic_empty_output_returns_empty_string(self):
        orch = build_orchestrator()
        # When output_text is "" the key exists so .get() returns ""
        orch.llm.call_gpt_5_2 = Mock(return_value={"output_text": ""})

        session = make_test_session()
        msg = await orch.generate_welcome_message(session)
        assert msg == ""
