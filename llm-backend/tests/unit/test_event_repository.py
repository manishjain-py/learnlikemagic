"""Unit tests for shared/repositories/event_repository.py

Tests EventRepository log/query operations using an in-memory SQLite database.
All database interactions go through the db_session fixture from conftest.py.
"""

import json
import pytest

from shared.repositories.event_repository import EventRepository
from shared.models.entities import Event, Session as SessionModel
from shared.models.domain import TutorState, Student, StudentPrefs, Goal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_session(db_session, session_id: str = "sess-1") -> None:
    """Insert a parent session row so FK constraints are satisfied."""
    state = TutorState(
        session_id=session_id,
        student=Student(id="s1", grade=3, prefs=StudentPrefs(style="standard", lang="en")),
        goal=Goal(topic="Fractions", syllabus="CBSE", learning_objectives=["obj1"], guideline_id="g1"),
        step_idx=0,
        history=[],
        evidence=[],
        mastery_score=0.0,
        last_grading=None,
        next_action="present",
    )
    row = SessionModel(
        id=session_id,
        student_json=state.student.model_dump_json(),
        goal_json=state.goal.model_dump_json(),
        state_json=state.model_dump_json(),
        mastery=0.0,
        step_idx=0,
    )
    db_session.add(row)
    db_session.commit()


# ===========================================================================
# Log event and retrieve
# ===========================================================================

class TestLogEvent:
    def test_log_returns_event_model(self, db_session):
        _seed_session(db_session, "sess-1")
        repo = EventRepository(db_session)

        event = repo.log("sess-1", "present", 0, {"message": "Hello!"})

        assert isinstance(event, Event)
        assert event.session_id == "sess-1"
        assert event.node == "present"
        assert event.step_idx == 0

    def test_log_persists_payload_as_json(self, db_session):
        _seed_session(db_session, "sess-1")
        repo = EventRepository(db_session)

        payload = {"message": "Hello!", "score": 0.85}
        event = repo.log("sess-1", "check", 1, payload)

        parsed = json.loads(event.payload_json)
        assert parsed["message"] == "Hello!"
        assert parsed["score"] == 0.85

    def test_log_generates_unique_id(self, db_session):
        _seed_session(db_session, "sess-1")
        repo = EventRepository(db_session)

        e1 = repo.log("sess-1", "present", 0, {"a": 1})
        e2 = repo.log("sess-1", "check", 1, {"b": 2})

        assert e1.id != e2.id

    def test_log_sets_created_at(self, db_session):
        _seed_session(db_session, "sess-1")
        repo = EventRepository(db_session)

        event = repo.log("sess-1", "present", 0, {})
        assert event.created_at is not None


# ===========================================================================
# get_for_session — ordered by step_idx
# ===========================================================================

class TestGetForSession:
    def test_returns_events_ordered_by_step_idx(self, db_session):
        _seed_session(db_session, "sess-1")
        repo = EventRepository(db_session)

        # Insert out of order
        repo.log("sess-1", "advance", 3, {"action": "advance"})
        repo.log("sess-1", "present", 0, {"action": "present"})
        repo.log("sess-1", "check", 1, {"action": "check"})
        repo.log("sess-1", "diagnose", 2, {"action": "diagnose"})

        events = repo.get_for_session("sess-1")

        assert len(events) == 4
        step_indices = [e.step_idx for e in events]
        assert step_indices == [0, 1, 2, 3]

    def test_returns_only_events_for_given_session(self, db_session):
        _seed_session(db_session, "sess-1")
        _seed_session(db_session, "sess-2")
        repo = EventRepository(db_session)

        repo.log("sess-1", "present", 0, {"for": "sess-1"})
        repo.log("sess-2", "present", 0, {"for": "sess-2"})
        repo.log("sess-1", "check", 1, {"for": "sess-1"})

        events = repo.get_for_session("sess-1")
        assert len(events) == 2
        assert all(e.session_id == "sess-1" for e in events)

    def test_returns_empty_list_for_unknown_session(self, db_session):
        repo = EventRepository(db_session)
        events = repo.get_for_session("no-such-session")
        assert events == []


# ===========================================================================
# get_by_node — filtering
# ===========================================================================

class TestGetByNode:
    def test_filters_by_node_name(self, db_session):
        _seed_session(db_session, "sess-1")
        repo = EventRepository(db_session)

        repo.log("sess-1", "present", 0, {})
        repo.log("sess-1", "check", 1, {})
        repo.log("sess-1", "present", 2, {})
        repo.log("sess-1", "diagnose", 3, {})

        present_events = repo.get_by_node("sess-1", "present")
        assert len(present_events) == 2
        assert all(e.node == "present" for e in present_events)

    def test_get_by_node_ordered_by_step_idx(self, db_session):
        _seed_session(db_session, "sess-1")
        repo = EventRepository(db_session)

        repo.log("sess-1", "check", 5, {})
        repo.log("sess-1", "check", 1, {})
        repo.log("sess-1", "check", 3, {})

        events = repo.get_by_node("sess-1", "check")
        step_indices = [e.step_idx for e in events]
        assert step_indices == [1, 3, 5]

    def test_get_by_node_returns_empty_for_missing_node(self, db_session):
        _seed_session(db_session, "sess-1")
        repo = EventRepository(db_session)

        repo.log("sess-1", "present", 0, {})

        events = repo.get_by_node("sess-1", "remediate")
        assert events == []

    def test_get_by_node_scoped_to_session(self, db_session):
        _seed_session(db_session, "sess-1")
        _seed_session(db_session, "sess-2")
        repo = EventRepository(db_session)

        repo.log("sess-1", "check", 0, {})
        repo.log("sess-2", "check", 0, {})

        events = repo.get_by_node("sess-1", "check")
        assert len(events) == 1
        assert events[0].session_id == "sess-1"
