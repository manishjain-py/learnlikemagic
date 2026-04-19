"""Unit tests for ChapterJobService with scoped-lock semantics (Phase 2).

Covers reader-writer semantics between chapter-level and topic-level jobs:
- Post-sync job_type requires guideline_id.
- Two topic-level jobs for different guidelines can coexist.
- Same (chapter, guideline) cannot have two active jobs.
- Chapter-level active blocks any topic-level start.
- Topic-level active blocks any chapter-level start.
- get_latest_job filters by guideline_id when given.
"""
from __future__ import annotations

import uuid

import pytest

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.services.chapter_job_service import (
    ChapterJobLockError,
    ChapterJobService,
)


def _ids(db):
    return {
        "book_id": str(uuid.uuid4()),
        "chapter_id": str(uuid.uuid4()),
        "g1": str(uuid.uuid4()),
        "g2": str(uuid.uuid4()),
    }


class TestLockSemantics:
    def test_post_sync_requires_guideline_id(self, db_session):
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        with pytest.raises(ChapterJobLockError, match="requires guideline_id"):
            svc.acquire_lock(
                book_id=ids["book_id"],
                chapter_id=ids["chapter_id"],
                job_type=V2JobType.EXPLANATION_GENERATION.value,
            )

    def test_two_topic_jobs_same_chapter_coexist(self, db_session):
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        jid1 = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g1"],
        )
        jid2 = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g2"],
        )
        assert jid1 != jid2

    def test_same_topic_twice_raises(self, db_session):
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g1"],
        )
        with pytest.raises(ChapterJobLockError, match="already pending"):
            svc.acquire_lock(
                book_id=ids["book_id"],
                chapter_id=ids["chapter_id"],
                job_type=V2JobType.EXPLANATION_GENERATION.value,
                guideline_id=ids["g1"],
            )

    def test_chapter_level_blocks_topic_level(self, db_session):
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.TOPIC_EXTRACTION.value,
        )
        with pytest.raises(ChapterJobLockError, match="Chapter-level"):
            svc.acquire_lock(
                book_id=ids["book_id"],
                chapter_id=ids["chapter_id"],
                job_type=V2JobType.EXPLANATION_GENERATION.value,
                guideline_id=ids["g1"],
            )

    def test_topic_level_blocks_chapter_level(self, db_session):
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g1"],
        )
        with pytest.raises(ChapterJobLockError, match="post-sync"):
            svc.acquire_lock(
                book_id=ids["book_id"],
                chapter_id=ids["chapter_id"],
                job_type=V2JobType.TOPIC_EXTRACTION.value,
            )

    def test_same_chapter_level_twice_raises(self, db_session):
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.TOPIC_EXTRACTION.value,
        )
        with pytest.raises(ChapterJobLockError, match="already pending"):
            svc.acquire_lock(
                book_id=ids["book_id"],
                chapter_id=ids["chapter_id"],
                job_type=V2JobType.TOPIC_EXTRACTION.value,
            )


class TestPipelineRunIdObservability:
    def test_record_pipeline_run_id_writes_detail(self, db_session):
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        jid = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g1"],
        )
        svc.record_pipeline_run_id(jid, "pipeline-xyz")
        job = svc.get_job(jid)
        assert job is not None
        assert job.progress_detail == {"pipeline_run_id": "pipeline-xyz"}

    def test_update_progress_preserves_pipeline_run_id(self, db_session):
        import json
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        jid = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g1"],
        )
        svc.record_pipeline_run_id(jid, "pipeline-xyz")
        svc.start_job(jid)
        svc.update_progress(
            jid,
            current_item="topic-a",
            completed=1,
            failed=0,
            detail=json.dumps({"generated": 1, "failed": 0, "errors": []}),
        )
        job = svc.get_job(jid)
        assert job is not None
        assert isinstance(job.progress_detail, dict)
        assert job.progress_detail.get("pipeline_run_id") == "pipeline-xyz"
        assert job.progress_detail.get("generated") == 1

    def test_update_progress_does_not_override_explicit_pipeline_run_id(self, db_session):
        import json
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        jid = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g1"],
        )
        svc.record_pipeline_run_id(jid, "old")
        svc.start_job(jid)
        svc.update_progress(
            jid,
            detail=json.dumps({"pipeline_run_id": "new", "generated": 1}),
        )
        job = svc.get_job(jid)
        assert job.progress_detail.get("pipeline_run_id") == "new"


class TestGetLatestJob:
    def test_get_latest_job_filters_by_guideline_id(self, db_session):
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        jid1 = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g1"],
        )
        jid2 = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g2"],
        )

        latest_g1 = svc.get_latest_job(
            ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g1"],
        )
        latest_g2 = svc.get_latest_job(
            ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g2"],
        )

        assert latest_g1 is not None and latest_g1.job_id == jid1
        assert latest_g2 is not None and latest_g2.job_id == jid2

    def test_get_latest_job_without_guideline_returns_most_recent(self, db_session):
        ids = _ids(db_session)
        svc = ChapterJobService(db_session)
        jid1 = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g1"],
        )
        jid2 = svc.acquire_lock(
            book_id=ids["book_id"],
            chapter_id=ids["chapter_id"],
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=ids["g2"],
        )
        latest = svc.get_latest_job(
            ids["chapter_id"], job_type=V2JobType.EXPLANATION_GENERATION.value,
        )
        assert latest is not None and latest.job_id == jid2  # most recent
        # Ensure both still reachable by id
        assert svc.get_job(jid1) is not None
