"""API routes for V2 sync, results, and explanation generation."""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from book_ingestion_v2.models.schemas import (
    SyncResponse,
    ExplanationGenerationResponse,
    BookResultsResponse,
    ChapterResultSummary,
)
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.repositories.topic_repository import TopicRepository
from book_ingestion_v2.services.topic_sync_service import TopicSyncService
from book_ingestion_v2.services.book_v2_service import BookV2Service

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


@router.post("/generate-explanations", response_model=ExplanationGenerationResponse)
def generate_explanations(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope generation"),
    db: Session = Depends(get_db),
):
    """Generate/regenerate pre-computed explanations for synced guidelines.

    Runs independently from sync. Idempotent — skips topics that already have
    explanations (delete existing rows first to force regeneration).
    """
    try:
        from config import get_settings
        from shared.services import LLMService, LLMConfigService
        from book_ingestion_v2.services.explanation_generator_service import ExplanationGeneratorService

        settings = get_settings()
        config = LLMConfigService(db).get_config("explanation_generator")
        llm_service = LLMService(
            api_key=settings.openai_api_key,
            provider=config["provider"],
            model_id=config["model_id"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )

        service = ExplanationGeneratorService(db, llm_service)
        result = service.generate_for_chapter(book_id, chapter_id)

        # Log warnings for failures so they surface in admin monitoring
        for error in result.get("errors", []):
            logger.warning(f"Explanation generation failed: {error}")

        return ExplanationGenerationResponse(**result)

    except Exception as e:
        logger.error(f"Explanation generation failed for book {book_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
