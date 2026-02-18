"""Unit tests for shared/models/domain.py — TutorState, Student, Goal, and related models."""

import pytest
from pydantic import ValidationError

from shared.models.domain import (
    Student,
    StudentPrefs,
    Goal,
    HistoryEntry,
    GradingResult,
    TutorState,
    RAGSnippet,
    GuidelineMetadata,
)


# ---------------------------------------------------------------------------
# Tests — StudentPrefs
# ---------------------------------------------------------------------------

class TestStudentPrefs:
    def test_defaults(self):
        prefs = StudentPrefs()
        assert prefs.style == "standard"
        assert prefs.lang == "en"

    def test_custom_values(self):
        prefs = StudentPrefs(style="challenge", lang="hi")
        assert prefs.style == "challenge"
        assert prefs.lang == "hi"


# ---------------------------------------------------------------------------
# Tests — Student
# ---------------------------------------------------------------------------

class TestStudent:
    def test_basic_student(self):
        student = Student(id="s1", grade=3)
        assert student.id == "s1"
        assert student.grade == 3
        assert student.prefs is None

    def test_student_with_prefs(self):
        student = Student(id="s2", grade=5, prefs=StudentPrefs(style="simple"))
        assert student.prefs.style == "simple"

    def test_student_serialization(self):
        student = Student(id="s3", grade=7, prefs=StudentPrefs(lang="es"))
        data = student.model_dump()
        assert data["id"] == "s3"
        assert data["grade"] == 7
        assert data["prefs"]["lang"] == "es"


# ---------------------------------------------------------------------------
# Tests — Goal
# ---------------------------------------------------------------------------

class TestGoal:
    def test_basic_goal(self):
        goal = Goal(
            topic="Fractions",
            syllabus="CBSE Grade 3 Math",
            learning_objectives=["Understand what a fraction is"],
        )
        assert goal.topic == "Fractions"
        assert len(goal.learning_objectives) == 1
        assert goal.guideline_id is None

    def test_goal_with_guideline(self):
        goal = Goal(
            topic="Fractions",
            syllabus="CBSE Grade 3",
            learning_objectives=["Learn fractions"],
            guideline_id="g-123",
        )
        assert goal.guideline_id == "g-123"

    def test_goal_requires_fields(self):
        with pytest.raises(ValidationError):
            Goal(topic="Fractions")  # missing syllabus, learning_objectives


# ---------------------------------------------------------------------------
# Tests — HistoryEntry
# ---------------------------------------------------------------------------

class TestHistoryEntry:
    def test_basic_entry(self):
        entry = HistoryEntry(role="teacher", msg="Hello!")
        assert entry.role == "teacher"
        assert entry.msg == "Hello!"
        assert entry.meta is None

    def test_entry_with_meta(self):
        entry = HistoryEntry(role="student", msg="42", meta={"confidence": 0.9})
        assert entry.meta["confidence"] == 0.9


# ---------------------------------------------------------------------------
# Tests — GradingResult
# ---------------------------------------------------------------------------

class TestGradingResult:
    def test_correct_grading(self):
        grading = GradingResult(
            score=0.9,
            rationale="Correct answer with good reasoning",
            labels=[],
            confidence=0.95,
        )
        assert grading.score == 0.9
        assert grading.confidence == 0.95

    def test_incorrect_grading_with_labels(self):
        grading = GradingResult(
            score=0.2,
            rationale="Incorrect — confuses numerator and denominator",
            labels=["numerator_denominator_confusion"],
            confidence=0.8,
        )
        assert len(grading.labels) == 1

    def test_score_range_validation(self):
        with pytest.raises(ValidationError):
            GradingResult(score=1.5, rationale="invalid", confidence=0.5)

        with pytest.raises(ValidationError):
            GradingResult(score=-0.1, rationale="invalid", confidence=0.5)

    def test_confidence_range_validation(self):
        with pytest.raises(ValidationError):
            GradingResult(score=0.5, rationale="ok", confidence=1.5)

    def test_default_labels(self):
        grading = GradingResult(score=0.5, rationale="ok", confidence=0.5)
        assert grading.labels == []


# ---------------------------------------------------------------------------
# Tests — TutorState
# ---------------------------------------------------------------------------

class TestTutorState:
    def _make_state(self, **overrides) -> TutorState:
        defaults = dict(
            session_id="sess-1",
            student=Student(id="s1", grade=3),
            goal=Goal(
                topic="Fractions",
                syllabus="CBSE Grade 3",
                learning_objectives=["Learn fractions"],
            ),
        )
        defaults.update(overrides)
        return TutorState(**defaults)

    def test_default_values(self):
        state = self._make_state()
        assert state.step_idx == 0
        assert state.history == []
        assert state.evidence == []
        assert state.mastery_score == 0.0
        assert state.last_grading is None
        assert state.next_action is None

    def test_with_history(self):
        state = self._make_state(
            history=[
                HistoryEntry(role="teacher", msg="Hello!"),
                HistoryEntry(role="student", msg="Hi!"),
            ]
        )
        assert len(state.history) == 2
        assert state.history[0].role == "teacher"

    def test_with_grading(self):
        grading = GradingResult(
            score=0.8,
            rationale="Good",
            confidence=0.9,
        )
        state = self._make_state(last_grading=grading)
        assert state.last_grading.score == 0.8

    def test_with_evidence(self):
        state = self._make_state(evidence=["confuses numerator", "counts wrong"])
        assert len(state.evidence) == 2

    def test_step_progression(self):
        state = self._make_state(step_idx=0)
        assert state.step_idx == 0

        state.step_idx = 3
        assert state.step_idx == 3

    def test_serialization_roundtrip(self):
        state = self._make_state(
            mastery_score=0.75,
            step_idx=2,
            next_action="check",
        )
        json_str = state.model_dump_json()
        restored = TutorState.model_validate_json(json_str)

        assert restored.session_id == "sess-1"
        assert restored.mastery_score == 0.75
        assert restored.step_idx == 2
        assert restored.next_action == "check"


# ---------------------------------------------------------------------------
# Tests — RAGSnippet
# ---------------------------------------------------------------------------

class TestRAGSnippet:
    def test_basic_snippet(self):
        snippet = RAGSnippet(id="c1", text="A fraction is part of a whole.")
        assert snippet.id == "c1"
        assert snippet.meta == {}

    def test_snippet_with_meta(self):
        snippet = RAGSnippet(
            id="c2",
            text="Comparing fractions...",
            meta={"grade": 3, "topic": "fractions"},
        )
        assert snippet.meta["grade"] == 3


# ---------------------------------------------------------------------------
# Tests — GuidelineMetadata
# ---------------------------------------------------------------------------

class TestGuidelineMetadata:
    def test_defaults(self):
        meta = GuidelineMetadata()
        assert meta.learning_objectives == []
        assert meta.depth_level == "intermediate"
        assert meta.prerequisites == []
        assert meta.common_misconceptions == []
        assert meta.scaffolding_strategies == []
        assert meta.assessment_criteria == {}

    def test_fully_populated(self):
        meta = GuidelineMetadata(
            learning_objectives=["Understand fractions", "Compare fractions"],
            depth_level="advanced",
            prerequisites=["Counting", "Division concept"],
            common_misconceptions=["Bigger denominator = bigger fraction"],
            scaffolding_strategies=["Use visuals", "Concrete to abstract"],
            assessment_criteria={"basic": "Can identify fraction", "advanced": "Can compare"},
        )
        assert len(meta.learning_objectives) == 2
        assert meta.depth_level == "advanced"
        assert len(meta.assessment_criteria) == 2
