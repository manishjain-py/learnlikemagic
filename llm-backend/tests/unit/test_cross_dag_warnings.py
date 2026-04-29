"""Unit tests for the Phase 6 cross-DAG warning helpers + endpoint.

Covers:
- `compute_input_hash` determinism + per-field sensitivity + NULL handling
  + separator collision resistance.
- `compute_input_hash_for_guideline` mirrors `explanation_generator_service`'s
  fallback chain (guideline OR description; topic_title OR topic).
- `stable_key_for_guideline` returns None when curriculum tuple is incomplete.
- `capture_explanations_input_hash` writes to `topic_content_hashes` keyed on
  the stable tuple, returns None on missing guideline / missing key,
  preserves the row across guideline_id changes (same chapter_key/topic_key).
- `last_explanations_at` reflects only successful runs (P2 fix is structural —
  the column is only ever written by `capture_*` on `done`).
- Terminal-hook integration: hash captured on `explanations` done, skipped
  on other stages and on `failed` terminal state.
- `GET /admin/v2/topics/{guideline_id}/cross-dag-warnings`:
  - 404 for unknown guideline.
  - Empty warnings when no hash captured yet.
  - Empty warnings when hash matches live.
  - `chapter_resynced` warning when hash differs.
  - `chapter_resynced` warning still fires after a `topic_sync` resync that
    deletes the guideline and recreates it with a new id (the headline use
    case).
  - `last_explanations_at` populated from the hash row.
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
    get_stored_hash,
    stable_key_for_guideline,
)
from book_ingestion_v2.models.database import (
    BookChapter,
    ChapterProcessingJob,
    TopicContentHash,
)
from shared.models.entities import Base, Book, TeachingGuideline


# ───── Hash function ─────


class TestComputeInputHash:
    def test_deterministic(self):
        a = compute_input_hash("g", "p", "t")
        b = compute_input_hash("g", "p", "t")
        assert a == b
        assert len(a) == 64

    def test_changes_when_guideline_changes(self):
        assert compute_input_hash("g1", "p", "t") != compute_input_hash("g2", "p", "t")

    def test_changes_when_prior_context_changes(self):
        assert compute_input_hash("g", "p1", "t") != compute_input_hash("g", "p2", "t")

    def test_changes_when_topic_title_changes(self):
        assert compute_input_hash("g", "p", "t1") != compute_input_hash("g", "p", "t2")

    def test_null_equals_empty_string(self):
        assert compute_input_hash(None, None, None) == compute_input_hash("", "", "")
        assert compute_input_hash("g", None, "t") == compute_input_hash("g", "", "t")

    def test_field_separator_collision_resistant(self):
        a = compute_input_hash("g\x1fp", "", "t")
        b = compute_input_hash("g", "p", "t")
        assert a != b


# ───── ORM helper + fallback chains ─────


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
    book_id: str | None = None,
    chapter_key: str = "chapter-5",
    topic_key: str = "comparing-fractions",
    guideline: str | None = "g",
    description: str | None = None,
    topic: str | None = None,
    topic_title: str | None = "Comparing Fractions",
    prior_topics_context: str | None = "p",
    book_title: str = "T",
):
    book_id = book_id or str(uuid.uuid4())
    if not session.query(Book).filter_by(id=book_id).first():
        session.add(Book(
            id=book_id, title=book_title, country="India", board="CBSE",
            grade=4, subject="Mathematics", s3_prefix=f"books/{book_id}/",
        ))
    guideline_id = str(uuid.uuid4())
    session.add(TeachingGuideline(
        id=guideline_id, country="India", board="CBSE", grade=4,
        subject="Mathematics", chapter="Fractions",
        topic=topic or "Comparing Fractions",
        guideline=guideline,
        description=description,
        chapter_key=chapter_key, topic_key=topic_key,
        chapter_title="Fractions", topic_title=topic_title,
        book_id=book_id, review_status="APPROVED",
        prior_topics_context=prior_topics_context,
    ))
    session.commit()
    return book_id, guideline_id


class TestComputeInputHashForGuidelineFallbacks:
    def test_uses_guideline_when_present(self, session):
        _, gid = _seed_guideline(
            session, guideline="primary text", description="ignored",
        )
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        live = compute_input_hash_for_guideline(guideline)
        assert live == compute_input_hash("primary text", "p", "Comparing Fractions")

    def test_falls_back_to_description_when_guideline_blank(self, session):
        # The DB column is NOT NULL but the generator falls back to
        # `description` whenever `guideline` is empty (or any falsy value).
        # Hash must reflect that or a `description` mutation goes silent.
        _, gid = _seed_guideline(
            session, guideline="", description="fallback text",
        )
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        live = compute_input_hash_for_guideline(guideline)
        assert live == compute_input_hash("fallback text", "p", "Comparing Fractions")

    def test_falls_back_to_topic_when_topic_title_blank(self, session):
        _, gid = _seed_guideline(
            session, topic_title=None, topic="Bare Topic",
        )
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        live = compute_input_hash_for_guideline(guideline)
        assert live == compute_input_hash("g", "p", "Bare Topic")

    def test_description_mutation_changes_hash_when_guideline_blank(self, session):
        """Regression test for P1: a `description` mutation must change the
        hash whenever `guideline` is the empty fallback path."""
        _, gid = _seed_guideline(
            session, guideline="", description="v1",
        )
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        h1 = compute_input_hash_for_guideline(guideline)
        guideline.description = "v2"
        session.commit()
        h2 = compute_input_hash_for_guideline(guideline)
        assert h1 != h2


class TestStableKeyForGuideline:
    def test_returns_full_tuple(self, session):
        _, gid = _seed_guideline(session)
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        assert stable_key_for_guideline(guideline) == (
            guideline.book_id, "chapter-5", "comparing-fractions",
        )

    def test_returns_none_when_book_id_missing(self, session):
        _, gid = _seed_guideline(session)
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.book_id = None
        assert stable_key_for_guideline(guideline) is None

    def test_returns_none_when_chapter_key_missing(self, session):
        _, gid = _seed_guideline(session)
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.chapter_key = None
        assert stable_key_for_guideline(guideline) is None

    def test_returns_none_when_topic_key_missing(self, session):
        _, gid = _seed_guideline(session)
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.topic_key = None
        assert stable_key_for_guideline(guideline) is None


# ───── Capture ─────


class TestCaptureExplanationsInputHash:
    def test_writes_hash_to_side_table(self, session):
        book_id, gid = _seed_guideline(session)
        captured = capture_explanations_input_hash(session, gid)
        session.commit()
        row = session.query(TopicContentHash).filter_by(
            book_id=book_id, chapter_key="chapter-5", topic_key="comparing-fractions",
        ).first()
        assert row is not None
        assert row.explanations_input_hash == captured
        assert len(captured) == 64
        assert row.last_explanations_at is not None

    def test_overwrites_existing_hash(self, session):
        book_id, gid = _seed_guideline(session, guideline="v1")
        capture_explanations_input_hash(session, gid)
        session.commit()

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.guideline = "v2"
        session.commit()

        new_hash = capture_explanations_input_hash(session, gid)
        session.commit()

        row = session.query(TopicContentHash).filter_by(
            book_id=book_id, chapter_key="chapter-5", topic_key="comparing-fractions",
        ).first()
        assert row.explanations_input_hash == new_hash

    def test_returns_none_when_guideline_missing(self, session):
        assert capture_explanations_input_hash(session, "does-not-exist") is None

    def test_returns_none_when_curriculum_tuple_incomplete(self, session):
        _, gid = _seed_guideline(session)
        # Wipe the topic_key so the stable key resolves to None.
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.topic_key = None
        session.commit()
        assert capture_explanations_input_hash(session, gid) is None
        assert session.query(TopicContentHash).count() == 0

    def test_uses_provided_completed_at(self, session):
        _, gid = _seed_guideline(session)
        ts = datetime(2026, 4, 28, 10, 0, 0)
        capture_explanations_input_hash(session, gid, completed_at=ts)
        session.commit()
        row = session.query(TopicContentHash).first()
        assert row.last_explanations_at == ts

    def test_survives_guideline_delete_recreate(self, session):
        """The whole point of this redesign: hash captured against a
        guideline must survive `topic_sync`'s delete-and-recreate."""
        book_id, original_gid = _seed_guideline(
            session, guideline="original chapter text",
        )
        capture_explanations_input_hash(session, original_gid)
        session.commit()
        original_hash = session.query(TopicContentHash).first().explanations_input_hash

        # Simulate `topic_sync._delete_chapter_guidelines` + `_sync_topic`.
        session.query(TeachingGuideline).filter_by(id=original_gid).delete()
        session.commit()
        _, new_gid = _seed_guideline(
            session, book_id=book_id, guideline="rewritten chapter text",
        )

        # Hash row outlives the guideline row.
        row = session.query(TopicContentHash).first()
        assert row is not None
        assert row.explanations_input_hash == original_hash
        # Live hash for the new guideline diverges from the stored one.
        new_guideline = session.query(TeachingGuideline).filter_by(id=new_gid).first()
        assert compute_input_hash_for_guideline(new_guideline) != original_hash


# ───── Terminal-hook integration ─────


def _seed_chapter_and_job(
    session,
    *,
    job_type: str,
    status: str = "completed",
):
    book_id, gid = _seed_guideline(session)
    chapter_id = str(uuid.uuid4())

    session.add(BookChapter(
        id=chapter_id, book_id=book_id, chapter_number=5,
        chapter_title="Fractions", start_page=1, end_page=20,
        status="chapter_completed", total_pages=20, uploaded_page_count=20,
    ))
    job_id = str(uuid.uuid4())
    session.add(ChapterProcessingJob(
        id=job_id, book_id=book_id, chapter_id=chapter_id,
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

        row = session.query(TopicContentHash).first()
        assert row is not None
        assert len(row.explanations_input_hash) == 64

    def test_no_capture_on_explanations_failed(self, session):
        gid, job_id = _seed_chapter_and_job(
            session, job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="failed",
        )
        started = datetime.utcnow() - timedelta(seconds=5)
        _write_topic_stage_run_terminal(session, job_id, started_at=started)

        assert session.query(TopicContentHash).count() == 0

    def test_no_capture_on_other_stages(self, session):
        gid, job_id = _seed_chapter_and_job(
            session, job_type=V2JobType.VISUAL_ENRICHMENT.value,
        )
        started = datetime.utcnow() - timedelta(seconds=5)
        _write_topic_stage_run_terminal(session, job_id, started_at=started)

        assert session.query(TopicContentHash).count() == 0


# ───── Endpoint ─────


@pytest.fixture
def api_with_db():
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
        resp = client.get("/admin/v2/topics/does-not-exist/cross-dag-warnings")
        assert resp.status_code == 404

    def test_empty_warnings_when_hash_never_captured(self, api_with_db):
        client, session = api_with_db
        _, gid = _seed_guideline(session)
        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert resp.json() == {"warnings": []}

    def test_empty_warnings_when_curriculum_tuple_incomplete(self, api_with_db):
        client, session = api_with_db
        _, gid = _seed_guideline(session)
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.topic_key = None
        session.commit()
        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert resp.json() == {"warnings": []}

    def test_empty_warnings_when_hash_matches(self, api_with_db):
        client, session = api_with_db
        _, gid = _seed_guideline(session)
        capture_explanations_input_hash(session, gid)
        session.commit()

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert resp.json() == {"warnings": []}

    def test_warning_when_guideline_text_mutated(self, api_with_db):
        client, session = api_with_db
        _, gid = _seed_guideline(session, guideline="original")
        capture_explanations_input_hash(session, gid)
        session.commit()

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.guideline = "rewritten"
        session.commit()

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["warnings"]) == 1
        assert body["warnings"][0]["kind"] == "chapter_resynced"

    def test_warning_when_topic_title_mutated(self, api_with_db):
        client, session = api_with_db
        _, gid = _seed_guideline(session, topic_title="Original Title")
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
        _, gid = _seed_guideline(session, prior_topics_context="old")
        capture_explanations_input_hash(session, gid)
        session.commit()

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.prior_topics_context = "new"
        session.commit()

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert len(resp.json()["warnings"]) == 1

    def test_warning_when_description_mutated_and_guideline_blank(self, api_with_db):
        """P1 regression: `description` is the LLM input when `guideline` is
        blank, so a `description` mutation must trigger the warning."""
        client, session = api_with_db
        _, gid = _seed_guideline(
            session, guideline="", description="v1",
        )
        capture_explanations_input_hash(session, gid)
        session.commit()

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.description = "v2"
        session.commit()

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert len(resp.json()["warnings"]) == 1

    def test_last_explanations_at_populated_from_hash_row(self, api_with_db):
        client, session = api_with_db
        _, gid = _seed_guideline(session, guideline="orig")
        ts = datetime(2026, 4, 28, 10, 0, 0)
        capture_explanations_input_hash(session, gid, completed_at=ts)
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

    def test_warning_survives_topic_sync_delete_recreate(self, api_with_db):
        """The headline use case: `topic_sync` deletes the existing
        guideline and creates a new one with a fresh uuid + same
        chapter_key/topic_key. The banner must still fire."""
        client, session = api_with_db
        book_id, original_gid = _seed_guideline(
            session, guideline="original chapter text",
        )

        # Successful explanations run captures the hash.
        capture_explanations_input_hash(session, original_gid)
        session.commit()

        # `topic_sync` resync: delete old guideline (FK cascade wipes
        # `topic_stage_runs` history), insert a new one with a fresh
        # uuid + the rewritten chapter content.
        session.query(TeachingGuideline).filter_by(id=original_gid).delete()
        session.commit()
        _, new_gid = _seed_guideline(
            session, book_id=book_id, guideline="rewritten chapter text",
        )

        # The endpoint, hit with the NEW guideline_id, must surface the
        # warning — the hash row outlived the guideline.
        resp = client.get(f"/admin/v2/topics/{new_gid}/cross-dag-warnings")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["warnings"]) == 1
        assert body["warnings"][0]["kind"] == "chapter_resynced"

    def test_warning_clears_when_explanations_reruns(self, api_with_db):
        """End-to-end the banner-clearing contract."""
        client, session = api_with_db
        _, gid = _seed_guideline(session, guideline="v1")
        capture_explanations_input_hash(session, gid)
        session.commit()

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.guideline = "v2"
        session.commit()
        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert len(resp.json()["warnings"]) == 1

        # Re-run explanations → captures new hash → warning clears.
        capture_explanations_input_hash(session, gid)
        session.commit()
        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.json() == {"warnings": []}
