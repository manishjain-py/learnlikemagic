"""Unit tests for the Phase 3 cascade orchestrator.

Covers:
- Pending-set computation (rerun-from-stage vs run-all).
- `_ready_in_pending` semantics (deps must be `done` AND not in pending).
- `start_cascade` + `on_stage_complete` event chain.
- Halt-on-failure clears the queue.
- Soft-cancel respects in-flight stage and skips next launch.
- Lock collision during start_cascade bubbles `ChapterJobLockError`.
- Stale flagging on descendants when cascade kicks off.
- Read-order overlay surfaces `is_stale` from the row.
- Terminal hook fires `on_stage_complete`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

import pytest

from book_ingestion_v2.api.processing_routes import (
    _write_topic_stage_run_terminal,
)
from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.dag import cascade as cascade_module
from book_ingestion_v2.dag.cascade import (
    CascadeAlreadyActiveError,
    CascadeNotReadyError,
    CascadeOrchestrator,
    build_launcher_kwargs,
)
from book_ingestion_v2.dag.launcher_map import LAUNCHER_BY_STAGE
from book_ingestion_v2.dag.topic_pipeline_dag import DAG
from book_ingestion_v2.models.database import (
    BookChapter,
    ChapterProcessingJob,
    TopicStageRun,
)
from book_ingestion_v2.repositories.topic_stage_run_repository import (
    TopicStageRunRepository,
)
from book_ingestion_v2.services.chapter_job_service import ChapterJobLockError
from book_ingestion_v2.services.topic_pipeline_status_service import (
    TopicPipelineStatusService,
)
from shared.models.entities import Book, TeachingGuideline, TopicExplanation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seed_topic(db_session):
    """A book + chapter + guideline so cascade has a real topic to run on."""
    book_id = str(uuid.uuid4())
    chapter_id = str(uuid.uuid4())
    guideline_id = str(uuid.uuid4())
    chapter_number = 5
    chapter_key = f"chapter-{chapter_number}"

    db_session.add(Book(
        id=book_id, title="T", country="India", board="CBSE", grade=4,
        subject="Mathematics", s3_prefix=f"books/{book_id}/",
    ))
    db_session.add(BookChapter(
        id=chapter_id, book_id=book_id, chapter_number=chapter_number,
        chapter_title="Fractions", start_page=1, end_page=20,
        status="chapter_completed", total_pages=20, uploaded_page_count=20,
    ))
    db_session.add(TeachingGuideline(
        id=guideline_id, country="India", board="CBSE", grade=4,
        subject="Mathematics", chapter="Fractions",
        topic="Comparing Fractions",
        guideline="g", chapter_key=chapter_key,
        topic_key="comparing-fractions",
        chapter_title="Fractions", topic_title="Comparing Fractions",
        book_id=book_id, review_status="APPROVED", topic_sequence=1,
    ))
    db_session.commit()
    return {
        "book_id": book_id, "chapter_id": chapter_id,
        "guideline_id": guideline_id, "topic_key": "comparing-fractions",
    }


@pytest.fixture
def fresh_orchestrator():
    """Fresh CascadeOrchestrator that uses the in-memory test session."""
    return CascadeOrchestrator()


@pytest.fixture
def reset_singleton():
    """Drop the module-level orchestrator before/after each test that uses
    the terminal hook (which goes through the singleton)."""
    cascade_module.reset_cascade_orchestrator()
    yield
    cascade_module.reset_cascade_orchestrator()


def _no_close_factory(session):
    """Return a session factory that yields the test session without
    letting the cascade's `finally: db.close()` detach our ORM
    instances. The conftest tears the session down at fixture exit."""

    class _Shim:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            pass

    return lambda: _Shim(session)


@pytest.fixture
def fake_launchers(monkeypatch, db_session, seed_topic):
    """Replace every stage's launcher with a recording stub.

    Each launcher inserts a `chapter_processing_jobs` row to acquire the
    per-topic lock (so the real lock semantics work) but does NOT spawn a
    background thread. Tests drive the cascade by manually flipping that
    job to terminal + calling `on_stage_complete`.
    """
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
    return calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finish_running_job(
    db,
    guideline_id: str,
    stage_id: str,
    *,
    status: str = "completed",
    error: Optional[str] = None,
):
    """Flip the latest active job for a stage to a terminal status,
    write the matching `topic_stage_runs` terminal row, and return the
    job_id. Mirrors what `run_in_background_v2` does on stage exit."""
    from book_ingestion_v2.dag.launcher_map import JOB_TYPE_TO_STAGE_ID

    job_type = next(
        jt for jt, sid in JOB_TYPE_TO_STAGE_ID.items() if sid == stage_id
    )
    job = (
        db.query(ChapterProcessingJob)
        .filter(
            ChapterProcessingJob.guideline_id == guideline_id,
            ChapterProcessingJob.job_type == job_type,
            ChapterProcessingJob.status.in_(["pending", "running"]),
        )
        .order_by(ChapterProcessingJob.created_at.desc())
        .first()
    )
    assert job is not None, f"no active job for {stage_id}"
    # Snapshot before any commit — the cascade hook below may issue
    # commits that expire ORM instances.
    job_id = job.id
    job.status = status
    if error:
        job.error_message = error
    db.commit()

    started_at = datetime.utcnow() - timedelta(seconds=2)
    _write_topic_stage_run_terminal(db, job_id, started_at=started_at)
    return job_id


# ---------------------------------------------------------------------------
# build_launcher_kwargs
# ---------------------------------------------------------------------------


class TestBuildLauncherKwargs:
    def test_explanations_includes_mode_and_force(self):
        kw = build_launcher_kwargs(
            "explanations", book_id="b", chapter_id="c", guideline_id="g",
            force=True,
        )
        assert kw["force"] is True
        assert kw["mode"] == "generate"
        assert kw["review_rounds"] == 2  # balanced default

    def test_audio_synthesis_minimal(self):
        kw = build_launcher_kwargs(
            "audio_synthesis", book_id="b", chapter_id="c", guideline_id="g",
        )
        assert kw == {"book_id": "b", "chapter_id": "c", "guideline_id": "g"}

    def test_audio_review_passes_language_none(self):
        kw = build_launcher_kwargs(
            "audio_review", book_id="b", chapter_id="c", guideline_id="g",
        )
        assert kw["language"] is None

    def test_quality_level_fast_zeros_review_rounds(self):
        kw = build_launcher_kwargs(
            "explanations", book_id="b", chapter_id="c", guideline_id="g",
            quality_level="fast",
        )
        assert kw["review_rounds"] == 0


# ---------------------------------------------------------------------------
# Pending-set computation
# ---------------------------------------------------------------------------


class TestComputePending:
    def test_rerun_from_explanations_includes_all_descendants(
        self, fresh_orchestrator
    ):
        pending = fresh_orchestrator._compute_pending(
            state_map={}, stale_set=set(), from_stage_id="explanations",
        )
        assert pending == {s.id for s in DAG.stages}

    def test_rerun_from_audio_review_includes_only_audio_synthesis(
        self, fresh_orchestrator
    ):
        pending = fresh_orchestrator._compute_pending(
            state_map={}, stale_set=set(), from_stage_id="audio_review",
        )
        assert pending == {"audio_review", "audio_synthesis"}

    def test_run_all_excludes_done_stages(self, fresh_orchestrator):
        state_map = {"explanations": "done", "visuals": "done"}
        pending = fresh_orchestrator._compute_pending(
            state_map=state_map, stale_set=set(), from_stage_id=None,
        )
        assert "explanations" not in pending
        assert "visuals" not in pending
        assert "check_ins" in pending  # no row → pending

    def test_run_all_includes_stale_done_rows(self, fresh_orchestrator):
        # `visuals` is `done` in state_map but flagged stale — per
        # plan §2 decision 16, stale-and-done counts as not-done.
        state_map = {"explanations": "done", "visuals": "done"}
        pending = fresh_orchestrator._compute_pending(
            state_map=state_map, stale_set={"visuals"}, from_stage_id=None,
        )
        assert "visuals" in pending
        assert "explanations" not in pending  # not stale, stays done

    def test_unknown_stage_id_raises(self, fresh_orchestrator):
        with pytest.raises(ValueError):
            fresh_orchestrator._compute_pending(
                state_map={}, stale_set=set(),
                from_stage_id="not_a_real_stage",
            )


# ---------------------------------------------------------------------------
# _ready_in_pending
# ---------------------------------------------------------------------------


class TestReadyInPending:
    def _make_cascade(self, pending: set[str]):
        return cascade_module.CascadeState(
            cascade_id="c1", book_id="b", chapter_id="c", guideline_id="g",
            quality_level="balanced", force_first=True, pending=set(pending),
        )

    def test_dep_in_pending_blocks(self, fresh_orchestrator):
        cascade = self._make_cascade({"explanations", "visuals"})
        # state_map says explanations is done, but it's still in pending →
        # not satisfied.
        ready = fresh_orchestrator._ready_in_pending(
            cascade, state_map={"explanations": "done", "visuals": "pending"},
        )
        assert "visuals" not in ready
        assert "explanations" in ready  # has no deps

    def test_dep_done_and_not_in_pending(self, fresh_orchestrator):
        cascade = self._make_cascade({"visuals"})
        ready = fresh_orchestrator._ready_in_pending(
            cascade, state_map={"explanations": "done", "visuals": "pending"},
        )
        assert ready == ["visuals"]

    def test_audio_synthesis_ready_only_after_audio_review(self, fresh_orchestrator):
        cascade = self._make_cascade({"audio_synthesis"})
        ready = fresh_orchestrator._ready_in_pending(
            cascade, state_map={"audio_review": "running"},
        )
        assert ready == []
        ready = fresh_orchestrator._ready_in_pending(
            cascade, state_map={"audio_review": "done"},
        )
        assert ready == ["audio_synthesis"]


# ---------------------------------------------------------------------------
# start_cascade end-to-end (with fake launchers)
# ---------------------------------------------------------------------------


class TestStartCascadeFromExplanations:
    def test_pending_set_covers_every_stage(
        self, db_session, seed_topic, fake_launchers,
    ):
        orch = CascadeOrchestrator()
        cascade = orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=seed_topic["guideline_id"],
            from_stage_id="explanations",
        )
        assert cascade.pending == {s.id for s in DAG.stages}
        assert cascade.running == "explanations"

    def test_first_launch_uses_force_true(
        self, db_session, seed_topic, fake_launchers,
    ):
        orch = CascadeOrchestrator()
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=seed_topic["guideline_id"],
            from_stage_id="explanations",
            force=True,
        )
        assert fake_launchers[-1]["stage_id"] == "explanations"
        assert fake_launchers[-1]["kwargs"]["force"] is True

    def test_marks_descendants_stale_on_existing_done_rows(
        self, db_session, seed_topic, fake_launchers,
    ):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        # Pretend visuals + check_ins were previously done.
        repo.upsert_terminal(gid, "visuals", state="done", duration_ms=100)
        repo.upsert_terminal(gid, "check_ins", state="done", duration_ms=100)

        orch = CascadeOrchestrator()
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
        )
        assert repo.get(gid, "visuals").is_stale is True
        assert repo.get(gid, "check_ins").is_stale is True

    def test_already_active_raises(
        self, db_session, seed_topic, fake_launchers,
    ):
        orch = CascadeOrchestrator()
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=seed_topic["guideline_id"],
            from_stage_id="explanations",
        )
        with pytest.raises(CascadeAlreadyActiveError):
            orch.start_cascade(
                db_session,
                book_id=seed_topic["book_id"],
                chapter_id=seed_topic["chapter_id"],
                guideline_id=seed_topic["guideline_id"],
                from_stage_id="explanations",
            )

    def test_lock_collision_propagates_and_clears_state(
        self, db_session, seed_topic, monkeypatch,
    ):
        # First, occupy the per-topic lock with an existing running job.
        from book_ingestion_v2.services.chapter_job_service import ChapterJobService

        ChapterJobService(db_session).acquire_lock(
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=seed_topic["guideline_id"],
            job_type=V2JobType.VISUAL_ENRICHMENT.value,
        )

        # Replace explanations launcher with a real-ish one that goes
        # through acquire_lock and will collide with the running job.
        def real_lock_launcher(db, **kwargs):
            from book_ingestion_v2.services.chapter_job_service import (
                ChapterJobService as _Svc,
            )
            return _Svc(db).acquire_lock(
                book_id=kwargs["book_id"],
                chapter_id=kwargs["chapter_id"],
                guideline_id=kwargs["guideline_id"],
                job_type=V2JobType.EXPLANATION_GENERATION.value,
            )
        monkeypatch.setitem(LAUNCHER_BY_STAGE, "explanations", real_lock_launcher)

        orch = CascadeOrchestrator()
        with pytest.raises(ChapterJobLockError):
            orch.start_cascade(
                db_session,
                book_id=seed_topic["book_id"],
                chapter_id=seed_topic["chapter_id"],
                guideline_id=seed_topic["guideline_id"],
                from_stage_id="explanations",
            )
        # State was cleaned up — no orphan cascade entry.
        assert orch.get_cascade(seed_topic["guideline_id"]) is None

    def test_lock_collision_does_not_commit_stale_flags(
        self, db_session, seed_topic, monkeypatch,
    ):
        # Pre-existing done rows on descendants — these would get
        # is_stale=True if cascade marked stale before launching.
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_terminal(gid, "visuals", state="done", duration_ms=100)
        repo.upsert_terminal(gid, "check_ins", state="done", duration_ms=100)

        # Occupy the per-topic lock so the explanations launch fails.
        from book_ingestion_v2.services.chapter_job_service import (
            ChapterJobService as _Svc,
        )
        _Svc(db_session).acquire_lock(
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            job_type=V2JobType.VISUAL_ENRICHMENT.value,
        )

        def real_lock_launcher(db, **kwargs):
            return _Svc(db).acquire_lock(
                book_id=kwargs["book_id"],
                chapter_id=kwargs["chapter_id"],
                guideline_id=kwargs["guideline_id"],
                job_type=V2JobType.EXPLANATION_GENERATION.value,
            )
        monkeypatch.setitem(LAUNCHER_BY_STAGE, "explanations", real_lock_launcher)

        orch = CascadeOrchestrator()
        with pytest.raises(ChapterJobLockError):
            orch.start_cascade(
                db_session,
                book_id=seed_topic["book_id"],
                chapter_id=seed_topic["chapter_id"],
                guideline_id=gid,
                from_stage_id="explanations",
            )
        # Stale flags must NOT have been committed — cascade rolled
        # back its in-memory entry, so descendants should be unchanged.
        assert repo.get(gid, "visuals").is_stale is False
        assert repo.get(gid, "check_ins").is_stale is False

    def test_rerun_with_unmet_upstream_deps_raises(
        self, db_session, seed_topic, fake_launchers,
    ):
        # `visuals` depends on `explanations`; explanations has no row
        # (never run) → CascadeNotReadyError, not a stuck cascade.
        orch = CascadeOrchestrator()
        with pytest.raises(CascadeNotReadyError):
            orch.start_cascade(
                db_session,
                book_id=seed_topic["book_id"],
                chapter_id=seed_topic["chapter_id"],
                guideline_id=seed_topic["guideline_id"],
                from_stage_id="visuals",
            )
        # No orphan cascade entry — future kickoffs aren't blocked.
        assert orch.get_cascade(seed_topic["guideline_id"]) is None

    def test_rerun_with_stale_upstream_dep_raises(
        self, db_session, seed_topic, fake_launchers,
    ):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_terminal(gid, "explanations", state="done", duration_ms=1)
        repo.mark_stale(gid, "explanations", is_stale=True)

        orch = CascadeOrchestrator()
        with pytest.raises(CascadeNotReadyError):
            orch.start_cascade(
                db_session,
                book_id=seed_topic["book_id"],
                chapter_id=seed_topic["chapter_id"],
                guideline_id=gid,
                from_stage_id="visuals",
            )

    def test_rerun_with_done_upstream_succeeds(
        self, db_session, seed_topic, fake_launchers,
    ):
        gid = seed_topic["guideline_id"]
        TopicStageRunRepository(db_session).upsert_terminal(
            gid, "explanations", state="done", duration_ms=1,
        )
        orch = CascadeOrchestrator()
        cascade = orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="visuals",
        )
        assert cascade.running == "visuals"


# ---------------------------------------------------------------------------
# Cascade event chain — full topological run
# ---------------------------------------------------------------------------


class TestCascadeEventChain:
    def test_full_cascade_from_explanations_runs_every_stage(
        self, db_session, seed_topic, fake_launchers, reset_singleton,
        monkeypatch,
    ):
        # Make on_stage_complete use the same in-memory session for state
        # reads — the default factory would open a real DB connection.
        orch = cascade_module.get_cascade_orchestrator()
        monkeypatch.setattr(
            orch, "_session_factory", _no_close_factory(db_session),
        )

        gid = seed_topic["guideline_id"]
        cascade = orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
        )
        cascade_id = cascade.cascade_id
        launched: list[str] = [c["stage_id"] for c in fake_launchers]

        # Drive the cascade by completing whatever's running.
        steps = 0
        while orch.get_cascade(gid) is not None and steps < 20:
            cur = orch.get_cascade(gid)
            assert cur is not None
            assert cur.cascade_id == cascade_id
            running = cur.running
            assert running is not None, "cascade has no running stage"
            _finish_running_job(db_session, gid, running)
            launched = [c["stage_id"] for c in fake_launchers]
            steps += 1

        all_launched = [c["stage_id"] for c in fake_launchers]
        # Every DAG stage was launched exactly once.
        assert len(all_launched) == len(DAG.stages)
        assert set(all_launched) == {s.id for s in DAG.stages}

        # Topo invariant: every dep precedes its dependant in the launch order.
        order = {sid: i for i, sid in enumerate(all_launched)}
        for s in DAG.stages:
            for dep in s.depends_on:
                assert order[dep] < order[s.id], (
                    f"{s.id} ran before its dep {dep}"
                )

    def test_halt_on_failure_clears_pending_and_does_not_launch_more(
        self, db_session, seed_topic, fake_launchers, reset_singleton,
        monkeypatch,
    ):
        orch = cascade_module.get_cascade_orchestrator()
        monkeypatch.setattr(orch, "_session_factory", _no_close_factory(db_session))

        gid = seed_topic["guideline_id"]
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
        )

        # Fail the first stage.
        _finish_running_job(
            db_session, gid, "explanations", status="failed", error="boom",
        )

        # Cascade should be cleaned up; no further launches.
        assert orch.get_cascade(gid) is None
        all_launched = [c["stage_id"] for c in fake_launchers]
        assert all_launched == ["explanations"]

        # explanations row should be `failed`, not `done`.
        repo = TopicStageRunRepository(db_session)
        assert repo.get(gid, "explanations").state == "failed"

    def test_halt_on_failure_clears_stale_on_descendants(
        self, db_session, seed_topic, fake_launchers, reset_singleton,
        monkeypatch,
    ):
        # Pre-existing done rows on descendants — cascade kickoff
        # marked them stale; halt-on-failure should clear them since
        # the failed rerun didn't actually invalidate their inputs.
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        repo.upsert_terminal(gid, "visuals", state="done", duration_ms=1)
        repo.upsert_terminal(gid, "check_ins", state="done", duration_ms=1)

        orch = cascade_module.get_cascade_orchestrator()
        monkeypatch.setattr(orch, "_session_factory", _no_close_factory(db_session))
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
        )
        # Sanity: kickoff did mark them stale.
        assert repo.get(gid, "visuals").is_stale is True
        assert repo.get(gid, "check_ins").is_stale is True

        _finish_running_job(
            db_session, gid, "explanations", status="failed", error="boom",
        )
        # After halt, descendants should be back to is_stale=False.
        assert repo.get(gid, "visuals").is_stale is False
        assert repo.get(gid, "check_ins").is_stale is False

    def test_cancel_mid_cascade_skips_next_launch(
        self, db_session, seed_topic, fake_launchers, reset_singleton,
        monkeypatch,
    ):
        orch = cascade_module.get_cascade_orchestrator()
        monkeypatch.setattr(orch, "_session_factory", _no_close_factory(db_session))

        gid = seed_topic["guideline_id"]
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
        )

        # Cancel while explanations is still running.
        assert orch.cancel(gid) is True
        # Now finish explanations — cascade should NOT launch the next
        # stage.
        _finish_running_job(db_session, gid, "explanations", status="completed")
        assert orch.get_cascade(gid) is None
        launched_ids = [c["stage_id"] for c in fake_launchers]
        assert launched_ids == ["explanations"]

    def test_cancel_with_no_active_returns_false(self, fresh_orchestrator):
        assert fresh_orchestrator.cancel("nonexistent-guideline") is False


# ---------------------------------------------------------------------------
# Phase 3.5 — force=True on cascade-launched descendants
# ---------------------------------------------------------------------------


class TestForceOnCascadeDescendants:
    """Cascade descendants whose prior row state is `done` or `failed`
    must launch with force=True. Several downstream services
    short-circuit on artifact presence — without force they'd "complete"
    without recomputing on the new upstream content, then upsert "done"
    + clear `is_stale`, leaving stale artifacts marked fresh."""

    def _drive_cascade_to_completion(self, orch, db_session, gid):
        """Finish whatever's running until the cascade clears."""
        steps = 0
        while orch.get_cascade(gid) is not None and steps < 25:
            cur = orch.get_cascade(gid)
            running = cur.running
            if running is None:
                break
            _finish_running_job(db_session, gid, running)
            steps += 1

    def test_descendant_with_done_row_uses_force_true(
        self, db_session, seed_topic, fake_launchers, reset_singleton,
        monkeypatch,
    ):
        gid = seed_topic["guideline_id"]
        # Seed visuals as previously-done.
        TopicStageRunRepository(db_session).upsert_terminal(
            gid, "visuals", state="done", duration_ms=1,
        )

        orch = cascade_module.get_cascade_orchestrator()
        monkeypatch.setattr(
            orch, "_session_factory", _no_close_factory(db_session),
        )
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
            force=True,
        )
        self._drive_cascade_to_completion(orch, db_session, gid)

        # Find the visuals launch among the recorded calls.
        visuals_launches = [
            c for c in fake_launchers if c["stage_id"] == "visuals"
        ]
        assert visuals_launches, "visuals never launched"
        assert visuals_launches[0]["kwargs"]["force"] is True, (
            "visuals had a prior `done` row → cascade must launch with "
            "force=True so visual_enrichment doesn't short-circuit on "
            "the existing artifact"
        )

    def test_descendant_with_failed_row_uses_force_true(
        self, db_session, seed_topic, fake_launchers, reset_singleton,
        monkeypatch,
    ):
        gid = seed_topic["guideline_id"]
        # Seed visuals as previously-failed.
        TopicStageRunRepository(db_session).upsert_terminal(
            gid, "visuals", state="failed", duration_ms=1,
            summary={"error": "boom"},
        )

        orch = cascade_module.get_cascade_orchestrator()
        monkeypatch.setattr(
            orch, "_session_factory", _no_close_factory(db_session),
        )
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
            force=True,
        )
        self._drive_cascade_to_completion(orch, db_session, gid)

        visuals_launches = [
            c for c in fake_launchers if c["stage_id"] == "visuals"
        ]
        assert visuals_launches, "visuals never launched"
        assert visuals_launches[0]["kwargs"]["force"] is True

    def test_first_time_descendant_uses_force_false(
        self, db_session, seed_topic, fake_launchers, reset_singleton,
        monkeypatch,
    ):
        gid = seed_topic["guideline_id"]
        # No row for visuals → first-time stage; force should stay False.
        orch = cascade_module.get_cascade_orchestrator()
        monkeypatch.setattr(
            orch, "_session_factory", _no_close_factory(db_session),
        )
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
            force=True,
        )
        self._drive_cascade_to_completion(orch, db_session, gid)

        visuals_launches = [
            c for c in fake_launchers if c["stage_id"] == "visuals"
        ]
        assert visuals_launches
        assert visuals_launches[0]["kwargs"]["force"] is False, (
            "first-time stage (no prior row) doesn't need force=True"
        )

    def test_first_stage_still_honours_force_arg(
        self, db_session, seed_topic, fake_launchers,
    ):
        # The first stage's force comes from the caller's `force` arg
        # — descendant-only logic must not change that contract.
        orch = CascadeOrchestrator()
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=seed_topic["guideline_id"],
            from_stage_id="explanations",
            force=False,
        )
        assert fake_launchers[0]["stage_id"] == "explanations"
        assert fake_launchers[0]["kwargs"]["force"] is False


# ---------------------------------------------------------------------------
# Phase 3.5 — defense cleanup in _launch_next
# ---------------------------------------------------------------------------


class TestLaunchNextDefenseCleanup:
    """If `_launch_next` ever finds non-empty pending with no ready,
    it must halt loudly so the cascade doesn't get stuck with
    `running=None`, blocking future kickoffs. The upfront check in
    `start_cascade` should prevent this — defense-in-depth for future
    regressions."""

    def test_no_ready_with_pending_halts_with_marker(
        self, db_session, seed_topic, fresh_orchestrator,
    ):
        gid = seed_topic["guideline_id"]
        # Manually inject a cascade whose pending is {"visuals"} but
        # with no row for `explanations` — `_ready_in_pending` returns
        # empty because the dep isn't done.
        state = cascade_module.CascadeState(
            cascade_id="bypass-checks", book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"], guideline_id=gid,
            quality_level="balanced", force_first=True,
            pending={"visuals"},
        )
        fresh_orchestrator._cascades[gid] = state

        fresh_orchestrator._launch_next(state, db=db_session)

        assert state.halted_at == "no_ready_stages"
        # Cleanup should drop the cascade entry — pending is non-empty
        # but `halted_at` flips `_maybe_cleanup` past its guard.
        assert fresh_orchestrator.get_cascade(gid) is None


# ---------------------------------------------------------------------------
# Phase 3.5 — preserve pre-existing stale flags on halt
# ---------------------------------------------------------------------------


class TestPreserveExistingStaleOnHalt:
    """Halt-on-failure should clear ONLY stale flags this cascade
    flipped at kickoff. Rows that were stale before the cascade started
    represent legitimate signals (prior cancelled cascade, operator
    action) and a failed rerun shouldn't erase them."""

    def test_pre_existing_stale_not_in_stale_marked(
        self, db_session, seed_topic, fake_launchers,
    ):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        # visuals: stale BEFORE the cascade kicked off.
        repo.upsert_terminal(gid, "visuals", state="done", duration_ms=1)
        repo.mark_stale(gid, "visuals", is_stale=True)
        # check_ins: clean-done; cascade SHOULD mark this one stale.
        repo.upsert_terminal(gid, "check_ins", state="done", duration_ms=1)

        orch = CascadeOrchestrator()
        cascade = orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
        )
        assert "visuals" not in cascade.stale_marked, (
            "visuals was already stale — cascade shouldn't claim it"
        )
        assert "check_ins" in cascade.stale_marked

    def test_halt_preserves_pre_existing_stale_clears_cascade_marked(
        self, db_session, seed_topic, fake_launchers, reset_singleton,
        monkeypatch,
    ):
        gid = seed_topic["guideline_id"]
        repo = TopicStageRunRepository(db_session)
        # visuals: pre-existing stale signal that must survive halt.
        repo.upsert_terminal(gid, "visuals", state="done", duration_ms=1)
        repo.mark_stale(gid, "visuals", is_stale=True)
        # check_ins: cascade flips to stale; halt must clear it.
        repo.upsert_terminal(gid, "check_ins", state="done", duration_ms=1)

        orch = cascade_module.get_cascade_orchestrator()
        monkeypatch.setattr(
            orch, "_session_factory", _no_close_factory(db_session),
        )
        orch.start_cascade(
            db_session,
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            from_stage_id="explanations",
        )
        # Sanity: kickoff state.
        assert repo.get(gid, "visuals").is_stale is True
        assert repo.get(gid, "check_ins").is_stale is True

        # Fail the cascade head — halt cleanup runs.
        _finish_running_job(
            db_session, gid, "explanations", status="failed", error="boom",
        )

        assert repo.get(gid, "visuals").is_stale is True, (
            "pre-existing stale signal must survive halt"
        )
        assert repo.get(gid, "check_ins").is_stale is False, (
            "cascade-flipped stale should be cleared on halt"
        )


# ---------------------------------------------------------------------------
# Read-order overlay — is_stale surfaces in dashboard responses
# ---------------------------------------------------------------------------


class TestReadOrderOverlay:
    def test_is_stale_overlay_from_row(self, db_session, seed_topic):
        gid = seed_topic["guideline_id"]
        # Seed an explanation so the artifact reconstruction yields "done".
        db_session.add(TopicExplanation(
            id=str(uuid.uuid4()), guideline_id=gid,
            variant_key="A", variant_label="Variant A",
            cards_json=[{"card_type": "explain"}],
        ))
        db_session.commit()

        # Mark explanations stale via repo.
        repo = TopicStageRunRepository(db_session)
        repo.upsert_terminal(gid, "explanations", state="done", duration_ms=1)
        repo.mark_stale(gid, "explanations", is_stale=True)

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"],
            seed_topic["topic_key"],
        )
        explanations = next(s for s in resp.stages if s.stage_id == "explanations")
        assert explanations.is_stale is True


# ---------------------------------------------------------------------------
# Terminal hook → cascade integration
# ---------------------------------------------------------------------------


class TestTerminalHookFiresCascade:
    def test_terminal_hook_calls_on_stage_complete(
        self, db_session, seed_topic, monkeypatch, reset_singleton,
    ):
        gid = seed_topic["guideline_id"]
        # Add a non-terminal job for the explanations stage.
        job = ChapterProcessingJob(
            id=str(uuid.uuid4()),
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="completed",
        )
        db_session.add(job)
        db_session.commit()

        captured: list[tuple[str, str, str]] = []

        class CaptureOrchestrator:
            def on_stage_complete(self, **kwargs):
                captured.append((
                    kwargs["guideline_id"],
                    kwargs["stage_id"],
                    kwargs["terminal_state"],
                ))

        monkeypatch.setattr(
            cascade_module, "get_cascade_orchestrator",
            lambda: CaptureOrchestrator(),
        )
        # The hook resolves the orchestrator via the dag.cascade module
        # path; importlib has already cached the import inside the hook
        # (it imports lazily), so monkeypatching the module attribute is
        # enough.

        started = datetime.utcnow() - timedelta(seconds=1)
        _write_topic_stage_run_terminal(db_session, job.id, started_at=started)
        assert captured == [(gid, "explanations", "done")]


# ---------------------------------------------------------------------------
# Reconciliation path → cascade integration
# ---------------------------------------------------------------------------


class TestReconciliationFiresCascade:
    def test_stuck_running_reconciliation_calls_on_stage_complete(
        self, db_session, seed_topic, monkeypatch, reset_singleton,
    ):
        # Setup: a stage row says `running` against a job that's
        # actually `failed` (worker died). Lazy backfill should
        # reconcile the row AND call cascade.on_stage_complete so an
        # active cascade waiting on this stage advances.
        gid = seed_topic["guideline_id"]
        # Create a failed job (heartbeat reaping marked it failed).
        job = ChapterProcessingJob(
            id=str(uuid.uuid4()),
            book_id=seed_topic["book_id"],
            chapter_id=seed_topic["chapter_id"],
            guideline_id=gid,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="failed",
            error_message="Heartbeat stale",
            started_at=datetime.utcnow() - timedelta(minutes=40),
            completed_at=datetime.utcnow() - timedelta(minutes=10),
        )
        db_session.add(job)
        db_session.commit()
        # Stuck `running` row pointing at the now-failed job.
        repo = TopicStageRunRepository(db_session)
        repo.upsert_running(gid, "explanations", job_id=job.id)
        db_session.add(TopicExplanation(
            id=str(uuid.uuid4()), guideline_id=gid,
            variant_key="A", variant_label="Variant A",
            cards_json=[{"card_type": "explain"}],
        ))
        db_session.commit()

        captured: list[tuple[str, str, str]] = []

        class CaptureOrchestrator:
            def on_stage_complete(self, **kwargs):
                captured.append((
                    kwargs["guideline_id"],
                    kwargs["stage_id"],
                    kwargs["terminal_state"],
                ))

        monkeypatch.setattr(
            cascade_module, "get_cascade_orchestrator",
            lambda: CaptureOrchestrator(),
        )

        # Trigger the lazy backfill via a status read.
        TopicPipelineStatusService(db_session).get_pipeline_status(
            seed_topic["book_id"], seed_topic["chapter_id"],
            seed_topic["topic_key"],
        )

        # Reconciliation found the failed job → row flipped to failed
        # → cascade hook fired with terminal_state="failed".
        assert (gid, "explanations", "failed") in captured
        assert repo.get(gid, "explanations").state == "failed"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def api_with_db(reset_singleton):
    """FastAPI TestClient backed by a thread-safe in-memory SQLite.

    The conftest's `db_session` fixture creates a single-thread engine,
    which doesn't survive TestClient's per-request thread. We build a
    fresh engine here with `check_same_thread=False` + StaticPool so
    every request and the test body share one connection.

    Returns `(client, session)` so tests can both hit the API and
    inspect the DB.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from database import get_db
    from main import app
    from shared.models.entities import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    def _override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    try:
        yield client, session
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        Base.metadata.drop_all(engine)


def _seed_topic_in(session):
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
        topic="Comparing Fractions", guideline="g",
        chapter_key="chapter-5", topic_key="comparing-fractions",
        chapter_title="Fractions", topic_title="Comparing Fractions",
        book_id=book_id, review_status="APPROVED", topic_sequence=1,
    ))
    session.commit()
    return {
        "book_id": book_id, "chapter_id": chapter_id,
        "guideline_id": guideline_id, "topic_key": "comparing-fractions",
    }


class TestDAGDefinitionEndpoint:
    def test_returns_every_stage(self, api_with_db):
        client, _ = api_with_db
        resp = client.get("/admin/v2/dag/definition")
        assert resp.status_code == 200
        body = resp.json()
        ids = {s["id"] for s in body["stages"]}
        assert ids == {s.id for s in DAG.stages}


class TestRerunStageEndpoint:
    def test_404_unknown_guideline(self, api_with_db):
        client, _ = api_with_db
        resp = client.post(
            "/admin/v2/topics/nonexistent-guideline-id/stages/explanations/rerun",
        )
        assert resp.status_code == 404

    def test_400_unknown_stage(self, api_with_db):
        client, session = api_with_db
        seed = _seed_topic_in(session)
        resp = client.post(
            f"/admin/v2/topics/{seed['guideline_id']}/stages/not_a_real_stage/rerun",
        )
        assert resp.status_code == 400

    def test_409_upstream_not_done(self, api_with_db, monkeypatch):
        client, session = api_with_db
        seed = _seed_topic_in(session)

        # Stub launchers so the test doesn't hit real services if it
        # ever reaches the launch path.
        for sid in [s.id for s in DAG.stages]:
            monkeypatch.setitem(
                LAUNCHER_BY_STAGE, sid,
                lambda db, **kwargs: "stub-job-id",
            )

        # `visuals` rerun while `explanations` has no row →
        # upstream_not_done.
        resp = client.post(
            f"/admin/v2/topics/{seed['guideline_id']}/stages/visuals/rerun",
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["detail"]["code"] == "upstream_not_done"


class TestCancelEndpoint:
    def test_404_unknown_guideline(self, api_with_db):
        client, _ = api_with_db
        resp = client.post(
            "/admin/v2/topics/nonexistent-guideline-id/dag/cancel",
        )
        assert resp.status_code == 404

    def test_no_active_cascade_returns_false(self, api_with_db):
        client, session = api_with_db
        seed = _seed_topic_in(session)
        resp = client.post(f"/admin/v2/topics/{seed['guideline_id']}/dag/cancel")
        assert resp.status_code == 200
        assert resp.json() == {"cancelled": False}


class TestRunAllEndpoint:
    def test_all_done_returns_empty_pending(self, api_with_db):
        client, session = api_with_db
        seed = _seed_topic_in(session)
        repo = TopicStageRunRepository(session)
        for stage in DAG.stages:
            repo.upsert_terminal(
                seed["guideline_id"], stage.id, state="done", duration_ms=1,
            )
        resp = client.post(f"/admin/v2/topics/{seed['guideline_id']}/dag/run-all")
        assert resp.status_code == 202
        body = resp.json()
        assert body["pending"] == []
        assert body["running"] is None


class TestGetTopicDAGEndpoint:
    def test_no_rows_returns_all_pending_or_reconstruction(self, api_with_db):
        client, session = api_with_db
        seed = _seed_topic_in(session)
        resp = client.get(f"/admin/v2/topics/{seed['guideline_id']}/dag")
        assert resp.status_code == 200
        body = resp.json()
        # Without any explanation artifact, every stage is `pending` in
        # the row vocabulary (lazy backfill writes nothing because
        # reconstruction returns ready/blocked, neither of which is a
        # terminal state to backfill).
        states = {s["stage_id"]: s["state"] for s in body["stages"]}
        assert all(v == "pending" for v in states.values()), states

    def test_legacy_null_topic_key_guideline_returns_200(self, api_with_db):
        """Phase 3.5 — `_load_guideline` filters by `topic_key`, so legacy
        guidelines with NULL topic_key 404'd from this endpoint even
        though `_resolve_topic_keys` already returned successfully. The
        guideline-id-keyed backfill entry point sidesteps the topic_key
        filter."""
        client, session = api_with_db
        book_id = str(uuid.uuid4())
        chapter_id = str(uuid.uuid4())
        guideline_id = str(uuid.uuid4())
        session.add(Book(
            id=book_id, title="T", country="India", board="CBSE", grade=4,
            subject="Mathematics", s3_prefix=f"books/{book_id}/",
        ))
        session.add(BookChapter(
            id=chapter_id, book_id=book_id, chapter_number=7,
            chapter_title="Decimals", start_page=1, end_page=20,
            status="chapter_completed", total_pages=20, uploaded_page_count=20,
        ))
        session.add(TeachingGuideline(
            id=guideline_id, country="India", board="CBSE", grade=4,
            subject="Mathematics", chapter="Decimals",
            topic="Place Value", guideline="g",
            chapter_key="chapter-7",
            topic_key=None,  # legacy row, never had topic_key set
            chapter_title="Decimals", topic_title="Place Value",
            book_id=book_id, review_status="APPROVED", topic_sequence=1,
        ))
        session.commit()

        resp = client.get(f"/admin/v2/topics/{guideline_id}/dag")
        assert resp.status_code == 200, resp.json()
        body = resp.json()
        assert body["guideline_id"] == guideline_id
        # Eight stages in the response, all `pending` (no artifacts).
        assert len(body["stages"]) == len(DAG.stages)
