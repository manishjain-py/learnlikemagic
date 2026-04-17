"""Unit tests for tutor/services/report_card_service.py

Tests deterministic report card aggregation (coverage + exam score only)
using an in-memory SQLite database.
"""

import json
import uuid
from datetime import datetime, timedelta

import pytest

from shared.models.entities import (
    PracticeAttempt,
    Session as SessionModel,
    TeachingGuideline,
    User,
)
from tutor.services.report_card_service import ReportCardService


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
    chapter="Fractions",
    topic="Comparing Fractions",
    chapter_key=None,
    topic_key=None,
    chapter_title=None,
    topic_title=None,
):
    """Create a teaching guideline record."""
    g = TeachingGuideline(
        id=guideline_id,
        country="India",
        board="CBSE",
        grade=3,
        subject=subject,
        chapter=chapter,
        topic=topic,
        guideline="Test guideline content",
        chapter_key=chapter_key,
        topic_key=topic_key,
        chapter_title=chapter_title,
        topic_title=topic_title,
    )
    db.add(g)
    db.commit()
    return g


def _create_practice_attempt(
    db,
    user_id=USER_ID,
    guideline_id="g1",
    total_score=7.5,
    total_possible=10,
    status="graded",
    graded_at=None,
    attempt_id=None,
):
    """Create a practice attempt for report-card merging tests."""
    if attempt_id is None:
        attempt_id = f"att-{uuid.uuid4().hex[:8]}"
    if graded_at is None and status == "graded":
        graded_at = datetime.utcnow()

    attempt = PracticeAttempt(
        id=attempt_id,
        user_id=user_id,
        guideline_id=guideline_id,
        question_ids=[],
        questions_snapshot_json=[],
        answers_json={},
        grading_json=None,
        total_score=total_score if status == "graded" else None,
        total_possible=total_possible,
        status=status,
        graded_at=graded_at,
    )
    db.add(attempt)
    db.commit()
    return attempt


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
    created_at=None,
    session_id=None,
):
    """Create a session with realistic state_json for report card testing."""
    if mastery_estimates is None:
        mastery_estimates = {"concept_a": 0.8, "concept_b": 0.7}
    if concepts_covered_set is None:
        concepts_covered_set = []
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
    }

    student_json = json.dumps({"id": user_id, "grade": 3})
    goal_json = json.dumps({"chapter": topic_name, "guideline_id": guideline_id})

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
# Empty Report Card
# ===========================================================================

class TestReportCardEmpty:
    """Test report card for users with no sessions."""

    def test_empty_report_card_returns_zeros(self, db_session):
        _create_user(db_session)
        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        assert result["total_sessions"] == 0
        assert result["total_chapters_studied"] == 0
        assert result["subjects"] == []
        assert "overall_score" not in result
        assert "strengths" not in result
        assert "needs_practice" not in result

    def test_nonexistent_user_returns_empty(self, db_session):
        service = ReportCardService(db_session)
        result = service.get_report_card("nonexistent-user")

        assert result["total_sessions"] == 0
        assert result["total_chapters_studied"] == 0


# ===========================================================================
# Single Session Structure
# ===========================================================================

class TestReportCardSingleSession:
    """Test report card with one session."""

    def test_single_session_creates_one_subject(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mastery=0.8)

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        assert result["total_sessions"] == 1
        assert len(result["subjects"]) == 1
        assert result["subjects"][0]["subject"] == "Mathematics"

    def test_single_session_has_no_aggregate_scores(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mastery=0.8)

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        subject = result["subjects"][0]
        assert "score" not in subject
        chapter = subject["chapters"][0]
        assert "score" not in chapter

    def test_single_session_topic_has_coverage(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mastery_estimates={"concept_a": 0.8, "concept_b": 0.7},
            concepts_covered_set=["concept_a"],
        )

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["coverage"] == 50.0  # 1 of 2 concepts covered


# ===========================================================================
# Coverage (teach_me only)
# ===========================================================================

class TestReportCardCoverage:
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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["coverage"] == pytest.approx(66.7, abs=0.1)  # 2/3

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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        # clarify_doubts session creates a subject entry but coverage stays 0
        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["coverage"] == 0.0

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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["coverage"] == 75.0  # 3 of 4 concepts

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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        # covered = {c1, c2}, plan = {c1, c2, c3} (latest), coverage = 2/3 ≈ 66.7%
        assert topic["coverage"] == pytest.approx(66.7, abs=0.1)

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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["coverage"] == 0.0


# ===========================================================================
# Practice Attempts
# ===========================================================================

class TestReportCardPracticeAttempts:
    """Test practice-attempt merging into the report card."""

    def test_practice_only_topic_creates_row_with_practice_fields(self, db_session):
        """A topic with only a graded practice attempt (no sessions) still appears."""
        _create_user(db_session)
        _create_guideline(db_session)
        _create_practice_attempt(
            db_session,
            guideline_id="g1",
            total_score=7.5,
            total_possible=10,
        )

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["latest_practice_score"] == 7.5
        assert topic["latest_practice_total"] == 10
        assert topic["practice_attempt_count"] == 1

    def test_topic_with_teach_me_plus_practice(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mode="teach_me",
            mastery_estimates={"c1": 0.9},
            concepts_covered_set=["c1"],
        )
        _create_practice_attempt(
            db_session,
            guideline_id="g1",
            total_score=8.0,
            total_possible=10,
        )

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["coverage"] == 100.0
        assert topic["latest_practice_score"] == 8.0
        assert topic["latest_practice_total"] == 10
        assert topic["practice_attempt_count"] == 1

    def test_grading_failed_attempt_excluded(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mode="teach_me",
                        mastery_estimates={"c1": 0.9},
                        concepts_covered_set=["c1"])
        _create_practice_attempt(
            db_session,
            guideline_id="g1",
            status="grading_failed",
            total_score=None,
        )

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["latest_practice_score"] is None
        assert topic["practice_attempt_count"] is None

    def test_in_progress_attempt_excluded(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session, mode="teach_me",
                        mastery_estimates={"c1": 0.9},
                        concepts_covered_set=["c1"])
        _create_practice_attempt(
            db_session,
            guideline_id="g1",
            status="in_progress",
            total_score=None,
            graded_at=None,
        )

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["latest_practice_score"] is None
        assert topic["practice_attempt_count"] is None

    def test_latest_graded_attempt_wins(self, db_session):
        """When multiple graded attempts exist, latest graded_at wins — and the count is all of them."""
        _create_user(db_session)
        _create_guideline(db_session)
        now = datetime.utcnow()

        _create_practice_attempt(
            db_session,
            guideline_id="g1",
            total_score=5.0,
            graded_at=now - timedelta(days=2),
        )
        _create_practice_attempt(
            db_session,
            guideline_id="g1",
            total_score=9.0,
            graded_at=now,
        )
        _create_practice_attempt(
            db_session,
            guideline_id="g1",
            total_score=7.5,
            graded_at=now - timedelta(days=1),
        )

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["latest_practice_score"] == 9.0
        assert topic["practice_attempt_count"] == 3

    def test_practice_only_user_gets_empty_total_sessions(self, db_session):
        """A user with only practice attempts (no chat sessions) still gets a subject row."""
        _create_user(db_session)
        _create_guideline(db_session)
        _create_practice_attempt(db_session, guideline_id="g1", total_score=6.5)

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        assert result["total_sessions"] == 0  # chat-session count unaffected
        assert len(result["subjects"]) == 1
        assert result["subjects"][0]["subject"] == "Mathematics"
        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["latest_practice_score"] == 6.5


# ===========================================================================
# No Aggregate Scores
# ===========================================================================

class TestReportCardNoAggregateScores:
    """Verify no aggregate scores, strengths, or needs_practice in output."""

    def test_no_overall_score(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session)

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        assert "overall_score" not in result

    def test_no_strengths_or_needs_practice(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session)

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        assert "strengths" not in result
        assert "needs_practice" not in result

    def test_no_score_on_subject_or_chapter(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", topic="A",
                          topic_key="a", chapter_key="t")
        _create_guideline(db_session, guideline_id="g2", topic="B",
                          topic_key="b", chapter_key="t")

        _create_session(db_session, guideline_id="g1",
                        topic_name="Fractions - A")
        _create_session(db_session, guideline_id="g2",
                        topic_name="Fractions - B")

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        subject = result["subjects"][0]
        assert "score" not in subject
        chapter = subject["chapters"][0]
        assert "score" not in chapter

    def test_no_trend_data(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(db_session)

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        subject = result["subjects"][0]
        assert "trend" not in subject


# ===========================================================================
# Guideline Lookup
# ===========================================================================

class TestReportCardGuidelineLookup:
    """Test chapter/topic hierarchy resolution."""

    def test_hierarchy_from_guideline_table(self, db_session):
        _create_user(db_session)
        _create_guideline(
            db_session, guideline_id="g1",
            chapter="Fractions", topic="Comparing Fractions",
            chapter_key="fractions", topic_key="comparing-fractions",
        )
        _create_session(db_session, guideline_id="g1",
                        topic_name="Fractions - Comparing Fractions")

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        chapter = result["subjects"][0]["chapters"][0]
        assert chapter["chapter_key"] == "fractions"
        topic = chapter["topics"][0]
        assert topic["topic_key"] == "comparing-fractions"

    def test_fallback_to_topic_name_split(self, db_session):
        """If guideline_id is not found, fall back to splitting topic_name."""
        _create_user(db_session)
        _create_session(db_session, guideline_id="nonexistent",
                        topic_name="Geometry - Shapes")

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        chapter = result["subjects"][0]["chapters"][0]
        assert chapter["chapter"] == "Geometry"
        topic = chapter["topics"][0]
        assert topic["topic"] == "Shapes"

    def test_v2_fields_preferred_over_v1(self, db_session):
        """Verify chapter_title/topic_title used when available."""
        _create_user(db_session)
        _create_guideline(
            db_session, guideline_id="g1",
            chapter="old_chapter", topic="old_topic",
            chapter_title="New Chapter Title", topic_title="New Topic Title",
            chapter_key="new-chapter", topic_key="new-topic",
        )
        _create_session(db_session, guideline_id="g1",
                        topic_name="old - names")

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        chapter = result["subjects"][0]["chapters"][0]
        assert chapter["chapter"] == "New Chapter Title"
        topic = chapter["topics"][0]
        assert topic["topic"] == "New Topic Title"


# ===========================================================================
# Resilience
# ===========================================================================

class TestReportCardResilience:
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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        topic = result["subjects"][0]["chapters"][0]["topics"][0]
        assert topic["coverage"] == 0.0  # no plan concepts → 0%

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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

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

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        assert result["total_sessions"] == 1
        assert result["subjects"] == []

    def test_multiple_subjects_grouped_correctly(self, db_session):
        _create_user(db_session)
        _create_guideline(db_session, guideline_id="g1", subject="Mathematics",
                          chapter="Numbers", topic="Addition",
                          chapter_key="numbers", topic_key="addition")
        _create_guideline(db_session, guideline_id="g2", subject="Science",
                          chapter="Plants", topic="Parts",
                          chapter_key="plants", topic_key="parts")

        _create_session(db_session, guideline_id="g1", subject="Mathematics",
                        topic_name="Numbers - Addition")
        _create_session(db_session, guideline_id="g2", subject="Science",
                        topic_name="Plants - Parts")

        service = ReportCardService(db_session)
        result = service.get_report_card(USER_ID)

        subject_names = [s["subject"] for s in result["subjects"]]
        assert "Mathematics" in subject_names
        assert "Science" in subject_names


# ===========================================================================
# Topic Progress
# ===========================================================================

class TestTopicProgress:
    """Test the lightweight topic progress endpoint."""

    def test_empty_user_returns_empty(self, db_session):
        _create_user(db_session)
        service = ReportCardService(db_session)
        result = service.get_topic_progress(USER_ID)

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

        service = ReportCardService(db_session)
        result = service.get_topic_progress(USER_ID)

        assert result["user_progress"]["g1"]["status"] == "studied"
        assert result["user_progress"]["g1"]["coverage"] == 50.0

    def test_clarify_doubts_excluded(self, db_session):
        """clarify_doubts sessions should not appear in topic progress."""
        _create_user(db_session)
        _create_guideline(db_session)
        _create_session(
            db_session,
            mode="clarify_doubts",
            mastery_estimates={"c1": 0.9},
            concepts_covered_set=["c1"],
        )

        service = ReportCardService(db_session)
        result = service.get_topic_progress(USER_ID)

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

        service = ReportCardService(db_session)
        result = service.get_topic_progress(USER_ID)

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

        service = ReportCardService(db_session)
        result = service.get_topic_progress(USER_ID)

        assert result["user_progress"]["g1"]["coverage"] == 100.0
