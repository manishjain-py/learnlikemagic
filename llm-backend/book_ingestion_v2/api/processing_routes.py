"""API routes for V2 chapter processing — extraction, finalization, status, topics."""
import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
# V2 uses its own run_in_background_v2 defined below
from book_ingestion_v2.constants import ChapterStatus, V2JobType
from book_ingestion_v2.models.schemas import (
    StartProcessingRequest,
    ReprocessRequest,
    RefinalizeRequest,
    ProcessingJobResponse,
    ChapterTopicResponse,
    ChapterTopicsResponse,
)
from typing import Optional
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.repositories.chapter_page_repository import ChapterPageRepository
from book_ingestion_v2.repositories.topic_repository import TopicRepository
from book_ingestion_v2.services.chapter_job_service import ChapterJobService, ChapterJobLockError
from book_ingestion_v2.services.chapter_page_service import ChapterPageService
from book_ingestion_v2.services.topic_extraction_orchestrator import TopicExtractionOrchestrator

router = APIRouter(
    prefix="/admin/v2/books/{book_id}/chapters/{chapter_id}",
    tags=["Book Ingestion V2 - Processing"],
)


def _validate_chapter_ownership(
    book_id: str, chapter_id: str, db: Session
) -> None:
    """Validate that chapter_id belongs to book_id. Raises 404 if not."""
    chapter_repo = ChapterRepository(db)
    chapter = chapter_repo.get_by_id(chapter_id)
    if not chapter or chapter.book_id != book_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chapter {chapter_id} not found in book {book_id}",
        )


@router.post("/process", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_processing(
    book_id: str,
    chapter_id: str,
    request: StartProcessingRequest = StartProcessingRequest(),
    db: Session = Depends(get_db),
):
    """Start topic extraction + auto-finalization for a chapter."""
    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter not found: {chapter_id}",
            )

        # Validate chapter is ready
        allowed_statuses = [ChapterStatus.UPLOAD_COMPLETE.value]
        if request.resume:
            allowed_statuses.extend([
                ChapterStatus.TOPIC_EXTRACTION.value,
                ChapterStatus.FAILED.value,
                ChapterStatus.NEEDS_REVIEW.value,
            ])
        if chapter.status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Chapter status is '{chapter.status}', "
                       f"expected one of {allowed_statuses}",
            )

        # Acquire job lock
        job_service = ChapterJobService(db)
        page_repo = ChapterPageRepository(db)
        total_chunks = _count_chunks(page_repo, chapter_id)

        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=chapter_id,
            job_type=V2JobType.TOPIC_EXTRACTION.value,
            total_items=total_chunks,
        )

        # Launch background task
        orchestrator = TopicExtractionOrchestrator(db)
        run_in_background_v2(
            orchestrator.extract, job_id, chapter_id, book_id, request.resume
        )

        return job_service.get_job(job_id)

    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/reprocess", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def reprocess(
    book_id: str,
    chapter_id: str,
    request: ReprocessRequest = ReprocessRequest(),
    db: Session = Depends(get_db),
):
    """Wipe topics and reprocess chapter from scratch."""
    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter not found: {chapter_id}",
            )

        # Reset to upload_complete
        chapter.status = ChapterStatus.UPLOAD_COMPLETE.value
        chapter.error_message = None
        chapter.error_type = None
        chapter_repo.update(chapter)

        # Start processing (non-resume)
        return start_processing(
            book_id, chapter_id,
            StartProcessingRequest(resume=False),
            db,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/refinalize", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def refinalize(
    book_id: str,
    chapter_id: str,
    request: RefinalizeRequest = RefinalizeRequest(),
    db: Session = Depends(get_db),
):
    """Re-run finalization only on existing draft topics."""
    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter not found: {chapter_id}",
            )

        if chapter.status not in [
            ChapterStatus.CHAPTER_COMPLETED.value,
            ChapterStatus.FAILED.value,
            ChapterStatus.NEEDS_REVIEW.value,
        ]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Chapter must be completed or failed to refinalize",
            )

        # Acquire job lock
        job_service = ChapterJobService(db)
        topic_repo = TopicRepository(db)
        topic_count = topic_repo.count_by_chapter(chapter_id)

        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=chapter_id,
            job_type=V2JobType.REFINALIZATION.value,
            total_items=topic_count,
        )

        # Launch finalization in background
        run_in_background_v2(
            _run_refinalization, job_id, chapter_id, book_id
        )

        return job_service.get_job(job_id)

    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/ocr-retry", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def ocr_retry(
    book_id: str, chapter_id: str, db: Session = Depends(get_db)
):
    """Bulk retry OCR for all pending/failed pages in a chapter."""
    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter not found: {chapter_id}",
            )

        if chapter.status not in [
            ChapterStatus.UPLOAD_IN_PROGRESS.value,
            ChapterStatus.UPLOAD_COMPLETE.value,
        ]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Chapter status is '{chapter.status}', expected upload_in_progress or upload_complete",
            )

        page_repo = ChapterPageRepository(db)
        pages_needing_ocr = page_repo.get_pages_needing_ocr(chapter_id)
        if not pages_needing_ocr:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No pages need OCR (all completed)",
            )

        job_service = ChapterJobService(db)
        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=chapter_id,
            job_type=V2JobType.OCR.value,
            total_items=len(pages_needing_ocr),
        )

        page_service = ChapterPageService(db)
        run_in_background_v2(page_service.bulk_ocr, job_id, chapter_id, book_id)

        return job_service.get_job(job_id)

    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/ocr-rerun", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def ocr_rerun(
    book_id: str, chapter_id: str, db: Session = Depends(get_db)
):
    """Reset all OCR and re-run from scratch for a chapter."""
    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter not found: {chapter_id}",
            )

        if chapter.status not in [
            ChapterStatus.UPLOAD_IN_PROGRESS.value,
            ChapterStatus.UPLOAD_COMPLETE.value,
        ]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Chapter status is '{chapter.status}', expected upload_in_progress or upload_complete",
            )

        page_repo = ChapterPageRepository(db)
        total_pages = page_repo.count_by_chapter(chapter_id)
        if total_pages == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No pages to re-OCR",
            )

        # Reset all OCR and revert chapter status
        page_repo.reset_ocr_for_chapter(chapter_id)
        chapter.status = ChapterStatus.UPLOAD_IN_PROGRESS.value
        chapter_repo.update(chapter)

        job_service = ChapterJobService(db)
        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=chapter_id,
            job_type=V2JobType.OCR.value,
            total_items=total_pages,
        )

        page_service = ChapterPageService(db)
        run_in_background_v2(page_service.bulk_ocr, job_id, chapter_id, book_id)

        return job_service.get_job(job_id)

    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/jobs/latest", response_model=ProcessingJobResponse)
def get_latest_job(
    book_id: str, chapter_id: str,
    job_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get the latest job status for a chapter, optionally filtered by job type."""
    try:
        _validate_chapter_ownership(book_id, chapter_id, db)
        job_service = ChapterJobService(db)
        result = job_service.get_latest_job(chapter_id, job_type=job_type)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No jobs found for this chapter",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/jobs/{job_id}", response_model=ProcessingJobResponse)
def get_job(
    book_id: str, chapter_id: str, job_id: str, db: Session = Depends(get_db)
):
    """Get specific job status."""
    try:
        _validate_chapter_ownership(book_id, chapter_id, db)
        job_service = ChapterJobService(db)
        result = job_service.get_job(job_id)
        if not result or result.chapter_id != chapter_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job not found: {job_id}",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/topics", response_model=ChapterTopicsResponse)
def get_chapter_topics(
    book_id: str, chapter_id: str, db: Session = Depends(get_db)
):
    """Get extracted topics for a chapter."""
    try:
        _validate_chapter_ownership(book_id, chapter_id, db)
        topic_repo = TopicRepository(db)
        topics = topic_repo.get_by_chapter_id(chapter_id)
        return ChapterTopicsResponse(
            chapter_id=chapter_id,
            topics=[
                ChapterTopicResponse(
                    id=t.id,
                    topic_key=t.topic_key,
                    topic_title=t.topic_title,
                    guidelines=t.guidelines,
                    summary=t.summary,
                    source_page_start=t.source_page_start,
                    source_page_end=t.source_page_end,
                    sequence_order=t.sequence_order,
                    status=t.status,
                    version=t.version,
                    prior_topics_context=t.prior_topics_context,
                    topic_assignment=t.topic_assignment,
                )
                for t in topics
            ],
            total=len(topics),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/topics/{topic_key}", response_model=ChapterTopicResponse)
def get_topic(
    book_id: str, chapter_id: str, topic_key: str, db: Session = Depends(get_db)
):
    """Get a specific topic with guidelines."""
    try:
        _validate_chapter_ownership(book_id, chapter_id, db)
        topic_repo = TopicRepository(db)
        topic = topic_repo.get_by_chapter_and_key(chapter_id, topic_key)
        if not topic:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Topic not found: {topic_key}",
            )
        return ChapterTopicResponse(
            id=topic.id,
            topic_key=topic.topic_key,
            topic_title=topic.topic_title,
            guidelines=topic.guidelines,
            summary=topic.summary,
            source_page_start=topic.source_page_start,
            source_page_end=topic.source_page_end,
            sequence_order=topic.sequence_order,
            status=topic.status,
            version=topic.version,
            prior_topics_context=topic.prior_topics_context,
            topic_assignment=topic.topic_assignment,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


# ───── Helpers ─────

def _count_chunks(page_repo, chapter_id: str) -> int:
    """Count expected chunks for progress tracking."""
    from book_ingestion_v2.utils.chunk_builder import build_chunk_windows
    pages = page_repo.get_by_chapter_id(chapter_id)
    page_numbers = [p.page_number for p in pages if p.ocr_status == "completed"]
    return len(build_chunk_windows(page_numbers))


def run_in_background_v2(target_fn, job_id: str, *args):
    """
    V2 background task runner — adapts V1 pattern for chapter jobs.

    Uses independent DB session and ChapterJobService for lifecycle.
    """
    import threading
    import time
    import logging
    from database import get_db_manager

    logger = logging.getLogger(__name__)

    def wrapper():
        db_manager = get_db_manager()
        session = db_manager.session_factory()
        try:
            job_service = ChapterJobService(session)
            job_service.start_job(job_id)

            # Re-create orchestrator/service with the background session
            target_fn(session, job_id, *args)

        except Exception as e:
            logger.error(f"V2 background task failed: {e}", exc_info=True)
            # Use a fresh session for error handling — the original may be dead
            # after a long LLM call timed out the DB connection
            try:
                error_session = db_manager.session_factory()
                try:
                    job_service = ChapterJobService(error_session)
                    job_service.release_lock(job_id, status="failed", error=str(e))
                finally:
                    error_session.close()
            except Exception:
                logger.error(f"Could not mark job {job_id} as failed")
        finally:
            try:
                session.close()
            except Exception:
                pass  # Session may already be closed by orchestrator refresh

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    logger.info(f"Launched V2 background task: {target_fn.__name__} (job_id={job_id})")
    return thread


def _run_refinalization(db: Session, job_id: str, chapter_id: str, book_id: str):
    """Background task for refinalization-only."""
    from config import get_settings
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from shared.repositories.book_repository import BookRepository
    from book_ingestion_v2.constants import LLM_CONFIG_KEY, ChapterStatus
    from book_ingestion_v2.services.chapter_finalization_service import ChapterFinalizationService
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService
    from book_ingestion_v2.repositories.chapter_repository import ChapterRepository

    settings = get_settings()
    config = LLMConfigService(db).get_config(LLM_CONFIG_KEY)
    llm_service = LLMService(
        api_key=settings.openai_api_key,
        provider=config["provider"],
        model_id=config["model_id"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )

    book = BookRepository(db).get_by_id(book_id)
    book_metadata = {
        "title": book.title, "subject": book.subject,
        "grade": book.grade, "board": book.board,
    }

    chapter_repo = ChapterRepository(db)
    chapter = chapter_repo.get_by_id(chapter_id)
    chapter.status = ChapterStatus.CHAPTER_FINALIZING.value
    chapter_repo.update(chapter)

    try:
        # Load planned topics from the job record (if this chapter was planned)
        from book_ingestion_v2.models.processing_models import ChapterTopicPlan
        from book_ingestion_v2.models.database import ChapterProcessingJob
        planned_topics = None
        job_record = db.query(ChapterProcessingJob).filter(
            ChapterProcessingJob.chapter_id == chapter_id,
            ChapterProcessingJob.planned_topics_json.isnot(None),
        ).order_by(ChapterProcessingJob.created_at.desc()).first()
        if job_record and job_record.planned_topics_json:
            try:
                plan = ChapterTopicPlan(**json.loads(job_record.planned_topics_json))
                planned_topics = plan.topics
            except Exception:
                pass  # Proceed without plan

        job_service = ChapterJobService(db)
        service = ChapterFinalizationService(
            db, llm_service, book_metadata,
            job_service=job_service, job_id=job_id,
        )
        result = service.finalize(chapter, job_id, planned_topics=planned_topics)

        # Refresh session after finalization (which does LLM calls)
        from database import get_db_manager
        db = get_db_manager().get_session()
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        chapter.status = result.final_status
        chapter_repo.update(chapter)

        job_service = ChapterJobService(db)
        job_service.release_lock(job_id, status="completed")
    except Exception as e:
        from database import get_db_manager
        db = get_db_manager().get_session()
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        chapter.status = ChapterStatus.FAILED.value
        chapter.error_message = f"Refinalization failed: {e}"
        chapter.error_type = "retryable"
        chapter_repo.update(chapter)
        raise
