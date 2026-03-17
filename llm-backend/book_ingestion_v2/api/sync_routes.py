"""API routes for V2 sync, results, and explanation generation."""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.models.schemas import (
    SyncResponse,
    ProcessingJobResponse,
    BookResultsResponse,
    ChapterResultSummary,
)
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.repositories.topic_repository import TopicRepository
from book_ingestion_v2.services.topic_sync_service import TopicSyncService
from book_ingestion_v2.services.book_v2_service import BookV2Service
from book_ingestion_v2.services.chapter_job_service import ChapterJobService, ChapterJobLockError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v2/books/{book_id}", tags=["Book Ingestion V2 - Sync"])


@router.post("/sync", response_model=SyncResponse)
def sync_book(book_id: str, db: Session = Depends(get_db)):
    """Sync all completed chapters to teaching_guidelines."""
    try:
        service = TopicSyncService(db)
        return service.sync_book(book_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/chapters/{chapter_id}/sync", response_model=SyncResponse)
def sync_chapter(book_id: str, chapter_id: str, db: Session = Depends(get_db)):
    """Sync a single chapter to teaching_guidelines."""
    try:
        service = TopicSyncService(db)
        return service.sync_chapter(book_id, chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/results", response_model=BookResultsResponse)
def get_book_results(book_id: str, db: Session = Depends(get_db)):
    """Book-level results overview with all chapters."""
    try:
        book_service = BookV2Service(db)
        book = book_service.get_book(book_id)
        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"V2 book not found: {book_id}",
            )

        chapter_repo = ChapterRepository(db)
        topic_repo = TopicRepository(db)
        chapters = chapter_repo.get_by_book_id(book_id)

        chapter_summaries = []
        total_topics = 0
        for ch in chapters:
            topic_count = topic_repo.count_by_chapter(ch.id)
            total_topics += topic_count
            chapter_summaries.append(
                ChapterResultSummary(
                    chapter_id=ch.id,
                    chapter_number=ch.chapter_number,
                    chapter_title=ch.chapter_title,
                    display_name=ch.display_name,
                    status=ch.status,
                    topic_count=topic_count,
                )
            )

        return BookResultsResponse(
            book_id=book_id,
            title=book.title,
            chapters=chapter_summaries,
            total_topics=total_topics,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/generate-explanations", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_explanations(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope generation"),
    db: Session = Depends(get_db),
):
    """Generate/regenerate pre-computed explanations for synced guidelines.

    Launches a background job and returns 202 immediately.
    Runs independently from sync. Idempotent — skips topics that already have
    explanations (delete existing rows first to force regeneration).
    """
    from book_ingestion_v2.api.processing_routes import run_in_background_v2
    from shared.models.entities import TeachingGuideline

    try:
        # Count guidelines to set total_items
        query = db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.review_status == "APPROVED",
        )
        if chapter_id:
            chapter_repo = ChapterRepository(db)
            chapter = chapter_repo.get_by_id(chapter_id)
            if not chapter or chapter.book_id != book_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chapter {chapter_id} not found in book {book_id}",
                )
            chapter_key = f"chapter-{chapter.chapter_number}"
            query = query.filter(TeachingGuideline.chapter_key == chapter_key)

        total_items = query.count()

        # Use chapter_id for lock scope, or book_id as sentinel for book-wide generation
        lock_chapter_id = chapter_id or book_id

        job_service = ChapterJobService(db)
        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=lock_chapter_id,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            total_items=total_items,
        )

        run_in_background_v2(
            _run_explanation_generation, job_id, book_id, chapter_id or ""
        )

        return job_service.get_job(job_id)

    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Explanation generation failed for book {book_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/explanation-jobs/latest", response_model=ProcessingJobResponse)
def get_latest_explanation_job(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Chapter ID (omit for book-wide job)"),
    db: Session = Depends(get_db),
):
    """Get the latest explanation generation job for a chapter or book."""
    try:
        lock_chapter_id = chapter_id or book_id
        job_service = ChapterJobService(db)
        result = job_service.get_latest_job(
            lock_chapter_id,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No explanation generation jobs found",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


def _run_explanation_generation(
    db: Session, job_id: str, book_id: str, chapter_id: str
):
    """Background task for explanation generation."""
    from config import get_settings
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.explanation_generator_service import ExplanationGeneratorService
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    settings = get_settings()
    config = LLMConfigService(db).get_config("explanation_generator")
    llm_service = LLMService(
        api_key=settings.openai_api_key,
        provider=config["provider"],
        model_id=config["model_id"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )

    job_service = ChapterJobService(db)
    service = ExplanationGeneratorService(db, llm_service)

    try:
        result = service.generate_for_chapter(
            book_id,
            chapter_id=chapter_id or None,
            job_service=job_service,
            job_id=job_id,
        )

        # Log warnings for failures
        for error in result.get("errors", []):
            logger.warning(f"Explanation generation failed: {error}")

        final_status = "completed" if result["failed"] == 0 else "completed_with_errors"
        job_service.release_lock(job_id, status=final_status)

    except Exception:
        raise  # run_in_background_v2 handles marking the job as failed
