"""Unit tests for shared/models/schemas.py and shared/models/entities.py."""

import pytest
from pydantic import ValidationError

from shared.models.domain import Student, Goal, GradingResult, GuidelineMetadata
from shared.models.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    StepRequest,
    StepResponse,
    SummaryResponse,
    GuidelineResponse,
    SubtopicInfo,
    CurriculumResponse,
)
from shared.models.entities import (
    Base,
    Session,
    Event,
    Content,
    TeachingGuideline,
    StudyPlan,
)


# ---------------------------------------------------------------------------
# Tests — Request / Response Schemas
# ---------------------------------------------------------------------------

class TestCreateSessionRequest:
    def test_valid_request(self):
        req = CreateSessionRequest(
            student=Student(id="s1", grade=3),
            goal=Goal(
                topic="Fractions",
                syllabus="CBSE Grade 3",
                learning_objectives=["Learn fractions"],
                guideline_id="g-1",
            ),
        )
        assert req.student.grade == 3
        assert req.goal.guideline_id == "g-1"

    def test_missing_student(self):
        with pytest.raises(ValidationError):
            CreateSessionRequest(
                goal=Goal(
                    topic="Fractions",
                    syllabus="CBSE",
                    learning_objectives=["test"],
                ),
            )

    def test_missing_goal(self):
        with pytest.raises(ValidationError):
            CreateSessionRequest(
                student=Student(id="s1", grade=3),
            )

    def test_serialization(self):
        req = CreateSessionRequest(
            student=Student(id="s1", grade=5),
            goal=Goal(
                topic="Algebra",
                syllabus="CBSE Grade 5",
                learning_objectives=["Solve equations"],
            ),
        )
        data = req.model_dump()
        assert data["student"]["id"] == "s1"
        assert data["goal"]["topic"] == "Algebra"


class TestCreateSessionResponse:
    def test_valid_response(self):
        resp = CreateSessionResponse(
            session_id="sess-abc",
            first_turn={"message": "Hello!", "hints": [], "step_idx": 1},
        )
        assert resp.session_id == "sess-abc"
        assert resp.first_turn["message"] == "Hello!"


class TestStepRequest:
    def test_valid_step(self):
        req = StepRequest(student_reply="3/4")
        assert req.student_reply == "3/4"

    def test_empty_reply(self):
        req = StepRequest(student_reply="")
        assert req.student_reply == ""


class TestStepResponse:
    def test_with_grading(self):
        grading = GradingResult(
            score=0.9,
            rationale="Correct",
            confidence=0.95,
        )
        resp = StepResponse(
            next_turn={"message": "Great!", "step_idx": 2},
            routing="Advance",
            last_grading=grading,
        )
        assert resp.routing == "Advance"
        assert resp.last_grading.score == 0.9

    def test_without_grading(self):
        resp = StepResponse(
            next_turn={"message": "Let me explain...", "step_idx": 1},
            routing="Continue",
        )
        assert resp.last_grading is None


class TestSummaryResponse:
    def test_valid_summary(self):
        summary = SummaryResponse(
            steps_completed=3,
            mastery_score=0.85,
            misconceptions_seen=["confuses numerator"],
            suggestions=["Great work!", "Try harder problems"],
        )
        assert summary.steps_completed == 3
        assert summary.mastery_score == 0.85
        assert len(summary.misconceptions_seen) == 1

    def test_empty_misconceptions(self):
        summary = SummaryResponse(
            steps_completed=0,
            mastery_score=0.0,
            misconceptions_seen=[],
            suggestions=[],
        )
        assert summary.misconceptions_seen == []


class TestGuidelineResponse:
    def test_basic_guideline(self):
        resp = GuidelineResponse(
            id="g-1",
            country="India",
            board="CBSE",
            grade=3,
            subject="Mathematics",
            topic="Fractions",
            subtopic="Basics",
            guideline="Teach fractions with visuals.",
        )
        assert resp.id == "g-1"
        assert resp.metadata is None

    def test_guideline_with_metadata(self):
        meta = GuidelineMetadata(
            learning_objectives=["Understand fractions"],
            depth_level="basic",
        )
        resp = GuidelineResponse(
            id="g-2",
            country="India",
            board="CBSE",
            grade=3,
            subject="Math",
            topic="Fractions",
            subtopic="Comparison",
            guideline="Teach comparing fractions.",
            metadata=meta,
        )
        assert resp.metadata.depth_level == "basic"


class TestSubtopicInfo:
    def test_valid(self):
        info = SubtopicInfo(subtopic="Basics", guideline_id="g-1")
        assert info.subtopic == "Basics"


class TestCurriculumResponse:
    def test_subjects_response(self):
        resp = CurriculumResponse(subjects=["Mathematics", "Science"])
        assert resp.subjects == ["Mathematics", "Science"]
        assert resp.topics is None

    def test_topics_response(self):
        resp = CurriculumResponse(topics=["Fractions", "Decimals"])
        assert resp.topics == ["Fractions", "Decimals"]

    def test_subtopics_response(self):
        resp = CurriculumResponse(
            subtopics=[
                SubtopicInfo(subtopic="Basics", guideline_id="g-1"),
                SubtopicInfo(subtopic="Comparison", guideline_id="g-2"),
            ]
        )
        assert len(resp.subtopics) == 2


# ---------------------------------------------------------------------------
# Tests — SQLAlchemy ORM Entities (class attribute checks, no DB required)
# ---------------------------------------------------------------------------

class TestSessionEntity:
    def test_tablename(self):
        assert Session.__tablename__ == "sessions"

    def test_columns(self):
        cols = {c.name for c in Session.__table__.columns}
        assert "id" in cols
        assert "student_json" in cols
        assert "goal_json" in cols
        assert "state_json" in cols
        assert "mastery" in cols
        assert "step_idx" in cols
        assert "created_at" in cols
        assert "updated_at" in cols


class TestEventEntity:
    def test_tablename(self):
        assert Event.__tablename__ == "events"

    def test_columns(self):
        cols = {c.name for c in Event.__table__.columns}
        assert "id" in cols
        assert "session_id" in cols
        assert "node" in cols
        assert "step_idx" in cols
        assert "payload_json" in cols

    def test_foreign_key(self):
        fks = [fk.target_fullname for fk in Event.__table__.foreign_keys]
        assert "sessions.id" in fks


class TestContentEntity:
    def test_tablename(self):
        assert Content.__tablename__ == "contents"

    def test_columns(self):
        cols = {c.name for c in Content.__table__.columns}
        assert "id" in cols
        assert "topic" in cols
        assert "grade" in cols
        assert "skill" in cols
        assert "text" in cols
        assert "tags" in cols


class TestTeachingGuidelineEntity:
    def test_tablename(self):
        assert TeachingGuideline.__tablename__ == "teaching_guidelines"

    def test_columns(self):
        cols = {c.name for c in TeachingGuideline.__table__.columns}
        assert "id" in cols
        assert "country" in cols
        assert "board" in cols
        assert "grade" in cols
        assert "subject" in cols
        assert "topic" in cols
        assert "subtopic" in cols
        assert "guideline" in cols
        assert "topic_title" in cols
        assert "subtopic_title" in cols
        assert "status" in cols
        assert "version" in cols

    def test_has_v1_fields(self):
        """V1 fields should still exist for backward compatibility."""
        cols = {c.name for c in TeachingGuideline.__table__.columns}
        assert "objectives_json" in cols
        assert "misconceptions_json" in cols
        assert "description" in cols


class TestStudyPlanEntity:
    def test_tablename(self):
        assert StudyPlan.__tablename__ == "study_plans"

    def test_columns(self):
        cols = {c.name for c in StudyPlan.__table__.columns}
        assert "id" in cols
        assert "guideline_id" in cols
        assert "plan_json" in cols
        assert "generator_model" in cols
        assert "reviewer_model" in cols
        assert "was_revised" in cols
        assert "version" in cols

    def test_foreign_key(self):
        fks = [fk.target_fullname for fk in StudyPlan.__table__.foreign_keys]
        assert "teaching_guidelines.id" in fks


class TestBaseDeclarativeBase:
    def test_base_has_metadata(self):
        assert Base.metadata is not None
        table_names = list(Base.metadata.tables.keys())
        assert "sessions" in table_names
        assert "events" in table_names
        assert "teaching_guidelines" in table_names
        assert "study_plans" in table_names
