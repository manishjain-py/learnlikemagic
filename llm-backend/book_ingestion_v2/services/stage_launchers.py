"""Per-stage launcher helpers for post-sync pipeline stages.

Each launcher owns the lock-and-launch sequence:
  1. `ChapterJobService.acquire_lock(..., guideline_id=...)`
  2. `run_in_background_v2(_run_<stage>, job_id, ...)` — `run_in_background_v2`
     calls `start_job(job_id)` internally before invoking the target.
  3. Returns `job_id` so callers can poll `get_job(job_id)` for terminal state.

Routes and the TopicPipelineOrchestrator both invoke these helpers so we
have a single code path for starting any post-sync stage.

The `_run_*` background task bodies live in `sync_routes.py` alongside the
corresponding routes — moving those functions here would create a circular
dependency chain with the router.
"""
from __future__ import annotations

import logging
from typing import Optional
from sqlalchemy.orm import Session

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.services.chapter_job_service import ChapterJobService

logger = logging.getLogger(__name__)


def launch_explanation_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    force: bool = False,
    mode: str = "generate",
    review_rounds: int = 1,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch explanation generation. Returns job_id."""
    from book_ingestion_v2.api.sync_routes import _run_explanation_generation
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.EXPLANATION_GENERATION.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_explanation_generation, job_id, book_id,
        chapter_id, guideline_id, str(force), mode, str(review_rounds),
    )
    return job_id


def launch_visual_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    force: bool = False,
    review_rounds: int = 1,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch visual enrichment. Returns job_id."""
    from book_ingestion_v2.api.sync_routes import _run_visual_enrichment
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.VISUAL_ENRICHMENT.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_visual_enrichment, job_id, book_id,
        chapter_id, guideline_id, str(force), str(review_rounds),
    )
    return job_id


def launch_check_in_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    force: bool = False,
    review_rounds: int = 1,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch check-in enrichment. Returns job_id."""
    from book_ingestion_v2.api.sync_routes import _run_check_in_enrichment
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.CHECK_IN_ENRICHMENT.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_check_in_enrichment, job_id, book_id,
        chapter_id, guideline_id, str(force), str(review_rounds),
    )
    return job_id


def launch_practice_bank_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    force: bool = False,
    review_rounds: int = 1,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch practice bank generation. Returns job_id."""
    from book_ingestion_v2.api.sync_routes import _run_practice_bank_generation
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.PRACTICE_BANK_GENERATION.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_practice_bank_generation, job_id, book_id,
        chapter_id, guideline_id, str(force), str(review_rounds),
    )
    return job_id


def launch_audio_review_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    language: Optional[str] = None,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch audio text review. Returns job_id."""
    from book_ingestion_v2.api.sync_routes import _run_audio_text_review
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.AUDIO_TEXT_REVIEW.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_audio_text_review, job_id, book_id,
        chapter_id, guideline_id, language or "",
    )
    return job_id


def launch_audio_synthesis_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch audio synthesis (TTS). Returns job_id."""
    from book_ingestion_v2.api.sync_routes import _run_audio_generation
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.AUDIO_GENERATION.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_audio_generation, job_id, book_id,
        chapter_id, guideline_id,
    )
    return job_id


# Stage-id → launcher map, consumed by the orchestrator.
# Keys match `StageId` values in models/schemas.py.
LAUNCHER_BY_STAGE = {
    "explanations": launch_explanation_job,
    "visuals": launch_visual_job,
    "check_ins": launch_check_in_job,
    "practice_bank": launch_practice_bank_job,
    "audio_review": launch_audio_review_job,
    "audio_synthesis": launch_audio_synthesis_job,
}
