"""Unit tests for tutor/services/scorecard_service.py

Tests scorecard aggregation logic using an in-memory SQLite database.
All database interactions go through the db_session fixture from conftest.py.
"""

import json
import uuid
from datetime import datetime, timedelta

import pytest

from shared.models.entities import Session as SessionModel, TeachingGuideline, User
from tutor.services.scorecard_service import ScorecardService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "test-user-1"


def _create_user(db, user_id=USER_ID):
    """Create a user record."""
    user = User(
        id=user_id,
        cognito_sub=f"cognito-{user_id}",
        auth_provider="email",
    )
    db.add(user)
    db.commit()
    return user


def _create_guideline(
    db,
    guideline_id="g1",
    subject="Mathematics",
    topic="Fractions",
    subtopic="Comparing Fractions",
    topic_key=None,
    subtopic_key=None,
    topic_title=None,
    subtopic_title=None,
):
    """Create a teaching guideline record."""
    g = TeachingGuideline(
        id=guideline_id,
        country="India",
        board="CBSE",
        grade=3,
        subject=subject,
        topic=topic,
        subtopic=subtopic,
        guideline="Test guideline content",
        topic_key=topic_key,
        subtopic_key=subtopic_key,
        topic_title=topic_title,
        subtopic_title=subtopic_title,
    )
    db.add(g)
    db.commit()
    return g


def _create_session(
    db,
    user_id=USER_ID,
    subject="Mathematics",
    topic_name="Fractions - Comparing Fractions",
    guideline_id="g1",
    mastery=0.75,
    mastery_estimates=None,
    misconceptions=None,
    created_at=None,
    session_id=None,
):
    """Create a session with realistic state_json for scorecard testing."""
    if mastery_estimates is None:
        mastery_estimates = {"concept_a": 0.8, "concept_b": 0.7}
    if misconceptions is None:
        misconceptions = []
    if created_at is None:
        created_at = datetime.utcnow()
    if session_id is None:
        session_id = f"sess-{uuid.uuid4().hex[:8]}"

    state = {
        "session_id": session_id,
        "topic": {
            "topic_id": guideline_id,
            "topic_name": topic_name,
            "subject": subject,
            "grade_level": 3,
        },
        "mastery_estimates": mastery_estimates,
        "misconceptions": misconceptions,
        "weak_areas": [],
    }

    # Minimal student/goal JSON
    student_json = json.dumps({"id": user_id, "grade": 3})
    goal_json = json.dumps({"topic": topic_name, "guideline_id": guideline_id})

    session = SessionModel(
        id=session_id,
        student_json=student_json,
        goal_json=goal_json,
        state_json=json.dumps(state),
        mastery=mastery,
        step_idx=3,
        user_id=user_id,
        subject=subject,
        created_at=created_at,
    )
    db.add(session)
    db.commit()
    return session


# ===========================================================================
# Empty Scorecard
# ===========================================================================

class TestScorecardEmpty:
    """Test scorecard for users with no sessions."""

    def test_empty_scorecard_returns_zeros(self, db_session):
        _create_user(db_session)
        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert result["overall_score"] == 0
        assert result["total_sessions"] == 0
        assert result["total_topics_studied"] == 0
        assert result["subjects"] == []
        assert result["strengths"] == []
        assert result["needs_practice"] == []

    def test_nonexistent_user_returns_empty(self, db_session):
        service = ScorecardService(db_session)
        result = service.get_scorecard("nonexistent-user")

        assert result["overall_score"] == 0
        assert result["total_sessions"] == 0


# ===========================================================================
# Single Session
# ===========================================================================

class TestScorecardSingleSession:
    """Test scorecard with one session."""

    def test_single_session_creates_one_subject(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mastery=0.8)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert result["total_sessions"] == 1
        assert len(result["subjects"]) == 1
        assert result["subjects"][0]["subject"] == "Mathematics"

    def test_single_session_mastery_propagates(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mastery=0.8)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subject = result["subjects"][0]
        assert subject["score"] == 0.8
        assert subject["topics"][0]["score"] == 0.8
        assert subject["topics"][0]["subtopics"][0]["score"] == 0.8

    def test_single_session_concepts_extracted(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mastery=0.85,
            mastery_estimates={"addition": 0.9, "carrying": 0.8},
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["concepts"]["addition"] == 0.9
        assert subtopic["concepts"]["carrying"] == 0.8

    def test_single_session_misconceptions_extracted(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mastery=0.6,
            misconceptions=[
                {"concept": "fractions", "description": "Larger denominator = larger fraction", "resolved": False},
            ],
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert len(subtopic["misconceptions"]) == 1
        assert subtopic["misconceptions"][0]["description"] == "Larger denominator = larger fraction"
        assert subtopic["misconceptions"][0]["resolved"] is False


# ===========================================================================
# Multiple Sessions
# ===========================================================================

class TestScorecardMultipleSessions:
    """Test scorecard aggregation across sessions."""

    def test_latest_session_per_subtopic_wins(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()

        # Older session with lower mastery
        _create_session(db_session, mastery=0.5, created_at=now - timedelta(days=2))
        # Newer session with higher mastery
        _create_session(db_session, mastery=0.9, created_at=now)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["score"] == 0.9
        assert subtopic["session_count"] == 2

    def test_topic_score_averages_subtopics(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", subtopic="Comparing Fractions",
                          subtopic_key="comparing-fractions")
        _create_guideline(db_session, guideline_id="g2", subtopic="Adding Fractions",
                          subtopic_key="adding-fractions")

        _create_session(db_session, guideline_id="g1",
                        topic_name="Fractions - Comparing Fractions", mastery=0.9)
        _create_session(db_session, guideline_id="g2",
                        topic_name="Fractions - Adding Fractions", mastery=0.7)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        topic = result["subjects"][0]["topics"][0]
        assert topic["score"] == 0.8  # avg of 0.9 and 0.7

    def test_subject_score_averages_topics(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", topic="Fractions",
                          subtopic="Comparing", topic_key="fractions", subtopic_key="comparing")
        _create_guideline(db_session, guideline_id="g2", topic="Geometry",
                          subtopic="Shapes", topic_key="geometry", subtopic_key="shapes")

        _create_session(db_session, guideline_id="g1",
                        topic_name="Fractions - Comparing", mastery=0.9)
        _create_session(db_session, guideline_id="g2",
                        topic_name="Geometry - Shapes", mastery=0.7)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert result["subjects"][0]["score"] == 0.8  # avg of 0.9 and 0.7

    def test_overall_score_averages_subjects(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", subject="Mathematics",
                          topic="Fractions", subtopic="Comparing",
                          topic_key="fractions", subtopic_key="comparing")
        _create_guideline(db_session, guideline_id="g2", subject="Science",
                          topic="Plants", subtopic="Parts",
                          topic_key="plants", subtopic_key="parts")

        _create_session(db_session, guideline_id="g1", subject="Mathematics",
                        topic_name="Fractions - Comparing", mastery=0.9)
        _create_session(db_session, guideline_id="g2", subject="Science",
                        topic_name="Plants - Parts", mastery=0.7)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert result["overall_score"] == 0.8  # avg of 0.9 and 0.7
        assert len(result["subjects"]) == 2

    def test_multiple_subjects_grouped_correctly(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", subject="Mathematics",
                          topic="Numbers", subtopic="Addition",
                          topic_key="numbers", subtopic_key="addition")
        _create_guideline(db_session, guideline_id="g2", subject="Science",
                          topic="Plants", subtopic="Parts",
                          topic_key="plants", subtopic_key="parts")

        _create_session(db_session, guideline_id="g1", subject="Mathematics",
                        topic_name="Numbers - Addition", mastery=0.85)
        _create_session(db_session, guideline_id="g2", subject="Science",
                        topic_name="Plants - Parts", mastery=0.72)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subject_names = [s["subject"] for s in result["subjects"]]
        assert "Mathematics" in subject_names
        assert "Science" in subject_names

    def test_zero_score_included_in_averages(self, db_session):
        """Regression: subtopics with score 0.0 must count in averages, not be excluded."""
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", subtopic="Easy",
                          subtopic_key="easy", topic_key="t")
        _create_guideline(db_session, guideline_id="g2", subtopic="Hard",
                          subtopic_key="hard", topic_key="t")

        _create_session(db_session, guideline_id="g1",
                        topic_name="Fractions - Easy", mastery=1.0)
        # mastery_estimates={} avoids the `not overall_mastery` fallback path
        _create_session(db_session, guideline_id="g2",
                        topic_name="Fractions - Hard", mastery=0.0,
                        mastery_estimates={})

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        # Topic average: (1.0 + 0.0) / 2 = 0.5 — NOT 1.0
        topic = result["subjects"][0]["topics"][0]
        assert topic["score"] == 0.5

        # Subject average should propagate the same
        assert result["subjects"][0]["score"] == 0.5

        # Overall average should propagate the same
        assert result["overall_score"] == 0.5

    def test_trend_data_includes_all_sessions(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()

        _create_session(db_session, mastery=0.5, created_at=now - timedelta(days=2))
        _create_session(db_session, mastery=0.7, created_at=now - timedelta(days=1))
        _create_session(db_session, mastery=0.9, created_at=now)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        trend = result["subjects"][0]["trend"]
        assert len(trend) == 3
        scores = [t["score"] for t in trend]
        assert scores == [0.5, 0.7, 0.9]


# ===========================================================================
# Strengths & Weaknesses
# ===========================================================================

class TestScorecardStrengthsAndWeaknesses:
    """Test strengths/needs-practice identification."""

    def test_strengths_sorted_by_score_desc(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", subtopic="A",
                          subtopic_key="a", topic_key="t")
        _create_guideline(db_session, guideline_id="g2", subtopic="B",
                          subtopic_key="b", topic_key="t")

        _create_session(db_session, guideline_id="g1",
                        topic_name="Fractions - A", mastery=0.7)
        _create_session(db_session, guideline_id="g2",
                        topic_name="Fractions - B", mastery=0.9)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert result["strengths"][0]["score"] == 0.9
        assert result["strengths"][1]["score"] == 0.7

    def test_needs_practice_below_065_threshold(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", subtopic="Easy",
                          subtopic_key="easy", topic_key="t")
        _create_guideline(db_session, guideline_id="g2", subtopic="Hard",
                          subtopic_key="hard", topic_key="t")

        _create_session(db_session, guideline_id="g1",
                        topic_name="Fractions - Easy", mastery=0.9)
        _create_session(db_session, guideline_id="g2",
                        topic_name="Fractions - Hard", mastery=0.4)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert len(result["needs_practice"]) == 1
        assert result["needs_practice"][0]["subtopic"] == "Hard"
        assert result["needs_practice"][0]["score"] == 0.4

    def test_max_five_strengths(self, db_session):
        _create_user(db_session)
        for i in range(7):
            gid = f"g{i}"
            _create_guideline(db_session, guideline_id=gid, subtopic=f"Sub{i}",
                              subtopic_key=f"sub{i}", topic_key="t")
            _create_session(db_session, guideline_id=gid,
                            topic_name=f"Fractions - Sub{i}", mastery=0.7 + i * 0.03)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert len(result["strengths"]) == 5

    def test_max_five_needs_practice(self, db_session):
        _create_user(db_session)
        for i in range(7):
            gid = f"g{i}"
            _create_guideline(db_session, guideline_id=gid, subtopic=f"Sub{i}",
                              subtopic_key=f"sub{i}", topic_key="t")
            _create_session(db_session, guideline_id=gid,
                            topic_name=f"Fractions - Sub{i}", mastery=0.1 + i * 0.05)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert len(result["needs_practice"]) <= 5


# ===========================================================================
# Guideline Lookup
# ===========================================================================

class TestScorecardGuidelineLookup:
    """Test topic hierarchy resolution."""

    def test_hierarchy_from_guideline_table(self, db_session):
        _create_user(db_session)
        _create_guideline(
            db_session, guideline_id="g1",
            topic="Fractions", subtopic="Comparing Fractions",
            topic_key="fractions", subtopic_key="comparing-fractions",
        )
        _create_session(db_session, guideline_id="g1",
                        topic_name="Fractions - Comparing Fractions", mastery=0.8)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        topic = result["subjects"][0]["topics"][0]
        assert topic["topic_key"] == "fractions"
        subtopic = topic["subtopics"][0]
        assert subtopic["subtopic_key"] == "comparing-fractions"

    def test_fallback_to_topic_name_split(self, db_session):
        """If guideline_id is not found, fall back to splitting topic_name."""
        _create_user(db_session)
        # No guideline created, so lookup will fail
        _create_session(db_session, guideline_id="nonexistent",
                        topic_name="Geometry - Shapes", mastery=0.7)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        topic = result["subjects"][0]["topics"][0]
        assert topic["topic"] == "Geometry"
        subtopic = topic["subtopics"][0]
        assert subtopic["subtopic"] == "Shapes"

    def test_v2_fields_preferred_over_v1(self, db_session):
        """Verify topic_title/subtopic_title used when available."""
        _create_user(db_session)
        _create_guideline(
            db_session, guideline_id="g1",
            topic="old_topic", subtopic="old_subtopic",
            topic_title="New Topic Title", subtopic_title="New Subtopic Title",
            topic_key="new-topic", subtopic_key="new-subtopic",
        )
        _create_session(db_session, guideline_id="g1",
                        topic_name="old - names", mastery=0.8)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        topic = result["subjects"][0]["topics"][0]
        assert topic["topic"] == "New Topic Title"
        subtopic = topic["subtopics"][0]
        assert subtopic["subtopic"] == "New Subtopic Title"


# ===========================================================================
# Resilience
# ===========================================================================

class TestScorecardResilience:
    """Test graceful handling of malformed/legacy data."""

    def test_malformed_state_json_skipped_not_500(self, db_session):
        _create_user(db_session)
        # Create a session with invalid JSON
        session = SessionModel(
            id="bad-session",
            student_json="{}",
            goal_json="{}",
            state_json="NOT VALID JSON {{{",
            mastery=0.5,
            step_idx=1,
            user_id=USER_ID,
            subject="Mathematics",
            created_at=datetime.utcnow(),
        )
        db_session.add(session)
        db_session.commit()

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        # Should not raise, just return empty since the only session is malformed
        assert result["total_sessions"] == 1
        assert result["subjects"] == []

    def test_missing_topic_in_state_json_skipped(self, db_session):
        _create_user(db_session)
        session = SessionModel(
            id="no-topic-session",
            student_json="{}",
            goal_json="{}",
            state_json=json.dumps({"session_id": "x", "mastery_estimates": {}}),
            mastery=0.5,
            step_idx=1,
            user_id=USER_ID,
            subject="Mathematics",
            created_at=datetime.utcnow(),
        )
        db_session.add(session)
        db_session.commit()

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert result["total_sessions"] == 1
        assert result["subjects"] == []

    def test_empty_mastery_estimates_uses_session_mastery(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mastery=0.75, mastery_estimates={})

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["score"] == 0.75

    def test_mixed_valid_and_invalid_sessions(self, db_session):
        """Valid sessions still aggregated when some are malformed."""
        _create_user(db_session)
        _create_guideline(db_session)

        # One valid session
        _create_session(db_session, mastery=0.8)

        # One malformed session
        session = SessionModel(
            id="bad-session-2",
            student_json="{}",
            goal_json="{}",
            state_json="INVALID",
            mastery=0.5,
            step_idx=1,
            user_id=USER_ID,
            subject="Mathematics",
            created_at=datetime.utcnow(),
        )
        db_session.add(session)
        db_session.commit()

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert result["total_sessions"] == 2
        assert len(result["subjects"]) == 1
        assert result["subjects"][0]["score"] == 0.8


# ===========================================================================
# Subtopic Progress
# ===========================================================================

class TestSubtopicProgress:
    """Test the lightweight subtopic progress endpoint."""

    def test_empty_user_returns_empty(self, db_session):
        _create_user(db_session)
        service = ScorecardService(db_session)
        result = service.get_subtopic_progress(USER_ID)

        assert result["user_progress"] == {}

    def test_mastered_status_above_085(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mastery=0.9)

        service = ScorecardService(db_session)
        result = service.get_subtopic_progress(USER_ID)

        assert result["user_progress"]["g1"]["status"] == "mastered"
        assert result["user_progress"]["g1"]["score"] == 0.9

    def test_in_progress_status_below_085(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mastery=0.6)

        service = ScorecardService(db_session)
        result = service.get_subtopic_progress(USER_ID)

        assert result["user_progress"]["g1"]["status"] == "in_progress"
        assert result["user_progress"]["g1"]["score"] == 0.6

    def test_session_count_increments(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()
        _create_session(db_session, mastery=0.5, created_at=now - timedelta(days=1))
        _create_session(db_session, mastery=0.7, created_at=now)

        service = ScorecardService(db_session)
        result = service.get_subtopic_progress(USER_ID)

        assert result["user_progress"]["g1"]["session_count"] == 2

    def test_latest_session_score_wins(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()
        _create_session(db_session, mastery=0.4, created_at=now - timedelta(days=1))
        _create_session(db_session, mastery=0.9, created_at=now)

        service = ScorecardService(db_session)
        result = service.get_subtopic_progress(USER_ID)

        assert result["user_progress"]["g1"]["score"] == 0.9
        assert result["user_progress"]["g1"]["status"] == "mastered"
