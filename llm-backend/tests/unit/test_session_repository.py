"""Unit tests for shared/repositories/session_repository.py

Tests SessionRepository CRUD operations using an in-memory SQLite database.
All database interactions go through the db_session fixture from conftest.py.
"""

import json
import pytest

from shared.repositories.session_repository import SessionRepository
from shared.models.entities import Session as SessionModel
from shared.models.domain import TutorState, Student, StudentPrefs, Goal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(
    session_id: str = "test-1",
    mastery_score: float = 0.5,
    step_idx: int = 1,
) -> TutorState:
    """Build a minimal TutorState for testing."""
    return TutorState(
        session_id=session_id,
        student=Student(
            id="s1",
            grade=3,
            prefs=StudentPrefs(style="standard", lang="en"),
        ),
        goal=Goal(
            topic="Fractions",
            syllabus="CBSE",
            learning_objectives=["obj1"],
            guideline_id="g1",
        ),
        step_idx=step_idx,
        history=[],
        evidence=[],
        mastery_score=mastery_score,
        last_grading=None,
        next_action="present",
    )


# ===========================================================================
# Create & Retrieve
# ===========================================================================

class TestCreateAndRetrieve:
    def test_create_returns_session_model(self, db_session):
        repo = SessionRepository(db_session)
        state = _make_state(session_id="sess-1")
        result = repo.create("sess-1", state)

        assert isinstance(result, SessionModel)
        assert result.id == "sess-1"

    def test_create_persists_state_json(self, db_session):
        repo = SessionRepository(db_session)
        state = _make_state(session_id="sess-1")
        repo.create("sess-1", state)

        row = db_session.query(SessionModel).filter_by(id="sess-1").first()
        assert row is not None
        parsed = json.loads(row.state_json)
        assert parsed["session_id"] == "sess-1"
        assert parsed["mastery_score"] == 0.5

    def test_create_persists_student_json(self, db_session):
        repo = SessionRepository(db_session)
        state = _make_state(session_id="sess-1")
        repo.create("sess-1", state)

        row = db_session.query(SessionModel).filter_by(id="sess-1").first()
        student = json.loads(row.student_json)
        assert student["id"] == "s1"
        assert student["grade"] == 3

    def test_create_persists_goal_json(self, db_session):
        repo = SessionRepository(db_session)
        state = _make_state(session_id="sess-1")
        repo.create("sess-1", state)

        row = db_session.query(SessionModel).filter_by(id="sess-1").first()
        goal = json.loads(row.goal_json)
        assert goal["topic"] == "Fractions"
        assert goal["syllabus"] == "CBSE"

    def test_create_sets_mastery_and_step_idx(self, db_session):
        repo = SessionRepository(db_session)
        state = _make_state(mastery_score=0.75, step_idx=3)
        repo.create("sess-1", state)

        row = db_session.query(SessionModel).filter_by(id="sess-1").first()
        assert row.mastery == 0.75
        assert row.step_idx == 3

    def test_create_sets_timestamps(self, db_session):
        repo = SessionRepository(db_session)
        state = _make_state()
        result = repo.create("sess-1", state)

        assert result.created_at is not None
        assert result.updated_at is not None

    def test_get_by_id_returns_created_session(self, db_session):
        repo = SessionRepository(db_session)
        state = _make_state(session_id="sess-1")
        repo.create("sess-1", state)

        fetched = repo.get_by_id("sess-1")
        assert fetched is not None
        assert fetched.id == "sess-1"
        assert fetched.mastery == 0.5


# ===========================================================================
# Get non-existent
# ===========================================================================

class TestGetNonExistent:
    def test_get_by_id_returns_none_for_missing(self, db_session):
        repo = SessionRepository(db_session)
        result = repo.get_by_id("does-not-exist")
        assert result is None


# ===========================================================================
# Update
# ===========================================================================

class TestUpdate:
    def test_update_changes_state_json(self, db_session):
        repo = SessionRepository(db_session)
        state = _make_state(session_id="sess-1", mastery_score=0.5, step_idx=1)
        repo.create("sess-1", state)

        updated_state = _make_state(session_id="sess-1", mastery_score=0.9, step_idx=5)
        repo.update("sess-1", updated_state)

        fetched = repo.get_by_id("sess-1")
        assert fetched.mastery == 0.9
        assert fetched.step_idx == 5

        parsed = json.loads(fetched.state_json)
        assert parsed["mastery_score"] == 0.9
        assert parsed["step_idx"] == 5

    def test_update_changes_updated_at(self, db_session):
        repo = SessionRepository(db_session)
        state = _make_state(session_id="sess-1")
        created = repo.create("sess-1", state)
        original_updated_at = created.updated_at

        updated_state = _make_state(session_id="sess-1", mastery_score=0.9)
        repo.update("sess-1", updated_state)

        fetched = repo.get_by_id("sess-1")
        assert fetched.updated_at >= original_updated_at

    def test_update_nonexistent_does_nothing(self, db_session):
        """Updating a non-existent session should not raise."""
        repo = SessionRepository(db_session)
        state = _make_state(session_id="ghost")
        # Should not raise
        repo.update("ghost", state)


# ===========================================================================
# List all
# ===========================================================================

class TestListAll:
    def test_list_all_empty(self, db_session):
        repo = SessionRepository(db_session)
        result = repo.list_all()
        assert result == []

    def test_list_all_returns_multiple(self, db_session):
        repo = SessionRepository(db_session)
        repo.create("sess-1", _make_state(session_id="sess-1", mastery_score=0.3))
        repo.create("sess-2", _make_state(session_id="sess-2", mastery_score=0.7))

        result = repo.list_all()
        assert len(result) == 2

    def test_list_all_returns_dicts_with_expected_keys(self, db_session):
        repo = SessionRepository(db_session)
        repo.create("sess-1", _make_state(session_id="sess-1"))

        result = repo.list_all()
        assert len(result) == 1
        item = result[0]
        assert "session_id" in item
        assert "created_at" in item
        assert "mastery" in item
        assert "message_count" in item
        assert item["session_id"] == "sess-1"

    def test_list_all_ordered_by_created_at_desc(self, db_session):
        """Most recently created session should appear first."""
        repo = SessionRepository(db_session)
        repo.create("sess-1", _make_state(session_id="sess-1"))
        repo.create("sess-2", _make_state(session_id="sess-2"))
        repo.create("sess-3", _make_state(session_id="sess-3"))

        result = repo.list_all()
        assert len(result) == 3
        # The last created should be first in the list
        assert result[0]["session_id"] == "sess-3"

    def test_list_all_mastery_reflects_db_value(self, db_session):
        repo = SessionRepository(db_session)
        repo.create("sess-1", _make_state(session_id="sess-1", mastery_score=0.42))

        result = repo.list_all()
        assert result[0]["mastery"] == pytest.approx(0.42)


# ===========================================================================
# Delete
# ===========================================================================

class TestDelete:
    def test_delete_existing_returns_true(self, db_session):
        repo = SessionRepository(db_session)
        repo.create("sess-1", _make_state(session_id="sess-1"))

        assert repo.delete("sess-1") is True

    def test_delete_removes_from_db(self, db_session):
        repo = SessionRepository(db_session)
        repo.create("sess-1", _make_state(session_id="sess-1"))
        repo.delete("sess-1")

        assert repo.get_by_id("sess-1") is None

    def test_delete_nonexistent_returns_false(self, db_session):
        repo = SessionRepository(db_session)
        assert repo.delete("does-not-exist") is False
