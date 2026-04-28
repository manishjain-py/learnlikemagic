"""Phase 6 integration tests for the topic-pipeline DAG.

These tests exercise the cascade engine + terminal hook + admin v2 API
together, using the FastAPI TestClient against an in-memory SQLite engine.
The narrower unit tests in `tests/unit/test_cascade_orchestrator.py` and
`tests/unit/test_cross_dag_warnings.py` cover individual pieces; this file
verifies the full request → cascade → terminal hook → response loop and
the cross-DAG warning lifecycle as a whole.

Scenarios per plan §7 Phase 6:
- Cascade halt-on-failure end-to-end via the API.
- Cancel mid-cascade via the API.
- Rerun a stage → downstream marked stale → next rerun runs them.
- Cross-DAG warning lifecycle: capture on explanations done → mutation
  surfaces banner → next explanations run clears it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from book_ingestion_v2.api.processing_routes import (
    _write_topic_stage_run_terminal,
)
from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag import cascade as cascade_module
from book_ingestion_v2.dag.launcher_map import (
    JOB_TYPE_TO_STAGE_ID,
    LAUNCHER_BY_STAGE,
)
from book_ingestion_v2.dag.topic_pipeline_dag import DAG
from book_ingestion_v2.models.database import (
    BookChapter,
    ChapterProcessingJob,
)
from book_ingestion_v2.repositories.topic_stage_run_repository import (
    TopicStageRunRepository,
)
from shared.models.entities import Base, Book, TeachingGuideline


# ───── Test infrastructure ─────


@pytest.fixture
def app_db():
    """FastAPI TestClient + a session bound to a thread-safe in-memory SQLite.

    Same plumbing as `test_cascade_orchestrator.api_with_db`, lifted here
    so this file is self-contained and the integration suite doesn't
    couple to a specific unit-test fixture.
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
    session = Session()

    def _override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    cascade_module.reset_cascade_orchestrator()
    client = TestClient(app)
    try:
        yield client, session
    finally:
        cascade_module.reset_cascade_orchestrator()
        app.dependency_overrides.pop(get_db, None)
        session.close()
        Base.metadata.drop_all(engine)


def _seed_topic(session) -> dict:
    book_id = str(uuid.uuid4())
    chapter_id = str(uuid.uuid4())
    guideline_id = str(uuid.uuid4())
    session.add(Book(
        id=book_id, title="T", country="India", board="CBSE", grade=4,
        subject="Mathematics", s3_prefix=f"books/{book_id}/",
    ))
    session.add(BookChapter(
        id=chapter_id, book_id=book_id, chapter_number=5,
        chapter_title="Fractions", start_page=1, end_page=20,
        status="chapter_completed", total_pages=20, uploaded_page_count=20,
    ))
    session.add(TeachingGuideline(
        id=guideline_id, country="India", board="CBSE", grade=4,
        subject="Mathematics", chapter="Fractions",
        topic="Comparing Fractions", guideline="initial guideline text",
        chapter_key="chapter-5", topic_key="comparing-fractions",
        chapter_title="Fractions", topic_title="Comparing Fractions",
        book_id=book_id, review_status="APPROVED", topic_sequence=1,
        prior_topics_context="initial prior context",
    ))
    session.commit()
    return {
        "book_id": book_id, "chapter_id": chapter_id,
        "guideline_id": guideline_id,
    }


@pytest.fixture
def fake_launchers(monkeypatch, app_db):
    """Replace every stage's launcher with a recording stub that takes the
    per-topic lock without spawning a real background thread. Tests drive
    the cascade by manually flipping the resulting job to terminal +
    routing through `_write_topic_stage_run_terminal`."""
    _, session = app_db
    calls: list[dict] = []

    def make_launcher(stage_id: str, job_type: V2JobType):
        def _launcher(db, **kwargs):
            calls.append({"stage_id": stage_id, "kwargs": kwargs})
            from book_ingestion_v2.services.chapter_job_service import (
                ChapterJobService,
            )
            svc = ChapterJobService(db)
            return svc.acquire_lock(
                book_id=kwargs["book_id"],
                chapter_id=kwargs["chapter_id"],
                guideline_id=kwargs["guideline_id"],
                job_type=job_type.value,
            )
        return _launcher

    job_type_by_stage = {
        "explanations": V2JobType.EXPLANATION_GENERATION,
        "baatcheet_dialogue": V2JobType.BAATCHEET_DIALOGUE_GENERATION,
        "baatcheet_visuals": V2JobType.BAATCHEET_VISUAL_ENRICHMENT,
        "visuals": V2JobType.VISUAL_ENRICHMENT,
        "check_ins": V2JobType.CHECK_IN_ENRICHMENT,
        "practice_bank": V2JobType.PRACTICE_BANK_GENERATION,
        "audio_review": V2JobType.AUDIO_TEXT_REVIEW,
        "audio_synthesis": V2JobType.AUDIO_GENERATION,
    }
    for stage_id, jt in job_type_by_stage.items():
        monkeypatch.setitem(LAUNCHER_BY_STAGE, stage_id, make_launcher(stage_id, jt))

    # Pin the cascade orchestrator's session factory to the test session
    # so its `on_stage_complete` reads see the same data we wrote here.
    orch = cascade_module.get_cascade_orchestrator()

    class _Shim:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            pass

    monkeypatch.setattr(orch, "_session_factory", lambda: _Shim(session))
    return calls


def _finish_running_job(
    session,
    guideline_id: str,
    stage_id: str,
    *,
    status: str = "completed",
    error: Optional[str] = None,
):
    """Flip the active job for a stage to terminal + write the matching
    `topic_stage_runs` terminal row. Mirrors what `run_in_background_v2`
    does on stage exit, including the Phase 6 hash capture."""
    job_type = next(
        jt for jt, sid in JOB_TYPE_TO_STAGE_ID.items() if sid == stage_id
    )
    job = (
        session.query(ChapterProcessingJob)
        .filter(
            ChapterProcessingJob.guideline_id == guideline_id,
            ChapterProcessingJob.job_type == job_type,
            ChapterProcessingJob.status.in_(["pending", "running"]),
        )
        .order_by(ChapterProcessingJob.created_at.desc())
        .first()
    )
    assert job is not None, f"no active job for {stage_id}"
    job_id = job.id
    job.status = status
    if error:
        job.error_message = error
    session.commit()

    started_at = datetime.utcnow() - timedelta(seconds=2)
    _write_topic_stage_run_terminal(session, job_id, started_at=started_at)
    return job_id


# ───── Cascade halt-on-failure ─────


class TestCascadeHaltOnFailure:
    def test_failure_halts_cascade_via_api(
        self, app_db, fake_launchers,
    ):
        client, session = app_db
        topic = _seed_topic(session)
        gid = topic["guideline_id"]

        # Kick off the cascade through the rerun API.
        resp = client.post(
            f"/admin/v2/topics/{gid}/stages/explanations/rerun"
        )
        assert resp.status_code == 202

        # Fail the first stage; terminal hook fires `on_stage_complete`.
        _finish_running_job(
            session, gid, "explanations", status="failed", error="boom",
        )

        # Cascade is gone; no more stages launched.
        cascade_resp = client.get(f"/admin/v2/topics/{gid}/dag")
        assert cascade_resp.status_code == 200
        assert cascade_resp.json()["cascade"] is None

        all_launched = [c["stage_id"] for c in fake_launchers]
        assert all_launched == ["explanations"]

        # The DAG view reports `failed` for explanations and leaves
        # downstream stages untouched (still `pending`).
        states = {
            row["stage_id"]: row["state"]
            for row in cascade_resp.json()["stages"]
        }
        assert states["explanations"] == "failed"
        for stage_id in (
            "visuals", "check_ins", "baatcheet_dialogue", "practice_bank",
            "audio_review", "audio_synthesis",
        ):
            assert states[stage_id] == "pending", (
                f"{stage_id} should not have started after halt"
            )


# ───── Cancel mid-cascade ─────


class TestCancelMidCascade:
    def test_cancel_via_api_skips_next_launch(
        self, app_db, fake_launchers,
    ):
        client, session = app_db
        topic = _seed_topic(session)
        gid = topic["guideline_id"]

        client.post(
            f"/admin/v2/topics/{gid}/stages/explanations/rerun"
        )

        # Cancel through the API while explanations is still running.
        cancel_resp = client.post(f"/admin/v2/topics/{gid}/dag/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json() == {"cancelled": True}

        # Finish explanations cleanly. Cascade should not pick up the
        # next stage despite a successful terminal status.
        _finish_running_job(session, gid, "explanations", status="completed")

        all_launched = [c["stage_id"] for c in fake_launchers]
        assert all_launched == ["explanations"]
        assert cascade_module.get_cascade_orchestrator().get_cascade(gid) is None


# ───── Rerun → downstream stale → catch-up ─────


class TestRerunMarksDownstreamStaleAndCatchesUp:
    def test_rerun_explanations_marks_descendants_stale_then_clears_via_run(
        self, app_db, fake_launchers,
    ):
        client, session = app_db
        topic = _seed_topic(session)
        gid = topic["guideline_id"]

        # Seed each non-explanations stage as `done` so we have something
        # to mark stale.
        repo = TopicStageRunRepository(session)
        for s in DAG.stages:
            if s.id == "explanations":
                continue
            repo.upsert_terminal(gid, s.id, state="done", duration_ms=1)
        # Explanations is also `done` to start; rerun cascades from it.
        repo.upsert_terminal(gid, "explanations", state="done", duration_ms=1)

        # Rerun explanations through the API — kickoff marks descendants stale.
        resp = client.post(
            f"/admin/v2/topics/{gid}/stages/explanations/rerun"
        )
        assert resp.status_code == 202

        view = client.get(f"/admin/v2/topics/{gid}/dag").json()
        stale_by_stage = {
            row["stage_id"]: row["is_stale"] for row in view["stages"]
        }
        for stage_id in (
            "visuals", "check_ins", "baatcheet_dialogue", "baatcheet_visuals",
            "practice_bank", "audio_review", "audio_synthesis",
        ):
            assert stale_by_stage[stage_id] is True, (
                f"{stage_id} should be marked stale after rerun"
            )

        # Drive the cascade to completion. Each stage clears its stale
        # flag when it transitions to `done`.
        steps = 0
        orch = cascade_module.get_cascade_orchestrator()
        while orch.get_cascade(gid) is not None and steps < 20:
            cur = orch.get_cascade(gid)
            assert cur is not None
            assert cur.running is not None
            _finish_running_job(session, gid, cur.running)
            steps += 1

        view = client.get(f"/admin/v2/topics/{gid}/dag").json()
        for row in view["stages"]:
            assert row["state"] == "done", (
                f"{row['stage_id']} should be done after cascade"
            )
            assert row["is_stale"] is False, (
                f"{row['stage_id']} should not still be stale"
            )


# ───── Cross-DAG warning lifecycle ─────


class TestCrossDAGWarningLifecycle:
    def test_full_lifecycle_through_terminal_hook_and_endpoint(
        self, app_db, fake_launchers,
    ):
        """Simulates the operator-facing experience end-to-end:

        1. Run explanations → terminal hook captures the input hash.
        2. Cross-DAG warnings endpoint returns no warnings.
        3. Upstream (e.g., topic_sync) mutates the guideline.
        4. Endpoint returns a `chapter_resynced` warning.
        5. Re-run explanations → endpoint returns no warnings.
        """
        client, session = app_db
        topic = _seed_topic(session)
        gid = topic["guideline_id"]

        # Step 1: rerun explanations → finish successfully → terminal
        # hook captures the input hash on the guideline row.
        client.post(f"/admin/v2/topics/{gid}/stages/explanations/rerun")
        _finish_running_job(session, gid, "explanations", status="completed")

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        assert guideline.explanations_input_hash is not None
        original_hash = guideline.explanations_input_hash

        # Cancel the cascade so subsequent rerun calls aren't blocked by
        # it auto-driving descendants. (Halt-on-failure / completion
        # cleanup leaves the next stage running; cancelling is the
        # cleanest way to isolate the cross-DAG flow.)
        client.post(f"/admin/v2/topics/{gid}/dag/cancel")
        # Drain whatever's running so the cascade clears.
        cascade = cascade_module.get_cascade_orchestrator().get_cascade(gid)
        if cascade and cascade.running:
            _finish_running_job(session, gid, cascade.running)

        # Step 2: no mutation yet → no warnings.
        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert resp.json() == {"warnings": []}

        # Step 3: simulate `topic_sync` rewriting the guideline text.
        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        guideline.guideline = "rewritten chapter content"
        session.commit()

        # Step 4: warning fires.
        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        warnings = resp.json()["warnings"]
        assert len(warnings) == 1
        assert warnings[0]["kind"] == "chapter_resynced"
        assert warnings[0]["last_explanations_at"] is not None

        # Step 5: re-run explanations → terminal hook writes the new hash.
        client.post(f"/admin/v2/topics/{gid}/stages/explanations/rerun")
        _finish_running_job(session, gid, "explanations", status="completed")

        guideline = session.query(TeachingGuideline).filter_by(id=gid).first()
        assert guideline.explanations_input_hash != original_hash

        resp = client.get(f"/admin/v2/topics/{gid}/cross-dag-warnings")
        assert resp.status_code == 200
        assert resp.json() == {"warnings": []}
