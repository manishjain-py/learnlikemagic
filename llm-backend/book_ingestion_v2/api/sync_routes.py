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
    ChapterExplanationStatusResponse,
    TopicExplanationStatus,
    TopicExplanationsDetailResponse,
    ExplanationVariantResponse,
    DeleteExplanationsResponse,
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
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic generation"),
    force: bool = Query(False, description="Delete existing explanations before regenerating"),
    db: Session = Depends(get_db),
):
    """Generate/regenerate pre-computed explanations for synced guidelines.

    Launches a background job and returns 202 immediately.
    Scoping: guideline_id (single topic) > chapter_id (chapter) > book-wide.
    By default skips topics that already have explanations; set force=true to regenerate.
    """
    from book_ingestion_v2.api.processing_routes import run_in_background_v2
    from shared.models.entities import TeachingGuideline

    try:
        if guideline_id:
            # Single-topic generation
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
                TeachingGuideline.book_id == book_id,
            ).first()
            if not guideline:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Guideline {guideline_id} not found in book {book_id}",
                )
            total_items = 1
            lock_chapter_id = guideline_id  # use guideline_id as lock scope
        else:
            # Chapter or book-wide generation
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
            lock_chapter_id = chapter_id or book_id

        job_service = ChapterJobService(db)
        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=lock_chapter_id,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            total_items=total_items,
        )

        run_in_background_v2(
            _run_explanation_generation, job_id, book_id,
            chapter_id or "", guideline_id or "", str(force),
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
    guideline_id: Optional[str] = Query(None, description="Guideline ID for single-topic job"),
    db: Session = Depends(get_db),
):
    """Get the latest explanation generation job for a topic, chapter, or book."""
    try:
        lock_chapter_id = guideline_id or chapter_id or book_id
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


@router.get("/explanation-status", response_model=ChapterExplanationStatusResponse)
def get_explanation_status(
    book_id: str,
    chapter_id: str = Query(..., description="Chapter ID to get explanation status for"),
    db: Session = Depends(get_db),
):
    """Get per-topic explanation variant counts for a chapter."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter {chapter_id} not found in book {book_id}",
            )
        chapter_key = f"chapter-{chapter.chapter_number}"

        repo = ExplanationRepository(db)
        counts = repo.get_variant_counts_for_chapter(book_id, chapter_key)

        # Get all guidelines for this chapter to list even those without explanations
        guidelines = (
            db.query(TeachingGuideline)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key == chapter_key,
                TeachingGuideline.review_status == "APPROVED",
            )
            .order_by(TeachingGuideline.topic_sequence)
            .all()
        )

        topics = [
            TopicExplanationStatus(
                guideline_id=g.id,
                topic_title=g.topic_title or g.topic,
                topic_key=g.topic_key,
                variant_count=counts.get(g.id, 0),
            )
            for g in guidelines
        ]

        return ChapterExplanationStatusResponse(
            chapter_id=chapter_id,
            chapter_key=chapter_key,
            topics=topics,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/explanations", response_model=TopicExplanationsDetailResponse)
def get_topic_explanations(
    book_id: str,
    guideline_id: str = Query(..., description="Guideline ID to get explanations for"),
    db: Session = Depends(get_db),
):
    """Get all explanation variants with full card data for a topic."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    try:
        guideline = db.query(TeachingGuideline).filter(
            TeachingGuideline.id == guideline_id,
            TeachingGuideline.book_id == book_id,
        ).first()
        if not guideline:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Guideline {guideline_id} not found in book {book_id}",
            )

        repo = ExplanationRepository(db)
        explanations = repo.get_by_guideline_id(guideline_id)

        variants = [
            ExplanationVariantResponse(
                id=e.id,
                variant_key=e.variant_key,
                variant_label=e.variant_label,
                cards_json=e.cards_json,
                summary_json=e.summary_json,
                generator_model=e.generator_model,
                created_at=e.created_at,
            )
            for e in explanations
        ]

        return TopicExplanationsDetailResponse(
            guideline_id=guideline_id,
            topic_title=guideline.topic_title or guideline.topic,
            topic_key=guideline.topic_key,
            variants=variants,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.delete("/explanations", response_model=DeleteExplanationsResponse)
def delete_explanations(
    book_id: str,
    guideline_id: Optional[str] = Query(None, description="Delete explanations for a specific topic"),
    chapter_id: Optional[str] = Query(None, description="Delete explanations for all topics in a chapter"),
    db: Session = Depends(get_db),
):
    """Delete explanation variants for a topic or chapter."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    try:
        if not guideline_id and not chapter_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must specify either guideline_id or chapter_id",
            )

        repo = ExplanationRepository(db)

        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
                TeachingGuideline.book_id == book_id,
            ).first()
            if not guideline:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Guideline {guideline_id} not found in book {book_id}",
                )
            count = repo.delete_by_guideline_id(guideline_id)
        else:
            chapter_repo = ChapterRepository(db)
            chapter = chapter_repo.get_by_id(chapter_id)
            if not chapter or chapter.book_id != book_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chapter {chapter_id} not found in book {book_id}",
                )
            chapter_key = f"chapter-{chapter.chapter_number}"
            count = repo.delete_by_chapter(book_id, chapter_key)

        return DeleteExplanationsResponse(deleted_count=count)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/generate-visuals", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_visuals(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope enrichment"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic enrichment"),
    force: bool = Query(False, description="Re-generate visuals even if cards already have them"),
    db: Session = Depends(get_db),
):
    """Generate pre-computed PixiJS visuals for explanation cards.

    Runs as a background job. Requires explanations to already exist.
    Scoping: guideline_id (single topic) > chapter_id (chapter) > book-wide.
    """
    from book_ingestion_v2.api.processing_routes import run_in_background_v2
    from shared.models.entities import TeachingGuideline

    try:
        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
                TeachingGuideline.book_id == book_id,
            ).first()
            if not guideline:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Guideline {guideline_id} not found in book {book_id}",
                )
            total_items = 1
            lock_chapter_id = guideline_id
        else:
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
            lock_chapter_id = chapter_id or book_id

        job_service = ChapterJobService(db)
        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=lock_chapter_id,
            job_type=V2JobType.VISUAL_ENRICHMENT.value,
            total_items=total_items,
        )

        run_in_background_v2(
            _run_visual_enrichment, job_id, book_id,
            chapter_id or "", guideline_id or "", str(force),
        )

        return job_service.get_job(job_id)

    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Visual enrichment failed for book {book_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


def _run_explanation_generation(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False",
):
    """Background task for explanation generation."""
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.explanation_generator_service import ExplanationGeneratorService
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"

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
        if guideline_id:
            # Single-topic generation
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).first()
            if not guideline:
                raise ValueError(f"Guideline {guideline_id} not found")

            topic = guideline.topic_title or guideline.topic
            job_service.update_progress(job_id, current_item=topic, completed=0, failed=0)

            if force:
                service.repo.delete_by_guideline_id(guideline_id)

            results = service.generate_for_guideline(guideline)
            generated = 1 if results else 0
            failed = 0 if results else 1
            errors = [] if results else [f"{topic}: no variants passed validation"]

            job_service.update_progress(
                job_id, current_item=None, completed=generated, failed=failed,
                detail=_json.dumps({
                    "generated": generated, "skipped": 0, "failed": failed, "errors": errors,
                }),
            )
            final_status = "completed" if failed == 0 else "completed_with_errors"
        else:
            # Chapter or book-wide generation
            result = service.generate_for_chapter(
                book_id,
                chapter_id=chapter_id or None,
                job_service=job_service,
                job_id=job_id,
                force=force,
            )

            for error in result.get("errors", []):
                logger.warning(f"Explanation generation failed: {error}")

            final_status = "completed" if result["failed"] == 0 else "completed_with_errors"

        job_service.release_lock(job_id, status=final_status)

    except Exception:
        raise  # run_in_background_v2 handles marking the job as failed


def _run_visual_enrichment(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False",
):
    """Background task for visual enrichment of explanation cards."""
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.animation_enrichment_service import AnimationEnrichmentService
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"

    settings = get_settings()

    # Decision+spec LLM (can be lighter model)
    config = LLMConfigService(db).get_config("animation_enrichment")
    llm_service = LLMService(
        api_key=settings.openai_api_key,
        provider=config["provider"],
        model_id=config["model_id"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )

    # Code generation LLM (heavier model for reliable code)
    code_config = LLMConfigService(db).get_config("animation_code_gen")
    code_llm = LLMService(
        api_key=settings.openai_api_key,
        provider=code_config["provider"],
        model_id=code_config["model_id"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )

    job_service = ChapterJobService(db)
    service = AnimationEnrichmentService(db, llm_service, code_gen_llm=code_llm)

    try:
        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).first()
            if not guideline:
                raise ValueError(f"Guideline {guideline_id} not found")

            topic = guideline.topic_title or guideline.topic
            job_service.update_progress(job_id, current_item=topic, completed=0, failed=0)

            result = service.enrich_guideline(guideline, force=force)

            job_service.update_progress(
                job_id, current_item=None,
                completed=result["enriched"], failed=result["failed"],
                detail=_json.dumps(result),
            )
            final_status = "completed" if result["failed"] == 0 else "completed_with_errors"
        else:
            result = service.enrich_chapter(
                book_id,
                chapter_id=chapter_id or None,
                force=force,
                job_service=job_service,
                job_id=job_id,
            )

            for error in result.get("errors", []):
                logger.warning(f"Visual enrichment error: {error}")

            final_status = "completed" if result["failed"] == 0 else "completed_with_errors"

        job_service.release_lock(job_id, status=final_status)

    except Exception:
        raise  # run_in_background_v2 handles marking the job as failed
