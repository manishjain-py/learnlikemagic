"""Unit tests for PracticeAttemptRepository.

Covers the non-service primitives: CRUD flows, recent-unread query (including
grading_failed — previously only returned `graded` which hid failures from
the banner), latest_graded + count_by_user_guideline for the scorecard
integration.

Note on the partial unique index: enforcement lives in _apply_practice_tables()
at migrate-time and only takes effect on Postgres. SQLite's test DB doesn't
enforce it, so concurrency enforcement is tested at the service level via the
IntegrityError-catch path; here we just verify the query shapes.
"""
from datetime import datetime, timedelta
from uuid import uuid4

from shared.models.entities import PracticeAttempt, TeachingGuideline, User
from shared.repositories.practice_attempt_repository import PracticeAttemptRepository


def _make_user_and_guideline(db_session, gid="g1", uid="u1"):
    user = User(id=uid, cognito_sub=f"sub-{uid}", auth_provider="email")
    guideline = TeachingGuideline(
        id=gid, topic="t", chapter="c", subject="math",
        country="India", board="CBSE", grade=3, guideline="test",
    )
    db_session.add_all([user, guideline])
    db_session.commit()


def _attempt(db_session, **kwargs):
    """Insert a PracticeAttempt with sensible defaults."""
    defaults = dict(
        id=str(uuid4()),
        user_id="u1",
        guideline_id="g1",
        question_ids=[],
        questions_snapshot_json=[],
        answers_json={},
        status="in_progress",
        total_possible=10,
    )
    defaults.update(kwargs)
    a = PracticeAttempt(**defaults)
    db_session.add(a)
    db_session.commit()
    return a


class TestCreateAndRead:
    def test_create_and_get(self, db_session):
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        a = repo.create(
            user_id="u1", guideline_id="g1",
            question_ids=["q0"], questions_snapshot_json=[{}],
        )
        fetched = repo.get(a.id)
        assert fetched is not None
        assert fetched.id == a.id
        assert fetched.status == "in_progress"

    def test_get_in_progress_returns_only_in_progress(self, db_session):
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        graded = _attempt(db_session, status="graded", total_score=8.0, submitted_at=datetime.utcnow())
        in_prog = _attempt(db_session, status="in_progress")

        result = repo.get_in_progress("u1", "g1")
        assert result is not None
        assert result.id == in_prog.id


class TestListRecentUnread:
    def test_includes_graded_and_grading_failed(self, db_session):
        """Regression: earlier draft filtered on graded_at IS NOT NULL, which
        silently excluded grading_failed. The banner must surface both so
        students can Retry failed attempts.
        """
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        now = datetime.utcnow()
        _attempt(db_session, status="graded", submitted_at=now)
        _attempt(db_session, status="grading_failed", submitted_at=now - timedelta(minutes=1))
        _attempt(db_session, status="in_progress")  # should NOT surface
        _attempt(db_session, status="grading")       # should NOT surface

        unread = repo.list_recent_unread("u1")
        statuses = {a.status for a in unread}
        assert statuses == {"graded", "grading_failed"}

    def test_excludes_already_viewed(self, db_session):
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        _attempt(db_session, status="graded", results_viewed_at=datetime.utcnow(),
                 submitted_at=datetime.utcnow())
        unseen = _attempt(db_session, status="graded", submitted_at=datetime.utcnow())

        unread = repo.list_recent_unread("u1")
        assert [a.id for a in unread] == [unseen.id]


class TestLatestGradedAndCount:
    def test_latest_graded_returns_most_recent(self, db_session):
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        now = datetime.utcnow()
        _attempt(db_session, status="graded", graded_at=now - timedelta(days=2), total_score=4.0)
        newest = _attempt(db_session, status="graded", graded_at=now, total_score=8.0)
        _attempt(db_session, status="graded", graded_at=now - timedelta(days=1), total_score=6.0)

        latest = repo.latest_graded("u1", "g1")
        assert latest is not None
        assert latest.id == newest.id
        assert latest.total_score == 8.0

    def test_count_excludes_non_graded(self, db_session):
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        now = datetime.utcnow()
        _attempt(db_session, status="graded", graded_at=now)
        _attempt(db_session, status="graded", graded_at=now - timedelta(days=1))
        _attempt(db_session, status="grading_failed")
        _attempt(db_session, status="in_progress")

        assert repo.count_by_user_guideline("u1", "g1") == 2


class TestSaveAnswerAndMarkSubmitted:
    def test_save_answer_merges_into_jsonb(self, db_session):
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        a = _attempt(db_session)
        repo.save_answer(a.id, 0, "first")
        repo.save_answer(a.id, 1, "second")
        repo.save_answer(a.id, 0, "first-updated")  # overwrite

        db_session.refresh(a)
        assert a.answers_json == {"0": "first-updated", "1": "second"}

    def test_mark_submitted_flips_and_merges(self, db_session):
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        a = _attempt(db_session, answers_json={"0": "prior"})
        repo.mark_submitted(a.id, final_answers={"0": "final", "1": "new"})

        db_session.refresh(a)
        assert a.status == "grading"
        assert a.submitted_at is not None
        assert a.answers_json == {"0": "final", "1": "new"}

    def test_mark_submitted_noop_when_not_in_progress(self, db_session):
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        a = _attempt(db_session, status="grading")
        repo.mark_submitted(a.id)
        db_session.refresh(a)
        assert a.status == "grading"  # unchanged


class TestMarkViewed:
    def test_stamps_results_viewed_at(self, db_session):
        _make_user_and_guideline(db_session)
        repo = PracticeAttemptRepository(db_session)
        a = _attempt(db_session, status="graded", submitted_at=datetime.utcnow())
        assert a.results_viewed_at is None
        repo.mark_viewed(a.id)
        db_session.refresh(a)
        assert a.results_viewed_at is not None
