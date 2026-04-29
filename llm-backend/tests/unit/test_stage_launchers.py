"""Unit tests for stage_launchers (Phase 2).

These don't actually start threads — we patch run_in_background_v2 to
capture invocation and verify the lock is acquired and the launcher returns
a job_id. The _run_* function bodies are not exercised here.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.services import stage_launchers


LAUNCHER_CASES = [
    ("launch_explanation_job", V2JobType.EXPLANATION_GENERATION.value, {"force": False, "mode": "generate", "review_rounds": 1}),
    ("launch_visual_job", V2JobType.VISUAL_ENRICHMENT.value, {"force": False, "review_rounds": 1}),
    ("launch_check_in_job", V2JobType.CHECK_IN_ENRICHMENT.value, {"force": False, "review_rounds": 1}),
    ("launch_practice_bank_job", V2JobType.PRACTICE_BANK_GENERATION.value, {"force": False, "review_rounds": 1}),
    ("launch_audio_review_job", V2JobType.AUDIO_TEXT_REVIEW.value, {"language": "en", "force": False}),
    ("launch_audio_synthesis_job", V2JobType.AUDIO_GENERATION.value, {"force": False}),
]


@pytest.mark.parametrize("launcher_name,expected_job_type,extra_kwargs", LAUNCHER_CASES)
def test_launcher_acquires_lock_and_returns_job_id(
    db_session, launcher_name, expected_job_type, extra_kwargs,
):
    book_id = str(uuid.uuid4())
    chapter_id = str(uuid.uuid4())
    guideline_id = str(uuid.uuid4())

    launcher = getattr(stage_launchers, launcher_name)

    with patch("book_ingestion_v2.services.stage_launchers.run_in_background_v2", create=True) as mock_rib:
        # The `run_in_background_v2` name is patched via lazy import inside
        # the launchers; patch the api module path too.
        with patch("book_ingestion_v2.api.processing_routes.run_in_background_v2") as mock_rib2:
            mock_rib2.return_value = None
            job_id = launcher(
                db_session,
                book_id=book_id,
                chapter_id=chapter_id,
                guideline_id=guideline_id,
                **extra_kwargs,
            )
            mock_rib2.assert_called_once()

    assert isinstance(job_id, str) and len(job_id) > 0

    # The lock was acquired — get_job should return a pending job record.
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService
    job = ChapterJobService(db_session).get_job(job_id)
    assert job is not None
    assert job.job_type == expected_job_type
    assert job.status == "pending"
