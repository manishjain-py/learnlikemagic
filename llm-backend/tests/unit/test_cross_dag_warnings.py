"""Unit tests for the Phase 6 cross-DAG warning helpers + endpoint.

Covers:
- `compute_input_hash` determinism + ordering + NULL handling.
- `capture_explanations_input_hash` writes to the column.
- Terminal-hook integration: hash captured on `explanations` done, skipped on
  other stages and on `failed` terminal state.
- `GET /admin/v2/topics/{guideline_id}/cross-dag-warnings`:
  - 404 for unknown guideline.
  - Empty warnings when hash never captured (explanations hasn't run).
  - Empty warnings when hash matches live.
  - `chapter_resynced` warning when hash differs.
  - `last_explanations_at` populated from `topic_stage_runs`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from book_ingestion_v2.api.processing_routes import (
    _write_topic_stage_run_terminal,
)
from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag.cross_dag_warnings import (
    capture_explanations_input_hash,
    compute_input_hash,
    compute_input_hash_for_guideline,
)
from book_ingestion_v2.models.database import (
    BookChapter,
    ChapterProcessingJob,
    TopicStageRun,
)
from shared.models.entities import Base, Book, TeachingGuideline


# ───── Hash function ─────


class TestComputeInputHash:
    def test_deterministic(self):
        a = compute_input_hash("g", "p", "t")
        b = compute_input_hash("g", "p", "t")
        assert a == b
        assert len(a) == 64  # sha256 hex

    def test_changes_when_guideline_changes(self):
        a = compute_input_hash("g1", "p", "t")
        b = compute_input_hash("g2", "p", "t")
        assert a != b

    def test_changes_when_prior_context_changes(self):
        a = compute_input_hash("g", "p1", "t")
        b = compute_input_hash("g", "p2", "t")
        assert a != b

    def test_changes_when_topic_title_changes(self):
        a = compute_input_hash("g", "p", "t1")
        b = compute_input_hash("g", "p", "t2")
        assert a != b

    def test_null_equals_empty_string(self):
        # Treating NULL as "" prevents a freshly-set empty prior_topics_context
        # from looking like a content change.
        assert compute_input_hash(None, None, None) == compute_input_hash("", "", "")
        assert compute_input_hash("g", None, "t") == compute_input_hash("g", "", "t")

    def test_field_separator_collision_resistant(self):
        # Putting the unit separator inside a field shouldn't collide with the
        # field boundary itself (which would let "g\x1fp" / "" / "t" hash the
        # same as "g" / "p" / "t").
        a = compute_input_hash("g\x1fp", "", "t")
        b = compute_input_hash("g", "p", "t")
        assert a != b


# ───── ORM helper ─────


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    Base.metadata.drop_all(engine)


def _seed_guideline(
    session,
    *,
    guideline: str = "g",
    prior_topics_context: str = "p",
    topic_title: str = "Topic Title",
):
    book_id = str(uuid.uuid4())
    guideline_id = str(uuid.uuid4())
    session.add(Book(
        id=book_id, title="T", country="India", board="CBSE", grade=4,
        subject="Mathematics", s3_prefix=f"books/{book_id}/",
    ))
    session.add(TeachingGuideline(
        id=guideline_id, country="India", board="CBSE", grade=4,
        subject="Mathematics", chapter="Fractions",
        topic="Comparing Fractions", guideline=guideline,
        chapter_key="chapter-5", topic_key="comparing-fractions",
        chapter_title="Fractions", topic_title=topic_title,
        book_id=book_id, review_status="APPROVED",
        prior_topics_context=prior_topics_context,
    ))
    session.commit()
    return guideline_id


class TestComputeInputHashForGuideline:
    def test_matches_raw_compute(self, session):
        gid = _seed_guideline(
            session, guideline="text", prior_topics_context="prior",
            topic_title="Title",
        )
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        live = compute_input_hash_for_guideline(guideline)
        assert live == compute_input_hash("text", "prior", "Title")


class TestCaptureExplanationsInputHash:
    def test_writes_hash_to_column(self, session):
        gid = _seed_guideline(session)
        captured = capture_explanations_input_hash(session, gid)
        session.commit()
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        assert guideline.explanations_input_hash == captured
        assert len(captured) == 64

    def test_overwrites_existing_hash(self, session):
        gid = _seed_guideline(session, guideline="v1")
        capture_explanations_input_hash(session, gid)
        session.commit()

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.guideline = "v2"
        session.commit()

        new_hash = capture_explanations_input_hash(session, gid)
        session.commit()
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        assert guideline.explanations_input_hash == new_hash

    def test_returns_none_when_guideline_missing(self, session):
        result = capture_explanations_input_hash(session, "does-not-exist")
        assert result is None


# ───── Terminal-hook integration ─────


def _seed_chapter_and_job(
    session,
    *,
    job_type: str,
    status: str = "completed",
):
    """Insert the rows the terminal hook expects: book + chapter + guideline + job."""
    gid = _seed_guideline(session)
    chapter_id = str(uuid.uuid4())
    book = session.query(Book).first()

    session.add(BookChapter(
        id=chapter_id, book_id=book.id, chapter_number=5,
        chapter_title="Fractions", start_page=1, end_page=20,
        status="chapter_completed", total_pages=20, uploaded_page_count=20,
    ))
    job_id = str(uuid.uuid4())
    session.add(ChapterProcessingJob(
        id=job_id, book_id=book.id, chapter_id=chapter_id,
        guideline_id=gid, job_type=job_type, status=status,
    ))
    session.commit()
    return gid, job_id


class TestTerminalHookCaptures:
    def test_captures_on_explanations_done(self, session):
        gid, job_id = _seed_chapter_and_job(
            session, job_type=V2JobType.EXPLANATION_GENERATION.value,
        )
        started = datetime.utcnow() - timedelta(seconds=5)
        _write_topic_stage_run_terminal(session, job_id, started_at=started)

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        assert guideline.explanations_input_hash is not None
        assert len(guideline.explanations_input_hash) == 64

    def test_no_capture_on_explanations_failed(self, session):
        gid, job_id = _seed_chapter_and_job(
            session, job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="failed",
        )
        started = datetime.utcnow() - timedelta(seconds=5)
        _write_topic_stage_run_terminal(session, job_id, started_at=started)

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        assert guideline.explanations_input_hash is None

    def test_no_capture_on_other_stages(self, session):
        gid, job_id = _seed_chapter_and_job(
            session, job_type=V2JobType.VISUAL_ENRICHMENT.value,
        )
        started = datetime.utcnow() - timedelta(seconds=5)
        _write_topic_stage_run_terminal(session, job_id, started_at=started)

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        assert guideline.explanations_input_hash is None


# ───── Endpoint ─────


@pytest.fixture
def api_with_db():
    """FastAPI TestClient backed by a thread-safe in-memory SQLite.

    Same plumbing as `test_cascade_orchestrator.api_with_db`. Returns
    `(client, session)` so tests can hit the endpoint and inspect/mutate
    the DB through the same connection.
    """
    from database import get_db
    from main import app

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    def _override_get_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    try:
        yield client, s
    finally:
        app.dependency_overrides.pop(get_db, None)
        s.close()
        Base.metadata.drop_all(engine)


class TestCrossDagWarningsEndpoint:
    def test_404_when_guideline_missing(self, api_with_db):
        client, _ = api_with_db
        resp = client.get(
            "/admin/v2/topics/does-not-exist/cross-dag-warnings"
        )
        assert resp.status_code == 404

    def test_empty_warnings_when_hash_never_captured(self, api_with_db):
        client, session = api_with_db
        gid = _seed_guideline(session)
        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert resp.json() == {"warnings": []}

    def test_empty_warnings_when_hash_matches(self, api_with_db):
        client, session = api_with_db
        gid = _seed_guideline(session)
        capture_explanations_input_hash(session, gid)
        session.commit()

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert resp.json() == {"warnings": []}

    def test_warning_when_guideline_text_mutated(self, api_with_db):
        client, session = api_with_db
        gid = _seed_guideline(session, guideline="original")

        # Capture baseline (mimics a successful explanations run).
        capture_explanations_input_hash(session, gid)
        session.commit()

        # Upstream stage rewrites the guideline.
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.guideline = "rewritten"
        session.commit()

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["warnings"]) == 1
        warning = body["warnings"][0]
        assert warning["kind"] == "chapter_resynced"
        assert "Re-run Explanations" in warning["message"]

    def test_warning_when_topic_title_mutated(self, api_with_db):
        client, session = api_with_db
        gid = _seed_guideline(session, topic_title="Original Title")
        capture_explanations_input_hash(session, gid)
        session.commit()

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.topic_title = "New Title"
        session.commit()

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert len(resp.json()["warnings"]) == 1

    def test_warning_when_prior_context_mutated(self, api_with_db):
        client, session = api_with_db
        gid = _seed_guideline(session, prior_topics_context="old")
        capture_explanations_input_hash(session, gid)
        session.commit()

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.prior_topics_context = "new"
        session.commit()

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert len(resp.json()["warnings"]) == 1

    def test_last_explanations_at_populated_from_topic_stage_runs(
        self, api_with_db,
    ):
        client, session = api_with_db
        gid = _seed_guideline(session, guideline="orig")
        capture_explanations_input_hash(session, gid)
        completed = datetime(2026, 4, 28, 10, 0, 0)
        session.add(TopicStageRun(
            guideline_id=gid, stage_id="explanations", state="done",
            completed_at=completed,
        ))
        session.commit()

        # Mutate to trigger warning.
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.guideline = "new"
        session.commit()

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        warning = resp.json()["warnings"][0]
        assert warning["last_explanations_at"] is not None
        assert warning["last_explanations_at"].startswith("2026-04-28")

    def test_warning_clears_when_explanations_reruns(self, api_with_db):
        """End-to-end the banner-clearing contract."""
        client, session = api_with_db
        gid = _seed_guideline(session, guideline="v1")
        capture_explanations_input_hash(session, gid)
        session.commit()

        # Upstream changes the guideline → warning fires.
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.guideline = "v2"
        session.commit()
        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert len(resp.json()["warnings"]) == 1

        # Explanations re-runs → captures new hash → warning clears.
        capture_explanations_input_hash(session, gid)
        session.commit()
        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.json() == {"warnings": []}
