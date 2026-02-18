"""Unit tests for tutor/models/session_state.py

Tests SessionState properties/methods, Misconception, Question, SessionSummary models,
and the create_session factory function.
"""

import pytest
from datetime import datetime

from tutor.models.session_state import (
    Misconception,
    Question,
    SessionSummary,
    SessionState,
    create_session,
)
from tutor.models.study_plan import (
    Topic,
    TopicGuidelines,
    StudyPlan,
    StudyPlanStep,
)
from tutor.models.messages import Message, StudentContext, create_teacher_message


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_topic(num_steps: int = 2, concepts: list[str] | None = None) -> Topic:
    """Build a minimal Topic with *num_steps* steps.

    Each concept generates an explain + check pair.  If the caller requests
    more steps than the concept list produces, additional concepts are
    auto-generated so the requested step count is met.
    """
    if concepts is None:
        concepts = ["Addition"]

    # Ensure we have enough concepts to produce the requested number of steps
    # (each concept yields 2 steps: explain + check).
    needed_concepts = (num_steps + 1) // 2
    while len(concepts) < needed_concepts:
        concepts.append(f"Concept_{len(concepts) + 1}")

    steps: list[StudyPlanStep] = []
    step_id = 1
    for concept in concepts:
        steps.append(StudyPlanStep(step_id=step_id, type="explain", concept=concept))
        step_id += 1
        steps.append(StudyPlanStep(step_id=step_id, type="check", concept=concept))
        step_id += 1

    # Trim to the exact count requested
    steps = steps[:num_steps]

    return Topic(
        topic_id="test-topic",
        topic_name="Test Topic",
        subject="Math",
        grade_level=3,
        guidelines=TopicGuidelines(learning_objectives=["obj1"]),
        study_plan=StudyPlan(steps=steps),
    )


def _make_state(**overrides) -> SessionState:
    """Build a SessionState with sensible defaults; override any field."""
    defaults = dict(
        topic=_make_topic(),
        student_context=StudentContext(grade=3),
        mastery_estimates={"Addition": 0.5},
    )
    defaults.update(overrides)
    return SessionState(**defaults)


def _msg(role: str = "teacher", content: str = "hello") -> Message:
    return Message(role=role, content=content)


# ===========================================================================
# Misconception model
# ===========================================================================

class TestMisconception:
    def test_defaults(self):
        m = Misconception(concept="Fractions", description="Adds denominators")
        assert m.concept == "Fractions"
        assert m.description == "Adds denominators"
        assert m.resolved is False
        assert isinstance(m.detected_at, datetime)

    def test_resolved_flag(self):
        m = Misconception(concept="X", description="Y", resolved=True)
        assert m.resolved is True


# ===========================================================================
# Question model
# ===========================================================================

class TestQuestion:
    def test_defaults(self):
        q = Question(
            question_text="What is 2+2?",
            expected_answer="4",
            concept="Addition",
        )
        assert q.question_text == "What is 2+2?"
        assert q.expected_answer == "4"
        assert q.concept == "Addition"
        assert q.rubric == ""
        assert q.hints == []
        assert q.hints_used == 0
        assert q.wrong_attempts == 0
        assert q.previous_student_answers == []
        assert q.phase == "asked"

    def test_custom_values(self):
        q = Question(
            question_text="Q",
            expected_answer="A",
            concept="C",
            rubric="strict",
            hints=["h1", "h2"],
            hints_used=1,
            wrong_attempts=2,
            previous_student_answers=["wrong1"],
            phase="hint",
        )
        assert q.rubric == "strict"
        assert len(q.hints) == 2
        assert q.hints_used == 1
        assert q.wrong_attempts == 2
        assert q.previous_student_answers == ["wrong1"]
        assert q.phase == "hint"


# ===========================================================================
# SessionSummary model
# ===========================================================================

class TestSessionSummary:
    def test_defaults(self):
        ss = SessionSummary()
        assert ss.turn_timeline == []
        assert ss.concepts_taught == []
        assert ss.depth_reached == {}
        assert ss.examples_used == []
        assert ss.analogies_used == []
        assert ss.student_responses_summary == []
        assert ss.progress_trend == "steady"
        assert ss.stuck_points == []
        assert ss.what_helped == []
        assert ss.next_focus is None


# ===========================================================================
# SessionState — properties
# ===========================================================================

class TestSessionStateProperties:
    # ---- is_complete ----

    def test_is_complete_false_at_start(self):
        state = _make_state()
        assert state.is_complete is False

    def test_is_complete_true_when_past_total(self):
        topic = _make_topic(num_steps=2)
        state = _make_state(topic=topic, current_step=3)
        assert state.is_complete is True

    def test_is_complete_false_when_on_last_step(self):
        topic = _make_topic(num_steps=2)
        state = _make_state(topic=topic, current_step=2)
        assert state.is_complete is False

    def test_is_complete_false_when_no_topic(self):
        state = SessionState(student_context=StudentContext(grade=3))
        assert state.is_complete is False

    # ---- current_step_data ----

    def test_current_step_data_returns_step(self):
        topic = _make_topic(num_steps=2)
        state = _make_state(topic=topic, current_step=1)
        step = state.current_step_data
        assert step is not None
        assert step.step_id == 1

    def test_current_step_data_returns_none_past_total(self):
        topic = _make_topic(num_steps=2)
        state = _make_state(topic=topic, current_step=99)
        assert state.current_step_data is None

    def test_current_step_data_none_without_topic(self):
        state = SessionState(student_context=StudentContext(grade=3))
        assert state.current_step_data is None

    # ---- progress_percentage ----

    def test_progress_zero_at_step_one(self):
        topic = _make_topic(num_steps=4)
        state = _make_state(topic=topic, current_step=1)
        assert state.progress_percentage == pytest.approx(0.0)

    def test_progress_fifty_at_midpoint(self):
        topic = _make_topic(num_steps=4)
        state = _make_state(topic=topic, current_step=3)
        # (3-1)/4 * 100 = 50.0
        assert state.progress_percentage == pytest.approx(50.0)

    def test_progress_capped_at_100(self):
        topic = _make_topic(num_steps=2)
        state = _make_state(topic=topic, current_step=100)
        assert state.progress_percentage <= 100.0

    def test_progress_zero_without_topic(self):
        state = SessionState(student_context=StudentContext(grade=3))
        assert state.progress_percentage == 0.0

    def test_progress_zero_with_empty_plan(self):
        topic = Topic(
            topic_id="t",
            topic_name="T",
            subject="S",
            grade_level=1,
            guidelines=TopicGuidelines(learning_objectives=["o"]),
            study_plan=StudyPlan(steps=[]),
        )
        state = _make_state(topic=topic)
        assert state.progress_percentage == 0.0

    # ---- overall_mastery ----

    def test_overall_mastery_average(self):
        state = _make_state(mastery_estimates={"A": 0.4, "B": 0.8})
        assert state.overall_mastery == pytest.approx(0.6)

    def test_overall_mastery_zero_when_empty(self):
        state = _make_state(mastery_estimates={})
        assert state.overall_mastery == 0.0

    def test_overall_mastery_single_concept(self):
        state = _make_state(mastery_estimates={"X": 0.75})
        assert state.overall_mastery == pytest.approx(0.75)


# ===========================================================================
# SessionState — methods
# ===========================================================================

class TestSessionStateMethods:
    # ---- get_current_turn_id ----

    def test_get_current_turn_id_initial(self):
        state = _make_state()
        assert state.get_current_turn_id() == "turn_1"

    def test_get_current_turn_id_after_increment(self):
        state = _make_state()
        state.increment_turn()
        assert state.get_current_turn_id() == "turn_2"

    # ---- add_message ----

    def test_add_message_appends(self):
        state = _make_state()
        msg = _msg()
        state.add_message(msg)
        assert len(state.conversation_history) == 1
        assert len(state.full_conversation_log) == 1

    def test_add_message_trims_to_max_10(self):
        state = _make_state()
        for i in range(15):
            state.add_message(_msg(content=f"msg-{i}"))
        assert len(state.conversation_history) == 10
        # The full log is never trimmed
        assert len(state.full_conversation_log) == 15

    def test_add_message_keeps_most_recent(self):
        state = _make_state()
        for i in range(12):
            state.add_message(_msg(content=f"msg-{i}"))
        # Should keep msg-2 through msg-11
        assert state.conversation_history[0].content == "msg-2"
        assert state.conversation_history[-1].content == "msg-11"

    def test_add_message_exactly_10_no_trim(self):
        state = _make_state()
        for i in range(10):
            state.add_message(_msg(content=f"m-{i}"))
        assert len(state.conversation_history) == 10
        assert state.conversation_history[0].content == "m-0"

    # ---- update_mastery ----

    def test_update_mastery_stores_value(self):
        state = _make_state(mastery_estimates={})
        state.update_mastery("Addition", 0.7)
        assert state.mastery_estimates["Addition"] == pytest.approx(0.7)

    def test_update_mastery_clamps_above_one(self):
        state = _make_state()
        state.update_mastery("A", 1.5)
        assert state.mastery_estimates["A"] == pytest.approx(1.0)

    def test_update_mastery_clamps_below_zero(self):
        state = _make_state()
        state.update_mastery("A", -0.3)
        assert state.mastery_estimates["A"] == pytest.approx(0.0)

    def test_update_mastery_boundary_zero(self):
        state = _make_state()
        state.update_mastery("A", 0.0)
        assert state.mastery_estimates["A"] == pytest.approx(0.0)

    def test_update_mastery_boundary_one(self):
        state = _make_state()
        state.update_mastery("A", 1.0)
        assert state.mastery_estimates["A"] == pytest.approx(1.0)

    def test_update_mastery_updates_timestamp(self):
        state = _make_state()
        before = state.updated_at
        state.update_mastery("X", 0.5)
        assert state.updated_at >= before

    # ---- add_misconception ----

    def test_add_misconception(self):
        state = _make_state()
        state.add_misconception("Fractions", "Adds denominators")
        assert len(state.misconceptions) == 1
        assert state.misconceptions[0].concept == "Fractions"
        assert state.misconceptions[0].description == "Adds denominators"

    def test_add_misconception_adds_to_weak_areas(self):
        state = _make_state()
        state.add_misconception("Fractions", "desc")
        assert "Fractions" in state.weak_areas

    def test_add_misconception_no_duplicate_weak_areas(self):
        state = _make_state()
        state.add_misconception("Fractions", "desc1")
        state.add_misconception("Fractions", "desc2")
        assert state.weak_areas.count("Fractions") == 1
        # But both misconceptions are stored
        assert len(state.misconceptions) == 2

    def test_add_misconception_updates_timestamp(self):
        state = _make_state()
        before = state.updated_at
        state.add_misconception("X", "Y")
        assert state.updated_at >= before

    # ---- advance_step ----

    def test_advance_step_increments(self):
        state = _make_state(current_step=1)
        result = state.advance_step()
        assert result is True
        assert state.current_step == 2

    def test_advance_step_returns_false_past_total(self):
        topic = _make_topic(num_steps=2)
        state = _make_state(topic=topic, current_step=3)
        result = state.advance_step()
        assert result is False
        assert state.current_step == 3

    def test_advance_step_allows_one_past(self):
        """Advancing from last step should succeed (moves past total)."""
        topic = _make_topic(num_steps=2)
        state = _make_state(topic=topic, current_step=2)
        result = state.advance_step()
        assert result is True
        assert state.current_step == 3

    def test_advance_step_returns_false_without_topic(self):
        state = SessionState(student_context=StudentContext(grade=3))
        result = state.advance_step()
        assert result is False

    def test_advance_step_updates_timestamp(self):
        state = _make_state(current_step=1)
        before = state.updated_at
        state.advance_step()
        assert state.updated_at >= before

    # ---- set_question / clear_question ----

    def test_set_question(self):
        state = _make_state()
        q = Question(question_text="Q?", expected_answer="A", concept="C")
        state.set_question(q)
        assert state.last_question is not None
        assert state.last_question.question_text == "Q?"
        assert state.awaiting_response is True

    def test_clear_question(self):
        state = _make_state()
        q = Question(question_text="Q?", expected_answer="A", concept="C")
        state.set_question(q)
        state.clear_question()
        assert state.last_question is None
        assert state.awaiting_response is False

    def test_clear_question_updates_timestamp(self):
        state = _make_state()
        before = state.updated_at
        state.clear_question()
        assert state.updated_at >= before

    # ---- increment_turn ----

    def test_increment_turn(self):
        state = _make_state()
        assert state.turn_count == 0
        state.increment_turn()
        assert state.turn_count == 1
        state.increment_turn()
        assert state.turn_count == 2

    def test_increment_turn_updates_timestamp(self):
        state = _make_state()
        before = state.updated_at
        state.increment_turn()
        assert state.updated_at >= before


# ===========================================================================
# create_session factory
# ===========================================================================

class TestCreateSession:
    _default_ctx = StudentContext(grade=3)

    def test_creates_session_with_topic(self):
        topic = _make_topic(num_steps=2)
        session = create_session(topic, student_context=self._default_ctx)
        assert session.topic is topic
        assert session.current_step == 1
        assert session.turn_count == 0

    def test_mastery_initialized_to_zero(self):
        topic = _make_topic(num_steps=4, concepts=["Addition", "Subtraction"])
        session = create_session(topic, student_context=self._default_ctx)
        assert "Addition" in session.mastery_estimates
        assert "Subtraction" in session.mastery_estimates
        for val in session.mastery_estimates.values():
            assert val == 0.0

    def test_uses_provided_student_context(self):
        topic = _make_topic()
        ctx = StudentContext(grade=5, board="ICSE", language_level="advanced")
        session = create_session(topic, student_context=ctx)
        assert session.student_context.grade == 5
        assert session.student_context.board == "ICSE"

    def test_provided_student_context_is_stored(self):
        topic = _make_topic()
        ctx = StudentContext(grade=7)
        session = create_session(topic, student_context=ctx)
        assert session.student_context is not None
        assert session.student_context.grade == 7

    def test_session_id_generated(self):
        topic = _make_topic()
        s1 = create_session(topic, student_context=self._default_ctx)
        s2 = create_session(topic, student_context=self._default_ctx)
        assert s1.session_id.startswith("sess_")
        assert s2.session_id.startswith("sess_")
        assert s1.session_id != s2.session_id

    def test_unique_concepts_only(self):
        """If a concept appears in multiple steps, mastery_estimates has one entry."""
        topic = _make_topic(num_steps=2, concepts=["Addition"])
        session = create_session(topic, student_context=self._default_ctx)
        # "Addition" appears in both explain and check steps, but only one key
        assert list(session.mastery_estimates.keys()) == ["Addition"]
