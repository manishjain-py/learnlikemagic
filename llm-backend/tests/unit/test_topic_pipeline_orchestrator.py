"""Unit tests for TopicPipelineOrchestrator.

Covers:
- `_poll_to_terminal` timeout path marks the job failed (zombie-job fix)
- `_run_one_stage` tags `pipeline_run_id` into the job's progress_detail
- `stages_to_run_from_status` decision helper
- `get_chapter_topic_statuses` single-pass helper
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.services.chapter_job_service import ChapterJobService
from book_ingestion_v2.services import topic_pipeline_orchestrator as tpo


@pytest.fixture
def ids():
    return {
        "book_id": str(uuid.uuid4()),
        "chapter_id": str(uuid.uuid4()),
        "guideline_id": str(uuid.uuid4()),
    }


class TestPollToTerminal:
    def test_timeout_marks_job_failed(self, db_session, ids, monkeypatch):
        svc = ChapterJobService(db_session)
        job_id = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["guideline_id"],
        )
        svc.start_job(job_id)

        monkeypatch.setattr(tpo, "POLL_INTERVAL_SEC", 0)
        monkeypatch.setattr(tpo, "MAX_POLL_WALL_TIME_SEC", 0)

        orch = tpo.TopicPipelineOrchestrator(
            session_factory=lambda: db_session,
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            guideline_id=ids["guideline_id"],
            quality_level="balanced",
        )
        result = orch._poll_to_terminal(db_session, job_id)
        assert result == "failed"
        job = svc.get_job(job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error_message and "timeout" in job.error_message.lower()

    def test_returns_terminal_status(self, db_session, ids, monkeypatch):
        svc = ChapterJobService(db_session)
        job_id = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["guideline_id"],
        )
        svc.start_job(job_id)
        svc.release_lock(job_id, status="completed")

        monkeypatch.setattr(tpo, "POLL_INTERVAL_SEC", 0)

        orch = tpo.TopicPipelineOrchestrator(
            session_factory=lambda: db_session,
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            guideline_id=ids["guideline_id"],
            quality_level="balanced",
        )
        assert orch._poll_to_terminal(db_session, job_id) == "completed"


class TestStagesToRunFromStatus:
    def _make_stage(self, stage_id, state):
        from book_ingestion_v2.models.schemas import StageStatus
        return StageStatus(stage_id=stage_id, state=state, summary="")

    def test_skips_running(self):
        stages = [
            self._make_stage("explanations", "running"),
            self._make_stage("visuals", "ready"),
        ]
        assert tpo.stages_to_run_from_status(stages, force=False) == ["visuals"]

    def test_skips_done_without_force(self):
        stages = [
            self._make_stage("explanations", "done"),
            self._make_stage("visuals", "ready"),
        ]
        assert tpo.stages_to_run_from_status(stages, force=False) == ["visuals"]

    def test_includes_done_with_force(self):
        stages = [
            self._make_stage("explanations", "done"),
            self._make_stage("visuals", "ready"),
        ]
        assert tpo.stages_to_run_from_status(stages, force=True) == ["explanations", "visuals"]

    def test_includes_failed_and_warning(self):
        stages = [
            self._make_stage("explanations", "failed"),
            self._make_stage("practice_bank", "warning"),
            self._make_stage("visuals", "blocked"),
        ]
        assert tpo.stages_to_run_from_status(stages, force=False) == [
            "explanations", "practice_bank", "visuals",
        ]


class TestPipelineRunIdTagging:
    def test_run_one_stage_tags_pipeline_run_id(self, db_session, ids, monkeypatch):
        """Orchestrator records pipeline_run_id into progress_detail after launch."""
        monkeypatch.setattr(tpo, "POLL_INTERVAL_SEC", 0)
        monkeypatch.setattr(tpo, "MAX_POLL_WALL_TIME_SEC", 0)

        # Patch the launcher to acquire a real lock but not spawn a thread.
        captured: dict[str, str] = {}

        def fake_launch(db, *, book_id, chapter_id, guideline_id, **kwargs):
            job_id = ChapterJobService(db).acquire_lock(
                book_id=book_id,
                chapter_id=chapter_id,
                guideline_id=guideline_id,
                job_type=V2JobType.EXPLANATION_GENERATION.value,
            )
            captured["job_id"] = job_id
            return job_id

        monkeypatch.setitem(tpo.LAUNCHER_BY_STAGE, "explanations", fake_launch)

        orch = tpo.TopicPipelineOrchestrator(
            session_factory=lambda: db_session,
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            guideline_id=ids["guideline_id"],
            quality_level="fast",
        )
        # _run_one_stage returns "failed" because poll timeout is 0, but the
        # tag-before-poll happens regardless — that's what we're verifying.
        orch._run_one_stage("explanations")

        job = ChapterJobService(db_session).get_job(captured["job_id"])
        assert job is not None
        assert isinstance(job.progress_detail, dict)
        assert job.progress_detail.get("pipeline_run_id") == orch.pipeline_run_id
