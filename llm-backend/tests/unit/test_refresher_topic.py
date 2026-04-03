"""Unit tests for the Chapter Prerequisites (Refresher Topics) feature.

Tests cover:
- SessionState.is_refresher serialization round-trip
- SessionState.is_complete logic for refresher sessions
- convert_guideline_to_topic with is_refresher flag
- RefresherOutput model validation
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-fake")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

# ---------------------------------------------------------------------------
# Prevent the heavy tutor.services.__init__ from importing SessionService
# which triggers google-genai / cryptography chain.  We inject a lightweight
# stub *before* importing topic_adapter so Python never tries to load the
# real __init__.
# ---------------------------------------------------------------------------
if "tutor.services" not in sys.modules:
    _stub = types.ModuleType("tutor.services")
    _pkg_dir = os.path.join(os.path.dirname(__file__), "..", "..", "tutor", "services")
    _stub.__path__ = [os.path.abspath(_pkg_dir)]
    _stub.__package__ = "tutor.services"
    sys.modules["tutor.services"] = _stub

from tutor.models.session_state import (  # noqa: E402
    SessionState,
    CardPhaseState,
)
from tutor.models.study_plan import (  # noqa: E402
    Topic,
    TopicGuidelines,
    StudyPlan,
    StudyPlanStep,
)
from tutor.models.messages import StudentContext  # noqa: E402
from shared.models.schemas import GuidelineResponse, GuidelineMetadata  # noqa: E402
from tutor.services.topic_adapter import convert_guideline_to_topic  # noqa: E402
from book_ingestion_v2.services.refresher_topic_generator_service import (  # noqa: E402
    RefresherOutput,
    PrerequisiteConcept,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_topic(num_steps: int = 2) -> Topic:
    """Build a minimal Topic with the given number of steps."""
    steps = []
    for i in range(1, num_steps + 1):
        steps.append(StudyPlanStep(step_id=i, type="explain", concept="TestConcept"))
    return Topic(
        topic_id="test-topic",
        topic_name="Test Topic",
        subject="Math",
        grade_level=3,
        guidelines=TopicGuidelines(learning_objectives=["obj1"]),
        study_plan=StudyPlan(steps=steps),
    )


def _make_guideline(**overrides) -> GuidelineResponse:
    """Build a minimal GuidelineResponse."""
    defaults = dict(
        id="g1",
        country="India",
        board="CBSE",
        grade=3,
        subject="Mathematics",
        chapter="Fractions",
        topic="Comparing",
        guideline="Teaching text about comparing fractions.",
        metadata=GuidelineMetadata(
            learning_objectives=["obj1", "obj2"],
            depth_level="intermediate",
            prerequisites=["counting"],
            common_misconceptions=["bigger denominator means bigger fraction"],
        ),
    )
    defaults.update(overrides)
    return GuidelineResponse(**defaults)


# ===========================================================================
# SessionState.is_refresher — serialization round-trip
# ===========================================================================

class TestRefresherStatePersisted:
    """is_refresher survives model_dump / model_validate round-trip."""

    def test_refresher_true_round_trip(self):
        state = SessionState(
            is_refresher=True,
            topic=_make_topic(),
            student_context=StudentContext(grade=3),
        )
        data = state.model_dump()
        restored = SessionState.model_validate(data)
        assert restored.is_refresher is True

    def test_refresher_false_round_trip(self):
        state = SessionState(
            is_refresher=False,
            topic=_make_topic(),
            student_context=StudentContext(grade=3),
        )
        data = state.model_dump()
        restored = SessionState.model_validate(data)
        assert restored.is_refresher is False

    def test_refresher_default_is_false(self):
        state = SessionState(
            topic=_make_topic(),
            student_context=StudentContext(grade=3),
        )
        assert state.is_refresher is False


# ===========================================================================
# SessionState.is_complete — refresher semantics
# ===========================================================================

class TestRefresherIsComplete:
    """For refresher sessions, is_complete depends only on card_phase.completed."""

    def test_refresher_incomplete_when_no_card_phase(self):
        """is_refresher=True but card_phase is None -> not complete."""
        state = SessionState(
            is_refresher=True,
            card_phase=None,
            topic=_make_topic(),
            student_context=StudentContext(grade=3),
        )
        assert state.is_complete is False

    def test_refresher_incomplete_when_card_phase_active(self):
        """Card phase exists but not yet completed -> not complete."""
        state = SessionState(
            is_refresher=True,
            card_phase=CardPhaseState(
                guideline_id="g1",
                active=True,
                completed=False,
                total_cards=3,
            ),
            topic=_make_topic(),
            student_context=StudentContext(grade=3),
        )
        assert state.is_complete is False

    def test_refresher_complete_after_cards_done(self):
        """Card phase completed -> session is complete."""
        state = SessionState(
            is_refresher=True,
            card_phase=CardPhaseState(
                guideline_id="g1",
                active=False,
                completed=True,
                total_cards=3,
                current_card_idx=3,
            ),
            topic=_make_topic(),
            student_context=StudentContext(grade=3),
        )
        assert state.is_complete is True

    def test_refresher_ignores_study_plan_step(self):
        """Refresher should not use current_step > total_steps logic."""
        state = SessionState(
            is_refresher=True,
            card_phase=CardPhaseState(
                guideline_id="g1",
                active=True,
                completed=False,
                total_cards=3,
            ),
            topic=_make_topic(num_steps=2),
            current_step=99,  # would be "complete" for normal sessions
            student_context=StudentContext(grade=3),
        )
        assert state.is_complete is False


# ===========================================================================
# convert_guideline_to_topic — refresher vs regular
# ===========================================================================

class TestRefresherZeroStepPlan:
    """Refresher topics get an empty study plan when no study_plan_record."""

    def test_refresher_empty_plan(self):
        guideline = _make_guideline()
        topic = convert_guideline_to_topic(guideline, study_plan_record=None, is_refresher=True)
        assert len(topic.study_plan.steps) == 0
        assert topic.study_plan.total_steps == 0

    def test_refresher_still_has_topic_metadata(self):
        guideline = _make_guideline()
        topic = convert_guideline_to_topic(guideline, study_plan_record=None, is_refresher=True)
        assert topic.subject == "Mathematics"
        assert topic.grade_level == 3
        assert "Fractions" in topic.topic_name


class TestRegularTopicDefaultPlan:
    """Non-refresher topics get a non-empty default plan when no study_plan_record."""

    def test_regular_default_plan_has_steps(self):
        guideline = _make_guideline()
        topic = convert_guideline_to_topic(guideline, study_plan_record=None, is_refresher=False)
        assert len(topic.study_plan.steps) > 0

    def test_regular_default_plan_has_five_steps(self):
        guideline = _make_guideline()
        topic = convert_guideline_to_topic(guideline, study_plan_record=None, is_refresher=False)
        assert len(topic.study_plan.steps) == 5

    def test_regular_default_plan_step_types(self):
        guideline = _make_guideline()
        topic = convert_guideline_to_topic(guideline, study_plan_record=None, is_refresher=False)
        types = [s.type for s in topic.study_plan.steps]
        assert types == ["explain", "explain", "check", "explain", "practice"]


# ===========================================================================
# RefresherOutput model validation
# ===========================================================================

class TestRefresherOutputModel:
    """RefresherOutput serializes and deserializes correctly."""

    def test_with_prerequisite_concepts(self):
        output = RefresherOutput(
            skip_refresher=False,
            prerequisite_concepts=[
                PrerequisiteConcept(concept="Addition", why_needed="Used in combining fractions"),
                PrerequisiteConcept(concept="Number Line", why_needed="Visual model for comparison"),
            ],
            refresher_guideline="Review addition and number lines before fractions.",
            topic_summary="Quick review of addition and number lines.",
            cards=[],
        )
        data = output.model_dump()
        assert data["skip_refresher"] is False
        assert len(data["prerequisite_concepts"]) == 2
        assert data["prerequisite_concepts"][0]["concept"] == "Addition"
        assert data["refresher_guideline"] == "Review addition and number lines before fractions."
        assert data["topic_summary"] == "Quick review of addition and number lines."

    def test_round_trip(self):
        output = RefresherOutput(
            skip_refresher=False,
            prerequisite_concepts=[
                PrerequisiteConcept(concept="Counting", why_needed="Foundation for all math"),
            ],
            refresher_guideline="Some guideline.",
            topic_summary="Some summary.",
        )
        data = output.model_dump()
        restored = RefresherOutput.model_validate(data)
        assert restored.skip_refresher is False
        assert len(restored.prerequisite_concepts) == 1
        assert restored.prerequisite_concepts[0].concept == "Counting"


class TestRefresherOutputSkip:
    """RefresherOutput with skip_refresher=True."""

    def test_skip_with_reason(self):
        output = RefresherOutput(
            skip_refresher=True,
            skip_reason="This is an introductory chapter with no prerequisites.",
        )
        assert output.skip_refresher is True
        assert output.skip_reason == "This is an introductory chapter with no prerequisites."
        assert output.prerequisite_concepts == []
        assert output.cards == []

    def test_skip_without_reason(self):
        output = RefresherOutput(skip_refresher=True)
        assert output.skip_refresher is True
        assert output.skip_reason is None

    def test_skip_serializes(self):
        output = RefresherOutput(
            skip_refresher=True,
            skip_reason="No prerequisites needed.",
        )
        data = output.model_dump()
        assert data["skip_refresher"] is True
        assert data["skip_reason"] == "No prerequisites needed."
