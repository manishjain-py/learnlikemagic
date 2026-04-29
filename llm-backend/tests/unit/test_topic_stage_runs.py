"""Unit tests for the Phase 2 `topic_stage_runs` machinery.

Covers:
- `TopicStageRunRepository` semantics (upsert_running, upsert_terminal,
  upsert_backfill, mark_stale, list_for_topic, validation).
- The `_write_topic_stage_run_started` / `_write_topic_stage_run_terminal`
  helpers in `processing_routes.py` (the `run_in_background_v2` hook).
- Lazy backfill in `TopicPipelineStatusService.get_pipeline_status` —
  rows appear after a read pass, response shape is unchanged.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from book_ingestion_v2.api.processing_routes import (
    _write_topic_stage_run_started,
    _write_topic_stage_run_terminal,
)
from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag.launcher_map import JOB_TYPE_TO_STAGE_ID
from book_ingestion_v2.models.database import (
    BookChapter,
    ChapterProcessingJob,
    TopicStageRun,
)
from book_ingestion_v2.repositories.topic_stage_run_repository import (
    TopicStageRunRepository,
)
from book_ingestion_v2.services.topic_pipeline_status_service import (
    TopicPipelineStatusService,
)
from shared.models.entities import (
    Book,
    PracticeQuestion,
    TeachingGuideline,
    TopicExplanation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seed_topic(db_session):
    """Minimal book/chapter/topic so FK on guideline_id is satisfiable."""
    book_id = str(uuid.uuid4())
    chapter_id = str(uuid.uuid4())
    guideline_id = str(uuid.uuid4())
    topic_key = "comparing-fractions"
    chapter_number = 3
    chapter_key = f"chapter-{chapter_number}"

    db_session.add(Book(
        id=book_id, title="T", country="India", board="CBSE", grade=3,
        subject="Mathematics", s3_prefix=f"books/{book_id}/",
    ))
    db_session.add(BookChapter(
        id=chapter_id, book_id=book_id, chapter_number=chapter_number,
        chapter_title="Fractions", start_page=1, end_page=20,
        status="chapter_completed", total_pages=20, uploaded_page_count=20,
    ))
    db_session.add(TeachingGuideline(
        id=guideline_id, country="India", board="CBSE", grade=3,
        subject="Mathematics", chapter="Fractions", topic="Comparing Fractions",
        guideline="g", chapter_key=chapter_key, topic_key=topic_key,
        chapter_title="Fractions", topic_title="Comparing Fractions",
        book_id=book_id, review_status="APPROVED", topic_sequence=1,
    ))
    db_session.commit()
    return {
        "book_id": book_id, "chapter_id": chapter_id,
        "guideline_id": guideline_id, "topic_key": topic_key,
    }


def _add_job(
    db,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str | None,
    job_type: str,
    status: str = "pending",
    error: str | None = None,
):
    job = ChapterProcessingJob(
        id=str(uuid.uuid4()),
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=job_type,
        status=status,
        error_message=error,
    )
    db.add(job)
    db.commit()
    return job


# ---------------------------------------------------------------------------
# TopicStageRunRepository
# ---------------------------------------------------------------------------


class TestRepositoryUpsertRunning:
    def test_creates_row_when_missing(self, db_session, seed_topic):
        repo = TopicStageRunRepository(db_session)
        row = repo.upsert_running(
            seed_topic["guideline_id"],
            "explanations",
            job_id="j1",
        )
        assert row.state == "running"
        assert row.last_job_id == "j1"
        assert row.started_at is not None
        assert row.completed_at is None
        assert row.duration_ms is None

    def test_clears_terminal_data_on_rerun(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "explanations", job_id="j1")
        repo.upsert_terminal(
            gid, "explanations",
            state="done",
            duration_ms=5000,
            summary={"variant_count": 2},
            last_job_id="j1",
        )

        row = repo.upsert_running(gid, "explanations", job_id="j2")
        assert row.state == "running"
        assert row.last_job_id == "j2"
        assert row.completed_at is None
        assert row.duration_ms is None
        assert row.summary_json is None

    def test_preserves_is_stale_across_running(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "visuals", job_id="j1")
        repo.mark_stale(gid, "visuals", is_stale=True)

        row = repo.upsert_running(gid, "visuals", job_id="j2")
        assert row.is_stale is True


class TestRepositoryUpsertTerminal:
    def test_done_clears_is_stale(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "visuals", job_id="j1")
        repo.mark_stale(gid, "visuals", is_stale=True)

        row = repo.upsert_terminal(
            gid, "visuals", state="done", duration_ms=1234, last_job_id="j1",
        )
        assert row.state == "done"
        assert row.is_stale is False
        assert row.duration_ms == 1234

    def test_failed_preserves_is_stale(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "visuals", job_id="j1")
        repo.mark_stale(gid, "visuals", is_stale=True)

        row = repo.upsert_terminal(
            gid, "visuals", state="failed", duration_ms=900, last_job_id="j1",
        )
        assert row.state == "failed"
        assert row.is_stale is True

    def test_rejects_non_terminal_state(self, db_session, seed_topic):
        repo = TopicStageRunRepository(db_session)
        with pytest.raises(ValueError):
            repo.upsert_terminal(
                seed_topic["guideline_id"], "explanations",
                state="running",
            )

    def test_backfills_started_at_when_missing(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        # No upsert_running first — terminal write must populate started_at.
        started = datetime.utcnow() - timedelta(seconds=10)
        row = repo.upsert_terminal(
            gid, "explanations",
            state="done", duration_ms=10000, started_at=started,
        )
        assert row.started_at == started

    def test_does_not_overwrite_started_at_when_present(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "explanations", job_id="j1")
        original_started = repo.get(gid, "explanations").started_at

        later = datetime.utcnow() + timedelta(seconds=60)
        repo.upsert_terminal(
            gid, "explanations",
            state="done", duration_ms=1000, started_at=later,
        )
        assert repo.get(gid, "explanations").started_at == original_started

    def test_summary_persisted(self, db_session, seed_topic):
        repo = TopicStageRunRepository(db_session)
        row = repo.upsert_terminal(
            seed_topic["guideline_id"], "practice_bank",
            state="done", duration_ms=100,
            summary={"question_count": 35, "review_passes": 2},
        )
        assert row.summary_json == {"question_count": 35, "review_passes": 2}


class TestRepositoryReadAndStale:
    def test_get_returns_none_when_missing(self, db_session, seed_topic):
        repo = TopicStageRunRepository(db_session)
        assert repo.get(seed_topic["guideline_id"], "explanations") is None

    def test_list_for_topic(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "explanations", job_id="j1")
        repo.upsert_running(gid, "visuals", job_id="j2")
        rows = repo.list_for_topic(gid)
        assert {r.stage_id for r in rows} == {"explanations", "visuals"}

    def test_mark_stale_no_op_when_row_missing(self, db_session, seed_topic):
        repo = TopicStageRunRepository(db_session)
        assert repo.mark_stale(seed_topic["guideline_id"], "explanations") is None

    def test_upsert_backfill_creates_minimal_row(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        completed = datetime.utcnow()
        row = repo.upsert_backfill(
            gid, "explanations",
            state="done",
            completed_at=completed,
            last_job_id="historical-job",
        )
        assert row.state == "done"
        assert row.completed_at == completed
        assert row.last_job_id == "historical-job"
        assert row.started_at is None
        assert row.duration_ms is None

    def test_upsert_backfill_is_idempotent(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_backfill(gid, "visuals", state="done")
        repo.upsert_backfill(gid, "visuals", state="done")
        assert len(repo.list_for_topic(gid)) == 1


# ---------------------------------------------------------------------------
# JOB_TYPE_TO_STAGE_ID coverage
# ---------------------------------------------------------------------------


class TestJobTypeToStageIdMap:
    def test_every_dag_stage_has_mapping(self):
        # The 10 DAG stages map to 10 V2 job types — both Baatcheet audio
        # stages are now first-class DAG nodes with their own job types.
        assert len(JOB_TYPE_TO_STAGE_ID) == 10
        assert V2JobType.BAATCHEET_AUDIO_REVIEW.value in JOB_TYPE_TO_STAGE_ID
        assert V2JobType.BAATCHEET_AUDIO_GENERATION.value in JOB_TYPE_TO_STAGE_ID

    def test_all_mapped_stage_ids_are_unique(self):
        assert len(set(JOB_TYPE_TO_STAGE_ID.values())) == len(JOB_TYPE_TO_STAGE_ID)


# ---------------------------------------------------------------------------
# run_in_background_v2 hook helpers
# ---------------------------------------------------------------------------


class TestHookStartedWriter:
    def test_writes_running_row_for_topic_stage_job(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        job = _add_job(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="running",
        )
        started = datetime.utcnow()
        _write_topic_stage_run_started(db_session, job.id, started_at=started)

        row = TopicStageRunRepository(db_session).get(gid, "explanations")
        assert row is not None
        assert row.state == "running"
        assert row.last_job_id == job.id
        assert row.started_at == started

    def test_skips_when_guideline_id_is_null(self, db_session, seed_topic):
        # Chapter-scope job — guideline_id is NULL. Hook must not write anything.
        job = _add_job(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=None,
            job_type=V2JobType.OCR.value,
            status="running",
        )
        _write_topic_stage_run_started(db_session, job.id, started_at=datetime.utcnow())
        assert db_session.query(TopicStageRun).count() == 0

    def test_skips_unknown_job_type(self, db_session, seed_topic):
        # REFRESHER_GENERATION is not in the topic DAG → hook must skip
        # silently. (Both Baatcheet audio job types are now first-class DAG
        # stages and therefore mapped, so we use a different unknown-to-DAG
        # job type here.)
        job = _add_job(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=seed_topic["guideline_id"],
            job_type=V2JobType.REFRESHER_GENERATION.value,
            status="running",
        )
        _write_topic_stage_run_started(db_session, job.id, started_at=datetime.utcnow())
        assert db_session.query(TopicStageRun).count() == 0

    def test_skips_when_job_missing(self, db_session, seed_topic):
        _write_topic_stage_run_started(
            db_session, "nonexistent-job-id", started_at=datetime.utcnow(),
        )
        assert db_session.query(TopicStageRun).count() == 0


class TestHookTerminalWriter:
    def _make_running(self, db, seed, job_type):
        job = _add_job(
            db,
            book_id=seed["book_id"],
            chapter_id=seed["chapter_id"],
            guideline_id=seed["guideline_id"],
            job_type=job_type,
            status="running",
        )
        started = datetime.utcnow() - timedelta(seconds=12)
        _write_topic_stage_run_started(db, job.id, started_at=started)
        return job, started

    def test_done_for_completed_job(self, db_session, seed_topic):
        job, started = self._make_running(
            db_session, seed_topic, V2JobType.EXPLANATION_GENERATION.value,
        )
        job.status = "completed"
        db_session.commit()

        _write_topic_stage_run_terminal(db_session, job.id, started_at=started)
        row = TopicStageRunRepository(db_session).get(
            seed_topic["guideline_id"], "explanations",
        )
        assert row.state == "done"
        assert row.completed_at is not None
        assert row.duration_ms >= 12000  # at least 12s elapsed
        assert row.last_job_id == job.id

    def test_done_for_completed_with_errors_job(self, db_session, seed_topic):
        job, started = self._make_running(
            db_session, seed_topic, V2JobType.VISUAL_ENRICHMENT.value,
        )
        job.status = "completed_with_errors"
        db_session.commit()

        _write_topic_stage_run_terminal(db_session, job.id, started_at=started)
        row = TopicStageRunRepository(db_session).get(
            seed_topic["guideline_id"], "visuals",
        )
        assert row.state == "done"

    def test_failed_for_failed_job(self, db_session, seed_topic):
        job, started = self._make_running(
            db_session, seed_topic, V2JobType.PRACTICE_BANK_GENERATION.value,
        )
        job.status = "failed"
        job.error_message = "LLM timeout"
        db_session.commit()

        _write_topic_stage_run_terminal(db_session, job.id, started_at=started)
        row = TopicStageRunRepository(db_session).get(
            seed_topic["guideline_id"], "practice_bank",
        )
        assert row.state == "failed"
        assert row.summary_json == {"error": "LLM timeout"}

    def test_override_state_wins(self, db_session, seed_topic):
        # Exception path: override_state="failed" + error_summary.
        job, started = self._make_running(
            db_session, seed_topic, V2JobType.AUDIO_GENERATION.value,
        )
        # Job row still says "running" (we crashed before release_lock could
        # update it) — override_state must steer the terminal write.
        _write_topic_stage_run_terminal(
            db_session, job.id,
            started_at=started,
            override_state="failed",
            error_summary="boom",
        )
        row = TopicStageRunRepository(db_session).get(
            seed_topic["guideline_id"], "audio_synthesis",
        )
        assert row.state == "failed"
        assert row.summary_json == {"error": "boom"}

    def test_skipped_when_job_still_running_and_no_override(self, db_session, seed_topic):
        # Edge case: target_fn returned without releasing the lock and no
        # override. Hook logs a warning and skips the terminal write — leaving
        # the row in 'running' is correct because we don't know what happened.
        job, started = self._make_running(
            db_session, seed_topic, V2JobType.CHECK_IN_ENRICHMENT.value,
        )
        _write_topic_stage_run_terminal(db_session, job.id, started_at=started)
        row = TopicStageRunRepository(db_session).get(
            seed_topic["guideline_id"], "check_ins",
        )
        # Stays at 'running' from the started write.
        assert row.state == "running"


# ---------------------------------------------------------------------------
# Lazy backfill via TopicPipelineStatusService
# ---------------------------------------------------------------------------


class TestStatusServiceLazyBackfill:
    def _add_explanation(self, db, gid):
        expl = TopicExplanation(
            id=str(uuid.uuid4()), guideline_id=gid,
            variant_key="A", variant_label="Variant A",
            cards_json=[{"card_type": "explain"}],
        )
        db.add(expl)
        db.commit()
        return expl

    def test_backfill_writes_done_row_for_terminal_stage(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        self._add_explanation(db_session, gid)

        svc = TopicPipelineStatusService(db_session)
        svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"], seed_topic["topic_key"],
        )

        rows = TopicStageRunRepository(db_session).list_for_topic(gid)
        by_stage = {r.stage_id: r for r in rows}
        # explanations is "done" (artifact present); downstream stages are
        # "blocked"/"ready" so they're not backfilled. Backfill only writes
        # 'done' / 'failed' rows in Phase 2.
        assert "explanations" in by_stage
        assert by_stage["explanations"].state == "done"

    def test_backfill_writes_failed_row(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        self._add_explanation(db_session, gid)
        # A failed visuals job (no artifact yet) → status_check returns "failed".
        _add_job(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=gid,  # historical overload — status service handles it
            guideline_id=None,
            job_type=V2JobType.VISUAL_ENRICHMENT.value,
            status="failed",
            error="pixi compile failed",
        )

        svc = TopicPipelineStatusService(db_session)
        svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"], seed_topic["topic_key"],
        )
        row = TopicStageRunRepository(db_session).get(gid, "visuals")
        assert row is not None
        assert row.state == "failed"

    def test_backfill_does_not_overwrite_existing_row(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        self._add_explanation(db_session, gid)

        # Pre-existing row with rich data (e.g. duration captured by the hook).
        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "explanations", job_id="prior-job")
        repo.upsert_terminal(
            gid, "explanations",
            state="done",
            duration_ms=4321,
            summary={"variant_count": 2},
            last_job_id="prior-job",
        )

        svc = TopicPipelineStatusService(db_session)
        svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"], seed_topic["topic_key"],
        )
        row = repo.get(gid, "explanations")
        assert row.duration_ms == 4321  # untouched by backfill
        assert row.summary_json == {"variant_count": 2}
        assert row.last_job_id == "prior-job"

    def test_backfill_skips_non_terminal_states(self, db_session, seed_topic):
        # Fresh topic — explanations="ready", everything else="blocked". No
        # terminal stages → no backfill rows.
        svc = TopicPipelineStatusService(db_session)
        svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"], seed_topic["topic_key"],
        )
        rows = TopicStageRunRepository(db_session).list_for_topic(
            seed_topic["guideline_id"]
        )
        assert rows == []

    def test_backfill_failure_does_not_break_read(self, db_session, seed_topic, monkeypatch):
        gid = seed_topic["guideline_id"]
        self._add_explanation(db_session, gid)

        # Force the backfill helper to raise.
        def boom(self, *args, **kwargs):
            raise RuntimeError("simulated DB outage")

        monkeypatch.setattr(
            TopicStageRunRepository, "list_for_topic", boom,
        )

        svc = TopicPipelineStatusService(db_session)
        # Read must still succeed.
        resp = svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"], seed_topic["topic_key"],
        )
        assert resp.guideline_id == gid
        assert len(resp.stages) == 10


# ---------------------------------------------------------------------------
# Existing dashboard rendering — regression
# ---------------------------------------------------------------------------


class TestPostSyncJobTypesBaatcheetCapture:
    """Reviewer1 P1.1 regression — Baatcheet stages must keep their
    guideline_id through `acquire_lock` so the Phase 2 hook can write a
    topic_stage_runs row. Pre-fix, BAATCHEET_DIALOGUE_GENERATION wasn't in
    POST_SYNC_JOB_TYPES, so acquire_lock forced guideline_id=None.
    """

    @pytest.mark.parametrize("job_type,expected_stage_id", [
        (V2JobType.BAATCHEET_DIALOGUE_GENERATION.value, "baatcheet_dialogue"),
        (V2JobType.BAATCHEET_VISUAL_ENRICHMENT.value, "baatcheet_visuals"),
    ])
    def test_baatcheet_stage_captured_via_acquire_lock(
        self, db_session, seed_topic, job_type, expected_stage_id,
    ):
        from book_ingestion_v2.services.chapter_job_service import ChapterJobService

        job_id = ChapterJobService(db_session).acquire_lock(
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=seed_topic["guideline_id"],
            job_type=job_type,
        )

        job = db_session.query(ChapterProcessingJob).filter_by(id=job_id).first()
        assert job.guideline_id == seed_topic["guideline_id"], (
            "Baatcheet job must retain guideline_id — POST_SYNC_JOB_TYPES gap"
        )

        _write_topic_stage_run_started(db_session, job_id, started_at=datetime.utcnow())
        row = TopicStageRunRepository(db_session).get(
            seed_topic["guideline_id"], expected_stage_id,
        )
        assert row is not None
        assert row.state == "running"
        assert row.last_job_id == job_id


class TestObservabilityWriteFailureIsolation:
    """Reviewer1 P1.2 regression — a failing topic_stage_runs write must not
    leave the caller's session in a poisoned PendingRollbackError state.
    The hook helpers rollback in their broad except so the session stays
    usable for follow-up work (target_fn, request handling).
    """

    def test_started_write_failure_rolls_back_session(
        self, db_session, seed_topic, monkeypatch,
    ):
        job = _add_job(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=seed_topic["guideline_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="running",
        )

        # Simulate a DB error during the running upsert.
        def boom(self, *args, **kwargs):
            raise RuntimeError("simulated commit failure")
        monkeypatch.setattr(
            TopicStageRunRepository, "upsert_running", boom,
        )

        # The helper must swallow the error and leave the session usable —
        # subsequent reads on db_session should not raise.
        _write_topic_stage_run_started(
            db_session, job.id, started_at=datetime.utcnow(),
        )
        # Smoke: session still usable.
        db_session.query(ChapterProcessingJob).count()

    def test_terminal_write_failure_rolls_back_session(
        self, db_session, seed_topic, monkeypatch,
    ):
        job = _add_job(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=seed_topic["guideline_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="completed",
        )

        def boom(self, *args, **kwargs):
            raise RuntimeError("simulated commit failure")
        monkeypatch.setattr(
            TopicStageRunRepository, "upsert_terminal", boom,
        )

        _write_topic_stage_run_terminal(
            db_session, job.id, started_at=datetime.utcnow() - timedelta(seconds=1),
        )
        db_session.query(ChapterProcessingJob).count()


class TestStuckRunningReconciliation:
    """Reviewer1 P2 — a row stuck at `running` whose `last_job_id` is now
    terminal must be reconciled by the lazy backfill. Otherwise heartbeat
    reaping leaves the row mismatched and Phase 3 cascade reads garbage.
    """

    def _add_explanation(self, db, gid):
        expl = TopicExplanation(
            id=str(uuid.uuid4()), guideline_id=gid,
            variant_key="A", variant_label="Variant A",
            cards_json=[{"card_type": "explain"}],
        )
        db.add(expl)
        db.commit()

    def test_running_row_reconciled_when_job_failed(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        self._add_explanation(db_session, gid)

        # Seed: failed job + stuck-running topic_stage_runs row.
        started = datetime.utcnow() - timedelta(seconds=30)
        completed = datetime.utcnow()
        job = _add_job(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="failed",
            error="heartbeat stale",
        )
        job.started_at = started
        job.completed_at = completed
        db_session.commit()

        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "explanations", job_id=job.id, started_at=started)

        svc = TopicPipelineStatusService(db_session)
        svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"], seed_topic["topic_key"],
        )

        row = repo.get(gid, "explanations")
        assert row.state == "failed"
        assert row.completed_at == completed
        assert row.duration_ms == 30000
        assert row.summary_json == {
            "error": "heartbeat stale", "reconciled": True,
        }
        assert row.last_job_id == job.id

    def test_running_row_reconciled_when_job_completed(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        self._add_explanation(db_session, gid)

        started = datetime.utcnow() - timedelta(seconds=15)
        completed = datetime.utcnow()
        job = _add_job(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            job_type=V2JobType.VISUAL_ENRICHMENT.value,
            status="completed",
        )
        job.started_at = started
        job.completed_at = completed
        db_session.commit()

        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "visuals", job_id=job.id, started_at=started)

        svc = TopicPipelineStatusService(db_session)
        svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"], seed_topic["topic_key"],
        )

        row = repo.get(gid, "visuals")
        assert row.state == "done"
        assert row.duration_ms == 15000
        assert row.summary_json == {"reconciled": True}

    def test_running_row_left_alone_when_job_still_running(
        self, db_session, seed_topic,
    ):
        gid = seed_topic["guideline_id"]
        self._add_explanation(db_session, gid)

        job = _add_job(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="running",
        )
        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "explanations", job_id=job.id)

        svc = TopicPipelineStatusService(db_session)
        svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"], seed_topic["topic_key"],
        )

        row = repo.get(gid, "explanations")
        assert row.state == "running"  # not reconciled — job is still live

    def test_running_row_left_alone_when_job_missing(self, db_session, seed_topic):
        # Job was hard-deleted; row points at a no-longer-existent job_id.
        # Reconciliation should skip silently rather than blow up.
        gid = seed_topic["guideline_id"]
        self._add_explanation(db_session, gid)

        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "explanations", job_id="ghost-job-id")

        svc = TopicPipelineStatusService(db_session)
        svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"], seed_topic["topic_key"],
        )

        row = repo.get(gid, "explanations")
        assert row.state == "running"


class TestUpsertBackfillStateValidation:
    """Reviewer2 minor #2 — upsert_backfill must reject non-terminal states
    so a future caller can't write garbage."""

    def test_rejects_running_state(self, db_session, seed_topic):
        repo = TopicStageRunRepository(db_session)
        with pytest.raises(ValueError):
            repo.upsert_backfill(
                seed_topic["guideline_id"], "explanations", state="running",
            )

    def test_rejects_pending_state(self, db_session, seed_topic):
        repo = TopicStageRunRepository(db_session)
        with pytest.raises(ValueError):
            repo.upsert_backfill(
                seed_topic["guideline_id"], "explanations", state="pending",
            )


class TestDashboardRenderingUnchanged:
    """Phase 2 acceptance: existing dashboards render identically.

    Backfill is a write-only side effect — `StageStatus` shape and counts
    must match what Phase 1 produced.
    """

    def test_chapter_summary_counts_unchanged_after_backfill(
        self, db_session, seed_topic
    ):
        gid = seed_topic["guideline_id"]
        db_session.add(TopicExplanation(
            id=str(uuid.uuid4()), guideline_id=gid,
            variant_key="A", variant_label="Variant A",
            cards_json=[{"card_type": "explain"}],
        ))
        db_session.commit()

        svc = TopicPipelineStatusService(db_session)
        # First call writes backfill rows.
        first = svc.get_chapter_summary(seed_topic["book_id"], seed_topic["chapter_id"])
        # Second call reads with rows present — must produce identical counts.
        second = svc.get_chapter_summary(seed_topic["book_id"], seed_topic["chapter_id"])

        assert first.chapter_totals == second.chapter_totals
        assert (
            first.topics[0].stage_counts == second.topics[0].stage_counts
        )
