"""Unit tests for tutor/agents/master_tutor.py — prompt building and summarization."""

import pytest
from unittest.mock import MagicMock

from tutor.agents.base_agent import AgentContext
from tutor.agents.master_tutor import MasterTutorAgent, TutorTurnOutput, MasteryUpdate
from tutor.models.session_state import (
    SessionState,
    create_session,
    Misconception,
    Question,
    SessionSummary,
)
from tutor.models.study_plan import (
    Topic,
    TopicGuidelines,
    StudyPlan,
    StudyPlanStep,
)
from tutor.models.messages import StudentContext, Message


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_topic() -> Topic:
    return Topic(
        topic_id="math_fractions_basics",
        topic_name="Fractions - Basics",
        subject="Mathematics",
        grade_level=3,
        guidelines=TopicGuidelines(
            learning_objectives=["Understand what a fraction is", "Compare simple fractions"],
            common_misconceptions=["Bigger denominator means bigger fraction"],
            teaching_approach="Use pizza slices and visual aids",
        ),
        study_plan=StudyPlan(
            steps=[
                StudyPlanStep(step_id=1, type="explain", concept="What is a fraction", content_hint="Pizza example"),
                StudyPlanStep(step_id=2, type="check", concept="What is a fraction", question_type="conceptual"),
                StudyPlanStep(step_id=3, type="practice", concept="Comparing fractions", question_count=2),
            ]
        ),
    )


def _make_session(turn_count: int = 0) -> SessionState:
    topic = _make_topic()
    ctx = StudentContext(grade=3, board="CBSE", language_level="simple")
    session = create_session(topic=topic, student_context=ctx)
    session.turn_count = turn_count
    return session


def _make_agent() -> MasterTutorAgent:
    llm = MagicMock()
    return MasterTutorAgent(llm_service=llm, timeout_seconds=30, reasoning_effort="none")


def _make_context(**overrides) -> AgentContext:
    defaults = dict(
        session_id="sess-1",
        turn_id="turn_1",
        student_message="I think a fraction is a piece of pizza?",
        current_step=1,
        current_concept="What is a fraction",
        student_grade=3,
        language_level="simple",
        additional_context={},
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


# ---------------------------------------------------------------------------
# Tests — build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    """Tests for MasterTutorAgent.build_prompt."""

    def test_raises_without_session(self):
        agent = _make_agent()
        ctx = _make_context()
        with pytest.raises(ValueError, match="Session not set"):
            agent.build_prompt(ctx)

    def test_returns_combined_prompt(self):
        agent = _make_agent()
        session = _make_session(turn_count=1)
        agent.set_session(session)

        ctx = _make_context()
        prompt = agent.build_prompt(ctx)

        # System portion present
        assert "Fractions - Basics" in prompt
        assert "Grade 3" in prompt or "grade 3" in prompt.lower()
        # Turn portion present
        assert "Student's Message" in prompt
        assert "piece of pizza" in prompt
        # Separator between system and turn
        assert "---" in prompt

    def test_prompt_contains_study_plan_steps(self):
        agent = _make_agent()
        session = _make_session(turn_count=1)
        agent.set_session(session)

        prompt = agent.build_prompt(_make_context())
        assert "Step 1" in prompt
        assert "explain" in prompt.lower()
        assert "Pizza example" in prompt


# ---------------------------------------------------------------------------
# Tests — _build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    """Tests for MasterTutorAgent._build_system_prompt."""

    def test_contains_topic_and_guidelines(self):
        agent = _make_agent()
        session = _make_session()

        prompt = agent._build_system_prompt(session)
        assert "Fractions - Basics" in prompt
        assert "pizza slices" in prompt.lower() or "Pizza" in prompt
        assert "Bigger denominator" in prompt

    def test_contains_student_context(self):
        agent = _make_agent()
        session = _make_session()

        prompt = agent._build_system_prompt(session)
        assert "simple" in prompt.lower()
        assert "food" in prompt.lower()

    def test_formats_steps(self):
        agent = _make_agent()
        session = _make_session()

        prompt = agent._build_system_prompt(session)
        assert "Step 1 [explain]" in prompt
        assert "Step 2 [check]" in prompt
        assert "Step 3 [practice]" in prompt


# ---------------------------------------------------------------------------
# Tests — _build_turn_prompt
# ---------------------------------------------------------------------------

class TestBuildTurnPrompt:
    """Tests for MasterTutorAgent._build_turn_prompt."""

    def test_contains_session_state(self):
        agent = _make_agent()
        session = _make_session(turn_count=1)
        ctx = _make_context()

        prompt = agent._build_turn_prompt(session, ctx)
        assert "Step 1 of 3" in prompt
        assert "piece of pizza" in prompt

    def test_mastery_shown_when_present(self):
        agent = _make_agent()
        session = _make_session(turn_count=2)
        session.mastery_estimates = {"What is a fraction": 0.6, "Comparing fractions": 0.0}

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "What is a fraction" in prompt
        assert "0.6" in prompt

    def test_no_mastery_shows_default(self):
        agent = _make_agent()
        session = _make_session(turn_count=1)
        session.mastery_estimates = {}

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "No data yet" in prompt

    def test_misconceptions_shown(self):
        agent = _make_agent()
        session = _make_session(turn_count=2)
        session.misconceptions = [
            Misconception(concept="fractions", description="Thinks denominator is the top number"),
        ]

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "denominator is the top number" in prompt

    def test_recurring_misconceptions_flagged(self):
        agent = _make_agent()
        session = _make_session(turn_count=3)
        session.misconceptions = [
            Misconception(concept="fractions", description="Reverses numerator and denominator"),
            Misconception(concept="fractions", description="Reverses numerator and denominator"),
        ]

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "RECURRING" in prompt

    def test_awaiting_answer_section(self):
        agent = _make_agent()
        session = _make_session(turn_count=2)
        session.awaiting_response = True
        session.last_question = Question(
            question_text="What is 1/4?",
            expected_answer="One quarter",
            concept="What is a fraction",
        )

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "What is 1/4?" in prompt
        assert "One quarter" in prompt

    def test_wrong_attempt_strategies(self):
        agent = _make_agent()
        session = _make_session(turn_count=3)
        session.awaiting_response = True
        session.last_question = Question(
            question_text="What is 1/4?",
            expected_answer="One quarter",
            concept="What is a fraction",
            wrong_attempts=3,
            previous_student_answers=["One half", "Two fourths", "One third"],
        )

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "EXPLAIN" in prompt or "COMPLETELY DIFFERENT" in prompt
        assert "attempt #4" in prompt

    def test_pacing_first_turn(self):
        agent = _make_agent()
        session = _make_session(turn_count=1)

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "FIRST TURN" in prompt

    def test_pacing_accelerate(self):
        agent = _make_agent()
        session = _make_session(turn_count=5)
        session.mastery_estimates = {"What is a fraction": 0.9, "Comparing fractions": 0.85}
        session.session_summary.progress_trend = "improving"

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "ACCELERATE" in prompt

    def test_pacing_simplify(self):
        agent = _make_agent()
        session = _make_session(turn_count=5)
        session.mastery_estimates = {"What is a fraction": 0.2, "Comparing fractions": 0.1}
        session.session_summary.progress_trend = "struggling"

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "SIMPLIFY" in prompt

    def test_student_style_quiet(self):
        agent = _make_agent()
        session = _make_session(turn_count=3)
        session.conversation_history = [
            Message(role="student", content="yes"),
            Message(role="student", content="ok"),
            Message(role="student", content="3"),
        ]

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "QUIET" in prompt

    def test_student_style_no_messages(self):
        agent = _make_agent()
        session = _make_session(turn_count=1)
        session.conversation_history = []

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "Unknown" in prompt or "first turn" in prompt.lower()

    def test_conversation_history_empty(self):
        agent = _make_agent()
        session = _make_session(turn_count=1)
        session.conversation_history = []

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "first turn" in prompt.lower() or "No prior messages" in prompt

    def test_turn_timeline(self):
        agent = _make_agent()
        session = _make_session(turn_count=3)
        session.session_summary.turn_timeline = [
            "Introduced fractions",
            "Student answered correctly",
            "Moved to comparison",
        ]

        prompt = agent._build_turn_prompt(session, _make_context())
        assert "Introduced fractions" in prompt


# ---------------------------------------------------------------------------
# Tests — _summarize_output
# ---------------------------------------------------------------------------

class TestSummarizeOutput:
    """Tests for MasterTutorAgent._summarize_output."""

    def test_summarize_tutor_output(self):
        agent = _make_agent()
        output = TutorTurnOutput(
            response="Great thinking! A fraction represents a part of a whole.",
            intent="answer",
            answer_correct=True,
            misconceptions_detected=[],
            mastery_signal="strong",
            mastery_updates=[MasteryUpdate(concept="What is a fraction", score=0.8)],
            question_asked="Can you draw 1/2 of a pizza?",
            expected_answer="Half a pizza",
            question_concept="What is a fraction",
            turn_summary="Student understood basic fraction concept",
            reasoning="Student showed clear understanding.",
        )

        summary = agent._summarize_output(output)
        assert summary["intent"] == "answer"
        assert summary["answer_correct"] is True
        assert summary["mastery_updates"] == {"What is a fraction": 0.8}
        assert summary["question_asked"] is True
        assert summary["response_length"] > 0

    def test_summarize_output_no_question(self):
        agent = _make_agent()
        output = TutorTurnOutput(
            response="Let me explain fractions.",
            intent="continuation",
            turn_summary="Explaining fractions",
        )

        summary = agent._summarize_output(output)
        assert summary["intent"] == "continuation"
        assert summary["question_asked"] is False
        assert summary["answer_correct"] is None


# ---------------------------------------------------------------------------
# Tests — agent properties
# ---------------------------------------------------------------------------

class TestAgentProperties:
    def test_agent_name(self):
        agent = _make_agent()
        assert agent.agent_name == "master_tutor"

    def test_get_output_model(self):
        agent = _make_agent()
        assert agent.get_output_model() is TutorTurnOutput

    def test_set_session(self):
        agent = _make_agent()
        session = _make_session()
        agent.set_session(session)
        assert agent._session is session


# ---------------------------------------------------------------------------
# Tests — compute pacing directives
# ---------------------------------------------------------------------------

class TestComputePacingDirective:
    def test_steady_pacing(self):
        agent = _make_agent()
        session = _make_session(turn_count=3)
        session.mastery_estimates = {"What is a fraction": 0.55}
        session.session_summary.progress_trend = "steady"

        result = agent._compute_pacing_directive(session)
        assert "STEADY" in result

    def test_consolidate_after_struggle(self):
        agent = _make_agent()
        session = _make_session(turn_count=5)
        session.mastery_estimates = {"What is a fraction": 0.5}
        session.session_summary.progress_trend = "steady"
        session.last_question = Question(
            question_text="What is 1/4?",
            expected_answer="One quarter",
            concept="fractions",
            wrong_attempts=2,
        )

        result = agent._compute_pacing_directive(session)
        assert "CONSOLIDATE" in result

    def test_extend_past_plan(self):
        agent = _make_agent()
        session = _make_session(turn_count=10)
        session.mastery_estimates = {"What is a fraction": 0.95, "Comparing fractions": 0.9}
        session.session_summary.progress_trend = "improving"
        session.current_step = 4  # past the 3 plan steps

        result = agent._compute_pacing_directive(session)
        assert "EXTEND" in result


class TestComputeStudentStyle:
    def test_expressive_student(self):
        agent = _make_agent()
        session = _make_session(turn_count=3)
        session.conversation_history = [
            Message(role="student", content="I really love learning about fractions because they remind me of pizza slices and sharing food with my friends and family"),
        ]

        result = agent._compute_student_style(session)
        assert "Expressive" in result

    def test_moderate_student(self):
        agent = _make_agent()
        session = _make_session(turn_count=3)
        session.conversation_history = [
            Message(role="student", content="I think fractions are parts of a whole thing"),
        ]

        result = agent._compute_student_style(session)
        assert "Moderate" in result

    def test_student_asks_questions(self):
        agent = _make_agent()
        session = _make_session(turn_count=2)
        session.conversation_history = [
            Message(role="student", content="But why do we need fractions?"),
        ]

        result = agent._compute_student_style(session)
        assert "asks questions" in result.lower()
