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
            chapter="Fractions",
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
        assert goal["chapter"] == "Fractions"
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


# ===========================================================================
# Per-user listing & stats
# ===========================================================================

def _seed_user_session(
    db_session,
    *,
    session_id: str,
    user_id: str,
    subject: str = "Mathematics",
    mastery: float = 0.5,
    step_idx: int = 1,
) -> SessionModel:
    """Insert a SessionModel directly to test user-scoped queries."""
    repo = SessionRepository(db_session)
    state = _make_state(session_id=session_id, mastery_score=mastery, step_idx=step_idx)
    row = repo.create(session_id, state)
    row.user_id = user_id
    row.subject = subject
    db_session.commit()
    return row


class TestListByUser:
    def test_list_by_user_returns_only_users_sessions(self, db_session):
        repo = SessionRepository(db_session)
        _seed_user_session(db_session, session_id="s1", user_id="u1")
        _seed_user_session(db_session, session_id="s2", user_id="u2")

        rows = repo.list_by_user("u1")
        assert [r["session_id"] for r in rows] == ["s1"]

    def test_list_by_user_filters_by_subject(self, db_session):
        repo = SessionRepository(db_session)
        _seed_user_session(db_session, session_id="m1", user_id="u1", subject="Mathematics")
        _seed_user_session(db_session, session_id="s1", user_id="u1", subject="Science")

        math_only = repo.list_by_user("u1", subject="Mathematics")
        assert {r["session_id"] for r in math_only} == {"m1"}

    def test_list_by_user_paginates(self, db_session):
        repo = SessionRepository(db_session)
        for i in range(5):
            _seed_user_session(db_session, session_id=f"s{i}", user_id="u1")

        page1 = repo.list_by_user("u1", offset=0, limit=2)
        page2 = repo.list_by_user("u1", offset=2, limit=2)
        assert len(page1) == 2
        assert len(page2) == 2
        # No overlap between pages
        assert {r["session_id"] for r in page1} & {r["session_id"] for r in page2} == set()

    def test_list_by_user_includes_step_and_mode(self, db_session):
        repo = SessionRepository(db_session)
        _seed_user_session(db_session, session_id="s1", user_id="u1", step_idx=4)

        rows = repo.list_by_user("u1")
        assert rows[0]["step_idx"] == 4
        # Default mode is "teach_me" via _make_state — coverage key set up
        assert "mode" in rows[0]


class TestCountByUser:
    def test_count_total(self, db_session):
        repo = SessionRepository(db_session)
        _seed_user_session(db_session, session_id="a", user_id="u1")
        _seed_user_session(db_session, session_id="b", user_id="u1")
        _seed_user_session(db_session, session_id="c", user_id="u2")

        assert repo.count_by_user("u1") == 2
        assert repo.count_by_user("u2") == 1
        assert repo.count_by_user("nobody") == 0

    def test_count_filtered_by_subject(self, db_session):
        repo = SessionRepository(db_session)
        _seed_user_session(db_session, session_id="m", user_id="u1", subject="Mathematics")
        _seed_user_session(db_session, session_id="s", user_id="u1", subject="Science")

        assert repo.count_by_user("u1", subject="Mathematics") == 1


class TestGetUserStats:
    def test_no_sessions_returns_zeros(self, db_session):
        repo = SessionRepository(db_session)
        stats = repo.get_user_stats("nobody")
        assert stats == {
            "total_sessions": 0,
            "average_mastery": 0,
            "topics_covered": [],
            "total_steps": 0,
        }

    def test_aggregates_across_sessions(self, db_session):
        repo = SessionRepository(db_session)
        _seed_user_session(
            db_session, session_id="a", user_id="u1", mastery=0.6, step_idx=2,
            subject="Math",
        )
        _seed_user_session(
            db_session, session_id="b", user_id="u1", mastery=0.8, step_idx=3,
            subject="Science",
        )

        stats = repo.get_user_stats("u1")
        assert stats["total_sessions"] == 2
        assert stats["average_mastery"] == 0.7
        assert stats["total_steps"] == 5
        assert sorted(stats["topics_covered"]) == ["Math", "Science"]


class TestComputeCoverage:
    def test_zero_when_no_canonical_concepts(self):
        assert SessionRepository._compute_coverage({"a"}, []) == 0.0

    def test_full_coverage(self):
        result = SessionRepository._compute_coverage({"a", "b"}, ["a", "b"])
        assert result == 100.0

    def test_partial_coverage(self):
        result = SessionRepository._compute_coverage({"a"}, ["a", "b", "c", "d"])
        assert result == 25.0

    def test_extra_covered_concepts_dont_count(self):
        # Concepts the student covered but that aren't canonical don't change %.
        result = SessionRepository._compute_coverage({"a", "z"}, ["a", "b"])
        assert result == 50.0


class TestListAllWithMalformedJson:
    def test_unparseable_state_falls_back_to_empty(self, db_session):
        repo = SessionRepository(db_session)
        # Insert a row with garbage state_json to exercise the JSON guard.
        row = SessionModel(
            id="bad",
            student_json="{}",
            goal_json="{}",
            state_json="not-valid-json",
            mastery=0.0,
            step_idx=0,
        )
        db_session.add(row)
        db_session.commit()

        results = repo.list_all()
        match = next(r for r in results if r["session_id"] == "bad")
        # No topic_name (state was unparseable) and message_count is 0.
        assert match["topic_name"] is None
        assert match["message_count"] == 0
