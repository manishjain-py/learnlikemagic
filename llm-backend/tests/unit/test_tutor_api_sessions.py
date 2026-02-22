"""
Tests for tutor/api/sessions.py REST endpoints.

Covers: list_sessions, create_session, submit_step, get_summary,
        get_session_state, get_agent_logs.

WebSocket endpoint is excluded (too complex for unit tests).
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fake user object returned by auth dependency overrides.
# ---------------------------------------------------------------------------

class _FakeUser:
    """Minimal user object for dependency override."""
    def __init__(self, user_id="test-user-1"):
        self.id = user_id


# ---------------------------------------------------------------------------
# Build a minimal FastAPI app that includes only the sessions router,
# with all heavy dependencies mocked out.
# ---------------------------------------------------------------------------

def _build_app_and_client():
    """
    Create a FastAPI app with the sessions router and fully mocked deps.

    Returns (app, client, mocks_dict).
    """
    # Patch heavy imports BEFORE importing the router module
    mock_session_service_cls = MagicMock()
    mock_session_repo_cls = MagicMock()
    mock_agent_log_store_fn = MagicMock()
    mock_get_db = MagicMock()

    with patch.dict("sys.modules", {
        # Prevent config from trying to load .env / validate settings
    }):
        pass

    # We need to be careful: sessions.py imports at module level.
    # Re-import the router from tutor.api.sessions after patching deps.
    # The cleanest approach: import the already-loaded router and override deps.

    from tutor.api.sessions import router

    app = FastAPI()
    app.include_router(router)

    # Override the get_db dependency
    from database import get_db

    mock_db = MagicMock()

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    # Override auth dependencies so endpoints don't require real JWT tokens.
    from auth.middleware.auth_middleware import get_current_user, get_optional_user

    fake_user = _FakeUser()

    def override_get_current_user():
        return fake_user

    def override_get_optional_user():
        return fake_user

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_optional_user] = override_get_optional_user

    client = TestClient(app)
    return app, client, {
        "db": mock_db,
        "fake_user": fake_user,
        "session_service_cls": mock_session_service_cls,
        "session_repo_cls": mock_session_repo_cls,
        "agent_log_store_fn": mock_agent_log_store_fn,
    }


def _make_anonymous_session_mock(**kwargs):
    """Create a mock DB session row with user_id=None (anonymous) to pass ownership checks."""
    mock_session = MagicMock()
    mock_session.user_id = None
    for k, v in kwargs.items():
        setattr(mock_session, k, v)
    return mock_session


# ===========================================================================
# Tests
# ===========================================================================


class TestListSessions:

    @patch("tutor.api.sessions.SessionRepository")
    def test_list_sessions(self, MockRepo):
        _, client, mocks = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.list_by_user.return_value = [
            {"session_id": "s1", "created_at": "2024-01-01", "topic_name": "Math", "message_count": 5, "mastery": 0.7},
        ]

        resp = client.get("/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["sessions"][0]["session_id"] == "s1"
        mock_repo.list_by_user.assert_called_once_with(mocks["fake_user"].id)

    @patch("tutor.api.sessions.SessionRepository")
    def test_list_sessions_empty(self, MockRepo):
        _, client, mocks = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.list_by_user.return_value = []

        resp = client.get("/sessions")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestCreateSession:

    @patch("tutor.api.sessions.SessionService")
    def test_create_session_success(self, MockService):
        _, client, _ = _build_app_and_client()

        mock_svc = MagicMock()
        MockService.return_value = mock_svc
        mock_svc.create_new_session.return_value = MagicMock(
            session_id="new-session",
            first_turn={"message": "Hello!", "hints": []},
            mode="teach_me",
        )

        payload = {
            "student": {"id": "s1", "grade": 3},
            "goal": {
                "topic": "Fractions",
                "syllabus": "CBSE Grade 3 Math",
                "learning_objectives": ["Compare fractions"],
            },
        }
        resp = client.post("/sessions", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "new-session"

    @patch("tutor.api.sessions.SessionService")
    def test_create_session_llm_exception(self, MockService):
        _, client, _ = _build_app_and_client()

        from shared.utils.exceptions import LLMProviderException

        mock_svc = MagicMock()
        MockService.return_value = mock_svc
        mock_svc.create_new_session.side_effect = LLMProviderException(RuntimeError("LLM down"))

        payload = {
            "student": {"id": "s1", "grade": 3},
            "goal": {
                "topic": "Fractions",
                "syllabus": "CBSE Grade 3 Math",
                "learning_objectives": ["Compare fractions"],
            },
        }
        resp = client.post("/sessions", json=payload)
        assert resp.status_code == 503

    @patch("tutor.api.sessions.SessionService")
    def test_create_session_generic_error(self, MockService):
        _, client, _ = _build_app_and_client()

        mock_svc = MagicMock()
        MockService.return_value = mock_svc
        mock_svc.create_new_session.side_effect = RuntimeError("unexpected")

        payload = {
            "student": {"id": "s1", "grade": 3},
            "goal": {
                "topic": "Fractions",
                "syllabus": "CBSE Grade 3 Math",
                "learning_objectives": ["Compare fractions"],
            },
        }
        resp = client.post("/sessions", json=payload)
        assert resp.status_code == 500


class TestSubmitStep:

    @patch("tutor.api.sessions.SessionService")
    @patch("tutor.api.sessions.SessionRepository")
    def test_submit_step_success(self, MockRepo, MockService):
        _, client, _ = _build_app_and_client()

        # Repo lookup must succeed (ownership check happens before SessionService)
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = _make_anonymous_session_mock()

        mock_svc = MagicMock()
        MockService.return_value = mock_svc
        mock_svc.process_step.return_value = MagicMock(
            next_turn={"message": "Correct!"},
            routing="Advance",
            last_grading=None,
        )

        resp = client.post(
            "/sessions/sess-123/step",
            json={"student_reply": "3/4"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["routing"] == "Advance"

    @patch("tutor.api.sessions.SessionRepository")
    def test_submit_step_session_not_found(self, MockRepo):
        _, client, _ = _build_app_and_client()

        # The endpoint now checks the repo directly before calling SessionService
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = None

        resp = client.post(
            "/sessions/sess-999/step",
            json={"student_reply": "answer"},
        )
        assert resp.status_code == 404

    @patch("tutor.api.sessions.SessionService")
    @patch("tutor.api.sessions.SessionRepository")
    def test_submit_step_generic_error(self, MockRepo, MockService):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = _make_anonymous_session_mock()

        mock_svc = MagicMock()
        MockService.return_value = mock_svc
        mock_svc.process_step.side_effect = RuntimeError("boom")

        resp = client.post(
            "/sessions/sess-123/step",
            json={"student_reply": "answer"},
        )
        assert resp.status_code == 500


class TestGetSummary:

    @patch("tutor.api.sessions.SessionService")
    @patch("tutor.api.sessions.SessionRepository")
    def test_get_summary_success(self, MockRepo, MockService):
        _, client, _ = _build_app_and_client()

        # Repo lookup must succeed (ownership check happens before SessionService)
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = _make_anonymous_session_mock()

        mock_svc = MagicMock()
        MockService.return_value = mock_svc
        mock_svc.get_summary.return_value = MagicMock(
            steps_completed=5,
            mastery_score=0.8,
            misconceptions_seen=["wrong denom"],
            suggestions=["Practice more"],
        )

        resp = client.get("/sessions/sess-123/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["steps_completed"] == 5
        assert data["mastery_score"] == 0.8

    @patch("tutor.api.sessions.SessionRepository")
    def test_get_summary_not_found(self, MockRepo):
        _, client, _ = _build_app_and_client()

        # The endpoint now checks the repo directly before calling SessionService
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = None

        resp = client.get("/sessions/sess-bad/summary")
        assert resp.status_code == 404


class TestGetSessionState:

    @patch("tutor.api.sessions.SessionRepository")
    def test_found(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_session = _make_anonymous_session_mock(
            state_json=json.dumps({"session_id": "s1", "step": 3}),
        )
        mock_repo.get_by_id.return_value = mock_session

        resp = client.get("/sessions/s1")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "s1"

    @patch("tutor.api.sessions.SessionRepository")
    def test_not_found(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = None

        resp = client.get("/sessions/nonexistent")
        assert resp.status_code == 404


class TestGetAgentLogs:

    @patch("tutor.api.sessions.get_agent_log_store")
    @patch("tutor.api.sessions.SessionRepository")
    def test_logs_found(self, MockRepo, mock_log_store_fn):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = _make_anonymous_session_mock()

        from datetime import datetime

        mock_log_entry = MagicMock()
        mock_log_entry.timestamp = datetime(2024, 1, 1, 12, 0, 0)
        mock_log_entry.turn_id = "turn-1"
        mock_log_entry.agent_name = "master_tutor"
        mock_log_entry.event_type = "generate"
        mock_log_entry.input_summary = "student said hello"
        mock_log_entry.output = {"msg": "hi"}
        mock_log_entry.reasoning = "greeting"
        mock_log_entry.duration_ms = 150
        mock_log_entry.prompt = "system prompt"
        mock_log_entry.model = "gpt-4o"

        mock_store = MagicMock()
        mock_log_store_fn.return_value = mock_store
        mock_store.get_recent_logs.return_value = [mock_log_entry]

        resp = client.get("/sessions/s1/agent-logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "s1"
        assert data["total_count"] == 1
        assert data["logs"][0]["agent_name"] == "master_tutor"

    @patch("tutor.api.sessions.get_agent_log_store")
    @patch("tutor.api.sessions.SessionRepository")
    def test_logs_with_filters(self, MockRepo, mock_log_store_fn):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = _make_anonymous_session_mock()

        mock_store = MagicMock()
        mock_log_store_fn.return_value = mock_store
        mock_store.get_logs.return_value = []

        resp = client.get("/sessions/s1/agent-logs?turn_id=t1&agent_name=safety")
        assert resp.status_code == 200
        mock_store.get_logs.assert_called_once_with("s1", turn_id="t1", agent_name="safety")

    @patch("tutor.api.sessions.SessionRepository")
    def test_logs_session_not_found(self, MockRepo):
        _, client, _ = _build_app_and_client()

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_by_id.return_value = None

        resp = client.get("/sessions/bad-id/agent-logs")
        assert resp.status_code == 404
