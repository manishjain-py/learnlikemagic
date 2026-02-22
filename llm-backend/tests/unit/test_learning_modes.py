"""
Tests for learning modes feature: session state modes, scorecard revision nudge,
exam service, and new REST endpoints (resumable, pause, resume, end-exam).
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from tutor.models.session_state import (
    SessionState,
    ExamQuestion,
    ExamFeedback,
    create_session,
)
from tutor.models.study_plan import (
    Topic,
    TopicGuidelines,
    StudyPlan,
    StudyPlanStep,
)
from tutor.models.messages import StudentContext
from tutor.services.scorecard_service import ScorecardService
from tutor.services.exam_service import ExamService, ExamGenerationError


# ---------------------------------------------------------------------------
# Test-data factories
# ---------------------------------------------------------------------------

def make_test_guidelines(**kwargs) -> TopicGuidelines:
    defaults = dict(
        learning_objectives=["Understand fractions", "Compare fractions"],
        required_depth="conceptual",
        prerequisite_concepts=["whole numbers"],
        common_misconceptions=["bigger denominator means bigger fraction"],
        teaching_approach="visual models",
    )
    defaults.update(kwargs)
    return TopicGuidelines(**defaults)


def make_test_study_plan(concepts=None) -> StudyPlan:
    if concepts is None:
        concepts = ["Numerator", "Denominator", "Comparing fractions"]
    steps = []
    for i, concept in enumerate(concepts, start=1):
        steps.append(StudyPlanStep(step_id=i, type="explain", concept=concept))
    return StudyPlan(steps=steps)


def make_test_topic(concepts=None, **kwargs) -> Topic:
    defaults = dict(
        topic_id="guideline-123",
        topic_name="Fractions",
        subject="Math",
        grade_level=3,
        guidelines=make_test_guidelines(),
        study_plan=make_test_study_plan(concepts),
    )
    defaults.update(kwargs)
    return Topic(**defaults)


def make_test_student_context(**kwargs) -> StudentContext:
    defaults = dict(grade=3, board="CBSE", language_level="simple")
    defaults.update(kwargs)
    return StudentContext(**defaults)


def make_test_session(mode="teach_me", concepts=None, **kwargs) -> SessionState:
    """Create a SessionState using create_session for realistic initialization."""
    topic = make_test_topic(concepts=concepts)
    ctx = make_test_student_context()
    session = create_session(topic=topic, student_context=ctx, mode=mode)
    for k, v in kwargs.items():
        setattr(session, k, v)
    return session


# ===========================================================================
# 1. SessionState model tests
# ===========================================================================

class TestCreateSession:
    """Tests for session_state.create_session()."""

    def test_teach_me_initializes_mastery_estimates(self):
        topic = make_test_topic(concepts=["A", "B", "C"])
        ctx = make_test_student_context()
        session = create_session(topic=topic, student_context=ctx, mode="teach_me")
        assert session.mode == "teach_me"
        assert set(session.mastery_estimates.keys()) == {"A", "B", "C"}
        assert all(v == 0.0 for v in session.mastery_estimates.values())

    def test_clarify_doubts_no_mastery_estimates(self):
        topic = make_test_topic(concepts=["A", "B"])
        ctx = make_test_student_context()
        session = create_session(topic=topic, student_context=ctx, mode="clarify_doubts")
        assert session.mode == "clarify_doubts"
        assert session.mastery_estimates == {}

    def test_exam_no_mastery_estimates(self):
        topic = make_test_topic(concepts=["A", "B"])
        ctx = make_test_student_context()
        session = create_session(topic=topic, student_context=ctx, mode="exam")
        assert session.mode == "exam"
        assert session.mastery_estimates == {}

    def test_student_context_is_preserved(self):
        topic = make_test_topic()
        ctx = make_test_student_context(grade=5, board="ICSE")
        session = create_session(topic=topic, student_context=ctx, mode="teach_me")
        assert session.student_context.grade == 5
        assert session.student_context.board == "ICSE"

    def test_default_student_context_uses_provided(self):
        topic = make_test_topic()
        ctx = make_test_student_context(grade=3)
        session = create_session(topic=topic, student_context=ctx)
        assert session.student_context is not None
        assert session.student_context.grade == 3


class TestConceptsCoveredSetValidator:
    """Tests for the field_validator that coerces list->set on concepts_covered_set."""

    def test_list_coerced_to_set(self):
        """JSON round-trip delivers a list; the validator must convert it to set."""
        session = make_test_session()
        session.concepts_covered_set = {"A", "B"}
        dumped = session.model_dump_json()
        restored = SessionState.model_validate_json(dumped)
        assert isinstance(restored.concepts_covered_set, set)
        assert restored.concepts_covered_set == {"A", "B"}

    def test_set_stays_as_set(self):
        ctx = make_test_student_context()
        session = SessionState(
            student_context=ctx,
            concepts_covered_set={"X", "Y"},
        )
        assert session.concepts_covered_set == {"X", "Y"}

    def test_empty_list_coerced(self):
        ctx = make_test_student_context()
        session = SessionState.model_validate({
            "student_context": ctx.model_dump(),
            "concepts_covered_set": [],
        })
        assert session.concepts_covered_set == set()

    def test_list_with_duplicates(self):
        ctx = make_test_student_context()
        session = SessionState.model_validate({
            "student_context": ctx.model_dump(),
            "concepts_covered_set": ["A", "A", "B"],
        })
        assert session.concepts_covered_set == {"A", "B"}


class TestCoveragePercentage:
    """Tests for the coverage_percentage property."""

    def test_no_topic_returns_zero(self):
        ctx = make_test_student_context()
        session = SessionState(student_context=ctx)
        assert session.coverage_percentage == 0.0

    def test_no_coverage(self):
        session = make_test_session(concepts=["A", "B", "C"])
        session.concepts_covered_set = set()
        assert session.coverage_percentage == 0.0

    def test_partial_coverage(self):
        session = make_test_session(concepts=["A", "B", "C", "D"])
        session.concepts_covered_set = {"A", "B"}
        assert session.coverage_percentage == 50.0

    def test_full_coverage(self):
        session = make_test_session(concepts=["A", "B"])
        session.concepts_covered_set = {"A", "B"}
        assert session.coverage_percentage == 100.0

    def test_extra_concepts_capped(self):
        """Covering concepts not in the plan should not push above 100%."""
        session = make_test_session(concepts=["A", "B"])
        session.concepts_covered_set = {"A", "B", "X"}
        assert session.coverage_percentage == 100.0


class TestExamQuestionModel:
    """Tests for ExamQuestion validation."""

    def test_valid_exam_question(self):
        q = ExamQuestion(
            question_idx=0,
            question_text="What is 1/2 + 1/4?",
            concept="Adding fractions",
            difficulty="medium",
            question_type="procedural",
            expected_answer="3/4",
        )
        assert q.question_idx == 0
        assert q.difficulty == "medium"
        assert q.question_type == "procedural"
        assert q.student_answer is None
        assert q.result is None
        assert q.feedback == ""

    def test_exam_question_with_result(self):
        q = ExamQuestion(
            question_idx=1,
            question_text="Define numerator",
            concept="Numerator",
            difficulty="easy",
            question_type="conceptual",
            expected_answer="Top number in a fraction",
            student_answer="The top part",
            result="correct",
            feedback="Good job!",
        )
        assert q.result == "correct"
        assert q.student_answer == "The top part"

    def test_exam_question_invalid_difficulty_rejected(self):
        with pytest.raises(Exception):
            ExamQuestion(
                question_idx=0,
                question_text="Q",
                concept="C",
                difficulty="super_hard",  # invalid literal
                question_type="conceptual",
                expected_answer="A",
            )

    def test_exam_question_invalid_result_rejected(self):
        with pytest.raises(Exception):
            ExamQuestion(
                question_idx=0,
                question_text="Q",
                concept="C",
                difficulty="easy",
                question_type="conceptual",
                expected_answer="A",
                result="almost",  # invalid literal
            )


class TestExamFeedbackModel:
    """Tests for ExamFeedback validation."""

    def test_valid_exam_feedback(self):
        fb = ExamFeedback(
            score=5,
            total=7,
            percentage=71.4,
            strengths=["Good at fractions"],
            weak_areas=["Decimals"],
            patterns=["Strong performance"],
            next_steps=["Practice decimals"],
        )
        assert fb.score == 5
        assert fb.total == 7
        assert fb.percentage == 71.4
        assert len(fb.strengths) == 1
        assert len(fb.weak_areas) == 1

    def test_empty_lists_valid(self):
        fb = ExamFeedback(
            score=0,
            total=0,
            percentage=0.0,
            strengths=[],
            weak_areas=[],
            patterns=[],
            next_steps=[],
        )
        assert fb.score == 0


# ===========================================================================
# 2. ScorecardService._get_revision_nudge tests
# ===========================================================================

class TestGetRevisionNudge:
    """Tests for ScorecardService._get_revision_nudge as a standalone method."""

    def _make_service(self):
        """Create a ScorecardService with a mocked DB session."""
        mock_db = MagicMock()
        return ScorecardService(mock_db)

    def test_returns_none_when_last_studied_is_none(self):
        svc = self._make_service()
        assert svc._get_revision_nudge(None, 80.0) is None

    def test_returns_none_when_coverage_below_20(self):
        svc = self._make_service()
        last_studied = (datetime.utcnow() - timedelta(days=31)).isoformat()
        assert svc._get_revision_nudge(last_studied, 10.0) is None

    def test_returns_none_when_coverage_exactly_20_is_not_below(self):
        """coverage >= 20 should not return None (edge case at boundary)."""
        svc = self._make_service()
        last_studied = (datetime.utcnow() - timedelta(days=31)).isoformat()
        result = svc._get_revision_nudge(last_studied, 20.0)
        assert result is not None

    def test_30_day_message(self):
        svc = self._make_service()
        last_studied = (datetime.utcnow() - timedelta(days=35)).isoformat()
        result = svc._get_revision_nudge(last_studied, 50.0)
        assert "month" in result.lower()

    def test_14_day_message(self):
        svc = self._make_service()
        last_studied = (datetime.utcnow() - timedelta(days=16)).isoformat()
        result = svc._get_revision_nudge(last_studied, 50.0)
        assert "revising" in result.lower() or "while" in result.lower()

    def test_7_day_with_high_coverage(self):
        svc = self._make_service()
        last_studied = (datetime.utcnow() - timedelta(days=8)).isoformat()
        result = svc._get_revision_nudge(last_studied, 60.0)
        assert result is not None
        assert "revisit" in result.lower() or "exam" in result.lower()

    def test_7_day_with_low_coverage_returns_none(self):
        """days_since >= 7 but coverage < 60 => no 7-day nudge."""
        svc = self._make_service()
        last_studied = (datetime.utcnow() - timedelta(days=8)).isoformat()
        result = svc._get_revision_nudge(last_studied, 40.0)
        assert result is None

    def test_recent_session_returns_none(self):
        """Less than 7 days => no nudge."""
        svc = self._make_service()
        last_studied = (datetime.utcnow() - timedelta(days=3)).isoformat()
        result = svc._get_revision_nudge(last_studied, 80.0)
        assert result is None

    def test_invalid_date_string_returns_none(self):
        svc = self._make_service()
        assert svc._get_revision_nudge("not-a-date", 80.0) is None


# ===========================================================================
# 3. ExamService tests
# ===========================================================================

class TestExamServiceGenerateQuestions:
    """Tests for ExamService.generate_questions."""

    def _make_exam_service(self):
        mock_llm = MagicMock()
        return ExamService(mock_llm), mock_llm

    def _make_valid_llm_response(self, count=3):
        questions = []
        for i in range(count):
            questions.append({
                "question_text": f"Question {i+1}?",
                "expected_answer": f"Answer {i+1}",
                "concept": f"Concept_{i}",
                "difficulty": "medium",
                "question_type": "conceptual",
            })
        return {"output_text": json.dumps({"questions": questions})}

    def test_generate_questions_success(self):
        svc, mock_llm = self._make_exam_service()
        mock_llm.call.return_value = self._make_valid_llm_response(count=5)

        session = make_test_session(mode="exam", concepts=["A", "B", "C"])
        result = svc.generate_questions(session, count=5)

        assert len(result) == 5
        assert all(isinstance(q, ExamQuestion) for q in result)
        assert result[0].question_idx == 0
        assert result[4].question_idx == 4
        mock_llm.call.assert_called_once()

    def test_generate_questions_no_topic_raises(self):
        svc, _ = self._make_exam_service()
        ctx = make_test_student_context()
        session = SessionState(student_context=ctx)  # no topic
        with pytest.raises(ExamGenerationError, match="No topic"):
            svc.generate_questions(session)

    def test_generate_questions_empty_response_raises(self):
        """LLM returns valid JSON but no questions array."""
        svc, mock_llm = self._make_exam_service()
        mock_llm.call.return_value = {"output_text": json.dumps({"questions": []})}

        session = make_test_session(mode="exam")
        with pytest.raises(ExamGenerationError, match="no questions"):
            svc.generate_questions(session)

    def test_generate_questions_retries_on_generic_exception(self):
        """First call raises a generic exception; retry with fewer questions succeeds."""
        svc, mock_llm = self._make_exam_service()

        # First call raises
        retry_response = {
            "output_text": json.dumps({
                "questions": [
                    {"question_text": "Q1?", "expected_answer": "A1",
                     "concept": "C1", "difficulty": "easy", "question_type": "conceptual"},
                    {"question_text": "Q2?", "expected_answer": "A2",
                     "concept": "C2", "difficulty": "medium", "question_type": "procedural"},
                ]
            })
        }

        mock_llm.call.side_effect = [RuntimeError("parse fail"), retry_response]

        session = make_test_session(mode="exam", concepts=["C1", "C2"])
        result = svc.generate_questions(session, count=7)

        assert len(result) == 2
        assert mock_llm.call.call_count == 2

    def test_generate_questions_raises_after_max_retries(self):
        """Both initial and retry calls fail => ExamGenerationError."""
        svc, mock_llm = self._make_exam_service()

        mock_llm.call.side_effect = RuntimeError("LLM down")

        session = make_test_session(mode="exam", concepts=["A"])
        with pytest.raises(ExamGenerationError, match="failed after retry"):
            svc.generate_questions(session, count=7)

    def test_generate_questions_caps_at_count(self):
        """If LLM returns more questions than requested, only count are used."""
        svc, mock_llm = self._make_exam_service()
        mock_llm.call.return_value = self._make_valid_llm_response(count=10)

        session = make_test_session(mode="exam", concepts=["A", "B"])
        result = svc.generate_questions(session, count=3)

        assert len(result) == 3

    def test_generate_questions_assigns_sequential_idx(self):
        svc, mock_llm = self._make_exam_service()
        mock_llm.call.return_value = self._make_valid_llm_response(count=4)

        session = make_test_session(mode="exam", concepts=["X"])
        result = svc.generate_questions(session, count=4)

        indices = [q.question_idx for q in result]
        assert indices == [0, 1, 2, 3]


# ===========================================================================
# 4. API endpoint tests (new learning-mode endpoints)
# ===========================================================================

# Reuse the same patterns from test_tutor_api_sessions.py

from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeUser:
    """Minimal user object for dependency override."""
    def __init__(self, user_id="test-user-1"):
        self.id = user_id


def _build_app_and_client():
    """
    Create a FastAPI app with the sessions router and fully mocked deps.
    Returns (app, client, mocks_dict).
    """
    from tutor.api.sessions import router
    from database import get_db
    from auth.middleware.auth_middleware import get_current_user, get_optional_user

    app = FastAPI()
    app.include_router(router)

    mock_db = MagicMock()

    def override_get_db():
        yield mock_db

    fake_user = _FakeUser()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_optional_user] = lambda: fake_user

    client = TestClient(app)
    return app, client, {"db": mock_db, "fake_user": fake_user}


def _make_session_row_mock(**kwargs):
    """Create a mock DB session row. Defaults to user_id=None (anonymous) for ownership checks."""
    mock_session = MagicMock()
    mock_session.user_id = kwargs.pop("user_id", None)
    for k, v in kwargs.items():
        setattr(mock_session, k, v)
    return mock_session


class TestGetResumableSession:
    """Tests for GET /sessions/resumable."""

    @patch("tutor.api.sessions.SessionRepository")
    def test_resumable_found(self, MockRepo):
        _, client, mocks = _build_app_and_client()

        # The endpoint queries the DB directly via db.query(SessionModel)
        # We need to mock db.query(...).filter(...).order_by(...).first()
        state = {
            "concepts_covered_set": ["Numerator", "Denominator"],
            "topic": {
                "study_plan": {"steps": [{"step_id": 1}, {"step_id": 2}, {"step_id": 3}]}
            },
        }
        mock_session = MagicMock()
        mock_session.id = "sess-abc"
        mock_session.state_json = json.dumps(state)
        mock_session.step_idx = 2

        mock_query = MagicMock()
        mocks["db"].query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = mock_session

        resp = client.get("/sessions/resumable?guideline_id=g1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-abc"
        assert data["current_step"] == 2
        assert data["total_steps"] == 3
        assert set(data["concepts_covered"]) == {"Numerator", "Denominator"}

    @patch("tutor.api.sessions.SessionRepository")
    def test_resumable_not_found(self, MockRepo):
        _, client, mocks = _build_app_and_client()

        mock_query = MagicMock()
        mocks["db"].query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = None

        resp = client.get("/sessions/resumable?guideline_id=g1")
        assert resp.status_code == 404

    @patch("tutor.api.sessions.SessionRepository")
    def test_resumable_missing_guideline_id(self, MockRepo):
        """guideline_id is a required query param; omitting it should return 422."""
        _, client, _ = _build_app_and_client()
        resp = client.get("/sessions/resumable")
        assert resp.status_code == 422


class TestPauseSession:
    """Tests for POST /sessions/{id}/pause."""

    @patch("tutor.api.sessions.SessionRepository")
    def test_pause_teach_me_success(self, MockRepo):
        _, client, mocks = _build_app_and_client()

        concepts = ["Numerator", "Denominator", "Comparing fractions"]
        topic = make_test_topic(concepts=concepts)
        ctx = make_test_student_context()
        session = create_session(topic=topic, student_context=ctx, mode="teach_me")
        session.concepts_covered_set = {"Numerator"}

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        session_row = _make_session_row_mock(
            mode="teach_me",
            state_json=session.model_dump_json(),
        )
        mock_repo.get_by_id.return_value = session_row

        resp = client.post("/sessions/sess-123/pause")
        assert resp.status_code == 200
        data = resp.json()
        assert "coverage" in data
        assert "concepts_covered" in data
        assert "message" in data
        assert "Numerator" in data["concepts_covered"]

    @patch("tutor.api.sessions.SessionRepository")
    def test_pause_non_teach_me_rejected(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        session_row = _make_session_row_mock(mode="exam")
        mock_repo.get_by_id.return_value = session_row

        resp = client.post("/sessions/sess-123/pause")
        assert resp.status_code == 400
        assert "Teach Me" in resp.json()["detail"] or "teach" in resp.json()["detail"].lower()

    @patch("tutor.api.sessions.SessionRepository")
    def test_pause_session_not_found(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = None

        resp = client.post("/sessions/nonexistent/pause")
        assert resp.status_code == 404


class TestResumeSession:
    """Tests for POST /sessions/{id}/resume."""

    @patch("tutor.api.sessions.SessionRepository")
    def test_resume_paused_session(self, MockRepo):
        _, client, mocks = _build_app_and_client()

        topic = make_test_topic()
        ctx = make_test_student_context()
        session = create_session(topic=topic, student_context=ctx, mode="teach_me")
        session.is_paused = True
        session.current_step = 2

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        session_row = _make_session_row_mock(
            is_paused=True,
            state_json=session.model_dump_json(),
        )
        mock_repo.get_by_id.return_value = session_row

        resp = client.post("/sessions/sess-abc/resume")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-abc"
        assert data["message"] == "Session resumed"
        assert data["current_step"] == 2

    @patch("tutor.api.sessions.SessionRepository")
    def test_resume_not_paused_rejected(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        session_row = _make_session_row_mock(is_paused=False)
        mock_repo.get_by_id.return_value = session_row

        resp = client.post("/sessions/sess-abc/resume")
        assert resp.status_code == 400
        assert "not paused" in resp.json()["detail"].lower()

    @patch("tutor.api.sessions.SessionRepository")
    def test_resume_session_not_found(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = None

        resp = client.post("/sessions/nonexistent/resume")
        assert resp.status_code == 404


class TestEndExam:
    """Tests for POST /sessions/{id}/end-exam."""

    @patch("tutor.api.sessions.SessionRepository")
    def test_end_exam_success(self, MockRepo):
        _, client, mocks = _build_app_and_client()

        topic = make_test_topic(concepts=["A", "B"])
        ctx = make_test_student_context()
        session = create_session(topic=topic, student_context=ctx, mode="exam")
        session.exam_questions = [
            ExamQuestion(
                question_idx=0, question_text="Q1?", concept="A",
                difficulty="easy", question_type="conceptual",
                expected_answer="A1", result="correct",
            ),
            ExamQuestion(
                question_idx=1, question_text="Q2?", concept="B",
                difficulty="medium", question_type="procedural",
                expected_answer="A2", result="incorrect",
            ),
        ]
        session.exam_total_correct = 1
        session.exam_finished = False

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        session_row = _make_session_row_mock(
            mode="exam",
            state_json=session.model_dump_json(),
        )
        mock_repo.get_by_id.return_value = session_row

        # The endpoint does TeacherOrchestrator.__new__(TeacherOrchestrator)
        # then calls orchestrator._build_exam_feedback(session).
        # Patch the orchestrator class so __new__ returns a mock.
        mock_feedback = ExamFeedback(
            score=1, total=2, percentage=50.0,
            strengths=["A"], weak_areas=["B"],
            patterns=["Mixed"], next_steps=["Practice B"],
        )
        with patch(
            "tutor.orchestration.orchestrator.TeacherOrchestrator._build_exam_feedback",
            return_value=mock_feedback,
        ):
            resp = client.post("/sessions/sess-exam/end-exam")

        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 1
        assert data["total"] == 2
        assert data["percentage"] == 50.0

    @patch("tutor.api.sessions.SessionRepository")
    def test_end_exam_not_exam_session(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        session_row = _make_session_row_mock(mode="teach_me")
        mock_repo.get_by_id.return_value = session_row

        resp = client.post("/sessions/sess-123/end-exam")
        assert resp.status_code == 400
        assert "exam" in resp.json()["detail"].lower()

    @patch("tutor.api.sessions.SessionRepository")
    def test_end_exam_already_finished(self, MockRepo):
        _, client, mocks = _build_app_and_client()

        topic = make_test_topic()
        ctx = make_test_student_context()
        session = create_session(topic=topic, student_context=ctx, mode="exam")
        session.exam_finished = True

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        session_row = _make_session_row_mock(
            mode="exam",
            state_json=session.model_dump_json(),
        )
        mock_repo.get_by_id.return_value = session_row

        resp = client.post("/sessions/sess-123/end-exam")
        assert resp.status_code == 400
        assert "already finished" in resp.json()["detail"].lower()

    @patch("tutor.api.sessions.SessionRepository")
    def test_end_exam_session_not_found(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = None

        resp = client.post("/sessions/nonexistent/end-exam")
        assert resp.status_code == 404
