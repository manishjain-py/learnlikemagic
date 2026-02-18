"""Unit tests for tutor/services/topic_adapter.py — guideline-to-topic conversion."""
import importlib
import json
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
    # Point __path__ to the real package directory so Python can locate
    # sub-modules like topic_adapter while skipping the real __init__.py
    _pkg_dir = os.path.join(os.path.dirname(__file__), "..", "..", "tutor", "services")
    _stub.__path__ = [os.path.abspath(_pkg_dir)]
    _stub.__package__ = "tutor.services"
    sys.modules["tutor.services"] = _stub

from shared.models.schemas import GuidelineResponse, GuidelineMetadata  # noqa: E402
from tutor.services.topic_adapter import (  # noqa: E402
    convert_guideline_to_topic,
    _convert_study_plan,
    _infer_step_type,
    _generate_default_plan,
)
from tutor.models.study_plan import Topic, StudyPlan, StudyPlanStep  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def guideline_with_metadata():
    """A GuidelineResponse with full metadata."""
    return GuidelineResponse(
        id="g1",
        country="India",
        board="CBSE",
        grade=3,
        subject="Mathematics",
        topic="Fractions",
        subtopic="Comparing",
        guideline="Teaching text about comparing fractions.",
        metadata=GuidelineMetadata(
            learning_objectives=["obj1", "obj2"],
            depth_level="intermediate",
            prerequisites=["counting", "number line"],
            common_misconceptions=["bigger denominator means bigger fraction"],
            scaffolding_strategies=["Use visual aids", "Show number line"],
        ),
    )


@pytest.fixture
def guideline_without_metadata():
    """A GuidelineResponse with no metadata."""
    return GuidelineResponse(
        id="g2",
        country="India",
        board="CBSE",
        grade=3,
        subject="Mathematics",
        topic="Fractions",
        subtopic="Adding",
        guideline="Full guideline text about adding fractions that is quite long.",
        metadata=None,
    )


@pytest.fixture
def valid_study_plan_record():
    """A mock study plan DB record with valid plan_json."""
    record = MagicMock()
    record.plan_json = json.dumps({
        "todo_list": [
            {"title": "Introduction to comparing", "description": "Explain the basics"},
            {"title": "Check understanding", "description": "Verify concepts"},
            {"title": "Practice problems", "description": "Solve exercises"},
        ]
    })
    return record


@pytest.fixture
def empty_study_plan_record():
    """A mock study plan DB record with empty todo_list."""
    record = MagicMock()
    record.plan_json = json.dumps({"todo_list": []})
    return record


@pytest.fixture
def invalid_json_study_plan_record():
    """A mock study plan DB record with invalid JSON."""
    record = MagicMock()
    record.plan_json = "this is not json {{"
    return record


# ---------------------------------------------------------------------------
# convert_guideline_to_topic — with metadata
# ---------------------------------------------------------------------------

class TestConvertGuidelineToTopicWithMetadata:
    """Tests for convert_guideline_to_topic when metadata is present."""

    def test_returns_topic_instance(self, guideline_with_metadata):
        """Result is a Topic model instance."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        assert isinstance(topic, Topic)

    def test_topic_id_uses_guideline_id(self, guideline_with_metadata):
        """topic_id comes from guideline.id when available."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        assert topic.topic_id == "g1"

    def test_topic_name_format(self, guideline_with_metadata):
        """topic_name is 'topic - subtopic'."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        assert topic.topic_name == "Fractions - Comparing"

    def test_subject_and_grade(self, guideline_with_metadata):
        """subject and grade_level come from the guideline."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        assert topic.subject == "Mathematics"
        assert topic.grade_level == 3

    def test_learning_objectives_from_metadata(self, guideline_with_metadata):
        """learning_objectives are taken from metadata."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        assert topic.guidelines.learning_objectives == ["obj1", "obj2"]

    def test_common_misconceptions_from_metadata(self, guideline_with_metadata):
        """common_misconceptions are taken from metadata."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        assert topic.guidelines.common_misconceptions == [
            "bigger denominator means bigger fraction"
        ]

    def test_teaching_approach_from_scaffolding(self, guideline_with_metadata):
        """teaching_approach is joined scaffolding_strategies."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        assert topic.guidelines.teaching_approach == "Use visual aids\nShow number line"

    def test_required_depth_from_metadata(self, guideline_with_metadata):
        """required_depth comes from metadata.depth_level."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        assert topic.guidelines.required_depth == "intermediate"

    def test_prerequisite_concepts(self, guideline_with_metadata):
        """prerequisite_concepts come from metadata.prerequisites."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        assert topic.guidelines.prerequisite_concepts == ["counting", "number line"]


# ---------------------------------------------------------------------------
# convert_guideline_to_topic — without metadata
# ---------------------------------------------------------------------------

class TestConvertGuidelineToTopicWithoutMetadata:
    """Tests for convert_guideline_to_topic when metadata is None."""

    def test_fallback_learning_objectives(self, guideline_without_metadata):
        """Without metadata, a default objective is generated from subtopic."""
        topic = convert_guideline_to_topic(guideline_without_metadata)
        assert len(topic.guidelines.learning_objectives) == 1
        assert "Adding" in topic.guidelines.learning_objectives[0]

    def test_fallback_teaching_approach_uses_guideline_text(self, guideline_without_metadata):
        """Without metadata scaffolding, teaching_approach falls back to guideline text."""
        topic = convert_guideline_to_topic(guideline_without_metadata)
        assert topic.guidelines.teaching_approach.startswith("Full guideline text")

    def test_fallback_required_depth(self, guideline_without_metadata):
        """Without metadata, required_depth defaults to 'intermediate'."""
        topic = convert_guideline_to_topic(guideline_without_metadata)
        assert topic.guidelines.required_depth == "intermediate"

    def test_fallback_prerequisites_empty(self, guideline_without_metadata):
        """Without metadata, prerequisite_concepts is empty."""
        topic = convert_guideline_to_topic(guideline_without_metadata)
        assert topic.guidelines.prerequisite_concepts == []

    def test_fallback_misconceptions_empty(self, guideline_without_metadata):
        """Without metadata, common_misconceptions is empty."""
        topic = convert_guideline_to_topic(guideline_without_metadata)
        assert topic.guidelines.common_misconceptions == []

    def test_topic_id_from_guideline_id(self, guideline_without_metadata):
        """topic_id uses guideline.id when present."""
        topic = convert_guideline_to_topic(guideline_without_metadata)
        assert topic.topic_id == "g2"


# ---------------------------------------------------------------------------
# convert_guideline_to_topic — with study plan record
# ---------------------------------------------------------------------------

class TestConvertGuidelineToTopicWithStudyPlan:
    """Tests for convert_guideline_to_topic with a study plan record."""

    def test_study_plan_steps_count(self, guideline_with_metadata, valid_study_plan_record):
        """Study plan has the correct number of steps from plan_json."""
        topic = convert_guideline_to_topic(guideline_with_metadata, valid_study_plan_record)
        assert len(topic.study_plan.steps) == 3

    def test_study_plan_step_concepts(self, guideline_with_metadata, valid_study_plan_record):
        """Step concepts match the 'title' fields from plan_json."""
        topic = convert_guideline_to_topic(guideline_with_metadata, valid_study_plan_record)
        concepts = [s.concept for s in topic.study_plan.steps]
        assert "Introduction to comparing" in concepts
        assert "Check understanding" in concepts
        assert "Practice problems" in concepts

    def test_study_plan_step_ids_are_sequential(self, guideline_with_metadata, valid_study_plan_record):
        """Step IDs are 1-indexed and sequential."""
        topic = convert_guideline_to_topic(guideline_with_metadata, valid_study_plan_record)
        ids = [s.step_id for s in topic.study_plan.steps]
        assert ids == [1, 2, 3]

    def test_explain_step_has_content_hint(self, guideline_with_metadata, valid_study_plan_record):
        """Explain-type steps have content_hint set from the description."""
        topic = convert_guideline_to_topic(guideline_with_metadata, valid_study_plan_record)
        explain_steps = [s for s in topic.study_plan.steps if s.type == "explain"]
        for step in explain_steps:
            assert step.content_hint is not None

    def test_check_step_has_question_type(self, guideline_with_metadata, valid_study_plan_record):
        """Check-type steps have question_type set to 'conceptual'."""
        topic = convert_guideline_to_topic(guideline_with_metadata, valid_study_plan_record)
        check_steps = [s for s in topic.study_plan.steps if s.type == "check"]
        for step in check_steps:
            assert step.question_type == "conceptual"

    def test_practice_step_has_question_count(self, guideline_with_metadata, valid_study_plan_record):
        """Practice-type steps have question_count set to 2."""
        topic = convert_guideline_to_topic(guideline_with_metadata, valid_study_plan_record)
        practice_steps = [s for s in topic.study_plan.steps if s.type == "practice"]
        for step in practice_steps:
            assert step.question_count == 2


# ---------------------------------------------------------------------------
# convert_guideline_to_topic — without study plan record
# ---------------------------------------------------------------------------

class TestConvertGuidelineToTopicWithoutStudyPlan:
    """Tests for convert_guideline_to_topic when study_plan_record is None."""

    def test_default_plan_is_generated(self, guideline_with_metadata):
        """Without a study plan record, a default plan is generated."""
        topic = convert_guideline_to_topic(guideline_with_metadata, study_plan_record=None)
        assert isinstance(topic.study_plan, StudyPlan)
        assert len(topic.study_plan.steps) == 4

    def test_default_plan_step_types(self, guideline_with_metadata):
        """Default plan follows explain-check-explain-practice pattern."""
        topic = convert_guideline_to_topic(guideline_with_metadata)
        types = [s.type for s in topic.study_plan.steps]
        assert types == ["explain", "check", "explain", "practice"]


# ---------------------------------------------------------------------------
# convert_guideline_to_topic — with invalid plan_json
# ---------------------------------------------------------------------------

class TestConvertGuidelineToTopicWithInvalidPlan:
    """Tests for convert_guideline_to_topic when plan_json is invalid."""

    def test_invalid_json_falls_back_to_default(self, guideline_with_metadata, invalid_json_study_plan_record):
        """Invalid JSON in plan_json falls back to the default plan."""
        topic = convert_guideline_to_topic(guideline_with_metadata, invalid_json_study_plan_record)
        assert len(topic.study_plan.steps) == 4
        types = [s.type for s in topic.study_plan.steps]
        assert types == ["explain", "check", "explain", "practice"]

    def test_empty_todo_list_falls_back(self, guideline_with_metadata, empty_study_plan_record):
        """An empty todo_list in plan_json falls back to the default plan."""
        topic = convert_guideline_to_topic(guideline_with_metadata, empty_study_plan_record)
        assert len(topic.study_plan.steps) == 4

    def test_none_plan_json_falls_back(self, guideline_with_metadata):
        """A record with plan_json=None falls back to the default plan."""
        record = MagicMock()
        record.plan_json = None
        topic = convert_guideline_to_topic(guideline_with_metadata, record)
        assert len(topic.study_plan.steps) == 4


# ---------------------------------------------------------------------------
# _infer_step_type
# ---------------------------------------------------------------------------

class TestInferStepType:
    """Tests for _infer_step_type helper."""

    def test_practice_keyword_in_title(self):
        """'practice' keyword in title yields 'practice'."""
        assert _infer_step_type({"title": "Practice problems"}, 1, 5) == "practice"

    def test_solve_keyword_in_description(self):
        """'solve' keyword in description yields 'practice'."""
        assert _infer_step_type({"title": "Step", "description": "Solve these"}, 1, 5) == "practice"

    def test_exercise_keyword(self):
        """'exercise' keyword in title yields 'practice'."""
        assert _infer_step_type({"title": "Exercise set"}, 1, 5) == "practice"

    def test_try_keyword(self):
        """'try' keyword in title yields 'practice'."""
        assert _infer_step_type({"title": "Try it yourself"}, 1, 5) == "practice"

    def test_check_keyword_in_title(self):
        """'check' keyword in title yields 'check'."""
        assert _infer_step_type({"title": "Check understanding"}, 1, 5) == "check"

    def test_quiz_keyword(self):
        """'quiz' keyword in description yields 'check'."""
        assert _infer_step_type({"title": "Step", "description": "Quick quiz"}, 1, 5) == "check"

    def test_assess_keyword(self):
        """'assess' keyword yields 'check'."""
        assert _infer_step_type({"title": "Assess knowledge"}, 1, 5) == "check"

    def test_test_keyword(self):
        """'test' keyword in description yields 'check'."""
        assert _infer_step_type({"title": "Step", "description": "test your knowledge"}, 1, 5) == "check"

    def test_verify_keyword(self):
        """'verify' keyword yields 'check'."""
        assert _infer_step_type({"title": "Verify understanding"}, 1, 5) == "check"

    def test_teaching_approach_keyword(self):
        """Keywords in teaching_approach field are also checked."""
        assert _infer_step_type({"title": "Step", "teaching_approach": "practice with examples"}, 1, 5) == "practice"

    def test_last_step_defaults_to_practice(self):
        """The last step (index == total) defaults to 'practice' when no keywords."""
        assert _infer_step_type({"title": "Final step"}, 3, 3) == "practice"

    def test_even_index_defaults_to_check(self):
        """Even-index steps default to 'check' when no keywords."""
        assert _infer_step_type({"title": "Step two"}, 2, 5) == "check"

    def test_odd_index_defaults_to_explain(self):
        """Odd-index steps default to 'explain' when no keywords."""
        assert _infer_step_type({"title": "Step one"}, 1, 5) == "explain"

    def test_third_odd_index_defaults_to_explain(self):
        """Index 3 (odd, not last) defaults to 'explain'."""
        assert _infer_step_type({"title": "Intro"}, 3, 5) == "explain"

    def test_fourth_even_index_defaults_to_check(self):
        """Index 4 (even, not last) defaults to 'check'."""
        assert _infer_step_type({"title": "Review"}, 4, 5) == "check"


# ---------------------------------------------------------------------------
# _generate_default_plan
# ---------------------------------------------------------------------------

class TestGenerateDefaultPlan:
    """Tests for _generate_default_plan helper."""

    def test_returns_study_plan(self, guideline_with_metadata):
        """Returns a StudyPlan instance."""
        plan = _generate_default_plan(guideline_with_metadata)
        assert isinstance(plan, StudyPlan)

    def test_has_four_steps(self, guideline_with_metadata):
        """Default plan has exactly 4 steps."""
        plan = _generate_default_plan(guideline_with_metadata)
        assert len(plan.steps) == 4

    def test_step_types_pattern(self, guideline_with_metadata):
        """Default plan follows explain-check-explain-practice."""
        plan = _generate_default_plan(guideline_with_metadata)
        types = [s.type for s in plan.steps]
        assert types == ["explain", "check", "explain", "practice"]

    def test_step_ids_sequential(self, guideline_with_metadata):
        """Step IDs are 1-4."""
        plan = _generate_default_plan(guideline_with_metadata)
        ids = [s.step_id for s in plan.steps]
        assert ids == [1, 2, 3, 4]

    def test_concepts_use_subtopic(self, guideline_with_metadata):
        """All step concepts use the guideline subtopic."""
        plan = _generate_default_plan(guideline_with_metadata)
        for step in plan.steps:
            assert step.concept == "Comparing"

    def test_first_step_content_hint(self, guideline_with_metadata):
        """First explain step has a content hint with 'Introduce'."""
        plan = _generate_default_plan(guideline_with_metadata)
        assert "Introduce" in plan.steps[0].content_hint
        assert "Comparing" in plan.steps[0].content_hint

    def test_check_step_has_conceptual_question_type(self, guideline_with_metadata):
        """Check step has question_type='conceptual'."""
        plan = _generate_default_plan(guideline_with_metadata)
        check_step = plan.steps[1]
        assert check_step.question_type == "conceptual"

    def test_practice_step_has_question_count(self, guideline_with_metadata):
        """Practice step has question_count=2."""
        plan = _generate_default_plan(guideline_with_metadata)
        practice_step = plan.steps[3]
        assert practice_step.question_count == 2

    def test_third_step_content_hint(self, guideline_with_metadata):
        """Third explain step has 'Deepen' in content hint."""
        plan = _generate_default_plan(guideline_with_metadata)
        assert "Deepen" in plan.steps[2].content_hint


# ---------------------------------------------------------------------------
# _convert_study_plan
# ---------------------------------------------------------------------------

class TestConvertStudyPlan:
    """Tests for _convert_study_plan helper."""

    def test_none_record_returns_default(self, guideline_with_metadata):
        """None record returns the default plan."""
        plan = _convert_study_plan(None, guideline_with_metadata)
        assert len(plan.steps) == 4

    def test_valid_record_returns_parsed_plan(self, guideline_with_metadata, valid_study_plan_record):
        """A valid record returns a plan with steps from the todo_list."""
        plan = _convert_study_plan(valid_study_plan_record, guideline_with_metadata)
        assert len(plan.steps) == 3

    def test_invalid_json_returns_default(self, guideline_with_metadata, invalid_json_study_plan_record):
        """Invalid JSON returns the default plan."""
        plan = _convert_study_plan(invalid_json_study_plan_record, guideline_with_metadata)
        assert len(plan.steps) == 4
