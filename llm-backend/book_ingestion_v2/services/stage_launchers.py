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
    force: bool = False,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch audio text review. Returns job_id.

    `force=True` clears every `audio_url` on the reviewed variant so the
    downstream `audio_synthesis` run regenerates the full clip set, not
    just the lines this review pass happens to revise.
    """
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
        chapter_id, guideline_id, language or "", str(force),
    )
    return job_id


def launch_baatcheet_dialogue_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    force: bool = False,
    review_rounds: int = 1,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch Baatcheet dialogue (Stage 5b). Returns job_id."""
    from book_ingestion_v2.api.sync_routes import _run_baatcheet_dialogue_generation
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.BAATCHEET_DIALOGUE_GENERATION.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_baatcheet_dialogue_generation, job_id, book_id,
        chapter_id, guideline_id, str(force), str(review_rounds),
    )
    return job_id


def launch_baatcheet_visual_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    force: bool = False,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch Baatcheet visual enrichment (Stage 5c). Returns job_id."""
    from book_ingestion_v2.api.sync_routes import _run_baatcheet_visual_enrichment
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.BAATCHEET_VISUAL_ENRICHMENT.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_baatcheet_visual_enrichment, job_id, book_id,
        chapter_id, guideline_id, str(force),
    )
    return job_id


def launch_baatcheet_audio_review_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    language: Optional[str] = None,
    force: bool = False,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch Baatcheet audio review. Returns job_id.

    Sibling of `launch_audio_review_job` — handles the dialogue-text review
    that variant A's `audio_review` doesn't cover. `force=True` clears
    every dialogue `audio_url` up front so the cascaded
    `baatcheet_audio_synthesis` regenerates the full clip set.
    """
    from book_ingestion_v2.api.sync_routes import _run_baatcheet_audio_review
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.BAATCHEET_AUDIO_REVIEW.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_baatcheet_audio_review, job_id, book_id,
        chapter_id, guideline_id, language or "", str(force),
    )
    return job_id


def launch_baatcheet_audio_synthesis_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    force: bool = False,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch Baatcheet dialogue TTS synthesis. Returns job_id.

    Sibling of `launch_audio_synthesis_job` — handles dialogue MP3s that
    variant A's `audio_synthesis` no longer covers. `force=True` overwrites
    lines that already have an `audio_url` (S3 keys are deterministic, so
    writes overwrite cleanly at the same URL).
    """
    from book_ingestion_v2.api.sync_routes import _run_baatcheet_audio_generation
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=guideline_id,
        job_type=V2JobType.BAATCHEET_AUDIO_GENERATION.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_baatcheet_audio_generation, job_id, book_id,
        chapter_id, guideline_id, str(force),
    )
    return job_id


def launch_audio_synthesis_job(
    db: Session,
    *,
    book_id: str,
    chapter_id: str,
    guideline_id: str,
    force: bool = False,
    total_items: int = 1,
) -> str:
    """Acquire lock + launch audio synthesis (TTS). Returns job_id.

    `force=True` overwrites lines that already have an `audio_url` (S3
    keys are deterministic so writes overwrite cleanly at the same URL).
    """
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
        chapter_id, guideline_id, str(force),
    )
    return job_id


# `LAUNCHER_BY_STAGE` is derived from the DAG and lives at
# `book_ingestion_v2.dag.launcher_map`. Defining the dict in this module
# would create a cycle (DAG → stages → this module → DAG), so the canonical
# location is the dag/ package. The PEP 562 shim below preserves the
# legacy import path (`from ...stage_launchers import LAUNCHER_BY_STAGE`)
# for any external caller that hasn't migrated yet — it returns the same
# dict object, so monkeypatching keeps working.
def __getattr__(name: str):
    if name == "LAUNCHER_BY_STAGE":
        from book_ingestion_v2.dag.launcher_map import LAUNCHER_BY_STAGE
        return LAUNCHER_BY_STAGE
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )
