"""
Tests for exam lifecycle, navigation overhaul & past exam review.

Covers:
- Duplicate exam creation guard (409 conflict semantics)
- GET /sessions/{id}/exam-review rejects unfinished exams
- GET /sessions/guideline/{id} behavior and filtering
- HTTPException pass-through in create_session endpoint
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeUser:
    def __init__(self, user_id="test-user-1"):
        self.id = user_id


def _build_app_and_client():
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


def _make_topic():
    return Topic(
        topic_id="math_fractions_basics",
        topic_name="Fractions - Basics",
        subject="Mathematics",
        grade_level=3,
        guidelines=TopicGuidelines(
            learning_objectives=["Understand fractions"],
            common_misconceptions=["Denominator confusion"],
            teaching_approach="Use visuals",
        ),
        study_plan=StudyPlan(
            steps=[
                StudyPlanStep(step_id=1, type="explain", concept="Fractions", content_hint="Pizza"),
            ]
        ),
    )


def _make_exam_session(finished=True, num_questions=3):
    """Build a SessionState in exam mode with optionally finished state."""
    topic = _make_topic()
    ctx = StudentContext(grade=3, board="CBSE", language_level="simple")
    session = create_session(topic=topic, student_context=ctx, mode="exam")
    session.session_id = "exam-session-1"
    session.exam_questions = [
        ExamQuestion(
            question_idx=i,
            question_text=f"Q{i+1}?",
            concept="Fractions",
            difficulty="easy",
            question_type="conceptual",
            expected_answer=f"A{i+1}",
            student_answer=f"A{i+1}" if finished else (f"A{i+1}" if i == 0 else None),
            result="correct" if finished else ("correct" if i == 0 else None),
            score=1.0 if finished else (1.0 if i == 0 else 0.0),
            marks_rationale="Good" if finished else ("Good" if i == 0 else ""),
        )
        for i in range(num_questions)
    ]
    session.exam_finished = finished
    session.exam_current_question_idx = num_questions if finished else 1
    if finished:
        session.exam_feedback = ExamFeedback(
            score=float(num_questions),
            total=num_questions,
            percentage=100.0,
            strengths=["Basics"],
            weak_areas=[],
            patterns=[],
            next_steps=["Try harder topics"],
        )
    return session


def _make_session_db_row(session_state, user_id="test-user-1"):
    """Create a mock DB row from a SessionState."""
    row = MagicMock()
    row.id = session_state.session_id
    row.user_id = user_id
    row.state_json = session_state.model_dump_json()
    row.mode = session_state.mode
    row.created_at = MagicMock()
    row.created_at.isoformat.return_value = "2026-02-27T10:00:00"
    row.state_version = 1
    return row


def _make_anonymous_session_mock(**kwargs):
    mock_session = MagicMock()
    mock_session.user_id = None
    for k, v in kwargs.items():
        setattr(mock_session, k, v)
    return mock_session


# ===========================================================================
# Tests: Duplicate exam creation guard (409 conflict)
# ===========================================================================


class TestDuplicateExamGuard:

    @patch("tutor.api.sessions.SessionService")
    def test_create_exam_returns_409_when_incomplete_exists(self, MockService):
        """Creating an exam when one already exists should return 409 with session_id."""
        _, client, _ = _build_app_and_client()

        mock_svc = MagicMock()
        MockService.return_value = mock_svc
        mock_svc.create_new_session.side_effect = HTTPException(
            status_code=409,
            detail={
                "message": "An incomplete exam already exists for this topic",
                "existing_session_id": "existing-exam-123",
            },
        )

        payload = {
            "student": {"id": "s1", "grade": 3},
            "goal": {
                "topic": "Fractions",
                "syllabus": "CBSE Grade 3 Math",
                "learning_objectives": ["Test fractions"],
                "guideline_id": "g1",
            },
            "mode": "exam",
        }
        resp = client.post("/sessions", json=payload)

        assert resp.status_code == 409
        data = resp.json()
        assert data["detail"]["existing_session_id"] == "existing-exam-123"

    @patch("tutor.api.sessions.SessionService")
    def test_create_exam_409_not_swallowed_as_500(self, MockService):
        """Regression: HTTPException must NOT be caught by generic Exception handler."""
        _, client, _ = _build_app_and_client()

        mock_svc = MagicMock()
        MockService.return_value = mock_svc
        mock_svc.create_new_session.side_effect = HTTPException(
            status_code=409,
            detail="conflict",
        )

        payload = {
            "student": {"id": "s1", "grade": 3},
            "goal": {
                "topic": "Fractions",
                "syllabus": "CBSE Grade 3 Math",
                "learning_objectives": ["Test"],
                "guideline_id": "g1",
            },
            "mode": "exam",
        }
        resp = client.post("/sessions", json=payload)
        assert resp.status_code == 409  # NOT 500

    @patch("tutor.services.session_service.get_settings")
    @patch("tutor.services.session_service.convert_guideline_to_topic")
    def test_service_guard_finds_incomplete_exam(self, mock_convert, mock_settings):
        """SessionService.create_new_session raises HTTPException when incomplete exam exists."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )
        mock_convert.return_value = _make_topic()

        from tutor.services.session_service import SessionService
        from shared.models.schemas import CreateSessionRequest
        from shared.models.domain import Student, Goal

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        svc.guideline_repo.get_guideline_by_id.return_value = MagicMock(subject="Math")

        # Simulate an incomplete exam already exists
        svc.session_repo.list_by_guideline.return_value = [
            {"session_id": "existing-exam-99", "is_complete": False, "mode": "exam"},
        ]

        request = CreateSessionRequest(
            student=Student(id="s1", grade=3),
            goal=Goal(
                topic="Fractions",
                syllabus="CBSE",
                learning_objectives=["Test"],
                guideline_id="g1",
            ),
            mode="exam",
        )

        with pytest.raises(HTTPException) as exc_info:
            svc.create_new_session(request, user_id="test-user-1")

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["existing_session_id"] == "existing-exam-99"

    @patch("tutor.services.session_service.get_settings")
    @patch("tutor.services.session_service.convert_guideline_to_topic")
    def test_service_guard_allows_when_no_incomplete(self, mock_convert, mock_settings):
        """Creating an exam when none exists should proceed normally."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )
        mock_convert.return_value = _make_topic()

        from tutor.services.session_service import SessionService
        from shared.models.schemas import CreateSessionRequest
        from shared.models.domain import Student, Goal

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        svc.guideline_repo.get_guideline_by_id.return_value = MagicMock(subject="Math")
        svc.db.query.return_value.filter.return_value.first.return_value = None

        # Only completed exams exist
        svc.session_repo.list_by_guideline.return_value = [
            {"session_id": "old-exam", "is_complete": True, "mode": "exam"},
        ]

        request = CreateSessionRequest(
            student=Student(id="s1", grade=3),
            goal=Goal(
                topic="Fractions",
                syllabus="CBSE",
                learning_objectives=["Test"],
                guideline_id="g1",
            ),
            mode="exam",
        )

        # Mock exam generation and welcome
        with patch("asyncio.run", return_value="Exam time!"):
            with patch("tutor.services.exam_service.ExamService") as MockExamSvc:
                MockExamSvc.return_value.generate_questions.return_value = []
                response = svc.create_new_session(request, user_id="test-user-1")

        assert response.session_id is not None
        assert response.mode == "exam"


# ===========================================================================
# Tests: GET /sessions/{id}/exam-review
# ===========================================================================


class TestExamReview:

    @patch("tutor.api.sessions.SessionRepository")
    def test_exam_review_finished_returns_questions(self, MockRepo):
        """Finished exam review returns full question details."""
        _, client, mocks = _build_app_and_client()

        session = _make_exam_session(finished=True, num_questions=2)
        db_row = _make_session_db_row(session)

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = db_row

        resp = client.get("/sessions/exam-session-1/exam-review")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "exam-session-1"
        assert len(data["questions"]) == 2
        assert data["questions"][0]["score"] == 1.0
        assert data["questions"][0]["marks_rationale"] == "Good"
        assert data["exam_feedback"]["percentage"] == 100.0

    @patch("tutor.api.sessions.SessionRepository")
    def test_exam_review_unfinished_returns_403(self, MockRepo):
        """Unfinished exam must NOT expose answer data."""
        _, client, mocks = _build_app_and_client()

        session = _make_exam_session(finished=False, num_questions=3)
        db_row = _make_session_db_row(session)

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = db_row

        resp = client.get("/sessions/exam-session-1/exam-review")
        assert resp.status_code == 403
        assert "not yet finished" in resp.json()["detail"].lower()

    @patch("tutor.api.sessions.SessionRepository")
    def test_exam_review_not_exam_returns_400(self, MockRepo):
        """Non-exam session returns 400."""
        _, client, _ = _build_app_and_client()

        topic = _make_topic()
        ctx = StudentContext(grade=3, board="CBSE", language_level="simple")
        session = create_session(topic=topic, student_context=ctx, mode="teach_me")
        session.session_id = "teach-session-1"
        db_row = _make_session_db_row(session)

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = db_row

        resp = client.get("/sessions/teach-session-1/exam-review")
        assert resp.status_code == 400

    @patch("tutor.api.sessions.SessionRepository")
    def test_exam_review_not_found(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = None

        resp = client.get("/sessions/nonexistent/exam-review")
        assert resp.status_code == 404

    @patch("tutor.api.sessions.SessionRepository")
    def test_exam_review_wrong_user_returns_403(self, MockRepo):
        """Session owned by different user returns 403."""
        _, client, mocks = _build_app_and_client()

        session = _make_exam_session(finished=True)
        db_row = _make_session_db_row(session, user_id="other-user")

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = db_row

        resp = client.get("/sessions/exam-session-1/exam-review")
        assert resp.status_code == 403


# ===========================================================================
# Tests: GET /sessions/guideline/{guideline_id}
# ===========================================================================


class TestGuidelineSessions:

    @patch("tutor.api.sessions.SessionRepository")
    def test_guideline_sessions_returns_list(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.list_by_guideline.return_value = [
            {
                "session_id": "s1",
                "mode": "exam",
                "created_at": "2026-02-27T10:00:00",
                "is_complete": True,
                "exam_finished": True,
                "exam_score": 2.5,
                "exam_total": 3,
                "exam_answered": 3,
                "coverage": None,
            },
            {
                "session_id": "s2",
                "mode": "teach_me",
                "created_at": "2026-02-26T10:00:00",
                "is_complete": False,
                "exam_finished": False,
                "exam_score": None,
                "exam_total": None,
                "exam_answered": None,
                "coverage": 45.0,
            },
        ]

        resp = client.get("/sessions/guideline/g1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 2
        assert data["sessions"][0]["session_id"] == "s1"
        assert data["sessions"][1]["coverage"] == 45.0

    @patch("tutor.api.sessions.SessionRepository")
    def test_guideline_sessions_with_mode_filter(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.list_by_guideline.return_value = []

        resp = client.get("/sessions/guideline/g1?mode=exam")
        assert resp.status_code == 200
        mock_repo.list_by_guideline.assert_called_once_with(
            user_id="test-user-1",
            guideline_id="g1",
            mode="exam",
            finished_only=False,
        )

    @patch("tutor.api.sessions.SessionRepository")
    def test_guideline_sessions_finished_only(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.list_by_guideline.return_value = []

        resp = client.get("/sessions/guideline/g1?finished_only=true")
        assert resp.status_code == 200
        mock_repo.list_by_guideline.assert_called_once_with(
            user_id="test-user-1",
            guideline_id="g1",
            mode=None,
            finished_only=True,
        )

    @patch("tutor.api.sessions.SessionRepository")
    def test_guideline_sessions_empty(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.list_by_guideline.return_value = []

        resp = client.get("/sessions/guideline/g1")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []
