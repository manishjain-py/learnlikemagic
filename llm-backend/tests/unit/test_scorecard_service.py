"""Unit tests for tutor/services/scorecard_service.py

Tests deterministic scorecard aggregation (coverage + exam score only)
using an in-memory SQLite database.
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
    concepts_covered_set=None,
    mode="teach_me",
    exam_finished=False,
    exam_total_correct=0,
    exam_questions=None,
    created_at=None,
    session_id=None,
):
    """Create a session with realistic state_json for scorecard testing."""
    if mastery_estimates is None:
        mastery_estimates = {"concept_a": 0.8, "concept_b": 0.7}
    if concepts_covered_set is None:
        concepts_covered_set = []
    if exam_questions is None:
        exam_questions = []
    if created_at is None:
        created_at = datetime.utcnow()
    if session_id is None:
        session_id = f"sess-{uuid.uuid4().hex[:8]}"

    state = {
        "session_id": session_id,
        "mode": mode,
        "topic": {
            "topic_id": guideline_id,
            "topic_name": topic_name,
            "subject": subject,
            "grade_level": 3,
        },
        "mastery_estimates": mastery_estimates,
        "concepts_covered_set": concepts_covered_set,
        "exam_finished": exam_finished,
        "exam_total_correct": exam_total_correct,
        "exam_questions": exam_questions,
    }

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

        assert result["total_sessions"] == 0
        assert result["total_topics_studied"] == 0
        assert result["subjects"] == []
        assert "overall_score" not in result
        assert "strengths" not in result
        assert "needs_practice" not in result

    def test_nonexistent_user_returns_empty(self, db_session):
        service = ScorecardService(db_session)
        result = service.get_scorecard("nonexistent-user")

        assert result["total_sessions"] == 0
        assert result["total_topics_studied"] == 0


# ===========================================================================
# Single Session Structure
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

    def test_single_session_has_no_aggregate_scores(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mastery=0.8)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subject = result["subjects"][0]
        assert "score" not in subject
        topic = subject["topics"][0]
        assert "score" not in topic

    def test_single_session_subtopic_has_coverage(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mastery_estimates={"concept_a": 0.8, "concept_b": 0.7},
            concepts_covered_set=["concept_a"],
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["coverage"] == 50.0  # 1 of 2 concepts covered


# ===========================================================================
# Coverage (teach_me only)
# ===========================================================================

class TestScorecardCoverage:
    """Test coverage computation from teach_me sessions only."""

    def test_coverage_from_teach_me_session(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9, "c2": 0.7, "c3": 0.5},
            concepts_covered_set=["c1", "c2"],
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["coverage"] == pytest.approx(66.7, abs=0.1)  # 2/3

    def test_clarify_doubts_excluded_from_coverage(self, db_session):
        """clarify_doubts sessions should not contribute to coverage."""
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mode="clarify_doubts",
            mastery_estimates={"c1": 0.9, "c2": 0.7},
            concepts_covered_set=["c1", "c2"],
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        # clarify_doubts session creates a subject entry but coverage stays 0
        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["coverage"] == 0.0

    def test_coverage_accumulates_across_sessions(self, db_session):
        """Coverage from multiple teach_me sessions should accumulate."""
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()

        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9, "c2": 0.7, "c3": 0.5, "c4": 0.3},
            concepts_covered_set=["c1", "c2"],
            created_at=now - timedelta(days=1),
        )
        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9, "c2": 0.7, "c3": 0.5, "c4": 0.3},
            concepts_covered_set=["c3"],
            created_at=now,
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["coverage"] == 75.0  # 3 of 4 concepts

    def test_latest_plan_used_not_union(self, db_session):
        """Coverage denominator should use the latest session's plan, not union of all."""
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()

        # Session 1: plan has c1, c2 — covers c1
        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9, "c2": 0.7},
            concepts_covered_set=["c1"],
            created_at=now - timedelta(days=1),
        )
        # Session 2: plan changes to c1, c2, c3 — covers c2
        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9, "c2": 0.7, "c3": 0.5},
            concepts_covered_set=["c2"],
            created_at=now,
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        # covered = {c1, c2}, plan = {c1, c2, c3} (latest), coverage = 2/3 ≈ 66.7%
        assert subtopic["coverage"] == pytest.approx(66.7, abs=0.1)

    def test_zero_plan_concepts_gives_zero_coverage(self, db_session):
        """If no plan concepts (empty mastery_estimates), coverage is 0."""
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={},
            concepts_covered_set=["c1"],
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["coverage"] == 0.0


# ===========================================================================
# Exam Score
# ===========================================================================

class TestScorecardExamScore:
    """Test latest exam score passthrough."""

    def test_latest_exam_shown(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()

        # teach_me session first
        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9},
            concepts_covered_set=["c1"],
            created_at=now - timedelta(days=2),
        )
        # exam session
        _create_session(
            db_session,
            mode="exam",
            mastery_estimates={},
            concepts_covered_set=[],
            exam_finished=True,
            exam_total_correct=7,
            exam_questions=[{} for _ in range(10)],
            created_at=now,
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["latest_exam_score"] == 7
        assert subtopic["latest_exam_total"] == 10

    def test_no_exam_returns_none(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9},
            concepts_covered_set=["c1"],
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["latest_exam_score"] is None
        assert subtopic["latest_exam_total"] is None

    def test_exam_updates_last_studied(self, db_session):
        """Exam sessions should also update last_studied."""
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()

        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9},
            concepts_covered_set=["c1"],
            created_at=now - timedelta(days=5),
        )
        _create_session(
            db_session,
            mode="exam",
            mastery_estimates={},
            exam_finished=True,
            exam_total_correct=8,
            exam_questions=[{} for _ in range(10)],
            created_at=now,
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["last_studied"] == now.isoformat()

    def test_latest_exam_wins(self, db_session):
        """When multiple exams exist, the latest one should be shown."""
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()

        _create_session(
            db_session,
            mode="exam",
            mastery_estimates={},
            exam_finished=True,
            exam_total_correct=3,
            exam_questions=[{} for _ in range(10)],
            created_at=now - timedelta(days=1),
        )
        _create_session(
            db_session,
            mode="exam",
            mastery_estimates={},
            exam_finished=True,
            exam_total_correct=8,
            exam_questions=[{} for _ in range(10)],
            created_at=now,
        )

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["latest_exam_score"] == 8
        assert subtopic["latest_exam_total"] == 10


# ===========================================================================
# No Aggregate Scores
# ===========================================================================

class TestScorecardNoAggregateScores:
    """Verify no aggregate scores, strengths, or needs_practice in output."""

    def test_no_overall_score(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert "overall_score" not in result

    def test_no_strengths_or_needs_practice(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert "strengths" not in result
        assert "needs_practice" not in result

    def test_no_score_on_subject_or_topic(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", subtopic="A",
                          subtopic_key="a", topic_key="t")
        _create_guideline(db_session, guideline_id="g2", subtopic="B",
                          subtopic_key="b", topic_key="t")

        _create_session(db_session, guideline_id="g1",
                        topic_name="Fractions - A")
        _create_session(db_session, guideline_id="g2",
                        topic_name="Fractions - B")

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subject = result["subjects"][0]
        assert "score" not in subject
        topic = subject["topics"][0]
        assert "score" not in topic

    def test_no_trend_data(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session)

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subject = result["subjects"][0]
        assert "trend" not in subject


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
                        topic_name="Fractions - Comparing Fractions")

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        topic = result["subjects"][0]["topics"][0]
        assert topic["topic_key"] == "fractions"
        subtopic = topic["subtopics"][0]
        assert subtopic["subtopic_key"] == "comparing-fractions"

    def test_fallback_to_topic_name_split(self, db_session):
        """If guideline_id is not found, fall back to splitting topic_name."""
        _create_user(db_session)
        _create_session(db_session, guideline_id="nonexistent",
                        topic_name="Geometry - Shapes")

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
                        topic_name="old - names")

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

    def test_mixed_valid_and_invalid_sessions(self, db_session):
        """Valid sessions still aggregated when some are malformed."""
        _create_user(db_session)
        _create_guideline(db_session)

        _create_session(db_session, mastery=0.8)

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

    def test_non_dict_mastery_estimates_handled(self, db_session):
        """mastery_estimates as a non-dict (e.g. string) should not crash."""
        _create_user(db_session)
        _create_guideline(db_session)
        session = SessionModel(
            id="bad-mastery",
            student_json="{}",
            goal_json="{}",
            state_json=json.dumps({
                "mode": "teach_me",
                "topic": {"topic_id": "g1", "topic_name": "Fractions - Comparing Fractions", "subject": "Mathematics"},
                "mastery_estimates": "not a dict",
                "concepts_covered_set": ["c1"],
            }),
            mastery=0.5, step_idx=1, user_id=USER_ID,
            subject="Mathematics", created_at=datetime.utcnow(),
        )
        db_session.add(session)
        db_session.commit()

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["coverage"] == 0.0  # no plan concepts → 0%

    def test_non_list_exam_questions_handled(self, db_session):
        """exam_questions as a non-list should not crash."""
        _create_user(db_session)
        _create_guideline(db_session)
        session = SessionModel(
            id="bad-exam",
            student_json="{}",
            goal_json="{}",
            state_json=json.dumps({
                "mode": "exam",
                "topic": {"topic_id": "g1", "topic_name": "Fractions - Comparing Fractions", "subject": "Mathematics"},
                "mastery_estimates": {},
                "exam_finished": True,
                "exam_total_correct": 5,
                "exam_questions": "not a list",
            }),
            mastery=0.5, step_idx=1, user_id=USER_ID,
            subject="Mathematics", created_at=datetime.utcnow(),
        )
        db_session.add(session)
        db_session.commit()

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["latest_exam_score"] is None  # exam_total=0, so not recorded

    def test_non_int_exam_total_correct_handled(self, db_session):
        """exam_total_correct as a string should be handled gracefully."""
        _create_user(db_session)
        _create_guideline(db_session)
        session = SessionModel(
            id="bad-score",
            student_json="{}",
            goal_json="{}",
            state_json=json.dumps({
                "mode": "exam",
                "topic": {"topic_id": "g1", "topic_name": "Fractions - Comparing Fractions", "subject": "Mathematics"},
                "mastery_estimates": {},
                "exam_finished": True,
                "exam_total_correct": "not a number",
                "exam_questions": [{}, {}, {}],
            }),
            mastery=0.5, step_idx=1, user_id=USER_ID,
            subject="Mathematics", created_at=datetime.utcnow(),
        )
        db_session.add(session)
        db_session.commit()

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subtopic = result["subjects"][0]["topics"][0]["subtopics"][0]
        assert subtopic["latest_exam_score"] == 0  # defaults to 0

    def test_topic_as_non_dict_skipped(self, db_session):
        """topic as a string instead of dict should be skipped."""
        _create_user(db_session)
        session = SessionModel(
            id="bad-topic",
            student_json="{}",
            goal_json="{}",
            state_json=json.dumps({
                "mode": "teach_me",
                "topic": "just a string",
                "mastery_estimates": {"c1": 0.9},
            }),
            mastery=0.5, step_idx=1, user_id=USER_ID,
            subject="Mathematics", created_at=datetime.utcnow(),
        )
        db_session.add(session)
        db_session.commit()

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert result["total_sessions"] == 1
        assert result["subjects"] == []

    def test_state_json_as_array_skipped(self, db_session):
        """state_json that parses as a list (not dict) should be skipped."""
        _create_user(db_session)
        session = SessionModel(
            id="array-state",
            student_json="{}",
            goal_json="{}",
            state_json="[1, 2, 3]",
            mastery=0.5, step_idx=1, user_id=USER_ID,
            subject="Mathematics", created_at=datetime.utcnow(),
        )
        db_session.add(session)
        db_session.commit()

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        assert result["total_sessions"] == 1
        assert result["subjects"] == []

    def test_multiple_subjects_grouped_correctly(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", subject="Mathematics",
                          topic="Numbers", subtopic="Addition",
                          topic_key="numbers", subtopic_key="addition")
        _create_guideline(db_session, guideline_id="g2", subject="Science",
                          topic="Plants", subtopic="Parts",
                          topic_key="plants", subtopic_key="parts")

        _create_session(db_session, guideline_id="g1", subject="Mathematics",
                        topic_name="Numbers - Addition")
        _create_session(db_session, guideline_id="g2", subject="Science",
                        topic_name="Plants - Parts")

        service = ScorecardService(db_session)
        result = service.get_scorecard(USER_ID)

        subject_names = [s["subject"] for s in result["subjects"]]
        assert "Mathematics" in subject_names
        assert "Science" in subject_names


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

    def test_studied_status_for_teach_me(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9, "c2": 0.7},
            concepts_covered_set=["c1"],
        )

        service = ScorecardService(db_session)
        result = service.get_subtopic_progress(USER_ID)

        assert result["user_progress"]["g1"]["status"] == "studied"
        assert result["user_progress"]["g1"]["coverage"] == 50.0

    def test_clarify_doubts_excluded(self, db_session):
        """clarify_doubts sessions should not appear in subtopic progress."""
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mode="clarify_doubts",
            mastery_estimates={"c1": 0.9},
            concepts_covered_set=["c1"],
        )

        service = ScorecardService(db_session)
        result = service.get_subtopic_progress(USER_ID)

        assert result["user_progress"] == {}

    def test_session_count_increments(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()
        _create_session(
            db_session, mode="teach_me",
            mastery_estimates={"c1": 0.9},
            concepts_covered_set=["c1"],
            created_at=now - timedelta(days=1),
        )
        _create_session(
            db_session, mode="teach_me",
            mastery_estimates={"c1": 0.9},
            concepts_covered_set=["c1"],
            created_at=now,
        )

        service = ScorecardService(db_session)
        result = service.get_subtopic_progress(USER_ID)

        assert result["user_progress"]["g1"]["session_count"] == 2

    def test_coverage_accumulates_across_sessions(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()
        _create_session(
            db_session, mode="teach_me",
            mastery_estimates={"c1": 0.9, "c2": 0.7},
            concepts_covered_set=["c1"],
            created_at=now - timedelta(days=1),
        )
        _create_session(
            db_session, mode="teach_me",
            mastery_estimates={"c1": 0.9, "c2": 0.7},
            concepts_covered_set=["c2"],
            created_at=now,
        )

        service = ScorecardService(db_session)
        result = service.get_subtopic_progress(USER_ID)

        assert result["user_progress"]["g1"]["coverage"] == 100.0
